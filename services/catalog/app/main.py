from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import HOST, PORT
from app.database import init_db
from app.router import router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    yield


app = FastAPI(title="catalog", lifespan=lifespan)
app.include_router(router)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=HOST, port=PORT)
