"""Deterministic Editor.js JSON builder for the network matrix.

The JSON STRUCTURE (ids, themes, subthemes, categories, types, NA/NM filter, block layout)
is built only from the parsed CSV — never invented. Only the preview VALUES are faked
(frontend). The chat model only collects the parameters and says when everything is there.
"""

import re
import time
import uuid
from typing import Any

CHART_TYPES = {"barre": "bar", "bar": "bar", "ligne": "line", "line": "line"}


def parse_chat_params(messages: list) -> dict[str, Any]:
    """Extract the questionnaire answers ('key: value' lines) from the user messages."""
    params: dict[str, Any] = {}
    text = "\n".join(m.content for m in messages if getattr(m, "role", "") == "user")
    for line in text.splitlines():
        m = re.match(r"\s*([a-zA-Z ]+?)\s*:\s*(.+)\s*$", line)
        if not m:
            continue
        key = m.group(1).strip().lower().replace(" ", "")
        val = m.group(2).strip()
        if key in {"clientname", "nomduclient", "entreprise", "client"}:
            params["clientName"] = val
        elif key in {"organizationid", "idclient", "idorga"}:
            params["organizationId"] = int(val) if val.isdigit() else None
        elif key in {"networkid", "idréseau", "idreseau"}:
            params["networkId"] = int(val) if val.isdigit() else None
        elif key in {"exerciceidnminus1", "exerciceid", "exerciceidn-1"}:
            params["exerciceIdNMinus1"] = int(val) if val.isdigit() else None
        elif key in {"yearn", "anneen"}:
            params["yearN"] = int(val) if val.isdigit() else 2026
        elif key in {"yearnminus1", "anneen-1"}:
            params["yearNMinus1"] = int(val) if val.isdigit() else 2025
        elif key in {"pastexercices", "exercices", "annees", "nombredexercicespassés"}:
            params["pastExercices"] = int(val) if val.isdigit() else 5
        elif key in {"ratio", "repartition", "répartition"}:
            params["ratio"] = val
        elif key in {"sommaire"}:
            params["sommaire"] = val
        elif key in {"charttype", "typedegraphique", "graphiques"}:
            params["chartType"] = val
        elif key in {"clienturl", "url", "siteduclient"}:
            params["clientUrl"] = val
    return params


def _block_id() -> str:
    return uuid.uuid4().hex[:10]


def build_report_json(
    indicators: list[dict],
    *,
    organization_id: int | None,
    network_id: int | None,
    exercice_id_n_minus_1: int | None,
    year_n: int,
    year_n_minus_1: int,
    past_exercices: int,
    chart_ratio: str,
    sommaire: bool,
    chart_type: str,
    client_name: str,
) -> tuple[dict, list[str]]:
    """Build the full Editor.js report JSON from the parsed matrix. Returns (report, excluded NA/NM names)."""
    kept = [i for i in indicators if i.get("flag") not in {"NA", "NM"}]
    excluded = [i.get("name", "") for i in indicators if i.get("flag") in {"NA", "NM"}]

    m = re.match(r"(\d+)\s*/\s*(\d+)", chart_ratio or "")
    chart_pct = int(m.group(1)) / 100 if m else 0.4
    ct = CHART_TYPES.get((chart_type or "").lower(), "line")

    blocks: list[dict] = []
    blocks.append({"id": _block_id(), "type": "header", "data": {"text": f"Rapport de durabilité {year_n} — {client_name or 'Client'}", "level": 1}})
    if sommaire:
        blocks.append({"id": _block_id(), "type": "table_of_content", "data": {"tableOfContent": {"title": "Sommaire", "level": 4}}})

    # group by theme then subtheme, preserving CSV order
    themes: dict[str, dict[str, list[dict]]] = {}
    for ind in kept:
        themes.setdefault(ind.get("theme") or "Général", {}).setdefault(ind.get("subTheme") or ind.get("theme") or "Général", []).append(ind)

    table_columns = [
        {"type": "IndicatorName", "label": "Indicator"},
        {"type": "LastValue", "label": str(year_n)},
        {"type": "YearXValue", "label": str(year_n_minus_1), "year": year_n_minus_1},
        {
            "type": "Progression",
            "progression": {
                "type": "percent",
                "column1": {"type": "ExerciceXValue", "exerciceId": exercice_id_n_minus_1},
                "column2": {"type": "LastValue"},
            },
        },
    ]

    for theme, subs in themes.items():
        blocks.append({"type": "pageBreak", "data": {}})
        blocks.append({"id": _block_id(), "type": "header", "data": {"text": theme, "level": 2}})
        for sub, inds in subs.items():
            blocks.append({"id": _block_id(), "type": "header", "data": {"text": sub, "level": 3}})
            kpi = [i for i in inds if i.get("type") in {"Nombre", "Pourcentage"}]
            narratifs = [i for i in inds if i.get("type") not in {"Nombre", "Pourcentage"}]
            n_charts = round(len(kpi) * chart_pct)
            chart_inds, table_inds = kpi[:n_charts], kpi[n_charts:] + narratifs
            if chart_inds:
                blocks.append(
                    {
                        "id": _block_id(),
                        "type": "chart",
                        "data": {
                            "organizationId": organization_id,
                            "networkId": network_id,
                            "locale": "fr",
                            "chart": {
                                "chartType": ct,
                                "xAxis": {"label": "date", "type": "Exercice", "relativeStart": {"minusX": past_exercices}, "relativeEnd": {"minusX": 1}},
                                "indicators": [{"type": "IndicatorValue", "indicatorId": int(i["parentId"])} for i in chart_inds if i.get("parentId") is not None],
                            },
                        },
                    }
                )
            for i in narratifs:
                if i.get("parentId") is not None:
                    blocks.append(
                        {
                            "id": _block_id(),
                            "type": "text_indicators",
                            "data": {"organizationId": organization_id, "networkId": network_id, "locale": "fr", "textIndicators": {"indicators": [{"type": "LastValue", "indicatorId": int(i["parentId"])}]}},
                        }
                    )
            for start in range(0, len(table_inds), 6):
                group = table_inds[start : start + 6]
                ids = [str(i["parentId"]) for i in group if i.get("parentId") is not None]
                if not ids:
                    continue
                blocks.append(
                    {
                        "id": _block_id(),
                        "type": "table",
                        "data": {"organizationId": organization_id, "locale": "fr", "networkId": network_id, "table": {"columns": table_columns, "indicatorIds": ids}},
                    }
                )

    return {"time": int(time.time() * 1000), "version": "2.30.5", "blocks": blocks}, excluded
