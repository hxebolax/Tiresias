"""Pruebas de las funciones de productividad.

Analizador de texto, reglas e historial de notificaciones, vigilancias,
búsqueda en ventanas y marcadores de texto. Son funciones puras o con
archivos temporales: no se toca UI Automation ni la carpeta de datos real.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias.productivity import text_analyzer as ta  # noqa: E402
from tiresias.productivity import window_find  # noqa: E402
from tiresias.productivity.notifications import (  # noqa: E402
	ACTION_BRAILLE,
	ACTION_SILENCE,
	PRIORITY_HIGH,
	SOURCE_LIVEREGION,
	SOURCE_NOTIFICATION,
	Entry,
	NotificationStore,
	Rule,
	findRule,
)
from tiresias.productivity.text_bookmarks import BookmarkStore, TextBookmark, relocate  # noqa: E402
from tiresias.productivity.text_context import TextContext, normalizeTitle  # noqa: E402
from tiresias.productivity.watch import changedText  # noqa: E402


def kinds(text: str, **checks) -> list[tuple[str, str]]:
	return [(i.kind, text[i.start : i.end]) for i in ta.analyze(text, checks or None)]


class TextAnalyzerTests(unittest.TestCase):
	def test_texto_correcto(self):
		self.assertEqual(ta.analyze("Hola, mundo. Esto (y aquello) está bien. ¿Vienes? ¡Claro!"), [])

	def test_parentesis_sin_cerrar_y_sin_abrir(self):
		self.assertIn(("unclosed", "("), kinds("Esto (no se cierra."))
		self.assertIn(("unopened", ")"), kinds("Esto no se abre)."))
		self.assertIn(("unclosed", "["), kinds("Lista [uno, dos."))

	def test_parentesis_cerrado_en_la_linea_siguiente(self):
		# Mismo párrafo: no es un error (falso positivo típico).
		self.assertEqual(kinds("Texto (que sigue\nen la otra línea) bien."), [])

	def test_parentesis_de_otro_parrafo(self):
		self.assertIn(("unclosed", "("), kinds("Uno (abierto.\n\nDos cerrado)."))

	def test_numeracion_de_listas(self):
		self.assertEqual(kinds("1) primero\n2) segundo\na) letra"), [])

	def test_comillas(self):
		self.assertIn(("unclosed", '"'), kinds('Dijo "hola y se fue.'))
		self.assertEqual(kinds('Dijo "hola" y se fue.'), [])
		self.assertIn(("unclosed", "«"), kinds("Dijo «hola y se fue."))

	def test_signos_espanoles(self):
		self.assertIn(("unclosed", "¿"), kinds("¿Vienes mañana."))
		self.assertIn(("unclosed", "¡"), kinds("¡Qué bien."))
		self.assertEqual(kinds("¿Vienes?"), [])
		self.assertEqual(kinds("¿Vienes mañana.", spanishMarks=False), [])

	def test_espacios(self):
		self.assertIn(("doubleSpace", "  "), kinds("Hola  mundo."))
		# La sangría y los espacios finales no cuentan.
		self.assertEqual(kinds("    Sangría.\nFin.   "), [])
		self.assertIn(("spaceBeforePunct", " "), kinds("Hola , mundo."))
		self.assertIn(("spaceBeforePunct", " "), kinds("Fin ."))
		self.assertEqual(kinds("Vale 0.5 y .5 están bien."), [])

	def test_mayuscula_tras_punto(self):
		self.assertIn(("lowercaseAfterPeriod", "y"), kinds("Fin. y sigue."))
		self.assertEqual(kinds("Vino el Sr. Pérez, etc. y más."), [])
		self.assertEqual(kinds("Hola... y adiós."), [])
		self.assertEqual(kinds("Por ej. esto, p. ej. aquello."), [])

	def test_palabra_repetida(self):
		self.assertIn(("repeatedWord", "el"), kinds("Vi el el coche."))
		self.assertEqual(kinds("Que que no."), [])

	def test_mayusculas_raras(self):
		self.assertEqual(kinds("Escribo hOla."), [])
		self.assertIn(("mixedCase", "hOla"), kinds("Escribo hOla.", mixedCase=True))

	def test_formato(self):
		text = "Hola mundo bonito hoy"
		runs = [
			ta.FormatRun(0, 7, "Arial", 12),
			ta.FormatRun(7, 11, "Times", 12),  # «ndo » cambia dentro de «mundo»
			ta.FormatRun(11, 21, "Arial", 12),
		]
		issues = ta.formatIssues(text, runs)
		self.assertTrue(any(i.kind == "format" and i.start == 7 for i in issues))
		self.assertTrue(any("Times" in i.message for i in issues))
		self.assertEqual(ta.formatIssues(text, [ta.FormatRun(0, 21, "Arial", 12)]), [])

	def test_busqueda(self):
		issues = ta.analyze("Uno  dos. tres  cuatro.")
		first = ta.nextIssue(issues, -1, 1)
		self.assertEqual(first.kind, "doubleSpace")
		second = ta.nextIssue(issues, first.start, 1)
		self.assertGreater(second.start, first.start)
		self.assertEqual(ta.nextIssue(issues, second.start, -1), first)
		self.assertIsNone(ta.nextIssue(issues, 10_000, 1))
		self.assertEqual(ta.issuesInRange(issues, 0, 5), [first])
		self.assertIn("espacio doble", ta.describe([first]))


class NotificationTests(unittest.TestCase):
	def test_reglas(self):
		rules = [
			Rule(name="silencio", apps="teams.exe, outlook", pattern=r"se ha unido", action=ACTION_SILENCE),
			Rule(name="braille", pattern=r"^descarga", action=ACTION_BRAILLE),
			Rule(name="alta", apps="chrome", priority=PRIORITY_HIGH, sources=[SOURCE_LIVEREGION]),
		]
		self.assertEqual(findRule(rules, "Teams", "Ana se ha unido a la reunión").name, "silencio")
		self.assertIsNone(findRule(rules, "notepad", "Ana se ha unido"))
		self.assertEqual(findRule(rules, "firefox", "Descarga completada").name, "braille")
		self.assertEqual(findRule(rules, "chrome", "x", SOURCE_LIVEREGION).name, "alta")
		self.assertIsNone(findRule(rules, "chrome", "x", SOURCE_NOTIFICATION))
		rules[0].enabled = False
		self.assertIsNone(findRule(rules, "teams", "Ana se ha unido"))

	def test_regla_invalida(self):
		r = Rule(pattern="(sin cerrar")
		self.assertFalse(r.isValid())
		self.assertFalse(r.matches("app", "(sin cerrar"))
		self.assertTrue(Rule(pattern="Hola", caseSensitive=True).matches("a", "Hola"))
		self.assertFalse(Rule(pattern="Hola", caseSensitive=True).matches("a", "hola"))

	def test_historial(self):
		store = NotificationStore(None, maxEntries=3)
		self.assertTrue(store.add(Entry(100.0, "app", SOURCE_NOTIFICATION, "uno")))
		self.assertFalse(store.add(Entry(100.5, "app", SOURCE_NOTIFICATION, "uno")))  # duplicado inmediato
		store.add(Entry(110.0, "app", SOURCE_NOTIFICATION, "dos"))
		store.add(Entry(120.0, "otra", SOURCE_LIVEREGION, "tres cosas"))
		store.add(Entry(130.0, "otra", SOURCE_LIVEREGION, "cuatro"))
		self.assertEqual([e.text for e in store.entries()], ["dos", "tres cosas", "cuatro"])
		self.assertEqual(store.last().text, "cuatro")
		self.assertEqual([e.text for e in store.search(store.entries(), "tres")], ["tres cosas"])
		self.assertEqual([e.text for e in store.search(store.entries(), "", app="app")], ["dos"])
		store.setMaxEntries(10)
		store.clear()
		self.assertIsNone(store.last())

	def test_guardar_reglas(self):
		tmp = tempfile.mkdtemp(prefix="tiresias_test_notif_")
		try:
			path = os.path.join(tmp, "config", "reglas.json")
			store = NotificationStore(path)
			store.rules = [Rule(name="a", apps="x", pattern="y", action=ACTION_SILENCE, sound="error", sources=[SOURCE_LIVEREGION])]
			store.saveRules()
			other = NotificationStore(path)
			other.loadRules()
			self.assertEqual(other.rules, store.rules)
		finally:
			shutil.rmtree(tmp, ignore_errors=True)


class WatchTests(unittest.TestCase):
	def test_texto_cambiado(self):
		self.assertEqual(changedText("", "Descargando 10%"), "Descargando 10%")
		self.assertEqual(changedText("Descargando 10%", "Descargando 20%"), "Descargando 20%")
		self.assertEqual(changedText("Hola", "Hola"), "")
		self.assertEqual(changedText("Ana: hola", "Ana: hola\nLuis: qué tal"), "Luis: qué tal")
		self.assertEqual(changedText("a\nb\nc", "b\nc\nd"), "d")
		self.assertEqual(changedText("algo", "   "), "")


@dataclass
class _Cand:
	text: str


class WindowFindTests(unittest.TestCase):
	def test_coincidencias(self):
		self.assertTrue(window_find.matches("Menú Archivo", "menu"))
		self.assertFalse(window_find.matches("Menú Archivo", "menu", caseSensitive=True))
		self.assertFalse(window_find.matches("Algo", ""))

	def test_siguiente_y_anterior(self):
		cands = [_Cand("Aceptar"), _Cand("Cancelar"), _Cand("Ayuda"), _Cand("Cancelar todo")]
		self.assertEqual(window_find.pickNext(cands, -1, "cancelar", 1), (1, False))
		self.assertEqual(window_find.pickNext(cands, 1, "cancelar", 1), (3, False))
		self.assertEqual(window_find.pickNext(cands, 3, "cancelar", 1), (1, True))
		self.assertEqual(window_find.pickNext(cands, 3, "cancelar", -1), (1, False))
		self.assertEqual(window_find.pickNext(cands, 1, "cancelar", -1), (3, True))
		self.assertEqual(window_find.pickNext(cands, -1, "cancelar", -1), (3, False))
		self.assertEqual(window_find.pickNext(cands, 0, "nada", 1), (-1, False))
		self.assertEqual(window_find.pickNext([_Cand("solo")], 0, "solo", 1), (0, True))
		self.assertEqual(window_find.pickNext([], -1, "x", 1), (-1, False))


class TextBookmarkTests(unittest.TestCase):
	def setUp(self):
		self.tmp = tempfile.mkdtemp(prefix="tiresias_test_marcas_")
		self.path = os.path.join(self.tmp, "config", "marcadores.json")

	def tearDown(self):
		shutil.rmtree(self.tmp, ignore_errors=True)

	def test_reubicar_tras_insertar_texto(self):
		text = "primera línea\nsegunda línea importante\ntercera\n"
		off = text.index("segunda")
		bm = TextBookmark.at(text, off)
		self.assertEqual(relocate(bm, text), off)
		edited = "texto nuevo al principio\n" + text
		self.assertEqual(relocate(bm, edited), edited.index("segunda"))

	def test_poner_quitar_y_navegar(self):
		text = "uno\ndos\ntres\ncuatro\n"
		ctx = TextContext(None, text, 0, "notepad", "a.txt")
		store = BookmarkStore(self.path)
		self.assertTrue(store.toggle(ctx.key, text, text.index("dos"), ctx.lineBounds))
		self.assertTrue(store.toggle(ctx.key, text, text.index("cuatro"), ctx.lineBounds))
		# Otra vez en la misma línea: se quita.
		self.assertFalse(store.toggle(ctx.key, text, text.index("dos") + 1, ctx.lineBounds))
		self.assertTrue(store.toggle(ctx.key, text, text.index("dos"), ctx.lineBounds))
		pos, wrapped = store.neighbour(ctx.key, text, 0, 1, ctx.lineBounds)
		self.assertEqual((pos, wrapped), (text.index("dos"), False))
		pos, wrapped = store.neighbour(ctx.key, text, text.index("dos"), 1, ctx.lineBounds)
		self.assertEqual((pos, wrapped), (text.index("cuatro"), False))
		pos, wrapped = store.neighbour(ctx.key, text, text.index("cuatro"), 1, ctx.lineBounds)
		self.assertEqual((pos, wrapped), (text.index("dos"), True))
		pos, wrapped = store.neighbour(ctx.key, text, text.index("tres"), -1, ctx.lineBounds)
		self.assertEqual((pos, wrapped), (text.index("dos"), False))
		# Se guardan en disco y se recuperan.
		again = BookmarkStore(self.path)
		self.assertEqual(len(again.get(ctx.key)), 2)
		self.assertEqual(again.neighbour("otro|doc", text, 0, 1, ctx.lineBounds), (None, False))

	def test_titulos(self):
		self.assertEqual(normalizeTitle("*documento.txt - Bloc de notas"), "documento.txt - Bloc de notas")
		self.assertEqual(normalizeTitle("informe.docx ●"), "informe.docx")


if __name__ == "__main__":
	unittest.main()
