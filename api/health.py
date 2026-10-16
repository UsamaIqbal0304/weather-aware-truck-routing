"""Serverless entry point for /api/health."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from config.serverless import entry_point  # noqa: E402

app = entry_point("/api/health")
