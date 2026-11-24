"""Every setting comes from an environment variable (listed in system.yaml)."""

import os

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/catalog.db")
