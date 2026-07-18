from __future__ import annotations

import re

from ..config import settings


_SCHEMA_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def require_database_url() -> str:
    database_url = settings.database_url.strip()
    if not database_url:
        raise RuntimeError("HREVN_DATABASE_URL is not configured.")
    return database_url


def schema_name() -> str:
    schema = settings.database_schema.strip() or "public"
    if not _SCHEMA_RE.match(schema):
        raise RuntimeError(f"Invalid HREVN_DATABASE_SCHEMA value: {schema!r}")
    return schema


def qualified_table(table_name: str) -> str:
    return f"{schema_name()}.{table_name}"


def connect_dict():
    try:
        from psycopg import connect
        from psycopg.rows import dict_row
    except ImportError as exc:
        raise RuntimeError(
            "psycopg is not installed. Add the PostgreSQL dependency before using course persistence."
        ) from exc

    return connect(require_database_url(), row_factory=dict_row)
