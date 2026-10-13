"""Caché inteligente y persistente de traducciones.

Las traducciones se agrupan por contexto: ``<aplicación>_<idioma destino>``
(o ``global_<idioma>`` si no se sabe la aplicación). Así «Limpiar la caché de
la aplicación actual» borra solo lo de esa aplicación. Al buscar se mira
primero el contexto de la aplicación y después el global.

Cada contexto guarda como mucho :data:`GestorCache.TAMANO_MAXIMO_MEMORIA`
entradas; al llenarse se descarta el 20 % menos usado. Se guarda en disco
(``cache\\*.json`` en la carpeta de datos del complemento) al desactivar la
traducción, cada pocas traducciones y al cerrar Tiresias.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from tiresias.log import getLogger

if TYPE_CHECKING:
	from .configuracion import GestorConfiguracion

log = getLogger("TraductorAvanzadoPro")


@dataclass
class EntradaCache:
	texto_original: str
	texto_traducido: str
	idioma_origen: str
	idioma_destino: str
	servicio: str
	fecha_creacion: str
	veces_usado: int = 1


def contexto_para(app: str | None, idioma_destino: str) -> str:
	return f"{app}_{idioma_destino}" if app else f"global_{idioma_destino}"


def _nombre_archivo(contexto: str) -> str:
	limpio = re.sub(r"[^\w.\-]", "_", contexto)
	if limpio != contexto:
		limpio += "_" + hashlib.md5(contexto.encode("utf-8"), usedforsecurity=False).hexdigest()[:8]
	return limpio + ".json"


class GestorCache:
	TAMANO_MAXIMO_MEMORIA = 1000

	def __init__(self, configuracion: "GestorConfiguracion") -> None:
		self.configuracion = configuracion
		self.ruta_cache = configuracion.ruta_cache
		self.cache_memoria: dict[str, dict[str, EntradaCache]] = {}
		self.bloqueo = threading.RLock()
		self._modificado = False
		self._cargada = False
		os.makedirs(self.ruta_cache, exist_ok=True)

	@staticmethod
	def _generar_clave(texto: str) -> str:
		return hashlib.md5(texto.encode("utf-8", "surrogatepass"), usedforsecurity=False).hexdigest()

	# ------------------------------------------------------------ consulta
	def obtener(self, texto: str, idioma_destino: str, contexto: str | None = None, app: str | None = None) -> str | None:
		"""Traducción guardada de ``texto`` (``None`` si no hay o la caché está desactivada)."""
		if not self.configuracion.cache_habilitada or not texto:
			return None
		contextos = [contexto] if contexto else []
		if app:
			contextos.append(contexto_para(app, idioma_destino))
		contextos.append(contexto_para(None, idioma_destino))
		clave = self._generar_clave(texto)
		with self.bloqueo:
			for ctx in contextos:
				entrada = self.cache_memoria.get(ctx, {}).get(clave)
				if entrada is not None and entrada.texto_original == texto:
					entrada.veces_usado += 1
					self._modificado = True
					return entrada.texto_traducido
		return None

	def guardar(self, texto_original: str, texto_traducido: str, idioma_destino: str, idioma_origen: str = "auto", contexto: str | None = None, app: str | None = None, servicio: str | None = None) -> None:
		if not self.configuracion.cache_habilitada or not texto_original or not texto_traducido:
			return
		contexto = contexto or contexto_para(app, idioma_destino)
		with self.bloqueo:
			ctx = self.cache_memoria.setdefault(contexto, {})
			clave = self._generar_clave(texto_original)
			if clave not in ctx and len(ctx) >= self.TAMANO_MAXIMO_MEMORIA:
				self._limpiar_entradas_antiguas(contexto)
			ctx[clave] = EntradaCache(
				texto_original=texto_original,
				texto_traducido=texto_traducido,
				idioma_origen=idioma_origen,
				idioma_destino=idioma_destino,
				servicio=servicio or self.configuracion.servicio_activo,
				fecha_creacion=datetime.now().isoformat(timespec="seconds"),
			)
			self._modificado = True

	def agregar(self, *args: Any, **kwargs: Any) -> None:
		"""Alias de :meth:`guardar` con el orden del original (texto, resultado, destino)."""
		if len(args) >= 3:
			self.guardar(args[0], args[1], args[2], **kwargs)
		else:
			self.guardar(*args, **kwargs)

	def _limpiar_entradas_antiguas(self, contexto: str) -> None:
		ctx = self.cache_memoria.get(contexto) or {}
		if not ctx:
			return
		ordenadas = sorted(ctx.items(), key=lambda kv: (kv[1].veces_usado, kv[1].fecha_creacion))
		for clave, _entrada in ordenadas[: max(1, len(ordenadas) // 5)]:
			del ctx[clave]

	# ------------------------------------------------------------ disco
	def cargar(self) -> None:
		"""Carga la caché de disco (las entradas en memoria más recientes se conservan)."""
		with self.bloqueo:
			try:
				archivos = os.listdir(self.ruta_cache)
			except OSError:
				return
			for archivo in archivos:
				if not archivo.endswith(".json"):
					continue
				ruta = os.path.join(self.ruta_cache, archivo)
				try:
					with open(ruta, encoding="utf-8") as f:
						datos = json.load(f)
				except (OSError, ValueError):
					log.warning("No se pudo leer la caché %s", archivo, exc_info=True)
					continue
				if isinstance(datos, dict) and "entradas" in datos:
					contexto = str(datos.get("contexto") or archivo[:-5])
					entradas = datos.get("entradas") or {}
				else:
					contexto, entradas = archivo[:-5], datos if isinstance(datos, dict) else {}
				ctx = self.cache_memoria.setdefault(contexto, {})
				for clave, v in entradas.items():
					if clave in ctx or not isinstance(v, dict):
						continue
					ctx[clave] = EntradaCache(
						texto_original=str(v.get("texto_original", "")),
						texto_traducido=str(v.get("texto_traducido", "")),
						idioma_origen=str(v.get("idioma_origen", "auto")),
						idioma_destino=str(v.get("idioma_destino", "")),
						servicio=str(v.get("servicio", "")),
						fecha_creacion=str(v.get("fecha_creacion", "")),
						veces_usado=int(v.get("veces_usado", 1) or 1),
					)
			self._cargada = True
			log.debug("Caché cargada: %d contextos", len(self.cache_memoria))

	def guardar_todo(self) -> None:
		if not self._modificado:
			return
		with self.bloqueo:
			for contexto, ctx in self.cache_memoria.items():
				ruta = os.path.join(self.ruta_cache, _nombre_archivo(contexto))
				datos = {"contexto": contexto, "entradas": {k: asdict(e) for k, e in ctx.items()}}
				try:
					tmp = ruta + ".tmp"
					with open(tmp, "w", encoding="utf-8") as f:
						json.dump(datos, f, ensure_ascii=False, indent=1)
					os.replace(tmp, ruta)
				except OSError:
					log.exception("Error al guardar la caché %s", contexto)
			self._modificado = False

	def limpiar(self, contexto: str | None = None) -> None:
		"""Borra un contexto o, sin argumento, toda la caché (memoria y disco)."""
		with self.bloqueo:
			if contexto:
				self.cache_memoria.pop(contexto, None)
				try:
					os.remove(os.path.join(self.ruta_cache, _nombre_archivo(contexto)))
				except OSError:
					pass
			else:
				self.cache_memoria.clear()
				try:
					for archivo in os.listdir(self.ruta_cache):
						if archivo.endswith((".json", ".tmp")):
							try:
								os.remove(os.path.join(self.ruta_cache, archivo))
							except OSError:
								pass
				except OSError:
					pass
				self._modificado = False

	def limpiar_aplicacion(self, app: str) -> int:
		"""Borra todos los contextos de ``app`` (cualquier idioma). Devuelve cuántos."""
		prefijo = f"{app}_"
		if not self._cargada:
			# Para encontrar también lo que solo está en disco.
			self.cargar()
		with self.bloqueo:
			contextos = [c for c in self.cache_memoria if c.startswith(prefijo)]
		for c in contextos:
			self.limpiar(c)
		return len(contextos)

	def obtener_estadisticas(self) -> dict[str, Any]:
		with self.bloqueo:
			return {
				"total_entradas": sum(len(c) for c in self.cache_memoria.values()),
				"total_contextos": len(self.cache_memoria),
				"contextos": sorted(self.cache_memoria),
				"tamano_maximo": self.TAMANO_MAXIMO_MEMORIA,
			}
