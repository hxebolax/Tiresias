"""Panel «Aplicaciones» del diálogo de opciones.

Reúne las opciones de los módulos de aplicación incorporados: modo dormir
(permanente y por perfil), Word, Excel, PowerPoint, correo (Outlook y Thunderbird),
aplicaciones de chat y reuniones, reproductores y Explorador de Windows.
"""

from __future__ import annotations

from ..i18n import _
from . import settings as S

OPEN_MESSAGE_CHOICES = [
	("body", _("leer solo el cuerpo del mensaje")),
	("none", _("no leer nada (solo el asunto)")),
	("full", _("lo normal de la aplicación")),
]

READ_LINE_CHOICES = [
	("start", _("desde el principio de la fila o columna")),
	("current", _("desde la celda actual")),
]

ALERT_MODE_CHOICES = [
	("all", _("leer los avisos")),
	("beep", _("solo un sonido")),
	("off", _("ningún aviso")),
]


class AppsPanel(S.ConfigPanel):
	title = _("Aplicaciones")
	section = "appModules"

	def getFields(self) -> list[S.Field]:
		gSleep = _("Modo dormir")
		gWord = _("Microsoft Word")
		gExcel = _("Microsoft Excel")
		gPpt = _("Microsoft PowerPoint")
		gMail = _("Correo (Outlook y Thunderbird)")
		gChat = _("Chat y reuniones (Teams, Zoom, Discord, Telegram, Slack)")
		gOther = _("Otras aplicaciones")
		gCharts = _("Gráficos de Office")
		gGoogle = _("Google Docs y Hojas de cálculo (en el navegador)")
		from ..appmodules import _gsuite  # noqa: F401 - registra la sección googleApps

		# Las páginas, los comentarios, las revisiones, las listas y los títulos de las
		# tablas de Word y Excel siguen la categoría «Formato de documento», como en NVDA.
		return [
			S.ListText("sleepApps", _("Aplicaciones con modo dormir permanente (nombres de ejecutable separados por comas):"), group=gSleep),
			# Pensada para perfiles asociados a una aplicación (#3721).
			S.Bool("enabled", _("Modo dormir en la aplicación activa mientras esta configuración o perfil esté activo"), section="sleepMode", group=gSleep),
			S.Bool("reportFormattingShortcuts", _("Confirmar los atajos de formato (negrita, alineación, sangría...)"), section="officeWord", group=gWord),
			S.Bool("reportCoordinates", _("Leer la dirección de la celda (A1, B2...)"), section="officeExcel", group=gExcel),
			S.Bool("reportCellDetails", _("Avisar de fórmulas, comentarios, notas, celdas combinadas y validación"), section="officeExcel", group=gExcel),
			S.Bool("reportSelection", _("Anunciar el rango seleccionado al ampliar la selección"), section="officeExcel", group=gExcel),
			S.Int("watchedCellsInterval", _("Comprobar las celdas vigiladas cada (milisegundos):"), 250, 60000, section="officeExcel", group=gExcel),
			S.Choice("readLineFrom", _("Al leer una fila o columna entera, empezar:"), READ_LINE_CHOICES, section="officeExcel", group=gExcel),
			S.Bool("readLineSkipBlank", _("Saltar las celdas vacías al leer una fila o columna"), section="officeExcel", group=gExcel),
			S.Bool("readLineHeaders", _("Decir el título de cada celda al leer una fila o columna"), section="officeExcel", group=gExcel),
			S.Bool("reportNotesIndicator", _("Indicar si una diapositiva tiene notas"), section="officePowerPoint", group=gPpt),
			S.Bool("reportHiddenSlides", _("Indicar si una diapositiva está oculta"), section="officePowerPoint", group=gPpt),
			S.Bool("readSlideOnShow", _("Leer cada diapositiva durante la presentación"), section="officePowerPoint", group=gPpt),
			S.Bool("readEquations", _("Leer las ecuaciones con el motor de matemáticas (si no, solo se dice «ecuación»)"), section="officePowerPoint", group=gPpt),
			S.Bool("reportHeaders", _("Decir los títulos de fila y columna fijados al moverse por las celdas"), section="googleApps", group=gGoogle),
			S.Bool("announceTips", _("Recordar cómo activar la compatibilidad con lectores de pantalla al abrir un documento"), section="googleApps", group=gGoogle),
			S.Choice("openMessageReading", _("Al abrir un mensaje:"), OPEN_MESSAGE_CHOICES, section="mail", group=gMail),
			S.Choice("alertMode", _("Avisos de la aplicación:"), ALERT_MODE_CHOICES, section="chatApps", group=gChat),
			S.Bool("alertChat", _("Mensajes de chat"), section="chatApps", group=gChat),
			S.Bool("alertJoinLeave", _("Entradas y salidas de participantes"), section="chatApps", group=gChat),
			S.Bool("alertHands", _("Manos levantadas"), section="chatApps", group=gChat),
			S.Bool("alertMute", _("Silenciar y activar micrófonos"), section="chatApps", group=gChat),
			S.Bool("alertRecording", _("Grabación y transcripción"), section="chatApps", group=gChat),
			S.Bool("alertSharing", _("Compartir pantalla"), section="chatApps", group=gChat),
			S.Bool("alertOther", _("Otros avisos"), section="chatApps", group=gChat),
			S.Int("historySize", _("Avisos que se guardan en el historial:"), 10, 1000, section="chatApps", group=gChat),
			S.Bool("pointTones", _("Tono proporcional al valor al recorrer los puntos de un gráfico"), section="charts", group=gCharts),
			S.Int("toneDuration", _("Duración de cada tono de los gráficos (milisegundos):"), 30, 1000, section="charts", group=gCharts),
			S.Bool("announceTrackChanges", _("Anunciar los cambios de canción (Spotify, foobar2000, Winamp)"), section="media", group=gOther),
			S.Bool("reportDetailsColumns", _("Leer las columnas de detalles en las carpetas del Explorador"), section="explorer", group=gOther),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		# El modo dormir por configuración solo tiene sentido en un perfil: en la
		# configuración normal dormiría todas las aplicaciones (#3721). Si ya
		# estuviera marcada, se deja activa para poder desmarcarla.
		from ..config import conf

		sleep = self.getControl("enabled", "sleepMode")
		if sleep is not None and not (conf.editProfile or conf.activeProfileName) and not sleep.GetValue():
			sleep.Enable(False)
			sleep.SetToolTip(_("Solo se puede marcar al editar un perfil (Perfiles de configuración)"))

	def afterSave(self, changes: dict) -> None:
		if ("appModules", "sleepApps") in changes:
			from .. import queue_handler

			queue_handler.queueFunction(_applySleepApps)


def _applySleepApps() -> None:
	"""Aplica la lista a los módulos ya cargados."""
	from ..appmodules import handler
	from ..config import conf
	from ..input import core as inputCore

	names = {n.lower() for n in conf["appModules"]["sleepApps"] or []}
	for app in handler.getRunningModules():
		app.sleepMode = app.appName.lower() in names
	inputCore.manager.updateChain()


def register() -> None:
	S.registerPanel("apps", AppsPanel.title, AppsPanel)
