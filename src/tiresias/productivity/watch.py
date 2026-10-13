"""Vigilancia de objetos y regiones de pantalla (hilo del núcleo). Petición de NVDA #498.

El usuario marca el objeto navegador como vigilado y Tiresias anuncia sus
cambios aunque el foco esté en otra parte: el progreso de una descarga, un
contador, el último mensaje de un chat, una barra de estado...

Dos clases de vigilancia:

- ``object``: lee por UI Automation el nombre, el valor, el texto o los
  nombres de los hijos del objeto.
- ``region``: reconoce con OCR el rectángulo de pantalla que ocupa el objeto
  (para juegos y programas sin accesibilidad). El OCR se hace en un hilo
  propio y solo se anuncia el texto nuevo.

Cada vigilancia recuerda la aplicación en la que se creó. Opcionalmente solo
se anuncia mientras esa aplicación está en primer plano.
"""

from __future__ import annotations

import difflib
import threading
import time
from dataclasses import dataclass, field

from .. import queue_handler
from ..i18n import _
from ..log import getLogger

log = getLogger("productivity")

KIND_OBJECT = "object"
KIND_REGION = "region"

#: Máximo de caracteres de un objeto vigilado que se comparan.
MAX_TEXT = 4000
#: Hijos que se leen como mucho de un contenedor sin texto propio.
MAX_CHILDREN = 40


def changedText(old: str, new: str) -> str:
	"""Qué hay que anunciar cuando el texto pasa de ``old`` a ``new``.

	- Si se ha añadido texto al final (un chat, un registro), solo lo nuevo.
	- Si hay varias líneas, las líneas nuevas o cambiadas.
	- Si no, el texto nuevo completo.
	"""
	new = new or ""
	old = old or ""
	if new == old:
		return ""
	if not new.strip():
		return ""
	if old and new.startswith(old):
		return new[len(old) :].strip()
	oldLines = [ln.strip() for ln in old.splitlines() if ln.strip()]
	newLines = [ln.strip() for ln in new.splitlines() if ln.strip()]
	if len(newLines) > 1 or len(oldLines) > 1:
		added: list[str] = []
		matcher = difflib.SequenceMatcher(a=oldLines, b=newLines, autojunk=False)
		for tag, _i1, _i2, j1, j2 in matcher.get_opcodes():
			if tag in ("replace", "insert"):
				added.extend(newLines[j1:j2])
		if added:
			return "\n".join(added)
		return ""
	return new.strip()


@dataclass
class Watch:
	slot: int
	kind: str
	appName: str
	label: str
	obj: object = None
	rect: tuple | None = None
	lastText: str = ""
	created: float = field(default_factory=time.time)
	lastChange: float = 0.0
	missed: int = 0
	#: OCR en curso (solo regiones).
	busy: bool = False
	#: Ya se ha leído una vez: el texto que había al empezar a vigilar no se anuncia.
	primed: bool = False

	def describe(self) -> str:
		kind = _("región") if self.kind == KIND_REGION else _("objeto")
		return _("Vigilancia {n}: {kind} {label} en {app}").format(n=self.slot, kind=kind, label=self.label or _("sin nombre"), app=self.appName or _("aplicación desconocida"))


def objectText(obj) -> str:
	"""Texto vigilable de un objeto UIA."""
	parts: list[str] = []
	try:
		name = obj.name or ""
	except Exception:
		name = ""
	try:
		value = obj.value or ""
	except Exception:
		value = ""
	if name:
		parts.append(name)
	if value and value != name:
		parts.append(value)
	try:
		if getattr(obj, "TextInfo", None) is not None:
			from .. import textinfo

			text = obj.makeTextInfo(textinfo.POSITION_ALL).text or ""
			if text and text not in parts:
				parts.append(text[-MAX_TEXT:])
	except Exception:
		pass
	if not parts or (len(parts) == 1 and not value):
		# Contenedor (lista de mensajes, panel): nombres de sus hijos.
		try:
			children = obj.children[-MAX_CHILDREN:]
		except Exception:
			children = []
		names = []
		for c in children:
			try:
				n = c.name or c.value or ""
			except Exception:
				n = ""
			if n:
				names.append(n)
		if names:
			parts.append("\n".join(names))
	return "\n".join(parts)[-MAX_TEXT:]


def isAlive(obj) -> bool:
	"""``False`` si el objeto ya no existe.

	- UIA: se lee una propiedad del elemento (falla si ya no existe).
	- MSAA, IAccessible2, Java Access Bridge...: la ventana del objeto tiene que
	  seguir existiendo y, con IAccessible, ``accRole`` tiene que responder.
	"""
	if obj is None:
		return False
	el = getattr(obj, "element", None)
	if el is not None:
		try:
			from ..a11y import uia_client as uc

			el.GetCurrentPropertyValue(uc.P_PROCESSID)
			return True
		except Exception:
			return False
	try:
		hwnd = int(getattr(obj, "windowHandle", 0) or 0)
	except Exception:
		hwnd = 0
	if hwnd:
		from .. import winapi

		if not winapi.user32.IsWindow(hwnd):
			return False
	iacc = getattr(obj, "IAccessibleObject", None)
	if iacc is not None:
		try:
			iacc.accRole(getattr(obj, "IAccessibleChildID", 0) or 0)
		except Exception:
			return False
		return True
	# Sin elemento UIA, sin IAccessible y con la ventana viva (o sin ventana):
	# no hay forma de saberlo, se sigue vigilando.
	return True


class WatchManager:
	"""Lista de vigilancias y sondeo periódico."""

	def __init__(self) -> None:
		self.watches: list[Watch] = []
		self._timer: int | None = None
		self._running = False

	# --------------------------------------------------- configuración
	@staticmethod
	def _conf():
		from ..config import conf

		return conf["watch"]

	def maxWatches(self) -> int:
		try:
			return max(1, min(10, int(self._conf()["maxWatches"])))
		except Exception:
			return 5

	# --------------------------------------------------- lista
	def findByObject(self, obj) -> Watch | None:
		for w in self.watches:
			if w.kind == KIND_OBJECT and w.obj is not None:
				try:
					if w.obj == obj:
						return w
				except Exception:
					continue
		return None

	def _freeSlot(self) -> int | None:
		used = {w.slot for w in self.watches}
		for n in range(1, self.maxWatches() + 1):
			if n not in used:
				return n
		return None

	def add(self, kind: str, obj, appName: str, label: str, rect=None, initialText: str = "") -> Watch | None:
		slot = self._freeSlot()
		if slot is None:
			return None
		w = Watch(slot, kind, appName, label, obj, rect, initialText)
		# Un objeto se lee al crear la vigilancia (``initialText``); una zona se lee
		# con OCR en el primer sondeo, y eso no se anuncia.
		w.primed = kind == KIND_OBJECT
		self.watches.append(w)
		self.watches.sort(key=lambda x: x.slot)
		self.start()
		return w

	def remove(self, watch: Watch) -> None:
		if watch in self.watches:
			self.watches.remove(watch)
		if not self.watches:
			self.stop()

	def clear(self) -> None:
		self.watches.clear()
		self.stop()

	def get(self, slot: int) -> Watch | None:
		for w in self.watches:
			if w.slot == slot:
				return w
		return None

	# --------------------------------------------------- sondeo
	def start(self) -> None:
		if self._running:
			return
		self._running = True
		self._schedule()

	def stop(self) -> None:
		self._running = False
		if self._timer is not None:
			queue_handler.cancelCallLater(self._timer)
			self._timer = None

	def _schedule(self) -> None:
		try:
			interval = max(250, int(self._conf()["intervalMs"]))
		except Exception:
			interval = 1000
		self._timer = queue_handler.callLater(interval, self._poll)

	def _poll(self) -> None:
		self._timer = None
		if not self._running:
			return
		try:
			for w in list(self.watches):
				if w.kind == KIND_OBJECT:
					self._pollObject(w)
				else:
					self._pollRegion(w)
		except Exception:
			log.exception("Error vigilando objetos")
		if self._running and self.watches:
			self._schedule()
		else:
			self._running = False

	def _pollObject(self, w: Watch) -> None:
		if not isAlive(w.obj):
			w.missed += 1
			if w.missed >= 3:
				self.remove(w)
				self._announce(w, _("Vigilancia {n}: el objeto ya no existe y se ha quitado").format(n=w.slot), force=True)
			return
		w.missed = 0
		text = objectText(w.obj)
		self._compare(w, text)

	def _pollRegion(self, w: Watch) -> None:
		if w.busy or not w.rect:
			return
		w.busy = True
		rect = w.rect

		def worker() -> None:
			text = ""
			try:
				from .. import imaging, ocr

				img = imaging.captureRect(rect, 0)
				lines = ocr.recognizeImage(img)
				text = "\n".join(line.text for line in lines)
			except Exception:
				log.debug("Error en el OCR de la vigilancia", exc_info=True)
				text = None  # type: ignore[assignment]
			queue_handler.queueFunction(self._regionDone, w, text)

		threading.Thread(target=worker, name="Vigilancia-OCR", daemon=True).start()

	def _regionDone(self, w: Watch, text: str | None) -> None:
		w.busy = False
		if text is None or w not in self.watches:
			return
		self._compare(w, text)

	def _compare(self, w: Watch, text: str) -> None:
		if not w.primed:
			# Primera lectura (OCR de una zona): se guarda lo que ya había sin anunciarlo.
			w.primed = True
			w.lastText = text
			return
		if text == w.lastText:
			return
		c = self._conf()
		message = changedText(w.lastText, text) if c["onlyNewText"] else text.strip()
		w.lastText = text
		if not message:
			return
		w.lastChange = time.time()
		self._announce(w, message)

	def _isForegroundApp(self, w: Watch) -> bool:
		from .. import api
		from .text_context import appNameOf

		fg = api.getForegroundObject()
		return fg is not None and appNameOf(fg) == w.appName

	def _announce(self, w: Watch, message: str, force: bool = False) -> None:
		from .. import speech
		from ..audio import tones

		c = self._conf()
		if not force and c["onlyWhenAppInForeground"] and not self._isForegroundApp(w):
			return
		if c["playSound"]:
			tones.playSound("watchChange")
		prefix = ""
		if c["announceSlot"]:
			prefix = _("Vigilancia {n}:").format(n=w.slot) + " "
		speech.speakMessage(prefix + message)
		if c["showInBraille"]:
			try:
				from .. import braille

				braille.handler.message(prefix + message)
			except Exception:
				pass
