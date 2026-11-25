"""Every setting comes from an environment variable (listed in system.yaml)."""

import os

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/matches.db")

# Where the catalog service lives, and how long matches waits for it.
CATALOG_URL = os.getenv("CATALOG_URL", "http://catalog:8000")
CATALOG_TIMEOUT_S = float(os.getenv("CATALOG_TIMEOUT_S", "20"))
CORS_ORIGINS = [o.strip() for o in os.getenv("CORS_ORIGINS", "http://localhost:8080,http://localhost:5173").split(",") if o.strip()]