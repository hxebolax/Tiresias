"""Gestos de entrada (teclas) y mapa de gestos personalizado del usuario."""

from __future__ import annotations

import json
import os
import threading
import time

from .. import paths, winapi
from ..baseobject import normalizeGestureId
from ..log import getLogger
from . import keys

log = getLogger("gestures")

UNBOUND = object()

_MOD_ORDER = ("tiresias", "control", "shift", "alt", "windows")
_MOD_VK = {"control": 0xA2, "shift": 0xA0, "alt": 0xA4, "windows": 0x5B}
_EXTENDED_NAMES = {
	"pageup",
	"pagedown",
	"end",
	"home",
	"leftarrow",
	"uparrow",
	"rightarrow",
	"downarrow",
	"insert",
	"delete",
	"numpadenter",
	"numpaddivide",
	"applications",
	"leftwindows",
	"rightwindows",
	"rightcontrol",
	"rightalt",
}


class InputGesture:
	"""Clase base de los gestos de entrada."""

	identifiers: list[str] = []
	displayName = ""
	isModifier = False

	def send(self) -> None:
		pass


class KeyboardGesture(InputGesture):
	def __init__(self, vk: int, scanCode: int, extended: bool, modifiers: frozenset[str], mainKeyName: str, layout: str = "desktop") -> None:
		self.vk = vk
		self.scanCode = scanCode
		self.extended = extended
		self.modifiers = modifiers
		self.mainKeyName = mainKeyName
		self.layout = layout
		self.char: str | None = None
		self.time = time.monotonic()
		mods = [m for m in _MOD_ORDER if m in modifiers]
		self.normalizedKeys = "+".join(mods + [mainKeyName])
		self.identifiers = [f"kb({layout}):{self.normalizedKeys}", f"kb:{self.normalizedKeys}"]

	@classmethod
	def fromName(cls, name: str) -> "KeyboardGesture":
		"""Crea un gesto a partir de un nombre como ``control+shift+a``."""
		gid = normalizeGestureId("kb:" + name)
		parts = gid.split(":", 1)[1].split("+")
		mods = frozenset(p for p in parts if p in _MOD_ORDER)
		main = [p for p in parts if p not in _MOD_ORDER]
		mainName = main[-1] if main else ""
		res = keys.vkFromName(mainName)
		vk, ext = res if res else (0, False)
		return cls(vk, 0, ext or mainName in _EXTENDED_NAMES, mods, mainName)

	@property
	def modifierNames(self) -> list[str]:
		return [m for m in _MOD_ORDER if m in self.modifiers]

	@property
	def displayName(self) -> str:  # type: ignore[override]
		return keys.labelForGesture("kb:" + self.normalizedKeys)

	@property
	def isCharacter(self) -> bool:
		return not (self.modifiers - {"shift"}) and self.char is not None and self.char.isprintable() and not self.char.isspace()

	@property
	def isNVDAKeyCombination(self) -> bool:
		return "tiresias" in self.modifiers

	def send(self) -> None:
		"""Envía la tecla a la aplicación (como si Tiresias no la hubiera capturado)."""
		inputs = []
		pressed: list[str] = []
		for mod in self.modifierNames:
			if mod == "tiresias":
				continue
			vk = _MOD_VK[mod]
			# Izquierda (vk) o derecha (vk + 1) ya pulsada por el usuario.
			if not (winapi.isKeyDown(vk) or winapi.isKeyDown(vk + 1)):
				inputs.append(winapi.makeKeyInput(vk, extended=(mod == "windows")))
				pressed.append(mod)
		if self.vk:
			inputs.append(winapi.makeKeyInput(self.vk, extended=self.extended, scan=self.scanCode))
			inputs.append(winapi.makeKeyInput(self.vk, up=True, extended=self.extended, scan=self.scanCode))
		for mod in reversed(pressed):
			inputs.append(winapi.makeKeyInput(_MOD_VK[mod], up=True, extended=(mod == "windows")))
		winapi.sendInputs(inputs)

	def __repr__(self) -> str:
		return f"<KeyboardGesture {self.normalizedKeys}>"


def sendKey(name: str) -> None:
	"""Envía una combinación de teclas, p. ej. ``sendKey("control+shift+m")``."""
	KeyboardGesture.fromName(name).send()


class UserGestureMap:
	"""Cambios de gestos hechos por el usuario (``data/config/gestures.json``)."""

	def __init__(self) -> None:
		self._map: dict[str, dict[str, str | None]] = {}
		self._lock = threading.Lock()

	@property
	def fileName(self) -> str:
		return os.path.join(paths.configDir(), "gestures.json")

	@staticmethod
	def classKey(cls: type) -> str:
		return f"{cls.__module__}.{cls.__qualname__}"

	def load(self) -> None:
		try:
			with open(self.fileName, encoding="utf-8") as f:
				data = json.load(f)
			if not isinstance(data, dict):
				raise ValueError("el archivo de gestos no contiene un objeto JSON")
			self._map = {
				k: {normalizeGestureId(g): s for g, s in v.items() if isinstance(g, str)}
				for k, v in data.items()
				if isinstance(v, dict)
			}
		except FileNotFoundError:
			self._map = {}
		except (OSError, ValueError, TypeError, AttributeError):
			log.exception("Archivo de gestos no válido")
			self._map = {}

	def save(self) -> None:
		os.makedirs(os.path.dirname(self.fileName), exist_ok=True)
		with open(self.fileName, "w", encoding="utf-8") as f:
			json.dump(self._map, f, ensure_ascii=False, indent="\t", sort_keys=True)

	def lookup(self, cls: type, gestureId: str):
		if not self._map:
			return None
		for klass in cls.__mro__:
			m = self._map.get(self.classKey(klass))
			if m and gestureId in m:
				val = m[gestureId]
				return UNBOUND if val is None else val
		return None

	def bind(self, classKey: str, gestureId: str, scriptName: str) -> None:
		with self._lock:
			self._map.setdefault(classKey, {})[normalizeGestureId(gestureId)] = scriptName

	def unbind(self, classKey: str, gestureId: str) -> None:
		with self._lock:
			self._map.setdefault(classKey, {})[normalizeGestureId(gestureId)] = None

	def reset(self) -> None:
		with self._lock:
			self._map = {}

	def userBindings(self) -> dict[str, dict[str, str | None]]:
		return {k: dict(v) for k, v in self._map.items()}


userMap = UserGestureMap()
