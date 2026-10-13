"""Pruebas del grupo «IA y PDF» (peticiones parciales F6, F9, F10 y F12).

- F6 (foros 3.10): orden de lectura a mano y con IA, texto alternativo de las
  imágenes de los PDF usado en el búfer.
- F9 (foros 6.3): etiquetado automático de los elementos sin nombre.
- F10 (foros 6.6): explorar la página (estructura, teclas y captura).
- F12 (foros 10.6): detectar CAPTCHA, ir al reto de audio y bajar la voz.

No se hace ninguna petición de red: el proveedor de IA es un doble que
devuelve respuestas fijas y el árbol UIA se simula con elementos falsos.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import imaging, paths, queue_handler, speech  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.ai import assistant  # noqa: E402,F401  (valores por defecto de «ai»)
from tiresias.ai import autolabel, captcha, explorer, labelstore, reading  # noqa: E402
from tiresias.ai.providers import Message  # noqa: E402
from tiresias.browse import flexweb, reading_order  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role  # noqa: E402

_rid = [5000]


class FakeArray:
	def __init__(self, items: list) -> None:
		self.items = items

	@property
	def Length(self) -> int:
		return len(self.items)

	def GetElement(self, i: int):
		return self.items[i]

	def QueryInterface(self, iface):
		return self


class FakeEl:
	def __init__(self, ct: int, name: str = "", children: list | None = None, **props) -> None:
		_rid[0] += 1
		self.rid = (7, _rid[0])
		self.props = {uc.P_CONTROLTYPE: ct, uc.P_NAME: name, uc.P_RUNTIMEID: self.rid}
		for k, v in props.items():
			self.props[getattr(uc, k)] = v
		self.children = children or []

	def GetCachedPropertyValueEx(self, propId: int, ignoreDefault: bool):
		return self.props.get(propId)

	GetCurrentPropertyValueEx = GetCachedPropertyValueEx

	def GetCachedPropertyValue(self, propId: int):
		return self.props.get(propId)

	def GetCachedChildren(self):
		return FakeArray(self.children)

	def BuildUpdatedCache(self, request):
		return self

	def GetCurrentPattern(self, pid):
		return None


def text(t: str, **props) -> FakeEl:
	return FakeEl(uc.CT_TEXT, t, **props)


def group(*children, name: str = "", **props) -> FakeEl:
	return FakeEl(uc.CT_GROUP, name, list(children), **props)


def doc(*children, name: str = "doc") -> FakeEl:
	return FakeEl(uc.CT_DOCUMENT, name, list(children))


def build(root: FakeEl, order=None, ai=None) -> VirtualBuffer:
	buf = VirtualBuffer(root)
	buf.readingOrder = order
	buf.aiLabels = ai
	buf.build()
	return buf


class _Patch:
	def __init__(self, *triples) -> None:
		self.triples = triples

	def __enter__(self):
		self.saved = [(o, a, getattr(o, a)) for o, a, _v in self.triples]
		for o, a, v in self.triples:
			setattr(o, a, v)
		return self

	def __exit__(self, *exc) -> None:
		for o, a, v in reversed(self.saved):
			setattr(o, a, v)


class FakeProvider:
	name = "Doble"
	isRemote = False
	needsKey = False

	def __init__(self, answers: list[str]) -> None:
		self.answers = list(answers)
		self.calls: list[list[Message]] = []

	def isConfigured(self) -> bool:
		return True

	def chat(self, messages, system="", maxTokens=4096, effort=""):
		self.calls.append(list(messages))
		return Message("assistant", self.answers.pop(0) if self.answers else "?")


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._old = paths.DATA_DIR
		self.dir = tempfile.mkdtemp(prefix="tiresias_iapdf_")
		paths.setDataDir(self.dir)
		paths.ensureDataDirs()
		flexweb._resetForTests()
		labelstore._resetForTests()
		self._bm = dict(conf["browseMode"])
		self._ai = dict(conf["ai"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 0
		conf["browseMode"]["reportUnlabeledGraphics"] = False
		self.spoken: list[str] = []
		self._speech = _Patch((speech, "speakMessage", lambda t, *a, **k: self.spoken.append(t)))
		self._speech.__enter__()

	def tearDown(self) -> None:
		self._speech.__exit__()
		for k, v in self._bm.items():
			conf["browseMode"][k] = v
		for k, v in self._ai.items():
			conf["ai"][k] = v
		paths.setDataDir(self._old)
		flexweb._resetForTests()
		labelstore._resetForTests()
		shutil.rmtree(self.dir, ignore_errors=True)


def lines(buf: VirtualBuffer) -> list[str]:
	return [ln for ln in buf.text.split("\n") if ln.strip()]


# ====================================================================== F6: orden de lectura
class ReadingOrderTests(Base):
	def test_apply_order_keeps_unlisted_after_their_predecessor(self) -> None:
		items = ["a", "b", "x", "c", "y"]
		# Los no listados van pegados al elemento que los precedía.
		self.assertEqual(reading_order.applyOrder(items, items, ["c", "a", "b"]), ["c", "y", "a", "b", "x"])
		self.assertEqual(reading_order.applyOrder(items, items, ["b", "a"]), ["b", "x", "c", "y", "a"])
		self.assertEqual(reading_order.applyOrder(["x", "a", "b"], ["x", "a", "b"], ["b", "a"]), ["x", "b", "a"])

	def test_duplicate_texts_get_distinct_keys(self) -> None:
		keys = reading_order.keysFor([group(text("Nota")), group(text("Nota")), group(text("Otra"), P_AUTOMATIONID="id1")])
		self.assertEqual(len(set(keys)), 3)
		self.assertTrue(keys[1].endswith("~1"))
		self.assertTrue(keys[2].endswith("#id1"))

	def test_manual_move_before_and_after(self) -> None:
		root = doc(group(text("Uno")), group(text("Dos")), group(text("Tres")))
		buf = build(root)
		nodes = {buf.text[n.start : n.end].strip(): n for n in buf.root.children}
		op = reading_order.planMove(buf, nodes["Tres"], nodes["Uno"], after=False)
		self.assertIsNotNone(op)
		self.assertEqual(op["container"], reading_order.ROOT_KEY)
		buf2 = build(root, reading_order.ReadingOrder([op]))
		self.assertEqual(lines(buf2), ["Tres", "Uno", "Dos"])
		# Se mueve sobre el orden actual (el ya cambiado).
		nodes2 = {buf2.text[n.start : n.end].strip(): n for n in buf2.root.children}
		op2 = reading_order.planMove(buf2, nodes2["Tres"], nodes2["Dos"], after=True)
		buf3 = build(root, reading_order.ReadingOrder([op, op2]))
		self.assertEqual(lines(buf3), ["Uno", "Dos", "Tres"])
		# Deshacer la última operación devuelve el orden anterior.
		self.assertEqual(lines(build(root, reading_order.ReadingOrder([op]))), ["Tres", "Uno", "Dos"])

	def test_move_across_containers_moves_the_enclosing_block(self) -> None:
		root = doc(group(group(text("A1")), group(text("A2"))), group(group(text("B1"))))
		buf = build(root)
		b1 = next(n for n in buf.nodes if n.role == Role.STATICTEXT and n.name == "B1")
		a1 = next(n for n in buf.nodes if n.role == Role.STATICTEXT and n.name == "A1")
		op = reading_order.planMove(buf, buf.textUnitOf(b1), buf.textUnitOf(a1), after=False)
		self.assertIsNotNone(op)
		self.assertEqual(lines(build(root, reading_order.ReadingOrder([op]))), ["B1", "A1", "A2"])
		# Un bloque no se puede mover dentro de sí mismo.
		self.assertIsNone(reading_order.planMove(buf, buf.root.children[0], a1, after=True))

	def test_nested_container_and_partial_rebuild(self) -> None:
		inner = group(text("primero"), text("segundo"), text("tercero"), P_AUTOMATIONID="col")
		root = doc(group(text("Título")), inner)
		buf = build(root)
		col = next(n for n in buf.nodes if n.automationId == "col")
		op = reading_order.planOrder(buf, col, [col.children[2], col.children[0], col.children[1]])
		self.assertEqual(op["container"].split("#")[-1], "col")
		order = reading_order.ReadingOrder([op])
		full = build(root, order)
		self.assertLess(full.text.index("tercero"), full.text.index("primero"))
		# Una actualización parcial del bloque conserva el orden propio.
		sub = VirtualBuffer(inner)
		sub.readingOrder = order
		block = full.byRid[inner.rid]
		sub.rootParent = block.parent
		sub.build()
		full.spliceSubtree(block, sub)
		self.assertEqual(full.text, build(root, order).text)

	def test_ops_storage_undo_and_scope(self) -> None:
		key = "https://ejemplo.com/doc.pdf"
		other = "https://ejemplo.com/otro.pdf"
		flexweb.addReadingOrderOp(key, {"container": "c", "order": ["a", "b"]})
		flexweb.addReadingOrderOp(key, {"container": "c", "order": ["b", "a"]})
		self.assertEqual(len(flexweb.readingOrderOps(key)), 2)
		self.assertEqual(flexweb.readingOrderOps(other), [])
		self.assertEqual(flexweb.readingOrderScope(key), "document")
		self.assertEqual(flexweb.toggleReadingOrderScope(key), "site")
		self.assertEqual(len(flexweb.readingOrderOps(other)), 2)
		self.assertEqual(flexweb.toggleReadingOrderScope(other), "document")
		self.assertEqual(flexweb.readingOrderOps(key), [])
		self.assertEqual(flexweb.undoReadingOrder(other), 1)
		self.assertEqual(flexweb.undoReadingOrder(other, everything=True), 0)
		self.assertEqual(flexweb.undoReadingOrder(other), -1)
		self.assertEqual(flexweb.allSites(), {})


class AiReadingOrderTests(Base):
	def test_parse_order(self) -> None:
		self.assertEqual(reading.parseOrder("3, 1, 2", 3), [2, 0, 1])
		self.assertEqual(reading.parseOrder("Orden: 2, 2, 9, 1", 4), [1, 0, 2, 3])
		self.assertIsNone(reading.parseOrder("no sé", 4))

	def test_suggest_order_with_confirmation(self) -> None:
		root = doc(group(text("Pie de página")), group(text("Introducción")), group(text("Desarrollo")))
		buf = build(root)

		class FakeDoc:
			def __init__(self) -> None:
				self.buffer = buf
				self.caret = 0
				self.rebuilt = 0

			def _documentKey(self) -> str:
				return "file:///C:/docs/informe.pdf"

			def requestRebuild(self) -> None:
				self.rebuilt += 1

		fake = FakeDoc()
		provider = FakeProvider(["2, 3, 1"])
		shown = []
		done = threading.Event()

		def confirm(title, preview, accept):
			shown.append(preview)
			accept()
			done.set()

		from tiresias.gui import ai_dialogs

		with _Patch((assistant, "currentBrowseDocument", lambda: fake), (assistant, "getProvider", lambda *a: provider), (ai_dialogs, "showOrderConfirm", confirm)):
			reading.suggestReadingOrder()
			self.assertTrue(done.wait(5))
		self.assertIn("1. Introducción", shown[0])
		self.assertIn("[1]", provider.calls[0][0].text)
		ops = flexweb.readingOrderOps(fake._documentKey())
		self.assertEqual(len(ops), 1)
		self.assertEqual(fake.rebuilt, 1)
		self.assertEqual(lines(build(root, reading_order.ReadingOrder(ops))), ["Introducción", "Desarrollo", "Pie de página"])


# ====================================================================== F6/F9: textos de IA en el búfer
def image(**props) -> FakeEl:
	props.setdefault("BOUNDINGRECT", (10, 10, 50, 40))
	return FakeEl(uc.CT_IMAGE, "", [], **{("P_" + k if not k.startswith("P_") else k): v for k, v in props.items()})


class AiLabelBufferTests(Base):
	def test_alt_text_is_used_in_buffer(self) -> None:
		key = "file:///C:/docs/informe.pdf"
		img1, img2 = image(), image()
		root = doc(group(text("Figura"), img1, img2, name="Resultados"))
		buf = build(root)
		self.assertNotIn("gráfico", buf.text)
		n1, n2 = buf.byRid[img1.rid], buf.byRid[img2.rid]
		self.assertNotEqual(labelstore.fingerprint(n1), labelstore.fingerprint(n2))
		labelstore.setLabel(key, n2, "Gráfico de barras de ventas")
		self.assertEqual(labelstore.scopeFor(key, n2), key)
		lookup = labelstore.lookupFor(key)
		buf2 = build(root, ai=lookup)
		self.assertIn("Gráfico de barras de ventas", buf2.text)
		self.assertEqual(buf2.byRid[img2.rid].name, "Gráfico de barras de ventas")
		self.assertFalse(buf2.byRid[img2.rid].unlabeled)
		self.assertEqual(buf2.byRid[img1.rid].name, "")
		# Otro documento no lo ve; el sitio guarda los botones.
		self.assertIsNone(labelstore.lookupFor("file:///C:/otra/cosa.pdf"))

	def test_describe_unlabeled_images_job(self) -> None:
		import time

		img1, img2 = image(), image(P_BOUNDINGRECT=(10, 60, 50, 40))
		root = doc(group(text("Informe"), img1, img2))
		buf = build(root)
		key = "file:///C:/docs/informe.pdf"

		class FakeDoc:
			rootObject = None

			def __init__(self) -> None:
				self.buffer = buf
				self.caret = 0
				self.rebuilt = 0

			def _documentKey(self) -> str:
				return key

			def requestRebuild(self) -> None:
				self.rebuilt += 1

		fake = FakeDoc()
		provider = FakeProvider(["Logotipo de la empresa.", "Gráfico de líneas con la evolución de las ventas."])
		tiny = imaging.Image(bytes(range(64)), 4, 4)
		conf["ai"]["altTextMaxImages"] = 20
		with _Patch(
			(assistant, "currentBrowseDocument", lambda: fake),
			(assistant, "getProvider", lambda *a: provider),
			(assistant, "liveRect", lambda el: (10, 10, 50, 40)),
			(imaging, "captureRect", lambda *a, **k: tiny),
			(imaging, "virtualScreenRect", lambda: (0, 0, 1920, 1080)),
			(queue_handler, "callLater", lambda ms, f, *a: f(*a) or 1),
		):
			reading.describeUnlabeledImages()
			deadline = time.monotonic() + 5
			while reading._job is not None and time.monotonic() < deadline:
				time.sleep(0.02)
		self.assertIsNone(reading._job)
		self.assertTrue(any("2 imágenes descritas" in s for s in self.spoken), self.spoken)
		self.assertEqual(fake.rebuilt, 1)
		buf2 = build(root, ai=labelstore.lookupFor(key))
		self.assertIn("Logotipo de la empresa.", buf2.text)
		self.assertIn("evolución de las ventas", buf2.text)
		# Ya no quedan imágenes sin descripción.
		self.assertEqual(reading.unlabeledImages(buf2), [])

	def test_button_label_is_per_site(self) -> None:
		btn = FakeEl(uc.CT_BUTTON, "", [], P_BOUNDINGRECT=(0, 0, 24, 24))
		root = doc(group(btn, name="Barra"))
		buf = build(root)
		node = buf.byRid[btn.rid]
		labelstore.setLabel("https://ejemplo.com/a", node, "Buscar")
		self.assertEqual(labelstore.scopeFor("https://ejemplo.com/a", node), "ejemplo.com")
		buf2 = build(root, ai=labelstore.lookupFor("https://ejemplo.com/otra-pagina"))
		self.assertIn("Buscar", buf2.text)
		self.assertEqual(labelstore.scopesForSite("ejemplo.com"), {"ejemplo.com": 1})
		labelstore.removeScope("ejemplo.com")
		self.assertIsNone(labelstore.lookupFor("https://ejemplo.com/a"))


# ====================================================================== F9: etiquetado automático
class AutoLabelTests(Base):
	def _doc(self, root):
		buf = build(root)

		class FakeDoc:
			rootObject = None

			def __init__(self) -> None:
				self.buffer = buf
				self.caret = 0
				self.rebuilds = []

			def _documentKey(self) -> str:
				return "https://ejemplo.com/pagina"

			def scheduleRebuild(self, ms: int = 600) -> None:
				self.rebuilds.append(ms)

		return FakeDoc(), buf

	def test_targets_in_buffer(self) -> None:
		btn = FakeEl(uc.CT_BUTTON, "", [], P_BOUNDINGRECT=(0, 0, 24, 24))
		named = FakeEl(uc.CT_BUTTON, "Enviar", [])
		link = FakeEl(uc.CT_HYPERLINK, "", [])
		img = image()
		_d, buf = self._doc(doc(group(btn, named, link, img)))
		self.assertIs(autolabel.unlabeledBufferTarget(buf, buf.byRid[btn.rid]), buf.byRid[btn.rid])
		self.assertIsNone(autolabel.unlabeledBufferTarget(buf, buf.byRid[named.rid]))
		self.assertIs(autolabel.unlabeledBufferTarget(buf, buf.byRid[link.rid]), buf.byRid[link.rid])
		self.assertIs(autolabel.unlabeledBufferTarget(buf, buf.byRid[img.rid]), buf.byRid[img.rid])

	def test_background_request_announces_and_saves(self) -> None:
		btn = FakeEl(uc.CT_BUTTON, "", [], P_BOUNDINGRECT=(100, 100, 24, 24))
		fake, buf = self._doc(doc(group(btn, name="Barra de herramientas")))
		node = buf.byRid[btn.rid]
		fake.caret = node.start
		provider = FakeProvider(["«Buscar».", "Otra"])
		conf["ai"]["autoLabel"] = True
		conf["ai"]["autoLabelMaxPerHour"] = 1
		labeler = autolabel.AutoLabeler()
		done = threading.Event()
		orig = labeler._done

		def doneHook(cand, label):
			orig(cand, label)
			done.set()

		labeler._done = doneHook
		tiny = imaging.Image(bytes(range(64)), 4, 4)
		with _Patch((assistant, "getProvider", lambda *a: provider), (imaging, "captureRect", lambda *a, **k: tiny), (imaging, "virtualScreenRect", lambda: (0, 0, 1920, 1080))):
			cand = labeler.candidateForNode(fake, node)
			self.assertIsNotNone(cand)
			self.assertIn("Barra de herramientas", cand.info)
			self.assertTrue(labeler.isStillCurrent(cand))
			self.assertTrue(labeler.request(cand))
			self.assertTrue(done.wait(5))
			# Cada elemento se intenta una vez y hay un máximo por hora.
			self.assertFalse(labeler.request(cand))
			other = autolabel.Candidate(key=("obj", "x", "y"), rect=(0, 0, 10, 10), hwnd=0, isGraphic=False, info="")
			self.assertFalse(labeler.request(other))
		self.assertIn("Etiqueta de IA: Buscar", self.spoken)
		self.assertEqual(labelstore.get("https://ejemplo.com/pagina", node), "Buscar")
		self.assertEqual(fake.rebuilds, [1500])
		self.assertTrue(any("máximo" in s for s in self.spoken))
		self.assertEqual(len(provider.calls), 1)
		self.assertTrue(provider.calls[0][0].images)

	def test_disabled_by_default_and_toggle(self) -> None:
		self.assertFalse(conf.defaults["ai"]["autoLabel"])
		labeler = autolabel.AutoLabeler()
		conf["ai"]["autoLabel"] = False
		labeler.toggle()
		self.assertTrue(conf["ai"]["autoLabel"])
		labeler.toggle()
		self.assertFalse(conf["ai"]["autoLabel"])
		# Desactivado: los eventos no hacen nada.
		labeler.onFocus(object())
		self.assertIsNone(labeler._pending)


# ====================================================================== F10: explorar la página
class ExplorerTests(Base):
	def _fakeDoc(self):
		form = FakeEl(uc.CT_GROUP, "Contacto", [FakeEl(uc.CT_EDIT, "Correo", []), FakeEl(uc.CT_BUTTON, "Enviar", [])], P_LANDMARKTYPE=uc.LANDMARK_FORM, P_BOUNDINGRECT=(0, 300, 400, 100))
		head = FakeEl(uc.CT_TEXT, "Ofertas", [], P_HEADINGLEVEL=uc.HEADINGLEVEL_NONE + 2, P_BOUNDINGRECT=(0, 50, 300, 30))
		root = FakeEl(uc.CT_DOCUMENT, "Tienda", [head, group(text("Precios bajos")), form], P_BOUNDINGRECT=(0, 0, 800, 600))
		buf = build(root)

		class FakeRoot:
			name = "Tienda"

		class FakeDoc:
			rootObject = FakeRoot()

			def __init__(self) -> None:
				self.buffer = buf
				self.caret = 0

			def _documentKey(self) -> str:
				return "https://tienda.example/"

		return FakeDoc()

	def test_structure_and_keys(self) -> None:
		fake = self._fakeDoc()
		s = explorer.bufferStructure(fake)
		self.assertIn("nivel 2: Ofertas (x=0, y=50", s)
		self.assertIn("Contacto formulario", s)
		self.assertIn("Correo", s)
		from tiresias.browse.document import BrowseModeDocument

		keys = explorer.keyTable(BrowseModeDocument)
		self.assertTrue(any("encabezado" in k for k in keys))
		self.assertTrue(all(":" in k for k in keys))
		prompt = explorer.buildPrompt(s, "\n".join(keys), "texto")
		for tag in ("<estructura>", "<teclas>", "<texto>"):
			self.assertIn(tag, prompt)

	def test_explore_sends_session_with_structure(self) -> None:
		fake = self._fakeDoc()
		calls = []
		conf["ai"]["exploreWithScreenshot"] = False
		with _Patch((assistant, "currentBrowseDocument", lambda: fake), (assistant, "getProvider", lambda *a: FakeProvider([])), (assistant, "startSession", lambda *a, **k: calls.append((a, k)))):
			explorer.explorePage()
		self.assertEqual(len(calls), 1)
		args, kw = calls[0]
		self.assertIn("Tienda", args[0])
		self.assertIn("<estructura>", args[1])
		self.assertIn("Diseño visual", args[1])
		self.assertIn("explorador de páginas", kw["system"])


# ====================================================================== F12: CAPTCHA
class CaptchaTests(Base):
	def _page(self):
		box = FakeEl(uc.CT_CHECKBOX, "No soy un robot", [])
		frame1 = FakeEl(uc.CT_DOCUMENT, "reCAPTCHA", [box])
		audio = FakeEl(uc.CT_BUTTON, "Obtener un desafío de audio", [])
		play = FakeEl(uc.CT_BUTTON, "Reproducir", [])
		frame2 = FakeEl(uc.CT_DOCUMENT, "el desafío recaptcha caduca dentro de dos minutos", [audio, play])
		video = FakeEl(uc.CT_BUTTON, "Reproducir vídeo", [])
		root = doc(group(text("Formulario de alta")), video, frame1, frame2)
		return build(root), box, audio, play, video

	def test_classify_and_detect(self) -> None:
		self.assertEqual(captcha.classify(["Widget containing checkbox for hCaptcha security challenge"]), "hcaptcha")
		self.assertEqual(captcha.classify(["Widget containing a Cloudflare security challenge"]), "turnstile")
		self.assertEqual(captcha.classify(["captcha_image"]), "generic")
		self.assertIsNone(captcha.classify(["Iniciar sesión"]))
		buf, *_rest = self._page()
		self.assertEqual(captcha.detect(buf.nodes), "recaptcha")
		plain = build(doc(group(text("Un artículo que habla de captcha"))))
		self.assertIsNone(captcha.detect(plain.nodes))
		# El distintivo de reCAPTCHA invisible no es un reto.
		badge = build(doc(group(FakeEl(uc.CT_DOCUMENT, "reCAPTCHA", []), P_CLASSNAME="grecaptcha-badge")))
		self.assertIsNone(captcha.detect(badge.nodes))

	def test_targets_prefer_inside_captcha(self) -> None:
		buf, box, audio, play, video = self._page()
		t = captcha.findTargets(buf.nodes)
		self.assertIs(t["play"], buf.byRid[play.rid])
		self.assertIs(t["audio"], buf.byRid[audio.rid])
		self.assertIs(t["checkbox"], buf.byRid[box.rid])

	def test_jump_then_play_and_duck(self) -> None:
		buf, box, audio, play, video = self._page()

		class FakeDoc:
			def __init__(self) -> None:
				self.buffer = buf
				self.caret = 0
				self.activated = []

			def _moveCaret(self, offset, node=None):
				self.caret = offset

			def activateAt(self, offset):
				self.activated.append(offset)

		fake = FakeDoc()
		later = []
		with _Patch((assistant, "currentBrowseDocument", lambda: fake), (queue_handler, "callLater", lambda ms, f, *a: later.append(f) or 1)):
			captcha.jumpToAudio()
			self.assertEqual(fake.caret, buf.byRid[play.rid].start)
			captcha.jumpToAudio()
		self.assertEqual(fake.activated, [buf.byRid[play.rid].start])
		self.assertIn(captcha.duck, later)

	def test_duck_lower_and_mute(self) -> None:
		class Player:
			volume = 0.8

		player = Player()
		conf["ai"]["captchaDuckMode"] = "lower"
		conf["ai"]["captchaDuckVolume"] = 25
		with _Patch((captcha, "_player", lambda: player), (queue_handler, "callLater", lambda ms, f, *a: 1), (queue_handler, "cancelCallLater", lambda t: None)):
			captcha.duck(5)
			self.assertAlmostEqual(player.volume, 0.2)
			self.assertTrue(captcha.restoreVoice(quiet=True))
			self.assertAlmostEqual(player.volume, 0.8)
			conf["ai"]["captchaDuckMode"] = "mute"
			captcha.duck(5)
			self.assertIn(captcha._muteFilter, speech.api.filter_speechSequence.handlers())
			self.assertTrue(captcha.restoreVoice(quiet=True))
			self.assertNotIn(captcha._muteFilter, speech.api.filter_speechSequence.handlers())
			self.assertFalse(captcha.restoreVoice(quiet=True))
			conf["ai"]["captchaDuckMode"] = "off"
			captcha.duck(5)
			self.assertFalse(captcha.isDucked())

	def test_announce_once_per_page(self) -> None:
		captcha._announced.clear()
		self.assertTrue(captcha._announceOnce("pagina", "recaptcha"))
		self.assertFalse(captcha._announceOnce("pagina", "recaptcha"))
		self.assertTrue(any("reCAPTCHA" in s for s in self.spoken))
		self.assertIn("cookie de accesibilidad", captcha.announcement("hcaptcha"))


# ====================================================================== órdenes y opciones
class CommandsTests(unittest.TestCase):
	def test_scripts_and_gestures(self) -> None:
		from tiresias.browse.document import BrowseModeDocument
		from tiresias.vision_commands import VisionCommands, menuActions

		for name in ("aiExplorePage", "aiToggleAutoLabel", "aiReadingOrder", "aiDescribeUnlabeledImages", "captchaAudio", "captchaDuck"):
			self.assertTrue(hasattr(VisionCommands, "script_" + name), name)
		self.assertEqual(VisionCommands.script_aiExplorePage.gestures, ["kb:tiresias+shift+e"])
		self.assertEqual(VisionCommands.script_captchaAudio.gestures, ["kb:tiresias+control+shift+u"])
		gestures = dict(BrowseModeDocument.iterClassGestures())
		self.assertEqual(gestures.get("kb:tiresias+control+shift+m"), "flexMarkBlock")
		self.assertEqual(gestures.get("kb:tiresias+control+shift+a"), "flexMoveBlockBefore")
		self.assertEqual(gestures.get("kb:tiresias+control+shift+d"), "flexMoveBlockAfter")
		self.assertEqual(gestures.get("kb:tiresias+control+shift+z"), "flexUndoReadingOrder")
		labels = [label for _g, label, _f in menuActions()]
		self.assertIn("Explorar la página (diseño visual y cómo moverse)", labels)
		self.assertIn("CAPTCHA: ir al reto de audio", labels)

	def test_option_defaults(self) -> None:
		d = conf.defaults["ai"]
		self.assertFalse(d["autoLabel"])
		self.assertTrue(d["captchaDetect"])
		self.assertEqual(d["captchaDuckMode"], "lower")
		self.assertTrue(d["exploreWithScreenshot"])
		self.assertEqual(d["altTextMaxImages"], 20)


if __name__ == "__main__":
	unittest.main()
