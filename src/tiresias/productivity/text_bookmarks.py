"""Marcadores de posición en cualquier aplicación con texto.

Funciona en campos editables y documentos (Bloc de notas, Word, editores de
código, campos de los navegadores...) y en modo exploración. Cada marcador
guarda su posición en caracteres y un trocito del texto que la rodea: si el
documento ha cambiado, al saltar se busca ese trocito cerca de la posición
original, así el marcador «sigue» al texto aunque se escriba antes.

Los marcadores se guardan por aplicación y documento (título de la ventana
sin la marca de «sin guardar») en ``data/config/marcadores_texto.json``.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass

from ..log import getLogger

log = getLogger("productivity")

#: Caracteres de contexto que se guardan a cada lado del marcador.
CONTEXT_CHARS = 24


@dataclass
class TextBookmark:
	offset: int
	before: str = ""
	after: str = ""
	name: str = ""
	created: float = 0.0

	@classmethod
	def at(cls, text: str, offset: int, name: str = "") -> "TextBookmark":
		offset = max(0, min(offset, len(text)))
		return cls(offset, text[max(0, offset - CONTEXT_CHARS) : offset], text[offset : offset + CONTEXT_CHARS], name, time.time())

	def preview(self) -> str:
		return " ".join((self.after or self.before).split())[:60]


def relocate(bm: TextBookmark, text: str) -> int:
	"""Posición actual del marcador en ``text`` (busca su contexto cerca)."""
	n = len(text)
	if not text:
		return 0
	offset = min(bm.offset, n)
	if text[offset : offset + len(bm.after)] == bm.after and text[max(0, offset - len(bm.before)) : offset] == bm.before:
		return offset
	best: tuple[int, int] | None = None
	for needle, shift in ((bm.before + bm.after, len(bm.before)), (bm.after, 0), (bm.before, len(bm.before))):
		if len(needle.strip()) < 3:
			continue
		start = 0
		while True:
			i = text.find(needle, start)
			if i < 0:
				break
			pos = i + shift
			dist = abs(pos - bm.offset)
			if best is None or dist < best[0]:
				best = (dist, pos)
			start = i + 1
		if best is not None:
			return best[1]
	return offset


class BookmarkStore:
	def __init__(self, path: str | None) -> None:
		self.path = path
		self._lock = threading.Lock()
		self._data: dict[str, list[TextBookmark]] | None = None

	def _load(self) -> dict[str, list[TextBookmark]]:
		if self._data is not None:
			return self._data
		data: dict[str, list[TextBookmark]] = {}
		if self.path and os.path.isfile(self.path):
			try:
				with open(self.path, encoding="utf-8") as f:
					raw = json.load(f)
				for key, items in (raw.get("documents") or {}).items():
					marks = []
					for it in items:
						try:
							marks.append(TextBookmark(**{k: v for k, v in it.items() if k in TextBookmark.__dataclass_fields__}))
						except TypeError:
							continue
					if marks:
						data[key] = marks
			except (OSError, ValueError, AttributeError):
				log.exception("No se pudieron leer los marcadores de texto")
		self._data = data
		return data

	def save(self) -> None:
		if not self.path:
			return
		with self._lock:
			data = self._load()
			os.makedirs(os.path.dirname(self.path), exist_ok=True)
			tmp = self.path + ".tmp"
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump({"version": 1, "documents": {k: [asdict(b) for b in v] for k, v in data.items() if v}}, f, ensure_ascii=False, indent=1)
			os.replace(tmp, self.path)

	def get(self, key: str) -> list[TextBookmark]:
		with self._lock:
			return sorted(self._load().get(key, []), key=lambda b: b.offset)

	def set(self, key: str, marks: list[TextBookmark]) -> None:
		with self._lock:
			data = self._load()
			if marks:
				data[key] = sorted(marks, key=lambda b: b.offset)
			else:
				data.pop(key, None)
		self.save()

	def keys(self) -> list[str]:
		with self._lock:
			return sorted(self._load())

	def toggle(self, key: str, text: str, offset: int, lineBounds) -> bool:
		"""Pone un marcador en ``offset`` o quita el de esa línea. ``True`` si se ha puesto."""
		marks = self.get(key)
		start, end = lineBounds(offset)
		for bm in marks:
			pos = relocate(bm, text)
			if start <= pos <= end:
				marks.remove(bm)
				self.set(key, marks)
				return False
		marks.append(TextBookmark.at(text, offset))
		self.set(key, marks)
		return True

	def neighbour(self, key: str, text: str, offset: int, direction: int, lineBounds) -> tuple[int | None, bool]:
		"""Posición del marcador siguiente (1) o anterior (-1) y si se ha dado la vuelta."""
		marks = self.get(key)
		if not marks:
			return None, False
		positions = sorted({relocate(bm, text) for bm in marks})
		lineStart, lineEnd = lineBounds(offset)
		if direction > 0:
			after = [p for p in positions if p > lineEnd or (p > offset and lineBounds(p)[0] != lineStart)]
			if after:
				return after[0], False
			return positions[0], True
		before = [p for p in positions if p < lineStart]
		if before:
			return before[-1], False
		return positions[-1], True
