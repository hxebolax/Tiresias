# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Categoría «zRadio BASS» del cuadro de Opciones de Tiresias.

Sustituye al diálogo «Configuración» del original (pestañas General, Caché
y Grabaciones; el botón Restablecer es el de valores de fábrica del cuadro
de Opciones) y añade reproducción, dispositivo de salida y efectos.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

import wx

from tiresias.gui import settings as S
from tiresias.gui.helpers import speakMessage
from tiresias.log import getLogger

from ..zr_core.config import SECTION, userMusicFolder
from ..zr_core.localization import TOP_CODE, sorted_countries

if TYPE_CHECKING:
	from ..zr_core.app import RadioApp

log = getLogger("zRadioBASS.ui")

PANEL_ID = "zRadioBASS"
PANEL_TITLE = "zRadio BASS"

G_GENERAL = "General"
G_PLAYBACK = "Reproducción"
G_EFFECTS = "Efectos de sonido"
G_CACHE = "Caché"
G_RECORDINGS = "Grabaciones"


def _countryChoices() -> list[tuple[str, str]]:
	return [(TOP_CODE, "Todas las populares")] + list(sorted_countries())


def make_panel_class(get_app: Callable[[], "RadioApp | None"]) -> type:
	"""Clase del panel (recibe una función que devuelve la aplicación)."""

	def deviceChoices() -> list[tuple[str, str]]:
		names: list[str] = []
		app = get_app()
		if app is not None:
			names = app.player.list_output_devices()
		return [("", "Predeterminado de Windows")] + [(n, n) for n in names]

	class ZRadioPanel(S.ConfigPanel):
		title = PANEL_TITLE
		section = SECTION

		def getFields(self) -> list[S.Field]:
			return [
				S.Bool("checkInternetOnStart", "Verificar la conexión a Internet al abrir la ventana", group=G_GENERAL),
				S.Bool("rememberLastStation", "Recordar la última emisora reproducida", group=G_GENERAL),
				S.Bool("resumeOnStart", "Reproducir la última emisora al iniciar Tiresias", group=G_GENERAL),
				S.Choice("defaultCountry", "País de la pestaña General:", _countryChoices, group=G_GENERAL),
				S.Int("searchLimit", "Número máximo de resultados de búsqueda:", 10, 100000, group=G_GENERAL),
				S.Bool("hideBroken", "Ocultar las emisoras que no funcionan", group=G_GENERAL),
				S.Choice("outputDevice", "Dispositivo de salida:", deviceChoices, group=G_PLAYBACK),
				S.Int("volumeStep", "Paso del volumen (%):", 1, 25, group=G_PLAYBACK),
				S.Bool("autoReconnect", "Reconectar automáticamente si se corta la emisora", group=G_PLAYBACK),
				S.Bool("announceTitle", "Anunciar el título de cada canción nueva", group=G_PLAYBACK),
				S.Bool("announceConnected", "Anunciar cuando la emisora empiece a sonar", group=G_PLAYBACK),
				S.Slider("eqBass", "Graves (dB):", -12, 12, group=G_EFFECTS, pageSize=3),
				S.Slider("eqMid", "Medios (dB):", -12, 12, group=G_EFFECTS, pageSize=3),
				S.Slider("eqTreble", "Agudos (dB):", -12, 12, group=G_EFFECTS, pageSize=3),
				S.Slider("balance", "Balance (izquierda -100, derecha 100):", -100, 100, group=G_EFFECTS, pageSize=10),
				S.Bool("cacheEnabled", "Habilitar caché de resultados", group=G_CACHE),
				S.Int("cacheDays", "Duración de la caché (días):", 1, 30, group=G_CACHE),
				S.Text("recordingDirectory", "Carpeta para guardar las grabaciones:", group=G_RECORDINGS),
			]

		def makeExtraSettings(self, builder: S.SettingsBuilder) -> None:
			cache = self._groups.get(G_CACHE, builder)
			btn = cache.addButton("&Vaciar la caché ahora")
			btn.Bind(wx.EVT_BUTTON, self._onClearCache)
			rec = self._groups.get(G_RECORDINGS, builder)
			music = userMusicFolder() or "la carpeta de datos del complemento"
			rec.addStaticText(f"Si se deja vacía, se usa la carpeta Música del usuario ({music}). Las grabaciones se guardan en WAV.")
			row = wx.BoxSizer(wx.HORIZONTAL)
			browse = wx.Button(rec.parent, label="E&xaminar...")
			default = wx.Button(rec.parent, label="&Usar la carpeta por defecto")
			row.Add(browse, 0, wx.RIGHT, 6)
			row.Add(default, 0)
			rec.sizer.Add(row, 0, wx.BOTTOM, 4)
			browse.Bind(wx.EVT_BUTTON, self._onBrowse)
			default.Bind(wx.EVT_BUTTON, lambda e: self._dirCtrl().SetValue(""))
			app = get_app()
			if app is not None and not app.player.available:
				builder.addStaticText("Aviso: no se pudo cargar BASS; la reproducción no funcionará.")

		def _dirCtrl(self) -> wx.TextCtrl:
			return self.getControl("recordingDirectory")

		def _onBrowse(self, event: Any) -> None:
			ctrl = self._dirCtrl()
			with wx.DirDialog(self, "Seleccione la carpeta para las grabaciones", defaultPath=ctrl.GetValue() or userMusicFolder(), style=wx.DD_DEFAULT_STYLE | wx.DD_DIR_MUST_EXIST) as dlg:
				if dlg.ShowModal() == wx.ID_OK:
					ctrl.SetValue(dlg.GetPath())
			ctrl.SetFocus()

		def _onClearCache(self, event: Any) -> None:
			app = get_app()
			if app is None:
				return
			n = app.clear_cache()
			speakMessage(f"Caché vaciada ({n} respuestas)")

		def isValid(self) -> bool:
			import os

			path = (self._dirCtrl().GetValue() or "").strip()
			if path and not os.path.isdir(path):
				S.showError(f"La carpeta de grabaciones no existe:\n{path}", self)
				return False
			return True

		def afterSave(self, changes: dict) -> None:
			app = get_app()
			if app is not None:
				try:
					app.apply_options()
				except Exception:
					log.exception("No se pudieron aplicar las opciones de zRadio BASS")

	return ZRadioPanel


def register(get_app: Callable[[], "RadioApp | None"]) -> None:
	cls = make_panel_class(get_app)
	S.registerPanel(PANEL_ID, PANEL_TITLE, cls)


def unregister() -> None:
	S.unregisterPanel(PANEL_ID)
