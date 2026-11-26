from contextlib import asynccontextmanager


import logging, time
from fastapi import Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi import FastAPI

from app.config import HOST, PORT, CORS_ORIGINS
from app.database import engine, wait_for_db
from app.migrations import run_migrations
from app.router import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    wait_for_db()
    run_migrations(engine)
    yield


app = FastAPI(title="catalog", lifespan=lifespan)
app.include_router(router)


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("catalog")

app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["GET", "POST"], allow_headers=["Content-Type"])

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    logger.info("%s %s %s %.0fms", request.method, request.url.path,
                response.status_code, (time.perf_counter() - start) * 1000)
    return response


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
