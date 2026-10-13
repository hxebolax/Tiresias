"""Imágenes: captura de pantalla, PNG, archivos de imagen, PDF y portapapeles.

Lo usan el OCR y la inteligencia artificial. Todas las imágenes se manejan
como ``Image``: píxeles BGRA de 32 bits de arriba abajo, con su anchura,
altura y la posición en pantalla de su esquina superior izquierda (para que
el OCR pueda devolver coordenadas de pantalla).

La captura tiene en cuenta la cortina de pantalla y la lupa (#19164): con
ellas activas, la imagen del escritorio que da Windows sale negra o ampliada,
así que se compone ventana a ventana con ``PrintWindow``, que dibuja cada
ventana sin los efectos de la API de ampliación. Las ventanas propias de
Tiresias que se superponen a la pantalla (resaltado, lupa en ventana,
foco) se excluyen de las capturas con ``SetWindowDisplayAffinity``.
"""

from __future__ import annotations

import array
import asyncio
import ctypes
import os
import struct
import zlib
from ctypes import wintypes
from dataclasses import dataclass

from .log import getLogger

log = getLogger("imaging")

gdi32 = ctypes.WinDLL("gdi32")
user32 = ctypes.WinDLL("user32")
kernel32 = ctypes.WinDLL("kernel32")
shell32 = ctypes.WinDLL("shell32")

SRCCOPY = 0x00CC0020
CAPTUREBLT = 0x40000000
PW_RENDERFULLCONTENT = 2
WDA_NONE = 0
WDA_EXCLUDEFROMCAPTURE = 0x11
CF_DIB = 8
CF_HDROP = 15

#: Lado mayor recomendado para enviar imágenes a los modelos de IA.
AI_MAX_SIDE = 1568


class BITMAPINFOHEADER(ctypes.Structure):
	_fields_ = [
		("biSize", wintypes.DWORD),
		("biWidth", wintypes.LONG),
		("biHeight", wintypes.LONG),
		("biPlanes", wintypes.WORD),
		("biBitCount", wintypes.WORD),
		("biCompression", wintypes.DWORD),
		("biSizeImage", wintypes.DWORD),
		("biXPelsPerMeter", wintypes.LONG),
		("biYPelsPerMeter", wintypes.LONG),
		("biClrUsed", wintypes.DWORD),
		("biClrImportant", wintypes.DWORD),
	]


gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.BitBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
gdi32.BitBlt.restype = wintypes.BOOL
gdi32.GetDIBits.argtypes = [wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
user32.PrintWindow.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsWindow.argtypes = [wintypes.HWND]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.SetWindowDisplayAffinity.restype = wintypes.BOOL
user32.GetWindowDisplayAffinity.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowDisplayAffinity.restype = wintypes.BOOL
user32.OpenClipboard.argtypes = [wintypes.HWND]
user32.GetClipboardData.argtypes = [wintypes.UINT]
user32.GetClipboardData.restype = wintypes.HANDLE
user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.argtypes = [wintypes.HGLOBAL]
kernel32.GlobalSize.restype = ctypes.c_size_t
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]


class RECT(ctypes.Structure):
	_fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG), ("right", wintypes.LONG), ("bottom", wintypes.LONG)]


@dataclass
class Image:
	"""Imagen BGRA de 32 bits, de arriba abajo."""

	data: bytes
	width: int
	height: int
	#: Posición en pantalla de la esquina superior izquierda (0, 0 si no viene de la pantalla).
	left: int = 0
	top: int = 0

	def isBlank(self) -> bool:
		"""``True`` si todos los píxeles son iguales (captura negra o vacía)."""
		if not self.data:
			return True
		first = self.data[:4]
		return self.data == first * (len(self.data) // 4)


# ====================================================================== captura
def _bitmapBits(hdc, hbmp, w: int, h: int) -> bytes:
	bmi = BITMAPINFOHEADER()
	bmi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
	bmi.biWidth = w
	bmi.biHeight = -h
	bmi.biPlanes = 1
	bmi.biBitCount = 32
	bmi.biCompression = 0
	buf = ctypes.create_string_buffer(w * h * 4)
	gdi32.GetDIBits(hdc, hbmp, 0, h, buf, ctypes.byref(bmi), 0)
	return buf.raw


def captureScreen(x: int, y: int, w: int, h: int) -> bytes:
	"""Captura un rectángulo de la pantalla tal como se ve (BGRA de arriba abajo)."""
	hdcScreen = user32.GetDC(None)
	hdcMem = gdi32.CreateCompatibleDC(hdcScreen)
	hbmp = gdi32.CreateCompatibleBitmap(hdcScreen, w, h)
	old = gdi32.SelectObject(hdcMem, hbmp)
	try:
		gdi32.BitBlt(hdcMem, 0, 0, w, h, hdcScreen, x, y, SRCCOPY | CAPTUREBLT)
		return _bitmapBits(hdcMem, hbmp, w, h)
	finally:
		gdi32.SelectObject(hdcMem, old)
		gdi32.DeleteObject(hbmp)
		gdi32.DeleteDC(hdcMem)
		user32.ReleaseDC(None, hdcScreen)


def _windowRect(hwnd: int) -> tuple[int, int, int, int]:
	r = RECT()
	user32.GetWindowRect(hwnd, ctypes.byref(r))
	return r.left, r.top, r.right - r.left, r.bottom - r.top


def captureWindowRect(hwnd: int, x: int, y: int, w: int, h: int) -> bytes | None:
	"""Captura una zona de una ventana aunque esté tapada por otras (PrintWindow)."""
	wx_, wy, ww, wh = _windowRect(hwnd)
	if ww <= 0 or wh <= 0:
		return None
	hdcScreen = user32.GetDC(None)
	hdcMem = gdi32.CreateCompatibleDC(hdcScreen)
	hbmp = gdi32.CreateCompatibleBitmap(hdcScreen, ww, wh)
	old = gdi32.SelectObject(hdcMem, hbmp)
	try:
		# PW_RENDERFULLCONTENT: también ventanas con DirectComposition.
		if not user32.PrintWindow(hwnd, hdcMem, PW_RENDERFULLCONTENT):
			return None
		full = _bitmapBits(hdcMem, hbmp, ww, wh)
	finally:
		gdi32.SelectObject(hdcMem, old)
		gdi32.DeleteObject(hbmp)
		gdi32.DeleteDC(hdcMem)
		user32.ReleaseDC(None, hdcScreen)
	ox, oy = x - wx_, y - wy
	if ox < 0 or oy < 0 or ox + w > ww or oy + h > wh:
		return None
	data = crop(full, ww, ox, oy, w, h)
	# Una captura completamente negra indica que PrintWindow no funcionó.
	if not data.strip(b"\x00"):
		return None
	return data


def crop(data: bytes, stride: int, x: int, y: int, w: int, h: int) -> bytes:
	"""Recorta un rectángulo de una imagen BGRA de anchura ``stride``."""
	return b"".join(data[((y + r) * stride + x) * 4 : ((y + r) * stride + x + w) * 4] for r in range(h))


def _isCloaked(hwnd: int) -> bool:
	try:
		dwm = ctypes.WinDLL("dwmapi")
		val = wintypes.DWORD()
		# DWMWA_CLOAKED = 14
		if dwm.DwmGetWindowAttribute(wintypes.HWND(hwnd), 14, ctypes.byref(val), ctypes.sizeof(val)) == 0:
			return bool(val.value)
	except OSError:
		pass
	return False


def _isExcludedFromCapture(hwnd: int) -> bool:
	aff = wintypes.DWORD()
	if user32.GetWindowDisplayAffinity(hwnd, ctypes.byref(aff)):
		return aff.value != WDA_NONE
	return False


def _topLevelWindows() -> list[int]:
	"""Ventanas de nivel superior visibles, de la de más arriba a la de más abajo."""
	out: list[int] = []

	def cb(hwnd, _lp):
		if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
			out.append(int(hwnd))
		return True

	user32.EnumWindows(WNDENUMPROC(cb), 0)
	return out


def captureComposited(x: int, y: int, w: int, h: int) -> bytes:
	"""Reconstruye la zona de pantalla dibujando cada ventana con PrintWindow.

	No depende de lo que se ve en el monitor, así que funciona con la cortina
	de pantalla o la lupa activas.
	"""
	hdcScreen = user32.GetDC(None)
	hdcComp = gdi32.CreateCompatibleDC(hdcScreen)
	hbmpComp = gdi32.CreateCompatibleBitmap(hdcScreen, w, h)
	oldComp = gdi32.SelectObject(hdcComp, hbmpComp)
	try:
		# BLACKNESS = 0x42: fondo negro.
		gdi32.PatBlt(hdcComp, 0, 0, w, h, 0x00000042)
		for hwnd in reversed(_topLevelWindows()):
			wx_, wy, ww, wh = _windowRect(hwnd)
			if ww <= 0 or wh <= 0 or wx_ >= x + w or wy >= y + h or wx_ + ww <= x or wy + wh <= y:
				continue
			if _isCloaked(hwnd) or _isExcludedFromCapture(hwnd):
				continue
			hdcWin = gdi32.CreateCompatibleDC(hdcScreen)
			hbmpWin = gdi32.CreateCompatibleBitmap(hdcScreen, ww, wh)
			oldWin = gdi32.SelectObject(hdcWin, hbmpWin)
			try:
				if user32.PrintWindow(hwnd, hdcWin, PW_RENDERFULLCONTENT):
					gdi32.BitBlt(hdcComp, wx_ - x, wy - y, ww, wh, hdcWin, 0, 0, SRCCOPY)
			finally:
				gdi32.SelectObject(hdcWin, oldWin)
				gdi32.DeleteObject(hbmpWin)
				gdi32.DeleteDC(hdcWin)
		return _bitmapBits(hdcComp, hbmpComp, w, h)
	finally:
		gdi32.SelectObject(hdcComp, oldComp)
		gdi32.DeleteObject(hbmpComp)
		gdi32.DeleteDC(hdcComp)
		user32.ReleaseDC(None, hdcScreen)


def screenIsAltered() -> bool:
	"""``True`` si la cortina o la lupa cambian lo que se ve en el monitor."""
	try:
		from . import vision
		from .magnifier import magnifier

		return bool(vision.handler.curtainActive or magnifier.altersScreen())
	except Exception:
		return False


def captureRect(rect: tuple[int, int, int, int], hwnd: int = 0) -> Image:
	"""Captura ``rect`` (x, y, ancho, alto) de la pantalla.

	Si se indica la ventana raíz ``hwnd`` se intenta primero ``PrintWindow``
	(así no molestan otras ventanas superpuestas).
	"""
	x, y, w, h = (int(v) for v in rect)
	if w <= 0 or h <= 0:
		raise ValueError("Rectángulo vacío")
	data = None
	if hwnd:
		try:
			data = captureWindowRect(hwnd, x, y, w, h)
		except OSError:
			data = None
	if data is None:
		data = captureComposited(x, y, w, h) if screenIsAltered() else captureScreen(x, y, w, h)
	return Image(data, w, h, x, y)


def virtualScreenRect() -> tuple[int, int, int, int]:
	x = user32.GetSystemMetrics(76)
	y = user32.GetSystemMetrics(77)
	w = user32.GetSystemMetrics(78) or user32.GetSystemMetrics(0)
	h = user32.GetSystemMetrics(79) or user32.GetSystemMetrics(1)
	return x, y, w, h


def excludeFromCapture(hwnd: int, exclude: bool = True) -> bool:
	"""Hace que una ventana propia no salga en las capturas (Windows 10 2004 o posterior)."""
	try:
		return bool(user32.SetWindowDisplayAffinity(hwnd, WDA_EXCLUDEFROMCAPTURE if exclude else WDA_NONE))
	except OSError:
		return False


# ====================================================================== transformaciones
def scaleDown(img: Image, maxSide: int) -> Image:
	"""Reduce la imagen para que el lado mayor mida ``maxSide`` (si es mayor).

	Se promedia el área de cada píxel nuevo (la letra pequeña sigue legible) y
	la escala no tiene por qué ser entera: una pantalla de 1920 de ancho queda
	en 1568 y no en 960. Sin numpy se usa el vecino más próximo con un factor
	entero, como antes.
	"""
	side = max(img.width, img.height)
	if side <= maxSide:
		return img
	try:
		import numpy as np

		w, h = img.width, img.height
		w2 = max(1, min(w, (w * maxSide) // side))
		h2 = max(1, min(h, (h * maxSide) // side))
		a = np.frombuffer(img.data, dtype=np.uint8, count=w * h * 4).reshape(h, w, 4)
		# Inicio de cada fila y columna de origen (estrictamente crecientes: h2 <= h).
		ys = (np.arange(h2, dtype=np.int64) * h) // h2
		xs = (np.arange(w2, dtype=np.int64) * w) // w2
		rows = np.add.reduceat(a, ys, axis=0, dtype=np.uint32)
		cells = np.add.reduceat(rows, xs, axis=1, dtype=np.uint32)
		ycnt = np.diff(np.append(ys, h)).astype(np.uint32)
		xcnt = np.diff(np.append(xs, w)).astype(np.uint32)
		area = ycnt[:, None, None] * xcnt[None, :, None]
		out = (cells + area // 2) // area
		return Image(out.astype(np.uint8).tobytes(), w2, h2, img.left, img.top)
	except ImportError:
		pass
	except Exception:
		log.debug("Reducción por áreas fallida; se usa el vecino más próximo", exc_info=True)
	factor = -(-side // maxSide)
	w2 = img.width // factor
	h2 = img.height // factor
	src = array.array("I")
	src.frombytes(img.data[: img.width * img.height * 4])
	out = array.array("I")
	for row in range(h2):
		start = row * factor * img.width
		out.extend(src[start : start + w2 * factor : factor][:w2])
	return Image(out.tobytes(), w2, h2, img.left, img.top)


def scale2x(data: bytes, w: int, h: int) -> bytes:
	"""Duplica el tamaño de la imagen (mejora el OCR de texto pequeño)."""
	src = array.array("I")
	src.frombytes(data)
	out = array.array("I", bytes(w * h * 16))
	w2 = w * 2
	for row in range(h):
		line = src[row * w : (row + 1) * w]
		doubled = array.array("I", bytes(w2 * 4))
		doubled[0::2] = line
		doubled[1::2] = line
		start = row * 2 * w2
		out[start : start + w2] = doubled
		out[start + w2 : start + 2 * w2] = doubled
	return out.tobytes()


def toGray(img: Image) -> bytes:
	"""Luminancia aproximada (un byte por píxel)."""
	d = img.data
	b = d[0::4]
	g = d[1::4]
	r = d[2::4]
	return bytes((ri * 77 + gi * 150 + bi * 29) >> 8 for ri, gi, bi in zip(r, g, b))


def meanLuma(gray: bytes, width: int, rect: tuple[int, int, int, int] | None = None) -> float:
	"""Luminancia media (0-255) de toda la imagen o de un rectángulo."""
	if not gray:
		return 0.0
	if rect is None:
		return sum(gray) / len(gray)
	x, y, w, h = rect
	total = 0
	count = 0
	for row in range(max(0, y), y + h):
		seg = gray[row * width + max(0, x) : row * width + x + w]
		total += sum(seg)
		count += len(seg)
	return total / count if count else 0.0


# ====================================================================== PNG
def encodePng(img: Image) -> bytes:
	"""Codifica la imagen en PNG RGB de 8 bits (sin dependencias externas)."""
	w, h = img.width, img.height
	d = img.data[: w * h * 4]
	rgb = bytearray(w * h * 3)
	rgb[0::3] = d[2::4]
	rgb[1::3] = d[1::4]
	rgb[2::3] = d[0::4]
	stride = w * 3
	raw = b"".join(b"\x00" + bytes(rgb[r * stride : (r + 1) * stride]) for r in range(h))

	def chunk(kind: bytes, payload: bytes) -> bytes:
		return struct.pack(">I", len(payload)) + kind + payload + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)

	header = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
	return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")


def decodePng(data: bytes) -> Image:
	"""Decodifica un PNG RGB o RGBA de 8 bits sin entrelazar (lo que produce :func:`encodePng`).

	Es lento con imágenes grandes: los archivos se abren con :func:`loadImageFile`.
	"""
	if data[:8] != b"\x89PNG\r\n\x1a\n":
		raise ValueError("No es un PNG")
	pos = 8
	idat = b""
	w = h = 0
	colorType = 2
	while pos < len(data):
		(length,) = struct.unpack(">I", data[pos : pos + 4])
		kind = data[pos + 4 : pos + 8]
		payload = data[pos + 8 : pos + 8 + length]
		pos += 12 + length
		if kind == b"IHDR":
			w, h, depth, colorType, _c, _f, interlace = struct.unpack(">IIBBBBB", payload)
			if depth != 8 or interlace or colorType not in (2, 6):
				raise ValueError("PNG no admitido")
		elif kind == b"IDAT":
			idat += payload
	bpp = 3 if colorType == 2 else 4
	raw = zlib.decompress(idat)
	stride = w * bpp
	out = bytearray(w * h * 4)
	prev = bytearray(stride)
	for r in range(h):
		f = raw[r * (stride + 1)]
		line = bytearray(raw[r * (stride + 1) + 1 : (r + 1) * (stride + 1)])
		for i in range(stride):
			a = line[i - bpp] if i >= bpp else 0
			b = prev[i]
			c = prev[i - bpp] if i >= bpp else 0
			if f == 1:
				line[i] = (line[i] + a) & 0xFF
			elif f == 2:
				line[i] = (line[i] + b) & 0xFF
			elif f == 3:
				line[i] = (line[i] + ((a + b) >> 1)) & 0xFF
			elif f == 4:
				p = a + b - c
				pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
				pred = a if pa <= pb and pa <= pc else (b if pb <= pc else c)
				line[i] = (line[i] + pred) & 0xFF
		for px in range(w):
			o = (r * w + px) * 4
			s = px * bpp
			out[o] = line[s + 2]
			out[o + 1] = line[s + 1]
			out[o + 2] = line[s]
			out[o + 3] = line[s + 3] if bpp == 4 else 255
		prev = line
	return Image(bytes(out), w, h)


# ====================================================================== archivos (WinRT)
IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".ico", ".jxr", ".heic", ".webp")


def _runAsync(coro):
	"""Ejecuta una corrutina de WinRT en un bucle propio (desde un hilo de trabajo)."""
	return asyncio.run(coro)


async def _softwareBitmapToImage(sb) -> Image:
	from winrt.windows.graphics.imaging import BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap
	from winrt.windows.storage.streams import Buffer

	if sb.bitmap_pixel_format != BitmapPixelFormat.BGRA8 or sb.bitmap_alpha_mode != BitmapAlphaMode.PREMULTIPLIED:
		sb = SoftwareBitmap.convert_with_alpha(sb, BitmapPixelFormat.BGRA8, BitmapAlphaMode.PREMULTIPLIED)
	w, h = sb.pixel_width, sb.pixel_height
	buf = Buffer(w * h * 4)
	sb.copy_to_buffer(buf)
	return Image(bytes(memoryview(buf)), w, h)


async def _decodeStream(stream) -> Image:
	from winrt.windows.graphics.imaging import BitmapDecoder

	dec = await BitmapDecoder.create_async(stream)
	sb = await dec.get_software_bitmap_async()
	return await _softwareBitmapToImage(sb)


async def _loadImageFile(path: str) -> Image:
	from winrt.windows.storage import FileAccessMode, StorageFile

	f = await StorageFile.get_file_from_path_async(os.path.abspath(path))
	stream = await f.open_async(FileAccessMode.READ)
	try:
		return await _decodeStream(stream)
	finally:
		stream.close()


def loadImageFile(path: str) -> Image:
	"""Abre un archivo de imagen (PNG, JPEG, BMP, GIF, TIFF...) con el decodificador de Windows."""
	return _runAsync(_loadImageFile(path))


async def _loadPdf(path: str):
	from winrt.windows.data.pdf import PdfDocument
	from winrt.windows.storage import StorageFile

	f = await StorageFile.get_file_from_path_async(os.path.abspath(path))
	return await PdfDocument.load_from_file_async(f)


async def _renderPdfPage(doc, index: int, scale: float) -> Image:
	from winrt.windows.data.pdf import PdfPageRenderOptions
	from winrt.windows.storage.streams import InMemoryRandomAccessStream

	page = doc.get_page(index)
	try:
		opts = PdfPageRenderOptions()
		opts.destination_width = max(1, int(page.size.width * scale))
		opts.destination_height = max(1, int(page.size.height * scale))
		stream = InMemoryRandomAccessStream()
		await page.render_with_options_to_stream_async(stream, opts)
		stream.seek(0)
		try:
			return await _decodeStream(stream)
		finally:
			stream.close()
	finally:
		page.close()


def renderPdf(path: str, onPage, scale: float = 2.0, maxPages: int = 0) -> int:
	"""Dibuja cada página de un PDF con ``Windows.Data.Pdf`` y llama a ``onPage(índice, total, Image)``.

	Si ``onPage`` devuelve ``False`` se detiene. Devuelve el número total de páginas.
	"""
	doc = _runAsync(_loadPdf(path))
	total = int(doc.page_count)
	count = min(total, maxPages) if maxPages > 0 else total
	# Cada página en su propio bucle: ``onPage`` puede usar asyncio (el OCR lo hace).
	for i in range(count):
		img = _runAsync(_renderPdfPage(doc, i, scale))
		if onPage(i, total, img) is False:
			break
	return total


# ====================================================================== portapapeles
def dibToImage(dib: bytes) -> Image:
	"""Convierte un CF_DIB (BITMAPINFOHEADER + píxeles) en una imagen BGRA de arriba abajo."""
	if len(dib) < 40:
		raise ValueError("DIB demasiado corto")
	(size, width, height, _planes, bpp, compression, _sizeImage, _x, _y, clrUsed, _imp) = struct.unpack("<IiiHHIIiiII", dib[:40])
	bottomUp = height > 0
	h = abs(height)
	w = width
	offset = size
	if compression == 3 and size == 40:
		offset += 12  # máscaras BI_BITFIELDS
	if bpp <= 8:
		offset += 4 * (clrUsed or (1 << bpp))
	if bpp not in (24, 32):
		raise ValueError(f"Profundidad de color no admitida: {bpp}")
	stride = ((w * bpp + 31) // 32) * 4
	pixels = dib[offset : offset + stride * h]
	out = bytearray(w * h * 4)
	for row in range(h):
		srcRow = (h - 1 - row) if bottomUp else row
		line = pixels[srcRow * stride : srcRow * stride + stride]
		o = row * w * 4
		if bpp == 32:
			out[o : o + w * 4] = line[: w * 4]
			out[o + 3 : o + w * 4 : 4] = b"\xff" * w
		else:
			seg = bytearray(w * 4)
			seg[0::4] = line[0 : w * 3 : 3]
			seg[1::4] = line[1 : w * 3 : 3]
			seg[2::4] = line[2 : w * 3 : 3]
			seg[3::4] = b"\xff" * w
			out[o : o + w * 4] = seg
	return Image(bytes(out), w, h)


def _openClipboard() -> bool:
	for _attempt in range(5):
		if user32.OpenClipboard(None):
			return True
		kernel32.Sleep(20)
	return False


def clipboardHasImage() -> bool:
	"""``True`` si el portapapeles tiene una imagen (comprobación rápida, sin leerla)."""
	try:
		return bool(user32.IsClipboardFormatAvailable(CF_DIB))
	except OSError:
		return False


def clipboardImageSize() -> tuple[int, int] | None:
	"""(ancho, alto) de la imagen del portapapeles leyendo solo la cabecera del DIB."""
	if not clipboardHasImage() or not _openClipboard():
		return None
	try:
		h = user32.GetClipboardData(CF_DIB)
		if not h or kernel32.GlobalSize(h) < 12:
			return None
		p = kernel32.GlobalLock(h)
		if not p:
			return None
		try:
			_size, width, height = struct.unpack("<Iii", ctypes.string_at(p, 12))
		finally:
			kernel32.GlobalUnlock(h)
	finally:
		user32.CloseClipboard()
	return abs(width), abs(height)


def getClipboardImage() -> Image | None:
	"""Imagen del portapapeles (CF_DIB) o ``None``."""
	if not user32.IsClipboardFormatAvailable(CF_DIB):
		return None
	if not _openClipboard():
		return None
	try:
		h = user32.GetClipboardData(CF_DIB)
		if not h:
			return None
		p = kernel32.GlobalLock(h)
		if not p:
			return None
		try:
			data = ctypes.string_at(p, kernel32.GlobalSize(h))
		finally:
			kernel32.GlobalUnlock(h)
	finally:
		user32.CloseClipboard()
	return dibToImage(data)


def getClipboardFiles() -> list[str]:
	"""Archivos copiados en el portapapeles (CF_HDROP)."""
	if not user32.IsClipboardFormatAvailable(CF_HDROP):
		return []
	if not _openClipboard():
		return []
	try:
		h = user32.GetClipboardData(CF_HDROP)
		if not h:
			return []
		count = shell32.DragQueryFileW(h, 0xFFFFFFFF, None, 0)
		out = []
		for i in range(count):
			n = shell32.DragQueryFileW(h, i, None, 0)
			buf = ctypes.create_unicode_buffer(n + 1)
			shell32.DragQueryFileW(h, i, buf, n + 1)
			out.append(buf.value)
		return out
	finally:
		user32.CloseClipboard()
