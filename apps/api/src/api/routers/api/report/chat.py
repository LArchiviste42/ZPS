import csv
import io
import json

from fastapi import APIRouter
from mistralai.client.models import ChatCompletionResponse
from pydantic import BaseModel, Field
from utils.mistral import caller_mistral_client

from . import _store
from .route import MODEL, SYSTEM_PROMPT, Mode

router = APIRouter()


class ChatMessageIn(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    mode: Mode
    messages: list[ChatMessageIn] = Field(default_factory=list)
    # Contenu texte d'un CSV de la matrice réseau uploadé par l'utilisateur.
    csv: str | None = None


class ChatResponse(BaseModel):
    reply: str
    done: bool = False
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None
    excluded: list[str] = Field(default_factory=list)
    notes: str = ""
    history_id: str | None = Field(default=None, alias="historyId")

    model_config = {"populate_by_name": True}


CHAT_SYSTEM_PROMPT = SYSTEM_PROMPT + """

TU ES EN MODE CONVERSATION : l'utilisateur discute avec toi pour construire son livrable.
- Parle en français, de façon courte et directe. À chaque réponse, demande UNE seule information manquante à la fois.
- Informations à rassembler selon le mode :
  * toujours : nom du client, organizationId, networkId (le networkId change à chaque usage) ;
  * si le mode inclut le CSS : URL du site web du client (pour extraire sa charte) ;
  * si le mode inclut le JSON : nombre d'exercices passés à afficher dans les charts, exerciceId de l'exercice N-1, années N et N-1 (propose 2026 / 2025 par défaut), et les indicateurs de la matrice réseau (fournis via le CSV uploadé, ou demande-les) ;
  * un fichier CSV de la matrice réseau peut être fourni : ses lignes deviennent les indicateurs (Thématique, Sous-thématique, Catégorie, nom, type, ID Parent, flag NA/NM).
- Dès que tu as tout ce qu'il faut, génère le livrable selon les règles ci-dessus et réponds avec "done": true en incluant reportJson et/ou css.
- Réponds UNIQUEMENT avec un objet JSON : { "reply": "<message à l'utilisateur>", "done": bool, "reportJson": ..., "css": "...", "excluded": [...], "notes": "..." }.
- Ne génère rien tant que les informations requises ne sont pas réunies.
"""

_HEADER_ALIASES = {
    "theme": "theme", "thématique": "theme", "thematique": "theme",
    "subtheme": "sub_theme", "sous-thématique": "sub_theme", "sous-thematique": "sub_theme", "sous thématique": "sub_theme",
    "categorie": "category", "catégorie": "category",
    "name": "name", "nom": "name", "indicateur": "name", "libellé": "name", "libelle": "name",
    "type": "type",
    "parentid": "parent_id", "id parent": "parent_id", "idparent": "parent_id",
    "flag": "flag", "na/nm": "flag", "nanm": "flag",
}


def parse_csv_indicators(text: str) -> tuple[list[dict], list[str]]:
    """Parse a network-matrix CSV into indicator dicts; returns (indicators, errors)."""
    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t|")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        return [], ["CSV sans ligne d'en-tête"]
    mapping = {_HEADER_ALIASES.get((f or "").strip().lower(), (f or "").strip().lower()): f for f in reader.fieldnames}
    indicators: list[dict] = []
    errors: list[str] = []
    for row in reader:
        name = (row.get(mapping.get("name", "")) or "").strip()
        if not name:
            continue
        theme = (row.get(mapping.get("theme", "")) or "Général").strip()
        raw_type = (row.get(mapping.get("type", "")) or "Narratif").strip()
        parent = (row.get(mapping.get("parent_id", "")) or "").strip()
        flag = (row.get(mapping.get("flag", "")) or "").strip().upper()
        indicators.append(
            {
                "theme": theme,
                "subTheme": (row.get(mapping.get("sub_theme", "")) or theme).strip(),
                "category": (row.get(mapping.get("category", "")) or "").strip(),
                "name": name,
                "type": raw_type if raw_type in {"Narratif", "Choix multiple", "Choix simple", "Oui/Non", "Nombre", "Pourcentage"} else "Narratif",
                "parentId": int(parent) if parent.isdigit() else None,
                "flag": flag if flag in {"NA", "NM"} else None,
            }
        )
    if not indicators:
        errors.append("Aucune ligne d'indicateur reconnue dans le CSV")
    return indicators, errors


def _parse(completion: ChatCompletionResponse) -> ChatResponse:
    content = completion.choices[0].message.content
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty completion")
    data = json.loads(content)
    return ChatResponse(
        reply=str(data.get("reply") or ""),
        done=bool(data.get("done")),
        report_json=data.get("reportJson"),
        css=data.get("css"),
        excluded=list(data.get("excluded") or []),
        notes=str(data.get("notes") or ""),
    )


@router.post(
    "",
    operation_id="report_chat",
    summary="Conversational report builder: asks for the needed data, then generates JSON/CSS",
)
def report_chat(request: ChatRequest) -> ChatResponse:
    indicators, csv_errors = ([], [])
    if request.csv:
        indicators, csv_errors = parse_csv_indicators(request.csv)
    payload = {
        "mode": request.mode,
        "csvIndicators": indicators,
        "csvErrors": csv_errors,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
    }
    completion = caller_mistral_client().chat.complete(
        model=MODEL,
        messages=[
            {"role": "system", "content": CHAT_SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ],
        response_format={"type": "json_object"},
    )
    response = _parse(completion)
    if response.done and (response.report_json or response.css):
        client_name = ""
        for m in reversed(request.messages):
            if m.role == "user" and m.content:
                client_name = m.content[:80]
                break
        entry = _store.save_entry(
            mode=request.mode,
            client_name=client_name,
            summary=response.reply[:200] or "livrable généré",
            report_json=response.report_json,
            css=response.css,
        )
        response.history_id = entry["id"]
    return response
