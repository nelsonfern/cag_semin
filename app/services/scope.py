"""Control de alcance: ¿la pregunta es sobre trámites? (§4, paso C.2 de la especificación).

Se hace **antes** de llamar al modelo, que tarda de 30 s a 3 minutos por respuesta: una pregunta
sobre programación o recetas se responde al instante, sin generar nada.

Criterio (deliberadamente simple y explicable): la pregunta está en el alcance si alguna de sus
palabras de contenido aparece en los **títulos y encabezados de los documentos oficiales** o en un
conjunto de **palabras de trámites y administrativas** («partida», «certificado», «licencia»,
«impuesto»...). Las palabras (de 4 letras o más) se comparan por su raíz de 5 letras sin tildes.
No se usa el texto completo del corpus: tiene palabras generales («capital», «escribir»,
«instalar») que dejaban pasar preguntas ajenas, como «¿Cuál es la capital de Francia?».

Las preguntas sobre trámites que el corpus no tiene (licencia de conducir, monotributo) siguen
pasando: el modelo se abstiene y eso se informa con las fuentes oficiales a consultar. El control
no reemplaza a las verificaciones de citas, que siguen aplicándose a todo lo que se genera.
"""

from __future__ import annotations

import re
import unicodedata

OUT_OF_SCOPE_MESSAGE = (
    "TramitaIA solo responde preguntas sobre trámites públicos de La Rioja (partidas, DNI, pasaporte, "
    "matrimonio, unión convivencial, defunciones y otros trámites del Registro Civil y la Secretaría de "
    "Justicia). Reformulá tu consulta sobre un trámite."
)

# Palabras que no indican el tema: artículos, preposiciones, interrogativos y verbos genéricos.
_STOP = set("""
como cual cuales cuando cuanto cuanta cuantos cuantas donde quien quienes que porque para pero sobre
entre desde hasta hacia segun sino tambien este esta esto estos estas ese esa eso esos esas aquel
algo alguno alguna algun todo toda todos todas cada otro otra otros otras mismo misma muy mucho mucha
hago hace hacen hacer hacerlo haria puedo puede pueden podes podria quiero quiere queres quisiera
necesito necesita necesitan necesitas debo debe deben tengo tiene tienen tenes saber sabes explicar
explicame explica decime decir dime ayuda ayudame ayudar gracias hola buenas buen bueno buena dias
tardes noches favor serian seria estan estoy esta tener tenga usar usan funciona funcionan
""".split())

# Vocabulario administrativo general: trámites que pueden no estar en el corpus pero son del
# alcance (el modelo debe abstenerse y recomendar el organismo, no quedar fuera de alcance).
_ADMIN = set("""
tramite tramites tramitar requisito requisitos documento documentacion certificado certificados
constancia constancias licencia licencias permiso permisos habilitacion inscripcion inscribir
inscribo registro registrar oficina oficinas turno turnos costo costos arancel tasa tasas pagar pago
impuesto impuestos monotributo afip arca anses jubilacion pension subsidio domicilio antecedentes
penales policia municipalidad municipio ministerio gobierno provincia provincial nacional estado
ciudadano ciudadana identidad documento legalizar legalizacion apostilla firma juzgado
divorcio herencia sucesion adopcion tutela vehiculo patente conducir residencia ciudadania
partida partidas acta actas nacimiento nacimientos nacido recien bebe hijo hija matrimonio casamiento
casarme casarse casar defuncion fallecimiento fallecido murio muerte union convivencial convivencia pasaporte dni
rectificacion rectificar error correccion copia legalizada certificada registro civil justicia
""".split())


# Raíces de títulos y encabezados demasiado generales para indicar que una pregunta es sobre
# trámites (Fase 6: «¿Cómo preparo un asado para diez personas?» pasaba por «Dirección de Personas
# Jurídicas»; «ejemp» de «Nuevo ejemplar» es también la raíz de «ejemplo»).
_GENERIC_HEADING_STEMS = set("""
perso infor pregu frecu nuevo ejemp publi direc inici reali prese prima prime acces actua adici anos
anual cambi crono deter digit eleme extra ingre instr integ perio recep unida valid reque contr mayor
""".split())


def _stems(text: str) -> set[str]:
    """Raíces de 5 letras, sin tildes, de las palabras de 3+ letras que no son vacías."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    words = re.findall(r"[a-z0-9]{3,}", text)
    # 4 letras o más, salvo siglas de trámites (dni).
    return {w[:5] for w in words if (len(w) >= 4 or w == "dni") and w not in _STOP and not w.isdigit()}


class ScopeChecker:
    """Decide si una pregunta es del alcance de TramitaIA con el vocabulario del corpus."""

    def __init__(self, corpus_texts: list[str]):
        self.vocabulary = set().union(*(_stems(t) for t in corpus_texts)) | _stems(" ".join(_ADMIN))

    @classmethod
    def from_index(cls, index) -> "ScopeChecker":
        """Vocabulario de los títulos y encabezados del ``CitationIndex`` (el corpus en la caché)."""
        texts = [h for _, h, _ in index.sections.values() if h]
        texts += [d.title for d in index.documents.values()]
        checker = cls(texts)
        # Se sacan las raíces generales de los encabezados; las del vocabulario administrativo quedan.
        checker.vocabulary -= _GENERIC_HEADING_STEMS - _stems(" ".join(_ADMIN))
        return checker

    def matching_words(self, question: str) -> set[str]:
        """Raíces de la pregunta que están en el vocabulario (vacío = fuera de alcance)."""
        return _stems(question) & self.vocabulary

    def in_scope(self, question: str) -> bool:
        return bool(self.matching_words(question))
