"""Audiocinemateca para Tiresias: todo el catálogo de la Audiocinemateca
(películas, series, documentales y cortometrajes con audiodescripción) con
reproductor propio, desde el menú Herramientas de Tiresias.

Basado en «Audiocinemateca para NVDA» de Héctor J. Benítez Corredera (GPL).
"""

from __future__ import annotations

import os
import threading

import wx

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from . import ajustes, credenciales, panel, red
from .control import SIN_REPRODUCCION, Controlador, hablar, informar
from .reproductor import REPRODUCIENDO

log = getLogger("audiocinemateca")

MENU_ID = "audiocinemateca"
CATEGORIA = ajustes.CATEGORIA_ORDENES
MSG_VENTANA_ABIERTA = (
	"La ventana de Audiocinemateca está abierta.\n"
	"Las teclas para manejar el reproductor de manera externa "
	"solo se pueden usar si la pantalla de la Audiocinemateca está cerrada."
)


def _enGui(func, *args, **kwargs) -> None:
	from tiresias.gui.helpers import runOnGui

	runOnGui(func, *args, **kwargs)


class GlobalPlugin(_Base):
	def __init__(self) -> None:
		super().__init__()
		ajustes.registrarDefectos()
		self.control: Controlador | None = None
		self.ventana = None
		self._ocupado = False
		self._dialogoInicio = None
		panel.complemento = self
		try:
			panel.registrar()
		except Exception:
			log.debug("No se pudo añadir la categoría de opciones", exc_info=True)
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, "&Audiocinemateca", self._entradasMenu, submenu=True)
		except Exception:
			log.debug("No se pudo añadir la entrada al menú Herramientas", exc_info=True)
		# Los datos se cargan en segundo plano para no retrasar el arranque.
		threading.Thread(target=self._iniciar, name="AudiocinematecaInicio", daemon=True).start()

	def _iniciar(self) -> None:
		try:
			self.control = Controlador(avisar=hablar)
			self.control.alTerminarTemporizador = self._trasTemporizador
		except Exception:
			log.exception("Error al iniciar el complemento Audiocinemateca")

	# ================================================================ menú Herramientas
	def _entradasMenu(self):
		return [
			("&Iniciar la Audiocinemateca", lambda: self.iniciar(desdeMenu=True)),
			("&Opciones", lambda: self.abrirOpciones(desdeMenu=True)),
			("&Volver a valores por defecto", lambda: self.restaurarDefecto(None)),
			("&Documentación del complemento", self.abrirDocumentacion),
		]

	def terminate(self) -> None:
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(MENU_ID)
		except Exception:
			pass
		panel.quitar()
		panel.complemento = None
		try:
			if self.ventana is not None:
				_enGui(self._cerrarVentanaAlTerminar)
		except Exception:
			pass
		if self.control is not None:
			try:
				self.control.terminar()
			except Exception:
				log.exception("Error al terminar Audiocinemateca")
		ajustes.estado.ventanaAbierta = False
		super().terminate()

	def _cerrarVentanaAlTerminar(self) -> None:
		v, self.ventana = self.ventana, None
		if v is not None:
			try:
				v.cerrar()
			except Exception:
				pass

	# ================================================================ avisos
	def _aviso(self, texto: str, desdeMenu: bool) -> None:
		"""Mensaje en un cuadro si se pidió desde el menú, o por voz si fue con una orden."""
		if desdeMenu:
			from .dialogos import mensaje

			_enGui(mensaje, texto, "Información")
		else:
			hablar(texto)

	def _cargando(self, desdeMenu: bool) -> bool:
		if self.control is None:
			self._aviso("El complemento Audiocinemateca todavía se está cargando.\nVuelva a intentarlo en unos segundos.", desdeMenu)
			return True
		return False

	# ================================================================ abrir la ventana
	def iniciar(self, desdeMenu: bool = False) -> None:
		"""Abre la ventana principal (pide la sesión y descarga el catálogo si hace falta)."""
		if ajustes.estado.ventanaAbierta and self.ventana is not None:
			self._aviso("Ya hay una instancia de Audiocinemateca abierta.", desdeMenu)
			_enGui(self._traerVentana)
			return
		if self._cargando(desdeMenu) or self._ocupado:
			return
		if self._dialogoInicio is not None:
			# Ya está abierto el inicio de sesión o la descarga del catálogo.
			_enGui(self._traerDialogoInicio)
			return
		self._ocupado = True
		threading.Thread(target=self._comprobarInicio, name="AudiocinematecaInicio", daemon=True).start()

	def _comprobarInicio(self) -> None:
		try:
			if not red.hayInternet():
				hablar("No se encontró conexión a internet. No es posible iniciar el complemento.")
				return
			if not ajustes.hayCredenciales():
				_enGui(self._flujoLogin)
				return
			if not self.control.catalogo.existe():
				_enGui(self._flujoDescargaCatalogo)
				return
			self._cargarYAbrir()
		finally:
			self._ocupado = False

	def _modal(self, dlg) -> int:
		"""Muestra un diálogo modal sin padre en primer plano (como los de Tiresias)."""
		from tiresias import gui

		frame = gui.mainFrame
		vivo = frame is not None
		if vivo:
			frame.prePopup()
		self._dialogoInicio = dlg
		try:
			dlg.Raise()
			return dlg.ShowModal()
		finally:
			self._dialogoInicio = None
			if vivo:
				frame.postPopup()

	def _traerDialogoInicio(self) -> None:
		dlg = self._dialogoInicio
		if dlg is not None:
			try:
				dlg.Raise()
				from tiresias.gui.helpers import bringToFront

				bringToFront(dlg)
			except Exception:
				pass

	def _flujoLogin(self) -> None:
		from .dialogos import DialogoLogin

		dlg = DialogoLogin(None)
		try:
			if self._modal(dlg) != wx.ID_OK:
				return
			usuario, contrasena = dlg.usuario, dlg.contrasena
		finally:
			dlg.Destroy()
		informar("Verificando credenciales...", 0)
		threading.Thread(target=self._verificarYContinuar, args=(usuario, contrasena), name="AudiocinematecaLogin", daemon=True).start()

	def _verificarYContinuar(self, usuario: str, contrasena: str) -> None:
		ok, error = red.verificarLogin(usuario, contrasena)
		if not ok:
			import wx

			from .dialogos import mensaje

			_enGui(mensaje, f"Las credenciales no son válidas.\n\nError: {error}", "Error", wx.OK | wx.ICON_ERROR)
			return
		credenciales.guardar(usuario, contrasena)
		if not self.control.catalogo.existe():
			_enGui(self._flujoDescargaCatalogo)
		else:
			self._cargarYAbrir()

	def _flujoDescargaCatalogo(self) -> None:
		import wx

		from .dialogos import DialogoDescarga

		dlg = DialogoDescarga(None, DialogoDescarga.DESCARGA)
		try:
			resultado = self._modal(dlg)
		finally:
			dlg.Destroy()
		if resultado == wx.ID_OK:
			threading.Thread(target=self._cargarYAbrir, name="AudiocinematecaCarga", daemon=True).start()

	def _cargarYAbrir(self) -> None:
		"""Lee el catálogo del disco (en un hilo) y abre la ventana."""
		informar("Cargando la interfaz...", 0)
		if not self.control.catalogo.cargar():
			import wx

			from .dialogos import mensaje

			_enGui(mensaje, "No se pudo leer el catálogo de la Audiocinemateca. Use «Actualizar base de datos» o vuelva a iniciar el complemento para descargarlo de nuevo.", "Error", wx.OK | wx.ICON_ERROR)
			try:
				os.remove(self.control.catalogo.rutaCatalogo)
			except OSError:
				pass
			return
		_enGui(self._abrirVentana)

	def _abrirVentana(self) -> None:
		from tiresias.gui.helpers import bringToFront

		from .ventana import VentanaPrincipal

		if self.ventana is not None:
			self._traerVentana()
			return
		self.ventana = VentanaPrincipal(self)
		self.ventana.Show()
		bringToFront(self.ventana)
		self.ventana.enfocarInicio()

	def _traerVentana(self) -> None:
		if self.ventana is not None:
			from tiresias.gui.helpers import bringToFront

			bringToFront(self.ventana)

	def ventanaCerrada(self, ventana, recargar: bool = False) -> None:
		if self.ventana is ventana:
			self.ventana = None
		if recargar:
			# Tras actualizar la base de datos se vuelve a abrir con el catálogo nuevo.
			threading.Thread(target=self._cargarYAbrir, name="AudiocinematecaCarga", daemon=True).start()

	def _trasTemporizador(self) -> None:
		v = self.ventana
		if v is not None:
			_enGui(v.actualizarEstadoBotones)

	# ================================================================ opciones y otros
	def abrirOpciones(self, desdeMenu: bool = False) -> None:
		from tiresias import gui

		gui.showSettings(panel.PANEL_ID)

	def opcionesCambiadas(self, claves: set[str]) -> None:
		"""Aplica al reproductor y a la ventana las opciones guardadas en el panel."""
		c = self.control
		if c is None:
			return
		if "dispositivo" in claves:
			c.setDispositivo(ajustes.get("dispositivo"))
		if "volumen" in claves:
			c.ponerVolumen(ajustes.get("volumen"))
		if "velocidad" in claves:
			c.ponerVelocidad(ajustes.get("velocidad"))
		if self.ventana is not None:
			_enGui(self.ventana.aplicarOpciones)

	def restaurarDefecto(self, parent=None) -> bool:
		"""Vuelve a los valores por defecto (incluidos usuario y contraseña). Debe ir en el hilo de la interfaz."""
		import wx

		from .dialogos import mensaje, preguntar

		if not wx.IsMainThread():
			_enGui(self.restaurarDefecto, parent)
			return False
		ventana = parent if parent is self.ventana else None
		if (ajustes.estado.ventanaAbierta and ventana is None) or (self.control is not None and self.control.hayReproduccion()):
			mensaje(
				"El complemento solo se puede volver a valores por defecto cuando no está cargada la interfaz y no hay nada reproduciéndose."
				if ventana is None
				else "El complemento solo se puede volver a valores por defecto cuando no hay nada reproduciéndose.",
				"Información",
				parent=parent,
			)
			return False
		texto = (
			"El complemento borrará toda la configuración guardada (incluidos el usuario y la contraseña) "
			"y volverá a valores por defecto.\n\n¿Está seguro de que desea continuar?"
		)
		if not preguntar(texto, parent):
			return False
		ajustes.restaurarDefecto()
		credenciales.borrar()
		if self.control is not None:
			self.control.cancelarTemporizador()
			if self.control.reproductorCreado():
				self.control.ponerVolumen(ajustes.get("volumen"))
				self.control.ponerVelocidad(ajustes.get("velocidad"))
				self.control.setDispositivo("")
		if self.ventana is not None:
			self.ventana.aplicarOpciones()
		informar("Valores por defecto restaurados", 0.2)
		return True

	def abrirDocumentacion(self) -> None:
		ruta = ajustes.rutaDocumentacion()
		try:
			os.startfile(ruta)
		except Exception:
			log.exception("Error al abrir la documentación")

	# ================================================================ órdenes
	def _comprobarExterno(self) -> bool:
		"""Comprobaciones comunes de las órdenes de control externo."""
		if ajustes.estado.ventanaAbierta:
			hablar(MSG_VENTANA_ABIERTA)
			return False
		if self.control is None or not self.control.hayReproduccion():
			hablar(SIN_REPRODUCCION)
			return False
		return True

	@script(description="Muestra la ventana de Audiocinemateca", category=CATEGORIA)
	def script_inicio(self, gesture) -> None:
		self.iniciar()

	@script(description="Muestra la ventana de Opciones", category=CATEGORIA)
	def script_opciones(self, gesture) -> None:
		self.abrirOpciones()

	@script(description="Bajar volumen", category=CATEGORIA)
	def script_BajarVolumen(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		if ajustes.get("volumen") <= 0:
			hablar("No se puede bajar más el volumen. Ya se encuentra al 0%")
			return
		hablar(f"Volumen al {self.control.cambiarVolumen(-1)}%")

	@script(description="Subir volumen", category=CATEGORIA)
	def script_SubirVolumen(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		if ajustes.get("volumen") >= 100:
			hablar("No se puede subir más el volumen. Ya se encuentra al 100%")
			return
		hablar(f"Volumen al {self.control.cambiarVolumen(1)}%")

	@script(description="Bajar velocidad", category=CATEGORIA)
	def script_BajarVelocidad(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		if ajustes.get("velocidad") <= 0:
			hablar("No se puede bajar más la velocidad. Ya se encuentra al mínimo posible")
			return
		hablar(f"Velocidad {ajustes.LISTA_VELOCIDAD[self.control.cambiarVelocidad(-1)]}")

	@script(description="Subir velocidad", category=CATEGORIA)
	def script_SubirVelocidad(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		if ajustes.get("velocidad") >= len(ajustes.LISTA_VELOCIDAD) - 1:
			hablar("No se puede subir más la velocidad. Ya se encuentra al máximo")
			return
		hablar(f"Velocidad {ajustes.LISTA_VELOCIDAD[self.control.cambiarVelocidad(1)]}")

	@script(description="Atrasar la reproducción", category=CATEGORIA)
	def script_Atrasar(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		self.control.atrasar()
		hablar(f"Atrasando {ajustes.LISTA_ATRASAR[ajustes.get('atrasar')]}")

	@script(description="Adelantar la reproducción", category=CATEGORIA)
	def script_Adelantar(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		self.control.adelantar()
		hablar(f"Adelantando {ajustes.LISTA_ADELANTAR[ajustes.get('adelantar')]}")

	@script(description="Reproducir / Pausar la reproducción", category=CATEGORIA)
	def script_ReproducirPausar(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		anterior = self.control.reproductor.estado()
		self.control.reproducirPausar()
		hablar("Pausando..." if anterior == REPRODUCIENDO else "Reproduciendo...")

	@script(description="Detener la reproducción", category=CATEGORIA)
	def script_Detener(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		self.control.detener()
		hablar("Detenido")

	@script(description="Información de la reproducción", category=CATEGORIA)
	def script_Informacion(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		transcurrido, total = self.control.textoTiempos()
		hablar(f"Tiempo transcurrido: {transcurrido} / Tiempo total: {total}")

	@script(description="Anuncia el título del contenido en reproducción", category=CATEGORIA)
	def script_TituloActual(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		titulo = self.control.reproductor.titulo
		hablar(f"Reproduciendo: {titulo}" if titulo else "Contenido en reproducción")

	@script(description="Anuncia el tiempo restante de reproducción", category=CATEGORIA)
	def script_TiempoRestante(self, gesture) -> None:
		if not self._comprobarExterno():
			return
		hablar(f"Tiempo restante: {self.control.textoRestante()}")

	@script(description="Anuncia el tiempo restante del temporizador de sueño", category=CATEGORIA)
	def script_Temporizador(self, gesture) -> None:
		if ajustes.estado.ventanaAbierta:
			hablar(MSG_VENTANA_ABIERTA)
			return
		if self.control is None:
			hablar("Temporizador de sueño no activo")
			return
		hablar(self.control.infoTemporizador())

	@script(description="Cancela el temporizador de sueño", category=CATEGORIA)
	def script_CancelarTemporizador(self, gesture) -> None:
		if ajustes.estado.ventanaAbierta:
			hablar(MSG_VENTANA_ABIERTA)
			return
		if ajustes.estado.temporizadorActivo and self.control is not None:
			self.control.cancelarTemporizador()
			hablar("Temporizador de sueño cancelado")
		else:
			hablar("No hay temporizador de sueño activo")
