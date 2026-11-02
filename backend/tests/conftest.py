"""Test bootstrap: isolated data directory, clean database per test."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

TEST_DATA = Path(tempfile.mkdtemp(prefix="cnki_scholar_test_"))
os.environ["CNKI_DATA_DIR"] = str(TEST_DATA)
os.environ["CNKI_DATABASE_URL"] = f"sqlite:///{TEST_DATA / 'test.db'}"
os.environ["CNKI_LOG_LEVEL"] = "WARNING"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

from app.database.init_db import init_db  # noqa: E402
from app.database.session import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(autouse=True)
def reset_database():
    Base.metadata.drop_all(bind=engine)
    with engine.connect() as conn:
        conn.execute(text("DROP TABLE IF EXISTS paper_fts"))
        conn.commit()
    init_db()
    yield


@pytest.fixture()
def db():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    # No lifespan: tests exercise handlers deterministically instead of a background loop.
    return TestClient(app)


@pytest.fixture(scope="session")
def sample_pdf() -> Path:
    path = Path(__file__).resolve().parents[2] / "examples" / "sample_papers" / "2023_岩土边坡稳定性预测_张示例.pdf"
    assert path.exists(), "sample PDF fixture missing"
    return path


@pytest.fixture(scope="session")
def sample_ris() -> Path:
    path = Path(__file__).resolve().parents[2] / "examples" / "sample_metadata.ris"
    assert path.exists(), "sample RIS fixture missing"
    return path
