"""File-backed history of generated reports (id, date, mode, client, deliverables).

Kept in a plain JSON file so the app needs no database module; the path comes from
REPORT_HISTORY_PATH (default: a file in the system temp dir, since the deployed container's
working directory is read-only).
"""

import json
import os
import tempfile
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_lock = threading.Lock()


def _path() -> Path:
    # Default to the temp dir: the deployed container's working directory is not writable.
    return Path(os.environ.get("REPORT_HISTORY_PATH") or Path(tempfile.gettempdir()) / "zps-report-history.json")


def list_entries() -> list[dict[str, Any]]:
    with _lock:
        path = _path()
        if not path.exists():
            return []
        entries = json.loads(path.read_text(encoding="utf-8"))
    return [
        {k: e[k] for k in ("id", "created_at", "mode", "client_name", "summary") if k in e}
        for e in entries
    ]


def get_entry(entry_id: str) -> dict[str, Any] | None:
    with _lock:
        path = _path()
        if not path.exists():
            return None
        entries = json.loads(path.read_text(encoding="utf-8"))
    for e in entries:
        if e.get("id") == entry_id:
            return e
    return None


def save_entry(*, mode: str, client_name: str, summary: str, report_json: Any, css: str | None) -> dict[str, Any]:
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
