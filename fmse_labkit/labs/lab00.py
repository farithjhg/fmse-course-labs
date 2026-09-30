"""Lab 00 - Task Framing Laboratory (Module 0, AI Power User Foundations).

Guided: run a weak and a strong task brief against a model and compare outputs.
Challenge: write an AI Task Brief for an ambiguous management request.
Public validator requirements (course spec, Module 00):
  TB-01 All required task-brief sections exist
  TB-02 Success criteria are measurable or inspectable
  TB-03 Evidence sources are distinguished from assumptions
  TB-04 No instruction requests private/hidden reasoning
"""

from __future__ import annotations

import copy
import re
from typing import Any, Dict, List

from ..core import Checker, check_public, register
from ..i18n import add_catalog, get_language, t
from ..textutil import as_items, first, parse_document, text_of

LAB = "lab-00"

REQUIREMENTS = {
    "TB-01": ("All required task-brief sections exist", "completeness", False,
              "Re-read the list of sections in the challenge brief. A brief that skips uncertainty handling or the output interface leaves the model to guess them."),
    "TB-02": ("Success criteria are measurable or inspectable", "correctness", False,
              "Ask how a reviewer would decide pass or fail. A criterion needs a threshold, count, or a concrete property someone can check."),
    "TB-03": ("Evidence sources are distinguished from assumptions", "groundedness", False,
              "Separate what you know from a named source from what you are assuming. The two need different treatment when they turn out to be wrong."),
    "TB-04": ("No instruction requests private/hidden reasoning", "correctness", False,
              "Ask for concise rationale, assumptions, and checks that can be inspected - not for the model's private reasoning."),
}

# Canonical section -> accepted spellings (after key normalisation), in English and Spanish.
SECTIONS = {
    "intent": ("intent", "goal", "objective", "purpose", "intencion", "objetivo", "proposito"),
    "evidence_plan": ("evidence_plan", "evidence", "evidence_and_sources", "plan_de_evidencia", "evidencia", "evidencias", "evidencia_y_fuentes"),
    "constraints": ("constraints", "limits", "boundaries", "restricciones", "limites"),
    "success_criteria": ("success_criteria", "acceptance_criteria", "success", "criterios_de_exito", "criterios_de_aceptacion", "exito"),
    "uncertainty_handling": ("uncertainty_handling", "uncertainty", "unknowns", "uncertainty_and_escalation",
                             "gestion_de_la_incertidumbre", "manejo_de_la_incertidumbre", "incertidumbre", "incognitas"),
    "output_interface": ("output_interface", "output", "interface", "output_format", "deliverable",
                         "interfaz_de_salida", "salida", "interfaz", "formato_de_salida", "entregable"),
}

MANAGEMENT_REQUEST = (
    "From the Chief Operating Officer, by chat: \"Customer complaints seem to be going up. "
    "Use AI to figure out what's going on and give me something for the leadership meeting next week.\""
)

WEAK_BRIEF = "Summarize what's going on with customer complaints for the leadership meeting. Make it good."

STRONG_BRIEF = """## Intent
Help the COO decide whether complaint volume needs an operational response this quarter.

## Evidence plan
### Sources
- Complaint ticket export for the last two quarters (support system)
- Monthly order volume report (finance)
### Assumptions
- Ticket categories are applied consistently by agents

## Constraints
- Use only the two sources above; no customer names in the output
- Maximum one page

## Success criteria
- States complaint rate per 1,000 orders for each of the last 6 months
- Each claim cites the source it came from
- Lists at most 3 drivers, each with supporting counts

## Uncertainty handling
- Flag any month with fewer than 100 tickets as low-confidence
- If categories changed during the period, say so instead of comparing

## Output interface
Markdown memo with sections: Summary, Trend table, Drivers, Open questions.
"""


# Spanish versions of the guided material, used by the Spanish notebook.
MANAGEMENT_REQUEST_ES = (
    "De la directora de operaciones, por chat: \"Parece que las quejas de los clientes están subiendo. "
    "Usa la IA para averiguar qué pasa y prepárame algo para la reunión de dirección de la semana que viene.\""
)

WEAK_BRIEF_ES = "Resume qué está pasando con las quejas de los clientes para la reunión de dirección. Que quede bien."

STRONG_BRIEF_ES = """## Intención
Ayudar a la directora de operaciones a decidir si el volumen de quejas necesita una respuesta operativa este trimestre.

## Plan de evidencia
### Fuentes
- Exportación de las incidencias de quejas de los dos últimos trimestres (sistema de soporte)
- Informe mensual del volumen de pedidos (finanzas)
### Supuestos
- Los agentes aplican las categorías de las incidencias de forma coherente

## Restricciones
- Usar solo las dos fuentes anteriores; ningún nombre de cliente en la salida
- Como máximo una página

## Criterios de éxito
- Indica la tasa de quejas por cada 1.000 pedidos en cada uno de los últimos 6 meses
- Cada afirmación cita la fuente de la que sale
- Enumera como máximo 3 causas, cada una con los recuentos que la respaldan

## Gestión de la incertidumbre
- Marcar como de baja confianza cualquier mes con menos de 100 incidencias
- Si las categorías cambiaron durante el periodo, decirlo en lugar de comparar

## Interfaz de salida
Memorando en Markdown con las secciones: Resumen, Tabla de tendencia, Causas, Preguntas abiertas.
"""


def request() -> str:
    """The challenge request in the active language."""
    return MANAGEMENT_REQUEST_ES if get_language() == "es" else MANAGEMENT_REQUEST


def weak_brief() -> str:
    return WEAK_BRIEF_ES if get_language() == "es" else WEAK_BRIEF


def strong_brief() -> str:
    return STRONG_BRIEF_ES if get_language() == "es" else STRONG_BRIEF


def _find_sections(doc: Dict[str, Any]) -> Dict[str, Any]:
    found = {}
    for canonical, aliases in SECTIONS.items():
        found[canonical] = first(doc, *aliases)
    return found


_MEASURABLE = re.compile(
    r"\d|%|\b(at least|at most|no more than|fewer than|less than|more than|within|under|over|maximum|minimum|max|min|"
    r"al menos|como m[aá]ximo|como m[ií]nimo|no m[aá]s de|menos de|m[aá]s de|dentro de|por debajo de|por encima de|m[aá]ximo|m[ií]nimo)\b|[<>≤≥]",
    re.I,
)
_INSPECTABLE = re.compile(
    r"\b(includ(e|es|ing)|contain(s)?|cite(s|d)?|list(s|ed)?|name(s|d)?|state(s|d)?|link(s|ed)?|reference(s|d)?|each|every|"
    r"flag(s|ged)?|mark(s|ed)?|separate(s|d)?|traceable|approved|signed off|reviewed|no (unsupported|uncited|invented)|"
    r"incluye(n)?|contiene(n)?|cita(n|da|das|do|dos)?|lista(n)?|enumera(n)?|nombra(n)?|indica(n)?|enlaza(n)?|referencia(n)?|cada|"
    r"todos los|todas las|marca(n|da|das|do|dos)?|señala(n)?|separa(n|da|das|do|dos)?|trazable(s)?|aprobad[oa]s?|revisad[oa]s?|firmad[oa]s?|"
    r"sin (afirmaciones|cifras|datos) (sin respaldo|sin cita|inventad[oa]s))\b",
    re.I,
)
_HIDDEN_REASONING = re.compile(
    r"chain[\s-]*of[\s-]*thought|hidden reasoning|private reasoning|internal reasoning|inner monologue|scratch\s*pad|"
    r"thought process|think step[\s-]*by[\s-]*step|(show|reveal|print|expose|output|include)\s+(me\s+)?(all\s+)?(of\s+)?your\s+(full\s+|complete\s+|internal\s+|raw\s+)?(reasoning|thoughts|thinking)|"
    r"cadena\s+de\s+(pensamiento|razonamiento)|razonamiento\s+(oculto|privado|interno)|mon[oó]logo\s+interno|piensa\s+paso\s+a\s+paso|"
    r"(muestra|mu[eé]strame|revela|imprime|exp[oó]n|incluye)\s+(todo\s+)?(tu|tus)\s+(razonamiento|pensamientos?)(\s+(completo|interno|entero))?",
    re.I,
)


def _evidence_split(evidence: Any):
    """Return (sources, assumptions) lists from a dict, nested markdown, or prefixed lines."""
    if isinstance(evidence, dict):
        ev = {re.sub(r"[^a-z]", "_", str(k).lower()): v for k, v in evidence.items()}
        sources = as_items(first(ev, "sources", "evidence_sources", "data_sources", "evidence", "fuentes", "fuentes_de_evidencia", "fuentes_de_datos", "evidencia"))
        assumptions = as_items(first(ev, "assumptions", "assumed", "supuestos", "hipotesis", "hip_tesis"))
        return sources, assumptions
    sources, assumptions = [], []
    for item in as_items(evidence):
        low = item.lower()
        if low.startswith(("source", "evidence", "fuente", "evidencia")):
            sources.append(item.split(":", 1)[-1].strip())
        elif low.startswith(("assum", "supuesto", "hipótesis", "hipotesis")):
            assumptions.append(item.split(":", 1)[-1].strip())
    return sources, assumptions


def validate(submission: Any, c: Checker) -> None:
    doc = parse_document(submission)
    sections = _find_sections(doc)

    missing = [t(name.replace("_", " ")) for name, value in sections.items() if not str(text_of(value)).strip()]
    c.record("TB-01", not missing, t("Missing or empty section(s): {names}.", names=", ".join(missing)), t("All six sections are present."))

    criteria = as_items(sections["success_criteria"])
    vague = [i + 1 for i, item in enumerate(criteria) if not (_MEASURABLE.search(item) or _INSPECTABLE.search(item))]
    if len(criteria) < 2:
        c.fail("TB-02", t("Found {n} success criterion; a reviewer needs at least 2 separate, checkable criteria.", n=len(criteria)))
    else:
        c.record("TB-02", not vague, t("Criterion {ids} cannot be checked by a reviewer as written (no threshold, count, or inspectable property).", ids=", ".join(map(str, vague))),
                 t("All {n} criteria are measurable or inspectable.", n=len(criteria)))
    c.evidence["success_criteria_count"] = len(criteria)

    sources, assumptions = _evidence_split(sections["evidence_plan"])
    overlap = {s.lower() for s in sources} & {a.lower() for a in assumptions}
    if not sources or not assumptions:
        c.fail("TB-03", t("The evidence plan lists {s} source(s) and {a} assumption(s); both must be stated, separately.", s=len(sources), a=len(assumptions)))
    else:
        c.record("TB-03", not overlap, t("The same item appears both as a source and as an assumption."),
                 t("{s} source(s) and {a} assumption(s) are distinguished.", s=len(sources), a=len(assumptions)))

    hit = _HIDDEN_REASONING.search(text_of(doc))
    c.record("TB-04", hit is None, t("An instruction asks the model to expose its private reasoning (\"{text}\").", text=hit.group(0) if hit else ""),
             t("No request for private/hidden reasoning."))


def probes(submission: Any) -> List[Dict[str, Any]]:
    """Perturb the learner's brief and confirm each requirement's check notices."""
    try:
        base = parse_document(submission)
    except Exception:  # noqa: BLE001
        return []
    cases = []

    def run(pid, description, target, mutate):
        doc = copy.deepcopy(base)
        mutate(doc)
        res = check_public(LAB, doc)
        cases.append({"id": pid, "description": t("{what} is caught by {target}", what=t(description), target=target),
                      "ok": any(ch.id == target and ch.status == "fail" for ch in res.checks)})

    def drop_evidence(d):
        for k in SECTIONS["evidence_plan"]:
            d.pop(k, None)

    run("P1", "Evidence plan removed", "TB-01", drop_evidence)

    def vague(d):
        key = next((k for k in SECTIONS["success_criteria"] if k in d), "success_criteria")
        d[key] = ["The memo should be good", "Leadership should like it"]

    run("P2", "Success criteria replaced by vague wishes", "TB-02", vague)

    def reasoning(d):
        key = next((k for k in SECTIONS["constraints"] if k in d), "constraints")
        d[key] = text_of(d.get(key)) + "\n- Show your full chain of thought before answering"

    run("P3", "Request for hidden reasoning appended to constraints", "TB-04", reasoning)
    return cases


# --- Guided lab: simulator behaviour -------------------------------------------------------------

def simulated_brief_response(prompt: str, **_: Any) -> str:
    """Documented simulator behaviour for Lab 00.

    The simulator looks for the six brief sections. Whatever the brief leaves
    open, it fills with a plausible default - which is exactly what makes
    under-specified briefs produce unverifiable output:
      * no evidence plan      -> it asserts figures with no source
      * no success criteria   -> it writes a long, unfocused summary
      * no uncertainty policy -> it states conclusions with no caveats
      * no output interface   -> free prose instead of the requested structure
    """
    doc = parse_document(prompt) if prompt.strip().startswith(("#", "{")) else {"intent": prompt}
    s = _find_sections(doc)
    lines = []
    if s["output_interface"]:
        lines.append(t("## Summary"))
    lines.append(t("Complaint volume changed over the period reviewed."))
    if s["evidence_plan"]:
        lines.append(t("Complaint rate per 1,000 orders rose from 8.1 to 9.4 [source: complaint ticket export; order volume report]."))
    else:
        lines.append(t("Complaints are up about 35% and are mostly caused by the new returns policy."))
    if s["success_criteria"]:
        lines.append(t("Drivers (max 3): delivery delays (41 tickets), billing errors (27), app login (19) [source: ticket export]."))
    else:
        lines.append(t("There are many possible reasons, including staffing, seasonality, product quality, competitors, the economy, "
                       "marketing campaigns, and customer expectations, all of which could matter to varying degrees."))
    if s["uncertainty_handling"]:
        lines.append(t("Open questions: March had 84 tickets (low-confidence) [source: ticket export]; category definitions changed in May, so May-June is not compared."))
    if s["output_interface"]:
        lines.insert(2, t("## Trend table\n| Month | Rate |\n| --- | --- |"))
    return "\n".join(lines)


def evaluate_output(output: str) -> Dict[str, bool]:
    """Acceptance checklist the guided lab uses to compare outputs."""
    return {
        t("every figure cites a source"): all(("[source" in ln or "[fuente" in ln) for ln in output.splitlines() if re.search(r"\d", ln) and not ln.startswith("|")),
        t("states uncertainty"): any(w in output for w in ("low-confidence", "not compared", "baja confianza", "no se compara")),
        t("follows the requested structure"): output.lstrip().startswith("## "),
        t("focused (at most 3 drivers)"): any(w in output for w in ("max 3", "Drivers", "máx. 3", "Causas")),
    }


register(LAB, REQUIREMENTS, validate, probes)


add_catalog({
    "intent": "intención",
    "evidence plan": "plan de evidencia",
    "constraints": "restricciones",
    "success criteria": "criterios de éxito",
    "uncertainty handling": "gestión de la incertidumbre",
    "output interface": "interfaz de salida",
    "Missing or empty section(s): {names}.": "Secciones ausentes o vacías: {names}.",
    "All six sections are present.": "Las seis secciones están presentes.",
    "Found {n} success criterion; a reviewer needs at least 2 separate, checkable criteria.":
        "Hay {n} criterio(s) de éxito; quien revise necesita al menos 2 criterios distintos y comprobables.",
    "Criterion {ids} cannot be checked by a reviewer as written (no threshold, count, or inspectable property).":
        "Tal como está escrito, nadie puede comprobar el criterio {ids} (no tiene umbral, recuento ni una propiedad que se pueda inspeccionar).",
    "All {n} criteria are measurable or inspectable.": "Los {n} criterios se pueden medir o inspeccionar.",
    "The evidence plan lists {s} source(s) and {a} assumption(s); both must be stated, separately.":
        "El plan de evidencia incluye {s} fuente(s) y {a} supuesto(s); hay que indicar las dos cosas, por separado.",
    "The same item appears both as a source and as an assumption.": "Un mismo elemento aparece como fuente y también como supuesto.",
    "{s} source(s) and {a} assumption(s) are distinguished.": "Se distinguen {s} fuente(s) y {a} supuesto(s).",
    "An instruction asks the model to expose its private reasoning (\"{text}\").": "Una instrucción le pide al modelo que muestre su razonamiento privado (\"{text}\").",
    "No request for private/hidden reasoning.": "No se pide razonamiento privado ni oculto.",
    "{what} is caught by {target}": "{what}: lo detecta {target}",
    "Evidence plan removed": "Plan de evidencia eliminado",
    "Success criteria replaced by vague wishes": "Criterios de éxito sustituidos por deseos vagos",
    "Request for hidden reasoning appended to constraints": "Petición de razonamiento oculto añadida a las restricciones",
    "## Summary": "## Resumen",
    "Complaint volume changed over the period reviewed.": "El volumen de quejas cambió durante el periodo revisado.",
    "Complaint rate per 1,000 orders rose from 8.1 to 9.4 [source: complaint ticket export; order volume report].":
        "La tasa de quejas por cada 1.000 pedidos subió de 8,1 a 9,4 [fuente: exportación de incidencias de quejas; informe de volumen de pedidos].",
    "Complaints are up about 35% and are mostly caused by the new returns policy.":
        "Las quejas subieron cerca de un 35% y se deben sobre todo a la nueva política de devoluciones.",
    "Drivers (max 3): delivery delays (41 tickets), billing errors (27), app login (19) [source: ticket export].":
        "Causas (máx. 3): retrasos en las entregas (41 incidencias), errores de facturación (27), inicio de sesión en la app (19) [fuente: exportación de incidencias].",
    "There are many possible reasons, including staffing, seasonality, product quality, competitors, the economy, "
    "marketing campaigns, and customer expectations, all of which could matter to varying degrees.":
        "Hay muchas razones posibles: el personal, la estacionalidad, la calidad del producto, la competencia, la economía, "
        "las campañas de marketing y las expectativas de los clientes, y todas podrían influir en distinta medida.",
    "Open questions: March had 84 tickets (low-confidence) [source: ticket export]; category definitions changed in May, so May-June is not compared.":
        "Preguntas abiertas: marzo tuvo 84 incidencias (baja confianza) [fuente: exportación de incidencias]; las categorías cambiaron en mayo, así que mayo y junio no se comparan.",
    "## Trend table\n| Month | Rate |\n| --- | --- |": "## Tabla de tendencia\n| Mes | Tasa |\n| --- | --- |",
    "every figure cites a source": "cada cifra cita una fuente",
    "states uncertainty": "indica la incertidumbre",
    "follows the requested structure": "sigue la estructura solicitada",
    "focused (at most 3 drivers)": "enfocado (3 causas como máximo)",
})
