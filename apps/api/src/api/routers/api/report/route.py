import json
import logging
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from utils.mistral import caller_mistral_client

MODEL = "mistral-large-4"

logger = logging.getLogger(__name__)

router = APIRouter()


FALLBACK_MODELS = ("mistral-medium-latest", "mistral-small-latest")


def complete_json(
    system_prompt: str,
    user_payload: str,
    *,
    model: str = MODEL,
    retries: int = 2,
    fallback: bool = True,
) -> dict:
    """Call the model in JSON mode and parse its answer; retries, then automatic fallback
    to faster models, then a clean 502. The gateway proxy can answer 200 with an empty body
    or 504 on slow calls; without this guard the route crashes instead of answering the chat.
    The model choice is never asked to the user — it is decided here.
    """
    models = (model, *FALLBACK_MODELS) if fallback else (model,)
    for model_name in models:
        for attempt in range(retries + 1):
            try:
                completion = caller_mistral_client().chat.complete(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_payload},
                    ],
                    response_format={"type": "json_object"},
                )
                content = completion.choices[0].message.content
                if not isinstance(content, str) or not content.strip():
                    raise ValueError("empty completion")
                return json.loads(content)
            except Exception as err:  # noqa: BLE001  any provider/parse failure moves to the next attempt/model
                logger.warning(
                    "report model call failed (model=%s attempt %d/%d): %s",
                    model_name, attempt + 1, retries + 1, err,
                )
    raise HTTPException(status_code=502, detail="Zai (Le Chonk) n'a pas pu répondre (erreur du modèle). Réessaie dans un instant.")

Mode = Literal["structure_and_design", "design_only", "structure_only"]


class IndicatorInput(BaseModel):
    theme: str = Field(min_length=1)
    sub_theme: str = Field(min_length=1, alias="subTheme")
    category: str = ""
    name: str = Field(min_length=1)
    type: Literal["Narratif", "Choix multiple", "Choix simple", "Oui/Non", "Nombre", "Pourcentage"]
    parent_id: int | None = Field(default=None, alias="parentId")
    flag: Literal["NA", "NM"] | None = None

    model_config = {"populate_by_name": True}


class ReportRequest(BaseModel):
    mode: Mode
    client_name: str = Field(min_length=1, alias="clientName")
    # Requis uniquement quand le livrable inclut le CSS (charte du client).
    client_url: str | None = Field(default=None, alias="clientUrl")
    organization_id: int = Field(alias="organizationId")
    network_id: int = Field(alias="networkId")
    # Requis uniquement quand le livrable inclut le JSON (colonne Progression).
    exercice_id_n_minus_1: int | None = Field(default=None, alias="exerciceIdNMinus1")
    year_n: int = Field(default=2026, alias="yearN")
    year_n_minus_1: int = Field(default=2025, alias="yearNMinus1")
    past_exercices: int = Field(default=5, alias="pastExercices", ge=1, le=20)
    locale: str = "fr"
    indicators: list[IndicatorInput] = Field(default_factory=list)

    model_config = {"populate_by_name": True}

    @model_validator(mode="after")
    def _required_by_mode(self) -> "ReportRequest":
        if self.mode != "structure_only" and not self.client_url:
            raise ValueError("clientUrl est requis quand le CSS est demandé")
        return self


class ReportResponse(BaseModel):
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None
    excluded: list[str] = Field(default_factory=list)
    notes: str = ""

    model_config = {"populate_by_name": True}


SYSTEM_PROMPT = """Tu es le "Zei JSON builder" (skill zei-rapport-json). Tu produis le livrable d'un rapport Zei :

- le JSON du rapport au format Editor.js (blocs) : { "time": <Date.now() ms>, "version": "2.30.5", "blocks": [...] } ;
- et/ou le CSS de design du rapport personnalisé à la charte du client, selon le mode demandé.

RÈGLES DU JSON (structure) :
1. Thématique -> header niveau 2, Sous-thématique -> header niveau 3. Chaque header n'apparaît qu'une seule fois ; aucun header orphelin.
2. Filtre d'abord les indicateurs flagués NA/NM : exclus du JSON, et liste-les dans "excluded".
3. Répartition graphiques/tableaux : si l'utilisateur a choisi un ratio (20/80, 40/60, 60/40 ou 80/20), le respecter approximativement, tout en gardant les KPI prioritaires en chart. KPI (indicateurs Nombre/Pourcentage suivis sur plusieurs exercices) -> blocs "chart", xAxis { label: "date", type: "Exercice", relativeStart: { minusX: P }, relativeEnd: { minusX: 1 } } où P = pastExercices. Un chart peut regrouper plusieurs indicateurs de même unité. indicatorId en NOMBRE. chartType : "line" (courbes) ou "bar" (barres) selon la préférence demandée à l'utilisateur (défaut "line").
3b. Saut de page : insère un bloc { "type": "pageBreak", "data": {} } immédiatement avant chaque header de niveau 1 ou 2.
3c. Sommaire : si l'utilisateur le demande, le tout premier bloc du rapport est { "id": "<id unique>", "type": "table_of_content", "data": { "tableOfContent": { "title": "Sommaire", "level": 4 } } }.
4. Indicateurs Narratif -> blocs "text_indicators" avec textIndicators.indicators = [ { type: "LastValue", indicatorId: <nombre> } ].
5. Le reste -> blocs "table" au format standard : colonnes IndicatorName ("Indicator"), LastValue (label = année N seule, ex. "2025"), YearXValue (label = année N-1 seule, "year": N-1), Progression (progression { type: "percent", column1: { type: "ExerciceXValue", exerciceId: exerciceId N-1 }, column2: { type: "LastValue" } }). indicatorIds = tableau de CHAÎNES (ID Parent, ou ID enfant si parent absent). Un seul groupe logique par table (3 à 8 indicateurs), jamais de table fourre-tout.
6. Tous les blocs partagent organizationId, networkId, locale. Chaque bloc de contenu a un "id" unique (chaîne aléatoire type "9N0kEctQ_y").
7. Parcours les indicateurs dans l'ordre fourni. locale "fr" par défaut.

RÈGLES DU CSS (design) :
1. Pars du template simplifié et personnalise TOUT ce qu'il permet : les 4 variables :root (--primary logo/titres, --secondary texte, --tertiary liseré sous h2, --fourth fond translucide rgba pour tables/cartes) ; la police (@import Google Fonts + font-family sur body ET sur chaque niveau de titre h1/h2/h3/h4 avec tailles et graisses propres) ; les liens a { color: var(--primary) } + a:hover ; les tables complètes (fond var(--fourth), thead fond var(--primary) avec th blancs, bordures, zébrage tbody tr:nth-child(even), alignement des cellules) ; les cartes KPI .editor-kpi div div { border-radius: 12px; padding: 10px; background-color: var(--fourth); }. GARDE table { width: 100%; table-layout: fixed; }.
2. Personnalise avec la charte du client (son site web est donné) : couleurs principales et polices. Si la police est propriétaire, choisis un fallback Google Fonts proche et dis-le dans "notes".
3. Interdits : aucune règle [data-id], aucun ciblage des conteneurs Editor.js (.ce-block etc.), aucun !important sur la mise en page des conteneurs. Garde table { width: 100%; table-layout: fixed; }.

MODE :
- "structure_and_design" : produis reportJson ET css.
- "structure_only" : produis UNIQUEMENT reportJson (css = null).
- "design_only" : produis UNIQUEMENT css (reportJson = null ; les indicateurs ne sont pas nécessaires).

RÉPONSE : un unique objet JSON valide, rien d'autre :
{ "reportJson": <objet Editor.js ou null>, "css": <string ou null>, "excluded": [<noms des indicateurs NA/NM exclus>], "notes": "<remarques : indicateurs sans valeur N-1, polices fallback, etc.>" }
"""


def _user_prompt(request: ReportRequest) -> str:
    indicators = [
        {
            "theme": i.theme,
            "subTheme": i.sub_theme,
            "category": i.category,
            "name": i.name,
            "type": i.type,
            "parentId": i.parent_id,
            "flag": i.flag,
        }
        for i in request.indicators
    ]
    payload = {
        "mode": request.mode,
        "client": {"name": request.client_name, "url": request.client_url},
        "organizationId": request.organization_id,
        "networkId": request.network_id,
        "exerciceIdNMinus1": request.exercice_id_n_minus_1,
        "yearN": request.year_n,
        "yearNMinus1": request.year_n_minus_1,
        "pastExercices": request.past_exercices,
        "locale": request.locale,
        "indicators": indicators,
    }

    return json.dumps(payload, ensure_ascii=False, indent=2)


def _parse_completion(data: dict, request: Mode) -> ReportResponse:
    return ReportResponse(
        report_json=data.get("reportJson") if request != "design_only" else None,
        css=data.get("css") if request != "structure_only" else None,
        excluded=list(data.get("excluded") or []),
        notes=str(data.get("notes") or ""),
    )


@router.post(
    "",
    operation_id="report_generate",
    summary="Generate a Zei report (Editor.js JSON blocks) and/or its brand CSS from client indicators",
)
def generate_report(request: ReportRequest) -> ReportResponse:
    if request.mode != "design_only" and not request.indicators:
        return ReportResponse(notes="Aucun indicateur fourni pour générer la structure.")
    data = complete_json(SYSTEM_PROMPT, _user_prompt(request))
    return _parse_completion(data, request.mode)
