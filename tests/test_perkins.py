"""Pruebas del modo Perkins (versión 1.0.17).

Escribir con el teclado del PC como en una máquina Perkins: F D S J K L son
los puntos 1 2 3 4 5 6, la barra espaciadora el espaciador, A la tecla de
interlineado y Ñ la de retroceso. Solo actúa en los campos de texto (fuera
del modo exploración), suena como la máquina y toca la campana cerca del
final de la línea.

Ninguna prueba pulsa teclas reales ni suena: los códigos de las teclas se
pasan a mano y el reproductor es falso.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_perkins -v``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
import wave
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_perkins_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]

from tiresias.braille import input as brailleInput  # noqa: E402
from tiresias.braille import perkins  # noqa: E402
from tiresias.braille import presenter  # noqa: E402,F401  (registra las opciones braille)
from tiresias.config import conf  # noqa: E402

F, D, S, J, K, L, A, NN, SPACE, ENTER, BACK = 0x21, 0x20, 0x1F, 0x24, 0x25, 0x26, 0x1E, 0x27, 0x39, 0x1C, 0x0E


class FakePlayer:
	def __init__(self) -> None:
		self.played: list[str] = []

	def play(self, name: str) -> None:
		self.played.append(name)


class SonidosTests(unittest.TestCase):
	def test_sonidos_incluidos(self) -> None:
		folder = os.path.join(ROOT, "data", "perkins")
		for name in perkins.SOUND_NAMES:
			files = perkins.soundFiles(name, [folder])
			self.assertTrue(files, name)
			for f in files:
				with wave.open(f) as w:
					self.assertEqual(w.getsampwidth(), 2, f)
					self.assertLess(w.getnframes() / w.getframerate(), 1.5, f)
		self.assertEqual(len(perkins.soundFiles("tecla", [folder])), 4)
		self.assertEqual(len(perkins.soundFiles("espacio", [folder])), 3)
		self.assertTrue(os.path.isfile(os.path.join(folder, "CREDITOS.txt")))

	def test_los_propios_tienen_preferencia(self) -> None:
		tmp = tempfile.mkdtemp()
		self.addCleanup(shutil.rmtree, tmp, True)
		own = os.path.join(tmp, "propios")
		os.makedirs(own)
		open(os.path.join(own, "tecla.wav"), "wb").close()
		folder = os.path.join(ROOT, "data", "perkins")
		self.assertEqual(perkins.soundFiles("tecla", [own, folder]), [os.path.join(own, "tecla.wav")])
		# Lo que no tiene el usuario sale del programa; «tecla» no confunde con «teclado».
		open(os.path.join(own, "teclado.wav"), "wb").close()
		self.assertEqual(len(perkins.soundFiles("tecla", [own])), 1)
		self.assertTrue(perkins.soundFiles("campana", [own, folder])[0].startswith(folder))

	def test_carpeta_del_usuario_aparte(self) -> None:
		folders = [os.path.normcase(f) for f in perkins.soundFolders()]
		self.assertEqual(folders[0], os.path.normcase(paths.data("perkinsPropios")))


class MaquinaTests(unittest.TestCase):
	def setUp(self) -> None:
		self.player = FakePlayer()
		self.m = perkins.PerkinsMachine(self.player)
		conf["braille"]["perkinsSounds"] = True
		conf["braille"]["perkinsBell"] = True
		conf["braille"]["perkinsLineLength"] = 20

	def test_campana_cerca_del_final(self) -> None:
		for _ in range(13):
			self.m.cell()
		self.assertNotIn("campana", self.player.played)
		self.m.cell()  # columna 14 = 20 - 6
		self.assertEqual(self.player.played.count("campana"), 1)
		self.m.cell()
		self.assertEqual(self.player.played.count("campana"), 1)

	def test_interlineado_y_retroceso(self) -> None:
		for _ in range(5):
			self.m.cell()
		self.m.backspace()
		self.assertEqual(self.m.column, 4)
		self.m.newLine()
		self.assertEqual(self.m.column, 0)
		self.m.backspace()
		self.assertEqual(self.m.column, 0)
		self.assertEqual(self.player.played, ["retroceso", "linea", "retroceso"])

	def test_sin_sonidos(self) -> None:
		conf["braille"]["perkinsSounds"] = False
		self.m.keyDown(False)
		self.m.newLine()
		self.assertEqual(self.player.played, [])

	def test_sin_campana(self) -> None:
		conf["braille"]["perkinsBell"] = False
		for _ in range(30):
			self.m.cell()
		self.assertNotIn("campana", self.player.played)

	def test_golpe_de_tecla_y_espacio(self) -> None:
		self.m.keyDown(False)
		self.m.keyDown(True)
		self.assertEqual(self.player.played, ["tecla", "espacio"])


class TecladoTests(unittest.TestCase):
	"""El gancho del teclado en modo Perkins (hilo de los ganchos)."""

	def setUp(self) -> None:
		self.kb = brailleInput.PcBrailleKeyboard()
		self.queued: list[tuple] = []
		self.player = FakePlayer()
		mgr = SimpleNamespace(_tiresiasDown=False, _mods=set())
		self.mgr = mgr
		patches = [
			mock.patch.object(brailleInput.queue_handler, "queueFunction", side_effect=lambda f, *a: self.queued.append((f.__name__, *a))),
			mock.patch("tiresias.input.core.manager", mgr),
			mock.patch("tiresias.input.core.decide_handleRawKey"),
			mock.patch.object(perkins.machine, "_player", self.player),
			mock.patch("tiresias.api.post_focusChange"),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)
		conf["braille"]["perkinsOnlyInEditable"] = True
		conf["braille"]["perkinsSounds"] = True
		self.kb.setEnabled(True, perkins=True)
		self.kb._focusObj = SimpleNamespace()
		self.kb._focusEditable = True

	def press(self, *scans: int) -> list[bool]:
		res = [self.kb.onRawKey(scanCode=s, pressed=True) for s in scans]
		res += [self.kb.onRawKey(scanCode=s, pressed=False) for s in scans]
		return res

	def test_acorde_de_puntos(self) -> None:
		# F + D a la vez: puntos 1 y 2 (la «b»).
		self.assertEqual(self.press(F, D), [False] * 4)
		self.assertEqual(self.queued, [("_executePcGesture", 0b11, False)])
		self.assertEqual(self.player.played, ["tecla"])

	def test_puntos_4_5_6(self) -> None:
		self.press(J, K, L)
		self.assertEqual(self.queued, [("_executePcGesture", 0b111000, False)])

	def test_espaciador(self) -> None:
		self.press(SPACE)
		self.assertEqual(self.queued, [("_executePcGesture", 0, True)])
		self.assertEqual(self.player.played, ["espacio"])

	def test_interlineado_y_retroceso(self) -> None:
		self.assertEqual(self.press(A), [False, False])
		self.assertEqual(self.press(NN), [False, False])
		self.assertEqual(self.press(ENTER), [False, False])
		self.assertEqual(self.press(BACK), [False, False])
		self.assertEqual([q for q in self.queued], [("_executePerkinsKey", "line"), ("_executePerkinsKey", "back"), ("_executePerkinsKey", "line"), ("_executePerkinsKey", "back")])

	def test_retroceso_mantenido_repite(self) -> None:
		self.kb.onRawKey(scanCode=BACK, pressed=True)
		self.kb.onRawKey(scanCode=BACK, pressed=True)
		self.kb.onRawKey(scanCode=BACK, pressed=False)
		self.assertEqual(self.queued, [("_executePerkinsKey", "back")] * 2)

	def test_las_demas_teclas_son_normales(self) -> None:
		g, h, q = 0x22, 0x23, 0x10
		self.assertEqual(self.press(g, h, q), [True] * 6)
		self.assertEqual(self.queued, [])

	def test_fuera_de_un_campo_de_texto(self) -> None:
		self.kb._focusEditable = False
		self.assertEqual(self.press(F, D, A, ENTER), [True] * 8)
		self.assertEqual(self.queued, [])

	def test_en_modo_exploracion(self) -> None:
		self.kb._focusObj = SimpleNamespace(_treeInterceptor=SimpleNamespace(_passThrough=False))
		self.assertEqual(self.press(F, ENTER), [True] * 4)
		# En modo foco sí.
		self.kb._focusObj._treeInterceptor._passThrough = True
		self.assertEqual(self.press(F), [False] * 2)

	def test_en_cualquier_sitio_si_se_elige(self) -> None:
		conf["braille"]["perkinsOnlyInEditable"] = False
		self.kb._focusEditable = False
		self.assertEqual(self.press(F), [False, False])

	def test_con_modificadores_funcionan_los_atajos(self) -> None:
		self.mgr._mods = {"control"}
		self.assertEqual(self.press(F, A, ENTER), [True] * 6)
		self.mgr._mods = set()
		self.mgr._tiresiasDown = True
		self.assertEqual(self.press(S), [True, True])

	def test_seis_puntos_aunque_el_teclado_del_pc_sea_de_ocho(self) -> None:
		conf["braille"]["pcKeyboardDots"] = 8
		self.assertIsNone(self.kb._keyFor(A))
		self.assertIsNone(self.kb._keyFor(NN))

	def test_teclas_inyectadas_y_extendidas(self) -> None:
		self.assertTrue(self.kb.onRawKey(scanCode=F, pressed=True, injected=True))
		self.assertTrue(self.kb.onRawKey(scanCode=ENTER, pressed=True, extended=True))  # Intro del teclado numérico

	def test_desactivar(self) -> None:
		self.kb.setEnabled(False)
		self.assertFalse(self.kb.perkins)
		self.assertEqual(self.kb.onRawKey(scanCode=F, pressed=True), True)

	def test_el_foco_cambia_reinicia_la_columna(self) -> None:
		perkins.machine.column = 12
		with mock.patch("tiresias.clipboard.focusIsEditable", return_value=False):
			self.kb._onFocusChange(SimpleNamespace())
		self.assertFalse(self.kb._focusEditable)
		self.assertEqual(perkins.machine.column, 0)


class AccionesTests(unittest.TestCase):
	def test_interlineado_traduce_y_pulsa_intro(self) -> None:
		with mock.patch.object(brailleInput.handler, "enter") as enter, mock.patch.object(perkins.machine, "newLine") as line:
			brailleInput._executePerkinsKey("line")
		enter.assert_called_once()
		line.assert_called_once()

	def test_retroceso_borra_sin_decir_celda_borrada(self) -> None:
		with mock.patch.object(brailleInput.handler, "eraseLastCell") as erase, mock.patch.object(perkins.machine, "backspace"):
			brailleInput._executePerkinsKey("back")
		erase.assert_called_once_with(announce=False)

	def test_conmutar(self) -> None:
		kb = brailleInput.pcKeyboard
		with mock.patch.object(kb, "setEnabled", wraps=lambda on, perkins=False: setattr(kb, "perkins", on and perkins)) as setEnabled, mock.patch.object(
			kb, "perkinsActiveHere", return_value=True
		), mock.patch.object(perkins.machine, "_player", FakePlayer()):
			kb.perkins = False
			self.assertEqual(perkins.toggle(), "modo Perkins")
			self.assertTrue(kb.perkins)
			self.assertEqual(perkins.toggle(), "teclado normal")
			self.assertFalse(kb.perkins)
		self.assertEqual(setEnabled.call_count, 2)

	def test_orden_con_tecla(self) -> None:
		from tiresias.braille import commands

		gestures = [g for func, _d, gs in commands._SCRIPTS if func is commands.script_braille_togglePerkins for g in gs]
		self.assertEqual(gestures, ["kb:tiresias+control+shift+b"])


class EscrituraTests(unittest.TestCase):
	"""Lo que se escribe de verdad en el campo con el modo Perkins (sin teclado real)."""

	def setUp(self) -> None:
		self.out: list[str] = []
		h = brailleInput.BrailleInputHandler()
		self.h = h

		def typed(text: str) -> None:
			self.out.append(text)

		def back(n: int) -> None:
			for _ in range(n):
				if self.out:
					last = self.out.pop()
					if len(last) > 1:
						self.out.append(last[:-1])

		for target, func in ((h, "_type"), (h, "_backspace"), (h, "_updateDisplay")):
			p = mock.patch.object(target, func, side_effect={"_type": typed, "_backspace": back, "_updateDisplay": lambda: None}[func])
			p.start()
			self.addCleanup(p.stop)
		p = mock.patch.object(brailleInput.pcKeyboard, "perkins", True)
		p.start()
		self.addCleanup(p.stop)
		conf["braille"]["perkinsTable"] = "auto"
		conf["braille"]["inputTable"] = "auto"  # la informática: el modo Perkins no la usa

	def write(self, *cells: tuple[int, ...]) -> str:
		for dots in cells:
			if dots == ():
				self.h.space()
			else:
				self.h.input(sum(1 << (d - 1) for d in dots))
		return "".join(self.out)

	def test_tabla_literaria_por_defecto(self) -> None:
		self.assertIn(perkins.tableName(), perkins.AUTO_TABLES)
		self.assertFalse(self.h.table().contracted)

	def test_mayuscula(self) -> None:
		self.assertEqual(self.write((4, 6), (1, 2, 5), (1, 3, 5), (1, 2, 3), (1,)), "Hola")

	def test_numeros(self) -> None:
		self.assertEqual(self.write((3, 4, 5, 6), (1,), (1, 2), (1, 4)), "123")

	def test_acentos_y_ene(self) -> None:
		self.assertEqual(self.write((1, 2, 3, 5, 6), (), (1, 2, 4, 5, 6), (), (2, 3, 4, 6)), "á ñ é")

	def test_interrogacion_y_exclamacion(self) -> None:
		self.assertEqual(self.write((2, 6), (1, 2, 5), (1, 3, 5), (1, 2, 3), (1,), (2, 6)), "¿hola?")
		self.out.clear()
		self.h.reset()
		self.assertEqual(self.write((2, 3, 5), (2, 4), (1, 2, 3, 4), (2, 3, 5)), "¡ip!")

	def test_frase(self) -> None:
		self.assertEqual(self.write((1, 2, 5), (1, 3, 5), (1, 2, 3), (1,), (), (1, 3, 4), (1, 3, 6), (1, 3, 4, 5), (1, 4, 5), (1, 3, 5)), "hola mundo")

	def test_retroceso_deshace_la_celda(self) -> None:
		self.write((1, 2, 5), (1, 3, 5))
		with mock.patch("tiresias.speech.speakMessage"):
			self.h.eraseLastCell(announce=False)
		self.assertEqual("".join(self.out), "h")

	def test_otra_tabla_elegida(self) -> None:
		conf["braille"]["perkinsTable"] = "es-g1"
		self.assertEqual(perkins.tableName(), "es-g1")
		conf["braille"]["perkinsTable"] = "auto"

	def test_signos_espanoles(self) -> None:
		self.assertEqual(perkins.fixSpanishMarks("?hola?"), "¿hola?")
		self.assertEqual(perkins.fixSpanishMarks("¿"), "¿")
		self.assertEqual(perkins.fixSpanishMarks("hola¡"), "hola!")
		self.assertEqual(perkins.fixSpanishMarks(""), "")


if __name__ == "__main__":
	unittest.main()
