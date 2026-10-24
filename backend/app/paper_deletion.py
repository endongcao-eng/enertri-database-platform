"""Shared deletion logic for uploaded paper files and knowledge documents.

There are two user-facing deletion entry points (the file center and the
paper knowledge-base page).  Both must use this module so an original file
cannot be removed while its structured evidence remains apparently usable.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .file_service import FILE_STORE_DIR
from .models import (
    KnowledgeChunk,
    KnowledgeDocument,
    KnowledgeFigure,
    KnowledgePage,
    KnowledgeTable,
    TaskFile,
    WorkspaceFile,
    WorkspaceTask,
)


@dataclass
class PaperDeletionResult:
    document_ids: list[int] = field(default_factory=list)
    source_file_ids: list[int] = field(default_factory=list)
    active_tasks_cancelled: int = 0
    task_results_cleared: int = 0
    tasks_deleted: int = 0
    remove_paths: list[Path] = field(default_factory=list)
    figure_dirs: list[Path] = field(default_factory=list)


def _safe_figure_dir(path: str | None, document_id: int) -> Path | None:
    if not path:
        return None
    figure_dir = Path(path).resolve().parent
    expected_name = f"doc_{document_id}_figures"
    if figure_dir.name != expected_name:
        return None
    try:
        if not figure_dir.is_relative_to(FILE_STORE_DIR.resolve()):
            return None
    except AttributeError:  # pragma: no cover - Python 3.12 has is_relative_to
        if FILE_STORE_DIR.resolve() not in figure_dir.parents:
            return None
    return figure_dir


def delete_document_rows(db: Session, document: KnowledgeDocument, *, mark_source_deleted: bool = True) -> PaperDeletionResult:
    """Delete one document's structured rows and prepare its source cleanup.

    The caller owns the transaction.  Files are removed only after the caller
    commits, so a database rollback cannot leave a source file without its DB
    record.  Shared duplicate source files are retained until their last
    KnowledgeDocument reference is deleted.
    """
    result = PaperDeletionResult(document_ids=[document.id])
    source = db.get(WorkspaceFile, document.file_id) if document.file_id else None
    if source:
        result.source_file_ids.append(source.id)

        paper_tasks = db.scalars(
            select(WorkspaceTask)
            .join(TaskFile, TaskFile.task_id == WorkspaceTask.id)
            .where(TaskFile.file_id == source.id, WorkspaceTask.task_type == "paper_ingest")
        ).all()
        for task in paper_tasks:
            result.task_results_cleared += 1
            if task.status in {"queued", "running"}:
                result.active_tasks_cancelled += 1
            # Paper-ingest tasks have no reusable output outside the paper
            # document. Delete the task itself (and TaskFile/TaskEvent
            # children via the relationship cascade) so history cannot
            # advertise a result for a removed document.
            if source and source.task_id == task.id:
                source.task_id = None
            db.delete(task)
            result.tasks_deleted += 1

    for figure in db.scalars(select(KnowledgeFigure).where(KnowledgeFigure.document_id == document.id)).all():
        figure_dir = _safe_figure_dir(figure.image_path, document.id)
        if figure_dir and figure_dir not in result.figure_dirs:
            result.figure_dirs.append(figure_dir)

    # Explicit deletes keep this correct on SQLite and on existing PostgreSQL
    # installations where foreign-key cascade enforcement may differ.
    db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document.id))
    db.execute(delete(KnowledgePage).where(KnowledgePage.document_id == document.id))
    db.execute(delete(KnowledgeTable).where(KnowledgeTable.document_id == document.id))
    db.execute(delete(KnowledgeFigure).where(KnowledgeFigure.document_id == document.id))
    db.delete(document)

    if source and mark_source_deleted:
        remaining = db.scalar(
            select(KnowledgeDocument.id)
            .where(KnowledgeDocument.file_id == source.id, KnowledgeDocument.id != document.id)
            .limit(1)
        )
        if not remaining:
            source.deleted_at = datetime.now(timezone.utc)
            result.remove_paths.append(Path(source.storage_path))

    return result


def merge_deletion_results(target: PaperDeletionResult, source: PaperDeletionResult) -> PaperDeletionResult:
    target.document_ids.extend(source.document_ids)
    target.source_file_ids.extend(source.source_file_ids)
    target.active_tasks_cancelled += source.active_tasks_cancelled
    target.tasks_deleted += source.tasks_deleted
    target.task_results_cleared += source.task_results_cleared
    for path in source.remove_paths:
        if path not in target.remove_paths:
            target.remove_paths.append(path)
    for path in source.figure_dirs:
        if path not in target.figure_dirs:
            target.figure_dirs.append(path)
    return target


def finalize_paper_deletion(result: PaperDeletionResult) -> None:
    """Remove committed source bytes and generated figure directories."""
    for path in result.remove_paths:
        try:
            path.unlink(missing_ok=True)
        except OSError:
            # The DB tombstone is authoritative; a later cleanup job can retry.
            pass
    for figure_dir in result.figure_dirs:
        shutil.rmtree(figure_dir, ignore_errors=True)
