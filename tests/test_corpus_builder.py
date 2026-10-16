"""Construcción del corpus: secciones, selección, duplicados, presupuesto y reproducibilidad.

Usa un tokenizer falso (1 token por palabra) para no depender de la red; el conteo con el
tokenizer real se valida en tests/test_corpus_real.py.
"""

import pytest

from app.ingestion.corpus_builder import build_corpus, split_articles, split_markdown, write_build
from app.ingestion.source_registry import STATUS_OK, DocumentRecord, Manifest, sha256_text


class WordTokenizer:
    tokenizer_id = "fake/words"
    fingerprint = "fake"

    def count(self, text: str) -> int:
        return len(text.split())


def add_doc(manifest, tmp_path, doc_id, text, **overrides):
    path = tmp_path / f"{doc_id}.txt"
    path.write_text(text + "\n", encoding="utf-8")
    fields = dict(
        document_id=doc_id, title=f"Título {doc_id}", organism="Organismo X", jurisdiction="provincial",
        source_url=f"https://x.gob.ar/{doc_id}", local_path=None, processed_path=str(path),
        document_type="html", publication_date=None, last_updated_date="2025-10-20",
        retrieved_at="2026-10-16T00:00:00+00:00", content_hash=sha256_text(text), raw_hash=None,
        status=STATUS_OK, version=0,
    )
    fields.update(overrides)
    manifest.upsert(DocumentRecord(**fields))


def config(docs, budget=10_000, **extra):
    return {"tokenizer_id": "fake/words", "max_context_tokens": budget,
            "group_order": ["provincial", "nacional", "normativa"], "documents": docs, **extra}


LONG = "Requisito largo que se repite textualmente en dos documentos distintos del corpus oficial."


# --- Secciones -------------------------------------------------------------

def test_split_markdown_preamble_headings_and_offsets():
    text = "# Título\nIntro\n## Requisitos\nDNI\n## Costo\nSin cargo"
    secs = split_markdown("d", text)
    assert [(s.section_id, s.heading) for s in secs] == [("d#s0", None), ("d#s1", "Requisitos"), ("d#s2", "Costo")]
    assert secs[1].text == "DNI"
    for s in secs:
        assert s.text in text[s.char_start:s.char_end]


def test_split_articles_handles_spaced_numbers_and_moves_headings():
    text = ("10.702\nPREÁMBULO\nARTÍCULO 1º.- Objeto.\nCAPÍTULO II\nREGISTRO CIVIL\n"
            "ARTÍCULO 1 6º.- Tasas: PESOS CIEN ($100,00).\nARTÍCULO 17º.- Final.")
    secs = {s.section_id.split("#")[1]: s for s in split_articles("ley", text)}
    assert set(secs) == {"preambulo", "art-1", "art-16", "art-17"}
    assert "CAPÍTULO II" not in secs["art-1"].text
    assert secs["art-16"].text.startswith("CAPÍTULO II\nREGISTRO CIVIL\nARTÍCULO 1 6º")
    assert "($100,00)" in secs["art-16"].text  # una línea con $ nunca se toma como título


# --- Construcción ----------------------------------------------------------

def test_selection_and_noise_lines(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "ley", "ARTÍCULO 1º.- Uno.\n10.702\n7\nARTÍCULO 2º.- Dos.\nARTÍCULO 3º.- Tres.")
    cfg = config({"ley": {"group": "normativa", "priority": 3, "splitter": "articles",
                          "include_sections": ["art-1", "art-3", "art-99"], "selection_reason": "Prueba.",
                          "drop_line_patterns": [r"^10\.702$", r"^\d{1,2}$"]}})
    build = build_corpus(m, cfg, WordTokenizer())
    assert "[ley#art-1]" in build.text and "[ley#art-3]" in build.text
    assert "Dos." not in build.text and "10.702" not in build.text
    assert "Extracto: solo se incluyen las secciones art-1, art-3. Prueba." in build.text
    assert any("art-99" in w for w in build.warnings)
    doc = build.report["documents"][0]
    assert doc["dropped_noise_lines"] == 2


def test_selection_by_heading(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "nac", "# Título\nIntro\n## DNI menor\nreq menor\n## Canje libreta\nreq canje\n## Pasaporte\nreq pas")
    cfg = config({"nac": {"group": "nacional", "priority": 2, "selection_reason": "Solo lo pertinente.",
                          "include_headings": ["DNI menor", "Pasaporte", "No existe"]}})
    build = build_corpus(m, cfg, WordTokenizer())
    assert "req menor" in build.text and "req pas" in build.text
    assert "req canje" not in build.text and "Intro" not in build.text
    assert "Extracto: solo se incluyen las secciones s1, s3. Solo lo pertinente." in build.text
    assert any("No existe" in w for w in build.warnings)


def test_duplicates_are_controlled_without_losing_traceability(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "a", f"## Req\n{LONG}")
    add_doc(m, tmp_path, "b", f"## Req\n{LONG.upper()}")  # misma frase, distinto formato
    cfg = config({"a": {"group": "provincial", "priority": 1}, "b": {"group": "provincial", "priority": 1}})
    build = build_corpus(m, cfg, WordTokenizer())
    assert build.text.count(LONG) == 1
    assert "[b#s0] Req (contenido idéntico a [a#s0]" in build.text
    assert build.report["duplicates"] == [{"section_id": "b#s0", "duplicate_of": "a#s0"}]


def test_short_repeated_sections_are_not_deduplicated(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "a", "## Costo\nSin cargo")
    add_doc(m, tmp_path, "b", "## Costo\nSin cargo")
    cfg = config({"a": {"group": "provincial", "priority": 1}, "b": {"group": "provincial", "priority": 1}})
    assert build_corpus(m, cfg, WordTokenizer()).report["duplicates"] == []


def test_deterministic_order_and_metadata_header(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "z-prov", "texto provincial")
    add_doc(m, tmp_path, "a-nac", "texto nacional", jurisdiction="nacional", last_updated_date=None)
    cfg = config({"z-prov": {"group": "provincial", "priority": 1}, "a-nac": {"group": "nacional", "priority": 2}})
    text = build_corpus(m, cfg, WordTokenizer()).text
    assert text.index("id=z-prov") < text.index("id=a-nac")  # el grupo manda sobre el orden alfabético
    assert "Fuente oficial: https://x.gob.ar/a-nac" in text
    assert "Última actualización publicada por el organismo: no publicada" in text
    assert "Fecha de obtención: 2026-10-16" in text


def test_budget_excludes_whole_documents_and_readds_what_fits(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "base", "palabra " * 50)
    add_doc(m, tmp_path, "grande", "palabra " * 300, jurisdiction="nacional")
    add_doc(m, tmp_path, "chica", "palabra " * 20)
    cfg = config({"base": {"group": "provincial", "priority": 1},
                  "grande": {"group": "nacional", "priority": 2},
                  "chica": {"group": "normativa", "priority": 3}}, budget=150)
    build = build_corpus(m, cfg, WordTokenizer())
    included = {d["document_id"]: d["included"] for d in build.report["documents"]}
    assert included == {"base": True, "grande": False, "chica": True}
    assert [e["document_id"] for e in build.report["excluded_documents"]] == ["grande"]
    assert "en lugar de truncarlo" in build.report["excluded_documents"][0]["reason"]
    assert build.report["totals"]["tokens"] <= 150
    assert "palabra " * 300 not in build.text  # nada truncado a medias


def test_unconfigured_and_missing_documents_are_reported(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "sin-config", "hola")
    cfg = config({"fantasma": {"group": "provincial", "priority": 1}})
    build = build_corpus(m, cfg, WordTokenizer())
    assert build.report["excluded_documents"][0]["document_id"] == "sin-config"
    assert any("fantasma" in w for w in build.warnings)


def test_build_is_reproducible_byte_for_byte(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "a", f"## Uno\n{LONG}\n## Dos\nmás texto")
    cfg = config({"a": {"group": "provincial", "priority": 1}})
    b1 = build_corpus(m, cfg, WordTokenizer())
    b2 = build_corpus(m, cfg, WordTokenizer())
    assert b1.build_id == b2.build_id and b1.text == b2.text and b1.report == b2.report
    txt1, rep1 = write_build(b1, tmp_path / "out1")
    txt2, rep2 = write_build(b2, tmp_path / "out2")
    assert txt1.read_bytes() == txt2.read_bytes() and rep1.read_bytes() == rep2.read_bytes()
    assert b"\r\n" not in txt1.read_bytes()


def test_build_id_changes_with_config_or_tokenizer(tmp_path):
    m = Manifest(tmp_path / "m.json")
    add_doc(m, tmp_path, "a", "texto")
    cfg = config({"a": {"group": "provincial", "priority": 1}})
    base = build_corpus(m, cfg, WordTokenizer()).build_id
    assert build_corpus(m, config(cfg["documents"], budget=5_000), WordTokenizer()).build_id != base

    class Other(WordTokenizer):
        fingerprint = "otro"
    assert build_corpus(m, cfg, Other()).build_id != base
