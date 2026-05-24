"""Repository factory — Postgres when DATABASE_URL is set."""

from __future__ import annotations

from app.config import get_settings
from app.repositories.db_job_store import DbJobStore
from app.repositories.db_results_repo import DbResultsRepository
from app.repositories.fs_adapter import AsyncFsResultsRepository
from app.repositories.legacy_job_store import LegacyJobStoreAdapter

_job_store: DbJobStore | LegacyJobStoreAdapter | None = None
_results_repo: DbResultsRepository | AsyncFsResultsRepository | None = None


def get_job_store() -> DbJobStore | LegacyJobStoreAdapter:
    global _job_store
    if _job_store is None:
        if get_settings().use_database:
            _job_store = DbJobStore()
        else:
            _job_store = LegacyJobStoreAdapter()
    return _job_store


def get_results_repo() -> DbResultsRepository | AsyncFsResultsRepository:
    global _results_repo
    if _results_repo is None:
        if get_settings().use_database:
            _results_repo = DbResultsRepository()
        else:
            _results_repo = AsyncFsResultsRepository()
    return _results_repo


def reset_repositories() -> None:
    global _job_store, _results_repo
    _job_store = None
    _results_repo = None
