"""Cuadros combinados (retraso), relaciones UIA (cierre 0xc0000374),
actualizaciones sin repositorio oficial y bloqueo del Control de aplicaciones."""

from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

sys.coinit_flags = 0

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from comtypes.automation import VARIANT  # noqa: E402

from tiresias import addon_store, app_control, updates  # noqa: E402
from tiresias.a11y import api_choice, msaa, uia_handler, winevents  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.config import conf  # noqa: E402


class FakeArray:
	def __init__(self, items):
		self.items = items

	@property
	def Length(self):
		return len(self.items)

	def GetElement(self, i):
		return self.items[i]


class FakeElement:
	"""Elemento con accesores tipados; leer relaciones como VARIANT es un error."""

	def __init__(self, pid=1234, rid=(1, 2), **relations):
		self.pid = pid
		self.rid = rid
		self.relations = relations

	def GetCachedPropertyValue(self, propId):
		if propId == uc.P_PROCESSID:
			return self.pid
		if propId == uc.P_RUNTIMEID:
			return list(self.rid)
		return 0

	def GetCurrentPropertyValueEx(self, propId, ignore):
		raise AssertionError("relación leída como VARIANT")

	GetCachedPropertyValueEx = GetCurrentPropertyValueEx

	def QueryInterface(self, iface):
		return self

	def __getattr__(self, name):
		for prefix in ("Current", "Cached"):
			if name.startswith(prefix):
				key = name[len(prefix) :]
				if key == "LabeledBy":
					return self.relations.get("LabeledBy")
				return FakeArray(self.relations.get(key, []))
		raise AttributeError(name)


class RelationTests(unittest.TestCase):
	def test_element_array_usa_accesores_tipados(self):
		a, b = object(), object()
		el = FakeElement(ControllerFor=[a, b], DescribedBy=[b], FlowsFrom=[a], AnnotationObjects=[b])
		self.assertEqual(uc.elementArray(el, uc.P_CONTROLLERFOR), [a, b])
		self.assertEqual(uc.elementArray(el, uc.P_DESCRIBEDBY, cached=True), [b])
		self.assertEqual(uc.elementArray(el, uc.P_FLOWSFROM), [a])
		self.assertEqual(uc.elementArray(el, uc.P_ANNOTATIONOBJECTS), [b])
		self.assertEqual(uc.elementArray(el, uc.P_FLOWSTO), [])
		self.assertEqual(uc.elementArray(el, uc.P_NAME), [])

	def test_prop_de_relacion_no_es_variant(self):
		from tiresias.objects.uia import UIAObject

		target = object()
		obj = UIAObject(FakeElement(ControllerFor=[target]))
		self.assertEqual(obj._prop(uc.P_CONTROLLERFOR), [target])
		self.assertEqual(obj.relationElements("controllerFor"), [target])
		self.assertEqual(obj._prop(uc.P_DESCRIBEDBY, "nada"), "nada")

	def test_variant_del_evento_se_vacia(self):
		# La copia del VARIANT no debe liberarse (UIA ya lo libera): vt = VT_EMPTY.
		handler = uia_handler._EventHandler()
		v = VARIANT("texto")
		with mock.patch.object(uia_handler.queue_handler, "queueFunction"):
			handler.IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(FakeElement(), uc.P_NAME, v)
		self.assertEqual(v.vt, 0)

	def test_estres_local_sin_corrupcion_del_monton(self):
		# Antes del arreglo este proceso terminaba con 0xc0000005/0xc0000374.
		r = subprocess.run([sys.executable, "-X", "utf8", os.path.join(ROOT, "tests", "uia_stress_relations.py"), "local", "20000"], capture_output=True, text=True, timeout=180)
		self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
		self.assertIn("sin fallos", r.stdout)


class OwnProcessTests(unittest.TestCase):
	def test_eventos_uia_propios_se_descartan(self):
		handler = uia_handler._EventHandler()
		with mock.patch.object(uia_handler.queue_handler, "queueFunction") as q:
			handler.IUIAutomationEventHandler_HandleAutomationEvent(FakeElement(pid=os.getpid()), uc.E_ELEMENTSELECTED)
			handler.IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(FakeElement(pid=os.getpid()), uc.P_VALUEVALUE, VARIANT(1))
			q.assert_not_called()
			handler.IUIAutomationFocusChangedEventHandler_HandleFocusChangedEvent(FakeElement(pid=os.getpid()))
			# Foco propio: solo la comprobación de respaldo (MSAA lo anuncia).
			self.assertEqual(q.call_args[0][0], uia_handler._ownFocusFallback)
			q.reset_mock()
			handler.IUIAutomationEventHandler_HandleAutomationEvent(FakeElement(pid=4242), uc.E_ELEMENTSELECTED)
			q.assert_called_once()

	def test_selecciones_de_combo_cerrado_se_descartan(self):
		handler = uia_handler._EventHandler()
		with mock.patch.object(uia_handler, "_focusComboCollapsed", True), mock.patch.object(uia_handler.queue_handler, "queueFunction") as q:
			handler.IUIAutomationEventHandler_HandleAutomationEvent(FakeElement(pid=4242), uc.E_ELEMENTSELECTED)
			q.assert_not_called()
			handler.IUIAutomationEventHandler_HandleAutomationEvent(FakeElement(pid=4242), uc.E_MENUOPENED)
			q.assert_called_once()

	def test_combo_se_abre_y_cierra(self):
		handler = uia_handler._EventHandler()
		el = FakeElement(pid=4242, rid=(7, 7))
		with mock.patch.object(uia_handler, "_focusIsCombo", True), mock.patch.object(uia_handler, "_focusRid", (7, 7)), mock.patch.object(uia_handler, "_focusComboCollapsed", True), mock.patch.object(uia_handler.queue_handler, "queueFunction"):
			handler.IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(el, uc.P_EXPANDCOLLAPSESTATE, VARIANT(1))
			self.assertFalse(uia_handler._focusComboCollapsed)
			handler.IUIAutomationPropertyChangedEventHandler_HandlePropertyChangedEvent(el, uc.P_EXPANDCOLLAPSESTATE, VARIANT(0))
			self.assertTrue(uia_handler._focusComboCollapsed)

	def test_winevents_propios_sin_foco_solo_menus(self):
		hwnd = 0x1234
		with mock.patch.object(winevents, "_pidOf", return_value=os.getpid()), mock.patch.object(winevents, "_focusPid", 999), mock.patch.object(api_choice, "cachedAPI", return_value=api_choice.API_MSAA), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			winevents.onWinEvent(msaa.EVENT_OBJECT_VALUECHANGE, hwnd, msaa.OBJID_CLIENT, 0, 1)
			q.assert_not_called()
			winevents.onWinEvent(msaa.EVENT_SYSTEM_MENUPOPUPSTART, hwnd, msaa.OBJID_CLIENT, 0, 1)
			self.assertEqual(q.call_args[0][1], "menuStart")

	def test_winevents_propios_con_foco_propio(self):
		with mock.patch.object(winevents, "_pidOf", return_value=os.getpid()), mock.patch.object(winevents, "_focusPid", os.getpid()), mock.patch.object(winevents, "_focusIsMSAA", True), mock.patch.object(api_choice, "cachedAPI", return_value=None), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			winevents.onWinEvent(msaa.EVENT_OBJECT_VALUECHANGE, 0x1234, msaa.OBJID_CLIENT, 0, 1)
			self.assertEqual(q.call_args[0][1], "valueChange")

	def test_cambios_msaa_pendientes_se_agrupan(self):
		winevents._pendingChanges.clear()
		with mock.patch.object(winevents, "_pidOf", return_value=4321), mock.patch.object(winevents, "_focusPid", 4321), mock.patch.object(api_choice, "cachedAPI", return_value=api_choice.API_MSAA), mock.patch.object(winevents.queue_handler, "queueFunction") as q:
			for _i in range(3):
				winevents.onWinEvent(msaa.EVENT_OBJECT_VALUECHANGE, 0x55, msaa.OBJID_CLIENT, 0, 1)
			self.assertEqual(q.call_count, 1)
			# Al procesarlo (núcleo) se libera la clave: el siguiente cambio vuelve a encolarse.
			with mock.patch.object(winevents.api, "getFocusObject", return_value=None), mock.patch("tiresias.objects.iaccessible.IAccessibleObject.fromEvent", return_value=None):
				winevents._onMSAAEvent("valueChange", 0x55, msaa.OBJID_CLIENT, 0)
			winevents.onWinEvent(msaa.EVENT_OBJECT_VALUECHANGE, 0x55, msaa.OBJID_CLIENT, 0, 1)
			self.assertEqual(q.call_count, 2)
		winevents._pendingChanges.clear()

	def test_ganchos_del_propio_proceso(self):
		own = [e for e in winevents.WIN_EVENTS if len(e) > 3 and e[3]]
		ranges = {(e[0], e[1]) for e in own}
		self.assertIn((msaa.EVENT_OBJECT_FOCUS, msaa.EVENT_OBJECT_VALUECHANGE), ranges)


class ComboEditSelectionTests(unittest.TestCase):
	def test_texto_entero_de_combo_no_se_anuncia_como_seleccion(self):
		from tiresias.objects import behaviors
		from tiresias.objects.roles import Role

		class Info:
			def __init__(self, s, e):
				self.s, self.e = s, e

			isCollapsed = property(lambda self: self.s == self.e)

			def compareEndPoints(self, other, which):
				a = self.s if which.startswith("start") else self.e
				b = other.s if which.endswith("ToStart") else other.e
				return (a > b) - (a < b)

		class Parent:
			role = Role.COMBOBOX

		fake = mock.Mock()
		fake.parent = Parent()
		fake.makeTextInfo.return_value = Info(0, 7)
		self.assertTrue(behaviors.EditableText._isWholeValueOfComboBox(fake, Info(0, 7)))
		self.assertFalse(behaviors.EditableText._isWholeValueOfComboBox(fake, Info(0, 3)))
		fake.parent = None
		self.assertFalse(behaviors.EditableText._isWholeValueOfComboBox(fake, Info(0, 7)))


class UpdateUrlTests(unittest.TestCase):
	"""Sin servidor de distribución (constante vacía) no se va nunca a la red."""

	def setUp(self):
		self._check = conf["update"]["checkUrl"]
		self._cat = conf["addons"]["catalogUrl"]
		self._server = conf["update"]["serverUrl"]
		conf["update"]["checkUrl"] = ""
		conf["addons"]["catalogUrl"] = ""
		conf["update"]["serverUrl"] = ""
		self._patch = mock.patch.object(updates, "DISTRIBUTION_URL", "")
		self._patch.start()

	def tearDown(self):
		self._patch.stop()
		conf["update"]["checkUrl"] = self._check
		conf["addons"]["catalogUrl"] = self._cat
		conf["update"]["serverUrl"] = self._server

	def test_sin_repositorio_oficial_no_hay_direccion(self):
		self.assertFalse(updates.hasOfficialRepository())
		self.assertEqual(updates.updateUrl(), "")
		self.assertEqual(addon_store.catalogUrl(), "")

	def test_servidor_real_por_defecto(self):
		self._patch.stop()
		try:
			self.assertTrue(updates.hasOfficialRepository())
			self.assertEqual(updates.updateUrl(), updates.DISTRIBUTION_URL + "/actualizacion.json")
			self.assertEqual(addon_store.catalogUrl(), updates.DISTRIBUTION_URL + "/complementos/catalogo.json")
		finally:
			self._patch.start()

	def test_comprobacion_automatica_no_hace_nada(self):
		conf["update"]["autoCheck"] = True
		conf["update"]["lastCheck"] = 0
		self.assertFalse(updates._due())
		with mock.patch.object(updates.threading, "Thread") as t, mock.patch.object(updates, "log") as lg:
			updates.checkNow(manual=False)
			t.assert_not_called()
			lg.info.assert_not_called()
		with self.assertRaises(ValueError):
			updates.checkForUpdate()

	def test_direccion_del_usuario_si_se_usa(self):
		conf["update"]["checkUrl"] = "https://ejemplo.invalid/act.json"
		self.assertEqual(updates.updateUrl(), "https://ejemplo.invalid/act.json")

	def test_tienda_usa_copia_local_sin_red(self):
		def noNetwork(url, timeout=0, noCache=False):
			if "://" in url and not url.lower().startswith("file://"):
				raise AssertionError("intento de red: " + url)
			return open(url, "rb")

		if not os.path.isfile(addon_store.localCatalogPath()):
			self.skipTest("sin catálogo local")
		with mock.patch.object(updates, "openUrl", side_effect=noNetwork):
			entries, source = addon_store.fetchCatalog()
		self.assertEqual(source, addon_store.localCatalogPath())


class AppControlTests(unittest.TestCase):
	def test_reconoce_el_bloqueo(self):
		e = ImportError("DLL load failed while importing _core: Una directiva de Control de aplicaciones bloqueó este archivo.")
		self.assertTrue(app_control.isBlockedError(e))
		err = OSError()
		err.winerror = 4551
		self.assertTrue(app_control.isBlockedError(err))
		self.assertFalse(app_control.isBlockedError(ImportError("No module named x")))

	def test_explicacion_y_registro(self):
		text = app_control.explanation(ImportError("x"))
		self.assertIn("Unblock-File", text)
		self.assertIn("Desbloquear", text)
		self.assertIn("firmad", text)
		lg = mock.Mock()
		with mock.patch.object(app_control.ctypes, "windll") as w:
			app_control.report(ImportError("x"), lg, show=False)
			w.user32.MessageBoxW.assert_not_called()
		lg.error.assert_called_once()


if __name__ == "__main__":
	unittest.main()
