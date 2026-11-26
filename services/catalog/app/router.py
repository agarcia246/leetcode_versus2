from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.config import GIT_SHA
from app.database import get_db
from app.models import FiltersOut, PickProblemsBody, ProblemOut
from app.services import get_problems, list_match_filters, pick_problems

router = APIRouter()


@router.get("/filters", response_model=FiltersOut)
def list_filters_route(db: Session = Depends(get_db)):
    """Topics and difficulties the UI can offer when creating a room."""

    try:
        return list_match_filters(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/problems/pick", response_model=list[ProblemOut])
def pick_problems_route(body: PickProblemsBody, db: Session = Depends(get_db)):
    """Called by matches when a room is created: `count` problems for the filters."""

    try:
        return pick_problems(db, count=body.count, topics=body.topics, difficulty=body.difficulty)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/problems", response_model=list[ProblemOut])
def get_problems_route(
    ids: str = Query("", description="Comma-separated problem IDs, e.g. 1,2,3"),
    db: Session = Depends(get_db),
):
    """Called by matches to show a room's problems. Unknown IDs are left out."""

    try:
        problem_ids = [int(part) for part in ids.split(",") if part.strip()]
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="ids must be comma-separated integers") from exc

    return get_problems(db, problem_ids)


@router.get("/health", responses={503: {"description": "Cannot read and write its own database"}})
def health(db: Session = Depends(get_db)):
    try:
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        db.execute(text("UPDATE health_check SET checked_at = :now WHERE id = 1"), {"now": now})
        db.execute(text("SELECT checked_at FROM health_check WHERE id = 1")).one()
        db.commit()
        return {"status": "ok", "db": "ok", "version": GIT_SHA}
    except SQLAlchemyError:
        db.rollback()
        return JSONResponse(status_code=503, content={"status": "error", "db": "unavailable", "version": GIT_SHA})
