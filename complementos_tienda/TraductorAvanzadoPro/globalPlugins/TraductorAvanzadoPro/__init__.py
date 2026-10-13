"""Traductor Avanzado Pro para Tiresias.

Basado en el complemento de NVDA de Héctor J. Benítez Corredera
(https://github.com/hxebolax/TranslateAdvanced), reescrito con la API de
Tiresias:

- Traducción simultánea de todo lo que dice Tiresias mediante el punto de
  extensión ``speech.filter_speechSequence`` (sin bloquear la voz: lo que no
  está en la caché se traduce en segundo plano y se dice a continuación).
- Servicios como plugins (Google, DeepL, Microsoft, LibreTranslate, OpenAI,
  Gemini, DeepSeek y Claude) y plugins de extensión (OCR, diccionario,
  detectores de idioma, historial inteligente).
- Caché por aplicación e idioma, historial con exportación y estadísticas,
  capa de órdenes con sonidos, interfaz de traducción con audio.
"""

from __future__ import annotations

import os
import threading
from typing import Any

from tiresias import queue_handler
from tiresias.baseobject import normalizeGestureId, script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _GlobalPluginBase

from .utilidades import lector, seguridad
from .utilidades.texto import es_texto_traducible, limpiar_sustitutos, obtener_texto_seleccionado, texto_de_objeto

log = getLogger("TraductorAvanzadoPro")

ID_COMPLEMENTO = "TraductorAvanzadoPro"
CATEGORIA = "Traductor Avanzado Pro"
URL_DONACIONES = "https://paypal.me/hjbcdonaciones"

#: Gestos de la capa de órdenes (se activan tras Tiresias+Control+Mayúsculas+T).
GESTOS_CAPA = {
	"kb:t": "alternar_traduccion",
	"kb:s": "traducir_seleccion",
	"kb:b": "traducir_portapapeles",
	"kb:l": "copiar_ultima_traduccion",
	"kb:h": "mostrar_historial",
	"kb:d": "elegir_idioma_destino",
	"kb:o": "elegir_idioma_origen",
	"kb:c": "seleccion_rapida",
	"kb:a": "limpiar_toda_cache",
	"kb:x": "limpiar_cache_app",
	"kb:g": "alternar_cache",
	"kb:v": "traducir_ultimo_hablado",
	"kb:z": "traducir_objeto",
	"kb:w": "abrir_interfaz_traduccion",
	"kb:i": "detectar_idioma",
	"kb:j": "alternar_intercambio_auto",
	"kb:k": "intercambiar_idiomas",
	"kb:u": "comprobar_actualizaciones",
	"kb:p": "abrir_configuracion",
	"kb:r": "traducir_ocr",
	"kb:e": "buscar_diccionario",
	"kb:escape": "cerrar_capa",
	"kb:f1": "mostrar_ayuda_comandos",
}

AYUDA_CAPA = (
	"Comandos de la capa del Traductor (se abre con Tiresias+Control+Mayúsculas+T):\n"
	"T: Alternar traducción simultánea\n"
	"S: Traducir selección\n"
	"B: Traducir portapapeles\n"
	"L: Copiar última traducción\n"
	"H: Mostrar historial\n"
	"D: Cambiar idioma destino\n"
	"O: Cambiar idioma origen\n"
	"C: Cambiar servicio (cambio rápido de servicio, modelo e idiomas)\n"
	"A: Limpiar toda la caché\n"
	"X: Limpiar caché de la aplicación actual\n"
	"G: Alternar caché\n"
	"V: Traducir último texto hablado\n"
	"Z: Traducir objeto (navegador)\n"
	"W: Abrir interfaz de traducción\n"
	"I: Detectar idioma de selección\n"
	"J: Alternar intercambio automático de idiomas\n"
	"K: Intercambiar idioma principal y alternativo\n"
	"U: Comprobar actualizaciones\n"
	"P: Configuración\n"
	"R: Traducir OCR (Plugin)\n"
	"E: Buscar en diccionario (Plugin)\n"
	"ESC: Cerrar capa\n"
	"F1: Esta ayuda\n"
	"\n"
	"Fuera de la capa: Tiresias+Control+Mayúsculas+G detecta el idioma del texto seleccionado."
)


class GlobalPlugin(_GlobalPluginBase):
	"""Complemento global del Traductor Avanzado Pro."""

	scriptCategory = CATEGORIA

	def __init__(self) -> None:
		super().__init__()
		self._inicializado = False
		self._traduccion_activa = False
		self._traduccion_en_curso = False
		self._capa_comandos_activa = False
		self._ultimo_texto_hablado: str | None = None
		self._ultimo_texto_traducido: str | None = None
		self._ultimo_error: str | None = None
		#: Traducciones que dice el propio complemento (el filtro no las vuelve a traducir).
		self._textos_propios: set[str] = set()
		self._max_textos_propios = 64
		self.configuracion = None
		self.gestor_traductores = None
		self.gestor_plugins = None
		self.cache = None
		self.historial = None
		self.gestor_idiomas = None
		self.gestor_ayuda = None
		self.monitor_portapapeles = None
		self.gestor_sonidos = None
		self.traductor_async = None
		self._filtro_registrado = False
		if seguridad.es_modo_seguro():
			# Como el original: en modo seguro el complemento no hace nada.
			log.info("Traductor Avanzado Pro desactivado en modo seguro")
			return
		self._inicializar_complemento()

	# ================================================================ inicio y fin
	def _inicializar_complemento(self) -> None:
		from .interfaces import panel_opciones
		from .nucleo.cache import GestorCache
		from .nucleo.configuracion import GestorConfiguracion
		from .nucleo.gestor_plugins import GestorPlugins
		from .nucleo.gestor_traductores import GestorTraductores
		from .nucleo.historial import GestorHistorial
		from .nucleo.traductor_async import TraductorAsync
		from .servicios.ayuda import GestorAyuda
		from .servicios.idiomas import GestorIdiomas
		from .servicios.portapapeles import MonitorPortapapeles
		from .servicios.sonido import GestorSonidos

		try:
			ruta = os.path.dirname(os.path.abspath(__file__))
			self.configuracion = GestorConfiguracion(ruta)
			self.gestor_idiomas = GestorIdiomas(self.configuracion)
			self.gestor_ayuda = GestorAyuda()
			self.gestor_sonidos = GestorSonidos(os.path.join(ruta, "datos", "sonidos"), self.configuracion)
			self.gestor_traductores = GestorTraductores(self.configuracion, os.path.join(ruta, "traductores"), __name__, self.configuracion.ruta_traductores_usuario)
			self.gestor_traductores.cargar_traductores()
			self.gestor_plugins = GestorPlugins(self.configuracion, os.path.join(ruta, "plugins"), __name__, self.configuracion.ruta_plugins_usuario)
			self.gestor_plugins.cargar_plugins(self)
			self.cache = GestorCache(self.configuracion)
			if self.configuracion.cache_habilitada:
				self.cache.cargar()
			self.historial = GestorHistorial(self.configuracion)
			hist = self.gestor_plugins.plugins.get("historial_inteligente")
			if hist is not None:
				hist.establecer_historial(self.historial)
			self.monitor_portapapeles = MonitorPortapapeles()
			from .interfaces.reproductor import limpiar_temporales

			limpiar_temporales(os.path.join(self.configuracion.ruta_config, "temp"))
			self.traductor_async = TraductorAsync(self)
			self.traductor_async.iniciar()
			self._registrar_extension_points()
			panel_opciones.plugin = self
			panel_opciones.registrar()
			self._crear_menu()
			self._inicializado = True
			log.info("Traductor Avanzado Pro iniciado correctamente: %d servicios, %d plugins", len(self.gestor_traductores.traductores), len(self.gestor_plugins.plugins))
		except Exception:
			log.exception("Error al inicializar Traductor Avanzado Pro")
			self._inicializado = False

	def _registrar_extension_points(self) -> None:
		from tiresias.speech import api as speechApi

		speechApi.filter_speechSequence.register(self._filtrar_secuencia_voz)
		self._filtro_registrado = True

	def _desregistrar_extension_points(self) -> None:
		if not self._filtro_registrado:
			return
		try:
			from tiresias.speech import api as speechApi

			speechApi.filter_speechSequence.unregister(self._filtrar_secuencia_voz)
		except Exception:
			pass
		self._filtro_registrado = False

	def terminate(self) -> None:
		if not self._inicializado:
			return
		self._inicializado = False
		self._traduccion_activa = False
		self._desregistrar_extension_points()
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(ID_COMPLEMENTO)
		except Exception:
			pass
		try:
			from .interfaces import panel_opciones

			panel_opciones.desregistrar()
			panel_opciones.plugin = None
		except Exception:
			pass
		if self.traductor_async:
			self.traductor_async.detener()
		try:
			if self.cache and self.configuracion.cache_habilitada:
				self.cache.guardar_todo()
			if self.configuracion:
				self.configuracion.guardar()
		except Exception:
			log.exception("Error al guardar los datos del Traductor Avanzado Pro")
		if self.gestor_plugins:
			self.gestor_plugins.terminar()
		if self.gestor_sonidos:
			self.gestor_sonidos.terminar()
		try:
			import wx

			from .interfaces import dialogos

			if wx.GetApp() is not None:
				wx.CallAfter(dialogos.cerrar_todos)
		except Exception:
			pass
		log.info("Traductor Avanzado Pro terminado correctamente")

	# ================================================================ menú Herramientas
	def _crear_menu(self) -> None:
		from tiresias import gui

		gui.registerToolsMenuItem(ID_COMPLEMENTO, "&Traductor Avanzado Pro", self._entradas_menu, submenu=True)

	def _entradas_menu(self) -> list:
		entradas: list = [
			("&Configuración...", self._on_menu_configuracion),
			("&Historial de traducciones...", self._on_menu_historial),
			("&Interfaz de traducción...", lambda: self._abrir_interfaz_traduccion("")),
			("Cambio &rápido de servicio e idiomas...", self._abrir_seleccion_rapida),
			("Idioma de &destino...", lambda: self._abrir_idiomas("destino")),
			("Idioma de &origen...", lambda: self._abrir_idiomas("origen")),
		]
		extra = []
		for plugin in (self.gestor_plugins.plugins.values() if self.gestor_plugins else []):
			if plugin.esta_habilitado:
				for elemento in plugin.obtener_elementos_menu():
					if elemento.get("etiqueta") and callable(elemento.get("accion")):
						extra.append((elemento["etiqueta"], elemento["accion"]))
		if extra:
			entradas += [None] + extra
		entradas += [None, ("&Documentación", self._on_menu_documentacion), ("&Apoyar el proyecto", self._on_menu_donaciones)]
		return entradas

	def _on_menu_configuracion(self) -> None:
		self._abrir_configuracion(desde_menu=True)

	def _on_menu_historial(self) -> None:
		self._abrir_historial(desde_menu=True)

	def _on_menu_documentacion(self) -> None:
		ruta = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "doc", "es", "readme.html"))
		lector.abrir_url(ruta)

	def _on_menu_donaciones(self) -> None:
		lector.abrir_url(URL_DONACIONES)

	# ================================================================ filtro de voz
	def _filtrar_secuencia_voz(self, value: list) -> list:
		"""Traduce la secuencia de voz si la traducción simultánea está activa.

		Nunca bloquea: usa la caché al instante y encola el resto para traducirlo
		en segundo plano (se dirá a continuación).
		"""
		secuencia = value
		if lector.silenciado():
			return []
		textos = [e for e in secuencia if isinstance(e, str) and e.strip()]
		if not textos:
			return secuencia
		completo = " ".join(textos)
		if completo in self._textos_propios:
			self._textos_propios.discard(completo)
			return secuencia
		if lector.es_mensaje_propio(completo) or any(lector.es_mensaje_propio(t) for t in textos):
			return secuencia
		self._ultimo_texto_hablado = completo
		if not self._traduccion_activa or not self._inicializado or self._traduccion_en_curso or self.traductor_async is None:
			return secuencia
		try:
			from tiresias.speech import api as speechApi

			if speechApi.currentOrigin() == speechApi.ORIGIN_TYPING:
				# Los caracteres y palabras que se escriben no se traducen.
				return secuencia
		except Exception:
			pass
		app = lector.app_actual() or None
		nueva = []
		try:
			for elemento in secuencia:
				if not isinstance(elemento, str) or not es_texto_traducible(elemento):
					nueva.append(elemento)
					continue
				if elemento in self._textos_propios:
					self._textos_propios.discard(elemento)
					nueva.append(elemento)
					continue
				cacheado = self._traducir_desde_cache(elemento, app)
				if cacheado and cacheado != elemento:
					nueva.append(cacheado)
					continue
				self.traductor_async.encolar(elemento, app)
				nueva.append(elemento)
			return nueva
		except Exception:
			log.exception("Error al filtrar la secuencia de voz")
			return secuencia

	def _traducir_desde_cache(self, texto: str, app: str | None = None) -> str | None:
		if not self.configuracion.cache_habilitada:
			return None
		limpio = limpiar_sustitutos(texto)
		if not limpio.strip():
			return None
		try:
			cacheado = self.cache.obtener(limpio, self.configuracion.idioma_destino, app=app)
		except Exception:
			return None
		if cacheado and cacheado != limpio:
			self._ultimo_texto_traducido = cacheado
			lector.braille(cacheado)
		return cacheado

	def _hablar_traduccion(self, traduccion: str) -> None:
		"""Dice una traducción de la traducción simultánea (hilo del núcleo)."""
		if not traduccion or not traduccion.strip() or not self._traduccion_activa:
			return
		if len(self._textos_propios) >= self._max_textos_propios:
			self._textos_propios.clear()
		self._textos_propios.add(traduccion)
		lector.hablar_texto(traduccion, siguiente=True)

	# ================================================================ traducción
	def _detectar(self, texto: str) -> str | None:
		plugin_det = self.gestor_plugins.obtener_plugin("detector_google") if self.gestor_plugins else None
		if plugin_det is not None:
			return plugin_det.detectar(texto)
		traductor = self.gestor_traductores.obtener_traductor_activo()
		if traductor is not None and traductor.soporta_deteccion:
			return traductor.detectar_idioma(texto)
		return None

	@staticmethod
	def _mismo_idioma(a: str | None, b: str | None) -> bool:
		if not a or not b:
			return False
		norm = lambda c: c.lower().replace("_", "-").split("-")[0]  # noqa: E731
		return norm(a) == norm(b)

	def _traducir_texto(self, texto: str, app: str | None = None) -> str | None:
		"""Traduce con el servicio activo (caché, intercambio automático, historial).

		Devuelve la traducción, el propio texto si no hacía falta traducir o
		``None`` si hubo un error (``self._ultimo_error`` dice cuál).
		"""
		self._ultimo_error = None
		if not texto:
			return ""
		traductor = self.gestor_traductores.obtener_traductor_activo()
		if traductor is None:
			self._ultimo_error = "No hay ningún servicio de traducción disponible"
			return None
		origen = self.configuracion.idioma_origen
		destino = self.configuracion.idioma_destino
		if self.configuracion.intercambio_automatico_idioma:
			try:
				detectado = self._detectar(texto)
				if self._mismo_idioma(detectado, destino):
					destino = self.configuracion.idioma_destino_alternativo
					log.debug("Intercambio automático: %s es el destino; se traduce a %s", detectado, destino)
			except Exception:
				log.debug("Fallo en la detección del intercambio automático", exc_info=True)
		if self.configuracion.cache_habilitada:
			cacheado = self.cache.obtener(texto, destino, app=app)
			if cacheado:
				return cacheado
		try:
			resultado = traductor.traducir(texto, idioma_origen=origen, idioma_destino=destino)
		except Exception as e:
			log.exception("Error en la traducción")
			self._ultimo_error = str(e)
			return None
		if resultado and resultado.strip() and resultado != texto:
			if self.configuracion.cache_habilitada:
				self.cache.guardar(texto, resultado, destino, origen, app=app, servicio=traductor.id)
			self.historial.agregar(texto, resultado, origen, destino, traductor.id)
			return resultado
		if resultado is None:
			self._ultimo_error = traductor.ultimo_error or "el servicio no respondió"
			return None
		return texto

	def _traducir_texto_fondo(self, texto: str, app: str | None = None) -> str:
		"""Traducción de la traducción simultánea (hilo de :class:`TraductorAsync`)."""
		if not texto or not texto.strip():
			return texto
		traduccion = self._traducir_texto(limpiar_sustitutos(texto), app)
		if traduccion and traduccion != texto:
			self._ultimo_texto_traducido = traduccion
		return traduccion or texto

	def _traducir_manual(self, texto: str, origen: str | None, destino: str | None) -> tuple[str | None, str | None]:
		"""Traducción de la interfaz de traducción con los idiomas elegidos en ella."""
		traductor = self.gestor_traductores.obtener_traductor_activo()
		if traductor is None:
			return None, "No hay ningún servicio de traducción disponible"
		origen = origen or "auto"
		destino = destino or self.configuracion.idioma_destino
		try:
			res = traductor.traducir(texto, idioma_origen=origen, idioma_destino=destino)
		except Exception as e:
			log.exception("Error en la traducción manual")
			return None, str(e)
		if res:
			self._ultimo_texto_traducido = res
			self.historial.agregar(texto, res, origen, destino, traductor.id)
			return res, None
		return None, traductor.ultimo_error

	def _traducir_y_mostrar(self, texto: str) -> None:
		"""Traduce (en un hilo) y muestra el resultado en ventana o lo dice."""
		try:
			traduccion = self._traducir_texto(texto, lector.app_actual() or None)
			if traduccion and traduccion != texto:
				self._ultimo_texto_traducido = traduccion
				self._mostrar_resultado(texto, traduccion)
			elif traduccion == texto:
				lector.mensaje("No se requería traducción o no hubo cambios")
			else:
				lector.mensaje("Error en la traducción" + (f": {self._ultimo_error}" if self._ultimo_error else ""))
		finally:
			self._traduccion_en_curso = False

	def _traducir_texto_largo(self, texto: str) -> None:
		"""Lo usa el plugin de OCR (ya está en un hilo propio)."""
		self._traduccion_en_curso = True
		self._traducir_y_mostrar(texto)

	def _mostrar_resultado(self, original: str, traduccion: str) -> None:
		if self.configuracion.mostrar_resultados:
			from tiresias.gui.helpers import runOnGui

			def mostrar() -> None:
				from .interfaces.resultado import DialogoResultado

				DialogoResultado(None, original, traduccion, self.monitor_portapapeles).mostrar()

			runOnGui(mostrar)
		else:
			self._textos_propios.add(traduccion)
			lector.hablar_texto(traduccion)

	def _lanzar_traduccion(self, texto: str) -> None:
		self._traduccion_en_curso = True
		threading.Thread(target=self._traducir_y_mostrar, args=(texto,), name="TraductorAvanzadoPro-Traducir", daemon=True).start()

	def _pegar_en_foco(self, texto: str) -> None:
		"""Pega ``texto`` en la ventana que estaba activa y restaura el portapapeles."""

		def pegar() -> None:
			from tiresias import clipboard, winapi

			copia = winapi.getClipboardText() or ""
			lector.silenciar_sintetizador(0.5)
			clipboard.ignoreNextChange()
			if not winapi.setClipboardText(texto):
				lector.mensaje("No se pudo copiar la traducción")
				return
			lector.enviar_teclas("control+v")

			def restaurar() -> None:
				clipboard.ignoreNextChange()
				winapi.setClipboardText(copia)

			queue_handler.callLater(500, restaurar)

		# Tras cerrarse el diálogo y volver el foco a la aplicación.
		queue_handler.callLater(400, pegar)

	# ================================================================ utilidades
	def _verificar_condiciones(self, desde_menu: bool = False, verificar_traduccion: bool = False) -> bool:
		if not self._inicializado:
			self._avisar("El Traductor Avanzado Pro no se ha podido iniciar; consulte el registro.", desde_menu)
			return False
		if self._traduccion_en_curso:
			self._avisar("Hay una traducción en curso. Espere a que termine.", desde_menu)
			return False
		if verificar_traduccion and self._traduccion_activa:
			self._avisar("Desactive la traducción simultánea para realizar esta acción.", desde_menu)
			return False
		return True

	@staticmethod
	def _avisar(texto: str, desde_menu: bool) -> None:
		if desde_menu:
			from tiresias import gui

			gui.messageBox(texto, "Información")
		else:
			lector.mensaje(texto)

	def _reproducir_sonido(self, nombre: str) -> None:
		if self.gestor_sonidos and self.configuracion and self.configuracion.sonidos_habilitados:
			self.gestor_sonidos.reproducir(nombre)

	def _activar_capa(self) -> None:
		self._reproducir_sonido("abrir")
		self.bindGestures(GESTOS_CAPA)
		self._capa_comandos_activa = True

	def _cerrar_capa_comandos(self) -> None:
		if not self._capa_comandos_activa:
			return
		self._capa_comandos_activa = False
		self.clearGestureBindings()
		if queue_handler.isCoreThread():
			self._reproducir_sonido("cerrar")
		else:
			queue_handler.queueFunction(self._reproducir_sonido, "cerrar")

	def getScript(self, gesture: Any):
		"""Con la capa activa: sus teclas; cualquier otra la cierra y funciona como siempre."""
		if not self._capa_comandos_activa:
			return super().getScript(gesture)
		ids = {normalizeGestureId(g) for g in getattr(gesture, "identifiers", [])}
		ids |= {"kb:" + g.split(":", 1)[1] for g in ids if g.startswith("kb(")}
		funcion = super().getScript(gesture)
		if funcion and (ids & set(GESTOS_CAPA) or getattr(funcion, "__name__", "") == "script_activar_capa_comandos"):
			# Las teclas de la capa, y su propio atajo, que la cierra.
			return funcion
		self._cerrar_capa_comandos()
		return super().getScript(gesture)

	def _abrir_configuracion(self, desde_menu: bool = False) -> None:
		if not self._verificar_condiciones(desde_menu, True):
			return
		from tiresias import gui

		from .interfaces import panel_opciones

		gui.showSettings(panel_opciones.PANEL_ID)

	def _abrir_historial(self, desde_menu: bool = False) -> None:
		if not self._verificar_condiciones(desde_menu, True):
			return
		if not self.historial or self.historial.esta_vacio():
			if desde_menu:
				from tiresias import gui

				gui.messageBox("No hay traducciones en el historial.", "Historial vacío")
			else:
				lector.mensaje("No hay traducciones en el historial.")
			return
		from tiresias.gui.helpers import runOnGui

		from .interfaces import dialogos

		def abrir() -> None:
			dlg = dialogos.mostrar_unico("historial", lambda: dialogos.DialogoHistorial(self), lambda d: d.lista.SetFocus())
			dlg.recargar()

		runOnGui(abrir)

	def _abrir_interfaz_traduccion(self, texto: str) -> None:
		from tiresias.gui.helpers import runOnGui

		from .interfaces import dialogos

		def abrir() -> None:
			dlg = dialogos.mostrar_unico("traduccion", lambda: dialogos.DialogoTraduccion(self, texto), lambda d: d.txt_origen.SetFocus())
			if texto and dlg.txt_origen.GetValue() != texto:
				dlg.txt_origen.SetValue(texto)

		runOnGui(abrir)

	def _abrir_seleccion_rapida(self) -> None:
		from tiresias.gui.helpers import runOnGui

		from .interfaces import dialogos

		runOnGui(lambda: dialogos.mostrar_unico("rapida", lambda: dialogos.DialogoSeleccionRapida(self), lambda d: d.combo_servicio.SetFocus()))

	def _abrir_idiomas(self, tipo: str) -> None:
		from tiresias.gui.helpers import runOnGui

		from .interfaces import dialogos

		runOnGui(lambda: dialogos.mostrar_unico(f"idiomas_{tipo}", lambda: dialogos.DialogoIdiomas(self, tipo), lambda d: d.lista_idiomas.SetFocus()))

	def _aplicar_seleccion_rapida(self, valores: dict[str, Any]) -> None:
		if valores.get("servicio"):
			self.configuracion.servicio_activo = valores["servicio"]
		if valores.get("origen"):
			self.configuracion.idioma_origen = valores["origen"]
		if valores.get("destino"):
			self.configuracion.idioma_destino = valores["destino"]
		modelo_info = ""
		if valores.get("modelo"):
			sc = self.configuracion.obtener_api(valores["servicio"])
			if sc:
				sc.modelo = valores["modelo"]
				modelo_info = f" ({valores['modelo']})"
		self.configuracion.guardar()
		traductor = self.gestor_traductores.obtener_traductor_activo()
		gi = self.gestor_idiomas
		lector.mensaje(
			f"Configuración actualizada. Motor: {traductor.nombre if traductor else valores.get('servicio')}{modelo_info}, "
			f"Origen: {gi.obtener_nombre_idioma(self.configuracion.idioma_origen)}, Destino: {gi.obtener_nombre_idioma(self.configuracion.idioma_destino)}"
		)

	@staticmethod
	def _veces_pulsado() -> int:
		try:
			from tiresias.input import core as inputCore

			return inputCore.getLastScriptRepeatCount()
		except Exception:
			return 0

	# ================================================================ órdenes
	@script(description="Activa la capa de comandos del traductor", category=CATEGORIA, gesture="kb:tiresias+control+shift+t", speakOnDemand=True)
	def script_activar_capa_comandos(self, gesture) -> None:
		if self._capa_comandos_activa:
			self._cerrar_capa_comandos()
			return
		if self._verificar_condiciones():
			self._activar_capa()

	@script(description="Activa o desactiva la traducción simultánea", category=CATEGORIA, speakOnDemand=True)
	def script_alternar_traduccion(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._verificar_condiciones():
			return
		self._traduccion_activa = not self._traduccion_activa
		if self._traduccion_activa:
			lector.mensaje("Traducción activada")
			if self.configuracion.cache_habilitada:
				threading.Thread(target=self.cache.cargar, daemon=True).start()
		else:
			lector.mensaje("Traducción desactivada")
			if self.traductor_async:
				self.traductor_async.vaciar()
			if self.configuracion.cache_habilitada:
				threading.Thread(target=self.cache.guardar_todo, daemon=True).start()

	@script(description="Traduce el texto seleccionado", category=CATEGORIA, speakOnDemand=True)
	def script_traducir_seleccion(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._verificar_condiciones(verificar_traduccion=True):
			return
		resultado = obtener_texto_seleccionado()
		if not resultado["exito"] or not resultado["texto"]:
			lector.mensaje("No hay texto seleccionado para traducir")
			return
		self._lanzar_traduccion(resultado["texto"])

	@script(description="Traduce el contenido del portapapeles", category=CATEGORIA, speakOnDemand=True)
	def script_traducir_portapapeles(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._verificar_condiciones(verificar_traduccion=True):
			return
		texto = self.monitor_portapapeles.obtener_texto()
		if not texto or not es_texto_traducible(texto):
			lector.mensaje("No hay texto para traducir en el portapapeles")
			return
		self._lanzar_traduccion(texto)

	@script(description="Copia la última traducción al portapapeles", category=CATEGORIA, speakOnDemand=True)
	def script_copiar_ultima_traduccion(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if self._ultimo_texto_traducido:
			if self.monitor_portapapeles.establecer_texto(self._ultimo_texto_traducido):
				lector.mensaje(f"Traducción copiada: {self._ultimo_texto_traducido}")
			else:
				lector.mensaje("No se pudo copiar")
		else:
			lector.mensaje("No hay traducción para copiar")

	@script(description="Muestra el historial de traducciones", category=CATEGORIA, speakOnDemand=True)
	def script_mostrar_historial(self, gesture) -> None:
		self._cerrar_capa_comandos()
		self._abrir_historial()

	@script(description="Cambio rápido de configuración (Motor e Idiomas)", category=CATEGORIA, speakOnDemand=True)
	def script_seleccion_rapida(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if self._verificar_condiciones():
			self._abrir_seleccion_rapida()

	@script(description="Elige el idioma de destino de la traducción", category=CATEGORIA, speakOnDemand=True)
	def script_elegir_idioma_destino(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if self._verificar_condiciones():
			self._abrir_idiomas("destino")

	@script(description="Elige el idioma de origen de la traducción", category=CATEGORIA, speakOnDemand=True)
	def script_elegir_idioma_origen(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if self._verificar_condiciones():
			self._abrir_idiomas("origen")

	@script(description="Limpia toda la caché de traducción (fuera de la capa, pulse dos veces)", category=CATEGORIA, speakOnDemand=True)
	def script_limpiar_toda_cache(self, gesture) -> None:
		if self._capa_comandos_activa:
			self._cerrar_capa_comandos()
		elif self._veces_pulsado() == 0:
			lector.mensaje("Pulse dos veces para limpiar toda la caché de todas las aplicaciones")
			return
		if self.cache:
			self.cache.limpiar()
			lector.mensaje("Toda la caché de traducción ha sido limpiada")

	@script(description="Limpia la caché de traducción de la aplicación actual (fuera de la capa, pulse dos veces)", category=CATEGORIA, speakOnDemand=True)
	def script_limpiar_cache_app(self, gesture) -> None:
		if self._capa_comandos_activa:
			self._cerrar_capa_comandos()
		elif self._veces_pulsado() == 0:
			lector.mensaje("Pulse dos veces para limpiar la caché de la aplicación enfocada")
			return
		app = lector.app_actual()
		if not app or not self.cache:
			lector.mensaje("No se pudo limpiar la caché de la aplicación actual")
			return
		self.cache.limpiar_aplicacion(app)
		lector.mensaje(f"Caché de la aplicación {app} limpiada")

	@script(description="Activa o desactiva la caché de traducción", category=CATEGORIA, speakOnDemand=True)
	def script_alternar_cache(self, gesture) -> None:
		self._cerrar_capa_comandos()
		self.configuracion.cache_habilitada = not self.configuracion.cache_habilitada
		if self.configuracion.cache_habilitada:
			lector.mensaje("Caché de traducción activada")
			if self.cache:
				threading.Thread(target=self.cache.cargar, daemon=True).start()
		else:
			lector.mensaje("Caché de traducción desactivada")

	@script(description="Traduce el último texto verbalizado", category=CATEGORIA, speakOnDemand=True)
	def script_traducir_ultimo_hablado(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._ultimo_texto_hablado:
			lector.mensaje("No hay texto verbalizado recientemente para traducir")
			return
		if self._verificar_condiciones(verificar_traduccion=True):
			texto = self._ultimo_texto_hablado
			lector.mensaje("Traduciendo último texto verbalizado...")
			self._lanzar_traduccion(texto)

	@script(description="Traduce el texto del objeto bajo el navegador", category=CATEGORIA, speakOnDemand=True)
	def script_traducir_objeto(self, gesture) -> None:
		self._cerrar_capa_comandos()
		obj = lector.objeto_navegador()
		if obj is None:
			lector.mensaje("No hay objeto sobre el que traducir")
			return
		texto = texto_de_objeto(obj)
		if not es_texto_traducible(texto):
			lector.mensaje("El objeto no tiene texto para traducir")
			return
		if self._verificar_condiciones(verificar_traduccion=True):
			self._lanzar_traduccion(texto)

	@script(description="Abre la interfaz de traducción manual", category=CATEGORIA, speakOnDemand=True)
	def script_abrir_interfaz_traduccion(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._inicializado:
			self._verificar_condiciones()
			return
		res = obtener_texto_seleccionado()
		self._abrir_interfaz_traduccion(res["texto"] if res["exito"] else "")

	@script(description="Detecta el idioma del texto seleccionado (Google)", category=CATEGORIA, gesture="kb:tiresias+control+shift+g", speakOnDemand=True)
	def script_detectar_idioma(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._inicializado:
			self._verificar_condiciones()
			return
		plugin = self.gestor_plugins.obtener_plugin("detector_google")
		if plugin is not None:
			plugin.ejecutar()
			return
		res = obtener_texto_seleccionado()
		if not res["exito"] or not res["texto"]:
			lector.mensaje("No hay texto seleccionado para detectar el idioma")
			return
		local = self.gestor_plugins.obtener_plugin("detector_idioma")
		if local is not None:
			lector.mensaje_navegable("Idioma detectado", local.obtener_descripcion_detallada(res["texto"]))
		else:
			lector.mensaje("Detector de Google no disponible")

	@script(description="Alterna el intercambio automático de idioma", category=CATEGORIA, speakOnDemand=True)
	def script_alternar_intercambio_auto(self, gesture) -> None:
		self._cerrar_capa_comandos()
		valor = not self.configuracion.intercambio_automatico_idioma
		self.configuracion.intercambio_automatico_idioma = valor
		lector.mensaje("Intercambio automático activado" if valor else "Intercambio automático desactivado")

	@script(description="Intercambia idioma principal y alternativo", category=CATEGORIA, speakOnDemand=True)
	def script_intercambiar_idiomas(self, gesture) -> None:
		self._cerrar_capa_comandos()
		principal = self.configuracion.idioma_destino
		alternativo = self.configuracion.idioma_destino_alternativo
		self.configuracion.idioma_destino = alternativo
		self.configuracion.idioma_destino_alternativo = principal
		lector.mensaje(f"Idiomas intercambiados. Nuevo destino: {self.gestor_idiomas.obtener_nombre_idioma(alternativo)}")

	@script(description="Comprueba actualizaciones del complemento", category=CATEGORIA, speakOnDemand=True)
	def script_comprobar_actualizaciones(self, gesture) -> None:
		self._cerrar_capa_comandos()
		lector.mensaje("Buscando actualizaciones...")
		threading.Thread(target=self._comprobar_actualizaciones, name="TraductorAvanzadoPro-Actualizar", daemon=True).start()

	def _comprobar_actualizaciones(self) -> None:
		try:
			from tiresias import addon_store, addons

			entradas, _origen = addon_store.fetchCatalog()
		except Exception as e:
			log.debug("No se pudo consultar la tienda de complementos", exc_info=True)
			lector.mensaje(f"No se pudo consultar la tienda de complementos: {e}")
			return
		entrada = next((e for e in entradas if e.id == ID_COMPLEMENTO), None)
		instalado = addons.getAddon(ID_COMPLEMENTO)
		if entrada is None or instalado is None:
			lector.mensaje("No hay actualizaciones disponibles en este momento")
			return
		if entrada.status() != "update":
			lector.mensaje(f"No hay actualizaciones disponibles en este momento. Versión instalada: {instalado.version}")
			return

		def preguntar() -> None:
			from tiresias import gui

			import wx

			if gui.messageBox(
				f"Hay una versión nueva del Traductor Avanzado Pro: {entrada.version} (instalada: {instalado.version}).\n\n¿Abrir la tienda de complementos para actualizarlo?",
				"Actualización disponible",
				wx.YES_NO | wx.ICON_QUESTION,
			) == wx.YES:
				gui.showAddonStore()

		from tiresias.gui.helpers import runOnGui

		runOnGui(preguntar)

	@script(description="Realiza OCR y traduce el resultado", category=CATEGORIA, speakOnDemand=True)
	def script_traducir_ocr(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._inicializado:
			self._verificar_condiciones()
			return
		plugin = self.gestor_plugins.obtener_plugin("ocr_traductor")
		if plugin is None:
			lector.mensaje("El plugin de OCR no está disponible")
			return
		if self._verificar_condiciones(verificar_traduccion=True):
			plugin.ejecutar()

	@script(description="Busca la palabra actual en el diccionario", category=CATEGORIA, speakOnDemand=True)
	def script_buscar_diccionario(self, gesture) -> None:
		self._cerrar_capa_comandos()
		if not self._inicializado:
			self._verificar_condiciones()
			return
		texto = obtener_texto_seleccionado(lector.objeto_foco())["texto"] or obtener_texto_seleccionado()["texto"]
		if not texto:
			lector.mensaje("Seleccione una palabra para buscar en el diccionario")
			return
		plugin = self.gestor_plugins.obtener_plugin("diccionario")
		if plugin is None:
			lector.mensaje("El plugin de diccionario no está disponible")
			return
		lector.mensaje("Buscando en el diccionario...")

		def buscar() -> None:
			try:
				resultado, _palabra = plugin.buscar_multilingue(texto)
			except Exception:
				log.exception("Error en el diccionario")
				resultado = None
			if resultado:
				lector.mensaje_navegable(f"Definición de {texto}", resultado)
			elif plugin.ultimo_error:
				lector.mensaje(f"Error en el diccionario: {plugin.ultimo_error}")
			else:
				lector.mensaje("No se encontró la palabra en el diccionario")

		threading.Thread(target=buscar, name="TraductorAvanzadoPro-Diccionario", daemon=True).start()

	@script(description="Abre la configuración del complemento", category=CATEGORIA, speakOnDemand=True)
	def script_abrir_configuracion(self, gesture) -> None:
		self._cerrar_capa_comandos()
		self._abrir_configuracion()

	@script(description="Cierra la capa de comandos", category=CATEGORIA, speakOnDemand=True)
	def script_cerrar_capa(self, gesture) -> None:
		if self._capa_comandos_activa:
			self._cerrar_capa_comandos()
			lector.mensaje("Capa de comandos cerrada")

	@script(description="Muestra la ayuda de comandos", category=CATEGORIA, speakOnDemand=True)
	def script_mostrar_ayuda_comandos(self, gesture) -> None:
		self._cerrar_capa_comandos()
		lector.mensaje_navegable("Ayuda de comandos del Traductor", AYUDA_CAPA)
