"""Adaptadores de formatos de sesión externos."""

from .opencode import normalize_opencode_export
from .pi import normalize_pi_jsonl

__all__ = ["normalize_opencode_export", "normalize_pi_jsonl"]
