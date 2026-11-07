import json

from fastapi import APIRouter
from mistralai.client.models import ChatCompletionResponse
from pydantic import BaseModel, Field
from utils.mistral import caller_mistral_client

from .route import MODEL, SYSTEM_PROMPT, Mode

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


def _parse(completion: ChatCompletionResponse, mode: Mode) -> RefineResponse:
    content = completion.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty completion")
    data = json.loads(content)
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
    completion = caller_mistral_client().chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content": REFINE_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    return _parse(completion, request.mode)
