"""Análisis del benchmark de la Fase 6: punto de equilibrio y costos.

Lee el JSON de ``benchmark.py`` y calcula, con lo medido:

- **Punto de equilibrio** (§7): costo acumulado de CAG = preparación + costo por consulta × N;
  baseline = costo por consulta × N. Se usan tres escenarios de preparación: construir la caché,
  cargarla de disco en frío y cargarla en caliente. La carga del modelo es común a los dos
  modos y no entra en la comparación (se informa aparte).
- **Energía por consulta**, estimada: no hay medidor de consumo, así que se multiplica el tiempo
  medido por una potencia supuesta (TDP de la CPU y una estimación de toda la PC). Con la tarifa
  oficial de EDELAR se pasa a pesos.
- **Costo de la misma consulta con APIs** que ofrecen prompt caching, con los precios oficiales
  verificados el día del análisis. Los modelos no son comparables en calidad ni en privacidad:
  se informa solo como referencia económica.

Uso:
    python -X utf8 -m app.evaluation.report data/results/phase6_benchmark_<fecha>.json
Resultados: data/results/phase6_summary_<fecha>.json
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path

from app.config import DATA_DIR

# --- Supuestos y fuentes (verificadas el 2026-10-17) -------------------------------------------
POTENCIA_W = {
    "cpu_tdp": 65,     # Ryzen 5 5500: TDP de fábrica (cota inferior: solo la CPU)
    "pc_estimada": 100,  # estimación de toda la PC bajo carga (sin medidor: supuesto declarado)
}
TARIFA_EDELAR_ARS_KWH = {
    "fuente": "EDELAR S.A., cuadro tarifario, Resolución EUCOP N.º 001 Acta 028 (14-04-2026), "
              "https://www.edelar.com.ar/files.php?f=cuadro-tarifario.pdf",
    "nota": "Cargo variable residencial antes del subsidio nacional; el cuadro no indica si incluye impuestos.",
    "primeros_200_kwh": 176.9956,
    "200_a_430_kwh": 125.4670,
    "mas_de_430_kwh": 197.8549,
}
PRECIOS_API_USD_MTOK = {
    "fuente_anthropic": "https://platform.claude.com/docs/en/about-claude/pricing (consultado 2026-10-17)",
    "fuente_openai": "https://developers.openai.com/api/docs/pricing (consultado 2026-10-17)",
    "modelos": {
        # entrada, escritura de caché (5 min), lectura de caché, salida
        "Claude Haiku 5.5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
        "Claude Sonnet 5.5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.10, "output": 10.00},
        "OpenAI gpt-5.4-mini": {"input": 0.75, "cache_write": 0.75, "cache_read": 0.075, "output": 4.50},
    },
    "nota": "OpenAI cobra la escritura de caché como entrada normal (no tiene recargo de escritura). "
            "Los conteos de tokens son los del tokenizer de Qwen: cada proveedor tokeniza distinto (aproximación).",
}


def equilibrio(preparacion: float, por_consulta_cag: float, por_consulta_base: float) -> dict:
    """N a partir del cual CAG acumula menos tiempo que el baseline (``None`` si nunca)."""
    ahorro = por_consulta_base - por_consulta_cag
    if ahorro <= 0:
        return {"n": None, "nota": "CAG no ahorra tiempo por consulta"}
    n = math.floor(preparacion / ahorro) + 1
    return {"n": n, "ahorro_por_consulta_s": round(ahorro, 1),
            "cag_acumulado_n_s": round(preparacion + n * por_consulta_cag, 1),
            "baseline_acumulado_n_s": round(n * por_consulta_base, 1)}


def costo_api(precios: dict, prefijo: int, pregunta: int, salida: int, con_cache: bool, primera: bool) -> float:
    """USD de una consulta: prefijo (normal, escrito o leído de caché) + pregunta + salida."""
    if not con_cache:
        entrada = (prefijo + pregunta) * precios["input"]
    elif primera:
        entrada = prefijo * precios["cache_write"] + pregunta * precios["input"]
    else:
        entrada = prefijo * precios["cache_read"] + pregunta * precios["input"]
    return (entrada + salida * precios["output"]) / 1e6


def main(argv: list[str] | None = None) -> None:
    """Calcula el resumen y lo guarda; imprime las cifras principales."""
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("benchmark", type=Path)
    args = parser.parse_args(argv)
    b = json.loads(args.benchmark.read_text(encoding="utf-8"))
    st = b["stages"]

    cag_total = st["cag"]["total"]["median"]
    base_total = st["baseline"]["total"]["median"]
    cargas = st["cache_load"]["seconds"]
    preparaciones = {
        "construir_cache": st["cache_build"]["seconds"],
        "cargar_cache_en_frio": cargas[0],
        "cargar_cache_en_caliente": sorted(cargas[1:])[len(cargas[1:]) // 2] if len(cargas) > 1 else cargas[0],
    }
    eq = {k: {"preparacion_s": v, **equilibrio(v, cag_total, base_total)} for k, v in preparaciones.items()}
    curvas = {n: {"cag_construyendo_s": round(preparaciones["construir_cache"] + n * cag_total, 1),
                  "cag_desde_disco_s": round(preparaciones["cargar_cache_en_frio"] + n * cag_total, 1),
                  "baseline_s": round(n * base_total, 1)} for n in (1, 2, 5, 10, 50, 100)}

    tarifa = TARIFA_EDELAR_ARS_KWH["mas_de_430_kwh"]
    energia = {}
    for nombre, segundos in (("cag_por_consulta", cag_total), ("baseline_por_consulta", base_total),
                             ("construir_cache", preparaciones["construir_cache"])):
        energia[nombre] = {w_name: {"wh": round(segundos * w / 3600, 2),
                                    "ars": round(segundos * w / 3600 / 1000 * tarifa, 3)}
                           for w_name, w in POTENCIA_W.items()}

    prefijo = b["engine"]["prefix_tokens"]
    pregunta = round(sum(f["question_tokens"] for f in st["cag"]["rows"]) / len(st["cag"]["rows"]))
    salida = b["config"]["tokens_per_answer"]
    api = {}
    for modelo, precios in PRECIOS_API_USD_MTOK["modelos"].items():
        sin = costo_api(precios, prefijo, pregunta, salida, con_cache=False, primera=False)
        primera = costo_api(precios, prefijo, pregunta, salida, con_cache=True, primera=True)
        siguiente = costo_api(precios, prefijo, pregunta, salida, con_cache=True, primera=False)
        api[modelo] = {"sin_cache_usd": round(sin, 6), "primera_con_cache_usd": round(primera, 6),
                       "siguientes_con_cache_usd": round(siguiente, 6),
                       "100_consultas_sin_cache_usd": round(100 * sin, 4),
                       "100_consultas_con_cache_usd": round(primera + 99 * siguiente, 4)}

    resumen = {
        "phase": 6, "generated_at": datetime.now().isoformat(timespec="seconds"), "benchmark_file": args.benchmark.name,
        "medianas_s": {"cag_por_consulta": cag_total, "cag_ttft": st["cag"]["ttft"]["median"],
                       "baseline_por_consulta": base_total, "baseline_ttft": st["baseline"]["ttft"]["median"],
                       "baseline_prefijo": st["baseline"]["prefix"]["median"],
                       "aceleracion_ttft": round(st["baseline"]["ttft"]["median"] / st["cag"]["ttft"]["median"], 1),
                       "aceleracion_total": round(base_total / cag_total, 1)},
        "punto_de_equilibrio": eq, "curvas_acumuladas": curvas,
        "energia_estimada": {"tarifa_ars_kwh": tarifa, "potencias_w": POTENCIA_W, "por_etapa": energia,
                             "fuente_tarifa": TARIFA_EDELAR_ARS_KWH},
        "apis_referencia": {"tokens": {"prefijo": prefijo, "pregunta": pregunta, "salida": salida},
                            "por_modelo": api, "precios": PRECIOS_API_USD_MTOK},
    }
    out = DATA_DIR / "results" / f"phase6_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    out.write_text(json.dumps(resumen, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: resumen[k] for k in ("medianas_s", "punto_de_equilibrio")}, ensure_ascii=False, indent=1))
    print(f"Guardado en {out}")


if __name__ == "__main__":
    main()
