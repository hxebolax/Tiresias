"""Reconocimiento óptico de caracteres (OCR).

Motores:

- **Windows OCR** (``Windows.Media.Ocr``): siempre disponible si Windows tiene
  instalado algún idioma de reconocimiento.
- **Tesseract**: si está instalado en el sistema (``tesseract.exe`` en el PATH,
  en «Archivos de programa» o en la ruta indicada en las opciones).

Orígenes: objeto navegador, ventana en primer plano, pantalla completa,
archivo de imagen, PDF (cada página se dibuja con ``Windows.Data.Pdf``) y
portapapeles (imagen copiada o archivo copiado).

El resultado se abre como un documento navegable (``OcrDocument``) con modo
exploración y cursor de revisión. Con Intro se hace clic en la palabra.

Modo continuo (subtítulos): reconoce periódicamente la misma zona y solo lee
las líneas nuevas, comparándolas de forma aproximada para que el ruido del
OCR no repita la misma frase.
"""

from __future__ import annotations

import asyncio
import difflib
import os
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from typing import Callable

from . import api, imaging, queue_handler, speech
from .config import conf, registerDefaults
from .i18n import _
from .imaging import Image
from .log import getLogger

log = getLogger("ocr")

registerDefaults(
	"ocr",
	{
		"language": "",
		"autoRefresh": False,
		"autoRefreshInterval": 1500,
		"autoSayAll": False,
		#: Motor: "windows" o "tesseract".
		"engine": "windows",
		"tesseractLanguage": "spa",
		"tesseractPath": "",
		#: Modo continuo: intervalo (ms) y parecido mínimo (%) para considerar repetida una línea.
		"continuousInterval": 1000,
		"continuousSimilarity": 80,
		#: Resolución con que se dibujan las páginas de los PDF (multiplicador).
		"pdfScale": 2,
		#: Máximo de páginas de un PDF (0: todas).
		"pdfMaxPages": 0,
		#: El resultado se abre en modo exploración (si no, en modo foco sobre el texto).
		"browseModeResult": True,
	},
)

# Compatibilidad: otros módulos importaban estas funciones desde aquí.
captureScreen = imaging.captureScreen
captureWindowRect = imaging.captureWindowRect


@dataclass
class OcrWord:
	text: str
	x: int
	y: int
	w: int
	h: int


@dataclass
class OcrLine:
	words: list[OcrWord]
	#: Número de página (1, 2...) en los PDF; ``None`` en el resto.
	page: int | None = None

	@property
	def text(self) -> str:
		return " ".join(w.text for w in self.words)


@dataclass
class OcrResult:
	lines: list[OcrLine] = field(default_factory=list)
	title: str = ""
	#: Origen para volver a reconocer: ("rect", rect, hwnd), ("file", ruta) o ("clipboard",).
	source: tuple = ()

	@property
	def text(self) -> str:
		return "\n".join(line.text for line in self.lines)


class OcrError(Exception):
	pass


# ====================================================================== motores
class OcrEngine:
	id = ""
	name = ""

	def isAvailable(self) -> bool:
		return False

	def languages(self) -> list[str]:
		return []

	def getLanguage(self) -> str:
		return ""

	def setLanguage(self, lang: str) -> None:
		pass

	def recognize(self, img: Image) -> list[OcrLine]:
		"""Reconoce una imagen (en un hilo de trabajo). Coordenadas de pantalla."""
		raise NotImplementedError


class WindowsOcrEngine(OcrEngine):
	id = "windows"
	name = _("OCR de Windows")

	def isAvailable(self) -> bool:
		return bool(self.languages())

	def languages(self) -> list[str]:
		try:
			from winrt.windows.media.ocr import OcrEngine as _E

			return [lang.language_tag for lang in _E.available_recognizer_languages]
		except Exception:
			return []

	def getLanguage(self) -> str:
		return conf["ocr"]["language"]

	def setLanguage(self, lang: str) -> None:
		conf["ocr"]["language"] = lang

	@staticmethod
	async def _recognize(data: bytes, w: int, h: int, language: str):
		from winrt.windows.globalization import Language
		from winrt.windows.graphics.imaging import BitmapPixelFormat, SoftwareBitmap
		from winrt.windows.media.ocr import OcrEngine as _E
		from winrt.windows.storage.streams import DataWriter

		writer = DataWriter()
		writer.write_bytes(data)
		buf = writer.detach_buffer()
		bmp = SoftwareBitmap.create_copy_from_buffer(buf, BitmapPixelFormat.BGRA8, w, h)
		engine = None
		if language:
			try:
				engine = _E.try_create_from_language(Language(language))
			except Exception:
				engine = None
		if engine is None:
			engine = _E.try_create_from_user_profile_languages()
		if engine is None:
			raise OcrError(_("No hay idiomas de reconocimiento instalados en Windows"))
		return await engine.recognize_async(bmp)

	def recognize(self, img: Image) -> list[OcrLine]:
		from winrt.windows.media.ocr import OcrEngine as _E

		maxDim = int(getattr(_E, "max_image_dimension", 10000) or 10000)
		if max(img.width, img.height) > maxDim:
			small = imaging.scaleDown(img, maxDim)
			factor = img.width / small.width
			lines = self._recognizeScaled(small.data, small.width, small.height, 1 / factor)
		else:
			scale = 1
			data = img.data
			if img.width * img.height < 900_000 and max(img.width, img.height) * 2 <= maxDim:
				data = imaging.scale2x(data, img.width, img.height)
				scale = 2
			lines = self._recognizeScaled(data, img.width * scale, img.height * scale, scale)
		for line in lines:
			for wd in line.words:
				wd.x += img.left
				wd.y += img.top
		return lines

	def _recognizeScaled(self, data: bytes, w: int, h: int, scale: float) -> list[OcrLine]:
		result = asyncio.run(self._recognize(data, w, h, self.getLanguage()))
		lines: list[OcrLine] = []
		for line in result.lines:
			words = []
			for word in line.words:
				r = word.bounding_rect
				words.append(OcrWord(word.text, int(r.x / scale), int(r.y / scale), max(1, int(r.width / scale)), max(1, int(r.height / scale))))
			if words:
				lines.append(OcrLine(words))
		return lines


#: Códigos ISO 639-1 -> códigos de Tesseract más habituales.
TESSERACT_CODES = {
	"es": "spa",
	"en": "eng",
	"fr": "fra",
	"de": "deu",
	"it": "ita",
	"pt": "por",
	"ca": "cat",
	"gl": "glg",
	"eu": "eus",
	"nl": "nld",
	"ru": "rus",
	"zh": "chi_sim",
	"ja": "jpn",
	"ar": "ara",
}


class TesseractEngine(OcrEngine):
	id = "tesseract"
	name = _("Tesseract")

	def __init__(self) -> None:
		self._langCache: tuple[str, list[str]] | None = None

	def executable(self) -> str | None:
		configured = str(conf["ocr"]["tesseractPath"] or "").strip().strip('"')
		candidates = []
		if configured:
			candidates.append(configured if configured.lower().endswith(".exe") else os.path.join(configured, "tesseract.exe"))
		# Solo carpetas absolutas del PATH: shutil.which mira también la carpeta
		# actual, donde cualquiera podría dejar un «tesseract.exe».
		for folder in os.environ.get("PATH", "").split(os.pathsep):
			folder = folder.strip().strip('"')
			if folder and os.path.isabs(folder):
				candidates.append(os.path.join(folder, "tesseract.exe"))
		for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"), os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs")):
			if base:
				candidates.append(os.path.join(base, "Tesseract-OCR", "tesseract.exe"))
		for c in candidates:
			if c and os.path.isfile(c):
				return c
		return None

	def isAvailable(self) -> bool:
		return self.executable() is not None

	@staticmethod
	def _run(args: list[str], timeout: float = 120) -> str:
		flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
		proc = subprocess.run(args, capture_output=True, timeout=timeout, creationflags=flags)
		if proc.returncode != 0:
			raise OcrError(proc.stderr.decode("utf-8", "replace").strip() or _("Tesseract terminó con un error"))
		return proc.stdout.decode("utf-8", "replace")

	def languages(self) -> list[str]:
		exe = self.executable()
		if not exe:
			return []
		if self._langCache and self._langCache[0] == exe:
			return list(self._langCache[1])
		try:
			out = self._run([exe, "--list-langs"], timeout=20)
		except (OSError, OcrError, subprocess.TimeoutExpired):
			log.debug("No se pudieron obtener los idiomas de Tesseract", exc_info=True)
			return []
		langs = [ln.strip() for ln in out.splitlines()[1:] if ln.strip() and ln.strip() != "osd"]
		self._langCache = (exe, langs)
		return list(langs)

	def getLanguage(self) -> str:
		return conf["ocr"]["tesseractLanguage"] or "eng"

	def setLanguage(self, lang: str) -> None:
		conf["ocr"]["tesseractLanguage"] = lang

	def recognize(self, img: Image) -> list[OcrLine]:
		exe = self.executable()
		if not exe:
			raise OcrError(_("Tesseract no está instalado"))
		scale = 2 if img.width * img.height < 900_000 else 1
		work = Image(imaging.scale2x(img.data, img.width, img.height), img.width * 2, img.height * 2) if scale == 2 else img
		from . import paths

		os.makedirs(paths.tempDir(), exist_ok=True)
		fd, path = tempfile.mkstemp(suffix=".png", prefix="ocr_", dir=paths.tempDir())
		try:
			with os.fdopen(fd, "wb") as f:
				f.write(imaging.encodePng(work))
			tsv = self._run([exe, path, "stdout", "-l", self.getLanguage(), "tsv"])
		finally:
			try:
				os.remove(path)
			except OSError:
				pass
		return parseTesseractTsv(tsv, scale, img.left, img.top)


def parseTesseractTsv(tsv: str, scale: float = 1, offsetX: int = 0, offsetY: int = 0) -> list[OcrLine]:
	"""Convierte la salida TSV de Tesseract en líneas con palabras y posiciones."""
	lines: dict[tuple[int, int, int, int], list[OcrWord]] = {}
	order: list[tuple[int, int, int, int]] = []
	for row in tsv.splitlines()[1:]:
		cols = row.split("\t")
		if len(cols) < 12 or cols[0] != "5":
			continue
		text = cols[11].strip()
		if not text:
			continue
		try:
			conf_ = float(cols[10])
		except ValueError:
			conf_ = 0
		if conf_ < 0:
			continue
		key = (int(cols[1]), int(cols[2]), int(cols[3]), int(cols[4]))
		left, top, w, h = (int(c) for c in cols[6:10])
		if key not in lines:
			lines[key] = []
			order.append(key)
		lines[key].append(OcrWord(text, int(left / scale) + offsetX, int(top / scale) + offsetY, max(1, int(w / scale)), max(1, int(h / scale))))
	return [OcrLine(lines[k]) for k in order]


ENGINES: dict[str, OcrEngine] = {"windows": WindowsOcrEngine(), "tesseract": TesseractEngine()}


def getEngine() -> OcrEngine:
	"""Motor elegido; si no está disponible, el de Windows."""
	eng = ENGINES.get(conf["ocr"]["engine"])
	if eng is None or (eng.id != "windows" and not eng.isAvailable()):
		return ENGINES["windows"]
	return eng


def availableEngines() -> list[OcrEngine]:
	return [e for e in ENGINES.values() if e.id == "windows" or e.isAvailable()]


def availableLanguages() -> list[str]:
	"""Idiomas del OCR de Windows (compatibilidad con el panel de opciones)."""
	return ENGINES["windows"].languages()


def cycleLanguage() -> None:
	"""Pasa al siguiente idioma de reconocimiento del motor actual.

	La lista de idiomas de Tesseract se pide a ``tesseract --list-langs`` (un
	proceso que puede tardar hasta 20 s): se obtiene en un hilo propio para no
	bloquear el hilo del núcleo y el cambio se aplica después en él.
	"""
	eng = getEngine()
	if eng.id == "tesseract":

		def worker() -> None:
			langs = eng.languages()
			queue_handler.queueFunction(_applyNextLanguage, eng, langs)

		threading.Thread(target=worker, name="OCR-idiomas", daemon=True).start()
		return
	_applyNextLanguage(eng, eng.languages())


def _applyNextLanguage(eng: OcrEngine, langs: list[str]) -> None:
	langs = list(langs)
	if eng.id == "windows":
		langs = [""] + langs
	if len(langs) < 2:
		speech.speakMessage(_("Solo hay un idioma de reconocimiento disponible"))
		return
	cur = eng.getLanguage()
	i = langs.index(cur) if cur in langs else -1
	new = langs[(i + 1) % len(langs)]
	eng.setLanguage(new)
	speech.speakMessage(_("Idioma de reconocimiento: {lang}").format(lang=languageLabel(new)))


def languageLabel(tag: str) -> str:
	if not tag:
		return _("automático")
	try:
		from winrt.windows.globalization import Language

		return Language(tag).display_name
	except Exception:
		return tag


def cycleEngine() -> None:
	engines = availableEngines()
	if len(engines) < 2:
		speech.speakMessage(_("Solo está disponible el OCR de Windows. Instala Tesseract para tener otro motor."))
		return
	ids = [e.id for e in engines]
	cur = getEngine().id
	new = ids[(ids.index(cur) + 1) % len(ids)] if cur in ids else ids[0]
	conf["ocr"]["engine"] = new
	speech.speakMessage(_("Motor de reconocimiento: {name}").format(name=ENGINES[new].name))


# ====================================================================== reconocimiento
_lastResult: OcrResult | None = None


def lastResult() -> OcrResult | None:
	return _lastResult


def _runWorker(name: str, func: Callable[[], OcrResult | None], onDone: Callable[[OcrResult], None], quiet: bool = False) -> None:
	def worker() -> None:
		try:
			result = func()
		except Exception as e:
			log.exception("Error de OCR")
			if not quiet:
				msg = str(e) if isinstance(e, OcrError) else _("Error de reconocimiento: {err}").format(err=e)
				queue_handler.queueFunction(speech.speakMessage, msg)
			return
		if result is not None:
			queue_handler.queueFunction(onDone, result)

	threading.Thread(target=worker, name=name, daemon=True).start()


def recognizeImage(img: Image) -> list[OcrLine]:
	"""Reconoce una imagen con el motor actual (bloquea: usar en un hilo)."""
	if img.isBlank():
		return []
	return getEngine().recognize(img)


def _captureAndRecognize(rect: tuple[int, int, int, int], hwnd: int) -> list[OcrLine]:
	img = imaging.captureRect(rect, hwnd)
	return recognizeImage(img)


def recognizeRect(rect: tuple[int, int, int, int], title: str = "", hwnd: int = 0, refresh: bool = False) -> None:
	"""Reconoce una zona de la pantalla y muestra el resultado."""
	x, y, w, h = rect
	if w <= 0 or h <= 0:
		speech.speakMessage(_("El objeto no tiene un tamaño válido"))
		return
	if not refresh:
		speech.speakMessage(_("Reconociendo"))
	source = ("rect", tuple(rect), hwnd)

	def job() -> OcrResult:
		return OcrResult(_captureAndRecognize(rect, hwnd), title, source)

	_runWorker("OCR", job, lambda r: _showResult(r, refresh), quiet=refresh)


def _showResult(result: OcrResult, refresh: bool = False) -> None:
	global _lastResult
	from .gui import ocr_viewer

	if refresh:
		if not ocr_viewer.isOpen():
			return
		# Si mientras tanto se abrió otro resultado (un archivo, el portapapeles u
		# otra zona), este refresco ya no corresponde: se descarta.
		if _lastResult is None or _lastResult.source != result.source:
			return
		old = _lastResult.lines if _lastResult else []
		_lastResult = result
		ocr_viewer.update(result)
		new = newLines([ln.text for ln in old], [ln.text for ln in result.lines], conf["ocr"]["continuousSimilarity"] / 100.0)
		if new:
			speech.speakText("\n".join(new))
		_scheduleRefresh()
		return
	if not result.lines:
		speech.speakMessage(_("No se reconoció texto"))
		return
	_lastResult = result
	ocr_viewer.show(result)
	_scheduleRefresh()


# ---------------------------------------------------------------- refresco del visor
_refreshTimer: int | None = None


def _scheduleRefresh() -> None:
	global _refreshTimer
	if _refreshTimer is not None:
		queue_handler.cancelCallLater(_refreshTimer)
		_refreshTimer = None
	if conf["ocr"]["autoRefresh"] and _lastResult and _lastResult.source[:1] == ("rect",):
		# Mínimo de 250 ms, el mismo que admiten el panel de opciones y la validación.
		_refreshTimer = queue_handler.callLater(max(250, int(conf["ocr"]["autoRefreshInterval"])), _refresh)


def _cancelRefresh() -> None:
	global _refreshTimer
	if _refreshTimer is not None:
		queue_handler.cancelCallLater(_refreshTimer)
		_refreshTimer = None


def _refresh() -> None:
	global _refreshTimer
	_refreshTimer = None
	from .gui import ocr_viewer

	if not _lastResult or not ocr_viewer.isOpen() or not conf["ocr"]["autoRefresh"]:
		return
	# Solo se refrescan zonas de la pantalla: un archivo ("file", ruta) o el
	# portapapeles ("clipboard",) no cambian solos.
	if len(_lastResult.source) != 3 or _lastResult.source[0] != "rect":
		return
	_kind, rect, hwnd = _lastResult.source
	recognizeRect(rect, _lastResult.title, hwnd, refresh=True)


def toggleAutoRefresh() -> None:
	v = not conf["ocr"]["autoRefresh"]
	conf["ocr"]["autoRefresh"] = v
	speech.speakMessage(_("Actualización automática del reconocimiento activada") if v else _("Actualización automática del reconocimiento desactivada"))
	_scheduleRefresh()


def rerecognize() -> None:
	"""Vuelve a reconocer el origen del último resultado."""
	if not _lastResult or not _lastResult.source:
		speech.speakMessage(_("No hay nada que volver a reconocer"))
		return
	kind = _lastResult.source[0]
	if kind == "rect":
		_k, rect, hwnd = _lastResult.source
		recognizeRect(rect, _lastResult.title, hwnd)
	elif kind == "file":
		recognizeFile(_lastResult.source[1])
	elif kind == "clipboard":
		recognizeClipboard()


# ---------------------------------------------------------------- orígenes
def _navigatorRect():
	obj = api.getNavigatorObject()
	loc = obj.location if obj is not None else None
	if not loc:
		return None, None, 0
	from . import winapi

	hwnd = 0
	try:
		hwnd = winapi.getAncestor(obj.windowHandle, winapi.GA_ROOT) if obj.windowHandle else 0
	except Exception:
		hwnd = 0
	return obj, loc, hwnd


def recognizeNavigatorObject() -> None:
	obj, loc, hwnd = _navigatorRect()
	if not loc:
		speech.speakMessage(_("El objeto navegador no tiene ubicación en pantalla"))
		return
	recognizeRect(loc, obj.name or "", hwnd)


def recognizeForegroundWindow(title: str | None = None) -> None:
	from . import winapi

	hwnd = winapi.getForegroundWindow()
	if not hwnd:
		speech.speakMessage(_("No hay ventana en primer plano"))
		return
	rect = winapi.getWindowRect(hwnd)
	vx, vy, vw, vh = imaging.virtualScreenRect()
	# Se recorta a la pantalla visible (ventanas maximizadas sobresalen unos píxeles).
	x = max(rect[0], vx)
	y = max(rect[1], vy)
	r = min(rect[0] + rect[2], vx + vw)
	b = min(rect[1] + rect[3], vy + vh)
	if r <= x or b <= y:
		speech.speakMessage(_("La ventana no está en la pantalla"))
		return
	fg = api.getForegroundObject()
	name = title or (fg.name if fg is not None and fg.name else _("Ventana"))
	recognizeRect((x, y, r - x, b - y), name, hwnd)


def screenReview() -> None:
	"""Revisión de pantalla por OCR: la ventana activa como documento con posiciones.

	Sirve para lo que no expone accesibilidad (escritorio remoto, Citrix,
	aplicaciones GDI antiguas, juegos): se navega por líneas y palabras, se
	pregunta la posición y se hace clic sobre cualquier palabra.
	"""
	recognizeForegroundWindow(_("Revisión de pantalla por OCR"))


def recognizeScreen() -> None:
	recognizeRect(imaging.virtualScreenRect(), _("Pantalla completa"))


def _recognizePdf(path: str) -> OcrResult:
	lines: list[OcrLine] = []
	eng = getEngine()

	def onPage(i: int, total: int, img: Image) -> None:
		pageLines = eng.recognize(img)
		for ln in pageLines:
			ln.page = i + 1
		if not pageLines:
			lines.append(OcrLine([], page=i + 1))
		lines.extend(pageLines)
		if total > 1 and (i + 1) % 5 == 0:
			queue_handler.queueFunction(speech.speakMessage, _("Página {n} de {total}").format(n=i + 1, total=total))

	imaging.renderPdf(path, onPage, scale=float(conf["ocr"]["pdfScale"] or 2), maxPages=int(conf["ocr"]["pdfMaxPages"] or 0))
	return OcrResult(lines, os.path.basename(path), ("file", path))


def recognizeFile(path: str) -> None:
	"""Reconoce un archivo de imagen o un PDF."""
	if not path or not os.path.isfile(path):
		speech.speakMessage(_("No se encuentra el archivo"))
		return
	speech.speakMessage(_("Reconociendo {name}").format(name=os.path.basename(path)))

	def job() -> OcrResult:
		if path.lower().endswith(".pdf"):
			return _recognizePdf(path)
		img = imaging.loadImageFile(path)
		img.left = img.top = 0
		return OcrResult(recognizeImage(img), os.path.basename(path), ("file", path))

	_runWorker("OCR-archivo", job, _showFileResult)


def _showFileResult(result: OcrResult) -> None:
	global _lastResult
	if not any(ln.words for ln in result.lines):
		speech.speakMessage(_("No se reconoció texto"))
		return
	from .gui import ocr_viewer

	# Un refresco automático pendiente de la zona anterior no debe sobrescribir
	# este resultado.
	_cancelRefresh()
	_lastResult = result
	ocr_viewer.show(result)


def recognizeFileDialog() -> None:
	"""Pide un archivo de imagen o PDF y lo reconoce."""
	from .gui import helpers

	def ask() -> None:
		import wx

		wildcard = _("Imágenes y PDF") + " (*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.pdf)|*.png;*.jpg;*.jpeg;*.bmp;*.gif;*.tif;*.tiff;*.pdf|" + _("Todos los archivos") + " (*.*)|*.*"
		with wx.FileDialog(None, _("Elige una imagen o un PDF para reconocer"), wildcard=wildcard, style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST) as dlg:
			if dlg.ShowModal() == wx.ID_OK:
				queue_handler.queueFunction(recognizeFile, dlg.GetPath())

	helpers.runOnGui(ask)


def recognizeClipboard() -> None:
	"""Reconoce la imagen copiada o el primer archivo (imagen o PDF) copiado."""
	files = imaging.getClipboardFiles()
	for f in files:
		if f.lower().endswith(imaging.IMAGE_EXTENSIONS + (".pdf",)):
			recognizeFile(f)
			return
	if not imaging.clipboardHasImage():
		speech.speakMessage(_("El portapapeles no contiene ninguna imagen"))
		return
	speech.speakMessage(_("Reconociendo"))

	def job() -> OcrResult:
		# La lectura del portapapeles y la conversión del DIB (un bucle por
		# filas en Python) se hacen aquí, en el hilo de trabajo.
		try:
			img = imaging.getClipboardImage()
		except ValueError as e:
			raise OcrError(_("La imagen del portapapeles no se puede leer: {err}").format(err=e)) from e
		if img is None:
			raise OcrError(_("El portapapeles no contiene ninguna imagen"))
		return OcrResult(recognizeImage(img), _("Imagen del portapapeles"), ("clipboard",))

	_runWorker("OCR-portapapeles", job, _showFileResult)


# ====================================================================== modo continuo
def similar(a: str, b: str) -> float:
	return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def newLines(old: list[str], new: list[str], threshold: float = 0.8) -> list[str]:
	"""Líneas de ``new`` que no se parecen (al menos ``threshold``) a ninguna de ``old``."""
	out = []
	for line in new:
		t = line.strip()
		if not t:
			continue
		if any(similar(t, o.strip()) >= threshold for o in old if o.strip()):
			continue
		out.append(t)
	return out


class ContinuousReader:
	"""Reconoce una zona periódicamente y lee solo lo que cambia (subtítulos, contadores).

	Cada activación tiene un número de generación: los temporizadores y los
	resultados de una generación anterior (un reconocimiento que seguía en curso
	al desactivar y volver a activar) se descartan, así nunca hay dos cadenas de
	temporizadores a la vez.
	"""

	def __init__(self) -> None:
		self.active = False
		self.rect: tuple[int, int, int, int] | None = None
		self.hwnd = 0
		self._previous: list[str] = []
		self._timer: int | None = None
		self._busy = False
		self._generation = 0

	def start(self, rect: tuple[int, int, int, int], hwnd: int = 0) -> None:
		self.stop(announce=False)
		self.rect = tuple(rect)
		self.hwnd = hwnd
		self.active = True
		self._previous = []
		speech.speakMessage(_("Lectura continua por OCR activada"))
		self._schedule(10)

	def stop(self, announce: bool = True) -> None:
		was = self.active
		self.active = False
		self._generation += 1
		self._cancelTimer()
		if announce and was:
			speech.speakMessage(_("Lectura continua por OCR desactivada"))

	def _cancelTimer(self) -> None:
		if self._timer is not None:
			queue_handler.cancelCallLater(self._timer)
			self._timer = None

	def toggle(self) -> None:
		if self.active:
			self.stop()
			return
		_obj, loc, hwnd = _navigatorRect()
		if not loc:
			speech.speakMessage(_("El objeto navegador no tiene ubicación en pantalla"))
			return
		self.start(loc, hwnd)

	def _schedule(self, delay: int | None = None, generation: int | None = None) -> None:
		if not self.active:
			return
		if generation is not None and generation != self._generation:
			return
		if delay is None:
			delay = max(300, int(conf["ocr"]["continuousInterval"]))
		# Un único temporizador pendiente por lector.
		self._cancelTimer()
		gen = self._generation
		self._timer = queue_handler.callLater(delay, self._tick, gen)

	def _tick(self, generation: int | None = None) -> None:
		if generation is not None and generation != self._generation:
			return
		self._timer = None
		if not self.active or self.rect is None:
			return
		if self._busy:
			# Sigue en curso el reconocimiento de una generación anterior.
			self._schedule()
			return
		self._busy = True
		rect, hwnd = self.rect, self.hwnd
		gen = self._generation

		def job() -> OcrResult:
			try:
				return OcrResult(_captureAndRecognize(rect, hwnd))
			finally:
				self._busy = False

		def done(result: OcrResult) -> None:
			if gen != self._generation or not self.active:
				return
			self.process([ln.text for ln in result.lines])
			self._schedule(generation=gen)

		def worker() -> None:
			try:
				result = job()
			except Exception:
				log.debug("Error en la lectura continua", exc_info=True)
				queue_handler.queueFunction(self._schedule, None, gen)
				return
			queue_handler.queueFunction(done, result)

		threading.Thread(target=worker, name="OCR-continuo", daemon=True).start()

	def process(self, texts: list[str]) -> list[str]:
		"""Habla las líneas nuevas y devuelve cuáles eran."""
		new = newLines(self._previous, texts, conf["ocr"]["continuousSimilarity"] / 100.0)
		self._previous = [t for t in texts if t.strip()]
		if new and self.active:
			speech.speakText("\n".join(new))
		return new


continuous = ContinuousReader()


def terminate() -> None:
	continuous.stop(announce=False)
	_cancelRefresh()
