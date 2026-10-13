"""Pruebas del complemento «Monitor de recursos» (complementos_tienda/resourceMonitor).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_complemento_resourcemonitor -v``
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))
ADDON = os.path.join(ROOT, "complementos_tienda", "resourceMonitor")
sys.path.insert(0, os.path.join(ADDON, "globalPlugins"))

from tiresias import paths  # noqa: E402

if not getattr(paths, "_dataDirForTests", None):
	_TMP = tempfile.mkdtemp(prefix="tiresias_resourcemonitor_")
	shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"))
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()
	paths._dataDirForTests = _TMP  # type: ignore[attr-defined]
else:
	_TMP = paths._dataDirForTests  # type: ignore[attr-defined]

from tiresias.baseobject import normalizeGestureId  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.input import core as inputCore  # noqa: E402

_oldBytecode = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # No deja __pycache__ en la carpeta del complemento.
import resourceMonitor as rm  # noqa: E402
from resourceMonitor import gpu, info, options, wlan  # noqa: E402

sys.dont_write_bytecode = _oldBytecode


class FakeGesture:
	isModifier = False

	def __init__(self, keys: str) -> None:
		gid = normalizeGestureId("kb:" + keys)
		self.identifiers = [gid.replace("kb:", "kb(desktop):", 1), gid]


def _power(ac=0, flag=1, pct=80, life=0xFFFFFFFF):
	s = info.SYSTEM_POWER_STATUS()
	s.ACLineStatus = ac
	s.BatteryFlag = flag
	s.BatteryLifePercent = pct
	s.BatteryLifeTime = life
	return s


# ====================================================================== manifiesto y archivos
class TestPaquete(unittest.TestCase):
	def test_manifiesto(self):
		with open(os.path.join(ADDON, "manifest.json"), encoding="utf-8-sig") as f:
			m = json.load(f)
		self.assertEqual(m["id"], "resourceMonitor")
		self.assertEqual(m["name"], "Monitor de recursos")
		self.assertEqual(m["version"], "1.0.0")
		self.assertEqual(m["url"], "https://github.com/kefaslungu/resourceMonitor")
		self.assertIn("Alex Hall, Joseph Lee, Kefas Lungu", m["author"])
		self.assertTrue(m["changelog"].startswith("Primera versión para Tiresias"))
		self.assertEqual((m["minApiVersion"], m["lastTestedApiVersion"]), ("1.0", "1.0"))

	def test_archivos(self):
		for rel in ("doc/es/readme.html", "globalPlugins/resourceMonitor/connect.wav", "globalPlugins/resourceMonitor/disconnect.wav"):
			self.assertTrue(os.path.isfile(os.path.join(ADDON, rel)), rel)

	def test_readme_documenta_todo(self):
		with open(os.path.join(ADDON, "doc", "es", "readme.html"), encoding="utf-8") as f:
			html = f.read()
		for text in ("Tiresias+Mayúsculas+0", "Tiresias+Mayúsculas+1", "Tiresias+Mayúsculas+7", "Mayúsculas+G", "Escape",
				"dos veces", "Unidad de temperatura de la GPU", "Aviso de conexión y desconexión de la wifi", "GPL", "Kefas Lungu", "nvidia-smi"):
			self.assertIn(text, html)

	def test_sin_modulos_ausentes_en_compilada(self):
		# La compilada no trae «datetime»: el complemento no debe importarlo.
		folder = os.path.join(ADDON, "globalPlugins", "resourceMonitor")
		for fn in os.listdir(folder):
			if fn.endswith(".py"):
				with open(os.path.join(folder, fn), encoding="utf-8") as f:
					src = f.read()
				self.assertNotRegex(src, r"^\s*(import datetime|from datetime)", fn)
				self.assertNotIn("winsound", src, fn)


# ====================================================================== formato de números
class TestFormato(unittest.TestCase):
	def test_number(self):
		self.assertEqual(info.number(5.0), "5")
		self.assertEqual(info.number(2.5), "2,5")
		self.assertEqual(info.number(18.7), "18,7")
		self.assertEqual(info.tryTrunk(3.0), 3)
		self.assertIsInstance(info.tryTrunk(3.0), int)

	def test_size(self):
		self.assertEqual(info.size(2 * 1024**3, info.ALTERNATIVE), "2,00 GB")
		self.assertEqual(info.size(1, info.ALTERNATIVE), "1,00 byte")
		self.assertEqual(info.size(0, info.ALTERNATIVE), "0,00 bytes")
		self.assertEqual(info.size(1536, info.TRADITIONAL), "1,50K")
		self.assertEqual(info.size(1024**4, info.VERBOSE), "1,00 terabyte")
		self.assertEqual(info.size(2 * 1024**2, info.VERBOSE), "2,00 megabytes")
		self.assertEqual(info.size(1024**2, info.IEC), "1,00Mi")
		self.assertEqual(info.size(1500, info.SI), "1,50K")

	def test_uptime(self):
		self.assertEqual(info.formatUptime(0), "0 días, 0 horas, 0 minutos, 0 segundos")
		self.assertEqual(info.formatUptime(86400 + 3600 + 60 + 1), "1 día, 1 hora, 1 minuto, 1 segundo")
		self.assertEqual(info.formatUptime(2 * 86400 + 5 * 3600 + 7 * 60 + 9), "2 días, 5 horas, 7 minutos, 9 segundos")

	def test_uptime_real_y_fallo(self):
		self.assertRegex(info.getUptime(), r"^\d+ días?, \d+ horas?, \d+ minutos?, \d+ segundos?$")
		with mock.patch.object(info.psutil, "boot_time", return_value=0.0):
			with self.assertRaises(ValueError):
				info.getUptime()


# ====================================================================== CPU, memoria y discos
class TestRecursos(unittest.TestCase):
	def setUp(self):
		info._lastTimes = None
		info._lastLoad = None

	def test_cpu_varios_nucleos(self):
		with mock.patch.object(info, "cpuLoad", return_value=(15.0, [10.0, 20.5])), \
				mock.patch.object(info.psutil, "cpu_count", return_value=2):
			self.assertEqual(info.getCpuInfo(), "Carga media de la CPU: 15%, núcleo 1: 10%, núcleo 2: 20,5%.")

	def test_cpu_un_nucleo(self):
		with mock.patch.object(info, "cpuLoad", return_value=(42.0, [42.0])), \
				mock.patch.object(info.psutil, "cpu_count", return_value=1):
			self.assertEqual(info.getCpuInfo(), "Carga de la CPU: 42%.")

	def test_calculo_de_carga(self):
		from collections import namedtuple

		T = namedtuple("T", "user system idle interrupt dpc")
		self.assertEqual(info.cpuPercent(T(0, 0, 0, 0, 0), T(30, 20, 50, 0, 0)), 50.0)
		self.assertEqual(info.cpuPercent(T(0, 0, 0, 0, 0), T(0, 0, 100, 0, 0)), 0.0)
		self.assertEqual(info.cpuPercent(T(1, 1, 1, 0, 0), T(1, 1, 1, 0, 0)), 0.0)

	def test_carga_independiente_del_hilo(self):
		# psutil guarda la medida anterior por hilo; el complemento la guarda él
		# mismo, así una consulta en un hilo nuevo mide desde la anterior.
		import threading
		from collections import namedtuple

		T = namedtuple("T", "user system idle interrupt dpc")
		seq = iter([T(0, 0, 0, 0, 0), [T(0, 0, 0, 0, 0)] * 2, T(25, 25, 50, 0, 0), [T(10, 0, 90, 0, 0), T(90, 0, 10, 0, 0)]])
		with mock.patch.object(info.psutil, "cpu_times", side_effect=lambda percpu=False: next(seq)):
			info.primeCpu()
			info._lastTimes = (info._lastTimes[0] - 1, info._lastTimes[1], info._lastTimes[2])
			out = []
			t = threading.Thread(target=lambda: out.append(info.cpuLoad()))
			t.start()
			t.join()
		self.assertEqual(out, [(50.0, [10.0, 90.0])])
		# Una segunda consulta inmediata repite la medida (no daría 0 %).
		with mock.patch.object(info.psutil, "cpu_times", side_effect=AssertionError("no se debe medir")):
			self.assertEqual(info.cpuLoad(), (50.0, [10.0, 90.0]))

	def test_carga_real(self):
		average, perCpu = info.cpuLoad()
		self.assertTrue(0 <= average <= 100)
		self.assertEqual(len(perCpu), info.psutil.cpu_count())

	def test_ram(self):
		vm = SimpleNamespace(used=4 * 1024**3, total=16 * 1024**3, percent=25.0)
		st = info.MEMORYSTATUSEX()
		st.ullTotalPageFile = 20 * 1024**3
		st.ullAvailPageFile = 15 * 1024**3
		with mock.patch.object(info.psutil, "virtual_memory", return_value=vm), mock.patch.object(info, "getMemoryStatus", return_value=st):
			self.assertEqual(
				info.getRamInfo(),
				"Física: 4,00 GB de 16,00 GB utilizados (25%). Virtual: 5,00 GB de 20,00 GB utilizados (25%).",
			)

	def test_ram_real(self):
		self.assertRegex(info.getRamInfo(), r"^Física: .+ GB de .+ GB utilizados \(.+%\)\. Virtual: .+ GB")

	def test_discos(self):
		parts = [
			SimpleNamespace(device="C:\\", mountpoint="C:\\", fstype="NTFS", opts="rw,fixed"),
			SimpleNamespace(device="D:\\", mountpoint="D:\\", fstype="", opts="cdrom"),
			SimpleNamespace(device="Z:\\", mountpoint="Z:\\", fstype="NTFS", opts="rw,remote"),
			SimpleNamespace(device="Y:\\", mountpoint="Y:\\", fstype="NTFS", opts="rw,remote"),
			SimpleNamespace(device="E:\\", mountpoint="E:\\", fstype="FAT32", opts="rw,removable"),
		]

		def usage(path):
			if path == "Y:\\":
				raise OSError("sin conexión")
			if path == "D:\\":
				raise AssertionError("no se debe consultar una unidad sin disco")
			return SimpleNamespace(total=100 * 1024**3, used=40 * 1024**3, percent=40.0)

		with mock.patch.object(info.psutil, "disk_partitions", return_value=parts) as dp, mock.patch.object(info.psutil, "disk_usage", side_effect=usage):
			text = info.getDriveInfo()
		dp.assert_called_once_with(all=True)
		self.assertEqual(
			text,
			"C: (unidad NTFS): 40,00 GB de 100,00 GB utilizados (40%). "
			"Z: (unidad de red): 40,00 GB de 100,00 GB utilizados (40%). "
			"Y: (unidad de red): no disponible. "
			"E: (unidad FAT32): 40,00 GB de 100,00 GB utilizados (40%).",
		)

	def test_discos_reales(self):
		self.assertIn("utilizados", info.getDriveInfo())

	def test_resumen_con_y_sin_bateria(self):
		vm = SimpleNamespace(percent=30.0)
		with mock.patch.object(info.psutil, "virtual_memory", return_value=vm), mock.patch.object(info, "cpuLoad", return_value=(12.5, [12.5])):
			with mock.patch.object(info, "getPowerStatus", return_value=_power(flag=128)):
				self.assertEqual(info.getSummary(), "30% de RAM utilizada, CPU al 12,5%.")
			with mock.patch.object(info, "getPowerStatus", return_value=_power(ac=0, flag=1, pct=70)):
				self.assertEqual(info.getSummary(), "30% de RAM utilizada, CPU al 12,5%. 70% de batería restante, tiempo restante desconocido.")


# ====================================================================== batería
class TestBateria(unittest.TestCase):
	def test_sin_bateria(self):
		self.assertEqual(info.getBatteryInfo(_power(flag=128)), "Este equipo no tiene ninguna batería conectada.")
		self.assertEqual(info.getBatteryInfo(_power(flag=255)), "Este equipo no tiene ninguna batería conectada.")

	def test_cargando(self):
		self.assertEqual(info.getBatteryInfo(_power(ac=1, flag=8, pct=55)), "55%, cargando la batería.")
		self.assertEqual(info.getBatteryInfo(_power(ac=1, flag=1, pct=100)), "100%, conectado a la corriente.")

	def test_tiempo_restante(self):
		self.assertEqual(info.getBatteryInfo(_power(pct=60, life=2 * 3600 + 5 * 60)), "60% de batería restante, aproximadamente 2 horas y 5 minutos.")
		self.assertEqual(info.getBatteryInfo(_power(pct=60, life=1 * 3600 + 60)), "60% de batería restante, aproximadamente 1 hora y 1 minuto.")
		self.assertEqual(info.getBatteryInfo(_power(pct=60, life=30 * 60)), "60% de batería restante, aproximadamente 30 minutos.")
		self.assertEqual(info.getBatteryInfo(_power(pct=60)), "60% de batería restante, tiempo restante desconocido.")

	def test_avisos(self):
		self.assertTrue(info.getBatteryInfo(_power(flag=2, pct=9)).endswith(" Advertencia: batería baja."))
		self.assertTrue(info.getBatteryInfo(_power(flag=4, pct=3)).endswith(" Advertencia: batería en nivel crítico."))

	def test_real(self):
		self.assertTrue(info.getBatteryInfo())


# ====================================================================== Windows
class TestWindows(unittest.TestCase):
	def test_nombres(self):
		self.assertEqual(info.releaseName(10, 0, 26100, "24H2"), "Windows 11 24H2")
		self.assertEqual(info.releaseName(10, 0, 19045, "22H2"), "Windows 10 22H2")
		self.assertEqual(info.releaseName(10, 0, 10240, ""), "Windows 10 1507")
		self.assertEqual(info.releaseName(10, 0, 99999, ""), "Windows 11 desconocida")
		self.assertEqual(info.releaseName(6, 1, 7601), "Windows 7")
		self.assertEqual(info.releaseName(6, 3, 9600), "Windows 8.1")
		self.assertEqual(info.releaseName(10, 0, 17763, "", isServer=True), "Windows Server 1809")
		self.assertEqual(info.releaseName(10, 0, 20348, "", isServer=True), "Windows Server 2022")

	def test_real(self):
		self.assertRegex(info.getWinVer(), r"^Windows .+ \((AMD64|ARM64|x86|ARM|IA64)\) compilación \d+\.\d+$")

	def test_arquitectura(self):
		self.assertIn(info.getArchitecture(), ("AMD64", "ARM64", "x86"))


# ====================================================================== GPU
class _Provider(gpu.BaseGpuProvider):
	def __init__(self, result):
		self.result = result

	def collect(self):
		return self.result


class TestGpu(unittest.TestCase):
	def test_parse(self):
		items = gpu.parseNvidiaSmi("45, 61, 2048, 8192\n\n3, 40, 100, 4096\nbasura\n")
		self.assertEqual(len(items), 2)
		self.assertEqual(items[0], gpu.GpuTelemetry("45", "61", "2048", "8192"))

	def test_temperatura(self):
		self.assertEqual(gpu.formatTemperature("50"), "50 grados Celsius")
		self.assertEqual(gpu.formatTemperature("50", "fahrenheit"), "122 grados Fahrenheit")
		self.assertEqual(gpu.formatTemperature("46", "fahrenheit"), "114,8 grados Fahrenheit")
		self.assertEqual(gpu.formatTemperature("[N/A]"), "[N/A]")

	def test_memoria(self):
		self.assertEqual(gpu.formatMemory("2048", "8192"), "2,00 GB de 8,00 GB utilizados (25%)")
		self.assertIsNone(gpu.formatMemory("x", "8192"))
		self.assertIsNone(gpu.formatMemory("1", "0"))

	def test_informes(self):
		ok = _Provider([gpu.GpuTelemetry("45", "61", "2048", "8192"), gpu.GpuTelemetry("3", "40", "1024", "4096")])
		self.assertEqual(gpu.getGpuInfo([ok]), "GPU 1: uso 45%, temperatura 61 grados Celsius. GPU 2: uso 3%, temperatura 40 grados Celsius.")
		self.assertEqual(gpu.getGpuMemoryInfo([ok]), "GPU 1: 2,00 GB de 8,00 GB utilizados (25%). GPU 2: 1,00 GB de 4,00 GB utilizados (25%).")
		self.assertEqual(gpu.getGpuInfo([_Provider(None)]), "No hay información de la GPU disponible.")
		self.assertEqual(gpu.getGpuInfo([_Provider([])]), "No se pudo obtener la información de la GPU.")
		self.assertEqual(gpu.getGpuMemoryInfo([_Provider(None)]), "No hay información de la GPU disponible.")
		self.assertEqual(gpu.getGpuMemoryInfo([_Provider([])]), "No se pudo obtener la información de la memoria de la GPU.")
		self.assertEqual(gpu.getGpuMemoryInfo([_Provider([gpu.GpuTelemetry("1", "2", "x", "y")])]), "No se pudo obtener la información de la memoria de la GPU.")

	def test_nvidia_sin_herramienta(self):
		p = gpu.NvidiaGpuProvider()
		with mock.patch.object(p, "findNvidiaSmi", return_value=None):
			self.assertIsNone(p.collect())

	def test_nvidia_falla(self):
		p = gpu.NvidiaGpuProvider()
		p._resolved, p._path = True, "C:\\no\\existe\\nvidia-smi.exe"
		self.assertEqual(p.collect(), [])


# ====================================================================== wifi
class TestWlan(unittest.TestCase):
	def _ssid(self, name: bytes) -> wlan.DOT11_SSID:
		s = wlan.DOT11_SSID()
		s.SSIDLength = len(name)
		for i, b in enumerate(name):
			s.SSID[i] = b
		return s

	def test_decode(self):
		self.assertEqual(wlan.decodeSSID(self._ssid("Casa Ñandú".encode())), "Casa Ñandú")
		s = self._ssid(b"x" * 32)
		s.SSIDLength = 99
		self.assertEqual(wlan.decodeSSID(s), "x" * 32)

	def test_texto_conectado(self):
		self.assertEqual(wlan.connectedText("Red", 80, wlan.DOT11_AUTH_ALGO_RSNA_PSK), "Conectado a Red, intensidad de la señal: 80%, tipo de seguridad: WPA2-PSK")
		self.assertTrue(wlan.connectedText("Red", 80, 0x80000001).endswith("desconocido"))
		self.assertIn("abierta", wlan.connectedText("Red", 1, wlan.DOT11_AUTH_ALGO_80211_OPEN))

	def _notification(self, code, ssid=b"", reason=0, source=wlan.WLAN_NOTIFICATION_SOURCE_ACM):
		data = wlan.WLAN_CONNECTION_NOTIFICATION_DATA()
		data.dot11Ssid = self._ssid(ssid)
		data.wlanReasonCode = reason
		self._keep = data
		n = wlan.WLAN_NOTIFICATION_DATA()
		n.NotificationSource = source
		n.NotificationCode = code
		n.pData = wlan.ctypes.addressof(data)
		return n

	def test_notificaciones(self):
		tr = wlan.WlanClient.translateNotification
		self.assertEqual(tr(self._notification(wlan.wlan_notification_acm_connection_complete, b"Casa")), (wlan.EVENT_CONNECTED, "Casa"))
		self.assertIsNone(tr(self._notification(wlan.wlan_notification_acm_connection_complete, b"Casa", reason=5)))
		self.assertEqual(tr(self._notification(wlan.wlan_notification_acm_disconnected, b"Casa")), (wlan.EVENT_DISCONNECTED, "Casa"))
		self.assertEqual(tr(self._notification(wlan.wlan_notification_acm_interface_arrival)), (wlan.EVENT_INTERFACE_ARRIVAL, ""))
		self.assertEqual(tr(self._notification(wlan.wlan_notification_acm_interface_removal)), (wlan.EVENT_INTERFACE_REMOVAL, ""))
		self.assertIsNone(tr(self._notification(wlan.wlan_notification_acm_interface_arrival, source=4)))
		self.assertIsNone(tr(self._notification(0x99)))

	def test_aviso_llega_por_la_retrollamada(self):
		got = []
		c = wlan.WlanClient(lambda k, s: got.append((k, s)))
		n = self._notification(wlan.wlan_notification_acm_disconnected, b"Bar")
		c._onNotification(wlan.ctypes.pointer(n), None)
		self.assertEqual(got, [(wlan.EVENT_DISCONNECTED, "Bar")])

	def test_sin_sesion(self):
		self.assertEqual(wlan.WlanClient().getInfo(), wlan.NO_DEVICES)

	@unittest.skipUnless(wlan.available, "este equipo no tiene wlanapi.dll")
	def test_sesion_real(self):
		c = wlan.WlanClient(lambda k, s: None)
		try:
			if not c.open():
				self.skipTest("el servicio WLAN no está en marcha")
			text = c.getInfo()
			self.assertTrue(text == wlan.NO_DEVICES or text == wlan.NO_CONNECTIONS or text.startswith("Conectado a "), text)
		finally:
			c.close()
		self.assertFalse(c.isOpen)


# ====================================================================== complemento global
class TestComplemento(unittest.TestCase):
	def setUp(self):
		with mock.patch.object(wlan.WlanClient, "open", return_value=False):
			self.plugin = rm.GlobalPlugin()
		self.plugin.runInThread = False

	def tearDown(self):
		self.plugin.terminate()

	def test_opciones_por_defecto(self):
		self.assertEqual(conf["resourceMonitor"]["gpuTempUnit"], "celsius")
		self.assertEqual(conf["resourceMonitor"]["wifiStatusNotification"], "both")
		conf["resourceMonitor"]["gpuTempUnit"] = "kelvin"
		try:
			self.assertEqual(options.get("gpuTempUnit"), "celsius")
		finally:
			conf["resourceMonitor"]["gpuTempUnit"] = "celsius"

	def test_panel_registrado(self):
		from tiresias.gui import settings as S

		self.assertIn(options.PANEL_ID, S._panels)
		title, cls = S._panels[options.PANEL_ID]
		self.assertEqual(title, "Monitor de recursos")
		self.assertTrue(issubclass(cls, S.ConfigPanel))
		fields = {f.key: f for f in cls.fields}
		self.assertEqual([v for v, _l in fields["gpuTempUnit"].choices], ["celsius", "fahrenheit"])
		self.assertEqual([v for v, _l in fields["wifiStatusNotification"].choices], ["off", "message", "sound", "both"])
		self.assertEqual([lbl for _v, lbl in fields["wifiStatusNotification"].choices], ["Desactivado", "Mensaje", "Sonido", "Mensaje y sonido"])
		self.plugin.terminate()
		self.assertNotIn(options.PANEL_ID, S._panels)

	def test_panel_real_guarda(self):
		import wx

		from tiresias.gui import settings as S

		app = wx.App.Get() or wx.App(False)  # noqa: F841
		frame = wx.Frame(None)
		try:
			panel = options.panelClass()(frame)
			unit = panel.getControl("gpuTempUnit")
			notify = panel.getControl("wifiStatusNotification")
			self.assertIsInstance(unit, wx.Choice)
			self.assertEqual(list(unit.GetStrings()), ["Celsius", "Fahrenheit"])
			self.assertEqual(notify.GetStringSelection(), "Mensaje y sonido")
			# Las etiquetas tienen tecla de acceso.
			labels = [c.GetLabel() for c in panel.GetChildren() if isinstance(c, wx.StaticText)]
			self.assertIn("Unidad de &temperatura de la GPU:", labels)
			self.assertIn("Aviso de conexión y desconexión de la &wifi:", labels)
			unit.SetSelection(1)
			notify.SetSelection(2)
			panel.onSave()
			self.assertEqual(conf["resourceMonitor"]["gpuTempUnit"], "fahrenheit")
			self.assertEqual(conf["resourceMonitor"]["wifiStatusNotification"], "sound")
			panel.resetToFactory()
			panel.onSave()
			self.assertEqual(conf["resourceMonitor"]["gpuTempUnit"], "celsius")
			self.assertEqual(conf["resourceMonitor"]["wifiStatusNotification"], "both")
			self.assertIn(options.PANEL_ID, S.getPanelIds())
		finally:
			conf["resourceMonitor"]["gpuTempUnit"] = "celsius"
			conf["resourceMonitor"]["wifiStatusNotification"] = "both"
			frame.Destroy()

	def test_gestos_directos(self):
		expected = {
			"kb:tiresias+shift+0": "layerEntry",
			"kb:tiresias+shift+1": "announceProcessorInfo",
			"kb:tiresias+shift+2": "announceRamInfo",
			"kb:tiresias+shift+5": "announceRamInfo",
			"kb:tiresias+shift+3": "announceDriveInfo",
			"kb:tiresias+shift+4": "wlanStatusReport",
			"kb:tiresias+shift+6": "announceWinVer",
			"kb:tiresias+shift+7": "announceUptime",
		}
		self.assertEqual(dict(rm.GlobalPlugin._classGestures), expected)

	def test_descripcion_y_categoria(self):
		names = [n for n in dir(rm.GlobalPlugin) if n.startswith("script_")]
		self.assertEqual(len(names), 12)
		for n in names:
			func = getattr(rm.GlobalPlugin, n)
			self.assertTrue(func.__doc__, n)
			self.assertEqual(func.category, "Monitor de recursos", n)
		for n in ("announceResourceSummary", "announceProcessorInfo", "announceRamInfo", "announceDriveInfo", "wlanStatusReport",
				"announceWinVer", "announceUptime", "announceGpuInfo", "announceGpuMemoryInfo", "announceBatteryInfo"):
			self.assertTrue(getattr(rm.GlobalPlugin, "script_" + n).speakOnDemand, n)

	def test_gestos_sin_conflictos(self):
		# Ningún gesto del complemento está ya en el núcleo ni en los complementos incluidos.
		mine = [normalizeGestureId(g) for g in rm.GlobalPlugin._classGestures]
		pattern = re.compile(r"kb(?:\([a-z]+\))?:[A-Za-z0-9+]+")
		used = set()
		for base in (os.path.join(ROOT, "src", "tiresias"), os.path.join(ROOT, "data", "addons")):
			for dirpath, _dirs, files in os.walk(base):
				for fn in files:
					if fn.endswith(".py"):
						with open(os.path.join(dirpath, fn), encoding="utf-8", errors="replace") as f:
							for m in pattern.findall(f.read()):
								used.add(normalizeGestureId(m.split(":", 1)[0].split("(")[0] + ":" + m.split(":", 1)[1]))
		for g in mine:
			self.assertNotIn(g, used, g)

	def test_capa(self):
		p = self.plugin
		self.assertIsNone(p.getScript(FakeGesture("c")))
		with mock.patch("tiresias.audio.tones.beep") as beep:
			p.script_layerEntry(None)
		beep.assert_called_once_with(100, 10)
		self.assertTrue(p.isLayerActive)
		expected = {"space": "announceResourceSummary", "c": "announceProcessorInfo", "m": "announceRamInfo", "d": "announceDriveInfo",
			"w": "wlanStatusReport", "o": "announceWinVer", "u": "announceUptime", "g": "announceGpuInfo", "shift+g": "announceGpuMemoryInfo",
			"b": "announceBatteryInfo", "escape": "layerExit"}
		for keys, name in expected.items():
			g = FakeGesture(keys)
			self.assertTrue(p._decideExecuteGesture(g))
			self.assertTrue(p.isLayerActive, keys)
			self.assertEqual(p.getScript(g).__name__, "script_" + name, keys)
		# La tecla de entrada no sale de la capa.
		p._decideExecuteGesture(FakeGesture("tiresias+shift+0"))
		self.assertTrue(p.isLayerActive)
		# Otra tecla sale de la capa y se deja pasar (el decisor no la bloquea).
		self.assertTrue(p._decideExecuteGesture(FakeGesture("x")))
		self.assertFalse(p.isLayerActive)
		self.assertIsNone(p.getScript(FakeGesture("c")))
		# Escape: sale con un pitido.
		with mock.patch("tiresias.audio.tones.beep"):
			p.script_layerEntry(None)
		with mock.patch("tiresias.audio.tones.beep") as beep:
			p.getScript(FakeGesture("escape"))(None)
		beep.assert_called_once_with(120, 100)
		self.assertFalse(p.isLayerActive)
		self.assertIsNone(p.getScript(FakeGesture("escape")))

	def test_decisor_registrado(self):
		self.assertIn(self.plugin._decideExecuteGesture, inputCore.decide_executeGesture.handlers())
		self.plugin.terminate()
		self.assertNotIn(self.plugin._decideExecuteGesture, inputCore.decide_executeGesture.handlers())

	def _run(self, scriptName: str, repeat: int = 0, secure: bool = False):
		with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=repeat), \
				mock.patch("tiresias.speech.api.speakMessage") as speak, \
				mock.patch("tiresias.api.copyToClip", return_value=True) as copy, \
				mock.patch.object(rm, "isSecureContext", return_value=secure):
			getattr(self.plugin, "script_" + scriptName)(None)
		return speak, copy

	def test_todas_las_ordenes_hablan_y_copian(self):
		fakeGpu = _Provider([gpu.GpuTelemetry("10", "50", "1024", "2048")])
		self.plugin._gpuProviders[:] = [fakeGpu]
		for name in ("announceResourceSummary", "announceProcessorInfo", "announceRamInfo", "announceDriveInfo", "wlanStatusReport",
				"announceWinVer", "announceUptime", "announceGpuInfo", "announceGpuMemoryInfo", "announceBatteryInfo"):
			speak, copy = self._run(name)
			speak.assert_called_once()
			copy.assert_not_called()
			text = speak.call_args[0][0]
			self.assertTrue(text, name)
			speak, copy = self._run(name, repeat=1)
			copy.assert_called_once()
			speak.assert_not_called()
			self.assertTrue(copy.call_args[0][0], name)
			if name not in ("announceResourceSummary", "announceProcessorInfo", "announceUptime", "announceRamInfo", "announceDriveInfo", "announceGpuInfo", "announceGpuMemoryInfo"):
				# Los datos estáticos se copian tal como se oyeron.
				self.assertEqual(copy.call_args[0][0], text, name)
			self.assertEqual(copy.call_args[1], {"notify": True})

	def test_textos_de_ordenes(self):
		self.plugin._gpuProviders[:] = [_Provider([gpu.GpuTelemetry("10", "50", "1024", "2048")])]
		self.assertEqual(self._run("announceGpuInfo")[0].call_args[0][0], "GPU 1: uso 10%, temperatura 50 grados Celsius.")
		conf["resourceMonitor"]["gpuTempUnit"] = "fahrenheit"
		try:
			self.assertEqual(self._run("announceGpuInfo")[0].call_args[0][0], "GPU 1: uso 10%, temperatura 122 grados Fahrenheit.")
		finally:
			conf["resourceMonitor"]["gpuTempUnit"] = "celsius"
		self.assertEqual(self._run("announceGpuMemoryInfo")[0].call_args[0][0], "GPU 1: 1,00 GB de 2,00 GB utilizados (50%).")
		self.assertEqual(self._run("wlanStatusReport")[0].call_args[0][0], wlan.NO_DEVICES)
		self.assertTrue(self._run("announceWinVer")[0].call_args[0][0].startswith("Windows "))

	def test_fallos(self):
		with mock.patch.object(info.psutil, "boot_time", return_value=0.0):
			speak, copy = self._run("announceUptime", repeat=1)
		copy.assert_not_called()
		self.assertEqual(speak.call_args[0][0], "No se pudo obtener el tiempo de actividad del sistema.")
		self.plugin._gpuProviders[:] = [mock.Mock(collect=mock.Mock(side_effect=RuntimeError("x")))]
		self.assertEqual(self._run("announceGpuInfo")[0].call_args[0][0], "Error al obtener la información de la GPU.")
		self.assertEqual(self._run("announceGpuMemoryInfo")[0].call_args[0][0], "Error al obtener la información de la memoria de la GPU.")

	def test_pantalla_segura_no_copia(self):
		speak, copy = self._run("announceRamInfo", repeat=1, secure=True)
		copy.assert_not_called()
		self.assertIn("pantalla segura", speak.call_args[0][0])

	def test_gpu_bloqueada_en_modo_seguro(self):
		provider = _Provider([gpu.GpuTelemetry("1", "2", "3", "4")])
		provider.collect = mock.Mock(return_value=[])
		self.plugin._gpuProviders[:] = [provider]
		with mock.patch.object(rm, "isSecureMode", return_value=True):
			for name in ("announceGpuInfo", "announceGpuMemoryInfo"):
				speak, _copy = self._run(name)
				self.assertEqual(speak.call_args[0][0], "Esta función no está disponible en modo seguro.")
		provider.collect.assert_not_called()

	def test_en_hilo(self):
		self.plugin.runInThread = True
		with mock.patch.object(inputCore, "getLastScriptRepeatCount", return_value=0), \
				mock.patch("tiresias.queue_handler.queueFunction") as queue:
			self.plugin.script_announceRamInfo(None)
			for _i in range(100):
				if queue.called:
					break
				import time

				time.sleep(0.02)
		queue.assert_called_once()
		func, text, repeat, ok = queue.call_args[0]
		self.assertEqual(func, self.plugin._present)
		self.assertTrue(text.startswith("Física:"))
		self.assertEqual((repeat, ok), (0, True))

	def test_avisos_wifi(self):
		cases = {
			"both": (True, True),
			"message": (True, False),
			"sound": (False, True),
			"off": (False, False),
		}
		for mode, (wantSpeech, wantSound) in cases.items():
			conf["resourceMonitor"]["wifiStatusNotification"] = mode
			try:
				with mock.patch("tiresias.speech.api.speakMessage") as speak, mock.patch("tiresias.audio.tones.playWaveFile") as play:
					self.plugin.notifyWifi(wlan.EVENT_CONNECTED, "Casa")
					self.plugin.notifyWifi(wlan.EVENT_DISCONNECTED, "Casa")
					self.plugin.notifyWifi(wlan.EVENT_INTERFACE_ARRIVAL)
					self.plugin.notifyWifi(wlan.EVENT_INTERFACE_REMOVAL)
			finally:
				conf["resourceMonitor"]["wifiStatusNotification"] = "both"
			if wantSpeech:
				self.assertEqual([c[0][0] for c in speak.call_args_list], [
					"Conectado a Casa", "Desconectado de Casa",
					"Se ha habilitado un dispositivo de red inalámbrica", "Se ha deshabilitado un dispositivo de red inalámbrica"], mode)
			else:
				speak.assert_not_called()
			if wantSound:
				self.assertEqual([os.path.basename(c[0][0]) for c in play.call_args_list], ["connect.wav", "disconnect.wav", "connect.wav", "disconnect.wav"], mode)
				self.assertTrue(all(os.path.isfile(c[0][0]) for c in play.call_args_list))
			else:
				play.assert_not_called()

	def test_aviso_wifi_pasa_por_la_cola(self):
		with mock.patch("tiresias.queue_handler.queueFunction") as queue:
			self.plugin._onWlanEvent(wlan.EVENT_CONNECTED, "Casa")
		queue.assert_called_once_with(self.plugin.notifyWifi, wlan.EVENT_CONNECTED, "Casa")
		self.plugin.terminate()
		with mock.patch("tiresias.speech.api.speakMessage") as speak, mock.patch("tiresias.audio.tones.playWaveFile") as play:
			self.plugin.notifyWifi(wlan.EVENT_CONNECTED, "Casa")
		speak.assert_not_called()
		play.assert_not_called()


if __name__ == "__main__":
	unittest.main()
