#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.migration_bootstrap import downgrade_database, upgrade_database  # noqa: E402

parser = argparse.ArgumentParser(description="EnerTri database migration command")
sub = parser.add_subparsers(dest="command", required=True)
up = sub.add_parser("upgrade")
up.add_argument("revision", nargs="?", default="head")
down = sub.add_parser("downgrade")
down.add_argument("revision", nargs="?", default="-1")
args = parser.parse_args()
result = upgrade_database(args.revision) if args.command == "upgrade" else downgrade_database(args.revision)
print(json.dumps(result, ensure_ascii=False))
