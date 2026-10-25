"""Read the question bank (the Project Scope tab, downloaded as CSV) into validated rows.

Columns are found by their header, so their order doesn't matter, and other columns
(`answer`, `found_by`, ...) are ignored. Every problem in a row is reported, not only the first.
Nothing here touches the database.
"""

import csv
import hashlib
import io
import json
import re
from dataclasses import dataclass, field
from enum import Enum

from imcp.db import enums as E

ID_PATTERN = re.compile(r"ID-\d{4,}")
CHOICE_TYPES = (E.QuestionType.single_choice, E.QuestionType.multi_choice)

# Header in the sheet (lower case) -> field. A few spellings are accepted for each.
HEADERS = {
    "id": "id", "question_id": "id",
    "enum": "type", "type": "type",
    "options": "options",
    "question": "question",
    "notes": "notes",
    "priority": "priority",
    "subsection": "subsection",
    "channels": "channels", "channel": "channels",
    "pillars": "pillars", "pillar": "pillars",
    "category": "categories", "categories": "categories",
    "platform": "platforms", "platforms": "platforms",
}
FIELDS = ("id", "type", "options", "question", "notes", "priority", "subsection",
          "channels", "pillars", "categories", "platforms")
REQUIRED = {"id": "id", "type": "enum", "question": "question", "priority": "priority", "subsection": "subsection"}

SUBSECTIONS: dict[str, E.Subsection] = {
    "introduction": E.Subsection.introduction,
    "discovery": E.Subsection.discovery,
    "features & functionality": E.Subsection.features_functionality,
    "features and functionality": E.Subsection.features_functionality,
    "technical considerations": E.Subsection.technical_considerations,
    "integration design": E.Subsection.integration_design,
    "documentation": E.Subsection.documentation,
    **{s.value: s for s in E.Subsection},  # "features_functionality" works too
}
TAGS: dict[str, tuple[type[Enum], str]] = {
    "channels": (E.Channel, "channel"),
    "pillars": (E.Pillar, "pillar"),
    "categories": (E.Category, "category"),
    "platforms": (E.Platform, "platform"),
}


@dataclass(frozen=True)
class BankRow:
    """One valid question, ready to store."""

    row: int  # row number in the sheet (the header is row 1)
    question_id: str
    text: str
    type: E.QuestionType
    options: list[str]
    notes: str | None
    priority: int
    subsection: E.Subsection
    channels: list[E.Channel]
    pillars: list[E.Pillar]
    categories: list[E.Category]
    platforms: list[E.Platform]

    def content(self) -> dict:
        """The question's content as plain values. Also what goes into question history."""
        return {
            "text": self.text,
            "type": self.type.value,
            "options": list(self.options),
            "notes": self.notes,
            "priority": self.priority,
            "subsection": self.subsection.value,
            "channels": [v.value for v in self.channels],
            "pillars": [v.value for v in self.pillars],
            "categories": [v.value for v in self.categories],
            "platforms": [v.value for v in self.platforms],
        }

    def content_hash(self) -> str:
        return content_hash(self.content())


def content_hash(content: dict) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


@dataclass
class RowProblem:
    row: int
    question_id: str | None  # as written in the sheet, even if it isn't a valid ID
    problems: list[str]


@dataclass
class ParseResult:
    rows: list[BankRow] = field(default_factory=list)
    invalid: list[RowProblem] = field(default_factory=list)
    ignored_columns: list[str] = field(default_factory=list)
    data_rows: int = 0  # non-blank rows read
    fatal: str | None = None  # the file can't be used at all (e.g. a required column is missing)


def _clean(value: str) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").strip()


def _tags(raw: str, enum_cls: type[Enum], label: str, problems: list[str]) -> list:
    found = []
    for part in raw.split(","):
        part = part.strip().upper()
        if not part:
            continue
        try:
            value = enum_cls(part)
        except ValueError:
            allowed = ", ".join(m.value for m in enum_cls)
            problems.append(f"unknown {label} '{part}' (expected {allowed})")
            continue
        if value not in found:
            found.append(value)
    order = list(enum_cls)
    return sorted(found, key=order.index)  # same order every time, so reordering a cell isn't a change


def _row(v: dict[str, str]) -> tuple[dict, list[str]]:
    """Check one row. Returns the parsed fields and the problems found (empty if it's valid)."""
    problems: list[str] = []
    out: dict = {}

    qid = v["id"]
    if not qid:
        problems.append("missing id")
    elif not ID_PATTERN.fullmatch(qid):
        problems.append(f"id '{qid}' should look like ID-0001")
    out["question_id"] = qid

    qtype = None
    if not v["type"]:
        problems.append("missing enum (the answer type)")
    else:
        try:
            qtype = E.QuestionType(v["type"].lower())
        except ValueError:
            allowed = ", ".join(t.value for t in E.QuestionType)
            problems.append(f"enum '{v['type']}' should be one of: {allowed}")
    out["type"] = qtype

    options: list[str] = []
    for part in v["options"].split("|"):
        part = part.strip()
        if not part:
            continue
        if part.lower() in (o.lower() for o in options):
            problems.append(f"option '{part}' appears twice")
            continue
        options.append(part)
    if qtype in CHOICE_TYPES and len(options) < 2:
        problems.append(f"a {qtype.value} question needs at least two options, written as A | B")
    if qtype is not None and qtype not in CHOICE_TYPES and options:
        problems.append(f"only choice questions have options; this one is {qtype.value}")
    out["options"] = options

    if not v["question"]:
        problems.append("missing question text")
    out["text"] = v["question"]
    out["notes"] = v["notes"] or None

    if v["priority"] in ("1", "2", "3"):
        out["priority"] = int(v["priority"])
    else:
        problems.append(f"priority '{v['priority']}' should be 1, 2 or 3" if v["priority"] else "missing priority")

    subsection = SUBSECTIONS.get(v["subsection"].lower())
    if subsection is None:
        problems.append(
            f"subsection '{v['subsection']}' isn't known (expected Introduction, Discovery, Features & Functionality, "
            "Technical Considerations, Integration Design or Documentation)"
            if v["subsection"] else "missing subsection"
        )
    out["subsection"] = subsection

    for name, (enum_cls, label) in TAGS.items():
        out[name] = _tags(v[name], enum_cls, label, problems)

    return out, problems


def parse_bank_csv(text: str) -> ParseResult:
    """Parse the CSV text of the Project Scope tab."""
    reader = csv.reader(io.StringIO(text.lstrip("﻿"), newline=""))
    try:
        header = next(reader)
    except StopIteration:
        return ParseResult(fatal="the file is empty")

    columns: dict[str, int] = {}
    ignored: list[str] = []
    for index, name in enumerate(header):
        name = name.strip()
        key = HEADERS.get(name.lower())
        if key is None:
            if name:
                ignored.append(name)
            continue
        if key in columns:
            return ParseResult(ignored_columns=ignored, fatal=f"the '{name}' column appears twice")
        columns[key] = index
    missing = [label for key, label in REQUIRED.items() if key not in columns]
    if missing:
        return ParseResult(
            ignored_columns=ignored,
            fatal="missing column(s): " + ", ".join(missing) + ". Is this the Project Scope tab?",
        )

    checked: list[tuple[int, dict, list[str]]] = []
    for row_number, cells in enumerate(reader, start=2):
        values = {
            f: _clean(cells[columns[f]]) if f in columns and columns[f] < len(cells) else ""
            for f in FIELDS
        }
        if not any(values.values()):
            continue  # blank row
        fields, problems = _row(values)
        checked.append((row_number, fields, problems))

    # An ID used on more than one row makes all of those rows invalid.
    rows_by_id: dict[str, list[int]] = {}
    for row_number, fields, _ in checked:
        if fields["question_id"]:
            rows_by_id.setdefault(fields["question_id"], []).append(row_number)
    for row_number, fields, problems in checked:
        others = [r for r in rows_by_id.get(fields["question_id"], []) if r != row_number]
        if others:
            problems.append(f"id {fields['question_id']} is also used on row {', '.join(map(str, others))}")

    result = ParseResult(ignored_columns=ignored, data_rows=len(checked))
    for row_number, fields, problems in checked:
        if problems:
            result.invalid.append(RowProblem(row_number, fields["question_id"] or None, problems))
        else:
            result.rows.append(BankRow(row=row_number, **fields))
    return result
