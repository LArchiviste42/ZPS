import base64
import csv
import io
import json
import logging
import os
import time
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
CHAT_MODEL = os.environ.get("REPORT_CHAT_MODEL", "mistral-small-latest")

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
    # Capture d'écran du site du client (image), encodée en base64 — pour déduire le design quand le site bloque les bots.
    image_b64: str | None = Field(default=None, alias="imageB64")
    # "css" quand l'utilisateur a cliqué « JSON terminé » : on passe alors à la phase CSS.
    force_phase: str | None = Field(default=None, alias="forcePhase")
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
    # True quand le prochain attendu est un FICHIER (matrice CSV/XLSX ou capture d'écran).
    awaiting_file: bool = Field(default=False, alias="awaitingFile")
    report_json: dict | None = Field(default=None, alias="reportJson")
    css: str | None = None
    excluded: list[str] = Field(default_factory=list)
    notes: str = ""
    history_id: str | None = Field(default=None, alias="historyId")

    model_config = {"populate_by_name": True}


CHAT_SYSTEM_PROMPT = SYSTEM_PROMPT + """

Tu t'appelles Zai. Quand tu livres un rapport, signe « — Zai ».

TU ES EN MODE CONVERSATION : l'utilisateur discute avec toi pour construire son livrable.
- Parle en français, de façon courte et directe. Tu peux poser les questions d'un même groupe en lot, une à la fois sinon.
- ORDRE DES QUESTIONS SELON LE MODE :
  * mode CSS seul ("design_only") : demande le nom du client, puis l'URL de son site web (pour extraire sa charte graphique).
  * mode JSON seul ("structure_only") : demande (1) EN PREMIER le fichier CSV **ou XLSX** de la matrice réseau / architecture du network du client (colonnes Thématique, Sous-thématique, Catégorie, Indicateur, Type, ID Parent, flag NA/NM — l'ORGANIZATION ID y figure souvent, note-le), (2) ensuite l'ID client (organizationId, s'il n'est pas dans le fichier) et l'ID réseau (networkId — il change à chaque usage), (3) combien d'années / exercices historiques afficher dans les graphiques, (4) la répartition souhaitée entre graphiques et tableaux : 20% graphiques / 80% tableaux, 40/60, 60/40 ou 80/20, (5) si un sommaire (table_of_content) est souhaité (oui/non), (6) le type de graphiques préféré : courbes "line" ou barres "bar".
  * mode JSON & CSS ("structure_and_design") : d'abord TOUTES les questions JSON (fichier matrice d'abord, puis IDs, exercices, ratio, sommaire, ligne/barre), puis en phase 2 les questions CSS (nom, URL).
- Dès que tu as tout ce qu'il faut :
  * en mode combiné (JSON & CSS) : JAMAIS les deux en même temps — d'abord le JSON (phase 1), puis le CSS en phase 2 après confirmation de l'utilisateur ;
  * réponds avec "done": true en incluant reportJson et/ou css.
- Quand tu poses une question fermée (oui/non ou choix unique entre plusieurs options), remplis "options" avec les choix cliquables en 1 clic, ex. ["Oui", "Non"] ou ["Ligne", "Barre"].
- Quand le prochain élément attendu est un FICHIER (export matrice réseau CSV/XLSX, ou capture d'écran du site), mets "awaitingFile": true (le bouton "Ajouter un fichier" apparaîtra dans le chat) ; si c'est dans un lot, mets aussi le champ correspondant en "fields" avec "type": "file".
- Quand tu demandes PLUSIEURS informations en même temps, ne les énumère pas en texte : remplis "fields" avec un questionnaire, un objet par champ : { "key": "organizationId", "label": "ID client (organizationId)", "type": "number", "placeholder": "ex. 49" }. Types : "text", "number", "file" (upload du CSV), "choice" (avec "choices": [...], ex. ["Oui","Non"]). Chaque champ indique le format de réponse attendu.
- ORDRE DES DEMANDES en mode JSON : d'abord le FICHIER matrice réseau (CSV ou XLSX, champ "type": "file"), PUIS les questions (organizationId + networkId toujours des NOMBRES "type": "number", puis exercices, ratio, sommaire, ligne/barre) (nombre d'exercices historiques, ratio graphiques/tableaux, sommaire oui/non, type de graphique ligne/barre). En mode combiné (JSON & CSS) : d'abord TOUTES les questions JSON (CSV, IDs, exercices, ratio, sommaire, ligne/barre) et on génère le JSON en phase 1 ; PUIS les questions CSS (nom du client, URL du site) et le CSS en phase 2 — jamais l'inverse.
- Réponds UNIQUEMENT avec un objet JSON : { "reply": "<message à l'utilisateur>", "done": bool, "options": [...], "reportJson": ..., "css": "...", "excluded": [...], "notes": "..." }.
- Ne génère rien tant que les informations requises ne sont pas réunies.
- Ne mentionne JAMAIS la protection contre les bots si "siteBrand" est absent ou si "siteBrand.blocked" n'est pas true.
- Si "siteBrand.blocked" == true (vrai bot-wall constaté) : dis que le site est protégé par les bots et demande une CAPTURE D'ÉCRAN dans le chat ; ne génère pas le CSS sans.
- Si "siteBrand.error" est présent (site non lisible depuis l'app, ex. proxy/egress) : ne dis PAS « protégé par les bots » — dis que tu n'as pas pu lire le site automatiquement et demande une capture d'écran (bouton « Ajouter un fichier »).
- Si une image est attachée au message utilisateur (capture d'écran du site) : analyse-la visuellement (couleurs dominantes, polices, style général, espacements) et déduis le CSS dessus pour --primary/--secondary/--tertiary/--fourth, les polices et l'agencement.
- Si "siteBrand" est présent dans le payload, c'est l'identité visuelle RÉELLEMENT extraite du site du client (couleurs hex, polices) : utilise SES couleurs pour --primary/--secondary/--tertiary/--fourth (--primary = la PREMIÈRE couleur de siteBrand.colors, la plus fréquente/dominante) et SES polices (première de siteBrand.fonts en priorité, avec @import Google Fonts si c'est une webfont connue) — ne devine aucune autre couleur.
- NE DIS JAMAIS « je vais extraire la charte graphique du site », « je consulte le site », « je récupère la charte » : tu ne peux pas naviguer. Dès que tu as le nom du client et l'URL, GÉNÈRE le CSS immédiatement : charte connue si la marque est célèbre (ex. EDF : --primary #07387a, --secondary #000000, --tertiary #ff5e11, --fourth rgba(150,210,242,0.35), police Nunito Sans), sinon demande les codes hex / polices de la charte du client (question avec options/fields si besoin). Ne reste jamais sur une phrase d'annonce sans rien produire. Le contenu du CSV/XLSX est DÉJÀ parsé et fourni dans "csvIndicators" : ne dis jamais « je vais analyser le fichier » — utilise directement csvIndicators pour construire le JSON.
- Ne réponds JAMAIS done=true sans livrable non vide : en mode CSS, "css" doit contenir le CSS complet ; en mode JSON, "reportJson" le JSON complet ; en mode combiné, les deux.
- Ne demande JAMAIS de confirmation à l'utilisateur (« c'est bon ? », « voulez-vous que je génère ? », « puis-je commencer ? », « je génère ? ») : dès que tu as toutes les informations requises, génère IMMÉDIATEMENT (done=true avec le livrable). Tu peux afficher le message « Merci pour les infos. Je génère le JSON du rapport maintenant… » MAIS tu dois produire le livrable dans la MÊME réponse (done=true), sans attendre aucun clic. L'utilisateur peut affiner ensuite en langage naturel.
- MODE COMBINÉ (structure_and_design) EN DEUX TEMPS :
  * phase 1 (currentReportJson absent) : rassemble les infos JSON (CSV matrice réseau, organizationId, networkId, exercices historiques, ratio graphiques/tableaux) et génère UNIQUEMENT reportJson (css = null), done=true. Dans "reply", dis : le JSON est prêt et téléchargeable — réponds « ok » pour passer au CSS.
  * phase 2 (currentReportJson fourni, currentCss absent) : rassemble les infos CSS si manquantes (nom du client, URL du site), puis génère UNIQUEMENT le css (reportJson = currentReportJson inchangé), done=true.
- MODE COMBINÉ, BOUCLE D'ITÉRATION : après la V1 du JSON (phase 1), laisse l'utilisateur itérer librement en langage naturel dans le chat (PAS de boutons/options imposés). Le passage au CSS se fait via le bouton « Passer au CSS » (forcePhase="css") ; tant qu'il n'est pas cliqué, tu ne produis JAMAIS de CSS.
- RAFFINEMENT : si un livrable a déjà été généré (currentCss / currentReportJson fournis) et que l'utilisateur demande une modification en langage naturel (« rends les titres plus gros », « change la couleur principale »…), modifie le livrable existant (currentCss prioritairement si la demande porte sur le design) en conséquence et réponds done=true avec le livrable modifié. Ne recommence JAMAIS les questions ni le questionnaire quand un livrable existe.
- NOUVELLE DEMANDE = repartir de zéro : si l'utilisateur annonce un nouveau client, une nouvelle URL de site ou une nouvelle demande, IGNORE currentCss / currentReportJson (ils appartiennent à une autre demande) et régénère depuis le template de base + la charte du NOUAUVEAU client. Ne mélange jamais la charte d'un ancien client avec celle du nouveau.
"""

_HEADER_ALIASES = {
    "theme": "theme", "thématique": "theme", "thematique": "theme",
    "subtheme": "sub_theme", "sub-theme": "sub_theme", "sous-thématique": "sub_theme", "sous-thematique": "sub_theme", "sous thématique": "sub_theme",
    "category": "category", "categorie": "category", "catégorie": "category",
    "name": "name", "nom": "name", "indicator": "name", "indicateur": "name", "libellé": "name", "libelle": "name",
    "type": "type",
    "parentid": "parent_id", "parent id": "parent_id", "id parent": "parent_id", "idparent": "parent_id",
    "flag": "flag", "na/nm": "flag", "nanm": "flag", "flag na/nm": "flag",
    "exercise": "exercise", "exercice": "exercise", "exercise id": "exercise", "exercice id": "exercise", "exercise name": "exercise",
}



_URL_RE = re.compile(r"https?://[^\s\"'<>)]+")


def fetch_site_brand(url: str) -> dict:
    """Extract the client site's visual identity: title, hex colors and font-families from the
    HTML and its first stylesheets. Best-effort; returns an error field on failure."""
    try:
        # trust_env=False: the container's HTTPS_PROXY points at the internal gateway (for api.mistral.ai);
        # reading a CLIENT site must go direct, not through that proxy.
        with httpx.Client(timeout=10, follow_redirects=True, trust_env=False, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}) as client:
            resp = client.get(url)
            head = resp.text[:5000].lower()
            bot_markers = ("cloudflare", "just a moment", "attention required", "captcha", "datadome", "perimeterx", "akamai", "access denied", "are you a robot", "verify you are human")
            # Only a REAL bot-wall counts as blocked: a bare 403 from an egress proxy is not the site blocking us.
            if resp.status_code in (401, 403, 429) and any(m in head for m in bot_markers):
                return {"url": url, "blocked": True, "status": resp.status_code}
            if resp.status_code >= 400:
                return {"url": url, "error": f"HTTP {resp.status_code} (proxy/egress ?) — page non lisible automatiquement"}
            html = resp.text[:200_000]
            colors = re.findall(r"#[0-9a-fA-F]{6}\b", html)
            fonts = re.findall(r"font-family:\s*([^;}]+)", html)
            for href in re.findall(r'<link[^>]+href=["\']([^"\']+\.css[^"\']*)["\']', html)[:3]:
                css_url = href if href.startswith("http") else str(resp.url.join(href))
                try:
                    css = client.get(css_url).text[:100_000]
                    colors += re.findall(r"#[0-9a-fA-F]{6}\b", css)
                    fonts += re.findall(r"font-family:\s*([^;}]+)", css)
                except Exception as css_err:  # noqa: BLE001  one stylesheet failing must not sink the rest
                    logger.warning("stylesheet fetch failed for %s: %s", css_url, css_err)
                    continue
            title = re.search(r"<title>([^<]+)</title>", html)
            # Dominant colors first (frequency), not alphabetical: the model picks --primary from the top.
            from collections import Counter

            color_counts = Counter(c.lower() for c in colors)
            top_colors = [c for c, _ in color_counts.most_common(16)]
            # Clean font list: strip !important, drop generic/icon fonts, keep distinctive families first.
            font_counts = Counter(f.strip().removesuffix("!important").strip() for f in fonts)
            generic = ("inherit", "icons", "helvetica", "arial", "sans-serif", "serif", "monospace")
            clean_fonts = [
                f
                for f, _ in font_counts.most_common(12)
                if len(f) > 4 and not any(f.lower().startswith(g) or f.lower() == g for g in generic)
            ]
            return {
                "url": str(resp.url),
                "title": title.group(1).strip() if title else "",
                "colors": top_colors,
                "fonts": clean_fonts,
            }
    except Exception as err:  # noqa: BLE001
        logger.warning("site brand fetch failed for %s: %s", url, err)
        return {"url": url, "error": str(err)}


def xlsx_to_csv_text(data: bytes) -> str:
    """Minimal XLSX reader (stdlib only). Parses every sheet (inline strings AND shared strings),
    then returns the sheet whose header row best matches the network-matrix columns."""
    ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
    rns = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
    pkg_rns = "{http://schemas.openxmlformats.org/package/2006/relationships}"
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall(f"{ns}si"):
                shared.append("".join(t.text or "" for t in si.iter(f"{ns}t")))
        # sheet order from workbook.xml + rels
        sheet_files: list[str] = []
        try:
            wb = ET.fromstring(z.read("xl/workbook.xml"))
            rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
            rel_map = {r.get("Id"): r.get("Target") for r in rels.findall(f"{pkg_rns}Relationship")}
            for sh in wb.iter(f"{ns}sheet"):
                target = rel_map.get(sh.get(f"{rns}id"), "")
                if target:
                    sheet_files.append("xl/" + target.lstrip("/") if not target.startswith("xl/") else target)
        except Exception as wb_err:  # noqa: BLE001
            logger.warning("workbook.xml unreadable, falling back to sheet files: %s", wb_err)
        if not sheet_files:
            sheet_files = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))

        def cell_text(c: ET.Element) -> str:
            t = c.get("t")
            if t == "inlineStr":
                return "".join(x.text or "" for x in c.iter(f"{ns}t"))
            v = c.find(f"{ns}v")
            if v is None or v.text is None:
                return ""
            if t == "s":
                idx = int(v.text)
                return shared[idx] if idx < len(shared) else v.text
            return v.text

        best_text, best_score = "", -1
        for sheet_file in sheet_files:
            root = ET.fromstring(z.read(sheet_file))
            lines: list[str] = []
            for row in root.iter(f"{ns}row"):
                cells = [cell_text(c) for c in row.findall(f"{ns}c")]
                lines.append(";".join(cells))
            if not lines:
                continue
            score = sum(1 for h in lines[0].split(";") if h.strip().lower() in _HEADER_ALIASES)
            if score > best_score:
                best_score, best_text = score, "\n".join(lines)
        return best_text


def extract_organization_id(csv_text: str) -> int | None:
    """The network matrix often carries ORGANIZATION ID in its first column."""
    try:
        first = next(csv.reader(io.StringIO(csv_text), delimiter=";"))
    except Exception:  # noqa: BLE001
        return None
    for i, h in enumerate(first):
        if h.strip().lower() in {"organization id", "organisation id", "organization_id", "id organisation", "id orga"}:
            rows = list(csv.reader(io.StringIO(csv_text), delimiter=";"))
            for row in rows[1:]:
                if len(row) > i and row[i].strip().isdigit():
                    return int(row[i])
    return None


def parse_csv_indicators(text: str) -> tuple[list[dict], list[str]]:
    """Parse a network-matrix CSV into indicator dicts; returns (indicators, errors).

    The matrix repeats every indicator once per exercise: only the MOST RECENT exercise's
    row is kept for each indicator (keyed by parentId, else name)."""
    header_line = text.splitlines()[0] if text.splitlines() else ""
    delimiter = max(";\t|,", key=lambda d: header_line.count(d))
    reader = csv.DictReader(io.StringIO(text), delimiter=delimiter)
    if not reader.fieldnames:
        return [], ["CSV sans ligne d'en-tête"]
    mapping = {_HEADER_ALIASES.get((f or "").strip().lower(), (f or "").strip().lower()): f for f in reader.fieldnames}
    best_by_key: dict[tuple, tuple] = {}
    errors: list[str] = []
    for row in reader:
        name = (row.get(mapping.get("name", "")) or "").strip()
        if not name:
            continue
        theme = (row.get(mapping.get("theme", "")) or "Général").strip()
        raw_type = (row.get(mapping.get("type", "")) or "Narratif").strip()
        parent = (row.get(mapping.get("parent_id", "")) or "").strip()
        flag = (row.get(mapping.get("flag", "")) or "").strip().upper()
        exercise_raw = (row.get(mapping.get("exercise", "")) or "").strip()
        try:
            exercise = int(exercise_raw)
        except ValueError:
            exercise = 0
        parent_id = int(parent) if parent.isdigit() else None
        key = (parent_id,) if parent_id is not None else (name,)
        candidate = (
            exercise,
            {
                "theme": theme,
                "subTheme": (row.get(mapping.get("sub_theme", "")) or theme).strip(),
                "category": (row.get(mapping.get("category", "")) or "").strip(),
                "name": name,
                "type": raw_type if raw_type in {"Narratif", "Choix multiple", "Choix simple", "Oui/Non", "Nombre", "Pourcentage"} else "Narratif",
                "parentId": parent_id,
                "flag": flag if flag in {"NA", "NM"} else None,
            },
        )
        if key not in best_by_key or exercise >= best_by_key[key][0]:
            best_by_key[key] = candidate
    indicators = [c[1] for c in best_by_key.values()]
    if not indicators:
        errors.append("Aucune ligne d'indicateur reconnue dans le CSV")
    return indicators, errors


def _parse(data: dict) -> ChatResponse:
    return ChatResponse(
        reply=str(data.get("reply") or ""),
        done=bool(data.get("done")),
        options=[str(o) for o in (data.get("options") or [])],
        awaiting_file=bool(data.get("awaitingFile")),
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
    request_deadline = time.monotonic() + 50  # the gateway times out around 60s
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
        "csvOrganizationId": extract_organization_id(csv_text) if csv_text else None,
        "csvIndicators": indicators[:300],
        "csvIndicatorsTotal": len(indicators),
        "csvIndicatorsTruncated": len(indicators) > 300,
        "csvErrors": csv_errors,
        "messages": [{"role": m.role, "content": m.content} for m in request.messages],
        "currentReportJson": request.report_json,
        "currentCss": request.css,
    }
    data = complete_json(CHAT_SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False), model=CHAT_MODEL, retries=2, fallback=False, image_b64=request.image_b64, deadline=request_deadline)
    response = _parse(data)
    if site_brand and site_brand.get("blocked") and not request.css:
        # Deterministic: the site really is bot-blocked -> ask for a screenshot, with the button.
        response.awaiting_file = True
        if "capture" not in response.reply.lower():
            response.reply += " Le site est protégé contre les bots : envoie une capture d'écran de son site via le bouton « Ajouter un fichier »."
    elif site_brand and site_brand.get("error") and not request.css:
        # Site unreachable from here (egress/proxy): NOT a bot block — offer the screenshot without claiming "blocked".
        response.awaiting_file = True
        if "capture" not in response.reply.lower():
            response.reply += " Je n'ai pas pu lire le site automatiquement depuis l'app : envoie une capture d'écran de son site via le bouton « Ajouter un fichier » et je déduis le design dessus."
    # Last resort: still nothing after the guard rounds -> one forced generation with ML4.
    if not response.done and not response.options and not response.fields and "?" not in response.reply:
        forced = complete_json(
            CHAT_SYSTEM_PROMPT + "\nDERNIER RECOURS : toutes les infos sont là. GÉNÈRE maintenant le livrable complet : done=true + reportJson et/ou css non vide. Aucune question.",
            json.dumps(payload, ensure_ascii=False),
            model=MODEL,
            retries=1,
            image_b64=request.image_b64, deadline=request_deadline,
        )
        forced_response = _parse(forced)
        if forced_response.done and (forced_response.report_json or forced_response.css):
            response.reply = forced_response.reply or response.reply
            response.done = True
            response.report_json = forced_response.report_json or response.report_json
            response.css = forced_response.css or response.css
            response.excluded = forced_response.excluded
            response.notes = forced_response.notes
    # Après chaque CSS produit (V1 ou itération), proposer l'optimisation par Le Chonk.
    if response.done and response.css and request.mode != "structure_only" and "le chonk" not in response.reply.lower():
        response.reply += " Souhaites-tu que j'appelle Le Chonk pour optimiser le CSS ?"
        response.options = ["Oui", "Non"]
    if response.done and (response.report_json or response.css):
        # The turn that produces the deliverable is regenerated with ML4 for quality.
        final = complete_json(
            CHAT_SYSTEM_PROMPT + "\nL'utilisateur a tout fourni : génère maintenant le livrable final complet.",
            json.dumps(payload, ensure_ascii=False),
            model=MODEL,
            retries=1,
            image_b64=request.image_b64, deadline=request_deadline,
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
            response.css = None  # phase 1 : JSON seul
        elif request.force_phase == "css":
            response.report_json = response.report_json or request.report_json  # phase 2 : CSS
        else:
            response.css = None  # itération sur le JSON : on ne touche pas au CSS
    # Guard: done=true but the deliverable for the mode is empty -> one corrective call.
    needs_css = request.mode == "design_only" or (request.mode == "structure_and_design" and request.force_phase == "css")
    needs_json = request.mode != "design_only"
    if response.done and ((needs_css and not response.css) or (needs_json and not response.report_json)):
        corrected = complete_json(
            CHAT_SYSTEM_PROMPT + "\nCORRECTION : ta réponse disait done=true sans livrer de contenu non vide. Produits maintenant le livrable complet demandé (css et/ou reportJson).",
            json.dumps(payload, ensure_ascii=False),
            model=CHAT_MODEL,
            retries=1,
            image_b64=request.image_b64, deadline=request_deadline,
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
        announced = "je vais" in response.reply.lower() or "en cours" in response.reply.lower() or bool(re.search(r"(je g\u00e9n\u00e8re|g\u00e9n\u00e9rer le|je commence|pr\u00eat \u00e0 g\u00e9n\u00e9rer|on y va|je lance)", response.reply, re.IGNORECASE))
        if response.done or response.options or response.fields or ("?" in response.reply and not announced):
            break
        corrected = complete_json(
            CHAT_SYSTEM_PROMPT + "\nCORRECTION : ta dernière réponse annonçait une action sans rien produire. Le CSV est déjà parsé dans csvIndicators. Génère maintenant le livrable demandé (done=true + contenu), ou pose la prochaine question.",
            json.dumps(payload, ensure_ascii=False),
            model=CHAT_MODEL,
            retries=1,
            fallback=False,
            image_b64=request.image_b64, deadline=request_deadline,
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
    if site_brand and site_brand.get("blocked") and not request.css:
        # Deterministic: the site really is bot-blocked -> ask for a screenshot, with the button.
        response.awaiting_file = True
        if "capture" not in response.reply.lower():
            response.reply += " Le site est protégé contre les bots : envoie une capture d'écran de son site via le bouton « Ajouter un fichier »."
    elif site_brand and site_brand.get("error") and not request.css:
        # Site unreachable from here (egress/proxy): NOT a bot block — offer the screenshot without claiming "blocked".
        response.awaiting_file = True
        if "capture" not in response.reply.lower():
            response.reply += " Je n'ai pas pu lire le site automatiquement depuis l'app : envoie une capture d'écran de son site via le bouton « Ajouter un fichier » et je déduis le design dessus."
    # Last resort: still nothing after the guard rounds -> one forced generation with ML4.
    if not response.done and not response.options and not response.fields and "?" not in response.reply:
        forced = complete_json(
            CHAT_SYSTEM_PROMPT + "\nDERNIER RECOURS : toutes les infos sont là. GÉNÈRE maintenant le livrable complet : done=true + reportJson et/ou css non vide. Aucune question.",
            json.dumps(payload, ensure_ascii=False),
            model=MODEL,
            retries=1,
            image_b64=request.image_b64, deadline=request_deadline,
        )
        forced_response = _parse(forced)
        if forced_response.done and (forced_response.report_json or forced_response.css):
            response.reply = forced_response.reply or response.reply
            response.done = True
            response.report_json = forced_response.report_json or response.report_json
            response.css = forced_response.css or response.css
            response.excluded = forced_response.excluded
            response.notes = forced_response.notes
    # Après chaque CSS produit (V1 ou itération), proposer l'optimisation par Le Chonk.
    if response.done and response.css and request.mode != "structure_only" and "le chonk" not in response.reply.lower():
        response.reply += " Souhaites-tu que j'appelle Le Chonk pour optimiser le CSS ?"
        response.options = ["Oui", "Non"]
    if response.done and (response.report_json or response.css):
        client_name = ""
        for m in request.messages:
            if m.role == "user":
                match = re.search(r"clientName\s*:\s*(.+)", m.content, re.IGNORECASE)
                if match:
                    client_name = match.group(1).strip()[:80]
                    break
        if not client_name:
            for m in request.messages:
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
                messages=[{"role": m.role, "content": m.content} for m in request.messages],
            )
            response.history_id = entry["id"]
        except OSError:
            # History is best-effort: never fail the request (and lose the deliverable) over it.
            logger.warning("history save failed", exc_info=True)
    return response
