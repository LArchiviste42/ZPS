import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .route import SYSTEM_PROMPT, Mode, complete_json

router = APIRouter()


class RefineRequest(BaseModel):
    mode: Mode
    instruction: str = Field(min_length=1)
    client_name: str = Field(default="", alias="clientName")
    client_url: str | None = Field(default=None, alias="clientUrl")
    organization_id: int | None = Field(default=None, alias="organizationId")
    network_id: int | None = Field(default=None, alias="networkId")
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None

    model_config = {"populate_by_name": True}


class RefineResponse(BaseModel):
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None
    notes: str = ""

    model_config = {"populate_by_name": True}


REFINE_SYSTEM_PROMPT = SYSTEM_PROMPT + """

MODE RAFFINEMENT : tu reçois le livrable courant (reportJson et/ou css) plus une instruction en langage
naturel de l'utilisateur. Modifie le livrable en conséquence (structure, contenu, ou style), en respectant
les mêmes règles. Ne change que ce que l'instruction demande. Réponds UNIQUEMENT avec le même objet JSON :
{ "reportJson": <objet Editor.js modifié ou null>, "css": <string modifiée ou null>, "notes": "<ce qui a changé>" }.
"""


def _parse(data: dict, mode: Mode) -> RefineResponse:
    return RefineResponse(
        report_json=data.get("reportJson") if mode != "design_only" else None,
        css=data.get("css") if mode != "structure_only" else None,
        notes=str(data.get("notes") or ""),
    )


@router.post(
    "",
    operation_id="report_refine",
    summary="Refine the generated report JSON/CSS from a natural-language instruction",
)
def refine_report(request: RefineRequest) -> RefineResponse:
    payload = {
        "mode": request.mode,
        "client": {"name": request.client_name, "url": request.client_url},
        "organizationId": request.organization_id,
        "networkId": request.network_id,
        "instruction": request.instruction,
        "currentReportJson": request.report_json,
        "currentCss": request.css,
    }
    data = complete_json(REFINE_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
    return _parse(data, request.mode)
