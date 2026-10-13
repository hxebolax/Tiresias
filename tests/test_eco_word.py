"""Escribir en Word: lo único que se dice es el eco de teclado.

Al escribir en Word, el botón «Contar palabras» de la barra de estado cambia de
nombre («Contar palabras 12 palabras»). La interfaz de Office (NetUI) publica
LiveSetting «asertivo» en todos sus elementos, y Tiresias trataba ese cambio de
nombre como una región viva: tras cada palabra se oía el recuento como
coletilla. NVDA no lo dice.
"""

from __future__ import annotations

import os
import sys
import unittest
from unittest import mock

sys.coinit_flags = 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from comtypes.automation import VARIANT  # noqa: E402

from tiresias import typing_echo  # noqa: E402
from tiresias.a11y import uia_handler  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.config import conf  # noqa: E402


class FakeElement:
	"""Elemento UIA con propiedades en caché (lo que llega en un evento)."""

	def __init__(self, className: str, live: int = 2, controlType: int = 50000, pid: int = 4242, rid=(42, 1)):
		self.props = {
			uc.P_CLASSNAME: className,
			uc.P_LIVESETTING: live,
			uc.P_CONTROLTYPE: controlType,
			uc.P_PROCESSID: pid,
			uc.P_RUNTIMEID: list(rid),
		}

	def GetCachedPropertyValue(self, propId):
		return self.props.get(propId, 0)


def _queued(handler, element, *, event=None):
	with mock.patch.object(uia_handler.queue_handler, "queueFunction") as q, mock.patch.object(uia_handler, "_focusRid", (9, 9)):
		if event is None:
			handler.IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(element, uc.P_NAME, VARIANT("x"))
		else:
			handler.IUIAutomationEventHandler_HandleAutomationEvent(element, event)
	return [c.args[1:] for c in q.call_args_list]


class StatusBarTests(unittest.TestCase):
	def setUp(self):
		self.handler = uia_handler._EventHandler()

	def test_recuento_de_palabras_de_word_no_es_region_viva(self):
		# «Contar palabras 3 palabras» (NetUISimpleButton, LiveSetting 2) cambia al escribir.
		el = FakeElement("NetUISimpleButton")
		self.assertFalse(uia_handler.isImplicitLiveRegion(el))
		# No es el foco ni un control con valor: el cambio de nombre se descarta, como en NVDA.
		self.assertEqual(_queued(self.handler, el), [])

	def test_resto_de_la_barra_de_estado_de_office_tampoco(self):
		for cls in ("NetUIStickyButton", "NetUISlider", "NetUIRibbonButton"):
			with self.subTest(cls=cls):
				self.assertEqual(_queued(self.handler, FakeElement(cls)), [])

	def test_otras_regiones_vivas_implicitas_se_siguen_leyendo(self):
		el = FakeElement("TextBlock", live=1, controlType=uc.CT_TEXT)
		self.assertTrue(uia_handler.isImplicitLiveRegion(el))
		self.assertEqual(_queued(self.handler, el), [(el, "liveRegionChange")])

	def test_sin_livesetting_no_hay_region_viva(self):
		self.assertEqual(_queued(self.handler, FakeElement("TextBlock", live=0, controlType=uc.CT_TEXT)), [])

	def test_aviso_real_de_office_se_lee(self):
		# Un evento LiveRegionChanged de verdad sí se lee, venga de donde venga.
		el = FakeElement("NetUILabel")
		self.assertEqual(_queued(self.handler, el, event=uc.E_LIVEREGIONCHANGED), [(el, "liveRegionChange")])

	def test_clase_ilegible_no_rompe(self):
		class Broken:
			def GetCachedPropertyValue(self, propId):
				raise OSError("desconectado")

		self.assertTrue(uia_handler.isImplicitLiveRegion(Broken()))


class FakeDoc:
	"""Documento de Word con texto (para el eco de teclado)."""

	hasText = True
	isEditable = True
	role = None


class TypingEchoTests(unittest.TestCase):
	"""Con los valores por defecto (palabras escritas: no) solo se dicen los caracteres."""

	def setUp(self):
		typing_echo._word.clear()
		typing_echo._recent.clear()
		self._saved = {k: conf["keyboard"][k] for k in ("speakTypedCharacters", "speakTypedWords", "speakWholeEditedWord", "alertForSpellingErrors")}
		conf["keyboard"]["speakTypedCharacters"] = "always"
		conf["keyboard"]["speakTypedWords"] = "off"
		conf["keyboard"]["speakWholeEditedWord"] = True
		conf["keyboard"]["alertForSpellingErrors"] = False

	def tearDown(self):
		for k, v in self._saved.items():
			conf["keyboard"][k] = v

	def test_escribir_en_word_no_dice_palabras(self):
		from tiresias import queue_handler, speech

		doc = FakeDoc()
		with (
			mock.patch.object(speech, "speakTypedCharacter") as chars,
			mock.patch.object(speech, "speakTypedWord") as words,
			mock.patch.object(speech, "cancelSpeech"),
			mock.patch.object(queue_handler, "callLater") as later,
			mock.patch.object(typing_echo, "checkFormatAfterTyping"),
		):
			# Se edita una palabra que ya existía (sin separador antes) y se cierra con espacio.
			typing_echo.resetWord()
			for ch in "hola mundo ":
				typing_echo.onTypedCharacter(doc, ch)
		self.assertEqual("".join(c.args[0] for c in chars.call_args_list), "hola mundo ")
		words.assert_not_called()
		later.assert_not_called()


class _FakeRange:
	def __init__(self, readOnly):
		self.readOnly = readOnly

	def GetAttributeValue(self, attrId):
		if attrId != uc.A_ISREADONLY:
			raise AssertionError(attrId)
		if isinstance(self.readOnly, Exception):
			raise self.readOnly
		return self.readOnly


class _FakeTextPattern:
	def __init__(self, readOnly):
		self.DocumentRange = _FakeRange(readOnly)


class _FakeDocElement:
	def __init__(self, props):
		self.props = props

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	GetCurrentPropertyValueEx = GetCachedPropertyValueEx


def _wordDoc(readOnly, className="_WwG"):
	"""Documento UIA de Word: sin patrón de valor (como el de verdad) y con patrón Text."""
	from tiresias.objects.uia import UIAObject

	props = {
		uc.P_CONTROLTYPE: uc.CT_DOCUMENT,
		uc.P_NAME: "Documento1",
		uc.P_CLASSNAME: className,
		uc.P_FRAMEWORKID: "Win32",
		uc.P_PROVIDERDESCRIPTION: "",
		uc.P_ISVALUEPATTERNAVAILABLE: False,
		uc.P_ISTEXTPATTERNAVAILABLE: True,
		uc.P_ISKEYBOARDFOCUSABLE: True,
		uc.P_ISENABLED: True,
		uc.P_LEGACYSTATE: 0,
	}
	pattern = _FakeTextPattern(readOnly)

	class Doc(UIAObject):
		calls = 0

		def _get_textPattern(self):
			type(self).calls += 1
			return pattern

		def _get_windowClassName(self):
			return className

		def _get_parent(self):
			return None

	return Doc(_FakeDocElement(props), windowHandle=0x1234)


class WordEditableTests(unittest.TestCase):
	"""Word editable empieza en modo foco sin búfer; la vista de lectura, en modo exploración."""

	def test_documento_editable(self):
		from tiresias import browse
		from tiresias.objects.roles import State

		doc = _wordDoc(False)
		self.assertIn(State.EDITABLE, doc.states)
		self.assertNotIn(State.READONLY, doc.states)
		self.assertTrue(doc.isEditable)
		self.assertEqual(browse.browseModeKind(doc), "lazyText")

	def test_vista_de_lectura_vista_protegida_y_panel_de_outlook(self):
		from tiresias import browse
		from tiresias.objects.roles import State

		doc = _wordDoc(True)
		self.assertIn(State.READONLY, doc.states)
		self.assertNotIn(State.EDITABLE, doc.states)
		self.assertEqual(browse.browseModeKind(doc), "text")

	def test_valor_mixto_es_editable(self):
		# Formulario protegido con campos rellenables: parte del texto se puede editar.
		from tiresias import browse

		self.assertEqual(browse.browseModeKind(_wordDoc(object())), "lazyText")

	def test_error_de_uia_se_trata_como_editable(self):
		import comtypes

		from tiresias import browse

		self.assertEqual(browse.browseModeKind(_wordDoc(comtypes.COMError(-2147220991, "desconectado", (None,) * 5))), "lazyText")

	def test_se_consulta_una_sola_vez(self):
		doc = _wordDoc(False)
		for _ in range(5):
			doc._isEditableWordDocument()
		self.assertEqual(type(doc).calls, 1)

	def test_otros_documentos_sin_patron_de_valor_siguen_de_solo_lectura(self):
		from tiresias.objects.roles import State

		doc = _wordDoc(False, className="RichTextBox")
		self.assertIn(State.READONLY, doc.states)
		self.assertEqual(type(doc).calls, 0)

	def test_word_editable_empieza_en_modo_foco_sin_bufer(self):
		from tiresias.browse.document import BrowseModeDocument

		with mock.patch.object(BrowseModeDocument, "requestRebuild") as rebuild:
			ti = BrowseModeDocument(_wordDoc(False))
			self.assertEqual(ti.bufferKind, "lazyText")
			self.assertTrue(ti.passThrough)
			self.assertIsNone(ti.buffer)
			rebuild.assert_not_called()
			ro = BrowseModeDocument(_wordDoc(True))
			self.assertEqual(ro.bufferKind, "text")
			rebuild.assert_called_once()


if __name__ == "__main__":
	unittest.main()
