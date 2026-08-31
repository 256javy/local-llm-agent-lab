"""Almacenamiento y contratos para trazas locales de agentes."""

from .capture import capture_opencode, capture_pi
from .store import TraceStore

__all__ = ["TraceStore", "capture_opencode", "capture_pi"]
