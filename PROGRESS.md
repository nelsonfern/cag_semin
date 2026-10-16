# Bitácora de TramitaIA (PROGRESS.md)

Registro del estado de cada fase, decisiones técnicas, comandos ejecutados,
pruebas aprobadas y tareas pendientes. Cada fase cierra con un commit.

## Estado de fases

| Fase | Descripción | Estado |
|------|-------------|--------|
| 0 | Inicialización del repositorio | Completada |
| 1 | Fuentes e ingesta | Pendiente |
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
