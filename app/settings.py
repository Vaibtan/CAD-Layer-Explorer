from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import Limits


def limit(name: str, default: int) -> int:
    return int(os.environ.get(f"CAD_{name}", default))


DATA = Path(os.environ.get("CAD_DATA", "data")).resolve()
LIMITS: Limits = {
    "upload_bytes": limit("UPLOAD_BYTES", 100 * 1024**2),
    "pages": limit("PAGES", 200),
    "queue": limit("QUEUE", 8),
    "pixels": limit("PIXELS", 4_000_000),
    "analysis_seconds": limit("ANALYSIS_SECONDS", 300),
    "render_seconds": limit("RENDER_SECONDS", 15),
    "memory_bytes": limit("MEMORY_BYTES", 1024**3),
    "depth": limit("DEPTH", 32),
    "stream_bytes": limit("STREAM_BYTES", 32 * 1024**2),
    "decoded_bytes": limit("DECODED_BYTES", 256 * 1024**2),
    "cache_bytes": limit("CACHE_BYTES", 512 * 1024**2),
}
