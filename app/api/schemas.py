"""Modelos de entrada de la API (la salida se arma con ``Answer.to_dict`` y diccionarios simples)."""

from __future__ import annotations

from pydantic import BaseModel, Field

from app.cag.engine import MAX_QUESTION_CHARS


class ChatRequest(BaseModel):
    """Una pregunta independiente: TramitaIA no usa el historial (cada consulta parte del prefijo)."""

    question: str = Field(..., min_length=1, max_length=MAX_QUESTION_CHARS)
    max_new_tokens: int | None = Field(None, ge=16, le=512, description="por defecto, el del motor (512)")
