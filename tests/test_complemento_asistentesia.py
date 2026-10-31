"""Pruebas del complemento «Asistentes de IA accesibles» (complementos_tienda/asistentesIA).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_asistentesia -v``

Los árboles imitan los volcados reales de Claude 4.4212, Codex 26.1016 y
Antigravity IDE (31-10-2026). Sin ganchos, sin voz y sin tocar ninguna aplicación.
"""

from __future__ import annotations

import importlib
import json
import os
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
BASE = os.path.join(ROOT, "complementos_tienda", "asistentesIA")

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_asistentes_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias.a11y import uia_client as uc  # noqa: E402
from tiresias.config import conf  # noqa: E402

sys.dont_write_bytecode = True
for _name, _path in (("t_asistentes", BASE), ("t_asistentes.appModules", os.path.join(BASE, "appModules")), ("t_asistentes.globalPlugins", os.path.join(BASE, "globalPlugins"))):
	if _name not in sys.modules:
		_mod = types.ModuleType(_name)
		_mod.__path__ = [_path]  # type: ignore[attr-defined]
		sys.modules[_name] = _mod

M = importlib.import_module("t_asistentes.appModules.ia_motor")
claude = importlib.import_module("t_asistentes.appModules.claude")
chatgpt = importlib.import_module("t_asistentes.appModules.chatgpt")
codex = importlib.import_module("t_asistentes.appModules.codex")
codeMod = importlib.import_module("t_asistentes.appModules.code")
op = importlib.import_module("t_asistentes.appModules.ia_opciones")
N = M.Nodo


def texto(t: str, **kw) -> N:
	return N(name=t, ct=uc.CT_TEXT, aria="description", **kw)


def rotulo(t: str) -> N:
	return N(name=t, ct=uc.CT_TEXT, aria="heading", cls="sr-only select-none", children=[texto(t)])


def grupo(*hijos, **kw) -> N:
	return N(ct=uc.CT_GROUP, aria="group", children=list(hijos), **kw)


def boton(t: str, cls: str = "no-drag") -> N:
	return N(name=t, ct=uc.CT_BUTTON, aria="button", cls=cls)


def lista(*items: str) -> N:
	return N(ct=uc.CT_LIST, aria="list", children=[N(name=i, ct=uc.CT_LISTITEM, aria="listitem") for i in items])


class ManifiestoTests(unittest.TestCase):
	def test_manifiesto(self) -> None:
		with open(os.path.join(BASE, "manifest.json"), encoding="utf-8") as f:
			data = json.load(f)
		self.assertEqual(data["id"], "asistentesIA")
		self.assertEqual(data["version"], "1.0.0")
		for key in ("name", "description", "changelog", "minApiVersion", "lastTestedApiVersion"):
			self.assertTrue(data[key], key)

	def test_readme_documenta_cada_orden(self) -> None:
		with open(os.path.join(BASE, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for tecla in ("Tiresias+Alt+U", "Tiresias+Alt+Y", "Tiresias+Alt+P", "Tiresias+Alt+Q", "Tiresias+Alt+Z", "Tiresias+Control+Flecha arriba", "Tiresias+Control+Flecha abajo", "Tiresias+Control+Inicio", "Tiresias+Control+Fin"):
			self.assertIn(tecla, html)

	def test_gestos_sin_conflictos(self) -> None:
		with open(os.path.join(BASE, "appModules", "ia_motor.py"), encoding="utf-8") as f:
			gestos = set(re.findall(r'gesture="(kb:[^"]+)"', f.read()))
		self.assertEqual(len(gestos), 9)
		usados: set[str] = set()
		carpetas = [os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons")]
		for raiz in carpetas:
			for base, _dirs, files in os.walk(raiz):
				if "asistentesIA" in base:
					continue
				for nombre in files:
					if nombre.endswith(".py"):
						with open(os.path.join(base, nombre), encoding="utf-8", errors="replace") as f:
							usados.update(re.findall(r"kb:[A-Za-z0-9+]+", f.read()))
		self.assertEqual(gestos & usados, set())

	def test_modulos_por_ejecutable(self) -> None:
		from tiresias.appmodules import handler

		self.assertEqual(handler.moduleNameForProcess("claude"), "claude")
		self.assertEqual(handler.moduleNameForProcess("ChatGPT"), "chatgpt")
		self.assertEqual(handler.moduleNameForProcess("Codex"), "codex")
		self.assertEqual(handler.moduleNameForProcess("Antigravity IDE"), "code")
		self.assertIs(codex.AppModule, chatgpt.AppModule)
		self.assertTrue(issubclass(codeMod.AppModule, M.AsistenteAppModule))


class TextoTests(unittest.TestCase):
	def test_trozos_del_mismo_padre_van_seguidos(self) -> None:
		parrafo = grupo(texto("Usa "), texto("negrita"), texto(" aquí."))
		self.assertEqual(M.textoDe(grupo(parrafo)), "Usa negrita aquí.")

	def test_parrafos_en_lineas_distintas(self) -> None:
		self.assertEqual(M.textoDe(grupo(grupo(texto("Primero.")), grupo(texto("Segundo.")))), "Primero.\nSegundo.")

	def test_saltos_de_linea_del_codigo(self) -> None:
		self.assertEqual(M.textoDe(grupo(grupo(texto("a = 1"), texto("\n"), texto("b = 2")))), "a = 1\nb = 2")

	def test_omite_botones_imagenes_horas_y_contadores(self) -> None:
		nodo = grupo(grupo(texto("Hola.")), boton("Copiar mensaje"), N(ct=uc.CT_IMAGE, name="icono"), texto("10:15"), texto("+135"), texto("-11"), N(aria="status", ct=uc.CT_STATUSBAR, name="estado"))
		self.assertEqual(M.textoDe(nodo), "Hola.")

	def test_mencion_en_linea_se_lee(self) -> None:
		nodo = grupo(texto("Instalado en "), boton("tu carpeta habitual", "_InlineMentionFocusRing_1fgd0_2"), texto("."))
		self.assertEqual(M.textoDe(grupo(nodo)), "Instalado en tu carpeta habitual.")

	def test_elemento_de_lista_con_su_nombre_entero(self) -> None:
		item = N(name="Tor sigue sin conectar. Puedes usar la directa.", ct=uc.CT_LISTITEM, children=[texto("Tor sigue sin conectar.")])
		self.assertEqual(M.textoDe(grupo(item)), "- Tor sigue sin conectar. Puedes usar la directa.")


class ClaudeTests(unittest.TestCase):
	def _feed(self) -> N:
		return N(
			name="Mensajes del chat",
			aria="feed",
			ct=uc.CT_GROUP,
			children=[
				grupo(texto("Usa las flechas"), cls="sr-only select-none"),
				N(name="Mensaje 1", aria="article", ct=uc.CT_GROUP, children=[rotulo("Dijiste: Hola"), grupo(texto("Hola"))]),
				grupo(boton("Ejecutó 12 comandos"), cls="group/message-row"),
				N(name="Mensaje 2", aria="article", ct=uc.CT_GROUP, children=[grupo(rotulo("Claude respondió: Buenas"), grupo(texto("Buenas tardes.")), boton("Copiar"))]),
				N(name="Mensaje en transmisión", aria="article", ct=uc.CT_GROUP, children=[grupo(rotulo("Claude respondió: Sigo"), grupo(texto("Sigo")))]),
			],
		)

	def test_mensajes(self) -> None:
		msgs = M.mensajesClaude(self._feed())
		self.assertEqual([(m.autor, m.texto) for m in msgs], [(M.USUARIO, "Hola"), (M.ASISTENTE, "Buenas tardes."), (M.ASISTENTE, "Sigo")])
		self.assertEqual([m.enCurso for m in msgs], [False, False, True])

	def test_trabajando_por_aria_busy(self) -> None:
		app = claude.AppModule.__new__(claude.AppModule)
		feed = mock.Mock()
		feed.GetCurrentPropertyValue.return_value = "busy=true;readonly=true"
		with mock.patch.object(app, "buscarConversacion", return_value=feed):
			self.assertTrue(app.estaTrabajando(object()))
			feed.GetCurrentPropertyValue.return_value = "readonly=true"
			self.assertFalse(app.estaTrabajando(object()))
		with mock.patch.object(app, "buscarConversacion", return_value=None):
			self.assertIsNone(app.estaTrabajando(object()))


class CodexTests(unittest.TestCase):
	def _conv(self) -> N:
		return N(
			name="Conversación",
			aria="region",
			ct=uc.CT_GROUP,
			children=[
				N(name="hoy 10:15", ct=uc.CT_SEPARATOR, aria="separator"),
				rotulo("Tú dijiste:"),
				grupo(texto("arregla el 443")),
				texto("10:15"),
				grupo(boton("Copiar mensaje")),
				boton("Ha trabajado durante 7min 39s"),
				rotulo("ChatGPT dijo:"),
				N(aria="status", ct=uc.CT_STATUSBAR, cls="sr-only"),
				grupo(texto("He corregido el código en "), boton("tu carpeta", "_InlineMentionFocusRing_1fgd0_2"), texto(".")),
				lista("48 pruebas superadas."),
				texto("Se han editado 7 archivos"),
				texto("+135"),
				boton("Deshacer"),
				rotulo("Última respuesta"),
				N(name="Trabaja con Codex", ct=uc.CT_EDIT, aria="textbox", cls="ProseMirror", children=[texto("Trabaja con Codex")]),
			],
		)

	def test_mensajes(self) -> None:
		msgs = M.mensajesCodex(self._conv())
		self.assertEqual([m.autor for m in msgs], [M.USUARIO, M.ASISTENTE])
		self.assertEqual(msgs[0].texto, "arregla el 443")
		self.assertIn("He corregido el código en tu carpeta.", msgs[1].texto)
		self.assertIn("- 48 pruebas superadas.", msgs[1].texto)
		self.assertIn("Se han editado 7 archivos", msgs[1].texto)
		for ruido in ("Deshacer", "+135", "Trabaja con Codex", "10:15", "Copiar"):
			self.assertNotIn(ruido, " ".join(m.texto for m in msgs))

	def test_rotulos_en_ingles(self) -> None:
		conv = grupo(rotulo("You said:"), texto("hi"), rotulo("ChatGPT said:"), texto("hello"), rotulo("Latest response"), texto("x"))
		self.assertEqual([(m.autor, m.texto) for m in M.mensajesCodex(conv)], [(M.USUARIO, "hi"), (M.ASISTENTE, "hello")])

	def test_acortar_descripcion(self) -> None:
		self.assertEqual(chatgpt.acortar("  corto  "), "corto")
		largo = chatgpt.acortar("palabra " * 80)
		self.assertLessEqual(len(largo), chatgpt.LARGO_DESCRIPCION + 1)
		self.assertTrue(largo.endswith("…"))

	def test_boton_de_mensaje_con_descripcion_corta(self) -> None:
		app = chatgpt.AppModule.__new__(chatgpt.AppModule)
		obj = types.SimpleNamespace(UIAControlType=uc.CT_BUTTON, name="Ir al mensaje del usuario 1", description="palabra " * 80)
		app.event_NVDAObject_init(obj)
		self.assertLessEqual(len(obj.description), chatgpt.LARGO_DESCRIPCION + 1)
		otro = types.SimpleNamespace(UIAControlType=uc.CT_BUTTON, name="Dictar", description="igual " * 80)
		original = otro.description
		app.event_NVDAObject_init(otro)
		self.assertEqual(otro.description, original)

	def test_boton_detener(self) -> None:
		for nombre, esperado in (("Detener", True), ("Stop generating", True), ("Interrumpir", True), ("Dictar", False), ("Cancelación", False)):
			self.assertEqual(bool(M.RE_DETENER.match(nombre)), esperado, nombre)


class AntigravityTests(unittest.TestCase):
	def test_excluye_el_cuadro_de_escribir(self) -> None:
		conv = N(
			name="Agent Conversation",
			aid="conversation",
			children=[
				grupo(
					grupo(texto("Primera respuesta.")),
					grupo(texto("Segunda respuesta.")),
					grupo(N(name="Message input", ct=uc.CT_COMBOBOX, aria="combobox"), texto("Ask anything"), boton("Send message")),
				)
			],
		)
		self.assertEqual([m.texto for m in M.mensajesAntigravity(conv)], ["Primera respuesta.", "Segunda respuesta."])

	def test_sin_conversacion(self) -> None:
		conv = N(children=[grupo(texto("mi-proyecto"), N(name="Message input", ct=uc.CT_COMBOBOX), boton("Send"))])
		self.assertEqual(M.mensajesAntigravity(conv), [])

	def test_el_aviso_fijo_no_es_un_mensaje(self) -> None:
		conv = N(children=[grupo(grupo(N(name="Message input", ct=uc.CT_COMBOBOX)), grupo(texto("AI may make mistakes. Double-check all generated code.")))])
		self.assertEqual(M.mensajesAntigravity(conv), [])

	def test_iconos_sin_nombre(self) -> None:
		app = codeMod.AppModule.__new__(codeMod.AppModule)
		app.appName = "Antigravity IDE"
		obj = types.SimpleNamespace(UIAControlType=uc.CT_HYPERLINK, name="")
		with mock.patch.object(app, "_nombreIcono", return_value="Nueva conversación"):
			app.event_NVDAObject_init(obj)
		self.assertEqual(obj.name, "Nueva conversación")
		otro = types.SimpleNamespace(UIAControlType=uc.CT_HYPERLINK, name="")
		app.appName = "Code"
		with mock.patch.object(app, "_nombreIcono", return_value="X"):
			app.event_NVDAObject_init(otro)
		self.assertEqual(otro.name, "")


class _App(M.AsistenteAppModule):
	nombreAsistente = "Claude"

	def __init__(self) -> None:
		self._iniciarAsistente()
		self.dicho: list[str] = []
		self.lista: list = []
		self.ocupado: bool | None = False
		self.delante = True

	def isForeground(self) -> bool:
		return self.delante

	def _decir(self, texto: str) -> None:
		self.dicho.append(texto)

	def mensajes(self):
		return self.lista

	def _raiz(self):
		return object()

	def estaTrabajando(self, raiz):
		return self.ocupado


class OrdenesTests(unittest.TestCase):
	def setUp(self) -> None:
		self.app = _App()
		self.app.lista = [M.Mensaje(M.USUARIO, "Hola"), M.Mensaje(M.ASISTENTE, "Buenas"), M.Mensaje(M.USUARIO, "Gracias"), M.Mensaje(M.ASISTENTE, "De nada")]
		self.saved = dict(conf[op.SECTION])
		for p in (mock.patch.object(M.tones, "beep"), mock.patch.object(M.speech, "speakMessage")):
			self.addCleanup(p.stop)
			setattr(self, "beep" if "beep" in str(p.attribute) else "habla", p.start())

	def tearDown(self) -> None:
		conf[op.SECTION].update(self.saved)

	def test_navegar_empieza_por_el_final(self) -> None:
		self.app.script_mensajeAnterior(None)
		self.assertEqual(self.app.dicho[-1], "Claude, 4 de 4: De nada")
		self.app.script_mensajeAnterior(None)
		self.assertEqual(self.app.dicho[-1], "Tú, 3 de 4: Gracias")
		self.app.script_mensajeSiguiente(None)
		self.assertEqual(self.app.dicho[-1], "Claude, 4 de 4: De nada")

	def test_limites(self) -> None:
		self.app.script_mensajeSiguiente(None)
		self.assertEqual(self.app.dicho[-1], "Último mensaje")
		self.beep.assert_called_once()
		self.app.script_primerMensaje(None)
		self.assertEqual(self.app.dicho[-1], "Tú, 1 de 4: Hola")
		self.app.script_mensajeAnterior(None)
		self.assertEqual(self.app.dicho[-1], "Primer mensaje")
		self.app.script_ultimoMensaje(None)
		self.assertEqual(self.app.dicho[-1], "Claude, 4 de 4: De nada")

	def test_sin_conversacion(self) -> None:
		self.app.lista = []
		self.app.script_mensajeAnterior(None)
		self.assertEqual(self.app.dicho[-1], "No se encuentra ninguna conversación")

	def test_ultima_respuesta_y_copia(self) -> None:
		with mock.patch.object(M.inputCore, "getLastScriptRepeatCount", return_value=0):
			self.app.script_ultimaRespuesta(None)
		self.assertEqual(self.app.dicho[-1], "Claude, 4 de 4: De nada")
		self.assertEqual(self.app._pos, 3)
		with mock.patch.object(M.inputCore, "getLastScriptRepeatCount", return_value=1), mock.patch.object(M.api, "copyToClip", return_value=True) as copia:
			self.app.script_ultimaRespuesta(None)
		copia.assert_called_once_with("De nada")
		self.assertEqual(self.app.dicho[-1], "Respuesta copiada")

	def test_estado(self) -> None:
		self.app.ocupado = True
		self.app.script_estado(None)
		self.assertEqual(self.app.dicho[-1], "Claude está trabajando, 4 mensajes")
		self.app.ocupado = False
		self.app.script_estado(None)
		self.assertEqual(self.app.dicho[-1], "Claude está esperando, 4 mensajes")
		self.app.ocupado = None
		self.app.script_estado(None)
		self.assertEqual(self.app.dicho[-1], "No se sabe si Claude está trabajando, 4 mensajes")
		self.app.lista = self.app.lista[:1]
		self.app.script_estado(None)
		self.assertEqual(self.app.dicho[-1], "No se sabe si Claude está trabajando, 1 mensaje")

	def test_alternar_lectura(self) -> None:
		conf[op.SECTION]["leerRespuesta"] = False
		self.app.script_alternarLectura(None)
		self.assertTrue(conf[op.SECTION]["leerRespuesta"])
		self.app.script_alternarLectura(None)
		self.assertFalse(conf[op.SECTION]["leerRespuesta"])

	def _turno(self) -> None:
		self.app.ocupado = True
		self.app.comprobarTurno()
		self.app.ocupado = False
		self.app.comprobarTurno()

	def test_aviso_solo_tras_dos_pasadas_libres(self) -> None:
		self._turno()
		self.habla.assert_not_called()
		self.app.comprobarTurno()
		self.habla.assert_called_once_with("Claude ha terminado")
		self.beep.assert_called_once()
		self.app.comprobarTurno()
		self.habla.assert_called_once()

	def test_el_indicador_que_parpadea_entre_pasos_no_avisa(self) -> None:
		self._turno()
		self.app.ocupado = True
		self.app.comprobarTurno()
		self.app.ocupado = False
		self.app.comprobarTurno()
		self.habla.assert_not_called()

	def test_sin_saber_no_cambia_nada(self) -> None:
		self.app.ocupado = True
		self.app.comprobarTurno()
		self.app.ocupado = None
		self.app.comprobarTurno()
		self.app.comprobarTurno()
		self.habla.assert_not_called()
		self.assertTrue(self.app._trabajando)

	def test_nada_que_avisar_si_no_trabajaba(self) -> None:
		self.app.comprobarTurno()
		self.app.comprobarTurno()
		self.habla.assert_not_called()

	def test_segundo_plano(self) -> None:
		self.app.delante = False
		conf[op.SECTION]["avisarEnSegundoPlano"] = False
		self._turno()
		self.app.comprobarTurno()
		self.habla.assert_not_called()
		conf[op.SECTION]["avisarEnSegundoPlano"] = True
		self._turno()
		self.app.comprobarTurno()
		self.habla.assert_called_once_with("Claude ha terminado")

	def test_lectura_automatica_sustituye_al_aviso(self) -> None:
		conf[op.SECTION]["leerRespuesta"] = True
		self._turno()
		self.app.comprobarTurno()
		self.habla.assert_not_called()
		self.assertEqual(self.app.dicho[-1], "Claude, 4 de 4: De nada")

	def test_lectura_automatica_no_lee_en_segundo_plano(self) -> None:
		conf[op.SECTION]["leerRespuesta"] = True
		self.app.delante = False
		self._turno()
		self.app.comprobarTurno()
		self.habla.assert_called_once_with("Claude ha terminado")
		self.assertEqual(self.app.dicho, [])


if __name__ == "__main__":
	unittest.main()
