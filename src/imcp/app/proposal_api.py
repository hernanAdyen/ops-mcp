"""/ops-create-solution endpoints.

POST /proposal/runs                 start: pick the answers per track, build the research briefs
POST /proposal/runs/{id}/doc-plan   check the draft and the copy's outline, return the Docs batch
POST /proposal/runs/{id}/record     finish the run
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from imcp.app.db import get_session
from imcp.proposal.runs import PlanRequest, ProposalStartRequest, RecordRequest, plan_proposal, record_proposal, start_proposal
from imcp.scope.runs import RunError

router = APIRouter(prefix="/proposal", tags=["ops-create-solution"])


def _done(session: Session, result: dict) -> dict:
    session.commit()
    return result


@router.post("/runs")
def start(req: ProposalStartRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, start_proposal(session, request.app.state.settings, request.app.state.embedder, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/runs/{run_id}/doc-plan")
def doc_plan(run_id: str, req: PlanRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, plan_proposal(session, request.app.state.settings, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/runs/{run_id}/record")
def record(run_id: str, req: RecordRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, record_proposal(session, request.app.state.settings, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
