"""Codificación de los mensajes del acceso remoto (JSON, uno por línea).

Las secuencias de voz (mensaje ``speak``) mezclan cadenas y órdenes de voz.
En el cable, cada orden viaja como ``[nombreDeClase, atributos]`` con los
nombres y atributos que usa NVDA (por ejemplo
``["PitchCommand", {"_offset": 30, "_multiplier": 1, "isDefault": false}]``),
para que Tiresias y NVDA se entiendan. Aquí se traducen a y desde las
órdenes de :mod:`tiresias.speech.commands`. Las órdenes que no tienen
sentido en otro equipo (llamadas, índices, pitidos y sonidos intercalados)
no se envían: los pitidos y sonidos viajan aparte como ``tone`` y ``wave``.
"""

from __future__ import annotations

import json
import math

from enum import Enum
from typing import Any

from ..log import getLogger
from ..speech import commands as cmds

log = getLogger("remote")

SEP = b"\n"

_PROSODY = {
	"PitchCommand": cmds.PitchCommand,
	"RateCommand": cmds.RateCommand,
	"VolumeCommand": cmds.VolumeCommand,
}


def encodeSpeechItem(item: Any) -> Any:
	"""Orden de Tiresias -> formato del cable (``None`` si no se envía)."""
	if isinstance(item, str):
		return item
	if isinstance(item, cmds.CharacterModeCommand):
		state = bool(item.state)
		return ["CharacterModeCommand", {"state": state, "isDefault": not state}]
	if isinstance(item, cmds.LangChangeCommand):
		return ["LangChangeCommand", {"lang": item.lang, "isDefault": not item.lang}]
	if isinstance(item, cmds.BreakCommand):
		return ["BreakCommand", {"time": int(item.time)}]
	if isinstance(item, (cmds.PitchCommand, cmds.RateCommand, cmds.VolumeCommand)):
		offset = item.offset
		mult = item.multiplier
		return [type(item).__name__, {"_offset": offset, "_multiplier": mult, "isDefault": offset == 0 and mult == 1}]
	if isinstance(item, cmds.PhonemeCommand):
		return ["PhonemeCommand", {"ipa": item.ipa, "text": item.text or None}]
	if isinstance(item, cmds.EndUtteranceCommand):
		return ["EndUtteranceCommand", {}]
	# IndexCommand, CallbackCommand, BeepCommand, WaveFileCommand: solo locales.
	return None


def encodeSpeechSequence(sequence: list) -> list:
	out = []
	for item in sequence:
		enc = encodeSpeechItem(item)
		if enc is None or enc == "":
			continue
		out.append(enc)
	return out


#: Límites de lo que se acepta de otro equipo.
MAX_PROSODY_OFFSET = 100
MAX_PROSODY_MULTIPLIER = 10.0
MAX_BREAK_MS = 10000


def _number(value: Any) -> float:
	"""Número finito (lanza ``ValueError`` con cadenas, booleanos, NaN o infinitos)."""
	if isinstance(value, bool) or not isinstance(value, (int, float)):
		raise ValueError(f"no es un número: {value!r}")
	value = float(value)
	if not math.isfinite(value):
		raise ValueError("número no finito")
	return value


def decodeSpeechItem(item: Any) -> Any:
	"""Formato del cable -> orden de Tiresias (``None`` si se ignora)."""
	if isinstance(item, str):
		return item
	if not (isinstance(item, (list, tuple)) and len(item) == 2 and isinstance(item[0], str)):
		return None
	name, values = item
	if not isinstance(values, dict):
		values = {}
	try:
		if name == "CharacterModeCommand":
			return cmds.CharacterModeCommand(bool(values.get("state", False)))
		if name == "LangChangeCommand":
			lang = values.get("lang")
			return cmds.LangChangeCommand(lang if isinstance(lang, str) and lang else None)
		if name == "BreakCommand":
			return cmds.BreakCommand(int(max(0.0, min(_number(values.get("time", 0) or 0), MAX_BREAK_MS))))
		if name in _PROSODY:
			offset = _number(values.get("_offset", values.get("offset", 0)) or 0)
			mult = values.get("_multiplier", values.get("multiplier", 1))
			mult = 1.0 if mult is None else _number(mult)
			# Valores acotados: el sintetizador fallaría con NaN, infinitos o cadenas.
			offset = int(max(-MAX_PROSODY_OFFSET, min(MAX_PROSODY_OFFSET, offset)))
			mult = max(0.0, min(MAX_PROSODY_MULTIPLIER, mult))
			return _PROSODY[name](offset=offset, multiplier=mult)
		if name == "PhonemeCommand":
			return cmds.PhonemeCommand(str(values.get("ipa", "")), values.get("text") or "")
		if name == "EndUtteranceCommand":
			return cmds.EndUtteranceCommand()
	except (TypeError, ValueError):
		log.debug("Orden de voz remota no válida: %r", item)
		return None
	log.debug("Orden de voz remota desconocida: %r", name)
	return None


def decodeSpeechSequence(sequence: Any) -> list:
	if not isinstance(sequence, list):
		return []
	out = []
	for item in sequence:
		dec = decodeSpeechItem(item)
		if dec is not None:
			out.append(dec)
	return out


class _Encoder(json.JSONEncoder):
	def default(self, o: Any) -> Any:
		if isinstance(o, Enum):
			return o.value
		if isinstance(o, (set, frozenset, tuple)):
			return list(o)
		if isinstance(o, cmds.SpeechCommand):
			return encodeSpeechItem(o)
		return super().default(o)


def serialize(type: Any, **payload: Any) -> bytes:
	"""Mensaje -> bytes (JSON en UTF-8 terminado en salto de línea)."""
	if isinstance(type, Enum):
		type = type.value
	payload["type"] = type
	if type == "speak" and isinstance(payload.get("sequence"), list):
		payload["sequence"] = encodeSpeechSequence(payload["sequence"])
	return json.dumps(payload, cls=_Encoder, separators=(",", ":")).encode("utf-8") + SEP


def deserialize(line: bytes | str) -> dict:
	"""Bytes de una línea -> diccionario. Las secuencias de voz se traducen.

	Lanza :class:`ValueError` si la línea no es un objeto JSON.
	"""
	if isinstance(line, bytes):
		line = line.decode("utf-8", errors="replace")
	obj = json.loads(line)
	if not isinstance(obj, dict):
		raise ValueError("El mensaje no es un objeto JSON")
	if obj.get("type") == "speak" and "sequence" in obj:
		obj["sequence"] = decodeSpeechSequence(obj["sequence"])
	return obj


def deserializeRaw(line: bytes | str) -> dict:
	"""Como :func:`deserialize` pero sin traducir la voz (lo usa el servidor)."""
	if isinstance(line, bytes):
		line = line.decode("utf-8", errors="replace")
	obj = json.loads(line)
	if not isinstance(obj, dict):
		raise ValueError("El mensaje no es un objeto JSON")
	return obj


def serializeRaw(obj: dict) -> bytes:
	return json.dumps(obj, separators=(",", ":")).encode("utf-8") + SEP
