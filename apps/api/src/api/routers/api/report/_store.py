"""History of generated reports, stored in the app's Postgres database when the platform
provides one (DATABASE_URL is set on deployed services), else in a local JSON file (dev/tests).
"""

import asyncio
import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_lock = threading.Lock()


def _use_db() -> bool:
    # The platform injects the managed DB's connection settings (POSTGRES_HOST / a non-local
    # DATABASE_URL) into deployed services. Local dev and tests keep the default localhost URL
    # or none at all -> file store, so nothing depends on a running Postgres.
    if os.environ.get("REPORT_HISTORY_DB") == "1":
        return True
    if os.environ.get("POSTGRES_HOST"):
        return True
    url = os.environ.get("DATABASE_URL", "")
    return bool(url) and "localhost" not in url and "127.0.0.1" not in url


def _path() -> Path:
    return Path(os.environ.get("REPORT_HISTORY_PATH") or Path(tempfile.gettempdir()) / "zps-report-history.json")


# ---------- Postgres backend ----------

def _db_list() -> list[dict[str, Any]]:
    from db.accessors.report_history import list_entries as db_list

    return asyncio.run(db_list())


def _db_get(entry_id: str) -> dict[str, Any] | None:
    from db.accessors.report_history import get_entry as db_get

    return asyncio.run(db_get(entry_id))


def _db_save(**kwargs: Any) -> dict[str, Any]:
    from db.accessors.report_history import save_entry as db_save

    return asyncio.run(db_save(**kwargs))


# ---------- File backend ----------

def _file_list() -> list[dict[str, Any]]:
    with _lock:
        path = _path()
        if not path.exists():
            return []
        entries = json.loads(path.read_text(encoding="utf-8"))
    return [{k: e[k] for k in ("id", "created_at", "mode", "client_name", "summary") if k in e} for e in entries]


def _file_get(entry_id: str) -> dict[str, Any] | None:
    with _lock:
        path = _path()
        if not path.exists():
            return None
        entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e.get("id") == entry_id:
            return e
    return None


def _file_save(*, mode: str, client_name: str, summary: str, report_json: Any, css: str | None) -> dict[str, Any]:
    entry = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(UTC).isoformat(),
        "mode": mode,
        "client_name": client_name,
        "summary": summary,
        "report_json": report_json,
        "css": css,
    }
    with _lock:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        entries = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        entries.insert(0, entry)
        path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")
    return entry


# ---------- Public facade ----------

def list_entries() -> list[dict[str, Any]]:
    if _use_db():
        try:
            return _db_list()
        except Exception:
            logger.warning("history DB read failed, falling back to file", exc_info=True)
    return _file_list()


def get_entry(entry_id: str) -> dict[str, Any] | None:
    if _use_db():
        try:
            return _db_get(entry_id)
        except Exception:
            logger.warning("history DB read failed, falling back to file", exc_info=True)
    return _file_get(entry_id)


def save_entry(*, mode: str, client_name: str, summary: str, report_json: Any, css: str | None) -> dict[str, Any]:
    if _use_db():
        try:
            return _db_save(mode=mode, client_name=client_name, summary=summary, report_json=report_json, css=css)
        except Exception:
            logger.warning("history DB write failed, falling back to file", exc_info=True)
    return _file_save(mode=mode, client_name=client_name, summary=summary, report_json=report_json, css=css)
