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

## Motor CAG y caché en disco (Fase 4)

Construir la caché KV lleva minutos en CPU; cargarla desde disco, segundos. El motor
(`CAGEngine` en [`app/cag/engine.py`](app/cag/engine.py)) la guarda en `data/caches/<cache_id>/`
(fuera de git) y la valida al cargarla: modelo, revisión, dtype, prefijo, versión del corpus
y huella SHA-256 de las K/V. Si algo no coincide, la descarta y la reconstruye.

```bash
.venv\Scripts\python -X utf8 -m app.cag.cli build                 # antes de la demo: construye y guarda
.venv\Scripts\python -X utf8 -m app.cag.cli info                  # cachés guardadas y si están vigentes
.venv\Scripts\python -X utf8 -m app.cag.cli ask "¿Cómo solicito una partida de nacimiento?"
.venv\Scripts\python -X utf8 -m app.cag.cli chat                  # varias preguntas con una sola carga
```

`ask` y `chat` solo cargan la caché (no la reconstruyen salvo con `--build-if-missing`) y
muestran la respuesta a medida que se genera. Para guardar los modelos en otro disco, definí
`HF_HOME` en el `.env`.

Código: [`app/cag/cache_store.py`](app/cag/cache_store.py) (guardar y cargar) y
[`app/cag/cli.py`](app/cag/cli.py).

## Motor de inferencia: llama.cpp con Qwen2.5-7B (Fase 5)

TramitaIA usa por defecto **Qwen2.5-7B-Instruct cuantizado a 4 bits (Q4_K_M)** con
**llama.cpp** ([`app/cag/llamacpp_engine.py`](app/cag/llamacpp_engine.py)). En esta PC (CPU,
16 GB de RAM) es el que mejor respondió en la comparación de modelos, y en PyTorch un 7B no entra
en memoria. El motor de Transformers (Fases 3 y 4) sigue disponible con `ENGINE=transformers`.

| Variable del `.env` | Para qué |
|---|---|
| `ENGINE` | `llamacpp` (por defecto en `.env.example`) o `transformers` |
| `LLAMACPP_REPO`, `LLAMACPP_FILE`, `LLAMACPP_REVISION` | Modelo GGUF del Hub (se descarga la primera vez, con el commit fijo); o `LLAMACPP_MODEL_PATH` para un archivo local |
| `LLAMACPP_TEMPLATE` | Plantilla de chat: `chatml` (Qwen) o `llama3` |
| `LLAMACPP_THREADS`, `LLAMACPP_FLASH_ATTN` | Hilos de CPU (6 en esta PC) y atención optimizada |
| `LLAMACPP_GPU_LAYERS` | Capas en la GPU: `0` solo CPU (por defecto), `-1` todas, `N` las primeras N. Ver «Usar una GPU NVIDIA» |

El motor de llama.cpp tiene las mismas garantías que el de PyTorch: restaura el prefijo antes
y después de cada consulta, verifica la huella SHA-256 de la caché KV, guarda la caché en
`data/caches/<cache_id>/` con sus metadatos y la valida al cargarla. Los comandos de la CLI
(`build`, `ask`, `chat`) y la evaluación usan el motor configurado.

En Windows, `llama-cpp-python` se instala desde el binario para CPU (sin compilador):

```bash
.venv\Scripts\python -m pip install llama-cpp-python==0.3.36 --only-binary=:all: --extra-index-url https://abetlen.github.io/llama-cpp-python/whl/cpu
```

### Usar una GPU NVIDIA (opcional)

Con una GPU NVIDIA el modelo puede mandar parte de sus capas a la placa. Construir la caché y
generar debería ser bastante más rápido. **No está medido en este proyecto:** las cifras de la
Fase 6 son solo en CPU.

1. **Instalar llama-cpp-python con CUDA.** Para la versión 0.3.36 no hay binario con CUDA para
   Windows, así que hay que compilarlo. Hace falta el
   [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads) y Visual Studio Build Tools con
   «Desarrollo para el escritorio con C++». En una consola **x64 Native Tools Command Prompt**:

   ```bat
   set CMAKE_ARGS=-DGGML_CUDA=on
   .venv\Scripts\python -m pip install llama-cpp-python==0.3.36 --force-reinstall --no-cache-dir --no-binary llama-cpp-python
   ```

   La compilación tarda un rato (10 a 30 minutos). Para comprobarla:

   ```bat
   .venv\Scripts\python -c "import llama_cpp; print(llama_cpp.llama_supports_gpu_offload())"
   ```

   Tiene que imprimir `True`.

2. **Elegir cuántas capas van a la GPU**, con `LLAMACPP_GPU_LAYERS` en el `.env`. Qwen2.5-7B
   tiene 28 capas. Con 6 GB de VRAM no entra entero junto con la caché de ~16.000 tokens:
   - empezar con `20`;
   - si al arrancar falla por falta de memoria, bajar de a 2;
   - si sobra memoria, subir.

   Con 8 GB o más, probar `-1` (todas).

3. **Arrancar la app.** La primera vez con un valor nuevo construye una caché nueva, porque las
   capas en GPU forman parte de la identidad de la caché. La caché de solo CPU no se borra y se
   sigue usando con `LLAMACPP_GPU_LAYERS=0`.

Si `LLAMACPP_GPU_LAYERS` es distinto de 0 y llama-cpp-python no tiene soporte de GPU, la app no
arranca y avisa con un mensaje claro: no corre en CPU sin decirlo.

## Aplicación: API e interfaz (Fase 5)

La API FastAPI ([`app/main.py`](app/main.py)) carga el modelo y la caché en segundo plano al
arrancar (alrededor de un minuto, con una consulta de calentamiento) y sirve también la
interfaz web en `/`: un chat hecho con HTML, CSS y Alpine.js ([`frontend/web`](frontend/web)),
sin compilación ni dependencias externas, así que funciona sin internet. Recargar la página no
vuelve a cargar el modelo.

```bash
.venv\Scripts\python scripts\run_app.py --abrir     # http://127.0.0.1:8000 (abre el navegador cuando está listo)
```

Equivale a `.venv\Scripts\python -m uvicorn app.main:app --port 8000`.

Antes de llegar al modelo, las preguntas pasan por un **control de alcance**
([`app/services/scope.py`](app/services/scope.py)): una consulta ajena a los trámites (por
ejemplo, de programación) se responde al instante sin generar nada.

| Ruta | Para qué |
|---|---|
| `GET /health` | Estado del motor (`loading`, `ready`, `error`), modelo, caché y cola |
| `GET /sources` | Documentos del corpus con sus metadatos y fecha de actualización |
| `POST /chat` | Respuesta completa en JSON |
| `POST /chat/stream` | Respuesta por SSE: `queued`, `token`, `final`, `error` |
| `GET /evaluation/results` | Resultados guardados en `data/results/` |
| `POST /admin/ingest`, `POST /admin/rebuild-cache`, `GET /admin/jobs` | Requieren `Authorization: Bearer <ADMIN_TOKEN>`; sin `ADMIN_TOKEN` quedan deshabilitadas |

Cómo se decide qué mostrar ([`app/services/answer_service.py`](app/services/answer_service.py)):

- El modelo cita secciones como `[rc-pasaporte#s1]`. Las citas se validan contra el corpus y los
  enlaces, organismos y fechas salen del registro, no del texto generado
  ([`app/services/citations.py`](app/services/citations.py)).
- Sin ninguna cita válida, la respuesta **no se muestra** y se informa que no hay respaldo.
- Si los documentos no responden, el modelo usa una frase fija de abstención.
- Se advierten costos sin vigencia confirmada, documentos incluidos como extracto y diferencias
  conocidas entre fuentes ([`data/citation_warnings.json`](data/citation_warnings.json)).

Evaluación con preguntas reales ([`app/evaluation/questions.json`](app/evaluation/questions.json)):

```bash
.venv\Scripts\python -X utf8 -m app.evaluation.evaluate
```

## Benchmark (Fase 6)

```bash
.venv\Scripts\python -X utf8 -m app.evaluation.benchmark --reps 5 --baseline-reps 3 --tokens 128
.venv\Scripts\python -X utf8 -m app.evaluation.report data\results\phase6_benchmark_<fecha>.json
.venv\Scripts\python -X utf8 -m app.evaluation.evaluate --questions app\evaluation\questions_heldout.json --phase 6
```

Mide por separado la descarga y preparación del corpus, la carga del modelo, la carga y
construcción de la caché KV, las consultas CAG y el baseline sin caché (con respuestas de largo
fijo), y calcula el punto de equilibrio y los costos. Con Qwen2.5-7B Q4 en CPU: primer token a los
~9 s con CAG contra ~630 s sin caché; CAG conviene desde la segunda consulta (desde la primera si
la caché ya está en disco). Detalle en [`PROGRESS.md`](PROGRESS.md), Fase 6.

## Pruebas

```bash
.venv\Scripts\python -m pytest
```
