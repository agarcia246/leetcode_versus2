from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import HOST, PORT, STATIC_DIR
from app.database import Base, engine, init_db
from app.domain.catalog.router import router as catalog_router
from app.domain.frontend.router import router as frontend_router
from app.domain.matches.router import router as matches_router

# Register both domain models on the shared metadata before create_all.
import app.domain.catalog.models  # noqa: F401
import app.domain.matches.models  # noqa: F401


init_db()
Base.metadata.create_all(bind=engine)

app = FastAPI()

app.include_router(frontend_router)
app.include_router(router=catalog_router, prefix="/backend")
app.include_router(router=matches_router, prefix="/backend")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
