"""Historial de notificaciones y reglas por aplicación.

Se guardan todas las notificaciones de UI Automation, los avisos emergentes
de Windows (toasts) y los cambios de las regiones vivas, para revisarlas
después en un diálogo con búsqueda.

Las reglas deciden qué se hace con cada aviso según la aplicación y una
expresión regular sobre su texto: anunciarlo normalmente, silenciarlo (solo
queda en el historial), mostrarlo solo en braille, cortar la voz antes de
decirlo (prioridad alta) y reproducir un sonido. La primera regla activa
que coincide es la que se aplica. Se guardan en
``data/config/reglas_notificaciones.json``.
"""

from __future__ import annotations

import collections
import json
import os
import re
import threading
import time
from dataclasses import asdict, dataclass, field

from ..i18n import _
from ..log import getLogger

log = getLogger("productivity")

SOURCE_NOTIFICATION = "notification"
SOURCE_TOAST = "toast"
SOURCE_LIVEREGION = "liveRegion"

SOURCE_LABELS = {
	SOURCE_NOTIFICATION: _("notificación"),
	SOURCE_TOAST: _("aviso de Windows"),
	SOURCE_LIVEREGION: _("región viva"),
}

ACTION_SPEAK = "speak"
ACTION_SILENCE = "silence"
ACTION_BRAILLE = "brailleOnly"

ACTION_LABELS = {
	ACTION_SPEAK: _("Anunciar"),
	ACTION_SILENCE: _("Silenciar (solo historial)"),
	ACTION_BRAILLE: _("Solo braille"),
}

PRIORITY_NORMAL = "normal"
PRIORITY_HIGH = "high"

PRIORITY_LABELS = {
	PRIORITY_NORMAL: _("Normal (se encola)"),
	PRIORITY_HIGH: _("Alta (corta la voz)"),
}

#: Avisos idénticos de la misma aplicación en este intervalo se guardan una vez.
DUPLICATE_SECONDS = 1.5


@dataclass
class Entry:
	time: float
	app: str
	source: str
	text: str
	#: Qué se hizo: acción de la regla aplicada (``speak`` si ninguna).
	action: str = ACTION_SPEAK
	rule: str = ""

	@property
	def sourceLabel(self) -> str:
		return SOURCE_LABELS.get(self.source, self.source)


@dataclass
class Rule:
	name: str = ""
	enabled: bool = True
	#: Procesos separados por comas (sin «.exe» o con él). Vacío: todas las aplicaciones.
	apps: str = ""
	#: Expresión regular sobre el texto. Vacía: cualquier texto.
	pattern: str = ""
	#: Distinguir mayúsculas en la expresión.
	caseSensitive: bool = False
	#: Fuentes a las que se aplica (vacía: todas).
	sources: list[str] = field(default_factory=list)
	action: str = ACTION_SPEAK
	priority: str = PRIORITY_NORMAL
	#: Sonido con nombre (``tones.availableSounds()``) o vacío.
	sound: str = ""

	def appList(self) -> list[str]:
		out = []
		for a in self.apps.split(","):
			a = a.strip().lower()
			if a.endswith(".exe"):
				a = a[:-4]
			if a:
				out.append(a)
		return out

	def compiled(self) -> re.Pattern | None:
		if not self.pattern:
			return None
		return re.compile(self.pattern, 0 if self.caseSensitive else re.IGNORECASE)

	def isValid(self) -> bool:
		try:
			self.compiled()
			return True
		except re.error:
			return False

	def matches(self, app: str, text: str, source: str = "") -> bool:
		if not self.enabled:
			return False
		apps = self.appList()
		appName = (app or "").lower()
		if appName.endswith(".exe"):
			appName = appName[:-4]
		if apps and appName not in apps:
			return False
		if self.sources and source and source not in self.sources:
			return False
		try:
			rx = self.compiled()
		except re.error:
			return False
		return rx is None or rx.search(text or "") is not None

	def describe(self) -> str:
		parts = [self.name or _("Regla sin nombre")]
		parts.append(_("aplicaciones: {apps}").format(apps=self.apps or _("todas")))
		if self.pattern:
			parts.append(_("texto: {pattern}").format(pattern=self.pattern))
		parts.append(ACTION_LABELS.get(self.action, self.action))
		if self.priority == PRIORITY_HIGH:
			parts.append(_("prioridad alta"))
		if self.sound:
			parts.append(_("sonido {name}").format(name=self.sound))
		if not self.enabled:
			parts.append(_("desactivada"))
		return ", ".join(parts)

	@classmethod
	def fromDict(cls, data: dict) -> "Rule":
		known = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
		rule = cls(**known)
		if rule.action not in ACTION_LABELS:
			rule.action = ACTION_SPEAK
		if rule.priority not in PRIORITY_LABELS:
			rule.priority = PRIORITY_NORMAL
		rule.sources = [s for s in (rule.sources or []) if s in SOURCE_LABELS]
		return rule


def findRule(rules: list[Rule], app: str, text: str, source: str = "") -> Rule | None:
	for r in rules:
		if r.matches(app, text, source):
			return r
	return None


# ------------------------------------------------------------------ almacén
class NotificationStore:
	"""Historial en memoria (hilo seguro) y reglas en disco."""

	def __init__(self, rulesFile: str | None = None, maxEntries: int = 500) -> None:
		self._lock = threading.Lock()
		self._entries: collections.deque[Entry] = collections.deque(maxlen=maxEntries)
		self.rulesFile = rulesFile
		self.rules: list[Rule] = []

	# --- historial
	def setMaxEntries(self, n: int) -> None:
		n = max(10, int(n))
		with self._lock:
			if self._entries.maxlen != n:
				self._entries = collections.deque(list(self._entries)[-n:], maxlen=n)

	def add(self, entry: Entry) -> bool:
		"""Añade un aviso; ``False`` si es un duplicado inmediato."""
		with self._lock:
			if self._entries:
				last = self._entries[-1]
				if last.text == entry.text and last.app == entry.app and entry.time - last.time < DUPLICATE_SECONDS:
					return False
			self._entries.append(entry)
			return True

	def entries(self) -> list[Entry]:
		with self._lock:
			return list(self._entries)

	def last(self) -> Entry | None:
		with self._lock:
			return self._entries[-1] if self._entries else None

	def clear(self) -> None:
		with self._lock:
			self._entries.clear()

	def remove(self, entry: Entry) -> None:
		with self._lock:
			try:
				self._entries.remove(entry)
			except ValueError:
				pass

	@staticmethod
	def search(entries: list[Entry], query: str, app: str = "") -> list[Entry]:
		"""Entradas que contienen todas las palabras de ``query`` (y de esa app)."""
		words = [w for w in query.lower().split() if w]
		out = []
		for e in entries:
			if app and e.app != app:
				continue
			hay = f"{e.text} {e.app} {e.sourceLabel}".lower()
			if all(w in hay for w in words):
				out.append(e)
		return out

	# --- reglas
	def loadRules(self) -> None:
		self.rules = []
		if not self.rulesFile or not os.path.isfile(self.rulesFile):
			return
		try:
			with open(self.rulesFile, encoding="utf-8") as f:
				data = json.load(f)
			self.rules = [Rule.fromDict(d) for d in data.get("rules", []) if isinstance(d, dict)]
		except (OSError, ValueError, TypeError):
			log.exception("No se pudieron leer las reglas de notificaciones")

	def saveRules(self) -> None:
		if not self.rulesFile:
			return
		os.makedirs(os.path.dirname(self.rulesFile), exist_ok=True)
		tmp = self.rulesFile + ".tmp"
		with open(tmp, "w", encoding="utf-8") as f:
			json.dump({"version": 1, "rules": [asdict(r) for r in self.rules]}, f, ensure_ascii=False, indent=1)
		os.replace(tmp, self.rulesFile)

	def findRule(self, app: str, text: str, source: str = "") -> Rule | None:
		return findRule(self.rules, app, text, source)


def now() -> float:
	return time.time()
