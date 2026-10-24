"""Backup and verify a Railway deployment without Docker.

Run inside the Railway service (or another trusted host with the same
DATABASE_URL and a mounted media volume). The database dump and media archive
are paired by manifest.json. Restore drills must always target an isolated
PostgreSQL database, never the production URL.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import tempfile
import time
from pathlib import Path


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def command_exists(name: str) -> None:
    if shutil.which(name) is None:
        raise RuntimeError(f"{name} is required; install postgresql-client in the Railway runtime")


def verify(folder: Path) -> dict:
    folder = folder.resolve()
    manifest = json.loads((folder / "manifest.json").read_text())
    expected = {"database.dump", "media.tar.gz"}
    if set(manifest.get("sha256", {})) != expected:
        raise ValueError("Unexpected manifest file list")
    for name, checksum in manifest["sha256"].items():
        item = folder / name
        if item.is_symlink() or not item.is_file() or digest(item) != checksum:
            raise ValueError(f"Backup checksum mismatch: {name}")
    with tarfile.open(folder / "media.tar.gz") as archive:
        for item in archive:
            path = Path(item.name)
            if path.is_absolute() or ".." in path.parts or not path.parts or path.parts[0] != "media":
                raise ValueError(f"Unsafe archive member: {item.name}")
            if not (item.isfile() or item.isdir()):
                raise ValueError(f"Unsupported archive member: {item.name}")
    return manifest


def backup(destination: Path) -> None:
    command_exists("pg_dump")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url.startswith(("postgresql", "postgres://")):
        raise RuntimeError("DATABASE_URL must point to Railway PostgreSQL")
    media_root = Path(os.getenv("MEDIA_DIR", "/data/media")).resolve()
    if not media_root.is_dir():
        raise RuntimeError(f"MEDIA_DIR does not exist: {media_root}")
    destination = destination.resolve()
    destination.mkdir(mode=0o700, parents=True, exist_ok=False)
    subprocess.run(["pg_dump", "--format=custom", "--no-owner", "--no-privileges", "--dbname", database_url, "--file", str(destination / "database.dump")], check=True)
    with tarfile.open(destination / "media.tar.gz", "w:gz") as archive:
        archive.add(media_root, arcname="media")
    manifest = {
        "format": 2,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "version": Path("VERSION").read_text().strip() if Path("VERSION").exists() else "unknown",
        "media_root": str(media_root),
        "sha256": {name: digest(destination / name) for name in ("database.dump", "media.tar.gz")},
    }
    (destination / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    for item in destination.iterdir():
        item.chmod(0o600)
    verify(destination)
    print(f"Railway backup verified: {destination}")


def drill(folder: Path, target_url: str) -> None:
    command_exists("pg_restore")
    command_exists("psql")
    verify(folder)
    with tempfile.TemporaryDirectory(prefix="enertri-railway-restore-") as temporary:
        extracted = Path(temporary)
        with tarfile.open(folder / "media.tar.gz") as archive:
            archive.extractall(extracted, filter="data")
        subprocess.run(["pg_restore", "--exit-on-error", "--clean", "--if-exists", "--no-owner", "--no-privileges", "--dbname", target_url, str(folder / "database.dump")], check=True)
        sql = "COPY (SELECT storage_path, sha256 FROM workspace_files WHERE deleted_at IS NULL) TO STDOUT WITH CSV"
        result = subprocess.run(["psql", "--dbname", target_url, "--set", "ON_ERROR_STOP=1", "--command", sql], check=True, capture_output=True, text=True)
        media_root = Path(os.getenv("RESTORE_MEDIA_DIR", "/data/media")).resolve()
        checked = 0
        for row in csv.reader(result.stdout.splitlines()):
            if len(row) != 2:
                raise ValueError("Unexpected workspace_files output")
            stored_path, checksum = row
            relative = Path(stored_path).resolve().relative_to(media_root)
            restored = extracted / "media" / relative
            if not restored.is_file() or digest(restored) != checksum:
                raise ValueError(f"Restored file missing or checksum mismatch: {stored_path}")
            checked += 1
        counts = subprocess.run(["psql", "--dbname", target_url, "--set", "ON_ERROR_STOP=1", "--tuples-only", "--no-align", "--command", "SELECT count(*) FROM users; SELECT count(*) FROM terms; SELECT version_num FROM alembic_version;"], check=True, capture_output=True, text=True).stdout.splitlines()
        print(json.dumps({"restore": "passed", "file_hashes_checked": checked, "users_terms_revision": [line.strip() for line in counts if line.strip()]}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("backup", "verify", "drill"))
    parser.add_argument("folder", type=Path)
    parser.add_argument("--target-url", help="isolated PostgreSQL URL required for drill")
    args = parser.parse_args()
    if args.action == "backup":
        backup(args.folder)
    elif args.action == "verify":
        verify(args.folder)
        print("Checksum and archive safety checks passed")
    else:
        if not args.target_url:
            parser.error("drill requires --target-url for an isolated database")
        drill(args.folder, args.target_url)


if __name__ == "__main__":
    main()
