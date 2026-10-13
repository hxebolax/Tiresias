"""Tiresias termina aunque haya un diálogo modal abierto.

Con un diálogo modal abierto (el cuadro propio de Tiresias, uno nativo de
Windows o dos seguidos), ``gui.exitMainLoop`` (lo que hacen ``--exit-after``,
Salir del menú y ``--quit``) cierra los diálogos y el proceso termina. Cada
caso va en un proceso aparte (``exit_modal_probe.py``).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBE = os.path.join(ROOT, "tests", "exit_modal_probe.py")


class ExitWithModalTests(unittest.TestCase):
	def _run(self, kind: str) -> dict:
		out = subprocess.run([sys.executable, "-X", "utf8", PROBE, kind], capture_output=True, text=True, encoding="utf-8", timeout=60)
		self.assertEqual(out.returncode, 0, f"El proceso no terminó bien ({out.returncode}): {out.stdout}{out.stderr}")
		lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
		self.assertTrue(lines, out.stdout + out.stderr)
		return json.loads(lines[-1])

	def test_cuadro_de_tiresias(self):
		import wx

		r = self._run("tiresias")
		self.assertTrue(r["mainLoopEnded"])
		self.assertEqual(r["results"], [wx.ID_CANCEL])

	def test_cuadro_nativo(self):
		r = self._run("nativo")
		self.assertTrue(r["mainLoopEnded"])
		self.assertEqual(len(r["results"]), 1)

	def test_dialogos_encadenados(self):
		r = self._run("encadenado")
		self.assertTrue(r["mainLoopEnded"])
		self.assertEqual(len(r["results"]), 2)


if __name__ == "__main__":
	unittest.main()
