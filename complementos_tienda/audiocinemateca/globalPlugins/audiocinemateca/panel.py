"""Categoría «Audiocinemateca» del diálogo de Opciones de Tiresias.

Las opciones del diálogo de opciones del original (mensajes informativos,
cantidad de resultados, tiempos de retroceso y avance y volver a valores por
defecto) más el volumen, la velocidad, el dispositivo de salida y la gestión
de la cuenta (cambiar usuario y contraseña o cerrar la sesión).
"""

from __future__ import annotations

import threading

import wx

from . import ajustes, credenciales, red

PANEL_ID = "audiocinemateca"

#: Complemento global en marcha (lo fija al iniciarse); el panel le avisa de los cambios.
complemento = None


def _opcionesDispositivo():
	opciones = [("", "Predeterminado de Windows")]
	try:
		from . import bass

		bass.cargar()
		opciones += [(n, n) for _num, n, _p in bass.dispositivos()]
	except Exception:
		pass
	return opciones


def crearClasePanel():
	from tiresias.gui import settings as S

	class PanelAudiocinemateca(S.ConfigPanel):
		title = "Audiocinemateca"
		section = ajustes.SECCION
		fields = [
			S.Bool("hablar", "Activar mensajes &informativos"),
			S.Choice("resultados", "Cantidad de &resultados a mostrar:", list(enumerate(ajustes.LISTA_RESULTADOS))),
			S.Choice("atrasar", "Tiempo para re&troceder:", list(enumerate(ajustes.LISTA_ATRASAR))),
			S.Choice("adelantar", "Tiempo para &adelantar:", list(enumerate(ajustes.LISTA_ADELANTAR))),
			S.Slider("volumen", "&Volumen del reproductor:", 0, 100),
			S.Choice("velocidad", "Ve&locidad de reproducción:", list(enumerate(ajustes.LISTA_VELOCIDAD))),
			S.Choice("dispositivo", "&Dispositivo de salida de audio:", _opcionesDispositivo),
		]

		def makeExtraSettings(self, builder) -> None:
			grupo = builder.group("Cuenta de la Audiocinemateca")
			self.lblCuenta = grupo.addStaticText(self._textoCuenta())
			self.btnCambiar = grupo.addButton("&Cambiar usuario y contraseña...")
			self.btnCerrarSesion = grupo.addButton("Cerrar &sesión (olvidar el usuario y la contraseña)")
			self.btnDefecto = builder.addButton("Volver a valores por &defecto...")
			self.btnCambiar.Bind(wx.EVT_BUTTON, self._onCambiar)
			self.btnCerrarSesion.Bind(wx.EVT_BUTTON, self._onCerrarSesion)
			self.btnDefecto.Bind(wx.EVT_BUTTON, self._onDefecto)
			self.btnCerrarSesion.Enable(ajustes.hayCredenciales())

		@staticmethod
		def _textoCuenta() -> str:
			if ajustes.hayCredenciales():
				return f"Sesión iniciada como: {ajustes.estado.usuario}"
			return "No hay ninguna sesión iniciada."

		def _refrescarCuenta(self) -> None:
			self.lblCuenta.SetLabel(self._textoCuenta())
			self.btnCerrarSesion.Enable(ajustes.hayCredenciales())
			self.relayout()

		def _onCambiar(self, evt) -> None:
			from .dialogos import DialogoLogin, mensaje

			dlg = DialogoLogin(self, editar=True)
			try:
				if dlg.ShowModal() != wx.ID_OK:
					return
				usuario, contrasena = dlg.usuario, dlg.contrasena
			finally:
				dlg.Destroy()
			self.btnCambiar.Disable()
			from .control import informar

			informar("Verificando credenciales...", 0)

			def trabajo():
				ok, error = red.verificarLogin(usuario, contrasena)
				wx.CallAfter(fin, ok, error)

			def fin(ok, error):
				if not self:
					return
				self.btnCambiar.Enable()
				if ok:
					credenciales.guardar(usuario, contrasena)
					self._refrescarCuenta()
					mensaje("Credenciales guardadas.", "Información", parent=self)
				else:
					mensaje(f"Las credenciales no son válidas.\n\nError: {error}", "Error", wx.OK | wx.ICON_ERROR, self)

			threading.Thread(target=trabajo, name="AudiocinematecaLogin", daemon=True).start()

		def _onCerrarSesion(self, evt) -> None:
			from .dialogos import preguntar

			if preguntar("Se olvidarán el usuario y la contraseña guardados. La próxima vez que inicie la Audiocinemateca se le pedirán de nuevo.\n¿Desea continuar?", self):
				credenciales.borrar()
				self._refrescarCuenta()

		def _onDefecto(self, evt) -> None:
			if complemento is not None and complemento.restaurarDefecto(self):
				for clave, valor in ajustes.DEFECTO.items():
					self.setControlValue(clave, valor)
				self._refrescarCuenta()

		def afterSave(self, changes) -> None:
			if complemento is not None:
				complemento.opcionesCambiadas({k for (_s, k) in changes})

	return PanelAudiocinemateca


def registrar() -> None:
	from tiresias.gui import settings as S

	cls = crearClasePanel()
	S.registerPanel(PANEL_ID, cls.title, cls)


def quitar() -> None:
	try:
		from tiresias.gui import settings as S

		S.unregisterPanel(PANEL_ID)
	except Exception:
		pass
