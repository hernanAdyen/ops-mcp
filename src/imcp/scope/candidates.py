"""The tag query for a new scope (/ops-create-scope).

Tag rule: any match within a tag, all chosen tags must match, and a question with no value for a
tag applies to everyone. A tag the IM leaves empty isn't used.
Priorities and subsections set how deep and which sections the scope covers. They limit the tag
matches and the questions offered to topic matching alike.
"""

from collections import Counter
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from imcp.config import AppSettings
from imcp.db import enums as E
from imcp.db.models import BankLoadRun, Question

SUBSECTION_LABELS = {
    E.Subsection.introduction: "Introduction",
    E.Subsection.discovery: "Discovery",
    E.Subsection.features_functionality: "Features & Functionality",
    E.Subsection.technical_considerations: "Technical Considerations",
    E.Subsection.integration_design: "Integration Design",
    E.Subsection.documentation: "Documentation",
}
TAG_COLUMNS = {
    "channels": Question.channels,
    "pillars": Question.pillars,
    "categories": Question.categories,
    "platforms": Question.platforms,
}
TAG_ENUMS = {"channels": E.Channel, "pillars": E.Pillar, "categories": E.Category, "platforms": E.Platform}
ORDER = (Question.subsection, Question.question_id)


class Tags(BaseModel):
    """The IM's choices. An empty list means 'all'."""

    channels: list[E.Channel] = Field(default_factory=list)
    pillars: list[E.Pillar] = Field(default_factory=list)
    categories: list[E.Category] = Field(default_factory=list)
    platforms: list[E.Platform] = Field(default_factory=list)
    priorities: list[Literal[1, 2, 3]] = Field(default_factory=list)
    subsections: list[E.Subsection] = Field(default_factory=list)

    def summary(self) -> dict:
        """The choices as plain values, 'all' where nothing was chosen."""
        out: dict = {}
        for name in ("channels", "pillars", "categories", "platforms", "subsections"):
            values = getattr(self, name)
            out[name] = [v.value for v in values] if values else "all"
        out["priorities"] = sorted(self.priorities) if self.priorities else "all"
        return out


def depth_conditions(tags: Tags) -> list:
    conds = [Question.status == E.QuestionStatus.active]
    if tags.priorities:
        conds.append(Question.priority.in_(tags.priorities))
    if tags.subsections:
        conds.append(Question.subsection.in_(tags.subsections))
    return conds


def tag_conditions(tags: Tags) -> list:
    conds = depth_conditions(tags)
    for name, column in TAG_COLUMNS.items():
        values = getattr(tags, name)
        if values:
            conds.append(or_(func.cardinality(column) == 0, column.overlap(values)))
    return conds


def tag_matches(session: Session, tags: Tags) -> list[Question]:
    return list(session.scalars(select(Question).where(*tag_conditions(tags)).order_by(*ORDER)))


def in_range(session: Session, tags: Tags) -> list[Question]:
    """Active questions within the chosen priorities and subsections, whatever their tags."""
    return list(session.scalars(select(Question).where(*depth_conditions(tags)).order_by(*ORDER)))


def brief(q: Question) -> dict:
    """A question in short form: enough to choose it, without its options or notes."""
    tags = {name: [enum_cls(v).value for v in getattr(q, name)] for name, enum_cls in TAG_ENUMS.items()}
    return {
        "id": q.question_id,
        "question": q.text,
        "priority": q.priority,
        "subsection": SUBSECTION_LABELS[E.Subsection(q.subsection)],
        "tags": {k: v for k, v in tags.items() if v},  # a missing tag = applies to everyone
    }


def counts(questions: list[Question]) -> dict:
    by_subsection = Counter(SUBSECTION_LABELS[E.Subsection(q.subsection)] for q in questions)
    by_priority = Counter(f"P{q.priority}" for q in questions)
    return {
        "count": len(questions),
        "by_subsection": {label: by_subsection[label] for label in SUBSECTION_LABELS.values() if by_subsection[label]},
        "by_priority": {p: by_priority[p] for p in ("P1", "P2", "P3") if by_priority[p]},
    }


def bank_status(session: Session, settings: AppSettings) -> dict:
    last = session.scalars(
        select(BankLoadRun).where(BankLoadRun.status == E.RunStatus.succeeded)
        .order_by(BankLoadRun.finished_at.desc()).limit(1)
    ).first()
    active = session.scalar(select(func.count()).select_from(Question)
                            .where(Question.status == E.QuestionStatus.active))
    return {
        "active_questions": active,
        "loaded_at": last.finished_at.isoformat() if last and last.finished_at else None,
        "load_run_id": str(last.run_id) if last else None,
        "master_sheet_url": str(settings.QUESTION_BANK_URL) if settings.QUESTION_BANK_URL else None,
    }
