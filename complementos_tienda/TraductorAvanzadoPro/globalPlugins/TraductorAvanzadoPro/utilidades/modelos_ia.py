"""Listas de modelos de los servicios de IA (OpenAI, Gemini, DeepSeek y Claude).

Las listas se guardan una semana en la carpeta de datos del complemento
(``modelos_<servicio>.json``); «Actualizar lista» borra esa copia.
"""

from __future__ import annotations

import json
import os
import time
import urllib.parse
from typing import Any

from . import red

#: Una semana en segundos.
VIGENCIA_CACHE = 7 * 24 * 60 * 60

#: Servicios de IA que tienen modelo y prompts configurables.
SERVICIOS_IA = ("openai", "gemini", "deepseek", "claude")


class ErrorAPI(Exception):
	"""Fallo controlado al consultar una API."""

	def __init__(self, proveedor: str, mensaje: str, estado_http: int | None = None) -> None:
		super().__init__(mensaje)
		self.proveedor = proveedor
		self.mensaje = mensaje
		self.estado_http = estado_http


class ListadorModelosIA:
	def __init__(self, ruta_cache: str, timeout_segundos: int = 30) -> None:
		self.ruta_cache = ruta_cache
		self._timeout = timeout_segundos
		#: Último error (para mostrarlo en los diálogos).
		self.ultimo_error: str | None = None
		os.makedirs(self.ruta_cache, exist_ok=True)

	# ------------------------------------------------------------ caché
	def _ruta(self, proveedor: str) -> str:
		return os.path.join(self.ruta_cache, f"modelos_{proveedor}.json")

	def _obtener_cache(self, proveedor: str) -> list[str] | None:
		ruta = self._ruta(proveedor)
		try:
			if time.time() - os.path.getmtime(ruta) > VIGENCIA_CACHE:
				return None
			with open(ruta, encoding="utf-8") as f:
				datos = json.load(f)
			return [str(m) for m in datos] if isinstance(datos, list) and datos else None
		except (OSError, ValueError):
			return None

	def _guardar_cache(self, proveedor: str, modelos: list[str]) -> None:
		try:
			with open(self._ruta(proveedor), "w", encoding="utf-8") as f:
				json.dump(modelos, f, indent=2)
		except OSError:
			pass

	def borrar_cache(self, proveedor: str) -> None:
		try:
			os.remove(self._ruta(proveedor))
		except OSError:
			pass

	def _get(self, url: str, cabeceras: dict[str, str] | None = None) -> Any:
		heads = {"Accept": "application/json"}
		if cabeceras:
			heads.update(cabeceras)
		try:
			return red.peticion_json(url, cabeceras=heads, timeout=self._timeout)
		except red.ErrorRed as e:
			raise ErrorAPI("desconocido", f"Error al llamar {url.split('?')[0]}: {e.mensaje_api()}", e.codigo) from None

	# ------------------------------------------------------------ proveedores
	def obtener_modelos(self, proveedor: str, api_key: str) -> list[str]:
		funcion = {
			"openai": self.obtener_modelos_openai,
			"gemini": self.obtener_modelos_gemini,
			"deepseek": self.obtener_modelos_deepseek,
			"claude": self.obtener_modelos_claude,
		}.get(proveedor)
		return funcion(api_key) if funcion else []

	def _lista_data(self, proveedor: str, url: str, cabeceras: dict[str, str]) -> list[str]:
		cache = self._obtener_cache(proveedor)
		if cache:
			return cache
		self.ultimo_error = None
		try:
			datos = self._get(url, cabeceras)
		except ErrorAPI as e:
			self.ultimo_error = e.mensaje
			return []
		modelos = sorted(m["id"] for m in datos.get("data", []) if isinstance(m, dict) and "id" in m)
		if modelos:
			self._guardar_cache(proveedor, modelos)
		return modelos

	def obtener_modelos_openai(self, api_key: str) -> list[str]:
		return self._lista_data("openai", "https://api.openai.com/v1/models", {"Authorization": f"Bearer {api_key}"})

	def obtener_modelos_deepseek(self, api_key: str) -> list[str]:
		return self._lista_data("deepseek", "https://api.deepseek.com/models", {"Authorization": f"Bearer {api_key}"})

	def obtener_modelos_gemini(self, api_key: str) -> list[str]:
		cache = self._obtener_cache("gemini")
		if cache:
			return cache
		self.ultimo_error = None
		base = "https://generativelanguage.googleapis.com/v1beta/models"
		modelos: list[str] = []
		token = None
		try:
			while True:
				params = {"key": api_key, "pageSize": "1000"}
				if token:
					params["pageToken"] = token
				datos = self._get(f"{base}?{urllib.parse.urlencode(params)}")
				for m in datos.get("models", []):
					nombre = str(m.get("name", ""))
					modelos.append(nombre[7:] if nombre.startswith("models/") else nombre)
				token = datos.get("nextPageToken")
				if not token:
					break
		except ErrorAPI as e:
			self.ultimo_error = e.mensaje
			return []
		modelos.sort()
		if modelos:
			self._guardar_cache("gemini", modelos)
		return modelos

	def obtener_modelos_claude(self, api_key: str) -> list[str]:
		"""Modelos de Anthropic (``GET /v1/models``, paginado con ``after_id``)."""
		cache = self._obtener_cache("claude")
		if cache:
			return cache
		self.ultimo_error = None
		cabeceras = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
		modelos: list[str] = []
		despues = None
		try:
			while True:
				params = {"limit": "100"}
				if despues:
					params["after_id"] = despues
				datos = self._get(f"https://api.anthropic.com/v1/models?{urllib.parse.urlencode(params)}", cabeceras)
				for m in datos.get("data", []):
					if isinstance(m, dict) and m.get("id"):
						modelos.append(str(m["id"]))
				if not datos.get("has_more") or not datos.get("last_id"):
					break
				despues = datos["last_id"]
		except ErrorAPI as e:
			self.ultimo_error = e.mensaje
			return []
		modelos.sort()
		if modelos:
			self._guardar_cache("claude", modelos)
		return modelos
