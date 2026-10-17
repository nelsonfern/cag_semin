"""Control de alcance: preguntas sobre trámites pasan; las ajenas se responden sin el modelo."""

import json

import pytest

from app.cag.engine import QuestionError
from app.services.answer_service import OUT_OF_SCOPE
from app.services.scope import OUT_OF_SCOPE_MESSAGE, ScopeChecker
from tests.fakes import make_service


@pytest.fixture(scope="module")
def scope():
    from app.ingestion.corpus_builder import load_latest
    from app.services.citations import CitationIndex

    text, report = load_latest()
    return ScopeChecker.from_index(CitationIndex.from_corpus(text, report))


def test_all_evaluation_questions_are_in_scope(scope):
    questions = json.load(open("app/evaluation/questions.json", encoding="utf-8"))["questions"]
    assert all(scope.in_scope(q["question"]) for q in questions)


@pytest.mark.parametrize("question", [
    "¿Qué necesito para casarme?", "Se murió mi abuelo, ¿qué tengo que hacer?", "Quiero sacar el pasaporte",
    "¿Dónde saco turno?", "¿Cuánto sale una copia de acta?", "Perdí el documento, ¿qué hago?", "Mi hijo nació ayer",
    "¿Necesito escribano para la unión convivencial?", "¿Cómo saco la licencia de conducir?",
])
def test_procedure_questions_are_in_scope(scope, question):
    assert scope.in_scope(question)


@pytest.mark.parametrize("question", [
    "¿Cómo hago un ciclo for en Python?", "Explicame qué es un bucle while", "Dame una receta de empanadas",
    "¿Quién ganó el mundial 2022?", "Escribime un poema sobre el mar", "hola", "¿Cuál es la capital de Francia?",
    "¿Cómo instalo Windows?", "Traducí esto al inglés", "¿Qué es la inteligencia artificial?",
])
def test_unrelated_questions_are_out_of_scope(scope, question):
    assert not scope.in_scope(question)


def test_out_of_scope_question_does_not_reach_the_model(scope):
    service = make_service(scope=scope)
    a = service.answer("¿Cómo hago un ciclo for en Python?")
    assert a.decision == OUT_OF_SCOPE and a.text == OUT_OF_SCOPE_MESSAGE
    assert service.engine.calls == 0 and a.tokens["output"] == 0


def test_empty_question_is_still_a_question_error(scope):
    with pytest.raises(QuestionError):
        make_service(scope=scope).answer("   ")
