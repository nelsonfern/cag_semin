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

# Frase exacta de abstención: el servicio de respuestas la detecta en el texto generado.
ABSTENTION_PHRASE = "No encontré esa información en los documentos oficiales disponibles."

# Las reglas van antes y después del corpus. Las dos partes están dentro del prefijo, así que
# se procesan una sola vez (caché KV) y no agregan costo por consulta; repetirlas al final las
# deja cerca de la pregunta, lo que ayuda a un modelo chico a respetarlas.
SYSTEM_INSTRUCTIONS = """Sos TramitaIA, un asistente que explica trámites públicos de la Provincia de La Rioja (Argentina).
Respondés en español rioplatense (usá "vos": "presentá", "tenés", "podés") y SOLO con la información de los documentos oficiales que siguen.
Cada documento empieza con <<<DOCUMENTO id=...>>> y cada sección con su identificador entre corchetes, por ejemplo [rc-pasaporte#s1].

DOCUMENTOS OFICIALES:
"""

SYSTEM_CLOSING = f"""
FIN DE LOS DOCUMENTOS OFICIALES.

Reglas para responder:
1. Usá únicamente los documentos anteriores. No inventes requisitos, costos, plazos, oficinas, teléfonos ni enlaces.
2. Después de cada dato, citá entre corchetes la sección de donde sale, copiando su identificador exacto, por ejemplo [rc-solicitud-partidas#s2].
3. Si los documentos no responden la pregunta, contestá exactamente: "{ABSTENTION_PHRASE}" y recomendá consultar al organismo oficial que corresponda. No agregues información de otras fuentes.
4. Aclarás si la información es provincial (Registro Civil o Secretaría de Justicia de La Rioja) o nacional (RENAPER).
5. Si dos documentos dicen cosas distintas, mostrá las dos versiones con sus citas y aclará que se contradicen.
6. Copiá el costo tal como figura en la sección «Costo» del documento del trámite (un monto, «gratuito», «sin cargo»). Los costos tienen la fecha de su documento: no afirmes que siguen vigentes.
7. No des asesoramiento legal.

8. Respondé breve (no más de 150 palabras) y solo sobre el trámite que se pregunta.

Formato de la respuesta (omití las partes que los documentos no informan):
**Trámite:** nombre del trámite y organismo.
**Requisitos:** lista con viñetas.
**Pasos:** lista numerada.
**Costo:** lo que diga la sección de costo del documento.
**Dónde:** oficina, sitio o modalidad.

EJEMPLO 1
Pregunta: ¿Qué necesito para casarme por civil?
Respuesta:
**Trámite:** Matrimonio, Registro Civil de La Rioja (provincial) [rc-matrimonios#s0].
**Requisitos:**
- DNI original y vigente de ambos contrayentes [rc-matrimonios#s1].
- Actas de nacimiento actualizadas, si corresponde [rc-matrimonios#s1].
- Entre 2 y 4 testigos mayores de edad con DNI original y vigente [rc-matrimonios#s1].
**Pasos:**
1. Pedir turno con dos meses de anticipación en la Oficina de Matrimonio Casa Central [rc-matrimonios#s1].
**Costo:** el documento cita la Ley Impositiva 2024 pero no publica el monto (figura «$??») [rc-matrimonios#s2].

EJEMPLO 2
Pregunta: ¿Cómo renuevo el carnet de la obra social?
Respuesta:
{ABSTENTION_PHRASE} Te recomiendo consultar directamente a tu obra social.
"""


# Qwen3 tiene un modo de razonamiento («thinking») que genera texto oculto antes de responder.
# Se desactiva: alarga mucho la generación en CPU y TramitaIA muestra solo la respuesta. Las
# plantillas que no conocen esta opción (Qwen2.5) la ignoran, así que su prefijo no cambia.
_TEMPLATE_KWARGS = {"enable_thinking": False}


@dataclass
class EncodedPrompt:
    """Un tramo del prompt: el texto y sus IDs de tokens."""

    text: str
    ids: list[int]


def _messages(corpus_text: str, question: str | None = None) -> list[dict]:
    """Mensajes de chat: sistema (instrucciones + corpus) y, si hay, la pregunta del usuario."""
    messages = [{"role": "system", "content": SYSTEM_INSTRUCTIONS + corpus_text + SYSTEM_CLOSING}]
    if question is not None:
        messages.append({"role": "user", "content": question})
    return messages


def build_prefix(tokenizer, corpus_text: str) -> EncodedPrompt:
    """Prefijo que se cachea: plantilla de chat con el mensaje de sistema y el corpus."""
    text = tokenizer.apply_chat_template(_messages(corpus_text), tokenize=False, add_generation_prompt=False, **_TEMPLATE_KWARGS)
    return EncodedPrompt(text=text, ids=tokenizer.encode(text, add_special_tokens=False))


def build_question(tokenizer, corpus_text: str, question: str) -> EncodedPrompt:
    """Sufijo de una pregunta: lo que la plantilla agrega después del prefijo."""
    prefix_text = tokenizer.apply_chat_template(_messages(corpus_text), tokenize=False, add_generation_prompt=False, **_TEMPLATE_KWARGS)
    full_text = tokenizer.apply_chat_template(_messages(corpus_text, question), tokenize=False, add_generation_prompt=True, **_TEMPLATE_KWARGS)
    if not full_text.startswith(prefix_text):
        raise ValueError("La plantilla de chat no produce el prefijo como inicio del prompt completo")
    suffix = full_text[len(prefix_text):]
    return EncodedPrompt(text=suffix, ids=tokenizer.encode(suffix, add_special_tokens=False))


def check_boundary(tokenizer, prefix: EncodedPrompt, question: EncodedPrompt) -> bool:
    """True si tokenizar prefijo y pregunta por separado equivale a tokenizar el texto completo."""
    return tokenizer.encode(prefix.text + question.text, add_special_tokens=False) == prefix.ids + question.ids


# --- Plantillas para llama.cpp (modelos GGUF) -------------------------------------------------
# Con llama.cpp no se usa el tokenizer de Hugging Face: el texto del prompt se arma con la
# plantilla de chat del modelo escrita a mano (son públicas y estables) y lo tokeniza llama.cpp.
# Cada una: (prefijo con el mensaje de sistema, sufijo con la pregunta, token de fin de turno).
CHAT_TEMPLATES = {
    # ChatML de Qwen2.5: la misma que genera su plantilla de Hugging Face con un mensaje de sistema
    # (el prefijo da 15.755 tokens con ambos tokenizers).
    "chatml": ("<|im_start|>system\n{system}<|im_end|>\n",
               "<|im_start|>user\n{question}<|im_end|>\n<|im_start|>assistant\n",
               "<|im_end|>"),
    "llama3": ("<|begin_of_text|><|start_header_id|>system<|end_header_id|>\n\n{system}<|eot_id|>",
               "<|start_header_id|>user<|end_header_id|>\n\n{question}<|eot_id|>"
               "<|start_header_id|>assistant<|end_header_id|>\n\n",
               "<|eot_id|>"),
}


def system_message(corpus_text: str) -> str:
    """Mensaje de sistema completo: instrucciones + corpus + reglas y ejemplos."""
    return SYSTEM_INSTRUCTIONS + corpus_text + SYSTEM_CLOSING


def template_prefix(template: str, corpus_text: str) -> str:
    """Texto del prefijo (lo que se cachea) con una plantilla de ``CHAT_TEMPLATES``."""
    return CHAT_TEMPLATES[template][0].format(system=system_message(corpus_text))


def template_question(template: str, question: str) -> str:
    """Texto del sufijo de una pregunta (turno del usuario + inicio del turno del asistente)."""
    return CHAT_TEMPLATES[template][1].format(question=question)
