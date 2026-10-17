/* TramitaIA — lógica de la interfaz (Alpine.js). Es solo un cliente de la API FastAPI.
 *
 * Seguridad del texto del modelo: se escapa todo el HTML y solo se agregan negritas, listas y
 * marcas de cita. Nunca se crean enlaces a partir del texto generado: los únicos enlaces son los
 * del registro documental (panel de fuentes y lista de documentos). */

const EJEMPLOS = [
  { tema: "Pasaporte", texto: "¿Qué requisitos publica el Registro Civil para el pasaporte de un menor?" },
  { tema: "Unión convivencial", texto: "¿Cuáles son los requisitos para registrar una unión convivencial?" },
  { tema: "Defunciones", texto: "¿Qué requisitos piden para inscribir una defunción?" },
  { tema: "DNI", texto: "¿Qué necesito para tramitar el DNI de un recién nacido?" },
];

const INSIGNIAS = {
  answered: { texto: "Con respaldo en documentos oficiales", clase: "insignia--verde" },
  abstained: { texto: "Sin información en los documentos", clase: "insignia--ambar" },
  unsupported: { texto: "Sin respaldo verificable", clase: "insignia--ambar" },
  out_of_scope: { texto: "Fuera del alcance de TramitaIA", clase: "insignia--gris" },
};

const CITA = /\[([a-z0-9][a-z0-9-]*#(?:s\d+|art-\d+)(?:\s*[,;]\s*[a-z0-9][a-z0-9-]*#(?:s\d+|art-\d+))*)\]/g;

function escapar(texto) {
  return texto.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

/** Markdown mínimo y seguro: párrafos, listas, negritas y citas. Sin enlaces ni HTML. */
function formatear(texto) {
  if (!texto) return "";
  const enLinea = (linea) => escapar(linea)
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(CITA, (_, ids) => ids.split(/\s*[,;]\s*/).map((id) => `<span class="cita">${id}</span>`).join(""));
  const html = [];
  let lista = null;
  const cerrar = () => { if (lista) { html.push(`</${lista}>`); lista = null; } };
  for (const cruda of texto.split("\n")) {
    const linea = cruda.trim();
    const vineta = linea.match(/^[-*•]\s+(.*)$/);
    const numero = linea.match(/^\d+[.)]\s+(.*)$/);
    if (vineta || numero) {
      const tipo = vineta ? "ul" : "ol";
      if (lista !== tipo) { cerrar(); html.push(`<${tipo}>`); lista = tipo; }
      html.push(`<li>${enLinea((vineta || numero)[1])}</li>`);
    } else {
      cerrar();
      if (linea) html.push(`<p>${enLinea(linea)}</p>`);
    }
  }
  cerrar();
  return html.join("");
}

/** Lee un flujo de Server-Sent Events y llama a ``alEvento(evento, datos)`` por cada uno. */
async function leerSSE(respuesta, alEvento) {
  const lector = respuesta.body.getReader();
  const decodificador = new TextDecoder();
  let pendiente = "";
  for (;;) {
    const { value, done } = await lector.read();
    if (done) break;
    pendiente += decodificador.decode(value, { stream: true });
    let corte;
    while ((corte = pendiente.indexOf("\n\n")) >= 0) {
      const bloque = pendiente.slice(0, corte);
      pendiente = pendiente.slice(corte + 2);
      let evento = "message";
      const datos = [];
      for (const linea of bloque.split("\n")) {
        if (linea.startsWith("event:")) evento = linea.slice(6).trim();
        else if (linea.startsWith("data:")) datos.push(linea.slice(5).trim());
      }
      if (datos.length) alEvento(evento, JSON.parse(datos.join("\n")));
    }
  }
}

async function mensajeDeError(respuesta) {
  try {
    const cuerpo = await respuesta.json();
    const detalle = cuerpo.detail;
    if (detalle && typeof detalle === "object" && !Array.isArray(detalle)) return detalle.message || JSON.stringify(detalle);
    if (Array.isArray(detalle)) return "La consulta no es válida (vacía o demasiado larga).";
  } catch (_) { /* sin cuerpo JSON */ }
  return `La API respondió ${respuesta.status}.`;
}

function tramitaia() {
  return {
    pregunta: "",
    ejemplos: EJEMPLOS,
    historial: [],
    fuentes: null,
    salud: null,
    enCurso: false,
    menu: false,
    siguienteId: 1,

    get listo() { return this.salud && this.salud.status === "ready"; },
    get puedeConsultar() { return this.listo && !this.enCurso; },
    get estado() {
      if (!this.salud) return { clase: "error", texto: "Sin conexión con TramitaIA", corto: "Sin conexión" };
      if (this.salud.status === "ready") return { clase: "listo", texto: "Listo para responder", corto: "En línea" };
      if (this.salud.status === "loading") return { clase: "cargando", texto: "Preparando el asistente (alrededor de un minuto)…", corto: "Preparando…" };
      return { clase: "error", texto: "El asistente no pudo iniciarse", corto: "Error" };
    },
    get motor() {
      const e = this.salud && this.salud.engine;
      if (!e || !e.model_id) return "";
      const modelo = e.model_id.split("/").pop().replace(/\.gguf$/, "");
      return `Motor ${e.engine || ""} · ${modelo} · caché ${e.cache_id} (${e.prefix_tokens} tokens del corpus)`;
    },

    async init() {
      await this.actualizarSalud();
      this.cargarFuentes();
      setInterval(() => this.actualizarSalud(), 5000);
    },

    async actualizarSalud() {
      try {
        const r = await fetch("/health", { cache: "no-store" });
        this.salud = r.ok ? await r.json() : null;
      } catch (_) { this.salud = null; }
    },

    async cargarFuentes() {
      try {
        const r = await fetch("/sources");
        if (r.ok) this.fuentes = await r.json();
      } catch (_) { /* el lateral queda sin la lista */ }
    },

    async preguntar() {
      const pregunta = this.pregunta.trim();
      if (!pregunta || !this.listo || this.enCurso) return;
      const item = { id: this.siguienteId++, pregunta, estado: "en-curso", fase: 1, cola: 0, borrador: "",
                     final: null, error: "", verFuentes: false, verAvisos: false };
      this.historial.push(item);
      const vivo = this.historial[this.historial.length - 1]; // referencia reactiva de Alpine
      this.pregunta = "";
      this.$nextTick(() => { this.autoajustar(); this.bajar(true); });
      this.enCurso = true;
      try {
        const r = await fetch("/chat/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question: pregunta }),
        });
        if (!r.ok) throw new Error(await mensajeDeError(r));
        await leerSSE(r, (evento, datos) => {
          if (evento === "queued") vivo.cola = datos.ahead || 0;
          else if (evento === "token") { vivo.fase = 2; vivo.cola = 0; vivo.borrador += datos.text; this.bajar(); }
          else if (evento === "replace") { vivo.fase = 2; vivo.borrador = datos.text; this.bajar(); }
          else if (evento === "final") { vivo.final = datos; vivo.estado = "lista"; this.$nextTick(() => this.bajar()); }
          else if (evento === "error") throw new Error(datos.message || "Error en la API");
        });
        if (!vivo.final) throw new Error("La conexión se cortó antes de terminar la respuesta.");
      } catch (e) {
        vivo.estado = "error";
        vivo.error = e.message || String(e);
      } finally {
        this.enCurso = false;
        this.$nextTick(() => this.$refs.campo && this.$refs.campo.focus());
      }
    },

    nuevaConsulta() {
      if (this.enCurso) return; // la consulta en curso sigue en el servidor: se espera a que termine
      this.historial = [];
      this.pregunta = "";
      this.menu = false;
      this.$nextTick(() => { this.autoajustar(); this.$refs.campo && this.$refs.campo.focus(); });
    },

    /** Ajusta la altura del campo al texto (hasta el máximo del CSS). */
    autoajustar() {
      const campo = this.$refs.campo;
      if (!campo) return;
      campo.style.height = "auto";
      campo.style.height = `${campo.scrollHeight}px`;
    },

    /** Lleva la conversación al último mensaje, salvo que el usuario haya subido a leer. */
    bajar(forzar = false) {
      const caja = this.$refs.scroll;
      if (!caja) return;
      const cerca = caja.scrollHeight - caja.scrollTop - caja.clientHeight < 160;
      if (forzar || cerca) caja.scrollTop = caja.scrollHeight;
    },

    paso(item, n) {
      if (n < item.fase) return "hecho";
      if (n === item.fase) return "actual";
      return "";
    },
    insignia(decision) { return INSIGNIAS[decision] || { texto: decision, clase: "insignia--gris" }; },
    formatear,

    /** Citas agrupadas por documento (los datos salen del registro, no del texto del modelo). */
    fuentesDe(final) {
      const porDoc = new Map();
      for (const c of (final && final.citations) || []) {
        const d = c.document;
        if (!porDoc.has(d.document_id)) porDoc.set(d.document_id, { ...d, sections: [] });
        porDoc.get(d.document_id).sections.push({ section_id: c.section_id, heading: c.heading });
      }
      return [...porDoc.values()];
    },
    jurisdiccion(j) { return j === "nacional" ? "Nacional" : j === "provincial" ? "Provincial · La Rioja" : (j || ""); },
    fecha(valor) {
      if (!valor) return "sin fecha publicada";
      const [a, m, d] = String(valor).slice(0, 10).split("-");
      return `${d}/${m}/${a}`;
    },
    segundos(s) {
      if (s == null) return "—";
      return s >= 60 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${s.toFixed(1)} s`;
    },
  };
}

// En el navegador, Alpine busca el componente en window; en Node (tests) se exportan las funciones.
if (typeof window !== "undefined") window.tramitaia = tramitaia;
if (typeof module !== "undefined") module.exports = { formatear, escapar, tramitaia };
