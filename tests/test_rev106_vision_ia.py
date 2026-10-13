"""Revisión 1.0.6: visión, OCR, lupa e inteligencia artificial.

Una prueba de regresión por cada fallo corregido en la auditoría. No se hace
ninguna petición real ni se toca la pantalla: las llamadas a Windows, a la
interfaz y a los servicios de IA se sustituyen por dobles.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import threading
import time
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import imaging, magnifier, ocr, queue_handler, speech, vision  # noqa: E402, F401
from tiresias.ai import assistant  # noqa: E402, F401  (registra las opciones de «ai»)
from tiresias.config import conf  # noqa: E402


def _now(f, *a, **k):
	return f(*a, **k)


class _SyncThread:
	"""Sustituto de ``threading.Thread`` que ejecuta el trabajo en el acto."""

	def __init__(self, target=None, name="", daemon=None, args=(), kwargs=None) -> None:
		self.target = target
		self.args = args
		self.kwargs = kwargs or {}

	def start(self) -> None:
		self.target(*self.args, **self.kwargs)


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self.spoken: list[str] = []
		self._saved = {s: dict(conf[s]) for s in ("ocr", "ai", "magnifier", "vision")}
		patches = [
			mock.patch.object(speech, "speakMessage", side_effect=lambda t, *a, **k: self.spoken.append(t)),
			mock.patch.object(speech, "speakText", side_effect=lambda t, *a, **k: self.spoken.append(t)),
			mock.patch.object(speech, "cancelSpeech", lambda *a, **k: None),
			mock.patch.object(queue_handler, "queueFunction", side_effect=_now),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self) -> None:
		for sec, values in self._saved.items():
			for k, v in values.items():
				conf[sec][k] = v


def _words(*texts):
	return [ocr.OcrWord(t, 10 * i, 10, 8, 8) for i, t in enumerate(texts)]


def _result(source=("rect", (0, 0, 100, 50), 0), title="Prueba", texts=("Hola", "mundo")):
	return ocr.OcrResult([ocr.OcrLine(_words(*texts))], title, source)


# ====================================================================== 1. refresco automático del OCR
class OcrRefreshTests(Base):
	def setUp(self) -> None:
		super().setUp()
		self._oldLast, self._oldTimer = ocr._lastResult, ocr._refreshTimer
		self.addCleanup(self._restore)

	def _restore(self) -> None:
		ocr._lastResult, ocr._refreshTimer = self._oldLast, self._oldTimer

	def test_refresh_ignores_file_and_clipboard_sources(self) -> None:
		from tiresias.gui import ocr_viewer

		conf["ocr"]["autoRefresh"] = True
		for source in (("file", "x.png"), ("clipboard",)):
			ocr._lastResult = _result(source)
			with mock.patch.object(ocr_viewer, "isOpen", return_value=True), mock.patch.object(ocr, "recognizeRect") as rec:
				ocr._refresh()  # antes: ValueError al desempaquetar
			rec.assert_not_called()

	def test_file_result_cancels_pending_refresh(self) -> None:
		from tiresias.gui import ocr_viewer

		ocr._refreshTimer = 4242
		with mock.patch.object(queue_handler, "cancelCallLater") as cancel, mock.patch.object(ocr_viewer, "show"):
			ocr._showFileResult(_result(("file", "x.png")))
		cancel.assert_called_once_with(4242)
		self.assertIsNone(ocr._refreshTimer)

	def test_stale_refresh_does_not_overwrite_new_result(self) -> None:
		from tiresias.gui import ocr_viewer

		fileResult = _result(("file", "x.png"), texts=("archivo",))
		ocr._lastResult = fileResult
		with mock.patch.object(ocr_viewer, "isOpen", return_value=True), mock.patch.object(ocr_viewer, "update") as upd:
			ocr._showResult(_result(texts=("pantalla",)), refresh=True)
		upd.assert_not_called()
		self.assertIs(ocr._lastResult, fileResult)


# ====================================================================== 2. el visor no sale en sus capturas
class OcrViewerCaptureTests(Base):
	def test_viewer_excluded_from_capture(self) -> None:
		from tiresias.gui import ocr_viewer

		class FakeDialog:
			def __init__(self, result) -> None:
				self.document = None

			def GetHandle(self) -> int:
				return 31337

		old = ocr_viewer._dialog
		self.addCleanup(setattr, ocr_viewer, "_dialog", old)
		ocr_viewer._dialog = None
		with (
			mock.patch.object(ocr_viewer, "runOnGui", side_effect=_now),
			mock.patch.object(ocr_viewer, "OcrViewerDialog", FakeDialog),
			mock.patch.object(ocr_viewer, "_makeDocument", return_value=mock.Mock()),
			mock.patch.object(queue_handler, "queueFunction"),
			mock.patch.object(imaging, "excludeFromCapture") as excl,
		):
			ocr_viewer.show(_result())
		excl.assert_called_once_with(31337)


# ====================================================================== 3 y 4. agente de IA
class AgentTests(Base):
	def setUp(self) -> None:
		super().setUp()
		from tiresias.ai.agent import ScreenAgent
		from tiresias.gui import ai_dialogs

		self.ag = ScreenAgent()
		p = mock.patch.object(ai_dialogs, "closeAgentConfirm", lambda: None)
		p.start()
		self.addCleanup(p.stop)

	def test_cancelled_question_stops_agent(self) -> None:
		from tiresias import gui

		self.ag.running = True
		with mock.patch.object(gui, "askText") as ask:
			self.ag._ask("¿Qué archivo?")
		onCancel = ask.call_args.args[4] if len(ask.call_args.args) > 4 else ask.call_args.kwargs["onCancel"]
		onCancel()
		self.assertFalse(self.ag.running)

	def test_action_waits_and_restores_foreground_first(self) -> None:
		from tiresias import winapi
		from tiresias.ai import agent as agentMod

		ag = self.ag
		ag.running = True
		ag.targetHwnd = 777
		ag._geom = ((0, 0, 100, 100), 100, 100)
		order: list[str] = []
		ag.executor = lambda action, geom: order.append("acción")
		scheduled = []
		with (
			mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: scheduled.append((ms, f, a))),
			mock.patch.object(winapi, "setForegroundWindow", side_effect=lambda h: order.append(f"primer plano {h}")),
			mock.patch.object(agentMod.ScreenAgent, "_isWindow", staticmethod(lambda h: True)),
		):
			ag._onChoice(agentMod.Action("key", {"keys": "control+s"}), "pulsar", "yes")
			# La acción no se hace en el acto (el diálogo aún tiene el foco).
			self.assertEqual(order, [])
			self.assertEqual(scheduled[0][0], agentMod.ACTION_DELAY_MS)
			self.assertGreaterEqual(agentMod.ACTION_DELAY_MS, 250)
			ms, f, a = scheduled[0]
			f(*a)
		self.assertEqual(order, ["primer plano 777", "acción"])

	def test_step_captures_target_not_tiresias_dialog(self) -> None:
		from tiresias import winapi
		from tiresias.ai import agent as agentMod
		from tiresias.ai.providers import Message

		ag = self.ag
		ag.running = True
		ag.targetHwnd = 777
		captured = []

		class Prov:
			def chat(self, *a, **k):
				return Message("assistant", '{"action": "done", "message": "hecho"}')

		with (
			mock.patch.object(winapi, "getForegroundWindow", return_value=555),
			mock.patch.object(winapi, "getAncestor", side_effect=lambda h, f=2: h),
			mock.patch.object(winapi, "getWindowRect", return_value=(0, 0, 40, 30)),
			mock.patch.object(winapi, "getWindowText", return_value="Bloc de notas"),
			mock.patch.object(agentMod.ScreenAgent, "_isOwnWindow", staticmethod(lambda h: h == 555)),
			mock.patch.object(agentMod.ScreenAgent, "_isWindow", staticmethod(lambda h: h in (555, 777))),
			mock.patch.object(imaging, "captureRect", side_effect=lambda r, h=0: captured.append(h) or imaging.Image(bytes(40 * 30 * 4), 40, 30)),
			mock.patch.object(agentMod, "getProvider", return_value=Prov()),
			mock.patch.object(agentMod.threading, "Thread", _SyncThread),
		):
			ag._nextStep()
		self.assertEqual(captured, [777])
		self.assertFalse(ag.running)
		self.assertTrue(any("hecho" in m for m in self.spoken))

	def test_start_refuses_own_window_as_target(self) -> None:
		from tiresias import winapi
		from tiresias.ai import agent as agentMod

		prov = mock.Mock(isConfigured=lambda: True)
		with (
			mock.patch.object(agentMod, "getProvider", return_value=prov),
			mock.patch.object(winapi, "getForegroundWindow", return_value=555),
			mock.patch.object(winapi, "getAncestor", side_effect=lambda h, f=2: h),
			mock.patch.object(agentMod.ScreenAgent, "_isOwnWindow", staticmethod(lambda h: True)),
		):
			self.ag.start("guarda el archivo")
		self.assertFalse(self.ag.running)

	def test_confirm_dialog_closes_before_answering(self) -> None:
		from tiresias.gui import ai_dialogs

		order: list[str] = []
		fake = types.SimpleNamespace(_answered=False, callback=lambda c: order.append("respuesta " + c), Destroy=lambda: order.append("cerrar"))
		ai_dialogs.AgentConfirmDialog.answer(fake, "yes")
		ai_dialogs.AgentConfirmDialog.answer(fake, "no")
		self.assertEqual(order, ["cerrar", "respuesta yes", "cerrar"])


# ====================================================================== 5. ayuda con el manual
_HTML = """<html><body><nav aria-labelledby="indice"><h2 id="indice">Índice</h2><ul><li>1. Voz</li><li>2. Visión</li></ul></nav>
<h2 id="voz">1. La voz</h2><p>Capítulo de la voz.</p>
<h3>1.1. Velocidad</h3><p>{relleno} Cambia la velocidad de la síntesis con Control+Tiresias+Flechas.</p>
<h2 id="vision">2. Visión</h2><p>Capítulo de visión.</p>
<h3>2.1. Cortina de pantalla</h3><p>La cortina de pantalla se activa con Tiresias+Control+Escape. {relleno}</p>
<h3>2.2. Lupa</h3><p>{relleno} La lupa amplía la pantalla.</p>
</body></html>"""


class ManualHelpTests(Base):
	def setUp(self) -> None:
		super().setUp()
		from tiresias.gui import dialogs

		self.assistant = assistant
		self.data = assistant.parseManual(_HTML.format(relleno="texto de relleno " * 200), dialogs.htmlToText)

	def test_sections_split_by_h3_with_index(self) -> None:
		titles = [s.title for s in self.data["sections"]]
		self.assertIn("2. Visión > 2.1. Cortina de pantalla", titles)
		self.assertIn("1. Voz", self.data["index"])

	def test_relevant_sections_chosen_when_manual_too_long(self) -> None:
		text, cut = self.assistant.selectManualContext("¿Cómo activo la cortina?", 5000, self.data)
		self.assertTrue(cut)
		self.assertLessEqual(len(text), 5000)
		self.assertIn("Tiresias+Control+Escape", text)
		self.assertNotIn("Control+Tiresias+Flechas", text)
		self.assertIn("Índice del manual", text)
		full, cut2 = self.assistant.selectManualContext("cortina", 10**7, self.data)
		self.assertFalse(cut2)
		self.assertEqual(full, self.data["text"])

	def test_warns_when_cut(self) -> None:
		with mock.patch.object(self.assistant, "startSession") as start:
			self.assistant._askHelpWithManual("¿cortina?", "texto", True)
		self.assertTrue(any("apartados" in m for m in self.spoken))
		self.assertIn("algunos apartados", start.call_args.kwargs["system"])

	def test_manual_text_cached(self) -> None:
		from tiresias import paths

		d = tempfile.mkdtemp(prefix="tiresias_manual_")
		self.addCleanup(shutil.rmtree, d, True)
		path = os.path.join(d, "manual.html")
		with open(path, "w", encoding="utf-8") as f:
			f.write(_HTML.format(relleno="x"))
		self.assistant._manualCache.clear()
		self.addCleanup(self.assistant._manualCache.clear)
		real = self.assistant.parseManual
		with mock.patch.object(paths, "manualPath", return_value=path), mock.patch.object(self.assistant, "parseManual", side_effect=real) as parse:
			self.assertIn("cortina de pantalla", self.assistant.manualText())
			self.assistant.manualText()
			self.assertEqual(parse.call_count, 1)

	def test_help_prepares_manual_off_core_thread(self) -> None:
		threads = []
		main = threading.get_ident()
		done = threading.Event()

		def fakeData():
			threads.append(threading.get_ident())
			return {"text": "", "index": "", "sections": []}

		with (
			mock.patch.object(self.assistant, "checkProvider", return_value=mock.Mock()),
			mock.patch.object(self.assistant, "manualData", side_effect=fakeData),
			mock.patch.object(self.assistant, "_askHelpWithManual", side_effect=lambda *a: done.set()),
		):
			self.assistant.askHelp("¿Qué es la lupa?")
			self.assertTrue(done.wait(5))
		self.assertNotEqual(threads, [main])


# ====================================================================== 6. posición actual en el modo exploración
class LiveRectTests(Base):
	def _node(self, live):
		from tiresias.browse.buffer import Node

		n = Node()
		n.location = (1, 2, 3, 4)
		if live is not None:
			n.element = mock.Mock()
			n.element.GetCurrentPropertyValueEx.return_value = live
		return n

	def test_live_rect_preferred_over_stale_location(self) -> None:
		from tiresias.browse.buffer import liveNodeRect

		self.assertEqual(liveNodeRect(self._node((10, 500, 30, 40))), (10, 500, 30, 40))
		self.assertEqual(liveNodeRect(self._node(None)), (1, 2, 3, 4))
		broken = self._node((0, 0, 0, 0))
		self.assertEqual(liveNodeRect(broken), (1, 2, 3, 4))

	def test_highlight_and_magnifier_use_live_rect(self) -> None:
		from tiresias import api
		from tiresias.browse.document import BufferTextInfo

		node = self._node((10, 500, 30, 40))
		buf = mock.Mock()
		buf.nodeAt.return_value = node
		caret = types.SimpleNamespace(buffer=buf, passThrough=False, caret=0)
		with mock.patch.object(api, "getCaretObject", return_value=caret):
			self.assertEqual(vision.VisionHandler()._browseRect(), (10, 500, 30, 40))
		info = BufferTextInfo.__new__(BufferTextInfo)
		info.doc = caret
		info._start = 0
		pt = info.pointAtStart
		self.assertEqual((pt.x, pt.y), (25, 520))


# ====================================================================== 7 y 8. proveedores
class ProviderTests(Base):
	def test_openai_and_local_send_output_limit(self) -> None:
		from tiresias.ai.providers import PROVIDERS, Message

		body, _h = PROVIDERS["openai"].buildBody([Message("user", "hola")], "", 1234)
		self.assertEqual(body["max_completion_tokens"], 1234)
		self.assertNotIn("max_tokens", body)
		body, _h = PROVIDERS["local"].buildBody([Message("user", "hola")], "", 1234)
		self.assertEqual(body["max_tokens"], 1234)

	def test_anthropic_low_effort_for_short_tasks(self) -> None:
		from tiresias.ai.providers import PROVIDERS, Message

		p = PROVIDERS["anthropic"]
		for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
			conf["ai"]["anthropicModel"] = model
			body, _h = p.buildBody([Message("user", "x")], "", 2000, "low")
			self.assertEqual(body["output_config"], {"effort": "low"})
			body, _h = p.buildBody([Message("user", "x")], "", 2000)
			self.assertEqual(body["output_config"], {"effort": "medium"})

	def test_max_tokens_stop_reason_has_own_message(self) -> None:
		from tiresias.ai.providers import PROVIDERS, AIError, Message

		p = PROVIDERS["anthropic"]
		data = {"content": [{"type": "thinking", "thinking": ""}], "stop_reason": "max_tokens"}
		with mock.patch.object(type(p), "key", lambda self: "k"), mock.patch.object(type(p), "_post", lambda self, *a: data):
			with self.assertRaises(AIError) as cm:
				p.chat([Message("user", "x")], maxTokens=10)
		self.assertEqual(cm.exception.kind, "truncated")
		self.assertIn("longitud", str(cm.exception))

	def test_short_tasks_use_low_effort_and_enough_tokens(self) -> None:
		from tiresias.ai import autolabel, reading
		from tiresias.ai.providers import Message

		calls = []

		class Prov:
			name = "Doble"
			isRemote = False

			def isConfigured(self):
				return True

			def chat(self, messages, system="", maxTokens=4096, effort=""):
				calls.append((maxTokens, effort))
				return Message("assistant", "Enviar")

		png = mock.patch.object(assistant, "_imageToPng", return_value=b"png")
		cap = mock.patch.object(imaging, "captureRect", return_value=imaging.Image(b"\0" * 16, 2, 2))
		thr = [mock.patch.object(m.threading, "Thread", _SyncThread) for m in (assistant, autolabel, reading)]
		with png, cap, thr[0], thr[1], thr[2]:
			lab = autolabel.AutoLabeler()
			cand = autolabel.Candidate(key=("obj", "app", "k"), rect=(10, 10, 20, 20), hwnd=0, isGraphic=False, info="")
			with mock.patch.object(assistant, "checkProvider", return_value=Prov()), mock.patch.object(lab, "_done"):
				conf["ai"]["imagePrivacyAccepted"] = True
				self.assertTrue(lab.request(cand))
			job = reading.AltTextJob.__new__(reading.AltTextJob)
			job.__dict__.update(provider=Prov(), items=[("fp", "sc", mock.Mock(ancestors=lambda: []))], index=0, doc=None, cancelled=False)
			with mock.patch.object(assistant, "liveRect", return_value=(10, 10, 20, 20)), mock.patch.object(job, "_described"):
				job._capture()
		self.assertEqual(len(calls), 2)
		for maxTokens, effort in calls:
			self.assertGreaterEqual(maxTokens, 2000)
			self.assertEqual(effort, "low")


# ====================================================================== 9. lectura automática en modo foco
class OcrAutoSayAllTests(Base):
	def test_auto_say_all_in_focus_mode(self) -> None:
		from tiresias.ocr_document import OcrDocument
		from tiresias.speech import sayall

		conf["ocr"]["autoSayAll"] = True
		conf["ocr"]["browseModeResult"] = False
		doc = OcrDocument(_result())
		self.addCleanup(doc.close)
		self.assertTrue(doc.passThrough)
		nextHandler = mock.Mock()
		with mock.patch.object(queue_handler, "callLater") as later:
			doc.event_gainFocus(mock.Mock(), nextHandler)
			doc.event_gainFocus(mock.Mock(), nextHandler)
		self.assertEqual(nextHandler.call_count, 2)
		later.assert_called_once()
		self.assertIs(later.call_args.args[1], sayall.readText)


# ====================================================================== 10. intervalo mínimo del refresco
class OcrIntervalTests(Base):
	def test_minimum_interval_is_250(self) -> None:
		old = ocr._lastResult, ocr._refreshTimer
		self.addCleanup(lambda: (setattr(ocr, "_lastResult", old[0]), setattr(ocr, "_refreshTimer", old[1])))
		conf["ocr"]["autoRefresh"] = True
		conf["ocr"]["autoRefreshInterval"] = 250
		ocr._lastResult = _result()
		ocr._refreshTimer = None
		with mock.patch.object(queue_handler, "callLater", return_value=1) as later:
			ocr._scheduleRefresh()
		self.assertEqual(later.call_args.args[0], 250)


# ====================================================================== 11. errores de la IA en segundo plano
class BackgroundErrorTests(Base):
	def _cand(self):
		from tiresias.ai import autolabel

		return autolabel.Candidate(key=("obj", "app", "k"), rect=(10, 10, 20, 20), hwnd=0, isGraphic=False, info="")

	def test_autolabel_key_error_stops_and_refunds_quota(self) -> None:
		from tiresias.ai import autolabel
		from tiresias.ai.providers import AIError

		lab = autolabel.AutoLabeler()
		cand = self._cand()
		lab._tried.add(cand.key)
		lab._times.append(5.0)
		lab._failed(cand, AIError("Clave rechazada", 401, "auth"), 5.0)
		self.assertEqual(len(lab._times), 0)
		self.assertTrue(lab._stopped)
		self.assertFalse(lab.request(cand))
		self.assertEqual(len([m for m in self.spoken if "detenido" in m]), 1)

	def test_autolabel_quota_warns_once(self) -> None:
		from tiresias.ai import autolabel
		from tiresias.ai.providers import AIError

		lab = autolabel.AutoLabeler()
		for t in (1.0, 2.0):
			lab._times.append(t)
			lab._failed(self._cand(), AIError("Límite de uso", 429, "quota"), t)
		self.assertEqual(len(lab._times), 0)
		self.assertFalse(lab._stopped)
		self.assertGreater(lab._pausedUntil, time.monotonic())
		self.assertEqual(len(self.spoken), 1)

	def test_alt_text_stops_and_says_why(self) -> None:
		from tiresias.ai import reading
		from tiresias.ai.providers import AIError

		job = reading.AltTextJob.__new__(reading.AltTextJob)
		job.__dict__.update(items=[("a", "s", None), ("b", "s", None)], index=0, done=0, skipped=0, cancelled=False, stopReason="", doc=mock.Mock(), docKey="d")
		old = reading._job
		self.addCleanup(setattr, reading, "_job", old)
		reading._job = job
		job._described("a", "s", "", AIError("Anthropic Claude rechazó la clave.", 401, "auth"))
		self.assertTrue(job.cancelled)
		self.assertTrue(any("rechazó la clave" in m for m in self.spoken))


# ====================================================================== 12. traducciones fallidas
class TranslateFailureTests(Base):
	def test_failed_translation_not_cached(self) -> None:
		from tiresias.ai import translate

		translate._cache.clear()
		translate._failed.clear()
		self.addCleanup(translate._failed.clear)
		conf["ai"]["translateSpeech"] = True
		with mock.patch.object(translate, "translateText", side_effect=RuntimeError("sin red")):
			translate._translateForSpeech("Buenos días")
		self.assertNotIn("Buenos días", translate._cache)
		self.assertEqual(self.spoken[-1], "Buenos días")
		# El original vuelve a pasar por el filtro sin pedir otra traducción en bucle.
		with mock.patch.object(translate.threading, "Thread") as thr:
			self.assertEqual(translate.speechFilter("Buenos días"), "Buenos días")
		thr.assert_not_called()


# ====================================================================== 13. cortina: referencias de la API de ampliación
class CurtainTests(Base):
	def _patch(self, effectResult: int):

		dll = mock.Mock()
		dll.MagSetFullscreenColorEffect.return_value = effectResult
		return (
			mock.patch.object(magnifier.magApi, "dll", return_value=dll),
			mock.patch.object(magnifier.magApi, "acquire", return_value=True),
			mock.patch.object(magnifier.magApi, "release"),
		)

	def test_failed_effect_releases_api(self) -> None:

		h = vision.VisionHandler()
		p1, p2, p3 = self._patch(0)
		with p1, p2 as acq, p3 as rel:
			self.assertFalse(h._applyCurtain(True))
		acq.assert_called_once()
		rel.assert_called_once()
		self.assertFalse(h._curtainAcquired)

	def test_two_enables_acquire_once(self) -> None:

		h = vision.VisionHandler()
		p1, p2, p3 = self._patch(1)
		with p1, p2 as acq, p3 as rel, mock.patch.object(magnifier.magnifier, "active", False):
			self.assertTrue(h._applyCurtain(True))
			self.assertTrue(h._applyCurtain(True))  # curtainActive aún no se ha actualizado
			self.assertEqual(acq.call_count, 1)
			self.assertTrue(h._applyCurtain(False))
			self.assertTrue(h._applyCurtain(False))
		self.assertEqual(rel.call_count, 1)


# ====================================================================== 14, 15 y 17. lupa
class MagnifierTests(Base):
	def setUp(self) -> None:
		super().setUp()

		self.mod = magnifier
		self.mag = magnifier.Magnifier()

	def test_activation_announces_real_result(self) -> None:
		mag = self.mag
		with (
			mock.patch.object(mag, "_run", side_effect=_now),
			mock.patch.object(self.mod.magApi, "acquire", return_value=True),
			mock.patch.object(self.mod.magApi, "release") as rel,
			mock.patch.object(mag, "_apply", return_value=False),
			mock.patch.object(mag, "_destroyWindows"),
			mock.patch.object(mag, "_resetFullscreen"),
			mock.patch.object(mag, "_applyColors"),
		):
			mag.setActive(True)
		self.assertFalse(mag.active)
		rel.assert_called_once()
		self.assertEqual(self.spoken, ["No se pudo activar la lupa"])
		self.spoken.clear()
		with (
			mock.patch.object(mag, "_run", side_effect=_now),
			mock.patch.object(self.mod.magApi, "acquire", return_value=False),
		):
			mag.setActive(True)
		self.assertEqual(self.spoken, ["No se pudo activar la lupa"])
		self.spoken.clear()
		with (
			mock.patch.object(mag, "_run", side_effect=_now),
			mock.patch.object(self.mod.magApi, "acquire", return_value=True),
			mock.patch.object(mag, "_apply", return_value=True),
			mock.patch.object(mag, "_applyColors"),
		):
			mag.setActive(True)
		self.assertTrue(mag.active)
		self.assertTrue(self.spoken[0].startswith("Lupa activada"))
		mag.active = False

	def test_alters_screen_only_fullscreen(self) -> None:
		mag = self.mag
		mag.active = True
		conf["magnifier"]["view"] = "fullscreen"
		self.assertTrue(mag.altersScreen())
		conf["magnifier"]["view"] = "lens"
		conf["magnifier"]["filter"] = "invert"
		self.assertFalse(mag.altersScreen())
		mag.active = False
		conf["magnifier"]["view"] = "fullscreen"
		self.assertFalse(mag.altersScreen())

	def test_dock_reserved_only_when_changed(self) -> None:
		mag = self.mag
		mag._window = mock.Mock(hwnd=99)
		conf["magnifier"]["dockPosition"] = "top"
		with mock.patch.object(self.mod, "_shell32") as shell:
			shell.SHAppBarMessage.return_value = 1
			r1 = mag._reserveDock((0, 0, 800, 200))
			n = shell.SHAppBarMessage.call_count
			self.assertEqual(mag._reserveDock((0, 0, 800, 200)), r1)
			self.assertEqual(shell.SHAppBarMessage.call_count, n)
			mag._reserveDock((0, 0, 800, 300))
			self.assertGreater(shell.SHAppBarMessage.call_count, n)
			conf["magnifier"]["dockPosition"] = "bottom"
			n2 = shell.SHAppBarMessage.call_count
			mag._reserveDock((0, 0, 800, 300))
			self.assertGreater(shell.SHAppBarMessage.call_count, n2)
			mag._releaseDock()
		self.assertIsNone(mag._dockReserved)
		mag._window = None


# ====================================================================== 16. nada lento en el hilo del núcleo
class CoreThreadTests(Base):
	def test_tesseract_languages_in_worker_thread(self) -> None:
		seen = []
		done = threading.Event()

		class Eng:
			id = "tesseract"

			def languages(self):
				seen.append(threading.get_ident())
				return ["spa", "eng"]

			def getLanguage(self):
				return "spa"

			def setLanguage(self, lang):
				done.set()

		with mock.patch.object(ocr, "getEngine", return_value=Eng()):
			ocr.cycleLanguage()
			self.assertTrue(done.wait(5))
		self.assertNotEqual(seen, [threading.get_ident()])

	def test_clipboard_image_read_in_worker(self) -> None:

		with (
			mock.patch.object(imaging, "getClipboardFiles", return_value=[]),
			mock.patch.object(imaging, "clipboardHasImage", return_value=True),
			mock.patch.object(imaging, "getClipboardImage", return_value=imaging.Image(b"\0" * 16, 2, 2)) as get,
			mock.patch.object(ocr, "_runWorker") as run,
			mock.patch.object(assistant, "_describeImage") as desc,
		):
			ocr.recognizeClipboard()
			assistant.describeClipboardImage()
			get.assert_not_called()
			job = run.call_args.args[1]
			capture = desc.call_args.args[1]
			with mock.patch.object(ocr, "recognizeImage", return_value=[]):
				job()
			capture()
		self.assertEqual(get.call_count, 2)

	def test_window_walks_have_time_limit(self) -> None:
		from tiresias.ai import explorer

		class Slow:
			name = "objeto"
			value = ""
			role = None
			location = None

			@property
			def children(self):
				return [Slow(), Slow()]

		texts = list(assistant._iterTexts(Slow(), deadline=time.monotonic() - 1))
		self.assertEqual(texts, [])
		with mock.patch.object(explorer, "MAX_WALK_SECONDS", -1):
			out = explorer.windowStructure(Slow())
		self.assertIn("incompleta", out)


# ====================================================================== 18. lectura continua: una sola cadena
class ContinuousReaderTests(Base):
	def test_old_generation_does_not_reschedule(self) -> None:
		r = ocr.ContinuousReader()
		timers = []
		with (
			mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: timers.append((f, a)) or len(timers)),
			mock.patch.object(queue_handler, "cancelCallLater"),
		):
			r.start((0, 0, 10, 10))
			oldGen = r._generation
			r.stop(announce=False)
			r.start((0, 0, 10, 10))
			count = len(timers)
			# Un reconocimiento de la activación anterior que termina ahora no
			# crea otra cadena de temporizadores.
			r._schedule(generation=oldGen)
			r._tick(oldGen)
			self.assertEqual(len(timers), count)
			# Dentro de la misma activación solo hay un temporizador pendiente.
			r._schedule()
			r._schedule()
			self.assertEqual(queue_handler.cancelCallLater.call_count, 3)
		r.stop(announce=False)


# ====================================================================== 19. orden de actualizar del OCR
class OcrRefreshScriptTests(unittest.TestCase):
	def test_refresh_script_has_description(self) -> None:
		from tiresias.ocr_document import CAT, OcrDocument

		func = OcrDocument.script_refreshBuffer
		self.assertTrue((func.__doc__ or "").strip())
		self.assertEqual(func.category, CAT)
		self.assertIn("kb:tiresias+f5", func.gestures)


if __name__ == "__main__":
	unittest.main()
