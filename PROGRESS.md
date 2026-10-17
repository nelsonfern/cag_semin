# Bitácora de TramitaIA (PROGRESS.md)

Registro del estado de cada fase, decisiones técnicas, comandos ejecutados,
pruebas aprobadas y tareas pendientes. Cada fase cierra con un commit.

## Estado de fases

| Fase | Descripción | Estado |
|------|-------------|--------|
| 0 | Inicialización del repositorio | Completada |
| 1 | Fuentes e ingesta | **Aprobada** (2026-10-16) |
| 2 | Corpus reproducible | **Aprobada** (2026-10-16) |
| 3 | Prueba mínima de KV cache | **Aprobada** (2026-10-17) |
| 4 | Motor CAG | Pendiente |
| 5 | TramitaIA (API + interfaz + citas) | Pendiente |
| 6 | Benchmark | Pendiente |
| 7 | Guía de exposición | Pendiente |

### Criterios de aprobación (resumen de `docs/PROMPT para cag.md`, §12)

1. **Fuentes e ingesta:** ≥ 5 documentos/páginas oficiales reales con URL, organismo,
   fecha de obtención y contenido extraído verificable. Si no se logra, documentar el bloqueo.
2. **Corpus:** extracción reproducible, metadatos conservados, duplicados controlados,
   tokens registrados.
3. **Prueba CAG:** el estado KV del prefijo se reutiliza para dos preguntas independientes
   sin que los tokens de la primera respuesta contaminen la segunda.
4. **Motor CAG:** tests automatizados de reutilización, errores, límites de contexto y aislamiento.
5. **TramitaIA:** app ejecutable que responde con fuentes y se abstiene sin respaldo.
6. **Benchmark:** mediciones reales y reproducibles (hardware, modelo, versiones, corpus,
   repeticiones, medianas/percentiles, punto de equilibrio).
7. **Exposición:** guía de 20–30 min basada en código y resultados reales.

---

## Fase 0 — Inicialización del repositorio (2026-10-16)

**Hecho**
- Lectura e interpretación de la especificación (`docs/PROMPT para cag.md`).
- Estructura base de carpetas (`app/{api,ingestion,cag,services,evaluation}`,
  `data/{raw,processed}`, `tests/`, `frontend/`).
- `README.md`, `PROGRESS.md`, `.gitignore`, `.env.example`.

**Entorno detectado**
- Windows 11 Pro, Python 3.15.0.
- Sin GPU NVIDIA detectada (`nvidia-smi` no disponible).
- RAM total reportada: ~5,8 GB.

**Riesgos identificados (a resolver en la Fase 3)**
- Con ~5,8 GB de RAM y sin GPU, el modelo debe ser pequeño (≈0,5B–1,5B parámetros)
  y la caché KV del corpus debe acotarse en tokens. Ejecución en CPU.
- Python 3.15 es muy reciente: verificar disponibilidad de wheels de `torch`/`transformers`;
  si no existen, usar un entorno virtual con una versión de Python soportada (p. ej. 3.11/3.12).

**Comandos**
```bash
git init   # ya existía
git add . && git commit -m "Commit inicial: estructura base, README y bitácora"
```

**Pendiente:** Fase 1.

---

## Fase 1 — Fuentes e ingesta (2026-10-16)

### Entorno
- Entorno virtual `.venv` con **Python 3.12.9**, porque el Python 3.15 del sistema es demasiado nuevo para el stack de ML.
- Dependencias: requests 2.34.2, beautifulsoup4 4.15.0, pypdf 6.21.0, json5 0.17.3, pytest 9.1.1.
- Decisión del usuario: el modelo podrá correr en **otra PC más potente o vía API** (se define en la Fase 3).

### 1. Inspección de fuentes (antes de programar)

| Fuente | Accesible | Formato | Hallazgos |
|---|---|---|---|
| registrocivil.larioja.gob.ar | Sí | HTML estático | `robots.txt` solo bloquea `/rgformulario/` (app con login) y archivos internos. La guía enlaza **14 fichas** `tramite-*.html` con `<main>`, `<h1>` y una «Última actualización» publicada (20/10/2025). La portada no tiene contenido de trámites. |
| .../guia-tramites.html | Sí | HTML | Índice de las 14 fichas. |
| .../tramite-solicitud-partidas.html | Sí | HTML | Requisitos, costos (cita la Ley 10.929, art. 79) y pasos. El trámite se inicia con Ciudadano Digital (requiere cuenta, no se accede). |
| secretariadejusticia.larioja.gob.ar | Sí | Sitio de una página con JS | `robots.txt` permite todo. El sitemap solo tiene la portada. La guía se renderiza con JS, pero sus datos (`AREAS`, `TRAMITES`, `FAQ`, `CONTACTOS`) están **incrustados en el HTML**: 13 trámites (Registro Civil, IGJ, Servicio Penitenciario, Acceso a la Justicia). Algunos trámites de la IGJ y el Servicio Penitenciario remiten a PDF. |
| legislaturalarioja.gob.ar/consulta-de-leyes/leyes/ | Sí | WordPress | Cada ley tiene una página de detalle con su PDF (p. ej. `ley-10900` → `L10900.pdf`). **`ley-10929` devuelve 404** y la búsqueda no la encuentra. |
| legislaturalarioja.gob.ar/normativa.php | Sí | HTML + PDF | 18 documentos (constituciones, códigos, leyes electorales). No son específicos de trámites del Registro Civil ni de Justicia, así que no se incorporan en esta versión. |
| argentina.gob.ar/tramitar | **No (robots)** | — | `robots.txt`: `Disallow: /tramitar`. No se descarga automáticamente y queda para importación manual. |
| argentina.gob.ar/interior/dni/requisitos-... | Sí | HTML (Drupal) | `Crawl-delay: 10`. Los requisitos de cada tipo de DNI y pasaporte están dentro de un `<form>` con secciones condicionales. Publica `article:modified_time` (2023-07-18). |

**Trámites confirmados con documentación oficial accesible:** solicitud de partidas, nacimientos,
matrimonios, defunciones, unión convivencial, rectificación de partidas, DNI (nuevo ejemplar),
DNI de recién nacido y pasaporte. Todos tienen ficha propia en el Registro Civil y varios
aparecen además en la guía de la Secretaría de Justicia. Fichas del Registro Civil que no se
incorporan todavía: autorización de nacimiento y de defunción, adición de apellido,
reconocimiento e identidad de género.

### 2. Implementación

| Archivo | Responsabilidad |
|---|---|
| `data/sources.json` | Registro curado de fuentes: id, organismo, jurisdicción (provincial/nacional), URL, parser y modo de adquisición (`auto`/`manual`). |
| `app/config.py` | Rutas del proyecto y parámetros de entorno (User-Agent, pausa entre solicitudes). |
| `app/ingestion/source_registry.py` | `SourceSpec`, `DocumentRecord` y `Manifest`: versionado por hash, historial, `corpus_version` y marcado de cachés desactualizadas. |
| `app/ingestion/downloader.py` | Descarga respetuosa: `robots.txt`, `Crawl-delay`, pausa mínima por host y User-Agent identificable. |
| `app/ingestion/parser.py` | Parsers `registro_civil`, `justicia_spa` (lee literales JS sin ejecutarlos), `argentina_gob` y `pdf` (registra páginas sin texto). |
| `app/ingestion/ingest.py` | CLI `run` / `status` / `import-manual`. Guarda versiones en `data/raw` y `data/processed`. |

**Decisiones técnicas**
- `content_hash` = SHA-256 del **texto extraído**, no de los bytes. Así, cambios cosméticos en el HTML (banners, scripts) no generan versiones nuevas. También se guarda `raw_hash` del original.
- `corpus_version` = hash de los pares (id, content_hash) de los documentos `ok`. Es la clave que se usará para asociar cada caché KV a una versión exacta del corpus.
- Si una descarga falla, **no se pisa** la última versión buena: queda en `last_error`.
- Fechas: `last_updated_date` y `publication_date` solo se completan con lo que publica el organismo (la «Última actualización» de la ficha o los metadatos `article:*_time`). `retrieved_at` es nuestra fecha de descarga. Las fechas desconocidas quedan en `null` (por ejemplo, la guía de la Secretaría de Justicia).
- El título del manifiesto es el `<h1>` publicado; el de `sources.json` es solo una etiqueta provisoria.
- Error detectado y corregido durante la fase: el parser nacional eliminaba el `<form>` que contiene los requisitos y extraía solo 43 caracteres. Se conserva el form y se quitan solo `select`, `input` y el campo anti-spam («Dejar en blanco»). Se borraron los datos generados en esa corrida y la ingesta se repitió desde cero.

### 3. Resultados de la ingesta (ejecución real, 2026-10-16)

`corpus_version = db76fabe6b5ad4b3`, **11 documentos `ok`** y 2 pendientes de importación manual.

| document_id | Organismo | Jurisdicción | Últ. act. (organismo) | Caracteres |
|---|---|---|---|---|
| rc-solicitud-partidas | Registro Civil LR | provincial | 2025-10-20 | 1648 |
| rc-nacimientos | Registro Civil LR | provincial | 2025-10-20 | 1936 |
| rc-matrimonios | Registro Civil LR | provincial | 2025-10-20 | 1929 |
| rc-defunciones | Registro Civil LR | provincial | 2025-10-20 | 1708 |
| rc-union-convivencial | Registro Civil LR | provincial | 2025-10-20 | 2161 |
| rc-rectificacion-partidas | Registro Civil LR | provincial | 2025-10-20 | 1648 |
| rc-dni-renovacion | Registro Civil LR | provincial | 2025-10-20 | 1472 |
| rc-dni-recien-nacido | Registro Civil LR | provincial | 2025-10-20 | 1307 |
| rc-pasaporte | Registro Civil LR | provincial | 2025-10-20 | 1647 |
| sj-guia-tramites | Secretaría de Justicia LR | provincial | — (no publicada) | 8847 |
| nac-requisitos-dni-pasaporte | RENAPER (Nación) | nacional | 2023-07-18 | 32517 |
| nac-portal-tramitar | Gob. Nacional | nacional | `manual_pending` (robots) | — |
| ley-10702-impositiva-2024 | Cámara de Diputados LR (vía DGIP) | provincial | — (sancionada 27/12/2023, vigente desde 01/01/2024 según su art. 127) | 138932 |

*(Tabla actualizada en la revisión 1.1. Antes figuraba `leg-ley-10929` como pendiente; se retiró.)*

Una segunda corrida inmediata dio `unchanged` en los 11 documentos y la misma `corpus_version`: la detección de cambios no genera versiones falsas.

**Observaciones para fases siguientes**
- Ya aparece una diferencia entre fuentes: para el pasaporte de menores, la ficha del Registro Civil pide la «presencia de ambos progenitores o tutor legal», mientras que la guía de Justicia menciona «el DNI de los padres o tutores legales que lo acompañen». Es un caso útil para probar que el sistema señale contradicciones (§5).
- El documento nacional (≈32,5 mil caracteres) es más grande que todo el corpus provincial junto. En la Fase 2 hay que decidir si entra completo o solo las secciones relevantes, informando lo que se excluye.
- Costos de partidas: ver la revisión 1.1. La ficha del Registro Civil y la Ley 10.702 no coinciden.

### 4. Comandos ejecutados
```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install requests beautifulsoup4 pypdf json5 pytest
.venv/Scripts/python -X utf8 -m app.ingestion.ingest run      # dos veces (new / unchanged)
.venv/Scripts/python -X utf8 -m app.ingestion.ingest status
.venv/Scripts/python -m pytest
```

### 5. Pruebas — 33 aprobadas, 0 fallidas (después de la revisión 1.1)
- `tests/test_source_registry.py`: versiones new/unchanged/updated, el fallo conserva la versión buena, `corpus_version` estable, fechas vacías, marcado de cachés desactualizadas, guardar y recargar, ids duplicados, validez de `sources.json`.
- `tests/test_parser.py`: los 4 parsers con fragmentos sintéticos, fechas inválidas reportadas (no inventadas), PDF inválido o sin texto, normalización.
- `tests/test_downloader.py`: URL bloqueada por robots no se descarga, caché de `robots.txt`, se respeta `Crawl-delay`.
- `tests/test_corpus_real.py` (**criterio de aprobación**): ≥5 documentos oficiales `.gob.ar` con URL, organismo, título y `retrieved_at`; originales y textos presentes con hashes coincidentes; texto sustantivo (≥500 caracteres); fechas del organismo válidas y no posteriores a la descarga; fuentes no obtenidas sin contenido inventado.

### 6. Criterio de aprobación de la Fase 1
> ≥ 5 documentos oficiales reales con URL, organismo, fecha de obtención y contenido extraído verificable.

**Se cumple:** hay 12 documentos oficiales: 11 páginas de 3 organismos (2 provinciales y 1 nacional) y la Ley Impositiva 2024 publicada por la DGIP. Todos tienen originales y textos versionados con hashes verificables. **Fase aprobada por el usuario el 2026-10-16.**

### Revisión 1.1 — Ley Impositiva 2024 (2026-10-16)

**Origen:** el usuario indicó que la Ley 10.929 no trata sobre tasas y que la Ley Impositiva 2024 es la **Ley 10.702**. Aportó el PDF (`data/raw/ley-impositiva/LEY IMPOSITIVA 2024.pdf`) y su fuente oficial, que es el sitio de la Dirección General de Ingresos Provinciales: https://www.dgiplarioja.gob.ar/archivos/Legislacion/Leyes%20Impositivas/LEY%20IMPOSITIVA%202024.pdf

**Verificaciones realizadas**
- El `robots.txt` de dgiplarioja.gob.ar permite la descarga y la URL responde 200 `application/pdf`.
- La copia aportada y la descarga oficial son **idénticas**: mismo SHA-256 (`7c0cc93c5e75…`), 694.951 bytes.
- Contenido: 60 páginas con texto extraíble (sin errores), unos 139 mil caracteres. El encabezado y el cierre corresponden a la «Ley Nº 10.702»: «Ley Impositiva Anual para el Período Fiscal 2024» (art. 1), sancionada el 27/12/2023 y vigente desde el 01/01/2024 (art. 127).
- Se registró como fuente **automática** (`ley-10702-impositiva-2024`) y reemplazó a `leg-ley-10929`, que salió del manifiesto con una entrada `removed` en el historial.

**Hallazgo: los costos publicados por el Registro Civil no coinciden con esta ley**

| Concepto | Ficha «Solicitud de Partidas» (RC, act. 20/10/2025) | Ley 10.702 |
|---|---|---|
| Norma citada | «Ley Impositiva 2024 (Ley 10.929, art. 79)» | La Ley Impositiva 2024 es la 10.702. Su art. 79 trata la *rúbrica de libros* |
| Copia de acta | Certificada $1.100 · legalizada $1.500 | Art. 39 inc. i: «copia de acta de nacimiento, adopción, defunción o matrimonio» **$100** |
| Otros | Copia para trámite de identificación y primera copia de matrimonio: sin cargo | Art. 39 incluye además: búsqueda de partida $100, partidas de otras provincias $170, acta de unión convivencial $100, rectificación $100 |

No se puede determinar desde el corpus de dónde salen los $1.100 y $1.500. Puede ser una norma posterior, por ejemplo una Ley Impositiva 2025 o una actualización, que no tenemos. **TramitaIA deberá mostrar ambas fuentes y advertir la inconsistencia** sin elegir un monto (§5). Para resolverlo convendría conseguir la Ley Impositiva vigente.

**Cambios de código**
- `parse_pdf` ya no usa el `/Title` del PDF como título: en esta ley era «LA CÁMARA DE DIPUTADOS…». Se usa el título curado de `sources.json`.
- Nuevo `Manifest.sync_spec`: las notas, el organismo y la jurisdicción curados se actualizan en el manifiesto sin crear versión nueva.
- Nuevo `Manifest.remove`: una fuente quitada de `sources.json` sale del manifiesto y queda asentada en el historial.
- Las notas de obtención (redirección, importación manual) pasan al campo `ingest_note`.
- 2 tests nuevos (33 en total).

**Corpus después de la revisión:** `corpus_version = 565fff0e449e2d6c`, 12 documentos `ok`.

### Limitaciones y pendientes
- No hay actualización periódica automática: el corpus se actualiza solo cuando se corre `ingest run`.
- `nac-portal-tramitar` requiere importación manual. Su aporte es bajo porque es un índice de enlaces.
- La Ley 10.702 ocupa unos 139 mil caracteres, casi todos sobre impuestos ajenos a los trámites. En la Fase 2 habrá que incorporar solo los artículos pertinentes (art. 39, Registro Civil), sin perder la trazabilidad y registrando qué se excluye.
- Los PDF de IGJ y del Servicio Penitenciario que enlaza la Secretaría de Justicia no se descargaron porque están fuera de los trámites elegidos. El parser `pdf` ya está disponible para ellos.
- **Para la Fase 3:** un CAG real necesita acceso al estado KV del modelo (Transformers en una PC propia o remota). Las APIs comerciales ofrecen *prompt caching* gestionado por el proveedor, que es un concepto distinto (§8). Esto condiciona la elección entre «API» y «PC potente».

---

## Fase 2 — Corpus reproducible (2026-10-16)

### Decisiones aprobadas por el usuario antes de empezar
1. Tokenizer de la familia **Qwen2.5-Instruct**.
2. De la Ley 10.702, solo los **arts. 1, 39 y 127**.
3. Documento nacional **completo**.
4. Presupuesto de **16.000 tokens**.

Sobre la consulta del usuario por **Ollama Cloud con MiniMax**: la API de Ollama recibe y devuelve texto y no expone, guarda ni restaura la caché KV, así que no sirve como motor CAG. Puede usarse como comparación «modelo grande en la nube sin caché propia» en el benchmark. Hay que verificarlo contra la documentación oficial al empezar la Fase 3 (§3).

### Verificaciones previas
- `tokenizer.json` y `tokenizer_config.json` de Qwen2.5-{0.5B, 1.5B, 3B, 7B, 14B, 32B, 72B}-Instruct tienen el **mismo SHA-256**. Los conteos valen para cualquier tamaño de la familia. En el config se usa `Qwen/Qwen2.5-7B-Instruct`.
- Ley 10.702: la extracción del PDF a veces separa los dígitos (`ARTÍCULO 1 6º`). Con una expresión regular tolerante se detectan los **128 artículos**, únicos y en orden.

### Implementación

| Archivo | Responsabilidad |
|---|---|
| `app/ingestion/parser.py` | Ahora marca los títulos: `##` para las secciones del Registro Civil (`<h2>`) y para cada uno de los 26 bloques de tipo de DNI y pasaporte del sitio nacional. Se descartan los bloques que solo tienen un título de grupo. |
| `app/ingestion/source_registry.py` | Nuevo tipo de cambio `reparsed`: el original es el mismo y cambió la extracción. Así no se confunde con un cambio del organismo. |
| `app/ingestion/ingest.py` | Nuevo comando `reparse`, que re-extrae desde los originales guardados sin usar la red. |
| `data/corpus_config.json` | Tokenizer, presupuesto, orden de grupos y, por documento: grupo, prioridad, divisor, secciones incluidas y líneas de ruido a descartar. |
| `app/ingestion/corpus_builder.py` | Construcción del corpus, detallada abajo. |

**Pipeline de `corpus_builder`**
1. Toma los documentos `ok` del manifiesto.
2. Los divide en secciones con ID estable: `doc#sN` en los documentos con títulos `##` y `doc#art-N` en la ley. Cada sección guarda su posición en el texto procesado.
3. Aplica la selección y descarta las líneas de ruido (los pies de página del PDF).
4. Controla duplicados con texto normalizado (minúsculas y espacios). La copia se reemplaza por una referencia `[doc#sN] (contenido idéntico a [otro#sM]…)`. Las secciones de menos de 80 caracteres no se deduplican, porque «Sin cargo» o «DNI vigente» se repiten legítimamente.
5. Ordena por grupo (provincial → nacional → normativa) y luego por ID. Cada documento lleva una cabecera con título, organismo, jurisdicción, fuente oficial, fecha publicada por el organismo, fecha de obtención y versión. Si es un extracto, la cabecera lo dice.
6. Cuenta tokens con el tokenizer real, sin tokens especiales. Si se pasa del presupuesto, excluye **documentos completos** por prioridad y después reincorpora los que caben. Nunca trunca.
7. `build_id` = hash del formato, el texto, el tokenizer (id y huella) y la configuración. Los archivos se escriben con `\n` fijo para que los bytes sean reproducibles en Windows.

**Errores encontrados y corregidos durante la fase**
- La primera versión del recorte por presupuesto excluyó la ley (1.372 tokens) antes que el documento nacional y no la volvió a incorporar, aunque después cabía. Se agregó una segunda pasada que reincorpora lo que entra. El build defectuoso se borró.
- `latest.json` guardaba rutas relativas a la raíz del proyecto, lo que fallaba fuera del repo. Ahora son relativas a la carpeta del corpus.

### Re-extracción (`ingest reparse`)
- 10 documentos pasaron a **v2** con cambio `reparsed`: las 9 fichas del Registro Civil y el documento nacional. El original es el mismo y solo se agregaron las marcas de título.
- La guía de la Secretaría de Justicia y la ley quedaron sin cambios.
- `corpus_version = b7b3289233add501`.

### Resultado real: `build_id = e30a011c26dfa791`

| Documento | Tokens | Estado |
|---|---|---|
| 9 fichas del Registro Civil | 5.926 | incluidas |
| sj-guia-tramites | 3.114 | incluida |
| ley-10702-impositiva-2024 (arts. 1, 39 y 127) | 1.372 | incluida (126 secciones excluidas por selección) |
| nac-requisitos-dni-pasaporte | 8.985 | **excluida por presupuesto** |
| **Total del corpus** | **10.423 / 16.000** | 11 documentos, 68 secciones, 0 duplicados |

**Desvío respecto del plan:** la estimación previa (~15.000 tokens con el documento nacional, calculada a 4 caracteres por token) fue optimista. Con el tokenizer real, el español rinde unos 3,2 caracteres por token y además suman las cabeceras y los marcadores. El corpus completo ocuparía **unos 19.400 tokens**, así que con 16.000 el documento nacional queda afuera. Queda informado en el reporte y se consulta al usuario cómo seguir.

**Reproducibilidad:** reconstruir con la misma entrada dio el mismo `build_id` y los mismos bytes.

**Duplicados:** no hay secciones idénticas entre documentos. Las fichas del Registro Civil y la guía de Justicia tratan los mismos trámites con **textos distintos** y se conservan las dos, porque incluso se contradicen (pasaporte de menores).

### Comandos ejecutados
```bash
.venv/Scripts/python -m pip install transformers tokenizers
.venv/Scripts/python -X utf8 -m app.ingestion.ingest reparse
.venv/Scripts/python -X utf8 -m app.ingestion.corpus_builder build   # dos veces: mismo build_id
.venv/Scripts/python -m pytest
```

### Pruebas — 47 aprobadas, 0 fallidas
- `tests/test_corpus_builder.py` (10 tests, con un tokenizer falso):
  - División en secciones con sus posiciones, y artículos con números separados.
  - Los títulos de capítulo pasan al artículo siguiente.
  - Selección de secciones y líneas de ruido descartadas.
  - Duplicados con trazabilidad, y textos cortos que no se deduplican.
  - Orden por grupo y cabecera con metadatos.
  - Exclusión por presupuesto sin truncar y con reincorporación de lo que cabe.
  - Documentos sin configurar o no disponibles quedan reportados.
  - Reproducibilidad byte a byte y sin `\r\n`; el `build_id` cambia si cambia la configuración o el tokenizer.
- `tests/test_corpus_real.py` (+3 sobre el corpus real):
  - El build corresponde al manifiesto actual y su hash coincide.
  - Se conservan los metadatos de cada documento incluido y toda exclusión está justificada.
  - El conteo de tokens coincide con el tokenizer real de Qwen2.5 y con su huella.
- `tests/test_source_registry.py` (+1): cambio `reparsed`.

### Criterio de aprobación de la Fase 2
> Extracción reproducible, metadatos conservados, duplicados controlados y cantidad de tokens registrada.

**Se cumple.** El documento nacional se resolvió en la revisión 2.1. **Fase aprobada por el usuario el 2026-10-16.**

### Pendientes y limitaciones
- Los 10.423 tokens son solo del corpus. En la Fase 3 se suman el prompt de sistema y la plantilla de chat del modelo.
- Una aclaración para la Fase 3: después de construir la caché, cada pregunta procesa solo sus propios tokens nuevos. Sin embargo, cada token generado sigue haciendo atención sobre todo el prefijo cacheado. El costo por consulta baja mucho, pero sigue dependiendo del tamaño del corpus, sobre todo en memoria (la caché KV crece linealmente con los tokens).

### Revisión 2.1 — Extracto del documento nacional (2026-10-16)

**Contexto:** con 16.000 tokens el documento nacional completo (8.985 tokens) no entraba. Se analizó su aporte:
- Es la única fuente nacional del corpus y la autoridad del DNI y del pasaporte (RENAPER). Sin él, la app no puede distinguir lo provincial de lo nacional (§5).
- No publica costos.
- Su última actualización es del 18/07/2023.
- De sus 26 secciones, solo unas 14 corresponden a trámites con ficha provincial.

**Decisión del usuario:** incluir las secciones clave y las modalidades rápidas, manteniendo el presupuesto de 16.000 tokens.

**Cambios**
- `corpus_builder`: nueva selección `include_headings`, por título de sección. Es más estable que el índice `sN` cuando el organismo agrega o quita secciones, y el builder avisa si un título desaparece. Tiene un test nuevo.
- `corpus_config.json`: el documento nacional entra con 14 secciones:
  - Primer ejemplar.
  - Actualizaciones de 5 a 8 años y de mayores de 14.
  - Nuevo ejemplar: cambio de domicilio, robo o extravío, menor y mayor.
  - DNI 24 hs y DNI exprés.
  - Pasaporte primer y nuevo ejemplar, menores y mayores.
  - Pasaporte exprés.

  Se excluyen las inscripciones tardías, rectificaciones, canjes de libreta, opciones de nacionalidad y extranjeros. La cabecera del documento declara que es un extracto y por qué.

**Resultado: `build_id = 10ba192df05e0285`**, con el mismo `build_id` al reconstruir.

| Documento | Tokens |
|---|---|
| 9 fichas del Registro Civil | 5.926 |
| sj-guia-tramites | 3.114 |
| nac-requisitos-dni-pasaporte (14 de 27 secciones) | 4.623 |
| ley-10702-impositiva-2024 (3 de 129 secciones) | 1.372 |
| **Total** | **15.047 / 16.000** (12 documentos, 82 secciones, 0 duplicados, 139 secciones excluidas por selección, ningún documento excluido) |

El margen libre es de 953 tokens. Para sumar documentos habrá que subir el presupuesto o recortar otra cosa; el builder no lo hace en silencio.

El build anterior (`e30a011c26dfa791`) se conserva como histórico; `latest.json` apunta al nuevo.

**Pruebas:** 48 aprobadas, 0 fallidas.

---

## Fase 3 — Prueba mínima de caché KV (2026-10-16)

### Verificaciones previas (§3 y §4: no asumir APIs)

**Transformers 5.20.1**, verificado leyendo el código instalado (`cache_utils.py`):
- `DynamicCache` guarda en `cache.layers[i].keys` y `.values` tensores de forma `[batch, cabezas_kv, tokens, dim_cabeza]`.
- **`crop()` cambió de semántica:** recibe la cantidad de tokens **a quitar como número negativo** (`crop(-n)`) y un valor positivo lanza `ValueError`. En versiones anteriores, ese valor era la longitud final. Un tutorial viejo que use `crop(prefix_len)` falla con esta versión. Hay un test que lo documenta.
- `crop` recorta con un slice (`keys[..., :-n, :]`), y cada paso de generación agrega con `torch.cat`. Es decir, la caché dinámica **copia todos sus tensores en cada token generado**: un costo a medir en el benchmark.
- `model(..., past_key_values=cache)` **modifica la caché que recibe**. Si no se restaura entre consultas, la respuesta anterior contamina la siguiente.

**Ollama**, verificado en la documentación oficial (`docs/api.md` en GitHub y `docs.ollama.com/cloud`):
- La API no tiene ningún endpoint ni parámetro para guardar, exportar o restaurar la caché KV.
- El parámetro `context` de `/api/generate` está marcado como obsoleto y se describe como «una codificación de la conversación», sin aclarar si son tokens o estados KV.
- Solo informa cuántos tokens del prompt salieron de caché (`prompt_eval_cached_count`), una caché que maneja el servidor.
- Ollama Cloud usa la misma API de chat con una API key. Su página no menciona control de caché ni lista modelos MiniMax.
- **Conclusión:** Ollama y Ollama Cloud **no** sirven como motor CAG. Pueden usarse como comparación en el benchmark.

**Memoria por modelo** (configs oficiales de Qwen2.5-Instruct; caché KV en bf16 para unos 15.500 tokens):

| Modelo | Capas | Cabezas KV | Dim. cabeza | Pesos bf16 | KV por token | Caché KV del corpus |
|---|---|---|---|---|---|---|
| 0.5B | 24 | 2 | 64 | 0,99 GB | 12 KB | 182 MB |
| 1.5B | 28 | 2 | 128 | 3,09 GB | 28 KB | 425 MB |
| 3B | 36 | 2 | 128 | 6,17 GB | 36 KB | 547 MB |
| 7B | 28 | 4 | 128 | 15,23 GB | 56 KB | 850 MB |
| 14B | 48 | 8 | 128 | 29,54 GB | 192 KB | 2,9 GB |

KV por token = 2 (K y V) × capas × cabezas KV × dim. cabeza × 2 bytes. Qwen2.5 usa **GQA** (pocas cabezas K/V compartidas), lo que achica mucho la caché.

**Hardware de esta PC:**
- AMD Ryzen 5 5500U, 6 hilos para torch, AVX2 **sin bfloat16 nativo**.
- 5,8 GB de RAM, con solo ~1,2 GB libres al empezar, y archivo de paginación de 7,5 GB.
- Por eso la Fase 3 usa **Qwen2.5-0.5B-Instruct en CPU y bfloat16**: el objetivo es demostrar el mecanismo, no la calidad de las respuestas. El modelo de producción (7B o similar en la PC potente) se define en la Fase 5.

### Implementación

| Archivo | Responsabilidad |
|---|---|
| `app/cag/model_loader.py` | Carga el modelo y el tokenizer (`MODEL_ID`, `DEVICE`, `DTYPE`) con atención SDPA. Registra tiempo y RAM de carga por separado. |
| `app/cag/prompt.py` | Prefijo = plantilla de chat + instrucciones provisionales + corpus. La pregunta es el sufijo que la plantilla agrega después. Ambos se tokenizan por separado y se concatenan los IDs. `check_boundary` verifica que coincide con tokenizar el texto completo. |
| `app/cag/cache_builder.py` | `prefill` por bloques de 2.048 tokens con `cache_position` explícito (posiciones absolutas para RoPE) y `logits_to_keep=1`. `build_kv_cache` crea la caché, registra tiempo, RAM, estructura (capas, formas, tipo, bytes) y una **huella SHA-256 de todas las K/V del prefijo**. |
| `app/cag/engine.py` | Ver detalle abajo. |
| `app/cag/demo_kv.py` | Demo reproducible con el corpus real. Resultados en `data/results/phase3_kv_demo_*.json`. |

**Funciones de `engine.py`**
- `reset_to_prefix` (`crop(-n)`) y `verify_base_state` (largo de la caché + huella).
- `answer_with_cache`: restaura → verifica → procesa solo la pregunta → genera token por token (greedy) → restaura.
- `answer_without_cache`: el baseline, con una caché nueva por consulta. Usa los **mismos bloques** que la construcción de la caché, para que la comparación aísle el efecto de reutilizarla.

**Decisiones técnicas**
- **Bucle de generación escrito a mano**, en vez de `generate()`, para que quede explícito qué se calcula en cada paso: un token nuevo por paso, en la posición siguiente, atendiendo sobre toda la caché. Es útil para la exposición.
- **Restaurar con `crop`, no copiar la caché** con `deepcopy`: no duplica 182 MB por consulta, y la huella garantiza que el prefijo quedó intacto.
- **Prefill por bloques** para acotar la memoria pico en una PC con poca RAM. Es matemáticamente equivalente a procesarlo de una vez, y hay un test que lo comprueba.

### Pruebas con un modelo minúsculo (`tests/test_cag_kv.py`)
El repo `hf-internal-testing/tiny-random-Qwen2ForCausalLM` ya no existe (401/404). En su lugar, el modelo se crea en memoria: Qwen2 de 2 capas, 4 cabezas (2 KV), pesos aleatorios con semilla 0, float32. No hace falta red.
1. Prefill por bloques = una sola pasada (logits iguales, atol 1e-5).
2. **CAG = baseline** token por token en dos preguntas, y la pregunta 2 hecha **después** de la 1 coincide con la pregunta 2 hecha desde cero (aislamiento). Después de cada consulta la caché vuelve al prefijo con la misma huella.
3. **Control negativo:** sin restaurar, la pregunta 2 arranca con la caché más larga, los logits cambian y `verify_base_state` lo detecta. Al restaurar se recupera exactamente el estado base.
4. Si se altera un valor de la caché, la huella lo detecta.
5. `crop(10)` con un valor positivo lanza error en esta versión.
6. Un prefijo más largo que el contexto del modelo se rechaza.

**Suite completa: 54 aprobadas, 0 fallidas.**

### Demo real (en ejecución)
- Modelo Qwen/Qwen2.5-0.5B-Instruct, revisión `7ae557604adf67be50417f59c2c2f167def9a775`, bfloat16, CPU.
- La primera carga tardó 287,7 s, **incluyendo la descarga** de 988 MB. No es el tiempo de carga desde disco.
- Prefijo de **15.208 tokens** (15.047 del corpus + instrucciones y plantilla). Preguntas de 22 y 27 tokens. Unión de tokenización correcta en ambas.
- Construcción de la caché: **interrumpida a pedido del usuario** después de ~5 minutos en CPU (6 hilos al 100 %, ~1,2 GB de RAM física más paginación a disco). **No se obtuvo ninguna medición de la construcción ni de las consultas**, así que no se informa ninguna. El log parcial se descartó.

**Decisión del usuario (opción 1):** correr la demo en la PC potente. La Fase 3 **queda abierta**: su criterio exige la demostración con el prefijo documental real, y los tests con el modelo minúsculo prueban el mecanismo pero no lo reemplazan.

**PC donde se correrá:** Ryzen 5 5500 de escritorio (6 núcleos / 12 hilos, AVX2, sin bf16 nativo), 16 GB de RAM y Radeon RX 6400 de 4 GB.
- **La GPU no sirve para este stack.** Es AMD, así que no tiene CUDA. La RX 6400 (RDNA2, gfx1034) no figura entre las GPU soportadas oficialmente por ROCm, y PyTorch con ROCm en Windows apunta a GPUs más nuevas. Además, 4 GB apenas alcanzan para el 0.5B. Hay que verificarlo antes de descartarla del todo, pero el plan es usar la **CPU**.
- Con 16 GB de RAM la CPU alcanza:

| Modelo | Pesos en float32 | Caché KV en float32 | Entra en 16 GB |
|---|---|---|---|
| 0.5B | ~2 GB | ~0,36 GB | Sí |
| 1.5B | ~6,2 GB | ~0,85 GB | Sí |
| 3B | ~12,3 GB | ~1,1 GB | Justo (bf16 entra en ~6,2 GB, pero es lento sin bf16 nativo) |

- En una CPU sin bf16 nativo, **float32 suele ser más rápido que bfloat16**. Hay que confirmarlo midiendo.

**Cómo correrla**
```bash
git clone https://github.com/nelsonfern/cag_semin.git && cd cag_semin
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt   # torch para CPU
.venv\Scripts\python -m pytest                             # deben pasar todos los tests
.venv\Scripts\python -X utf8 -m app.cag.demo_kv --device cpu --dtype float32
```
El corpus (`data/processed/corpus/`) y el manifiesto vienen en el repo, así que no hace falta volver a descargar las fuentes. Hay que commitear el JSON de `data/results/` y traerlo para documentarlo.

Se agregó `--device` a la demo y el registro de GPU, VRAM total y VRAM máxima usada.

### Demo real en la PC potente (2026-10-17)

**Elección del modelo (decisiones del usuario)**
- Primero se pidió **Qwen2.5-7B-Instruct**. Se descartó para esta PC: los pesos ocupan 15,2 GB en bf16 y ~30 GB en float32, y no entran en 15,9 GB de RAM (había 4,2 GB libres). Habría que paginar a disco en cada pasada.
- Después se eligió **Qwen2.5-3B-Instruct en bfloat16**. La corrida se **cortó a pedido del usuario** durante la descarga, por la duración estimada (1 a 2,5 h, porque esta CPU emula bf16). No dio ninguna medición.
- Se eligió **Qwen2.5-1.5B-Instruct en float32**, pensando también en una demo en vivo. Usa el mismo tokenizer que el corpus, así que no hubo que reconstruir nada.
- Una primera corrida del 1.5B se interrumpió durante la descarga porque se reinició la sesión de Claude Code. Se relanzó como proceso independiente. No dio ninguna medición.

**Cambios de código:** `DEFAULT_MODEL_ID = Qwen/Qwen2.5-1.5B-Instruct` y dtype por defecto `float32` en `app/cag/model_loader.py`. También se actualizaron `.env.example`, la ayuda de `demo_kv.py` y el comando del README.

**Entorno**
- AMD Ryzen 5 5500, 12 hilos (torch usó 6).
- 15,87 GB de RAM, 7,77 GB disponibles al empezar.
- Windows 11.
- Python 3.12.0, torch 2.14.1+cpu, transformers 5.20.1.
- Sin GPU usable (Radeon RX 6400, sin CUDA).
- Modelo descargado en `D:\hf_cache` (`HF_HOME`).

**Comandos**
```bash
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python -m pytest            # 54 aprobadas, 0 fallidas
set HF_HOME=D:\hf_cache
.venv\Scripts\python -X utf8 -m app.cag.demo_kv --model Qwen/Qwen2.5-1.5B-Instruct --device cpu --dtype float32
```
Resultado: `data/results/phase3_kv_demo_20261017_015231.json`. Log: `data/results/phase3_demo_1.5b_fp32.log`.

**Mediciones (una sola corrida, sin repeticiones; las repeticiones y percentiles van en la Fase 6)**

| Etapa | Valor |
|---|---|
| Carga del modelo | 262,9 s, **incluye terminar la descarga**; no es el tiempo de carga desde disco. RSS de 295 a 6.305 MB |
| Prefijo | 15.208 tokens (corpus `10ba192df05e0285`). Preguntas de 22 y 27 tokens; la unión de tokenización es correcta en ambas |
| Construcción de la caché KV | **204,1 s**. `DynamicCache` de 28 capas, K y V `[1, 2, 15208, 128]` en float32. **831,69 MB** (56 KB por token, igual al cálculo teórico). RSS de 6.316 a 7.317 MB |

| Consulta | CAG: pregunta procesada | CAG: TTFT | CAG: total | Baseline: prefill | Baseline: total |
|---|---|---|---|---|---|
| P1 (partida de nacimiento) | 2,32 s | 2,44 s | **54,6 s** | 206,6 s | **256,5 s** |
| P2 (pasaporte de un menor) | 2,35 s | 2,35 s | **53,3 s** | 201,8 s | **252,1 s** |

En las dos consultas se generaron 96 tokens, el límite (`max_new_tokens`). Con CAG, casi todo el tiempo se va en la generación: ~51 s para 96 tokens, unos 0,53 s por token, cada uno atendiendo sobre ~15.300 posiciones.

**Verificaciones de corrección**
- **CAG = baseline token por token** en P1 y en P2. La diferencia máxima de los primeros logits de P2 frente al baseline es **0,0**.
- La caché tenía **15.208 posiciones antes de cada consulta CAG** y se restauró al prefijo después de cada una, con la misma huella (`1f8da2a58d4c5dd3a107fb47a5342f66`).
- **Control negativo** (sin restaurar):
  - P2 arrancó con **15.325 posiciones**, es decir, 117 de más que sobraron de P1: 22 de la pregunta y 95 generados.
  - Su respuesta difiere de la limpia. La diferencia máxima de los primeros logits es 6,46.
  - Al restaurar se quitaron 239 posiciones y se recuperó exactamente el estado base.

### Criterio de aprobación de la Fase 3
> El estado KV del prefijo documental se reutiliza correctamente para dos preguntas independientes, sin que se incorporen tokens de la primera respuesta a la segunda.

**Se cumple con el corpus real y un modelo real. Fase aprobada por el usuario el 2026-10-17.**

### Limitaciones y pendientes
- `revision` del modelo quedó en `null`: el loader no la obtuvo de la caché local. Para reproducir con precisión, hay que registrarla (se corrige en la Fase 4).
- torch usó 6 de los 12 hilos (su valor por defecto en esta CPU). Se puede medir con 12 en el benchmark.
- Las respuestas están en «tú» porque las instrucciones son todavía provisionales. El voseo y las citas van en la Fase 5.
- Para la demo en vivo, se propone para la Fase 4 **guardar la caché KV en disco** con metadatos (modelo, revisión, dtype, `build_id`, huella), y verificarlos al cargarla, para no reconstruirla durante la exposición.
- En `D:\hf_cache` quedó la descarga parcial del 3B (~4,2 GB), que se puede borrar.
