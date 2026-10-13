"""Puntos de extensión.

Permiten que módulos y complementos reaccionen a sucesos del núcleo sin
acoplarse entre sí.

- :class:`Action`: notifica a todos los manejadores registrados.
- :class:`Filter`: encadena manejadores que transforman un valor.
- :class:`Decider`: pregunta a los manejadores; si alguno devuelve ``False``
  la decisión es negativa.
"""

from __future__ import annotations

import inspect
import threading
import types
import weakref
from typing import Any, Callable, Iterable

from .log import log


def _acceptedParams(handler: Callable) -> frozenset[str] | None:
	"""Nombres de los argumentos que acepta ``handler`` (``None``: todos)."""
	try:
		sig = inspect.signature(handler)
	except (TypeError, ValueError):
		return None
	params = sig.parameters
	if any(p.kind == p.VAR_KEYWORD for p in params.values()):
		return None
	return frozenset(params)


def _callWith(handler: Callable, accepted: frozenset[str] | None, kwargs: dict) -> Any:
	if accepted is None:
		return handler(**kwargs)
	return handler(**{k: v for k, v in kwargs.items() if k in accepted})


def _call(handler: Callable, **kwargs: Any) -> Any:
	"""Llama a ``handler`` pasando solo los argumentos que acepta."""
	return _callWith(handler, _acceptedParams(handler), kwargs)


class _Entry:
	"""Un manejador registrado y su firma (calculada una sola vez al registrarlo).

	Los métodos ligados se guardan con referencia débil (como en NVDA): si su
	objeto desaparece (un complemento global terminado y recargado), el
	manejador se da de baja solo en lugar de seguir recibiendo avisos. Las
	funciones y lambdas se guardan con referencia normal (muchas se registran
	sin guardarlas en otro sitio).
	"""

	__slots__ = ("_strong", "_weak", "accepted")

	def __init__(self, handler: Callable) -> None:
		self.accepted = _acceptedParams(handler)
		if isinstance(handler, types.MethodType):
			self._strong = None
			self._weak = weakref.WeakMethod(handler)
		else:
			self._strong = handler
			self._weak = None

	def get(self) -> Callable | None:
		if self._weak is not None:
			return self._weak()
		return self._strong


#: Todos los puntos de extensión creados (para :func:`unregisterOwnedBy`).
_registries: "weakref.WeakSet[_HandlerRegistry]" = weakref.WeakSet()
_registriesLock = threading.Lock()


class _HandlerRegistry:
	def __init__(self) -> None:
		# Lista de _Entry (el nombre se conserva: algunas pruebas la sustituyen).
		self._handlers: list[_Entry] = []
		self._lock = threading.Lock()
		with _registriesLock:
			_registries.add(self)

	def _find(self, handler: Callable) -> int:
		for i, entry in enumerate(self._handlers):
			h = entry.get()
			if h is not None and h == handler:
				return i
		return -1

	def register(self, handler: Callable) -> None:
		with self._lock:
			self._handlers = [e for e in self._handlers if e.get() is not None]
			if self._find(handler) < 0:
				self._handlers.append(_Entry(handler))

	def unregister(self, handler: Callable) -> bool:
		with self._lock:
			i = self._find(handler)
			if i < 0:
				return False
			del self._handlers[i]
			return True

	def _live(self) -> list[tuple[Callable, frozenset[str] | None]]:
		with self._lock:
			out = []
			dead = False
			for e in self._handlers:
				h = e.get()
				if h is None:
					dead = True
				else:
					out.append((h, e.accepted))
			if dead:
				self._handlers = [e for e in self._handlers if e.get() is not None]
			return out

	def handlers(self) -> list[Callable]:
		return [h for h, _acc in self._live()]

	def unregisterOwnedBy(self, owners: Iterable[Any]) -> int:
		"""Da de baja los métodos ligados a alguno de ``owners`` (por identidad)."""
		ids = {id(o) for o in owners}
		if not ids:
			return 0
		with self._lock:
			before = len(self._handlers)
			keep = []
			for e in self._handlers:
				h = e.get()
				if h is None or id(getattr(h, "__self__", None)) in ids:
					continue
				keep.append(e)
			self._handlers = keep
			return before - len(keep)

	def __len__(self) -> int:
		return len(self._handlers)


def unregisterOwnedBy(owners: Iterable[Any]) -> int:
	"""Quita de TODOS los puntos de extensión los métodos de ``owners``.

	Lo usa la recarga de complementos: un complemento global o módulo de
	aplicación terminado que no anuló sus registros seguiría reaccionando
	(duplicado junto a su sustituto). Devuelve cuántos se han quitado.
	"""
	owners = list(owners)
	with _registriesLock:
		registries = list(_registries)
	return sum(r.unregisterOwnedBy(owners) for r in registries)


class Action(_HandlerRegistry):
	def notify(self, **kwargs: Any) -> None:
		for h, accepted in self._live():
			try:
				_callWith(h, accepted, kwargs)
			except Exception:
				log.exception("Error en manejador de acción %r", h)


class Filter(_HandlerRegistry):
	def apply(self, value: Any, **kwargs: Any) -> Any:
		for h, accepted in self._live():
			try:
				value = _callWith(h, accepted, dict(kwargs, value=value))
			except Exception:
				log.exception("Error en manejador de filtro %r", h)
		return value


class Decider(_HandlerRegistry):
	def decide(self, **kwargs: Any) -> bool:
		for h, accepted in self._live():
			try:
				if _callWith(h, accepted, kwargs) is False:
					return False
			except Exception:
				log.exception("Error en manejador de decisión %r", h)
		return True
