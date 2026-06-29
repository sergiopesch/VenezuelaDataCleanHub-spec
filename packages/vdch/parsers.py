from dataclasses import dataclass
from typing import Any, Protocol

from vdch.manifest import mapped_value
from vdch.normalization import build_person_fields


class ParserError(RuntimeError):
    pass


@dataclass(frozen=True)
class ParsedPersonRecord:
    source_record_id: str
    person_fields: dict[str, Any]


class RecordParser(Protocol):
    name: str
    version: str

    def parse(self, record: dict[str, Any], mappings: dict[str, str]) -> ParsedPersonRecord:
        pass


class PersonJsonParser:
    name = "person_json_v1"
    version = "1"

    def parse(self, record: dict[str, Any], mappings: dict[str, str]) -> ParsedPersonRecord:
        source_record_id = mapped_value(record, mappings, "source_record_id")
        if source_record_id in (None, ""):
            raise ParserError("source_record_id is required")
        return ParsedPersonRecord(
            source_record_id=str(source_record_id),
            person_fields=build_person_fields(record, mappings),
        )


def get_parser(name: str, version: str = "1") -> RecordParser:
    if name == PersonJsonParser.name and version == PersonJsonParser.version:
        return PersonJsonParser()
    raise ParserError(f"unknown parser: {name}@{version}")
