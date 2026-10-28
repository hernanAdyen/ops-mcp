"""Graph endpoints: loading assets. Manual (the owner only), a dry run unless apply is set.

POST /graph/loads/docs        load the Adyen doc pages as a job (fetching the index and embedding take a while)
POST /graph/loads/diagrams    load the owner's flow diagrams CSV as a job
GET  /graph/jobs/{job_id}     the job's result, or pending
"""

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from imcp.app.jobs import job_reply
from imcp.graph.diagrams import load_diagrams
from imcp.graph.docs_index import RulesError
from imcp.graph.load_docs import load_doc_pages
from imcp.scope.runs import RunError

router = APIRouter(prefix="/graph", tags=["graph"])


class DocsLoadRequest(BaseModel):
    rules_csv: str = Field(description="The rules file (data/graph/adyen-doc-pages.csv)", max_length=1_000_000)
    source_ref: str | None = Field(default=None, description="Which rules file, for the run record")
    apply: bool = Field(default=False, description="False: report what would change. True: make the changes.")


class DiagramsLoadRequest(BaseModel):
    csv: str = Field(description="The diagrams file (data/graph/diagrams.csv)", max_length=1_000_000)
    source_ref: str | None = None
    apply: bool = False


def _load_job(request: Request, wait: float, load) -> dict:
    """Runs `load(session, app)` as a job: commits when the report was applied, rolls back otherwise."""
    app = request.app

    def work() -> dict:
        session = app.state.session_factory()
        try:
            report = load(session, app)
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


@router.post("/loads/docs")
def load_docs(req: DocsLoadRequest, request: Request, wait: float = 40) -> dict:
    return _load_job(request, wait, lambda session, app: load_doc_pages(
        session, app.state.settings, app.state.embedder, rules_csv=req.rules_csv, source_ref=req.source_ref, apply=req.apply))


@router.post("/loads/diagrams")
def load_diagram_rows(req: DiagramsLoadRequest, request: Request, wait: float = 40) -> dict:
    def load(session, app):
        if req.apply and app.state.embedder is None:
            raise RunError(422, "EMBEDDING_MODEL (and MODEL_BASE_URL or EMBEDDING_BASE_URL) must be set to load.")
        try:
            return load_diagrams(session, app.state.embedder, csv_text=req.csv, source_ref=req.source_ref, apply=req.apply,
                                 sanitize=app.state.settings.FLAG_SANITIZE)
        except RulesError as exc:
            raise RunError(422, f"The diagrams file can't be used: {exc}") from exc

    return _load_job(request, wait, load)


@router.get("/jobs/{job_id}")
def job(job_id: str, request: Request, wait: float = 40) -> dict:
    return job_reply(request, job_id, wait)
