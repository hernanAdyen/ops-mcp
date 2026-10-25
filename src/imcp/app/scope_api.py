"""/create-scope endpoints: start a run, plan the sheet edit, record the run."""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from imcp.app.db import get_session
from imcp.scope.runs import PlanRequest, RecordRequest, RunError, StartRequest, plan_run, record_run, start_run

router = APIRouter(prefix="/scope/runs", tags=["create-scope"])


def _done(session: Session, result: dict) -> dict:
    session.commit()
    return result


@router.post("")
def start(req: StartRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, start_run(session, request.app.state.settings, request.app.state.model, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/{run_id}/sheet-plan")
def sheet_plan(run_id: str, req: PlanRequest, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, plan_run(session, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/{run_id}/record")
def record(run_id: str, req: RecordRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, record_run(session, request.app.state.settings, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
