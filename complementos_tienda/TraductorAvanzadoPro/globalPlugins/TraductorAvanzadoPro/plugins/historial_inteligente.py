"""Historial inteligente: exportar a JSON o CSV, estadísticas y búsqueda avanzada.

En el original este plugin no estaba conectado a ninguna parte; aquí lo usan
los botones del diálogo de historial (Exportar, Estadísticas, filtros).
"""

from __future__ import annotations

import csv
import json
import os
from datetime import datetime
from typing import Any, Callable

from tiresias.log import getLogger

from ..nucleo.gestor_plugins import PluginBase, TipoPlugin

log = getLogger("TraductorAvanzadoPro")


def carpeta_documentos() -> str:
	"""Carpeta «Documentos» del usuario (la real, aunque esté redirigida)."""
	try:
		import ctypes
		from ctypes import wintypes

		buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
		# CSIDL_PERSONAL = 5
		if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
			return buf.value
	except Exception:
		pass
	return os.path.join(os.path.expanduser("~"), "Documents")


class PluginHistorialInteligente(PluginBase):
	id = "historial_inteligente"
	nombre = "Historial Inteligente"
	descripcion = "Funciones avanzadas de historial: exportar, estadísticas y búsqueda"
	tipo = TipoPlugin.UTILIDAD
	version = "1.0.0"
	autor = "Traductor Avanzado Pro"

	def _inicializar(self) -> None:
		self._historial_ref: Any = None
		self._ruta_exportacion = carpeta_documentos()

	def establecer_historial(self, historial: Any) -> None:
		self._historial_ref = historial

	def ejecutar(self, accion: str = "", *args: Any, **kwargs: Any) -> Any:
		if accion == "exportar_json":
			return self.exportar_json(kwargs.get("ruta"))
		if accion == "exportar_csv":
			return self.exportar_csv(kwargs.get("ruta"))
		if accion == "estadisticas":
			return self.obtener_estadisticas()
		if accion == "buscar":
			return self.buscar_avanzado(kwargs.get("termino", ""), kwargs.get("filtros", {}))
		if accion == "resumen":
			return self.obtener_resumen_texto()
		log.warning("Acción no reconocida: %s", accion)
		return None

	def _ruta_por_defecto(self, extension: str) -> str:
		marca = datetime.now().strftime("%Y%m%d_%H%M%S")
		return os.path.join(self._ruta_exportacion, f"traducciones_{marca}.{extension}")

	def exportar_json(self, ruta: str | None = None, entradas: list | None = None) -> str | None:
		if not self._historial_ref:
			log.error("Historial no disponible")
			return None
		ruta = ruta or self._ruta_por_defecto("json")
		datos = [e.a_diccionario() for e in entradas] if entradas is not None else self._historial_ref.exportar()
		try:
			with open(ruta, "w", encoding="utf-8") as f:
				json.dump(datos, f, ensure_ascii=False, indent=2)
			return ruta
		except OSError:
			log.exception("Error exportando el historial a JSON")
			return None

	def exportar_csv(self, ruta: str | None = None, entradas: list | None = None) -> str | None:
		if not self._historial_ref:
			return None
		ruta = ruta or self._ruta_por_defecto("csv")
		datos = [e.a_diccionario() for e in entradas] if entradas is not None else self._historial_ref.exportar()
		try:
			# Con BOM para que Excel reconozca el UTF-8.
			with open(ruta, "w", encoding="utf-8-sig", newline="") as f:
				escritor = csv.writer(f, delimiter=";")
				escritor.writerow(["Texto Original", "Traducción", "Idioma Origen", "Idioma Destino", "Servicio", "Fecha"])
				for d in datos:
					escritor.writerow([d.get("texto_original", ""), d.get("texto_traducido", ""), d.get("idioma_origen", ""), d.get("idioma_destino", ""), d.get("servicio", ""), d.get("fecha", "")])
			return ruta
		except OSError:
			log.exception("Error exportando el historial a CSV")
			return None

	def obtener_estadisticas(self) -> dict[str, Any]:
		if not self._historial_ref:
			return {}
		entradas = self._historial_ref.listar_todos()
		if not entradas:
			return {"total": 0, "idiomas_destino": {}, "servicios": {}, "promedio_caracteres": 0}
		idiomas: dict[str, int] = {}
		servicios: dict[str, int] = {}
		for e in entradas:
			idiomas[e.idioma_destino] = idiomas.get(e.idioma_destino, 0) + 1
			servicios[e.servicio] = servicios.get(e.servicio, 0) + 1
		total_caracteres = sum(len(e.texto_original) for e in entradas)
		return {
			"total": len(entradas),
			"idiomas_destino": idiomas,
			"servicios": servicios,
			"promedio_caracteres": total_caracteres // len(entradas),
			"total_caracteres": total_caracteres,
			"idioma_mas_usado": max(idiomas, key=idiomas.get),
			"servicio_mas_usado": max(servicios, key=servicios.get),
		}

	def buscar_avanzado(self, termino: str, filtros: dict[str, Any] | None = None) -> list[Any]:
		if not self._historial_ref:
			return []
		filtros = filtros or {}
		t = (termino or "").lower()
		resultados = []
		for e in self._historial_ref.listar_todos():
			if t and t not in e.texto_original.lower() and t not in e.texto_traducido.lower():
				continue
			if filtros.get("idioma") and e.idioma_destino != filtros["idioma"]:
				continue
			if filtros.get("servicio") and e.servicio != filtros["servicio"]:
				continue
			resultados.append(e)
		return resultados

	def obtener_resumen_texto(self, nombre_idioma: Callable[[str], str] | None = None, nombre_servicio: Callable[[str], str] | None = None) -> str:
		stats = self.obtener_estadisticas()
		if not stats or stats.get("total", 0) == 0:
			return "No hay traducciones en el historial."
		ni = nombre_idioma or (lambda c: c)
		ns = nombre_servicio or (lambda s: s)
		lineas = [
			"=== Estadísticas del Historial ===",
			"",
			f"Total de traducciones: {stats['total']}",
			f"Caracteres traducidos: {stats['total_caracteres']}",
			f"Promedio de caracteres: {stats['promedio_caracteres']}",
			"",
			f"Idioma más traducido: {ni(stats['idioma_mas_usado'])}",
			f"Servicio más usado: {ns(stats['servicio_mas_usado'])}",
			"",
			"Idiomas utilizados:",
		]
		for idioma, cantidad in sorted(stats["idiomas_destino"].items(), key=lambda kv: -kv[1]):
			lineas.append(f"  - {ni(idioma)}: {cantidad}")
		lineas += ["", "Servicios utilizados:"]
		for servicio, cantidad in sorted(stats["servicios"].items(), key=lambda kv: -kv[1]):
			lineas.append(f"  - {ns(servicio)}: {cantidad}")
		return "\n".join(lineas)

	def obtener_comandos(self) -> dict[str, Callable]:
		return {
			"exportar_json": self.exportar_json,
			"exportar_csv": self.exportar_csv,
			"estadisticas": self.obtener_estadisticas,
			"buscar": self.buscar_avanzado,
			"resumen": self.obtener_resumen_texto,
		}
