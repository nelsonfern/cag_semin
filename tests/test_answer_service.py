"""Servicio de respuestas: las tres decisiones y lo que se muestra en cada una."""

import pytest

from app.cag.engine import QuestionError
from app.services.answer_service import ABSTAINED, ABSTENTION_MESSAGE, ANSWERED, UNSUPPORTED, decide
from app.services.citations import CitationReport
from tests.fakes import REPLIES, make_service


def test_answer_with_valid_citation_is_shown_with_its_sources():
    a = make_service().answer("partida")
    assert a.decision == ANSWERED
    assert a.text == REPLIES["partida"]
    assert [c.section_id for c in a.citations.citations] == ["rc-partidas#s1"]
    d = a.to_dict()
    assert d["documents"][0]["source_url"] == "https://oficial.example/rc-partidas"
    assert d["tokens"]["output"] == len(REPLIES["partida"]) and d["timings"]["first_token_seconds"] == 0.02


def test_abstention_phrase_gives_the_standard_message():
    a = make_service().answer("licencia")
    assert a.decision == ABSTAINED
    assert a.text == ABSTENTION_MESSAGE and a.raw_text == REPLIES["licencia"]
    assert a.citations.citations == []


def test_answer_without_citations_is_not_shown():
    a = make_service().answer("inventa")
    assert a.decision == UNSUPPORTED
    assert a.text == ABSTENTION_MESSAGE           # lo que ve el ciudadano
    assert a.raw_text == REPLIES["inventa"]        # se conserva para la evaluación
    assert "sin citar" in a.citations.warnings[0]


def test_only_invented_citations_count_as_unsupported():
    a = make_service().answer("inventa-cita")
    assert a.decision == UNSUPPORTED
    assert a.citations.invalid_ids == ["muni#s1"]


def test_tokens_are_forwarded_for_streaming():
    seen = []
    make_service().answer("partida", on_token=seen.append)
    assert "".join(map(chr, seen)) == REPLIES["partida"]


def test_question_errors_propagate():
    with pytest.raises(QuestionError):
        make_service().answer("   ")


@pytest.mark.parametrize("text", [
    "no encontré esa información en los documentos oficiales disponibles",
    "Lo siento.  No   encontré esa información en los documentos oficiales disponibles. Consultá.",
])
def test_abstention_detection_tolerates_case_and_spacing(text):
    assert decide("q", text, CitationReport())[0] == ABSTAINED


def test_uncited_but_literal_answer_is_shown_with_auto_sources():
    replies = {"¿Qué necesito para pedir una partida?":
               "Tenés que presentar el DNI del titular de la partida o de un familiar directo."}
    a = make_service(replies=replies).answer("¿Qué necesito para pedir una partida?")
    assert a.decision == ANSWERED and a.citations.citations[0].auto


def test_abstention_is_not_overridden_by_auto_attribution():
    phrase = "No encontré esa información en los documentos oficiales disponibles."
    replies = {"partida": phrase + " Presentar el DNI del titular de la partida o de un familiar directo."}
    a = make_service(replies=replies).answer("partida")
    # Se verifica igual, pero las citas que asignó el código no anulan la abstención del modelo.
    assert a.decision == ABSTAINED and a.text == ABSTENTION_MESSAGE


def test_displayed_text_drops_citations_that_do_not_support_it():
    q = "¿Qué requisitos tiene el pasaporte de un menor?"
    replies = {q: "Concurrir con el DNI de los padres o tutores legales que acompañen al menor [rc-pasaporte#s1]."}
    a = make_service(replies=replies).answer(q)
    assert a.decision == ANSWERED
    assert "[rc-pasaporte#s1]" not in a.text and "[rc-pasaporte#s1]" in a.raw_text
    assert [c.section_id for c in a.citations.citations] == ["sj-guia#s3"]


def test_unsupported_note_does_not_contradict_discarded_citations():
    a = make_service().answer("inventa-cita")  # citó una sección que no existe
    assert a.decision == UNSUPPORTED
    assert "sin citar" not in a.citations.warnings[0] and "no se pudo comprobar" in a.citations.warnings[0]
    assert any("no existen" in w for w in a.citations.warnings)


def test_abstention_with_an_unverified_citation_is_still_an_abstention():
    # Caso real (Qwen2.5-7B, q14): frase de abstención más una cita que no respalda nada.
    phrase = "No encontré esa información en los documentos oficiales disponibles."
    replies = {"partida": phrase + " Consultá en el sitio oficial del Registro Civil [rc-partidas#s2]."}
    a = make_service(replies=replies).answer("partida")
    assert a.decision == ABSTAINED and a.text == ABSTENTION_MESSAGE
