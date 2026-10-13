"""Interceptores de árbol.

Un interceptor de árbol se sitúa sobre un objeto raíz (por ejemplo, un
documento web) y procesa las teclas y eventos de todos sus descendientes.
El modo exploración es el ejemplo principal.
"""

from __future__ import annotations

from typing import Any

from .baseobject import ScriptableObject
from .extension_points import Action
from .log import getLogger

log = getLogger("treeInterceptor")

runningTable: list["TreeInterceptor"] = []

#: Se notifica al crear un interceptor: ``treeInterceptor``.
post_treeInterceptorCreated = Action()


class TreeInterceptor(ScriptableObject):
	"""Clase base."""

	def __init__(self, rootObject: Any) -> None:
		super().__init__()
		self.rootObject = rootObject
		self._passThrough = False

	@property
	def isAlive(self) -> bool:
		try:
			return self.rootObject is not None and bool(self.rootObject.processID)
		except Exception:
			return False

	@property
	def isReady(self) -> bool:
		return True

	def contains(self, obj: Any, ancestors: list | None = None) -> bool:
		if obj is None:
			return False
		if obj == self.rootObject:
			return True
		# Rev. 10.11 (A7): un objeto de otro proceso no puede estar dentro (se
		# evita recorrer sus antecesores, llamadas entre procesos, en cada evento).
		try:
			pid = getattr(obj, "processID", None)
			rootPid = getattr(self.rootObject, "processID", None)
			if isinstance(pid, int) and isinstance(rootPid, int) and pid and rootPid and pid != rootPid:
				return False
		except Exception:
			pass
		if ancestors is None:
			try:
				ancestors = list(obj.iterAncestors())
			except Exception:
				return False
		return any(a == self.rootObject for a in ancestors)

	def _get_passThrough(self) -> bool:
		return self._passThrough

	def _set_passThrough(self, state: bool) -> None:
		self._passThrough = state

	def terminate(self) -> None:
		pass

	def makeTextInfo(self, position: Any):
		raise NotImplementedError


def getTreeInterceptor(obj: Any, ancestors: list | None = None) -> TreeInterceptor | None:
	for ti in list(runningTable):
		if not ti.isAlive:
			_kill(ti)
			continue
		try:
			if ti.contains(obj, ancestors):
				return ti
		except Exception:
			log.debug("Error comprobando interceptor", exc_info=True)
	return None


def update(obj: Any, ancestors: list | None = None) -> TreeInterceptor | None:
	"""Crea el interceptor adecuado para ``obj`` si no existe."""
	ti = getTreeInterceptor(obj, ancestors)
	if ti is not None:
		return ti
	candidates = [obj] + list(reversed(ancestors or []))
	for cand in candidates:
		cls = getattr(cand, "treeInterceptorClass", None)
		if cls is None or not getattr(cand, "shouldCreateTreeInterceptor", True):
			continue
		app = getattr(cand, "appModule", None)
		try:
			ti = cls(cand)
		except Exception:
			log.exception("No se pudo crear el interceptor para %r", cand)
			return None
		if app is not None and getattr(app, "disableBrowseModeByDefault", False):
			ti.passThrough = True
			if hasattr(ti, "_disableAutoPassThrough"):
				# Rev. 10.11: el paso automático a modo exploración (al llegar el foco
				# a un enlace o un botón) queda en pausa hasta que el usuario lo pida
				# con Tiresias+Espacio, como con «activar el modo exploración al cargar».
				ti._disableAutoPassThrough = True
		runningTable.append(ti)
		post_treeInterceptorCreated.notify(treeInterceptor=ti)
		return ti
	return None


def _kill(ti: TreeInterceptor) -> None:
	try:
		runningTable.remove(ti)
	except ValueError:
		pass
	try:
		ti.terminate()
	except Exception:
		log.exception("Error terminando interceptor")


def cleanup() -> None:
	for ti in list(runningTable):
		if not ti.isAlive:
			_kill(ti)


def terminateAll() -> None:
	for ti in list(runningTable):
		_kill(ti)
