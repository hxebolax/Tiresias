"""TCA SystemUtilities para Tiresias: acciones rápidas de Windows.

Versión para Tiresias del complemento de NVDA de Peter Reina
(«TCA SystemUtilities», GPL), con el lanzador de consolas de Héctor J.
Benítez Corredera. Apagar, reiniciar (con el sonido clásico de Windows),
hibernar, suspender, modo seguro, BIOS-UEFI; reiniciar el Explorador, cerrar
aplicaciones y tareas que no responden, menú de contexto clásico; SFC, DISM,
limpieza de disco, planes de energía, caché DNS, almacenamiento reservado;
control de cuentas de usuario y Microsoft Defender; webcam, opciones de voz
y de sonido; asistentes de Windows; y, en el Explorador, copiar la ruta o la
lista de archivos, abrir consolas en la carpeta y ocultar o mostrar archivos.

Cada acción es una orden de la categoría «TCA SystemUtilities» de Gestos de
entrada (sin tecla asignada, como el original). Todas están también en
Herramientas > TCA SystemUtilities y en un menú emergente que se abre con
Tiresias+Mayúsculas+8.
"""

from __future__ import annotations

from tiresias.baseobject import script
from tiresias.log import getLogger
from tiresias.plugins import GlobalPlugin as _Base

from . import explorador, funciones

log = getLogger("TCA_SystemUtilities")

CATEGORIA = "TCA SystemUtilities"
MENU_ID = "TCA_SystemUtilities"
PANEL_ID = "TCA_SystemUtilities"
#: Gesto del menú emergente (nuevo en Tiresias: el original no tiene teclas asignadas).
GESTO_MENU = "kb:tiresias+shift+8"
MSG_MODO_SEGURO = "Esta función no está disponible en modo seguro."


def _politicaSegura() -> bool:
	try:
		from tiresias.config import policy

		return bool(policy.policy.secureMode)
	except Exception:
		return False


def _modoSeguro() -> bool:
	"""Pantallas seguras o sesión bloqueada: no se ejecuta nada."""
	if _politicaSegura():
		return True
	try:
		from tiresias.a11y import system

		return bool(system.isLockScreenActive())
	except Exception:
		return False


def _enGui(func, *args) -> None:
	from tiresias.gui.helpers import runOnGui

	runOnGui(func, *args)


def _panelClass():
	from tiresias.gui import settings as S

	class PanelTCA(S.ConfigPanel):
		title = "TCA SystemUtilities"
		section = funciones.SECCION
		fields = [S.Bool("preguntarPerfilLimpieza", "&Preguntar si se quiere crear un perfil de limpieza antes de limpiar el disco")]

	return PanelTCA


class GlobalPlugin(_Base):
	scriptCategory = CATEGORIA

	def __init__(self) -> None:
		super().__init__()
		self._menuAbierto = False
		funciones.registrarOpciones()
		if _politicaSegura():
			return
		try:
			from tiresias import gui

			gui.registerToolsMenuItem(MENU_ID, "&TCA SystemUtilities", self._entradasHerramientas, submenu=True)
		except Exception:
			log.debug("No se pudo añadir TCA SystemUtilities al menú Herramientas", exc_info=True)
		try:
			from tiresias.gui import settings as S

			cls = _panelClass()
			S.registerPanel(PANEL_ID, cls.title, cls)
		except Exception:
			log.debug("No se pudo añadir la categoría de TCA SystemUtilities a las opciones", exc_info=True)

	def terminate(self) -> None:
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
		super().terminate()

	# ------------------------------------------------------------------ acciones
	def ejecutarAccion(self, idAccion: str, ctx: explorador.Contexto | None = None) -> None:
		"""Ejecuta una acción del catálogo (desde una orden o un menú)."""
		if _modoSeguro():
			funciones.mensaje(MSG_MODO_SEGURO)
			return
		accion = funciones.POR_ID[idAccion]
		if ctx is None:
			# Antes de que se abra ningún diálogo: la ventana del Explorador.
			ctx = explorador.capturarContexto()
		_enGui(accion.funcion, ctx)

	# ------------------------------------------------------------------ menús
	def entradasMenu(self, ctx: explorador.Contexto) -> list:
		"""Submenús con todas las acciones (formato de ``gui.registerToolsMenuItem``)."""
		salida = []
		for grupo, etiqueta in funciones.GRUPOS:
			sub = [(a.etiqueta, self._accionMenu(a.id, ctx)) for a in funciones.ACCIONES if a.grupo == grupo]
			salida.append((etiqueta, sub))
		return salida

	def _accionMenu(self, idAccion: str, ctx: explorador.Contexto):
		def accion() -> None:
			self.ejecutarAccion(idAccion, ctx)

		return accion

	def _entradasHerramientas(self) -> list:
		# Se llama al abrir el menú de Tiresias, antes de que pase a primer plano.
		return self.entradasMenu(explorador.capturarContexto(leerFoco=False))

	@script(description="Muestra el menú de TCA SystemUtilities con todas sus acciones", category=CATEGORIA, gesture=GESTO_MENU)
	def script_mostrarMenu(self, gesture) -> None:
		if _modoSeguro():
			funciones.mensaje(MSG_MODO_SEGURO)
			return
		if self._menuAbierto:
			return
		_enGui(self._mostrarMenu, explorador.capturarContexto())

	def _mostrarMenu(self, ctx: explorador.Contexto) -> None:
		import wx

		from tiresias import gui

		marco = getattr(gui, "mainFrame", None)
		if marco is None or self._menuAbierto:
			return
		self._menuAbierto = True
		acciones: dict[int, object] = {}
		menu = construirMenu(self.entradasMenu(ctx), acciones)
		try:
			marco.prePopup()
			try:
				elegido = marco.GetPopupMenuSelectionFromUser(menu, (0, 0))
			finally:
				marco.postPopup()
		finally:
			menu.Destroy()
			self._menuAbierto = False
		accion = acciones.get(elegido)
		if accion is not None:
			wx.CallAfter(accion)


def construirMenu(entradas: list, acciones: dict):
	"""``wx.Menu`` con las entradas; ``acciones`` recibe identificador → función."""
	import wx

	menu = wx.Menu()
	for etiqueta, destino in entradas:
		if isinstance(destino, (list, tuple)):
			menu.AppendSubMenu(construirMenu(list(destino), acciones), etiqueta)
		else:
			item = menu.Append(wx.ID_ANY, etiqueta)
			acciones[item.GetId()] = destino
	return menu


def _crearOrden(accion: funciones.Accion):
	def orden(self, gesture) -> None:
		self.ejecutarAccion(accion.id)

	orden.__name__ = orden.__qualname__ = "script_" + accion.id
	return script(description=accion.descripcion, category=CATEGORIA)(orden)


# Una orden por acción del catálogo (sin tecla: se asignan en Gestos de entrada).
for _accion in funciones.ACCIONES:
	setattr(GlobalPlugin, "script_" + _accion.id, _crearOrden(_accion))
del _accion
