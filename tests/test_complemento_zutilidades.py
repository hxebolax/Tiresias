"""Pruebas del complemento zUtilidades (lanzador de aplicaciones y notas rápidas).

Sin interfaz visible ni ganchos: las ventanas se crean ocultas y no se
ejecuta ningún programa (ShellExecute y PowerShell se sustituyen).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_zutilidades -v``
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import pickle
import shutil
import sys
import tempfile
import types
import unittest
import zipfile
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_zutilidades_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

ADDON = os.path.join(ROOT, "complementos_tienda", "zUtilidades")
PKG = "zutil_prueba"


def _cargar(nombre: str):
	"""Carga un módulo del complemento como hace el cargador de Tiresias."""
	for name, path in ((PKG, ADDON), (f"{PKG}.globalPlugins", os.path.join(ADDON, "globalPlugins"))):
		if name not in sys.modules:
			mod = types.ModuleType(name)
			mod.__path__ = [path]  # type: ignore[attr-defined]
			sys.modules[name] = mod
	return importlib.import_module(f"{PKG}.globalPlugins.zUtilidades{('.' + nombre) if nombre else ''}")


plugin = _cargar("")
datos = _cargar("datos")
copias = _cargar("copias")
sistema = _cargar("sistema")
estado = _cargar("estado")
menu_virtual = _cargar("menu_virtual")


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self.dir = tempfile.mkdtemp(prefix="zut_datos_")
		datos.setBaseDir(self.dir)
		estado.ventanaAbierta = False

	def tearDown(self) -> None:
		datos.setBaseDir(None)
		estado.ventanaAbierta = False
		shutil.rmtree(self.dir, ignore_errors=True)

	def poblar(self, modulo=datos.LANZADOR):
		b = datos.BaseDatos(modulo)
		b.añadirCategoria("Internet")
		b.añadirCategoria("Oficina")
		b.añadirCategoria("Juegos")
		return b


# ====================================================================== datos
class PruebasDatos(Base):
	def test_carpeta_en_addonsData(self) -> None:
		datos.setBaseDir(None)
		self.assertEqual(datos.baseDir(), paths.addonDataDir("zUtilidades"))
		self.assertTrue(datos.moduloDir(datos.LANZADOR).endswith(os.path.join("addonsData", "zUtilidades", "zLauncher")))
		datos.setBaseDir(self.dir)

	def test_categorias(self) -> None:
		b = self.poblar()
		self.assertEqual(b.nombresCategorias(), ["Internet", "Oficina", "Juegos"])
		with self.assertRaises(ValueError):
			b.añadirCategoria("Oficina")
		b.renombrarCategoria(1, "Trabajo")
		b.renombrarCategoria(1, "Trabajo")  # mismo nombre: vale
		with self.assertRaises(ValueError):
			b.renombrarCategoria(1, "Juegos")
		self.assertEqual(b.moverCategoria(0, -1), None)
		self.assertEqual(b.moverCategoria(2, 1), None)
		self.assertEqual(b.moverCategoria(0, 1), 1)
		self.assertEqual(b.nombresCategorias(), ["Trabajo", "Internet", "Juegos"])
		archivo = b.categorias()[2]["archivo"]
		self.assertTrue(archivo.endswith(".json") and len(archivo) == 20)
		b.borrarCategoria(2)
		self.assertFalse(os.path.exists(b.rutaCategoria(archivo)))
		self.assertEqual(b.nombresCategorias(), ["Trabajo", "Internet"])

	def test_elementos(self) -> None:
		b = self.poblar()
		app = ["app", "Bloc", r"C:\Windows\notepad.exe", False, "", False]
		cmd = ["cmd", "Dir", "dir & echo hola", True, False]
		self.assertEqual(b.añadirElemento(0, app), 0)
		self.assertEqual(b.añadirElemento(0, cmd), 1)
		with self.assertRaises(ValueError):
			b.añadirElemento(0, ["fol", "Bloc", "C:\\"])
		self.assertEqual(b.nombresElementos(0), ["Bloc", "Dir"])
		self.assertEqual(b.moverElemento(0, 1, 1), None)
		self.assertEqual(b.moverElemento(0, 1, -1), 0)
		self.assertEqual(b.nombresElementos(0), ["Dir", "Bloc"])
		b.sustituirElemento(0, 1, ["app", "Bloc de notas", r"C:\Windows\notepad.exe", True, "a.txt", True])
		self.assertEqual(b.elementos(0)[1], ["app", "Bloc de notas", r"C:\Windows\notepad.exe", True, "a.txt", True])
		with self.assertRaises(ValueError):
			b.sustituirElemento(0, 1, ["app", "Dir", "x", False, "", False])
		b.borrarElemento(0, 0)
		self.assertEqual(b.nombresElementos(0), ["Bloc de notas"])
		self.assertEqual(b.elementos(99), [])

	def test_mover_a_categoria(self) -> None:
		b = self.poblar(datos.NOTAS)
		b.añadirElemento(0, ["txt", "Saludo", "Hola"])
		b.añadirElemento(1, ["txt", "Saludo", "Otro"])
		with self.assertRaises(ValueError):
			b.moverACategoria(0, 0, 1)
		b.moverACategoria(0, 0, 1, "Saludo 2")
		self.assertEqual(b.elementos(0), [])
		self.assertEqual(b.elementos(1), [["txt", "Saludo", "Otro"], ["txt", "Saludo 2", "Hola"]])
		b.moverACategoria(1, 0, 2)
		self.assertEqual(b.elementos(2), [["txt", "Saludo", "Otro"]])

	def test_comprobar_y_borrar_todo(self) -> None:
		b = self.poblar()
		os.remove(b.rutaCategoria(b.categorias()[1]["archivo"]))
		self.assertEqual(b.comprobar(), 1)
		self.assertEqual(b.nombresCategorias(), ["Internet", "Juegos"])
		b.borrarTodo()
		self.assertEqual(b.nombresCategorias(), [])
		self.assertEqual(os.listdir(b.carpeta), ["index.json"])

	def test_normalizar(self) -> None:
		self.assertEqual(datos._normalizarElemento(["app", "x", "y"]), ["app", "x", "y", False, "", False])
		self.assertEqual(datos._normalizarElemento(["cmd", "x", "y", 1, 0]), ["cmd", "x", "y", True, False])
		self.assertIsNone(datos._normalizarElemento(["zzz", "x", "y"]))
		self.assertIsNone(datos._normalizarElemento("texto"))

	def test_validacion(self) -> None:
		self.assertEqual(datos.validarCategoria("", []), datos.MSG_VACIO_CATEGORIA)
		self.assertEqual(datos.validarCategoria("A", ["A"]), datos.MSG_DUPLICADO_CATEGORIA)
		self.assertIsNone(datos.validarCategoria("A", ["A"], "A"))
		self.assertIsNone(datos.validarCategoria("B", ["A"]))
		self.assertTrue(datos.nombreDuplicado("A", ["A"]))
		self.assertFalse(datos.nombreDuplicado("A", ["A"], "A"))


# ====================================================================== copias
def _zipNVDA(destino: str, modulo: str, archivos: dict) -> None:
	"""Copia como las del complemento de NVDA (pickle y firma MD5)."""
	with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
		for fn, objetos in archivos.items():
			data = b"".join(pickle.dumps(o) for o in objetos)
			z.writestr(f"{modulo}/{fn}", data)
	with zipfile.ZipFile(destino) as z:
		firma = hashlib.md5("-".join(z.namelist()).encode("utf-8")).hexdigest()
	with zipfile.ZipFile(destino, "a") as z:
		z.comment = firma.encode("utf-8")


class PruebasCopias(Base):
	def test_copia_y_restauracion(self) -> None:
		b = self.poblar(datos.NOTAS)
		b.añadirElemento(1, ["txt", "Dirección", "Calle Mayor, 1"])
		destino = os.path.join(self.dir, "copia.zut-zn")
		avisos = []
		copias.hacerCopia(datos.NOTAS, destino, lambda p, t: avisos.append((p, t)))
		self.assertTrue(copias.firmaValida(destino))
		self.assertEqual(avisos[-1][0], 100)
		with zipfile.ZipFile(destino) as z:
			self.assertTrue(all(n.startswith("zNotes/") for n in z.namelist()))
		b.borrarTodo()
		self.assertEqual(copias.restaurarCopia(datos.NOTAS, destino), 3)
		self.assertEqual(b.nombresCategorias(), ["Internet", "Oficina", "Juegos"])
		self.assertEqual(b.elementos(1), [["txt", "Dirección", "Calle Mayor, 1"]])

	def test_nombre_por_defecto(self) -> None:
		self.assertRegex(copias.nombrePorDefecto(), r"^Backup-\d{14}$")

	def test_firma_alterada(self) -> None:
		self.poblar()
		destino = os.path.join(self.dir, "copia.zut-zl")
		copias.hacerCopia(datos.LANZADOR, destino)
		with zipfile.ZipFile(destino, "a") as z:
			z.writestr("zLauncher/extra.json", "{}")
		self.assertFalse(copias.firmaValida(destino))
		with self.assertRaises(ValueError):
			copias.restaurarCopia(datos.LANZADOR, destino)
		self.assertEqual(datos.BaseDatos(datos.LANZADOR).nombresCategorias(), ["Internet", "Oficina", "Juegos"])

	def test_copia_de_otro_modulo(self) -> None:
		self.poblar()
		destino = os.path.join(self.dir, "copia.zut-zl")
		copias.hacerCopia(datos.LANZADOR, destino)
		with self.assertRaises(ValueError):
			copias.restaurarCopia(datos.NOTAS, destino)

	def test_rutas_peligrosas(self) -> None:
		destino = os.path.join(self.dir, "mala.zut-zn")
		_zipNVDA(destino, "zNotes", {"../../fuera.dat": [1.0, []]})
		with self.assertRaises(ValueError):
			copias.restaurarCopia(datos.NOTAS, destino)
		self.assertFalse(os.path.exists(os.path.join(self.dir, "fuera.dat")))

	def test_restaurar_copia_de_nvda(self) -> None:
		destino = os.path.join(self.dir, "nvda.zut-zl")
		_zipNVDA(
			destino,
			"zLauncher",
			{
				"index.dat": [1.0, ["Sistema", "Vacía"], ["AbCdEfGhIjKlMnO.dat", "ZZZZZZZZZZZZZZZ.dat"]],
				"AbCdEfGhIjKlMnO.dat": [1.0, [["cmd", "Reiniciar explorador", "taskkill /f /im explorer.exe & start explorer", False, True], ["sap", "Calculadora", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", False]]],
				"ZZZZZZZZZZZZZZZ.dat": [1.0, []],
			},
		)
		self.assertEqual(copias.restaurarCopia(datos.LANZADOR, destino), 2)
		b = datos.BaseDatos(datos.LANZADOR)
		self.assertEqual(b.nombresCategorias(), ["Sistema", "Vacía"])
		self.assertEqual(b.elementos(0)[1], ["sap", "Calculadora", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App", False])
		self.assertFalse(any(f.endswith(".dat") for f in os.listdir(b.carpeta)))

	def test_pickle_con_objetos_rechazado(self) -> None:
		destino = os.path.join(self.dir, "mala.zut-zl")
		_zipNVDA(destino, "zLauncher", {"index.dat": [1.0, ["A"], ["x.dat"]], "x.dat": [1.0, [os.getcwd]]})
		with self.assertRaises(Exception):
			copias.restaurarCopia(datos.LANZADOR, destino)


# ====================================================================== sistema
class PruebasSistema(Base):
	def test_parametros(self) -> None:
		P = sistema.ParametrosEjecucion
		self.assertEqual(sistema.parametrosEjecucion(["app", "n", r"C:\p\a.exe", False, "x", False]), P("open", r"C:\p\a.exe", None, r"C:\p"))
		self.assertEqual(sistema.parametrosEjecucion(["app", "n", r"C:\p\a.exe", True, "-v", True]), P("runas", r"C:\p\a.exe", "-v", r"C:\p"))
		self.assertEqual(sistema.parametrosEjecucion(["cmd", "n", "dir", False, False]), P("open", "cmd.exe", "/cdir", None))
		self.assertEqual(sistema.parametrosEjecucion(["cmd", "n", "dir", True, True]), P("runas", "cmd.exe", "/cdir&pause", None))
		self.assertEqual(sistema.parametrosEjecucion(["fol", "n", "C:\\"]), P("explore", "C:\\", None, None))
		self.assertEqual(sistema.parametrosEjecucion(["adr", "n", "C:\\a.lnk", True]), P("runas", "C:\\a.lnk", None, None))
		self.assertEqual(sistema.parametrosEjecucion(["sap", "n", "Id!App", False]), P("open", "explorer.exe", "shell:appsfolder\\Id!App", None))
		with self.assertRaises(ValueError):
			sistema.parametrosEjecucion(["txt", "n", "x"])

	def test_rutas(self) -> None:
		self.assertTrue(sistema.rutaNoEncontrada(["app", "n", r"C:\no\existe.exe", False, "", False]))
		self.assertFalse(sistema.rutaNoEncontrada(["fol", "n", self.dir]))
		self.assertFalse(sistema.rutaNoEncontrada(["cmd", "n", "dir", False, False]))
		self.assertIn("Ejecute el lanzador", sistema.mensajeRutaNoEncontrada(["fol", "n", "C:\\x"], False))
		self.assertIn("¿Desea editar", sistema.mensajeRutaNoEncontrada(["app", "Bloc", "C:\\x", False, "", False], True))

	def test_ejecutar_sin_lanzar_nada(self) -> None:
		llamadas, errores = [], []
		with mock.patch.object(sistema, "shellExecute", side_effect=lambda p: llamadas.append(p) or 42):
			sistema.ejecutar(["cmd", "n", "dir", False, False], errores.append).join(5)
		self.assertEqual(llamadas[0].archivo, "cmd.exe")
		self.assertEqual(errores, [])
		with mock.patch.object(sistema, "shellExecute", return_value=2):
			sistema.ejecutar(["fol", "n", "C:\\"], errores.append).join(5)
		self.assertEqual(len(errores), 1)
		self.assertIn("2 (archivo no encontrado)", errores[0])
		with mock.patch.object(sistema, "shellExecute", return_value=5):
			sistema.ejecutar(["adr", "n", "C:\\a.lnk", True], errores.append).join(5)
		self.assertEqual(len(errores), 1)  # Control de cuentas cancelado: sin aviso.

	def test_start_apps(self) -> None:
		salida = json.dumps([{"Name": "Calculadora", "AppID": "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App"}, {"Name": "", "AppID": "x"}])
		self.assertEqual(sistema.analizarStartApps(salida), [("Calculadora", "Microsoft.WindowsCalculator_8wekyb3d8bbwe!App")])
		self.assertEqual(sistema.analizarStartApps('{"Name":"Uno","AppID":"a b"}'), [("Uno", "a b")])
		self.assertEqual(sistema.analizarStartApps(""), [])

	def test_texto_y_url(self) -> None:
		self.assertEqual(sistema.unirTextoYUrl("hola", None), "hola")
		self.assertEqual(sistema.unirTextoYUrl("hola", "https://a.es"), "hola\n\nhttps://a.es")

	def test_seleccion_y_url_con_objetos_simulados(self) -> None:
		from tiresias.objects.roles import Role

		class Info:
			def __init__(self, texto):
				self.text = texto
				self.isCollapsed = not texto

		class Obj:
			def __init__(self, texto="", role=None, value="", parent=None, ti=None):
				self._t = texto
				self.role = role
				self.value = value
				self.parent = parent
				self.treeInterceptor = ti

			def makeTextInfo(self, pos):
				return Info(self._t)

		doc = Obj(role=Role.DOCUMENT, value="https://ejemplo.es/pagina")
		foco = Obj("texto elegido", role=Role.EDITABLETEXT, parent=doc)
		with mock.patch("tiresias.api.getCaretObject", return_value=foco), mock.patch("tiresias.api.getFocusObject", return_value=foco):
			self.assertEqual(sistema.textoSeleccionado(), "texto elegido")
			self.assertEqual(sistema.urlDocumento(), "https://ejemplo.es/pagina")
		vacio = Obj("")
		with mock.patch("tiresias.api.getCaretObject", return_value=vacio), mock.patch("tiresias.api.getFocusObject", return_value=vacio):
			self.assertIsNone(sistema.textoSeleccionado())
			self.assertIsNone(sistema.urlDocumento())
		ti = mock.Mock()
		ti.documentUrl.return_value = "https://modo.exploracion/"
		con = Obj("x", ti=ti)
		with mock.patch("tiresias.api.getFocusObject", return_value=con):
			self.assertEqual(sistema.urlDocumento(), "https://modo.exploracion/")

	def test_pegar_en_foco(self) -> None:
		from tiresias import queue_handler, winapi

		portapapeles = {"t": "anterior"}
		pendientes = []
		with mock.patch.object(winapi, "getClipboardText", side_effect=lambda: portapapeles["t"]), mock.patch.object(
			winapi, "setClipboardText", side_effect=lambda t: portapapeles.__setitem__("t", t) or True
		), mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: pendientes.append((f, a))), mock.patch.object(
			winapi, "getForegroundWindow", return_value=1
		), mock.patch.object(winapi, "getClassName", return_value="Notepad"), mock.patch("tiresias.input.gestures.sendKey") as enviar, mock.patch.object(
			sistema, "mensaje"
		) as decir:
			sistema.pegarEnFoco("nota")
			self.assertEqual(portapapeles["t"], "nota")
			f, a = pendientes.pop(0)
			f(*a)
			enviar.assert_called_once_with("control+v")
			decir.assert_called_once_with("Nota pegada en el foco")
			f, a = pendientes.pop(0)
			f(*a)
			self.assertEqual(portapapeles["t"], "anterior")


# ====================================================================== menú virtual
class PruebasMenuVirtual(Base):
	def setUp(self) -> None:
		super().setUp()
		self.dichos: list[str] = []
		self.m = menu_virtual.MenuVirtual(self.dichos.append)
		self.m.pitido = mock.Mock()
		self.m.ejecutarAccion = mock.Mock()
		self.m.pegar = mock.Mock()
		self.m.copiar = mock.Mock(return_value=True)

	def test_sin_categorias(self) -> None:
		self.assertFalse(self.m.activar(datos.LANZADOR))
		self.assertEqual(self.dichos, ["No hay categorías"])
		self.assertFalse(estado.ventanaAbierta)

	def test_otra_ventana_abierta(self) -> None:
		self.poblar()
		estado.ventanaAbierta = True
		self.assertFalse(self.m.activar(datos.LANZADOR))
		self.assertEqual(self.dichos, [estado.MSG_INSTANCIA])

	def test_navegacion_lanzador(self) -> None:
		b = self.poblar()
		b.añadirElemento(1, ["cmd", "Dir", "dir", False, False])
		b.añadirElemento(1, ["fol", "Raíz", self.dir])
		self.assertTrue(self.m.activar(datos.LANZADOR))
		self.assertTrue(estado.ventanaAbierta)
		self.assertEqual(self.dichos, ["Menú activado", menu_virtual.AYUDA_LANZADOR, "Internet"])
		self.dichos.clear()
		self.m.accionParaTecla("downarrow")()
		self.m.accionParaTecla("enter")()
		self.m.accionParaTecla("rightarrow")()
		self.m.accionParaTecla("enter")()
		self.m.accionParaTecla("uparrow")()
		self.m.accionParaTecla("uparrow")()
		self.m.accionParaTecla("leftarrow")()
		self.m.accionParaTecla("leftarrow")()
		self.assertEqual(self.dichos, ["Sin acción", menu_virtual.AYUDA_LANZADOR, "Oficina", menu_virtual.AYUDA_LANZADOR, "Raíz", "Dir", "Internet", "Juegos"])
		self.dichos.clear()
		self.m.accionParaTecla("o")()
		self.m.accionParaTecla("downarrow")()
		self.m.accionParaTecla("numpadenter")()
		self.assertEqual(self.dichos, ["Oficina", "Dir", "Ejecutando acción", "Saliendo del menú"])
		self.m.ejecutarAccion.assert_called_once_with(["cmd", "Dir", "dir", False, False])
		self.assertFalse(self.m.activo)
		self.assertFalse(estado.ventanaAbierta)
		# Se recuerda la posición.
		self.dichos.clear()
		self.m.activar(datos.LANZADOR)
		self.assertEqual(self.dichos, ["Menú activado", "Oficina"])

	def test_letras_y_ayuda(self) -> None:
		self.poblar()
		self.m.activar(datos.LANZADOR)
		self.dichos.clear()
		self.m.accionParaTecla("j")()
		self.m.accionParaTecla("j")()
		self.m.accionParaTecla("x")()
		self.m.accionParaTecla("control+a")()
		self.m.accionParaTecla("f1")()
		self.assertEqual(self.dichos, ["Juegos", "Juegos", menu_virtual.AYUDA_LANZADOR, menu_virtual.AYUDA_LANZADOR])
		self.m.pitido.assert_called_once_with(200, 30)
		self.m.accionParaTecla("escape")()
		self.assertEqual(self.dichos[-1], "Saliendo del menú")
		self.assertFalse(self.m.activo)

	def test_ruta_inexistente(self) -> None:
		b = self.poblar()
		b.añadirElemento(0, ["app", "Falta", r"C:\no\existe.exe", False, "", False])
		self.m.activar(datos.LANZADOR)
		self.m.accionParaTecla("downarrow")()
		self.m.accionParaTecla("enter")()
		self.assertIn("Ejecute el lanzador de aplicaciones en modo grafico", self.dichos[-1])
		self.m.ejecutarAccion.assert_not_called()

	def test_notas(self) -> None:
		b = self.poblar(datos.NOTAS)
		b.añadirElemento(0, ["txt", "Firma", "Un saludo, Héctor"])
		self.m.activar(datos.NOTAS)
		self.assertIn(menu_virtual.AYUDA_NOTAS, self.dichos)
		self.dichos.clear()
		self.m.accionParaTecla("f1")()
		self.assertEqual(self.dichos, [menu_virtual.AYUDA_NOTAS])
		self.m.accionParaTecla("enter")()  # Intro no hace nada en notas: ayuda.
		self.m.accionParaTecla("downarrow")()
		self.m.accionParaTecla("f1")()
		self.assertEqual(self.dichos[-2:], ["Firma", "Un saludo, Héctor"])
		self.m.accionParaTecla("f2")()
		self.m.copiar.assert_called_once_with("Un saludo, Héctor")
		self.assertEqual(self.dichos[-2:], ["Se ha copiado la nota Firma al portapapeles", "Saliendo del menú"])
		self.assertFalse(self.m.activo)
		self.m.activar(datos.NOTAS)
		self.m.accionParaTecla("f3")()
		self.m.pegar.assert_called_once_with("Un saludo, Héctor")
		self.assertFalse(estado.ventanaAbierta)

	def test_categoria_sin_notas(self) -> None:
		self.poblar(datos.NOTAS)
		self.m.activar(datos.NOTAS)
		self.m.accionParaTecla("downarrow")()
		self.assertEqual(self.dichos[-1], "Sin notas")

	def test_cambia_el_numero_de_categorias(self) -> None:
		b = self.poblar()
		self.m.activar(datos.LANZADOR)
		self.m.accionParaTecla("rightarrow")()
		self.m.salir()
		b.añadirCategoria("Nueva")
		self.dichos.clear()
		self.m.activar(datos.LANZADOR)
		self.assertEqual(self.dichos, ["Menú activado", "Internet"])


# ====================================================================== complemento global
class Gesto:
	def __init__(self, teclas: str, prefijo: str = "kb") -> None:
		self.normalizedKeys = teclas
		self.identifiers = [f"{prefijo}(desktop):{teclas}", f"{prefijo}:{teclas}"] if prefijo == "kb" else [f"{prefijo}:{teclas}"]


class PruebasComplemento(Base):
	def setUp(self) -> None:
		super().setUp()
		from tiresias import gui

		self.gui = gui
		self.p = plugin.GlobalPlugin()
		self.dichos: list[str] = []
		self.p.menu.decir = self.dichos.append

	def tearDown(self) -> None:
		with mock.patch.object(plugin, "_enGui"):
			self.p.terminate()
		super().tearDown()

	def test_registro_menu_y_opciones(self) -> None:
		from tiresias.config import conf
		from tiresias.gui import settings as S

		self.assertIn("zUtilidades", self.gui._addonToolsEntries)
		etiqueta, accion, submenu = self.gui._addonToolsEntries["zUtilidades"]
		self.assertTrue(submenu)
		self.assertEqual([e[0] for e in accion()], ["&Lanzador de Aplicaciones", "&Notas rápidas"])
		self.assertIn("zUtilidades", S._panels)
		self.assertFalse(conf["zUtilidades"]["tituloCaptura"])
		self.assertFalse(conf["zUtilidades"]["urlCaptura"])
		with mock.patch.object(plugin, "_enGui"):
			self.p.terminate()
		self.assertNotIn("zUtilidades", self.gui._addonToolsEntries)
		self.assertNotIn("zUtilidades", S._panels)

	def test_ordenes_sin_gesto_con_descripcion(self) -> None:
		for nombre in ("zLauncher", "zNotes", "zNotesCopy"):
			f = getattr(plugin.GlobalPlugin, "script_" + nombre)
			self.assertTrue(f.__doc__)
			self.assertEqual(f.category, "zUtilidades")
			self.assertEqual(f.gestures, [])
		self.assertEqual(dict(plugin.GlobalPlugin._classGestures), {})

	def test_menu_virtual_captura_teclas(self) -> None:
		self.assertIsNone(self.p.getScript(Gesto("downarrow")))
		b = self.poblar()
		b.añadirElemento(0, ["cmd", "Dir", "dir", False, False])
		self.p.menu.activar(datos.LANZADOR)
		self.dichos.clear()
		f = self.p.getScript(Gesto("downarrow"))
		self.assertIsNotNone(f)
		f(None)
		self.assertEqual(self.dichos, ["Dir"])
		self.p.getScript(Gesto("alt+tab"))(None)
		self.assertEqual(self.dichos[-1], menu_virtual.AYUDA_LANZADOR)
		# Las líneas braille siguen funcionando.
		self.assertIsNone(self.p.getScript(Gesto("routing", prefijo="br(freedomScientific)")))
		self.p.getScript(Gesto("escape"))(None)
		self.assertFalse(self.p.menu.activo)
		self.assertIsNone(self.p.getScript(Gesto("downarrow")))

	def test_una_y_dos_pulsaciones(self) -> None:
		from tiresias import queue_handler
		from tiresias.input import core as inputCore

		self.poblar()
		programados = []
		with mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: programados.append((ms, f, a)) or 7), mock.patch.object(
			queue_handler, "cancelCallLater"
		) as cancelar, mock.patch.object(plugin, "_enGui") as enGui, mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=0):
			self.p.script_zLauncher(None)
			self.assertEqual(len(programados), 1)
			ms, f, a = programados[0]
			f(*a)
			enGui.assert_called_once_with(plugin._abrirLanzador)
		programados.clear()
		with mock.patch.object(queue_handler, "callLater", side_effect=lambda ms, f, *a: programados.append((ms, f, a)) or 8), mock.patch.object(
			queue_handler, "cancelCallLater"
		) as cancelar, mock.patch.object(plugin, "_enGui") as enGui:
			with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=0):
				self.p.script_zLauncher(None)
			with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=1):
				self.p.script_zLauncher(None)
			cancelar.assert_called_with(8)
			enGui.assert_not_called()
		self.assertTrue(self.p.menu.activo)
		self.p.menu.salir()

	def test_nota_de_seleccion(self) -> None:
		from tiresias.config import conf

		with mock.patch.object(plugin, "_enGui") as enGui, mock.patch.object(sistema, "textoSeleccionado", return_value=None), mock.patch.object(sistema, "mensaje") as decir:
			self.p.notaDeSeleccion()
			decir.assert_called_once_with(plugin.MSG_SELECCIONE)
			enGui.assert_not_called()
		conf["zUtilidades"]["urlCaptura"] = True
		conf["zUtilidades"]["tituloCaptura"] = True
		try:
			with mock.patch.object(plugin, "_enGui") as enGui, mock.patch.object(sistema, "textoSeleccionado", return_value="hola"), mock.patch.object(
				sistema, "urlDocumento", return_value="https://a.es"
			), mock.patch.object(sistema, "tituloVentana", return_value="Mi ventana"):
				self.p.notaDeSeleccion()
				enGui.assert_called_once_with(plugin._abrirNotaRapida, "hola\n\nhttps://a.es", "Mi ventana", False)
				enGui.reset_mock()
				self.p.notaNueva()
				enGui.assert_called_once_with(plugin._abrirNotaRapida, "https://a.es", "Mi ventana", True)
			with mock.patch.object(plugin, "_enGui") as enGui, mock.patch.object(sistema, "tituloVentana", return_value=None), mock.patch.object(sistema, "urlDocumento", return_value=None):
				self.p.notaNueva()
				enGui.assert_called_once_with(plugin._abrirNotaRapida, None, plugin.MSG_SIN_TITULO, True)
		finally:
			conf["zUtilidades"]["urlCaptura"] = False
			conf["zUtilidades"]["tituloCaptura"] = False

	def test_una_sola_instancia(self) -> None:
		estado.ventanaAbierta = True
		with mock.patch.object(plugin, "_enGui") as enGui, mock.patch.object(sistema, "mensaje") as decir:
			self.p._abrirVentana(plugin._abrirLanzador)
			self.p.notaNueva()
			enGui.assert_not_called()
			self.assertEqual(decir.call_count, 2)
			decir.assert_called_with(estado.MSG_INSTANCIA)


# ====================================================================== ventanas (ocultas)
class PruebasVentanas(Base):
	@classmethod
	def setUpClass(cls) -> None:
		import wx

		cls.app = wx.App.Get() or wx.App(False)

	def setUp(self) -> None:
		super().setUp()
		self.comun = _cargar("comun")
		self.lanzador = _cargar("lanzador")
		self.notas = _cargar("notas")
		self.avisos: list[str] = []
		self.parches = [
			mock.patch.object(self.comun, "mensaje", side_effect=lambda parent, texto, *a, **k: self.avisos.append(texto)),
			mock.patch.object(self.lanzador, "mensaje", side_effect=lambda parent, texto, *a, **k: self.avisos.append(texto)),
			mock.patch.object(self.notas, "mensaje", side_effect=lambda parent, texto, *a, **k: self.avisos.append(texto)),
		]
		for p in self.parches:
			p.start()

	def tearDown(self) -> None:
		for p in self.parches:
			p.stop()
		super().tearDown()

	def test_ventana_lanzador_vacia(self) -> None:
		v = self.lanzador.VentanaLanzador()
		try:
			self.assertTrue(estado.ventanaAbierta)
			self.assertEqual(v.lstCategorias.GetStrings(), ["No hay categorías"])
			self.assertEqual(v.lstElementos.GetStrings(), ["Sin acciones"])
			v.editarCategoria()
			v.editar()
			self.assertEqual(len(self.avisos), 2)
			self.assertIn("No tiene ninguna categoría para Editar", self.avisos[0])
			self.assertIn("Agregue una categoría antes para poder añadir una acción", self.avisos[1])
			etiquetas = [e[0] for e in v.entradasMenu()]
			self.assertEqual(etiquetas, ["&Categorías", "&Acciones", "&Hacer o restaurar copias de seguridad", "&Opciones", "&Salir"])
			self.assertEqual([e[0] for e in v.entradasAñadir()], ["Añadir &aplicación", "Añadir comando &CMD", "Añadir accesos a car&petas", "Añadir ejecutar accesos directos de &Windows", "Añadir aplicación &instalada"])
		finally:
			v.cerrar()
		self.assertFalse(estado.ventanaAbierta)

	def test_ventana_lanzador_con_datos_y_posicion(self) -> None:
		b = self.poblar()
		b.añadirElemento(1, ["cmd", "A", "dir", False, False])
		b.añadirElemento(1, ["cmd", "B", "dir", False, False])
		v = self.lanzador.VentanaLanzador()
		try:
			v.lstCategorias.SetSelection(1)
			v.refrescarElementos()
			self.assertEqual(v.lstElementos.GetStrings(), ["A", "B"])
			v.lstElementos.SetSelection(1)
			with mock.patch.object(sistema, "pitido") as pitido:
				v.moverElemento(1)
				pitido.assert_called_once_with(200, 150)
			v.moverElemento(-1)
			self.assertEqual(v.lstElementos.GetStrings(), ["B", "A"])
			self.assertEqual(b.nombresElementos(1), ["B", "A"])
			v.lstCategorias.SetSelection(1)
			v.moverCategoria(1)
			self.assertEqual(b.nombresCategorias(), ["Internet", "Juegos", "Oficina"])
			self.assertEqual(v.lstCategorias.GetSelection(), 2)
		finally:
			v.cerrar()
		self.assertEqual(estado.sesiones[datos.LANZADOR].posicion[0], 2)
		v2 = self.lanzador.VentanaLanzador()
		try:
			self.assertEqual(v2.lstCategorias.GetSelection(), 2)
		finally:
			v2.cerrar(guardarPosicion=False)
		estado.sesiones[datos.LANZADOR].reiniciar()

	def test_ejecutar_desde_ventana(self) -> None:
		b = self.poblar()
		b.añadirElemento(0, ["fol", "Datos", self.dir])
		v = self.lanzador.VentanaLanzador()
		with mock.patch.object(sistema, "ejecutar") as ejecutar:
			v.ejecutar(0)
			ejecutar.assert_called_once()
			self.assertEqual(ejecutar.call_args[0][0], ["fol", "Datos", self.dir])
		self.assertFalse(estado.ventanaAbierta)

	def test_dialogos_de_acciones(self) -> None:
		import wx

		v = self.lanzador.VentanaLanzador()
		try:
			d = self.lanzador.DialogoAplicacion(v, ["Bloc"])
			self.assertFalse(d.validar())
			d.textoNombre.SetValue("Bloc")
			self.assertFalse(d.validar())
			d.textoDirectorio.SetValue(r"C:\Windows\notepad.exe")
			self.assertFalse(d.validar())
			self.assertEqual(self.avisos[-1], datos.MSG_DUPLICADO_ACCION)
			d.textoNombre.SetValue("Bloc de notas")
			self.assertFalse(d.textoParametro.IsEnabled())
			d.chkParametro.SetValue(True)
			d.onParametro(None)
			d.textoParametro.SetValue("leeme.txt")
			d.chkAdministrador.SetValue(True)
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, ["app", "Bloc de notas", r"C:\Windows\notepad.exe", True, "leeme.txt", True])
			d.Destroy()
			# Edición: el mismo nombre vale.
			d = self.lanzador.DialogoCMD(v, ["Dir"], ["cmd", "Dir", "dir", True, False])
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, ["cmd", "Dir", "dir", True, False])
			d.textoParametro.SetValue("")
			self.assertFalse(d.validar())
			d.Destroy()
			d = self.lanzador.DialogoCarpeta(v, [], ["fol", "X", r"C:\no\existe"])
			self.assertEqual(d.textoDirectorio.GetValue(), "")
			self.assertFalse(d.validar())
			d.Destroy()
			d = self.lanzador.DialogoAcceso(v, [])
			d.textoNombre.SetValue("Acceso")
			d.textoDirectorio.SetValue(r"C:\a.lnk")
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, ["adr", "Acceso", r"C:\a.lnk", False])
			d.Destroy()
			d = self.lanzador.DialogoInstalada(v, [], obtener=lambda: [("Calculadora", "Calc!App")])
			d.cargarLista([("Calculadora", "Calc!App")])
			self.assertFalse(d.validar())
			d.choiceApps.SetSelection(1)
			d.onChoiceApp(None)
			self.assertEqual(d.textoNombre.GetValue(), "Calculadora")
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, ["sap", "Calculadora", "Calc!App", False])
			d.Destroy()
			wx.Yield()
		finally:
			v.cerrar()

	def test_dialogos_comunes(self) -> None:
		b = self.poblar(datos.NOTAS)
		b.añadirElemento(0, ["txt", "Nota", "Texto"])
		b.añadirElemento(1, ["txt", "Nota", "Otro"])
		v = self.notas.VentanaNotas()
		try:
			d = self.comun.DialogoCategoria(v, b.nombresCategorias())
			d.texto.SetValue("Oficina")
			self.assertFalse(d.validar())
			d.texto.SetValue("Casa")
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, "Casa")
			d.Destroy()
			d = self.comun.DialogoMover(v, b, 0, 0, True)
			self.assertEqual(d.choice.GetStrings(), ["Oficina", "Juegos"])
			self.assertFalse(d.validar())
			self.assertTrue(d.textoNombre.IsEnabled())
			self.assertEqual(self.avisos[-1], datos.MSG_DUPLICADO_NOTA)
			d.textoNombre.SetValue("Nota movida")
			self.assertTrue(d.validar())
			d.Destroy()
			self.assertEqual(b.nombresElementos(1), ["Nota", "Nota movida"])
			self.assertEqual(b.elementos(0), [])
			d = self.notas.DialogoNota(v, ["Nota"])
			self.assertFalse(d.validar())
			self.assertEqual(self.avisos[-1], self.notas.MSG_NOMBRE_VACIO)
			d.textoNombre.SetValue("Nueva")
			self.assertFalse(d.validar())
			self.assertEqual(self.avisos[-1], self.notas.MSG_TEXTO_VACIO)
			d.textoNota.SetValue("contenido\nde varias líneas")
			self.assertTrue(d.validar())
			self.assertEqual(d.resultado, ["txt", "Nueva", "contenido\nde varias líneas"])
			d.Destroy()
			from tiresias.config import conf

			d = self.comun.DialogoOpciones(v)
			d.chkURL.SetValue(True)
			self.assertTrue(d.validar())
			self.assertTrue(conf["zUtilidades"]["urlCaptura"])
			conf["zUtilidades"]["urlCaptura"] = False
			d.Destroy()
			self.assertEqual([e[0] for e in v.entradasOpciones()], ["&Opciones", "&Volver a valores por defecto Notas rápidas"])
			self.assertEqual([e[0] for e in v.entradasElementos()], ["&Añadir Nota", "&Editar Nota", "&Borrar Nota", "&Mover Nota"])
		finally:
			v.cerrar()

	def test_teclas_de_notas(self) -> None:
		import wx

		b = self.poblar(datos.NOTAS)
		b.añadirElemento(0, ["txt", "Firma", "Saludos"])
		v = self.notas.VentanaNotas()
		with mock.patch.object(sistema, "mensaje") as decir, mock.patch.object(sistema, "copiarAlPortapapeles", return_value=True) as copiar:
			self.assertTrue(v.teclaElemento(wx.WXK_F1, 0))
			decir.assert_called_with("Saludos")
			self.assertTrue(v.teclaElemento(wx.WXK_F2, 0))
			copiar.assert_called_once_with("Saludos")
			decir.assert_called_with("Se ha copiado la nota Firma al portapapeles.")
		from tiresias import queue_handler

		with mock.patch.object(queue_handler, "queueFunction") as encolar:
			self.assertTrue(v.teclaElemento(wx.WXK_F3, 0))
			encolar.assert_called_once_with(sistema.pegarEnFoco, "Saludos", 400)
		self.assertFalse(estado.ventanaAbierta)

	def test_nota_rapida(self) -> None:
		b = self.poblar(datos.NOTAS)
		b.añadirElemento(1, ["txt", "Repetida", "x"])
		with mock.patch.object(sistema, "mensaje") as decir:
			estado.ventanaAbierta = True
			self.assertIsNone(self.notas.abrirNotaRapida("t", None, False))
			decir.assert_called_with(estado.MSG_INSTANCIA)
		estado.ventanaAbierta = False
		d = self.notas.DialogoNotaRapida("texto seleccionado", "Título", False)
		try:
			self.assertEqual(d.GetTitle(), "Agregar nota rápida del texto seleccionado")
			self.assertEqual(d.textoNombre.GetValue(), "Título")
			self.assertEqual(d.textoNota.GetValue(), "texto seleccionado")
			d.choice.SetSelection(1)
			d.textoNombre.SetValue("Repetida")
			d.onAceptar(None)
			self.assertEqual(self.avisos[-1], datos.MSG_DUPLICADO_NOTA)
			d.textoNombre.SetValue("Nueva")
			d.onAceptar(None)
		finally:
			d.cerrar()
		self.assertEqual(b.elementos(1)[-1], ["txt", "Nueva", "texto seleccionado"])
		self.assertFalse(estado.ventanaAbierta)

	def test_sin_categorias_para_nota_rapida(self) -> None:
		with mock.patch.object(sistema, "mensaje") as decir:
			self.assertIsNone(self.notas.abrirNotaRapida(None, None, True))
			self.assertIn("crear una nota rápida", decir.call_args[0][0])

	def test_menu_del_boton(self) -> None:
		import wx

		v = self.lanzador.VentanaLanzador()
		llamado = []
		menu = v._menu([("&Categorías", [("&Uno", lambda: llamado.append(1))]), ("&Salir", lambda: v.onSalir(None))])
		try:
			sub = menu.FindItemByPosition(0).GetSubMenu()
			item = sub.FindItemByPosition(0)
			sub.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, item.GetId()))
			salir = menu.FindItemByPosition(1)
			menu.ProcessEvent(wx.CommandEvent(wx.wxEVT_MENU, salir.GetId()))
			for _i in range(5):
				self.app.ProcessPendingEvents()
				wx.YieldIfNeeded()
		finally:
			menu.Destroy()
		self.assertEqual(llamado, [1])
		self.assertFalse(estado.ventanaAbierta)

	def test_panel_de_opciones(self) -> None:
		import wx

		frame = wx.Frame(None)
		try:
			cls = plugin._panelClass()
			panel = cls(frame)
			casillas = [c for c in panel.GetChildren() if isinstance(c, wx.CheckBox)]
			etiquetas = [c.GetLabel() for c in casillas]
			for _clave, texto in estado.ETIQUETAS:
				self.assertIn(texto, etiquetas)
		finally:
			frame.Destroy()

	def test_borrar_valores(self) -> None:
		self.poblar()
		v = self.lanzador.VentanaLanzador()
		with mock.patch.object(self.comun, "preguntar", return_value=True):
			v.borrarValores()
		self.assertEqual(datos.BaseDatos(datos.LANZADOR).nombresCategorias(), [])
		self.assertFalse(estado.ventanaAbierta)


class PruebasArchivos(unittest.TestCase):
	def test_manifiesto(self) -> None:
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "zUtilidades")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["url"], "https://github.com/hxebolax/zUtilidades-para-NVDA")
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))

	def test_documentacion(self) -> None:
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for texto in ("Lanzador de aplicaciones", "Notas rápidas", "menú virtual", "zut-zl", "Gestos de entrada", "GPL"):
			self.assertIn(texto, html)

	def test_solo_modulos_de_la_compilada(self) -> None:
		"""Los módulos estándar que se importan existen en la versión compilada."""
		import ast

		permitidos = {
			"__future__", "ctypes", "hashlib", "json", "os", "pickle", "secrets", "shutil", "subprocess",
			"tempfile", "threading", "time", "typing", "zipfile", "wx", "tiresias", "ast", "sys",
		}
		carpeta = os.path.join(ADDON, "globalPlugins", "zUtilidades")
		for fn in os.listdir(carpeta):
			if not fn.endswith(".py"):
				continue
			with open(os.path.join(carpeta, fn), encoding="utf-8") as f:
				arbol = ast.parse(f.read())
			for nodo in ast.walk(arbol):
				if isinstance(nodo, ast.Import):
					nombres = [a.name.split(".")[0] for a in nodo.names]
				elif isinstance(nodo, ast.ImportFrom) and nodo.level == 0:
					nombres = [nodo.module.split(".")[0]]
				else:
					continue
				for n in nombres:
					self.assertIn(n, permitidos, f"{fn} importa {n}")


if __name__ == "__main__":
	unittest.main()
