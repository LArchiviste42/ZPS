"""Reads/writes of report_history rows. The only place that queries this table."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from db.engine import get_session_maker
from db.models.report_history import ReportHistory


def _to_dict(row: ReportHistory) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at.isoformat(),
        "mode": row.mode,
        "client_name": row.client_name,
        "summary": row.summary,
        "report_json": row.report_json,
        "css": row.css,
        "messages": row.messages,
    }


async def list_entries() -> list[dict[str, Any]]:
    async with get_session_maker()() as session:  # type: AsyncSession
        result = await session.execute(select(ReportHistory).order_by(ReportHistory.created_at.desc()))
        return [_to_dict(row) for row in result.scalars().all()]


async def get_entry(entry_id: str) -> dict[str, Any] | None:
    async with get_session_maker()() as session:
        row = await session.get(ReportHistory, entry_id)
        return _to_dict(row) if row else None


async def save_entry(*, mode: str, client_name: str, summary: str, report_json: Any, css: str | None, messages: Any = None) -> dict[str, Any]:
    row = ReportHistory(
        id=uuid.uuid4().hex[:12],
        created_at=datetime.now(UTC),
        mode=mode,
        client_name=client_name,
        summary=summary,
        report_json=report_json,
        css=css,
        messages=messages,
    )
    async with get_session_maker()() as session:
        session.add(row)
        await session.commit()
    return _to_dict(row)
