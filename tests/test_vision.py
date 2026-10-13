"""Pruebas de visión, OCR, inteligencia artificial y herramientas extra.

No se hace ninguna petición real a servicios externos: los proveedores de IA
se prueban contra un servidor HTTP local que imita sus API. Las imágenes y
el PDF de prueba se generan en la propia prueba.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import ctypes
import http.server
import json
import os
import shutil
import struct
import sys
import tempfile
import threading
import time
import unittest
import wave
from ctypes import wintypes

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

_TMP = tempfile.mkdtemp(prefix="tiresias_test_vision_")
if not os.path.isdir(os.path.join(_TMP, "symbols")):
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
paths.setDataDir(_TMP)
paths.ensureDataDirs()

from tiresias import imaging, ocr, queue_handler  # noqa: E402
from tiresias.config import conf  # noqa: E402


class _DataDir:
	"""Usa una carpeta de datos propia durante la prueba (otras pruebas cambian la global)."""

	def __enter__(self):
		self._old = paths.DATA_DIR
		self.path = tempfile.mkdtemp(prefix="tiresias_vis_")
		paths.setDataDir(self.path)
		paths.ensureDataDirs()
		return self

	def __exit__(self, *exc) -> None:
		paths.setDataDir(self._old)
		shutil.rmtree(self.path, ignore_errors=True)


class _Patch:
	"""Sustituye atributos temporalmente."""

	def __init__(self, *triples) -> None:
		self.triples = triples
		self.saved: list = []

	def __enter__(self):
		for obj, name, value in self.triples:
			self.saved.append((obj, name, getattr(obj, name)))
			setattr(obj, name, value)
		return self

	def __exit__(self, *exc) -> None:
		for obj, name, value in reversed(self.saved):
			setattr(obj, name, value)


class _Speech:
	def __init__(self) -> None:
		self.messages: list[str] = []

	def __enter__(self):
		from tiresias import speech

		def rec(text, *a, **k):
			self.messages.append(text)

		self._p = _Patch((speech, "speakMessage", rec), (speech, "speakText", rec), (speech, "cancelSpeech", lambda *a, **k: None))
		self._p.__enter__()
		return self

	def __exit__(self, *exc) -> None:
		self._p.__exit__(*exc)


def _immediateQueue():
	"""Ejecuta en el acto lo que se encola al núcleo (no hay bucle del núcleo en las pruebas)."""
	return _Patch((queue_handler, "queueFunction", lambda f, *a, **k: f(*a, **k)))


# ====================================================================== imágenes generadas
_gdi = ctypes.WinDLL("gdi32")
_user = ctypes.WinDLL("user32")
_gdi.CreateCompatibleDC.restype = wintypes.HDC
_gdi.CreateCompatibleDC.argtypes = [wintypes.HDC]
_gdi.CreateCompatibleBitmap.restype = wintypes.HBITMAP
_gdi.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
_gdi.SelectObject.restype = wintypes.HGDIOBJ
_gdi.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
_gdi.CreateFontW.restype = wintypes.HFONT
_gdi.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
_gdi.TextOutW.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.LPCWSTR, ctypes.c_int]
_gdi.PatBlt.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.DWORD]
_gdi.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
_gdi.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
_gdi.DeleteObject.argtypes = [wintypes.HGDIOBJ]
_gdi.DeleteDC.argtypes = [wintypes.HDC]
_user.GetDC.restype = wintypes.HDC
_user.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]


def textImage(lines: list[str], width: int = 900, lineHeight: int = 70) -> imaging.Image:
	"""Dibuja texto negro sobre blanco con GDI y devuelve la imagen BGRA."""
	h = lineHeight * len(lines) + 40
	screen = _user.GetDC(None)
	dc = _gdi.CreateCompatibleDC(screen)
	bmp = _gdi.CreateCompatibleBitmap(screen, width, h)
	old = _gdi.SelectObject(dc, bmp)
	font = _gdi.CreateFontW(48, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 4, 0, "Arial")
	oldFont = _gdi.SelectObject(dc, font)
	try:
		_gdi.PatBlt(dc, 0, 0, width, h, 0x00FF0062)  # WHITENESS
		_gdi.SetBkMode(dc, 1)
		_gdi.SetTextColor(dc, 0)
		for i, text in enumerate(lines):
			_gdi.TextOutW(dc, 20, 20 + i * lineHeight, text, len(text))
		data = imaging._bitmapBits(dc, bmp, width, h)
	finally:
		_gdi.SelectObject(dc, oldFont)
		_gdi.DeleteObject(font)
		_gdi.SelectObject(dc, old)
		_gdi.DeleteObject(bmp)
		_gdi.DeleteDC(dc)
		_user.ReleaseDC(None, screen)
	return imaging.Image(data, width, h)


def makePdf(path: str, pages: list[str]) -> None:
	"""PDF mínimo con una línea de texto en Helvetica por página."""
	objs: list[bytes] = []
	n = len(pages)
	kids = " ".join(f"{3 + i * 2} 0 R" for i in range(n))
	fontId = 3 + n * 2
	objs.append(b"<< /Type /Catalog /Pages 2 0 R >>")
	objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {n} >>".encode())
	for i, text in enumerate(pages):
		stream = f"BT /F1 36 Tf 30 120 Td ({text}) Tj ET".encode()
		objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 500 250] /Contents {4 + i * 2} 0 R /Resources << /Font << /F1 {fontId} 0 R >> >> >>".encode())
		objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
	objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
	out = bytearray(b"%PDF-1.4\n")
	offsets = []
	for i, body in enumerate(objs):
		offsets.append(len(out))
		out += f"{i + 1} 0 obj\n".encode() + body + b"\nendobj\n"
	xref = len(out)
	out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
	for off in offsets:
		out += f"{off:010d} 00000 n \n".encode()
	out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
	with open(path, "wb") as f:
		f.write(out)


def _hasWindowsOcr() -> bool:
	return bool(ocr.ENGINES["windows"].languages())


# ====================================================================== imágenes
class ImagingTests(unittest.TestCase):
	def test_png_roundtrip(self) -> None:
		data = bytes([10, 20, 30, 255, 200, 100, 50, 255, 0, 0, 0, 255, 255, 255, 255, 255])
		img = imaging.Image(data, 2, 2)
		back = imaging.decodePng(imaging.encodePng(img))
		self.assertEqual((back.width, back.height), (2, 2))
		self.assertEqual(back.data, data)

	def test_dib_24_bottom_up(self) -> None:
		# 2x2, filas de abajo arriba, cada fila con relleno a 4 bytes.
		header = struct.pack("<IiiHHIIiiII", 40, 2, 2, 1, 24, 0, 0, 0, 0, 0, 0)
		bottom = bytes([1, 2, 3, 4, 5, 6]) + b"\x00\x00"
		top = bytes([7, 8, 9, 10, 11, 12]) + b"\x00\x00"
		img = imaging.dibToImage(header + bottom + top)
		self.assertEqual(img.data[:8], bytes([7, 8, 9, 255, 10, 11, 12, 255]))
		self.assertEqual(img.data[8:], bytes([1, 2, 3, 255, 4, 5, 6, 255]))

	def test_scale_crop_blank(self) -> None:
		img = imaging.Image(bytes(range(4)) * 100 * 50, 100, 50, 5, 6)
		small = imaging.scaleDown(img, 25)
		self.assertLessEqual(max(small.width, small.height), 25)
		self.assertEqual((small.left, small.top), (5, 6))
		self.assertTrue(img.isBlank())
		self.assertEqual(len(imaging.crop(img.data, 100, 10, 10, 3, 2)), 3 * 2 * 4)
		gray = imaging.toGray(imaging.Image(b"\xff\xff\xff\xff" * 4, 2, 2))
		self.assertGreater(imaging.meanLuma(gray, 2), 250)

	def test_load_image_file(self) -> None:
		img = textImage(["Prueba"])
		path = os.path.join(_TMP, "prueba.png")
		with open(path, "wb") as f:
			f.write(imaging.encodePng(img))
		loaded = imaging.loadImageFile(path)
		self.assertEqual((loaded.width, loaded.height), (img.width, img.height))


# ====================================================================== OCR
class OcrTests(unittest.TestCase):
	def test_parse_tesseract_tsv(self) -> None:
		tsv = "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
		tsv += "5\t1\t1\t1\t1\t1\t20\t40\t60\t20\t95\tHola\n"
		tsv += "5\t1\t1\t1\t1\t2\t90\t40\t70\t20\t93\tmundo\n"
		tsv += "5\t1\t1\t1\t2\t1\t20\t80\t50\t20\t90\tadiós\n"
		lines = ocr.parseTesseractTsv(tsv, scale=2, offsetX=100, offsetY=10)
		self.assertEqual([ln.text for ln in lines], ["Hola mundo", "adiós"])
		self.assertEqual((lines[0].words[0].x, lines[0].words[0].y), (110, 30))

	def test_new_lines_tolerates_noise(self) -> None:
		old = ["Hola, ¿qué tal estás?", "Bien"]
		new = ["Hola, ¿que tal estas?", "Me alegro mucho"]
		self.assertEqual(ocr.newLines(old, new, 0.8), ["Me alegro mucho"])

	def test_continuous_reader_reads_only_new(self) -> None:
		r = ocr.ContinuousReader()
		r.active = True
		with _Speech() as sp:
			self.assertEqual(r.process(["Primera frase del subtítulo"]), ["Primera frase del subtítulo"])
			self.assertEqual(r.process(["Primera frase del subtitulo"]), [])
			self.assertEqual(r.process(["Otra frase distinta"]), ["Otra frase distinta"])
		self.assertEqual(len(sp.messages), 2)

	def test_engine_fallback(self) -> None:
		conf["ocr"]["engine"] = "tesseract"
		try:
			eng = ocr.getEngine()
			if not ocr.ENGINES["tesseract"].isAvailable():
				self.assertEqual(eng.id, "windows")
		finally:
			conf["ocr"]["engine"] = "windows"

	@unittest.skipUnless(_hasWindowsOcr(), "Windows no tiene idiomas de OCR")
	def test_windows_ocr_generated_image(self) -> None:
		img = textImage(["Tiresias reconoce texto", "Segunda linea 2026"])
		img.left, img.top = 1000, 500
		lines = ocr.ENGINES["windows"].recognize(img)
		text = " ".join(ln.text for ln in lines).lower()
		self.assertIn("tiresias", text)
		self.assertIn("2026", text)
		# Coordenadas de pantalla: desplazadas por la posición de la imagen.
		self.assertGreaterEqual(lines[0].words[0].x, 1000)
		self.assertGreaterEqual(lines[0].words[0].y, 500)

	@unittest.skipUnless(_hasWindowsOcr(), "Windows no tiene idiomas de OCR")
	def test_pdf_render_and_ocr(self) -> None:
		path = os.path.join(_TMP, "prueba.pdf")
		makePdf(path, ["Primera pagina PDF", "Segunda pagina PDF"])
		result = ocr._recognizePdf(path)
		pages = {ln.page for ln in result.lines}
		self.assertEqual(pages, {1, 2})
		text = result.text.lower()
		self.assertIn("primera", text)
		self.assertIn("segunda", text)


# ====================================================================== documento del OCR
def _result():
	W = ocr.OcrWord
	lines = [
		ocr.OcrLine([W("Hola", 10, 20, 40, 15), W("mundo", 60, 20, 50, 15)], page=1),
		ocr.OcrLine([W("adiós", 10, 50, 45, 15)], page=1),
		ocr.OcrLine([W("final", 10, 20, 40, 15)], page=2),
	]
	return ocr.OcrResult(lines, "Prueba", ("rect", (0, 0, 200, 100), 0))


class OcrDocumentTests(unittest.TestCase):
	def test_buffer_matches_viewer_text(self) -> None:
		from tiresias.gui import ocr_viewer
		from tiresias.ocr_document import OcrBuffer

		res = _result()
		buf = OcrBuffer(res)
		buf.build()
		text, mapping = ocr_viewer._resultText(res)
		self.assertEqual(buf.text.rstrip("\n"), text)
		self.assertIn("Página 2", buf.text)
		off = buf.text.index("mundo") + 2
		node = buf.wordNodeAt(off)
		self.assertEqual(node.name, "mundo")
		self.assertEqual(node.location, (60, 20, 50, 15))
		# En el espacio entre palabras se toma la anterior.
		self.assertEqual(buf.wordNodeAt(buf.text.index(" mundo")).name, "Hola")

	def test_document_navigation(self) -> None:
		from tiresias import textinfo
		from tiresias.ocr_document import OcrDocument, caretToLineCol

		doc = OcrDocument(_result())
		self.assertFalse(doc.passThrough)
		info = doc.makeTextInfo(textinfo.POSITION_FIRST)
		info.expand(textinfo.UNIT_LINE)
		self.assertIn("Página 1", info.text)
		headings = [n for n in doc.buffer.nodes if n.isHeading()]
		self.assertEqual(len(headings), 2)
		self.assertEqual(caretToLineCol("ab\ncd", 4), (1, 1))
		doc.close()

	def test_file_result_has_no_positions(self) -> None:
		from tiresias.ocr_document import OcrBuffer

		res = _result()
		res.source = ("file", "x.png")
		buf = OcrBuffer(res, screenCoordinates=False)
		buf.build()
		self.assertIsNone(buf.wordNodeAt(0 + buf.text.index("Hola")).location)


# ====================================================================== lupa y resaltado
class MagnifierTests(unittest.TestCase):
	def test_view_origin_modes(self) -> None:
		from tiresias.magnifier import computeViewOrigin

		screen = (0, 0, 1000, 800)
		view = (500, 400)
		self.assertEqual(computeViewOrigin((500, 400), view, screen, "center", None), (250, 200))
		# Se limita a la pantalla.
		self.assertEqual(computeViewOrigin((10, 10), view, screen, "center", None), (0, 0))
		# Por bordes: no se mueve si el punto está dentro del margen.
		self.assertEqual(computeViewOrigin((300, 300), view, screen, "edge", (100, 100)), (100, 100))
		left, top = computeViewOrigin((590, 300), view, screen, "edge", (100, 100))
		self.assertGreater(left, 100)
		# Relativo: el punto queda en la misma proporción de la vista que de la pantalla.
		left, top = computeViewOrigin((750, 200), view, screen, "relative", None)
		self.assertAlmostEqual((750 - left) / 500, 0.75)

	def test_lens_rect(self) -> None:
		from tiresias.magnifier import lensRect

		self.assertEqual(lensRect((500, 400), (200, 100), (0, 0, 1000, 800), True), (400, 350, 200, 100))
		x, y, w, h = lensRect((990, 790), (200, 100), (0, 0, 1000, 800), False)
		self.assertTrue(x + w <= 1000 and y + h <= 800)
		self.assertFalse(x <= 990 <= x + w and y <= 790 <= y + h)

	def test_filters(self) -> None:
		from tiresias.magnifier import FILTER_MATRICES, applyMatrix

		self.assertEqual(applyMatrix("invert", 1, 1, 1), (0, 0, 0))
		r, g, b = applyMatrix("grayscale", 1, 0, 0)
		self.assertAlmostEqual(r, g)
		self.assertAlmostEqual(g, b)
		self.assertEqual(applyMatrix("yellowOnBlack", 0, 0, 0), (1, 1, 0))
		for v in applyMatrix("yellowOnBlack", 1, 1, 1):
			self.assertAlmostEqual(v, 0)
		self.assertEqual(applyMatrix("none", 0.2, 0.4, 0.6), (0.2, 0.4, 0.6))
		for m in FILTER_MATRICES.values():
			self.assertEqual(len(m), 25)

	def test_commands_change_config(self) -> None:
		from tiresias.magnifier import Magnifier

		mag = Magnifier()
		with _Speech() as sp, _Patch((mag, "_run", lambda f, *a: None)):
			old = conf["magnifier"]["filter"]
			mag.setFilter("none", announce=False)
			mag.toggleColorFilter()
			self.assertNotEqual(conf["magnifier"]["filter"], "none")
			mag.toggleColorFilter()
			self.assertEqual(conf["magnifier"]["filter"], "none")
			mag.toggleFollow("followMouse")
			mag.toggleFollow("followMouse")
			mag.cycleTrackingMode()
			conf["magnifier"]["filter"] = old
		self.assertTrue(sp.messages)


class HighlightTests(unittest.TestCase):
	def test_compute_highlights(self) -> None:
		from tiresias.vision import computeHighlights

		r = {"focus": (10, 10, 50, 20), "navigator": (10, 10, 50, 20), "browseMode": None, "mouse": (100, 100, 5, 5)}
		out = computeHighlights(r, padding=2)
		self.assertEqual(set(out), {"focus", "mouse"})
		self.assertEqual(out["focus"], (8, 8, 54, 24))

	def test_edges(self) -> None:
		from tiresias.gui.highlighter import edgeRects

		top, bottom, left, right = edgeRects((10, 10, 100, 50), 3)
		self.assertEqual(top, (7, 7, 106, 3))
		self.assertEqual(right, (110, 10, 3, 50))

	def test_curtain_state_and_startup(self) -> None:
		from tiresias import vision

		h = vision.VisionHandler()
		with _Speech() as sp:
			h._afterCurtain(True, True, announce=False, startup=True)
		self.assertTrue(h.curtainActive)
		self.assertIn("activada", h.curtainStateText())
		self.assertTrue(any("activada" in m for m in sp.messages))
		conf["vision"]["screenCurtain"] = False


# ====================================================================== IA: servidor simulado
class _MockHandler(http.server.BaseHTTPRequestHandler):
	server_version = "Mock"

	def log_message(self, *a) -> None:
		pass

	def do_POST(self) -> None:
		length = int(self.headers.get("Content-Length", 0))
		body = json.loads(self.rfile.read(length).decode("utf-8"))
		srv = self.server
		srv.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
		status, payload = srv.responder(self.path, body)
		data = json.dumps(payload).encode("utf-8")
		self.send_response(status)
		self.send_header("Content-Type", "application/json")
		self.send_header("Content-Length", str(len(data)))
		self.send_header("Connection", "close")
		self.end_headers()
		self.wfile.write(data)
		self.wfile.flush()
		# Cerrar el socket enseguida provoca a veces un reinicio de la conexión
		# (WinError 10054) en el cliente local antes de leer la respuesta.
		time.sleep(0.05)


class _Server(http.server.ThreadingHTTPServer):
	# En Windows SO_REUSEADDR permite que dos sockets compartan puerto: se desactiva.
	allow_reuse_address = False
	daemon_threads = True


class MockServer:
	def __init__(self, responder) -> None:
		self.httpd = _Server(("127.0.0.1", 0), _MockHandler)
		self.httpd.requests = []
		self.httpd.responder = responder
		self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

	@property
	def url(self) -> str:
		return f"http://127.0.0.1:{self.httpd.server_address[1]}"

	@property
	def requests(self) -> list:
		return self.httpd.requests

	def __enter__(self):
		self.thread.start()
		return self

	def __exit__(self, *exc) -> None:
		self.httpd.shutdown()
		self.httpd.server_close()


class AiProviderTests(unittest.TestCase):
	@classmethod
	def setUpClass(cls) -> None:
		from tiresias.ai import assistant  # noqa: F401  (valores por defecto)

	def _anthropic(self, url: str):
		from tiresias.ai import keys
		from tiresias.ai.providers import PROVIDERS

		p = PROVIDERS["anthropic"]
		return _Patch((p, "baseUrl", url), (keys, "getKey", lambda pid: "clave-de-prueba"))

	def test_anthropic_request_and_raw_history(self) -> None:
		from tiresias.ai.providers import Message, PROVIDERS

		def responder(path, body):
			return 200, {"content": [{"type": "thinking", "thinking": "", "signature": "x"}, {"type": "text", "text": "Un botón azul."}], "stop_reason": "end_turn"}

		with MockServer(responder) as srv, self._anthropic(srv.url):
			p = PROVIDERS["anthropic"]
			conf["ai"]["anthropicModel"] = "claude-opus-5-5"
			reply = p.chat([Message("user", "Describe", [b"PNGDATA"])], "sistema")
			self.assertEqual(reply.text, "Un botón azul.")
			req = srv.requests[0]
			self.assertEqual(req["path"], "/v1/messages")
			self.assertEqual(req["headers"]["x-api-key"], "clave-de-prueba")
			self.assertEqual(req["headers"]["anthropic-version"], "2023-06-01")
			self.assertEqual(req["body"]["model"], "claude-opus-5-5")
			self.assertEqual(req["body"]["system"], "sistema")
			self.assertEqual(req["body"]["fallbacks"], "default")
			content = req["body"]["messages"][0]["content"]
			self.assertEqual(content[0]["type"], "image")
			self.assertEqual(content[0]["source"]["media_type"], "image/png")
			# La respuesta se reenvía completa (con su bloque de razonamiento).
			p.chat([Message("user", "Describe"), reply, Message("user", "¿De qué color?")])
			sent = srv.requests[1]["body"]["messages"][1]["content"]
			self.assertEqual(sent[0]["type"], "thinking")
			# Haiku no lleva esfuerzo ni reintento con otro modelo.
			conf["ai"]["anthropicModel"] = "claude-haiku-4-5-20251001"
			p.chat([Message("user", "Hola")])
			self.assertNotIn("output_config", srv.requests[2]["body"])
			conf["ai"]["anthropicModel"] = "claude-opus-5-5"

	def test_anthropic_errors(self) -> None:
		from tiresias.ai.providers import AIError, Message, PROVIDERS

		answers = iter([(401, {"error": {"message": "invalid x-api-key"}}), (200, {"content": [], "stop_reason": "refusal", "stop_details": {"explanation": "no"}})])
		with MockServer(lambda path, body: next(answers)) as srv, self._anthropic(srv.url):
			p = PROVIDERS["anthropic"]
			with self.assertRaises(AIError) as ctx:
				p.chat([Message("user", "x")])
			self.assertIn("clave", str(ctx.exception))
			with self.assertRaises(AIError) as ctx:
				p.chat([Message("user", "x")])
			self.assertIn("rechazado", str(ctx.exception))

	def test_openai_compatible_local(self) -> None:
		from tiresias.ai.providers import Message, PROVIDERS

		def responder(path, body):
			return 200, {"choices": [{"message": {"role": "assistant", "content": "Respuesta local"}}]}

		with MockServer(responder) as srv:
			old = conf["ai"]["localUrl"]
			conf["ai"]["localUrl"] = srv.url + "/v1"
			try:
				reply = PROVIDERS["local"].chat([Message("user", "Hola", [b"IMG"])], "sis")
			finally:
				conf["ai"]["localUrl"] = old
			self.assertEqual(reply.text, "Respuesta local")
			req = srv.requests[0]
			self.assertEqual(req["path"], "/v1/chat/completions")
			msgs = req["body"]["messages"]
			self.assertEqual(msgs[0], {"role": "system", "content": "sis"})
			self.assertTrue(msgs[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,"))
			self.assertNotIn("authorization", req["headers"])

	def test_gemini(self) -> None:
		from tiresias.ai import keys
		from tiresias.ai.providers import Message, PROVIDERS

		def responder(path, body):
			return 200, {"candidates": [{"content": {"parts": [{"text": "Hola desde Gemini"}]}}]}

		p = PROVIDERS["gemini"]
		with MockServer(responder) as srv, _Patch((p, "baseUrl", srv.url + "/v1beta"), (keys, "getKey", lambda pid: "gk")):
			reply = p.chat([Message("user", "Hola")], "sis")
			self.assertEqual(reply.text, "Hola desde Gemini")
			req = srv.requests[0]
			self.assertIn(":generateContent", req["path"])
			self.assertNotIn("key=", req["path"])
			self.assertEqual(req["headers"]["x-goog-api-key"], "gk")
			self.assertEqual(req["body"]["systemInstruction"]["parts"][0]["text"], "sis")

	def test_missing_key(self) -> None:
		from tiresias.ai import keys
		from tiresias.ai.providers import AIError, Message, PROVIDERS

		with _Patch((keys, "getKey", lambda pid: "")):
			with self.assertRaises(AIError):
				PROVIDERS["openai"].chat([Message("user", "x")])

	def test_chat_session_follow_up(self) -> None:
		from tiresias.ai.assistant import ChatSession
		from tiresias.ai.providers import PROVIDERS

		calls = []

		def responder(path, body):
			calls.append(body)
			return 200, {"content": [{"type": "text", "text": f"respuesta {len(calls)}"}], "stop_reason": "end_turn"}

		with MockServer(responder) as srv, self._anthropic(srv.url), _immediateQueue():
			s = ChatSession("t", "sis", PROVIDERS["anthropic"])
			done = threading.Event()
			got = []
			s.ask("primera", [b"IMG"], onAnswer=lambda t: (got.append(t), done.set()))
			self.assertTrue(done.wait(10))
			done.clear()
			s.ask("segunda", onAnswer=lambda t: (got.append(t), done.set()))
			self.assertTrue(done.wait(10))
		self.assertEqual(got, ["respuesta 1", "respuesta 2"])
		self.assertEqual(len(calls[1]["messages"]), 3)
		self.assertEqual([r for r, _t in s.transcript], ["user", "assistant", "user", "assistant"])

	def test_keys_dpapi(self) -> None:
		from tiresias.ai import keys

		self.assertEqual(keys.unprotect(keys.protect(b"secreto")), b"secreto")
		with _DataDir() as d:
			keys.setKey("anthropic", "sk-prueba")
			self.assertTrue(keys.hasStoredKey("anthropic"))
			with open(os.path.join(d.path, "config", "aiKeys.json"), encoding="utf-8") as f:
				self.assertNotIn("sk-prueba", f.read())
			self.assertEqual(keys.getKey("anthropic"), "sk-prueba")
			keys.setKey("anthropic", None)
			self.assertFalse(keys.hasStoredKey("anthropic"))

	def test_label_cleanup(self) -> None:
		from tiresias.ai.assistant import cleanLabel

		self.assertEqual(cleanLabel("«Enviar mensaje».\nOtra línea"), "Enviar mensaje")

	def test_privacy_only_once_and_not_local(self) -> None:
		from tiresias.ai import assistant

		ran = []
		old = conf["ai"]["provider"]
		conf["ai"]["provider"] = "local"
		try:
			assistant.withImagePrivacy(lambda: ran.append(1))
		finally:
			conf["ai"]["provider"] = old
		self.assertEqual(ran, [1])
		conf["ai"]["imagePrivacyAccepted"] = True
		assistant.withImagePrivacy(lambda: ran.append(2))
		conf["ai"]["imagePrivacyAccepted"] = False
		self.assertEqual(ran, [1, 2])


class TranslateTests(unittest.TestCase):
	def test_speech_filter(self) -> None:
		from tiresias.ai import assistant  # noqa: F401
		from tiresias.ai import translate

		done = threading.Event()
		spoken = []
		with _Patch((translate, "translateText", lambda t: "Hello world"), (queue_handler, "queueFunction", lambda f, *a: (spoken.append(a[0]), done.set()))):
			conf["ai"]["translateSpeech"] = True
			try:
				translate._cache.clear()
				self.assertEqual(translate.speechFilter("Hola mundo"), "")
				self.assertTrue(done.wait(5))
				self.assertEqual(spoken, ["Hello world"])
				self.assertEqual(translate.speechFilter("Hola mundo"), "Hello world")
				# La traducción no se vuelve a traducir; los textos sin letras pasan.
				self.assertEqual(translate.speechFilter("Hello world"), "Hello world")
				self.assertEqual(translate.speechFilter("12"), "12")
			finally:
				conf["ai"]["translateSpeech"] = False
		self.assertEqual(translate.speechFilter("Hola"), "Hola")

	def test_prompt_language(self) -> None:
		from tiresias.ai import translate

		conf["ai"]["translateTo"] = "en"
		try:
			self.assertIn("inglés", translate.translationPrompt("hola"))
		finally:
			conf["ai"]["translateTo"] = "es"


class AgentTests(unittest.TestCase):
	def test_parse_actions(self) -> None:
		from tiresias.ai.agent import describeAction, parseAction

		a = parseAction('Vale: {"action": "click", "x": "10", "y": 20, "explanation": "Abro el menú"}')
		self.assertEqual((a.kind, a.data["x"]), ("click", 10))
		self.assertIn("Abro el menú", describeAction(a))
		self.assertEqual(parseAction('{"action": "done", "message": "Hecho"}').explanation, "Hecho")
		for bad in ("sin json", '{"action": "borrar_todo"}', '{"action": "key", "keys": "control+s; rm"}', '{"action": "type"}'):
			with self.assertRaises((ValueError, KeyError)):
				parseAction(bad)

	def test_to_screen(self) -> None:
		from tiresias.ai.agent import toScreen

		self.assertEqual(toScreen(((100, 50, 1000, 500), 500, 250), 250, 125), (600, 300))

	def test_choices(self) -> None:
		from tiresias.ai.agent import Action, ScreenAgent

		ag = ScreenAgent()
		ag.running = True
		executed = []
		ag.executor = lambda action, geom: executed.append(action.kind)
		ag._geom = ((0, 0, 100, 100), 100, 100)
		with _Speech(), _Patch((ag, "_nextStep", lambda: None), (queue_handler, "callLater", lambda ms, f, *a: f(*a))):
			ag._onChoice(Action("click", {"x": 1, "y": 2}), "clic", "no")
			self.assertEqual(executed, [])
			self.assertIn("NO", ag.steps[-1])
			ag._onChoice(Action("key", {"keys": "control+s"}), "pulsar", "yes")
			self.assertEqual(executed, ["key"])
			from tiresias.gui import ai_dialogs

			with _Patch((ai_dialogs, "closeAgentConfirm", lambda: None)):
				ag._onChoice(Action("click", {"x": 1, "y": 2}), "clic", "stop")
		self.assertFalse(ag.running)
		self.assertEqual(executed, ["key"])


class CameraTests(unittest.TestCase):
	def test_hints(self) -> None:
		from tiresias.ai.camera import Frame, analyzeFrame

		self.assertIn("ninguna cara", analyzeFrame(Frame(640, 480, [], 120))[0])
		good = analyzeFrame(Frame(640, 480, [(240, 150, 160, 170)], 130, 125))
		self.assertEqual(len(good), 1)
		self.assertIn("Bien", good[0])
		left = " ".join(analyzeFrame(Frame(640, 480, [(20, 150, 160, 170)], 130, 125)))
		self.assertIn("izquierda", left)
		far = " ".join(analyzeFrame(Frame(640, 480, [(300, 200, 40, 50)], 130, 125)))
		self.assertIn("lejos", far)
		back = " ".join(analyzeFrame(Frame(640, 480, [(240, 150, 160, 170)], 160, 60)))
		self.assertIn("contraluz", back)
		self.assertIn("negra", analyzeFrame(Frame(640, 480, [], 5))[0])


# ====================================================================== ratón, portapapeles y audio
class MouseKeysTests(unittest.TestCase):
	def test_clamp(self) -> None:
		from tiresias.mouse_keys import clampToScreen

		x, y, edges = clampToScreen(-5, 50, (0, 0, 100, 100))
		self.assertEqual((x, y), (0, 50))
		self.assertEqual(len(edges), 1)
		self.assertEqual(clampToScreen(50, 50, (0, 0, 100, 100))[2], [])

	def test_positions_per_app(self) -> None:
		from tiresias import mouse_keys

		with _DataDir(), _Patch((mouse_keys, "foregroundOrigin", lambda: (100, 200))):
			conf["mouseKeys"]["relativePositions"] = True
			mouse_keys.savePosition("Enviar", "app1", (150, 260))
			mouse_keys.savePosition("Otro", "app2", (10, 10))
			self.assertEqual(sorted(mouse_keys.positionsFor("app1")), ["Enviar"])
			self.assertEqual(mouse_keys.resolve(mouse_keys.positionsFor("app1")["Enviar"]), (150, 260))
			mouse_keys.deletePosition("Enviar", "app1")
			self.assertEqual(mouse_keys.positionsFor("app1"), {})
			self.assertIn("Otro", mouse_keys.positionsFor("app2"))

	def test_step_cycle(self) -> None:
		from tiresias import mouse_keys

		conf["mouseKeys"]["step"] = 10
		with _Speech():
			mouse_keys.changeStep(1)
			self.assertEqual(conf["mouseKeys"]["step"], 20)
			mouse_keys.changeStep(-1)
		self.assertEqual(conf["mouseKeys"]["step"], 10)


class ClipboardTests(unittest.TestCase):
	def test_join_for_append(self) -> None:
		from tiresias import clipboard

		self.assertEqual(clipboard.joinForAppend("", "b", "newline"), "b")
		self.assertEqual(clipboard.joinForAppend("a", "b", "newline"), "a\r\nb")
		self.assertEqual(clipboard.joinForAppend("a", "b", "space"), "a b")
		self.assertEqual(clipboard.joinForAppend("a", "b", "none"), "ab")


class AudioExportTests(unittest.TestCase):
	def test_render_and_write(self) -> None:
		from tiresias import audio_export
		from tiresias.synth.base import AudioSynthDriver

		class FakeSynth(AudioSynthDriver):
			name = "falso"

			def __init__(self) -> None:  # sin reproductor real
				self.sampleRate = 16000
				self.channels = 1

			def runInWorker(self, func) -> None:
				threading.Thread(target=func, daemon=True).start()

			def _synthesizeSegment(self, items, emit, isCancelled) -> None:
				emit(b"\x01\x00" * len(items[0]))

		from tiresias.synth.base import splitLongText

		text = "Hola mundo. " * 100
		pcm, rate, ch = audio_export.renderPcm(text, FakeSynth(), timeout=10)
		self.assertEqual((rate, ch), (16000, 1))
		self.assertEqual(len(pcm), sum(2 * len(p) for p in splitLongText(text, 400) if p.strip()))
		path = os.path.join(_TMP, "voz.wav")
		audio_export.writeWav(path, pcm, rate, ch)
		with wave.open(path, "rb") as w:
			self.assertEqual(w.getframerate(), 16000)
			self.assertEqual(w.getnframes(), len(pcm) // 2)


# ====================================================================== órdenes
class CommandTests(unittest.TestCase):
	def test_gestures_installed_and_free(self) -> None:
		from tiresias import global_commands, vision_commands
		from tiresias.baseobject import normalizeGestureId
		from tiresias.gui import gesture_tools

		cls = global_commands.GlobalCommands
		for attr, func in vars(vision_commands.VisionCommands).items():
			if not attr.startswith("script_"):
				continue
			self.assertTrue(hasattr(cls, attr), attr)
			for g in func.gestures:
				gid = normalizeGestureId(g)
				self.assertEqual(cls._classGestures.get(gid), attr[7:], f"{g} ya lo usa otra orden")
				keys = gid.split(":", 1)[1]
				self.assertNotIn(keys, gesture_tools.RESERVED, g)

	def test_menu_actions(self) -> None:
		from tiresias import vision_commands

		actions = vision_commands.menuActions()
		self.assertGreater(len(actions), 20)
		for _g, label, func in actions:
			self.assertTrue(callable(func), label)


if __name__ == "__main__":
	unittest.main()
