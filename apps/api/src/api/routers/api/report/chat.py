import base64
import csv
import io
import json
import logging
import re
import xml.etree.ElementTree as ET
import zipfile
from typing import Literal

import httpx
from fastapi import APIRouter
from pydantic import BaseModel, Field

from . import _store
from .route import MODEL, SYSTEM_PROMPT, Mode, complete_json

logger = logging.getLogger(__name__)

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
    # Fichier XLSX uploadé, encodé en base64 (les .xlsx sont des zip binaires).
    file_b64: str | None = Field(default=None, alias="fileB64")
    # Livrable courant, pour les demandes de raffinement en langage naturel après génération.
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None


class FieldSpec(BaseModel):
    key: str
    label: str
    type: Literal["text", "number", "file", "choice"]
    choices: list[str] | None = None
    placeholder: str | None = None


class ChatResponse(BaseModel):
    reply: str
    done: bool = False
    # Choix cliquables proposés à l'utilisateur quand la question est fermée (oui/non, ligne/barre…).
    options: list[str] = Field(default_factory=list)
    # Questionnaire multi-champs quand plusieurs informations sont demandées en même temps.
    fields: list[FieldSpec] = Field(default_factory=list)
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
  * mode JSON seul ("structure_only") : demande (1) EN PREMIER le fichier CSV **ou XLSX** de la matrice réseau / architecture du network du client (colonnes Thématique, Sous-thématique, Catégorie, Indicateur, Type, ID Parent, flag NA/NM — l'ORGANIZATION ID y figure souvent, note-le), (2) ensuite l'ID client (organizationId, s'il n'est pas dans le fichier) et l'ID réseau (networkId — il change à chaque usage), (3) combien d'années / exercices historiques afficher dans les graphiques, (4) la répartition souhaitée entre graphiques et tableaux : 20% graphiques / 80% tableaux, 40/60, 60/40 ou 80/20, (5) si un sommaire (table_of_content) est souhaité (oui/non), (6) le type de graphiques préféré : courbes "line" ou barres "bar".
  * mode JSON & CSS ("structure_and_design") : d'abord les questions CSS (nom du client, URL du site), puis les questions JSON (CSV, IDs, exercices historiques, répartition graphiques/tableaux).
- Dès que tu as tout ce qu'il faut :
  * en mode combiné, produis le CSS ET le JSON dans la même réponse (présente d'abord le CSS dans "reply", puis le JSON aussitôt après, sans attendre) ;
  * réponds avec "done": true en incluant reportJson et/ou css.
- Quand tu poses une question fermée (oui/non ou choix unique entre plusieurs options), remplis "options" avec les choix cliquables en 1 clic, ex. ["Oui", "Non"] ou ["Ligne", "Barre"].
- Quand tu demandes PLUSIEURS informations en même temps, ne les énumère pas en texte : remplis "fields" avec un questionnaire, un objet par champ : { "key": "organizationId", "label": "ID client (organizationId)", "type": "number", "placeholder": "ex. 49" }. Types : "text", "number", "file" (upload du CSV), "choice" (avec "choices": [...], ex. ["Oui","Non"]). Chaque champ indique le format de réponse attendu.
- ORDRE DES DEMANDES en mode JSON : d'abord organizationId + networkId (toujours des NOMBRES : champs "type": "number"), puis le fichier CSV de la matrice réseau, puis les choix (nombre d'exercices historiques, ratio graphiques/tableaux, sommaire oui/non, type de graphique ligne/barre). En mode combiné, les questions CSS (nom, URL) viennent avant.
- Réponds UNIQUEMENT avec un objet JSON : { "reply": "<message à l'utilisateur>", "done": bool, "options": [...], "reportJson": ..., "css": "...", "excluded": [...], "notes": "..." }.
- Ne génère rien tant que les informations requises ne sont pas réunies.
- Si "siteBrand" est présent dans le payload, c'est l'identité visuelle RÉELLEMENT extraite du site du client (couleurs hex, polices) : utilise SES couleurs pour --primary/--secondary/--tertiary/--fourth et SES polices pour les font-family — ne devine aucune autre couleur.
- NE DIS JAMAIS « je vais extraire la charte graphique du site », « je consulte le site », « je récupère la charte » : tu ne peux pas naviguer. Dès que tu as le nom du client et l'URL, GÉNÈRE le CSS immédiatement : charte connue si la marque est célèbre (ex. EDF : --primary #07387a, --secondary #000000, --tertiary #ff5e11, --fourth rgba(150,210,242,0.35), police Nunito Sans), sinon demande les codes hex / polices de la charte du client (question avec options/fields si besoin). Ne reste jamais sur une phrase d'annonce sans rien produire. Le contenu du CSV/XLSX est DÉJÀ parsé et fourni dans "csvIndicators" : ne dis jamais « je vais analyser le fichier » — utilise directement csvIndicators pour construire le JSON.
- Ne réponds JAMAIS done=true sans livrable non vide : en mode CSS, "css" doit contenir le CSS complet ; en mode JSON, "reportJson" le JSON complet ; en mode combiné, les deux.
- Ne demande JAMAIS de confirmation à l'utilisateur (« c'est bon ? », « voulez-vous que je génère ? », « puis-je commencer ? ») : dès que tu as toutes les informations requises, génère immédiatement (done=true avec le livrable). L'utilisateur peut toujours affiner ensuite en langage naturel.
- MODE COMBINÉ (structure_and_design) EN DEUX TEMPS :
  * phase 1 (currentReportJson absent) : rassemble les infos JSON (CSV matrice réseau, organizationId, networkId, exercices historiques, ratio graphiques/tableaux) et génère UNIQUEMENT reportJson (css = null), done=true. Dans "reply", dis : le JSON est prêt et téléchargeable — réponds « ok » pour passer au CSS.
  * phase 2 (currentReportJson fourni, currentCss absent) : rassemble les infos CSS si manquantes (nom du client, URL du site), puis génère UNIQUEMENT le css (reportJson = currentReportJson inchangé), done=true.
- RAFFINEMENT : si un livrable a déjà été généré (currentCss / currentReportJson fournis) et que l'utilisateur demande une modification en langage naturel (« rends les titres plus gros », « change la couleur principale »…), modifie le livrable existant en conséquence et réponds done=true avec le livrable modifié. Ne recommence pas les questions.
- NOUVELLE DEMANDE = repartir de zéro : si l'utilisateur annonce un nouveau client, une nouvelle URL de site ou une nouvelle demande, IGNORE currentCss / currentReportJson (ils appartiennent à une autre demande) et régénère depuis le template de base + la charte du NOUAUVEAU client. Ne mélange jamais la charte d'un ancien client avec celle du nouveau.
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



_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


def fetch_site_brand(url: str) -> dict:
    """Extract the client site's visual identity: title, hex colors and font-families from the
    HTML and its first stylesheets. Best-effort; returns an error field on failure."""
    try:
        with httpx.Client(timeout=10, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"}) as client:
            resp = client.get(url)
            html = resp.text[:200_000]
            colors = re.findall(r"#[0-9a-fA-F]{6}\b", html)
            fonts = re.findall(r"font-family:\s*([^;}]+)", html)
            for href in re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\']', html)[:3]:
                css_url = href if href.startswith("http") else resp.url.join(href).human_repr()
                try:
                    css = client.get(css_url).text[:100_000]
                    colors += re.findall(r"#[0-9a-fA-F]{6}\b", css)
                    fonts += re.findall(r"font-family:\s*([^;}]+)", css)
                except Exception:  # noqa: BLE001  one stylesheet failing must not sink the rest
                    continue
            title = re.search(r"<title>([^<]+)</title>", html)
            return {
                "url": str(resp.url),
                "title": title.group(1).strip() if title else "",
                "colors": sorted({c.lower() for c in colors})[:16],
                "fonts": sorted(set(fonts))[:10],
            }
    except Exception as err:  # noqa: BLE001
        logger.warning("site brand fetch failed for %s: %s", url, err)
        return {"url": url, "error": str(err)}


def xlsx_to_csv_text(data: bytes) -> str:
    """Minimal XLSX reader (stdlib only): first sheet, shared strings resolved, cells joined by ';'."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
        sheet_name = next((n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")), None)
        if sheet_name is None:
            raise ValueError("Aucune feuille trouvée dans le XLSX")
        root = ET.fromstring(z.read(sheet_name))
    lines: list[str] = []
    for row in root.iter(f"{ns}row"):
        cells: list[str] = []
        for c in row.findall(f"{ns}c"):
            v = c.find(f"{ns}v")
            text = v.text if v is not None else ""
            if c.get("t") == "s" and text is not None:
                text = shared[int(text)] if int(text) < len(shared) else text
            cells.append(text or "")
        lines.append(";".join(cells))
    return "\n".join(lines)


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
        options=[str(o) for o in (data.get("options") or [])],
        fields=[
            FieldSpec(
                key=str(f.get("key") or ""),
                label=str(f.get("label") or ""),
                type=str(f.get("type") or "text"),
                choices=[str(c) for c in f["choices"]] if f.get("choices") else None,
                placeholder=f.get("placeholder"),
            )
            for f in (data.get("fields") or [])
            if isinstance(f, dict) and f.get("key")
        ],
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
    csv_text = request.csv
    if request.file_b64:
        raw = base64.b64decode(request.file_b64)
        if raw[:2] == b"PK":  # XLSX = zip
            try:
                csv_text = xlsx_to_csv_text(raw)
            except Exception as err:  # noqa: BLE001
                csv_errors = [f"XLSX illisible : {err}"]
        else:
            csv_text = raw.decode("utf-8", errors="replace")
    if csv_text:
        indicators, csv_errors = parse_csv_indicators(csv_text) if not csv_errors else (indicators, csv_errors)
    site_url = next((m for msg in reversed(request.messages) for m in [_URL_RE.search(msg.content)] if m), None)
    site_brand = None
    if site_url and request.mode != "structure_only":
        site_brand = fetch_site_brand(site_url.group(0).rstrip(".,;"))
    payload = {
        "mode": request.mode,
        "siteBrand": site_brand,
        "csvIndicators": indicators,
        "csvErrors": csv_errors,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "currentReportJson": request.report_json,
        "currentCss": request.css,
    }
    data = complete_json(CHAT_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), model=CHAT_MODEL, retries=2, fallback=False)
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
    # Two-phase combined mode: phase 1 = JSON only, phase 2 (current JSON present) = CSS.
    if request.mode == "structure_and_design":
        if request.report_json is None:
            response.css = None
        else:
            response.report_json = response.report_json or request.report_json
    # Guard: done=true but the deliverable for the mode is empty -> one corrective call.
    needs_css = request.mode == "design_only" or (request.mode == "structure_and_design" and request.report_json is not None)
    needs_json = request.mode != "design_only"
    if response.done and ((needs_css and not response.css) or (needs_json and not response.report_json)):
        corrected = complete_json(
            CHAT_SYSTEM_PROMPT + "\nCORRECTION : ta réponse disait done=true sans livrer de contenu non vide. Produits maintenant le livrable complet demandé (css et/ou reportJson).",
            json.dumps(payload, ensure_ascii=False),
            model=CHAT_MODEL,
            retries=1,
        )
        fixed = _parse(corrected)
        if needs_css and not response.css:
            response.css = fixed.css
        if needs_json and not response.report_json:
            response.report_json = fixed.report_json
        if not ((needs_css and response.css) or (needs_json and response.report_json)):
            response.done = False
            response.reply += " (Je n'ai pas réussi à produire le livrable : peux-tu me donner les codes couleur hex de la charte du client ?)"
    # Stuck guard: not done, no question, no options/fields, or an announcement ("je vais...") ->
    # the model announced instead of acting. Up to 2 corrective rounds until it delivers or asks.
    for _ in range(2):
        announced = "je vais" in response.reply.lower()
        if response.done or response.options or response.fields or ("?" in response.reply and not announced):
            break
        corrected = complete_json(
            CHAT_SYSTEM_PROMPT + "\nCORRECTION : ta dernière réponse annonçait une action sans rien produire. Le CSV est déjà parsé dans csvIndicators. Génère maintenant le livrable demandé (done=true + contenu), ou pose la prochaine question.",
            json.dumps(payload, ensure_ascii=False),
            model=CHAT_MODEL,
            retries=1,
            fallback=False,
        )
        fixed = _parse(corrected)
        response.reply = fixed.reply or response.reply
        response.done = fixed.done
        response.options = fixed.options
        response.fields = fixed.fields
        response.report_json = fixed.report_json or response.report_json
        response.css = fixed.css or response.css
        response.excluded = fixed.excluded or response.excluded
        if not response.notes and fixed.notes:
            response.notes = fixed.notes
    if response.done and (response.report_json or response.css):
        client_name = ""
        for m in reversed(request.messages):
            if m.role == "user" and m.content:
                client_name = m.content[:80]
                break
        try:
            entry = _store.save_entry(
                mode=request.mode,
                client_name=client_name,
                summary=response.reply[:200] or "livrable généré",
                report_json=response.report_json,
                css=response.css,
            )
            response.history_id = entry["id"]
        except OSError:
            # History is best-effort: never fail the request (and lose the deliverable) over it.
            logger.warning("history save failed", exc_info=True)
    return response
