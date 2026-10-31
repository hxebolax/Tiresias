"""Arreglo web: reparar páginas poco accesibles desde el modo exploración.

A petición del usuario (Tiresias+Mayúsculas+Alt+P en un documento del modo
exploración) analiza la página y presenta un informe de los problemas de
accesibilidad que detecta: enlaces y botones sin nombre o con nombres
inútiles o repetidos, imágenes sin texto alternativo, campos sin etiqueta,
elementos pulsables que no son botones, falta de encabezados o regiones,
tablas de maquetación, textos que parecen encabezados y superposiciones de
cookies. Para cada problema propone un arreglo sobre **lo que Tiresias
presenta** (nunca sobre la página, que un lector de pantalla no puede
modificar): nombres deducidos, etiquetas, botones, encabezados, región
principal, tablas de maquetación y ocultación con la web flexible.

Los arreglos se guardan por sitio en ``data\\addonsData\\arregloWeb`` y se
aplican solos al cargar sus páginas mediante el punto de extensión
``browse.buffer.filter_node`` del modo exploración. Las imágenes sin
alternativo se pueden describir con los proveedores de IA de Tiresias.
"""

from __future__ import annotations

from typing import Any

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

from . import almacen, analisis, arreglos, options

log = getLogger("arregloWeb")

CATEGORY = "Arreglo web"
#: Tiresias+Alt+R («reparar») lo usa el acceso remoto y todas las letras de
#: Tiresias+Alt están ocupadas por el núcleo o por otros complementos: se usan
#: Tiresias+Mayúsculas+Alt+P («página») y Tiresias+Mayúsculas+Alt+Q («quitar»).
GESTURE_ANALYZE = "kb:tiresias+shift+alt+p"
GESTURE_REMOVE = "kb:tiresias+shift+alt+q"
MENU_ID = "arregloWeb"


def _speak(text: str) -> None:
	from tiresias import speech

	with speech.allowOnDemand():
		speech.speakMessage(text)


def _repeatCount() -> int:
	from tiresias.input import core as inputCore

	return inputCore.getLastScriptRepeatCount()


def currentDocument() -> Any:
	"""Documento del modo exploración (árbol de elementos) con el búfer listo, o ``None``."""
	try:
		from tiresias.ai.assistant import currentBrowseDocument

		doc = currentBrowseDocument()
	except Exception:
		return None
	if doc is None or getattr(doc, "buffer", None) is None:
		return None
	if getattr(doc, "bufferKind", "tree") != "tree":
		return None
	if not getattr(doc, "isReady", True):
		return None
	return doc


class GlobalPlugin(_BaseGlobalPlugin):
	scriptCategory = CATEGORY

	def __init__(self) -> None:
		super().__init__()
		self._terminated = False
		#: Sitios cuyos arreglos se aplican en esta sesión aunque la opción de aplicar guardados esté desactivada.
		self._sitiosSesion: set[str] = set()
		#: Último análisis: (clave del documento, problemas).
		self._ultimo: tuple[str, list] | None = None
		self._sinFiltro = False
		options.registerDefaults()
		try:
			options.registerPanel()
		except Exception:
			log.debug("No se pudo añadir la categoría del Arreglo web", exc_info=True)
		try:
			from tiresias.browse import buffer as vbuf

			vbuf.filter_node.register(self.filtrarNodo)
		except Exception:
			# ``filter_node`` llegó con Tiresias 1.0.15.
			self._sinFiltro = True
			log.exception("No se pudo registrar el filtro de nodos del Arreglo web")
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, "Arreglo &web: arreglos guardados por sitio...", self.mostrarSitios)
		except Exception:
			log.debug("Sin entrada de menú del Arreglo web", exc_info=True)

	def terminate(self) -> None:
		self._terminated = True
		try:
			from tiresias.browse import buffer as vbuf

			vbuf.filter_node.unregister(self.filtrarNodo)
		except Exception:
			pass
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(MENU_ID)
		except Exception:
			pass
		try:
			options.unregisterPanel()
		except Exception:
			pass
		super().terminate()

	# ================================================================ filtro del búfer
	def reglasActivas(self, documentKey: str) -> arreglos.ReglasSitio | None:
		"""Reglas que se aplican a un documento (según la opción y la sesión)."""
		sitio = almacen.sitioDe(documentKey)
		if not sitio:
			return None
		if not options.get("aplicarGuardados") and sitio not in self._sitiosSesion:
			return None
		return almacen.reglasDe(sitio)

	def filtrarNodo(self, value: Any, buffer: Any = None, controlType: int = 0) -> Any:
		"""Manejador de ``browse.buffer.filter_node`` (hilo de construcción del búfer)."""
		if value is None or self._terminated:
			return value
		try:
			reglas = self.reglasActivas(getattr(buffer, "documentKey", "") or "")
			if reglas is None:
				return value
			return arreglos.aplicar(reglas, value, controlType)
		except Exception:
			log.debug("Error aplicando un arreglo web", exc_info=True)
			return value

	# ================================================================ análisis
	def analizarDocumento(self, doc: Any) -> list[analisis.Problema]:
		opciones = {"encabezadosDeducidos": options.get("encabezadosDeducidos"), "pulsablesComoBotones": options.get("pulsablesComoBotones")}
		problemas = analisis.analizar(doc.buffer, doc, opciones)
		try:
			self._ultimo = (doc._documentKey(), problemas)
		except Exception:
			self._ultimo = ("", problemas)
		return problemas

	def _sitioDe(self, doc: Any) -> tuple[str, str]:
		try:
			key = doc._documentKey()
		except Exception:
			key = ""
		return key, almacen.sitioDe(key)

	def aplicarArreglos(self, doc: Any, problemas: list, guardar: bool = True) -> int:
		"""Aplica (y guarda) los arreglos de ``problemas`` y reconstruye el documento. Devuelve cuántos."""
		key, sitio = self._sitioDe(doc)
		reglas = [p.regla for p in problemas if p.regla]
		if not reglas:
			_speak("No hay ningún arreglo que aplicar.")
			return 0
		ocultas = 0
		try:
			from tiresias.browse import flexweb

			for r in reglas:
				if r.get("tipo") == "ocultar" and r.get("flex"):
					r["doc"] = key
					if r["flex"] not in flexweb.rulesFor(key).hidden:
						flexweb.addHidden(key, r["flex"])
					ocultas += 1
		except Exception:
			log.debug("No se pudo ocultar con la web flexible", exc_info=True)
		if sitio:
			if guardar:
				almacen.anadir(sitio, reglas)
			else:
				# Solo mientras dure la sesión (no se escriben en el archivo).
				almacen.anadirSesion(sitio, reglas)
			self._sitiosSesion.add(sitio)
		try:
			doc.requestRebuild()
		except Exception:
			log.debug("No se pudo reconstruir el documento", exc_info=True)
		n = len(reglas)
		_speak(f"{n} arreglo{'' if n == 1 else 's'} aplicado{'' if n == 1 else 's'}" + (" y guardados para este sitio." if guardar and sitio else "."))
		return n

	def describirImagenes(self, doc: Any, nodos: list) -> None:
		if not options.get("describirImagenesIA"):
			_speak("La descripción de imágenes con IA está desactivada en las opciones del Arreglo web.")
			return
		from . import ia

		def fin(hechas: int, fallidas: int, error: str) -> None:
			if hechas:
				_speak(f"{hechas} imagen{'' if hechas == 1 else 'es'} descrita{'' if hechas == 1 else 's'} con IA" + (f"; {fallidas} sin descripción." if fallidas else "."))
			else:
				_speak("No se pudo describir ninguna imagen" + (f": {error}" if error else "."))

		ia.describir(doc, nodos, options.get("maxImagenesIA"), fin)

	def _mostrar(self, doc: Any, problemas: list) -> None:
		key, sitio = self._sitioDe(doc)
		from . import dialogo

		dialogo.mostrarInforme(
			doc,
			sitio or key[:60],
			problemas,
			lambda elegidos, guardar, _doc=doc: self._aplicarDesdeDialogo(_doc, elegidos, guardar),
			(lambda nodos, _doc=doc: self._describirDesdeDialogo(_doc, nodos)) if options.get("describirImagenesIA") else None,
			True,
		)

	def _aplicarDesdeDialogo(self, doc: Any, elegidos: list, guardar: bool) -> None:
		from tiresias import queue_handler

		queue_handler.queueFunction(self.aplicarArreglos, doc, elegidos, guardar)

	def _describirDesdeDialogo(self, doc: Any, nodos: list) -> None:
		from tiresias import queue_handler

		queue_handler.queueFunction(self.describirImagenes, doc, nodos)

	# ================================================================ órdenes
	@script(
		description="Arreglo web: analiza la página del modo exploración, anuncia los problemas de accesibilidad y abre la lista para aplicar arreglos (dos veces: aplica todos los arreglos sin preguntar)",
		gesture=GESTURE_ANALYZE,
		category=CATEGORY,
	)
	def script_analizar(self, gesture) -> None:
		if self._sinFiltro:
			_speak("Arreglo web necesita Tiresias 1.0.15 o posterior. Actualiza Tiresias para usarlo.")
			return
		doc = currentDocument()
		if doc is None:
			_speak("Arreglo web: no hay ningún documento del modo exploración.")
			return
		todos = _repeatCount() >= 1
		problemas = self.analizarDocumento(doc)
		_key, sitio = self._sitioDe(doc)
		if not problemas:
			_speak(analisis.resumen(problemas, sitio))
			return
		if todos:
			self.aplicarArreglos(doc, problemas, True)
			return
		if options.get("informeVoz"):
			_speak(analisis.resumen(problemas, sitio))
		self._mostrar(doc, problemas)

	@script(
		description="Arreglo web: anuncia solo el resumen de problemas de la página (sin abrir la lista)",
		category=CATEGORY,
		speakOnDemand=True,
	)
	def script_informe(self, gesture) -> None:
		doc = currentDocument()
		if doc is None:
			_speak("Arreglo web: no hay ningún documento del modo exploración.")
			return
		problemas = self.analizarDocumento(doc)
		_key, sitio = self._sitioDe(doc)
		_speak(analisis.resumen(problemas, sitio))

	@script(
		description="Arreglo web: quita los arreglos guardados del sitio de la página actual y vuelve a construirla",
		gesture=GESTURE_REMOVE,
		category=CATEGORY,
	)
	def script_quitarArreglos(self, gesture) -> None:
		doc = currentDocument()
		if doc is None:
			_speak("Arreglo web: no hay ningún documento del modo exploración.")
			return
		key, sitio = self._sitioDe(doc)
		quitados = almacen.quitarSitio(sitio) if sitio else []
		self._sitiosSesion.discard(sitio)
		if not quitados:
			_speak(f"No hay arreglos guardados para {sitio or 'este documento'}.")
			return
		try:
			from tiresias.browse import flexweb

			for r in quitados:
				if r.get("tipo") == "ocultar":
					ocultas = flexweb.rulesFor(key).hidden
					for i, fr in enumerate(ocultas):
						if fr == r.get("flex"):
							flexweb.removeHidden(key, i)
							break
		except Exception:
			log.debug("No se pudo quitar la ocultación de la web flexible", exc_info=True)
		try:
			doc.requestRebuild()
		except Exception:
			pass
		n = len(quitados)
		_speak(f"{n} arreglo{'' if n == 1 else 's'} quitado{'' if n == 1 else 's'} de {sitio}.")

	@script(
		description="Arreglo web: activa o desactiva la aplicación automática de los arreglos guardados al cargar las páginas",
		category=CATEGORY,
	)
	def script_alternarAutomatico(self, gesture) -> None:
		valor = not options.get("aplicarGuardados")
		options.set("aplicarGuardados", valor)
		_speak("Arreglos guardados: se aplican al cargar las páginas." if valor else "Arreglos guardados: no se aplican al cargar (solo cuando se piden).")
		doc = currentDocument()
		if doc is not None:
			try:
				doc.requestRebuild()
			except Exception:
				pass

	@script(
		description="Arreglo web: abre la lista de sitios con arreglos guardados para quitarlos",
		category=CATEGORY,
	)
	def script_sitios(self, gesture) -> None:
		self.mostrarSitios()

	# ================================================================ gestión
	def mostrarSitios(self) -> None:
		from . import dialogo

		dialogo.mostrarSitios(self._sitioCambiado)

	def _sitioCambiado(self, sitio: str) -> None:
		from tiresias import queue_handler

		def rehacer() -> None:
			doc = currentDocument()
			if doc is not None and self._sitioDe(doc)[1] == sitio:
				try:
					doc.requestRebuild()
				except Exception:
					pass

		queue_handler.queueFunction(rehacer)
