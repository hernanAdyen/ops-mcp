"""/source-scope-answers endpoints.

POST /answers/jobs           start finding answers (our model is slow, so this is a job)
GET  /answers/jobs/{job_id}  the job's result, or pending
POST /answers/runs/{id}/record
POST /answers/runs           the same as a job, but waits however long it takes (for tests and scripts)
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from imcp.app.db import get_session
from imcp.scope.answers import AnswersRecordRequest, AnswersStartRequest, record_answers, start_answers
from imcp.scope.runs import RunError

router = APIRouter(prefix="/answers", tags=["source-scope-answers"])


@router.post("/runs")
def start(req: AnswersStartRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        result = start_answers(session, request.app.state.settings, request.app.state.model, req)
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    session.commit()
    return result


def _job_reply(request: Request, job_id: str, wait: float) -> dict:
    try:
        state, result = request.app.state.jobs.wait(job_id, wait)
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    if state == "unknown":
        raise HTTPException(404, {"error": "There's no job with that ID. It may have expired: start again."})
    if state == "pending":
        return {"job_id": job_id, "pending": True}
    return {"job_id": job_id, "pending": False, **result}


@router.post("/jobs")
def start_job(req: AnswersStartRequest, request: Request, wait: float = 40) -> dict:
    app = request.app

    def work() -> dict:
        session = app.state.session_factory()
        try:
            result = start_answers(session, app.state.settings, app.state.model, req)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _job_reply(request, app.state.jobs.submit(work), wait)


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request, wait: float = 40) -> dict:
    return _job_reply(request, job_id, wait)


@router.post("/runs/{run_id}/record")
def record(run_id: str, req: AnswersRecordRequest, request: Request, session: Session = Depends(get_session)) -> dict:
    try:
        result = record_answers(session, request.app.state.settings, run_id, req)
    except RunError as exc:
        raise HTTPException(exc.status, exc.detail) from exc
    session.commit()
    return result
