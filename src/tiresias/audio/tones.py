"""Generación de pitidos y sonidos sintetizados (y temas de sonido).

Todos los sonidos se generan en memoria (no hacen falta archivos). Si el
usuario coloca un archivo ``.wav`` con el mismo nombre en ``data/sounds`` (o
en una subcarpeta de tema, ``data/sounds/<tema>``), se reproducirá en su
lugar. :func:`exportTheme` escribe el tema generado como archivos ``.wav``
para usarlo como punto de partida de un tema propio.

Cada sonido puede reproducirse panoramizado (``pan`` entre -1, izquierda, y
1, derecha): lo usan los sonidos de controles con audio posicional.
"""

from __future__ import annotations

import array
import math
import os
import random
import threading
import wave
from functools import lru_cache

from .. import paths
from ..extension_points import Action
from ..log import getLogger
from .wave_player import WavePlayer, _applyGains

log = getLogger("tones")

#: Antes de cada pitido: ``hz``, ``length``, ``left``, ``right`` (lo usa el acceso remoto).
pre_beep = Action()
#: Antes de cada sonido: ``name`` (sonido con nombre o ``""``) y ``fileName`` (ruta .wav o ``""``).
pre_playSound = Action()

SAMPLE_RATE = 44100
_player: WavePlayer | None = None
_lock = threading.Lock()

#: Timbres de los sonidos generados.
TIMBRES = ("soft", "pure", "pluck", "bell", "square", "click")


def _getPlayer() -> WavePlayer:
	global _player
	with _lock:
		if _player is None:
			_player = WavePlayer(SAMPLE_RATE, 2, name="tones", keepAwake=False)
		return _player


#: Quién ha silenciado los pitidos y sonidos locales (p. ej., ``"rdp"`` mientras
#: el equipo cliente de Escritorio remoto los recibe). Los avisos ``pre_beep``
#: y ``pre_playSound`` se siguen enviando.
_mutedBy: set[str] = set()


def setMuted(owner: str, state: bool) -> None:
	"""Silencia (o no) los pitidos y sonidos de este equipo en nombre de ``owner``."""
	if state:
		_mutedBy.add(owner)
	else:
		_mutedBy.discard(owner)


def isMuted() -> bool:
	return bool(_mutedBy)


def _soundVolume() -> float:
	if _mutedBy:
		return 0.0
	try:
		from ..config import conf

		if not conf["audio"]["playSounds"]:
			return 0.0
		if conf["audio"]["soundVolumeFollowsVoice"]:
			from .. import synth

			s = synth.getSynth()
			vol = s.getSetting("volume") if s is not None else None
			if vol is not None:
				return max(0, min(100, int(vol))) / 100.0
		return conf["audio"]["soundVolume"] / 100.0
	except Exception:
		return 1.0


def panGains(pan: float | None) -> tuple[float, float]:
	"""Ganancias (izquierda, derecha) de potencia constante para ``pan`` en [-1, 1]."""
	if pan is None:
		return (1.0, 1.0)
	pan = max(-1.0, min(1.0, float(pan)))
	angle = (pan + 1.0) * math.pi / 4.0
	# Normalizado para que en el centro las dos ganancias valgan 1.
	return (math.cos(angle) * math.sqrt(2.0), math.sin(angle) * math.sqrt(2.0))


#: Retraso máximo de pitidos y sonidos (s). Si al encolar uno hay más audio
#: pendiente, lo anterior se descarta: los pitidos de una barra de progreso o
#: los sonidos de una lista recorrida deprisa no se acumulan para sonar
#: segundos o minutos después (NVDA interrumpe cada pitido con el siguiente).
MAX_BACKLOG_SECONDS = 0.6
#: Duración máxima de las notas que se guardan en caché (ms): una nota de 5 s
#: ocupa casi 1 MB y la caché de 512 notas podía llegar a cientos de MB.
CACHE_MAX_MS = 400
#: Límites de un pitido (ms).
MAX_BEEP_MS = 10000


def _trimBacklog(player: WavePlayer) -> None:
	try:
		if player.queuedSeconds() > MAX_BACKLOG_SECONDS:
			player.stop()
	except Exception:
		pass


def _genNote(hz: float, ms: int, left: int, right: int, timbre: str = "soft") -> bytes:
	"""Nota estéreo con envolvente (las cortas, en caché)."""
	if ms <= CACHE_MAX_MS:
		return _genNoteCached(hz, ms, left, right, timbre)
	return _genNoteRaw(hz, ms, left, right, timbre)


@lru_cache(maxsize=512)
def _genNoteCached(hz: float, ms: int, left: int, right: int, timbre: str = "soft") -> bytes:
	return _genNoteRaw(hz, ms, left, right, timbre)


def _genNoteRaw(hz: float, ms: int, left: int, right: int, timbre: str = "soft") -> bytes:
	"""Nota estéreo con envolvente para evitar chasquidos."""
	n = int(SAMPLE_RATE * ms / 1000)
	if n <= 0:
		return b""
	samples = array.array("h", bytes(n * 4))
	w = 2 * math.pi * hz / SAMPLE_RATE
	ampL = 0.55 * 32767 * (left / 100.0) / 1.35
	ampR = 0.55 * 32767 * (right / 100.0) / 1.35
	attack = min(n // 4, int(SAMPLE_RATE * 0.004))
	release = min(n // 3, int(SAMPLE_RATE * 0.012))
	rnd = random.Random(int(hz * 10) + ms)
	for i in range(n):
		env = 1.0
		if i < attack:
			env = i / attack
		elif i > n - release:
			env = (n - i) / release
		if timbre == "pure":
			v = math.sin(w * i) * 1.2
		elif timbre == "pluck":
			v = math.exp(-5.0 * i / n) * (math.sin(w * i) + 0.5 * math.sin(2 * w * i) + 0.25 * math.sin(3 * w * i))
		elif timbre == "bell":
			v = math.exp(-3.5 * i / n) * (math.sin(w * i) + 0.6 * math.sin(2.76 * w * i) + 0.3 * math.sin(5.4 * w * i))
		elif timbre == "square":
			v = 0.8 * (math.sin(w * i) + math.sin(3 * w * i) / 3 + math.sin(5 * w * i) / 5)
		elif timbre == "click":
			v = math.exp(-12.0 * i / n) * (rnd.uniform(-0.6, 0.6) + math.sin(w * i))
		else:  # soft
			v = math.sin(w * i) + 0.25 * math.sin(2 * w * i) + 0.1 * math.sin(3 * w * i)
		v *= env
		samples[2 * i] = max(-32768, min(32767, int(ampL * v)))
		samples[2 * i + 1] = max(-32768, min(32767, int(ampR * v)))
	return samples.tobytes()


def _genTone(hz: float, ms: int, left: int, right: int) -> bytes:
	"""Tono estéreo con armónicos suaves (compatibilidad)."""
	return _genNote(hz, ms, left, right, "soft")


def beep(hz: float, ms: int, left: int = 50, right: int = 50, interrupt: bool = False) -> None:
	"""Emite un pitido. ``left``/``right`` son volúmenes 0-100 de cada canal."""
	if len(pre_beep):
		pre_beep.notify(hz=hz, length=ms, left=left, right=right)
	vol = _soundVolume()
	if vol <= 0:
		return
	try:
		hz = float(hz)
		ms = float(ms)
		left = float(left)
		right = float(right)
	except (TypeError, ValueError):
		return
	if not all(math.isfinite(v) for v in (hz, ms, left, right)):
		return
	hz = max(20.0, min(20000.0, hz))
	ms = int(max(0, min(MAX_BEEP_MS, ms)))
	data = _genTone(round(hz, 1), ms, int(max(0, min(100, left))), int(max(0, min(100, right))))
	if not data:
		return
	p = _getPlayer()
	if interrupt:
		p.stop()
	else:
		_trimBacklog(p)
	p.volume = vol
	p.feed(data)


def _silence(ms: int) -> bytes:
	try:
		ms = float(ms)
	except (TypeError, ValueError):
		return b""
	if not math.isfinite(ms) or ms <= 0:
		return b""
	return bytes(int(SAMPLE_RATE * min(ms, MAX_BEEP_MS) / 1000) * 4)


Note = tuple  # (hz, ms) o (hz, ms, timbre); hz <= 0 es silencio


def _sequence(notes: list, gapMs: int = 0, volume: int = 50, pan: float | None = None, timbre: str = "soft") -> bytes:
	gl, gr = panGains(pan)
	left = max(0, min(100, int(round(volume * gl))))
	right = max(0, min(100, int(round(volume * gr))))
	out = bytearray()
	for note in notes:
		hz, ms = note[0], note[1]
		t = note[2] if len(note) > 2 else timbre
		out += _silence(ms) if hz <= 0 else _genNote(float(hz), int(ms), left, right, t)
		if gapMs:
			out += _silence(gapMs)
	return bytes(out)


# Sonidos con nombre (equivalentes a los "earcons" de otros lectores).
_SOUND_RECIPES: dict[str, list] = {
	"start": [(523.25, 70), (659.25, 70), (783.99, 70), (1046.5, 140)],
	"exit": [(1046.5, 70), (783.99, 70), (659.25, 70), (523.25, 140)],
	"browseMode": [(880, 40), (660, 60)],
	"focusMode": [(660, 40), (880, 60)],
	"error": [(220, 90), (0, 30), (220, 120)],
	"textError": [(1200, 25), (900, 25)],
	"notification": [(988, 50), (1319, 80)],
	"link": [(1500, 18)],
	"clickable": [(1100, 15)],
	"boundary": [(180, 40)],
	# Límites con dirección (#13612, #4285): principio grave descendente, final grave ascendente.
	"boundaryStart": [(240, 30), (170, 40)],
	"boundaryEnd": [(170, 30), (240, 40)],
	"wrap": [(700, 30), (500, 30)],
	"suggestion": [(1400, 30), (1700, 30)],
	"recording": [(600, 60)],
	"screenCurtainOn": [(300, 80), (200, 120)],
	"screenCurtainOff": [(200, 80), (300, 120)],
	"profileSwitch": [(700, 40), (900, 40)],
	"copy": [(1600, 25), (2000, 25)],
	"enterContainer": [(450, 25)],
	"exitContainer": [(350, 25)],
	"newMessage": [(1175, 60), (1568, 90)],
	# Mezclador: micrófono y volumen.
	"micMuted": [(660, 60, "bell"), (440, 110, "bell")],
	"micUnmuted": [(440, 60, "bell"), (660, 110, "bell")],
	"volumeChange": [(1000, 30, "pure")],
	"muted": [(400, 70, "square"), (300, 90, "square")],
	"unmuted": [(300, 70, "square"), (400, 90, "square")],
	"deviceChange": [(784, 45, "pluck"), (988, 45, "pluck"), (1175, 70, "pluck")],
}

#: Descripción legible de cada sonido para la interfaz (los complementos pueden ampliarla).
SOUND_DESCRIPTIONS: dict[str, str] = {}


def _wavFileFor(name: str) -> str | None:
	try:
		from ..config import conf

		theme = conf["audio"]["soundTheme"]
	except Exception:
		theme = "default"
	for folder in (os.path.join(paths.soundsDir(), theme), paths.soundsDir()):
		path = os.path.join(folder, name + ".wav")
		if os.path.isfile(path):
			return path
	return None


@lru_cache(maxsize=64)
def _loadWav(path: str, mtime: float) -> tuple[bytes, int, int]:
	with wave.open(path, "rb") as w:
		if w.getsampwidth() != 2:
			raise ValueError("Solo WAV de 16 bits")
		if w.getnchannels() not in (1, 2):
			# Con 3 o más canales el reproductor desparejaba los canales (y
			# podía caerse su hilo): solo mono o estéreo.
			raise ValueError("Solo WAV mono o estéreo")
		rate = w.getframerate()
		if not 4000 <= rate <= 192000:
			raise ValueError("Frecuencia de muestreo no válida")
		return w.readframes(w.getnframes()), rate, w.getnchannels()


_wavPlayers: dict[tuple[int, int], WavePlayer] = {}
_wavLock = threading.Lock()


def playWaveFile(path: str) -> None:
	"""Reproduce un archivo WAV de 16 bits (sin esperar a que termine)."""
	if len(pre_playSound):
		pre_playSound.notify(name="", fileName=path)
	_playWaveFile(path)


def _playWaveFile(path: str, pan: float | None = None) -> None:
	vol = _soundVolume()
	if vol <= 0:
		return
	try:
		data, rate, channels = _loadWav(path, os.path.getmtime(path))
	except Exception:
		log.exception("No se pudo reproducir %s", path)
		return
	if pan is not None:
		data = _applyGains(data, channels, 1.0, panGains(pan))
		channels = 2
	key = (rate, channels)
	with _wavLock:
		player = _wavPlayers.get(key)
		if player is None:
			player = _wavPlayers[key] = WavePlayer(rate, channels, name=f"wav{rate}", keepAwake=False)
	_trimBacklog(player)
	player.volume = vol
	player.feed(data)


def playSound(name: str, pan: float | None = None) -> None:
	"""Reproduce un sonido con nombre (``"browseMode"``, ``"error"``...).

	``pan``: posición estéreo entre -1 (izquierda) y 1 (derecha), o ``None``.
	"""
	path = _wavFileFor(name)
	if len(pre_playSound):
		pre_playSound.notify(name=name, fileName=path or "")
	if path:
		_playWaveFile(path, pan=pan)
		return
	recipe = _SOUND_RECIPES.get(name)
	if not recipe:
		log.debug("Sonido desconocido %s", name)
		return
	vol = _soundVolume()
	if vol <= 0:
		return
	data = _cachedSequence(name, None if pan is None else round(max(-1.0, min(1.0, pan)), 1))
	p = _getPlayer()
	_trimBacklog(p)
	p.volume = vol
	p.feed(data)


@lru_cache(maxsize=256)
def _cachedSequence(name: str, pan: float | None = None) -> bytes:
	return _sequence(_SOUND_RECIPES[name], volume=45, pan=pan)


def registerSound(name: str, notes: list, description: str = "") -> None:
	"""Permite a complementos registrar sonidos sintetizados propios.

	``notes`` es una lista de ``(hz, ms)`` o ``(hz, ms, timbre)``.
	"""
	_SOUND_RECIPES[name] = list(notes)
	if description:
		SOUND_DESCRIPTIONS[name] = description
	_cachedSequence.cache_clear()


def availableSounds() -> list[str]:
	return sorted(_SOUND_RECIPES)


def availableThemes() -> list[str]:
	"""Temas instalados: «default» (generado) y las subcarpetas de ``data/sounds``."""
	themes = ["default"]
	try:
		base = paths.soundsDir()
		for entry in sorted(os.listdir(base)):
			if entry != "default" and os.path.isdir(os.path.join(base, entry)):
				themes.append(entry)
	except OSError:
		pass
	return themes


def renderSound(name: str) -> bytes:
	"""PCM estéreo de 16 bits a 44,1 kHz del sonido generado ``name``."""
	return _sequence(_SOUND_RECIPES[name], volume=45)


def exportTheme(folder: str, names: list[str] | None = None, overwrite: bool = False) -> int:
	"""Escribe los sonidos generados como ``.wav`` en ``folder``. Devuelve cuántos se escribieron."""
	os.makedirs(folder, exist_ok=True)
	count = 0
	for name in names or availableSounds():
		if name not in _SOUND_RECIPES:
			continue
		path = os.path.join(folder, name + ".wav")
		if os.path.exists(path) and not overwrite:
			continue
		with wave.open(path, "wb") as w:
			w.setnchannels(2)
			w.setsampwidth(2)
			w.setframerate(SAMPLE_RATE)
			w.writeframes(renderSound(name))
		count += 1
	return count


def stopAll() -> None:
	if _player:
		_player.stop()
	for p in _wavPlayers.values():
		p.stop()


def terminate() -> None:
	global _player
	if _player:
		_player.terminate()
		_player = None
	with _wavLock:
		players = list(_wavPlayers.values())
		_wavPlayers.clear()
	for p in players:
		p.terminate()
