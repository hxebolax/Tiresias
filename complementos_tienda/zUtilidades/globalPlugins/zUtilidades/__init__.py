"""zUtilidades para Tiresias: conjunto de utilidades para Windows.

Versión para Tiresias del complemento de NVDA de Héctor J. Benítez Corredera
(«zUtilidades para NVDA», GPL). Módulos:

- Lanzador de aplicaciones (aplicaciones, órdenes de CMD, carpetas, accesos
  directos y aplicaciones instaladas, por categorías).
- Notas rápidas (por categorías; también desde cualquier sitio con el texto
  seleccionado).

Cada módulo tiene su ventana (una pulsación de su orden) y su menú virtual
(dos pulsaciones). Las órdenes no tienen tecla asignada: se asignan en
Gestos de entrada, categoría «zUtilidades». Entradas en Herramientas >
zUtilidades y opciones en la categoría «zUtilidades» de las Opciones.
"""

from __future__ import annotations

from tiresias import queue_handler
from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from . import datos, estado, sistema
from .menu_virtual import MenuVirtual

log = getLogger("zUtilidades")

CATEGORIA = "zUtilidades"
MENU_ID = "zUtilidades"
PANEL_ID = "zUtilidades"
MSG_SELECCIONE = "Seleccione un texto para poder agregar a una nota rápida"
MSG_SIN_TITULO = "No se pudo capturar el título"


def _politicaSegura() -> bool:
	"""Tiresias en modo seguro (pantallas de inicio de sesión)."""
	try:
		from tiresias.config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def _modoSeguro() -> bool:
	"""Pantallas seguras o sesión bloqueada: no se permite lanzar nada."""
	if _politicaSegura():
		return True
	try:
		from tiresias.a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		return False


def _panelClass():
	from tiresias.gui import settings as S

	class PanelZUtilidades(S.ConfigPanel):
		title = "zUtilidades"
		section = estado.SECCION
		fields = [S.Bool(clave, texto) for clave, texto in estado.ETIQUETAS]

	return PanelZUtilidades


def _enGui(func, *args) -> None:
	from tiresias.gui.helpers import runOnGui

	runOnGui(func, *args)


def _abrirLanzador() -> None:
	from . import lanzador

	lanzador.abrir()


def _abrirNotas() -> None:
	from . import notas

	notas.abrir()


def _abrirNotaRapida(texto, titulo, nueva) -> None:
	from . import notas

	notas.abrirNotaRapida(texto, titulo, nueva)


class GlobalPlugin(_Base):
	scriptCategory = CATEGORIA

	def __init__(self) -> None:
		super().__init__()
		self.menu = MenuVirtual()
		self._pendiente: int | None = None
		estado.registrarOpciones()
		if _politicaSegura():
			return
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, "&zUtilidades", self._entradasMenu, submenu=True)
		except Exception:
			log.debug("No se pudo añadir zUtilidades al menú Herramientas", exc_info=True)
		try:
			from tiresias.gui import settings as S

			cls = _panelClass()
			S.registerPanel(PANEL_ID, cls.title, cls)
		except Exception:
			log.debug("No se pudo añadir la categoría de zUtilidades a las opciones", exc_info=True)

	# ------------------------------------------------------------------ menú Herramientas
	def _entradasMenu(self) -> list:
		return [
			("&Lanzador de Aplicaciones", self._desdeMenu(_abrirLanzador)),
			("&Notas rápidas", self._desdeMenu(_abrirNotas)),
		]

	def _desdeMenu(self, abrir):
		def accion() -> None:
			if self.menu.activo or estado.ventanaAbierta:
				sistema.mensaje(estado.MSG_INSTANCIA)
				return
			abrir()

		return accion

	def terminate(self) -> None:
		if self._pendiente is not None:
			queue_handler.cancelCallLater(self._pendiente)
			self._pendiente = None
		if self.menu.activo:
			self.menu.terminar()
		try:
			from tiresias import gui

			gui.unregisterToolsMenuItem(MENU_ID)
		except Exception:
			pass
		try:
			from tiresias.gui import settings as S

			S.unregisterPanel(PANEL_ID)
		except Exception:
			pass
		_enGui(_cerrarVentanas)
		super().terminate()

	# ------------------------------------------------------------------ pulsaciones
	def _pulsacion(self, simple, doble) -> None:
		"""Una pulsación ejecuta ``simple`` (pasado el tiempo de pulsación
		múltiple); dos pulsaciones, ``doble``."""
		from tiresias.config import conf
		from tiresias.input import core as inputCore

		if inputCore.getLastScriptRepeatCount() == 0:
			if self._pendiente is not None:
				queue_handler.cancelCallLater(self._pendiente)
			try:
				espera = int(conf["keyboard"]["multiPressTimeout"])
			except Exception:
				espera = 500
			self._pendiente = queue_handler.callLater(espera, self._simple, simple)
		else:
			if self._pendiente is not None:
				queue_handler.cancelCallLater(self._pendiente)
				self._pendiente = None
			doble()

	def _simple(self, simple) -> None:
		self._pendiente = None
		simple()

	def _bloqueado(self) -> bool:
		if _modoSeguro():
			sistema.mensaje("Esta función no está disponible en modo seguro.")
			return True
		return False

	# ------------------------------------------------------------------ órdenes
	@script(description="Con una pulsación muestra la ventana del lanzador de aplicaciones, con doble pulsación el menú virtual del lanzador de aplicaciones", category=CATEGORIA)
	def script_zLauncher(self, gesture) -> None:
		if self._bloqueado():
			return
		self._pulsacion(lambda: self._abrirVentana(_abrirLanzador), lambda: self.menu.activar(datos.LANZADOR))

	@script(description="Con una pulsación muestra la ventana de notas rápidas, con doble pulsación el menú virtual de notas rápidas", category=CATEGORIA)
	def script_zNotes(self, gesture) -> None:
		if self._bloqueado():
			return
		self._pulsacion(lambda: self._abrirVentana(_abrirNotas), lambda: self.menu.activar(datos.NOTAS))

	@script(description="Con una pulsación agrega una nota rápida del texto seleccionado, con doble pulsación agrega una nueva nota rápida", category=CATEGORIA)
	def script_zNotesCopy(self, gesture) -> None:
		if self._bloqueado():
			return
		self._pulsacion(self.notaDeSeleccion, self.notaNueva)

	def _abrirVentana(self, abrir) -> None:
		if estado.ventanaAbierta or self.menu.activo:
			sistema.mensaje(estado.MSG_INSTANCIA)
			return
		_enGui(abrir)

	def _titulo(self) -> str | None:
		if not estado.opcion("tituloCaptura"):
			return None
		return sistema.tituloVentana() or MSG_SIN_TITULO

	def notaDeSeleccion(self) -> None:
		"""Abre «Agregar nota rápida del texto seleccionado» (hilo del núcleo)."""
		if estado.ventanaAbierta or self.menu.activo:
			sistema.mensaje(estado.MSG_INSTANCIA)
			return
		texto = sistema.textoSeleccionado()
		if not texto:
			sistema.mensaje(MSG_SELECCIONE)
			return
		if estado.opcion("urlCaptura"):
			texto = sistema.unirTextoYUrl(texto, sistema.urlDocumento())
		_enGui(_abrirNotaRapida, texto, self._titulo(), False)

	def notaNueva(self) -> None:
		"""Abre «Añadir una nueva nota rápida» (hilo del núcleo)."""
		if estado.ventanaAbierta or self.menu.activo:
			sistema.mensaje(estado.MSG_INSTANCIA)
			return
		texto = sistema.urlDocumento() if estado.opcion("urlCaptura") else None
		_enGui(_abrirNotaRapida, texto, self._titulo(), True)

	# ------------------------------------------------------------------ menú virtual
	def getScript(self, gesture):
		if not self.menu.activo:
			return super().getScript(gesture)
		ids = list(getattr(gesture, "identifiers", None) or [])
		if not ids or not all(i.startswith("kb") for i in ids):
			# Líneas braille y otros dispositivos: siguen funcionando.
			return super().getScript(gesture)
		func = super().getScript(gesture)
		if func is not None:
			# Las órdenes de zUtilidades asignadas por el usuario (por ejemplo,
			# volver a pulsar dos veces la del módulo para salir).
			return func
		tecla = getattr(gesture, "normalizedKeys", "") or ids[-1].split(":", 1)[-1]
		accion = self.menu.accionParaTecla(tecla)

		def ordenMenuVirtual(gesture) -> None:
			if self.menu.activo:
				accion()

		return ordenMenuVirtual


def _cerrarVentanas() -> None:
	"""Cierra las ventanas abiertas del complemento (al descargarlo)."""
	import sys

	import wx

	# Sin importarlos: si nunca se abrió una ventana, sus módulos no están
	# cargados, y al cerrar Tiresias ya no se pueden importar (el complemento
	# se ha descargado).
	comun = sys.modules.get(f"{__name__}.comun")
	notas = sys.modules.get(f"{__name__}.notas")
	clases = tuple(c for c in (getattr(comun, "VentanaBase", None), getattr(notas, "DialogoNotaRapida", None)) if c is not None)
	if not clases:
		estado.ventanaAbierta = False
		return
	for w in list(wx.GetTopLevelWindows()):
		try:
			if isinstance(w, clases):
				w.cerrar()
		except Exception:
			pass
	estado.ventanaAbierta = False
