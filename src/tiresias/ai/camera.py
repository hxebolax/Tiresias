"""«Cara a la vista»: comprobar el encuadre de la cámara antes de una videollamada.

Hace fotos con la cámara (``Windows.Media.Capture``), busca caras con
``Windows.Media.FaceAnalysis`` (en el propio equipo, sin enviar nada a
Internet) y da indicaciones habladas: si la cara está centrada, si está
cerca o lejos y si hay poca luz o contraluz. Repite la comprobación cada
pocos segundos y solo habla cuando cambia la indicación; se detiene sola o
con la misma orden.
"""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass

from .. import imaging, queue_handler, speech
from ..i18n import _
from ..log import getLogger

log = getLogger("ai.camera")

INTERVAL = 2.0
DURATION = 60.0


@dataclass
class Frame:
	width: int
	height: int
	#: Caras: (x, y, ancho, alto) en píxeles.
	faces: list[tuple[int, int, int, int]]
	#: Luminancia media de la imagen y de la zona de la cara (0-255).
	meanLuma: float
	faceLuma: float | None = None


def analyzeFrame(frame: Frame) -> list[str]:
	"""Indicaciones para mejorar el encuadre (lista vacía no se da nunca)."""
	hints: list[str] = []
	if frame.meanLuma < 35:
		return [_("La imagen está casi negra: comprueba que la cámara no esté tapada y enciende una luz.")]
	if not frame.faces:
		return [_("No se ve ninguna cara. Ponte delante de la cámara.")]
	if len(frame.faces) > 1:
		hints.append(_("Se ven {n} caras.").format(n=len(frame.faces)))
	x, y, w, h = max(frame.faces, key=lambda f: f[2] * f[3])
	cx = (x + w / 2) / frame.width
	cy = (y + h / 2) / frame.height
	# La imagen de la cámara no está en espejo: la izquierda de la imagen es tu derecha.
	if cx < 0.38:
		hints.append(_("Muévete un poco a tu izquierda."))
	elif cx > 0.62:
		hints.append(_("Muévete un poco a tu derecha."))
	if cy < 0.3:
		hints.append(_("Tu cara está muy arriba: inclina la cámara un poco hacia arriba o baja el asiento."))
	elif cy > 0.62:
		hints.append(_("Tu cara está muy abajo: inclina la cámara un poco hacia abajo o sube el asiento."))
	size = h / frame.height
	if size < 0.18:
		hints.append(_("Estás lejos: acércate a la cámara."))
	elif size > 0.6:
		hints.append(_("Estás demasiado cerca: aléjate un poco."))
	if frame.meanLuma < 70:
		hints.append(_("Hay poca luz."))
	elif frame.meanLuma > 225:
		hints.append(_("Hay demasiada luz."))
	if frame.faceLuma is not None and frame.faceLuma < frame.meanLuma - 45:
		hints.append(_("Hay contraluz: la luz te llega por detrás."))
	if not hints:
		hints.append(_("Bien: la cara está centrada, a buena distancia y con buena luz."))
	return hints


async def _captureFrame(mc) -> Frame:
	from winrt.windows.graphics.imaging import BitmapDecoder, BitmapPixelFormat, SoftwareBitmap
	from winrt.windows.media.faceanalysis import FaceDetector
	from winrt.windows.media.mediaproperties import ImageEncodingProperties
	from winrt.windows.storage.streams import InMemoryRandomAccessStream

	stream = InMemoryRandomAccessStream()
	await mc.capture_photo_to_stream_async(ImageEncodingProperties.create_bmp(), stream)
	stream.seek(0)
	dec = await BitmapDecoder.create_async(stream)
	sb = await dec.get_software_bitmap_async()
	img = await imaging._softwareBitmapToImage(sb)
	stream.close()
	gray = SoftwareBitmap.convert(sb, BitmapPixelFormat.GRAY8) if sb.bitmap_pixel_format != BitmapPixelFormat.GRAY8 else sb
	det = await FaceDetector.create_async()
	faces = await det.detect_faces_async(gray)
	boxes = [(int(f.face_box.x), int(f.face_box.y), int(f.face_box.width), int(f.face_box.height)) for f in faces]
	lum = imaging.toGray(img)
	mean = imaging.meanLuma(lum, img.width)
	faceL = None
	if boxes:
		faceL = imaging.meanLuma(lum, img.width, max(boxes, key=lambda b: b[2] * b[3]))
	return Frame(img.width, img.height, boxes, mean, faceL)


class FaceCheck:
	def __init__(self) -> None:
		self.running = False
		self._stop = threading.Event()

	def toggle(self) -> None:
		if self.running and self._stop.is_set():
			# La anterior aún está cerrando la cámara (acaba la foto en curso).
			speech.speakMessage(_("La comprobación de la cámara se está deteniendo. Espera un momento y vuelve a intentarlo."))
			return
		if self.running:
			self._stop.set()
			speech.speakMessage(_("Comprobación de la cámara detenida"))
			return
		self.running = True
		self._stop.clear()
		speech.speakMessage(_("Comprobando la cámara. Vuelve a pulsar la orden para terminar."))
		threading.Thread(target=self._run, name="CaraALaVista", daemon=True).start()

	def _run(self) -> None:
		try:
			asyncio.run(self._loop())
		except Exception as e:
			log.exception("Error con la cámara")
			queue_handler.queueFunction(speech.speakMessage, _("No se pudo usar la cámara: {err}. Comprueba en Configuración de Windows, Privacidad, Cámara, que las aplicaciones de escritorio pueden usarla.").format(err=e))
		finally:
			self.running = False

	async def _loop(self) -> None:
		from winrt.windows.media.capture import MediaCapture, MediaCaptureInitializationSettings, StreamingCaptureMode

		settings = MediaCaptureInitializationSettings()
		settings.streaming_capture_mode = StreamingCaptureMode.VIDEO
		mc = MediaCapture()
		await mc.initialize_async(settings)
		try:
			last: list[str] = []
			end = time.monotonic() + DURATION
			while not self._stop.is_set() and time.monotonic() < end:
				frame = await _captureFrame(mc)
				hints = analyzeFrame(frame)
				if hints != last:
					last = hints
					queue_handler.queueFunction(speech.speakMessage, " ".join(hints))
				await asyncio.sleep(INTERVAL)
			if not self._stop.is_set():
				queue_handler.queueFunction(speech.speakMessage, _("Fin de la comprobación de la cámara"))
		finally:
			mc.close()


faceCheck = FaceCheck()
