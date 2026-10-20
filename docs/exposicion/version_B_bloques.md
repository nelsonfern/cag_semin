# Versión B: por bloques

Cada integrante presenta **un bloque seguido** con su tema y, al terminar, pasa al siguiente. Pide
menos ensayo conjunto que la [versión A](version_A_dinamica.md): cada uno prepara su bloque solo.
Para que no sea una lectura, cada bloque tiene **un momento de interacción** (una pregunta al
público o un ejemplo en pantalla) y termina con una frase de pase al siguiente.

El código se muestra **de punta a punta con el código real**, repartido en dos bloques seguidos:
- **Ramiro:** la aplicación por fuera y cómo entran los datos (ingesta y corpus).
- **Nelson:** CAG por dentro (prefijo, construir, guardar y cargar la caché, responder).

**Duración:** parte 1 ~32,5 min + parte 2 (demo) ~7 min = **~39,5 min**.

| Orden | Integrante | Bloque | Tiempo |
|---|---|---|---|
| 0 | Nelson | Apertura | 1,5 min |
| 1 | Jero | Qué es CAG | 6 min |
| 2 | Ramiro | La aplicación y los datos de entrada | 7 min |
| 3 | Nelson | El código de CAG | 5,5 min |
| 4 | Martin | Qué hay en el corpus y cómo evitamos que invente | 6 min |
| 5 | Carlos | Resultados, lo que salió mal y conclusiones | 6 min |
| — | Ramiro (conduce) + todos | **Parte 2: demo** | 7 min |

**Tiempo de exposición por integrante:** Nelson 7 min (apertura + código), Ramiro 7, Jero 6, Martin
6 y Carlos 6. Ramiro además conduce la demo, donde cada uno hace una pregunta.

## Parte 1: la exposición (~32,5 min)

### Apertura · Nelson (1,5 min)
- **Pregunta al público:** «¿Quién tuvo que hacer un trámite y no sabía qué papeles llevar?».
- Mostrar la captura real de la respuesta del nacimiento: un modelo de lenguaje en una PC común,
  sin GPU y sin internet, citando el documento oficial.
- La técnica: **CAG**, generación aumentada por caché. Orden de los bloques. «La demo va al final.»

### Bloque 1 · Jero · Qué es CAG (6 min)
1. **Cómo lee un modelo** (1,5 min): cada token, en cada capa, genera Query, Key y Value. Un token
   nuevo compara su Query con las Keys de los anteriores y mezcla sus Values. Las K/V de un token
   dependen solo de los anteriores: las del corpus son siempre iguales.
2. **La caché KV y el paper** (2 min): guardar esas K/V para no recalcularlas. Analogía: leer el
   libro una vez y quedarse con los apuntes. Chan et al., 2024, *Don't Do RAG*: precargar, responder
   sin búsqueda, reiniciar truncando lo que agregó la pregunta. Diagrama del flujo.
3. **CAG frente a RAG y otras cachés** (2,5 min): RAG busca *k* fragmentos por pregunta y puede
   traer el equivocado; CAG no busca pero necesita que todo entre en el contexto. El paper muestra
   que la ventaja de CAG se achica cuando el corpus crece. Tabla de la §8.
- **Interacción:** «¿Cuánto creen que tarda esta PC en leer los 15.800 tokens? ¿10 segundos, 1
  minuto o 10 minutos?». Votación; la respuesta la da Carlos en el bloque 5.
- **Pase:** «Eso es la idea. Ramiro les muestra cómo está armada la aplicación y de dónde salen los
  datos.»

### Bloque 2 · Ramiro · La aplicación y los datos de entrada (7 min)

| Diapositiva | Qué mostrar | Min |
|---|---|---|
| **Arquitectura** | Navegador (chat HTML + Alpine.js) → FastAPI → control de alcance → motor CAG (llama.cpp + Qwen2.5-7B en 4 bits) → verificación → registro documental. Una sola caché → una consulta por vez con cola de 4; consulta de calentamiento al arrancar (sin ella, la primera tardaba 22 s) | 2 |
| **Borrador en vivo** | Streaming (SSE): cada palabra llega apenas se genera, pero dice «sin verificar» hasta que termina la verificación | 1,5 |
| **El recorrido** | Mapa de las 7 etapas del código: «yo muestro la 1 y la 2, cómo entran los datos; Nelson sigue con CAG» | 0,5 |
| **1 · Ingesta** (`app/ingestion/ingest.py`, `downloader.py`, `parser.py`, `source_registry.py`) | `fetch` respeta `robots.txt` y espera 2 s entre pedidos; un parser por sitio (HTML, JavaScript, PDF; los `<h2>` se marcan `## `); SHA-256 del original y del texto; el manifiesto decide `new` / `updated` / `reparsed` / `unchanged` y guarda `vN.html` + `vN.txt`. Si una descarga falla, se conserva la versión anterior | 1,5 |
| **2 · Corpus** (`app/ingestion/corpus_builder.py`) | `split_markdown` corta en cada `## ` y numera `doc#sN`; `_render_block` agrega título, organismo, fuente y fechas; el texto real del bloque `rc-nacimientos`. `build_id` = hash del texto + tokenizer + configuración | 1,5 |

- **Interacción:** en el borrador, preguntar «¿Por qué creen que dice *sin verificar*?». Respuesta:
  se verifica recién cuando el texto está completo; en una prueba, el borrador nombró un organismo
  que no está en el corpus y al final se reemplazó por la abstención.
- **Pase:** «Este texto es lo que va a la caché. Nelson les muestra cómo.»

### Bloque 3 · Nelson · El código de CAG (5,5 min)

| Diapositiva | Archivo | Qué mostrar | Min |
|---|---|---|---|
| **3 · Prefijo** | `app/cag/prompt.py` | Instrucciones + corpus + reglas y ejemplos dentro de la plantilla ChatML = ~15.800 tokens que se cachean; la pregunta va aparte (~20 tokens) | 1 |
| **4 · Construir y guardar** | `app/cag/llamacpp_engine.py` (`_prepare_locked`, `_save`) | Primero intenta cargarla; si no hay una válida, `llm.eval(prefix_ids)` una vez (~11 min) y `save_state` → `state.bin` (~868 MB) + `meta.json`, en una carpeta temporal que se renombra al final. El `cache_id` es el hash de modelo + revisión + cuantización + prefijo | 1,5 |
| **5 · Cargar desde disco** | `llamacpp_engine.py` (`_load`) | Compara `meta.json` con el modelo y el prefijo actuales, carga `state.bin` con `load_state` y recalcula la huella SHA-256. Si algo no coincide, la descarta y la reconstruye. 1 a 10 s en vez de 11 min | 1 |
| **6 · Responder** | `llamacpp_engine.py` (`answer`) | Los siete pasos: validar, lock, volver al prefijo, verificar la huella, procesar solo la pregunta, generar token por token, limpiar siempre en el `finally` | 1,5 |
| **7 · ¿Está bien?** | `tests/`, Fase 6 | «¿Qué pasa si no limpio la caché?»; 117 posiciones de más; 6 de 6 respuestas idénticas con y sin caché; huella SHA-256 | 0,5 |

- **Interacción:** en la etapa 7, preguntar «¿Qué pasa si no limpio la caché entre preguntas?».
- **Pase:** «¿Y qué sabe el asistente, y cómo evitamos que invente? Martin.»

### Bloque 4 · Martin · Qué hay en el corpus y cómo evitamos que invente (6 min)
1. **El corpus** (1,5 min): 12 documentos oficiales (Registro Civil y Secretaría de Justicia de La
   Rioja, páginas nacionales de argentina.gob.ar y la Ley Impositiva), 82 secciones con id, ~15.800
   tokens. Ramiro mostró cómo se arma; acá, qué contiene y por qué cada sección tiene id: para poder
   citarla.
2. **Las fuentes se contradicen** (1 min): pasaporte de un menor entre el Registro Civil y
   Justicia; la app muestra las dos con advertencia.
3. **Las capas de control** (2,5 min), cada una con el caso real que frenó: alcance (ciclo for en
   Python), citas desde el registro (el modelo nunca escribe un enlace), filtro de tema
   (monotributo con una sección de nacimientos), verificación de frases, verificación de costos
   («gratuito» sin respaldo).
4. **Abstención y límites** (1 min): 12 de 12 preguntas sin respuesta en el corpus, sin
   información inventada. La verificación compara palabras, no significado.
- **Interacción:** «¿Qué es peor para un ciudadano: que la app diga *no sé* o que diga algo falso
  con seguridad?».
- **Pase:** «¿Y todo esto cuánto rinde? Carlos.»

### Bloque 5 · Carlos · Resultados, lo que salió mal y conclusiones (6 min)
1. **La respuesta a la votación** (1,5 min): leer el corpus tarda **630 s**; con CAG la primera
   palabra llega a los **8,8 s** (72 veces menos).
2. **Los gráficos** (2 min): respuesta de 128 tokens, 708 s → 87,7 s, con la generación igual en
   los dos (0,62 s por token: CAG no acelera la escritura); punto de equilibrio desde la 2.ª
   consulta, o la 1.ª con la caché en disco.
3. **Lo que salió mal** (1,5 min): 7B en PyTorch no entraba; 1,5B citaba 1 de 8 e inventaba
   trámites; 7B en 4 bits con llama.cpp. CAG resuelve tener el corpus disponible, no que el modelo
   sepa usarlo.
4. **Conclusiones** (1 min): con un corpus chico y estable, CAG evita repetir 10 minutos de
   lectura por pregunta; la caché hay que limpiarla y verificarla; la confianza la da el código
   alrededor del modelo.
- **Pase a la demo:** «Ahora, verlo funcionando.»

## Parte 2: la demo (~7 min)

La conduce **Ramiro** y cada integrante hace una pregunta. Guion, lista de control y plan B en el
[README](README.md#demo-parte-2-lista-de-control).
