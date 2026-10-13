"""Exportar texto a un archivo WAV con la voz actual.

El texto (selección, documento o portapapeles) se sintetiza en el hilo del
propio sintetizador con ``_synthesizeSegment``, sin pasar por la tarjeta de
sonido, y se guarda como PCM de 16 bits con la frecuencia de la voz.
"""

from __future__ import annotations

import os
import threading
import time
import wave

from . import api, queue_handler, speech, textinfo
from .i18n import _
from .log import getLogger

log = getLogger("audioExport")


class ExportError(Exception):
	pass


#: Reintentos de un trozo cuya síntesis cortó una cancelación de la voz.
MAX_PIECE_RETRIES = 5


def renderPcm(text: str, synthDriver=None, timeout: float = 120.0, progress=None) -> tuple[bytes, int, int]:
	"""Sintetiza ``text`` y devuelve (pcm, frecuencia, canales). Bloquea: usar en un hilo.

	Cada trozo (unos 400 caracteres) es un trabajo aparte en el hilo del
	sintetizador, así lo que el lector tenga que decir mientras tanto se
	intercala entre trozos y el usuario no se queda sin voz durante una
	exportación larga. Si la voz se cancela (una tecla, un cambio de foco)
	en mitad de un trozo, ese trozo se repite para que el archivo no salga
	cortado. ``timeout`` es el tiempo máximo sin avanzar ningún trozo.
	"""
	from . import synth as synthModule
	from .synth.base import AudioSynthDriver, splitLongText

	drv = synthDriver or synthModule.getSynth()
	if drv is None or not isinstance(drv, AudioSynthDriver) or not hasattr(drv, "runInWorker"):
		raise ExportError(_("La voz actual no permite guardar el audio"))
	chunks: list[bytes] = []
	done = threading.Event()
	errors: list[BaseException] = []
	cancelled = [False]
	pieces = [p for p in splitLongText(text, 400) if p.strip()]
	state = {"next": 0, "progressAt": time.monotonic()}

	def job() -> None:
		i = state["next"]
		try:
			if cancelled[0] or i >= len(pieces):
				return
			for _attempt in range(MAX_PIECE_RETRIES + 1):
				gen = getattr(drv, "_generation", 0)
				buf: list[bytes] = []
				drv._synthesizeSegment([pieces[i]], buf.append, lambda: cancelled[0])
				if cancelled[0] or getattr(drv, "_generation", 0) == gen:
					break
				# Una cancelación de la voz cortó este trozo: se vuelve a generar.
			chunks.extend(buf)
			state["next"] = i + 1
			state["progressAt"] = time.monotonic()
			if progress is not None:
				progress(i + 1, len(pieces))
		except BaseException as e:  # se informa en el hilo que espera
			errors.append(e)
			done.set()
			return
		if state["next"] >= len(pieces) or cancelled[0]:
			done.set()
		else:
			drv.runInWorker(job)

	if not pieces:
		return b"", int(drv.sampleRate), int(getattr(drv, "channels", 1))
	drv.runInWorker(job)
	while not done.wait(0.25):
		worker = getattr(drv, "_worker", None)
		if worker is not None and getattr(drv, "_workerStarted", False) and not worker.is_alive():
			# Se cambió de voz o se cerró el sintetizador a mitad de la exportación.
			cancelled[0] = True
			raise ExportError(_("la voz se cerró antes de terminar"))
		if time.monotonic() - state["progressAt"] > timeout:
			cancelled[0] = True
			raise ExportError(_("La voz tardó demasiado en generar el audio"))
	if errors:
		raise ExportError(str(errors[0]))
	return b"".join(chunks), int(drv.sampleRate), int(getattr(drv, "channels", 1))


def writeWav(path: str, pcm: bytes, rate: int, channels: int = 1) -> None:
	with wave.open(path, "wb") as w:
		w.setnchannels(channels)
		w.setsampwidth(2)
		w.setframerate(rate)
		w.writeframes(pcm)


def exportText(text: str, path: str) -> None:
	"""Exporta en un hilo y avisa al terminar."""
	speech.speakMessage(_("Generando el audio"))
	lastReport = [0]

	def progress(i: int, total: int) -> None:
		pct = i * 100 // max(1, total)
		if total > 10 and pct - lastReport[0] >= 25:
			lastReport[0] = pct
			queue_handler.queueFunction(speech.speakMessage, _("{pct} por ciento").format(pct=pct))

	def worker() -> None:
		try:
			pcm, rate, channels = renderPcm(text, progress=progress)
			writeWav(path, pcm, rate, channels)
		except (ExportError, OSError) as e:
			queue_handler.queueFunction(speech.speakMessage, _("No se pudo guardar el audio: {err}").format(err=e))
			return
		except Exception as e:
			log.exception("Error exportando audio")
			queue_handler.queueFunction(speech.speakMessage, _("No se pudo guardar el audio: {err}").format(err=e))
			return
		secs = len(pcm) // (2 * channels * rate) if rate else 0
		queue_handler.queueFunction(speech.speakMessage, _("Audio guardado: {name}, {secs} segundos").format(name=os.path.basename(path), secs=secs))

	threading.Thread(target=worker, name="ExportarWAV", daemon=True).start()


def _textFor(source: str) -> str:
	from . import winapi

	if source == "clipboard":
		return winapi.getClipboardText() or ""
	obj = api.getCaretObject()
	if obj is None:
		return ""
	try:
		if source == "selection":
			info = obj.makeTextInfo(textinfo.POSITION_SELECTION)
			return "" if info.isCollapsed else info.text
		return obj.makeTextInfo(textinfo.POSITION_ALL).text
	except Exception:
		return ""


SOURCES = {"selection": _("el texto seleccionado"), "document": _("el documento"), "clipboard": _("el texto del portapapeles")}


def exportDialog(source: str) -> None:
	"""Pide dónde guardar y exporta (llamar en el hilo del núcleo)."""
	text = _textFor(source)
	if not text.strip():
		speech.speakMessage(_("No hay texto: {what} está vacío").format(what=SOURCES[source]))
		return
	from .gui import helpers

	def ask() -> None:
		import wx

		with wx.FileDialog(None, _("Guardar {what} como audio").format(what=SOURCES[source]), defaultFile="tiresias.wav", wildcard=_("Audio WAV") + " (*.wav)|*.wav", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() == wx.ID_OK:
				path = dlg.GetPath()
				if not path.lower().endswith(".wav"):
					path += ".wav"
				queue_handler.queueFunction(exportText, text, path)

	helpers.runOnGui(ask)
