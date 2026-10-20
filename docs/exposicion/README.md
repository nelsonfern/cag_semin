# Exposición de TramitaIA

Hay tres versiones de la misma exposición. Las tres duran entre 30 y 40 minutos, reparten el
tiempo de forma pareja entre los cinco integrantes y dejan la **demo para el final, como parte
separada**. El grupo eligió presentar **por bloques**: la B o la C.

| | [A: clase dinámica](version_A_dinamica.md) | [B: por bloques](version_B_bloques.md) | [C: por temas](version_C_temas.md) |
|---|---|---|---|
| Estilo | Clase con preguntas, diálogos y relevos cortos | Un bloque seguido por integrante | Un bloque seguido por integrante |
| Orden | El caso del nacimiento como hilo | CAG → app y datos → código → confianza → resultados | Qué es → ventajas y límites → stack (datos, modelo y app) → código |
| Ensayo que pide | Más: hay pases y diálogos | Menos | Menos |
| Parte 1 (exposición) | ~30 min | ~32,5 min | ~32,5 min (6,5 por integrante) |
| Parte 2 (demo) | ~8 min | ~7 min | ~7 min |
| Qué dice cada uno | En la guía | [Guion B](guion_B.md) | [Guion C](guion_C.md) |
| Diapositivas | [Presentación A](https://claude.ai/artifact/FB4xod6t5HCJYtivaTECXY) | [Presentación B](https://claude.ai/artifact/GQMYoSsVy6yVU7wVcvAach) · [copia](presentacion_B/) | [Presentación C](https://claude.ai/artifact/WRjZe6Ykmg9npV7FYXza4w) · [copia](presentacion_C/) |

B y C tienen **dos diseños**, con el mismo contenido, los mismos oradores y las mismas notas:

| | Diseño 1 (oscuro) | Diseño 2 (futurista) |
|---|---|---|
| Estilo | Fondo azul noche, degradés azul-violeta, Space Grotesk + Inter | Negro con líneas finas y círculos de fondo, tarjetas con esquinas marcadas, íconos en cuadrados rojos, acento rojo anaranjado y ámbar, Chakra Petch + Space Grotesk, gráficos oscuros |
| B | [Presentación B](https://claude.ai/artifact/GQMYoSsVy6yVU7wVcvAach) | [Presentación B · diseño 2](https://claude.ai/artifact/JV9mDvsr8NXSAuDbrPqDdW) · [copia](presentacion_B2/) |
| C | [Presentación C](https://claude.ai/artifact/WRjZe6Ykmg9npV7FYXza4w) | [Presentación C · diseño 2](https://claude.ai/artifact/RTqiumNMqwUj8oZyQRoLXB) · [copia](presentacion_C2/) |

Los gráficos del diseño 2 son `docs/img/*_oscuro.svg`. Se generan con
`python -X utf8 -m app.evaluation.charts data/results/phase6_benchmark_20261017_211141.json --oscuro`,
con la paleta validada para fondo oscuro.

Las presentaciones web son privadas hasta que se compartan desde su menú Compartir. Cada
diapositiva indica quién habla y tiene notas para el orador.

**Material común:**
- [Contenido técnico](contenido_tecnico.md): cifras, explicación de CAG, código comentado,
  diagramas, cómo se evita que invente, el camino de los modelos.
- Gráficos: [`respuesta_cag_vs_baseline.svg`](../img/respuesta_cag_vs_baseline.svg) y
  [`punto_de_equilibrio.svg`](../img/punto_de_equilibrio.svg).
- Capturas reales de la app para el plan B: [`docs/img/demo/`](../img/demo/).

El tema de costos económicos (precios de API, hardware) quedó **fuera** a pedido del grupo. Lo que
sí se muestra es el punto de equilibrio **en tiempo**, porque es la idea central de CAG: pagar una
vez el procesamiento del corpus.

## Reparto de tiempo

| Integrante | Versión A | Versión B | Temas |
|---|---|---|---|
| Nelson | ~7 min | ~7 min | Apertura y el código de CAG (en B: prefijo, construir, guardar y cargar la caché, responder) |
| Martin | ~7 min | ~6 min | Las fuentes y el corpus; cómo se evita que invente |
| Jero | ~6,5 min | ~6 min | Qué es CAG: atención, caché KV, el paper, la diferencia con RAG |
| Carlos | ~7 min | ~6 min | Resultados medidos; lo que salió mal |
| Ramiro | ~3 min + demo | ~7 min + demo | Arquitectura de la app (en B también la ingesta y el corpus, con código); conduce la demo |

## Demo (parte 2): lista de control

**Primera vez en otra PC** (hacerlo el día anterior, no en la clase)

El repositorio trae el corpus procesado, pero **no** trae el modelo ni la caché KV: los dos son
pesados y están en el `.gitignore`.
- [ ] Clonar el repositorio, crear el entorno virtual e instalar las dependencias (ver el
      [README principal](../../README.md)).
- [ ] Arrancar la app una vez: `.venv\Scripts\python scripts\run_app.py --abrir`. Al arrancar (no en
      la primera pregunta) hace esto:
  1. descarga el modelo de Hugging Face (~4,7 GB, depende de la conexión);
  2. no encuentra la caché y la construye: **~11 minutos** en una CPU como la del equipo de prueba;
     queda guardada en `data/caches/`;
  3. hace la consulta de calentamiento y recién ahí muestra **«En línea»**.
- [ ] Hacer una pregunta de prueba y cerrar la app. Desde el siguiente arranque, la caché se carga
      desde disco y la app está lista en ~70 s.
- [ ] Si esa PC tiene otra CPU o menos RAM, los tiempos van a ser distintos a los de las
      diapositivas (que se midieron en un Ryzen 5 5500 con 16 GB). Conviene medir cuánto tarda la
      pregunta del nacimiento para saber si alcanza el tiempo de la demo.

**Antes de la clase**
- [ ] Probar la app el mismo día en la misma PC. Cerrar el navegador pesado y todo lo que use RAM:
      el modelo y la caché ocupan ~7 GB.
- [ ] Confirmar que la caché está en disco (`data/caches/bda0d01871987281/`). Si no está, la primera
      vez tarda ~11 minutos en construirse.

**Entre la parte 1 y la parte 2** (o unos minutos antes de empezar la demo)
- [ ] Arrancar la app: `.venv\Scripts\python scripts\run_app.py --abrir`. Tarda **~70 s** en estar
      lista (modelo, caché desde disco y una consulta de calentamiento). Abre el navegador sola.
- [ ] Comprobar que arriba a la derecha dice **«En línea»**.
- [ ] Zoom del navegador al 125–150 % para que se lea desde el fondo.

**Guion de la demo** (conduce Ramiro; cada uno hace una pregunta)

| # | Quién pregunta | Pregunta | Qué se espera | Tiempo |
|---|---|---|---|---|
| 1 | Ramiro | ¿Qué documentación tengo que llevar para inscribir el nacimiento de mi hijo? | Requisitos y pasos con citas `[rc-nacimientos#s2]`; «Fuentes» con el documento oficial | 2–3 min |
| 2 | Martin | ¿Cómo preparo un asado para diez personas? | «Fuera del alcance», **al instante** (no llega al modelo) | 10 s |
| 3 | Jero | ¿Qué necesito para sacar la licencia de conducir? | Abstención: no está en los documentos | ~1 min |
| 4 | Carlos | ¿Tiene costo inscribir un nacimiento? | «Gratuito», citado de la sección de costo | ~1 min |
| 5 | Nelson | Cierre: mostrar «Fuentes» y «Ver fuente oficial» | El enlace sale del registro, no del modelo | 1 min |

Mientras el modelo escribe (la primera palabra tarda ~9 s, después ~0,6 s por palabra), quien
pregunta explica qué está pasando: «ahora el modelo solo procesa nuestra pregunta; los 15.800
tokens de documentos ya están en la caché». Es tiempo para contar, no tiempo muerto.

**Plan B** (si la PC falla, se cuelga o tarda demasiado): mostrar las capturas reales de
[`docs/img/demo/`](../img/demo/), tomadas de la app con el mismo modelo:

| Captura | Qué muestra |
|---|---|
| `01_inicio.jpg` | Pantalla inicial con preguntas sugeridas |
| `02_borrador_en_vivo.jpg` | La respuesta mientras se escribe («borrador sin verificar») |
| `03_respuesta_con_fuentes.jpg` | Respuesta final con citas y la fuente oficial desplegada |
| `04_fuera_de_alcance.jpg` | Pregunta fuera de tema, rechazada al instante |
| `05_abstencion.jpg` | Licencia de conducir: no inventa, deriva al organismo |
| `06_costo.jpg` | Costo de inscribir un nacimiento, citado |

> Nota honesta: en la captura 03 la respuesta llegó al límite de largo y la última línea quedó
> cortada («Costo: El trámite es gratuito [rc-nac»). La app lo avisa en amarillo. Si pasa en vivo,
> es un buen momento para mostrar ese aviso.
>
> En la abstención (captura 05), mientras escribía, el borrador mencionó «la Subsecretaría de
> Tránsito y Transporte», que no está en el corpus. Al terminar, la app lo reemplazó por el
> mensaje fijo. Sirve para explicar por qué el borrador dice «sin verificar».

## Preguntas probables del público

| Pregunta | Responde | Respuesta corta |
|---|---|---|
| ¿Por qué no usaron RAG? | Jero | Con 15.800 tokens el corpus entra entero en el contexto: no hace falta elegir fragmentos ni arriesgar que el buscador traiga el equivocado. Si el corpus creciera mucho, RAG volvería a convenir. |
| ¿Qué pasa si cambian los documentos? | Martin | Hay que reconstruir la caché (~11 min). Cada caché tiene un id que depende del modelo, del prompt y del corpus: si algo cambia, no se usa una vieja por error. |
| ¿Cuánto ocupa la caché? | Jero | 865 MB para ~15.800 tokens: unos 56 KB por token. |
| ¿Por qué tarda tanto cada respuesta? | Carlos | CAG ahorra procesar el corpus (630 s → 8,8 s hasta la primera palabra), pero **no** acelera escribir: 0,62 s por token en CPU. Con GPU sería mucho más rápido. |
| ¿Cómo saben que la caché no se «ensucia»? | Nelson | Después de cada respuesta se recorta al prefijo, y antes de la siguiente se compara una huella SHA-256 de las K/V. Y la respuesta con caché es idéntica a la de procesar todo de cero (6 de 6). |
| ¿Y si dos personas preguntan a la vez? | Ramiro | Hay una sola caché, así que se atiende de a una (lock) con una cola de hasta 4. Es una limitación conocida del prototipo. |
| ¿Puede inventar igual? | Martin | Puede generar algo inventado, pero no se muestra sin respaldo: citas validadas, filtro de tema, verificación de frases y de costos. La verificación es por palabras, no perfecta. |
| ¿Por qué un modelo de 7B y no uno más chico? | Carlos | Probamos 0,5B, 1,5B y 3B: con un contexto tan largo se pierden, citan mal o inventan trámites. |
| ¿Qué es cuantizar a 4 bits? | Carlos | Guardar los pesos con menos precisión: el 7B pasa de ~15 GB a ~4,7 GB y entra en la RAM, con poca pérdida de calidad. |
| ¿Es lo mismo que el «prompt caching» de las APIs? | Jero | Es la misma idea (guardar las K/V del prefijo), pero ahí lo hace el proveedor en su servidor y vence en minutos. Acá la caché es nuestra y queda en disco. |
| ¿Es lo mismo que guardar respuestas? | Jero | No. Una caché de respuestas solo sirve si la pregunta se repite igual. La caché KV sirve para cualquier pregunta. |
| ¿Por qué greedy y no muestreo? | Nelson | Para que sea reproducible y se pueda comparar token por token con el baseline. |
| ¿De dónde salen las fuentes que muestra? | Martin | Del manifiesto del corpus: URL, organismo y fechas. El modelo solo escribe un código `[doc#sN]`; nunca escribe un enlace. |
| ¿Es un sitio oficial? | Ramiro | No. Es un prototipo académico y lo dice en pantalla. |
| ¿Qué harían con más tiempo? | Nelson | GPU, corpus más grande con un esquema híbrido, verificación semántica y más preguntas de evaluación. |
