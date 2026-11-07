import csv
import io
import json

from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import _store
from .route import MODEL, SYSTEM_PROMPT, Mode, complete_json

# Fast model for the conversational Q&A turns; ML4 (MODEL) is reserved for the final
# generation, which is the heavy turn. ML4's reasoning makes even a trivial question take
# several seconds per call.
CHAT_MODEL = "mistral-small-latest"

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

Tu t'appelles Zai (Le Chonk). Quand tu livres un rapport, signe « — Zai (Le Chonk) ».

TU ES EN MODE CONVERSATION : l'utilisateur discute avec toi pour construire son livrable.
- Parle en français, de façon courte et directe. Tu peux poser les questions d'un même groupe en lot, une à la fois sinon.
- ORDRE DES QUESTIONS SELON LE MODE :
  * mode CSS seul ("design_only") : demande le nom du client, puis l'URL de son site web (pour extraire sa charte graphique).
  * mode JSON seul ("structure_only") : demande (1) le fichier CSV de la matrice réseau / architecture du network du client (export Excel accepté en CSV ; colonnes Thématique, Sous-thématique, Catégorie, Indicateur, Type, ID Parent, flag NA/NM), (2) l'ID client (organizationId) et l'ID réseau (networkId — il change à chaque usage), (3) combien d'années / exercices historiques afficher dans les graphiques, (4) la répartition souhaitée entre graphiques et tableaux : 20% graphiques / 80% tableaux, 40/60, 60/40 ou 80/20.
  * mode JSON & CSS ("structure_and_design") : d'abord les questions CSS (nom du client, URL du site), puis les questions JSON (CSV, IDs, exercices historiques, répartition graphiques/tableaux).
- Dès que tu as tout ce qu'il faut :
  * en mode combiné, produis le CSS ET le JSON dans la même réponse (présente d'abord le CSS dans "reply", puis le JSON aussitôt après, sans attendre) ;
  * réponds avec "done": true en incluant reportJson et/ou css.
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


def _parse(data: dict) -> ChatResponse:
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
    data = complete_json(CHAT_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), model=CHAT_MODEL, retries=2)
    response = _parse(data)
    if response.done and (response.report_json or response.css):
        # The turn that produces the deliverable is regenerated with ML4 for quality.
        final = complete_json(
            CHAT_SYSTEM_PROMPT + "\nL'utilisateur a tout fourni : génère maintenant le livrable final complet.",
            json.dumps(payload, ensure_ascii=False),
            model=MODEL,
            retries=2,
        )
        final_response = _parse(final)
        response.report_json = final_response.report_json
        response.css = final_response.css
        response.excluded = final_response.excluded
        if final_response.notes:
            response.notes = final_response.notes
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
