"""El complemento de Eloquence corrige las rutas absolutas de ECI.INI."""

import os
import re
import shutil
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DRIVER = os.path.join(ROOT, "data", "addons", "eloquence", "synthDrivers", "ibmtts.py")
#: Eloquence es propietario: no está en el repositorio público (se distribuye
#: aparte en la tienda). Sin él, estas pruebas se saltan.
HAS_ELOQUENCE = os.path.isfile(DRIVER)
NO_ELOQUENCE = "Falta el complemento Eloquence (data/addons/eloquence): no se incluye en el repositorio"

SAMPLE = (
	b"[2.0]\r\nPath=C:\\Users\\otro\\AppData\\Roaming\\nvda\\addons\\IBMTTS\\synthDrivers\\ibmtts\\esp.syn\r\n"
	b"Version=6.1\r\n[8.0]\r\nPath=D:\\viejo\\jpn.syn\r\nPath_Rom=D:\\viejo\\jpnrom.dll\r\n"
)


class _Log:
	def warning(self, *args) -> None:
		pass


def _loadFixer(libDir: str):
	code = open(DRIVER, encoding="utf8").read()
	ns = {"os": os, "re": re, "LIB_DIR": libDir, "log": _Log()}
	exec(code[code.index("def _fixIniPaths") : code.index("class SynthDriver")], ns)
	return ns["_fixIniPaths"]


@unittest.skipUnless(HAS_ELOQUENCE, NO_ELOQUENCE)
class EciIniTests(unittest.TestCase):
	def setUp(self) -> None:
		self.dir = tempfile.mkdtemp(prefix="Tirés ")
		with open(os.path.join(self.dir, "ECI.INI"), "wb") as f:
			f.write(SAMPLE)

	def tearDown(self) -> None:
		shutil.rmtree(self.dir, ignore_errors=True)

	def test_rutas_apuntan_a_la_carpeta_actual(self) -> None:
		_loadFixer(self.dir)()
		data = open(os.path.join(self.dir, "ECI.INI"), "rb").read()
		expected = (self.dir + "\\").encode("mbcs")
		paths = re.findall(rb"^Path(?:_Rom)?=(.*?)\r?$", data, flags=re.M)
		self.assertEqual(len(paths), 3)
		for p in paths:
			self.assertTrue(p.startswith(expected), p)
		self.assertIn(expected + b"esp.syn\r\n", data)
		self.assertIn(expected + b"jpnrom.dll\r\n", data)
		self.assertIn(b"Version=6.1\r\n", data)

	def test_idempotente(self) -> None:
		fix = _loadFixer(self.dir)
		fix()
		first = open(os.path.join(self.dir, "ECI.INI"), "rb").read()
		fix()
		self.assertEqual(first, open(os.path.join(self.dir, "ECI.INI"), "rb").read())


if __name__ == "__main__":
	unittest.main()
