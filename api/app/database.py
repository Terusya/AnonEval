from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from app.config import get_settings


_pool: ConnectionPool | None = None


def open_pool() -> None:
    global _pool
    settings = get_settings()
    _pool = ConnectionPool(
        conninfo=settings.database_url,
        min_size=1,
        max_size=10,
        kwargs={"row_factory": dict_row},
        open=True,
    )


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    return _pool
