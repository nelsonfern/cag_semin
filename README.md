# TramitaIA

Asistente para entender trámites públicos de la Provincia de La Rioja (Argentina),
basado en documentación oficial verificable y en una implementación real de
**Cache-Augmented Generation (CAG)**: el corpus documental se procesa una sola vez,
se conserva su estado KV (Key/Value de atención) y ese estado se reutiliza en cada
consulta independiente.

> TramitaIA no es asesoría legal ni reemplaza a los organismos oficiales.
> Ante cualquier duda, consultá directamente al organismo correspondiente.

## Estado

Proyecto en desarrollo por fases. El estado detallado, las decisiones y los comandos
ejecutados se registran en la bitácora [`PROGRESS.md`](PROGRESS.md).
La especificación completa está en [`docs/PROMPT para cag.md`](docs/PROMPT%20para%20cag.md).

## Estructura

```
app/
  api/          # FastAPI: rutas públicas y administrativas
  ingestion/    # Registro de fuentes, descarga, parseo y construcción del corpus
  cag/          # Carga del modelo, construcción y reutilización de la caché KV
  services/     # Servicio de respuestas y citas
  evaluation/   # Benchmark (baseline vs CAG) y preguntas de evaluación
data/
  raw/          # Documentos oficiales tal como se descargaron
  processed/    # Texto extraído y corpus preparado
  manifest.json # Manifiesto documental (versión del corpus usada por cada caché)
frontend/       # Interfaz web en español rioplatense
tests/          # Pruebas automatizadas
docs/           # Especificación y material de la exposición
```

## Instalación

Requiere Python 3.12.

```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
```

Copiá `.env.example` a `.env` si querés cambiar el User-Agent o la pausa entre solicitudes.

## Ingesta de fuentes oficiales (Fase 1)

Las fuentes se declaran en [`data/sources.json`](data/sources.json). La ingesta descarga
las automáticas (respetando `robots.txt` y `Crawl-delay`), extrae el texto y registra
metadatos, hash y versión en [`data/manifest.json`](data/manifest.json).

```bash
.venv\Scripts\python -X utf8 -m app.ingestion.ingest run        # descargar y registrar
.venv\Scripts\python -X utf8 -m app.ingestion.ingest status     # ver estado del manifiesto
.venv\Scripts\python -X utf8 -m app.ingestion.ingest import-manual --id nac-portal-tramitar --file pagina.html
```

- Originales: `data/raw/<document_id>/v<versión>.<ext>`
- Texto extraído: `data/processed/<document_id>/v<versión>.txt`
- Si el texto de un documento cambia, se crea una versión nueva (las anteriores se conservan),
  cambia `corpus_version` y las cachés KV construidas con la versión anterior quedan marcadas
  como desactualizadas.

Si cambia un parser, `reparse` vuelve a extraer el texto de los originales guardados sin usar la red:

```bash
.venv\Scripts\python -X utf8 -m app.ingestion.ingest reparse
```

## Corpus para la caché KV (Fase 2)

[`data/corpus_config.json`](data/corpus_config.json) define qué documentos y secciones entran,
su orden, el tokenizer y el presupuesto de tokens.

```bash
.venv\Scripts\python -X utf8 -m app.ingestion.corpus_builder build
```

Genera `data/processed/corpus/<build_id>.txt`, que es el texto exacto que se cargará en la caché,
y `<build_id>.json`, el reporte con documentos incluidos y excluidos, duplicados y tokens por
sección. La misma entrada produce siempre los mismos bytes y el mismo `build_id`.

## Demostración de la caché KV (Fase 3)

```bash
.venv\Scripts\python -X utf8 -m app.cag.demo_kv --device cpu --dtype float32
```

Construye una vez la caché KV del prefijo (instrucciones + corpus) y responde dos preguntas
reutilizándola. Compara cada respuesta con el baseline (todo recalculado), verifica que la
caché vuelva exactamente al estado del prefijo después de cada consulta y corre un control
negativo sin restaurarla. Los resultados quedan en `data/results/phase3_kv_demo_*.json`.

Código: [`app/cag/cache_builder.py`](app/cag/cache_builder.py) (construcción),
[`app/cag/engine.py`](app/cag/engine.py) (consulta, restauración y baseline) y
[`app/cag/prompt.py`](app/cag/prompt.py) (prefijo y pregunta).

## Pruebas

```bash
.venv\Scripts\python -m pytest
```
