"""TCA-Portapapeles para Tiresias.

- Anuncia con voz y con sonidos las teclas del portapapeles: seleccionar
  todo, copiar, cortar, pegar, deshacer y rehacer. Al copiar o cortar sin
  nada seleccionado dice «Sin selección». Las teclas se observan sin
  quitárselas a la aplicación (siguen funcionando igual) y se pueden cambiar
  en las opciones para otras distribuciones de teclado.
- Historial propio que guarda todos los formatos de lo copiado (texto con
  formato, HTML, imágenes, archivos y carpetas) y lo pega en la aplicación
  que haya detrás de la ventana, dejando luego el portapapeles como estaba.
- Leer el portapapeles completo, estadísticas del texto seleccionado y un
  selector de palabras de la selección para copiar solo algunas.
- Modo juego: traduce y lee lo que los juegos copian al portapapeles.

Las órdenes están en una capa: Tiresias+Control+Mayúsculas+V y después una
letra. Escape sale de la capa; cualquier otra tecla sale y llega a la
aplicación.

Basado en TCA-Portapapeles para NVDA, de Peter Reina (basado a su vez en
zPortapapeles de Héctor J. Benítez Corredera; idea original de Peter
Vagner), licencia GPL. Código propio para Tiresias.
"""

from __future__ import annotations

import os
import threading
import time

from tiresias import queue_handler
from tiresias.baseobject import normalizeGestureId, script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _BaseGlobalPlugin

from . import historial as historialMod
from . import juego, opciones, portapapeles
from . import texto as textoMod

log = getLogger("tcaPortapapeles")

MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
SONIDOS_DIR = os.path.join(MODULE_DIR, "sonidos")
CATEGORIA = "TCA-Portapapeles"
MENU_ID = "tcaPortapapeles"

#: Gesto que activa la capa de órdenes. El original no asigna ninguno; se usa
#: una combinación libre con la V de pegar (Tiresias+Alt+V ya es el historial
#: del portapapeles de Tiresias).
GESTO_CAPA = "kb:tiresias+control+shift+v"

#: Teclas de la capa → orden.
GESTOS_CAPA = {
	"kb:h": "mostrarHistorial",
	"kb:l": "leerPortapapeles",
	"kb:e": "estadisticasSeleccion",
	"kb:p": "copiarParteSeleccion",
	"kb:a": "activarDesactivar",
	"kb:j": "modoJuego",
	"kb:f1": "ayudaCapa",
	"kb:escape": "salirCapa",
}

AYUDA_CAPA = (
	"Capa de TCA-Portapapeles. H: historial. L: leer el portapapeles. E: estadísticas del texto seleccionado. "
	"P: copiar parte del texto seleccionado. A: activar o desactivar los anuncios. J: modo juego. "
	"F1: esta ayuda. Escape: salir."
)

MENSAJES = {
	"selectAll": "Seleccionar todo",
	"copy": "Copiar",
	"cut": "Cortar",
	"paste": "Pegar",
	"undo": "Deshacer",
	"redo": "Rehacer",
}
SONIDOS = {
	"selectAll": "todo.wav",
	"copy": "copiar.wav",
	"cut": "cortar.wav",
	"paste": "pegar.wav",
	"undo": "deshacer.wav",
	"redo": "rehacer.wav",
}
SONIDO_HISTORIAL = "historial.wav"

MSG_SIN_SELECCION = "Sin selección"
MSG_JUEGO_ACTIVO = "El modo juego está activado. Desactívelo para usar esta opción."
MSG_DOS_VENTANAS = "Ya hay una ventana del historial o de copia de texto abierta. No es posible tener dos ventanas a la vez."
MSG_VENTANA_JUEGO = "Tiene una ventana de historial o de copia de texto abierta. Para activar el modo juego ciérrela primero."
MSG_HISTORIAL_VACIO = "No hay nada en el historial de TCA-Portapapeles."
MSG_HISTORIAL_DESACTIVADO = "El historial de TCA-Portapapeles está desactivado. Esta función no está disponible."
MSG_UN_ELEMENTO = "Solo tiene un elemento seleccionado, esta opción necesita más de un elemento para usarse"
MSG_SIN_TEXTO = "No hay texto en el portapapeles"
MSG_PROTEGIDO = "El portapapeles tiene un texto protegido (por ejemplo, una contraseña copiada desde un gestor de contraseñas)"
MSG_PEGADO = "Pegado al foco."
MSG_NO_PEGADO = "No se pudo poner el elemento en el portapapeles"
MSG_NO_TRADUCIDO = "No se pudo traducir"
MSG_SEGURO = "No disponible en una pantalla segura"

#: Tiempo máximo que se espera a que cambie el portapapeles tras copiar o cortar (segundos).
ESPERA_COPIA = 0.8
#: Cada cuánto se mira si cambió (milisegundos).
PASO_COPIA = 50
#: Espera para que el foco vuelva a la aplicación tras cerrar el historial (segundos).
ESPERA_FOCO = 0.25
#: Tras pegar, cuándo se restaura el portapapeles anterior (milisegundos, como el original).
RETRASO_RESTAURAR = 350
#: Clases de ventana de las consolas (Control+C interrumpe: no se dice «Sin selección»).
CLASES_CONSOLA = ("ConsoleWindowClass", "CASCADIA_HOSTING_WINDOW_CLASS")


# ====================================================================== utilidades
def isSecureMode() -> bool:
	"""Tiresias se ejecuta en modo seguro (pantallas de inicio de sesión, UAC...)."""
	try:
		from tiresias.config.policy import policy

		return bool(policy.secureMode)
	except Exception:
		return False


def isSecureContext() -> bool:
	"""Modo seguro o pantalla de bloqueo."""
	if isSecureMode():
		return True
	try:
		from tiresias.a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		return False


def hablar(texto: str) -> None:
	from tiresias import speech

	with speech.allowOnDemand():
		speech.speakMessage(texto)


def hablarTexto(texto: str) -> None:
	from tiresias import speech

	with speech.allowOnDemand():
		speech.speakText(texto)


def pitar(hz: int, ms: int) -> None:
	from tiresias.audio import tones

	tones.beep(hz, ms)


def reproducir(nombre: str) -> None:
	from tiresias.audio import tones

	ruta = os.path.join(SONIDOS_DIR, nombre)
	if os.path.isfile(ruta):
		tones.playWaveFile(ruta)


def textoSeleccionado() -> str | None:
	"""Texto seleccionado en el foco o en el modo exploración (``None`` si no hay)."""
	from tiresias import api, textinfo

	obj = api.getCaretObject()
	if obj is None:
		return None
	try:
		info = obj.makeTextInfo(textinfo.POSITION_SELECTION)
		if info is None or info.isCollapsed:
			return None
		return info.text or None
	except Exception:
		return None


def focoEnConsola() -> bool:
	from tiresias import api
	from tiresias.objects.roles import Role

	foco = api.getFocusObject()
	if foco is None:
		return False
	try:
		if getattr(foco, "windowClassName", "") in CLASES_CONSOLA:
			return True
		return foco.role == Role.TERMINAL
	except Exception:
		return False


def focoDormido() -> bool:
	"""La aplicación con el foco está en modo dormir: no se anuncia nada."""
	from tiresias import api

	try:
		foco = api.getFocusObject()
		app = foco.appModule if foco is not None else None
		return bool(getattr(app, "sleepMode", False))
	except Exception:
		return False


def nucleoAnunciaCopia() -> bool:
	"""Tiresias ya dice «Copiado» o «Cortado» (opciones de la categoría Portapapeles)."""
	from tiresias import clipboard
	from tiresias.config import conf

	cb = conf["clipboard"]
	if not cb["announceCopy"]:
		return False
	if cb["announceCutCopyPaste"]:
		return True
	# Sin distinguir las teclas, Tiresias solo anuncia el texto copiado.
	try:
		return portapapeles.hayTexto() and not clipboard.isSensitiveContent()
	except Exception:
		return False


def nucleoAnunciaPegado() -> bool:
	"""Tiresias ya dice «Pegado» (o lee lo pegado) en el foco actual."""
	from tiresias import clipboard
	from tiresias.config import conf

	cb = conf["clipboard"]
	if not (cb["announceCutCopyPaste"] or (cb["announcePastedText"] and portapapeles.hayTexto())):
		return False
	try:
		esEditable = getattr(clipboard, "focusIsEditable", None) or clipboard._focusIsEditable
		return bool(esEditable())
	except Exception:
		return False


def teclaDelNucleo(gesture, accion: str) -> bool:
	"""La tecla es una de las que Tiresias reconoce para cortar, copiar o pegar."""
	from tiresias import clipboard

	try:
		return clipboard.classifyKey(getattr(gesture, "vk", 0), getattr(gesture, "modifiers", frozenset())) == accion
	except Exception:
		return False


def mapaDeTeclas() -> dict[str, str]:
	"""Gesto normalizado → acción, según las teclas de las opciones."""
	mapa: dict[str, str] = {}
	for clave, accion, _etiqueta in opciones.TECLAS:
		for tecla in opciones.get(clave):
			tecla = tecla.strip()
			if not tecla:
				continue
			gid = tecla if ":" in tecla else "kb:" + tecla
			try:
				mapa.setdefault(normalizeGestureId(gid), accion)
			except Exception:
				log.debug("Tecla no válida en las opciones: %s", tecla)
	return mapa


# ====================================================================== complemento
def _callarAvisosDelNucleo(callar: bool) -> None:
	"""En el modo juego el complemento lee lo copiado: Tiresias no dice «Copiado: …»."""
	try:
		from tiresias import clipboard

		silence = getattr(clipboard, "silenceAnnouncements", None)
		if silence is not None:
			silence("tcaPortapapeles", callar)
	except Exception:
		pass


class GlobalPlugin(_BaseGlobalPlugin):
	scriptCategory = CATEGORIA
	#: Las tareas lentas (pegar desde el historial) van en un hilo (las pruebas lo desactivan).
	enHilo = True
	#: Arranca los hilos que vigilan el portapapeles (las pruebas lo desactivan).
	vigilar = True

	def __init__(self) -> None:
		super().__init__()
		self._terminado = False
		self._capaActiva = False
		self._idsCapa = frozenset(normalizeGestureId(g) for g in (*GESTOS_CAPA, GESTO_CAPA))
		self.historial = historialMod.Historial()
		self._vigilante: historialMod.Vigilante | None = None
		self._vigilanteJuego: historialMod.Vigilante | None = None
		self._traductor: juego.Traductor | None = None
		self._ultimoJuego = ""
		self._falloAvisado = False
		self._teclas: dict[str, str] = {}
		self._activo = True
		self._juego = False
		opciones.registerDefaults()
		self._seguro = isSecureMode()
		if self._seguro:
			# Como el original: en las pantallas seguras el complemento no hace nada.
			return
		try:
			opciones.registerPanel(self)
		except Exception:
			log.debug("No se pudo añadir la categoría de TCA-Portapapeles", exc_info=True)
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, "&TCA-Portapapeles", self._entradasMenu, submenu=True)
		except Exception:
			log.debug("No se pudo añadir TCA-Portapapeles al menú Herramientas", exc_info=True)
		try:
			from tiresias.input import core as inputCore

			inputCore.decide_executeGesture.register(self._decidir)
		except Exception:
			log.debug("No se pudo registrar el observador de teclas", exc_info=True)
		self.aplicarOpciones()

	def terminate(self) -> None:
		self._terminado = True
		try:
			from tiresias.input import core as inputCore

			inputCore.decide_executeGesture.unregister(self._decidir)
		except Exception:
			pass
		self._terminarCapa()
		self._pararVigilante()
		self._pararJuego()
		_callarAvisosDelNucleo(False)
		if not self._seguro:
			try:
				opciones.unregisterPanel()
			except Exception:
				pass
			try:
				from tiresias import gui

				gui.unregisterToolsMenuItem(MENU_ID)
			except Exception:
				pass
			try:
				from . import dialogos

				dialogos.cerrarVentanas()
			except Exception:
				log.debug("No se pudieron cerrar las ventanas de TCA-Portapapeles", exc_info=True)
		super().terminate()

	def getScript(self, gesture):
		if self._seguro:
			return None
		return super().getScript(gesture)

	# ================================================================ opciones
	def aplicarOpciones(self) -> None:
		"""Aplica la configuración (al iniciar y al guardar las opciones)."""
		if self._terminado or self._seguro:
			return
		self._teclas = mapaDeTeclas()
		self._activo = bool(opciones.get("activado"))
		juegoActivo = bool(opciones.get("modoJuego"))
		if opciones.get("historial"):
			if self._vigilante is None:
				self._iniciarVigilante()
			else:
				self._vigilante.cambiarIntervalo(opciones.get("intervalo"))
		else:
			self._pararVigilante()
		if juegoActivo != self._juego or (juegoActivo and self._vigilanteJuego is None):
			self._aplicarJuego(juegoActivo)
		elif self._vigilanteJuego is not None:
			self._vigilanteJuego.cambiarIntervalo(opciones.get("intervaloJuego"))

	@property
	def modoJuegoActivo(self) -> bool:
		return self._juego

	@property
	def anunciosActivos(self) -> bool:
		return self._activo

	# ================================================================ capa de órdenes
	def _decidir(self, gesture) -> bool:
		"""Observa cada tecla (hilo de los ganchos: debe ser muy rápido) y la deja pasar siempre.

		Sale de la capa con las teclas que no son suyas y, si la tecla es de
		las del portapapeles, encola su anuncio. Nunca bloquea la tecla: llega
		a la aplicación igual que sin el complemento.
		"""
		try:
			if getattr(gesture, "isModifier", False):
				return True
			ids = {normalizeGestureId(i) for i in getattr(gesture, "identifiers", ()) or ()}
			if self._capaActiva and self._idsCapa.isdisjoint(ids):
				self._terminarCapa()
			if not self._activo or self._juego or self._terminado:
				return True
			accion = next((self._teclas[i] for i in ids if i in self._teclas), None)
			if accion is None:
				return True
			from tiresias.input import core as inputCore

			if inputCore.manager.inputHelp:
				return True
			queue_handler.queueFunction(self._alPulsar, accion, portapapeles.secuencia(), teclaDelNucleo(gesture, accion))
		except Exception:
			log.debug("Error observando una tecla", exc_info=True)
		return True

	def _terminarCapa(self) -> None:
		self._capaActiva = False
		inst = self.__dict__.get("_instanceGestures")
		if inst is None:
			return
		for gestureId in GESTOS_CAPA:
			inst.pop(normalizeGestureId(gestureId), None)

	@property
	def capaActiva(self) -> bool:
		return self._capaActiva

	@script(description="Entra en la capa de órdenes de TCA-Portapapeles", category=CATEGORIA, gesture=GESTO_CAPA)
	def script_capa(self, gesture) -> None:
		if self._capaActiva:
			return
		self.bindGestures(GESTOS_CAPA)
		self._capaActiva = True
		pitar(100, 10)
		try:
			from tiresias import braille

			braille.handler.message(CATEGORIA)
		except Exception:
			pass

	@script(description="Sale de la capa de órdenes de TCA-Portapapeles", category=CATEGORIA)
	def script_salirCapa(self, gesture) -> None:
		self._terminarCapa()
		pitar(120, 100)

	@script(description="Dice las teclas de la capa de órdenes de TCA-Portapapeles", category=CATEGORIA, speakOnDemand=True)
	def script_ayudaCapa(self, gesture) -> None:
		hablar(AYUDA_CAPA)

	# ================================================================ anuncios de las teclas
	def _alPulsar(self, accion: str, seqAntes: int, delNucleo: bool) -> None:
		"""Hilo del núcleo: anuncia la tecla del portapapeles pulsada."""
		if self._terminado or not self._activo or self._juego or focoDormido():
			return
		if accion in ("copy", "cut"):
			self._comprobarCopia(accion, seqAntes, delNucleo, time.monotonic())
			return
		callaNucleo = accion == "paste" and delNucleo and nucleoAnunciaPegado()
		self.anunciar(accion, hablarMensaje=not callaNucleo)

	def _comprobarCopia(self, accion: str, seqAntes: int, delNucleo: bool, inicio: float) -> None:
		"""Espera a que cambie el portapapeles: si cambia, se anuncia; si no, «Sin selección»."""
		if self._terminado:
			return
		if portapapeles.secuencia() != seqAntes:
			self.anunciar(accion, hablarMensaje=not (delNucleo and nucleoAnunciaCopia()))
			return
		if time.monotonic() - inicio < ESPERA_COPIA:
			queue_handler.callLater(PASO_COPIA, self._comprobarCopia, accion, seqAntes, delNucleo, inicio)
			return
		# En las consolas Control+C interrumpe el programa: no es un error.
		if opciones.get("voz") and not focoEnConsola():
			hablar(MSG_SIN_SELECCION)

	def anunciar(self, accion: str, hablarMensaje: bool = True) -> None:
		if opciones.get("voz") and hablarMensaje:
			hablar(MENSAJES[accion])
		if opciones.get("audio"):
			reproducir(SONIDOS[accion])

	@script(description="Activa o desactiva los anuncios de las teclas del portapapeles de TCA-Portapapeles", category=CATEGORIA)
	def script_activarDesactivar(self, gesture) -> None:
		if self._juego:
			hablar(MSG_JUEGO_ACTIVO)
			return
		self._activo = not self._activo
		opciones.guardar("activado", self._activo)
		if self._activo:
			hablar("TCA-Portapapeles activado")
			pitar(400, 150)
		else:
			hablar("TCA-Portapapeles desactivado")
			pitar(100, 150)

	# ================================================================ historial
	def _iniciarVigilante(self) -> None:
		if not self.vigilar:
			return
		self._vigilante = historialMod.Vigilante(opciones.get("intervalo"), self._alCambiarHistorial, portapapeles.secuencia)
		if self._juego:
			self._vigilante.pausar()
		self._vigilante.start()

	def _pararVigilante(self) -> None:
		v, self._vigilante = self._vigilante, None
		if v is not None:
			v.detener()

	def _alCambiarHistorial(self) -> None:
		"""Hilo del vigilante: guarda lo copiado en el historial."""
		if self._juego or self._terminado:
			return
		from tiresias import clipboard

		# Lo que un gestor de contraseñas marca como protegido no se guarda.
		if clipboard.isSensitiveContent():
			return
		el = portapapeles.leerTodo()
		if el is None:
			return
		self.agregarAlHistorial(el)

	def agregarAlHistorial(self, el: portapapeles.Elemento) -> bool:
		nuevo = self.historial.agregar(el)
		if nuevo:
			queue_handler.queueFunction(self._avisarNuevo, el.texto)
		return nuevo

	def _avisarNuevo(self, texto: str) -> None:
		if self._terminado:
			return
		if opciones.get("sonidoHistorial"):
			reproducir(SONIDO_HISTORIAL)
		if opciones.get("vozCopiado") and texto.strip():
			hablarTexto(texto)

	def _comprobarVentanas(self) -> bool:
		"""``True`` si se puede abrir una ventana (no hay otra abierta)."""
		from . import dialogos

		if dialogos.hayVentana():
			hablar(MSG_DOS_VENTANAS)
			return False
		return True

	@script(description="Muestra la ventana del historial de TCA-Portapapeles (pega en el foco el elemento elegido)", category=CATEGORIA)
	def script_mostrarHistorial(self, gesture) -> None:
		if self._juego:
			hablar(MSG_JUEGO_ACTIVO)
			return
		if not opciones.get("historial"):
			hablar(MSG_HISTORIAL_DESACTIVADO)
			return
		if not len(self.historial):
			hablar(MSG_HISTORIAL_VACIO)
			return
		if isSecureContext():
			hablar(MSG_SEGURO)
			return
		if not self._comprobarVentanas():
			return
		from . import dialogos

		dialogos.mostrarHistorial(self)

	def pegarElemento(self, el: portapapeles.Elemento) -> None:
		"""Pega ``el`` en la aplicación con el foco (desde cualquier hilo) y luego restaura el portapapeles."""
		if self.enHilo:
			threading.Thread(target=self._prepararPegado, args=(el,), name="TCA-Portapapeles-pegar", daemon=True).start()
		else:
			self._prepararPegado(el)

	def _prepararPegado(self, el: portapapeles.Elemento) -> None:
		if self.enHilo:
			# El foco vuelve a la aplicación al cerrarse la ventana del historial.
			time.sleep(ESPERA_FOCO)
		if self._vigilante is not None:
			self._vigilante.pausar()
		try:
			copia = portapapeles.leerTodo()
		except Exception:
			copia = None
		queue_handler.queueFunction(self._pegar, el, copia)

	def _pegar(self, el: portapapeles.Elemento, copia: portapapeles.Elemento | None) -> None:
		"""Hilo del núcleo: pone el elemento, pulsa Control+V y programa la restauración."""
		from tiresias import clipboard, winapi

		if self._terminado or isSecureContext():
			self._reanudarVigilante()
			return
		clipboard.ignoreNextChange()
		if not portapapeles.escribirTodo(el):
			clipboard.cancelIgnore()
			hablar(MSG_NO_PEGADO)
			self._reanudarVigilante()
			return
		hwnd = winapi.getForegroundWindow()
		try:
			clase = winapi.getClassName(hwnd)
		except Exception:
			clase = ""
		if clase == "ConsoleWindowClass":
			# Consola clásica de Windows: Control+V no funciona; se usa la orden Pegar de su menú.
			WM_COMMAND = 0x0111
			winapi.user32.SendMessageTimeoutW(hwnd, WM_COMMAND, 0xFFF1, 0, 0x0002, 2000, None)
		else:
			if opciones.get("voz"):
				hablar(MSG_PEGADO)
			from tiresias.input.gestures import sendKey

			try:
				sendKey("control+v")
			except Exception:
				# Teclados sin la V latina (cirílicos...).
				sendKey("shift+insert")
		queue_handler.callLater(RETRASO_RESTAURAR, self._restaurar, copia)

	def _restaurar(self, copia: portapapeles.Elemento | None) -> None:
		from tiresias import clipboard

		if copia is not None:
			clipboard.ignoreNextChange()
			if not portapapeles.escribirTodo(copia):
				clipboard.cancelIgnore()
		queue_handler.callLater(100, self._reanudarVigilante)

	def _reanudarVigilante(self) -> None:
		if self._vigilante is not None and not self._juego:
			self._vigilante.reanudar()

	# ================================================================ otras órdenes
	@script(description="Lee el contenido completo del portapapeles (texto o nombres de los archivos copiados)", category=CATEGORIA, speakOnDemand=True)
	def script_leerPortapapeles(self, gesture) -> None:
		from tiresias import clipboard

		if clipboard.isSensitiveContent():
			hablar(MSG_PROTEGIDO)
			return
		contenido = portapapeles.leerTextoOArchivos()
		if contenido and contenido.strip():
			hablarTexto(contenido)
		else:
			hablar(MSG_SIN_TEXTO)

	@script(description="Dice las estadísticas del texto seleccionado (caracteres, palabras, líneas y párrafos)", category=CATEGORIA, speakOnDemand=True)
	def script_estadisticasSeleccion(self, gesture) -> None:
		texto = textoSeleccionado()
		if not texto:
			hablar(MSG_SIN_SELECCION)
			return
		hablar(textoMod.mensajeEstadisticas(textoMod.estadisticas(texto)))

	@script(description="Abre la ventana para copiar al portapapeles solo algunas palabras del texto seleccionado", category=CATEGORIA)
	def script_copiarParteSeleccion(self, gesture) -> None:
		if self._juego:
			hablar(MSG_JUEGO_ACTIVO)
			return
		if not self._comprobarVentanas():
			return
		texto = textoSeleccionado()
		if not texto or not textoMod.trocear(texto):
			hablar(MSG_SIN_SELECCION)
			return
		if len(textoMod.trocear(texto)) == 1:
			hablar(MSG_UN_ELEMENTO)
			return
		if isSecureContext():
			hablar(MSG_SEGURO)
			return
		from . import dialogos

		dialogos.mostrarPartes(self, texto)

	def copiarTexto(self, texto: str) -> bool:
		"""Hilo del núcleo: copia ``texto`` al portapapeles (lo recoge el historial)."""
		from tiresias import api

		if isSecureContext():
			hablar(MSG_SEGURO)
			return False
		return api.copyToClip(texto, notify=True)

	# ================================================================ modo juego
	@script(description="Activa o desactiva el modo juego de TCA-Portapapeles (traduce y lee lo que se copia al portapapeles)", category=CATEGORIA)
	def script_modoJuego(self, gesture) -> None:
		from . import dialogos

		if dialogos.hayVentana():
			hablar(MSG_VENTANA_JUEGO)
			return
		nuevo = not self._juego
		opciones.guardar("modoJuego", nuevo)
		self._aplicarJuego(nuevo)
		if nuevo:
			hablar("Modo juego de TCA-Portapapeles activado")
			pitar(400, 150)
		else:
			hablar("Modo juego de TCA-Portapapeles desactivado")
			pitar(100, 150)

	def _aplicarJuego(self, activo: bool) -> None:
		self._juego = activo
		_callarAvisosDelNucleo(activo)
		if activo:
			if self._vigilante is not None:
				self._vigilante.pausar()
			self._iniciarJuego()
		else:
			self._pararJuego()
			self._reanudarVigilante()

	def _iniciarJuego(self) -> None:
		self._pararJuego()
		self._ultimoJuego = ""
		self._falloAvisado = False
		self._traductor = juego.Traductor(lambda: opciones.get("idiomaJuego"), self._entregarTraduccion)
		if not self.vigilar:
			return
		self._traductor.start()
		self._vigilanteJuego = historialMod.Vigilante(opciones.get("intervaloJuego"), self._alCambiarJuego, portapapeles.secuencia, "TCA-Portapapeles-vigilante-juego")
		self._vigilanteJuego.start()

	def _pararJuego(self) -> None:
		v, self._vigilanteJuego = self._vigilanteJuego, None
		if v is not None:
			v.detener()
		t, self._traductor = self._traductor, None
		if t is not None and t.is_alive():
			t.detener()

	def _alCambiarJuego(self) -> None:
		"""Hilo del vigilante del modo juego: manda a traducir lo nuevo del portapapeles."""
		if not self._juego or self._terminado:
			return
		from tiresias import clipboard

		if clipboard.isSensitiveContent():
			return
		texto = portapapeles.leerTextoOArchivos()
		self.textoDelJuego(texto)

	def textoDelJuego(self, texto: str | None) -> bool:
		"""Manda ``texto`` a traducir si es nuevo; ``True`` si se mandó."""
		if not texto or not texto.strip() or portapapeles.esTextoDeLimpieza(texto) or texto == self._ultimoJuego:
			return False
		self._ultimoJuego = texto
		t = self._traductor
		if t is None:
			return False
		if t.is_alive():
			t.pedir(texto)
		else:
			t.procesar(texto)
		return True

	def _entregarTraduccion(self, original: str, traduccion: str | None) -> None:
		queue_handler.queueFunction(self._decirTraduccion, original, traduccion)

	def _decirTraduccion(self, original: str, traduccion: str | None) -> None:
		if not self._juego or self._terminado:
			return
		if traduccion is None or not traduccion.strip():
			if not self._falloAvisado:
				self._falloAvisado = True
				hablar(MSG_NO_TRADUCIDO)
			hablarTexto(original)
			return
		self._falloAvisado = False
		hablarTexto(traduccion)

	# ================================================================ menú Herramientas
	def _entradasMenu(self) -> list:
		def enNucleo(func):
			return lambda: queue_handler.queueFunction(func, None)

		return [
			("&Historial de TCA-Portapapeles...", enNucleo(self.script_mostrarHistorial)),
			("Desactivar los &anuncios" if self._activo else "Activar los &anuncios", enNucleo(self.script_activarDesactivar)),
			("Desactivar el &modo juego" if self._juego else "Activar el &modo juego", enNucleo(self.script_modoJuego)),
		]
