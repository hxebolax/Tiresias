"""Historial de traducciones (las 500 más recientes, la primera la más nueva).

A diferencia del original (que lo perdía al cerrar NVDA), el historial se
guarda en ``historial.json`` en la carpeta de datos del complemento, así que
se conserva entre sesiones. «Guardar historial de traducciones» desactivado
hace que no se añada nada.
"""

from __future__ import annotations

import json
import os
import threading
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tiresias.log import getLogger

if TYPE_CHECKING:
	from .configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")


@dataclass
class EntradaHistorial:
	texto_original: str
	texto_traducido: str
	idioma_origen: str
	idioma_destino: str
	servicio: str
	fecha: str

	def a_diccionario(self) -> dict[str, str]:
		return {
			"texto_original": self.texto_original,
			"texto_traducido": self.texto_traducido,
			"idioma_origen": self.idioma_origen,
			"idioma_destino": self.idioma_destino,
			"servicio": self.servicio,
			"fecha": self.fecha,
		}


class GestorHistorial:
	CAPACIDAD_DEFECTO = 500

	def __init__(self, configuracion: "GestorConfiguracion", capacidad: int = CAPACIDAD_DEFECTO, persistente: bool = True) -> None:
		self.configuracion = configuracion
		self.capacidad = capacidad
		self.historial: deque[EntradaHistorial] = deque(maxlen=capacidad)
		self._indice_actual = 0
		self._bloqueo = threading.RLock()
		self._ruta = getattr(configuracion, "ruta_historial", None) if persistente else None
		self._cargar()

	# ------------------------------------------------------------ disco
	def _cargar(self) -> None:
		if not self._ruta:
			return
		try:
			with open(self._ruta, encoding="utf-8") as f:
				datos = json.load(f)
		except FileNotFoundError:
			return
		except (OSError, ValueError):
			log.exception("No se pudo leer el historial")
			return
		for d in datos if isinstance(datos, list) else []:
			if isinstance(d, dict) and d.get("texto_original"):
				self.historial.append(
					EntradaHistorial(
						str(d.get("texto_original", "")),
						str(d.get("texto_traducido", "")),
						str(d.get("idioma_origen", "auto")),
						str(d.get("idioma_destino", "")),
						str(d.get("servicio", "")),
						str(d.get("fecha", "")),
					)
				)

	def _guardar(self) -> None:
		if not self._ruta:
			return
		with self._bloqueo:
			datos = [e.a_diccionario() for e in self.historial]
			try:
				tmp = self._ruta + ".tmp"
				with open(tmp, "w", encoding="utf-8") as f:
					json.dump(datos, f, ensure_ascii=False, indent=1)
				os.replace(tmp, self._ruta)
			except OSError:
				log.exception("No se pudo guardar el historial")

	# ------------------------------------------------------------ uso
	def agregar(self, texto_original: str, texto_traducido: str, idioma_origen: str = "auto", idioma_destino: str = "es", servicio: str | None = None) -> bool:
		if not self.configuracion.historial_habilitado:
			return False
		if not texto_original or not texto_traducido:
			return False
		texto_original = texto_original.strip()
		with self._bloqueo:
			if self.historial and self.historial[0].texto_original == texto_original and self.historial[0].idioma_destino == idioma_destino:
				return False
			self.historial.appendleft(
				EntradaHistorial(
					texto_original,
					texto_traducido.strip(),
					idioma_origen,
					idioma_destino,
					servicio or self.configuracion.servicio_activo,
					datetime.now().isoformat(timespec="seconds"),
				)
			)
			self._indice_actual = 0
		self._guardar()
		return True

	def obtener_ultimo(self) -> EntradaHistorial | None:
		return self.historial[0] if self.historial else None

	def obtener_por_indice(self, indice: int) -> EntradaHistorial | None:
		with self._bloqueo:
			return self.historial[indice] if 0 <= indice < len(self.historial) else None

	def siguiente(self) -> EntradaHistorial | None:
		if self._indice_actual > 0:
			self._indice_actual -= 1
		return self.obtener_por_indice(self._indice_actual)

	def anterior(self) -> EntradaHistorial | None:
		if self._indice_actual < len(self.historial) - 1:
			self._indice_actual += 1
		return self.obtener_por_indice(self._indice_actual)

	def buscar(self, termino: str, en_original: bool = True, en_traducido: bool = True) -> list[EntradaHistorial]:
		t = termino.lower()
		return [e for e in list(self.historial) if (en_original and t in e.texto_original.lower()) or (en_traducido and t in e.texto_traducido.lower())]

	def listar_todos(self) -> list[EntradaHistorial]:
		with self._bloqueo:
			return list(self.historial)

	def listar_paginado(self, pagina: int = 0, por_pagina: int = 20) -> tuple[list[EntradaHistorial], int]:
		todos = self.listar_todos()
		total = (len(todos) + por_pagina - 1) // por_pagina
		return todos[pagina * por_pagina : (pagina + 1) * por_pagina], max(1, total)

	def eliminar(self, entrada: EntradaHistorial) -> bool:
		with self._bloqueo:
			try:
				self.historial.remove(entrada)
			except ValueError:
				return False
		self._guardar()
		return True

	def limpiar(self) -> None:
		with self._bloqueo:
			self.historial.clear()
			self._indice_actual = 0
		self._guardar()

	def esta_vacio(self) -> bool:
		return len(self.historial) == 0

	def obtener_tamano(self) -> int:
		return len(self.historial)

	def exportar(self) -> list[dict[str, Any]]:
		return [e.a_diccionario() for e in self.listar_todos()]
