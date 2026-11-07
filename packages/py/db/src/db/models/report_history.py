import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Column, Text
from sqlmodel import Field, SQLModel


class ReportHistory(SQLModel, table=True):
    __tablename__ = "report_history"

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12], primary_key=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    mode: str
    client_name: str = Field(default="")
    summary: str = Field(default="")
    report_json: dict | None = Field(default=None, sa_column=Column(JSON))
    css: str | None = Field(default=None, sa_column=Column(Text))
