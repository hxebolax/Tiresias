"""Paneles de Opciones del área de configuración.

- «Navegación por documentos» (``documentNavigation``): qué encuentra la
  tecla P del modo exploración y la expresión de los párrafos de texto.
- «Composición de entrada (IME)» (``inputComposition``).
- «Actualizaciones y complementos» (``update`` y ``addons``).
"""

from __future__ import annotations

import re
from typing import Any

import wx

from ..config import policy as policyModule
from ..i18n import _
from . import settings as S


class DocumentNavigationPanel(S.ConfigPanel):
	title = _("Navegación por documentos")
	section = "documentNavigation"

	def getFields(self) -> list[S.Field]:
		return [
			S.Choice(
				"paragraphStyle",
				_("Estilo de párrafo:"),
				[("application", _("El de la aplicación")), ("singleLineBreak", _("Un salto de línea")), ("multiLineBreak", _("Varios saltos de línea (línea en blanco)"))],
			),
			S.Choice(
				"paragraphQuickNav",
				_("La tecla P del modo exploración salta a:"),
				[
					("both", _("Párrafos marcados y párrafos de texto")),
					("role", _("Solo los párrafos marcados por la página")),
					("text", _("Solo los párrafos de texto")),
				],
			),
			S.Text("textParagraphRegex", _("Expresión regular de un párrafo de texto:")),
			S.Int("textParagraphMinLength", _("Longitud mínima de un párrafo de texto (caracteres):"), 0, 1000),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		btn = builder.addButton(_("Restablecer la &expresión por defecto"))
		btn.Bind(wx.EVT_BUTTON, self._onDefault)

	def _onDefault(self, evt: Any) -> None:
		from ..config import schema

		self.setControlValue("textParagraphRegex", schema.DEFAULTS["documentNavigation"]["textParagraphRegex"])

	def isValid(self) -> bool:
		pattern = self.getValue("textParagraphRegex") or ""
		try:
			re.compile(pattern)
		except re.error as e:
			S.showError(_("La expresión regular no es válida: {error}").format(error=e), self)
			ctrl = self.getControl("textParagraphRegex")
			if ctrl:
				ctrl.SetFocus()
			return False
		return True


class InputCompositionPanel(S.ConfigPanel):
	title = _("Composición de entrada (IME)")
	section = "inputComposition"
	fields = [
		S.Bool("reportCompositionStringChanges", _("Leer el texto mientras se compone")),
		S.Bool("reportCompositionFinalized", _("Leer el texto al confirmarlo")),
		S.Bool("announceSelectedCandidate", _("Anunciar el candidato seleccionado")),
		S.Bool("autoReportAllCandidates", _("Leer todos los candidatos al abrirse la lista")),
	]


class UpdatesPanel(S.ConfigPanel):
	title = _("Actualizaciones y complementos")
	section = "update"

	def getFields(self) -> list[S.Field]:
		gu = _("Actualizaciones de Tiresias")
		ga = _("Tienda de complementos")
		return [
			# Origen de las actualizaciones y de la tienda (1.0.13), ver updates.currentOrigin.
			S.Choice(
				"origin",
				_("Origen de las actualizaciones y de la tienda:"),
				[
					("ambos", _("Servidor del proyecto y GitHub")),
					("servidor", _("Solo el servidor del proyecto")),
					("github", _("Solo GitHub")),
					("propio", _("Servidor propio")),
				],
			),
			S.Text("serverUrl", _("Dirección del servidor propio:")),
			S.Bool("autoCheck", _("Buscar actualizaciones automáticamente"), group=gu),
			S.Int("intervalHours", _("Cada cuántas horas:"), 1, 720, group=gu),
			S.Choice("channel", _("Canal de actualizaciones:"), [("estable", _("estable")), ("beta", _("beta (versiones de prueba)"))], group=gu),
			S.Text("checkUrl", _("Dirección de comprobación (vacía: la del servidor de distribución):"), group=gu),
			S.Bool("autoCheckUpdates", _("Avisar de las actualizaciones de los complementos"), section="addons", group=ga),
			S.Text("catalogUrl", _("Dirección del catálogo (vacía: la del servidor de distribución):"), section="addons", group=ga),
		]

	def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
		from .. import updates

		btn = builder.addButton(_("&Buscar actualización ahora"))
		btn.Bind(wx.EVT_BUTTON, self._onCheck)
		btn.Enable(policyModule.isAllowed("updateCheck"))
		btn = builder.addButton(_("Abrir la &tienda de complementos"))
		btn.Bind(wx.EVT_BUTTON, lambda evt: __import__("tiresias.gui", fromlist=["showAddonStore"]).showAddonStore())
		btn.Enable(policyModule.isAllowed("addonStore"))
		# Las direcciones que fija la política no se pueden cambiar aquí (no tendrían efecto).
		fixed = False
		for kind, key, section in (("distribution", "serverUrl", "update"), ("update", "checkUrl", "update"), ("addonCatalog", "catalogUrl", "addons")):
			if policyModule.policy.url(kind):
				fixed = True
				ctrl = self.getControl(key, section)
				if ctrl:
					ctrl.Enable(False)
					ctrl.SetToolTip(_("Bloqueada por el administrador del equipo"))
		origin = self.getControl("origin")
		if origin is not None:
			if policyModule.policy.url("distribution"):
				# Con un servidor fijado por la política no hay origen que elegir.
				origin.Enable(False)
				origin.SetToolTip(_("Bloqueada por el administrador del equipo"))
			origin.Bind(wx.EVT_CHOICE, lambda evt: (self._syncOrigin(), evt.Skip()))
		self._syncOrigin()
		if fixed:
			builder.addStaticText(_("Las direcciones las fija el administrador del equipo."))
		elif updates.DISTRIBUTION_URL:
			parts = [_("Servidor del proyecto: {url}.").format(url=updates.DISTRIBUTION_URL.rstrip("/") + "/")]
			if updates.githubRepoUrl():
				parts.append(_("GitHub: {url}.").format(url=updates.githubRepoUrl()))
			builder.addStaticText(" ".join(parts))
		else:
			builder.addStaticText(_("No hay servidor de distribución: sin una dirección escrita aquí no se buscan actualizaciones y la tienda muestra el catálogo local."))

	def _serverUrlFixed(self) -> bool:
		from ..config import conf

		return bool(policyModule.policy.url("distribution")) or conf.isLocked("update", "serverUrl")

	def _syncOrigin(self) -> None:
		"""La dirección del servidor propio solo se escribe con «Servidor propio»."""
		ctrl = self.getControl("serverUrl")
		if ctrl is None or self._serverUrlFixed():
			return
		ctrl.Enable(self.getValue("origin") == "propio")

	def resetExtraToFactory(self) -> None:
		self._syncOrigin()

	def isValid(self) -> bool:
		from .helpers import urlProblem

		for key, section in (("serverUrl", "update"), ("checkUrl", "update"), ("catalogUrl", "addons")):
			problem = urlProblem(self.getValue(key, section) or "", allowLocal=True)
			if problem:
				S.showError(problem, self)
				ctrl = self.getControl(key, section)
				if ctrl:
					ctrl.SetFocus()
				return False
		if self.getValue("origin") == "propio" and not (self.getValue("serverUrl") or "").strip() and not self._serverUrlFixed():
			S.showError(_("Escriba la dirección del servidor propio o elija otro origen de las actualizaciones y de la tienda."), self)
			ctrl = self.getControl("serverUrl")
			if ctrl:
				ctrl.SetFocus()
			return False
		return True

	def onSave(self) -> None:
		# Con otro origen la dirección del servidor propio no se usa: se borra para que
		# no vuelva a contar como servidor propio (ver updates.currentOrigin).
		if self.getValue("origin") != "propio" and (self.getValue("serverUrl") or "").strip() and not self._serverUrlFixed():
			self.setControlValue("serverUrl", "")
		super().onSave()

	def _onCheck(self, evt: Any) -> None:
		from .. import queue_handler, updates

		queue_handler.queueFunction(updates.checkNow, True)

	def afterSave(self, changes: dict) -> None:
		if ("update", "autoCheck") in changes and changes[("update", "autoCheck")][1]:
			from .. import updates

			updates.scheduleAutomaticChecks()


def register() -> None:
	"""Añade las categorías (su sitio en la lista lo da ``settings.getPanelIds``)."""
	S.registerPanel("documentNavigation", DocumentNavigationPanel.title, DocumentNavigationPanel)
	S.registerPanel("inputComposition", InputCompositionPanel.title, InputCompositionPanel)
	S.registerPanel("updates", UpdatesPanel.title, UpdatesPanel)


register()
