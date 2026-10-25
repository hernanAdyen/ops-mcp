"""Question bank endpoints. Loading is manual (the owner only in v1) and a dry run unless apply is set."""

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from imcp.app.db import get_session
from imcp.bank.load import load_bank
from imcp.bank.parse import parse_bank_csv

router = APIRouter(prefix="/bank", tags=["question bank"])


class LoadRequest(BaseModel):
    csv: str = Field(description="The Project Scope tab, downloaded as CSV", max_length=5_000_000)
    source_ref: str | None = Field(default=None, description="Where the CSV came from, for the run record")
    apply: bool = Field(default=False, description="False: report what would change. True: make the changes.")


@router.post("/loads")
def create_load(req: LoadRequest, session: Session = Depends(get_session)) -> dict:
    report = load_bank(session, parse_bank_csv(req.csv), source_ref=req.source_ref, apply=req.apply)
    if report.applied:
        session.commit()
    else:
        session.rollback()
    return report.to_dict()
