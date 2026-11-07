# noqa: N999  (file-based router: [entry] is the {entry} URL parameter)
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .. import _store

router = APIRouter()


class HistoryDetail(BaseModel):
    id: str
    created_at: str
    mode: str
    client_name: str
    summary: str
    report_json: Any = Field(alias="reportJson")
    css: str | None = None
    messages: list | None = None

    model_config = {"populate_by_name": True}


@router.get(
    "",
    operation_id="report_history_get",
    summary="Load one past generated report (JSON and/or CSS)",
)
def history_get(entry: str) -> HistoryDetail:
    record = _store.get_entry(entry)
    if record is None:
        raise HTTPException(status_code=404, detail="Entrée d'historique introuvable")
    return HistoryDetail(
        id=record["id"],
        created_at=record.get("created_at", ""),
        mode=record.get("mode", ""),
        client_name=record.get("client_name", ""),
        summary=record.get("summary", ""),
        report_json=record.get("report_json"),
        css=record.get("css"),
        messages=record.get("messages"),
    )
