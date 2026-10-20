# Versión C: por temas

Misma forma de trabajo que la [versión B](version_B_bloques.md): cada integrante presenta **un
bloque seguido**, con un momento de interacción y una frase de pase. Cambia el orden del contenido,
que va **de lo general a lo particular**:

1. qué es CAG y cómo funciona;
2. ventajas, desventajas y limitaciones;
3. stack tecnológico (en dos bloques: los datos, y el modelo y la aplicación);
4. el código;
5. la demostración.

Las diapositivas: [presentación C](https://claude.ai/artifact/WRjZe6Ykmg9npV7FYXza4w). Lo que dice cada uno:
[guion C](guion_C.md).

**Duración:** parte 1 ~32,5 min + parte 2 (demo) ~7 min = **~39,5 min**. Cada integrante expone
**6,5 min**; además, en la demo cada uno hace una pregunta.

| Orden | Integrante | Bloque | Tiempo |
|---|---|---|---|
| 0 | Nelson | Apertura | 1 min |
| 1 | Jero | Qué es CAG y cómo funciona | 5,5 min |
| 2 | Carlos | Ventajas, desventajas y limitaciones | 6,5 min |
| 3 | Martin | Stack tecnológico I: los datos | 6,5 min |
| 4 | Ramiro | Stack tecnológico II: el modelo y la aplicación | 6,5 min |
| 5 | Nelson | El código de CAG | 5,5 min |
| 6 | Jero | Cierre: conclusiones | 1 min |
| — | Ramiro (conduce) + todos | **Parte 2: demostración** | 7 min |

## Parte 1: la exposición (~32,5 min)

### Apertura · Nelson (1 min)
Portada, pregunta al público («¿Quién tuvo que hacer un trámite y no sabía qué papeles llevar?»)
con la captura real de la respuesta del nacimiento, y la agenda. **Pase:** «Empezamos por la idea
central. Jero.»

### Bloque 1 · Jero · Qué es CAG y cómo funciona (5,5 min)
| Diapositiva | Qué mostrar | Min |
|---|---|---|
| Votación | «¿Cuánto tarda esta PC en leer 15.800 tokens?» (la responde Carlos en el bloque siguiente) | 0,5 |
| Atención: Q, K, V | Las K/V de un token dependen solo de los anteriores: las del corpus se calculan una vez | 1,5 |
| Las tres fases | Analogía de los apuntes; precargar, responder, reiniciar (Chan et al., 2024) | 1,5 |
| El flujo en TramitaIA | Una vez: corpus → caché de 865 MB en disco. Cada pregunta: ~20 tokens sobre la caché | 1 |
| CAG frente a RAG | RAG busca *k* fragmentos y puede traer el equivocado; CAG no busca, pero todo tiene que entrar en el contexto | 1 |

- **Pase:** «Suena muy bien. ¿Tiene contras? Carlos.»

### Bloque 2 · Carlos · Ventajas, desventajas y limitaciones (6,5 min)
| Diapositiva | Qué mostrar | Min |
|---|---|---|
| Hasta la primera palabra | Respuesta a la votación: 630 s sin caché, 8,8 s con CAG (72 veces menos) | 1 |
| Ventajas | Sin errores de búsqueda; latencia; se paga una vez (conviene desde la 2.ª consulta); arquitectura simple; reproducible y verificable; corre local, sin GPU ni internet | 1,5 |
| CAG ahorra leer, no escribir | Gráfico: 708 s → 87,7 s; generar cuesta lo mismo (0,62 s por token) | 1,5 |
| Desventajas | El corpus tiene que entrar en el contexto; memoria (865 MB de caché, ~7 GB la app); reconstruir si cambian los documentos (~11 min); no acelera la escritura; una consulta por vez | 1,5 |
| Limitaciones | El paper: la ventaja se achica con corpus grandes; la calidad depende del modelo (el 1,5B citaba 1 de 8); la caché sirve solo para ese modelo, prompt y parámetros | 1 |

- **Interacción:** antes de «Desventajas», preguntar «¿Qué pasa si el Registro Civil cambia un
  requisito mañana?». Respuesta: hay que reconstruir la caché.
- **Pase:** «¿Con qué está hecho? Empezamos por los datos. Martin.»

### Bloque 3 · Martin · Stack tecnológico I: los datos (6,5 min)
| Diapositiva | Qué mostrar | Min |
|---|---|---|
| Qué sabe el asistente | 12 documentos oficiales, 82 secciones con id, ~15.800 tokens | 1 |
| Stack de datos | requests (con robots.txt), BeautifulSoup, json5, pypdf, manifiesto con versiones y SHA-256, tokenizer de Qwen | 1,5 |
| Ni las fuentes coinciden | Pasaporte de un menor: Registro Civil frente a Justicia; la app muestra las dos | 1 |
| Cada capa frenó un caso real | Alcance, citas desde el registro, filtro de tema, frases, costos, abstención | 2 |
| ¿No sé o algo falso? | 12 de 12 sin información inventada; la verificación es léxica | 1 |

- **Pase:** «Esos datos los lee un modelo dentro de una aplicación. Ramiro.»

### Bloque 4 · Ramiro · Stack tecnológico II: el modelo y la aplicación (6,5 min)
| Diapositiva | Qué mostrar | Min |
|---|---|---|
| Stack del modelo y la app | Qwen2.5-7B-Instruct Q4_K_M, llama.cpp (llama-cpp-python 0.3.36), FastAPI + uvicorn con SSE, HTML + CSS + Alpine.js, Python 3.12, pytest | 1,5 |
| Por qué estas piezas | 7B en PyTorch no entraba (15,2 GB de pesos); llama.cpp guarda y recorta la caché; interfaz sin dependencias externas, anda sin internet | 1,5 |
| Arquitectura | Los seis pasos, de la pregunta a la respuesta citada; cola y calentamiento | 2 |
| Borrador en vivo | «Sin verificar» hasta que termina la verificación | 1,5 |

- **Interacción:** en el borrador, «¿Por qué creen que dice *sin verificar*?».
- **Pase:** «Por dentro de ese motor está CAG. Nelson.»

### Bloque 5 · Nelson · El código de CAG (5,5 min)
| Diapositiva | Archivo | Qué mostrar | Min |
|---|---|---|---|
| Prefijo | `app/cag/prompt.py` | Qué se cachea (~15.800 tokens) y qué va por consulta (~20) | 1 |
| Construir y guardar | `llamacpp_engine.py` (`_prepare_locked`, `_save`) | Una pasada (~11 min), `state.bin` + `meta.json`, carpeta temporal, `cache_id` | 1,5 |
| Cargar desde disco | `llamacpp_engine.py` (`_load`) | Valida `meta.json`, `load_state`, recalcula la huella | 1 |
| Responder | `llamacpp_engine.py` (`answer`) | Los siete pasos y el `finally` | 1,5 |
| ¿Está bien? | `tests/`, Fase 6 | «¿Qué pasa si no limpio la caché?»; 117 posiciones; 6 de 6 idénticas | 0,5 |

- **Pase:** «Para cerrar, Jero.»

### Cierre · Jero (1 min)
Conclusiones: tres ideas para llevarse, volviendo a la analogía de los apuntes. **Pase a la demo:**
«Ahora, verlo funcionando.»

## Parte 2: la demostración (~7 min)

Igual que en la versión B: la conduce **Ramiro** y cada integrante hace una pregunta. Guion, lista
de control y plan B en el [README](README.md#demo-parte-2-lista-de-control).
