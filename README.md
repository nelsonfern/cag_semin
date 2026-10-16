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

## Configuración

Copiá `.env.example` a `.env` y completá los valores. Las instrucciones de instalación
y ejecución se agregan a medida que cada fase queda aprobada.
