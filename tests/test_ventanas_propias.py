"""Pruebas de las ventanas propias de Tiresias leídas con MSAA, del registro de
cierres y del cambio de sintetizador en caliente.

- ``a11y/own_windows.py``: los objetos MSAA de las ventanas de la interfaz se
  leen en el hilo de la interfaz, con tiempo máximo y cortacircuitos (prueba
  real con un diálogo wx en un proceso aparte: ``own_windows_probe.py``).
- Menús: los elementos con submenú son objetos completos y no se confunden
  entre sí (antes, al bajar por el menú de Tiresias, Herramientas, IA,
  Tienda... no se anunciaban); posición «2 de 10».
- ``crash_log.py``: las excepciones que COM/RPC lanzan y recogen ellos mismos
  no se anotan como cierres; los cierres de verdad sí, con las pilas.
- ``synth._trySet``: volver a cargar el mismo controlador cierra antes el
  anterior (eSpeak y Eloquence tienen estado global: si no, violación de
  acceso).

No se inyectan teclas ni se tocan programas del usuario.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

PY = sys.executable


def _run(code: str, timeout: float = 60) -> subprocess.CompletedProcess:
	return subprocess.run([PY, "-X", "utf8", "-c", code], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=ROOT)


class OwnWindowsProcessTests(unittest.TestCase):
	"""Diálogo wx real leído desde un hilo MTA (como el núcleo)."""

	@classmethod
	def setUpClass(cls):
		r = subprocess.run(
			[PY, "-X", "utf8", os.path.join(ROOT, "tests", "own_windows_probe.py")],
			capture_output=True,
			text=True,
			encoding="utf-8",
			errors="replace",
			timeout=90,
			cwd=ROOT,
		)
		lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
		if not lines:
			raise AssertionError("La sonda no devolvió resultado:\n" + r.stdout + r.stderr)
		cls.res = json.loads(lines[-1])

	def test_sin_error(self):
		self.assertNotIn("error", self.res)

	def test_objetos_envueltos_y_en_el_hilo_de_la_interfaz(self):
		self.assertEqual(self.res["tipo"], "OwnAccessible")
		self.assertTrue(self.res["hilos"], "alguna llamada COM se hizo fuera del hilo de la interfaz")

	def test_lectura(self):
		self.assertEqual(self.res["nombre"], "Prueba propia")
		self.assertEqual(self.res["rol"], "DIALOG")
		self.assertTrue(self.res["mismo"])

	def test_hijos_son_los_controles_no_las_ventanas(self):
		roles = [r for r, _n in self.res["hijosNombres"]]
		self.assertEqual(roles, ["STATICTEXT", "EDITABLETEXT", "CHECKBOX", "LIST", "BUTTON"])

	def test_posicion_en_lista(self):
		self.assertEqual(self.res["lista"][1], ["dos", {"indexInGroup": 2, "similarItemsInGroup": 3}])

	def test_interfaz_ocupada_no_bloquea(self):
		# La primera llamada espera el tiempo máximo y las siguientes fallan al instante.
		self.assertTrue(self.res["ocupada1"])
		self.assertLess(self.res["ocupada1_ms"], 1000)
		self.assertTrue(self.res["ocupada20"])
		self.assertLess(self.res["ocupada20_ms"], 200)
		# Al liberarse la interfaz vuelve a funcionar.
		self.assertEqual(self.res["libre"], "Casilla")

	def test_ventana_destruida(self):
		self.assertEqual(self.res["destruida"], ["", []])


class MenuObjectTests(unittest.TestCase):
	def test_objectid_solo_si_el_evento_es_del_objeto(self):
		from tiresias.objects import iaccessible

		created = []

		def fake(pacc, childId=0, windowHandle=0, objectId=None):
			created.append((childId, objectId))
			return object()

		with mock.patch.object(iaccessible.msaa, "accessibleObjectFromEvent", return_value=("PACC", 0)), mock.patch.object(
			iaccessible.IAccessibleObject, "fromIAccessible", side_effect=fake
		):
			# Elemento con submenú: el evento es del hijo 3, pero llega un objeto completo.
			iaccessible.IAccessibleObject.fromEvent(100, iaccessible.msaa.OBJID_CLIENT, 3)
			# Evento del propio objeto.
			iaccessible.IAccessibleObject.fromEvent(100, iaccessible.msaa.OBJID_CLIENT, 0)
		self.assertEqual(created, [(0, None), (0, iaccessible.msaa.OBJID_CLIENT)])

	def test_posicion_en_menu(self):
		from tiresias.objects import iaccessible
		from tiresias.objects.roles import Role

		msaa = iaccessible.msaa

		class Item:
			def __init__(self, name, role=msaa.ROLE_MENUITEM):
				self.n, self.r = name, role

			def accRole(self, c):
				return self.r

			def accState(self, c):
				return msaa.STATE_HASPOPUP

			def accName(self, c):
				return self.n

		class Menu:
			accChildCount = 5

			def accRole(self, c):
				return msaa.ROLE_SEPARATOR if c == 3 else msaa.ROLE_MENUITEM

			def accState(self, c):
				return 0

			def accName(self, c):
				return f"e{c}"

		menu = Menu()
		sub = Item("Herramientas")
		kids = [(menu, 1), (Item("Preferencias"), 0), (menu, 3), (sub, 0), (menu, 5)]

		def children(pacc, start, count):
			return kids

		class Fake(iaccessible.IAccessibleObject):
			pass

		with mock.patch.object(msaa, "accessibleChildren", side_effect=children), mock.patch.object(
			msaa, "normalizeIAccessible", return_value=menu
		), mock.patch.object(iaccessible, "ctypes_addr", side_effect=lambda p: id(p)):
			# Elemento simple (identificador de hijo 5): el 4.º sin contar el separador.
			o = Fake(menu, 5, 1)
			with mock.patch.object(Fake, "role", Role.MENUITEM, create=True), mock.patch.object(Fake, "name", "e5", create=True):
				self.assertEqual(o._siblingPosition(), {"indexInGroup": 4, "similarItemsInGroup": 4})
			# Elemento con submenú (objeto completo): se reconoce por el nombre.
			o2 = Fake(sub, 0, 1)
			with mock.patch.object(Fake, "role", Role.MENUITEM, create=True), mock.patch.object(Fake, "name", "Herramientas", create=True), mock.patch.object(
				Fake, "IAccessibleRole", msaa.ROLE_MENUITEM, create=True
			):
				self.assertEqual(o2._siblingPosition(), {"indexInGroup": 3, "similarItemsInGroup": 4})


class CrashLogTests(unittest.TestCase):
	def _script(self, mode: str, path: str) -> str:
		return textwrap.dedent(
			f"""
			import ctypes, sys, time
			sys.path.insert(0, r"{os.path.join(ROOT, 'src')}")
			from tiresias import crash_log
			crash_log.install(r"{path}")
			k = ctypes.windll.kernel32
			# Excepción SEH que alguien recoge (ctypes): como las de COM/RPC.
			try:
				k.RaiseException(0x8001010D, 0, 0, None)
			except OSError:
				pass
			if "{mode}" == "crash":
				k.CreateThread.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
				def esperando_el_cierre():
					time.sleep(10)
				k.CreateThread(None, 0, 16, None, 0, None)
				esperando_el_cierre()
			elif "{mode}" == "abort":
				ctypes.CDLL("ucrtbase").abort()
			print("fin normal")
			"""
		)

	def _log(self, mode: str) -> tuple[subprocess.CompletedProcess, str]:
		fd, path = tempfile.mkstemp(suffix=".log")
		os.close(fd)
		try:
			r = _run(self._script(mode, path))
			with open(path, encoding="utf-8", errors="replace") as f:
				return r, f.read()
		finally:
			os.remove(path)

	def test_excepcion_gestionada_no_se_registra(self):
		r, text = self._log("none")
		self.assertIn("fin normal", r.stdout)
		self.assertEqual(text, "")

	def test_cierre_real_con_pilas(self):
		r, text = self._log("crash")
		self.assertNotEqual(r.returncode, 0)
		self.assertIn("Cierre inesperado de Tiresias", text)
		self.assertIn("0xC0000005 (violación de acceso)", text)
		self.assertIn("esperando_el_cierre", text)
		self.assertNotIn("8001010D", text.upper())

	def test_abort(self):
		r, text = self._log("abort")
		self.assertNotEqual(r.returncode, 0)
		self.assertIn("abort()", text)

	def test_describir(self):
		from tiresias import crash_log

		self.assertEqual(crash_log.describeException(0xC0000005, 0), "0xC0000005 (violación de acceso)")
		self.assertTrue(crash_log.describeException(0x80010108, 0).startswith("0x80010108"))


class SynthReloadTests(unittest.TestCase):
	def test_mismo_controlador_se_cierra_antes(self):
		from tiresias import synth

		order = []

		class Fake:
			name = "falso"

			def __init__(self, tag):
				self.tag = tag

			def cancel(self):
				pass

			def terminate(self):
				order.append(("cierra", self.tag))

			def saveableSettings(self):
				return {}

		def instantiate(name):
			order.append(("crea", name))
			return Fake("nuevo")

		old = Fake("viejo")
		with mock.patch.object(synth, "_current", old), mock.patch.object(synth, "_instantiate", side_effect=instantiate), mock.patch.object(
			synth, "saveCurrentSettings"
		), mock.patch.object(synth, "_startWatchdog"), mock.patch.object(synth.synthChanged, "notify"):
			self.assertTrue(synth._trySet("falso"))
			self.assertEqual(order, [("cierra", "viejo"), ("crea", "falso")])
			order.clear()
			# Otro controlador: el anterior sigue funcionando hasta que el nuevo carga.
			synth._current = Fake("otro")
			synth._current.name = "otro"
			self.assertTrue(synth._trySet("falso"))
			self.assertEqual(order, [("crea", "falso"), ("cierra", "otro")])


if __name__ == "__main__":
	unittest.main()
