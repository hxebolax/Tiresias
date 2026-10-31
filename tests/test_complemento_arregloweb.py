"""Pruebas del complemento «Arreglo web» (complementos_tienda/arregloWeb).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_arregloweb -v``

El modo exploración se simula con los elementos UIA falsos de
``tests.test_browse`` (sin navegador).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "arregloWeb")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_arregloweb_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tests.test_browse import FakeEl, build, group, text  # noqa: E402
from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.browse import buffer as vbuf  # noqa: E402
from tiresias.browse import flexweb  # noqa: E402
from tiresias.browse.buffer import VirtualBuffer  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.objects.roles import Role, State  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import arregloWeb as aw  # noqa: E402
from arregloWeb import almacen, analisis, arreglos, options  # noqa: E402

sys.dont_write_bytecode = _oldBytecode

SITIO = "https://www.ejemplo.com/pagina.html"


# ====================================================================== ayudas
def link(name: str = "", children: list | None = None, url: str = "https://www.ejemplo.com/destino", **props) -> FakeEl:
	return FakeEl(uc.CT_HYPERLINK, name, children or [], P_VALUEVALUE=url, **props)


def image(name: str = "", **props) -> FakeEl:
	return FakeEl(uc.CT_IMAGE, name, [], **props)


def button(name: str = "", **props) -> FakeEl:
	return FakeEl(uc.CT_BUTTON, name, [], **props)


def edit(name: str = "", **props) -> FakeEl:
	return FakeEl(uc.CT_EDIT, name, [], P_ISKEYBOARDFOCUSABLE=True, **props)


def heading(t: str, level: int = 2) -> FakeEl:
	return FakeEl(uc.CT_TEXT, t, [text(t)], P_ARIAROLE="heading", P_ARIAPROPERTIES=f"level={level}")


def doc(*children) -> FakeEl:
	return FakeEl(uc.CT_DOCUMENT, "doc", list(children), P_VALUEVALUE=SITIO)


class FakeDoc:
	"""Documento del modo exploración mínimo para el complemento."""

	bufferKind = "tree"
	isReady = True
	rootObject = None

	def __init__(self, buf: VirtualBuffer, key: str = SITIO) -> None:
		self.buffer = buf
		self.key = key
		self.rebuilds = 0
		self.caret = 0
		self.moved: list[int] = []

	def _documentKey(self) -> str:
		return self.key

	def requestRebuild(self) -> None:
		self.rebuilds += 1

	def moveToOffsetFromGui(self, offset: int, activate: bool = False) -> None:
		self.moved.append(offset)


def buildWith(root: FakeEl, reglas: list[dict] | None = None, sitio: str = "www.ejemplo.com") -> VirtualBuffer:
	"""Construye el búfer aplicando ``reglas`` con el punto de extensión ``filter_node``."""
	rs = arreglos.ReglasSitio(sitio, reglas or [])

	def handler(value, buffer, controlType):
		return arreglos.aplicar(rs, value, controlType)

	vbuf.filter_node.register(handler)
	try:
		buf = VirtualBuffer(root)
		buf.documentKey = SITIO
		buf.build()
	finally:
		vbuf.filter_node.unregister(handler)
	return buf


def tipos(problemas: list) -> list[str]:
	return [p.tipo for p in problemas]


def porTipo(problemas: list, tipo: str) -> list:
	return [p for p in problemas if p.tipo == tipo]


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self._saved = dict(conf["browseMode"])
		conf["browseMode"]["useScreenLayout"] = False
		conf["browseMode"]["maxLineLength"] = 0
		conf["browseMode"]["reportUnlabeledGraphics"] = True
		self.tmp = tempfile.mkdtemp(prefix="tiresias_aw_")
		almacen._resetForTests(os.path.join(self.tmp, "sitios.json"))
		self._oldFlexFile = flexweb._file
		flexweb._file = lambda: os.path.join(self.tmp, "flexibleWeb.json")
		flexweb._resetForTests()

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["browseMode"][k] = v
		almacen._resetForTests(None)
		flexweb._file = self._oldFlexFile
		flexweb._resetForTests()
		shutil.rmtree(self.tmp, ignore_errors=True)


# ====================================================================== manifiesto y archivos
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "arregloWeb")
		self.assertEqual(m["name"], "Arreglo web: reparar páginas poco accesibles")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["author"], "Proyecto Tiresias")
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))
		self.assertIn("Tiresias+Mayúsculas+Alt+P", m["description"])
		self.assertTrue(m["changelog"].startswith("Primera versión"))

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "globalPlugins/arregloWeb/__init__.py", "globalPlugins/arregloWeb/analisis.py", "globalPlugins/arregloWeb/arreglos.py",
				"globalPlugins/arregloWeb/almacen.py", "globalPlugins/arregloWeb/options.py", "globalPlugins/arregloWeb/dialogo.py", "globalPlugins/arregloWeb/ia.py"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for t in ("Tiresias+Mayúsculas+Alt+P", "Tiresias+Mayúsculas+Alt+Q", "dos veces", "sin nombre", "texto alternativo", "sin etiqueta", "pulsable", "encabezado",
				"maquetación", "cookies", "web flexible", "IA", "Herramientas", "Aplicar al cargar", "Opciones", "DOM", "No se puede", "filter_node"):
			self.assertIn(t, html, t)

	def test_sin_modulos_ausentes_en_compilada(self):
		folder = os.path.join(ADDON, "globalPlugins", "arregloWeb")
		for fn in os.listdir(folder):
			if fn.endswith(".py"):
				with open(os.path.join(folder, fn), encoding="utf-8") as f:
					src = f.read()
				self.assertNotRegex(src, r"^\s*(import datetime|from datetime)", fn)
				self.assertNotIn("winsound", src, fn)


# ====================================================================== utilidades de texto
class TestUtilidades(unittest.TestCase):
	def test_tramo_url(self):
		self.assertEqual(analisis.tramoUrl("https://x.com/noticias/informe-anual-2026.pdf"), "informe anual 2026 (pdf)")
		self.assertEqual(analisis.tramoUrl("https://www.ejemplo.com/"), "ejemplo.com")
		self.assertEqual(analisis.tramoUrl("https://ejemplo.com/index.html"), "ejemplo.com")
		self.assertEqual(analisis.tramoUrl("https://e.com/articulo/12345"), "articulo")
		self.assertEqual(analisis.tramoUrl("https://e.com/p/mi-articulo-genial.html#seccion-dos"), "mi articulo genial")
		self.assertEqual(analisis.tramoUrl("mailto:info@x.com"), "correo a info@x.com")
		self.assertEqual(analisis.tramoUrl("javascript:void(0)"), "")
		self.assertEqual(analisis.tramoUrl(""), "")

	def test_nombres_inutiles(self):
		for t in ("clic aquí", "Leer más...", "https://x.com/a", "www.x.com", "Ver", "1", ">>", "»", "Más información"):
			self.assertTrue(analisis.esNombreInutil(t), t)
		for t in ("Informe anual", "Contacto", "", "Política de cookies"):
			self.assertFalse(analisis.esNombreInutil(t), t)

	def test_humanizar(self):
		self.assertEqual(analisis.humanizarIdentificador("btnBuscarAvanzada"), "Buscar Avanzada")
		self.assertEqual(analisis.humanizarIdentificador("icon-search"), "search")
		self.assertEqual(analisis.humanizarIdentificador("x1"), "")
		self.assertEqual(analisis.humanizarIdentificador(""), "")

	def test_huella_y_claves(self):
		n = vbuf.Node()
		n.automationId = "principal"
		self.assertEqual(arreglos.huella(n, uc.CT_GROUP), {"ct": uc.CT_GROUP, "id": "principal"})
		m = vbuf.Node()
		m.role = Role.LINK
		m.url = "https://x.com/a"
		m.name = "Ver"
		self.assertEqual(arreglos.huella(m, uc.CT_HYPERLINK), {"ct": uc.CT_HYPERLINK, "url": "https://x.com/a", "name": "Ver"})
		p = vbuf.Node()
		p.name = "Formulario"
		q = vbuf.Node()
		q.parent = p
		q.className = "campo"
		p.children = [vbuf.Node(), vbuf.Node()]
		self.assertEqual(arreglos.huella(q, uc.CT_EDIT), {"ct": uc.CT_EDIT, "cls": "campo", "p": "Formulario", "n": 2})
		r1 = {"tipo": "nombre", "huella": arreglos.huella(m, uc.CT_HYPERLINK), "nombre": "a"}
		r2 = {"tipo": "nombre", "huella": arreglos.huella(m, uc.CT_HYPERLINK), "nombre": "b"}
		self.assertEqual(arreglos.claveRegla(r1), arreglos.claveRegla(r2))
		self.assertNotEqual(arreglos.claveRegla(r1), arreglos.claveRegla({"tipo": "boton", "huella": r1["huella"]}))
		self.assertIn("«a»", arreglos.describirRegla(r1))
		self.assertIn("posición 3", arreglos.describirHuella(arreglos.huella(q, uc.CT_EDIT)))


# ====================================================================== detección
class TestDeteccion(Base):
	def test_enlace_sin_nombre_por_url_titulo_y_archivo(self):
		l1 = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		l2 = link("", [image("")], url="https://www.ejemplo.com/x", P_FULLDESCRIPTION="Ir a la portada")
		l3 = link("", [image("")], url="https://www.ejemplo.com/y")
		buf = build(doc(group(l1), group(l2), group(l3)))
		buf.byRid[l3.children[0].rid].aria["_src"] = "foto de la playa"
		problemas = analisis.analizar(buf)
		sin = porTipo(problemas, "enlaceSinNombre")
		self.assertEqual(len(sin), 3)
		self.assertEqual(sin[0].regla["nombre"], "informe anual (pdf)")
		self.assertIn("dirección", sin[0].arreglo)
		self.assertEqual(sin[1].regla["nombre"], "Ir a la portada")
		self.assertIn("title", sin[1].arreglo)
		self.assertEqual(sin[2].regla["nombre"], "foto de la playa")
		self.assertIn("archivo", sin[2].arreglo)
		self.assertEqual(sin[0].regla["tipo"], "nombre")
		self.assertEqual(sin[0].regla["huella"]["ct"], uc.CT_HYPERLINK)

	def test_nombre_inutil_con_contexto(self):
		l1 = link("clic aquí", [text("clic aquí")], url="https://www.ejemplo.com/matricula")
		l2 = link("https://www.ejemplo.com/becas-2026", [text("https://www.ejemplo.com/becas-2026")], url="https://www.ejemplo.com/becas-2026")
		buf = build(doc(heading("Matrícula del curso"), group(text("Plazo abierto hasta el 30 de junio.")), group(l1), group(l2)))
		problemas = analisis.analizar(buf)
		inutiles = porTipo(problemas, "nombreInutil")
		self.assertEqual(len(inutiles), 2)
		self.assertEqual(inutiles[0].regla["nombre"], "clic aquí: Matrícula del curso")
		self.assertEqual(inutiles[1].regla["nombre"], "becas 2026")

	def test_enlaces_repetidos_con_distinto_destino(self):
		ls = [link("Ver", [text("Ver")], url=f"https://www.ejemplo.com/noticia/{i}") for i in range(3)]
		buf = build(doc(heading("Noticias"), group(text("Primera noticia del día, con detalle.")), group(ls[0]), group(text("Segunda noticia, más larga todavía.")), group(ls[1]), group(ls[2])))
		problemas = analisis.analizar(buf)
		# «Ver» es también un nombre inútil: no se cuenta dos veces.
		self.assertEqual(len(porTipo(problemas, "nombreRepetido")), 0)
		self.assertEqual(len(porTipo(problemas, "nombreInutil")), 3)
		ls = [link("Detalle del producto", [text("Detalle del producto")], url=f"https://www.ejemplo.com/p/{i}") for i in range(2)]
		buf = build(doc(heading("Silla"), group(ls[0]), heading("Mesa"), group(ls[1])))
		rep = porTipo(analisis.analizar(buf), "nombreRepetido")
		self.assertEqual(len(rep), 2)
		self.assertEqual(rep[0].regla["nombre"], "Detalle del producto: Silla")
		self.assertEqual(rep[1].regla["nombre"], "Detalle del producto: Mesa")

	def test_boton_sin_nombre(self):
		b1 = button("", P_AUTOMATIONID="btnBuscarAvanzada")
		b2 = button("", P_CLASSNAME="icon-search")
		b3 = button("")
		b4 = button("clic aquí", P_FULLDESCRIPTION="Enviar el formulario")
		buf = build(doc(group(b1), group(b2), group(text("Enviar"), b3), group(b4)))
		problemas = analisis.analizar(buf)
		sin = porTipo(problemas, "botonSinNombre")
		self.assertEqual([p.regla["nombre"] for p in sin], ["Buscar Avanzada", "search", "Enviar"])
		self.assertIn("identificador", sin[0].arreglo)
		self.assertIn("cercano", sin[2].arreglo)
		inutil = porTipo(problemas, "nombreInutil")
		self.assertEqual(inutil[0].regla["nombre"], "Enviar el formulario")

	def test_imagenes_sin_alternativo(self):
		i1 = image("")
		i2 = image("", P_BOUNDINGRECT=(0, 0, 1, 1))
		i3 = image("")
		i4 = image("Logotipo")
		buf = build(doc(group(i1), group(i2), group(i3), group(i4), group(link("", [image("")]))))
		buf.byRid[i3.rid].aria["_src"] = "grafico de ventas"
		problemas = analisis.analizar(buf)
		imgs = porTipo(problemas, "imagenSinAlt")
		# La de 1×1 es decorativa; la del enlace la cubre el enlace.
		self.assertEqual(len(imgs), 2)
		self.assertIsNone(imgs[0].regla)
		self.assertIn("IA", imgs[0].texto())
		self.assertEqual(imgs[1].regla["nombre"], "grafico de ventas")

	def test_campos_sin_etiqueta(self):
		e1 = edit("")
		cb = FakeEl(uc.CT_CHECKBOX, "", [], P_ISKEYBOARDFOCUSABLE=True)
		e2 = edit("", P_AUTOMATIONID="codigoPostal")
		e3 = edit("", P_FULLDESCRIPTION="Buscar en el sitio")

		def cell(t, r, c, ct=uc.CT_DATAITEM, aria="cell", kids=None):
			return FakeEl(ct, t, kids if kids is not None else [text(t)], P_ARIAROLE=aria, P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c)

		e4 = edit("")
		row1 = FakeEl(uc.CT_DATAITEM, "", [cell("Nombre", 0, 0, ct=uc.CT_HEADERITEM, aria="columnheader"), cell("Correo", 0, 1, ct=uc.CT_HEADERITEM, aria="columnheader")], P_ARIAROLE="row")
		row2 = FakeEl(uc.CT_DATAITEM, "", [cell("Ana", 1, 0), cell("", 1, 1, kids=[e4])], P_ARIAROLE="row")
		table = FakeEl(uc.CT_TABLE, "t", [row1, row2], P_GRIDROWCOUNT=2, P_GRIDCOLUMNCOUNT=2)
		buf = build(doc(group(text("Nombre y apellidos:")), group(e1), group(cb, text("Acepto las condiciones")), group(e2), group(e3), table))
		problemas = analisis.analizar(buf)
		campos = porTipo(problemas, "campoSinEtiqueta")
		self.assertEqual([p.regla["nombre"] for p in campos], ["Nombre y apellidos", "Acepto las condiciones", "codigo Postal", "Buscar en el sitio", "Correo"])
		self.assertIn("anterior", campos[0].arreglo)
		self.assertIn("siguiente", campos[1].arreglo)
		self.assertIn("cabecera", campos[4].arreglo)
		self.assertTrue(all(p.regla["tipo"] == "etiqueta" for p in campos))

	def test_pulsable_que_no_es_boton(self):
		g = group(text("Abrir menú"), P_ISINVOKEPATTERNAVAILABLE=True, P_AUTOMATIONID="menuToggle")
		grande = group(text("x" * 200), P_ISINVOKEPATTERNAVAILABLE=True)
		buf = build(doc(g, grande))
		problemas = analisis.analizar(buf)
		puls = porTipo(problemas, "pulsable")
		self.assertEqual(len(puls), 1)
		self.assertEqual(puls[0].regla, {"tipo": "boton", "huella": {"ct": uc.CT_GROUP, "id": "menuToggle"}, "nombre": "Abrir menú"})
		self.assertEqual(porTipo(analisis.analizar(buf, opciones={"pulsablesComoBotones": False}), "pulsable"), [])

	def test_tabla_de_maquetacion(self):
		def cell(t, r, c):
			return FakeEl(uc.CT_DATAITEM, t, [text(t)], P_ARIAROLE="cell", P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c)

		row1 = FakeEl(uc.CT_DATAITEM, "", [cell("Menú lateral", 0, 0), cell("Contenido " * 30, 0, 1)], P_ARIAROLE="row")
		row2 = FakeEl(uc.CT_DATAITEM, "", [cell("Más menú", 1, 0), cell("Más contenido " * 30, 1, 1)], P_ARIAROLE="row")
		table = FakeEl(uc.CT_TABLE, "t", [row1, row2], P_GRIDROWCOUNT=2, P_GRIDCOLUMNCOUNT=2, P_AUTOMATIONID="layout")
		conf["browseMode"]["includeLayoutTables"] = True
		buf = build(doc(table))
		# Tiresias no la considera de maquetación (2×2), pero sus celdas son párrafos.
		self.assertFalse(buf.byRid[table.rid].layoutTable)
		problemas = analisis.analizar(buf)
		tablas = porTipo(problemas, "tablaMaquetacion")
		self.assertEqual(len(tablas), 1)
		self.assertIn("párrafos largos", tablas[0].descripcion)
		self.assertEqual(tablas[0].regla, {"tipo": "maquetacion", "huella": {"ct": uc.CT_TABLE, "id": "layout"}})
		# Una tabla con encabezados no se toca.
		h = FakeEl(uc.CT_HEADERITEM, "Col", [text("Col")], P_ARIAROLE="columnheader", P_GRIDITEMROW=0, P_GRIDITEMCOLUMN=0)
		rowh = FakeEl(uc.CT_DATAITEM, "", [h], P_ARIAROLE="row")
		row2 = FakeEl(uc.CT_DATAITEM, "", [cell("dato", 1, 0)], P_ARIAROLE="row")
		buf = build(doc(FakeEl(uc.CT_TABLE, "t", [rowh, row2], P_GRIDROWCOUNT=2, P_GRIDCOLUMNCOUNT=1)))
		self.assertEqual(porTipo(analisis.analizar(buf), "tablaMaquetacion"), [])

	def test_nombres_de_archivo_sin_palabras(self):
		for nombre in ("AA13Q6AL", "BBX9W3D", "8f3a2c", "IMG 2041", ""):
			self.assertTrue(analisis.pareceIdentificador(nombre), nombre)
		for nombre in ("carrito compra", "zapatillas rojas", "logo", "Logo2026"):
			self.assertFalse(analisis.pareceIdentificador(nombre), nombre)

	def test_aviso_de_cookies_sin_contenedor(self):
		# Chromium no publica el <div>: solo quedan el texto y el botón.
		raiz = doc(text("Artículo largo sobre recetas de cocina. " * 20), text("Usamos cookies en este sitio."), button("Aceptar todas las cookies"))
		probs = porTipo(analisis.analizar(build(raiz)), "superposicion")
		self.assertEqual(len(probs), 2)
		self.assertTrue(all(p.regla and p.regla["tipo"] == "ocultar" for p in probs))

	def test_articulo_sobre_cookies_no_es_un_aviso(self):
		raiz = doc(text("Las cookies de avena son muy fáciles de hacer. " * 10), button("Ver receta"))
		self.assertEqual(porTipo(analisis.analizar(build(raiz)), "superposicion"), [])

	def test_superposicion_de_cookies(self):
		banner = group(text("Usamos cookies propias y de terceros."), button("Aceptar todas"), button("Rechazar todas"), P_AUTOMATIONID="cookie-banner")
		contenido = group(text("Texto del artículo. " * 20))
		buf = build(doc(banner, contenido))
		problemas = analisis.analizar(buf)
		sup = porTipo(problemas, "superposicion")
		self.assertEqual(len(sup), 1)
		self.assertEqual(sup[0].regla["tipo"], "ocultar")
		self.assertEqual(sup[0].regla["flex"]["id"], "cookie-banner")
		self.assertIn("web flexible", sup[0].arreglo)
		# Un diálogo normal (inicio de sesión) no es una superposición de cookies.
		dlg = group(text("Usuario"), edit("usuario"), P_ISDIALOG=True)
		self.assertEqual(porTipo(analisis.analizar(build(doc(dlg, contenido))), "superposicion"), [])

	def test_sin_encabezados_ni_regiones_y_region_principal(self):
		nav = group(*[link(f"Sección {i}", [text(f"Sección {i}")], url=f"https://www.ejemplo.com/s{i}") for i in range(10)], P_AUTOMATIONID="menu")
		main = group(*[group(text("Párrafo de contenido con bastante texto para que cuente. " * 3)) for _ in range(8)], P_AUTOMATIONID="contenido")
		buf = build(doc(nav, main))
		self.assertGreater(len(buf.text), analisis.TEXTO_MINIMO_ESTRUCTURA)
		problemas = analisis.analizar(buf)
		self.assertEqual(len(porTipo(problemas, "sinEncabezados")), 1)
		self.assertIsNone(porTipo(problemas, "sinEncabezados")[0].regla)
		reg = porTipo(problemas, "sinRegiones")
		self.assertEqual(len(reg), 1)
		self.assertEqual(reg[0].regla, {"tipo": "region", "huella": {"ct": uc.CT_GROUP, "id": "contenido"}, "landmark": "principal"})
		# Con una región y un encabezado no hay problema de estructura.
		buf = build(doc(heading("Título"), group(nav, main, P_ARIAROLE="main", P_LANDMARKTYPE=uc.LANDMARK_MAIN)))
		problemas = analisis.analizar(buf)
		self.assertEqual(porTipo(problemas, "sinEncabezados") + porTipo(problemas, "sinRegiones"), [])
		# Páginas cortas: no se echa nada en falta.
		self.assertEqual(tipos(analisis.analizar(build(doc(group(text("Hola")))))), [])

	def test_texto_que_parece_encabezado(self):
		titulo = group(text("Novedades de octubre"))
		sub = group(text("Lo más leído"))
		parrafo = group(text("Un párrafo normal con su texto de siempre."))
		buf = build(doc(heading("Portada", 1), titulo, parrafo, sub))
		nodos = {buf.byRid[titulo.rid], buf.byRid[sub.rid]}
		tam = {id(buf.byRid[titulo.rid]): 24.0, id(buf.byRid[sub.rid]): 18.0}
		problemas = analisis.analizar(buf, estiloBloque=lambda b: b in nodos, nivelBloque=lambda b: tam.get(id(b), 0.0))
		enc = porTipo(problemas, "pareceEncabezado")
		self.assertEqual([(p.regla["nivel"], p.regla["huella"]["name"]) for p in enc], [(2, "Novedades de octubre"), (3, "Lo más leído")])
		# Sin h1 en la página, el mayor pasa a ser nivel 1.
		buf = build(doc(titulo, parrafo, sub))
		nodos = {buf.byRid[titulo.rid], buf.byRid[sub.rid]}
		tam = {id(buf.byRid[titulo.rid]): 24.0, id(buf.byRid[sub.rid]): 18.0}
		enc = porTipo(analisis.analizar(buf, estiloBloque=lambda b: b in nodos, nivelBloque=lambda b: tam.get(id(b), 0.0)), "pareceEncabezado")
		self.assertEqual([p.regla["nivel"] for p in enc], [1, 2])
		# Con la opción desactivada no se buscan.
		self.assertEqual(porTipo(analisis.analizar(buf, opciones={"encabezadosDeducidos": False}, estiloBloque=lambda b: True, nivelBloque=lambda b: 1), "pareceEncabezado"), [])

	def test_resumen_e_informe(self):
		self.assertEqual(analisis.resumen([], "x.com"), "Arreglo web: no se han encontrado problemas en x.com.")
		ps = [analisis.Problema("enlaceSinNombre", "", None, 0, {"tipo": "nombre"}, "nombre «a»"), analisis.Problema("enlaceSinNombre", "", None, 1, None, ""), analisis.Problema("imagenSinAlt", "", None, 2, None, "")]
		self.assertEqual(analisis.resumen(ps, "x.com"), "Arreglo web: 3 problemas en x.com: 2 enlaces sin nombre, 1 imagen sin texto alternativo. 1 con arreglo.")
		self.assertEqual(analisis.resumen(ps[:1]), "Arreglo web: 1 problema: 1 enlace sin nombre. Tiene arreglo.")
		informe = analisis.informeTexto(ps, "x.com")
		self.assertIn("1. Enlace sin nombre → nombre «a»", informe)
		self.assertIn("3. Imagen sin texto alternativo (sin arreglo automático: se puede describir con IA)", informe)


# ====================================================================== arreglos aplicados por el filtro
class TestArreglos(Base):
	def test_punto_de_extension_existe_y_se_llama(self):
		self.assertIsInstance(vbuf.filter_node, vbuf.extension_points.Filter)
		llamadas = []

		def h(value, buffer, controlType):
			llamadas.append((value.role, controlType, buffer.documentKey))
			return value

		vbuf.filter_node.register(h)
		try:
			buf = VirtualBuffer(doc(group(text("hola"))))
			buf.documentKey = SITIO
			buf.build()
		finally:
			vbuf.filter_node.unregister(h)
		self.assertIn((Role.STATICTEXT, uc.CT_TEXT, SITIO), llamadas)
		self.assertEqual(len(llamadas), 3)
		# Devolver None quita el nodo con sus descendientes.
		vbuf.filter_node.register(lambda value, buffer, controlType: None if value.name == "fuera" else value)
		try:
			buf = build(doc(group(text("dentro")), group(text("x"), name="fuera")))
		finally:
			vbuf.filter_node._handlers.clear()
		self.assertIn("dentro", buf.text)
		self.assertNotIn("x", buf.text)

	def test_nombre_de_enlace_sustituye_el_grafico(self):
		l = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		buf = build(doc(group(l)))
		self.assertIn("gráfico", buf.text)
		regla = porTipo(analisis.analizar(buf), "enlaceSinNombre")[0].regla
		buf2 = buildWith(doc(group(l)), [regla])
		n = buf2.byRid[l.rid]
		self.assertEqual(n.name, "informe anual (pdf)")
		self.assertEqual(buf2.text.strip(), "informe anual (pdf)")
		self.assertEqual(n.role, Role.LINK)
		self.assertNotIn(l.children[0].rid, buf2.byRid)
		# Ya no es un problema.
		self.assertEqual(porTipo(analisis.analizar(buf2), "enlaceSinNombre"), [])

	def test_boton_desde_pulsable(self):
		g = group(text("Abrir menú"), P_ISINVOKEPATTERNAVAILABLE=True, P_AUTOMATIONID="menuToggle")
		regla = porTipo(analisis.analizar(build(doc(g))), "pulsable")[0].regla
		buf = buildWith(doc(g), [regla])
		n = buf.byRid[g.rid]
		self.assertEqual(n.role, Role.BUTTON)
		self.assertEqual(n.name, "Abrir menú")
		self.assertFalse(n.clickable)
		self.assertNotIn(State.CLICKABLE, n.states)
		self.assertEqual(buf.text.strip(), "Abrir menú")
		self.assertEqual(porTipo(analisis.analizar(buf), "pulsable"), [])

	def test_encabezado_region_maquetacion_y_etiqueta(self):
		titulo = group(text("Novedades"), P_AUTOMATIONID="titulo")
		main = group(text("Contenido " * 50), P_AUTOMATIONID="contenido")

		def cell(t, r, c):
			return FakeEl(uc.CT_DATAITEM, t, [text(t)], P_ARIAROLE="cell", P_GRIDITEMROW=r, P_GRIDITEMCOLUMN=c)

		table = FakeEl(uc.CT_TABLE, "t", [FakeEl(uc.CT_DATAITEM, "", [cell("a", 0, 0), cell("b", 0, 1)], P_ARIAROLE="row")], P_GRIDROWCOUNT=1, P_GRIDCOLUMNCOUNT=2, P_AUTOMATIONID="layout")
		campo = edit("", P_AUTOMATIONID="nombre")
		reglas = [
			{"tipo": "encabezado", "huella": {"ct": uc.CT_GROUP, "id": "titulo"}, "nivel": 2},
			{"tipo": "region", "huella": {"ct": uc.CT_GROUP, "id": "contenido"}, "landmark": "principal"},
			{"tipo": "maquetacion", "huella": {"ct": uc.CT_TABLE, "id": "layout"}},
			{"tipo": "etiqueta", "huella": {"ct": uc.CT_EDIT, "id": "nombre"}, "nombre": "Nombre"},
		]
		conf["browseMode"]["includeLayoutTables"] = False
		buf = buildWith(doc(titulo, main, table, group(text("Nombre:"), campo)), reglas)
		t = buf.byRid[titulo.rid]
		self.assertEqual(t.role, Role.HEADING2)
		self.assertEqual(t.headingLevel(), 2)
		self.assertIn("Novedades", buf.text)
		m = buf.byRid[main.rid]
		self.assertEqual((m.role, m.landmark), (Role.LANDMARK, "principal"))
		tb = buf.byRid[table.rid]
		self.assertTrue(tb.layoutTable)
		self.assertTrue(vbuf.isLayoutTable(tb))
		c = buf.byRid[campo.rid]
		self.assertEqual(c.name, "Nombre")
		self.assertIn("Nombre:\nNombre", buf.text)
		# El análisis ya no encuentra esos problemas.
		p = analisis.analizar(buf)
		self.assertEqual(porTipo(p, "campoSinEtiqueta") + porTipo(p, "tablaMaquetacion") + porTipo(p, "sinRegiones"), [])

	def test_ocultar_superposicion_con_web_flexible(self):
		banner = group(text("Usamos cookies."), button("Aceptar todas"), P_AUTOMATIONID="cookie-banner")
		contenido = group(text("Texto del artículo. " * 20))
		buf = build(doc(banner, contenido))
		regla = porTipo(analisis.analizar(buf), "superposicion")[0].regla
		plugin = aw.GlobalPlugin()
		try:
			d = FakeDoc(buf)
			with mock.patch("tiresias.speech.api.speakMessage"):
				plugin.aplicarArreglos(d, [analisis.Problema("superposicion", "", None, 0, regla)], True)
			self.assertEqual(flexweb.rulesFor(SITIO).hidden, [{"ct": uc.CT_GROUP, "id": "cookie-banner", "name": "", "cls": ""}])
			self.assertEqual(d.rebuilds, 1)
			buf2 = VirtualBuffer(doc(banner, contenido))
			buf2.hiddenRules = flexweb.rulesFor(SITIO)
			buf2.build()
			self.assertNotIn("cookies", buf2.text)
			self.assertIn("artículo", buf2.text)
			# Quitar los arreglos del sitio quita también la ocultación.
			with mock.patch.object(aw, "currentDocument", return_value=d), mock.patch("tiresias.speech.api.speakMessage") as speak:
				plugin.script_quitarArreglos(None)
			self.assertEqual(flexweb.rulesFor(SITIO).hidden, [])
			self.assertEqual(almacen.sitios(), {})
			self.assertIn("1 arreglo quitado", speak.call_args[0][0])
		finally:
			plugin.terminate()

	def test_ciclo_completo_con_plugin_y_almacen(self):
		l = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		g = group(text("Abrir menú"), P_ISINVOKEPATTERNAVAILABLE=True, P_AUTOMATIONID="menuToggle")
		campo = edit("")
		raiz = doc(group(l), g, group(text("Correo:"), campo))
		plugin = aw.GlobalPlugin()
		try:
			self.assertIn(plugin.filtrarNodo, vbuf.filter_node.handlers())
			buf = VirtualBuffer(raiz)
			buf.documentKey = SITIO
			buf.build()
			d = FakeDoc(buf)
			problemas = plugin.analizarDocumento(d)
			self.assertEqual(tipos(problemas), ["enlaceSinNombre", "campoSinEtiqueta", "pulsable"])
			with mock.patch("tiresias.speech.api.speakMessage") as speak:
				n = plugin.aplicarArreglos(d, problemas, True)
			self.assertEqual(n, 3)
			self.assertIn("3 arreglos aplicados y guardados", speak.call_args[0][0])
			self.assertEqual(almacen.sitios(), {"www.ejemplo.com": 3})
			# La siguiente construcción (misma página) ya sale arreglada por el filtro del complemento.
			buf2 = VirtualBuffer(raiz)
			buf2.documentKey = SITIO
			buf2.build()
			self.assertEqual(buf2.byRid[l.rid].name, "informe anual (pdf)")
			self.assertEqual(buf2.byRid[g.rid].role, Role.BUTTON)
			self.assertEqual(buf2.byRid[campo.rid].name, "Correo")
			self.assertEqual(tipos(analisis.analizar(buf2)), [])
			# Otro sitio no se toca.
			buf3 = VirtualBuffer(raiz)
			buf3.documentKey = "https://otro.org/"
			buf3.build()
			self.assertEqual(buf3.byRid[l.rid].name, "")
			# Con la opción desactivada solo se aplican en los sitios pedidos en la sesión.
			options.set("aplicarGuardados", False)
			try:
				plugin._sitiosSesion.clear()
				buf4 = VirtualBuffer(raiz)
				buf4.documentKey = SITIO
				buf4.build()
				self.assertEqual(buf4.byRid[l.rid].name, "")
				plugin._sitiosSesion.add("www.ejemplo.com")
				buf5 = VirtualBuffer(raiz)
				buf5.documentKey = SITIO
				buf5.build()
				self.assertEqual(buf5.byRid[l.rid].name, "informe anual (pdf)")
			finally:
				options.set("aplicarGuardados", True)
			# Las reglas sobreviven a una recarga del almacén (archivo JSON).
			almacen._resetForTests(os.path.join(self.tmp, "sitios.json"))
			self.assertEqual(len(almacen.listaDe("www.ejemplo.com")), 3)
			with open(os.path.join(self.tmp, "sitios.json"), encoding="utf-8") as f:
				self.assertIn("informe anual (pdf)", f.read())
		finally:
			plugin.terminate()
		self.assertNotIn(plugin.filtrarNodo, vbuf.filter_node.handlers())

	def test_arreglos_solo_de_sesion(self):
		l = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		raiz = doc(group(l))
		plugin = aw.GlobalPlugin()
		try:
			buf = VirtualBuffer(raiz)
			buf.documentKey = SITIO
			buf.build()
			d = FakeDoc(buf)
			with mock.patch("tiresias.speech.api.speakMessage"):
				plugin.aplicarArreglos(d, plugin.analizarDocumento(d), False)
			self.assertEqual(almacen.sitios(), {})
			self.assertFalse(os.path.exists(os.path.join(self.tmp, "sitios.json")))
			buf2 = VirtualBuffer(raiz)
			buf2.documentKey = SITIO
			buf2.build()
			self.assertEqual(buf2.byRid[l.rid].name, "informe anual (pdf)")
		finally:
			plugin.terminate()


# ====================================================================== almacén
class TestAlmacen(Base):
	def test_guardado_por_sitio(self):
		r1 = {"tipo": "nombre", "huella": {"ct": 1, "id": "a"}, "nombre": "A"}
		r2 = {"tipo": "nombre", "huella": {"ct": 1, "id": "b"}, "nombre": "B"}
		self.assertEqual(almacen.anadir("www.ejemplo.com", [r1, r2]), 2)
		self.assertEqual(almacen.anadir("www.ejemplo.com", [r1]), 0)
		# La misma huella con otro nombre sustituye a la anterior.
		self.assertEqual(almacen.anadir("www.ejemplo.com", [dict(r1, nombre="A2")]), 0)
		self.assertEqual([r["nombre"] for r in almacen.listaDe("www.ejemplo.com")], ["A2", "B"])
		self.assertEqual(almacen.anadir("otro.org", [r1]), 1)
		self.assertEqual(almacen.sitios(), {"www.ejemplo.com": 2, "otro.org": 1})
		self.assertEqual(almacen.sitioDe(SITIO), "www.ejemplo.com")
		self.assertEqual(almacen.sitioDe(""), "")
		self.assertIsNone(almacen.reglasDe(""))
		self.assertIsNone(almacen.reglasDe("nadie.com"))
		rs = almacen.reglasDe("www.ejemplo.com")
		self.assertEqual(len(rs), 2)
		n = vbuf.Node()
		n.automationId = "b"
		self.assertEqual(rs.reglaPara(n, 1)["nombre"], "B")
		self.assertIsNone(rs.reglaPara(n, 2))
		self.assertEqual(almacen.quitarRegla("www.ejemplo.com", 0)["nombre"], "A2")
		self.assertIsNone(almacen.quitarRegla("www.ejemplo.com", 5))
		self.assertEqual(almacen.quitarSitio("www.ejemplo.com"), [r2])
		self.assertEqual(almacen.quitarSitio("www.ejemplo.com"), [])
		almacen._resetForTests(os.path.join(self.tmp, "sitios.json"))
		self.assertEqual(almacen.sitios(), {"otro.org": 1})

	def test_archivo_roto_no_rompe(self):
		with open(os.path.join(self.tmp, "sitios.json"), "w", encoding="utf-8") as f:
			f.write("{basura")
		self.assertEqual(almacen.sitios(), {})
		self.assertEqual(almacen.anadir("x.com", [{"tipo": "maquetacion", "huella": {"ct": 1, "id": "t"}}]), 1)

	def test_sesion(self):
		r = {"tipo": "nombre", "huella": {"ct": 1, "id": "a"}, "nombre": "A"}
		almacen.anadirSesion("x.com", [r])
		almacen.anadirSesion("x.com", [r])
		self.assertEqual(len(almacen.reglasDe("x.com")), 1)
		self.assertEqual(almacen.sitios(), {})
		self.assertEqual(almacen.quitarSitio("x.com"), [r])
		self.assertIsNone(almacen.reglasDe("x.com"))


# ====================================================================== complemento global
class TestComplemento(Base):
	def setUp(self):
		super().setUp()
		self.plugin = aw.GlobalPlugin()

	def tearDown(self):
		self.plugin.terminate()
		super().tearDown()

	def test_opciones_por_defecto(self):
		for k, v in options.DEFAULTS.items():
			self.assertEqual(conf["arregloWeb"][k], v, k)
		conf["arregloWeb"]["maxImagenesIA"] = 999
		try:
			self.assertEqual(options.get("maxImagenesIA"), 50)
		finally:
			conf["arregloWeb"]["maxImagenesIA"] = 8

	def test_panel_registrado(self):
		from tiresias.gui import settings as S

		self.assertIn(options.PANEL_ID, S._panels)
		title, cls = S._panels[options.PANEL_ID]
		self.assertEqual(title, "Arreglo web")
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		self.assertEqual([f.key for f in cls.fields], list(options.DEFAULTS))
		self.plugin.terminate()
		self.assertNotIn(options.PANEL_ID, S._panels)

	def test_panel_real_guarda(self):
		import wx

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		try:
			panel = options.panelClass()(frame)
			auto = panel.getControl("aplicarGuardados")
			self.assertIsInstance(auto, wx.CheckBox)
			self.assertTrue(auto.GetValue())
			self.assertIn("Aplicar al cargar cada página los arreglos guardados de su sitio", auto.GetLabel().replace("&", ""))
			auto.SetValue(False)
			panel.onSave()
			self.assertFalse(conf["arregloWeb"]["aplicarGuardados"])
			panel.resetToFactory()
			panel.onSave()
			self.assertTrue(conf["arregloWeb"]["aplicarGuardados"])
		finally:
			conf["arregloWeb"]["aplicarGuardados"] = True
			frame.Destroy()

	def test_registros(self):
		from tiresias import gui

		self.assertIn(self.plugin.filtrarNodo, vbuf.filter_node.handlers())
		self.assertIn(aw.MENU_ID, gui._addonToolsEntries)
		self.plugin.terminate()
		self.assertNotIn(self.plugin.filtrarNodo, vbuf.filter_node.handlers())
		self.assertNotIn(aw.MENU_ID, gui._addonToolsEntries)

	def test_gestos(self):
		self.assertEqual(dict(aw.GlobalPlugin._classGestures), {"kb:tiresias+shift+alt+p": "analizar", "kb:tiresias+shift+alt+q": "quitarArreglos"})
		names = sorted(n for n in dir(aw.GlobalPlugin) if n.startswith("script_"))
		self.assertEqual(names, ["script_alternarAutomatico", "script_analizar", "script_informe", "script_quitarArreglos", "script_sitios"])
		for n in names:
			func = getattr(aw.GlobalPlugin, n)
			self.assertTrue(func.__doc__.startswith("Arreglo web:"), n)
			self.assertEqual(func.category, "Arreglo web", n)
		self.assertTrue(aw.GlobalPlugin.script_informe.speakOnDemand)

	def test_gestos_sin_conflictos(self):
		# Ningún gesto del complemento está ya en el núcleo ni en otros complementos.
		mine = [normalizeGestureId(g) for g in aw.GlobalPlugin._classGestures]
		pattern = re.compile(r"kb(?:\([a-z]+\))?:[A-Za-z0-9+]+")
		used = set()
		for base in (os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons"), os.path.join(ROOT, "complementos_tienda")):
			for dirpath, _dirs, files in os.walk(base):
				if os.path.basename(dirpath) == "arregloWeb":
					continue
				for fn in files:
					if fn.endswith(".py"):
						with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
							for m in pattern.findall(f.read()):
								used.add(normalizeGestureId(m.split(":", 1)[0].split("(")[0] + ":" + m.split(":", 1)[1]))
		for g in mine:
			self.assertNotIn(g, used, g)

	def _doc(self) -> FakeDoc:
		l = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		buf = VirtualBuffer(doc(group(l), group(image(""))))
		buf.documentKey = SITIO
		buf.build()
		return FakeDoc(buf)

	def test_analizar_sin_documento(self):
		with mock.patch.object(aw, "currentDocument", return_value=None), mock.patch("tiresias.speech.api.speakMessage") as speak:
			self.plugin.script_analizar(None)
			self.plugin.script_informe(None)
			self.plugin.script_quitarArreglos(None)
		self.assertEqual(speak.call_count, 3)
		self.assertIn("no hay ningún documento", speak.call_args[0][0])

	def test_analizar_anuncia_y_abre_la_lista(self):
		d = self._doc()
		mostrado = {}

		def mostrar(doc_, sitio, problemas, aplicar, describir, guardar):
			mostrado.update(sitio=sitio, problemas=problemas, aplicar=aplicar, describir=describir, guardar=guardar)

		with mock.patch.object(aw, "currentDocument", return_value=d), mock.patch("tiresias.speech.api.speakMessage") as speak, \
				mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=0), mock.patch("arregloWeb.dialogo.mostrarInforme", mostrar):
			self.plugin.script_analizar(None)
		self.assertEqual(speak.call_args[0][0], "Arreglo web: 2 problemas en www.ejemplo.com: 1 enlace sin nombre, 1 imagen sin texto alternativo. 1 con arreglo.")
		self.assertEqual(mostrado["sitio"], "www.ejemplo.com")
		self.assertEqual(tipos(mostrado["problemas"]), ["enlaceSinNombre", "imagenSinAlt"])
		self.assertIsNotNone(mostrado["describir"])
		self.assertTrue(mostrado["guardar"])
		# Lo que hace el diálogo al aplicar pasa por el núcleo y guarda.
		with mock.patch("tiresias.queue_handler.queueFunction", side_effect=lambda f, *a, **k: f(*a, **k)), mock.patch("tiresias.speech.api.speakMessage"):
			mostrado["aplicar"](mostrado["problemas"], True)
		self.assertEqual(almacen.sitios(), {"www.ejemplo.com": 1})
		self.assertEqual(d.rebuilds, 1)
		# Sin la opción de voz no se anuncia el resumen.
		options.set("informeVoz", False)
		try:
			with mock.patch.object(aw, "currentDocument", return_value=d), mock.patch("tiresias.speech.api.speakMessage") as speak, \
					mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=0), mock.patch("arregloWeb.dialogo.mostrarInforme", mostrar):
				self.plugin.script_analizar(None)
			speak.assert_not_called()
		finally:
			options.set("informeVoz", True)

	def test_dos_pulsaciones_aplican_todo(self):
		d = self._doc()
		with mock.patch.object(aw, "currentDocument", return_value=d), mock.patch("tiresias.speech.api.speakMessage") as speak, \
				mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=1), mock.patch("arregloWeb.dialogo.mostrarInforme") as mostrar:
			self.plugin.script_analizar(None)
		mostrar.assert_not_called()
		self.assertIn("1 arreglo aplicado y guardados", speak.call_args[0][0])
		self.assertEqual(almacen.listaDe("www.ejemplo.com")[0]["nombre"], "informe anual (pdf)")
		self.assertEqual(d.rebuilds, 1)
		# Sin problemas: solo el resumen.
		d2 = FakeDoc(build(doc(group(text("Todo bien")))))
		with mock.patch.object(aw, "currentDocument", return_value=d2), mock.patch("tiresias.speech.api.speakMessage") as speak, \
				mock.patch("tiresias.input.core.getLastScriptRepeatCount", return_value=0), mock.patch("arregloWeb.dialogo.mostrarInforme") as mostrar:
			self.plugin.script_analizar(None)
		mostrar.assert_not_called()
		self.assertEqual(speak.call_args[0][0], "Arreglo web: no se han encontrado problemas en www.ejemplo.com.")

	def test_quitar_y_alternar(self):
		d = self._doc()
		with mock.patch.object(aw, "currentDocument", return_value=d), mock.patch("tiresias.speech.api.speakMessage") as speak:
			self.plugin.script_quitarArreglos(None)
			self.assertIn("No hay arreglos guardados para www.ejemplo.com", speak.call_args[0][0])
			almacen.anadir("www.ejemplo.com", [{"tipo": "maquetacion", "huella": {"ct": 1, "id": "t"}}])
			self.plugin.script_quitarArreglos(None)
			self.assertEqual(speak.call_args[0][0], "1 arreglo quitado de www.ejemplo.com.")
			self.assertEqual(almacen.sitios(), {})
			self.assertEqual(d.rebuilds, 1)
			self.plugin.script_alternarAutomatico(None)
			self.assertFalse(options.get("aplicarGuardados"))
			self.assertIn("no se aplican", speak.call_args[0][0])
			self.plugin.script_alternarAutomatico(None)
			self.assertTrue(options.get("aplicarGuardados"))
			self.assertEqual(d.rebuilds, 3)

	def test_describir_imagenes_pasa_por_la_ia_de_tiresias(self):
		d = self._doc()
		nodos = [p.node for p in analisis.analizar(d.buffer) if p.tipo == "imagenSinAlt"]
		self.assertEqual(len(nodos), 1)
		with mock.patch("tiresias.ai.assistant.checkProvider", return_value=None) as check, mock.patch("tiresias.speech.api.speakMessage"):
			self.plugin.describirImagenes(d, nodos)
		check.assert_called_once()
		options.set("describirImagenesIA", False)
		try:
			with mock.patch("tiresias.ai.assistant.checkProvider") as check, mock.patch("tiresias.speech.api.speakMessage") as speak:
				self.plugin.describirImagenes(d, nodos)
			check.assert_not_called()
			self.assertIn("desactivada", speak.call_args[0][0])
		finally:
			options.set("describirImagenesIA", True)

		# Con proveedor: se captura, se pregunta y se guarda en el almacén de textos de IA de Tiresias.
		class Prov:
			isRemote = False

			def chat(self, messages, system, maxTokens=0, effort=""):
				from tiresias.ai.providers import Message

				self.got = messages
				return Message("assistant", "Gráfico de ventas por trimestre.")

		prov = Prov()
		from arregloWeb import ia

		fin = []
		with mock.patch("tiresias.ai.assistant.checkProvider", return_value=prov), mock.patch("tiresias.ai.assistant.privacyAccepted", return_value=True), \
				mock.patch("tiresias.imaging.captureRect", return_value=object()), mock.patch("tiresias.ai.assistant._imageToPng", return_value=b"png"), \
				mock.patch("tiresias.ai.assistant.paddedRect", return_value=(0, 0, 10, 10)), mock.patch("tiresias.ai.labelstore.setLabel") as setLabel, \
				mock.patch("tiresias.ai.assistant.liveRect", return_value=(0, 0, 10, 10)), \
				mock.patch("tiresias.speech.api.speakMessage"), mock.patch("tiresias.queue_handler.queueFunction", side_effect=lambda f, *a, **k: f(*a, **k)), \
				mock.patch("threading.Thread") as thread:
			thread.side_effect = lambda target, args, name, daemon: mock.Mock(start=lambda: target(*args))
			self.assertTrue(ia.describir(d, nodos, 8, lambda h, f, e: fin.append((h, f, e))))
		self.assertEqual(fin, [(1, 0, "")])
		setLabel.assert_called_once_with(SITIO, nodos[0], "Gráfico de ventas por trimestre.")
		self.assertEqual(prov.got[0].images, [b"png"])
		self.assertEqual(d.rebuilds, 1)


# ====================================================================== diálogos (wx real)
class TestDialogos(Base):
	def test_informe(self):
		import wx

		from arregloWeb import dialogo

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		l = link("", [image("")], url="https://www.ejemplo.com/informes/informe-anual.pdf")
		buf = build(doc(group(l), group(image(""))))
		d = FakeDoc(buf)
		problemas = analisis.analizar(buf)
		aplicado = []
		dlg = dialogo.DialogoInforme(d, "www.ejemplo.com", problemas, lambda elegidos, guardar: aplicado.append((elegidos, guardar)), lambda nodos: None, True)
		try:
			self.assertEqual(dlg.lista.GetCount(), 2)
			self.assertTrue(dlg.lista.IsChecked(0))
			self.assertFalse(dlg.lista.IsChecked(1))
			self.assertTrue(dlg.btnIA.IsEnabled())
			self.assertEqual(len(dlg.marcados()), 1)
			dlg.lista.Check(0, False)
			self.assertEqual(dlg.marcados(), [])
			dlg.guardar.SetValue(False)
			dlg.aplicar(True)
		except Exception:
			dlg.Destroy()
			raise
		self.assertEqual(aplicado, [([problemas[0]], False)])
		# «Ir al elemento» mueve el cursor del documento (por el núcleo).
		dlg = dialogo.DialogoInforme(d, "www.ejemplo.com", problemas, lambda e, g: None, None, True)
		self.assertFalse(dlg.btnIA.IsEnabled())
		dlg.lista.SetSelection(1)
		with mock.patch("tiresias.queue_handler.queueFunction", side_effect=lambda f, *a, **k: f(*a, **k)):
			dlg.irAlElemento()
		self.assertEqual(d.moved, [problemas[1].offset])

	def test_sitios(self):
		import wx

		from arregloWeb import dialogo

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		almacen.anadir("www.ejemplo.com", [{"tipo": "nombre", "huella": {"ct": 1, "id": "a"}, "nombre": "A"}, {"tipo": "maquetacion", "huella": {"ct": 1, "id": "t"}}])
		almacen.anadir("otro.org", [{"tipo": "ocultar", "flex": {"ct": uc.CT_GROUP, "id": "cookie", "name": "", "cls": ""}, "doc": "https://otro.org/"}])
		flexweb.addHidden("https://otro.org/", {"ct": uc.CT_GROUP, "id": "cookie", "name": "", "cls": ""})
		cambios = []
		dlg = dialogo.DialogoSitios(cambios.append)
		try:
			self.assertEqual(dlg.claves, ["otro.org", "www.ejemplo.com"])
			dlg.sitios.SetSelection(1)
			dlg.mostrarSitio()
			self.assertEqual(dlg.reglas.GetCount(), 2)
			self.assertIn("Nombre «A»", dlg.reglas.GetString(0))
			dlg.reglas.SetSelection(0)
			dlg.quitarRegla()
			self.assertEqual(almacen.sitios(), {"www.ejemplo.com": 1, "otro.org": 1})
			dlg.sitios.SetSelection(0)
			dlg.mostrarSitio()
			self.assertIn("Oculto", dlg.reglas.GetString(0))
			dlg.quitarSitio()
			self.assertEqual(almacen.sitios(), {"www.ejemplo.com": 1})
			self.assertEqual(flexweb.rulesFor("https://otro.org/").hidden, [])
			self.assertEqual(cambios, ["www.ejemplo.com", "otro.org"])
		finally:
			dlg.Destroy()


if __name__ == "__main__":
	unittest.main()
