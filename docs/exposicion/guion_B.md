# Guion de la versión B (por bloques)

Qué dice cada integrante, diapositiva por diapositiva, en la [presentación B](https://claude.ai/artifact/GQMYoSsVy6yVU7wVcvAach)
(copia de las diapositivas en [`presentacion_B/`](presentacion_B/)). La estructura y los tiempos
están en la [guía B](version_B_bloques.md).

Cómo usarlo:
- **No hay que leerlo de memoria.** Es una base para decir con tus palabras. Lo importante son las
  ideas en **negrita** y las cifras, que tienen que ser exactas.
- A un ritmo tranquilo se dicen unas 130 palabras por minuto. Cada bloque está escrito para su
  tiempo; si te pasás, cortá lo que está marcado con ✂.
- Entre corchetes van las acciones: [pasar diapositiva], [señalar], [esperar respuestas].

| Orden | Quién | Bloque | Tiempo |
|---|---|---|---|
| 0 | Nelson | Apertura | 1,5 min |
| 1 | Jero | Qué es CAG | 6 min |
| 2 | Ramiro | La aplicación y los datos de entrada | 7 min |
| 3 | Nelson | El código de CAG | 5,5 min |
| 4 | Martin | Qué hay en el corpus y cómo evitamos que invente | 6 min |
| 5 | Carlos | Resultados, lo que salió mal y conclusiones | 6 min |
| — | Ramiro + todos | Demo | 7 min |

---

## Apertura · Nelson (1,5 min)

**[Portada]**
> Buenas. Somos Nelson, Martin, Jero, Ramiro y Carlos, y les vamos a presentar TramitaIA.

**[Pregunta al público]**
> Antes de arrancar, una pregunta: ¿quién tuvo que hacer alguna vez un trámite y no sabía qué
> papeles llevar? [esperar respuestas, levantar la mano uno mismo]
>
> Bueno, eso es lo que intentamos resolver. Esto que ven acá [señalar la captura] es una respuesta
> real de nuestra aplicación a la pregunta «¿qué documentación tengo que llevar para inscribir el
> nacimiento de mi hijo?». La escribió un modelo de lenguaje **corriendo en una PC común, sin placa
> de video y sin internet**, y cada dato tiene al lado **la sección del documento oficial de donde
> sale**.
>
> La técnica que lo hace posible se llama **CAG, Cache-Augmented Generation**: generación aumentada
> por caché. Hoy les vamos a explicar qué es y cómo la implementamos.

**[Agenda]**
> La presentación está en cinco bloques. Jero explica qué es CAG. Ramiro muestra la aplicación y
> cómo entran los datos. Yo muestro el código de CAG por dentro. Martin cuenta qué sabe el
> asistente y cómo evitamos que invente. Y Carlos cierra con los resultados. La demo en vivo va
> toda al final.
>
> Empezamos por la idea central. Jero.

---

## Bloque 1 · Jero · Qué es CAG (6 min)

**[Votación]**
> Gracias. Arranco con una pregunta para ustedes. Todos los documentos oficiales que usamos suman
> unos **15.800 tokens**, que son algo así como 12.000 palabras. ¿Cuánto creen que tarda esta PC
> en **leer** todo eso antes de poder contestar una pregunta? ¿10 segundos, 1 minuto o 10 minutos?
> Levanten la mano. [contar] ¿10 segundos? ¿1 minuto? ¿10 minutos? Bien, lo anotamos: la
> respuesta la tiene Carlos al final.

**[Atención: Q, K, V]**
> Para entender CAG hay que entender cómo lee un modelo. Un modelo como el nuestro procesa el texto
> de a pedazos llamados tokens. Para cada token, en cada una de sus 28 capas, calcula tres
> vectores: la **Query**, que es lo que ese token busca; la **Key**, que es lo que ofrece para que
> otros lo encuentren; y el **Value**, que es la información que aporta.
>
> Cuando llega un token nuevo, compara su Query con las Keys de todos los anteriores y mezcla sus
> Values. Eso es la atención.
>
> Y acá está la clave [señalar el recuadro oscuro]: **las K y V de un token dependen solo de él y
> de los anteriores**, nunca de lo que viene después. Entonces, las K y V de los documentos son
> siempre las mismas, venga la pregunta que venga. **Se pueden calcular una vez y guardar.** Eso
> guardado es la **caché KV**.

**[Las tres fases]**
> La analogía es leer un libro una vez y quedarse con los apuntes: después, para cada pregunta, se
> consultan los apuntes y no se relee el libro.
>
> El paper que propone CAG, de Chan y otros, de 2024, lo llama justamente «Don't Do RAG», y lo
> divide en tres fases. **Precargar:** el corpus pasa una vez por el modelo y sus K/V quedan en la
> caché. **Responder:** para cada pregunta se procesa solo la pregunta, sin buscar nada. Y
> **reiniciar:** después de responder, se recortan los tokens que agregó la pregunta y la caché
> vuelve a tener solo el corpus.
>
> Ojo con una cosa [señalar abajo]: lo que **no** se ahorra es escribir la respuesta. Eso Carlos lo
> va a mostrar con números.

**[El flujo en TramitaIA]**
> En nuestro proyecto queda así. Arriba, lo que se hace **una sola vez**: instrucciones más corpus,
> unos 15.800 tokens, una pasada del modelo, y queda una caché de **865 MB guardada en disco**.
> Abajo, lo que pasa **en cada pregunta**: entran unos 20 tokens, el modelo atiende sobre toda la
> caché y responde. Al terminar se recorta al prefijo, listo para la siguiente.

**[CAG frente a RAG]**
> Seguramente escucharon hablar de RAG, que es lo más común. RAG, en cada pregunta, **busca** los
> fragmentos que parecen relevantes y le pasa al modelo solo esos. El riesgo es que el buscador
> traiga el fragmento equivocado: el modelo responde mal aunque la respuesta estuviera en los
> documentos. CAG **no busca nada**: el modelo ve todo el corpus, siempre. El costo es que todo
> tiene que entrar en el contexto del modelo.
>
> Y el propio paper lo admite: **cuando el corpus crece, la ventaja de CAG se achica**. Para
> nuestro caso, 15.800 tokens, entra perfecto.

**[No es lo mismo que guardar respuestas]**
> Última aclaración, porque la palabra «caché» se usa para muchas cosas. Una caché de respuestas
> guarda pregunta → respuesta, y sirve solo si alguien pregunta exactamente lo mismo. **La caché
> KV guarda la lectura del corpus**, así que sirve para cualquier pregunta. ✂ El «prompt caching»
> de las APIs comerciales es la misma idea que la nuestra, pero en el servidor del proveedor y
> por unos minutos.
>
> Eso es la idea. Ramiro les muestra cómo está armada la aplicación y de dónde salen los datos.

---

## Bloque 2 · Ramiro · La aplicación y los datos de entrada (7 min)

**[Arquitectura]**
> Gracias, Jero. Así es TramitaIA por fuera, en seis pasos. [ir señalando]
> Uno: el **navegador**, un chat hecho en HTML con Alpine.js. Dos: un servidor **FastAPI**, que
> manda la respuesta palabra por palabra. Tres: antes de tocar el modelo, un **control de
> alcance**: si la pregunta no es sobre trámites, por ejemplo cómo hacer un asado, se responde al
> instante y no se gasta ni un segundo de cómputo. Cuatro: el **motor CAG**, con llama.cpp y el
> modelo Qwen 2.5 de 7.000 millones de parámetros, comprimido a 4 bits. Cinco: la
> **verificación** de lo que escribió. Y seis: el **registro documental**, de donde sale el enlace
> a la fuente oficial. **El enlace lo pone el código, no el modelo.**
>
> Dos decisiones de diseño: como hay **una sola caché**, se atiende **una consulta por vez**, con
> una cola de hasta cuatro. Y al arrancar hacemos una consulta de calentamiento, porque sin ella la
> primera pregunta tardaba 22 segundos en empezar.

**[Borrador en vivo]**
> La respuesta se ve mientras se escribe, para no esperar con la pantalla en blanco. Pero fíjense
> que dice **«borrador sin verificar»**. ¿Por qué creen que no la mostramos directamente como
> definitiva? [esperar respuestas]
>
> Porque la verificación se puede hacer recién cuando el texto está completo. En una prueba, el
> borrador nombró un organismo que no está en nuestros documentos, y al terminar la app lo
> reemplazó por «no encontré esa información». Por eso el borrador avisa.

**[El recorrido del código]**
> Ahora, por dentro. Este es el camino completo en el código, siguiendo un documento: el del
> nacimiento. Yo les muestro las etapas uno y dos, **cómo entran los datos**. Nelson sigue desde la
> tres, que es CAG propiamente dicho.

**[1 · Ingesta]**
> La ingesta baja las páginas oficiales. Cada fuente está registrada con su URL y su tipo. El
> descargador es **educado**: consulta el `robots.txt` de cada sitio y espera dos segundos entre
> pedidos. Después hay **un parser por tipo de sitio**: el Registro Civil es HTML, la Secretaría de
> Justicia es una página en JavaScript y la ley impositiva es un PDF. El parser marca los títulos
> de sección con dos numerales, que vamos a usar enseguida.
>
> Y calculamos **dos huellas SHA-256**: una del archivo original y otra del texto extraído. Con eso
> el manifiesto sabe si el organismo **cambió la página** o si cambió **nuestra forma de leerla**.
> Si hay versión nueva, se guarda como v2, v3, con su fecha. Y si una descarga falla, **no se pierde
> nada**: se conserva la versión anterior.

**[2 · Corpus]**
> Con el texto limpio armamos el corpus. Esta línea corta el documento en cada título marcado con
> dos numerales, y cada sección recibe un **id estable**: documento, numeral, s y un número. Por
> ejemplo, `rc-nacimientos#s2` es la documentación requerida para inscribir un nacimiento.
>
> Así queda en el corpus, es texto real [señalar]: arriba los datos del documento (organismo,
> fuente oficial, fecha de actualización) y después cada sección con su id entre corchetes. **Ese
> id es lo que el modelo escribe como cita**, y lo que después el código verifica.
>
> Este texto es lo que va a la caché. Nelson les muestra cómo.

---

## Bloque 3 · Nelson · El código de CAG (5,5 min)

**[3 · Prefijo]**
> Gracias, Ramiro. El primer paso de CAG es decidir **qué entra en la caché y qué no**. Todo lo que
> es igual para cualquier pregunta va en el **prefijo**: las instrucciones, el corpus que mostró
> Ramiro y las reglas con ejemplos. Son unos **15.800 tokens** y se procesan **una sola vez**. Lo
> único que cambia, **la pregunta**, va aparte: unos 20 tokens.
>
> En código es así de simple [señalar]: el mensaje de sistema es instrucciones más corpus más
> reglas, dentro de la plantilla de chat del modelo; y la pregunta va en su propio turno. Los
> tokenizamos por separado, así el modelo ve **exactamente los mismos tokens** que generaron la
> caché.

**[4 · Construir y guardar]**
> Esto es la fase de **precarga** del paper. Primero, la app intenta cargar una caché del disco. Si
> no hay una válida, la construye: [señalar la línea naranja] **una sola pasada** del modelo por
> los 15.800 tokens. En esta PC eso tarda **unos 11 minutos**.
>
> Después la guardamos en dos archivos: `state.bin`, con la caché, **unos 868 MB**, y `meta.json`,
> con todo lo que la identifica: modelo, prefijo y una huella SHA-256 de las K y V. Se escribe en
> una carpeta temporal y se renombra al final, así un corte de luz **nunca deja una caché a medias**.
>
> El nombre de la carpeta es un hash del modelo, la cuantización y el prefijo. Si cambia el corpus
> o el prompt, cambia el nombre: **nunca se usa una caché vieja por error**.

**[5 · Cargar desde disco]**
> Esto es lo que hace la app cada vez que arranca, y **no confía en el archivo**. Primero compara
> el `meta.json` con el modelo y el corpus actuales. Después carga el estado y **recalcula la
> huella**: si un solo byte cambió, la rechaza y la reconstruye. Cargarla tarda **entre 1,3 y 9,6
> segundos**, en vez de 11 minutos. Por eso la app arranca en un minuto.

**[6 · Responder]**
> Y esto es lo que pasa en cada pregunta, en siete pasos. [ir señalando] Uno: validar que la
> pregunta entre en el contexto. Dos: un lock, porque hay una sola caché. Tres: **volver al estado
> base**, solo el corpus. Cuatro: **verificar la huella**. Cinco: **procesar solo la pregunta**,
> unos 20 tokens, no 15.800: ahí está todo el ahorro. Seis: generar token por token, siempre el
> más probable. Y siete, lo más importante: en el `finally`, **limpiar siempre**, aunque algo
> falle.

**[7 · ¿Está bien?]**
> Les pregunto: ¿qué pasa si no limpio la caché entre una pregunta y otra? [esperar respuestas]
>
> La segunda pregunta «ve» la primera. Lo probamos: sin limpiar, la segunda pregunta arranca con
> **117 posiciones de más** y la respuesta cambia. Limpiar es esto [señalar]: dos líneas, que son
> el «reiniciar» del paper.
>
> ¿Y cómo sabemos que la caché no cambia la respuesta? La comparamos con procesar todo desde cero:
> **6 de 6 respuestas idénticas, token por token**.
>
> Hasta acá, cómo funciona. Ahora: ¿qué sabe el asistente y cómo evitamos que invente? Martin.

---

## Bloque 4 · Martin · Qué hay en el corpus y cómo evitamos que invente (6 min)

**[Qué sabe el asistente]**
> Gracias, Nelson. Ramiro mostró cómo se arma el corpus; yo les cuento qué tiene adentro.
> Son **12 documentos oficiales**: del Registro Civil y la Secretaría de Justicia de La Rioja,
> páginas nacionales y la ley impositiva. En total, **82 secciones**, cada una con su id, y
> **15.800 tokens**. Volviendo a la pregunta del principio: la respuesta del nacimiento sale de la
> sección `rc-nacimientos#s2`. Ese id es lo que nos permite citarla y verificarla.

**[Ni las fuentes oficiales coinciden]**
> Algo que nos sorprendió: **las propias fuentes oficiales se contradicen**. Para el pasaporte de un
> menor, la ficha del Registro Civil pide [leer] «presencia de ambos progenitores o tutor legal», y
> la guía de la Secretaría de Justicia dice «el DNI de los padres o tutores legales que lo
> acompañen». ¿Cuál vale? [esperar respuestas]
>
> No hay forma de saberlo desde los documentos. Por eso no elegimos: **la app muestra las dos
> fuentes con una advertencia**. Y por eso cada dato tiene que llevar su fuente.

**[Cada capa frenó un caso real]**
> El modelo puede inventar, así que lo rodeamos de controles. Cada uno lo agregamos porque **vimos
> un error real**. [contar 3 o 4 filas]
> El **control de alcance**: «¿cómo hago un ciclo for en Python?» ni siquiera llega al modelo.
> Las **citas desde el registro**: el modelo solo escribe el código de la sección; **nunca escribe
> un enlace**. El **filtro de tema**: el modelo llegó a «respaldar» una respuesta sobre
> monotributo con una sección de nacimientos, y el código la descartó. La **verificación de
> costos**: el modelo escribió «gratuito» en un trámite cuyo documento no publica el costo, y el
> código quitó esa línea.

**[No sé o algo falso]**
> Les pregunto: ¿qué es peor para alguien que va a hacer un trámite, que la app le diga «no sé» o
> que le diga algo falso con total seguridad? [esperar respuestas]
>
> Para nosotros, lo segundo: hace perder un viaje o un turno. Por eso, cuando no hay respaldo, la
> app **se abstiene**. En las pruebas, **12 de 12 preguntas** sobre trámites que no están en el
> corpus terminaron **sin información inventada**.
>
> Y un límite honesto: la verificación compara **palabras, no significado**. Puede ocultar una
> respuesta correcta dicha con otras palabras. No reemplaza a la fuente oficial.
>
> ¿Y todo esto cuánto rinde? Carlos.

---

## Bloque 5 · Carlos · Resultados, lo que salió mal y conclusiones (6 min)

**[Hasta la primera palabra]**
> Gracias, Martin. Volvamos a la votación de Jero: ¿quién dijo 10 minutos? [esperar] Ganaron.
> Leer todo el corpus, sin caché, tarda **630 segundos: diez minutos y medio**. Con CAG, la
> primera palabra llega a los **8,8 segundos**. **72 veces menos.** Misma PC, mismo modelo: lo
> único que cambia es si reusamos la caché. Es una PC con un Ryzen 5, 16 GB de RAM y **sin placa
> de video**.

**[CAG ahorra leer, no escribir]**
> Este gráfico es una respuesta completa de 128 tokens. La parte azul es leer el contexto; la
> naranja, escribir. Sin caché: **708 segundos**. Con CAG: **87,7**, ocho veces menos. Pero miren
> la naranja: **es igual en los dos**, 0,62 segundos por token. Como dijo Jero, **CAG ahorra leer,
> no escribir**. Por eso, en la demo, cada respuesta igual va a tardar uno o dos minutos: en una
> CPU, escribir es lento.

**[Desde la segunda consulta ya conviene]** ✂
> ¿Vale la pena construir la caché? Construirla tarda 11 minutos, casi lo mismo que **una sola**
> consulta sin caché. Así que **desde la segunda consulta ya conviene**, y si la caché ya está en
> disco, desde la primera. Ocupa 865 MB; la app entera, unos 7 GB de RAM.

**[Cuatro modelos hasta el que funcionó]**
> No llegamos acá de una. El modelo de 7.000 millones en formato normal **no entraba** en la RAM:
> solo los pesos ocupaban 15 GB. Uno de 3.000 millones en otro formato tardaba hasta dos horas y
> media. Uno de 1.500 millones funcionaba, y **CAG funcionaba perfecto**, pero **citaba bien 1 de
> 8 preguntas e inventaba trámites**. El que anduvo fue el de 7.000 millones **comprimido a 4
> bits** con llama.cpp.
>
> La lección: **CAG resuelve tener todo el corpus disponible, no que el modelo sepa usarlo**.

**[Conclusiones]**
> Tres ideas para llevarse. Una: con un corpus **chico y estable**, CAG evita releer diez minutos
> de documentos en cada pregunta. Dos: la caché hay que **limpiarla y verificarla** en cada
> consulta; si no, contamina. Tres: **la confianza no la da el modelo, la da el código
> alrededor**. Con más tiempo, probaríamos con GPU, un esquema híbrido para un corpus más grande y
> una verificación por significado.
>
> Ahora lo vamos a ver funcionando.

---

## Parte 2 · Demo (7 min) · conduce Ramiro

Antes: la app arrancada unos 70 s antes y diciendo **«En línea»** (lista de control en el
[README](README.md#demo-parte-2-lista-de-control)).

**Ramiro** [escribe la pregunta del nacimiento]
> Vamos a hacer la misma pregunta del principio. [enviar] Mientras escribe, fíjense: tardó unos
> segundos en arrancar, porque solo procesa nuestra pregunta. Los 15.800 tokens de documentos ya
> están en la caché. Ahora va palabra por palabra, y dice «borrador sin verificar». [al terminar]
> Ahí está, con cada cita.

**Martin** [escribe «¿Cómo preparo un asado para diez personas?»]
> Una que no tiene nada que ver. [enviar] Respuesta al instante: ni llegó al modelo.

**Jero** [escribe «¿Qué necesito para sacar la licencia de conducir?»]
> Un trámite real, pero que no está en nuestros documentos. [enviar, esperar] No inventa: dice que
> no lo encontró y deriva al organismo.

**Carlos** [escribe «¿Tiene costo inscribir un nacimiento?»]
> Ahora un costo, que es donde el modelo más inventaba. [enviar, esperar] «Gratuito», con la cita
> a la sección de costo del documento.

**Nelson** [abre «Fuentes» y «Ver fuente oficial»]
> Y para cerrar: acá están las fuentes. Este enlace no lo escribió el modelo: sale del registro
> de documentos. Eso es TramitaIA. ¿Preguntas?

**Si algo falla:** decir «tenemos capturas reales de estas mismas preguntas» y pasar a la
diapositiva de plan B.
