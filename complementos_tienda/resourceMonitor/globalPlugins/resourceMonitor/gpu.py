"""Información de la tarjeta gráfica (GPU).

Como el original, se obtiene de las GPU NVIDIA con la herramienta
``nvidia-smi`` que instala su controlador: uso, temperatura y memoria de
cada GPU. Se ejecuta sin abrir ventanas de consola y con tiempo límite.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass

from .info import ALTERNATIVE, number, size

#: Evita que aparezca (y se lea) una ventana de consola al ejecutar las herramientas.
CREATE_NO_WINDOW = 0x08000000


@dataclass
class GpuTelemetry:
	utilization: str
	temperature: str
	memoryUsed: str
	memoryTotal: str


class BaseGpuProvider:
	def collect(self) -> list[GpuTelemetry] | None:
		"""``None``: no hay GPU de este tipo; ``[]``: hay pero falló la lectura."""
		raise NotImplementedError


class NvidiaGpuProvider(BaseGpuProvider):
	def __init__(self) -> None:
		self._path: str | None = None
		self._resolved = False

	def findNvidiaSmi(self) -> str | None:
		candidates: list[str] = []
		for name in ("nvidia-smi", "nvidia-smi.exe"):
			found = shutil.which(name)
			if found:
				candidates.append(found)
		try:
			result = subprocess.run(
				["where.exe", "nvidia-smi"],
				capture_output=True,
				text=True,
				timeout=2,
				check=False,
				creationflags=CREATE_NO_WINDOW,
			)
			for line in result.stdout.splitlines():
				path = line.strip().strip('"')
				if path:
					candidates.append(path)
		except (OSError, subprocess.TimeoutExpired):
			pass
		windir = os.environ.get("WINDIR", r"C:\Windows")
		candidates.append(os.path.join(windir, "System32", "nvidia-smi.exe"))
		candidates.append(os.path.join(windir, "Sysnative", "nvidia-smi.exe"))
		for var in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
			base = os.environ.get(var)
			if base:
				candidates.append(os.path.join(base, "NVIDIA Corporation", "NVSMI", "nvidia-smi.exe"))
		seen: set[str] = set()
		for path in candidates:
			norm = os.path.normcase(os.path.abspath(path))
			if norm in seen:
				continue
			seen.add(norm)
			if os.path.isfile(path):
				return path
		return None

	def collect(self) -> list[GpuTelemetry] | None:
		if not self._resolved:
			self._path = self.findNvidiaSmi()
			self._resolved = True
		if not self._path:
			return None
		try:
			result = subprocess.run(
				[
					self._path,
					"--query-gpu=utilization.gpu,temperature.gpu,memory.used,memory.total",
					"--format=csv,noheader,nounits",
				],
				capture_output=True,
				text=True,
				timeout=5,
				check=True,
				creationflags=CREATE_NO_WINDOW,
			)
		except (subprocess.CalledProcessError, OSError, subprocess.TimeoutExpired):
			return []
		return parseNvidiaSmi(result.stdout)


def parseNvidiaSmi(output: str) -> list[GpuTelemetry]:
	"""Interpreta la salida CSV de ``nvidia-smi`` (una línea por GPU)."""
	items: list[GpuTelemetry] = []
	for line in output.splitlines():
		parts = [p.strip() for p in line.split(",")]
		if len(parts) < 4 or not parts[0]:
			continue
		items.append(GpuTelemetry(parts[0], parts[1], parts[2], parts[3]))
	return items


def getGpuProviders() -> list[BaseGpuProvider]:
	return [NvidiaGpuProvider()]


def formatTemperature(celsiusText: str, unit: str = "celsius") -> str:
	"""Temperatura en la unidad elegida (``celsius`` o ``fahrenheit``)."""
	try:
		celsius = float(celsiusText)
	except (TypeError, ValueError):
		return celsiusText
	if unit == "fahrenheit":
		return "{v} grados Fahrenheit".format(v=number(round(celsius * 9.0 / 5.0 + 32.0, 1)))
	return "{v} grados Celsius".format(v=number(round(celsius, 1)))


def formatMemory(usedMibText: str, totalMibText: str) -> str | None:
	"""«2,00 GB de 8,00 GB utilizados (25%)» a partir de MiB, o ``None``."""
	try:
		usedMib = float(usedMibText)
		totalMib = float(totalMibText)
	except (TypeError, ValueError):
		return None
	if totalMib <= 0:
		return None
	used = usedMib * 1024.0 * 1024.0
	total = totalMib * 1024.0 * 1024.0
	return "{used} de {total} utilizados ({pct}%)".format(
		used=size(used, ALTERNATIVE), total=size(total, ALTERNATIVE), pct=number(round(used / total * 100, 1))
	)


def getGpuInfo(providers: list[BaseGpuProvider], unit: str = "celsius") -> str:
	hasProvider = False
	hasFailure = False
	for provider in providers:
		telemetry = provider.collect()
		if telemetry is None:
			continue
		hasProvider = True
		if not telemetry:
			hasFailure = True
			continue
		parts = [
			"GPU {n}: uso {u}%, temperatura {t}.".format(n=i, u=item.utilization, t=formatTemperature(item.temperature, unit))
			for i, item in enumerate(telemetry, start=1)
		]
		if parts:
			return " ".join(parts)
		hasFailure = True
	if not hasProvider:
		return "No hay información de la GPU disponible."
	if hasFailure:
		return "No se pudo obtener la información de la GPU."
	return "No hay datos de la GPU."


def getGpuMemoryInfo(providers: list[BaseGpuProvider]) -> str:
	hasProvider = False
	hasFailure = False
	for provider in providers:
		telemetry = provider.collect()
		if telemetry is None:
			continue
		hasProvider = True
		if not telemetry:
			hasFailure = True
			continue
		parts = []
		for i, item in enumerate(telemetry, start=1):
			memory = formatMemory(item.memoryUsed, item.memoryTotal)
			if memory:
				parts.append("GPU {n}: {m}.".format(n=i, m=memory))
		if parts:
			return " ".join(parts)
		hasFailure = True
	if not hasProvider:
		return "No hay información de la GPU disponible."
	if hasFailure:
		return "No se pudo obtener la información de la memoria de la GPU."
	return "No hay datos de la GPU."
