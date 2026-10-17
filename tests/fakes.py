"""Motor y servicio falsos para probar el servicio de respuestas y la API sin cargar un modelo."""

import threading
import time

from app.cag.engine import ContextLimitError, GenerationResult, QuestionError
from app.services.answer_service import AnswerService
from app.services.citations import CitationIndex
from tests.test_citations import CORPUS, REPORT


class FakeTokenizer:
    """Cada token es un carácter: decodificar es unir los caracteres."""

    def decode(self, ids, skip_special_tokens=True):
        return "".join(chr(i) for i in ids)


class FakeEngine:
    """Devuelve respuestas fijas por pregunta y emite cada carácter como un token."""

    def __init__(self, replies: dict[str, str], delay: float = 0.0):
        self.replies = replies
        self.delay = delay
        self.tokenizer = FakeTokenizer()
        self.max_new_tokens = 256
        self.calls = 0
        self.max_concurrent = 0
        self._active = 0
        self._lock = threading.Lock()

    def validate_question(self, question, max_new_tokens=None):
        if not question.strip():
            raise QuestionError("La pregunta está vacía")
        if question == "contexto":
            raise ContextLimitError("no entra en el contexto")
        return [ord(ch) for ch in question]

    def answer(self, question, max_new_tokens=None, on_token=None):
        if not question.strip():
            raise QuestionError("La pregunta está vacía")
        if question == "contexto":
            raise ContextLimitError("no entra en el contexto")
        if question == "explota":
            raise RuntimeError("falla interna")
        with self._lock:
            self._active += 1
            self.max_concurrent = max(self.max_concurrent, self._active)
            self.calls += 1
        try:
            text = self.replies.get(question, "Respuesta genérica sin citas.")
            ids = [ord(ch) for ch in text]
            for i in ids:
                if on_token:
                    on_token(i)
                if self.delay:
                    time.sleep(self.delay)
            return GenerationResult(question_tokens=len(question), output_ids=ids, text=text,
                                    prefill_seconds=0.01, ttft_seconds=0.02, total_seconds=0.05)
        finally:
            with self._lock:
                self._active -= 1


REPLIES = {
    "partida": "**Trámite:** Solicitud de Partidas.\n**Requisitos:** presentar el DNI del titular de la partida "
               "o de un familiar directo [rc-partidas#s1].",
    "licencia": "No encontré esa información en los documentos oficiales disponibles. Consultá al organismo.",
    "inventa": "La licencia de conducir se tramita en la municipalidad y cuesta 5000 pesos.",
    "inventa-cita": "Se tramita en la municipalidad [muni#s1].",
    "¿Cuándo entregan el DNI exprés?": "El DNI exprés se entrega en 24 horas en las oficinas del RENAPER [nac-dni#s2]. ñ",
}


class AllInScope:
    """Alcance permisivo para los tests que usan preguntas cortas de juguete («partida», «explota»)."""

    def in_scope(self, question):
        return True


def make_service(delay: float = 0.0, replies: dict | None = None, scope=None) -> AnswerService:
    engine = FakeEngine(replies or REPLIES, delay=delay)
    return AnswerService(engine, CitationIndex.from_corpus(CORPUS, REPORT, warnings_file=None),
                         scope=scope or AllInScope())
