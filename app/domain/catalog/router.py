from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.domain.catalog.services import list_match_filters

router = APIRouter()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.get("/filters")
def list_filters_route(db: Session = Depends(get_db)):
    try:
        return list_match_filters(db)
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
