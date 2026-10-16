# Bitácora de TramitaIA (PROGRESS.md)

Registro del estado de cada fase, decisiones técnicas, comandos ejecutados,
pruebas aprobadas y tareas pendientes. Cada fase cierra con un commit.

## Estado de fases

| Fase | Descripción | Estado |
|------|-------------|--------|
| 0 | Inicialización del repositorio | Completada |
| 1 | Fuentes e ingesta | Implementada — esperando aprobación |
| 2 | Corpus reproducible | Pendiente |
| 3 | Prueba mínima de KV cache | Pendiente |
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
| leg-ley-10929 | Legislatura LR | provincial | `manual_pending` (404) | — |

Una segunda corrida inmediata dio `unchanged` en los 11 documentos y la misma `corpus_version`: la detección de cambios no genera versiones falsas.

**Observaciones para fases siguientes**
- Ya aparece una diferencia entre fuentes: para el pasaporte de menores, la ficha del Registro Civil pide la «presencia de ambos progenitores o tutor legal», mientras que la guía de Justicia menciona «el DNI de los padres o tutores legales que lo acompañen». Es un caso útil para probar que el sistema señale contradicciones (§5).
- El documento nacional (≈32,5 mil caracteres) es más grande que todo el corpus provincial junto. En la Fase 2 hay que decidir si entra completo o solo las secciones relevantes, informando lo que se excluye.
- Los costos de partidas citan la Ley 10.929, que no se pudo obtener; su vigencia no está verificada.

### 4. Comandos ejecutados
```bash
py -3.12 -m venv .venv
.venv/Scripts/python -m pip install requests beautifulsoup4 pypdf json5 pytest
.venv/Scripts/python -X utf8 -m app.ingestion.ingest run      # dos veces (new / unchanged)
.venv/Scripts/python -X utf8 -m app.ingestion.ingest status
.venv/Scripts/python -m pytest
```

### 5. Pruebas — 31 aprobadas, 0 fallidas
- `tests/test_source_registry.py`: versiones new/unchanged/updated, el fallo conserva la versión buena, `corpus_version` estable, fechas vacías, marcado de cachés desactualizadas, guardar y recargar, ids duplicados, validez de `sources.json`.
- `tests/test_parser.py`: los 4 parsers con fragmentos sintéticos, fechas inválidas reportadas (no inventadas), PDF inválido o sin texto, normalización.
- `tests/test_downloader.py`: URL bloqueada por robots no se descarga, caché de `robots.txt`, se respeta `Crawl-delay`.
- `tests/test_corpus_real.py` (**criterio de aprobación**): ≥5 documentos oficiales `.gob.ar` con URL, organismo, título y `retrieved_at`; originales y textos presentes con hashes coincidentes; texto sustantivo (≥500 caracteres); fechas del organismo válidas y no posteriores a la descarga; fuentes no obtenidas sin contenido inventado.

### 6. Criterio de aprobación de la Fase 1
> ≥ 5 documentos oficiales reales con URL, organismo, fecha de obtención y contenido extraído verificable.

**Se cumple:** hay 11 documentos de 3 organismos oficiales (2 provinciales y 1 nacional), con originales y textos versionados y hashes verificables. Queda pendiente la aprobación del usuario.

### Limitaciones y pendientes
- No hay actualización periódica automática: el corpus se actualiza solo cuando se corre `ingest run`.
- `nac-portal-tramitar` y `leg-ley-10929` requieren importación manual.
- Los PDF de IGJ y del Servicio Penitenciario que enlaza la Secretaría de Justicia no se descargaron porque están fuera de los trámites elegidos. El parser `pdf` ya está disponible para ellos.
- **Para la Fase 3:** un CAG real necesita acceso al estado KV del modelo (Transformers en una PC propia o remota). Las APIs comerciales ofrecen *prompt caching* gestionado por el proveedor, que es un concepto distinto (§8). Esto condiciona la elección entre «API» y «PC potente».
