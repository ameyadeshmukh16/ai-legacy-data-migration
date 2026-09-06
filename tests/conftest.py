import pytest
from sqlalchemy import create_engine, text
from config.settings import settings


def _postgres_available():
    if not settings.source_db_url:
        return False
    try:
        eng = create_engine(settings.source_db_url)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def pg_engine():
    """A live source-Postgres engine, or skip the test if none is reachable."""
    if not _postgres_available():
        pytest.skip("source Postgres not reachable (start docker-compose to run this test)")
    return create_engine(settings.source_db_url)
