"""Objetos con propiedades automáticas y órdenes (scripts).

:class:`AutoPropertyObject` convierte métodos ``_get_x`` / ``_set_x`` en la
propiedad ``x``. Si la clase tiene ``cachePropertiesByDefault = True`` (o el
atributo ``_cache_x = True``), el valor se guarda hasta el siguiente ciclo
del núcleo, lo que evita repetir llamadas costosas de accesibilidad.

:class:`ScriptableObject` añade la asociación de gestos (teclas) a órdenes.
"""

from __future__ import annotations

import threading
from typing import Callable

_cacheGeneration = 0
_genLock = threading.Lock()


def invalidateCaches() -> None:
	"""Invalida las propiedades cacheadas (lo llama el núcleo en cada ciclo)."""
	global _cacheGeneration
	with _genLock:
		_cacheGeneration += 1


class _AutoProperty(property):
	__slots__ = ("cache", "propName")


class AutoPropertyType(type):
	def __init__(cls, name, bases, dct):
		super().__init__(name, bases, dct)
		cacheByDefault = dct.get("cachePropertiesByDefault")
		if cacheByDefault is None:
			for b in cls.__mro__[1:]:
				if "cachePropertiesByDefault" in b.__dict__:
					cacheByDefault = b.__dict__["cachePropertiesByDefault"]
					break
		props: set[str] = set()
		for key in dct:
			if key.startswith(("_get_", "_set_")) and callable(dct[key]):
				props.add(key[5:])
		for prop in props:
			getter = None
			setter = None
			for klass in cls.__mro__:
				if getter is None and "_get_" + prop in klass.__dict__:
					getter = klass.__dict__["_get_" + prop]
				if setter is None and "_set_" + prop in klass.__dict__:
					setter = klass.__dict__["_set_" + prop]
			cache = dct.get("_cache_" + prop)
			if cache is None:
				for klass in cls.__mro__[1:]:
					if "_cache_" + prop in klass.__dict__:
						cache = klass.__dict__["_cache_" + prop]
						break
			if cache is None:
				cache = bool(cacheByDefault)
			setattr(cls, prop, _makeProperty(prop, getter, setter, cache))


def _makeProperty(name: str, getter: Callable | None, setter: Callable | None, cache: bool) -> property:
	if getter is not None and cache:

		def fget(self):
			ov = self.__dict__.get("_propOverrides")
			if ov and name in ov:
				return ov[name]
			gen = _cacheGeneration
			c = self.__dict__.get("_propCache")
			if c is None or c[0] != gen:
				c = (gen, {})
				self.__dict__["_propCache"] = c
			store = c[1]
			try:
				return store[name]
			except KeyError:
				val = getter(self)
				store[name] = val
				return val

	elif getter is not None:

		def fget(self):
			ov = self.__dict__.get("_propOverrides")
			if ov and name in ov:
				return ov[name]
			return getter(self)

	else:
		fget = None  # type: ignore[assignment]

	if setter is not None:

		def fset(self, value):
			c = self.__dict__.get("_propCache")
			if c is not None:
				c[1].pop(name, None)
			setter(self, value)

	elif getter is not None:

		def fset(self, value):
			# Propiedad de solo lectura: las clases que lo permiten guardan un
			# valor fijo (p. ej. ``obj.name = "..."`` en ``event_NVDAObject_init``).
			if not getattr(self, "allowPropertyOverrides", False):
				raise AttributeError(f"La propiedad {name} es de solo lectura")
			self.__dict__.setdefault("_propOverrides", {})[name] = value

	else:
		fset = None  # type: ignore[assignment]
	return property(fget, fset, doc=getattr(getter, "__doc__", None))


class AutoPropertyObject(metaclass=AutoPropertyType):
	cachePropertiesByDefault = False
	#: Permite asignar valores fijos a propiedades sin método ``_set_``.
	allowPropertyOverrides = False

	def invalidateCache(self) -> None:
		self.__dict__.pop("_propCache", None)


# --------------------------------------------------------------- órdenes
def script(
	description: str = "",
	category: str | None = None,
	gesture: str | None = None,
	gestures: list[str] | tuple[str, ...] | None = None,
	canPropagate: bool = False,
	bypassInputHelp: bool = False,
	speakOnDemand: bool = False,
	allowInSleepMode: bool = False,
	resumeSayAll: bool = False,
) -> Callable:
	"""Decorador para definir una orden asociada a gestos.

	``canPropagate``: la orden también se aplica cuando el foco está dentro
	de un descendiente del objeto que la define.
	"""

	def wrap(func: Callable) -> Callable:
		if not func.__name__.startswith("script_"):
			raise ValueError("Las órdenes deben llamarse script_xxx")
		func.__doc__ = description or func.__doc__
		func.category = category  # type: ignore[attr-defined]
		gs = list(gestures or ())
		if gesture:
			gs.append(gesture)
		func.gestures = gs  # type: ignore[attr-defined]
		func.canPropagate = canPropagate  # type: ignore[attr-defined]
		func.bypassInputHelp = bypassInputHelp  # type: ignore[attr-defined]
		func.speakOnDemand = speakOnDemand  # type: ignore[attr-defined]
		func.allowInSleepMode = allowInSleepMode  # type: ignore[attr-defined]
		func.resumeSayAll = resumeSayAll  # type: ignore[attr-defined]
		return func

	return wrap


class GestureDict(dict):
	"""Diccionario {gesto: orden} que normaliza siempre los identificadores.

	Al pulsar una tecla, el gesto se genera normalizado (``kb:shift+alt+1``) y
	se busca tal cual. Si un módulo añadiera ``kb:alt+shift+1`` directamente a
	``_classGestures`` no se encontraría nunca; con este diccionario el orden
	en que se escriban los modificadores da igual.
	"""

	def __init__(self, *args, **kwargs) -> None:
		super().__init__()
		self.update(*args, **kwargs)

	def __setitem__(self, key: str, value) -> None:
		super().__setitem__(normalizeGestureId(key), value)

	def __getitem__(self, key: str):
		try:
			return super().__getitem__(key)
		except KeyError:
			return super().__getitem__(normalizeGestureId(key))

	def __contains__(self, key: object) -> bool:
		if super().__contains__(key):
			return True
		return isinstance(key, str) and super().__contains__(normalizeGestureId(key))

	def __delitem__(self, key: str) -> None:
		super().__delitem__(key if super().__contains__(key) else normalizeGestureId(key))

	def get(self, key, default=None):
		return self[key] if key in self else default

	def pop(self, key, *default):
		if isinstance(key, str) and not super().__contains__(key):
			key = normalizeGestureId(key)
		return super().pop(key, *default)

	def setdefault(self, key: str, default=None):
		return super().setdefault(normalizeGestureId(key), default)

	def update(self, *args, **kwargs) -> None:
		for k, v in dict(*args, **kwargs).items():
			self[k] = v


class ScriptableType(AutoPropertyType):
	def __init__(cls, name, bases, dct):
		super().__init__(name, bases, dct)
		gestures = GestureDict(dict(dct.get(f"_{name.lstrip('_')}__gestures", {})))
		for key, value in dct.items():
			if key.startswith("script_") and callable(value):
				for g in getattr(value, "gestures", ()) or ():
					gestures[g] = key[7:]
		cls._classGestures = gestures  # type: ignore[attr-defined]


class ScriptableObject(AutoPropertyObject, metaclass=ScriptableType):
	"""Objeto que puede tener órdenes asociadas a gestos de entrada.

	Además del decorador :func:`script`, se puede definir un diccionario de
	clase ``__gestures = {"kb:control+a": "nombreDeOrden"}``.
	"""

	#: Categoría por defecto para las órdenes de esta clase.
	scriptCategory: str | None = None

	def __init__(self) -> None:
		self._instanceGestures: dict[str, str | None] = GestureDict()

	def bindGesture(self, gestureId: str, scriptName: str) -> None:
		if "_instanceGestures" not in self.__dict__:
			self._instanceGestures = GestureDict()
		self._instanceGestures[normalizeGestureId(gestureId)] = scriptName

	def removeGestureBinding(self, gestureId: str) -> None:
		if "_instanceGestures" not in self.__dict__:
			self._instanceGestures = GestureDict()
		self._instanceGestures[normalizeGestureId(gestureId)] = None

	def bindGestures(self, mapping: dict[str, str]) -> None:
		for g, s in mapping.items():
			self.bindGesture(g, s)

	def clearGestureBindings(self) -> None:
		self._instanceGestures = GestureDict()

	def _scriptNameForGesture(self, gestureId: str) -> str | None:
		inst = self.__dict__.get("_instanceGestures") or {}
		if gestureId in inst:
			return inst[gestureId]
		for klass in type(self).__mro__:
			cg = klass.__dict__.get("_classGestures")
			if cg and gestureId in cg:
				return cg[gestureId]
		return None

	def getScript(self, gesture) -> Callable | None:
		"""Busca la orden asociada a un gesto (objeto con ``identifiers``)."""
		from .input import gestures as gestureMap

		ids = list(gesture.identifiers)
		# Prioridad: lo que asigna el usuario, luego los gestos de instancia (mapas
		# alternativos, complementos) y por último los de la clase, cada nivel con
		# todos los identificadores del gesto. Si no, una asignación general
		# («kb:...») nunca vencería a una de la distribución de la clase
		# («kb(desktop):...»), que se mira antes.
		for gid in ids:
			name = gestureMap.userMap.lookup(type(self), gid)
			if name is gestureMap.UNBOUND:
				return None
			if name:
				func = getattr(self, "script_" + name, None)
				if func:
					return func
		inst = self.__dict__.get("_instanceGestures") or {}
		for gid in ids:
			if gid in inst:
				name = inst[gid]
				if not name:
					# Gesto quitado en esta instancia (removeGestureBinding).
					return None
				func = getattr(self, "script_" + name, None)
				if func:
					return func
		for gid in ids:
			for klass in type(self).__mro__:
				cg = klass.__dict__.get("_classGestures")
				if cg and gid in cg:
					func = getattr(self, "script_" + cg[gid], None)
					if func:
						return func
					break
		return None

	@classmethod
	def iterClassGestures(cls):
		"""Pares (gesto, nombre de orden) definidos en la clase y sus bases."""
		seen = set()
		for klass in cls.__mro__:
			for g, s in (klass.__dict__.get("_classGestures") or {}).items():
				if g not in seen:
					seen.add(g)
					yield g, s


# --------------------------------------------------------------- gestos
_MODIFIER_ORDER = ("tiresias", "control", "shift", "alt", "windows")
_ALIASES = {
	"ctrl": "control",
	"nvda": "tiresias",
	"tir": "tiresias",
	"win": "windows",
	"leftwindows": "windows",
	"rightwindows": "windows",
	"leftcontrol": "control",
	"rightcontrol": "control",
	"leftshift": "shift",
	"rightshift": "shift",
	"leftalt": "alt",
	"rightalt": "alt",
	"altgr": "alt+control",
}


def normalizeGestureId(gid: str) -> str:
	"""Normaliza ``"kb:NVDA+Shift+a"`` a ``"kb:tiresias+shift+a"``.

	Los identificadores con prefijo de distribución (``kb(laptop):``) se
	conservan. Los que no empiezan por ``kb`` se devuelven en minúsculas.
	"""
	gid = gid.strip()
	if ":" not in gid:
		return gid.lower()
	prefix, keys = gid.split(":", 1)
	prefix = prefix.lower()
	if not prefix.startswith("kb"):
		# Gestos de líneas braille y otros dispositivos: el orden de las teclas
		# de un acorde no importa.
		return f"{prefix}:" + "+".join(sorted(p for p in keys.lower().split("+") if p))
	parts = [p for p in keys.replace(" ", "").split("+") if p]
	mods: set[str] = set()
	main: list[str] = []
	for p in parts:
		low = p.lower()
		low = _ALIASES.get(low, low)
		for sub in low.split("+"):
			if sub in _MODIFIER_ORDER:
				mods.add(sub)
			else:
				main.append(sub)
	ordered = [m for m in _MODIFIER_ORDER if m in mods]
	return f"{prefix}:" + "+".join(ordered + main)
