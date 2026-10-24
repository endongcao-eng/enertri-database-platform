#!/usr/bin/env python
from __future__ import annotations

from pathlib import Path
import sys

# Allow direct execution via `python scripts/task_worker.py` in Docker and local shells.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.task_worker import main

if __name__ == "__main__":
    main()
