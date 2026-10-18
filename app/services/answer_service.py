"""Servicio de respuestas: pregunta -> motor CAG -> citas -> decisión final.

Cada respuesta termina en una de tres decisiones:

- ``answered``: el modelo respondió y citó al menos una sección válida del corpus, o el código
  pudo asignarle las citas (la mayoría de las oraciones aparecen en secciones del tema).
- ``abstained``: el modelo dijo que los documentos no responden la pregunta (frase fija).
- ``unsupported``: el modelo respondió pero sin ninguna cita válida. Por decisión del usuario
  (Fase 5), no se muestra ese texto: se responde como una abstención, porque no hay forma de
  comprobar de dónde salió.

El texto generado se conserva siempre en ``raw_text`` para la evaluación, aunque no se muestre.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.cag.prompt import ABSTENTION_PHRASE
from app.services.citations import CitationIndex, CitationReport, keep_only_citations
from app.services.scope import OUT_OF_SCOPE_MESSAGE, ScopeChecker

ANSWERED, ABSTAINED, UNSUPPORTED, OUT_OF_SCOPE = "answered", "abstained", "unsupported", "out_of_scope"

ABSTENTION_MESSAGE = (
    f"{ABSTENTION_PHRASE} Te recomiendo consultar directamente al organismo correspondiente: "
    "el Registro Civil de La Rioja (registrocivil.larioja.gob.ar) para partidas, DNI y pasaporte, "
    "o la Secretaría de Justicia (secretariadejusticia.larioja.gob.ar)."
)
UNSUPPORTED_NOTE = ("El modelo generó una respuesta, pero sin citar ninguna sección de los documentos oficiales, "
                    "así que no se muestra: no se puede comprobar de dónde salió.")
UNVERIFIED_NOTE = ("El modelo generó una respuesta, pero no se pudo comprobar en los documentos oficiales, "
                   "así que no se muestra.")


@dataclass
class Answer:
    """Respuesta lista para la API: texto a mostrar, decisión, fuentes, advertencias y tiempos."""

    question: str
    decision: str
    text: str                       # lo que se muestra al ciudadano
    raw_text: str                   # lo que generó el modelo (para evaluación)
    citations: CitationReport
    timings: dict = field(default_factory=dict)
    tokens: dict = field(default_factory=dict)
    stopped_by: str = ""

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "decision": self.decision,
            "text": self.text,
            "raw_text": self.raw_text,
            **self.citations.to_dict(),
            "timings": self.timings,
            "tokens": self.tokens,
            "stopped_by": self.stopped_by,
        }


def _is_abstention(text: str) -> bool:
    """True si el modelo usó la frase de abstención (tolerando puntuación y mayúsculas)."""
    norm = " ".join(text.lower().split())
    return ABSTENTION_PHRASE.lower().rstrip(".") in norm


def decide(question: str, raw_text: str, citations: CitationReport) -> tuple[str, str]:
    """Decisión y texto a mostrar, a partir de lo generado y de las citas válidas."""
    if _is_abstention(raw_text) and not any(not c.auto for c in citations.citations):
        # Se abstuvo y no citó nada que pasara la verificación (o solo hay citas que asignó el
        # código): se respeta la abstención.
        return ABSTAINED, ABSTENTION_MESSAGE
    if not citations.citations:
        return UNSUPPORTED, ABSTENTION_MESSAGE
    keep = {c.section_id for c in citations.citations}
    # Se quitan las líneas de costo sin respaldo (el motivo queda en las advertencias).
    removed = {item["line"] for item in citations.removed_cost_lines}
    text = "\n".join(line for line in raw_text.splitlines() if line.strip() not in removed)
    return ANSWERED, keep_only_citations(text, keep).strip()


class AnswerService:
    """Une el motor CAG con la validación de citas. No sabe nada de HTTP."""

    def __init__(self, engine, index: CitationIndex, scope: ScopeChecker | None = None):
        self.engine = engine
        self.index = index
        self.scope = scope or ScopeChecker.from_index(index)

    def answer(self, question: str, on_token=None, max_new_tokens: int | None = None) -> Answer:
        """Responde ``question``. ``on_token`` recibe cada token generado (para el streaming).

        Las validaciones de la pregunta (vacía, larga, contexto) las hace el motor y se propagan
        como ``QuestionError`` o ``ContextLimitError``. Una pregunta fuera del alcance de TramitaIA
        (ver ``scope.py``) se responde al instante, sin llamar al modelo.
        """
        start = time.perf_counter()
        self.engine.validate_question(question, max_new_tokens)
        if not self.scope.in_scope(question):
            return Answer(question=question, decision=OUT_OF_SCOPE, text=OUT_OF_SCOPE_MESSAGE, raw_text="",
                          citations=CitationReport(), tokens={"question": 0, "output": 0},
                          timings={"question_seconds": 0.0, "first_token_seconds": 0.0, "generation_seconds": 0.0,
                                   "total_seconds": round(time.perf_counter() - start, 3)},
                          stopped_by="out_of_scope")
        result = self.engine.answer(question, max_new_tokens=max_new_tokens, on_token=on_token)
        # Siempre se verifica, también si el texto trae la frase de abstención: un modelo puede
        # abstenerse y además pegar una cita (que no debe mostrarse sin verificar).
        citations = self.index.review(result.text, question)
        decision, text = decide(question, result.text, citations)
        if decision == UNSUPPORTED:
            # Si citó algo (aunque se haya descartado), el motivo concreto ya está en las advertencias.
            cited = citations.invalid_ids or citations.off_topic_ids or citations.rejected_citations
            citations.warnings.insert(0, UNVERIFIED_NOTE if cited else UNSUPPORTED_NOTE)
        return Answer(
            question=question, decision=decision, text=text, raw_text=result.text, citations=citations,
            timings={
                "question_seconds": round(result.prefill_seconds, 3),
                "first_token_seconds": round(result.ttft_seconds, 3),
                "generation_seconds": round(result.total_seconds, 3),
                "total_seconds": round(time.perf_counter() - start, 3),
            },
            tokens={"question": result.question_tokens, "output": len(result.output_ids)},
            stopped_by=result.stopped_by,
        )
