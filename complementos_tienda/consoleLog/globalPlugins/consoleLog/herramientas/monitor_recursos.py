"""Monitor de recursos: disco, memoria y versión de Tiresias."""

from __future__ import annotations

import ctypes
import os
import shutil

from . import HerramientaBase, MetadatosHerramienta


class _MEMORYSTATUSEX(ctypes.Structure):
	_fields_ = [
		("dwLength", ctypes.c_ulong),
		("dwMemoryLoad", ctypes.c_ulong),
		("ullTotalPhys", ctypes.c_ulonglong),
		("ullAvailPhys", ctypes.c_ulonglong),
		("ullTotalPageFile", ctypes.c_ulonglong),
		("ullAvailPageFile", ctypes.c_ulonglong),
		("ullTotalVirtual", ctypes.c_ulonglong),
		("ullAvailVirtual", ctypes.c_ulonglong),
		("sullAvailExtendedVirtual", ctypes.c_ulonglong),
	]


def informe_recursos() -> list[str]:
	res = []
	try:
		unidad = os.environ.get("SystemDrive", "C:") + "\\"
		_total, _usado, libre = shutil.disk_usage(unidad)
		res.append("Espacio libre en disco ({}): {} GB".format(unidad.rstrip("\\"), libre // (2**30)))
	except OSError:
		pass
	try:
		estado = _MEMORYSTATUSEX()
		estado.dwLength = ctypes.sizeof(estado)
		if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(estado)):
			raise OSError
		res.append("Uso de memoria RAM: {}%".format(estado.dwMemoryLoad))
		res.append("RAM disponible: {} MB de {} MB".format(estado.ullAvailPhys // (1024 * 1024), estado.ullTotalPhys // (1024 * 1024)))
	except Exception:
		res.append("No se pudo obtener información detallada de la memoria.")
	try:
		import tiresias

		res.append("Versión de Tiresias: {}".format(tiresias.VERSION))
	except Exception:
		pass
	return res


class HerramientaMonitorRecursos(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Monitor de recursos",
		version="1.0.0",
		descripcion="Muestra información básica de recursos del sistema",
		autor="Héctor J. Benítez Corredera",
		categoria="utilidades",
	)

	def ejecutar(self, **kwargs):
		return informe_recursos()
