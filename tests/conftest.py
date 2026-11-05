from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.repositories.sqlite import SQLiteRepository


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        APP_ENV="test",
        APP_HOST="127.0.0.1",
        PORT=9000,
        ADMIN_API_KEY="admin-secret",
        DATABASE_PROVIDER="sqlite",
        STORAGE_PROVIDER="local",
        VECTOR_PROVIDER="sqlite",
        SQLITE_PATH=tmp_path / "orbit.db",
        LOCAL_STORAGE_PATH=tmp_path / "storage",
        ROUTER_PROVIDER="test",
        ROUTER_MODEL="router-model",
        ROUTER_API_KEY="router-secret",
        ANSWER_PROVIDER="test",
        ANSWER_MODEL="answer-model",
        ANSWER_API_KEY="answer-secret",
        GEMINI_API_KEY="embedding-secret",
    )


@pytest.fixture
def repository(settings: Settings) -> SQLiteRepository:
    return SQLiteRepository(settings.sqlite_path, "test:embeddings:3")
