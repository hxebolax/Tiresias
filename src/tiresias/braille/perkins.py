"""Modo Perkins: escribir con el teclado del PC como en una máquina Perkins.

La máquina Perkins tiene seis teclas de puntos (de izquierda a derecha 3, 2,
1 y 4, 5, 6), un espaciador en el centro, la tecla de interlineado a la
izquierda y la de retroceso a la derecha. Se escribe pulsando a la vez las
teclas de los puntos de cada celda. En el teclado del PC:

- F D S son los puntos 1 2 3 y J K L los puntos 4 5 6 (siempre en la misma
  posición física, sea cual sea la distribución del teclado);
- la barra espaciadora es el espaciador;
- A es la tecla de interlineado (y también Intro);
- Ñ es la de retroceso (y también Retroceso).

Este módulo pone el sonido de la máquina (grabaciones de una Perkins real) y
lleva la cuenta de la columna para tocar la campana cuando quedan pocas
celdas para el final de la línea, como la máquina. La escritura en sí la hace
la entrada braille (:mod:`.input`), con la tabla de entrada elegida.

Sonidos: ``data\\perkins`` del programa (``teclaN.wav``, ``espacioN.wav``,
``retroceso.wav``, ``linea.wav``, ``campana.wav`` y ``papel.wav``). Quien
quiera otros puede poner los suyos con esos nombres en la carpeta
``perkinsPropios`` de su carpeta de datos: tienen preferencia y no se tocan
al actualizar.
"""

from __future__ import annotations

import os
import queue
import random
import threading

from ..config import conf
from ..log import getLogger

log = getLogger("perkins")

#: Celdas antes del final de la línea en las que suena la campana (como la Perkins).
BELL_BEFORE_END = 6
#: Carpeta de la carpeta de datos con los sonidos propios del usuario (tienen
#: preferencia y no se tocan al actualizar Tiresias).
USER_FOLDER = "perkinsPropios"
SOUND_NAMES = ("tecla", "espacio", "retroceso", "linea", "campana", "papel")


def soundFolders() -> list[str]:
	"""Carpetas donde se buscan los sonidos: la del usuario y la del programa."""
	from .. import paths

	folders = [paths.data(USER_FOLDER), paths.programData("perkins")]
	result: list[str] = []
	for f in folders:
		if os.path.normcase(f) not in (os.path.normcase(r) for r in result):
			result.append(f)
	return result


def soundFiles(name: str, folders: list[str] | None = None) -> list[str]:
	"""Archivos de un sonido (``tecla`` puede tener varios: tecla1.wav, tecla2.wav...).

	Se usan los de la primera carpeta que tenga alguno.
	"""
	for folder in folders if folders is not None else soundFolders():
		try:
			names = os.listdir(folder)
		except OSError:
			continue
		found = sorted(
			os.path.join(folder, n)
			for n in names
			if n.lower().endswith(".wav") and (n.lower() == f"{name}.wav" or (n.lower().startswith(name) and n[len(name) : -4].isdigit()))
		)
		if found:
			return found
	return []


#: Tabla del modo Perkins por defecto: braille integral español de 6 puntos
#: (liblouis) y, si no está, la propia de Tiresias. Una Perkins escribe braille
#: literario: con la tabla informática «Hola» saldría «{hola» y «123», «#abc».
AUTO_TABLES = ("es.tbl", "es-g1")


def tableName() -> str:
	"""Nombre de la tabla que usa el modo Perkins (``braille.perkinsTable``)."""
	try:
		name = str(conf["braille"]["perkinsTable"] or "auto")
	except Exception:
		name = "auto"
	if name != "auto":
		return name
	from . import liblouis

	try:
		louis = liblouis.load()
	except Exception:
		louis = False
	return AUTO_TABLES[0] if louis else AUTO_TABLES[1]


def inputTable():
	from . import tables

	return tables.getTable(tableName(), forInput=True)


def tableChoices() -> list[tuple[str, str]]:
	"""Opciones de la tabla del modo Perkins (para las Opciones)."""
	from ..i18n import _
	from . import tables

	choices = [("auto", _("Automática: español, braille integral de 6 puntos"))]
	return choices + [(n, label) for n, label in tables.listTables(forInput=True) if n != "auto"]


#: Signos que en braille español son la misma celda al abrir y al cerrar.
_OPENING = {"?": "¿", "!": "¡"}
_CLOSING = {v: k for k, v in _OPENING.items()}


def fixSpanishMarks(text: str) -> str:
	"""«¿» y «¡» al principio de la palabra; «?» y «!» en el resto.

	En braille español la interrogación (puntos 2 6) y la exclamación (puntos
	2 3 5) son la misma celda al abrir y al cerrar: se distinguen por su
	posición, como al leer en papel. ``text`` es la palabra que se escribe.
	"""
	if not text:
		return text
	chars = list(text)
	for i, ch in enumerate(chars):
		if i == 0:
			chars[i] = _OPENING.get(ch, ch)
		else:
			chars[i] = _CLOSING.get(ch, ch)
	return "".join(chars)


class _SoundWorker:
	"""Reproduce los sonidos en un hilo propio: el hilo de los ganchos no espera."""

	def __init__(self) -> None:
		self._queue: queue.SimpleQueue = queue.SimpleQueue()
		self._thread: threading.Thread | None = None
		self._lock = threading.Lock()

	def play(self, name: str) -> None:
		with self._lock:
			if self._thread is None or not self._thread.is_alive():
				self._thread = threading.Thread(target=self._run, name="Sonidos Perkins", daemon=True)
				self._thread.start()
		self._queue.put(name)

	def _run(self) -> None:
		from ..audio import tones

		cache: dict[str, list[str]] = {}
		while True:
			name = self._queue.get()
			try:
				files = cache.get(name)
				if files is None:
					files = cache[name] = soundFiles(name)
				if files:
					tones._playWaveFile(random.choice(files))
			except Exception:
				log.debug("No se pudo reproducir el sonido Perkins %s", name, exc_info=True)


class PerkinsMachine:
	"""Sonidos y columna de la máquina Perkins emulada."""

	def __init__(self, player=None) -> None:
		self.column = 0
		self._player = player or _SoundWorker()

	# ---------------------------------------------------------- opciones
	@staticmethod
	def lineLength() -> int:
		try:
			return max(10, int(conf["braille"]["perkinsLineLength"]))
		except Exception:
			return 40

	@staticmethod
	def soundsOn() -> bool:
		try:
			return bool(conf["braille"]["perkinsSounds"])
		except Exception:
			return True

	def _play(self, name: str) -> None:
		if self.soundsOn():
			self._player.play(name)

	# ---------------------------------------------------------- acciones
	def reset(self) -> None:
		"""Papel nuevo: al activar el modo o cambiar de campo."""
		self.column = 0

	def keyDown(self, space: bool) -> None:
		"""Primera tecla de un acorde (hilo de los ganchos): el golpe de la máquina."""
		self._play("espacio" if space else "tecla")

	def cell(self) -> None:
		"""Una celda escrita (o un espacio): avanza el carro; campana cerca del final."""
		self.column += 1
		try:
			bell = conf["braille"]["perkinsBell"]
		except Exception:
			bell = True
		if bell and self.column == self.lineLength() - BELL_BEFORE_END:
			self._play("campana")

	def newLine(self) -> None:
		"""Tecla de interlineado: el carro vuelve al principio."""
		self.column = 0
		self._play("linea")

	def backspace(self) -> None:
		if self.column > 0:
			self.column -= 1
		self._play("retroceso")

	def paperIn(self) -> None:
		self.column = 0
		self._play("linea")

	def paperOut(self) -> None:
		self._play("papel")


machine = PerkinsMachine()


def toggle() -> str:
	"""Activa o desactiva el modo Perkins. Devuelve el mensaje que se dice."""
	from ..i18n import _
	from . import input as brailleInput

	kb = brailleInput.pcKeyboard
	if kb.perkins:
		kb.setEnabled(False)
		machine.paperOut()
		return _("teclado normal")
	kb.setEnabled(True, perkins=True)
	machine.paperIn()
	if conf["braille"]["perkinsOnlyInEditable"] and not kb.perkinsActiveHere():
		return _("modo Perkins activado; se usará al escribir en un campo de texto")
	return _("modo Perkins")
