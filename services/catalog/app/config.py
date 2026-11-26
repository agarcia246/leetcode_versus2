"""Every setting comes from an environment variable (listed in system.yaml)."""

import os

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
GIT_SHA = os.getenv("GIT_SHA", "dev")
DATABASE_URL = os.environ["DATABASE_URL"]
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:5173").split(",") if o.strip()]
