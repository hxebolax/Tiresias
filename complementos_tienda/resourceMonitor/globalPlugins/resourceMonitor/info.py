"""Obtención de la información de recursos del sistema (sin interfaz).

Todas las funciones devuelven el texto que se anuncia, en español. Se pueden
llamar desde cualquier hilo: el complemento global las ejecuta en un hilo
aparte para no bloquear el núcleo (los discos de red o la GPU pueden tardar).

Basado en Resource Monitor para NVDA (Alex Hall, Joseph Lee, Kefas Lungu,
Beqa Gozalishvili, Tuukka Ojala, Ethin Probst, Kevin Derome y otros; GPL).
"""

from __future__ import annotations

import ctypes
import functools
import threading
import time
import winreg
from ctypes import wintypes
from typing import Any

import psutil

# ====================================================================== números
#: Estilos de unidades de tamaño (como en el original). El complemento usa
#: ``ALTERNATIVE`` (KB, MB, GB...); los demás se conservan para quien los use.
TRADITIONAL = [
	(1024.0**10, "Q"),
	(1024.0**9, "R"),
	(1024.0**8, "Y"),
	(1024.0**7, "Z"),
	(1024.0**6, "E"),
	(1024.0**5, "P"),
	(1024.0**4, "T"),
	(1024.0**3, "G"),
	(1024.0**2, "M"),
	(1024.0**1, "K"),
	(1024.0**0, "B"),
]

ALTERNATIVE = [
	(1024.0**10, " QB"),
	(1024.0**9, " RB"),
	(1024.0**8, " YB"),
	(1024.0**7, " ZB"),
	(1024.0**6, " EB"),
	(1024.0**5, " PB"),
	(1024.0**4, " TB"),
	(1024.0**3, " GB"),
	(1024.0**2, " MB"),
	(1024.0**1, " KB"),
	(1024.0**0, (" byte", " bytes")),
]

VERBOSE = [
	(1024.0**10, (" quettabyte", " quettabytes")),
	(1024.0**9, (" ronnabyte", " ronnabytes")),
	(1024.0**8, (" yottabyte", " yottabytes")),
	(1024.0**7, (" zettabyte", " zettabytes")),
	(1024.0**6, (" exabyte", " exabytes")),
	(1024.0**5, (" petabyte", " petabytes")),
	(1024.0**4, (" terabyte", " terabytes")),
	(1024.0**3, (" gigabyte", " gigabytes")),
	(1024.0**2, (" megabyte", " megabytes")),
	(1024.0**1, (" kilobyte", " kilobytes")),
	(1024.0**0, (" byte", " bytes")),
]

IEC = [
	(1024.0**10, "Qi"),
	(1024.0**9, "Ri"),
	(1024.0**8, "Yi"),
	(1024.0**7, "Zi"),
	(1024.0**6, "Ei"),
	(1024.0**5, "Pi"),
	(1024.0**4, "Ti"),
	(1024.0**3, "Gi"),
	(1024.0**2, "Mi"),
	(1024.0**1, "Ki"),
	(1024.0**0, ""),
]

SI = [
	(1000.0**10, "Q"),
	(1000.0**9, "R"),
	(1000.0**8, "Y"),
	(1000.0**7, "Z"),
	(1000.0**6, "E"),
	(1000.0**5, "P"),
	(1000.0**4, "T"),
	(1000.0**3, "G"),
	(1000.0**2, "M"),
	(1000.0**1, "K"),
	(1000.0**0, "B"),
]


def number(n: float) -> str:
	"""Número sin decimales sobrantes y con coma decimal (5,0 → «5»; 2,5 → «2,5»)."""
	n = tryTrunk(n)
	return str(n).replace(".", ",")


def tryTrunk(n: float) -> int | float:
	"""Quita el «,0» de los números enteros (5.0 → 5); los demás no cambian."""
	try:
		if n == int(n):
			return int(n)
	except (OverflowError, ValueError):
		pass
	return n


def size(amount: float, system: list[tuple[float, Any]] = TRADITIONAL) -> str:
	"""Tamaño legible con dos decimales (``2,50 GB``)."""
	factor, suffix = system[-1]
	for factor, suffix in system:
		if amount >= factor:
			break
	value = amount / factor
	if isinstance(suffix, tuple):
		singular, multiple = suffix
		suffix = singular if value == 1.0 else multiple
	return f"{value:.2f}".replace(".", ",") + suffix


def plural(n: int, singular: str, multiple: str) -> str:
	return (singular if n == 1 else multiple).format(n=n)


def percentOf(used: float, total: float) -> str:
	return number(round(used / total * 100, 1)) if total else "0"


# ====================================================================== CPU y memoria
#: Tiempos de CPU de la consulta anterior: (instante, total, por procesador).
#: Se guardan aquí y no en psutil, que los guarda por hilo (cada consulta va en
#: un hilo nuevo y psutil daría siempre 0 %).
_lastTimes: tuple[float, Any, list[Any]] | None = None
#: Última carga calculada: (media, por procesador).
_lastLoad: tuple[float, list[float]] | None = None
_cpuLock = threading.Lock()
#: Por debajo de este intervalo no se puede medir bien: se repite la medida anterior.
MIN_CPU_INTERVAL = 0.25


def cpuPercent(t1: Any, t2: Any) -> float:
	"""Porcentaje de uso entre dos lecturas de ``psutil.cpu_times()`` (como psutil)."""
	deltas = [max(0.0, b - a) for a, b in zip(t1, t2)]
	total = sum(deltas)
	if total <= 0:
		return 0.0
	idle = max(0.0, t2.idle - t1.idle)
	busy = max(0.0, total - idle)
	return round(min(100.0, busy / total * 100), 1)


def _snapshot() -> tuple[float, Any, list[Any]]:
	return time.monotonic(), psutil.cpu_times(), list(psutil.cpu_times(percpu=True))


def primeCpu() -> None:
	"""Primera lectura de la CPU (la carga se mide desde la consulta anterior)."""
	global _lastTimes
	try:
		with _cpuLock:
			_lastTimes = _snapshot()
	except Exception:
		pass


def cpuLoad() -> tuple[float, list[float]]:
	"""Carga media y de cada procesador lógico desde la consulta anterior."""
	global _lastTimes, _lastLoad
	with _cpuLock:
		if _lastTimes is None:
			_lastTimes = _snapshot()
			time.sleep(MIN_CPU_INTERVAL)
		elif time.monotonic() - _lastTimes[0] < MIN_CPU_INTERVAL:
			if _lastLoad is not None:
				return _lastLoad[0], list(_lastLoad[1])
			time.sleep(MIN_CPU_INTERVAL)
		now = _snapshot()
		before = _lastTimes
		average = cpuPercent(before[1], now[1])
		perCpu = [cpuPercent(a, b) for a, b in zip(before[2], now[2])]
		_lastTimes = now
		_lastLoad = (average, perCpu)
		return average, list(perCpu)


def getSummary() -> str:
	"""RAM utilizada, carga media de la CPU y la batería si la hay."""
	info = "{ram}% de RAM utilizada, CPU al {cpu}%.".format(
		ram=number(psutil.virtual_memory().percent),
		cpu=number(cpuLoad()[0]),
	)
	status = getPowerStatus()
	if status is not None and hasBattery(status):
		info += " " + getBatteryInfo(status)
	return info


def getCpuInfo() -> str:
	"""Carga media del procesador y la de cada núcleo (procesador lógico)."""
	average, perCpu = cpuLoad()
	if (psutil.cpu_count() or 1) == 1:
		return "Carga de la CPU: {avg}%.".format(avg=number(average))
	cores = ", ".join(
		"núcleo {n}: {p}%".format(n=i, p=number(load)) for i, load in enumerate(perCpu, start=1)
	)
	return "Carga media de la CPU: {avg}%, {cores}.".format(avg=number(average), cores=cores)


class MEMORYSTATUSEX(ctypes.Structure):
	_fields_ = [
		("dwLength", wintypes.DWORD),
		("dwMemoryLoad", wintypes.DWORD),
		("ullTotalPhys", ctypes.c_ulonglong),
		("ullAvailPhys", ctypes.c_ulonglong),
		("ullTotalPageFile", ctypes.c_ulonglong),
		("ullAvailPageFile", ctypes.c_ulonglong),
		("ullTotalVirtual", ctypes.c_ulonglong),
		("ullAvailVirtual", ctypes.c_ulonglong),
		("ullAvailExtendedVirtual", ctypes.c_ulonglong),
	]


def getMemoryStatus() -> MEMORYSTATUSEX | None:
	status = MEMORYSTATUSEX()
	status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
	if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
		return status
	return None


def getRamInfo() -> str:
	"""Memoria física y virtual (memoria comprometida: RAM más archivo de paginación)."""
	memory = psutil.virtual_memory()
	used, total = memory.used, memory.total
	info = "Física: {used} de {total} utilizados ({pct}%).".format(
		used=size(used, ALTERNATIVE), total=size(total, ALTERNATIVE), pct=percentOf(used, total)
	)
	status = getMemoryStatus()
	if status is not None and status.ullTotalPageFile:
		vTotal = status.ullTotalPageFile
		vUsed = vTotal - status.ullAvailPageFile
		info += " Virtual: {used} de {total} utilizados ({pct}%).".format(
			used=size(vUsed, ALTERNATIVE), total=size(vTotal, ALTERNATIVE), pct=percentOf(vUsed, vTotal)
		)
	return info


# ====================================================================== discos
def _driveName(device: str) -> str:
	name = device.rstrip("\\/")
	return name or device


def getDriveInfo() -> str:
	"""Espacio usado y total de las unidades fijas, extraíbles y de red conectadas."""
	info: list[str] = []
	for drive in psutil.disk_partitions(all=True):
		# Solo las unidades preparadas (con sistema de archivos): así no se espera
		# a una disquetera o lector vacío, ni a una unidad de red nunca conectada.
		if not drive.fstype:
			continue
		isNetwork = "remote" in drive.opts.split(",")
		name = _driveName(drive.device)
		try:
			usage = psutil.disk_usage(drive.mountpoint)
		except OSError:
			# Unidad registrada pero inalcanzable (p. ej. unidad de red sin conexión).
			if isNetwork:
				info.append("{name} (unidad de red): no disponible.".format(name=name))
			continue
		driveType = "de red" if isNetwork else drive.fstype
		info.append(
			"{name} (unidad {kind}): {used} de {total} utilizados ({pct}%).".format(
				name=name,
				kind=driveType,
				used=size(usage.used, ALTERNATIVE),
				total=size(usage.total, ALTERNATIVE),
				pct=number(usage.percent),
			)
		)
	if not info:
		return "No hay unidades disponibles."
	return " ".join(info)


# ====================================================================== batería
AC_ONLINE = 1
BATTERY_FLAG_HIGH = 1
BATTERY_FLAG_LOW = 2
BATTERY_FLAG_CRITICAL = 4
BATTERY_FLAG_CHARGING = 8
BATTERY_FLAG_NO_BATTERY = 128
BATTERY_FLAG_UNKNOWN = 255
BATTERY_PERCENTAGE_UNKNOWN = 255
BATTERY_LIFE_TIME_UNKNOWN = 0xFFFFFFFF


class SYSTEM_POWER_STATUS(ctypes.Structure):
	_fields_ = [
		("ACLineStatus", ctypes.c_ubyte),
		("BatteryFlag", ctypes.c_ubyte),
		("BatteryLifePercent", ctypes.c_ubyte),
		("SystemStatusFlag", ctypes.c_ubyte),
		("BatteryLifeTime", wintypes.DWORD),
		("BatteryFullLifeTime", wintypes.DWORD),
	]


def getPowerStatus() -> SYSTEM_POWER_STATUS | None:
	status = SYSTEM_POWER_STATUS()
	try:
		if ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
			return status
	except Exception:
		pass
	return None


def hasBattery(status: SYSTEM_POWER_STATUS) -> bool:
	flag = status.BatteryFlag
	return flag != BATTERY_FLAG_UNKNOWN and not flag & BATTERY_FLAG_NO_BATTERY


def getBatteryInfo(status: SYSTEM_POWER_STATUS | None = None) -> str:
	"""Porcentaje, carga, tiempo restante y aviso de batería baja o crítica."""
	if status is None:
		status = getPowerStatus()
	if status is None or not hasBattery(status):
		return "Este equipo no tiene ninguna batería conectada."
	percent = status.BatteryLifePercent
	pct = "?" if percent == BATTERY_PERCENTAGE_UNKNOWN else str(percent)
	if status.ACLineStatus == AC_ONLINE or status.BatteryFlag & BATTERY_FLAG_CHARGING:
		if status.BatteryFlag & BATTERY_FLAG_CHARGING:
			info = "{p}%, cargando la batería.".format(p=pct)
		else:
			info = "{p}%, conectado a la corriente.".format(p=pct)
	elif status.BatteryLifeTime == BATTERY_LIFE_TIME_UNKNOWN:
		info = "{p}% de batería restante, tiempo restante desconocido.".format(p=pct)
	else:
		hours, minutes = divmod(status.BatteryLifeTime // 60, 60)
		parts = []
		if hours:
			parts.append(plural(hours, "{n} hora", "{n} horas"))
		parts.append(plural(minutes, "{n} minuto", "{n} minutos"))
		info = "{p}% de batería restante, aproximadamente {time}.".format(p=pct, time=" y ".join(parts))
	if status.BatteryFlag & BATTERY_FLAG_CRITICAL:
		info += " Advertencia: batería en nivel crítico."
	elif status.BatteryFlag & BATTERY_FLAG_LOW:
		info += " Advertencia: batería baja."
	return info


# ====================================================================== tiempo de actividad
def formatUptime(totalSeconds: float) -> str:
	"""«N días, N horas, N minutos, N segundos» (siempre las cuatro partes)."""
	days, rest = divmod(int(totalSeconds), 86400)
	hours, rest = divmod(rest, 3600)
	minutes, seconds = divmod(rest, 60)
	return ", ".join(
		(
			plural(days, "{n} día", "{n} días"),
			plural(hours, "{n} hora", "{n} horas"),
			plural(minutes, "{n} minuto", "{n} minutos"),
			plural(seconds, "{n} segundo", "{n} segundos"),
		)
	)


def getUptime() -> str:
	"""Tiempo desde el último arranque. Lanza ``ValueError`` si no se puede saber."""
	boot = psutil.boot_time()
	if not boot:
		raise ValueError("hora de arranque desconocida")
	elapsed = time.time() - boot
	if elapsed < 0:
		raise ValueError("hora de arranque en el futuro")
	return formatUptime(elapsed)


# ====================================================================== Windows
class RTL_OSVERSIONINFOEXW(ctypes.Structure):
	_fields_ = [
		("dwOSVersionInfoSize", wintypes.DWORD),
		("dwMajorVersion", wintypes.DWORD),
		("dwMinorVersion", wintypes.DWORD),
		("dwBuildNumber", wintypes.DWORD),
		("dwPlatformId", wintypes.DWORD),
		("szCSDVersion", wintypes.WCHAR * 128),
		("wServicePackMajor", wintypes.WORD),
		("wServicePackMinor", wintypes.WORD),
		("wSuiteMask", wintypes.WORD),
		("wProductType", wintypes.BYTE),
		("wReserved", wintypes.BYTE),
	]


VER_NT_WORKSTATION = 1

#: Nombres de las versiones de Windows 10/11 sin «DisplayVersion» fiable en el registro.
BUILDS_TO_RELEASE_NAMES = {
	10240: "Windows 10 1507",
	10586: "Windows 10 1511",
	14393: "Windows 10 1607",
	15063: "Windows 10 1703",
	16299: "Windows 10 1709",
	17134: "Windows 10 1803",
	17763: "Windows 10 1809",
	18362: "Windows 10 1903",
	18363: "Windows 10 1909",
	19041: "Windows 10 2004",
	19042: "Windows 10 20H2",
	19043: "Windows 10 21H1",
	19044: "Windows 10 21H2",
	19045: "Windows 10 22H2",
	20348: "Windows Server 2022",
	22000: "Windows 11 21H2",
	22621: "Windows 11 22H2",
	22631: "Windows 11 23H2",
	26100: "Windows 11 24H2",
	26200: "Windows 11 25H2",
}

#: IMAGE_FILE_MACHINE_* → arquitectura (como la anuncia el original).
MACHINES = {
	0x014C: "x86",
	0x8664: "AMD64",
	0xAA64: "ARM64",
	0x01C4: "ARM",
	0x0200: "IA64",
}
#: PROCESSOR_ARCHITECTURE_* (GetNativeSystemInfo) → arquitectura.
PROCESSOR_ARCHITECTURES = {0: "x86", 5: "ARM", 6: "IA64", 9: "AMD64", 12: "ARM64"}


def _rtlGetVersion() -> RTL_OSVERSIONINFOEXW | None:
	info = RTL_OSVERSIONINFOEXW()
	info.dwOSVersionInfoSize = ctypes.sizeof(info)
	try:
		if ctypes.windll.ntdll.RtlGetVersion(ctypes.byref(info)) == 0:
			return info
	except Exception:
		pass
	return None


def _currentVersionValues() -> dict[str, Any]:
	values: dict[str, Any] = {}
	try:
		with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", 0, winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
			for name in ("DisplayVersion", "ReleaseId", "UBR", "CurrentBuildNumber", "CurrentBuild", "ProductName", "InstallationType"):
				try:
					values[name] = winreg.QueryValueEx(key, name)[0]
				except OSError:
					pass
	except OSError:
		pass
	return values


def getArchitecture() -> str:
	"""Arquitectura real del equipo (AMD64, ARM64, x86), aunque el proceso sea emulado."""
	kernel32 = ctypes.windll.kernel32
	try:
		fn = kernel32.IsWow64Process2
		fn.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT)]
		fn.restype = wintypes.BOOL
		process = wintypes.USHORT()
		native = wintypes.USHORT()
		kernel32.GetCurrentProcess.restype = wintypes.HANDLE
		if fn(kernel32.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)):
			if native.value in MACHINES:
				return MACHINES[native.value]
	except (AttributeError, OSError):
		pass

	class SYSTEM_INFO(ctypes.Structure):
		_fields_ = [
			("wProcessorArchitecture", wintypes.WORD),
			("wReserved", wintypes.WORD),
			("dwPageSize", wintypes.DWORD),
			("lpMinimumApplicationAddress", ctypes.c_void_p),
			("lpMaximumApplicationAddress", ctypes.c_void_p),
			("dwActiveProcessorMask", ctypes.c_size_t),
			("dwNumberOfProcessors", wintypes.DWORD),
			("dwProcessorType", wintypes.DWORD),
			("dwAllocationGranularity", wintypes.DWORD),
			("wProcessorLevel", wintypes.WORD),
			("wProcessorRevision", wintypes.WORD),
		]

	si = SYSTEM_INFO()
	try:
		kernel32.GetNativeSystemInfo(ctypes.byref(si))
		return PROCESSOR_ARCHITECTURES.get(si.wProcessorArchitecture, "desconocida")
	except Exception:
		return "desconocida"


def releaseName(major: int, minor: int, build: int, displayVersion: str = "", isServer: bool = False) -> str:
	"""Nombre comercial de la versión de Windows («Windows 11 24H2»)."""
	if (major, minor) == (6, 1):
		name = "Windows 7"
	elif (major, minor) == (6, 2):
		name = "Windows 8"
	elif (major, minor) == (6, 3):
		name = "Windows 8.1"
	elif major == 10:
		base = "Windows 11" if build >= 22000 else "Windows 10"
		if displayVersion:
			name = f"{base} {displayVersion}"
		elif build in BUILDS_TO_RELEASE_NAMES:
			name = BUILDS_TO_RELEASE_NAMES[build]
		else:
			name = f"{base} desconocida"
	else:
		name = f"Windows {major}.{minor}"
	if isServer and not name.startswith("Windows Server"):
		# En los servidores se dice «Windows Server <versión>».
		name = "Windows Server " + name.rpartition(" ")[-1]
	return name


@functools.lru_cache(maxsize=1)
def getWinVer() -> str:
	"""«Windows 11 24H2 (AMD64) compilación 26100.1234» (no cambia hasta reiniciar)."""
	values = _currentVersionValues()
	ver = _rtlGetVersion()
	if ver is not None:
		major, minor, build = ver.dwMajorVersion, ver.dwMinorVersion, ver.dwBuildNumber
		isServer = ver.wProductType != VER_NT_WORKSTATION
	else:
		major, minor = 10, 0
		try:
			build = int(values.get("CurrentBuildNumber") or values.get("CurrentBuild") or 0)
		except ValueError:
			build = 0
		isServer = str(values.get("InstallationType", "")).lower() == "server"
	display = str(values.get("DisplayVersion") or values.get("ReleaseId") or "")
	# «ReleaseId» se quedó en 2009 desde 20H2: solo vale si no hay «DisplayVersion».
	name = releaseName(major, minor, build, display, isServer)
	product = str(values.get("ProductName") or "")
	if isServer and product.startswith("Windows Server "):
		# «Windows Server 2022 Datacenter» → «Windows Server 2022».
		name = " ".join(product.split()[:3])
	revision = values.get("UBR", 0)
	return "{name} ({arch}) compilación {build}.{rev}".format(name=name, arch=getArchitecture(), build=build, rev=revision)
