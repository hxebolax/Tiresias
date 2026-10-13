"""El equipo local visto por el acceso remoto (implementación para Tiresias).

Todas las funciones se llaman en el hilo del núcleo, salvo :meth:`sendKey`,
que inyecta las teclas recibidas desde el hilo de red con ``SendInput`` para
no depender de lo ocupado que esté el núcleo.
"""

from __future__ import annotations

import functools
import os
from typing import TYPE_CHECKING, Any

from .. import queue_handler, winapi
from ..config import conf
from ..i18n import _
from ..log import getLogger
from . import cues
from .session import LocalMachine, RemoteSession

if TYPE_CHECKING:
	from .client import RemoteClient

log = getLogger("remote")

VK_NONE = 0xFF


def _say(text: str, interrupt: bool = False) -> None:
	from .. import speech

	if interrupt:
		speech.cancelSpeech()
	speech.speakMessage(text)


DRIVE_REMOTE = 4


def _driveType(root: str) -> int:
	try:
		import ctypes

		return int(ctypes.windll.kernel32.GetDriveTypeW(root))
	except Exception:
		return 0


def isLocalWavePath(fileName: str, driveType=_driveType) -> bool:
	"""``True`` si ``fileName`` es un ``.wav`` de un disco de este equipo.

	Los sonidos que manda el otro equipo nunca se buscan en carpetas
	compartidas ni unidades de red: abrir ``\\\\servidor\\x.wav`` conectaría
	con ese servidor (y le mandaría las credenciales de Windows).
	"""
	if not isinstance(fileName, str) or not fileName.lower().endswith(".wav"):
		return False
	if any(ord(c) < 32 for c in fileName) or fileName.startswith(("\\\\", "//", "\\", "/")):
		return False
	drive, _rest = os.path.splitdrive(fileName)
	if len(drive) != 2 or drive[1] != ":" or not os.path.isabs(fileName):
		return False
	return driveType(drive + "\\") != DRIVE_REMOTE


class TiresiasMachine(LocalMachine):
	def __init__(self, client: "RemoteClient") -> None:
		self.client = client
		#: Silencia la voz, pitidos y sonidos del equipo controlado.
		self.isMuted = False
		#: La línea braille muestra lo que envía el equipo controlado.
		self.receivingBraille = False
		self._lastCells: list[int] = []

	# ================================================================ salida recibida
	def speak(self, sequence: list, priority: int = 0) -> None:
		if self.isMuted or not sequence:
			return
		from ..speech import api as speechApi

		mode = speechApi.getSpeechMode()
		texts = [s for s in sequence if isinstance(s, str)]
		speechApi._addToHistory(" ".join(t for t in texts if t), speechApi.ORIGIN_REMOTE)
		if mode == speechApi.SpeechMode.beeps:
			if any(t.strip() for t in texts):
				from ..audio import tones

				tones.beep(conf_beepPitch(), 20)
			return
		if mode in (speechApi.SpeechMode.off, speechApi.SpeechMode.onDemand):
			return
		if priority >= speechApi.Priority.NOW:
			speechApi.cancelSpeech()
		speechApi._beenCanceled = False
		# La voz ya viene procesada por el otro equipo (símbolos, diccionarios).
		prio = speechApi.Priority(min(max(int(priority), 0), 2))
		speechApi.pre_speech.notify(sequence=list(sequence))
		speechApi.getManager().speak(list(sequence), prio, origin=speechApi.ORIGIN_REMOTE)
		speechApi.pre_speechQueued.notify(speechSequence=list(sequence), priority=prio)

	def cancelSpeech(self) -> None:
		if self.isMuted:
			return
		from .. import speech

		speech.cancelSpeech()

	def pauseSpeech(self, switch: bool) -> None:
		if self.isMuted:
			return
		from .. import speech

		speech.pauseSpeech(switch)

	def beep(self, hz: float, length: int, left: int = 50, right: int = 50) -> None:
		if self.isMuted:
			return
		from ..audio import tones

		tones.beep(hz, max(0, min(length, 5000)), left, right)

	def playWave(self, fileName: str = "", name: str = "") -> None:
		if self.isMuted:
			return
		from ..audio import tones

		if name and name in tones.availableSounds():
			tones.playSound(name)
			return
		base = os.path.splitext(os.path.basename(fileName.replace("\\", "/")))[0].lower() if fileName else ""
		mapped = cues.NVDA_WAVES.get(base)
		if mapped:
			tones.playSound(mapped)
		elif isLocalWavePath(fileName) and os.path.isfile(fileName):
			tones.playWaveFile(fileName)
		elif fileName:
			log.debug("Sonido remoto no admitido: %r", fileName)

	def display(self, cells: list[int]) -> None:
		self._lastCells = list(cells)
		if self.receivingBraille:
			from .. import braille

			braille.handler.showRemoteCells(self._lastCells, owner=self)

	def setReceivingBraille(self, state: bool) -> None:
		from .. import braille

		self.receivingBraille = state
		# Cada equipo (acceso remoto, cada ventana de Escritorio remoto) es un
		# dueño distinto: dejar de mostrar uno no borra lo que muestra otro.
		braille.handler.showRemoteCells(self._lastCells if state and self._lastCells else None, owner=self)

	# ================================================================ entrada recibida
	def sendKey(self, vk: int, extended: bool, pressed: bool, scan: int | None = None) -> None:
		"""Inyecta una tecla del equipo que controla (hilo de red)."""
		if not (0 < vk <= 0xFF):
			return
		inp = winapi.INPUT()
		inp.type = winapi.INPUT_KEYBOARD
		inp.ki.wVk = vk
		# Como NVDA: el código de exploración se calcula con la distribución local.
		inp.ki.wScan = winapi.user32.MapVirtualKeyW(vk, 0) & 0xFFFF if vk != VK_NONE else 0
		flags = 0
		if not pressed:
			flags |= winapi.KEYEVENTF_KEYUP
		if extended:
			flags |= winapi.KEYEVENTF_EXTENDEDKEY
		inp.ki.dwFlags = flags
		inp.ki.dwExtraInfo = winapi.REMOTE_INJECTION_MARK
		try:
			winapi.sendInputs([inp])
		except Exception:
			log.exception("No se pudo inyectar la tecla remota %#x", vk)

	def brailleInput(self, **kwargs: Any) -> None:
		"""Teclas de la línea braille del equipo que controla."""
		from .. import braille
		from ..input import core as inputCore

		gesture = _RemoteBrailleGesture(kwargs)
		scriptPath = kwargs.get("scriptPath")
		name = scriptPath[2] if isinstance(scriptPath, list) and len(scriptPath) == 3 and isinstance(scriptPath[2], str) else ""
		if name.startswith("kb:"):
			from ..input.gestures import sendKey

			try:
				sendKey(name[3:])
			except Exception:
				log.debug("No se pudo emular %s", name, exc_info=True)
			return
		if name:
			func = _findScript(name)
			if func is not None:
				try:
					func(gesture)
				except Exception:
					log.exception("Error ejecutando la orden braille remota %s", name)
				return
		if name == "braille_routeTo" and gesture.routingIndex is not None:
			braille.handler.routeTo(gesture.routingIndex)
			return
		if gesture.dots or gesture.space:
			inputCore._brailleInput(gesture.dots, gesture.space)

	def sendSAS(self) -> None:
		# Windows solo deja simular Control+Alt+Supr a servicios del sistema o a
		# programas con «uiAccess» firmados e instalados en Archivos de programa.
		log.info("Petición remota de Control+Alt+Supr: no disponible en Tiresias")
		_say(_("Este equipo no puede recibir Control+Alt+Supr por acceso remoto. Pulsa la combinación en el propio equipo o usa el Administrador de tareas."))

	def setBrailleDisplaySize(self, size: int) -> None:
		from .. import braille

		braille.handler.setRemoteNumCells(size, owner="remote")

	# ================================================================ común
	def setClipboardText(self, text: str) -> None:
		from .. import clipboard

		try:
			clipboard.ignoreNextChange()
			if not winapi.setClipboardText(text):
				raise OSError("SetClipboardData")
		except Exception:
			log.exception("No se pudo escribir el portapapeles recibido")
			_say(_("No se pudo copiar el portapapeles recibido"))
			return
		cues.clipboardReceived()

	def onClientJoined(self, session: RemoteSession, client: dict) -> None:
		self.client._onClientJoined(session, client)

	def onClientLeft(self, session: RemoteSession, client: dict) -> None:
		self.client._onClientLeft(session, client)

	def onMotd(self, session: RemoteSession, motd: str, forceDisplay: bool) -> None:
		self.client._onMotd(session, motd, forceDisplay)

	def onServerError(self, session: RemoteSession, error: str) -> None:
		self.client._onServerError(session, error)

	def onVersionMismatch(self, session: RemoteSession) -> None:
		_say(_("El servidor de acceso remoto no es compatible con esta versión del protocolo. Usa otro servidor."))
		queue_handler.queueFunction(self.client.disconnect, True)

	def onRemoteNotConnected(self, session: RemoteSession) -> None:
		_say(_("El equipo remoto no está conectado"), interrupt=True)


class _RemoteBrailleGesture:
	"""Gesto braille recibido (imita lo necesario de un gesto local)."""

	def __init__(self, data: dict) -> None:
		self.source = f"remote{str(data.get('source', '')).capitalize()}"
		self.id = str(data.get("id", ""))
		cells = data.get("cellIndexes")
		idx = data.get("routingIndex")
		if isinstance(cells, list) and cells and isinstance(cells[0], int):
			idx = cells[0]
		self.routingIndex: int | None = idx if isinstance(idx, int) else None
		dots = data.get("dots", 0)
		self.dots = dots if isinstance(dots, int) else 0
		self.space = bool(data.get("space", False))
		self.identifiers = [f"br({self.source}):{self.id}"] if self.id else []
		self.displayName = self.id
		self.isModifier = False

	def send(self) -> None:
		pass


def _findScript(name: str):
	"""Busca ``script_<name>`` en los complementos globales y las órdenes globales."""
	from ..global_commands import commands
	from ..plugins import handler as pluginHandler

	attr = f"script_{name}"
	for plugin in list(pluginHandler.runningPlugins):
		func = getattr(plugin, attr, None)
		if callable(func):
			return func
	func = getattr(commands, attr, None)
	return func if callable(func) else None


def nvdaWavePath(soundName: str) -> str:
	"""Ruta donde un NVDA instalado tendría el sonido equivalente (o ``""``).

	El protocolo solo admite una ruta, que el NVDA del otro equipo reproduce
	tal cual. NVDA de 64 bits se instala en ``%ProgramFiles%`` y el de 32 bits
	(hasta 2025.x) en ``%ProgramFiles(x86)%``: si en este equipo hay un NVDA
	instalado en una de las dos, se usa esa (lo normal es que los dos equipos
	tengan la misma versión); si no, ``%ProgramFiles%``. Un NVDA instalado en
	otra carpeta o portable no encontrará el sonido (manual, apartado 19.11).
	"""
	nvda = cues.TIRESIAS_TO_NVDA.get(soundName)
	if not nvda:
		return ""
	return os.path.join(_nvdaWavesDir(), nvda + ".wav")


@functools.lru_cache(maxsize=1)
def _nvdaWavesDir() -> str:
	"""Carpeta ``waves`` de NVDA (se calcula una vez: no se mira el disco en cada sonido)."""
	candidates = [os.environ.get("ProgramFiles") or r"C:\Program Files"]
	x86 = os.environ.get("ProgramFiles(x86)")
	if x86 and x86 not in candidates:
		candidates.append(x86)
	dirs = [os.path.join(base, "NVDA", "waves") for base in candidates]
	for d in dirs:
		if os.path.isdir(d):
			return d
	return dirs[0]


def muteOnLocalControl() -> bool:
	try:
		return bool(conf["remote"]["muteOnLocalControl"])
	except KeyError:
		return False


def conf_beepPitch() -> int:
	"""Tono del modo de voz «pitidos» (opción de voz)."""
	from ..config import conf

	try:
		return int(conf["speech"]["beepSpeechModePitch"])
	except (KeyError, TypeError, ValueError):
		return 800
