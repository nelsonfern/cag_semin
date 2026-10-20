# Versión A: clase dinámica

La exposición es una **clase**, no una lectura en orden. Hay un caso que se usa de punta a punta
(el hilo), preguntas al público, un diálogo entre integrantes y relevos cortos: cada uno habla dos
o tres veces y nadie habla más de 4 minutos seguidos.

**El hilo:** «¿Qué documentación tengo que llevar para inscribir el nacimiento de mi hijo?». Se
muestra la respuesta real al principio y se vuelve a ella en cada parte: de qué documento salió
(Martin), cómo la pudo leer el modelo tan rápido (Jero, Nelson, Carlos), por qué se puede creer
(Martin).

**Duración:** parte 1 ~30 min + parte 2 (demo) ~8 min = **~38 min**. Si hay que recortar, los
segmentos marcados con ✂ tienen una versión corta.

| Integrante | Segmentos | Total |
|---|---|---|
| Nelson | 1, 6, 11 + cierre de la demo | ~7 min |
| Martin | 2, 9 + pregunta en la demo | ~7 min |
| Jero | 3, 4, 5 + pregunta en la demo | ~6,5 min |
| Carlos | 5, 7, 10 + pregunta en la demo | ~7 min |
| Ramiro | 8 + conduce la demo | ~3 min + ~5 min |

## Parte 1: la clase (~30 min)

### 1 · Nelson · Apertura (1,5 min)
- **Pregunta al público** (a mano alzada): «¿Quién tuvo que hacer un trámite y no sabía qué
  papeles llevar?». Dejar que respondan dos o tres.
- Mostrar la **captura real** de la respuesta del hilo (diapositiva). «Esto lo respondió un modelo
  de lenguaje corriendo en una PC común, sin internet y sin GPU, citando el documento oficial.»
- Presentar el tema en una frase: «Hoy vamos a explicar cómo: se llama **CAG**, generación
  aumentada por caché».
- Presentar al equipo y el recorrido: datos → CAG → código → resultados → app → confianza → demo.
- **Pase:** «Pero antes de la IA, el problema son los datos. Martin.»

### 2 · Martin · Los datos: de la web oficial al corpus (3 min)
- El problema real: la información está repartida en **12 páginas oficiales** (Registro Civil y
  Secretaría de Justicia de La Rioja), con formatos distintos.
- Qué se hizo: descarga con registro de URL, fecha y hash; limpieza; división en **82 secciones**
  con un id cada una (`rc-nacimientos#s2`). Así se puede citar una sección exacta.
- **Momento clave:** dos fuentes oficiales se **contradicen**. Para el pasaporte de un menor, la
  ficha del Registro Civil pide la presencia de ambos progenitores y la guía de Justicia dice otra
  cosa. No lo resolvimos a mano: la app muestra las dos fuentes con una advertencia. «Ni las fuentes oficiales son perfectas; por eso cada dato tiene que
  llevar su fuente.»
- Cifra para cerrar: todo eso suma **~15.800 tokens**.
- **Pase:** «¿Y eso es mucho o es poco para un modelo? Jero.»

### 3 · Jero · Pregunta al público (1 min)
- «¿Cuánto creen que tarda esta PC en **leer** esos 15.800 tokens antes de poder contestar?»
  Opciones en la diapositiva: **10 segundos / 1 minuto / 10 minutos**. Votación a mano alzada.
- «Guardamos la respuesta para más tarde: Carlos la tiene.»

### 4 · Jero · Qué es CAG (4 min)
- Cómo lee un modelo: cada token, en cada capa, produce **Query, Key y Value**. Un token nuevo
  compara su Query con las Keys de todos los anteriores y mezcla sus Values (atención).
- Lo importante: las K/V de un token **dependen solo de los anteriores**. Las del corpus son
  siempre las mismas, venga la pregunta que venga.
- **Analogía:** leer el libro una vez y quedarse con los apuntes. Para cada pregunta se consultan
  los apuntes, no se relee el libro.
- El paper (Chan et al., 2024, *Don't Do RAG*): tres fases. **Precargar** el corpus en la caché
  KV, **responder** sin búsqueda y **reiniciar** truncando lo que agregó la pregunta.
- Diagrama del flujo (diapositiva): una vez → caché → disco; cada pregunta → solo la pregunta.
- ✂ Versión corta: saltar Q/K/V y quedarse con la analogía y las tres fases.

### 5 · Carlos ↔ Jero · Diálogo: «¿Y esto no es RAG?» (3 min)
Carlos hace de escéptico; Jero responde. Guion aproximado:
- **Carlos:** «Pará, esto ya existe: RAG. Buscás los fragmentos que importan y listo.»
- **Jero:** «RAG busca en cada pregunta y le pasa al modelo solo *k* fragmentos. Si el buscador
  trae el fragmento equivocado, el modelo responde mal aunque la respuesta esté en el corpus.»
- **Carlos:** «¿Y CAG no tiene ese problema?»
- **Jero:** «No hay búsqueda: el modelo ve todo el corpus siempre. El costo es que todo tiene que
  entrar en el contexto.»
- **Carlos:** «¿Y si el corpus fuera enorme?»
- **Jero:** «Ahí RAG gana. El propio paper muestra que la ventaja de CAG se achica con el tamaño.
  Con 15.800 tokens, a nosotros nos entra.»
- **Carlos:** «¿Y no es lo mismo que guardar respuestas en una caché?»
- **Jero:** «No: eso sirve solo si repetís la pregunta igual. Esto guarda la *lectura* del corpus
  y sirve para cualquier pregunta.» (Diapositiva con la tabla de la §8.)
- **Pase (Jero):** «La idea es simple. Lo difícil es que funcione bien en código. Nelson.»

### 6 · Nelson · El código del motor (4 min)
- Mostrar `LlamaCppEngine.answer()` comentado (diapositiva) y recorrerlo en 7 pasos: validar →
  lock → **volver al prefijo** → **verificar la huella** → procesar solo la pregunta → generar
  token por token → **limpiar siempre en el `finally`**.
- `_reset_to_prefix()`: en llama.cpp alcanza con `n_tokens = prefix_len` y `eval([])`. Es el
  «reinicio» del paper, en dos líneas.
- **Pregunta al público:** «¿Qué pasa si **no** limpio la caché entre una pregunta y otra?»
  Dejar que respondan. Respuesta: la segunda pregunta «ve» la anterior; en nuestro control
  negativo arranca con **117 posiciones de más** y sus resultados cambian.
- Cómo sabemos que está bien: la respuesta con caché es **idéntica, token por token**, a procesar
  todo de cero (6 de 6), y la huella SHA-256 detecta cualquier byte alterado.
- **Pase:** «¿Y cuánto se gana con todo esto? Carlos tiene la respuesta a la pregunta de Jero.»

### 7 · Carlos · Lo que medimos (4 min)
- **Revelación:** leer los 15.800 tokens tarda **630 segundos** (10,5 minutos). Con CAG, la
  primera palabra llega a los **8,8 s**: 72 veces menos. ¿Quién había votado 10 minutos?
- Gráfico de barras: una respuesta completa de 128 tokens: **708 s → 87,7 s**. La parte naranja
  (generar) es igual en los dos: **CAG no acelera la escritura**, 0,62 s por token en CPU.
- Gráfico de equilibrio: construir la caché lleva **11 minutos** una vez; **desde la 2.ª consulta**
  ya conviene, y desde la 1.ª si la caché está guardada en disco (se carga en 1 a 10 s).
- Memoria: la caché ocupa **865 MB** (~56 KB por token); la app entera usa ~7 GB de RAM.
- Honestidad: equipo de 16 GB sin GPU; medianas de varias corridas; el baseline se corrió 6 veces
  porque cada una tarda 12 minutos.
- ✂ Versión corta: solo la revelación y el gráfico de barras.

### 8 · Ramiro · La aplicación (3 min)
- Diagrama de arquitectura (diapositiva): navegador (chat en HTML + Alpine.js) → FastAPI →
  control de alcance → motor CAG (llama.cpp + Qwen2.5-7B en 4 bits) → verificación → registro
  documental.
- Detalles que importan: la respuesta llega **en streaming** (SSE) para no esperar en blanco; el
  borrador dice «sin verificar» hasta que termina la verificación; una sola caché → una consulta
  por vez con cola; al arrancar hace una consulta de calentamiento (la primera tardaba 22 s).
- Mostrar la captura del borrador en vivo.
- **Pase:** «Pero un modelo que escribe rápido también puede inventar rápido. Martin.»

### 9 · Martin · Cómo evitamos que invente (4 min)
- Volver al hilo: cada requisito lleva una cita `[rc-nacimientos#s2]`. **El modelo nunca escribe
  un enlace**: escribe un código y la URL, el organismo y las fechas salen del registro.
- Las capas (diapositiva), cada una con **un caso real que frenó**:
  - control de alcance → «¿Cómo hago un ciclo for en Python?» ni llega al modelo;
  - citas validadas → el modelo inventó trámites (licencia, monotributo) con citas falsas;
  - filtro de tema → monotributo «respaldado» con una sección de nacimientos;
  - verificación de frases → requisitos de otro trámite bajo el título equivocado;
  - verificación de costos → «gratuito» cuando el documento no publica costos.
- **Pregunta al público:** «¿Qué es peor para un ciudadano: que la app diga *no sé* o que diga
  algo falso con seguridad?». Por eso la abstención: 12 de 12 preguntas sin respuesta en el corpus
  terminaron sin información inventada.
- Límite honesto: la verificación compara palabras, no significado.

### 10 · Carlos · Lo que salió mal (1,5 min)
- El camino de los modelos: 7B en PyTorch no entraba en la RAM → 1,5B funcionaba pero citaba 1 de
  8 e inventaba trámites → **7B cuantizado a 4 bits con llama.cpp**.
- La lección: **CAG resuelve tener el corpus disponible, no que el modelo sepa usarlo**.

### 11 · Nelson · Conclusiones (1,5 min)
- Tres ideas: (1) con un corpus chico y estable, CAG evita repetir 10 minutos de lectura en cada
  pregunta; (2) la caché tiene que limpiarse y verificarse, si no contamina; (3) la confianza no la
  da el modelo, la da el código alrededor.
- Lo que haríamos con más tiempo: GPU, un esquema híbrido para un corpus grande, verificación por
  significado.
- **Pase a la demo:** «Ahora vamos a verlo funcionando.»

## Parte 2: la demo (~8 min)

La conduce **Ramiro**; cada integrante hace una pregunta. Guion, lista de control y plan B en el
[README](README.md#demo-parte-2-lista-de-control). Resumen:

1. **Ramiro:** la pregunta del hilo. Mientras escribe, explica que solo se procesa la pregunta.
2. **Martin:** «¿Cómo preparo un asado para diez personas?» → fuera de alcance, al instante.
3. **Jero:** «¿Qué necesito para sacar la licencia de conducir?» → abstención.
4. **Carlos:** «¿Tiene costo inscribir un nacimiento?» → «gratuito», citado.
5. **Nelson:** abre «Fuentes» y «Ver fuente oficial», y cierra.
