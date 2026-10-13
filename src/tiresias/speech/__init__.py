"""Subsistema de voz.

Las funciones públicas están en :mod:`tiresias.speech.api` y se reexportan
aquí de forma perezosa para evitar importaciones circulares con los
sintetizadores. Así, ``from tiresias import speech; speech.speakMessage("x")``
funciona sin cargar nada hasta que se usa.
"""

from __future__ import annotations

import importlib
from typing import Any

# Las opciones de voz deben existir antes de cualquier lectura de ``conf``.
from . import defaults as _defaults  # noqa: F401

_SUBMODULES = (
	"api",
	"commands",
	"symbols",
	"dictionaries",
	"sayall",
	"defaults",
	"languages",
	"langdetect",
	"numbers",
	"voice_schemes",
	"verbosity",
	"plugin",
)


def __getattr__(name: str) -> Any:
	if name.startswith("__"):
		raise AttributeError(name)
	if name in _SUBMODULES:
		return importlib.import_module(f"{__name__}.{name}")
	api = importlib.import_module(__name__ + ".api")
	try:
		return getattr(api, name)
	except AttributeError:
		raise AttributeError(f"module 'tiresias.speech' has no attribute {name!r}") from None
