"""Citas: extracción, validación contra el registro, respaldo y advertencias."""

import json

import pytest

from app.services.citations import CitationIndex, extract_ids, split_sections

CORPUS = """<<<DOCUMENTO id=rc-partidas>>>
Título: Solicitud de Partidas
Organismo: Registro Civil de La Rioja

[rc-partidas#s0]
# Solicitud de Partidas
Este trámite permite pedir copias de partidas de nacimiento, matrimonio y defunción.

[rc-partidas#s1] Requisitos
Presentar el DNI del titular de la partida o de un familiar directo.

[rc-partidas#s2] Costo
La partida digital cuesta 1500 pesos según la ley impositiva.

<<<FIN DOCUMENTO id=rc-partidas>>>

<<<DOCUMENTO id=sj-guia>>>
[sj-guia#s3] Pasaporte de menores
Concurrir con el DNI de los padres o tutores legales que acompañen al menor.

<<<FIN DOCUMENTO id=sj-guia>>>

<<<DOCUMENTO id=rc-pasaporte>>>
[rc-pasaporte#s1] Requisitos
Presencia de ambos progenitores o tutor legal del menor.

<<<FIN DOCUMENTO id=rc-pasaporte>>>

<<<DOCUMENTO id=nac-dni>>>
[nac-dni#s2] DNI exprés
El DNI exprés se entrega en 24 horas en las oficinas del RENAPER.

<<<FIN DOCUMENTO id=nac-dni>>>

<<<DOCUMENTO id=ley-imp>>>
Extracto: solo se incluyen las secciones art-39.

[ley-imp#art-39]
ARTÍCULO 39º Por los servicios del Registro Civil se abonarán las tasas siguientes.

<<<FIN DOCUMENTO id=ley-imp>>>
"""


def _doc(doc_id, title, jurisdiction, sections, excluded=0, updated="2025-10-20"):
    secs = [{"section_id": sid, "heading": h, "status": "included"} for sid, h in sections]
    secs += [{"section_id": f"{doc_id}#x{i}", "heading": None, "status": "excluded_by_selection"} for i in range(excluded)]
    return {"document_id": doc_id, "title": title, "organism": "Organismo " + doc_id, "jurisdiction": jurisdiction,
            "source_url": f"https://oficial.example/{doc_id}", "last_updated_date": updated,
            "retrieved_at": "2026-10-16T18:29:55+00:00", "version": 2, "included": True, "sections": secs}


REPORT = {"documents": [
    _doc("rc-partidas", "Solicitud de Partidas", "provincial",
         [("rc-partidas#s0", None), ("rc-partidas#s1", "Requisitos"), ("rc-partidas#s2", "Costo")]),
    _doc("sj-guia", "Guía de trámites", "provincial", [("sj-guia#s3", "Pasaporte de menores")], updated=None),
    _doc("rc-pasaporte", "Pasaporte", "provincial", [("rc-pasaporte#s1", "Requisitos")]),
    _doc("nac-dni", "Requisitos DNI", "nacional", [("nac-dni#s2", "DNI exprés")], excluded=3, updated="2023-07-18"),
    _doc("ley-imp", "Ley Impositiva", "provincial", [("ley-imp#art-39", None)], excluded=5, updated=None),
    {**_doc("excluido", "Excluido", "provincial", [("excluido#s0", None)]), "included": False},
]}


@pytest.fixture()
def index(tmp_path):
    warnings = tmp_path / "warnings.json"
    warnings.write_text(json.dumps({
        "documents": {"rc-partidas": "Los costos de partidas no coinciden con la ley."},
        "pairs": [{"documents": ["rc-pasaporte", "sj-guia"], "message": "Las fuentes difieren sobre menores."}],
    }), encoding="utf-8")
    return CitationIndex.from_corpus(CORPUS, REPORT, warnings)


def test_split_sections_stops_at_next_marker_and_document_end():
    sections = split_sections(CORPUS)
    assert sections["rc-partidas#s1"].startswith("Requisitos\nPresentar el DNI")
    assert "Costo" not in sections["rc-partidas#s1"]
    assert sections["rc-partidas#s2"].endswith("ley impositiva.")  # sin la marca de fin de documento
    assert "FIN DOCUMENTO" not in sections["ley-imp#art-39"]
    assert len(sections) == 7


def test_extract_ids_handles_lists_and_ignores_other_brackets():
    ids, malformed = extract_ids("Dato [rc-partidas#s1]. Otro [rc-partidas#s1, nac-dni#s2]; nota [ver abajo] "
                                 "y [rc-partidas#s1] repetido. Raro [rc-partidas#seccion1].")
    assert ids == ["rc-partidas#s1", "nac-dni#s2"]
    assert malformed == ["rc-partidas#seccion1"]


def test_valid_citations_take_metadata_from_the_registry(index):
    report = index.review("Tenés que presentar el DNI del titular de la partida o de un familiar directo [rc-partidas#s1].")
    assert [c.section_id for c in report.citations] == ["rc-partidas#s1"]
    c = report.citations[0]
    assert c.document.source_url == "https://oficial.example/rc-partidas"
    assert c.document.organism == "Organismo rc-partidas" and c.heading == "Requisitos"
    assert c.support >= 0.5 and not c.weak_support
    assert report.invalid_ids == []


def test_invented_ids_are_discarded_and_reported(index):
    report = index.review("Hay que ir al registro [rc-partidas#s9] y pagar [inventado#s1].")
    assert report.citations == []
    assert report.invalid_ids == ["rc-partidas#s9", "inventado#s1"]
    assert any("no existen" in w for w in report.warnings)


def test_sections_of_excluded_documents_are_not_citable(index):
    assert index.review("Algo [excluido#s0].").invalid_ids == ["excluido#s0"]


def test_unrelated_sentence_is_flagged_as_weak_support(index):
    report = index.review("El trámite de licencia de conducir requiere examen psicofísico teórico [rc-partidas#s1].")
    assert report.citations[0].weak_support
    assert any("no coinciden bien" in w for w in report.warnings)


def test_short_sentence_is_not_judged(index):
    report = index.review("Requisitos:\n[rc-partidas#s1]")
    assert report.citations[0].support is None and not report.citations[0].weak_support


def test_cost_warning_includes_document_date(index):
    report = index.review("La partida digital cuesta 1500 pesos [rc-partidas#s2].")
    assert any("No se pudo confirmar que sigan vigentes" in w and "2025-10-20" in w for w in report.warnings)
    assert "Los costos de partidas no coinciden con la ley." in report.warnings  # advertencia curada


def test_law_and_excerpt_warnings(index):
    report = index.review("Por los servicios del Registro Civil se abonan tasas [ley-imp#art-39].")
    assert any("sigan vigentes" in w for w in report.warnings)
    assert any("extracto" in w and "Ley Impositiva" in w for w in report.warnings)


def test_known_contradiction_needs_both_documents(index):
    one = index.review("Presencia de ambos progenitores del menor [rc-pasaporte#s1].")
    assert "Las fuentes difieren sobre menores." not in one.warnings
    both = index.review("Presencia de ambos progenitores [rc-pasaporte#s1]. DNI de los padres que acompañen [sj-guia#s3].")
    assert "Las fuentes difieren sobre menores." in both.warnings


def test_mixed_jurisdictions_are_flagged(index):
    report = index.review("Presentá el DNI del titular [rc-partidas#s1]. El DNI exprés se entrega en 24 horas [nac-dni#s2].")
    assert any("provincial" in w and "nacional" in w for w in report.warnings)
    assert [d.document_id for d in report.documents] == ["rc-partidas", "nac-dni"]


def test_real_corpus_sections_are_all_indexed():
    from app.ingestion.corpus_builder import load_latest

    text, report = load_latest()
    index = CitationIndex.from_corpus(text, report)
    included = [s["section_id"] for d in report["documents"] if d["included"]
                for s in d["sections"] if s["status"] == "included"]
    assert len(index.sections) == len(included) == 82
    assert all(index.sections[sid][2] for sid in included)  # ninguna sección vacía
    assert "ley-10702-impositiva-2024#art-39" in index.sections


# --- Asignación automática de citas ---------------------------------------------------------

def test_auto_attribution_when_the_model_does_not_cite(index):
    answer = ("**Requisitos:**\n- Presentar el DNI del titular de la partida o de un familiar directo.\n"
              "- La partida digital cuesta 1500 pesos según la ley impositiva.")
    report = index.review(answer, question="¿Qué necesito para pedir una partida?")
    assert [c.section_id for c in report.citations] == ["rc-partidas#s1", "rc-partidas#s2"]
    assert all(c.auto for c in report.citations) and report.coverage == 1.0
    assert "identificaron comparando cada frase" in report.warnings[0]


def test_no_verification_without_question(index):
    report = index.review("Presentar el DNI del titular de la partida o de un familiar directo.")
    assert report.citations == [] and report.coverage is None
    # Sin pregunta solo se valida que las citas existan (lo usan los tests de formato).
    assert index.review("Algo [rc-pasaporte#s1].").citations[0].section_id == "rc-pasaporte#s1"


def test_topic_filter_blocks_text_copied_from_another_procedure(index):
    # Texto literal del pasaporte, pero la pregunta es sobre partidas: no se acepta.
    report = index.review("Presencia de ambos progenitores o tutor legal del menor.",
                          question="¿Cómo pido una partida?")
    assert report.citations == [] and report.coverage == 0.0


def test_question_without_topic_match_gets_no_candidates(index):
    assert index.topic_sections("¿Cómo saco la licencia de conducir?") == []


def test_generic_words_without_matching_phrases_are_not_enough(index):
    # Mismas palabras sueltas que la sección, pero en otro orden: no hay bigramas en común.
    report = index.review("DNI presentar, directo familiar o partida titular.",
                          question="¿Qué necesito para pedir una partida?")
    assert report.citations == []


def test_low_coverage_answer_is_rejected(index):
    answer = ("Presentar el DNI del titular de la partida o de un familiar directo.\n"
              "La oficina atiende los sábados de nueve a doce en la terminal de ómnibus.\n"
              "Hay que llevar dos fotos carnet color con fondo celeste.")
    report = index.review(answer, question="¿Qué necesito para pedir una partida?")
    assert report.citations == [] and report.coverage == pytest.approx(1 / 3, abs=0.001)


def test_model_citations_take_precedence_over_auto(index):
    report = index.review("Presencia de ambos progenitores o tutor legal del menor [rc-pasaporte#s1].",
                          question="¿Qué requisitos tiene el pasaporte de un menor?")
    assert [c.section_id for c in report.citations] == ["rc-pasaporte#s1"]
    assert not report.citations[0].auto and report.coverage == 1.0


def test_model_citation_outside_the_topic_is_discarded(index):
    # Caso real (q10): trámite inventado con una cita a una sección que existe pero de otro tema.
    report = index.review("Presencia de ambos progenitores o tutor legal del menor [rc-pasaporte#s1].",
                          question="¿Qué necesito para pedir una partida?")
    assert report.citations == [] and report.off_topic_ids == ["rc-pasaporte#s1"]
    assert any("no tratan el tema" in w for w in report.warnings)


def test_model_citation_with_unrelated_text_is_rejected(index):
    # Caso real (q01): cita la sección correcta pero el texto es de otro trámite.
    answer = ("- Dos testigos mayores de edad que no sean parientes en ningún grado [rc-partidas#s1].\n"
              "- Declaración jurada completa y suscripta por ambos convivientes [rc-partidas#s1].")
    report = index.review(answer, question="¿Qué necesito para pedir una partida?")
    assert report.citations == [] and report.rejected_citations == ["rc-partidas#s1"]
    assert report.coverage == 0.0 and any("no coincide" in w for w in report.warnings)


def test_generic_procedure_words_are_not_a_topic(index):
    # «inscribo» coincidía con «Inscripción de ...»: ya no cuenta como tema.
    assert index.topic_sections("¿Cómo me inscribo en el monotributo?") == []


# --- Fuentes = secciones que respaldan el texto ------------------------------------------

def test_sources_are_the_sections_that_support_the_text(index):
    # Caso real (unión convivencial): el texto se copió de la guía de Justicia, pero el modelo
    # citó la ficha del Registro Civil. La fuente que se muestra es la que respalda el texto.
    answer = "Concurrir con el DNI de los padres o tutores legales que acompañen al menor [rc-pasaporte#s1]."
    report = index.review(answer, question="¿Qué requisitos tiene el pasaporte de un menor?")
    assert [c.section_id for c in report.citations] == ["sj-guia#s3"]
    assert report.citations[0].auto  # el modelo no la había citado
    assert report.unverified_ids == ["rc-pasaporte#s1"]
    assert any("no respaldan el texto" in w for w in report.warnings)


def test_model_citation_that_supports_the_text_is_not_marked_auto(index):
    answer = "Presencia de ambos progenitores o tutor legal del menor [rc-pasaporte#s1]."
    report = index.review(answer, question="¿Qué requisitos tiene el pasaporte de un menor?")
    assert [(c.section_id, c.auto) for c in report.citations] == [("rc-pasaporte#s1", False)]
    assert report.unverified_ids == []


def test_keep_only_citations():
    from app.services.citations import keep_only_citations

    text = "Dato uno [a-doc#s1]. Dato dos [a-doc#s2, b-doc#s3]. Nota [ver abajo] y otro [x-doc#s9]."
    assert keep_only_citations(text, {"a-doc#s1", "b-doc#s3"}) == \
        "Dato uno [a-doc#s1]. Dato dos [b-doc#s3]. Nota [ver abajo] y otro."


def test_ties_prefer_the_section_whose_heading_matches_the_question():
    from app.services.citations import CitationIndex

    corpus = ("<<<DOCUMENTO id=nac>>>\n[nac#s1] DNI exprés\nOficio judicial o testimonio de tutela del menor.\n"
              "<<<FIN DOCUMENTO id=nac>>>\n<<<DOCUMENTO id=nac2>>>\n[nac2#s2] Pasaporte menor\n"
              "Oficio judicial o testimonio de tutela del menor.\n<<<FIN DOCUMENTO id=nac2>>>\n")
    rep = {"documents": [
        {**REPORT["documents"][3], "document_id": "nac", "title": "Requisitos DNI pasaporte",
         "sections": [{"section_id": "nac#s1", "heading": "DNI exprés", "status": "included"}]},
        {**REPORT["documents"][3], "document_id": "nac2", "title": "Requisitos DNI pasaporte",
         "sections": [{"section_id": "nac2#s2", "heading": "Pasaporte menor", "status": "included"}]},
    ]}
    idx = CitationIndex.from_corpus(corpus, rep, warnings_file=None)
    report = idx.review("Oficio judicial o testimonio de tutela del menor.",
                        question="¿Qué piden para el pasaporte de un menor?")
    assert [c.section_id for c in report.citations] == ["nac2#s2"]


def test_procedure_title_line_does_not_count_for_coverage(index):
    answer = ("**Trámite:** Solicitud de Partidas, Registro Civil de La Rioja (provincial).\n"
              "- Presentar el DNI del titular de la partida o de un familiar directo.")
    report = index.review(answer, question="¿Qué necesito para pedir una partida?")
    assert report.coverage == 1.0


def test_section_of_another_procedure_is_not_on_topic(index):
    # Pasaporte contra DNI: aunque compartan otras palabras («menor»), son trámites distintos.
    # «exprés» coincide con el encabezado «DNI exprés», pero la pregunta es sobre pasaporte.
    assert "nac-dni#s2" not in index.topic_sections("¿Cómo es el pasaporte exprés?")
    assert "nac-dni#s2" in index.topic_sections("¿Cuándo entregan el DNI exprés?")


def test_ids_with_accents_are_recognized():
    from app.services.citations import keep_only_citations

    ids, _ = extract_ids("Dato [rc-rectificación-partidas#s1] y [RC-Partidas#S2].")
    assert ids == ["rc-rectificacion-partidas#s1", "rc-partidas#s2"]
    assert keep_only_citations("Dato [rc-rectificación-partidas#s1].", set()) == "Dato."


def test_short_cited_sentence_is_kept_only_if_the_section_says_it(index):
    # Caso real (7B, q02): «Costo: El trámite es gratuito [s4]» es correcto aunque la frase sea corta.
    base = "- Presentar el DNI del titular de la partida o de un familiar directo [rc-partidas#s1].\n"
    ok = index.review(base + "**Costo:** La partida digital cuesta 1500 pesos [rc-partidas#s2].",
                      question="¿Qué necesito para pedir una partida?")
    assert "rc-partidas#s2" in [c.section_id for c in ok.citations] and ok.unverified_ids == []
    bad = index.review(base + "**Costo:** Es gratis los domingos [rc-partidas#s2].",
                       question="¿Qué necesito para pedir una partida?")
    assert "rc-partidas#s2" not in [c.section_id for c in bad.citations]
    assert bad.unverified_ids == ["rc-partidas#s2"]


# --- Verificación de costos (Fase 6) ------------------------------------------------------

COST_Q = "¿Qué necesito para pedir una partida?"
REQ = "- Presentar el DNI del titular de la partida o de un familiar directo [rc-partidas#s1].\n"


@pytest.mark.parametrize("cost_line, removed", [
    ("**Costo:** La partida digital cuesta 1500 pesos [rc-partidas#s2].", False),   # monto que figura
    ("**Costo:** $1.500 [rc-partidas#s2].", False),
    ("**Costo:** $2.000 [rc-partidas#s2].", True),                                  # monto inventado
    ("**Costo:** Gratuito.", True),                                                 # el documento no lo dice
    ("**Costo:** no informado.", True),                                             # el documento sí lo informa
])
def test_cost_lines_are_checked_against_the_document(index, cost_line, removed):
    report = index.review(REQ + cost_line, question=COST_Q)
    assert bool(report.removed_cost_lines) is removed
    if removed:
        assert any("Se quitó una afirmación sobre el costo" in w for w in report.warnings)


def test_cost_line_without_any_cost_section_is_removed(index):
    # Caso real (h09): «Costo: Gratuito» con un documento que no publica costos.
    report = index.review("- El DNI exprés se entrega en 24 horas en las oficinas del RENAPER [nac-dni#s2].\n"
                          "**Costo:** Gratuito.", question="¿Cuándo entregan el DNI exprés?")
    assert [x["reason"] for x in report.removed_cost_lines] == ["los documentos de la respuesta no publican costos"]


def test_free_claim_is_removed_when_the_document_also_lists_amounts(tmp_path):
    from app.services.citations import CitationIndex

    corpus = ("<<<DOCUMENTO id=rc-p>>>\n[rc-p#s1] Requisitos\nPresentar el DNI del titular de la partida.\n\n"
              "[rc-p#s2] Costo\nCopia certificada: $1.100\nCopia para identificación: Sin cargo\n<<<FIN DOCUMENTO id=rc-p>>>\n")
    rep = {"documents": [{**REPORT["documents"][0], "document_id": "rc-p", "title": "Partidas",
                          "sections": [{"section_id": "rc-p#s1", "heading": "Requisitos", "status": "included"},
                                       {"section_id": "rc-p#s2", "heading": "Costo", "status": "included"}]}]}
    idx = CitationIndex.from_corpus(corpus, rep, warnings_file=None)
    # Caso real (h07): «Sin cargo» es verdad solo para identificación.
    r = idx.review("- Presentar el DNI del titular de la partida [rc-p#s1].\n**Costo:** Sin cargo [rc-p#s2].",
                   question="¿Qué necesito para pedir una partida?")
    assert r.removed_cost_lines and "montos distintos" in r.removed_cost_lines[0]["reason"]


def test_short_only_answer_is_accepted_when_its_lines_match(index):
    # Caso real (v3, c01/c02/c04): solo «Trámite:» y «Costo:», correctas; antes daban cobertura 0.
    ok = index.review("**Trámite:** Solicitud de Partidas [rc-partidas#s0].\n**Costo:** $1.500 [rc-partidas#s2].",
                      question="¿Cuánto cuesta una partida?")
    assert "rc-partidas#s2" in [c.section_id for c in ok.citations] and ok.removed_cost_lines == []
    bad = index.review("**Trámite:** Solicitud de Partidas [rc-partidas#s0].\n**Costo:** $9.999 [rc-partidas#s2].",
                       question="¿Cuánto cuesta una partida?")
    assert "rc-partidas#s2" not in [c.section_id for c in bad.citations]


def test_citation_markers_are_not_counted_as_words():
    from app.services.citations import _answer_sentences

    assert _answer_sentences("Es gratuito [rc-dni-renovacion#s4].") == ["Es gratuito ."]
