#!/usr/bin/env python3
"""Optional TTL cleanup for data/results/ — run via cron on the VM."""

import shutil
import time
from pathlib import Path

from app.config import get_settings


def main() -> None:
    settings = get_settings()
    ttl_seconds = settings.results_ttl_hours * 3600
    cutoff = time.time() - ttl_seconds
    results = settings.results_path
    if not results.exists():
        return
    for path in results.iterdir():
        if path.is_dir() and path.stat().st_mtime < cutoff:
            shutil.rmtree(path)
            print(f"Removed {path}")


if __name__ == "__main__":
    main()
