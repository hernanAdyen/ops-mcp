"""Graph endpoints: loading assets. Manual (the owner only), a dry run unless apply is set.

POST /graph/loads/docs        load the Adyen doc pages as a job (fetching the index and embedding take a while)
GET  /graph/jobs/{job_id}     the job's result, or pending
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from imcp.app.jobs import job_reply
from imcp.graph.load_docs import load_doc_pages

router = APIRouter(prefix="/graph", tags=["graph"])


class DocsLoadRequest(BaseModel):
    rules_csv: str = Field(description="The rules file (data/graph/adyen-doc-pages.csv)", max_length=1_000_000)
    source_ref: str | None = Field(default=None, description="Which rules file, for the run record")
    apply: bool = Field(default=False, description="False: report what would change. True: make the changes.")


@router.post("/loads/docs")
def load_docs(req: DocsLoadRequest, request: Request, wait: float = 40) -> dict:
    app = request.app

    def work() -> dict:
        session = app.state.session_factory()
        try:
            report = load_doc_pages(session, app.state.settings, app.state.embedder, rules_csv=req.rules_csv,
                                    source_ref=req.source_ref, apply=req.apply)
            if report.applied:
                session.commit()
            else:
                session.rollback()
            return report.to_dict()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return job_reply(request, app.state.jobs.submit(work), wait)


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request, wait: float = 40) -> dict:
    return job_reply(request, job_id, wait)
