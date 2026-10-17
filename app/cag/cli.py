"""Línea de comandos del motor CAG (pensada también para la demo en vivo).

    python -X utf8 -m app.cag.cli build [--force]     # construye y guarda la caché del corpus
    python -X utf8 -m app.cag.cli info                # cachés guardadas y si están vigentes
    python -X utf8 -m app.cag.cli ask "pregunta" ...  # responde cargando la caché desde disco
    python -X utf8 -m app.cag.cli chat                # varias preguntas con una sola carga

``ask`` y ``chat`` no reconstruyen la caché salvo que se pase ``--build-if-missing``: en una
exposición, la caché se construye antes y en vivo solo se carga.
"""

from __future__ import annotations

import app.config  # noqa: F401  (carga el .env, incluido HF_HOME, antes de importar transformers)

import argparse
import sys
import time

from app.cag.engine import ContextLimitError, QuestionError


def _log(msg: str) -> None:
    """Imprime con hora, para ver cuánto tarda cada etapa durante la demo."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def _engine(args):
    """Carga el modelo y arma el motor para el último corpus (todavía sin caché)."""
    from app.cag.engine import CAGEngine
    from app.cag.model_loader import load_model

    _log("Cargando modelo...")
    lm = load_model(args.model, device=args.device, dtype=args.dtype)
    _log(f"Modelo {lm.model_id} ({lm.dtype}, revisión {(lm.revision or '?')[:12]}) cargado en {lm.load_seconds:.1f} s")
    engine = CAGEngine.from_latest_corpus(lm, max_new_tokens=args.max_new_tokens)
    _log(f"Prefijo: {engine.prefix_len} tokens · cache_id {engine.identity.cache_id} · "
         f"contexto permitido {engine.context_limit}")
    return engine


def _prepare(engine, allow_build: bool, force: bool = False) -> None:
    """Deja la caché lista (desde disco o construida) e informa de dónde salió y cuánto tardó."""
    if force:
        _log("Construyendo la caché KV (forzado)...")
    report = engine.prepare(allow_build=allow_build, force_rebuild=force)
    if report["rejected"] and not force:
        _log(f"Caché en disco descartada: {report['rejected']}")
    if report["source"] == "disk":
        _log(f"Caché cargada desde disco en {report['seconds']:.2f} s ({engine.state.structure['total_mb']} MB)")
    else:
        _log(f"Caché construida en {report['seconds']:.1f} s y guardada en {report['save_seconds']:.2f} s "
             f"({report['file_bytes'] / 2**20:.1f} MB)")


def _ask(engine, question: str, max_new_tokens: int | None) -> None:
    """Responde una pregunta mostrando el texto a medida que se genera, y después los tiempos.

    Se decodifica todo lo generado en cada token y se imprime solo lo nuevo: decodificar
    cada token por separado rompe las palabras y caracteres que ocupan varios tokens.
    """
    tok = engine.tokenizer
    shown = ""
    generated: list[int] = []

    def on_token(token_id: int) -> None:
        nonlocal shown
        generated.append(token_id)
        text = tok.decode(generated, skip_special_tokens=True)
        print(text[len(shown):], end="", flush=True)
        shown = text

    print(f"\n> {question}\n", flush=True)
    try:
        r = engine.answer(question, max_new_tokens=max_new_tokens, on_token=on_token)
    except (QuestionError, ContextLimitError) as exc:
        print(f"No se pudo responder: {exc}")
        return
    print("\n")
    _log(f"Pregunta: {r.question_tokens} tokens procesados en {r.prefill_seconds:.2f} s · "
         f"primer token a los {r.ttft_seconds:.2f} s · {len(r.output_ids)} tokens en {r.total_seconds:.1f} s "
         f"(fin: {r.stopped_by})")


def cmd_build(args) -> None:
    """``build``: construye y guarda la caché (o la carga si ya hay una válida, salvo ``--force``)."""
    engine = _engine(args)
    _prepare(engine, allow_build=True, force=args.force)


def cmd_info(args) -> None:
    """``info``: lista las cachés guardadas y si están vigentes, sin cargar el modelo."""
    from app.cag.cache_store import list_caches
    from app.ingestion.corpus_builder import load_latest
    from app.ingestion.source_registry import Manifest

    current = Manifest().corpus_version
    _, report = load_latest()
    print(f"Corpus actual: build {report['build_id']} · versión del manifiesto {current}")
    caches = list_caches()
    if not caches:
        print("No hay cachés guardadas en data/caches/")
    for meta in caches:
        if "error" in meta:
            print(f"- {meta['cache_id']}: ilegible ({meta['error']})")
            continue
        status = "vigente" if meta.get("corpus_version") == current else "DESACTUALIZADA"
        print(f"- {meta['cache_id']}: {meta['model_id']} {meta['dtype']} rev {(meta['revision'] or '?')[:12]} · "
              f"{meta['prefix_len']} tokens · {meta['file_bytes'] / 2**20:.1f} MB · corpus {meta['corpus_build_id']} · "
              f"{status} · creada {meta['created_at']}")


def cmd_ask(args) -> None:
    """``ask``: responde una o más preguntas con una sola carga de modelo y caché."""
    engine = _engine(args)
    _prepare(engine, allow_build=args.build_if_missing)
    for question in args.questions:
        _ask(engine, question, args.max_new_tokens)


def cmd_chat(args) -> None:
    """``chat``: modo interactivo; pregunta hasta recibir una línea vacía."""
    engine = _engine(args)
    _prepare(engine, allow_build=args.build_if_missing)
    print("\nEscribí tu pregunta (línea vacía o Ctrl+C para salir).")
    while True:
        try:
            question = input("\n? ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not question:
            break
        _ask(engine, question, args.max_new_tokens)


def main(argv: list[str] | None = None) -> None:
    """Define los subcomandos y sus opciones, y ejecuta el elegido."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(prog="python -m app.cag.cli")
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--model", default=None, help="por defecto, MODEL_ID del .env")
    common.add_argument("--device", default=None)
    common.add_argument("--dtype", default=None)
    common.add_argument("--max-new-tokens", type=int, default=256)
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build", parents=[common], help="construye y guarda la caché KV")
    p.add_argument("--force", action="store_true", help="reconstruir aunque haya una caché válida")
    p.set_defaults(func=cmd_build)

    p = sub.add_parser("info", help="cachés guardadas")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("ask", parents=[common], help="responde preguntas")
    p.add_argument("questions", nargs="+")
    p.add_argument("--build-if-missing", action="store_true")
    p.set_defaults(func=cmd_ask)

    p = sub.add_parser("chat", parents=[common], help="modo interactivo")
    p.add_argument("--build-if-missing", action="store_true")
    p.set_defaults(func=cmd_chat)

    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
