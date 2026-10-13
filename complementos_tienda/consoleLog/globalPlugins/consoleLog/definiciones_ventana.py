"""Definiciones de ventana: regiones del texto de la consola con modo de lectura propio.

Sirven para separar paneles de tmux o screen, silenciar la barra de estado o
vigilar una región de htop o vim. Coordenadas en base 1 e inclusivas.

- ``anunciar``: la región se lee con normalidad.
- ``silencio``: sus líneas se quitan del texto del visor.
- ``monitorizar``: se vigilan sus cambios y se anuncian durante el
  seguimiento.

Las definiciones se guardan en ``data\\addonsData\\consoleLog\\definiciones_ventana.json``.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass

from tiresias.log import getLogger

log = getLogger("consoleLog")

MODO_ANUNCIAR = "anunciar"
MODO_SILENCIO = "silencio"
MODO_MONITORIZAR = "monitorizar"
MODOS_VALIDOS = (MODO_ANUNCIAR, MODO_SILENCIO, MODO_MONITORIZAR)
NOMBRES_MODOS = {
	MODO_ANUNCIAR: "Anunciar",
	MODO_SILENCIO: "Silencio",
	MODO_MONITORIZAR: "Monitorizar cambios",
}
ARCHIVO = "definiciones_ventana.json"


@dataclass
class DefinicionVentana:
	nombre: str
	fila_superior: int
	fila_inferior: int
	columna_izquierda: int
	columna_derecha: int
	modo: str = MODO_ANUNCIAR
	habilitada: bool = True
	descripcion: str = ""
	color_resaltado: str | None = None

	def __post_init__(self) -> None:
		if self.modo not in MODOS_VALIDOS:
			self.modo = MODO_ANUNCIAR
		self.fila_superior = max(1, int(self.fila_superior))
		self.columna_izquierda = max(1, int(self.columna_izquierda))
		self.fila_inferior = max(self.fila_superior, int(self.fila_inferior))
		self.columna_derecha = max(self.columna_izquierda, int(self.columna_derecha))

	def contiene(self, fila: int, columna: int) -> bool:
		return self.habilitada and self.fila_superior <= fila <= self.fila_inferior and self.columna_izquierda <= columna <= self.columna_derecha

	def contiene_linea(self, fila: int) -> bool:
		return self.habilitada and self.fila_superior <= fila <= self.fila_inferior

	def obtener_dimensiones(self) -> tuple[int, int]:
		return (self.fila_inferior - self.fila_superior + 1, self.columna_derecha - self.columna_izquierda + 1)

	def extraer_texto(self, texto_completo: str) -> str:
		if not texto_completo or not self.habilitada:
			return ""
		resultado = []
		for i, linea in enumerate(texto_completo.splitlines()):
			fila = i + 1
			if self.fila_superior <= fila <= self.fila_inferior:
				resultado.append(linea[self.columna_izquierda - 1:self.columna_derecha])
			elif fila > self.fila_inferior:
				break
		return "\n".join(resultado)

	def to_dict(self) -> dict:
		return asdict(self)

	@classmethod
	def from_dict(cls, datos: dict) -> "DefinicionVentana":
		return cls(
			nombre=str(datos.get("nombre", "")),
			fila_superior=int(datos.get("fila_superior", 1)),
			fila_inferior=int(datos.get("fila_inferior", 1)),
			columna_izquierda=int(datos.get("columna_izquierda", 1)),
			columna_derecha=int(datos.get("columna_derecha", 80)),
			modo=str(datos.get("modo", MODO_ANUNCIAR)),
			habilitada=bool(datos.get("habilitada", True)),
			descripcion=str(datos.get("descripcion", "")),
			color_resaltado=datos.get("color_resaltado"),
		)

	def obtener_descripcion(self) -> str:
		filas, columnas = self.obtener_dimensiones()
		return "{nombre}: filas {fs}-{fi}, columnas {ci}-{cd} ({f}×{c}), modo: {modo}, {estado}".format(
			nombre=self.nombre,
			fs=self.fila_superior,
			fi=self.fila_inferior,
			ci=self.columna_izquierda,
			cd=self.columna_derecha,
			f=filas,
			c=columnas,
			modo=NOMBRES_MODOS.get(self.modo, self.modo),
			estado="activa" if self.habilitada else "deshabilitada",
		)


def clave_desde_nombre(nombre: str) -> str:
	return "".join(c if c.isalnum() else "_" for c in (nombre or "").strip().lower()) or "region"


class GestorDefinicionesVentana:
	"""Crea, guarda y aplica las definiciones de ventana."""

	def __init__(self, ruta: str | None = None) -> None:
		self._definiciones: dict[str, DefinicionVentana] = {}
		self._contenido_anterior: dict[str, str] = {}
		self._cerrojo = threading.RLock()
		self._ruta = ruta
		self._inicializar_predefinidas()
		if ruta:
			self.cargar_definiciones(ruta)

	def _inicializar_predefinidas(self) -> None:
		self._definiciones["barra_estado"] = DefinicionVentana(
			"Barra de estado", 24, 24, 1, 80, MODO_SILENCIO, False, "Última línea de la consola (típica barra de estado)"
		)
		self._definiciones["panel_tmux"] = DefinicionVentana(
			"Panel principal (tmux)", 1, 23, 1, 120, MODO_ANUNCIAR, False, "Área principal del terminal (excluyendo barra de estado)"
		)
		self._definiciones["panel_izquierdo"] = DefinicionVentana(
			"Panel izquierdo", 1, 24, 1, 40, MODO_ANUNCIAR, False, "Mitad izquierda de la consola"
		)
		self._definiciones["panel_derecho"] = DefinicionVentana(
			"Panel derecho", 1, 24, 41, 80, MODO_ANUNCIAR, False, "Mitad derecha de la consola"
		)

	@property
	def ruta(self) -> str | None:
		return self._ruta

	def agregar_definicion(self, clave: str, definicion: DefinicionVentana) -> None:
		with self._cerrojo:
			self._definiciones[clave] = definicion
			self._contenido_anterior.pop(clave, None)

	def eliminar_definicion(self, clave: str) -> bool:
		with self._cerrojo:
			if clave in self._definiciones:
				del self._definiciones[clave]
				self._contenido_anterior.pop(clave, None)
				return True
			return False

	def obtener_definicion(self, clave: str) -> DefinicionVentana | None:
		with self._cerrojo:
			return self._definiciones.get(clave)

	def listar_definiciones(self) -> list[str]:
		with self._cerrojo:
			return list(self._definiciones.keys())

	def obtener_definiciones_activas(self) -> list[DefinicionVentana]:
		with self._cerrojo:
			return [d for d in self._definiciones.values() if d.habilitada]

	def habilitar_definicion(self, clave: str, habilitar: bool = True) -> None:
		with self._cerrojo:
			if clave in self._definiciones:
				self._definiciones[clave].habilitada = bool(habilitar)

	def aplicar_filtros(self, texto: str) -> str:
		"""Quita las líneas de las regiones en modo silencio."""
		activas = self.obtener_definiciones_activas()
		if not activas or not texto:
			return texto
		silenciadas: set[int] = set()
		for d in activas:
			if d.modo == MODO_SILENCIO:
				silenciadas.update(range(d.fila_superior, d.fila_inferior + 1))
		if not silenciadas:
			return texto
		return "\n".join(linea for i, linea in enumerate(texto.splitlines()) if i + 1 not in silenciadas)

	def extraer_region(self, texto: str, clave: str) -> str:
		d = self.obtener_definicion(clave)
		return d.extraer_texto(texto) if d else ""

	def detectar_cambios(self, texto: str) -> dict[str, str]:
		"""Regiones monitorizadas cuyo contenido ha cambiado: ``{clave: texto nuevo}``."""
		cambios: dict[str, str] = {}
		with self._cerrojo:
			for clave, d in self._definiciones.items():
				if not d.habilitada or d.modo != MODO_MONITORIZAR:
					continue
				actual = d.extraer_texto(texto)
				if actual != self._contenido_anterior.get(clave, ""):
					cambios[clave] = actual
					self._contenido_anterior[clave] = actual
		return cambios

	def hay_monitorizadas(self) -> bool:
		return any(d.modo == MODO_MONITORIZAR for d in self.obtener_definiciones_activas())

	def obtener_ventana_en_posicion(self, fila: int, columna: int) -> DefinicionVentana | None:
		with self._cerrojo:
			for d in self._definiciones.values():
				if d.contiene(fila, columna):
					return d
		return None

	def guardar_definiciones(self, ruta: str | None = None) -> bool:
		ruta = ruta or self._ruta
		if not ruta:
			return False
		try:
			with self._cerrojo:
				datos = {clave: d.to_dict() for clave, d in self._definiciones.items()}
			os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
			tmp = ruta + ".tmp"
			with open(tmp, "w", encoding="utf-8") as f:
				json.dump(datos, f, indent="\t", ensure_ascii=False)
			os.replace(tmp, ruta)
			return True
		except OSError:
			log.exception("consoleLog: no se pudieron guardar las definiciones de ventana")
			return False

	def cargar_definiciones(self, ruta: str | None = None) -> None:
		ruta = ruta or self._ruta
		if not ruta or not os.path.isfile(ruta):
			return
		try:
			with open(ruta, encoding="utf-8-sig") as f:
				datos = json.load(f)
			if not isinstance(datos, dict):
				return
			with self._cerrojo:
				for clave, d in datos.items():
					if isinstance(d, dict):
						self._definiciones[str(clave)] = DefinicionVentana.from_dict(d)
		except (OSError, ValueError, TypeError):
			log.warning("consoleLog: definiciones de ventana no válidas en %s", ruta, exc_info=True)

	def crear_definicion_interactiva(
		self,
		nombre: str,
		fila_superior: int,
		fila_inferior: int,
		columna_izquierda: int,
		columna_derecha: int,
		modo: str = MODO_ANUNCIAR,
		descripcion: str = "",
	) -> DefinicionVentana:
		clave = clave_desde_nombre(nombre)
		d = DefinicionVentana(nombre, fila_superior, fila_inferior, columna_izquierda, columna_derecha, modo, True, descripcion)
		self.agregar_definicion(clave, d)
		return d

	def obtener_resumen(self) -> str:
		with self._cerrojo:
			items = list(self._definiciones.items())
		if not items:
			return "No hay definiciones de ventana configuradas."
		partes = [
			"=== Definiciones de ventana ===",
			"Total: {}".format(len(items)),
			"Activas: {}".format(sum(1 for _c, d in items if d.habilitada)),
			"",
		]
		partes += ["[{}] {}".format(clave, d.obtener_descripcion()) for clave, d in items]
		return "\n".join(partes)
