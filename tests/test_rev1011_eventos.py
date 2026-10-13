"""Pruebas de la revisión 1.0.11 de accesibilidad, eventos, foco y objetos.

Cada clase corresponde a un hallazgo de la auditoría (numeración del informe):
voz de objetos que no son el foco (2), avalanchas de eventos (4), foco MSAA
fantasma (5), eventos de texto locales (6), hash de IAccessible2 (7), regiones
vivas repetidas (8), notificaciones (9), foco UIA caducado (10), antecesores
reutilizados (12), hilo de registro UIA (13), vía rápida del vigilante (14),
vuelta del escritorio seguro (15), proveedor lento (16), foco anterior borrado
(17), Java en espera (21), aria-current (22), valores refrescados (23), PID
reutilizado (25), comprobación del foco sin aplazamientos infinitos (27) y
ráfagas de texto (28).

No instala ganchos ni abre ventanas. Ejecutar con:
``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_eventos -v``
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import unittest
from unittest import mock

sys.coinit_flags = 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

import comtypes  # noqa: E402

from tiresias import api, events, presentation, queue_handler, speech  # noqa: E402
from tiresias.a11y import api_choice, jab, msaa, uia_handler, winevents  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.a11y.mta_worker import MTAWorker  # noqa: E402
from tiresias.appmodules import AppModule  # noqa: E402
from tiresias.browse import aria as ariaSem  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects import base as objbase  # noqa: E402
from tiresias.objects.iaccessible import IAccessibleObject  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402
from tiresias.objects.uia import UIAObject  # noqa: E402
from tiresias.speech.api import Priority, SpeechManager, Utterance  # noqa: E402


class _ConfValue:
	"""Cambia un valor de configuración durante la prueba y lo restaura."""

	def __init__(self, section: str, key: str, value) -> None:
		self.section, self.key, self.value = section, key, value

	def __enter__(self):
		self.old = conf[self.section][self.key]
		conf[self.section][self.key] = self.value
		return self

	def __exit__(self, *exc) -> None:
		conf[self.section][self.key] = self.old


class _Focus:
	"""Fija el foco de ``api`` durante la prueba."""

	def __init__(self, obj, ancestors=None) -> None:
		self.obj, self.ancestors = obj, ancestors or []

	def __enter__(self):
		self.old = (api._focusObject, api._focusAncestors)
		api._focusObject, api._focusAncestors = self.obj, list(self.ancestors)
		return self

	def __exit__(self, *exc) -> None:
		api._focusObject, api._focusAncestors = self.old


class FakeEl:
	"""Elemento UIA mínimo: propiedades en un diccionario."""

	def __init__(self, rid=(42, 1, 7), pid=4242, **props) -> None:
		self.props = {uc.P_RUNTIMEID: rid, uc.P_PROCESSID: pid}
		for k, v in props.items():
			self.props[getattr(uc, k)] = v

	def GetCachedPropertyValue(self, propId):
		return self.props.get(propId)

	def GetCachedPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetCurrentPropertyValueEx(self, propId, ignoreDefault):
		return self.props.get(propId)

	def GetRuntimeId(self):
		return self.props.get(uc.P_RUNTIMEID)

	def __bool__(self):
		return True


# ====================================================================== 2
class VoiceOfNonFocusObjectsTests(unittest.TestCase):
	"""Alertas, sugerencias y emojis se leían «como el foco» y se descartaban."""

	def test_alerta_que_no_es_el_foco_se_dice(self):
		focus, alert = object(), object()
		with _Focus(focus), _ConfValue("speech", "cancelExpiredFocusSpeech", True):
			valid = presentation._focusValidator(alert, presentation.Reason.FOCUS)
			m = SpeechManager()
			m._queues[Priority.NORMAL].append(Utterance(["Error"], Priority.NORMAL, valid))
			self.assertIsNotNone(m._nextCandidate())
			# Si el foco cambia antes de decirse, ya no vale.
			api._focusObject = object()
			self.assertFalse(valid())

	def test_voz_del_foco_sigue_igual(self):
		focus = object()
		with _Focus(focus), _ConfValue("speech", "cancelExpiredFocusSpeech", True):
			valid = presentation._focusValidator(focus, presentation.Reason.FOCUS)
			self.assertTrue(valid())
			api._focusObject = object()
			self.assertFalse(valid())


# ====================================================================== 4
class WinEventFloodTests(unittest.TestCase):
	def setUp(self):
		winevents._pendingChanges.clear()
		winevents._pendingPerThread.clear()

	def _send(self, event, hwnd=0x100, idObject=msaa.OBJID_CLIENT, idChild=-5, threadId=77, cls="Foo"):
		with mock.patch.object(winevents, "_pidOf", return_value=999), mock.patch.object(winevents, "_focusPid", 999), mock.patch.object(api_choice, "cachedAPI", return_value=api_choice.API_MSAA), mock.patch.object(api_choice, "getClassName", return_value=cls), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			winevents.onWinEvent(event, hwnd, idObject, idChild, threadId)
		return q.call_args_list

	def test_hide_se_descarta(self):
		self.assertEqual(self._send(msaa.EVENT_OBJECT_HIDE), [])

	def test_show_de_objetos_hijo_se_descarta(self):
		self.assertEqual(self._send(msaa.EVENT_OBJECT_SHOW, idChild=-12), [])
		# Una ventana que aparece (ayuda emergente) sí, y las clases conocidas también.
		self.assertEqual(len(self._send(msaa.EVENT_OBJECT_SHOW, idChild=0)), 1)
		self.assertEqual(len(self._send(msaa.EVENT_OBJECT_SHOW, hwnd=0x101, idChild=-3, cls="tooltips_class32")), 1)

	def test_eventos_del_foco_se_filtran_antes_de_crear_el_objeto(self):
		with mock.patch.object(winevents, "_focusIsMSAA", True), mock.patch.object(winevents, "_focusRootHwnd", 0x10), mock.patch.object(winevents.winapi, "getAncestor", return_value=0x20):
			self.assertEqual(self._send(msaa.IA2_EVENT_TEXT_INSERTED), [])
		with mock.patch.object(winevents, "_focusIsMSAA", True), mock.patch.object(winevents, "_focusRootHwnd", 0x10), mock.patch.object(winevents.winapi, "getAncestor", return_value=0x10):
			self.assertEqual(len(self._send(msaa.IA2_EVENT_TEXT_INSERTED)), 1)

	def test_limite_por_hilo(self):
		with mock.patch.object(winevents, "MAX_PENDING_PER_THREAD", 2):
			calls = []
			for child in (-1, -2, -3, -4):
				calls += self._send(msaa.EVENT_OBJECT_STATECHANGE, idChild=child)
		self.assertEqual(len(calls), 2)
		# Al procesarse uno, queda sitio para otro.
		winevents._releasePending(77)
		with mock.patch.object(winevents, "MAX_PENDING_PER_THREAD", 2):
			self.assertEqual(len(self._send(msaa.EVENT_OBJECT_STATECHANGE, idChild=-9)), 1)

	def test_repetidos_del_mismo_objeto_se_agrupan(self):
		first = self._send(msaa.EVENT_OBJECT_SELECTIONADD, idChild=-8)
		second = self._send(msaa.EVENT_OBJECT_SELECTIONADD, idChild=-8)
		self.assertEqual((len(first), len(second)), (1, 0))

	def test_alertas_no_se_agrupan(self):
		self.assertEqual(len(self._send(msaa.EVENT_SYSTEM_ALERT, idChild=0)), 1)
		self.assertEqual(len(self._send(msaa.EVENT_SYSTEM_ALERT, idChild=0)), 1)


class UIAFloodTests(unittest.TestCase):
	def setUp(self):
		uia_handler._pendingEvents.clear()

	def test_se_agrupa_y_gana_el_mas_reciente(self):
		a, b = FakeEl(), FakeEl()
		with mock.patch.object(uia_handler.queue_handler, "queueFunction") as q:
			uia_handler._queueEvent(a, "valueChange")
			uia_handler._queueEvent(b, "valueChange")
		self.assertEqual(q.call_count, 1)
		self.assertIs(q.call_args[0][0], uia_handler._dispatchPending)
		with mock.patch.object(uia_handler, "_dispatch") as d:
			uia_handler._dispatchPending(q.call_args[0][1])
		d.assert_called_once_with(b, "valueChange")

	def test_regiones_vivas_no_se_agrupan(self):
		a = FakeEl()
		with mock.patch.object(uia_handler.queue_handler, "queueFunction") as q:
			uia_handler._queueEvent(a, "liveRegionChange")
			uia_handler._queueEvent(a, "liveRegionChange")
		self.assertEqual(q.call_count, 2)

	def test_barra_de_progreso_de_otra_aplicacion(self):
		el = FakeEl(pid=4242)
		with _ConfValue("presentation", "reportBackgroundProgressBars", False), mock.patch("tiresias.winapi.getForegroundWindow", return_value=0x55), mock.patch("tiresias.winapi.getWindowProcessId", return_value=1111):
			self.assertFalse(uia_handler._acceptBackgroundProgress(el))
		with _ConfValue("presentation", "reportBackgroundProgressBars", False), mock.patch("tiresias.winapi.getForegroundWindow", return_value=0x55), mock.patch("tiresias.winapi.getWindowProcessId", return_value=4242):
			self.assertTrue(uia_handler._acceptBackgroundProgress(el))
		with _ConfValue("presentation", "reportBackgroundProgressBars", True):
			self.assertTrue(uia_handler._acceptBackgroundProgress(el))


# ====================================================================== 5
class _FakeMSAA:
	def __init__(self, focused=False, parent=None):
		self.states = {State.FOCUSED} if focused else set()
		self.parent = parent


class GhostFocusTests(unittest.TestCase):
	def test_foco_de_ventana_de_fondo_no_se_encola(self):
		with mock.patch.object(api_choice, "cachedAPI", return_value=api_choice.API_MSAA), mock.patch.object(winevents, "isForegroundRelated", return_value=False), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			winevents.onWinEvent(msaa.EVENT_OBJECT_FOCUS, 0x300, msaa.OBJID_CLIENT, 0, 1)
		q.assert_not_called()

	def test_foco_antiguo_se_descarta(self):
		with mock.patch.object(api_choice, "cachedAPI", return_value=api_choice.API_MSAA), mock.patch.object(winevents, "isForegroundRelated", return_value=True), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			winevents.onWinEvent(msaa.EVENT_OBJECT_FOCUS, 0x300, msaa.OBJID_CLIENT, -1, 1)
			winevents.onWinEvent(msaa.EVENT_OBJECT_FOCUS, 0x300, msaa.OBJID_CLIENT, -2, 1)
		oldSeq = q.call_args_list[0][0][4]
		with mock.patch.object(api_choice, "chooseAPI") as choose:
			winevents._onFocusWinEvent(0x300, msaa.OBJID_CLIENT, -1, oldSeq)
		choose.assert_not_called()

	def test_estado_con_foco_en_el_objeto_o_un_antecesor(self):
		with mock.patch.object(winevents, "_isWindowFocus", return_value=False):
			self.assertTrue(winevents.shouldAllowMSAAFocus(_FakeMSAA(True), 1, msaa.OBJID_CLIENT, -1))
			self.assertTrue(winevents.shouldAllowMSAAFocus(_FakeMSAA(False, _FakeMSAA(True)), 1, msaa.OBJID_CLIENT, -1))
			self.assertFalse(winevents.shouldAllowMSAAFocus(_FakeMSAA(False, _FakeMSAA(False)), 1, msaa.OBJID_CLIENT, -1))
		with mock.patch.object(winevents, "_isWindowFocus", return_value=True):
			# La ventana que Windows da como enfocada se acepta aunque no lo marque.
			self.assertTrue(winevents.shouldAllowMSAAFocus(_FakeMSAA(False), 1, msaa.OBJID_CLIENT, 0))

	def test_ventana_relacionada_con_la_activa(self):
		with mock.patch.object(winevents._user32, "GetForegroundWindow", return_value=0x500), mock.patch.object(winevents.winapi, "getAncestor", side_effect=lambda h, *f: 0x600 if h == 0x700 else h), mock.patch.object(winevents, "_pidOf", side_effect=lambda h: 1 if h == 0x700 else 2), mock.patch.object(winevents, "_isMenuWindow", return_value=False), mock.patch.object(winevents.winapi, "getGUIThreadInfo", return_value=None), mock.patch.object(winevents.winapi, "getWindowThreadId", return_value=5):
			self.assertFalse(winevents.isForegroundRelated(0x700))
		with mock.patch.object(winevents._user32, "GetForegroundWindow", return_value=0x500), mock.patch.object(winevents.winapi, "getAncestor", return_value=0x500):
			self.assertTrue(winevents.isForegroundRelated(0x700))


# ====================================================================== 6, 13
class _TextObj:
	def __init__(self, element, hasText=True):
		self.element = element
		self.hasText = hasText


class LocalHandlersTests(unittest.TestCase):
	def test_foco_rechazado_conserva_los_eventos_del_campo(self):
		field, container = _TextObj("campo"), _TextObj("contenedor", hasText=False)
		with _Focus(field), mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler._registrar, "submit") as submit:
			uia_handler._registerLocalHandlers(container)
			submit.assert_not_called()
			uia_handler._registerLocalHandlers(field)
			submit.assert_called_once()
			self.assertEqual(submit.call_args[0][1], "campo")

	def test_mismo_elemento_no_se_vuelve_a_registrar(self):
		client = mock.Mock()
		with mock.patch.object(uc, "client", client), mock.patch.object(uc, "compareElements", return_value=True), mock.patch.object(uia_handler, "_localTextElement", "campo"):
			uia_handler._updateLocalHandlers("campo", uia_handler._handler)
		client.RemoveAutomationEventHandler.assert_not_called()
		client.AddAutomationEventHandler.assert_not_called()

	def test_espera_quita_los_manejadores_en_el_hilo_de_registro(self):
		fake = mock.Mock()
		with mock.patch.object(uia_handler, "_registrar", fake), mock.patch.object(uia_handler, "_handler", object()), mock.patch.object(uia_handler, "_suspended", False):
			uia_handler.suspend()
			self.assertTrue(uia_handler._suspended)
		fake.submit.assert_called_once_with(uia_handler._removeAllHandlers)


class MTAWorkerTests(unittest.TestCase):
	def test_orden_hilo_propio_y_errores(self):
		w = MTAWorker("prueba")
		out = []
		w.submit(out.append, 1)
		w.submit(lambda: 1 / 0)  # se registra y el hilo sigue
		w.submit(lambda: out.append(threading.current_thread().name))
		w.submit(out.append, 3)
		self.assertTrue(w.wait(5))
		self.assertEqual(out, [1, "prueba", 3])
		self.assertTrue(w.stop(5))
		self.assertFalse(w.isRunning)


# ====================================================================== 7
class _FakeIA2:
	def __init__(self, uid):
		self.uid = uid
		self.reads = 0

	@property
	def uniqueID(self):
		self.reads += 1
		return self.uid


class IA2HashTests(unittest.TestCase):
	def _obj(self, ia2):
		obj = IAccessibleObject(object(), 0, 0x77)
		obj._ia2Cache = ia2
		return obj

	def test_hash_distingue_objetos_de_la_misma_ventana(self):
		# (Ojo: en Python hash(-1) == hash(-2); se usan otros identificadores.)
		a, b, a2 = self._obj(_FakeIA2(-10)), self._obj(_FakeIA2(-20)), self._obj(_FakeIA2(-10))
		self.assertNotEqual(hash(a), hash(b))
		self.assertEqual(hash(a), hash(a2))
		self.assertEqual(a, a2)
		self.assertNotEqual(a, b)

	def test_unique_id_se_pide_una_vez(self):
		ia2 = _FakeIA2(-9)
		obj = self._obj(ia2)
		for _i in range(5):
			hash(obj)
			obj == self._obj(_FakeIA2(-9))  # noqa: B015
		self.assertEqual(ia2.reads, 1)


# ====================================================================== 8
class LiveRegionTests(unittest.TestCase):
	def test_mismo_texto_seguido_se_dice_una_vez(self):
		objbase._lastLiveText = ("", 0.0)
		self.assertTrue(objbase.shouldReportLiveText("Se muestra 5"))
		self.assertFalse(objbase.shouldReportLiveText("Se  muestra 5"))
		self.assertTrue(objbase.shouldReportLiveText("Se muestra 6"))
		objbase._lastLiveText = ("Se muestra 6", time.monotonic() - 1)
		self.assertTrue(objbase.shouldReportLiveText("Se muestra 6"))


# ====================================================================== 9
class NotificationTests(unittest.TestCase):
	def test_por_defecto_no_las_de_segundo_plano(self):
		from tiresias.config import schema

		self.assertIs(schema.DEFAULTS["uia"]["notificationsFromBackground"], False)

	def test_no_corta_la_lectura_continua(self):
		with _ConfValue("presentation", "reportNotifications", True), _ConfValue("uia", "honorNotificationProcessing", True), mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler, "_makeObject", return_value=None), mock.patch.object(uia_handler, "_sayAllRunning", return_value=True), mock.patch.object(speech, "cancelSpeech") as cancel, mock.patch.object(speech, "speakText"):
			uia_handler._lastNotification = ("descarga", time.monotonic())
			uia_handler._onNotification(None, 0, 1, "50 %", "descarga")
		cancel.assert_not_called()


# ====================================================================== 10
class StaleUIAFocusTests(unittest.TestCase):
	def test_se_mira_el_foco_actual_no_la_cache(self):
		class El(FakeEl):
			CurrentHasKeyboardFocus = False

		el, current = El(), FakeEl(rid=(42, 2, 2))
		obj = mock.Mock(shouldAllowFocusEvent=True)
		with mock.patch.object(uia_handler, "_suspended", False), mock.patch.object(uia_handler, "_focusSeq", 5), mock.patch.object(uia_handler, "_makeObject", return_value=obj) as make, mock.patch.object(uc, "getFocusedElement", return_value=current), mock.patch.object(uc, "compareElements", return_value=False), mock.patch.object(uia_handler, "isInForegroundWindow", return_value=False), mock.patch.object(winevents, "scheduleFocusCheck"):
			uia_handler._onFocus(el, 5)
		self.assertEqual(make.call_args_list[-1][0][0], current)


# ====================================================================== 12
class _Node:
	def __init__(self, name, parent=None):
		self.name = name
		self._parent = parent
		self.parentReads = 0

	@property
	def parent(self):
		self.parentReads += 1
		return self._parent

	def __eq__(self, other):
		return isinstance(other, _Node) and other.name == self.name

	def __hash__(self):
		return hash(self.name)


class AncestorsTests(unittest.TestCase):
	def test_reutiliza_la_linea_del_foco_anterior(self):
		root = _Node("raíz")
		win = _Node("ventana", root)
		lst = _Node("lista", win)
		old = _Node("elemento 1", lst)
		# Objetos nuevos (otra instancia) para los mismos elementos.
		newList = _Node("lista", _Node("ventana", _Node("raíz")))
		new = _Node("elemento 2", newList)
		with _Focus(old, [root, win, lst]):
			ancestors = events.computeAncestors(new)
		self.assertEqual([a.name for a in ancestors], ["raíz", "ventana", "lista"])
		# Se paró en la lista: no subió más allá.
		self.assertIs(ancestors[0], root)
		self.assertEqual(newList.parentReads, 0)

	def test_sin_foco_anterior_sube_hasta_la_raiz(self):
		root = _Node("raíz")
		obj = _Node("botón", _Node("diálogo", root))
		with _Focus(None):
			self.assertEqual([a.name for a in events.computeAncestors(obj)], ["raíz", "diálogo"])


# ====================================================================== 14
class EarlyRecoveryTests(unittest.TestCase):
	def test_sin_ventana_activa_o_en_otra_ventana(self):
		with mock.patch.object(winevents._user32, "GetForegroundWindow", return_value=0):
			self.assertTrue(winevents.shouldRecoverEarly())
		info = mock.Mock(hwndFocus=0x900)
		with mock.patch.object(winevents._user32, "GetForegroundWindow", return_value=0x800), mock.patch.object(winevents.winapi, "getGUIThreadInfo", return_value=info), mock.patch.object(winevents.winapi, "getWindowThreadId", return_value=1), mock.patch.object(winevents, "_focusRootHwnd", 0x111), mock.patch.object(winevents.winapi, "getAncestor", return_value=0x800):
			self.assertTrue(winevents.shouldRecoverEarly())
		with mock.patch.object(winevents._user32, "GetForegroundWindow", return_value=0x111), mock.patch.object(winevents.winapi, "getGUIThreadInfo", return_value=info), mock.patch.object(winevents.winapi, "getWindowThreadId", return_value=1), mock.patch.object(winevents, "_focusRootHwnd", 0x111), mock.patch.object(winevents.winapi, "getAncestor", return_value=0x111):
			self.assertFalse(winevents.shouldRecoverEarly())


# ====================================================================== 15, 27
class FocusCheckTests(unittest.TestCase):
	def setUp(self):
		winevents._pendingCheck = None
		winevents._forceFocusCheck = False
		winevents._onSecureDesktop = False

	def tearDown(self):
		winevents._pendingCheck = None
		winevents._forceFocusCheck = False

	def test_vuelta_del_escritorio_seguro_anuncia_el_mismo_foco(self):
		from tiresias.a11y import system

		with mock.patch.object(system, "isSecureDesktopActive", return_value=True), mock.patch.object(speech, "speakMessage"), mock.patch.object(winevents, "scheduleFocusCheck") as sched:
			winevents._onDesktopSwitch()
		sched.assert_not_called()
		with mock.patch.object(system, "isSecureDesktopActive", return_value=False), mock.patch.object(winevents, "scheduleFocusCheck") as sched:
			winevents._onDesktopSwitch()
		self.assertTrue(sched.call_args.kwargs.get("force"))
		focus = object()
		winevents._forceFocusCheck = True
		with _Focus(focus), mock.patch.object(winevents, "_menuStillOpen", return_value=False), mock.patch("tiresias.objects.uia.getFocusObject", return_value=focus), mock.patch("tiresias.events.executeEvent") as ex, mock.patch.object(uia_handler, "_registerLocalHandlers"):
			winevents._checkFocus()
		ex.assert_called_once_with("gainFocus", focus)

	def test_sin_aplazamientos_infinitos(self):
		ids = iter(range(1, 100))
		clock = [100.0]
		with mock.patch.object(winevents.queue_handler, "callLater", side_effect=lambda *a, **k: next(ids)) as later, mock.patch.object(winevents.queue_handler, "cancelCallLater") as cancel, mock.patch.object(winevents.time, "monotonic", side_effect=lambda: clock[0]):
			winevents.scheduleFocusCheck(150)
			clock[0] += 0.2
			winevents.scheduleFocusCheck(150)
			self.assertEqual(cancel.call_count, 1)
			clock[0] += 0.4
			winevents.scheduleFocusCheck(150)
			# Más de medio segundo desde la primera: ya no se aplaza.
			self.assertEqual(cancel.call_count, 1)
			self.assertEqual(later.call_count, 2)


# ====================================================================== 16
class SlowProviderTests(unittest.TestCase):
	def test_solo_cuenta_lo_que_tarda_el_proveedor(self):
		el = FakeEl(pid=3131)
		with mock.patch.object(uia_handler, "markSlowProcess") as mark:
			uia_handler._checkSlowProvider(el, 50)
			mark.assert_not_called()
			uia_handler._checkSlowProvider(el, 5000)
			mark.assert_called_once_with(3131)
		# Un evento cuyo anuncio tarda (voz, braille) ya no marca el proceso.
		with mock.patch.object(uia_handler, "_dispatchEvent", side_effect=lambda *a: time.sleep(0.01)), mock.patch.object(uia_handler, "markSlowProcess") as mark, _ConfValue("objects", "slowProviderThresholdMs", 1):
			uia_handler._dispatch(el, "liveRegionChange")
		mark.assert_not_called()


# ====================================================================== 17
class _Container:
	role = Role.PANE
	name = ""
	value = ""

	def __eq__(self, other):
		return isinstance(other, _Container)

	def __hash__(self):
		return 1


class DefunctFocusTests(unittest.TestCase):
	def test_foco_anterior_borrado_no_se_ignora_el_contenedor(self):
		old = mock.Mock()
		container = _Container()
		events._lastFocusTime = time.monotonic()
		with _Focus(old, [object(), _Container()]):
			old.isDefunct.return_value = False
			self.assertTrue(events.isTransientContainerFocus(container))
			old.isDefunct.return_value = True
			self.assertFalse(events.isTransientContainerFocus(container))

	def test_elemento_uia_borrado(self):
		class Dead(FakeEl):
			@property
			def CurrentProcessId(self):
				raise comtypes.COMError(-2147220991, "UIA_E_ELEMENTNOTAVAILABLE", None)

		class Slow(FakeEl):
			@property
			def CurrentProcessId(self):
				raise comtypes.COMError(-2147220992, "tiempo agotado", None)

		class Alive(FakeEl):
			CurrentProcessId = 10

		self.assertTrue(UIAObject(Dead()).isDefunct())
		self.assertFalse(UIAObject(Slow()).isDefunct())
		self.assertFalse(UIAObject(Alive()).isDefunct())


# ====================================================================== 21
class JavaStandbyTests(unittest.TestCase):
	def test_en_espera_no_se_encola_y_se_suelta(self):
		with mock.patch.object(jab, "_isStandby", return_value=True), mock.patch.object(jab, "_release") as rel, mock.patch.object(queue_handler, "queueFunction") as q:
			jab._queue("gainFocus", 1, 0xABC)
		q.assert_not_called()
		rel.assert_called_once_with(1, 0xABC)

	def test_liberacion_desde_otro_hilo_va_al_nucleo(self):
		with mock.patch.object(jab, "bridge", object()), mock.patch.object(queue_handler, "_coreThreadId", -1), mock.patch.object(queue_handler, "queueFunction") as q:
			jab.releaseObject(3, 0x55)
		q.assert_called_once_with(jab._release, 3, 0x55)


# ====================================================================== 22, 23
class AriaCurrentTests(unittest.TestCase):
	def test_aria_current_no_es_seleccionado(self):
		obj = UIAObject(FakeEl(P_CONTROLTYPE=uc.CT_HYPERLINK, P_ARIAPROPERTIES="current=page"))
		self.assertNotIn(State.SELECTED, obj.states)
		self.assertEqual(obj.ariaCurrent, "page")
		self.assertEqual(presentation.ariaCurrentText(obj), ariaSem.currentLabel("page"))
		self.assertTrue(presentation.ariaCurrentText(obj))

	def test_false_no_dice_nada(self):
		obj = UIAObject(FakeEl(P_CONTROLTYPE=uc.CT_HYPERLINK, P_ARIAPROPERTIES="current=false"))
		self.assertEqual(presentation.ariaCurrentText(obj), "")

	def test_refrescar_deja_de_usar_la_cache_del_evento(self):
		el = FakeEl(P_CONTROLTYPE=uc.CT_EDIT)
		obj = UIAObject(el)
		self.assertNotEqual(obj._creationGen, -1)
		obj.refreshProperties()
		self.assertEqual(obj._creationGen, -1)


# ====================================================================== 25
class ReusedPidTests(unittest.TestCase):
	def test_proceso_terminado_aunque_el_numero_se_reutilice(self):
		proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(0.4)"])
		try:
			app = AppModule(proc.pid, "prueba")
			self.assertTrue(app.isAlive)
			proc.wait(10)
			self.assertFalse(app.isAlive)
		finally:
			if proc.poll() is None:
				proc.kill()

	def test_propio_proceso(self):
		self.assertTrue(AppModule(os.getpid(), "tiresias").isAlive)


# ====================================================================== 28
class TrailingTextTests(unittest.TestCase):
	def test_el_ultimo_cambio_de_texto_de_una_rafaga_no_se_pierde(self):
		el = FakeEl(rid=(42, 9, 9))
		key = ((42, 9, 9), "textChange")
		uia_handler._trailingPending.clear()
		with _ConfValue("advanced", "eventCoalesceMs", 1000), mock.patch.object(uia_handler, "_lastEventKey", key), mock.patch.object(uia_handler, "_lastEventTime", time.monotonic()), mock.patch.object(uc, "runtimeIdOf", return_value=(42, 9, 9)), mock.patch.object(uia_handler.queue_handler, "callLater") as later:
			uia_handler._dispatchEvent(el, "textChange")
			uia_handler._dispatchEvent(el, "textChange")
		self.assertEqual(later.call_count, 1)
		uia_handler._trailingPending.clear()


if __name__ == "__main__":
	unittest.main()
