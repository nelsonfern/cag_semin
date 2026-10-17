"""Citas verificables construidas desde el registro documental, no desde el texto del modelo.

El modelo solo escribe identificadores de sección entre corchetes, como ``[rc-pasaporte#s1]``.
Este módulo:

1. Extrae esos identificadores y los valida contra el reporte del corpus que generó la caché.
   Los que no existen se descartan y se informan (el modelo pudo inventarlos).
2. Completa cada cita con los metadatos del registro: título, organismo, jurisdicción, URL
   oficial, fecha publicada por el organismo, fecha de obtención y versión. Ninguno de esos
   datos sale del texto generado.
3. Estima si la cita respalda lo que se dijo: compara las palabras de la oración que la contiene
   con las de la sección citada. Es un control grueso (no entiende el significado), pero marca
   citas puestas al azar.
4. Agrega advertencias: costos sin vigencia confirmada, documentos incluidos como extracto,
   diferencias conocidas entre fuentes y mezcla de información provincial y nacional.
5. Filtra por tema: las secciones válidas para una pregunta son las de documentos o
   encabezados que comparten palabras con ella. Las citas del modelo fuera del tema se
   descartan.
6. Verifica el contenido de toda respuesta: la mayoría de sus frases tienen que aparecer casi
   textuales (pares de palabras) en secciones del tema; si no, se descartan todas las citas.
   Si el modelo no citó pero el contenido está respaldado, las citas las asigna el código y
   quedan marcadas como automáticas.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

from app.config import DATA_DIR

WARNINGS_FILE = DATA_DIR / "citation_warnings.json"

# Un corchete puede traer uno o varios identificadores: [rc-pasaporte#s1] o [rc-pasaporte#s1, rc-pasaporte#s2].
BRACKET_RE = re.compile(r"\[([^\[\]\n]{3,200})\]")
SECTION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]*#(?:s\d+|art-\d+)$")
# Marcadores de sección y de documento tal como los escribe corpus_builder.
SECTION_MARK_RE = re.compile(r"^\[([a-z0-9][a-z0-9-]*#(?:s\d+|art-\d+))\]", re.MULTILINE)
DOC_END_RE = re.compile(r"^<<<FIN DOCUMENTO id=[^>]+>>>", re.MULTILINE)

COST_WORDS = ("costo", "arancel", "tasa", "precio", "valor")
WEAK_SUPPORT = 0.25  # menos de un cuarto de las palabras de la oración aparecen en la sección
MIN_WORDS_FOR_SUPPORT = 3

# Asignación automática de citas (cuando el modelo no cita). Se comparan pares de palabras
# consecutivas (bigramas): una frase copiada casi textual de una sección comparte sus pares; una
# inventada con palabras sueltas del corpus («DNI», «original», «fotocopia») no. Umbrales
# provisorios, calibrados con las 8 respuestas largas de la primera evaluación de la Fase 5
# (data/results/phase5_eval_20261017_152910.json): con palabras sueltas se colaba una respuesta
# inventada; con bigramas, no.
AUTO_SUPPORT = 0.4    # una oración se respalda si el 40 % de sus bigramas está en una sección del tema
AUTO_COVERAGE = 0.6   # la respuesta se acepta si al menos el 60 % de sus oraciones quedaron respaldadas
# (con 0,5 se mostraba una respuesta que presentaba la renovación del DNI como «DNI exprés»; las
# respuestas fieles de la segunda evaluación, phase5_eval_20261017_160821.json, tienen 71-90 %).
AUTO_MIN_WORDS = 4
SHORT_SUPPORT = 0.6  # frase corta citada por el modelo: fracción de sus palabras que tiene que haber en la sección

_STOPWORDS = set("""
para como pero porque sobre entre desde hasta donde cuando cual cuales quien quienes este esta estos estas
debe deben puede pueden podes tenes tiene tienen hacer realizar tramite tramites documento documentos
seccion requisitos pasos costo informacion oficial oficiales provincia rioja segun tambien ademas cada
""".split())

# Palabras que no indican el tema de una pregunta (para el filtro de tema y las oraciones).
_TOPIC_STOPWORDS = _STOPWORDS | set("""
que los las del una uno por con sin sus son mas hay ser fue muy ese esa eso nos les
hago hacer necesito necesita debo quiero puedo saco sacar pido pedir obtener tramitar tramito
requisito requisitos tramite tramites documentacion piden pide cuanto cuantos cual cuales
inscribo inscribir inscribe inscripcion solicito solicitar solicitud registrar nuevo nueva
""".split())


def _stems(text: str) -> set[str]:
    """Raíces aproximadas: minúsculas, sin tildes, palabras de 3+ letras recortadas a 5.

    Recortar a 5 letras hace coincidir «rectificar» con «rectificación» o «partida» con
    «partidas» sin un analizador morfológico. Es grueso, pero suficiente para comparar temas.
    """
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return {w[:5] for w in re.findall(r"[a-z0-9]{3,}", text) if w not in _TOPIC_STOPWORDS}


# Raíces (5 letras, sin tildes) de los trámites del corpus, para no mezclar uno con otro.
PROCEDURE_STEMS = {
    "dni": "dni", "pasap": "pasaporte", "parti": "partidas", "acta": "partidas", "actas": "partidas",
    "matri": "matrimonio", "casar": "matrimonio", "defun": "defunción", "falle": "defunción",
    "nacim": "nacimiento", "convi": "unión convivencial", "recti": "rectificación",
}


def _procedures(text: str) -> set[str]:
    """Trámites que nombra un texto (según ``PROCEDURE_STEMS``)."""
    return {PROCEDURE_STEMS[s] for s in _stems(text) if s in PROCEDURE_STEMS}


def _bigrams(text: str) -> set[tuple[str, str]]:
    """Pares de raíces consecutivas (sin palabras vacías), para comparar frases casi textuales."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = [w[:5] for w in re.findall(r"[a-z0-9]{3,}", text) if w not in _TOPIC_STOPWORDS]
    return set(zip(words, words[1:]))


def _answer_sentences(text: str) -> list[str]:
    """Oraciones de una respuesta: por línea y por punto, sin viñetas ni negritas de Markdown.

    La línea «Trámite: <nombre>, <organismo>» que pide el formato del prompt no cuenta: nombra
    el trámite, no afirma ningún dato que haya que respaldar.
    """
    parts = []
    for line in text.splitlines():
        # Primero las negritas («**Requisitos:**») y después las viñetas: al revés, la viñeta
        # «*» se comía un asterisco de la negrita.
        line = re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line.replace("**", "")).strip()
        if re.match(r"(?i)tr[áa]mite\s*:", line):
            continue
        parts.extend(p.strip() for p in re.split(r"(?<=[.;])\s+", line) if p.strip())
    return parts


@dataclass
class DocumentInfo:
    """Metadatos de un documento del corpus, tomados del reporte del build (snapshot del registro)."""

    document_id: str
    title: str
    organism: str
    jurisdiction: str
    source_url: str
    last_updated_date: str | None
    retrieved_at: str | None
    version: int
    is_excerpt: bool


@dataclass
class Citation:
    """Una sección citada y validada, con los metadatos de su documento."""

    section_id: str
    heading: str | None
    document: DocumentInfo
    support: float | None          # fracción de palabras de la oración presentes en la sección
    weak_support: bool
    auto: bool = False             # True si la asignó el código y no el modelo


@dataclass
class CitationReport:
    """Resultado de revisar las citas de una respuesta."""

    citations: list[Citation] = field(default_factory=list)
    invalid_ids: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    off_topic_ids: list[str] = field(default_factory=list)       # existen, pero no son del tema de la pregunta
    rejected_citations: list[str] = field(default_factory=list)  # citas descartadas porque el texto no coincide
    unverified_ids: list[str] = field(default_factory=list)      # citas del modelo que no respaldan ninguna frase
    coverage: float | None = None   # fracción de frases respaldadas por secciones del tema (si se verificó)

    @property
    def documents(self) -> list[DocumentInfo]:
        """Documentos citados, sin repetir, en orden de aparición."""
        seen, docs = set(), []
        for c in self.citations:
            if c.document.document_id not in seen:
                seen.add(c.document.document_id)
                docs.append(c.document)
        return docs

    def to_dict(self) -> dict:
        return {
            "citations": [asdict(c) for c in self.citations],
            "documents": [asdict(d) for d in self.documents],
            "invalid_ids": self.invalid_ids,
            "warnings": self.warnings,
            "off_topic_ids": self.off_topic_ids,
            "rejected_citations": self.rejected_citations,
            "unverified_ids": self.unverified_ids,
            "coverage": self.coverage,
        }


def _normalize_words(text: str) -> set[str]:
    """Palabras de contenido: minúsculas, sin tildes, de 4 letras o más y sin palabras vacías."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return {w for w in re.findall(r"[a-z0-9]{4,}", text) if w not in _STOPWORDS}


def split_sections(corpus_text: str) -> dict[str, str]:
    """Texto de cada sección del corpus, desde su marcador hasta el siguiente marcador o fin de documento."""
    marks = list(SECTION_MARK_RE.finditer(corpus_text))
    ends = [m.start() for m in DOC_END_RE.finditer(corpus_text)]
    sections = {}
    for i, m in enumerate(marks):
        stop = marks[i + 1].start() if i + 1 < len(marks) else len(corpus_text)
        stop = min([e for e in ends if m.end() <= e < stop] + [stop])
        sections[m.group(1)] = corpus_text[m.end():stop].strip()
    return sections


def normalize_id(part: str) -> str:
    """ID de sección sin tildes y en minúsculas: el modelo a veces escribe «rc-rectificación-partidas#s1»."""
    part = unicodedata.normalize("NFKD", part.strip().lower())
    return "".join(ch for ch in part if not unicodedata.combining(ch))


def extract_ids(text: str) -> tuple[list[str], list[str]]:
    """Identificadores con forma de sección (en orden, sin repetir) y textos entre corchetes que no lo son."""
    found, malformed = [], []
    for bracket in BRACKET_RE.finditer(text):
        for part in re.split(r"[,;]", bracket.group(1)):
            part = normalize_id(part)
            if SECTION_ID_RE.match(part):
                if part not in found:
                    found.append(part)
            elif "#" in part:
                malformed.append(part)
    return found, malformed


def _raw_stems(text: str) -> set[str]:
    """Raíces de 5 letras de las palabras de 4+ letras, sin quitar palabras de trámite («costo»)."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return {w[:5] for w in re.findall(r"[a-z0-9]{4,}", text)}


def keep_only_citations(text: str, keep: set[str]) -> str:
    """Quita del texto las citas que no están en ``keep`` (y los corchetes que quedan vacíos).

    Así las citas en línea que ve el ciudadano coinciden con el panel de fuentes: no quedan
    referencias inventadas, fuera de tema o que no respaldan lo que dice la frase.
    """
    def fix(match: re.Match) -> str:
        parts = [normalize_id(p) for p in re.split(r"[,;]", match.group(1))]
        if not any(SECTION_ID_RE.match(p) for p in parts):
            return match.group(0)  # corchete que no es una cita: se deja como está
        kept = [p for p in parts if p in keep]
        return f"[{', '.join(kept)}]" if kept else ""

    text = BRACKET_RE.sub(fix, text)
    return re.sub(r"[ \t]+([.,;:])", r"\1", text)  # espacio que quedó antes de la puntuación


def _sentence_with(text: str, start: int) -> str:
    """La oración o línea que termina en la posición de una cita (lo que la cita respalda)."""
    begin = max(text.rfind("\n", 0, start), text.rfind(". ", 0, start))
    return text[begin + 1:start]


class CitationIndex:
    """Índice de secciones y documentos del corpus que está en la caché."""

    def __init__(self, documents: dict[str, DocumentInfo], sections: dict[str, tuple[str, str | None, str]],
                 doc_warnings: dict[str, str] | None = None, pair_warnings: list[dict] | None = None):
        self.documents = documents
        self.sections = sections  # section_id -> (document_id, heading, texto)
        self.doc_warnings = doc_warnings or {}
        self.pair_warnings = pair_warnings or []
        # Raíces precalculadas: del contenido (para respaldar oraciones) y del tema (título del
        # documento + encabezado de la sección, para el filtro de tema).
        self._content_stems = {sid: _stems(text) for sid, (_, _, text) in sections.items()}
        self._content_bigrams = {sid: _bigrams(text) for sid, (_, _, text) in sections.items()}
        self._topic_stems = {
            sid: _stems(f"{documents[doc_id].title} {heading or ''}") for sid, (doc_id, heading, _) in sections.items()
        }
        # Trámite de cada sección. En un documento que reúne varios trámites (el nacional de DNI y
        # pasaporte, la guía de Justicia) el título los nombra a todos, así que el trámite de cada
        # sección sale solo de su encabezado.
        headings_by_doc: dict[str, set[str]] = {}
        for doc_id, heading, _ in sections.values():
            headings_by_doc.setdefault(doc_id, set()).update(_procedures(heading or ""))
        self.multi_procedure_docs = {
            doc_id for doc_id, doc in documents.items()
            if len(_procedures(doc.title) | headings_by_doc.get(doc_id, set())) >= 2
        }
        self._section_procedures = {
            sid: _procedures(heading or "") if doc_id in self.multi_procedure_docs
            else _procedures(f"{documents[doc_id].title} {heading or ''}")
            for sid, (doc_id, heading, _) in sections.items()
        }

    @classmethod
    def from_corpus(cls, corpus_text: str, report: dict, warnings_file: Path | None = WARNINGS_FILE) -> "CitationIndex":
        """Arma el índice con el texto y el reporte del build (los mismos que generaron la caché)."""
        texts = split_sections(corpus_text)
        documents, sections = {}, {}
        for doc in report["documents"]:
            if not doc.get("included"):
                continue
            statuses = {s["status"] for s in doc["sections"]}
            documents[doc["document_id"]] = DocumentInfo(
                document_id=doc["document_id"], title=doc["title"], organism=doc["organism"],
                jurisdiction=doc["jurisdiction"], source_url=doc["source_url"],
                last_updated_date=doc.get("last_updated_date"), retrieved_at=doc.get("retrieved_at"),
                version=doc["version"], is_excerpt=statuses != {"included"},
            )
            for s in doc["sections"]:
                if s["status"] == "included" and s["section_id"] in texts:
                    sections[s["section_id"]] = (doc["document_id"], s.get("heading"), texts[s["section_id"]])
        doc_warnings, pair_warnings = {}, []
        if warnings_file and warnings_file.exists():
            data = json.loads(warnings_file.read_text(encoding="utf-8"))
            doc_warnings, pair_warnings = data.get("documents", {}), data.get("pairs", [])
        return cls(documents, sections, doc_warnings, pair_warnings)

    def support(self, sentence: str, section_id: str) -> float | None:
        """Fracción de las palabras de contenido de ``sentence`` que aparecen en la sección citada."""
        words = _normalize_words(sentence)
        if len(words) < MIN_WORDS_FOR_SUPPORT:
            return None  # muy poco texto para juzgar (por ejemplo, la cita sola en una línea)
        section_words = _normalize_words(self.sections[section_id][2])
        return round(len(words & section_words) / len(words), 3)

    def topic_sections(self, question: str) -> list[str]:
        """Secciones del tema de la pregunta.

        Una sección es del tema si su documento o su encabezado comparten alguna palabra con la
        pregunta, **salvo** que la pregunta nombre un trámite y la sección trate de otro distinto
        (por ejemplo, una pregunta sobre pasaporte y la sección «DNI Nuevo ejemplar menor»).
        """
        q = _stems(question)
        q_procedures = _procedures(question)

        def same_procedure(sid: str) -> bool:
            own = self._section_procedures[sid]
            return not q_procedures or not own or bool(q_procedures & own)

        return [sid for sid, topic in self._topic_stems.items() if q & topic and same_procedure(sid)]

    def attribute(self, answer_text: str, question: str,
                  preferred: set[str] | None = None) -> tuple[list[Citation], float, int]:
        """Asigna a cada oración la sección del tema que mejor la respalda (por bigramas).

        Devuelve las citas (una por sección, en orden de aparición), la fracción de oraciones
        respaldadas y la cantidad de oraciones evaluadas. Las oraciones con menos de
        ``AUTO_MIN_WORDS`` palabras de contenido (títulos como «Requisitos:») no cuentan.

        Hay textos repetidos en varias secciones (por ejemplo, la acreditación del representante
        legal figura igual en el DNI exprés y en el pasaporte de menores). Ante un empate gana la
        sección cuyo encabezado comparte más palabras con la pregunta y, después, una de las
        ``preferred`` (las que citó el modelo).
        """
        preferred = preferred or set()
        q_stems = _stems(question)
        candidates = self.topic_sections(question)
        topic_score = {sid: len(q_stems & self._topic_stems[sid]) for sid in candidates}
        sentences = [s for s in _answer_sentences(answer_text) if len(_stems(s)) >= AUTO_MIN_WORDS]
        if not candidates or not sentences:
            return [], 0.0, len(sentences)
        chosen: dict[str, float] = {}
        supported = 0
        for sentence in sentences:
            pairs = _bigrams(sentence)
            if not pairs:
                continue
            best_sid, best = max(((sid, len(pairs & self._content_bigrams[sid]) / len(pairs)) for sid in candidates),
                                 key=lambda x: (x[1], topic_score[x[0]], x[0] in preferred))
            if best >= AUTO_SUPPORT:
                supported += 1
                chosen[best_sid] = max(chosen.get(best_sid, 0.0), best)
        citations = [
            Citation(section_id=sid, heading=self.sections[sid][1], document=self.documents[self.sections[sid][0]],
                     support=round(score, 3), weak_support=False, auto=True)
            for sid, score in chosen.items()
        ]
        return citations, round(supported / len(sentences), 3), len(sentences)

    def review(self, answer_text: str, question: str | None = None) -> CitationReport:
        """Valida las citas de una respuesta y arma la lista de fuentes y advertencias.

        Sin ``question`` solo valida que las citas existan. Con ``question`` (lo que usa el
        servicio) además:

        1. Descarta las citas del modelo a secciones fuera del tema de la pregunta: un modelo
           chico tiende a pegar una sección real cualquiera a un trámite inventado.
        2. Verifica el contenido: al menos ``AUTO_COVERAGE`` de las frases tienen que aparecer
           casi textuales (bigramas) en secciones del tema. Si no, se descartan todas las citas
           y la respuesta queda sin respaldo, aunque el modelo haya citado.
        3. Si el contenido está respaldado, **las fuentes que se muestran son las secciones que
           respaldan las frases**, no las que eligió el modelo: el modelo a veces copia el texto
           de un documento y cita otro. Las citas del modelo que no respaldan ninguna frase se
           informan en ``unverified_ids`` (y el servicio las quita del texto que se muestra).
        """
        report = CitationReport()
        ids, malformed = extract_ids(answer_text)
        report.invalid_ids.extend(malformed)
        topic = set(self.topic_sections(question)) if question else None
        short_scores: dict[str, float] = {}  # cita del modelo -> palabras de su frase presentes en la sección
        for section_id in ids:
            if section_id not in self.sections:
                report.invalid_ids.append(section_id)
                continue
            if topic is not None and section_id not in topic:
                report.off_topic_ids.append(section_id)
                continue
            doc_id, heading, section_text = self.sections[section_id]
            pos = answer_text.find(section_id)
            sentence = _sentence_with(answer_text, pos)
            score = self.support(sentence, section_id)
            words = _raw_stems(re.sub(r"(?i)^\W*\w+\s*:\s*", "", sentence.replace("**", "")))
            if words:
                short_scores[section_id] = max(short_scores.get(section_id, 0.0),
                                               len(words & _raw_stems(section_text)) / len(words))
            report.citations.append(Citation(
                section_id=section_id, heading=heading, document=self.documents[doc_id],
                support=score, weak_support=score is not None and score < WEAK_SUPPORT,
            ))
        if question:
            model_ids = [c.section_id for c in report.citations]
            supporting, coverage, _ = self.attribute(answer_text, question, preferred=set(model_ids))
            report.coverage = coverage
            if coverage < AUTO_COVERAGE:
                report.rejected_citations = model_ids
                report.citations = []
            else:
                supporting_ids = {c.section_id for c in supporting}
                for c in supporting:
                    c.auto = c.section_id not in model_ids  # True: el modelo no la había citado
                # Las frases cortas («Costo: gratuito») no entran en la verificación por bigramas.
                # Una cita del modelo en una frase así se acepta si sus palabras están en la
                # sección citada (antes se descartaba, aunque fuera la sección correcta).
                short_ok = [c for c in report.citations
                            if c.section_id not in supporting_ids and short_scores.get(c.section_id, 0.0) >= SHORT_SUPPORT]
                report.unverified_ids = [sid for sid in model_ids
                                         if sid not in supporting_ids and sid not in {c.section_id for c in short_ok}]
                report.citations = supporting + short_ok
        report.warnings = self._warnings(report)
        if report.citations and report.coverage is not None:
            pct = round(100 * report.coverage)
            report.warnings.insert(0, "Las fuentes se identificaron comparando cada frase de la respuesta con los "
                                      f"documentos oficiales ({pct} % de las frases coinciden). Es un control "
                                      "automático: confirmá los datos en la fuente oficial.")
        return report

    def _warnings(self, report: CitationReport) -> list[str]:
        warnings = []
        cited_docs = {c.document.document_id for c in report.citations}
        for c in report.citations:
            heading = (c.heading or "").lower()
            if any(w in heading for w in COST_WORDS) or c.document.document_id.startswith("ley-"):
                date = c.document.last_updated_date or "sin fecha publicada"
                msg = (f"Los costos salen de «{c.document.title}» ({date}; obtenido el "
                       f"{(c.document.retrieved_at or '')[:10]}). No se pudo confirmar que sigan vigentes.")
                if msg not in warnings:
                    warnings.append(msg)
        for doc in report.documents:
            if doc.is_excerpt:
                warnings.append(f"«{doc.title}» está incluido solo en parte (extracto): puede haber información "
                                "que TramitaIA no tiene.")
            if doc.document_id in self.doc_warnings:
                warnings.append(self.doc_warnings[doc.document_id])
        for pair in self.pair_warnings:
            if set(pair["documents"]) <= cited_docs:
                warnings.append(pair["message"])
        jurisdictions = {d.jurisdiction for d in report.documents}
        if {"provincial", "nacional"} <= jurisdictions:
            warnings.append("La respuesta combina información provincial (La Rioja) y nacional (RENAPER).")
        weak = [c.section_id for c in report.citations if c.weak_support]
        if weak:
            warnings.append("Algunas citas no coinciden bien con el texto de la respuesta: "
                            f"{', '.join(weak)}. Revisá la fuente.")
        if report.off_topic_ids:
            warnings.append("Se descartaron citas a documentos que no tratan el tema de la pregunta: "
                            f"{', '.join(report.off_topic_ids)}.")
        if report.unverified_ids:
            warnings.append("El modelo citó secciones que no respaldan el texto "
                            f"({', '.join(report.unverified_ids)}): se muestran las que sí lo respaldan.")
        if report.rejected_citations:
            warnings.append("El texto generado no coincide con los documentos citados "
                            f"({', '.join(report.rejected_citations)}), así que no se muestra.")
        if report.invalid_ids:
            warnings.append("Se descartaron referencias que no existen en los documentos: "
                            f"{', '.join(report.invalid_ids)}.")
        return warnings
