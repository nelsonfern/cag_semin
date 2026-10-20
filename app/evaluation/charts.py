"""Gráficos de la exposición (Fase 7), generados desde el JSON del benchmark de la Fase 6.

Genera SVG estáticos (con tooltip nativo por elemento) en ``docs/img``:

- ``respuesta_cag_vs_baseline.svg``: barras apiladas «procesar el contexto» + «generar 128
  tokens», con CAG y sin caché. Muestra que CAG elimina el procesamiento del corpus y que la
  generación cuesta lo mismo en los dos modos.
- ``punto_de_equilibrio.svg``: tiempo acumulado según la cantidad de consultas (baseline, CAG
  construyendo la caché y CAG cargándola de disco).

Con ``--oscuro`` genera las mismas figuras para diapositivas de fondo oscuro
(``*_oscuro.svg``). Las dos paletas categóricas están validadas (all-pairs) con el validador de
la guía de visualización: la clara sobre ``#fcfcfb`` y la oscura sobre ``#141414``.

Uso:
    python -X utf8 -m app.evaluation.charts data/results/phase6_benchmark_<fecha>.json [--oscuro]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from xml.sax.saxutils import escape

from app.config import ROOT_DIR

OUT_DIR = ROOT_DIR / "docs" / "img"
SURFACE, INK, INK_2, GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e5e4e0"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]  # azul, naranja, aqua (validados, all-pairs)
# Tema oscuro (diapositivas negras): pasos para fondo oscuro, con el naranja primero para que
# combine con el acento de las diapositivas (validados all-pairs sobre #141414).
OSCURO = {"SURFACE": "#141414", "INK": "#f5f5f5", "INK_2": "#a3a3a3", "GRID": "#262626",
          "SERIES": ["#d95926", "#3987e5", "#199e70"]}
FONT = "font-family:'Segoe UI',Roboto,Arial,sans-serif"


def _svg(width: int, height: int, body: str, title: str) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="100%" '
            f'role="img" aria-label="{escape(title)}" style="{FONT}">\n'
            f'<rect width="{width}" height="{height}" fill="{SURFACE}"/>\n{body}</svg>\n')


def _fmt(s: float) -> str:
    return f"{s:,.1f} s".replace(",", "X").replace(".", ",").replace("X", ".")


def barras(b: dict) -> str:
    """Barras horizontales apiladas: procesar el contexto + generar, por modo."""
    cag, base = b["stages"]["cag"], b["stages"]["baseline"]
    filas = [
        ("Con CAG", cag["ttft"]["median"], cag["total"]["median"] - cag["ttft"]["median"]),
        ("Sin caché (baseline)", base["ttft"]["median"], base["total"]["median"] - base["ttft"]["median"]),
    ]
    W, H, x0, x1 = 880, 300, 190, 800
    escala = (x1 - x0) / max(p + g for _, p, g in filas)
    body = [f'<text x="24" y="34" font-size="18" font-weight="600" fill="{INK}">Tiempo de una respuesta de 128 tokens (mediana)</text>',
            f'<text x="24" y="58" font-size="13" fill="{INK_2}">Qwen2.5-7B Q4 · llama.cpp · CPU Ryzen 5 5500 · corpus de 15.807 tokens</text>']
    for t in range(0, 801, 100):  # grilla cada 100 s
        x = x0 + t * escala
        if x <= x1 + 1:
            body.append(f'<line x1="{x:.1f}" y1="84" x2="{x:.1f}" y2="226" stroke="{GRID}"/>'
                        f'<text x="{x:.1f}" y="246" font-size="12" fill="{INK_2}" text-anchor="middle">{t} s</text>')
    for i, (nombre, proc, gen) in enumerate(filas):
        y = 100 + i * 64
        wp, wg = proc * escala, gen * escala
        body.append(f'<text x="{x0 - 12}" y="{y + 22}" font-size="14" fill="{INK}" text-anchor="end">{nombre}</text>')
        body.append(f'<rect x="{x0}" y="{y}" width="{max(wp, 2):.1f}" height="34" rx="4" fill="{SERIES[0]}">'
                    f'<title>{nombre}: procesar el contexto {_fmt(proc)}</title></rect>')
        body.append(f'<rect x="{x0 + wp + 2:.1f}" y="{y}" width="{max(wg - 2, 2):.1f}" height="34" rx="4" fill="{SERIES[1]}">'
                    f'<title>{nombre}: generar 128 tokens {_fmt(gen)}</title></rect>')
        body.append(f'<text x="{x0 + wp + wg + 10:.1f}" y="{y + 22}" font-size="14" font-weight="600" fill="{INK}">{_fmt(proc + gen)}</text>')
    ly = 274
    for j, etiqueta in enumerate(["Procesar el contexto (prefijo y/o pregunta)", "Generar 128 tokens"]):
        lx = 190 + j * 330
        body.append(f'<rect x="{lx}" y="{ly - 11}" width="14" height="14" rx="3" fill="{SERIES[j]}"/>'
                    f'<text x="{lx + 20}" y="{ly}" font-size="13" fill="{INK_2}">{etiqueta}</text>')
    return _svg(W, H, "\n".join(body), "Tiempo de una respuesta con CAG y sin caché")


def equilibrio(b: dict) -> str:
    """Tiempo acumulado (minutos) según la cantidad de consultas, para los tres escenarios."""
    st = b["stages"]
    q_cag, q_base = st["cag"]["total"]["median"], st["baseline"]["total"]["median"]
    build, disco = st["cache_build"]["seconds"], st["cache_load"]["seconds"][0]
    ns = list(range(0, 7))
    series = [
        ("Sin caché (baseline)", [n * q_base / 60 for n in ns]),
        ("CAG construyendo la caché", [(build + n * q_cag) / 60 for n in ns]),
        ("CAG con la caché en disco", [(disco + n * q_cag) / 60 for n in ns]),
    ]
    W, H, x0, x1, y0, y1 = 880, 420, 80, 640, 360, 90
    ymax = 75
    sx = lambda n: x0 + n * (x1 - x0) / ns[-1]
    sy = lambda m: y0 - m * (y0 - y1) / ymax
    body = [f'<text x="24" y="34" font-size="18" font-weight="600" fill="{INK}">Tiempo acumulado según la cantidad de consultas</text>',
            f'<text x="24" y="58" font-size="13" fill="{INK_2}">Medianas medidas: {_fmt(q_cag)} por consulta con CAG, {_fmt(q_base)} sin caché, '
            f'{_fmt(build)} para construir la caché</text>']
    for m in range(0, ymax + 1, 15):
        body.append(f'<line x1="{x0}" y1="{sy(m):.1f}" x2="{x1}" y2="{sy(m):.1f}" stroke="{GRID}"/>'
                    f'<text x="{x0 - 10}" y="{sy(m) + 4:.1f}" font-size="12" fill="{INK_2}" text-anchor="end">{m} min</text>')
    for n in ns:
        body.append(f'<text x="{sx(n):.1f}" y="{y0 + 22}" font-size="12" fill="{INK_2}" text-anchor="middle">{n}</text>')
    body.append(f'<text x="{(x0 + x1) / 2:.1f}" y="{y0 + 46}" font-size="13" fill="{INK_2}" text-anchor="middle">Consultas respondidas</text>')
    etiquetas_y = []
    for i, (nombre, valores) in enumerate(series):
        pts = " ".join(f"{sx(n):.1f},{sy(v):.1f}" for n, v in zip(ns, valores))
        body.append(f'<polyline points="{pts}" fill="none" stroke="{SERIES[i]}" stroke-width="2" stroke-linejoin="round"/>')
        for n, v in zip(ns, valores):
            body.append(f'<circle cx="{sx(n):.1f}" cy="{sy(v):.1f}" r="5" fill="{SERIES[i]}" stroke="{SURFACE}" stroke-width="2">'
                        f'<title>{nombre} · {n} consultas: {v:.1f} min</title></circle>')
        etiquetas_y.append([sy(valores[-1]), nombre, i])
    etiquetas_y.sort()
    for k in range(1, len(etiquetas_y)):  # separa las etiquetas finales que se pisan
        if etiquetas_y[k][0] - etiquetas_y[k - 1][0] < 18:
            etiquetas_y[k][0] = etiquetas_y[k - 1][0] + 18
    for y, nombre, i in etiquetas_y:
        body.append(f'<rect x="{x1 + 14}" y="{y - 10:.1f}" width="12" height="12" rx="3" fill="{SERIES[i]}"/>'
                    f'<text x="{x1 + 32}" y="{y + 1:.1f}" font-size="13" fill="{INK}">{nombre}</text>')
    # Marca del punto de equilibrio construyendo la caché (N = 2)
    body.append(f'<text x="{sx(2.9):.1f}" y="{sy(28):.1f}" font-size="13" fill="{INK}">CAG gana desde la 2.ª consulta</text>'
                f'<text x="{sx(2.9):.1f}" y="{sy(28) + 18:.1f}" font-size="12" fill="{INK_2}">(desde la 1.ª si la caché ya está en disco)</text>')
    return _svg(W, H, "\n".join(body), "Punto de equilibrio entre CAG y el baseline")


def main(argv: list[str] | None = None) -> None:
    """Genera los SVG en docs/img (con ``--oscuro``, la versión para fondo oscuro)."""
    sys.stdout.reconfigure(encoding="utf-8")
    args = list(argv if argv is not None else sys.argv[1:])
    oscuro = "--oscuro" in args
    if oscuro:
        args.remove("--oscuro")
        globals().update(OSCURO)
    path = Path(args[0])
    b = json.loads(path.read_text(encoding="utf-8"))
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    sufijo = "_oscuro" if oscuro else ""
    for nombre, svg in ((f"respuesta_cag_vs_baseline{sufijo}.svg", barras(b)), (f"punto_de_equilibrio{sufijo}.svg", equilibrio(b))):
        (OUT_DIR / nombre).write_text(svg, encoding="utf-8", newline="\n")
        print(OUT_DIR / nombre)


if __name__ == "__main__":
    main()
