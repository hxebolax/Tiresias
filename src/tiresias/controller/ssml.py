"""Interpretación del SSML que mandan los programas con ``speakSsml``.

:func:`parse` convierte el SSML en una lista neutra de elementos (cadenas y
tuplas) que no depende de la voz ni de la configuración, para poder
probarla sin el lector:

- ``"texto"``
- ``("break", milisegundos)``
- ``("mark", nombre)``
- ``("pitch" | "rate" | "volume", multiplicador)`` (1.0 = normal)
- ``("lang", código | None)``
- ``("spell", texto)``: deletrear (``say-as interpret-as="characters"``)
- ``("phoneme", ipa, texto)``

Se admite el subconjunto habitual: ``speak``, ``p``, ``s``, ``break``,
``mark``, ``prosody``, ``voice``/``lang``/``xml:lang``, ``say-as``,
``sub``, ``phoneme``, ``emphasis`` y ``audio`` (se lee su texto
alternativo). Lo desconocido se lee como texto. Si el SSML no es XML
válido, se quitan las etiquetas y se lee el texto.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

_PITCH_WORDS = {"x-low": 0.5, "low": 0.75, "medium": 1.0, "default": 1.0, "high": 1.25, "x-high": 1.5}
_RATE_WORDS = {"x-slow": 0.5, "slow": 0.75, "medium": 1.0, "default": 1.0, "fast": 1.5, "x-fast": 2.0}
_VOLUME_WORDS = {"silent": 0.0, "x-soft": 0.4, "soft": 0.7, "medium": 1.0, "default": 1.0, "loud": 1.2, "x-loud": 1.4}
_STRENGTH_MS = {"none": 0, "x-weak": 100, "weak": 200, "medium": 400, "strong": 700, "x-strong": 1000}
_SPELL_KINDS = {"characters", "spell-out", "verbatim", "letters"}

#: Pausa máxima admitida (evita que un programa deje la voz parada).
MAX_BREAK_MS = 5000


def _localName(tag: str) -> str:
	return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def parseTime(value: str) -> int | None:
	"""``"500ms"``, ``"1.5s"`` o ``"300"`` → milisegundos (``None`` si no vale)."""
	m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(ms|s)?\s*", value or "")
	if not m:
		return None
	n = float(m.group(1))
	ms = n * 1000 if m.group(2) == "s" else n
	return max(0, min(MAX_BREAK_MS, int(ms)))


def parseMultiplier(value: str, words: dict[str, float]) -> float | None:
	"""Valor de ``prosody`` → multiplicador (``"150%"``, ``"+20%"``, ``"-10%"``, ``"high"``, ``"1.5"``)."""
	if not value:
		return None
	v = value.strip().lower()
	if v in words:
		return words[v]
	m = re.fullmatch(r"([+-])?(\d+(?:\.\d+)?)\s*%", v)
	if m:
		n = float(m.group(2)) / 100.0
		if m.group(1) == "+":
			return 1.0 + n
		if m.group(1) == "-":
			return max(0.0, 1.0 - n)
		return n
	m = re.fullmatch(r"(\d+(?:\.\d+)?)", v)
	if m:
		return float(m.group(1))
	return None


def stripTags(text: str) -> str:
	"""Texto de un SSML no válido: sin etiquetas y con entidades resueltas."""
	return html.unescape(re.sub(r"<[^>]*>", " ", text or "")).strip()


class _Builder:
	def __init__(self) -> None:
		self.items: list = []
		self.state = {"pitch": [1.0], "rate": [1.0], "volume": [1.0], "lang": [None]}

	def text(self, s: str | None) -> None:
		if not s:
			return
		s = " ".join(s.split())
		if not s:
			return
		if self.items and isinstance(self.items[-1], str):
			self.items[-1] = self.items[-1] + " " + s
		else:
			self.items.append(s)

	def push(self, kind: str, value) -> None:
		self.state[kind].append(value)
		self.items.append((kind, value))

	def pop(self, kind: str) -> None:
		stack = self.state[kind]
		if len(stack) > 1:
			stack.pop()
		self.items.append((kind, stack[-1]))

	def walk(self, el: ET.Element) -> None:
		name = _localName(el.tag)
		pushed: list[str] = []
		lang = el.get(XML_LANG) or el.get("lang")
		if lang and name not in ("say-as",):
			self.push("lang", lang)
			pushed.append("lang")
		if name == "break":
			ms = parseTime(el.get("time", ""))
			if ms is None:
				ms = _STRENGTH_MS.get((el.get("strength") or "medium").lower(), 400)
			self.items.append(("break", ms))
		elif name == "mark":
			markName = el.get("name")
			if markName:
				self.items.append(("mark", markName))
		elif name == "prosody":
			for attr, words in (("pitch", _PITCH_WORDS), ("rate", _RATE_WORDS), ("volume", _VOLUME_WORDS)):
				mult = parseMultiplier(el.get(attr, ""), words)
				if mult is not None:
					self.push(attr, mult)
					pushed.append(attr)
		if name == "say-as" and (el.get("interpret-as") or "").lower() in _SPELL_KINDS:
			text = "".join(el.itertext()).strip()
			if text:
				self.items.append(("spell", text))
		elif name == "sub":
			self.text(el.get("alias") or "".join(el.itertext()))
		elif name == "phoneme":
			inner = "".join(el.itertext()).strip()
			ipa = el.get("ph") or ""
			if ipa and (el.get("alphabet") or "ipa").lower() == "ipa":
				self.items.append(("phoneme", ipa, inner))
			else:
				self.text(inner)
		elif name in ("break", "mark"):
			pass
		else:
			self.text(el.text)
			for child in el:
				self.walk(child)
				self.text(child.tail)
			if name in ("p", "s"):
				# Separación entre frases y párrafos.
				self.items.append(("break", 100 if name == "s" else 300))
		for kind in reversed(pushed):
			self.pop(kind)


def parse(ssml: str) -> list:
	"""Convierte SSML en la lista neutra descrita en el módulo."""
	source = (ssml or "").strip()
	if not source:
		return []
	if not source.startswith("<"):
		source = f"<speak>{source}</speak>"
	try:
		root = ET.fromstring(source)
	except ET.ParseError:
		try:
			root = ET.fromstring(f"<speak>{source}</speak>")
		except ET.ParseError:
			text = stripTags(ssml)
			return [text] if text else []
	b = _Builder()
	b.walk(root)
	items = b.items
	# Quita los cambios de prosodia o idioma finales que no afectan a nada.
	while items and isinstance(items[-1], tuple) and items[-1][0] in ("pitch", "rate", "volume", "lang", "break"):
		items.pop()
	return items


def plainText(items: list) -> str:
	"""Texto legible de una lista de :func:`parse` (para el historial y el braille)."""
	parts: list[str] = []
	for it in items:
		if isinstance(it, str):
			parts.append(it)
		elif it[0] == "spell":
			parts.append(it[1])
		elif it[0] == "phoneme" and it[2]:
			parts.append(it[2])
	return " ".join(p for p in parts if p).strip()
