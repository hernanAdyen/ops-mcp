"""/propose-solution: start → plan → write → record.

Start picks the answers per track and builds the research brief from the graph. The IM's model
researches and drafts in their own harness. Plan checks the draft and returns the exact Docs batch.
Record checks the document and finishes the run. Every run is a `generation`; its trace keeps IDs,
URLs and counts, never the answers or the draft.
"""

import uuid
from urllib.parse import urlsplit

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from imcp import SERVICE_VERSION
from imcp.config import AppSettings, describe_config
from imcp.db import enums as E
from imcp.db.models import Asset, Generation, Merchant, Node, Opportunity, Question, Source
from imcp.proposal.answers import TrackAnswers, feature_rows, pick_answers
from imcp.proposal.brief import INSTRUCTIONS, build_brief
from imcp.proposal.doc_plan import plan_document
from imcp.proposal.draft import Draft, check_draft
from imcp.proposal.outline import ElementIn, parse_outline
from imcp.scope.candidates import bank_status
from imcp.scope.runs import MAX_TRACKS, RunError, TAG_NAMES, feedback_link, normalise_name

COMMAND = "propose-solution"
# The two Introduction questions (bank IDs are permanent): 1.4 Project Background, 1.5 Project Goals.
INTRO_BACKGROUND, INTRO_GOALS = "ID-0083", "ID-0084"
MAX_OPEN_LISTED = 10


class TabIn(BaseModel):
    name: str = Field(min_length=1, max_length=100, description="The tab's title: the track's name")
    id_column: list[str] = Field(description="Column A as read, starting with its 'id' header")
    columns: dict[str, list[str]] = Field(
        default_factory=dict,
        description="By header name, each as read starting with its header: answer (required), status, source, question",
    )


class ProposalStartRequest(BaseModel):
    sheet_id: str = Field(min_length=10, max_length=200)
    merchant_name: str | None = Field(default=None, max_length=200)
    tabs: list[TabIn] = Field(min_length=1, max_length=MAX_TRACKS)
    max_links: int = Field(default=8, ge=1, le=20, description="Documentation links per track in the document")


class PlanRequest(BaseModel):
    tabs: list[TabIn] = Field(min_length=1, max_length=MAX_TRACKS, description="The same tabs as at start")
    draft: Draft
    outline: list[ElementIn] = Field(description="The copy's body, one item per structural element")


class RecordRequest(BaseModel):
    doc_id: str = Field(min_length=10, max_length=200)
    doc_url: str = Field(max_length=500)
    leftover_tokens: list[str] = Field(default_factory=list, description="Any {{tokens}} still in the document")


def _tab_read(tab: TabIn) -> tuple[list[str], dict[str, list[str]]]:
    if not tab.id_column or tab.id_column[0].strip().lower() not in ("id", "question_id"):
        raise RunError(422, f"id_column must be column A of the {tab.name!r} tab, starting with its 'id' header.")
    columns: dict[str, list[str]] = {}
    for key, values in tab.columns.items():
        name = key.strip().lower()
        first = values[0].strip().lower() if values else ""
        if first != name:
            raise RunError(422, f"The column passed as '{key}' for the {tab.name!r} tab starts with "
                                f"'{values[0] if values else ''}'. Pass the column whose header is '{name}', as read.")
        columns[name] = values[1:]
    if "answer" not in columns:
        raise RunError(422, f"Read and pass the 'answer' column of the {tab.name!r} tab too.")
    return [v.strip() for v in tab.id_column[1:]], columns


def _opportunity(session: Session, sheet_id: str) -> tuple[Opportunity | None, Merchant | None]:
    opp = session.scalar(select(Opportunity).where(Opportunity.alias == sheet_id))
    return opp, (session.get(Merchant, opp.merchant_id) if opp else None)


def track_tags(opp: Opportunity | None, name: str) -> dict[str, list[str]]:
    """The track's tags from /create-scope (by tab name), else the opportunity's union, else no filter."""
    if opp is None:
        return {t: [] for t in TAG_NAMES}
    for track in opp.tracks or []:
        if " ".join(str(track.get("name", "")).casefold().split()) == " ".join(name.casefold().split()):
            return {t: [str(v) for v in track.get(t, [])] for t in TAG_NAMES}
    return {t: [getattr(v, "value", v) for v in getattr(opp, t)] for t in TAG_NAMES}


def _docs_host(settings: AppSettings) -> str | None:
    return urlsplit(str(settings.DOCS_INDEX_URL)).netloc if settings.DOCS_INDEX_URL else None


def start_proposal(session: Session, settings: AppSettings, embedder, req: ProposalStartRequest) -> dict:
    if not bank_status(session, settings)["active_questions"]:
        raise RunError(409, "The question bank isn't loaded yet. Load it with im_bank_load first.")
    if embedder is None:
        raise RunError(503, "EMBEDDING_MODEL isn't set on the app server, so the graph can't be searched.")
    names = [t.name.strip() for t in req.tabs]
    if len({n.casefold() for n in names}) != len(names):
        raise RunError(422, "Two tabs have the same name.")
    opp, merchant = _opportunity(session, req.sheet_id)
    merchant_name = merchant.name if merchant else (req.merchant_name or "").strip()
    if not merchant_name:
        raise RunError(422, "This sheet wasn't made by /create-scope, so I don't know the merchant. Pass merchant_name.")
    bank = {q.question_id: q for q in session.scalars(select(Question).where(Question.status == E.QuestionStatus.active))}

    tracks: list[TrackAnswers] = []
    briefs: list[dict] = []
    for tab in req.tabs:
        ids, columns = _tab_read(tab)
        track = pick_answers(tab.name.strip(), ids, columns, bank)
        tracks.append(track)
        briefs.append(build_brief(session, embedder, track, track_tags(opp, track.name), docs_host=_docs_host(settings)))

    intro = {a.id: a for t in tracks for a in t.by_subsection(E.Subsection.introduction.value)}
    introduction = {
        "background": intro[INTRO_BACKGROUND].answer if INTRO_BACKGROUND in intro else None,
        "goals": intro[INTRO_GOALS].answer if INTRO_GOALS in intro else None,
    }

    gen = Generation(
        command=COMMAND, tool_version=SERVICE_VERSION, flags=describe_config(settings)["flags"],
        opportunity_id=opp.opportunity_id if opp else None,
        trace={
            "stage": "draft",
            "sheet_id": req.sheet_id,
            "merchant_name": None if opp else merchant_name,
            "max_links": req.max_links,
            "introduction_ids": [i for i in (INTRO_BACKGROUND, INTRO_GOALS) if i in intro],
            "tracks": [
                {
                    "name": t.name,
                    "tags": b["tags"],
                    "used_ids": t.used_ids,
                    "suggested_ids": t.suggested_ids,
                    "open_p1_ids": t.open_p1_ids,
                    "skipped_rejected_ids": t.skipped_rejected_ids,
                    "not_loaded": t.not_loaded,
                    "feature_rows": len(feature_rows(t)),
                    "doc_urls": [d["url"] for d in b["doc_pages"]],
                    "diagram_urls": [d["url"] for d in b["diagrams"]],
                }
                for t, b in zip(tracks, briefs)
            ],
        },
    )
    session.add(gen)
    session.flush()
    text = {q.question_id: q.text for q in bank.values()}
    return {
        "draft_id": str(gen.generation_id),
        "merchant": merchant_name,
        "master_doc_url": str(settings.PROPOSAL_MASTER_URL) if settings.PROPOSAL_MASTER_URL else None,
        "introduction": introduction,
        "tracks": [
            {
                "name": t.name,
                "discovery": [a.to_dict() for a in t.by_subsection(E.Subsection.discovery.value)],
                "features": feature_rows(t),
                "suggested_used": t.suggested_ids,
                "open_priority_1": {"count": len(t.open_p1_ids),
                                    "questions": [{"id": i, "question": text.get(i, "")} for i in t.open_p1_ids[:MAX_OPEN_LISTED]]},
                "not_loaded": t.not_loaded,
                "brief": b,
            }
            for t, b in zip(tracks, briefs)
        ],
        "instructions": INSTRUCTIONS,
        "next": "Research and draft section 3 per track (and 1.4/1.5) from the briefs, then call im_proposal_plan.",
    }


def _assets(session: Session) -> dict[str, dict]:
    """canonical URL -> {title, kind} for every live asset node."""
    rows = session.execute(select(Node, Asset).join(Asset, Asset.node_id == Node.node_id)
                           .where(Node.status == E.Lifecycle.active, Asset.deprecated.is_(False))).all()
    return {n.canonical_key: {"title": n.label, "kind": a.kind.value} for n, a in rows}


def _tracks_from_tabs(session: Session, tabs: list[TabIn], trace: dict) -> list[TrackAnswers]:
    names = [t["name"] for t in trace["tracks"]]
    given = [t.name.strip() for t in tabs]
    if [n.casefold() for n in given] != [n.casefold() for n in names]:
        raise RunError(422, f"Pass the same tabs as at start, in the same order: {', '.join(names)}.")
    bank = {q.question_id: q for q in session.scalars(select(Question).where(Question.status == E.QuestionStatus.active))}
    out = []
    for tab, name in zip(tabs, names):
        ids, columns = _tab_read(tab)
        out.append(pick_answers(name, ids, columns, bank))
    return out


def plan_proposal(session: Session, settings: AppSettings, run_id: str, req: PlanRequest) -> dict:
    gen = get_run(session, run_id, ("draft", "planned"))
    trace = dict(gen.trace)
    tracks = _tracks_from_tabs(session, req.tabs, trace)
    assets = _assets(session)
    checked = check_draft(req.draft, [t.name for t in tracks], {u: a["title"] for u, a in assets.items()},
                          _docs_host(settings))
    outline = parse_outline(req.outline)

    opp = session.get(Opportunity, gen.opportunity_id) if gen.opportunity_id else None
    merchant = session.get(Merchant, opp.merchant_id).name if opp else trace.get("merchant_name") or ""

    intro = {a.id: a for t in tracks for a in t.by_subsection(E.Subsection.introduction.value)}
    introduction = {
        "background": checked["introduction"]["background"] or ([intro[INTRO_BACKGROUND].answer] if INTRO_BACKGROUND in intro else []),
        "goals": checked["introduction"]["goals"] or ([intro[INTRO_GOALS].answer] if INTRO_GOALS in intro else []),
    }

    planned_tracks, links_used, diagrams_used = [], [], []
    for track, t_trace in zip(tracks, trace["tracks"]):
        drafted = checked["tracks"][track.name]
        links = list(drafted["links"])
        for url in t_trace.get("doc_urls", []):  # fill up from the brief's pages, best first
            if len(links) >= trace["max_links"]:
                break
            if url in assets and all(l["url"] != url for l in links):
                links.append({"url": url, "title": assets[url]["title"]})
        links = links[:trace["max_links"]]
        diagram = next(({"url": u, "title": assets[u]["title"]} for u in t_trace.get("diagram_urls", []) if u in assets), None)
        planned_tracks.append({
            "name": track.name,
            "discovery": [a.to_dict() for a in track.by_subsection(E.Subsection.discovery.value)],
            "features": feature_rows(track),
            "technical_considerations": drafted["technical_considerations"],
            "integration_design": drafted["integration_design"],
            "diagram": diagram,
            "links": links,
        })
        links_used.append([l["url"] for l in links])
        diagrams_used.append(diagram["url"] if diagram else None)

    plan = plan_document(outline, merchant=merchant, introduction=introduction, tracks=planned_tracks)
    trace["stage"] = "planned"
    trace["plan"] = {**plan["summary"], "links_used": links_used, "diagram_urls": diagrams_used,
                     "outline_elements": len(req.outline), "requests": len(plan["requests"])}
    gen.trace = trace
    session.flush()
    return {
        "draft_id": str(gen.generation_id),
        "requests": plan["requests"],
        "summary": plan["summary"],
        "tracks": [{"name": t["name"], "links": t["links"], "diagram": t["diagram"]} for t in planned_tracks],
        "next": "Send the requests unchanged in one Docs batchUpdate on the copy, then call im_proposal_record.",
    }


def record_proposal(session: Session, settings: AppSettings, run_id: str, req: RecordRequest) -> dict:
    gen = get_run(session, run_id, ("planned",))
    trace = dict(gen.trace)
    opp = session.get(Opportunity, gen.opportunity_id) if gen.opportunity_id else None
    if opp is None:
        name = trace.get("merchant_name") or "Unknown merchant"
        normalised = normalise_name(name)
        merchant = session.scalar(select(Merchant).where(Merchant.normalized_name == normalised))
        if merchant is None:
            merchant = Merchant(name=name, normalized_name=normalised)
            session.add(merchant)
            session.flush()
        opp = session.scalar(select(Opportunity).where(Opportunity.alias == trace["sheet_id"]))
        if opp is None:
            opp = Opportunity(merchant_id=merchant.merchant_id, alias=trace["sheet_id"])
            session.add(opp)
            session.flush()
    merchant_name = session.get(Merchant, opp.merchant_id).name
    # Where the finished proposal is, for ingestion later: a pointer, never the content.
    session.add(Source(opportunity_id=opp.opportunity_id, type=E.SourceType.proposal, ref=f"doc:{req.doc_id}"))
    gen.opportunity_id, gen.output_ref = opp.opportunity_id, req.doc_url
    trace["stage"], trace["merchant_name"] = "recorded", None
    trace["leftover_tokens"] = req.leftover_tokens
    gen.trace = trace
    session.flush()
    text = {q.question_id: q.text for q in session.scalars(select(Question).where(Question.status == E.QuestionStatus.active))}
    return {
        "ok": True,
        "merchant": merchant_name,
        "doc_url": req.doc_url,
        "tracks": [
            {
                "name": t["name"],
                "suggested_used": t["suggested_ids"],
                "open_priority_1": {"count": len(t["open_p1_ids"]),
                                    "questions": [{"id": i, "question": text.get(i, "")} for i in t["open_p1_ids"][:MAX_OPEN_LISTED]]},
                "feature_rows": t["feature_rows"],
                "diagram": (trace.get("plan", {}).get("diagram_urls") or [None] * (i + 1))[i] is not None,
            }
            for i, t in enumerate(trace["tracks"])
        ],
        "plan": trace.get("plan", {}),
        "leftover_tokens": req.leftover_tokens,
        "feedback_url": feedback_link(settings, str(gen.generation_id)),
    }


def get_run(session: Session, run_id: str, stages: tuple[str, ...]) -> Generation:
    try:
        gen = session.get(Generation, uuid.UUID(run_id))
    except ValueError:
        gen = None
    if gen is None or gen.command != COMMAND:
        raise RunError(404, f"There's no /propose-solution run with ID {run_id}.")
    stage = gen.trace.get("stage")
    if stage not in stages:
        if stage == "recorded":
            raise RunError(409, "This run is already recorded. Start a new run to change the proposal.")
        raise RunError(409, "Plan the document first (im_proposal_plan), then record the run.")
    return gen
