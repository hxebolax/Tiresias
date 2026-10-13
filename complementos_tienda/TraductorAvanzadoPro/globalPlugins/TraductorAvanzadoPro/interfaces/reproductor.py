"""Reproductor del audio de una traducción (botón «Escuchar»).

Usa ``wx.media.MediaCtrl`` del wxPython que trae Tiresias (el original
llevaba copias de ``wx.media`` para Python 3.11 y 3.13 que aquí no hacen
falta). El audio de Google es MP3; se guarda en un archivo temporal dentro
de la carpeta de datos del complemento y se borra al cerrar.

Teclas: F1 retroceder, F2 reproducir o pausar, F3 adelantar, F4 detener,
F5 y F6 bajar y subir el volumen, F7 y F8 bajar y subir la velocidad, F9 tiempo
transcurrido y total. Con Mayúsculas+F10 (o la tecla Aplicaciones) sobre los
botones Retroceder y Adelantar se elige el tamaño del salto.
"""

from __future__ import annotations

import os
import tempfile
from typing import Any, Callable

import wx

from tiresias.log import getLogger

from ..utilidades import lector

log = getLogger("TraductorAvanzadoPro")

TIEMPOS_TEXTO = ["1 segundo", "5 segundos", "10 segundos", "15 segundos", "30 segundos", "1 minuto"]
TIEMPOS_MS = [1000, 5000, 10000, 15000, 30000, 60000]
VELOCIDADES = ["0.5", "0.75", "1.0", "1.25", "1.5", "1.75", "2.0"]


def formatear_tiempo(ms: int) -> str:
	s = max(0, int(ms)) // 1000
	return f"{s // 60:02}:{s % 60:02}"


class WAVPlayer:
	"""Reproducción con ``MediaCtrl`` (sirve para MP3 y WAV pese al nombre del original)."""

	def __init__(self, parent: wx.Window, carpeta_temporal: str | None = None) -> None:
		try:
			import wx.media as wx_media
		except ImportError as e:
			raise ImportError("wx.media no está disponible en este sistema.") from e
		self._wx_media = wx_media
		self.media_ctrl = None
		for backend in (wx_media.MEDIABACKEND_WMP10, wx_media.MEDIABACKEND_DIRECTSHOW, ""):
			try:
				self.media_ctrl = wx_media.MediaCtrl(parent, szBackend=backend, size=(1, 1)) if backend else wx_media.MediaCtrl(parent, size=(1, 1))
				break
			except Exception:
				continue
		if self.media_ctrl is None:
			raise ImportError("No se pudo crear el reproductor multimedia.")
		self.media_ctrl.Hide()
		self.carpeta_temporal = carpeta_temporal
		self.current_volume = 0.5
		self.current_speed = 1.0
		self.is_playing = False
		self.is_paused = False
		self.cargado = False
		self._reproducir_al_cargar = False
		self.temp_file: str | None = None
		self.callback_fin: Callable[[], None] | None = None
		self.media_ctrl.Bind(wx_media.EVT_MEDIA_LOADED, self._on_cargado)
		self.media_ctrl.Bind(wx_media.EVT_MEDIA_FINISHED, self._on_fin)

	def cargar_audio(self, audio_bytes: bytes, extension: str = ".mp3") -> bool:
		self.limpiar()
		if self.carpeta_temporal:
			os.makedirs(self.carpeta_temporal, exist_ok=True)
		with tempfile.NamedTemporaryFile(delete=False, suffix=extension, dir=self.carpeta_temporal) as f:
			f.write(audio_bytes)
			self.temp_file = f.name
		self.cargado = False
		if not self.media_ctrl.Load(self.temp_file):
			raise OSError("Error al cargar el audio en el controlador.")
		return True

	def _aplicar_ajustes(self) -> None:
		try:
			self.media_ctrl.SetVolume(self.current_volume)
			self.media_ctrl.SetPlaybackRate(self.current_speed)
		except Exception:
			pass

	def _on_cargado(self, event: Any) -> None:
		self.cargado = True
		self._aplicar_ajustes()
		if self._reproducir_al_cargar:
			self._reproducir_al_cargar = False
			self.reproducir()

	def reproducir(self) -> None:
		if not self.temp_file:
			return
		if not self.cargado:
			self._reproducir_al_cargar = True
			return
		self.media_ctrl.Play()
		self._aplicar_ajustes()
		self.is_playing = True
		self.is_paused = False

	def pausar(self) -> None:
		self._reproducir_al_cargar = False
		self.media_ctrl.Pause()
		self.is_playing = False
		self.is_paused = True

	def detener(self) -> None:
		self._reproducir_al_cargar = False
		try:
			self.media_ctrl.Stop()
		except Exception:
			pass
		self.is_playing = False
		self.is_paused = False

	def fijar_volumen(self, vol_0_100: int) -> None:
		self.current_volume = max(0, min(100, int(vol_0_100))) / 100.0
		if self.cargado:
			self.media_ctrl.SetVolume(self.current_volume)

	def fijar_velocidad(self, multiplicador: float) -> None:
		self.current_speed = float(multiplicador)
		if self.cargado:
			self.media_ctrl.SetPlaybackRate(self.current_speed)

	def buscar(self, milisegundos: int, relativo: bool = True) -> None:
		nueva = self.media_ctrl.Tell() + milisegundos if relativo else milisegundos
		total = self.media_ctrl.Length()
		self.media_ctrl.Seek(max(0, min(nueva, total)))

	def obtener_estado_tiempo(self) -> str:
		return f"Tiempo: {formatear_tiempo(self.media_ctrl.Tell())} de {formatear_tiempo(self.media_ctrl.Length())}"

	def _on_fin(self, event: Any) -> None:
		self.is_playing = False
		self.is_paused = False
		if self.callback_fin:
			wx.CallAfter(self.callback_fin)

	def limpiar(self) -> None:
		self.detener()
		if self.temp_file:
			try:
				os.remove(self.temp_file)
			except OSError:
				# Aún abierto por el control: se borra al cerrar o al iniciar Tiresias.
				pass
		self.temp_file = None
		self.cargado = False

	def cerrar(self) -> None:
		self.detener()
		temporal, self.temp_file = self.temp_file, None
		try:
			self.media_ctrl.Destroy()
		except Exception:
			pass
		if temporal:
			try:
				os.remove(temporal)
			except OSError:
				pass


def limpiar_temporales(carpeta: str) -> None:
	"""Borra los audios temporales que quedaran de una sesión anterior."""
	try:
		for nombre in os.listdir(carpeta):
			try:
				os.remove(os.path.join(carpeta, nombre))
			except OSError:
				pass
	except OSError:
		pass


class DialogoReproductor(wx.Dialog):
	"""Reproductor con controles por teclado y menú de saltos."""

	def __init__(self, parent: wx.Window | None, plugin: Any, texto: str, audio: bytes) -> None:
		super().__init__(parent, title="Reproductor de audio", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.plugin = plugin
		self.audio = audio
		self.texto = texto
		self.player: WAVPlayer | None = None
		config = plugin.configuracion.config
		self.snd_vol = _entero(getattr(config, "volumen_reproductor", 50), 50, 0, 100)
		self.snd_vel_idx = _entero(getattr(config, "velocidad_audio", 2), 2, 0, len(VELOCIDADES) - 1)
		self.snd_rw_idx = _entero(getattr(config, "salto_atras", 1), 1, 0, len(TIEMPOS_MS) - 1)
		self.snd_ff_idx = _entero(getattr(config, "salto_adelante", 1), 1, 0, len(TIEMPOS_MS) - 1)
		self.panel = wx.Panel(self)
		self._crear_interfaz()
		carpeta = os.path.join(plugin.configuracion.ruta_config, "temp")
		self.player = WAVPlayer(self.panel, carpeta)
		self.player.callback_fin = self._on_audio_terminado
		self.player.fijar_volumen(self.snd_vol)
		self.player.fijar_velocidad(float(VELOCIDADES[self.snd_vel_idx]))
		self.player.cargar_audio(self.audio)
		self.CentreOnScreen()
		self.btn_play.SetFocus()

	def _crear_interfaz(self) -> None:
		p = self.panel
		sizer = wx.BoxSizer(wx.VERTICAL)
		sizer.Add(wx.StaticText(p, label="&Texto a escuchar:"), 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
		self.txt_display = wx.TextCtrl(p, value=self.texto, size=(560, 140), style=wx.TE_MULTILINE | wx.TE_READONLY)
		sizer.Add(self.txt_display, 1, wx.EXPAND | wx.ALL, 6)
		controles = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_atras = wx.Button(p, label="F1: Retroceder")
		self.btn_play = wx.Button(p, label="F2: Reproducir")
		self.btn_adelante = wx.Button(p, label="F3: Adelantar")
		self.btn_stop = wx.Button(p, label="F4: Detener")
		for b in (self.btn_atras, self.btn_play, self.btn_adelante, self.btn_stop):
			controles.Add(b, 0, wx.ALL, 4)
		sizer.Add(controles, 0, wx.ALIGN_CENTER)
		opciones = wx.BoxSizer(wx.HORIZONTAL)
		opciones.Add(wx.StaticText(p, label="&Volumen (F5/F6):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.slider_vol = wx.Slider(p, value=self.snd_vol, minValue=0, maxValue=100, size=(180, -1))
		self.slider_vol.SetLineSize(5)
		opciones.Add(self.slider_vol, 1, wx.EXPAND | wx.ALL, 4)
		opciones.Add(wx.StaticText(p, label="Veloci&dad (F7/F8):"), 0, wx.ALIGN_CENTER_VERTICAL | wx.ALL, 4)
		self.choice_vel = wx.Choice(p, choices=[f"{v}x" for v in VELOCIDADES])
		self.choice_vel.SetSelection(self.snd_vel_idx)
		opciones.Add(self.choice_vel, 0, wx.ALL, 4)
		sizer.Add(opciones, 0, wx.EXPAND | wx.ALL, 4)
		self.lbl_ayuda = wx.StaticText(p, label="Atajos: F1-F4 control, F5/F6 volumen, F7/F8 velocidad, F9 tiempo, Mayúsculas+F10 en Retroceder o Adelantar: menú de saltos")
		sizer.Add(self.lbl_ayuda, 0, wx.ALL, 6)
		finales = wx.BoxSizer(wx.HORIZONTAL)
		self.btn_guardar = wx.Button(p, label="&Guardar audio...")
		self.btn_cerrar = wx.Button(p, wx.ID_CLOSE, "&Cerrar")
		finales.Add(self.btn_guardar, 0, wx.ALL, 4)
		finales.Add(self.btn_cerrar, 0, wx.ALL, 4)
		sizer.Add(finales, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		p.SetSizer(sizer)
		marco = wx.BoxSizer(wx.VERTICAL)
		marco.Add(p, 1, wx.EXPAND)
		self.SetSizerAndFit(marco)
		self.SetEscapeId(wx.ID_CLOSE)
		self.btn_play.Bind(wx.EVT_BUTTON, self._on_play_pause)
		self.btn_stop.Bind(wx.EVT_BUTTON, self._on_stop)
		self.btn_atras.Bind(wx.EVT_BUTTON, self._on_atras_click)
		self.btn_adelante.Bind(wx.EVT_BUTTON, self._on_adelante_click)
		self.btn_atras.Bind(wx.EVT_CONTEXT_MENU, self._on_atras_menu)
		self.btn_adelante.Bind(wx.EVT_CONTEXT_MENU, self._on_adelante_menu)
		self.slider_vol.Bind(wx.EVT_SLIDER, self._on_vol_cambiado)
		self.choice_vel.Bind(wx.EVT_CHOICE, self._on_vel_cambiado)
		self.btn_guardar.Bind(wx.EVT_BUTTON, self._on_guardar)
		self.btn_cerrar.Bind(wx.EVT_BUTTON, lambda e: self.Close())
		self.Bind(wx.EVT_CLOSE, self._on_close)
		self.Bind(wx.EVT_CHAR_HOOK, self._on_key_down)

	# ------------------------------------------------------------ teclado
	def _on_key_down(self, event: wx.KeyEvent) -> None:
		tecla = event.GetKeyCode()
		mods = event.GetModifiers()
		if mods == wx.MOD_NONE:
			acciones = {
				wx.WXK_F1: lambda: self._on_atras_click(None),
				wx.WXK_F2: lambda: self._on_play_pause(None),
				wx.WXK_F3: lambda: self._on_adelante_click(None),
				wx.WXK_F4: lambda: self._on_stop(None),
				wx.WXK_F5: lambda: self._cambiar_volumen(-5),
				wx.WXK_F6: lambda: self._cambiar_volumen(5),
				wx.WXK_F7: lambda: self._cambiar_velocidad(-1),
				wx.WXK_F8: lambda: self._cambiar_velocidad(1),
				wx.WXK_F9: lambda: self._on_info_tecla(None),
			}
			accion = acciones.get(tecla)
			if accion:
				accion()
				return
		event.Skip()

	def _cambiar_volumen(self, paso: int) -> None:
		self.slider_vol.SetValue(max(0, min(100, self.slider_vol.GetValue() + paso)))
		self._on_vol_cambiado(None)

	def _cambiar_velocidad(self, paso: int) -> None:
		idx = max(0, min(len(VELOCIDADES) - 1, self.choice_vel.GetSelection() + paso))
		self.choice_vel.SetSelection(idx)
		self._on_vel_cambiado(None)

	# ------------------------------------------------------------ acciones
	def _on_play_pause(self, event: Any) -> None:
		if self.player.is_playing:
			self.player.pausar()
			self.btn_play.SetLabel("F2: Reproducir")
			lector.mensaje("Pausado")
		else:
			self.player.reproducir()
			self.btn_play.SetLabel("F2: Pausar")
			lector.mensaje("Reproduciendo")

	def _on_stop(self, event: Any) -> None:
		self.player.detener()
		self.btn_play.SetLabel("F2: Reproducir")
		lector.mensaje("Detenido")

	def _on_atras_click(self, event: Any) -> None:
		self.player.buscar(-TIEMPOS_MS[self.snd_rw_idx])
		lector.mensaje(f"Retroceder {TIEMPOS_TEXTO[self.snd_rw_idx]}")

	def _on_adelante_click(self, event: Any) -> None:
		self.player.buscar(TIEMPOS_MS[self.snd_ff_idx])
		lector.mensaje(f"Adelantar {TIEMPOS_TEXTO[self.snd_ff_idx]}")

	def _menu_saltos(self, actual: int, alElegir: Callable[[int], None]) -> None:
		menu = wx.Menu()
		for i, texto in enumerate(TIEMPOS_TEXTO):
			item = menu.AppendRadioItem(wx.ID_ANY, texto)
			if i == actual:
				item.Check()
			self.Bind(wx.EVT_MENU, lambda e, n=i: alElegir(n), item)
		self.PopupMenu(menu)
		menu.Destroy()

	def _on_atras_menu(self, event: Any) -> None:
		self._menu_saltos(self.snd_rw_idx, self._fijar_atras)

	def _on_adelante_menu(self, event: Any) -> None:
		self._menu_saltos(self.snd_ff_idx, self._fijar_adelante)

	def _fijar_atras(self, i: int) -> None:
		self.snd_rw_idx = i
		lector.mensaje(f"Salto atrás fijado a {TIEMPOS_TEXTO[i]}")

	def _fijar_adelante(self, i: int) -> None:
		self.snd_ff_idx = i
		lector.mensaje(f"Salto adelante fijado a {TIEMPOS_TEXTO[i]}")

	def _on_vol_cambiado(self, event: Any) -> None:
		vol = self.slider_vol.GetValue()
		self.player.fijar_volumen(vol)
		if event is None:
			lector.mensaje(f"Volumen {vol}%")

	def _on_vel_cambiado(self, event: Any) -> None:
		vel = float(VELOCIDADES[self.choice_vel.GetSelection()])
		self.player.fijar_velocidad(vel)
		if event is None:
			lector.mensaje(f"Velocidad {VELOCIDADES[self.choice_vel.GetSelection()]}x")

	def _on_info_tecla(self, event: Any) -> None:
		lector.mensaje(self.player.obtener_estado_tiempo())

	def _on_audio_terminado(self) -> None:
		try:
			self.btn_play.SetLabel("F2: Reproducir")
		except RuntimeError:
			pass

	def _on_guardar(self, event: Any) -> None:
		with wx.FileDialog(self, "Guardar audio", defaultFile="traduccion.mp3", wildcard="Audio MP3 (*.mp3)|*.mp3", style=wx.FD_SAVE | wx.FD_OVERWRITE_PROMPT) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			ruta = dlg.GetPath()
		try:
			with open(ruta, "wb") as f:
				f.write(self.audio)
		except OSError as e:
			from tiresias import gui

			gui.messageBox(f"No se pudo guardar el audio:\n{e}", "Error", wx.OK | wx.ICON_ERROR, self)
			return
		from tiresias import gui

		gui.messageBox("Audio guardado con éxito.", "Información", wx.OK | wx.ICON_INFORMATION, self)

	def _on_close(self, event: Any) -> None:
		config = self.plugin.configuracion.config
		try:
			config.volumen_reproductor = self.slider_vol.GetValue()
			config.velocidad_audio = self.choice_vel.GetSelection()
			config.salto_atras = self.snd_rw_idx
			config.salto_adelante = self.snd_ff_idx
		except Exception:
			log.debug("No se pudieron guardar los ajustes del reproductor", exc_info=True)
		if self.player:
			self.player.cerrar()
		if self.IsModal():
			self.EndModal(wx.ID_CLOSE)
		else:
			self.Destroy()


def _entero(valor: Any, defecto: int, minimo: int, maximo: int) -> int:
	try:
		return max(minimo, min(maximo, int(valor)))
	except (TypeError, ValueError):
		return defecto
