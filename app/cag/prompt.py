"""Armado del prefijo documental (lo que se cachea) y de cada pregunta (lo que se agrega).

La entrada del modelo se divide en dos partes:

    [ prefijo: plantilla de chat + instrucciones + corpus ]  -> se procesa UNA vez (caché KV)
    [ sufijo: turno del usuario con la pregunta + inicio del turno del asistente ] -> por consulta

Prefijo y sufijo se tokenizan por separado y se concatenan los IDs. Así, los tokens que el
modelo ve en cada consulta son exactamente los que generaron la caché, más los de la pregunta.
``check_boundary`` comprueba además que esa concatenación coincide con tokenizar el texto
completo (que no haya un token que "cruce" la unión).
"""

from __future__ import annotations

from dataclasses import dataclass

# Prompt de sistema provisional para la Fase 3. La versión definitiva (citas, abstención,
# contradicciones) se completa en la Fase 5.
SYSTEM_INSTRUCTIONS = """Sos TramitaIA, un asistente que explica trámites públicos de la Provincia de La Rioja (Argentina).
Respondé en español rioplatense usando ÚNICAMENTE los documentos oficiales que siguen.
- No inventes requisitos, costos, plazos ni oficinas.
- Distinguí la información provincial de la nacional.
- Si los documentos no alcanzan para responder, decilo y recomendá consultar al organismo oficial.
- Si dos documentos se contradicen, señalalo.
- Indicá entre corchetes el identificador de la sección que respalda cada dato, por ejemplo [rc-pasaporte#s1].

DOCUMENTOS OFICIALES:
"""


@dataclass
class EncodedPrompt:
    """Un tramo del prompt: el texto y sus IDs de tokens."""

    text: str
    ids: list[int]


def _messages(corpus_text: str, question: str | None = None) -> list[dict]:
    """Mensajes de chat: sistema (instrucciones + corpus) y, si hay, la pregunta del usuario."""
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTIONS + corpus_text}]
    if question is not None:
        messages.append({"role": "user", "content": question})
    return messages


def build_prefix(tokenizer, corpus_text: str) -> EncodedPrompt:
    """Prefijo que se cachea: plantilla de chat con el mensaje de sistema y el corpus."""
    text = tokenizer.apply_chat_template(_messages(corpus_text), tokenize=False, add_generation_prompt=False)
    return EncodedPrompt(text=text, ids=tokenizer.encode(text, add_special_tokens=False))


def build_question(tokenizer, corpus_text: str, question: str) -> EncodedPrompt:
    """Sufijo de una pregunta: lo que la plantilla agrega después del prefijo."""
    prefix_text = tokenizer.apply_chat_template(_messages(corpus_text), tokenize=False, add_generation_prompt=False)
    full_text = tokenizer.apply_chat_template(_messages(corpus_text, question), tokenize=False, add_generation_prompt=True)
    if not full_text.startswith(prefix_text):
        raise ValueError("La plantilla de chat no produce el prefijo como inicio del prompt completo")
    suffix = full_text[len(prefix_text):]
    return EncodedPrompt(text=suffix, ids=tokenizer.encode(suffix, add_special_tokens=False))


def check_boundary(tokenizer, prefix: EncodedPrompt, question: EncodedPrompt) -> bool:
    """True si tokenizar prefijo y pregunta por separado equivale a tokenizar el texto completo."""
    return tokenizer.encode(prefix.text + question.text, add_special_tokens=False) == prefix.ids + question.ids
