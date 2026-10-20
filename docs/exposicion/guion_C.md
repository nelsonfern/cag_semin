# Guion de la versión C (por temas)

Qué dice cada integrante, diapositiva por diapositiva, en la [presentación C](https://claude.ai/artifact/WRjZe6Ykmg9npV7FYXza4w).
La estructura y los tiempos están en la [guía C](version_C_temas.md).

Cómo usarlo:
- **No hay que leerlo de memoria.** Es una base para decir con tus palabras. Lo importante son las
  ideas en **negrita** y las cifras, que tienen que ser exactas.
- A un ritmo tranquilo se dicen unas 130 palabras por minuto. Si te pasás, cortá lo marcado con ✂.
- Entre corchetes van las acciones: [pasar diapositiva], [señalar], [esperar respuestas].

| Orden | Quién | Bloque | Tiempo |
|---|---|---|---|
| 0 | Nelson | Apertura | 1 min |
| 1 | Jero | Qué es CAG y cómo funciona | 5,5 min |
| 2 | Carlos | Ventajas, desventajas y limitaciones | 6,5 min |
| 3 | Martin | Stack tecnológico I: los datos | 6,5 min |
| 4 | Ramiro | Stack tecnológico II: el modelo y la aplicación | 6,5 min |
| 5 | Nelson | El código de CAG | 5,5 min |
| 6 | Jero | Cierre: conclusiones | 1 min |

Cada integrante expone 6,5 minutos: Nelson abre y muestra el código, y Jero explica CAG y cierra.
| — | Ramiro + todos | Demostración | 7 min |

---

## Apertura · Nelson (1 min)

**[Portada]**
> Buenas. Somos Nelson, Martin, Jero, Ramiro y Carlos, y les vamos a presentar TramitaIA.

**[Pregunta al público]**
> Arranco con una pregunta: ¿quién tuvo que hacer alguna vez un trámite y no sabía qué papeles
> llevar? [esperar respuestas]
>
> Esto [señalar la captura] es una respuesta real de nuestra aplicación a «¿qué documentación tengo
> que llevar para inscribir el nacimiento de mi hijo?». La escribió un modelo de lenguaje en una
> **PC común, sin placa de video y sin internet**, y cada dato cita **la sección del documento
> oficial** de donde sale. La técnica se llama **CAG, Cache-Augmented Generation**. Vamos a ver
> qué es, sus ventajas y desventajas, con qué lo hicimos, el código, y al final una demo en vivo.

**[Agenda]**
> Jero explica qué es CAG. Carlos, qué gana y qué cuesta. Martin y Ramiro, con qué está hecho:
> los datos, y el modelo y la aplicación. Yo muestro el código. Y la demo va toda al final.
> Empezamos por la idea central. Jero.

---

## Bloque 1 · Jero · Qué es CAG y cómo funciona (5,5 min)

**[Votación]**
> Gracias, Nelson. Arranco con una votación. Los documentos que usamos suman unos **15.800 tokens**, unas 12.000
> palabras. ¿Cuánto tarda esta PC en **leerlos** antes de poder contestar? ¿10 segundos, 1 minuto
> o 10 minutos? Levanten la mano. [contar] Carlos les da la respuesta en un rato.

**[Atención: Q, K, V]**
> Para entender CAG hay que entender cómo lee un modelo. Procesa el texto de a pedazos llamados
> tokens, y para cada token, en cada una de sus 28 capas, calcula tres vectores: la **Query**, lo
> que busca; la **Key**, lo que ofrece para que lo encuentren; y el **Value**, la información que
> aporta. Un token nuevo compara su Query con las Keys de todos los anteriores y mezcla sus Values:
> eso es la atención.
>
> La clave [señalar el recuadro]: **las K y V de un token dependen solo de los anteriores**. Las de
> los documentos son siempre las mismas, venga la pregunta que venga. **Se calculan una vez y se
> guardan.** Eso es la **caché KV**.

**[Las tres fases]**
> Es como leer un libro una vez y quedarse con los apuntes. El paper de Chan y otros, de 2024, lo
> divide en tres fases: **precargar** el corpus en la caché, una sola vez; **responder** procesando
> solo la pregunta, sin buscar nada; y **reiniciar**, recortando lo que agregó la pregunta para que
> la caché vuelva a tener solo los documentos.

**[El flujo en TramitaIA]**
> En nuestro caso: **una vez**, los 15.800 tokens pasan por el modelo y queda una caché de **865 MB
> guardada en disco**. **En cada pregunta**, entran unos 20 tokens y el modelo responde mirando
> toda la caché. Al terminar, se recorta y queda lista para la siguiente.

**[CAG frente a RAG]**
> La alternativa más conocida es RAG. RAG, en cada pregunta, **busca** los fragmentos que parecen
> relevantes y le pasa solo esos al modelo. Si el buscador trae el equivocado, la respuesta sale
> mal aunque estuviera en los documentos. CAG **no busca**: el modelo ve todo, siempre. ✂ Y no es
> una caché de respuestas: esa solo sirve si repetís la pregunta exacta; la caché KV sirve para
> cualquiera.
>
> Suena muy bien. ¿Tiene contras? Carlos.

---

## Bloque 2 · Carlos · Ventajas, desventajas y limitaciones (6,5 min)

**[Hasta la primera palabra]**
> Gracias, Jero. Primero, la votación: ¿quién dijo 10 minutos? [esperar] Ganaron. Leer todo sin
> caché tarda **630 segundos: diez minutos y medio**. Con CAG, la primera palabra llega a los
> **8,8 segundos**. **72 veces menos**, en la misma PC, con el mismo modelo.

**[Ventajas]**
> Esa es la primera ventaja, pero hay más. [ir señalando]
> **No hay errores de búsqueda**: el modelo ve todo el corpus.
> **Se paga una sola vez**: construir la caché tarda casi lo mismo que una consulta sin caché, así
> que **desde la segunda consulta ya conviene**, y si está guardada en disco, desde la primera.
> **Arquitectura simple**: sin buscador, sin base de datos vectorial.
> **Reproducible y verificable**: con caché y sin caché la respuesta es idéntica, token por token.
> Y **corre local**: sin placa de video y sin internet, así que los datos no salen de la máquina.

**[CAG ahorra leer, no escribir]**
> Ahora el matiz. Este gráfico es una respuesta completa de 128 tokens. Azul es leer; naranja,
> escribir. Sin caché, **708 segundos**; con CAG, **87,7**. Ocho veces menos, pero miren la
> naranja: **es igual en los dos**, 0,62 segundos por token. **CAG ahorra leer, no escribir.** Por
> eso en la demo cada respuesta va a tardar uno o dos minutos.

**[Desventajas]**
> Una pregunta: ¿qué pasa si mañana el Registro Civil cambia un requisito? [esperar respuestas]
>
> Hay que **reconstruir la caché**: unos 11 minutos. Esa es una desventaja. Las otras: **todo el
> corpus tiene que entrar en el contexto** del modelo; **ocupa memoria**, 865 MB la caché y unos
> 7 GB la aplicación entera; **no acelera la escritura**; y como hay una sola caché, se atiende
> **una consulta por vez**.

**[Limitaciones]**
> Y tres límites de fondo. Uno, del propio paper: **cuando el corpus crece, la ventaja frente a RAG
> se achica**; en su prueba más grande, RAG le gana por poco. Dos: **CAG no hace más inteligente al
> modelo**. Probamos uno de 1.500 millones de parámetros: CAG funcionaba perfecto, pero **citaba
> bien 1 de 8 preguntas e inventaba trámites**. Tres: la caché sirve **solo para ese modelo, ese
> prompt y esos parámetros**; si cambia algo, se reconstruye.
>
> ¿Con qué está hecho? Empezamos por los datos. Martin.

---

## Bloque 3 · Martin · Stack tecnológico I: los datos (6,5 min)

**[Qué sabe el asistente]**
> Gracias, Carlos. El asistente sabe lo que está en **12 documentos oficiales**: del Registro Civil
> y la Secretaría de Justicia de La Rioja, páginas nacionales y la ley impositiva. Son **82
> secciones**, cada una con un id, y **15.800 tokens**. La respuesta del nacimiento, por ejemplo,
> sale de la sección `rc-nacimientos#s2`.

**[Stack de datos]**
> ¿Cómo llegan ahí? [ir señalando]
> Las páginas se descargan con **requests**, respetando el `robots.txt` de cada sitio y esperando
> dos segundos entre pedidos. Se leen con **BeautifulSoup**, las páginas armadas en JavaScript con
> **json5**, y la ley con **pypdf**. Todo se registra en un **manifiesto** con su versión, su fecha
> y una huella **SHA-256**, así sabemos si el organismo cambió algo. Después se corta en secciones
> con id y se cuentan los tokens con el **tokenizer del mismo modelo**, para saber si entra.

**[Ni las fuentes coinciden]**
> Algo que nos sorprendió: **las fuentes oficiales se contradicen**. Para el pasaporte de un menor,
> el Registro Civil pide «presencia de ambos progenitores o tutor legal» y Justicia dice «el DNI de
> los padres o tutores legales que lo acompañen». ¿Cuál vale? [esperar] No se puede saber desde los
> documentos: **la app muestra las dos con una advertencia**.

**[Cada capa frenó un caso real]**
> El modelo puede inventar, así que lo rodeamos de controles, y cada uno lo agregamos por **un
> error real**. [contar 3 o 4] El **control de alcance**: «¿cómo hago un ciclo for en Python?» ni
> llega al modelo. Las **citas desde el registro**: el modelo solo escribe el código de la
> sección, **nunca un enlace**. El **filtro de tema**: llegó a «respaldar» monotributo con una
> sección de nacimientos, y se descartó. La **verificación de costos**: escribió «gratuito» donde
> el documento no publica costos, y se quitó.

**[¿No sé o algo falso?]**
> ¿Qué es peor para alguien que va a hacer un trámite: «no sé» o algo falso con seguridad?
> [esperar] Lo segundo. Por eso, sin respaldo, la app **se abstiene**: **12 de 12** preguntas sobre
> trámites que no están terminaron **sin información inventada**. El límite: la verificación
> compara **palabras, no significado**.
>
> Esos datos los lee un modelo dentro de una aplicación. Ramiro.

---

## Bloque 4 · Ramiro · Stack tecnológico II: el modelo y la aplicación (6,5 min)

**[Stack del modelo y la app]**
> Gracias, Martin. [ir señalando] El modelo es **Qwen 2.5 de 7.000 millones de parámetros**, en
> versión Instruct, comprimido a **4 bits**: pesa unos 4,7 GB. Lo corre **llama.cpp**, desde Python
> con llama-cpp-python. El servidor es **FastAPI** con uvicorn, y manda la respuesta **palabra por
> palabra**. La interfaz es **HTML, CSS y Alpine.js**. Todo en **Python 3.12**, con **pytest**
> para las pruebas automáticas.

**[Por qué estas piezas]**
> ¿Por qué esto y no otra cosa? El 7B en PyTorch, el formato normal, **no entraba** en 16 GB de RAM:
> solo los pesos ocupaban 15,2 GB. Comprimido a 4 bits, sí. Y **llama.cpp** nos da justo lo que
> CAG necesita: **guardar la caché en disco, cargarla y recortarla**. La interfaz no usa nada
> externo: **funciona sin internet**.

**[Arquitectura]**
> Y así se conecta todo, en seis pasos. El **navegador** manda la pregunta a **FastAPI**. Antes del
> modelo, el **control de alcance**: si no es sobre trámites, responde al instante. Si es, va al
> **motor CAG**. Lo que escribe pasa por la **verificación**, y el enlace a la fuente lo pone el
> **registro documental**, no el modelo. Como hay una sola caché, se atiende **una consulta por
> vez**, con cola. Y al arrancar hacemos una consulta de calentamiento: sin ella, la primera
> tardaba 22 segundos en empezar.

**[Borrador en vivo]**
> La respuesta se ve mientras se escribe, pero dice **«borrador sin verificar»**. ¿Por qué creen?
> [esperar] Porque se verifica recién al final. En una prueba, el borrador nombró un organismo que
> no está en los documentos, y al terminar se reemplazó por «no encontré esa información».
>
> Por dentro de ese motor está CAG. Nelson.

---

## Bloque 5 · Nelson · El código de CAG (5,5 min)

**[Prefijo]**
> Gracias, Ramiro. El primer paso es decidir **qué entra en la caché y qué no**. Lo que es igual
> para cualquier pregunta va en el **prefijo**: instrucciones, documentos y reglas, **15.800
> tokens**, una sola vez. Lo que cambia, **la pregunta**, va aparte: unos 20 tokens. Los tokenizamos
> por separado para que el modelo vea **exactamente los mismos tokens** que generaron la caché.

**[Construir y guardar]**
> Esto es la **precarga**. La app primero intenta cargar una caché del disco; si no hay una válida,
> la construye con **una sola pasada** del modelo [señalar la línea naranja], unos **11 minutos**.
> Se guarda en dos archivos: `state.bin`, **868 MB**, y `meta.json`, con lo que la identifica y una
> huella SHA-256. Se escribe en una carpeta temporal y se renombra al final: **nunca queda una caché
> a medias**. Y el nombre es un hash del modelo y el prefijo: **nunca se usa una caché vieja por
> error**.

**[Cargar desde disco]**
> Al arrancar, la app **no confía en el archivo**: compara el `meta.json` con el modelo y el
> corpus actuales, carga el estado y **recalcula la huella**. Un solo byte distinto y la rechaza.
> Cargarla tarda **entre 1,3 y 9,6 segundos** en vez de 11 minutos.

**[Responder]**
> Y en cada pregunta, siete pasos. [ir señalando] Validar; tomar el lock; **volver al estado base**;
> **verificar la huella**; **procesar solo la pregunta**, 20 tokens y no 15.800, ahí está el
> ahorro; generar token por token; y en el `finally`, **limpiar siempre**, aunque algo falle.

**[¿Está bien?]**
> ¿Qué pasa si no limpio la caché? [esperar] La segunda pregunta «ve» la primera: sin limpiar,
> arranca con **117 posiciones de más** y la respuesta cambia. Y comparando con procesar todo de
> cero: **6 de 6 respuestas idénticas**, token por token.
>
> Para cerrar, Jero.

---

## Cierre · Jero (1 min)

**[Conclusiones]**
> Gracias, Nelson. Al principio dijimos que CAG es leer el libro una vez y quedarse con los
> apuntes. Tres ideas para llevarse. Con un corpus **chico y estable**, CAG evita releer diez minutos de
> documentos en cada pregunta. La caché hay que **limpiarla y verificarla**. Y **la confianza no la
> da el modelo, la da el código alrededor**.
>
> Ahora lo vamos a ver funcionando.

---

## Parte 2 · Demostración (7 min) · conduce Ramiro

Igual que en la versión B: ver el [guion B](guion_B.md#parte-2--demo-7-min--conduce-ramiro). Ramiro
hace la pregunta del nacimiento, Martin la del asado, Jero la de la licencia de conducir, Carlos la
del costo y Nelson cierra mostrando las fuentes.
