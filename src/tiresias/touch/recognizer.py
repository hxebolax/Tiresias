"""Reconocimiento de gestos táctiles.

Módulo puro: no depende de Windows ni del resto de Tiresias, así que se puede
probar alimentándolo con secuencias sintéticas de puntos. Recibe los contactos
de cada dedo (``down``, ``move``, ``up``) con su instante en segundos y
devuelve los gestos reconocidos como :class:`TouchEvent`.

Conceptos:

- Un **grupo** es el conjunto de dedos que tocan la pantalla casi a la vez
  (dentro de ``holdTime`` desde el primero). El grupo termina cuando se
  levantan todos sus dedos.
- Si todos los dedos del grupo se levantan pronto y sin moverse, es un
  **toque**; si se mueven rápido en la misma dirección, un **deslizamiento**
  (flick); si dos dedos se acercan o se separan, un **pellizco**.
- Un deslizamiento que cambia bruscamente de dirección sin levantar el dedo
  es una **secuencia de dos deslizamientos** (``flickRightThenLeft``,
  ``flickUpThenRight``...): las cuatro contrarias y las ocho en L. Si
  ``sequenceFilter`` lo permite, también cuentan dos deslizamientos hechos
  levantando el dedo entre ellos (el primero espera ``sequenceTimeout``).
- Si un dedo solo sigue apoyado al cumplirse ``holdTime`` (y no se está
  deslizando rápido), empieza la **exploración** (``hoverDown``, ``hover``
  al moverse y ``hoverUp`` al levantarlo). Con varios dedos quietos es un
  gesto de **mantener**.
- Los toques seguidos con los mismos dedos se agrupan: doble y triple toque.
  Un toque seguido de otro contacto que se queda apoyado es **toque y
  mantener** (o **doble toque y mantener**).
- Mientras un dedo explora, un toque breve con otro dedo es un **toque
  dividido** (activa lo que hay bajo el dedo que explora).
- Con ``edgeMargin`` y ``bounds``, un deslizamiento de un dedo que empieza
  en la franja de un borde lleva ``edge`` (``left``, ``right``, ``top`` o
  ``bottom``): es un **gesto de borde**.

Los instantes los da quien llama, así que el reconocedor no lee el reloj:
:meth:`GestureRecognizer.poll` resuelve los plazos vencidos y
:meth:`GestureRecognizer.nextDeadline` dice cuándo hay que volver a llamarlo.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------- acciones
TAP = "tap"
DOUBLE_TAP = "doubleTap"
TRIPLE_TAP = "tripleTap"
TAP_AND_HOLD = "tapAndHold"
DOUBLE_TAP_AND_HOLD = "doubleTapAndHold"
HOLD = "hold"
FLICK_UP = "flickUp"
FLICK_DOWN = "flickDown"
FLICK_LEFT = "flickLeft"
FLICK_RIGHT = "flickRight"
PINCH_IN = "pinchIn"
PINCH_OUT = "pinchOut"
HOVER_DOWN = "hoverDown"
HOVER = "hover"
HOVER_UP = "hoverUp"
SPLIT_TAP = "splitTap"

HOVER_ACTIONS = frozenset({HOVER_DOWN, HOVER, HOVER_UP})
FLICK_ACTIONS = frozenset({FLICK_UP, FLICK_DOWN, FLICK_LEFT, FLICK_RIGHT})

_DIRECTIONS = {FLICK_UP: "Up", FLICK_DOWN: "Down", FLICK_LEFT: "Left", FLICK_RIGHT: "Right"}
_OPPOSITE = {FLICK_UP: FLICK_DOWN, FLICK_DOWN: FLICK_UP, FLICK_LEFT: FLICK_RIGHT, FLICK_RIGHT: FLICK_LEFT}


def sequenceAction(first: str, second: str) -> str:
	"""``flickRight`` + ``flickLeft`` -> ``flickRightThenLeft``."""
	return f"{first}Then{_DIRECTIONS[second]}"


#: Las 12 secuencias de dos deslizamientos: 4 contrarias y 8 en L.
SEQUENCE_ACTIONS = tuple(sequenceAction(a, b) for a in _DIRECTIONS for b in _DIRECTIONS if a != b)
OPPOSITE_SEQUENCES = tuple(sequenceAction(a, _OPPOSITE[a]) for a in _DIRECTIONS)
L_SEQUENCES = tuple(a for a in SEQUENCE_ACTIONS if a not in OPPOSITE_SEQUENCES)
#: Acciones que pueden ser gestos de borde (las de un dedo que se desliza).
EDGE_ACTIONS = FLICK_ACTIONS | frozenset(SEQUENCE_ACTIONS)
EDGES = ("left", "right", "top", "bottom")

ALL_ACTIONS = (
	TAP,
	DOUBLE_TAP,
	TRIPLE_TAP,
	TAP_AND_HOLD,
	DOUBLE_TAP_AND_HOLD,
	HOLD,
	FLICK_UP,
	FLICK_DOWN,
	FLICK_LEFT,
	FLICK_RIGHT,
	*SEQUENCE_ACTIONS,
	PINCH_IN,
	PINCH_OUT,
	HOVER_DOWN,
	HOVER,
	HOVER_UP,
	SPLIT_TAP,
)

_TAP_BY_COUNT = {1: TAP, 2: DOUBLE_TAP, 3: TRIPLE_TAP}
_HOLD_BY_COUNT = {1: TAP_AND_HOLD, 2: DOUBLE_TAP_AND_HOLD}
_MAX_PATH = 400


@dataclass
class RecognizerSettings:
	"""Umbrales del reconocedor (tiempos en segundos, distancias en píxeles)."""

	#: Un dedo que sigue apoyado pasado este tiempo deja de ser un toque o un
	#: deslizamiento: explora (un dedo) o mantiene (varios dedos). También es
	#: la ventana para que varios dedos cuenten como un solo gesto.
	holdTime: float = 0.25
	#: Tiempo máximo entre levantar los dedos y volver a tocar para que cuente
	#: como doble o triple toque.
	multiTapTimeout: float = 0.3
	#: Movimiento máximo de un dedo para que siga siendo un toque.
	maxTapDrift: float = 12.0
	#: Recorrido mínimo para que un movimiento sea un deslizamiento (y cada
	#: tramo de una secuencia de dos deslizamientos).
	minFlickDistance: float = 50.0
	#: Cambio mínimo de la distancia entre dos dedos para que sea un pellizco.
	minPinchDistance: float = 60.0
	#: Duración máxima de una secuencia de dos deslizamientos sin levantar el
	#: dedo. Mientras el dedo se desliza rápido no empieza la exploración.
	continuousFlickTimeout: float = 0.6
	#: Tiempo máximo entre dos deslizamientos (levantando el dedo) para que
	#: formen una secuencia. Solo se espera si ``sequenceFilter`` lo pide.
	sequenceTimeout: float = 0.3
	#: Anchura de la franja de cada borde en píxeles (0: sin gestos de borde).
	edgeMargin: float = 0.0
	#: Rectángulo (x, y, ancho, alto) cuyos bordes cuentan.
	bounds: tuple[int, int, int, int] | None = None


@dataclass
class TouchEvent:
	"""Gesto reconocido."""

	action: str
	fingers: int
	x: int
	y: int
	time: float
	#: Borde donde empezó el gesto (``left``, ``right``, ``top``, ``bottom``) o ``None``.
	edge: str | None = None

	@property
	def name(self) -> str:
		"""Nombre del gesto sin el borde, p. ej. ``tap``, ``2finger_flickDown``."""
		return makeName(self.action, self.fingers)

	@property
	def edgeName(self) -> str | None:
		"""Nombre con el borde (``leftEdge_flickRight``) o ``None``."""
		return makeName(self.action, self.fingers, self.edge) if self.edge else None

	@property
	def isHover(self) -> bool:
		return self.action in HOVER_ACTIONS


def makeName(action: str, fingers: int = 1, edge: str | None = None) -> str:
	name = f"{fingers}finger_{action}" if fingers > 1 else action
	return f"{edge}Edge_{name}" if edge else name


def splitEdge(name: str) -> tuple[str | None, str]:
	"""``leftedge_flickright`` -> (``left``, ``flickright``)."""
	head, sep, rest = name.partition("_")
	if sep and head.lower().endswith("edge") and head[:-4].lower() in EDGES:
		return head[:-4].lower(), rest
	return None, name


def splitName(name: str) -> tuple[int, str]:
	"""``2finger_flickdown`` -> ``(2, "flickdown")``; ``tap`` -> ``(1, "tap")``."""
	head, sep, rest = name.partition("finger_")
	if sep and head.isdigit():
		return int(head), rest
	return 1, name


def _direction(dx: float, dy: float) -> str:
	if abs(dx) >= abs(dy):
		return FLICK_RIGHT if dx > 0 else FLICK_LEFT
	return FLICK_DOWN if dy > 0 else FLICK_UP


class _Contact:
	__slots__ = ("id", "x0", "y0", "t0", "x", "y", "t", "maxDrift", "maxAxis", "up", "path")

	def __init__(self, cid: int, x: int, y: int, t: float) -> None:
		self.id = cid
		self.x0 = self.x = x
		self.y0 = self.y = y
		self.t0 = self.t = t
		self.maxDrift = 0.0
		#: Mayor desplazamiento en un eje desde el inicio.
		self.maxAxis = 0.0
		self.up = False
		self.path: list[tuple[int, int]] = [(x, y)]

	def update(self, x: int, y: int, t: float) -> None:
		self.x = x
		self.y = y
		self.t = t
		d = math.hypot(x - self.x0, y - self.y0)
		if d > self.maxDrift:
			self.maxDrift = d
		a = max(abs(x - self.x0), abs(y - self.y0))
		if a > self.maxAxis:
			self.maxAxis = a
		if len(self.path) < _MAX_PATH:
			self.path.append((x, y))
		else:
			self.path[-1] = (x, y)


class _Group:
	"""Dedos que empezaron a tocar a la vez."""

	__slots__ = ("start", "members", "extras", "state", "hoverId", "hoverEnded", "extendUntil")

	def __init__(self, start: float) -> None:
		self.start = start
		self.members: dict[int, _Contact] = {}
		#: Dedos que llegan tarde (toque dividido o dedos ignorados).
		self.extras: dict[int, _Contact] = {}
		#: pending, hover, hold o ignore
		self.state = "pending"
		self.hoverId: int | None = None
		self.hoverEnded = False
		#: Plazo ampliado mientras los dedos se deslizan rápido.
		self.extendUntil = 0.0

	def find(self, cid: int) -> _Contact | None:
		return self.members.get(cid) or self.extras.get(cid)

	def allUp(self) -> bool:
		return all(c.up for c in self.members.values()) and all(c.up for c in self.extras.values())

	def deadline(self, holdTime: float) -> float:
		return max(max(c.t0 for c in self.members.values()) + holdTime, self.extendUntil)


class _PendingTap:
	__slots__ = ("fingers", "count", "x", "y", "tEnd")

	def __init__(self, fingers: int, x: int, y: int, tEnd: float) -> None:
		self.fingers = fingers
		self.count = 1
		self.x = x
		self.y = y
		self.tEnd = tEnd


class _PendingFlick:
	__slots__ = ("action", "fingers", "x", "y", "tEnd", "edge")

	def __init__(self, action: str, fingers: int, x: int, y: int, tEnd: float, edge: str | None) -> None:
		self.action = action
		self.fingers = fingers
		self.x = x
		self.y = y
		self.tEnd = tEnd
		self.edge = edge


class GestureRecognizer:
	"""Convierte contactos de dedos en gestos.

	:param sequenceFilter: ``sequenceFilter(acción, dedos)`` dice si, tras un
		deslizamiento, hay que esperar ``sequenceTimeout`` por si llega un
		segundo deslizamiento (secuencia hecha levantando el dedo). Sin filtro
		no se espera nunca y solo se reconocen las secuencias sin levantar el
		dedo.
	"""

	def __init__(self, settings: RecognizerSettings | None = None, sequenceFilter: Callable[[str, int], bool] | None = None) -> None:
		self.settings = settings or RecognizerSettings()
		self.sequenceFilter = sequenceFilter
		self._group: _Group | None = None
		self._pending: _PendingTap | None = None
		self._pendingFlick: _PendingFlick | None = None
		self._out: list[TouchEvent] = []

	# ------------------------------------------------------------ entrada
	def down(self, cid: int, x: int, y: int, t: float) -> list[TouchEvent]:
		self._advance(t)
		g = self._group
		if g is not None and g.find(cid) is not None:
			# Contacto repetido (el sistema a veces lo reenvía): se trata como movimiento.
			return self._move(cid, x, y, t)
		c = _Contact(cid, x, y, t)
		if g is None:
			g = _Group(t)
			g.members[cid] = c
			self._group = g
		elif g.state == "pending" and t - g.start <= self.settings.holdTime:
			g.members[cid] = c
		else:
			g.extras[cid] = c
		return self._take()

	def move(self, cid: int, x: int, y: int, t: float) -> list[TouchEvent]:
		self._advance(t)
		return self._move(cid, x, y, t)

	def up(self, cid: int, x: int, y: int, t: float) -> list[TouchEvent]:
		self._advance(t)
		g = self._group
		c = g.find(cid) if g is not None else None
		if g is None or c is None or c.up:
			return self._take()
		c.update(x, y, t)
		c.up = True
		if g.state == "hover":
			if cid == g.hoverId:
				g.hoverEnded = True
				self._emit(HOVER_UP, 1, x, y, t)
			elif cid in g.extras and not g.hoverEnded:
				s = self.settings
				if t - c.t0 < s.holdTime and c.maxDrift <= s.maxTapDrift:
					h = g.members[g.hoverId] if g.hoverId in g.members else c
					self._emit(SPLIT_TAP, 1, h.x, h.y, t)
		if g.allUp():
			if g.state == "pending":
				self._resolveRelease(g, t)
			self._group = None
		return self._take()

	def cancel(self, t: float | None = None) -> list[TouchEvent]:
		"""El sistema anuló los contactos: se olvida todo sin emitir gestos."""
		self._group = None
		self._pending = None
		self._pendingFlick = None
		self._out = []
		return []

	def poll(self, t: float) -> list[TouchEvent]:
		"""Resuelve los plazos vencidos hasta el instante ``t``."""
		self._advance(t)
		return self._take()

	def nextDeadline(self) -> float | None:
		"""Instante en que hay que llamar a :meth:`poll` (o ``None``)."""
		times = []
		g = self._group
		if g is not None and g.state == "pending" and g.members:
			times.append(g.deadline(self.settings.holdTime))
		for expiry in (self._tapExpiry(), self._flickExpiry()):
			if expiry is not None and not (g is not None and g.start <= expiry):
				times.append(expiry)
		return min(times) if times else None

	@property
	def isTouching(self) -> bool:
		return self._group is not None

	@property
	def isHovering(self) -> bool:
		g = self._group
		return g is not None and g.state == "hover" and not g.hoverEnded

	# ------------------------------------------------------------ lógica
	def _take(self) -> list[TouchEvent]:
		out, self._out = self._out, []
		return out

	def _emit(self, action: str, fingers: int, x: float, y: float, t: float, edge: str | None = None) -> None:
		self._out.append(TouchEvent(action, fingers, int(round(x)), int(round(y)), t, edge))

	def _edgeOf(self, x: float, y: float) -> str | None:
		s = self.settings
		if s.edgeMargin <= 0 or not s.bounds:
			return None
		bx, by, bw, bh = s.bounds
		distances = {"left": x - bx, "right": bx + bw - 1 - x, "top": y - by, "bottom": by + bh - 1 - y}
		edge = min(distances, key=lambda k: distances[k])
		return edge if 0 <= distances[edge] < s.edgeMargin else None

	def _move(self, cid: int, x: int, y: int, t: float) -> list[TouchEvent]:
		g = self._group
		c = g.find(cid) if g is not None else None
		if g is None or c is None or c.up:
			return self._take()
		if (x, y) == (c.x, c.y):
			return self._take()
		c.update(x, y, t)
		if g.state == "hover" and cid == g.hoverId and not g.hoverEnded:
			self._emit(HOVER, 1, x, y, t)
		return self._take()

	def _tapExpiry(self) -> float | None:
		p = self._pending
		return p.tEnd + self.settings.multiTapTimeout if p is not None else None

	def _flickExpiry(self) -> float | None:
		f = self._pendingFlick
		return f.tEnd + self.settings.sequenceTimeout if f is not None else None

	def _advance(self, t: float) -> None:
		s = self.settings
		g = self._group
		for _i in range(3):
			if g is None or g.state != "pending" or not g.members:
				break
			deadline = g.deadline(s.holdTime)
			if t < deadline or all(c.up for c in g.members.values()):
				break
			self._resolveHold(g, deadline)
		g = self._group
		for expiry, flush in ((self._flickExpiry(), self._flushFlick), (self._tapExpiry(), self._flushTap)):
			if expiry is not None and t >= expiry and not (g is not None and g.start <= expiry):
				flush(expiry)

	def _flushTap(self, t: float) -> None:
		p = self._pending
		if p is None:
			return
		self._pending = None
		self._emit(_TAP_BY_COUNT.get(p.count, TAP), p.fingers, p.x, p.y, t)

	def _flushFlick(self, t: float) -> None:
		f = self._pendingFlick
		if f is None:
			return
		self._pendingFlick = None
		self._emit(f.action, f.fingers, f.x, f.y, t, f.edge)

	def _flushPending(self, t: float) -> None:
		"""Emite lo que esperaba (deslizamiento y toques) antes de otro gesto."""
		self._flushFlick(t)
		self._flushTap(t)

	def _continuesTaps(self, g: _Group, fingers: int) -> bool:
		p = self._pending
		return p is not None and p.fingers == fingers and g.start <= p.tEnd + self.settings.multiTapTimeout

	def _classify(self, c: _Contact) -> str | None:
		"""Toque, deslizamiento, secuencia de dos deslizamientos o ``None``."""
		s = self.settings
		if c.maxDrift <= s.maxTapDrift:
			return TAP
		dx = c.x - c.x0
		dy = c.y - c.y0
		# Busca el punto de giro: el más alejado de la cuerda inicio-fin o, si
		# el dedo volvió cerca del inicio, el más alejado del inicio.
		chord = math.hypot(dx, dy)
		turn = None
		best = 0.0
		for px, py in c.path:
			if chord >= s.minFlickDistance:
				d = abs(dy * (px - c.x0) - dx * (py - c.y0)) / chord
			else:
				d = math.hypot(px - c.x0, py - c.y0)
			if d > best:
				best, turn = d, (px, py)
		if turn is not None and best >= s.minFlickDistance * 0.5:
			tx, ty = turn
			s1 = (tx - c.x0, ty - c.y0)
			s2 = (c.x - tx, c.y - ty)
			if max(map(abs, s1)) >= s.minFlickDistance and max(map(abs, s2)) >= s.minFlickDistance:
				d1 = _direction(*s1)
				d2 = _direction(*s2)
				if d1 != d2:
					return sequenceAction(d1, d2)
		if max(abs(dx), abs(dy)) < s.minFlickDistance:
			return None
		return _direction(dx, dy)

	def _onFlick(self, action: str, n: int, x: float, y: float, t: float, edge: str | None, g: _Group) -> None:
		"""Un deslizamiento simple: puede ser el segundo de una secuencia."""
		f = self._pendingFlick
		s = self.settings
		if f is not None and f.fingers == n and g.start <= f.tEnd + s.sequenceTimeout and f.action != action:
			self._pendingFlick = None
			self._flushTap(g.start)
			self._emit(sequenceAction(f.action, action), n, f.x, f.y, t, f.edge)
			return
		self._flushPending(g.start)
		if self.sequenceFilter is not None:
			try:
				wait = bool(self.sequenceFilter(action, n))
			except Exception:
				wait = False
			if wait:
				self._pendingFlick = _PendingFlick(action, n, int(round(x)), int(round(y)), t, edge)
				return
		self._emit(action, n, x, y, t, edge)

	def _resolveRelease(self, g: _Group, t: float) -> None:
		"""Todos los dedos se levantaron antes de cumplirse el plazo."""
		members = list(g.members.values())
		n = len(members)
		actions = {self._classify(c) for c in members}
		x = sum(c.x0 for c in members) / n
		y = sum(c.y0 for c in members) / n
		if actions == {TAP}:
			self._flushFlick(g.start)
			if self._continuesTaps(g, n):
				p = self._pending
				assert p is not None
				p.count += 1
				p.tEnd = t
				if p.count >= 3:
					self._pending = None
					self._emit(TRIPLE_TAP, n, p.x, p.y, t)
				return
			self._flushTap(g.start)
			self._pending = _PendingTap(n, int(round(x)), int(round(y)), t)
			return
		if len(actions) == 1:
			action = next(iter(actions))
			edge = self._edgeOf(members[0].x0, members[0].y0) if n == 1 else None
			if action in FLICK_ACTIONS:
				self._onFlick(action, n, x, y, t, edge, g)
				return
			if action in SEQUENCE_ACTIONS:
				self._flushPending(g.start)
				self._emit(action, n, x, y, t, edge)
				return
		self._flushPending(g.start)
		if n == 2 and TAP not in actions:
			# Pellizco: los dos dedos se mueven y cambia la distancia entre ellos.
			a, b = members
			before = math.hypot(a.x0 - b.x0, a.y0 - b.y0)
			after = math.hypot(a.x - b.x, a.y - b.y)
			if abs(after - before) >= self.settings.minPinchDistance:
				self._emit(PINCH_OUT if after > before else PINCH_IN, 2, x, y, t)
		# Cualquier otra combinación no es un gesto reconocible.

	def _resolveHold(self, g: _Group, t: float) -> None:
		"""Algún dedo sigue apoyado al cumplirse el plazo."""
		s = self.settings
		members = list(g.members.values())
		n = len(members)
		if any(c.up for c in members):
			# Unos dedos se levantaron y otros no: no es un gesto claro.
			self._flushPending(g.start)
			g.state = "ignore"
			return
		# Dedos que se deslizan rápido: puede ser una secuencia de dos
		# deslizamientos sin levantar el dedo; se espera un poco más.
		limit = max(c.t0 for c in members) + s.continuousFlickTimeout
		if all(c.maxAxis >= s.minFlickDistance for c in members) and t < limit - 1e-9:
			g.extendUntil = limit
			return
		still = all(c.maxDrift <= s.maxTapDrift for c in members)
		x = sum(c.x for c in members) / n
		y = sum(c.y for c in members) / n
		if still and self._continuesTaps(g, n):
			p = self._pending
			assert p is not None
			self._pending = None
			self._flushFlick(g.start)
			if p.count in _HOLD_BY_COUNT:
				self._emit(_HOLD_BY_COUNT[p.count], n, x, y, t)
			g.state = "hold"
			return
		self._flushPending(g.start)
		if n == 1:
			c = members[0]
			g.state = "hover"
			g.hoverId = c.id
			self._emit(HOVER_DOWN, 1, c.x, c.y, t)
			return
		if still:
			self._emit(HOLD, n, x, y, t)
			g.state = "hold"
		else:
			g.state = "ignore"
