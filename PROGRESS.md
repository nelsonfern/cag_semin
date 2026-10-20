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
| 4 | Motor CAG | **Aprobada** (2026-10-17) |
| 5 | TramitaIA (API + interfaz + citas) | **Aprobada** (2026-10-17) |
| 6 | Benchmark | **Aprobada** (2026-10-18) |
| 7 | Guía de exposición | En revisión (2026-10-18) |

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

---

## Fase 4 — Motor CAG (2026-10-17)

**Plan aprobado por el usuario:**
- guardar y cargar la caché KV en disco, con validación;
- `CAGEngine` con lock, restauración garantizada y límites de contexto;
- CLI para la demo en vivo;
- tests y medición real.

Quedan fuera de esta fase la API, las citas y el prompt definitivo (Fase 5), y las repeticiones y percentiles (Fase 6).

### Implementación

| Archivo | Responsabilidad |
|---|---|
| `app/cag/cache_store.py` (nuevo) | Guarda las K/V del prefijo en `data/caches/<cache_id>/kv.safetensors`, en su dtype exacto, junto con `meta.json`: modelo, revisión, dtype, hash de los IDs del prefijo, `build_id` y versión del corpus, huella, formas y versiones de torch y transformers. Escribe en una carpeta temporal y la renombra al final. Al cargar, valida todo y **recalcula la huella**. |
| `app/cag/engine.py` | `CAGEngine` (detallado abajo). Además, `answer_with_cache` ahora restaura la caché en un `finally` y acepta `on_token` para mostrar la respuesta mientras se genera. |
| `app/cag/model_loader.py` | `resolve_revision`: toma el commit de `snapshots/<commit>` de la caché de Hugging Face. En la Fase 3 había quedado en `null`. El dtype por defecto pasa a `float32`. |
| `app/cag/cache_builder.py` | `KVCacheState` registra su origen (`built` o `disk`) y el tiempo de carga. |
| `app/ingestion/corpus_builder.py` | `load_latest()`: texto y reporte del último build. |
| `app/cag/cli.py` (nuevo) | Comandos `build`, `info`, `ask` y `chat`. `ask` y `chat` solo cargan la caché, salvo que se pase `--build-if-missing`. |
| `app/cag/demo_store.py` (nuevo) | Medición real de guardado y carga, comparada contra la Fase 3. |
| `.gitignore`, `.env.example`, `README.md` | `data/caches/` queda fuera de git. Se agrega `HF_HOME` opcional y la sección «Motor CAG y caché en disco». |

**Decisiones**
- **safetensors** en lugar de `torch.save`: cargar el archivo no ejecuta código (pickle).
- **Se guarda en el dtype exacto.** Pasar a bf16 reduciría el archivo a la mitad, pero cambiaría las K/V, y CAG dejaría de coincidir con el baseline.
- **`cache_id` = hash de (modelo, revisión, dtype, IDs del prefijo).** Si cambian el corpus o las instrucciones del sistema (en la Fase 5), cambia el `cache_id`. La versión del corpus se valida aparte, para poder avisar «desactualizada».
- **Ante cualquier duda, se reconstruye.** Una caché que no pasa la validación nunca se usa.
- **Lock por motor.** La caché es una sola y cada consulta la extiende temporalmente, así que las consultas se atienden de a una. Es la base para FastAPI (Fase 5) y limita el throughput a una consulta por vez.
- **`CAGEngine.from_latest_corpus` rechaza un corpus desactualizado**, es decir, uno construido con otra versión del manifiesto.
- **Cada caché construida se registra en `data/manifest.json`** con `register_cache` y `mark_stale_caches`, que ya existían desde la Fase 1. Por eso este commit modifica el manifiesto.

**`CAGEngine`**
- `prepare(allow_build, force_rebuild)` carga la caché desde disco si es válida. Si no, la construye, la guarda y la registra. Informa de dónde salió la caché, cuánto tardó y por qué se descartó la anterior.
- `answer(pregunta)` hace, en orden:
  1. Valida la pregunta: que no esté vacía y que no supere 1.000 caracteres ni 256 tokens.
  2. Valida el contexto: prefijo + pregunta + `max_new_tokens` ≤ min(contexto del modelo, `MAX_CONTEXT_TOKENS`).
  3. Toma el lock.
  4. Restaura la caché y verifica la huella. Si la caché está contaminada o alterada, la **recupera desde disco** y lo registra en `recoveries`.
  5. Responde.
- Errores: `QuestionError`, `ContextLimitError`, `CacheNotReadyError`, `CacheValidationError`.

### Pruebas — 86 aprobadas, 0 fallidas (32 nuevas)

`tests/tiny_model.py` reúne el modelo minúsculo de los tests (sin red).

**`tests/test_cache_store.py` (13 tests)**
- Ida y vuelta exacta: los tensores son idénticos, la huella y la estructura también, y las respuestas y logits coinciden con los de la caché recién construida.
- `meta.json` completo, y el `cache_id` cambia si cambia el modelo, la revisión, el dtype o el prefijo.
- Se rechaza la caché si cambia el modelo, la revisión, el dtype o el prefijo, o si el corpus está desactualizado.
- Se rechaza si se altera **un solo byte** del archivo (falla la huella), si el archivo está truncado, o si `meta.json` falta, no es JSON válido o tiene otro formato.
- Solo se puede guardar la caché en su estado base.

**`tests/test_engine.py` (19 tests)**
- **Reutilización:**
  - el primer `prepare` construye y guarda, y el segundo carga desde disco y responde igual que el baseline;
  - `force_rebuild` reconstruye aunque haya una caché válida;
  - `allow_build=False` sin caché falla;
  - consultar antes de `prepare` falla;
  - la caché queda registrada en el manifiesto sin duplicarse.
- **Aislamiento:**
  - 5 preguntas en 3 órdenes distintos dan respuestas iguales al baseline;
  - una excepción a mitad de la generación deja la caché en el prefijo;
  - una caché alterada en memoria se recupera desde disco;
  - 10 consultas concurrentes desde varios hilos dan lo mismo que en serie;
  - los tokens transmitidos coinciden con el resultado.
- **Errores y límites:**
  - pregunta vacía, demasiado larga en caracteres o en tokens;
  - prefijo + pregunta + respuesta justo en el límite (se acepta) y un token por encima (se rechaza);
  - el límite es el menor entre el del modelo y `MAX_CONTEXT_TOKENS`;
  - un prefijo que no entra se rechaza al crear el motor.

### Medición real (Qwen2.5-1.5B-Instruct, float32, CPU; una sola corrida)
Comando: `python -X utf8 -m app.cag.demo_store --phase3 data/results/phase3_kv_demo_20261017_015231.json`.
Resultado: `data/results/phase4_cache_store_20261017_021149.json`. Log: `data/results/phase4_demo.log`.

| Etapa | Valor |
|---|---|
| Carga del modelo desde disco, sin descarga | **31,3 s** (28,7 s en la corrida de la CLI). Revisión `989aa7980e4cf806f80c7fef2b1adb7bc71aa306` |
| Construcción de la caché | 207,4 s (204,1 s en la Fase 3) |
| Guardado | **6,18 s**, 831,69 MB en disco |
| Huella de la caché construida | **Idéntica a la de la Fase 3** (`1f8da2a5…`): las K/V son reproducibles bit a bit |
| Carga desde disco con validación completa | **1,23 s** justo después de guardarla (el archivo seguía en la caché de disco del sistema operativo); **13,6 s** en la CLI unos minutos después |
| P1 con la caché cargada | 54,0 s (pregunta procesada en 2,49 s). **Texto idéntico al de la Fase 3** |
| P2 con la caché cargada | 51,6 s (pregunta procesada en 2,42 s). **Texto idéntico al de la Fase 3** |

`cache_restored = true` y `recoveries = []`.

**Prueba de la CLI:** `cli ask "¿Dónde saco una partida de matrimonio?" --max-new-tokens 24`:
- modelo cargado en 28,7 s;
- caché cargada en 13,6 s;
- pregunta de 20 tokens procesada en 3,15 s;
- primer token a los 3,24 s;
- 24 tokens en 16,4 s.

La respuesta se muestra mientras se genera.

**Qué implica para la demo en vivo:** se arranca en unos 45 s (modelo y caché) en lugar de unos 4 minutos. Cada respuesta empieza a los ~3 s y genera unos 2 tokens por segundo. La diferencia entre 1,2 y 13,6 s al cargar depende de si el archivo ya estaba en la caché de disco del sistema operativo. Hay que medirla con repeticiones en la Fase 6. Esa carga incluye recalcular la huella SHA-256 de los 832 MB.

### Criterio de aprobación de la Fase 4
> Pruebas automatizadas de reutilización, manejo de errores, límites de contexto y aislamiento entre consultas.

**Se cumple:** 32 tests nuevos cubren las cuatro áreas, y la medición real confirma que la caché cargada desde disco responde exactamente igual que en la Fase 3.

**Revisión del usuario:** pidió que el código se pudiera leer y entender función por función. Se agregaron docstrings a las piezas centrales que no las tenían:
- `_decode`, el bucle de generación, que explica por qué cada paso procesa un solo token y no recalcula el prefijo;
- `CAGEngine.answer`, `validate_question`, `__init__` y `_prepare_locked`;
- `build_kv_cache`, `cache_structure` y `load_model`;
- las clases `GenerationResult`, `KVCacheState`, `LoadedModel` y `EncodedPrompt`;
- los comandos de la CLI.

No cambió ningún comportamiento: 86 tests aprobados. **Fase aprobada por el usuario el 2026-10-17.**

### Limitaciones y pendientes
- Un solo motor atiende una consulta por vez. Si se necesitan consultas en paralelo, hay que copiar la caché, lo que implica unos 830 MB por consulta (Fase 5 o 6).
- El tiempo de carga desde disco varía mucho entre lectura en frío y en caliente; se mide en la Fase 6.
- Las respuestas siguen saliendo en «tú» aunque el prompt pide voseo. El modelo de 1.5B no siempre lo respeta. Se trabaja en la Fase 5 junto con las citas y la abstención.
- `data/caches/` no se versiona. En otra PC hay que correr `cli build` una vez, o copiar la carpeta, que solo sirve con el mismo modelo, revisión, dtype y corpus.

---

## Fase 5 — TramitaIA: API, interfaz y citas (2026-10-17)

**Decisiones del usuario antes de empezar**
- Interfaz en **Streamlit**, como cliente de la API FastAPI. El diseño visual se define más adelante.
- Si una respuesta no tiene ninguna cita válida, **no se muestra**: se responde como abstención.
- Respuestas de hasta **256 tokens**.
- Medir 12 hilos de CPU contra 6.
- Después de la primera evaluación: agregar un ejemplo resuelto al prompt y asignar citas por código con filtro de tema (opciones 1 y 2).

### Arquitectura
```
Navegador ─► Streamlit (frontend/app.py, :8501) ─HTTP+SSE─► FastAPI (app/main.py, :8000)
                                                              └─► AnswerService ─► CAGEngine (caché KV)
                                                                               └─► CitationIndex (registro)
```
Streamlit nunca carga el modelo. La API lo carga en segundo plano al arrancar: `/health` informa `loading` y después `ready`.

### Implementación

| Archivo | Responsabilidad |
|---|---|
| `app/cag/prompt.py` | Prompt definitivo. Las reglas de la §5 van antes **y después** del corpus, todo dentro del prefijo cacheado, así que no suman costo por consulta. Incluye la frase fija de abstención (`ABSTENTION_PHRASE`), el formato con títulos, un tope de 150 palabras y **dos ejemplos resueltos**: una respuesta citada, sobre matrimonio (un documento que no está en la evaluación), y una abstención. |
| `app/services/citations.py` | Extrae los `[doc#sN]` y los valida contra el reporte del corpus que generó la caché. Los metadatos (URL, organismo, jurisdicción, fechas, versión) salen del registro. Aplica el **filtro de tema** y la **verificación del contenido por bigramas** (ver abajo). Agrega advertencias por costos sin vigencia confirmada, extractos, diferencias conocidas entre fuentes y mezcla de información provincial y nacional. |
| `data/citation_warnings.json` | Advertencias curadas para el ciudadano: costos de partidas frente a la Ley 10.702, y pasaporte de menores entre Registro Civil y Justicia. Las notas técnicas del manifiesto no se muestran. |
| `app/services/answer_service.py` | Decide entre `answered`, `abstained` (frase fija) y `unsupported` (sin citas válidas, se muestra el mensaje de abstención). Conserva el texto generado en `raw_text` para evaluar. |
| `app/api/runtime.py`, `routes.py`, `schemas.py`, `app/main.py` | Endpoints `/health`, `/sources`, `/chat`, `/chat/stream` (SSE: `queued`, `token`, `replace`, `final`, `error`), `/evaluation/results` y las rutas de admin. La carga del motor va en segundo plano. Cola de hasta 4 consultas; con más responde 429. Las rutas de admin exigen `ADMIN_TOKEN` (comparado con `compare_digest`), corren en segundo plano y de a una. Sin token configurado quedan deshabilitadas. |
| `frontend/app.py`, `frontend/api_client.py` | Interfaz de chat:<br>• borrador en vivo y después la respuesta verificada;<br>• panel «Fuentes consultadas» con los datos del registro;<br>• advertencias, abstenciones y errores;<br>• barra lateral con el estado del motor, la fecha del corpus, la lista de documentos y el alcance y las limitaciones;<br>• las 4 preguntas de ejemplo de la §6. |
| `scripts/run_app.py`, `.streamlit/config.toml` | Arranque de los dos servidores con un comando, y tema mínimo de Streamlit. |
| `app/evaluation/questions.json`, `evaluate.py`, `thread_check.py` | 12 preguntas (8 que el corpus responde y 4 que no), la evaluación (con modo `--rescore`) y la medición de hilos. |
| `requirements.txt` | `safetensors`, `fastapi`, `uvicorn`, `httpx` y `streamlit`, con versiones fijas. |

**Seguridad del texto generado:** nunca se inserta como HTML. Los enlaces e imágenes en Markdown y las URL sueltas que escriba el modelo se desarman (`safe_markdown`). Los únicos enlaces son los del registro.

### Hilos de CPU (`data/results/phase5_threads_20261017_150941.json`)
Pregunta de 48 tokens, 3 repeticiones, después de un calentamiento.

| Hilos | s/token (mediana) | Rango | Pregunta procesada | Total |
|---|---|---|---|---|
| **6** (por defecto de torch) | **0,565** | 0,563-0,572 | 3,45 s | 29,9 s |
| 12 | 0,599 | 0,531-0,651 | 3,98 s | 31,6 s |

**12 hilos no mejoran y varían más**: la generación está limitada por el ancho de banda de memoria, y los hilos de SMT compiten por los mismos núcleos. Queda en 6. El texto fue idéntico en las 7 corridas.

### Evaluación con preguntas reales (Qwen2.5-1.5B, float32, CPU)

**Primera evaluación** (`phase5_eval_20261017_152910.json`, prompt sin ejemplos, caché `92ccc319fbff1dbe`):
- Respondibles: **1 de 8** mostrada. En 7 el modelo no citó nada, y la única que pasó solo decía «**Requisitos:** [rc-defunciones#s1] Requisitos del Trámite».
- No respondibles: 4 de 4 sin mostrar. En 2 el modelo inventó documentos enteros, con URL incluida, y el validador los frenó.

**Revisión del texto generado:**
- A veces el contenido es correcto pero sin cita: $1.100 por la copia certificada y 96 hs para el DNI exprés.
- A veces mezcla documentos: el horario de matrimonio aparece dentro de la respuesta sobre partidas.
- Una respuesta se fue de tema: la pregunta sobre rectificar una partida la respondió con visitas a la cárcel.

**Cambios:**
1. **Ejemplos resueltos en el prompt.** Suman 269 tokens al prefijo (15.755 en total, caché `83ed348a1d8ba1b7` construida en 229,5 s) y no tienen costo por consulta.
2. **Filtro de tema.** Una sección es del tema si el título de su documento o su encabezado comparten alguna palabra con la pregunta (raíces de 5 letras, sin palabras genéricas como «solicitud», «inscribo» o «requisitos»).
3. **Verificación por bigramas en toda respuesta.** Al menos el **60 %** de las frases de 4 o más palabras tienen que compartir el 40 % de sus pares de palabras consecutivas con alguna sección del tema. Si no, se descartan todas las citas, aunque las haya puesto el modelo.
4. **Citas del modelo fuera de tema:** se descartan.
5. **Si el modelo no cita** pero el contenido pasa la verificación, las citas las asigna el código y quedan marcadas como automáticas, con una advertencia.

**Segunda evaluación** (`phase5_eval_20261017_160821.json`, con ejemplos): el modelo pasó a citar en casi todas las respuestas, pero **también en las inventadas**. Pegaba una sección real cualquiera a trámites como monotributo, antecedentes penales o domicilio, y 3 de las 4 no respondibles se habrían mostrado con las reglas anteriores.

**Re-evaluación con las reglas de verificación** (`phase5_eval_20261017_160821_rescored_v1.json`; la versión final, con las fuentes corregidas, está más abajo). Como la decodificación es greedy (determinista), con el mismo prefijo el modelo produce exactamente el mismo texto. Por eso `--rescore` aplica las reglas nuevas a los textos guardados, después de comprobar que el `cache_id` actual sea el de la corrida original.

| Pregunta | Resultado | Cobertura | Revisión manual del texto |
|---|---|---|---|
| q02 defunción | mostrada, citas del modelo | 0,90 | Fiel |
| q04 DNI recién nacido | mostrada | 0,71 | Fiel |
| q05 pasaporte de un menor | mostrada | 0,88 | **Parcialmente fiel** (detectado en la revisión de fuentes, ver abajo): copia los requisitos del documento nacional y mezcla la acreditación del representante legal de las secciones del DNI |
| q06 unión convivencial | mostrada | 0,90 | Fiel |
| q07 rectificación | mostrada | 0,80 | Fiel |
| q01 partida de nacimiento | **oculta** | 0,13 | Correcto ocultarla: requisitos de unión convivencial bajo el título «Solicitud de Partidas» |
| q03 costo de partida | **oculta** | 0,14 | Correcto ocultarla: mismo error que q01 |
| q08 DNI exprés | **oculta** | 0,50 | Correcto ocultarla: requisitos de renovación presentados como «DNI Express» |
| q09-q12 no respondibles | **ocultas (4 de 4)** | 0,00 | Licencia, monotributo, antecedentes y domicilio: trámites inventados con citas falsas o fuera de tema |

**Resumen:** se muestran 5 de 8 respondibles: 4 fieles y 1 parcialmente fiel (q05). Las 3 ocultas tenían errores. De las 4 no respondibles, **ninguna** alucinación quedó visible.

### Revisión: las fuentes que se muestran son las que respaldan el texto
**Problema encontrado por el usuario en la interfaz.** En una consulta sobre unión convivencial, los requisitos estaban copiados casi textuales de la guía de la Secretaría de Justicia (`sj-guia-tramites#s3`), pero el panel mostraba como única fuente la ficha del Registro Civil, que era lo que había citado el modelo. Además, el modelo citó `rc-union-convivencial#s2` («Documentación requerida») junto al costo, que está en `#s4`.

**Causa:** la verificación comprobaba que las frases aparecieran en *alguna* sección del tema, pero después se mostraban las citas que había elegido el modelo, sin comprobar que fueran las secciones que respaldan cada frase.

**Corrección** (`citations.py`, `answer_service.py`, `frontend/app.py`):
- **Las fuentes que se muestran son las secciones que respaldan las frases** (la mejor sección del tema para cada frase, por bigramas).
- Las citas del modelo que no respaldan ninguna frase se informan en `unverified_ids`, con una advertencia, y **se quitan del texto que se muestra** (`keep_only_citations`). Así las citas en línea coinciden con el panel.
- **Desempate:** si el mismo texto aparece en varias secciones (el documento nacional repite párrafos entre el DNI y el pasaporte), gana la sección cuyo encabezado comparte más palabras con la pregunta y, después, la que citó el modelo.
- El rótulo «Respuesta verificada» pasó a ser **«Respuesta con respaldo en los documentos»**: el control es automático y por coincidencia de texto, y el rótulo anterior prometía más de lo que se comprueba. La advertencia general también lo aclara.

**Re-evaluación final** (`phase5_eval_20261017_160821_rescored_163102.json`): **las mismas decisiones** (5 mostradas, 3 ocultas y 4 abstenciones), pero con otras fuentes:

| Pregunta | Fuentes que citó el modelo | Fuentes que se muestran ahora |
|---|---|---|
| q02 | `rc-defunciones#s0, s1, s2` | `rc-defunciones#s1, s2` |
| q04 | `rc-dni-recien-nacido#s0, s1, s2` | `sj-guia-tramites#s2`, `rc-dni-recien-nacido#s0, s2` |
| q05 | `rc-pasaporte#s1` | `nac-requisitos-dni-pasaporte#s22` (Primer pasaporte menor), `#s12` (DNI nuevo ejemplar menor), `#s20` (DNI 24 hs) |
| q06 | `rc-union-convivencial#s1, s2`, `sj-guia-tramites#s3` | `rc-union-convivencial#s1, s2` |
| q07 | `rc-rectificacion-partidas#s0, s1, s2` | `rc-rectificacion-partidas#s1, s2` |

**Hallazgo en la q05.** El modelo tituló la respuesta «Pasaporte, Registro Civil de La Rioja (provincial)» y citó la ficha provincial, pero copió los requisitos del documento **nacional**. Además, los párrafos sobre el oficio judicial y la acreditación del representante legal **no están en las secciones del pasaporte**: salen de las del DNI. La corrección no oculta esta respuesta (su texto sí está en el corpus), pero ahora **el panel lo deja a la vista**: una pregunta sobre pasaporte muestra fuentes de DNI. Antes la cita del modelo lo escondía.

**Limitación que queda:** el filtro de tema usa el título del documento más el encabezado de la sección. El documento nacional se llama «Requisitos para trámites de DNI o Pasaporte», así que todas sus secciones de DNI pasan el filtro en una pregunta sobre pasaporte. Para detectar esta mezcla habría que filtrar por encabezado en los documentos que reúnen varios trámites (el nacional y la guía de Justicia).

**Tiempos:** primer token a los 2,5-2,8 s. La mayoría de las respuestas llega a 256 tokens en unos 130 s (alrededor de 0,5 s por token).

**Calibración:** los umbrales (40 % de bigramas y 60 % de cobertura) se ajustaron con estas mismas 20 respuestas. **Son provisorios**: hay que validarlos con preguntas nuevas en la Fase 6. Una frase parafraseada (no textual) cuenta como no respaldada, así que el sistema prefiere abstenerse.

### Prueba de punta a punta en el navegador
- La API y Streamlit se lanzaron con `.claude/launch.json`. El modelo cargó en 33,3 s y la caché desde disco en 15,1 s.
- Pregunta «¿Qué requisitos piden para inscribir una defunción?»:
  - el borrador se vio en vivo y después «Respuesta verificada» (rótulo anterior a la revisión de fuentes), con citas;
  - el panel de fuentes mostró organismo, jurisdicción, fechas, versión y el enlace oficial;
  - primer token a los 9,3 s y 256 tokens en 159 s. Es más lento que en la evaluación (2,5 s y 127 s); falta medir si se debe al servidor web y al navegador, que comparten la CPU, o al calentamiento de la primera consulta.
- La pregunta de antecedentes penales mostró el borrador inventado mientras se generaba (rotulado como borrador). Una consulta simultánea del usuario mostró «Hay 1 consulta antes que la tuya».
- **Errores encontrados y corregidos:**
  - el recuadro de estado se colapsaba y ocultaba el borrador;
  - los títulos («**Pasos:**») quedaban pegados al último ítem de la lista;
  - no había aviso cuando la respuesta se cortaba por el límite de 256 tokens.

### Pruebas — 158 aprobadas, 0 fallidas (72 nuevas)
- `tests/test_citations.py` (26 tests):
  - división en secciones, extracción de IDs y metadatos del registro;
  - IDs inventados, documentos excluidos y respaldo débil;
  - advertencias (costos, extractos, contradicciones, jurisdicciones);
  - asignación automática;
  - filtro de tema y verificación por bigramas, incluidos los casos reales q01 y q10;
  - fuentes = secciones que respaldan el texto (caso real de unión convivencial), desempate por encabezado y limpieza de citas en el texto;
  - las 82 secciones del corpus real indexadas.
- `tests/test_answer_service.py` (11 tests): las tres decisiones, el texto oculto pero conservado, el streaming y que la asignación automática no anule una abstención.
- `tests/test_api.py` (21 tests):
  - estados del motor (`loading`, `ready`, `error`) y validación de entrada;
  - cola llena (429) y liberación del lugar después de un error;
  - SSE (tokens, `final` y errores), y consultas concurrentes que se atienden de a una;
  - `/sources` y `/evaluation/results` (con protección contra rutas);
  - admin: deshabilitado sin token, token inválido, tarea en segundo plano y de a una.
- `tests/test_frontend.py` (14 tests):
  - parser de SSE y `safe_markdown`;
  - errores de la API y API caída;
  - la página con AppTest: lista, cargando, respuesta con fuentes, abstención, error y respuesta cortada.
- `tests/fakes.py`: motor y servicio falsos (sin modelo).

### Criterio de aprobación de la Fase 5
> Aplicación ejecutable que responda sobre los documentos disponibles, muestre sus fuentes y se abstenga cuando no tenga respaldo suficiente.

**Se cumple con limitaciones:**
- es ejecutable y se probó en el navegador;
- responde con fuentes del registro en 5 de 8 preguntas respondibles (4 fieles y 1 parcialmente fiel, con fuentes que dejan ver la mezcla);
- se abstiene en 4 de 4 no respondibles y oculta las 3 respuestas erróneas.

El costo es que se pierden respuestas: 3 de 8 preguntas legítimas terminan en abstención. **El estado final está en la revisión 5.1 (más abajo)**: se cambió de modelo y de motor.

### Limitaciones y pendientes
- **El modelo es el límite principal.** El 1.5B mezcla documentos y fabrica trámites con un contexto de 15.700 tokens. La seguridad depende de los controles del código, que son léxicos: una respuesta inventada que copie frases textuales de una sección del tema pasaría. Es un hallazgo para la exposición: CAG pone todo el corpus en el contexto, y un modelo chico se pierde en un contexto largo.
- **Umbrales calibrados con pocos datos** (20 respuestas). Hay que validarlos en la Fase 6.
- **El borrador en vivo muestra texto sin verificar** mientras se genera, aunque esté rotulado. Alternativa posible: no mostrar el texto hasta verificarlo, a costa de esperar unos 2 minutos sin ver nada.
- **Respuestas largas:** la mayoría llega al tope de 256 tokens (unos 2 minutos), a pesar de la regla de 150 palabras.
- **Una consulta por vez:** con varias personas, la cola crece unos 2 minutos por consulta.
- El voseo se respeta parcialmente.
- `.claude/launch.json` (configuración local de la vista previa) no se versiona.
- En `data/caches/` quedaron las cachés de los prompts anteriores (`2c872ad2…`, `92ccc319…`, unos 850 MB cada una), que se pueden borrar.

---

### Revisión 5.1 — Motor llama.cpp con Qwen2.5-7B-Instruct Q4_K_M (2026-10-17)

**Por qué.** Al probar la interfaz, el usuario vio que el 1.5B fallaba en casi todas las preguntas reales: los ejemplos de la §6 sobre el pasaporte de un menor y el costo de una partida. Pidió comparar modelos y después probar uno cuantizado con llama.cpp.

#### Comparación de modelos (6 preguntas: q01, q02, q10, q11, q13 y q14)
- La comparación con **Transformers** (Qwen3-1.7B y Qwen2.5-3B en bf16) **se cortó a pedido del usuario** por la duración. Solo quedó medido el 1.5B (`phase5_eval_20261017_165416_qwen25-1.5b-fp32.json`).
- Qwen3-1.7B no entraba en fp32: su caché KV ocupa **3,37 GB** porque tiene 8 cabezas K/V contra 2 del Qwen2.5-1.5B.
- **Gemma no sirve para este esquema de CAG**: usa atención de ventana deslizante, y esas capas no conservan la caché del corpus completo.
- **Ollama y LM Studio tampoco**, porque no exponen la caché KV (Fase 3). **llama.cpp sí lo permite** a través de `llama-cpp-python`.

**Factibilidad de CAG con llama.cpp** (`app/evaluation/llamacpp_probe.py`). Verificado en el código de llama-cpp-python 0.3.36:
- `eval()` borra de la caché todo lo posterior a `n_tokens`, así que **restaurar el prefijo es volver `n_tokens` a su largo**;
- `llama_state_seq_get_data` permite tomar una huella solo de las K/V;
- `save_state` y `load_state` permiten guardarla en disco.

Con Llama 3.2 3B, Qwen2.5-3B y Qwen2.5-7B (todos en Q4_K_M) se cumplió lo mismo:
- la huella de la caché se restaura después de cada consulta;
- el control negativo sin restaurar detecta la contaminación;
- la caché cargada desde disco tiene la misma huella y reproduce la misma respuesta.

El baseline completo (recalcular el prefijo) se salteó a pedido del usuario: tarda unos 8 minutos por modelo. **CAG = baseline token por token** con llama.cpp quedó verificado en los tests del motor (con un corpus chico; ver abajo).

**Resultados** (`phase5_llamacpp_20261017_{173400,174416,180442}.json`; re-evaluados con las reglas de citas finales):

| Modelo | Respondibles mostradas y fieles | Alucinaciones visibles | Por token | Primer token | RAM en uso (pico) | Construir la caché | Cargarla desde disco |
|---|---|---|---|---|---|---|---|
| Qwen2.5-1.5B fp32 (PyTorch) | 1 de 4 (q02) | 0 | 0,56 s | ~2,5 s | 7,2 GB | ~3,5-4 min | 15 s |
| Llama 3.2 3B Q4 | 1 de 4, más q13 con requisitos nacionales atribuidos al Registro Civil | 0 | 0,21 s | 13-15 s (sin `flash_attn`) | 4,8 GB (9,4) | 8,3 min | 18 s |
| Qwen2.5-3B Q4 | 1 de 4 (q02 con «costo no informado», copiado del ejemplo del prompt), más q13 parcial | 0 | 0,19 s | ~2 s | 5,2 GB (6,6) | 6,1 min | 0,7 s |
| **Qwen2.5-7B Q4** | **2 de 4** (q02 y q13, la única que respondió bien la ficha del Registro Civil) | 0 | 0,64 s | 8-10 s | 8,3 GB (10) | 11 min | 9 s |

En las 2 preguntas no respondibles, **los tres modelos de llama.cpp se abstuvieron solos**; el 1.5B inventaba trámites y lo frenaba el código. La pregunta de razonamiento (q14) no la resolvió ninguno.

**Decisión del usuario: Qwen2.5-7B-Instruct Q4_K_M con llama.cpp.** Es el modelo que se había pedido al principio de la Fase 3 y que en PyTorch no entraba en memoria.

#### Cambios de código

| Archivo | Cambio |
|---|---|
| `app/cag/llamacpp_engine.py` (nuevo) | `LlamaCppEngine`, con la misma interfaz que `CAGEngine`. `prepare` carga la caché desde disco o la construye; `answer` valida, toma el lock, restaura el prefijo, verifica la huella (y si falla, recupera desde disco), genera en greedy con streaming y restaura en un `finally`. La caché va a `data/caches/<cache_id>/state.bin` + `meta.json`, y al cargarla se validan modelo, revisión, cuantización, `flash_attn`, `n_ctx`, tamaño del archivo, prefijo, versión del corpus y la huella recalculada. `warmup()` hace una consulta de un token al arrancar. |
| `app/cag/factory.py` (nuevo) | `create_engine()` según `ENGINE` (`llamacpp` o `transformers`). Lo usan la API, la CLI y la evaluación. |
| `app/cag/prompt.py` | Plantillas de chat para GGUF (`chatml`, `llama3`). El ejemplo de costo ahora cita lo que dice el documento: con «no informado» los modelos copiaban esa frase aunque el documento informara el costo. Además, `enable_thinking=False` para Qwen3 (no cambia el prefijo de Qwen2.5). |
| `app/api/runtime.py`, `app/cag/cli.py`, `app/evaluation/evaluate.py` | Usan la fábrica. La reconstrucción de la caché libera el motor anterior antes de cargar el nuevo, para no tener dos 7B en memoria. La evaluación mide memoria y tiempo por token, y acepta `--engine`, `--model`, `--dtype` y `--tag`. |
| `app/services/citations.py` | (1) **Filtro por trámite**: con palabras clave por trámite, si la pregunta nombra uno y la sección trata de otro, la sección no es del tema. En los documentos que reúnen varios trámites (detectados solos: el nacional, la guía de Justicia), el trámite sale del encabezado. Antes, una pregunta sobre pasaporte aceptaba secciones del DNI. (2) La línea «Trámite:» del formato no cuenta en la cobertura. (3) Se quitan las negritas antes que las viñetas: antes, «**Título:**» perdía un asterisco y no se reconocía. (4) Los IDs con tilde (`rc-rectificación-partidas#s1`) se normalizan. |
| `app/services/answer_service.py` | Siempre se verifica, también cuando el texto trae la frase de abstención. El 7B se abstuvo y además pegó una cita; antes eso se mostraba sin verificar. Las notas de «sin respaldo» ya no se contradicen con las citas descartadas. |
| `.env.example`, `requirements.txt`, `README.md` | Variables `ENGINE` y `LLAMACPP_*`; `llama-cpp-python==0.3.36` (en Windows se instala el binario para CPU); sección del motor en el README. |

#### Evaluación con las 14 preguntas (`phase5_eval_20261017_185557_qwen25-7b-q4-llamacpp.json`)
- **Caché:** construida en 678 s, 865 MB (15.807 tokens de prefijo con el prompt corregido).
- **Memoria:** RSS de 6,7 GB y pico de 9,7 GB. Después de cargar quedaban 3,2 GB libres.
- **Tiempos:** primer token a los 7,3-10,1 s (mediana 9,0); 0,55-0,64 s por token (mediana 0,59); respuestas de 28 a 169 s (mediana 79 s).

Revisión manual de cada respuesta contra el corpus:

| | Preguntas | Revisión |
|---|---|---|
| **Mostradas y fieles** | q02 defunción, q04 DNI de recién nacido, q06 unión convivencial, q07 rectificación, q13 pasaporte (Registro Civil) | Datos copiados de la ficha, con el costo correcto («gratuito» en q02 y q04). La q13 incluye además una frase de la guía de Justicia: el panel muestra las dos fuentes y **la advertencia de contradicción** entre ellas |
| **Mostrada con un dato inventado** | q05 pasaporte de un menor | Los requisitos salen de las secciones nacionales del pasaporte, pero dice «**Costo: Gratuito**», que la sección no dice. Pasó con 60 % de cobertura, justo en el umbral |
| **Ocultas** | q01 y q03 partida, q08 DNI exprés, q14 costo | q01 y q03: correcto ocultarlas, porque dicen «sin cargo» para la partida y la copia certificada cuesta $1.100. **q08: la respuesta era correcta** (96 hs hábiles) pero parafraseada, y la verificación por bigramas la ocultó. q14: falla de razonamiento |
| **No respondibles** | q09-q12 | **4 de 4 abstenciones del propio modelo**, sin inventar |

**Resumen:**
- Se muestran 6 de 10 respondibles: 5 fieles y 1 con un dato de costo inventado.
- Ninguna de las 4 no respondibles muestra información inventada.
- Frente al 1.5B: más respuestas mostradas, mejor calidad, y el modelo ya no inventa trámites.

#### Prueba en el navegador y arranque
- La API arrancó con `ENGINE=llamacpp`: modelo en 29-36 s, caché desde disco en 10 s.
- La pregunta de ejemplo del pasaporte mostró «Respuesta con respaldo en los documentos», con las citas de `rc-pasaporte`, la advertencia de costos y la de contradicción con la guía de Justicia, y las dos fuentes en el panel.
- **La primera consulta después de arrancar tardó 33 s hasta el primer token** (las siguientes, unos 8 s). Por eso se agregó `warmup()` al arranque: el arranque pasa a unos 67 s (29 s el modelo, 10 s la caché y 28 s el calentamiento) y **la primera consulta real tiene el primer token a los 7,9 s**.

#### Pruebas — 173 aprobadas, 0 fallidas
`tests/test_llamacpp_engine.py` (10 tests, con el GGUF real de Qwen2.5-3B y un corpus chico; se saltean si el archivo no está descargado):
- metadatos de la caché guardada;
- **CAG = baseline token por token** y aislamiento (q2 después de q1 da lo mismo que q2 sola);
- la carga desde disco reproduce la respuesta;
- una falla a mitad de la generación restaura el prefijo;
- una huella alterada se recupera desde disco;
- los tokens del streaming coinciden con el resultado;
- se rechazan un archivo de estado alterado y metadatos que no coinciden (`n_ctx`);
- límites de pregunta y de contexto;
- el calentamiento no toca el prefijo.

También hay tests nuevos de citas: filtro por trámite, línea «Trámite:», IDs con tilde y abstención con una cita no verificada.

#### Criterio de aprobación de la Fase 5 (estado final)
> Aplicación ejecutable que responda sobre los documentos disponibles, muestre sus fuentes y se abstenga cuando no tenga respaldo suficiente.

**Se cumple con limitaciones:**
- la aplicación es ejecutable con el motor llama.cpp y se probó en el navegador;
- responde con fuentes del registro en 6 de 10 preguntas respondibles;
- se abstiene en 4 de 4 no respondibles.

**Fase aprobada por el usuario el 2026-10-17**, con las revisiones 5.1 (motor llama.cpp y Qwen2.5-7B) y 5.2 (control de alcance e interfaz de chat).

#### Limitaciones y pendientes
- **Un dato inventado puede pasar dentro de una respuesta respaldada** (el costo de la q05). El control es por frases y alcanza con que el 60 % coincida.
- **El control por bigramas oculta respuestas correctas parafraseadas** (q08) y nunca deja pasar las de razonamiento. El usuario lo cuestionó: si el modelo razona, el control léxico estorba. Alternativas para la Fase 6: comparar por significado (embeddings), o advertir en lugar de ocultar.
- **Velocidad:** el primer token sale a ~8-10 s y las respuestas tardan de 0,5 a 3 minutos. El arranque tarda unos 67 s.
- **Memoria:** con el 7B quedan unos 3 GB libres en una PC de 16 GB. Con el navegador y Streamlit abiertos el margen es chico.
- **Umbrales y filtros calibrados con pocas preguntas** (14). La lista de palabras clave por trámite está escrita a mano para este corpus.
- La construcción de la caché del 7B tarda 11 minutos. Cualquier cambio de prompt o de corpus la invalida (el `cache_id` cambia solo).
- En `data/caches/` quedaron cachés de pruebas y de prompts anteriores (varios GB), que se pueden borrar.

---

### Revisión 5.2 — Control de alcance e interfaz de chat (2026-10-17)

**Pedidos del usuario al probar la interfaz con el 7B:**
1. «No tiene control para preguntas que no tengan que ver con el tema»: preguntó sobre un ciclo `for` de Python y la interfaz «se puso a contestar».
2. La interfaz de Streamlit no le gustó, «tiene bug» y pidió algo más producido. Primero eligió HTML + Alpine.js con estilo gubernamental moderno y borrador visible pero atenuado. Después de verla, pidió **un chatbot moderno**.

**Diagnóstico del punto 1.** Reproducido: con «¿Cómo hago un ciclo for en Python?» el modelo se abstuvo, pero cualquier pregunta llegaba al modelo. **Faltaba el control de alcance que pide la §4 (paso C.2).** Además, el borrador en vivo muestra el texto sin verificar: aunque al final se reemplaza por la abstención, durante la generación se ve la respuesta sobre Python.

#### Control de alcance (`app/services/scope.py`)
- **Se hace antes de llamar al modelo.** Una pregunta fuera de alcance se responde al instante con la decisión `out_of_scope` y un mensaje fijo; no se genera nada (antes eran de 30 s a 3 min de cómputo).
- **Criterio:** alguna palabra de contenido (4 letras o más, raíz de 5 letras sin tildes) tiene que aparecer en los **títulos y encabezados del corpus** o en un conjunto de **palabras de trámites y administrativas** («partida», «certificado», «licencia», «monotributo», «turno»...).
- **No se usa el texto completo del corpus**: con él pasaban «¿Cuál es la capital de Francia?» o «Escribime un poema» (por «capital» y «escribano»).
- Las preguntas sobre trámites que el corpus no tiene (licencia, monotributo, antecedentes) **siguen pasando**: el modelo se abstiene, como en la evaluación.
- Verificado:
  - las 14 preguntas de evaluación y 9 formulaciones coloquiales («Se murió mi abuelo», «¿Qué necesito para casarme?») quedan **dentro**;
  - 10 preguntas ajenas (Python, recetas, fútbol, poemas, Windows, traducción, IA) quedan **fuera**.

#### Corrección de citas encontrada en la prueba en el navegador
El modelo escribió «**Costo:** El trámite es gratuito [rc-defunciones#s4]». La cita es correcta, pero la frase es tan corta que no entraba en la verificación, así que se descartaba con el aviso «no respalda el texto». Ahora, una cita del modelo en una frase corta se acepta si al menos el 60 % de las palabras de esa frase están en la sección citada. «Cuesta 5000 pesos [s4]» sigue marcándose como no respaldada.

#### Interfaz de chat (`frontend/web/`: `index.html`, `styles.css`, `app.js`, `vendor/alpine.min.js`)
- **Reemplaza a Streamlit.** Se borraron `frontend/app.py`, `frontend/api_client.py`, `tests/test_frontend.py`, `.streamlit/` y la dependencia `streamlit`.
- **Un solo servidor:** FastAPI sirve la página en `/` y los archivos en `/static`. `scripts/run_app.py` lanza solo uvicorn y, con `--abrir`, abre el navegador cuando el motor está listo.
- **Diseño de chat moderno:**
  - barra lateral con la marca, «Nueva consulta», el estado del motor, el alcance y los documentos; en el celular se pliega;
  - conversación centrada: las preguntas en burbujas a la derecha y las respuestas a la izquierda;
  - campo de escritura fijo abajo, que crece con el texto (Enter envía y Shift+Enter agrega una línea);
  - bienvenida con sugerencias por tema;
  - modo claro y oscuro automático;
  - paleta propia, **sin colores, logos ni marcas oficiales**, y con el aviso «No es un sitio oficial» en la barra lateral y debajo del campo.
- **Mientras genera:** indicador de escritura y **borrador atenuado** con la etiqueta «borrador sin verificar».
- **Al terminar**, debajo de cada respuesta:
  - una insignia («Con respaldo en documentos oficiales», «Sin información en los documentos», «Sin respaldo verificable» o «Fuera del alcance de TramitaIA»);
  - los chips plegables **Fuentes (n)** y **Avisos (n)**; las tarjetas de fuente muestran el organismo, la jurisdicción, las fechas, la versión, las secciones por nombre y el enlace oficial;
  - el tiempo que tardó.
- **Funciona sin internet:** Alpine.js 3.14.1 está copiado en el proyecto (SHA-256 `358d9afb…`) y no se usan CDN ni fuentes externas. Hay un test que lo controla.
- **Seguridad del texto del modelo:** se escapa todo el HTML y solo se agregan negritas, listas y marcas de cita. Nunca se crean enlaces desde el texto generado: los únicos enlaces son los del registro.
- **Error encontrado y corregido:** el atajo de Enter usaba el modificador `.exact`, que existe en Vue pero no en Alpine, y nunca se disparaba.

**Prueba en el navegador** (motor 7B, escritorio y ancho de celular, modo claro y oscuro):
- la pregunta de Python dio «Fuera del alcance» al instante;
- la de defunción dio una respuesta con respaldo, con el borrador visible mientras se generaba, el aviso de corte por largo y las fuentes;
- la de unión convivencial mostró burbujas, el borrador, las fuentes de Registro Civil y Justicia en tarjetas, y Avisos (1). Tardó 3 min 32 s con el navegador abierto en la misma PC;
- no hubo errores en la consola.
- **No se llegó a probar en el navegador el menú plegable del celular**: el usuario cerró el servidor durante la prueba.

**Pruebas: 190 aprobadas, 0 fallidas.**
- Se fueron los 14 tests de Streamlit.
- Nuevos:
  - `tests/test_scope.py` (22): preguntas dentro y fuera de alcance, y que una fuera de alcance no llega al modelo;
  - `tests/test_web.py` (8): la página y sus archivos, que no carga nada de internet y el formateo seguro en JavaScript (ejecutado con Node): HTML escapado, sin enlaces, listas, citas y citas maliciosas;
  - un test de citas en frases cortas.

**Pendientes y limitaciones**
- **El borrador sigue mostrando texto sin verificar** durante la generación (decisión del usuario: visible pero atenuado). Las preguntas fuera de alcance ya no generan borrador.
- **El control de alcance es léxico**: una pregunta ajena que use una palabra de trámites («¿Qué licencia tiene Python?») pasa al modelo, aunque el modelo y la verificación de citas siguen actuando después.
- **Respuestas largas** (hasta 3 min 30 s con el navegador abierto). Conviene medir si bajar `max_new_tokens` o el largo pedido en el prompt mejora la experiencia.
- El usuario mencionó un «bug» de la interfaz de Streamlit sin describirlo. La interfaz se reemplazó por completo, pero no se pudo confirmar cuál era.

---

## Fase 6 — Benchmark (2026-10-17)

**Decisiones del usuario:**
- solo CAG contra el baseline, sin RAG;
- baseline con 2 preguntas × 3 repeticiones;
- el apartado económico no incluye el costo del hardware.

### Configuración

| | |
|---|---|
| Equipo | AMD Ryzen 5 5500 (6 núcleos / 12 hilos), 15,87 GB de RAM, Windows 11. **No se usó GPU**: la Radeon RX 6400 no tiene CUDA y no está soportada por ROCm en Windows; llama-cpp-python está instalado para CPU, así que **no hay VRAM que medir** |
| Software | Python 3.12.0, llama-cpp-python 0.3.36, 6 hilos, `flash_attn` activado |
| Modelo | Qwen2.5-7B-Instruct Q4_K_M (`bartowski/Qwen2.5-7B-Instruct-GGUF`, revisión `8911e8a4…`, 4,36 GB) |
| Corpus y caché | Corpus `10ba192df05e0285`; prefijo de 15.807 tokens; caché `bbcce11f9b11369f` (865 MB de K/V; estado guardado de 907 MB) |
| Medición | Cada respuesta de las mediciones de tiempo genera **exactamente 128 tokens** (`ignore_eos`), para que el largo no influya. La calidad se evalúa aparte, con respuestas normales |
| Archivos | `app/evaluation/benchmark.py` → `data/results/phase6_benchmark_20261017_211141.json` (todas las mediciones individuales); análisis con `app/evaluation/report.py` → `phase6_summary_20261017_233736.json` |

### Resultados por etapa (los costos se miden por separado, §7)

| Etapa | Resultado |
|---|---|
| Descarga de las 11 fuentes automáticas (robots.txt y pausas de cortesía incluidos; sin tocar el manifiesto) | 20,2 s |
| Construcción del corpus | 0,2 s, más 11,4 s para cargar el tokenizer. Mismo `build_id` (reproducible) |
| Carga del modelo | 6,7 s en el proceso principal; 5,1, 24,8 y 11,5 s en procesos separados (cargaban con 7 GB ya ocupados por el proceso principal). **Depende mucho de cuánta RAM libre queda para la caché de disco del sistema** |
| Carga de la caché KV desde disco | **9,6 s la primera vez (en frío)** y **1,27 a 1,34 s las siguientes** (el archivo ya está en la caché de disco del sistema operativo). Esto **explica la diferencia de 1,2 contra 13,6 s** que había quedado pendiente en la Fase 4 |
| Construcción de la caché KV | **651 s**, más 9,1 s para guardarla. Pico de memoria del proceso: 10,0 GB |
| Primera consulta sin calentamiento | Primer token a los **22,2 s** (después, ~8,8 s). Por eso la API hace una consulta de calentamiento al arrancar |

### CAG frente al baseline (mediana, con p10–p90 entre paréntesis)

| | CAG (6 preguntas × 5 repeticiones; n = 29 sin contar la primera) | Baseline (2 preguntas × 3 repeticiones; n = 6) | Relación |
|---|---|---|---|
| Procesar el contexto | Solo la pregunta: **8,8 s** (7,5–9,3) | Prefijo + pregunta: **621,5 s** (619,1–622,4) | |
| Hasta el primer token | **8,8 s** (7,5–9,3) | **630,1 s** (628,3–630,5) | **72 veces** |
| Respuesta completa de 128 tokens | **87,7 s** (86,4–89,8) | **708,0 s** (706,9–708,4) | **8,1 veces** |
| Segundos por token generado | 0,624 (0,612–0,641) | 0,614 (0,611–0,622) | Igual: generar cuesta lo mismo |
| Tokens iguales a los de CAG | | **6 de 6** | CAG = baseline token por token con el corpus real |

**Lectura:**
- CAG elimina el costo de procesar el corpus en cada consulta: 621 s menos por consulta.
- **No acelera la generación**: cada token sigue leyendo los pesos y atendiendo sobre las 15.807 posiciones de la caché. Por eso la respuesta completa mejora 8 veces y el primer token, 72.

### Punto de equilibrio (§7)
Costo acumulado de CAG = preparación + 87,7 s × N; baseline = 708,0 s × N. La carga del modelo es común a los dos modos y no entra.

| Preparación de CAG | Segundos | CAG gana desde | Acumulado con N consultas: CAG / baseline |
|---|---|---|---|
| Construir la caché | 651,2 | **N = 2** (826,7 s contra 1.416 s) | N = 10: 1.528 s / 7.080 s · N = 100: 2,6 h / 19,7 h |
| Cargarla desde disco en frío | 9,6 | **N = 1** (97,3 s contra 708 s) | N = 10: 887 s / 7.080 s |
| Cargarla desde disco en caliente | 1,3 | **N = 1** | |

Construir la caché cuesta casi lo mismo que un solo prefill del baseline (651 contra 622 s). Por eso **en este equipo CAG conviene desde la segunda consulta** si hay que construir la caché, **y desde la primera si ya está guardada**. Con la caché persistida en disco (Fase 4), el costo de preparación prácticamente desaparece.

### Memoria
- Durante las consultas, el proceso usa ~6,7-7,2 GB (modelo y caché), con un **pico de 10,0 GB** al construir o cargar la caché (se copia el estado).
- Con el modelo cargado quedan **2,9 a 3,6 GB libres** de 15,9 GB.
- La caché KV del corpus ocupa 865 MB en f16: 56 KB por token, porque Qwen2.5-7B usa GQA con 4 cabezas K/V.

### Calidad con preguntas nuevas (`questions_heldout.json`; `phase6_eval_20261017_234209_heldout-qwen25-7b.json`)
Son 16 preguntas escritas antes de correrlas, con la respuesta esperada tomada del corpus: 10 respondibles, 4 de trámites que el corpus no tiene y 2 fuera de tema. Se evitó el trámite de matrimonio porque es el ejemplo del prompt.
- **El clasificador automático da 10 de 10 respondibles correctas y 6 de 6 abstenciones.**
- **La revisión manual contra el corpus encuentra menos aciertos:**

| | Preguntas | Revisión manual |
|---|---|---|
| Fieles | h01, h05, h06, h08, h10 | Datos correctos con las secciones correctas. La h08 es incompleta y la h10 dice que el costo no se publica, pero omite la Ley 10.702 |
| Fieles con errores menores | h02, h03 | Lo preguntado es correcto (40 días y luego inscripción de oficio; quién puede iniciar), pero agregan líneas falsas («no se especifican requisitos», «pasos no especificados») |
| **Con un dato incorrecto a la vista** | h04, h07, h09 | **Siempre la línea «Costo:»**: h04 y h09 dicen «gratuito», pero el documento nacional no publica costos; h07 dice «sin cargo», pero la copia certificada cuesta $1.100. La h09 además atribuye el DNI 24 hs al Registro Civil provincial (es del RENAPER) y la h04 usa la sección de cambio de domicilio en lugar de la de extravío |
| No respondibles | h11-h14 | **4 de 4 abstenciones** del propio modelo |
| Fuera de tema | h15, h16 | h16 («serie»): fuera de alcance, al instante. **h15 («asado») pasó el control de alcance** por la palabra «personas» (del encabezado «Dirección de Personas Jurídicas»); el modelo se abstuvo, pero gastó 34 s |

**Conclusiones de calidad:**
- **Los umbrales de citas no se sostienen fuera de la muestra en un punto concreto: el costo.** El formato del prompt pide siempre una línea «**Costo:**». Cuando el documento no publica el monto, el 7B la completa con «gratuito» o «sin cargo». Es una frase corta, a veces sin cita, que no entra en ninguna verificación.
- En el resto, las respuestas mostradas reproducen bien las secciones citadas, y **ninguna pregunta sin respuesta en el corpus mostró información inventada** (4 de 4 en esta muestra; 4 de 4 en la Fase 5).

**Correcciones propuestas** (se dejan para después de aprobar la fase, para no ajustar las reglas sobre el mismo conjunto con el que se mide):
1. Que el formato del prompt no pida «Costo:» cuando el documento no lo informa.
2. Que el código verifique toda frase que mencione un costo contra una sección de costo del documento citado, y la quite si no coincide.
3. Ajustar el vocabulario del control de alcance («personas» es demasiado general).

### Apartado económico (§7)
Cifras por consulta, con lo medido.

| Concepto | CAG | Baseline |
|---|---|---|
| Tiempo | 87,7 s | 708,0 s |
| Energía estimada (65 W de TDP de la CPU, o ~100 W para toda la PC) | 1,6 a 2,4 Wh | 12,8 a 19,7 Wh |
| Costo de esa energía con la tarifa EDELAR (escalón > 430 kWh: $197,8549/kWh) | **$0,31 a $0,48** | **$2,5 a $3,9** |

- **Fuente de la tarifa:** cuadro tarifario de EDELAR, Resolución EUCOP N.º 001 Acta 028 del 14-04-2026, cargo variable residencial antes del subsidio nacional. El cuadro no indica si incluye impuestos.
- **La energía es una estimación**: no se midió el consumo real, porque no había medidor.
- **Hardware:** fuera del alcance, por decisión del usuario.
- **Mantenimiento:** reconstruir la caché ante un cambio de corpus o de prompt lleva 651 s (~12-18 Wh, ~$2,3-3,6). La ingesta de fuentes lleva unos 20 s. La revisión manual de los documentos y de las advertencias curadas es tiempo humano, no medido.

**Referencia: la misma consulta en APIs con prompt caching.** Son 15.807 tokens de prefijo, ~23 de pregunta y 128 de salida, contados con el tokenizer de Qwen (cada proveedor tokeniza distinto: es una aproximación). Precios oficiales consultados el 2026-10-17 en [Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) y [OpenAI](https://developers.openai.com/api/docs/pricing):

| Modelo | Sin caché (USD por consulta) | Con caché: primera / siguientes | 100 consultas con caché |
|---|---|---|---|
| Claude Haiku 5.5 | 0,00165 | 0,00204 / 0,00022 | USD 0,024 |
| OpenAI gpt-5.4-mini | 0,01245 | 0,01245 / 0,00178 | USD 0,19 |
| Claude Sonnet 5.5 | 0,03294 | 0,04085 / 0,00291 | USD 0,33 |

Es la misma idea de CAG del lado del proveedor: pagar una vez por procesar el prefijo y reutilizarlo con un descuento de ~90 %. Pero **la caché vence** a los 5 minutos (o 1 hora, más cara), así que con consultas espaciadas se vuelve a pagar la escritura. Además, los modelos no son comparables en calidad y los datos salen del equipo. En local, la caché persiste en disco sin vencimiento y el costo marginal es la energía.

### Métricas que no se obtuvieron, y por qué
- **VRAM:** no se usa GPU (ver la configuración).
- **Consumo eléctrico real:** no había medidor; se informa una estimación con supuestos declarados.
- **Carga en frío controlada del modelo:** Windows no permite vaciar la caché de disco sin permisos de administrador. Se informa la variación observada (5 a 25 s).
- **RAG:** fuera del alcance, por decisión del usuario.

### Pruebas
- 190 aprobadas: no cambiaron en esta fase.
- Se agregaron `benchmark.py` y `report.py`, y la opción `ignore_eos` del motor, que solo usa el benchmark.

### Criterio de aprobación de la Fase 6
> Mediciones realmente ejecutadas y reproducibles, con configuración del equipo, modelo, versiones, corpus, repeticiones y resultados. Si alguna métrica no puede obtenerse, explicá por qué.

**Se cumple:**
- las mediciones son reales y repetidas (30 de CAG y 6 del baseline), con mediana y percentiles;
- se informan la configuración completa, el punto de equilibrio con lo medido y el apartado económico con fuentes oficiales;
- se explican las métricas que no se pudieron obtener.

La evaluación con preguntas nuevas encontró una debilidad concreta (el costo inventado), documentada con las correcciones propuestas. Queda a la espera de la aprobación del usuario.

### Revisión 6.1 — Corrección del costo inventado y del control de alcance (2026-10-18)

**Pedido del usuario:** corregir los dos problemas que encontró la evaluación con preguntas nuevas y volver a evaluar. Después pidió no repetir todas las evaluaciones y validar **solo con un conjunto nuevo**.

**Cómo se evitó ajustar sobre lo mismo que se mide:**
- Antes de cambiar el código se escribió `app/evaluation/questions_v3.json`: 11 preguntas nunca usadas, con la respuesta y el costo esperados tomados del corpus.
  - 7 respondibles: costo gratuito, costo con monto, costo «determinado por RENAPER», costo no publicado, y preguntas que no piden costo pero tientan a inventarlo;
  - 1 de un trámite que el corpus no tiene;
  - 3 fuera de tema, una con la trampa «gastos *personales*».
- Las correcciones se validaron con ese conjunto. Los dos anteriores solo se usaron para comprobar que no hubiera regresiones, re-evaluando sus textos guardados.

#### Correcciones
1. **Prompt** (`app/cag/prompt.py`): la línea «Costo» se escribe **solo si el documento del trámite tiene sección de costo**, copiando lo que dice y con su cita; nunca un «gratuito» puesto por el modelo. Cambia el prefijo: la caché nueva es `bda0d01871987281` (construida en 624 s, 868 MB).
2. **Verificación de costos en el código** (`CitationIndex.check_costs`): cada línea que afirma algo sobre el costo se compara con las secciones de costo de los documentos que respaldan la respuesta.
   - «gratuito» pasa solo si el documento lo dice y no publica además montos (las partidas son sin cargo solo para identificación);
   - un monto pasa solo si figura;
   - «no publicado» pasa solo si el documento no informa el costo;
   - cualquier otra afirmación tiene que coincidir con la sección de costo.

   Si no pasa, **se quita la línea del texto mostrado** y se avisa con el motivo.
3. **Control de alcance** (`app/services/scope.py`): se sacaron del vocabulario las raíces generales de los encabezados («perso», «infor», «pregu», «nuevo», «ejemp», «publi», «direc»…). «¿Cómo preparo un asado para diez personas?» entraba por «Dirección de **Personas** Jurídicas», y «ejemp» (de «Nuevo ejemplar») es también la raíz de «ejemplo».

**Dos errores que destapó el conjunto nuevo (y se corrigieron):**
4. **Respuestas hechas solo de frases cortas.** «**Trámite:** …» y «**Costo:** El trámite es gratuito [s5]» no tienen ninguna frase medible por bigramas: la cobertura daba 0 % y se ocultaban, **aunque fueran correctas** (c01, c02, c04). Ahora, si no hay nada que medir, se aceptan las citas del modelo cuya frase coincide con la sección citada (por palabras, o por monto si la frase es solo un monto). Igual pasan por el control de costos.
5. **Las marcas de cita se contaban como palabras.** `[rc-dni-renovacion#s4]` sumaba «renov» y «dni» a la frase, y eso afectaba la medición por bigramas de todas las respuestas. Ahora se quitan antes de medir.

#### Validación con el conjunto nuevo (`phase6_eval_20261018_001532_v3.json`; re-evaluado con las reglas finales en `…_v3_rescored.json`, mismo prompt y caché)

| Pregunta | Resultado | Revisión manual |
|---|---|---|
| c01 ¿Cuánto cuesta renovar el DNI? | mostrada | ✅ «determinado por Re.Na.Per» [rc-dni-renovacion#s4] |
| c02 ¿Tiene costo inscribir un nacimiento? | mostrada | ✅ «gratuito» [rc-nacimientos#s5] |
| c03 ¿Cuánto sale el pasaporte? | mostrada | ✅ «determinado por Re.Na.Per» y dónde se inicia |
| c04 ¿Cuánto cuesta una copia legalizada? | mostrada | ✅ «$1.500» [rc-solicitud-partidas#s3], con las advertencias de vigencia y de diferencia con la Ley 10.702 |
| c05 Requisitos del DNI exprés | **oculta** | Correcto ocultarla: usa secciones del pasaporte exprés y un monto de la ley («$1.700») |
| c06 Unión convivencial y costo | mostrada | ✅ requisitos, pasos y «$?» (no publicado) |
| c07 Personas extranjeras: inscripción de nacimiento | mostrada | ✅ documentación de rc-nacimientos#s2, **sin línea de costo** |
| c08 Costo de la licencia de conducir | abstención | ✅ |
| c09 pizza, c10 presidente de Francia, c11 planilla de «gastos personales» | **fuera de alcance, al instante** | ✅ 3 de 3 |

**Resultado:**
- **6 de 7 respondibles mostradas, las 6 correctas**, incluidos sus costos;
- 1 oculta con razón;
- 4 de 4 sin respuesta en el corpus sin información inventada.
- **Con el prompt nuevo, el modelo no inventó ningún «gratuito».** El control de costos no tuvo que quitar ninguna línea en este conjunto.

**Sin regresiones** en los conjuntos anteriores (textos guardados del prompt anterior, re-evaluados con las reglas nuevas):
- 16 preguntas de `questions_heldout`: siguen las 10 mostradas, y **se quitan las 3 líneas de costo inventadas** (h04, h07, h09).
- 14 originales: siguen las 6 mostradas, y **se quita el costo inventado de la q05**.
- Ningún costo correcto («gratuito» de q02, q04, h02 y h03; «determinado por Re.Na.Per» de q13 y h05; «$?» de h06 y h10) se quitó.

**Pruebas: 202 aprobadas, 0 fallidas.** Hay tests nuevos de costos (montos, «gratuito» con y sin montos, «no publicado», documento sin costos), de respuestas cortas, de marcas de cita y de alcance (asado y «ejemplo de código»).

**Limitaciones que siguen:**
- Las correcciones 4 y 5 salieron del conjunto nuevo: **solo están validadas sobre los textos ya guardados**, no con un cuarto conjunto.
- La verificación sigue siendo léxica: una respuesta correcta parafraseada puede ocultarse (la q08 de la Fase 5) y un dato inventado que copie palabras del documento podría pasar.
- El benchmark de tiempos se midió con el prompt anterior (prefijo de 15.807 tokens). El nuevo es apenas más largo (868 MB de K/V contra 865), así que las conclusiones de tiempo no cambian.
- En `data/caches/` quedan las cachés de prompts anteriores, varios GB que se pueden borrar.

**Criterio de aprobación de la Fase 6:** se cumple (ver arriba). **Fase aprobada por el usuario el 2026-10-18.**

## Fase 7 — Guía de exposición (2026-10-18)

**Pedido del usuario:**
- exposición de 30 a 40 minutos;
- cinco integrantes (Nelson, Martin, Jero, Ramiro y Carlos) con tiempos parejos;
- formato de clase dinámica, no lineal;
- Nelson explica el código, Jero presenta CAG y Martin tiene una parte más fuerte;
- **sin el apartado de costos económicos**, porque no es relevante para la materia;
- la **demo al final y por separado**;
- **dos versiones**: una dinámica y otra por bloques.

Formato elegido: guías en el repositorio y diapositivas como presentación web.

### Archivos

| Archivo | Contenido |
|---|---|
| `docs/exposicion/README.md` | Comparación de las dos versiones; reparto de tiempo por integrante; lista de control de la demo (arranque ~70 s antes, «En línea», zoom); guion de la demo con una pregunta por integrante; plan B con capturas; 15 preguntas probables del público, con quién responde cada una |
| `docs/exposicion/version_A_dinamica.md` | Versión A: 11 segmentos con relevos, tres preguntas al público, una votación que se resuelve más tarde y un diálogo Carlos ↔ Jero («¿Y esto no es RAG?»). Usa como hilo la pregunta del nacimiento. Parte 1 ~30 min + demo ~8 min |
| `docs/exposicion/version_B_bloques.md` | Versión B: apertura de Nelson y cinco bloques seguidos (Jero, Nelson, Ramiro, Martin, Carlos), cada uno con un momento de interacción y una frase de pase. Parte 1 ~31 min + demo ~8 min |
| `docs/exposicion/contenido_tecnico.md` | Material común: cifras con su fuente, CAG según el paper y el repositorio de referencia, atención y caché KV, tabla de la §8, `answer()` comentado, arquitectura y flujo en Mermaid, capas contra la invención y el camino de los modelos |
| `app/evaluation/charts.py` | Genera `docs/img/respuesta_cag_vs_baseline.svg` y `docs/img/punto_de_equilibrio.svg` desde el JSON del benchmark (paleta categórica validada con el validador de la guía de visualización) |
| `docs/img/demo/01…06_*.jpg` | Capturas reales de la app con el 7B (2026-10-18): inicio, borrador en vivo, respuesta con fuentes, fuera de alcance, abstención y costo |

**Presentaciones web** (privadas hasta que se compartan desde el menú Compartir):
- Versión A: https://claude.ai/artifact/FB4xod6t5HCJYtivaTECXY
- Versión B: https://claude.ai/artifact/GQMYoSsVy6yVU7wVcvAach

La A tiene 25 diapositivas y la B 31, con el orador marcado en cada una, notas para quien habla, los dos gráficos, las capturas y una diapositiva de plan B.

**Versión elegida: B (por bloques).** A pedido del usuario, el código se amplió a ~9 min. Recorre el sistema de punta a punta con el código real:
- ingesta (`ingest.py`, descarga, parser, hashes y versiones);
- corpus (`split_markdown`, `_render_block`);
- prefijo (`prompt.py`);
- construcción y guardado de la caché (`_prepare_locked`, `_save`, `cache_id`);
- carga desde disco (`_load`, validación y huella);
- respuesta (`answer`).

Para emparejar tiempos, se reparte en dos bloques seguidos:
- Ramiro (bloque 2, 7 min): arquitectura, borrador en vivo, ingesta y corpus;
- Nelson (bloque 3, 5,5 min + 1,5 de apertura): prefijo, caché y respuesta.

Jero, Martin y Carlos quedan con 6 min cada uno y la demo con ~7.

**Guardado y versión C (2026-10-19):**
- La presentación B quedó copiada en `docs/exposicion/presentacion_B/` (31 diapositivas con notas) y su guion completo, con lo que dice cada integrante, en `docs/exposicion/guion_B.md`.
- Se agregó la **versión C, por temas**: qué es CAG → ventajas, desventajas y limitaciones → stack de los datos → stack del modelo y la app → código → demostración.
  - 6,5 min por integrante: Jero, Carlos, Martin, Ramiro y Nelson.
  - Diapositivas: https://claude.ai/artifact/WRjZe6Ykmg9npV7FYXza4w (copia en `presentacion_C/`).
  - Guía en `version_C_temas.md` y guion en `guion_C.md`.
  - Las diapositivas nuevas (ventajas, desventajas, limitaciones, los dos stacks y «por qué estas piezas») usan solo cifras de esta bitácora, del paper y de `requirements.txt`.

**Diseños (2026-10-19):**
- **Diseño 1 (oscuro):** B y C pasaron a un estilo oscuro en sus mismos links.
- **Diseño 2 (glassmorphism):** a pedido del usuario se crearon versiones nuevas sin borrar las anteriores, para elegir después.
  - Fondo `#0B0F19` con brillos sutiles, tarjetas de vidrio translúcidas con desenfoque, íconos geométricos y tipografía Sora + Manrope.
  - B: https://claude.ai/artifact/JV9mDvsr8NXSAuDbrPqDdW (copia en `presentacion_B2/`).
  - C: https://claude.ai/artifact/RTqiumNMqwUj8oZyQRoLXB (copia en `presentacion_C2/`).
- `charts.py` admite `--oscuro` y genera `docs/img/*_oscuro.svg` con los pasos oscuros de la paleta, el naranja primero y validados sobre `#141414`: todas las comprobaciones aprobadas, peor par CVD ΔE 9,4.
- **Arreglo:** 7 diapositivas de B y 5 de C (las que tienen bloques de código) quedaban bloqueadas en el editor. La causa eran comillas mal escapadas por el script del diseño 1. Se corrigieron en los dos diseños.
- **Diseño 2 rediseñado a pedido del usuario:** más futurista y sin violeta, siguiendo una imagen de referencia.
  - Negro con líneas finas y círculos de fondo, y tarjetas con esquinas marcadas.
  - Íconos en cuadrados rojos, acento rojo anaranjado `#FF4D2E` y ámbar para las advertencias.
  - Tipografía Chakra Petch + Space Grotesk.

### Datos que se verificaron para la exposición
- **Paper** (arXiv 2412.15605): precarga, inferencia sin recuperación y reinicio truncando los tokens nuevos. La ventaja de CAG frente a RAG se achica al crecer el corpus (en HotPotQA grande, RAG supera a CAG en BERTScore). No se le atribuye al paper nada que no diga.
- **Repositorio `hhhuang/CAG`**: `DynamicCache` con una pasada y `clean_up()` que recorta las K/V al largo original antes de cada pregunta.
- **Cifras**: todas salen de esta bitácora y de `data/results/`. Se cambiaron dos ejemplos que no estaban registrados por otros que sí lo están: la contradicción del pasaporte de menores (Fase 2) y los «trámites inventados con citas falsas» (Fase 5).

### Lo que mostraron las capturas
- Respuesta del nacimiento: **3 min 1 s**. Llegó al límite de largo y la última línea quedó cortada; la app lo avisa.
- Abstención (licencia): **36 s**. El borrador mencionó «la Subsecretaría de Tránsito y Transporte», que no está en el corpus, y al terminar se reemplazó por el mensaje fijo. Es un buen ejemplo de por qué el borrador dice «sin verificar».
- Costo del nacimiento: **41 s**, «gratuito» con la cita `rc-nacimientos#s5`.
- Asado: fuera de alcance, al instante.

### Limitaciones
- Los tiempos por integrante son estimados: hay que ensayar con reloj.
- La demo depende de la PC: si hay otros programas abiertos, la respuesta del nacimiento puede pasar de 3 minutos. El plan B cubre ese caso.
- Las presentaciones web no están en el repositorio. El contenido de las diapositivas está en las guías.

### Pruebas
202 aprobadas, 0 fallidas. En esta fase solo se agregó `charts.py`, que no cambia la aplicación.

**Criterio de aprobación de la Fase 7:** guía con duración, reparto parejo, diapositivas, demo con plan B y preguntas probables. Queda a la espera de la aprobación del usuario.
