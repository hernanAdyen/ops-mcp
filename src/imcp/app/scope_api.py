"""/ops-create-scope endpoints: start a run, plan the sheet edit, record the run.

POST /scope/runs                 start (waits however long topic matching takes: tests and scripts)
POST /scope/jobs                 start as a job: with several tracks our model runs once per track
GET  /scope/jobs/{job_id}        the job's result, or pending
POST /scope/runs/{id}/sheet-plan
POST /scope/runs/{id}/record
POST /scope/runs/{id}/call-prompt   after record, when the IM wants the call-notes prompt as a tab
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from imcp.app.db import get_session
from imcp.app.jobs import job_reply
from imcp.scope.runs import (CallPromptRequest, PlanRequest, RecordRequest, RunError, StartRequest, call_prompt_run,
                             plan_run, record_run, start_run)

router = APIRouter(prefix="/scope", tags=["ops-create-scope"])


def _done(session: Session, result: dict) -> dict:
    session.commit()
    return result


@router.post("/runs")
def start(req: StartRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, start_run(session, request.app.state.settings, request.app.state.model, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/jobs")
def start_job(req: StartRequest, request: Request, wait: float = 40) -> dict:
    app = request.app

    def work() -> dict:
        session = app.state.session_factory()
        try:
            result = start_run(session, app.state.settings, app.state.model, req)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return job_reply(request, app.state.jobs.submit(work), wait)


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request, wait: float = 40) -> dict:
    return job_reply(request, job_id, wait)


@router.post("/runs/{run_id}/sheet-plan")
def sheet_plan(run_id: str, req: PlanRequest, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, plan_run(session, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/runs/{run_id}/record")
def record(run_id: str, req: RecordRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, record_run(session, request.app.state.settings, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc


@router.post("/runs/{run_id}/call-prompt")
def call_prompt_tab(run_id: str, req: CallPromptRequest, session: Session = Depends(get_session)) -> dict:
    try:
        return _done(session, call_prompt_run(session, run_id, req))
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
