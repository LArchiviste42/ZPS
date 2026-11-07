from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel

from .. import _store

router = APIRouter()


class HistoryEntry(BaseModel):
    id: str
    created_at: str
    mode: str
    client_name: str
    summary: str


class HistoryListResponse(BaseModel):
    entries: list[HistoryEntry]


@router.get(
    "",
    operation_id="report_history_list",
    summary="List past generated reports (newest first)",
)
def history_list() -> HistoryListResponse:
    entries: list[dict[str, Any]] = _store.list_entries()
    return HistoryListResponse(
        entries=[
            HistoryEntry(
                id=e["id"],
                created_at=e.get("created_at", ""),
                mode=e.get("mode", ""),
                client_name=e.get("client_name", ""),
                summary=e.get("summary", ""),
            )
            for e in entries
        ]
    )
