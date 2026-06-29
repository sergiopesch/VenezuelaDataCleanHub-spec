from collections import defaultdict
from itertools import combinations

from sqlalchemy import select
from sqlalchemy.orm import Session

from vdch.models import DuplicateCandidate, PersonRecord, ReviewCase

MATCH_MODEL_VERSION = "deterministic-v1"


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
        if person.normalized_name and person.last_name:
            blocks[("name_last", f"{person.normalized_name}|{person.last_name}")].append(person.id)

    created = 0
    seen_pairs: set[tuple[str, str]] = set()
    for (signal, _value), person_ids in blocks.items():
        if len(person_ids) < 2:
            continue
        for left_id, right_id in combinations(sorted(set(person_ids)), 2):
            pair = _pair_key(left_id, right_id)
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            existing = session.scalar(
                select(DuplicateCandidate).where(
                    DuplicateCandidate.left_person_record_id == pair[0],
                    DuplicateCandidate.right_person_record_id == pair[1],
                )
            )
            if existing:
                continue

            left = by_id[pair[0]]
            right = by_id[pair[1]]
            confidence = {
                "cedula": 0.99,
                "phone": 0.95,
                "photo_url": 0.92,
                "name_last": 0.72,
            }[signal]
            conflict_flags = _conflicts(left, right)
            bucket = _bucket_for(confidence, conflict_flags)
            candidate = DuplicateCandidate(
                left_person_record_id=pair[0],
                right_person_record_id=pair[1],
                confidence=confidence,
                evidence_json={"signals": [signal], "model": MATCH_MODEL_VERSION},
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


def review_case_query(status_filter: str = "open"):
    query = select(ReviewCase)
    if status_filter != "all":
        query = query.where(ReviewCase.status == status_filter)
    return query.order_by(ReviewCase.priority.asc(), ReviewCase.created_at.asc())
