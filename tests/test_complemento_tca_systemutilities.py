"""Pruebas del complemento «TCA SystemUtilities» (complementos_tienda/TCA_SystemUtilities).

No se ejecuta nada real: ShellExecute, los programas ocultos, los hilos, los
diálogos, el registro y psutil se sustituyen. Solo se tocan archivos de una
carpeta temporal.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_tca_systemutilities -v``
"""

from __future__ import annotations

import json
import os
import re
import shutil
import struct
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "TCA_SystemUtilities")
GP_DIR = os.path.join(ADDON, "globalPlugins")

from tiresias import paths

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_tca_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias import addons
from tiresias.baseobject import normalizeGestureId
from tiresias.config import conf
from tiresias.plugins import handler as pluginHandler

# Carga como la hace Tiresias (addons.loadAll + plugins.handler.initialize).
_ADDON_OBJ = addons.Addon(ADDON, addons._readManifest(ADDON))
PKG = _ADDON_OBJ.packageName
_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
addons._ensurePackage(PKG, ADDON)
addons._ensurePackage(f"{PKG}.globalPlugins", GP_DIR)
tca = pluginHandler._loadModule(f"{PKG}.globalPlugins.TCA_SystemUtilities", os.path.join(GP_DIR, "TCA_SystemUtilities"))
from importlib import import_module

_base = f"{PKG}.globalPlugins.TCA_SystemUtilities"
ejecutor = import_module(_base + ".ejecutor")
explorador = import_module(_base + ".explorador")
funciones = import_module(_base + ".funciones")
procesos = import_module(_base + ".procesos")
consolas = import_module(_base + ".consolas")
dialogos = import_module(_base + ".dialogos")
sys.dont_write_bytecode = _oldBytecode

import wx

_APP = wx.App.Get() or wx.App(False)  # runOnGui necesita una aplicación wx.

Contexto = explorador.Contexto
EXPLORADOR = Contexto(hwnd=1234, esExplorador=True, clase="CabinetWClass", titulo="Documentos")
OTRA = Contexto(hwnd=99, esExplorador=False, clase="Notepad", titulo="Bloc de notas")


def _wav(ruta: str, segundos: float, bytesPorSegundo: int = 176400) -> None:
	datos = b"\0" * int(segundos * bytesPorSegundo)
	fmt = struct.pack("<HHIIHH", 1, 2, 44100, bytesPorSegundo, 4, 16)
	with open(ruta, "wb") as f:
		f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + 4 + 8 + len(datos)) + b"WAVE")
		f.write(b"LIST" + struct.pack("<I", 4) + b"INFO")
		f.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt)
		f.write(b"data" + struct.pack("<I", len(datos)) + datos)


class Base(unittest.TestCase):
	"""Sustituye todo lo que tendría efectos en el sistema."""

	def setUp(self) -> None:
		self.mensajes: list[str] = []
		self.oculto = mock.Mock(return_value=(0, ""))
		self.elevado = mock.Mock(return_value=0)
		self.abrir = mock.Mock(return_value=True)
		self.copiado: list[str] = []
		parches = [
			mock.patch.object(funciones, "mensaje", side_effect=self.mensajes.append),
			mock.patch.object(funciones, "pitido"),
			mock.patch.object(funciones, "sonidoApagado"),
			mock.patch.object(funciones, "copiar", side_effect=lambda t: self.copiado.append(t) or True),
			mock.patch.object(ejecutor, "oculto", self.oculto),
			mock.patch.object(ejecutor, "elevado", self.elevado),
			mock.patch.object(ejecutor, "abrir", self.abrir),
			mock.patch.object(ejecutor, "enHilo", side_effect=lambda f, *a: f(*a)),
			mock.patch.object(funciones.time, "sleep"),
			mock.patch.object(dialogos, "preguntar", return_value=True),
		]
		for p in parches:
			p.start()
			self.addCleanup(p.stop)
		self.preguntar = dialogos.preguntar

	def ultimo(self) -> str:
		return self.mensajes[-1] if self.mensajes else ""


# ====================================================================== paquete
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "TCA_SystemUtilities")
		self.assertTrue(addons.isValidAddonId(m["id"]))
		self.assertEqual(m["name"], "TCA SystemUtilities")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["url"], "https://github.com/peterrc87/TCA-SystemUtilities-NVDA-Complemento")
		self.assertTrue(m["author"].startswith("Proyecto Tiresias (basado en TCA SystemUtilities de Peter Reina"))
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))
		self.assertIn("Tiresias+Mayúsculas+8", m["description"])

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "globalPlugins/TCA_SystemUtilities/__init__.py"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for texto in ("Tiresias+Mayúsculas+8", "Gestos de entrada", "Herramientas &gt; TCA SystemUtilities", "Peter Reina", "Benítez Corredera", "GPL", "Diferencias con el original", "Preguntar si se quiere crear un perfil de limpieza"):
			self.assertIn(texto, html)
		# Cada acción del menú aparece en la ayuda.
		for a in funciones.ACCIONES:
			etiqueta = a.etiqueta.rstrip(".").replace("&", "")
			self.assertIn(etiqueta, html, a.id)

	def test_sin_modulos_de_nvda_ni_ausentes(self):
		carpeta = os.path.join(GP_DIR, "TCA_SystemUtilities")
		for fn in os.listdir(carpeta):
			if fn.endswith(".py"):
				with open(os.path.join(carpeta, fn), encoding="utf-8") as f:
					src = f.read()
				self.assertNotRegex(src, r"^\s*(import datetime|from datetime)", fn)
				self.assertNotIn("winsound", src, fn)
				self.assertNotRegex(src, r"^\s*import (ui|api|gui|addonHandler|globalPluginHandler|keyboardHandler|shellapi|tones)\b", fn)
				self.assertNotIn("KeyboardInputGesture", src, fn)

	def test_carga_como_tiresias(self):
		self.assertTrue(_ADDON_OBJ.isCompatible)
		self.assertIsNone(_ADDON_OBJ.incompatibilityReason())
		self.assertTrue(_ADDON_OBJ.docPath().endswith("readme.html"))
		self.assertTrue(issubclass(tca.GlobalPlugin, pluginHandler.GlobalPlugin))


# ====================================================================== órdenes y menús
class TestComplemento(Base):
	def setUp(self):
		super().setUp()
		self.plugin = tca.GlobalPlugin()
		self.addCleanup(self.plugin.terminate)

	def test_catalogo(self):
		ids = [a.id for a in funciones.ACCIONES]
		self.assertEqual(len(ids), len(set(ids)))
		self.assertEqual(len(ids), 53)
		grupos = {g for g, _e in funciones.GRUPOS}
		for a in funciones.ACCIONES:
			self.assertIn(a.grupo, grupos, a.id)
			self.assertTrue(a.etiqueta and a.descripcion, a.id)
		for g in grupos:
			self.assertTrue(any(a.grupo == g for a in funciones.ACCIONES), g)

	def test_ordenes(self):
		for a in funciones.ACCIONES:
			f = getattr(tca.GlobalPlugin, "script_" + a.id)
			self.assertEqual(f.__doc__, a.descripcion)
			self.assertEqual(f.category, "TCA SystemUtilities")
			self.assertEqual(f.gestures, [], a.id)
		self.assertEqual(tca.GlobalPlugin.script_mostrarMenu.category, "TCA SystemUtilities")
		# Solo el menú tiene tecla (el original no asigna ninguna).
		self.assertEqual(dict(tca.GlobalPlugin._classGestures), {"kb:tiresias+shift+8": "mostrarMenu"})

	def test_aparecen_en_gestos_de_entrada(self):
		from tiresias.gui import config_dialogs

		infos = config_dialogs._scriptsForClass(tca.GlobalPlugin, "x")
		nombres = {i.name for i in infos if i.category == "TCA SystemUtilities"}
		self.assertEqual(nombres, {a.id for a in funciones.ACCIONES} | {"mostrarMenu"})

	def test_gesto_sin_conflictos(self):
		mios = {normalizeGestureId(g) for g in tca.GlobalPlugin._classGestures}
		patron = re.compile(r"kb(?:\([a-z]+\))?:[A-Za-z0-9+]+")
		usados = set()
		bases = [os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons")]
		tienda = os.path.join(ROOT, "complementos_tienda")
		bases += [os.path.join(tienda, d) for d in os.listdir(tienda) if d != "TCA_SystemUtilities"]
		for base in bases:
			for dirpath, _dirs, files in os.walk(base):
				for fn in files:
					if fn.endswith(".py"):
						with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
							for m in patron.findall(f.read()):
								usados.add(normalizeGestureId("kb:" + m.split(":", 1)[1]))
		for g in mios:
			self.assertNotIn(g, usados, g)

	def test_orden_ejecuta_su_accion(self):
		with mock.patch.object(explorador, "capturarContexto", return_value=OTRA), \
				mock.patch.object(tca, "_modoSeguro", return_value=False), \
				mock.patch.dict(funciones.POR_ID, {"apagar": funciones.Accion("apagar", "a", "b", "apagado", mock.Mock())}):
			self.plugin.script_apagar(None)
			funciones.POR_ID["apagar"].funcion.assert_called_once_with(OTRA)

	def test_bloqueado_en_modo_seguro(self):
		with mock.patch.object(tca, "_modoSeguro", return_value=True), mock.patch.object(funciones, "apagar") as apagar:
			self.plugin.script_apagar(None)
			self.plugin.script_mostrarMenu(None)
		apagar.assert_not_called()
		self.assertEqual(self.mensajes, [tca.MSG_MODO_SEGURO] * 2)

	def test_menu_herramientas_registrado(self):
		from tiresias import gui

		self.assertIn(tca.MENU_ID, gui._addonToolsEntries)
		etiqueta, accion, submenu = gui._addonToolsEntries[tca.MENU_ID]
		self.assertEqual(etiqueta, "&TCA SystemUtilities")
		self.assertTrue(submenu)
		with mock.patch.object(explorador, "capturarContexto", return_value=EXPLORADOR) as cap:
			entradas = accion()
		cap.assert_called_once_with(leerFoco=False)
		self.assertEqual([e for e, _s in entradas], [e for _g, e in funciones.GRUPOS])
		total = sum(len(s) for _e, s in entradas)
		self.assertEqual(total, len(funciones.ACCIONES))
		# Las entradas usan el contexto capturado al abrir el menú.
		etiquetaRuta, accionRuta = next(x for x in entradas[6][1] if x[0] == "Copiar la ruta")
		with mock.patch.object(tca, "_modoSeguro", return_value=False), mock.patch.object(funciones, "obtenerRutas", return_value=(r"C:\x", r"C:\\")), \
				mock.patch.object(funciones.os.path, "exists", return_value=True):
			accionRuta()
		self.assertEqual(self.copiado, ['"C:\\x"'])
		self.plugin.terminate()
		self.assertNotIn(tca.MENU_ID, gui._addonToolsEntries)

	def test_panel(self):
		import wx

		from tiresias.gui import settings as S

		self.assertIn(tca.PANEL_ID, S._panels)
		titulo, cls = S._panels[tca.PANEL_ID]
		self.assertEqual(titulo, "TCA SystemUtilities")
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		self.assertEqual(conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"], True)
		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		try:
			panel = cls(frame)
			casilla = panel.getControl("preguntarPerfilLimpieza")
			self.assertIsInstance(casilla, wx.CheckBox)
			self.assertTrue(casilla.GetValue())
			casilla.SetValue(False)
			panel.onSave()
			self.assertFalse(conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"])
		finally:
			conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"] = True
			frame.Destroy()
		self.plugin.terminate()
		self.assertNotIn(tca.PANEL_ID, S._panels)

	def test_construir_menu(self):
		import wx

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		acciones: dict = {}
		menu = tca.construirMenu(self.plugin.entradasMenu(EXPLORADOR), acciones)
		try:
			self.assertEqual(menu.GetMenuItemCount(), len(funciones.GRUPOS))
			self.assertEqual(len(acciones), len(funciones.ACCIONES))
			self.assertEqual(menu.GetMenuItems()[0].GetItemLabel(), "&Apagado del sistema")
			sub = menu.GetMenuItems()[0].GetSubMenu()
			self.assertEqual(sub.GetMenuItems()[0].GetItemLabelText(), "Apagar")
		finally:
			menu.Destroy()

	def test_menu_emergente(self):
		import wx

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		marco = mock.Mock()
		elegido = {}

		def popup(menu, pos):
			item = menu.GetMenuItems()[0].GetSubMenu().GetMenuItems()[0]  # «Apagar»
			elegido["id"] = item.GetId()
			return item.GetId()

		marco.GetPopupMenuSelectionFromUser.side_effect = popup
		from tiresias import gui

		with mock.patch.object(gui, "mainFrame", marco, create=True), mock.patch.object(wx, "CallAfter", side_effect=lambda f: f()), \
				mock.patch.object(tca, "_modoSeguro", return_value=False), mock.patch.object(funciones, "apagar") as apagar, \
				mock.patch.dict(funciones.POR_ID, {"apagar": funciones.Accion("apagar", "Apagar", "x", "apagado", funciones.apagar)}):
			self.plugin._mostrarMenu(EXPLORADOR)
		marco.prePopup.assert_called_once()
		marco.postPopup.assert_called_once()
		self.assertFalse(self.plugin._menuAbierto)
		self.assertIn("id", elegido)


# ====================================================================== ejecutor
class TestEjecutor(unittest.TestCase):
	def test_cmd(self):
		self.assertEqual(ejecutor.cmdParametros("sfc /scannow", pausa=True), '/c "sfc /scannow & pause"')
		self.assertEqual(ejecutor.cmdParametros('"C:\\a b\\x.exe" -y'), '/c ""C:\\a b\\x.exe" -y"')
		self.assertEqual(ejecutor.cmdParametros("dir", mantener=True), '/k "dir"')

	def test_powershell(self):
		import base64

		script = "Write-Output 'cámara'"
		self.assertEqual(base64.b64decode(ejecutor.psCodificado(script)).decode("utf-16-le"), script)
		args = ejecutor.psArgumentos(script)
		self.assertEqual(args[-2], "-EncodedCommand")
		self.assertIn("-NonInteractive", args)
		self.assertTrue(ejecutor.psParametros(script).endswith(ejecutor.psCodificado(script)))

	def test_decodificar(self):
		self.assertEqual(ejecutor.decodificar("Configuración".encode()), "Configuración")
		self.assertEqual(ejecutor.decodificar("\ufeffhola".encode("utf-8")), "hola")
		self.assertEqual(ejecutor.decodificar(b"\xff\xfe" + "año".encode("utf-16-le")), "año")
		self.assertEqual(ejecutor.decodificar("Configuración".encode("cp850")), "Configuración".encode("cp850").decode("oem"))
		self.assertEqual(ejecutor.decodificar(None), "")

	def test_rutas_de_windows(self):
		self.assertTrue(ejecutor.CMD.lower().endswith(r"system32\cmd.exe"))
		self.assertTrue(os.path.isfile(ejecutor.SHUTDOWN))
		self.assertTrue(os.path.isfile(ejecutor.TASKKILL))

	def test_oculto_real_sin_efectos(self):
		codigo, salida = ejecutor._oculto([ejecutor.CMD, "/c", "echo hola"])
		self.assertEqual((codigo, salida.strip()), (0, "hola"))
		self.assertEqual(ejecutor._oculto([os.path.join(tempfile.gettempdir(), "no_existe_tca.exe")])[0], -1)


# ====================================================================== explorador
class TestExplorador(unittest.TestCase):
	def setUp(self):
		self.dir = tempfile.mkdtemp(prefix="tca_exp_")
		self.addCleanup(shutil.rmtree, self.dir, True)
		for nombre in ("b.txt", "A.txt", "oculto.txt"):
			open(os.path.join(self.dir, nombre), "w").close()
		for nombre in ("zeta", "Alfa"):
			os.mkdir(os.path.join(self.dir, nombre))
		explorador._ponerAtributos(os.path.join(self.dir, "oculto.txt"), explorador.FILE_ATTRIBUTE_HIDDEN)

	def tearDown(self):
		for raiz, _d, archivos in os.walk(self.dir):
			for a in archivos:
				try:
					explorador._ponerAtributos(os.path.join(raiz, a), 0x80)
				except OSError:
					pass

	def test_listado_ordenado_sin_ocultos(self):
		self.assertEqual(explorador.listarCarpeta(self.dir), ["Alfa", "zeta", "A.txt", "b.txt"])

	def test_carpeta_de(self):
		self.assertEqual(explorador.carpetaDe(self.dir), self.dir)
		self.assertEqual(explorador.carpetaDe(os.path.join(self.dir, "b.txt")), self.dir)
		self.assertIsNone(explorador.carpetaDe(None))

	def test_ocultar_y_mostrar(self):
		ruta = os.path.join(self.dir, "b.txt")
		self.assertFalse(explorador.estaOculto(ruta))
		explorador.cambiarOculto(ruta, True)
		self.assertTrue(explorador.estaOculto(ruta))
		self.assertEqual([os.path.basename(p) for p in explorador.ocultosEn(self.dir)], ["b.txt", "oculto.txt"])
		explorador.cambiarOculto(ruta, False)
		self.assertFalse(explorador.estaOculto(ruta))
		carpeta = os.path.join(self.dir, "Alfa")
		explorador.cambiarOculto(carpeta, True)
		self.assertTrue(os.path.isdir(carpeta) and explorador.estaOculto(carpeta))

	def test_permiso_denegado_usa_attrib_elevado(self):
		ruta = os.path.join(self.dir, "b.txt")
		with mock.patch.object(explorador, "_ponerAtributos", side_effect=PermissionError(13, "x")), \
				mock.patch.object(explorador, "_attribElevado") as elev:
			explorador.cambiarOculto(ruta, True)
		elev.assert_called_once_with(ruta, True)

	def test_attrib_elevado(self):
		ruta = os.path.join(self.dir, "b.txt")
		with mock.patch.object(ejecutor, "elevado", return_value=0) as elev, mock.patch.object(explorador, "estaOculto", return_value=True):
			explorador._attribElevado(ruta, True)
		self.assertEqual(elev.call_args[0], (ejecutor.CMD, f'/c "attrib +h "{ruta}""'))
		with mock.patch.object(ejecutor, "elevado", side_effect=ejecutor.Cancelado()):
			with self.assertRaises(ejecutor.Cancelado):
				explorador._attribElevado(ruta, True)

	def test_salida_powershell(self):
		archivo = os.path.join(self.dir, "b.txt")
		salida = f"111|C:\\nada|C:\\\n1234|{archivo}|{self.dir}\n"
		self.assertEqual(explorador.analizarSalidaPowerShell(salida, 1234), (archivo, self.dir))
		self.assertEqual(explorador.analizarSalidaPowerShell(f"1234||{self.dir}", 1234), (None, self.dir))
		self.assertIsNone(explorador.analizarSalidaPowerShell(salida, 5))

	def test_elegir_pestana(self):
		a = types.SimpleNamespace(LocationName="Descargas")
		b = types.SimpleNamespace(LocationName="Documentos")
		self.assertIs(explorador._elegirVentana([a, b], "Documentos - Explorador de archivos"), b)
		self.assertIs(explorador._elegirVentana([a, b], "Otra"), a)
		self.assertIs(explorador._elegirVentana([b], ""), b)
		self.assertIsNone(explorador._elegirVentana([], "x"))

	def test_rutas(self):
		self.assertEqual(explorador.rutas(OTRA), (None, None))
		with mock.patch.object(explorador, "carpetaEscritorio", return_value=self.dir):
			ctx = Contexto(1, True, "Progman", "", "b.txt")
			self.assertEqual(explorador.rutas(ctx), (os.path.join(self.dir, "b.txt"), self.dir))
			ctx.nombreFoco = "no existe"
			self.assertEqual(explorador.rutas(ctx), (None, self.dir))
		with mock.patch.object(explorador, "_rutasCom", return_value=None):
			self.assertEqual(explorador.rutas(EXPLORADOR), (None, None))
		with mock.patch.object(explorador, "_rutasCom", return_value=("x", "y")):
			self.assertEqual(explorador.rutas(EXPLORADOR), ("x", "y"))

	def test_com_con_ventanas_falsas(self):
		archivo = os.path.join(self.dir, "b.txt")
		doc = types.SimpleNamespace(FocusedItem=types.SimpleNamespace(Path=archivo), Folder=types.SimpleNamespace(Self=types.SimpleNamespace(Path=self.dir)))
		ventana = types.SimpleNamespace(HWND=1234, LocationName="Documentos", Document=doc)
		otra = types.SimpleNamespace(HWND=5, LocationName="x", Document=None)
		lista = [otra, ventana]
		shell = types.SimpleNamespace(Windows=lambda: types.SimpleNamespace(Count=2, Item=lambda i: lista[i]))
		cc = types.ModuleType("comtypes.client")
		cc.CreateObject = lambda *a, **k: shell
		with mock.patch.dict(sys.modules, {"comtypes.client": cc}):
			self.assertEqual(explorador._rutasCom(EXPLORADOR), (archivo, self.dir))
			doc.FocusedItem = None
			self.assertEqual(explorador._rutasCom(EXPLORADOR), (None, self.dir))
			self.assertIsNone(explorador._rutasCom(Contexto(77, True, "CabinetWClass")))

	def test_contexto(self):
		from tiresias import winapi

		with mock.patch.object(winapi, "getForegroundWindow", return_value=10), mock.patch.object(winapi, "getWindowProcessId", return_value=4), \
				mock.patch.object(winapi, "getProcessName", return_value="explorer"), mock.patch.object(winapi, "getClassName", return_value="CabinetWClass"), \
				mock.patch.object(winapi, "getWindowText", return_value="Música"), \
				mock.patch("tiresias.api.getFocusObject", return_value=types.SimpleNamespace(name="canción.mp3")):
			ctx = explorador.capturarContexto()
			sinFoco = explorador.capturarContexto(leerFoco=False)
		self.assertEqual(ctx, Contexto(10, True, "CabinetWClass", "Música", "canción.mp3"))
		self.assertEqual(sinFoco.nombreFoco, "")
		self.assertFalse(ctx.esEscritorio)
		self.assertTrue(Contexto(1, True, "WorkerW").esEscritorio)


# ====================================================================== apagado
class TestApagado(Base):
	def test_apagar_reiniciar(self):
		funciones.apagar(OTRA)
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/s", "/t", "3"])
		funciones.sonidoApagado.assert_called_once()
		self.assertIn("Apagando el PC", self.mensajes[0])
		self.oculto.reset_mock()
		funciones.reiniciar(OTRA)
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/r", "/t", "3"])
		self.oculto.return_value = (1, "")
		funciones.apagar(OTRA)
		self.assertEqual(self.ultimo(), "No se pudo apagar el PC.")
		self.elevado.assert_not_called()

	def test_anular(self):
		for codigo, texto in ((0, "Anulando el apagado o reinicio del PC."), (1116, "No hay ningún apagado ni reinicio en curso."), (5, "No se pudo anular el apagado o reinicio del PC.")):
			self.oculto.return_value = (codigo, "")
			funciones.anularApagado(OTRA)
			self.assertEqual(self.ultimo(), texto)
		self.oculto.assert_called_with([ejecutor.SHUTDOWN, "/a"])

	def test_hibernar_y_suspender(self):
		self.oculto.return_value = (1, "")
		funciones.hibernar(OTRA)
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/h"])
		self.assertIn("hibernación esté desactivada", self.ultimo())
		with mock.patch.object(funciones, "suspenderSistema", return_value=True) as sus:
			funciones.suspender(OTRA)
		sus.assert_called_once_with()
		self.assertEqual(self.ultimo(), "Suspendiendo el sistema")
		with mock.patch.object(funciones, "suspenderSistema", return_value=False):
			funciones.suspender(OTRA)
		self.assertEqual(self.ultimo(), "No se pudo suspender el sistema.")

	def test_bios(self):
		self.preguntar.return_value = False
		funciones.entrarBios(OTRA)
		self.elevado.assert_not_called()
		self.preguntar.return_value = True
		funciones.entrarBios(OTRA)
		self.elevado.assert_called_once_with(ejecutor.SHUTDOWN, "/r /fw /t 3", esperar=True)
		self.assertIn("BIOS-UEFI", self.ultimo())
		self.elevado.return_value = 1
		funciones.entrarBios(OTRA)
		self.assertIn("firmware UEFI", self.ultimo())

	def test_modo_seguro_y_normal(self):
		self.preguntar.return_value = False
		funciones.modoSeguro(OTRA)
		self.elevado.assert_not_called()
		self.preguntar.return_value = True
		funciones.modoSeguro(OTRA)
		self.assertEqual(self.elevado.call_args[0], (ejecutor.CMD, '/c "bcdedit /set {default} safeboot network"'))
		self.assertNotIn("alternateshell", self.elevado.call_args[0][1].replace("deletevalue", ""))
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/r", "/t", "3"])
		self.assertEqual(self.ultimo(), "Modo seguro activado, se va a reiniciar el PC")
		self.oculto.reset_mock()
		funciones.modoNormal(OTRA)
		params = self.elevado.call_args[0][1]
		self.assertIn("bcdedit /deletevalue {default} safeboot", params)
		self.assertIn("safebootalternateshell", params)
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/r", "/t", "3"])
		self.oculto.reset_mock()
		self.elevado.return_value = 1
		funciones.modoNormal(OTRA)
		self.oculto.assert_not_called()
		self.assertIn("No se pudo desactivar el Modo seguro", self.ultimo())

	def test_cancelar_permiso(self):
		self.elevado.side_effect = ejecutor.Cancelado()
		funciones.entrarBios(OTRA)
		self.assertEqual(self.ultimo(), funciones.MSG_CANCELADO)

	def test_duracion_wav(self):
		d = tempfile.mkdtemp(prefix="tca_wav_")
		self.addCleanup(shutil.rmtree, d, True)
		ruta = os.path.join(d, "s.wav")
		_wav(ruta, 1.5)
		self.assertAlmostEqual(funciones.duracionWav(ruta), 1.5, places=2)
		self.assertEqual(funciones.duracionWav(os.path.join(d, "no.wav")), 0.0)
		real = funciones.rutaSonidoApagado()
		if os.path.isfile(real):
			self.assertGreater(funciones.duracionWav(real), 0.5)


class TestSonido(unittest.TestCase):
	def test_sonido_espera(self):
		d = tempfile.mkdtemp(prefix="tca_wav_")
		self.addCleanup(shutil.rmtree, d, True)
		ruta = os.path.join(d, "s.wav")
		_wav(ruta, 9)
		with mock.patch.object(funciones, "rutaSonidoApagado", return_value=ruta), mock.patch("tiresias.audio.tones.playWaveFile") as play, \
				mock.patch.object(funciones.time, "sleep") as dormir:
			funciones.sonidoApagado()
		play.assert_called_once_with(ruta)
		dormir.assert_called_once_with(6.0)


# ====================================================================== explorador y procesos
class TestExploradorYProcesos(Base):
	def test_reiniciar_explorador(self):
		with mock.patch.object(funciones, "_exploradorEnMarcha", return_value=False):
			funciones.reiniciarExplorador(OTRA)
		self.oculto.assert_called_once_with([ejecutor.TASKKILL, "/f", "/im", "explorer.exe"])
		self.abrir.assert_called_once_with(ejecutor.windows("explorer.exe"))
		self.abrir.reset_mock()
		with mock.patch.object(funciones, "_exploradorEnMarcha", return_value=True):
			funciones.reiniciarExplorador(OTRA)
		self.abrir.assert_not_called()
		self.elevado.assert_not_called()

	def test_borrar_portapapeles(self):
		with mock.patch.object(funciones, "_vaciarPortapapeles", return_value=True):
			funciones.borrarPortapapeles(OTRA)
			self.assertEqual(self.ultimo(), "Se limpió correctamente el portapapeles y su historial")
			self.elevado.assert_not_called()
			self.oculto.return_value = (2, "")
			funciones.borrarPortapapeles(OTRA)
			self.elevado.assert_called_once()
			self.assertEqual(self.ultimo(), "Se limpió correctamente el portapapeles y su historial")
			self.elevado.side_effect = ejecutor.Cancelado()
			funciones.borrarPortapapeles(OTRA)
			self.assertEqual(self.ultimo(), "Se vació el portapapeles, pero no se pudo borrar su historial")
		with mock.patch.object(funciones, "_vaciarPortapapeles", return_value=False):
			funciones.borrarPortapapeles(OTRA)
		self.assertEqual(self.ultimo(), "No fue posible borrar el portapapeles")
		self.assertIn("ClearHistory", funciones.PS_BORRAR_HISTORIAL)

	def test_cerrar_todas(self):
		with mock.patch.object(procesos, "cerrarTodas", return_value=procesos.Resultado(["a.exe", "b.exe"], ["c.exe"])) as cerrar:
			self.preguntar.return_value = False
			funciones.cerrarTodas(OTRA)
			cerrar.assert_not_called()
			self.preguntar.return_value = True
			funciones.cerrarTodas(OTRA)
		cerrar.assert_called_once()
		self.assertEqual(self.ultimo(), "Se cerraron 2 procesos: a.exe, b.exe. No se pudieron cerrar 1: c.exe.")
		with mock.patch.object(procesos, "cerrarTodas", return_value=procesos.Resultado()):
			funciones.cerrarTodas(OTRA)
		self.assertEqual(self.ultimo(), "No hay aplicaciones que cerrar.")

	def test_no_responden(self):
		with mock.patch.object(procesos, "cerrarNoResponden", return_value=procesos.Resultado()):
			funciones.cerrarNoResponden(OTRA)
		self.assertEqual(self.ultimo(), "No hay tareas que no respondan.")
		with mock.patch.object(procesos, "cerrarNoResponden", return_value=procesos.Resultado(["x.exe"])):
			funciones.cerrarNoResponden(OTRA)
		self.assertEqual(self.ultimo(), "Se cerraron 1 tareas que no respondían: x.exe.")

	def test_matar_procesos(self):
		with mock.patch.object(dialogos, "pedirTexto", return_value=None), mock.patch.object(procesos, "terminarPorNombre") as t:
			funciones.matarProcesos(OTRA)
			t.assert_not_called()
		with mock.patch.object(dialogos, "pedirTexto", return_value="  "):
			funciones.matarProcesos(OTRA)
		self.assertEqual(self.ultimo(), "Debe escribir el nombre de una aplicación")
		with mock.patch.object(dialogos, "pedirTexto", return_value="chrome"), mock.patch.object(procesos, "terminarPorNombre", return_value=procesos.Resultado(["chrome.exe"])) as t:
			funciones.matarProcesos(OTRA)
		t.assert_called_once_with("chrome")
		self.assertEqual(self.ultimo(), "Se terminaron todos los procesos de: chrome de forma correcta")
		with mock.patch.object(dialogos, "pedirTexto", return_value="nada"), mock.patch.object(procesos, "terminarPorNombre", return_value=procesos.Resultado()):
			funciones.matarProcesos(OTRA)
		self.assertEqual(self.ultimo(), "No se encontró ningún proceso de: nada")

	def test_menu_contexto(self):
		winreg = mock.MagicMock()
		winreg.HKEY_CURRENT_USER = "HKCU"
		winreg.KEY_SET_VALUE = 2
		winreg.REG_SZ = 1
		with mock.patch.dict(sys.modules, {"winreg": winreg}), mock.patch.object(funciones, "_exploradorEnMarcha", return_value=True):
			funciones.menuContextoClasico(OTRA)
			winreg.CreateKeyEx.assert_called_once_with("HKCU", funciones.CLAVE_MENU_CLASICO + r"\InprocServer32", 0, 2)
			winreg.SetValueEx.assert_called_once()
			self.assertIn("clásico habilitado", self.ultimo())
			funciones.menuContexto11(OTRA)
			self.assertEqual([c[0][1] for c in winreg.DeleteKey.call_args_list], [funciones.CLAVE_MENU_CLASICO + r"\InprocServer32", funciones.CLAVE_MENU_CLASICO])
		self.assertEqual(self.oculto.call_count, 2)  # Se reinicia el Explorador.
		self.assertIn("{86ca1aa0-34aa-4e8b-a509-50c905bae2a2}", funciones.CLAVE_MENU_CLASICO)


class TestProcesos(unittest.TestCase):
	class P:
		def __init__(self, pid, name, username="yo", exe=""):
			self.info = {"pid": pid, "name": name, "username": username, "exe": exe}

	def test_filtros(self):
		win = ejecutor.windows("explorer.exe")
		self.assertTrue(procesos.esDeWindows(win))
		self.assertTrue(procesos.esDeWindows(""))
		self.assertFalse(procesos.esDeWindows(r"C:\Program Files\App\app.exe"))
		self.assertTrue(procesos.esProtegido(5, "nvda.exe", set()))
		self.assertTrue(procesos.esProtegido(5, "Tiresias.exe", set()))
		self.assertTrue(procesos.esProtegido(7, "app.exe", {7}))
		self.assertFalse(procesos.esProtegido(8, "app.exe", {7}))

	def test_aplicaciones_del_usuario(self):
		lista = [
			self.P(10, "app.exe", exe=r"C:\Program Files\App\app.exe"),
			self.P(11, "explorer.exe", exe=ejecutor.windows("explorer.exe")),
			self.P(12, "nvda.exe", exe=r"C:\Program Files\NVDA\nvda.exe"),
			self.P(13, "otro.exe", username="otro", exe=r"C:\x\otro.exe"),
			self.P(os.getpid(), "python.exe", exe=r"C:\py\python.exe"),
		]
		falso = mock.Mock()
		falso.process_iter.return_value = lista
		falso.Process.return_value.username.return_value = "yo"
		with mock.patch.object(procesos, "_psutil", return_value=falso), mock.patch.object(procesos, "procesosDeTiresias", return_value={os.getpid()}):
			self.assertEqual(procesos.aplicacionesDelUsuario(), {10: "app.exe"})
			lista.append(self.P(14, "Chrome.exe"))
			self.assertEqual(procesos.coincidentes("chr"), {14: "Chrome.exe"})
			self.assertEqual(procesos.coincidentes("python"), {})
			self.assertEqual(procesos.coincidentes(""), {})

	def test_terminar(self):
		import psutil

		falso = mock.Mock()
		falso.NoSuchProcess, falso.AccessDenied, falso.TimeoutExpired = psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired
		procs = {1: mock.Mock(), 2: mock.Mock(), 3: mock.Mock()}
		procs[2].kill.side_effect = psutil.AccessDenied(2)
		procs[3].kill.side_effect = psutil.NoSuchProcess(3)
		falso.Process.side_effect = lambda pid: procs[pid]
		falso.pid_exists.return_value = False
		with mock.patch.object(procesos, "_psutil", return_value=falso), mock.patch.object(ejecutor, "elevado", return_value=0) as elev:
			res = procesos._terminar({1: "a.exe", 2: "b.exe", 3: "c.exe"})
		self.assertEqual(sorted(res.terminados), ["a.exe", "b.exe", "c.exe"])
		elev.assert_called_once_with(ejecutor.TASKKILL, "/f /pid 2", esperar=True)
		falso.pid_exists.return_value = True
		with mock.patch.object(procesos, "_psutil", return_value=falso), mock.patch.object(ejecutor, "elevado", side_effect=ejecutor.Cancelado()):
			res = procesos._terminar({2: "b.exe"})
		self.assertEqual((res.fallidos, res.cancelado), (["b.exe"], True))

	def test_tiresias_protegido(self):
		self.assertIn(os.getpid(), procesos.procesosDeTiresias())

	def test_ventanas_colgadas_reales(self):
		# Solo enumera (no termina nada).
		colgadas = procesos.ventanasColgadas()
		self.assertIsInstance(colgadas, dict)
		self.assertNotIn(os.getpid(), colgadas)


# ====================================================================== reparación y seguridad
class TestReparacion(Base):
	def test_reservado(self):
		funciones.desactivarReservado(OTRA)
		self.assertEqual(self.elevado.call_args[0][1], '/c "DISM.exe /Online /Set-ReservedStorageState /State:Disabled"')
		self.assertEqual(self.ultimo(), "Se desactivó el almacenamiento reservado")
		self.elevado.return_value = 87
		funciones.activarReservado(OTRA)
		self.assertIn("State:Enabled", self.elevado.call_args[0][1])
		self.assertIn("código 87", self.ultimo())

	def test_planes(self):
		funciones.planAltoRendimiento(OTRA)
		self.oculto.assert_called_with([ejecutor.system32("powercfg.exe"), "/setactive", "SCHEME_MIN"])
		self.assertEqual(self.ultimo(), "Plan alto rendimiento activado")
		self.oculto.return_value = (1, "")
		funciones.planEquilibrado(OTRA)
		self.oculto.assert_called_with([ejecutor.system32("powercfg.exe"), "/setactive", "SCHEME_BALANCED"])
		self.assertIn("No fue posible activar el plan equilibrado", self.ultimo())
		self.elevado.assert_not_called()

	def test_sfc_dism(self):
		funciones.analisisSfc(OTRA)
		self.elevado.assert_called_with(ejecutor.CMD, '/c "sfc /scannow & pause"', esperar=False, mostrar=ejecutor.SW_SHOWNORMAL)
		funciones.repararDism(OTRA)
		self.elevado.assert_called_with(ejecutor.CMD, '/c "DISM /Online /Cleanup-Image /RestoreHealth & pause"', esperar=False, mostrar=ejecutor.SW_SHOWNORMAL)

	def test_dns(self):
		funciones.limpiarDns(OTRA)
		self.elevado.assert_not_called()
		self.assertEqual(self.ultimo(), "Se limpió la caché DNS")
		self.oculto.return_value = (1, "")
		funciones.limpiarDns(OTRA)
		self.assertIn("ipconfig /flushdns", self.elevado.call_args[0][1])
		self.elevado.return_value = 1
		funciones.limpiarDns(OTRA)
		self.assertEqual(self.ultimo(), "No se pudo limpiar la caché DNS")

	def test_pantallas_seguras(self):
		d = tempfile.mkdtemp(prefix="tca_sys_")
		self.addCleanup(shutil.rmtree, d, True)
		with mock.patch.object(funciones, "carpetaConfigSistema", return_value=os.path.join(d, "no")), mock.patch.object(funciones, "_quitarConfigSistema") as quitar:
			funciones.limpiarPantallasSeguras(OTRA)
			quitar.assert_not_called()
			self.assertEqual(self.ultimo(), "No existen configuraciones guardadas en pantallas seguras")
		with mock.patch.object(funciones, "carpetaConfigSistema", return_value=d), mock.patch.object(funciones, "_quitarConfigSistema") as quitar:
			self.preguntar.return_value = False
			funciones.limpiarPantallasSeguras(OTRA)
			quitar.assert_not_called()
			self.preguntar.return_value = True
			funciones.limpiarPantallasSeguras(OTRA)
			quitar.assert_called_once_with()
			self.assertEqual(self.ultimo(), "Se limpió la configuración en pantallas seguras")
			quitar.side_effect = OSError("x")
			funciones.limpiarPantallasSeguras(OTRA)
			self.assertEqual(self.ultimo(), "No se pudo limpiar la configuración en pantallas seguras")
		from tiresias import installer

		self.assertTrue(callable(installer.removeSystemConfig))
		self.assertEqual(funciones.carpetaConfigSistema(), paths.SYSTEM_CONFIG_DIR)

	def test_limpiar_disco(self):
		cleanmgr = ejecutor.system32("cleanmgr.exe")
		funciones.registrarOpciones()
		try:
			with mock.patch.object(dialogos, "perfilLimpieza", return_value=(None, False)):
				funciones.limpiarDisco(OTRA)
			self.elevado.assert_not_called()
			with mock.patch.object(dialogos, "perfilLimpieza", return_value=(dialogos.CREAR_PERFIL, True)):
				funciones.limpiarDisco(OTRA)
			self.assertEqual([c[0] for c in self.elevado.call_args_list], [(cleanmgr, "/sageset:1"), (cleanmgr, "/sagerun:1")])
			self.assertTrue(self.elevado.call_args_list[0][1]["esperar"])
			self.assertFalse(conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"])
			self.elevado.reset_mock()
			with mock.patch.object(dialogos, "perfilLimpieza") as dlg:
				funciones.limpiarDisco(OTRA)
			dlg.assert_not_called()
			self.assertEqual([c[0] for c in self.elevado.call_args_list], [(cleanmgr, "/sagerun:1")])
			conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"] = True
			self.elevado.reset_mock()
			with mock.patch.object(dialogos, "perfilLimpieza", return_value=(dialogos.LIMPIAR, False)):
				funciones.limpiarDisco(OTRA)
			self.assertEqual([c[0] for c in self.elevado.call_args_list], [(cleanmgr, "/sagerun:1")])
			self.assertTrue(conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"])
		finally:
			conf["TCA_SystemUtilities"]["preguntarPerfilLimpieza"] = True

	def test_abrir_programas(self):
		casos = {
			"optimizarUnidades": (ejecutor.system32("dfrgui.exe"), None, None),
			"restablecerPC": ("ms-settings:recovery", None, None),
			"monitorRecursos": (ejecutor.system32("resmon.exe"), None, None),
			"opcionesSonido": (ejecutor.system32("control.exe"), "mmsys.cpl", None),
			"opcionesVoz": (ejecutor.system32("Speech", "SpeechUX", "sapi.cpl"), None, None),
			"asistenteCredenciales": (ejecutor.system32("credwiz.exe"), None, None),
			"bluetooth": (ejecutor.system32("fsquirt.exe"), None, None),
			"asistenteContrasena": (ejecutor.system32("rundll32.exe"), "keymgr.dll,PRShowSaveWizardExW", None),
			"mapaCaracteres": (ejecutor.system32("charmap.exe"), None, None),
		}
		for ident, esperado in casos.items():
			self.abrir.reset_mock()
			funciones.POR_ID[ident].funcion(OTRA)
			self.abrir.assert_called_once_with(*esperado)
		self.abrir.reset_mock()
		with mock.patch.dict(os.environ, {"APPDATA": r"C:\Users\x\AppData\Roaming"}):
			funciones.carpetaRoaming(OTRA)
		self.abrir.assert_called_once_with(r"C:\Users\x\AppData\Roaming", None, None)
		self.abrir.return_value = False
		funciones.mapaCaracteres(OTRA)
		self.assertEqual(self.ultimo(), "No se pudo abrir el mapa de caracteres.")
		self.elevado.assert_not_called()


class TestSeguridad(Base):
	def test_uac(self):
		self.assertIn("ConsentPromptBehaviorAdmin /t REG_DWORD /d 5 /f && reg add", funciones.ordenUac(5))
		self.assertIn(r'"HKLM\SOFTWARE\Microsoft\Windows\CurrentVersion\Policies\System"', funciones.ordenUac(0))
		with mock.patch.object(funciones, "leerUac", return_value=(5, 1)):
			funciones.desactivarUac(OTRA)
		self.assertIn("/d 0 /f", self.elevado.call_args[0][1])
		self.assertEqual(self.ultimo(), "Se ha desactivado el control de cuentas de usuario (uac). El cambio ya está en vigor.")
		with mock.patch.object(funciones, "leerUac", return_value=(0, 0)):
			funciones.activarUac(OTRA)
		self.assertIn("/d 5 /f", self.elevado.call_args[0][1])
		self.preguntar.assert_called()
		self.assertIn("reiniciar", self.preguntar.call_args[0][0])
		self.oculto.assert_called_once_with([ejecutor.SHUTDOWN, "/r", "/t", "3"])
		self.elevado.return_value = 1
		with mock.patch.object(funciones, "leerUac", return_value=(5, 1)):
			funciones.activarUac(OTRA)
		self.assertIn("No fue posible activar", self.ultimo())
		nivel, lua = funciones.leerUac()  # Solo lectura del registro.
		self.assertTrue(lua in (0, 1, None))

	def test_defender(self):
		d = tempfile.mkdtemp(prefix="tca_def_")
		self.addCleanup(shutil.rmtree, d, True)
		exe = os.path.join(d, "MpCmdRun.exe")
		with mock.patch.object(funciones, "rutaMpCmdRun", return_value=exe):
			funciones.analisisRapido(OTRA)
			self.elevado.assert_not_called()
			self.assertIn("Microsoft Defender", self.ultimo())
			open(exe, "w").close()
			funciones.analisisRapido(OTRA)
			self.assertEqual(self.elevado.call_args[0][1], f'/c ""{exe}" -Scan -ScanType 1 & pause"')
			funciones.analisisCompleto(OTRA)
			self.assertIn("-Scan -ScanType 2", self.elevado.call_args[0][1])
			funciones.analisisArranque(OTRA)
			self.assertIn('-Scan -ScanType 3 -File "', self.elevado.call_args[0][1])
			self.assertIn("-BootSectorScan", self.elevado.call_args[0][1])
			self.assertEqual(self.elevado.call_args[1], {"esperar": False, "mostrar": ejecutor.SW_SHOWNORMAL})

	def test_comprimidos(self):
		import base64

		funciones.escanearComprimidos(OTRA)
		self.assertEqual(self.elevado.call_args[0][0], ejecutor.powershell())
		script = base64.b64decode(self.elevado.call_args[0][1].split()[-1]).decode("utf-16-le")
		self.assertIn("Set-MpPreference -DisableArchiveScanning $false", script)
		self.assertEqual(self.ultimo(), "Se activó el escaneo de archivos comprimidos")
		funciones.noEscanearComprimidos(OTRA)
		script = base64.b64decode(self.elevado.call_args[0][1].split()[-1]).decode("utf-16-le")
		self.assertIn("-DisableArchiveScanning $true", script)

	def test_cuarentena(self):
		d = tempfile.mkdtemp(prefix="tca_def_")
		self.addCleanup(shutil.rmtree, d, True)
		exe = os.path.join(d, "MpCmdRun.exe")
		open(exe, "w").close()

		def escribir(archivo, params, **kw):
			destino = re.search(r'> "([^"]+)"', params).group(1)
			with open(destino, "wb") as f:
				f.write(b"Elemento en cuarentena: virus.exe")
			return 0

		self.elevado.side_effect = escribir
		with mock.patch.object(funciones, "rutaMpCmdRun", return_value=exe):
			funciones.cuarentena(OTRA)
		self.assertEqual(self.copiado, ["Elemento en cuarentena: virus.exe"])
		self.assertEqual(self.ultimo(), "Lista de archivos en cuarentena copiada al portapapeles")
		self.assertFalse(os.path.exists(funciones._archivoTemporal("cuarentena.txt")))
		self.elevado.side_effect = None
		with mock.patch.object(funciones, "rutaMpCmdRun", return_value=exe):
			funciones.cuarentena(OTRA)
		self.assertIn("No se pudo obtener la lista", self.ultimo())

	def test_webcam(self):
		self.assertIn("Disable-PnpDevice -Confirm:$false", funciones.scriptWebcam(False))
		self.assertIn("Enable-PnpDevice -Confirm:$false", funciones.scriptWebcam(True))
		self.assertIn("'Camera'", funciones.scriptWebcam(True))
		for codigo, texto in ((0, "Se desactivó la Webcam"), (3, "No se encontró ninguna webcam en el equipo"), (1, "No se pudo desactivar la Webcam")):
			self.elevado.return_value = codigo
			funciones.desactivarWebcam(OTRA)
			self.assertEqual(self.ultimo(), texto)
		self.elevado.return_value = 0
		funciones.activarWebcam(OTRA)
		self.assertEqual(self.ultimo(), "Se activó la Webcam")


# ====================================================================== archivos y carpetas
class TestArchivos(Base):
	def setUp(self):
		super().setUp()
		self.dir = tempfile.mkdtemp(prefix="tca_arch_")
		self.addCleanup(shutil.rmtree, self.dir, True)
		self.archivo = os.path.join(self.dir, "b.txt")
		open(self.archivo, "w").close()
		os.mkdir(os.path.join(self.dir, "sub"))
		open(os.path.join(self.dir, "sub", "dentro.txt"), "w").close()
		self.rutas = mock.patch.object(funciones, "obtenerRutas", return_value=(self.archivo, self.dir))
		self.rutas.start()
		self.addCleanup(self.rutas.stop)

	def tearDown(self):
		for raiz, _dirs, archivos in os.walk(self.dir):
			for a in archivos:
				try:
					explorador._ponerAtributos(os.path.join(raiz, a), 0x80)
				except OSError:
					pass

	def test_sin_explorador(self):
		for ident in ("copiarRuta", "copiarListado", "abrirCmd", "abrirCmdAdmin", "ocultar", "mostrarOcultos", "lanzadorConsolas"):
			self.mensajes.clear()
			funciones.POR_ID[ident].funcion(OTRA)
			self.assertEqual(self.mensajes, [explorador.MSG_ACTIVE_EXPLORADOR], ident)
		self.assertEqual(self.copiado, [])
		self.abrir.assert_not_called()

	def test_copiar_ruta(self):
		funciones.copiarRuta(EXPLORADOR)
		self.assertEqual(self.copiado, [f'"{self.archivo}"'])
		self.assertEqual(self.ultimo(), "Ruta copiada")
		funciones.obtenerRutas.return_value = (None, self.dir)
		funciones.copiarRuta(EXPLORADOR)
		self.assertEqual(self.copiado[-1], f'"{self.dir}"')
		funciones.obtenerRutas.return_value = (None, None)
		funciones.copiarRuta(EXPLORADOR)
		self.assertEqual(self.ultimo(), "No se pudo copiar la ruta")

	def test_copiar_listado(self):
		funciones.copiarListado(EXPLORADOR)
		self.assertEqual(self.copiado, ["sub\r\nb.txt"])
		funciones.obtenerRutas.return_value = (os.path.join(self.dir, "sub"), self.dir)
		funciones.copiarListado(EXPLORADOR)
		self.assertEqual(self.copiado[-1], "dentro.txt")
		vacia = os.path.join(self.dir, "vacía")
		os.mkdir(vacia)
		funciones.obtenerRutas.return_value = (vacia, self.dir)
		funciones.copiarListado(EXPLORADOR)
		self.assertEqual(self.ultimo(), "La carpeta no tiene elementos visibles")

	def test_cmd(self):
		funciones.abrirCmd(EXPLORADOR)
		self.abrir.assert_called_once_with(ejecutor.CMD, None, self.dir)
		funciones.abrirCmdAdmin(EXPLORADOR)
		self.elevado.assert_called_once_with(ejecutor.CMD, f'/k cd /d "{self.dir}"', False, ejecutor.SW_SHOWNORMAL)

	def test_ocultar_y_mostrar(self):
		funciones.ocultar(EXPLORADOR)
		self.assertTrue(explorador.estaOculto(self.archivo))
		self.assertIn('Elemento "b.txt" oculto correctamente', self.ultimo())
		funciones.ocultar(EXPLORADOR)
		self.assertEqual(self.ultimo(), 'El elemento "b.txt" ya está oculto')
		# El foco está en el elemento oculto: se muestra él.
		funciones.mostrarOcultos(EXPLORADOR)
		self.assertFalse(explorador.estaOculto(self.archivo))
		self.assertEqual(self.ultimo(), 'Elemento "b.txt" mostrado')
		# Foco en un elemento visible: se muestran los ocultos de su carpeta.
		otro = os.path.join(self.dir, "c.txt")
		open(otro, "w").close()
		explorador.cambiarOculto(otro, True)
		funciones.mostrarOcultos(EXPLORADOR)
		self.assertFalse(explorador.estaOculto(otro))
		self.assertEqual(self.ultimo(), f"Se mostraron 1 elementos ocultos en: {os.path.basename(self.dir)}")
		funciones.mostrarOcultos(EXPLORADOR)
		self.assertIn("No hay archivos ni carpetas ocultos", self.ultimo())
		funciones.obtenerRutas.return_value = (None, self.dir)
		funciones.ocultar(EXPLORADOR)
		self.assertIn("Seleccione un archivo o carpeta", self.ultimo())
		self.elevado.assert_not_called()

	def test_lanzador_consolas(self):
		ops = consolas.opciones({"cmd": ejecutor.CMD, "powershell": "ps.exe"})
		self.assertEqual([o.etiqueta for o in ops], ["Abrir CMD aquí", "Abrir CMD como Administrador", "Abrir PowerShell aquí", "Abrir PowerShell como Administrador"])
		with mock.patch.object(consolas, "opciones", return_value=ops), mock.patch.object(dialogos, "elegirConsola", return_value=None) as dlg:
			funciones.lanzadorConsolas(EXPLORADOR)
		dlg.assert_called_once_with(ops, self.dir)
		self.abrir.assert_not_called()
		with mock.patch.object(consolas, "opciones", return_value=ops), mock.patch.object(dialogos, "elegirConsola", return_value=ops[0]):
			funciones.lanzadorConsolas(EXPLORADOR)
		self.abrir.assert_called_once_with(ejecutor.CMD, f'/k pushd "{self.dir}"', self.dir)
		with mock.patch.object(consolas, "opciones", return_value=ops), mock.patch.object(dialogos, "elegirConsola", return_value=ops[3]):
			funciones.lanzadorConsolas(EXPLORADOR)
		self.elevado.assert_called_once_with("ps.exe", f"-NoExit -Command \"Set-Location -LiteralPath '{self.dir}'\"", esperar=False, mostrar=ejecutor.SW_SHOWNORMAL, carpeta=self.dir)

	def test_parametros_consolas(self):
		self.assertEqual(consolas.parametros("powershell", "C:\\l'a"), "-NoExit -Command \"Set-Location -LiteralPath 'C:\\l''a'\"")
		self.assertEqual(consolas.parametros("wt", "C:\\x"), '-d "C:\\x"')
		self.assertEqual(consolas.parametros("git-bash", "C:\\x"), '--cd="C:\\x"')
		with self.assertRaises(ValueError):
			consolas.parametros("zsh", "C:\\x")
		detectadas = consolas.detectar()
		self.assertEqual(detectadas["cmd"], ejecutor.CMD)

	def test_info_al_portapapeles(self):
		self.oculto.return_value = (0, "Nombre de host: PC\r\n")
		funciones.copiarInfoSistema(OTRA)
		self.oculto.assert_called_once_with([ejecutor.system32("systeminfo.exe")], 180)
		self.assertEqual(self.copiado, ["Nombre de host: PC"])
		self.assertEqual(self.mensajes, ["Obteniendo la información del sistema...", "Información del sistema copiada al portapapeles"])
		self.oculto.return_value = (0, "Name : Realtek\r\n")
		funciones.copiarInfoSonido(OTRA)
		self.assertEqual(self.copiado[-1], "Name : Realtek")
		self.assertEqual(self.ultimo(), "Copiada la info del sonido al portapapeles")
		self.assertIn("Win32_SoundDevice", funciones.PS_SONIDO)
		self.oculto.return_value = (1, "")
		funciones.copiarInfoSistema(OTRA)
		self.assertEqual(self.ultimo(), "No se pudo obtener la información del sistema")


# ====================================================================== diálogos
class TestDialogos(unittest.TestCase):
	def setUp(self):
		import wx

		self.app = wx.App.Get() or wx.App(False)

	def test_perfil_limpieza(self):
		import wx

		dlg = dialogos.DialogoPerfilLimpieza(None)
		try:
			self.assertEqual(dlg.GetTitle(), "Limpiar disco")
			self.assertEqual([dlg.btnCrear.GetLabel(), dlg.btnLimpiar.GetLabel(), dlg.btnCancelar.GetLabel()], ["&Crear perfil", "&Limpiar sin crear perfil", "Cancelar"])
			self.assertEqual(dlg.noMostrar.GetLabel(), "&No volver a mostrar este mensaje")
			with mock.patch.object(dlg, "EndModal") as fin:
				dlg._fin(dialogos.LIMPIAR)
			fin.assert_called_once_with(wx.ID_OK)
			self.assertEqual(dlg.respuesta, dialogos.LIMPIAR)
		finally:
			dlg.Destroy()

	def test_consolas(self):
		import wx

		ops = consolas.opciones({"cmd": ejecutor.CMD})
		dlg = dialogos.DialogoConsolas(None, ops, "C:\\x")
		try:
			self.assertEqual(dlg.GetTitle(), "Lanzador de consolas")
			self.assertEqual(dlg.lista.GetSelection(), 0)
			dlg.lista.SetSelection(1)
			with mock.patch.object(dlg, "EndModal") as fin:
				dlg.onAbrir()
			fin.assert_called_once_with(wx.ID_OK)
			self.assertEqual(dlg.elegida, ops[1])
		finally:
			dlg.Destroy()

	def test_preguntar(self):
		import wx

		from tiresias import gui

		with mock.patch.object(gui, "messageBox", return_value=wx.YES) as mb:
			self.assertTrue(dialogos.preguntar("¿Seguro?", "Título"))
		mb.assert_called_once_with("¿Seguro?", "Título", wx.YES_NO | wx.ICON_QUESTION)
		with mock.patch.object(gui, "messageBox", return_value=wx.NO):
			self.assertFalse(dialogos.preguntar("¿Seguro?", "Título"))


class TestProtegido(Base):
	def test_errores(self):
		def falla():
			raise RuntimeError("roto")

		funciones._protegido(falla)
		self.assertEqual(self.ultimo(), "Se produjo un error: roto")

		def cancela():
			raise ejecutor.Cancelado()

		funciones._protegido(cancela)
		self.assertEqual(self.ultimo(), funciones.MSG_CANCELADO)


if __name__ == "__main__":
	unittest.main()
