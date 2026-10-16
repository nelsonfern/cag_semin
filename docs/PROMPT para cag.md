# TramitaIA: CAG real, fuentes oficiales de La Rioja y aplicación funcional

Actuá como un ingeniero senior especializado en LLM, Cache-Augmented Generation (CAG), Python, recuperación de información y desarrollo de aplicaciones.

Quiero desarrollar **TramitaIA**, un asistente que ayude a los ciudadanos a entender cómo realizar trámites públicos de la Provincia de La Rioja, Argentina.

El proyecto tiene dos objetivos inseparables:

1. Construir una aplicación funcional y útil basada en información oficial real de La Rioja.
2. Implementar y estudiar CAG de forma técnicamente rigurosa, para poder explicar su funcionamiento, código, tiempos, memoria y costos en una exposición universitaria de 20–30 minutos.

CAG debe ser el centro técnico del proyecto. RAG se utilizará como referencia comparativa secundaria, no como eje principal.

No construyas únicamente un chatbot que agrega documentos a un prompt. La implementación debe permitir identificar, explicar y probar qué estado se precalcula, qué caché se reutiliza y qué cálculos se ejecutan durante cada consulta.

## 1. Fuentes documentales oficiales

El sistema debe trabajar con documentación auténtica, verificable y atribuible a su organismo emisor.

Comenzá investigando estas fuentes:

### Fuentes provinciales

1. Registro Civil de La Rioja:
   https://registrocivil.larioja.gob.ar/

2. Guía de trámites del Registro Civil:
   https://registrocivil.larioja.gob.ar/guia-tramites.html

3. Solicitud de partidas:
   https://registrocivil.larioja.gob.ar/tramite-solicitud-partidas.html

4. Secretaría de Justicia de La Rioja:
   https://secretariadejusticia.larioja.gob.ar/

5. Consulta de leyes de la Legislatura de La Rioja:
   https://legislaturalarioja.gob.ar/consulta-de-leyes/leyes/

6. Normativa publicada por la Legislatura:
   https://www.legislaturalarioja.gob.ar/normativa.php

### Fuentes nacionales complementarias

7. Portal de trámites nacionales:
   https://www.argentina.gob.ar/tramitar

8. Requisitos nacionales para DNI y pasaporte:
   https://www.argentina.gob.ar/interior/dni/requisitos-para-tramites-de-dni-o-pasaporte

Estas URLs son puntos de partida, no una garantía de que todas las páginas estén actualizadas ni de que todos los documentos puedan descargarse automáticamente.

### Estrategia de recopilación

Antes de programar el scraper:

- Inspeccioná las páginas y determiná si contienen información HTML, enlaces a PDF, formularios o servicios externos.
- Identificá cuáles son accesibles y cuáles requieren navegación adicional.
- Preferí las páginas de detalle de cada trámite y los documentos oficiales completos.
- No uses páginas de terceros como autoridad principal cuando exista una fuente oficial.
- No inventes documentos, URLs, requisitos, tasas ni fechas.
- No intentes eludir autenticación, CAPTCHA o controles de acceso.
- Respetá las condiciones de uso, los límites de solicitudes y las indicaciones del sitio.
- Registrá las fuentes que no se puedan obtener automáticamente y permití importarlas manualmente.

Para la primera versión, seleccioná aproximadamente 5–10 trámites del Registro Civil y de la Secretaría de Justicia. Ampliá el corpus solamente después de comprobar que el pipeline funciona correctamente.

Ejemplos iniciales de temas:

- Solicitud de partidas de nacimiento, matrimonio y defunción.
- DNI nuevo ejemplar.
- DNI de recién nacido.
- Pasaporte.
- Rectificación de partidas.
- Inscripción de matrimonios.
- Unión convivencial.

Confirmá cuáles de estos trámites cuentan efectivamente con documentación oficial accesible antes de incorporarlos.

## 2. Registro y trazabilidad documental

Cada documento debe conservar sus metadatos.

Usá una estructura similar a:

- `document_id`
- `title`
- `organism`
- `source_url`
- `local_path`
- `document_type`
- `publication_date`
- `last_updated_date`
- `retrieved_at`
- `content_hash`
- `status`
- `version`
- `notes`

Las fechas desconocidas deben permanecer vacías. No confundas la fecha de descarga con la fecha de publicación o de actualización del organismo.

Conservá el texto original descargado siempre que sea legal y técnicamente apropiado. Para PDF, extraé el texto con una herramienta adecuada y registrá los errores de extracción. Para HTML, conservá la URL y el título de la página.

Implementá un manifiesto documental que permita saber exactamente qué versión del corpus se utilizó para construir una caché.

Si cambia un documento:

1. Detectá el cambio mediante un hash del contenido.
2. Registrá la nueva versión.
3. Marcá la caché anterior como desactualizada.
4. Reconstruí la caché cuando corresponda.
5. Conservá un registro de la fecha de actualización.

No afirmes que el corpus está actualizado automáticamente si no existe un proceso de actualización implementado.

## 3. Arquitectura técnica centrada en CAG

Separá claramente la aplicación ciudadana del motor de inferencia y del pipeline documental.

Arquitectura sugerida:

- Frontend web.
- API FastAPI.
- Servicio de consultas.
- Registro y almacenamiento documental.
- Pipeline de ingesta y actualización.
- Motor CAG.
- Caché KV del modelo.
- Servicio LLM.
- Registro de fuentes y citas.
- Evaluación y benchmark.

Utilizá Python y dependencias compatibles entre sí. Preferí Hugging Face Transformers para la implementación educativa principal de CAG porque permite controlar explícitamente el estado de atención cuando la arquitectura del modelo lo soporta.

Ollama puede utilizarse como alternativa de inferencia local, pero investigá y documentá sus capacidades reales antes de afirmar que permite guardar, restaurar y reutilizar una KV cache arbitraria.

No simules CAG mediante una variable que almacena texto ni mediante una simple caché de respuestas.

## 4. Implementación real de CAG

Implementá un pipeline que permita explicar el proceso completo.

### Fase A: preparación

- Seleccionar documentos oficiales.
- Extraer y limpiar el contenido.
- Eliminar duplicados sin perder trazabilidad.
- Ordenar el corpus de forma reproducible.
- Controlar el tamaño del contexto.
- Tokenizar usando el tokenizer correcto del modelo.
- Registrar la cantidad de documentos y tokens.

No trunques silenciosamente los documentos que excedan el límite de contexto. Informá qué contenido se excluye y por qué.

### Fase B: construcción de la caché

- Cargar un modelo compatible.
- Preparar el contexto documental.
- Procesarlo y construir el estado KV.
- Conservarlo en memoria de manera reutilizable.
- Documentar la estructura de la caché.
- Registrar el tiempo de preparación y la memoria utilizada.

Explicá la relación entre atención, matrices Key y Value, tokens del prefijo y reutilización del estado calculado.

### Fase C: consulta

Cuando el ciudadano formule una pregunta:

1. Recibir la pregunta en FastAPI.
2. Validar que sea una consulta relacionada con el alcance de TramitaIA.
3. Reutilizar el estado KV del corpus.
4. Incorporar la pregunta como continuación independiente del prefijo documental.
5. Manejar correctamente las posiciones, máscaras de atención y tokens nuevos requeridos por el modelo.
6. Generar una respuesta.
7. Asociar las afirmaciones a fuentes verificables del corpus.
8. Devolver la respuesta con enlaces y metadatos de las fuentes.

Cada consulta independiente debe partir del estado base correcto. No permitas que la pregunta anterior ni sus tokens de generación contaminen la siguiente.

No asumas que un modelo admite cualquier forma de `past_key_values`. Verificá las APIs, las versiones y los requisitos de su arquitectura.

Si no se puede garantizar la reutilización correcta de la caché en la implementación elegida, documentá el problema y resolvelo antes de presentar el resultado como CAG.

## 5. Cómo fundamentar las respuestas

TramitaIA debe responder con información oficial real, no con ejemplos inventados.

El prompt del modelo debe exigir que:

- Utilice el contexto documental proporcionado.
- No invente requisitos, costos, plazos ni oficinas.
- Distinga información provincial de información nacional.
- Indique cuándo falta información suficiente.
- Señale contradicciones entre documentos.
- No afirme que una norma sigue vigente si no se pudo comprobar.
- Recomiende consultar el organismo oficial cuando la información sea insuficiente o dudosa.

Las citas deben construirse a partir del registro de documentos y no depender exclusivamente de que el LLM genere una URL.

Cada respuesta debe poder mostrar, cuando corresponda:

- Nombre del trámite.
- Requisitos documentados.
- Pasos para realizarlo.
- Costos publicados, con fecha y advertencia si no se pudo confirmar su vigencia.
- Organismo responsable.
- Enlace oficial.
- Fecha de actualización conocida.
- Fuentes que respaldan la respuesta.

No presentes el sistema como asesoría legal oficial ni como sustituto de la autoridad administrativa.

## 6. Interfaz funcional

Construí una interfaz sencilla, clara y usable en español rioplatense.

Debe incluir:

- Campo para escribir preguntas.
- Respuestas legibles y estructuradas.
- Enlaces a fuentes oficiales.
- Indicador de que se está procesando la consulta.
- Mensajes cuando la información no está disponible.
- Panel de fuentes consultadas.
- Sección informativa sobre el alcance y las limitaciones del sistema.
- Indicador de la fecha de actualización conocida del corpus.

Incluí ejemplos de preguntas como:

- ¿Cómo solicito una partida de nacimiento en La Rioja?
- ¿Qué requisitos publica el Registro Civil para este trámite?
- ¿Dónde puedo consultar la fuente oficial?
- ¿Qué información falta para responder con seguridad?

Estas preguntas sirven para probar la aplicación; las respuestas deben derivarse de los documentos obtenidos, no estar codificadas manualmente.

## 7. Benchmark: tiempos, memoria y costos

La evaluación debe ayudar a explicar cuándo resulta útil CAG.

Implementá, sobre el mismo corpus y modelo, al menos dos modos:

A. Baseline sin caché reutilizable: procesar el contexto documental completo en cada consulta.

B. CAG: procesar el corpus una vez y reutilizar el estado KV para consultas posteriores.

Como comparación secundaria, podés implementar un RAG básico con recuperación de fragmentos, siempre que no retrase el desarrollo del motor CAG.

Medí:

- Tiempo de descarga y preparación documental.
- Tiempo de construcción de la KV cache.
- Latencia de la primera consulta.
- Latencia de consultas posteriores.
- Tiempo hasta el primer token, si puede medirse correctamente.
- Tiempo total de generación.
- Tokens de entrada y salida.
- RAM y VRAM utilizadas.
- Calidad y exactitud de las respuestas.
- Validez de las citas.
- Comportamiento ante preguntas sin respuesta en el corpus.

Realizá varias repeticiones y reportá medianas y percentiles o rangos. Separá el costo de cargar el modelo del costo de procesar el corpus y del costo de generar respuestas.

Calculá el punto de equilibrio usando los resultados medidos:

Costo acumulado de CAG = preparación inicial + costo por consulta CAG × número de consultas.

Costo acumulado del baseline = costo por consulta sin caché × número de consultas.

Si CAG no ofrece una ventaja en el hardware utilizado, explicá las causas. No inventes benchmarks ni prometas porcentajes de mejora.

En el apartado económico, diferenciá ejecución local, costos de hardware, electricidad, tiempo de mantenimiento y tarifas de proveedores de API cuando corresponda.

## 8. Fuentes académicas y explicación técnica

Utilizá como punto de partida:

Artículo original:
https://arxiv.org/abs/2412.15605

Repositorio de referencia:
https://github.com/hhhuang/CAG

Documentación oficial de Transformers:
https://huggingface.co/docs/transformers/

Documentación de Ollama:
https://github.com/ollama/ollama/blob/main/docs/api.md

Verificá las afirmaciones técnicas contra las fuentes originales. No atribuyas al artículo una funcionalidad que no hayas comprobado.

Explicá especialmente la diferencia entre:

- KV cache.
- Prompt caching.
- Caché de respuestas.
- Almacenamiento de documentos.
- Índice vectorial.
- Recuperación RAG.

## 9. Organización del proyecto

Usá una estructura modular similar a:

- `app/main.py`
- `app/api/routes.py`
- `app/ingestion/source_registry.py`
- `app/ingestion/downloader.py`
- `app/ingestion/parser.py`
- `app/ingestion/corpus_builder.py`
- `app/cag/model_loader.py`
- `app/cag/cache_builder.py`
- `app/cag/engine.py`
- `app/services/citations.py`
- `app/services/answer_service.py`
- `app/evaluation/benchmark.py`
- `app/evaluation/questions.json`
- `data/raw/`
- `data/processed/`
- `data/manifest.json`
- `tests/`
- `frontend/`
- `README.md`
- `.env.example`

Adaptá esta estructura cuando sea necesario, sin mezclar ingesta documental, construcción de caché, generación, citas e interfaz en un solo archivo.

Incluí endpoints apropiados, por ejemplo:

- `GET /health`
- `GET /sources`
- `POST /chat`
- `POST /admin/ingest`
- `POST /admin/rebuild-cache`
- `GET /evaluation/results`

Protegé las operaciones administrativas y evitá que cualquier usuario pueda iniciar descargas o reconstrucciones costosas sin control.

## 10. Material para la exposición

Además de la aplicación, prepará una guía para explicar CAG durante 20–30 minutos.

Debe incluir:

1. Problema que resuelve.
2. Definición de CAG.
3. Atención y KV cache.
4. Preparación del corpus real de La Rioja.
5. Explicación del código que construye y reutiliza la caché.
6. Demostración de preguntas reales.
7. Medición de latencia y memoria.
8. Costos y punto de equilibrio.
9. Comparación breve con RAG.
10. Limitaciones, mantenimiento y conclusiones.

Incluí un guion oral, un esquema de arquitectura, un fragmento de código central explicado paso a paso, preguntas que podrían hacerme y respuestas fundamentadas.

## 11. Orden de trabajo

No generes toda la aplicación de una sola vez sin validar sus componentes.

Primero inspeccioná el repositorio existente y presentá una propuesta breve de arquitectura.

Luego trabajá por etapas:

1. Verificación de fuentes oficiales.
2. Ingesta y registro de documentos reales.
3. Preparación reproducible del corpus.
4. Selección del modelo y prueba mínima de KV cache.
5. Implementación CAG.
6. Pruebas de aislamiento entre consultas.
7. Integración con FastAPI y la interfaz.
8. Citas y validación documental.
9. Benchmark.
10. Guía de exposición y documentación.

Al finalizar cada etapa, ejecutá las pruebas y documentá los resultados.

El objetivo es entregar una **TramitaIA funcional, alimentada por documentación oficial verificable de La Rioja, y una implementación de CAG que pueda explicar técnicamente y evaluar con datos reales**.

## 12. Desarrollo estrictamente por fases y criterios de aprobación

Trabajá en una fase por vez. No intentes implementar todo el proyecto en una sola respuesta o en una única modificación masiva.

### Reglas de trabajo

1. Antes de empezar, inspeccioná el repositorio existente y detectá qué está implementado, qué funciona y qué falta. No sobrescribas código existente sin necesidad.
2. Presentá un plan breve de la fase actual y los archivos que vas a crear o modificar.
3. Implementá únicamente lo necesario para completar esa fase.
4. Ejecutá las pruebas y verificaciones pertinentes.
5. Informá qué funciona, qué no funciona, qué decisiones técnicas tomaste y qué limitaciones quedan.
6. No marques una fase como terminada si sus criterios de aceptación no se cumplen.
7. Si aparece un error que bloquea la fase, investigalo y corregilo antes de avanzar.
8. No simules funcionalidades para declarar una fase terminada.
9. No inventes resultados de pruebas, documentos obtenidos ni mediciones.
10. Conservá un archivo `PROGRESS.md` con el estado de cada fase, decisiones tomadas, comandos ejecutados, pruebas aprobadas y tareas pendientes.

### Criterios de aprobación

**Fase 1 — Fuentes e ingesta:** al menos cinco documentos o páginas oficiales reales, con URL, organismo, fecha de obtención y contenido extraído verificable. Si no se pueden obtener cinco fuentes válidas, documentá el bloqueo y no inventes contenido.

**Fase 2 — Corpus:** extracción reproducible, metadatos conservados, duplicados controlados y cantidad de tokens registrada.

**Fase 3 — Prueba CAG:** demostración mínima reproducible en la que el estado KV del prefijo documental se reutiliza correctamente para dos preguntas independientes. Verificá que no se incorporen tokens de la primera respuesta a la segunda.

**Fase 4 — Motor CAG:** pruebas automatizadas de reutilización, manejo de errores, límites de contexto y aislamiento entre consultas.

**Fase 5 — TramitaIA:** aplicación ejecutable que responda sobre los documentos disponibles, muestre sus fuentes y se abstenga cuando no tenga respaldo suficiente.

**Fase 6 — Benchmark:** mediciones realmente ejecutadas y reproducibles, con configuración del equipo, modelo, versiones, corpus, repeticiones y resultados. Si alguna métrica no puede obtenerse, explicá por qué.

**Fase 7 — Exposición:** guía de 20–30 minutos basada en el código y los resultados reales del proyecto.

No empieces la fase siguiente hasta que la fase actual esté aprobada. Si una decisión arquitectónica obliga a revisar una fase anterior, explicá el motivo y actualizá `PROGRESS.md`.

Al finalizar cada fase, detenete y presentá un resumen de resultados y el siguiente paso propuesto. Continuá solamente cuando el usuario te indique que avances.