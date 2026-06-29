from collections import defaultdict
from itertools import combinations

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from vdch.config import get_settings
from vdch.models import (
    DuplicateCandidate,
    DuplicateCluster,
    DuplicateClusterMember,
    PersonRecord,
    ReviewCase,
)

MATCH_MODEL_VERSION = "deterministic-v1"

SIGNAL_WEIGHTS = {
    "cedula": 0.99,
    "phone": 0.95,
    "photo_url": 0.92,
    "source_record_id": 0.9,
    "name_last": 0.72,
}


def _pair_key(left_id: str, right_id: str) -> tuple[str, str]:
    return tuple(sorted((left_id, right_id)))


def _bucket_for(confidence: float, conflicts: dict) -> str:
    if conflicts:
        return "conflicto"
    if confidence >= 0.95:
        return "alta_confianza"
    return "revision_humana"


def _priority_for(bucket: str) -> int:
    return {"conflicto": 10, "revision_humana": 50, "alta_confianza": 80}.get(bucket, 100)


def _conflicts(left: PersonRecord, right: PersonRecord) -> dict:
    flags = {}
    if left.age is not None and right.age is not None and abs(left.age - right.age) > 2:
        flags["age_mismatch"] = {"left": left.age, "right": right.age}
    if left.status and right.status and left.status != right.status:
        flags["status_mismatch"] = {"left": left.status, "right": right.status}
    return flags


def _combined_confidence(signals: list[str]) -> float:
    if not signals:
        return 0.0
    sorted_weights = sorted((SIGNAL_WEIGHTS[signal] for signal in signals), reverse=True)
    confidence = sorted_weights[0]
    for weight in sorted_weights[1:]:
        confidence += (1 - confidence) * weight * 0.35
    return round(min(confidence, 0.999), 3)


def _cluster_key(member_ids: list[str]) -> str:
    return "cluster:" + ":".join(sorted(member_ids))


def _canonical_member(members: list[PersonRecord]) -> PersonRecord:
    return max(
        members,
        key=lambda person: (
            person.quality_score or 0,
            bool(person.cedula_fingerprint),
            bool(person.phone_fingerprint),
            person.created_at,
        ),
    )


def create_duplicate_candidates(session: Session, *, source_id: str | None = None) -> int:
    query = select(PersonRecord)
    if source_id:
        query = query.where(PersonRecord.source_id == source_id)
    people = list(session.scalars(query).all())
    by_id = {person.id: person for person in people}

    blocks: dict[tuple[str, str], list[str]] = defaultdict(list)
    for person in people:
        if person.cedula_fingerprint:
            blocks[("cedula", person.cedula_fingerprint)].append(person.id)
        if person.phone_fingerprint:
            blocks[("phone", person.phone_fingerprint)].append(person.id)
        if person.photo_fingerprint:
            blocks[("photo_url", person.photo_fingerprint)].append(person.id)
        if person.source_id and person.source_record_id:
            blocks[("source_record_id", f"{person.source_id}|{person.source_record_id}")].append(
                person.id
            )
        if person.normalized_name and person.last_name:
            blocks[("name_last", f"{person.normalized_name}|{person.last_name}")].append(person.id)

    created = 0
    pair_signals: dict[tuple[str, str], set[str]] = defaultdict(set)
    for (signal, _value), person_ids in blocks.items():
        if len(person_ids) < 2:
            continue
        if len(person_ids) > get_settings().max_match_block_size:
            continue
        for left_id, right_id in combinations(sorted(set(person_ids)), 2):
            pair = _pair_key(left_id, right_id)
            pair_signals[pair].add(signal)

    for pair, signals_set in pair_signals.items():
        signals = sorted(signals_set, key=lambda signal: SIGNAL_WEIGHTS[signal], reverse=True)
        existing = session.scalar(
            select(DuplicateCandidate).where(
                DuplicateCandidate.left_person_record_id == pair[0],
                DuplicateCandidate.right_person_record_id == pair[1],
            )
        )
        left = by_id[pair[0]]
        right = by_id[pair[1]]
        confidence = _combined_confidence(signals)
        conflict_flags = _conflicts(left, right)
        bucket = _bucket_for(confidence, conflict_flags)
        evidence = {
            "signals": signals,
            "signal_weights": {signal: SIGNAL_WEIGHTS[signal] for signal in signals},
            "model": MATCH_MODEL_VERSION,
            "left": {"person_record_id": left.id, "source_record_id": left.source_record_id},
            "right": {"person_record_id": right.id, "source_record_id": right.source_record_id},
        }
        if existing:
            if existing.evidence_json != evidence or existing.conflict_flags_json != conflict_flags:
                existing.confidence = confidence
                existing.evidence_json = evidence
                existing.review_bucket = bucket
                existing.conflict_flags_json = conflict_flags
                existing.model_version = MATCH_MODEL_VERSION
            review_case = session.scalar(
                select(ReviewCase).where(ReviewCase.duplicate_candidate_id == existing.id)
            )
            if review_case:
                review_case.queue = bucket
                review_case.priority = _priority_for(bucket)
            continue

        candidate = DuplicateCandidate(
            left_person_record_id=pair[0],
            right_person_record_id=pair[1],
            confidence=confidence,
            evidence_json=evidence,
            review_bucket=bucket,
            conflict_flags_json=conflict_flags,
            model_version=MATCH_MODEL_VERSION,
        )
        session.add(candidate)
        session.flush()
        session.add(
            ReviewCase(
                duplicate_candidate_id=candidate.id,
                queue=bucket,
                priority=_priority_for(bucket),
            )
        )
        created += 1
    return created


class _UnionFind:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def find(self, value: str) -> str:
        self.parent.setdefault(value, value)
        if self.parent[value] != value:
            self.parent[value] = self.find(self.parent[value])
        return self.parent[value]

    def union(self, left: str, right: str) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root

    def groups(self) -> list[list[str]]:
        grouped: dict[str, list[str]] = defaultdict(list)
        for value in self.parent:
            grouped[self.find(value)].append(value)
        return [sorted(members) for members in grouped.values() if len(members) > 1]


def rebuild_duplicate_clusters(session: Session) -> int:
    session.execute(update(ReviewCase).values(cluster_id=None))
    session.execute(delete(DuplicateClusterMember))
    session.execute(delete(DuplicateCluster))
    session.flush()

    candidates = list(
        session.scalars(
            select(DuplicateCandidate).where(
                DuplicateCandidate.confidence >= 0.95,
                DuplicateCandidate.review_bucket == "alta_confianza",
            )
        ).all()
    )
    union_find = _UnionFind()
    edge_confidence: dict[tuple[str, str], float] = {}
    for candidate in candidates:
        union_find.union(candidate.left_person_record_id, candidate.right_person_record_id)
        pair = _pair_key(candidate.left_person_record_id, candidate.right_person_record_id)
        edge_confidence[pair] = candidate.confidence

    clusters_created = 0
    for member_ids in union_find.groups():
        member_id_set = set(member_ids)
        members = list(session.scalars(select(PersonRecord).where(PersonRecord.id.in_(member_ids))))
        if len(members) < 2:
            continue
        pair_confidences = [
            confidence
            for pair, confidence in edge_confidence.items()
            if pair[0] in member_ids and pair[1] in member_ids
        ]
        cluster_confidence = round(min(pair_confidences), 3) if pair_confidences else 0.0
        canonical = _canonical_member(members)
        cluster = DuplicateCluster(
            cluster_key=_cluster_key(member_ids),
            canonical_person_record_id=canonical.id,
            confidence=cluster_confidence,
            status="open",
        )
        session.add(cluster)
        session.flush()
        for member in members:
            session.add(
                DuplicateClusterMember(
                    cluster_id=cluster.id,
                    person_record_id=member.id,
                    membership_confidence=cluster_confidence,
                )
            )
        for candidate in candidates:
            if {
                candidate.left_person_record_id,
                candidate.right_person_record_id,
            }.issubset(member_id_set):
                review_case = session.scalar(
                    select(ReviewCase).where(ReviewCase.duplicate_candidate_id == candidate.id)
                )
                if review_case:
                    review_case.cluster_id = cluster.id
        clusters_created += 1
    return clusters_created


def review_case_query(status_filter: str = "open"):
    query = select(ReviewCase)
    if status_filter != "all":
        query = query.where(ReviewCase.status == status_filter)
    return query.order_by(ReviewCase.priority.asc(), ReviewCase.created_at.asc())
