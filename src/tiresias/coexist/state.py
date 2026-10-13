"""Máquina de estados de la convivencia con otros lectores de pantalla.

Lógica pura (sin Windows ni hilos) para poder probarla con detectores
simulados:

- :class:`Debouncer` convierte las detecciones de cada sondeo en un
  conjunto **estable** de lectores: un lector cuenta como presente cuando se
  ve en dos sondeos seguidos o cuando ya está listo (su ventana existe), y
  como ausente cuando falta en dos sondeos seguidos. Así un ``nvda.exe -k``
  de un instante o el reinicio de NVDA no hacen saltar a Tiresias.
- :class:`Coexistence` decide cuándo Tiresias está activo o en espera y
  avisa a unas «acciones» (las reales están en :mod:`tiresias.coexist`).
"""

from __future__ import annotations

from typing import Iterable, Protocol

from .detect import ORDER, ReaderInfo

ACTIVE = "active"
STANDBY = "standby"

#: Motivos de activación (para el anuncio).
REASON_READER_CLOSED = "readerClosed"
REASON_FORCED = "forced"
REASON_OPTION_OFF = "optionOff"


class Debouncer:
	def __init__(self, appearPolls: int = 2, disappearPolls: int = 2) -> None:
		self.appearPolls = max(1, appearPolls)
		self.disappearPolls = max(1, disappearPolls)
		self._seen: dict[str, int] = {}
		self._missing: dict[str, int] = {}
		self.stable: dict[str, ReaderInfo] = {}

	def update(self, readers: Iterable[ReaderInfo]) -> bool:
		"""Añade un sondeo; devuelve ``True`` si cambia el conjunto estable."""
		now = {r.id: r for r in readers}
		before = set(self.stable)
		for rid, info in now.items():
			self._missing.pop(rid, None)
			self._seen[rid] = self._seen.get(rid, 0) + 1
			if rid in self.stable or info.ready or self._seen[rid] >= self.appearPolls:
				self.stable[rid] = info
		for rid in list(self._seen):
			if rid not in now:
				del self._seen[rid]
		for rid in list(self.stable):
			if rid not in now:
				self._missing[rid] = self._missing.get(rid, 0) + 1
				if self._missing[rid] >= self.disappearPolls:
					del self.stable[rid]
					del self._missing[rid]
		return set(self.stable) != before

	def reset(self, readers: Iterable[ReaderInfo] = ()) -> None:
		"""Fija el conjunto estable sin esperar (detección al arrancar)."""
		self._seen = {}
		self._missing = {}
		self.stable = {r.id: r for r in readers}
		for rid in self.stable:
			self._seen[rid] = self.appearPolls


def primaryReader(readers: Iterable[ReaderInfo]) -> ReaderInfo | None:
	"""El lector «principal» cuando hay varios (NVDA, JAWS, Narrador...)."""
	items = list(readers)
	if not items:
		return None
	return sorted(items, key=lambda r: ORDER.index(r.id) if r.id in ORDER else len(ORDER))[0]


class Actions(Protocol):
	def goStandby(self, reader: ReaderInfo, initial: bool) -> None: ...

	def goActive(self, reason: str, reader: ReaderInfo | None) -> None: ...


class Coexistence:
	"""Estado de Tiresias frente a otros lectores de pantalla."""

	def __init__(self, actions: Actions) -> None:
		self.actions = actions
		self.state = ACTIVE
		#: El usuario ha forzado la activación aunque haya otro lector.
		self.forced = False
		self.yieldEnabled = True
		self.readers: dict[str, ReaderInfo] = {}
		#: Lector ante el que se cedió (o que estaba al forzar).
		self.reader: ReaderInfo | None = None

	@property
	def isStandby(self) -> bool:
		return self.state == STANDBY

	def _primary(self) -> ReaderInfo | None:
		return primaryReader(self.readers.values())

	def start(self, readers: Iterable[ReaderInfo], yieldEnabled: bool, forced: bool = False) -> str:
		"""Estado inicial al arrancar Tiresias."""
		self.readers = {r.id: r for r in readers}
		self.yieldEnabled = bool(yieldEnabled)
		primary = self._primary()
		if primary is not None and forced:
			self.forced = True
			self.reader = primary
		if primary is not None and self.yieldEnabled and not self.forced:
			self.state = STANDBY
			self.reader = primary
			self.actions.goStandby(primary, True)
		else:
			self.state = ACTIVE
		return self.state

	def onReaders(self, readers: Iterable[ReaderInfo]) -> None:
		"""Nuevo conjunto estable de lectores en ejecución."""
		self.readers = {r.id: r for r in readers}
		primary = self._primary()
		if primary is None:
			self.forced = False
			if self.state == STANDBY:
				last = self.reader
				self.state = ACTIVE
				self.reader = None
				self.actions.goActive(REASON_READER_CLOSED, last)
			else:
				self.reader = None
			return
		if self.state == STANDBY:
			# Sigue en espera; se recuerda el lector principal actual.
			self.reader = primary
			return
		if self.yieldEnabled and not self.forced:
			self.state = STANDBY
			self.reader = primary
			self.actions.goStandby(primary, False)
		else:
			# Activo junto a otro lector (forzado u opción desactivada): el lector
			# en ejecución de ahora («Ceder el paso a...», mensajes).
			self.reader = primary

	def setYieldEnabled(self, enabled: bool) -> None:
		"""Cambia la opción «Ceder ante otros lectores» (solo actúa si cambia)."""
		if bool(enabled) == self.yieldEnabled:
			return
		self.yieldEnabled = bool(enabled)
		primary = self._primary()
		if not self.yieldEnabled and self.state == STANDBY:
			last = self.reader
			self.state = ACTIVE
			self.actions.goActive(REASON_OPTION_OFF, last)
		elif self.yieldEnabled and self.state == ACTIVE and primary is not None and not self.forced:
			self.state = STANDBY
			self.reader = primary
			self.actions.goStandby(primary, False)

	def force(self) -> bool:
		"""Activa Tiresias aunque haya otro lector. ``True`` si cambia algo."""
		primary = self._primary()
		if self.state == STANDBY:
			self.forced = True
			self.state = ACTIVE
			last = self.reader or primary
			self.reader = last
			self.actions.goActive(REASON_FORCED, last)
			return True
		if primary is not None and not self.forced:
			self.forced = True
			self.reader = primary
			return True
		return False

	def yieldNow(self) -> bool:
		"""Deja de forzar y cede ante el lector activo. ``True`` si pasa a espera."""
		primary = self._primary()
		self.forced = False
		if self.state == ACTIVE and primary is not None:
			self.state = STANDBY
			self.reader = primary
			self.actions.goStandby(primary, False)
			return True
		return False
