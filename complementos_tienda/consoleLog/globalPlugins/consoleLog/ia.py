"""Inteligencia artificial del chat y de los informes.

Dos formas de trabajar (opción «Proveedor de IA»):

- ``google``: como el complemento original, Google AI Studio (Gemini y Gemma)
  con **varias claves** propias del complemento. Si una clave falla por
  autenticación o cuota (401, 403, 429) se prueba la siguiente. La lista de
  modelos se pide a la API y se guarda un día en caché. Las claves se guardan
  cifradas con DPAPI (ligadas a la cuenta de Windows) en
  ``data\\addonsData\\consoleLog\\claves_google.json`` y viajan en la
  cabecera ``x-goog-api-key``, nunca en la dirección.
- ``tiresias``, ``anthropic``, ``openai``, ``gemini`` o ``local``: los
  proveedores de IA de Tiresias, con la clave y el modelo de *Opciones,
  Inteligencia artificial*.

Las peticiones son síncronas y deben hacerse siempre en un hilo de trabajo.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

from tiresias.log import getLogger

from . import configuracion

log = getLogger("consoleLog")

URL_GOOGLE = "https://generativelanguage.googleapis.com/v1beta"
MODELOS_RESERVA = ["gemini-3.6-flash", "gemini-3.5-flash", "gemini-3.5-flash-lite"]
CACHE_MODELOS = "google_ai_models.json"
ARCHIVO_CLAVES = "claves_google.json"
DURACION_CACHE = 86400
TIEMPO_ESPERA = 60


class ErrorIA(Exception):
	pass


@dataclass
class Turno:
	"""Un turno de la conversación: ``rol`` es ``user`` o ``model``."""

	rol: str
	texto: str


# ====================================================================== claves de Google
def _rutaClaves() -> str:
	return configuracion.rutaDatos(ARCHIVO_CLAVES)


def guardar_claves(claves: list[str], ruta: str | None = None) -> None:
	"""Guarda las claves de Google AI cifradas con DPAPI (lista vacía = borrarlas)."""
	from tiresias.ai import keys

	ruta = ruta or _rutaClaves()
	limpias = [c.strip() for c in claves if c and c.strip()]
	if not limpias:
		try:
			os.remove(ruta)
		except FileNotFoundError:
			pass
		return
	cifrado = base64.b64encode(keys.protect("\n".join(limpias).encode("utf-8"))).decode("ascii")
	os.makedirs(os.path.dirname(ruta) or ".", exist_ok=True)
	tmp = ruta + ".tmp"
	with open(tmp, "w", encoding="utf-8") as f:
		json.dump({"version": 1, "claves": cifrado}, f)
	os.replace(tmp, ruta)


def cargar_claves(ruta: str | None = None) -> list[str]:
	from tiresias.ai import keys

	ruta = ruta or _rutaClaves()
	try:
		with open(ruta, encoding="utf-8") as f:
			datos = json.load(f)
		texto = keys.unprotect(base64.b64decode(datos.get("claves", ""))).decode("utf-8")
	except FileNotFoundError:
		return []
	except (OSError, ValueError, TypeError, AttributeError):
		log.warning("consoleLog: no se pudieron descifrar las claves de Google AI (¿otra cuenta u otro equipo?)")
		return []
	return [c.strip() for c in texto.splitlines() if c.strip()]


def separar_claves(texto: str) -> list[str]:
	return [c.strip() for c in (texto or "").splitlines() if c.strip()]


# ====================================================================== Google AI propio
def _peticion(url: str, clave: str, cuerpo: dict | None = None, timeout: int = TIEMPO_ESPERA) -> dict:
	datos = json.dumps(cuerpo).encode("utf-8") if cuerpo is not None else None
	req = urllib.request.Request(url, data=datos, method="POST" if cuerpo is not None else "GET")
	req.add_header("x-goog-api-key", clave)
	if cuerpo is not None:
		req.add_header("Content-Type", "application/json")
	with urllib.request.urlopen(req, timeout=timeout) as resp:
		return json.loads(resp.read().decode("utf-8"))


def cuerpo_google(turnos: list[Turno], prompt_sistema: str, max_tokens: int = 8192) -> dict:
	cuerpo: dict = {
		"contents": [{"role": "user" if t.rol == "user" else "model", "parts": [{"text": t.texto}]} for t in turnos],
		"generationConfig": {"maxOutputTokens": int(max_tokens)},
	}
	if prompt_sistema:
		cuerpo["systemInstruction"] = {"parts": [{"text": prompt_sistema}]}
	return cuerpo


def texto_respuesta_google(datos: dict) -> str:
	try:
		cand = datos["candidates"][0]
		texto = "".join(p.get("text", "") for p in cand.get("content", {}).get("parts", []))
	except (KeyError, IndexError, TypeError, AttributeError):
		bloqueo = (datos.get("promptFeedback") or {}).get("blockReason") if isinstance(datos, dict) else None
		if bloqueo:
			raise ErrorIA("El modelo ha rechazado la petición ({}).".format(bloqueo)) from None
		raise ErrorIA("Formato de respuesta inválido de la API") from None
	if not texto.strip():
		if cand.get("finishReason") == "MAX_TOKENS":
			raise ErrorIA("La respuesta se cortó porque superó la longitud máxima.")
		raise ErrorIA("La API no devolvió texto.")
	return texto


class ClienteGoogle:
	nombre = "Google AI"

	def __init__(self, claves: list[str] | None = None, modelo: str | None = None) -> None:
		self._claves = claves
		self._modelo = modelo

	def claves(self) -> list[str]:
		return list(self._claves) if self._claves is not None else cargar_claves()

	def modelo(self) -> str:
		return self._modelo or str(configuracion.valor("iaModeloGoogle") or configuracion.MODELO_GOOGLE_DEFECTO)

	def configurado(self) -> bool:
		return bool(self.claves())

	def chat(self, turnos: list[Turno], prompt_sistema: str = "", max_tokens: int = 8192) -> str:
		claves = self.claves()
		if not claves:
			raise ErrorIA("No hay claves de API de Google AI configuradas. Añádalas en el menú IA del chat o en las opciones del complemento.")
		url = "{}/models/{}:generateContent".format(URL_GOOGLE, self.modelo())
		cuerpo = cuerpo_google(turnos, prompt_sistema, max_tokens)
		for i, clave in enumerate(claves):
			try:
				return texto_respuesta_google(_peticion(url, clave, cuerpo))
			except urllib.error.HTTPError as e:
				if e.code in (401, 403, 429) and i < len(claves) - 1:
					try:
						e.close()
					except Exception:
						pass
					log.warning("consoleLog: la clave %d de Google AI falló (error %s); se prueba la siguiente", i + 1, e.code)
					continue
				detalle = ""
				try:
					detalle = (json.loads(e.read().decode("utf-8", "replace")).get("error") or {}).get("message", "")
				except Exception:
					pass
				raise ErrorIA("Error {}: {}".format(e.code, detalle or e.reason)) from None
			except urllib.error.URLError as e:
				raise ErrorIA("No se pudo conectar con Google AI: {}".format(e.reason)) from None
			except (TimeoutError, OSError) as e:
				raise ErrorIA("No se pudo conectar con Google AI: {}".format(e)) from None
		raise ErrorIA("Todas las claves de API fallaron o están agotadas.")


class ListadorModelos:
	"""Modelos Gemini y Gemma disponibles (caché de un día)."""

	def __init__(self, ruta_cache: str | None = None) -> None:
		self.ruta_cache = ruta_cache or configuracion.rutaDatos(CACHE_MODELOS)

	def _leerCache(self, fresca: bool) -> list[str] | None:
		try:
			if fresca and time.time() - os.path.getmtime(self.ruta_cache) >= DURACION_CACHE:
				return None
			with open(self.ruta_cache, encoding="utf-8") as f:
				datos = json.load(f)
			if isinstance(datos, list) and datos:
				return [str(m) for m in datos]
		except (OSError, ValueError):
			pass
		return None

	def obtener_modelos(self, claves: list[str]) -> list[str]:
		cache = self._leerCache(True)
		if cache:
			return cache
		for clave in claves:
			try:
				datos = _peticion("{}/models?pageSize=1000".format(URL_GOOGLE), clave, None, timeout=10)
			except Exception:
				continue
			modelos = sorted({str(m.get("name", "")).replace("models/", "") for m in datos.get("models", []) if "gemini" in str(m.get("name", "")) or "gemma" in str(m.get("name", ""))})
			if modelos:
				try:
					with open(self.ruta_cache, "w", encoding="utf-8") as f:
						json.dump(modelos, f)
				except OSError:
					pass
				return modelos
		# Si la consulta falla se usa la caché antigua y, si no hay, la lista de reserva.
		return self._leerCache(False) or list(MODELOS_RESERVA)


# ====================================================================== proveedores de Tiresias
class ClienteTiresias:
	"""Un proveedor de IA de Tiresias (``None`` = el elegido en sus opciones)."""

	def __init__(self, proveedor: str | None = None) -> None:
		self._id = proveedor

	def _proveedor(self):
		from tiresias.ai import providers

		return providers.getProvider(self._id)

	@property
	def nombre(self) -> str:
		try:
			return str(self._proveedor().name)
		except Exception:
			return "IA de Tiresias"

	def modelo(self) -> str:
		try:
			return str(self._proveedor().model())
		except Exception:
			return ""

	def configurado(self) -> bool:
		try:
			return bool(self._proveedor().isConfigured())
		except Exception:
			return False

	def chat(self, turnos: list[Turno], prompt_sistema: str = "", max_tokens: int = 8192) -> str:
		from tiresias.ai import providers

		proveedor = self._proveedor()
		mensajes = [providers.Message("assistant" if t.rol == "model" else "user", t.texto) for t in turnos]
		try:
			return proveedor.chat(mensajes, prompt_sistema, max_tokens).text
		except providers.AIError as e:
			raise ErrorIA(str(e)) from None


def cliente_actual():
	proveedor = str(configuracion.valor("iaProveedor") or "google")
	if proveedor == "google":
		return ClienteGoogle()
	if proveedor == "tiresias":
		return ClienteTiresias(None)
	return ClienteTiresias(proveedor)


def prompt_informe(fecha_iso: str) -> str:
	"""Instrucciones del generador de informes (con la fecha local de referencia)."""
	return (
		"Eres un experto en análisis de sistemas y depuración. "
		"La fecha local de referencia es {}. "
		"Analiza únicamente la evidencia del texto: no conviertas una fecha, "
		"un archivo antiguo o una simple lista de directorio en un fallo sin "
		"justificación. Separa hechos observados, inferencias y datos que faltan. "
		"Genera Markdown semántico con estas secciones: "
		"1. RESUMEN; 2. HALLAZGOS Y EVIDENCIA; 3. ERRORES CONFIRMADOS; "
		"4. POSIBLES SOLUCIONES; 5. DATOS ADICIONALES NECESARIOS. "
		"Indica el nivel de confianza y advierte antes de comandos destructivos "
		"o que requieran privilegios. Usa un tono profesional y directo."
	).format(fecha_iso)


PROMPT_REPARAR = (
	"He encontrado un error en el log de mi consola. "
	"Por favor, analízalo y sugiéreme exactamente qué debo cambiar en mi código para solucionarlo. "
	"Si es posible, dame el bloque de código corregido."
)


def construir_prompt(pregunta: str, seleccion: str = "", consola: str = "", adjuntos: list[dict] | None = None) -> str:
	"""Pregunta con el contexto elegido (selección, consola y archivos adjuntos)."""
	contextos = []
	if seleccion:
		contextos.append("[CONSOLA - SELECCIÓN]\n{}".format(seleccion))
	if consola:
		contextos.append("[CONSOLA - COMPLETO]\n{}".format(consola[-50000:]))
	for adj in adjuntos or []:
		contextos.append("[ARCHIVO: {}]\n{}".format(adj.get("nombre", ""), adj.get("texto", "")))
	if not contextos:
		return pregunta
	return "Contexto adicional:\n" + "\n---\n".join(contextos) + "\n\nPregunta: {}".format(pregunta)
