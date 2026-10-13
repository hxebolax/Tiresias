"""Diálogos del complemento: inicio de sesión, descarga y actualización del
catálogo, ir a una posición, fichas, ecualizador, temporizador de sueño,
descargas, estadísticas, historial de búsqueda y «Acerca de».

Todos se crean y se usan en el hilo de la interfaz (wx).
"""

from __future__ import annotations

import ctypes
import json
import os
import threading

import wx

from . import ajustes, catalogo, red
from .control import hablar, informar
from .descargas import CANCELADA, COMPLETADA, DESCARGANDO, ERROR

# Resultados de los diálogos.
ID_REPRODUCIR = 1001
ID_DESCARGAR = 1002
ID_CERRAR = 1003
ID_ACTUALIZADO = 1004


def _beep(tipo: int) -> None:
	"""Sonido del sistema (0 = predeterminado, 0x10 = error), como el original."""
	try:
		ctypes.windll.user32.MessageBeep(tipo)
	except Exception:
		pass


def mensaje(texto: str, titulo: str = "Información", estilo: int = wx.OK | wx.ICON_INFORMATION, parent: wx.Window | None = None) -> int:
	"""Cuadro de mensaje accesible de Tiresias (devuelve ``wx.OK``, ``wx.YES``...)."""
	try:
		from tiresias import gui

		res = gui.messageBox(texto, titulo, estilo, parent)
		return wx.OK if res is None else res
	except Exception:
		return wx.MessageBox(texto, titulo, estilo, parent)


def preguntar(texto: str, parent: wx.Window | None = None, titulo: str = "Pregunta") -> bool:
	return mensaje(texto, titulo, wx.YES_NO | wx.NO_DEFAULT | wx.ICON_QUESTION, parent) == wx.YES


def abrirWeb(url: str) -> None:
	try:
		wx.LaunchDefaultBrowser(url)
	except Exception:
		try:
			os.startfile(url)
		except Exception:
			pass


def copiarAlPortapapeles(texto: str) -> bool:
	if wx.TheClipboard.Open():
		try:
			wx.TheClipboard.SetData(wx.TextDataObject(texto))
		finally:
			wx.TheClipboard.Close()
		return True
	return False


def _etiqueta(parent: wx.Window, sizer: wx.Sizer, texto: str) -> wx.StaticText:
	st = wx.StaticText(parent, label=texto)
	sizer.Add(st, 0, wx.LEFT | wx.RIGHT | wx.TOP, 6)
	return st


class _Base(wx.Dialog):
	"""Diálogo con Escape para cerrar (devuelve ``idEscape``)."""

	idEscape = wx.ID_CANCEL

	def __init__(self, parent, titulo: str, size=wx.DefaultSize, estilo=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER) -> None:
		super().__init__(parent, title=titulo, size=size, style=estilo)
		self.Bind(wx.EVT_CHAR_HOOK, self._onCharHook)
		self.Bind(wx.EVT_CLOSE, self._onCerrarVentana)

	def _onCharHook(self, evt: wx.KeyEvent) -> None:
		if evt.GetKeyCode() == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.alEscape()
			return
		evt.Skip()

	def alEscape(self) -> None:
		self.EndModal(self.idEscape)

	def _onCerrarVentana(self, evt) -> None:
		self.alEscape()


# =================================================================== inicio de sesión
class DialogoLogin(_Base):
	"""Inicio de sesión o cambio de las credenciales de la cuenta."""

	def __init__(self, parent, editar: bool = False) -> None:
		titulo = "Editar sesión" if editar else "Iniciar sesión en Audiocinemateca"
		super().__init__(parent, titulo)
		self.contrasena = ""
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Usuario:")
		self.txtUsuario = wx.TextCtrl(self, size=(320, -1))
		s.Add(self.txtUsuario, 0, wx.EXPAND | wx.ALL, 6)
		self.lblContrasena = _etiqueta(self, s, "&Contraseña:")
		self.txtOculta = wx.TextCtrl(self, style=wx.TE_PASSWORD, size=(320, -1))
		s.Add(self.txtOculta, 0, wx.EXPAND | wx.ALL, 6)
		self.txtVisible = wx.TextCtrl(self, size=(320, -1))
		self.txtVisible.Hide()
		s.Add(self.txtVisible, 0, wx.EXPAND | wx.ALL, 6)
		self.chkMostrar = wx.CheckBox(self, label="&Mostrar contraseña")
		s.Add(self.chkMostrar, 0, wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnAceptar = wx.Button(self, wx.ID_OK, "&Aceptar")
		self.btnAceptar.SetDefault()
		btnCancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		btnWeb = wx.Button(self, label="&Visitar la web")
		for b in (self.btnAceptar, btnCancelar, btnWeb):
			botones.Add(b, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(s)
		self.chkMostrar.Bind(wx.EVT_CHECKBOX, self._onMostrar)
		self.btnAceptar.Bind(wx.EVT_BUTTON, self._onAceptar)
		btnCancelar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		btnWeb.Bind(wx.EVT_BUTTON, lambda e: abrirWeb(ajustes.URL_WEB))
		if editar:
			self.txtUsuario.SetValue(ajustes.estado.usuario)
			self.txtOculta.SetValue(ajustes.estado.contrasena)
		self.CentreOnScreen()
		self.txtUsuario.SetFocus()

	def _contrasenaActual(self) -> str:
		return self.txtVisible.GetValue() if self.txtVisible.IsShown() else self.txtOculta.GetValue()

	def _onMostrar(self, evt) -> None:
		if self.chkMostrar.GetValue():
			self.txtVisible.SetValue(self.txtOculta.GetValue())
			self.txtOculta.Hide()
			self.txtVisible.Show()
			self.Layout()
			self.txtVisible.SetFocus()
		else:
			self.txtOculta.SetValue(self.txtVisible.GetValue())
			self.txtVisible.Hide()
			self.txtOculta.Show()
			self.Layout()
			self.txtOculta.SetFocus()

	@property
	def usuario(self) -> str:
		return self.txtUsuario.GetValue().strip()

	def _onAceptar(self, evt) -> None:
		contrasena = self._contrasenaActual()
		if not self.usuario or not contrasena:
			mensaje("Los campos Usuario y Contraseña son obligatorios.", "Información", parent=self)
			(self.txtUsuario if not self.usuario else (self.txtVisible if self.txtVisible.IsShown() else self.txtOculta)).SetFocus()
			return
		self.contrasena = contrasena
		self.EndModal(wx.ID_OK)


# =================================================================== catálogo
class DialogoDescarga(_Base):
	"""Descarga del catálogo (modo ``DESCARGA``) o comprobación y descarga de
	su actualización (modo ``ACTUALIZAR``), con barra de progreso."""

	DESCARGA = 1
	ACTUALIZAR = 3

	def __init__(self, parent, modo: int, carpeta: str | None = None, versionLocal: dict | None = None) -> None:
		super().__init__(parent, "Actualizando..." if modo == self.ACTUALIZAR else "Descargando...", size=(550, 400))
		self.modo = modo
		self.carpeta = carpeta or ajustes.dirDatos()
		self.versionLocal = versionLocal
		self.ocupado = True
		self.rutaCatalogo = os.path.join(self.carpeta, "catalogo.json")
		self.rutaVersion = os.path.join(self.carpeta, "version.json")
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Progreso:")
		self.barra = wx.Gauge(self, range=100, style=wx.GA_HORIZONTAL)
		s.Add(self.barra, 0, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, s, "&Información:")
		self.txtInfo = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(500, 200))
		s.Add(self.txtInfo, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnActualizar = wx.Button(self, label="&Actualizar")
		self.btnAceptar = wx.Button(self, label="&Aceptar")
		self.btnCerrar = wx.Button(self, label="&Cerrar")
		for b in (self.btnActualizar, self.btnAceptar, self.btnCerrar):
			b.Disable()
			botones.Add(b, 1, wx.ALL, 4)
		s.Add(botones, 0, wx.EXPAND | wx.ALL, 4)
		self.SetSizer(s)
		self.btnActualizar.Bind(wx.EVT_BUTTON, self._onActualizar)
		self.btnAceptar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(ID_ACTUALIZADO if self._actualizado else wx.ID_OK))
		self.btnCerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		self._actualizado = False
		self.CentreOnScreen()
		self.txtInfo.SetFocus()
		objetivo = self._descargarCatalogo if modo == self.DESCARGA else self._comprobar
		threading.Thread(target=self._envolver, args=(objetivo,), name="AudiocinematecaCatalogo", daemon=True).start()

	# -- utilidades de hilo
	def _info(self, texto: str) -> None:
		def f():
			if self:
				self.txtInfo.SetValue(texto)
				self.txtInfo.SetInsertionPoint(0)

		wx.CallAfter(f)

	def _progreso(self, porcentaje: float) -> None:
		wx.CallAfter(lambda: self and self.barra.SetValue(int(porcentaje)))

	def _envolver(self, objetivo) -> None:
		try:
			objetivo()
		except Exception as e:
			self._error(e)

	def _error(self, error) -> None:
		self._limpiarTemporales()
		self._info("Se produjo un error:\n\n" + red.mensajeError(error))
		wx.CallAfter(self._habilitar, cerrar=True, sonido=0x10)

	def _habilitar(self, aceptar=False, cerrar=False, actualizar=False, sonido=0) -> None:
		if not self:
			return
		self.ocupado = False
		_beep(sonido)
		self.btnAceptar.Enable(aceptar)
		self.btnCerrar.Enable(cerrar)
		self.btnActualizar.Enable(actualizar)
		self.txtInfo.SetInsertionPoint(0)
		self.txtInfo.SetFocus()

	def _temporal(self, nombre: str) -> str:
		return os.path.join(self.carpeta, nombre)

	def _limpiarTemporales(self) -> None:
		for nombre in ("catalogo.json.bz2", "version.json.gz", "version_servidor.json"):
			try:
				os.remove(self._temporal(nombre))
			except OSError:
				pass

	def alEscape(self) -> None:
		# Durante la descarga no se puede cerrar (como el original).
		if self.ocupado:
			_beep(0x30)
			return
		if self.btnAceptar.IsEnabled():
			self.EndModal(ID_ACTUALIZADO if self._actualizado else wx.ID_OK)
		else:
			self.EndModal(wx.ID_CANCEL)

	# -- trabajos
	def _bajarYDescomprimirCatalogo(self, versionServidor: str) -> None:
		u, c = ajustes.estado.usuario, ajustes.estado.contrasena
		bz = self._temporal("catalogo.json.bz2")
		red.descargar(ajustes.URL_CATALOGO, bz, u, c, self._progreso)
		self._info("Descomprimiendo el catálogo.\nEspere por favor…")
		self._progreso(0)
		red.descomprimirBz2(bz, self.rutaCatalogo, self._progreso)
		# El catálogo nuevo ya está: ahora sí se sustituye la versión local.
		os.replace(versionServidor, self.rutaVersion)
		self._limpiarTemporales()

	def _bajarVersion(self) -> str:
		u, c = ajustes.estado.usuario, ajustes.estado.contrasena
		gz = self._temporal("version.json.gz")
		red.descargar(ajustes.URL_VERSION, gz, u, c, self._progreso)
		destino = self._temporal("version_servidor.json")
		red.descomprimirGz(gz, destino)
		return destino

	def _descargarCatalogo(self) -> None:
		self._info("Descargando el catálogo de la Audiocinemateca.\nEspere por favor…")
		version = self._bajarVersion()
		self._bajarYDescomprimirCatalogo(version)
		self._info("Descarga del catálogo completada.\nYa puede cerrar esta pantalla y disfrutar.")
		wx.CallAfter(self._habilitar, aceptar=True)

	def _comprobar(self) -> None:
		self._info("Comprobando si hay actualizaciones.\nEspere por favor…")
		ruta = self._bajarVersion()
		with open(ruta, encoding="utf-8") as f:
			servidor = json.load(f)
		if red.compararVersiones(self.versionLocal, servidor):
			self._info("Hay actualizaciones disponibles.\n¿Desea actualizar?")
			wx.CallAfter(self._habilitar, cerrar=True, actualizar=True)
		else:
			self._limpiarTemporales()
			self._info("No hay actualizaciones disponibles.\nCompruébelo más adelante.")
			wx.CallAfter(self._habilitar, aceptar=True)

	def _onActualizar(self, evt) -> None:
		self.ocupado = True
		self.btnActualizar.Disable()
		self.btnCerrar.Disable()
		threading.Thread(target=self._envolver, args=(self._actualizar,), name="AudiocinematecaCatalogo", daemon=True).start()

	def _actualizar(self) -> None:
		self._info("Actualizando la base de datos.\nEspere por favor…")
		self._bajarYDescomprimirCatalogo(self._temporal("version_servidor.json"))
		self._actualizado = True
		self._info("Actualización completada.\nEl complemento se recargará para aplicar los cambios.")
		wx.CallAfter(self._habilitar, aceptar=True)


# =================================================================== ir a la posición
class DialogoPosicion(_Base):
	def __init__(self, parent, total: int) -> None:
		super().__init__(parent, "Ir a la posición...")
		self.total = total
		self.numero = 0
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, f"&Introduzca un número entre 1 y {total}:")
		self.txtNumero = wx.TextCtrl(self, style=wx.TE_PROCESS_ENTER, size=(200, -1))
		s.Add(self.txtNumero, 0, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, "&Aceptar")
		ok.SetDefault()
		cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		botones.Add(ok, 0, wx.ALL, 4)
		botones.Add(cancelar, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(s)
		ok.Bind(wx.EVT_BUTTON, self._onAceptar)
		self.txtNumero.Bind(wx.EVT_TEXT_ENTER, self._onAceptar)
		cancelar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		self.CentreOnScreen()
		self.txtNumero.SetFocus()

	def _onAceptar(self, evt) -> None:
		try:
			valor = int(self.txtNumero.GetValue().strip())
		except ValueError:
			valor = 0
		if 1 <= valor <= self.total:
			self.numero = valor
			self.EndModal(wx.ID_OK)
			return
		mensaje(f"Solo se admite un número entre 1 y {self.total}.", "Información", parent=self)
		self.txtNumero.Clear()
		self.txtNumero.SetFocus()


# =================================================================== ficha
class DialogoFicha(_Base):
	"""Ficha de una película, serie, documental o cortometraje.

	Devuelve ``ID_REPRODUCIR``, ``ID_DESCARGAR`` o ``ID_CERRAR``; el enlace
	elegido (parte o episodio) queda en :attr:`enlaceElegido` y su título en
	:attr:`tituloElegido`.
	"""

	idEscape = ID_CERRAR
	TITULOS = {
		"peliculas": "Ficha de la película",
		"series": "Ficha de la Serie",
		"documentales": "Ficha del documental",
		"cortometrajes": "Ficha del cortometraje",
	}

	def __init__(self, parent, controlador, datos: dict, categoria: str) -> None:
		super().__init__(parent, self.TITULOS.get(categoria, "Ficha"), size=(700, 560))
		self.control = controlador
		self.datos = datos
		self.categoria = categoria
		self.enlaceElegido = ""
		self.tituloElegido = catalogo.titulo(datos)
		self._episodios: list[dict] = []
		self._temporadas = catalogo.episodiosPorTemporada(datos.get("capitulos", {})) if categoria == "series" else []
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Información de la serie:" if categoria == "series" else "&Información:")
		self.txtInfo = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.HSCROLL, size=(650, 260))
		s.Add(self.txtInfo, 2, wx.EXPAND | wx.ALL, 6)
		self.choiceEnlaces = None
		self.choiceTemporadas = None
		self.listEpisodios = None
		if categoria == "peliculas":
			_etiqueta(self, s, "&Enlaces:")
			enl = catalogo.enlaces(datos, categoria)
			self.choiceEnlaces = wx.Choice(self, choices=[f"Parte {i + 1} de {len(enl)}" for i in range(len(enl))])
			if enl:
				self.choiceEnlaces.SetSelection(0)
			s.Add(self.choiceEnlaces, 0, wx.EXPAND | wx.ALL, 6)
		elif categoria == "series":
			_etiqueta(self, s, "&Temporada:" if len(self._temporadas) <= 1 else "&Temporadas:")
			self.choiceTemporadas = wx.Choice(self, choices=[f"Temporada {t}" for t, _e in self._temporadas])
			s.Add(self.choiceTemporadas, 0, wx.EXPAND | wx.ALL, 6)
			_etiqueta(self, s, "&Episodios:")
			self.listEpisodios = wx.ListBox(self, size=(650, 150))
			s.Add(self.listEpisodios, 2, wx.EXPAND | wx.ALL, 6)
			self.choiceTemporadas.Bind(wx.EVT_CHOICE, lambda e: self._cargarEpisodios(self.choiceTemporadas.GetSelection()))
			self.listEpisodios.Bind(wx.EVT_LISTBOX_DCLICK, lambda e: self._terminar(ID_REPRODUCIR))
		botones = wx.WrapSizer(wx.HORIZONTAL)
		self.btnReproducir = wx.Button(self, label="&Reproducir")
		self.btnDescargar = wx.Button(self, label="&Descargar")
		self.btnWeb = wx.Button(self, label="Información en la &web")
		self.btnFavorito = wx.Button(self, label="&Agregar a Favoritos")
		self.btnLista = wx.Button(self, label="Agregar a &lista")
		self.btnCopiar = wx.Button(self, label="&Copiar información")
		self.btnCerrar = wx.Button(self, label="C&errar")
		for b in (self.btnReproducir, self.btnDescargar, self.btnWeb, self.btnFavorito, self.btnLista, self.btnCopiar, self.btnCerrar):
			botones.Add(b, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.EXPAND | wx.ALL, 4)
		self.SetSizer(s)
		self.btnReproducir.Bind(wx.EVT_BUTTON, lambda e: self._terminar(ID_REPRODUCIR))
		self.btnDescargar.Bind(wx.EVT_BUTTON, lambda e: self._terminar(ID_DESCARGAR))
		self.btnWeb.Bind(wx.EVT_BUTTON, self._onWeb)
		self.btnFavorito.Bind(wx.EVT_BUTTON, self._onFavorito)
		self.btnLista.Bind(wx.EVT_BUTTON, self._onLista)
		self.btnCopiar.Bind(wx.EVT_BUTTON, self._onCopiar)
		self.btnCerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(ID_CERRAR))
		self.txtInfo.SetValue(catalogo.textoFicha(datos, categoria))
		self.txtInfo.SetInsertionPoint(0)
		if self.choiceTemporadas is not None and self._temporadas:
			self.choiceTemporadas.SetSelection(0)
			self._cargarEpisodios(0)
		self._actualizarFavorito()
		self.CentreOnScreen()
		self.txtInfo.SetFocus()

	def _onCharHook(self, evt: wx.KeyEvent) -> None:
		# Intro en la lista de episodios reproduce el episodio elegido.
		if evt.GetKeyCode() in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and not evt.HasAnyModifiers() and self.listEpisodios is not None and wx.Window.FindFocus() is self.listEpisodios:
			self._terminar(ID_REPRODUCIR)
			return
		super()._onCharHook(evt)

	def _cargarEpisodios(self, indice: int) -> None:
		self.listEpisodios.Clear()
		self._episodios = list(self._temporadas[indice][1]) if 0 <= indice < len(self._temporadas) else []
		for ep in self._episodios:
			self.listEpisodios.Append(f"Cap. {ep.get('capitulo', '')} - {ep.get('titulo', '')}")
		if self._episodios:
			self.listEpisodios.SetSelection(0)

	def enlaceSeleccionado(self) -> tuple[str, str]:
		"""``(enlace, título)`` de la parte o el episodio elegido."""
		titulo = catalogo.titulo(self.datos)
		if self.categoria == "series":
			sel = self.listEpisodios.GetSelection() if self.listEpisodios else -1
			if 0 <= sel < len(self._episodios):
				ep = self._episodios[sel]
				temporada = self._temporadas[self.choiceTemporadas.GetSelection()][0]
				return str(ep.get("enlace", "")), f"{titulo} - T{temporada} Cap. {ep.get('capitulo', '')} - {ep.get('titulo', '')}"
			return "", titulo
		enl = catalogo.enlaces(self.datos, self.categoria)
		if self.categoria == "peliculas" and self.choiceEnlaces is not None:
			sel = self.choiceEnlaces.GetSelection()
			if 0 <= sel < len(enl):
				return enl[sel], (titulo if len(enl) == 1 else f"{titulo} - Parte {sel + 1} de {len(enl)}")
			return "", titulo
		return (enl[0] if enl else ""), titulo

	def _terminar(self, resultado: int) -> None:
		enlace, titulo = self.enlaceSeleccionado()
		if not enlace:
			mensaje("No hay ningún enlace que reproducir o descargar en esta ficha.", "Información", parent=self)
			return
		self.enlaceElegido, self.tituloElegido = enlace, titulo
		self.EndModal(resultado)

	def _onWeb(self, evt) -> None:
		url = str(self.datos.get("filmaffinity", "") or "")
		if red.esUrl(url):
			abrirWeb(url)
		else:
			mensaje("Esta ficha no tiene información web adicional.", "Información", parent=self)

	def _actualizarFavorito(self) -> None:
		es = self.control.favoritos.esFavorito(self.categoria, self.datos.get("id"))
		self.btnFavorito.SetLabel("&Quitar de Favoritos" if es else "&Agregar a Favoritos")

	def _onFavorito(self, evt) -> None:
		es = self.control.favoritos.alternar(self.categoria, self.datos.get("id"))
		self._actualizarFavorito()
		informar("Agregado a favoritos" if es else "Quitado de favoritos", 0)

	def _onCopiar(self, evt) -> None:
		if copiarAlPortapapeles(catalogo.textoCopiar(self.datos, self.categoria)):
			mensaje("Información copiada al portapapeles", "Información", parent=self)
		else:
			mensaje("No se pudo acceder al portapapeles", "Error", wx.OK | wx.ICON_ERROR, parent=self)

	def _onLista(self, evt) -> None:
		menu = wx.Menu()
		nombres = self.control.listas.nombres()
		if not nombres:
			menu.Append(wx.ID_ANY, "No hay listas. Cree una desde la pestaña Listas.")
		else:
			ids = {}
			for nombre in nombres:
				item = menu.Append(wx.ID_ANY, nombre)
				ids[item.GetId()] = nombre

			def alElegir(e):
				nombre = ids.get(e.GetId())
				if nombre is None:
					return
				if self.control.listas.agregarItem(nombre, self.datos.get("id", ""), self.categoria, catalogo.titulo(self.datos)):
					mensaje(f"Agregado a la lista '{nombre}'.", "Información", parent=self)
				else:
					mensaje(f"Ya está en la lista '{nombre}'.", "Información", parent=self)

			menu.Bind(wx.EVT_MENU, alElegir)
		self.btnLista.PopupMenu(menu)
		menu.Destroy()


# =================================================================== ecualizador
class DialogoEcualizador(_Base):
	DESCRIPCIONES = [
		"&Graves (80 Hz) - Sonidos profundos, explosiones, pasos:",
		"Graves &medios (230 Hz) - Cuerpo de la voz, calidez:",
		"Me&dios (910 Hz) - Claridad de voz y diálogos:",
		"Medios a&ltos (3.6 kHz) - Presencia, nitidez de la voz:",
		"Ag&udos (14 kHz) - Brillo, detalle, ambiente:",
	]

	def __init__(self, parent) -> None:
		super().__init__(parent, "Ecualizador", size=(520, 520))
		s = wx.BoxSizer(wx.VERTICAL)
		self.chkActivo = wx.CheckBox(self, label="&Activar ecualizador")
		self.chkActivo.SetValue(ajustes.get("ecualizadorActivo"))
		s.Add(self.chkActivo, 0, wx.ALL, 6)
		_etiqueta(self, s, "&Preset:")
		self.choicePreset = wx.Choice(self, choices=[n for n, _v in ajustes.EQ_PRESETS])
		self.choicePreset.SetSelection(0)
		s.Add(self.choicePreset, 0, wx.EXPAND | wx.ALL, 6)
		self.sliders: list[wx.Slider] = []
		valores = ajustes.get("ecualizadorValores")
		for i, desc in enumerate(self.DESCRIPCIONES):
			_etiqueta(self, s, desc)
			sl = wx.Slider(self, value=valores[i], minValue=ajustes.EQ_MIN, maxValue=ajustes.EQ_MAX, style=wx.SL_HORIZONTAL)
			s.Add(sl, 0, wx.EXPAND | wx.ALL, 6)
			self.sliders.append(sl)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, "A&ceptar")
		cancelar = wx.Button(self, wx.ID_CANCEL, "Ca&ncelar")
		botones.Add(ok, 0, wx.ALL, 4)
		botones.Add(cancelar, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizer(s)
		self.choicePreset.Bind(wx.EVT_CHOICE, self._onPreset)
		ok.Bind(wx.EVT_BUTTON, self._onAceptar)
		cancelar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		self.CentreOnScreen()
		self.chkActivo.SetFocus()

	def _onPreset(self, evt) -> None:
		sel = self.choicePreset.GetSelection()
		if 0 <= sel < len(ajustes.EQ_PRESETS):
			for sl, v in zip(self.sliders, ajustes.EQ_PRESETS[sel][1]):
				sl.SetValue(v)

	def valores(self) -> list[int]:
		return [int(sl.GetValue()) for sl in self.sliders]

	def _onAceptar(self, evt) -> None:
		ajustes.put("ecualizadorActivo", bool(self.chkActivo.GetValue()))
		ajustes.put("ecualizadorValores", self.valores())
		self.EndModal(wx.ID_OK)


# =================================================================== temporizador de sueño
class DialogoTemporizador(_Base):
	def __init__(self, parent) -> None:
		super().__init__(parent, "Temporizador de sueño")
		self._minutos = [m for _n, m in ajustes.TEMPORIZADOR_OPCIONES]
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Seleccione el tiempo:")
		self.choiceTiempo = wx.Choice(self, choices=[n for n, _m in ajustes.TEMPORIZADOR_OPCIONES])
		s.Add(self.choiceTiempo, 0, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, s, "&Minutos personalizados:")
		self.spinMinutos = wx.SpinCtrl(self, min=1, max=480, initial=60)
		s.Add(self.spinMinutos, 0, wx.EXPAND | wx.ALL, 6)
		personalizado = len(self._minutos) - 1
		if ajustes.estado.temporizadorActivo and ajustes.estado.temporizadorMinutos > 0:
			m = ajustes.estado.temporizadorMinutos
			if m in self._minutos:
				self.choiceTiempo.SetSelection(self._minutos.index(m))
			else:
				self.choiceTiempo.SetSelection(personalizado)
				self.spinMinutos.SetValue(m)
		else:
			self.choiceTiempo.SetSelection(0)
		self.spinMinutos.Enable(self.choiceTiempo.GetSelection() == personalizado)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		ok = wx.Button(self, wx.ID_OK, "&Aceptar")
		ok.SetDefault()
		cancelar = wx.Button(self, wx.ID_CANCEL, "&Cancelar")
		botones.Add(ok, 0, wx.ALL, 4)
		botones.Add(cancelar, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(s)
		self.choiceTiempo.Bind(wx.EVT_CHOICE, lambda e: self.spinMinutos.Enable(self.choiceTiempo.GetSelection() == personalizado))
		ok.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_OK))
		cancelar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		self.CentreOnScreen()
		self.choiceTiempo.SetFocus()

	def obtenerMinutos(self) -> int:
		sel = self.choiceTiempo.GetSelection()
		if sel == len(self._minutos) - 1:
			return int(self.spinMinutos.GetValue())
		return self._minutos[sel] if sel >= 0 else 0


# =================================================================== descargas
class DialogoDescargas(_Base):
	"""Descargas en curso (con progreso) y finalizadas; se actualiza cada segundo."""

	def __init__(self, parent, controlador, alReproducir=None) -> None:
		super().__init__(parent, "Descargas", size=(680, 540))
		self.idEscape = wx.ID_CLOSE
		self.control = controlador
		self.gestor = controlador.descargas
		self.alReproducir = alReproducir
		self._activas = []
		self._finalizadas = []
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "Descargas en &curso:")
		self.listActivas = wx.ListBox(self, size=(640, 120))
		s.Add(self.listActivas, 1, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, s, "&Progreso:")
		self.barra = wx.Gauge(self, range=100)
		s.Add(self.barra, 0, wx.EXPAND | wx.ALL, 6)
		self.btnCancelar = wx.Button(self, label="&Cancelar descarga seleccionada")
		s.Add(self.btnCancelar, 0, wx.ALL, 4)
		_etiqueta(self, s, "Descargas &finalizadas:")
		self.listFinalizadas = wx.ListBox(self, size=(640, 120))
		s.Add(self.listFinalizadas, 1, wx.EXPAND | wx.ALL, 6)
		acciones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnReproducir = wx.Button(self, label="&Reproducir offline")
		self.btnCarpeta = wx.Button(self, label="&Abrir carpeta")
		self.btnReintentar = wx.Button(self, label="Re&intentar")
		self.btnLimpiar = wx.Button(self, label="&Limpiar lista")
		for b in (self.btnReproducir, self.btnCarpeta, self.btnReintentar, self.btnLimpiar):
			acciones.Add(b, 1, wx.ALL, 4)
		s.Add(acciones, 0, wx.EXPAND | wx.ALL, 4)
		btnCerrar = wx.Button(self, wx.ID_CLOSE, "C&errar")
		s.Add(btnCerrar, 0, wx.ALIGN_RIGHT | wx.ALL, 6)
		self.SetSizer(s)
		self.listActivas.Bind(wx.EVT_LISTBOX, lambda e: self._actualizarBarra())
		self.listFinalizadas.Bind(wx.EVT_LISTBOX, lambda e: self._actualizarBotones())
		self.btnCancelar.Bind(wx.EVT_BUTTON, self._onCancelar)
		self.btnReproducir.Bind(wx.EVT_BUTTON, self._onReproducir)
		self.btnCarpeta.Bind(wx.EVT_BUTTON, self._onCarpeta)
		self.btnReintentar.Bind(wx.EVT_BUTTON, self._onReintentar)
		self.btnLimpiar.Bind(wx.EVT_BUTTON, self._onLimpiar)
		btnCerrar.Bind(wx.EVT_BUTTON, lambda e: self.alEscape())
		self._activas = self.gestor.obtenerActivas()
		self._finalizadas = self.gestor.obtenerFinalizadas()
		self._reconstruirActivas()
		self._reconstruirFinalizadas()
		self._actualizarBarra()
		self._actualizarBotones()
		self._timer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._onTimer, self._timer)
		self._timer.Start(1000)
		self.CentreOnScreen()
		self.listActivas.SetFocus()

	def alEscape(self) -> None:
		self._timer.Stop()
		self.EndModal(wx.ID_CLOSE)

	@staticmethod
	def textoActiva(item) -> str:
		if item.estado == DESCARGANDO:
			return f"{item.nombre} - Descargando ({item.progreso}%)"
		return f"{item.nombre} - Pendiente"

	@staticmethod
	def textoFinalizada(item) -> str:
		if item.estado == COMPLETADA:
			return f"{item.nombre} - Completada"
		if item.estado == ERROR:
			return f"{item.nombre} - Error: {item.error or 'desconocido'}"
		if item.estado == CANCELADA:
			return f"{item.nombre} - Cancelada"
		return item.nombre

	def _rellenar(self, lista: wx.ListBox, textos: list[str], vacio: str) -> None:
		sel = lista.GetSelection()
		lista.Set(textos or [vacio])
		if 0 <= sel < lista.GetCount():
			lista.SetSelection(sel)
		elif lista.GetCount():
			lista.SetSelection(0)

	def _reconstruirActivas(self) -> None:
		self._rellenar(self.listActivas, [self.textoActiva(i) for i in self._activas], "No hay descargas en curso")

	def _reconstruirFinalizadas(self) -> None:
		self._rellenar(self.listFinalizadas, [self.textoFinalizada(i) for i in self._finalizadas], "No hay descargas finalizadas")

	def _onTimer(self, evt) -> None:
		"""Actualización silenciosa: solo cambia lo que ha cambiado."""
		nuevas = self.gestor.obtenerActivas()
		if [id(i) for i in nuevas] != [id(i) for i in self._activas]:
			self._activas = nuevas
			self._reconstruirActivas()
		else:
			for n, item in enumerate(self._activas):
				texto = self.textoActiva(item)
				if n < self.listActivas.GetCount() and self.listActivas.GetString(n) != texto:
					self.listActivas.SetString(n, texto)
		fin = self.gestor.obtenerFinalizadas()
		if [id(i) for i in fin] != [id(i) for i in self._finalizadas]:
			self._finalizadas = fin
			self._reconstruirFinalizadas()
		self._actualizarBarra()
		self._actualizarBotones()

	def _actualizarBarra(self) -> None:
		sel = self.listActivas.GetSelection()
		self.barra.SetValue(self._activas[sel].progreso if 0 <= sel < len(self._activas) else 0)

	def _finalizadaSeleccionada(self):
		sel = self.listFinalizadas.GetSelection()
		return self._finalizadas[sel] if 0 <= sel < len(self._finalizadas) else None

	def _actualizarBotones(self) -> None:
		self.btnCancelar.Enable(bool(self._activas))
		item = self._finalizadaSeleccionada()
		self.btnReproducir.Enable(item is not None and item.estado == COMPLETADA)
		self.btnCarpeta.Enable(item is not None and item.estado == COMPLETADA)
		self.btnReintentar.Enable(item is not None and item.estado in (ERROR, CANCELADA))
		self.btnLimpiar.Enable(bool(self._finalizadas))

	def _onCancelar(self, evt) -> None:
		sel = self.listActivas.GetSelection()
		item = self._activas[sel] if 0 <= sel < len(self._activas) else None
		if item is not None and item.estado != DESCARGANDO:
			self.gestor.quitarPendiente(item)
		else:
			self.gestor.cancelarActual()
		hablar("Descarga cancelada")
		self._onTimer(None)

	def _onReproducir(self, evt) -> None:
		item = self._finalizadaSeleccionada()
		if item is None or item.estado != COMPLETADA:
			return
		if not os.path.isfile(item.rutaCompleta):
			hablar("El archivo ya no existe en disco.")
			return
		if self.alReproducir is not None:
			self.alReproducir(item)

	def _onCarpeta(self, evt) -> None:
		item = self._finalizadaSeleccionada()
		if item is None:
			return
		if os.path.isdir(item.directorio):
			os.startfile(item.directorio)
		else:
			hablar("La carpeta ya no existe.")

	def _onReintentar(self, evt) -> None:
		item = self._finalizadaSeleccionada()
		if item is None:
			return
		if self.gestor.reintentar(item) is not None:
			hablar(f"Descarga reencolada: {item.nombre}")
			self._onTimer(None)

	def _onLimpiar(self, evt) -> None:
		self.gestor.limpiarFinalizadas()
		self._finalizadas = []
		self._reconstruirFinalizadas()
		self._actualizarBotones()
		hablar("Lista de finalizadas limpiada")


# =================================================================== estadísticas
def formatoTiempoLargo(segundos: float) -> str:
	horas = int(segundos) // 3600
	minutos = (int(segundos) % 3600) // 60
	if horas > 0:
		return f"{horas} horas y {minutos} minutos"
	return f"{minutos} minutos"


def textoResumen(resumen: dict) -> str:
	lineas = [
		f"Total de reproducciones: {resumen['total_reproducciones']}",
		f"Tiempo total de reproducción: {formatoTiempoLargo(resumen['tiempo_total_segundos'])}",
		"",
		"Por categoría:",
	]
	for clave, cantidad in resumen["por_categoria"].items():
		lineas.append(f"  {ajustes.nombreCategoria(clave, singular=False) or clave}: {cantidad}")
	if resumen["categoria_favorita"]:
		lineas += ["", f"Categoría favorita: {ajustes.nombreCategoria(resumen['categoria_favorita'], singular=False)}"]
	if resumen["mas_reproducido"]:
		m = resumen["mas_reproducido"]
		lineas += ["", f"Contenido más reproducido: {m.get('titulo', '')} ({m.get('veces', 0)} veces)"]
	return "\n".join(lineas) + "\n"


class DialogoEstadisticas(_Base):
	def __init__(self, parent, controlador) -> None:
		super().__init__(parent, "Estadísticas de uso", size=(520, 440))
		self.idEscape = wx.ID_CLOSE
		self.gestor = controlador.estadisticas
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Resumen de uso:")
		self.txtResumen = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(480, 160))
		s.Add(self.txtResumen, 1, wx.EXPAND | wx.ALL, 6)
		_etiqueta(self, s, "&Contenidos más reproducidos:")
		self.listTop = wx.ListBox(self, size=(480, 140))
		s.Add(self.listTop, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		limpiar = wx.Button(self, label="&Limpiar estadísticas")
		cerrar = wx.Button(self, wx.ID_CLOSE, "C&errar")
		botones.Add(limpiar, 0, wx.ALL, 4)
		botones.Add(cerrar, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizer(s)
		limpiar.Bind(wx.EVT_BUTTON, self._onLimpiar)
		cerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
		self._mostrar()
		self.CentreOnScreen()
		self.txtResumen.SetFocus()

	def _mostrar(self) -> None:
		self.txtResumen.SetValue(textoResumen(self.gestor.resumen()))
		self.txtResumen.SetInsertionPoint(0)
		top = self.gestor.top(10)
		self.listTop.Set([f"{i.get('titulo', '')} - {i.get('veces', 0)} veces" for i in top] or ["Sin datos"])
		self.listTop.SetSelection(0)

	def _onLimpiar(self, evt) -> None:
		if preguntar("¿Desea eliminar todas las estadísticas?", self):
			self.gestor.vaciar()
			self._mostrar()


# =================================================================== historial de búsqueda
class DialogoHistorialBusqueda(_Base):
	"""Últimas búsquedas; Intro (o «Buscar de nuevo») repite la elegida."""

	def __init__(self, parent, controlador) -> None:
		super().__init__(parent, "Historial de búsqueda", size=(560, 400))
		self.control = controlador
		self.entradas = controlador.historialBusqueda.obtener(limite=controlador.historialBusqueda.MAXIMO)
		self.elegida: dict | None = None
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "Últimas &búsquedas:")
		self.lista = wx.ListBox(self, size=(520, 260))
		s.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnBuscar = wx.Button(self, wx.ID_OK, "Buscar de &nuevo")
		self.btnBuscar.SetDefault()
		self.btnVaciar = wx.Button(self, label="&Vaciar historial de búsqueda")
		cerrar = wx.Button(self, wx.ID_CANCEL, "C&errar")
		for b in (self.btnBuscar, self.btnVaciar, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizer(s)
		self.btnBuscar.Bind(wx.EVT_BUTTON, self._onBuscar)
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, self._onBuscar)
		self.btnVaciar.Bind(wx.EVT_BUTTON, self._onVaciar)
		cerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CANCEL))
		self._rellenar()
		self.CentreOnScreen()
		self.lista.SetFocus()

	@staticmethod
	def texto(e: dict) -> str:
		cat = e.get("categoria", -1)
		donde = "Búsqueda global" if cat == -1 else (ajustes.CATEGORIAS[cat][1] if 0 <= cat < len(ajustes.CATEGORIAS) else "")
		return f"{e.get('texto', '')} - {donde}, por {e.get('filtro', '')} - {e.get('fecha', '')}"

	def _rellenar(self) -> None:
		self.lista.Set([self.texto(e) for e in self.entradas] or ["No hay búsquedas"])
		self.lista.SetSelection(0)
		self.btnBuscar.Enable(bool(self.entradas))
		self.btnVaciar.Enable(bool(self.entradas))

	def _onBuscar(self, evt) -> None:
		sel = self.lista.GetSelection()
		if 0 <= sel < len(self.entradas):
			self.elegida = self.entradas[sel]
			self.EndModal(wx.ID_OK)

	def _onVaciar(self, evt) -> None:
		if preguntar("Se eliminará el historial de búsqueda.\n¿Desea continuar?", self):
			self.control.historialBusqueda.vaciar()
			self.entradas = []
			self._rellenar()


# =================================================================== acerca de
CHANGELOG = (
	"Versión 1.0.0 para Tiresias (2026)\n"
	"- Primera versión para Tiresias, reescrita a partir de Audiocinemateca 2.0 para NVDA.\n"
	"- Reproductor con un envoltorio propio de la biblioteca BASS (sin sound_lib).\n"
	"- Credenciales cifradas con la protección de datos de Windows.\n"
	"- Opciones en la categoría «Audiocinemateca» de las Opciones de Tiresias, con elección del dispositivo de salida.\n"
	"- Historial de búsqueda consultable desde el menú de la ventana.\n"
	"\n"
	"Versión 2.0 para NVDA (2026)\n"
	"- Reescritura completa del complemento.\n"
	"- Nuevo reproductor basado en sound_lib (BASS) en lugar de VLC.\n"
	"- Compatible con NVDA 2026.1 (64 bits).\n"
	"- Interfaz reorganizada con pestañas y controles de reproducción integrados.\n"
	"- Sistema de favoritos por categoría.\n"
	"- Marcas de visualización para reanudar donde se dejó.\n"
	"- Búsqueda por múltiples campos en todas las categorías.\n"
	"- Descarga de contenidos a disco.\n"
	"- Control externo del reproductor con scripts de teclado.\n"
	"- Tecla F12 para activar/desactivar mensajes informativos.\n"
	"- Menú contextual para cambiar el filtro de búsqueda.\n"
	"- Historial de reproducción.\n"
	"- Historial de búsqueda.\n"
	"- Ecualizador con presets.\n"
	"- Temporizador de sueño.\n"
	"- Listas personalizadas.\n"
	"- Copiar información de contenido al portapapeles.\n"
	"- Búsqueda global unificada.\n"
	"- Cola de descargas en segundo plano.\n"
	"- Reproducción offline de contenidos descargados.\n"
	"- Diálogo \"Acerca de\" con información del complemento.\n"
	"- Estadísticas de uso.\n"
)


def textoAcercaDe(versionBd) -> str:
	lineas = [
		"Audiocinemateca para Tiresias",
		f"Versión del complemento: {ajustes.VERSION_COMPLEMENTO} (basada en la {ajustes.VERSION_ORIGINAL} para NVDA)",
	]
	if versionBd:
		lineas.append(f"Versión de la base de datos: {red.formatearVersion(versionBd)}")
	try:
		from . import bass

		lineas.append(f"Biblioteca de audio: BASS {bass.version()} (Un4seen Developments, gratuita para uso no comercial)")
	except Exception:
		pass
	lineas += [
		"",
		"Autor: Héctor J. Benítez Corredera",
		"Licencia: GNU General Public License",
		f"Web: {ajustes.URL_WEB}",
		"",
		"--- Registro de cambios ---",
		"",
	]
	return "\n".join(lineas) + "\n" + CHANGELOG


class DialogoAcercaDe(_Base):
	def __init__(self, parent, versionBd) -> None:
		super().__init__(parent, "Acerca de Audiocinemateca", size=(560, 460))
		self.idEscape = wx.ID_CLOSE
		s = wx.BoxSizer(wx.VERTICAL)
		_etiqueta(self, s, "&Información del complemento:")
		self.txtInfo = wx.TextCtrl(self, style=wx.TE_MULTILINE | wx.TE_READONLY, size=(520, 320))
		s.Add(self.txtInfo, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		web = wx.Button(self, label="&Visitar la web")
		donar = wx.Button(self, label="&Donar")
		cerrar = wx.Button(self, wx.ID_CLOSE, "&Cerrar")
		for b in (web, donar, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		s.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizer(s)
		web.Bind(wx.EVT_BUTTON, lambda e: abrirWeb(ajustes.URL_WEB))
		donar.Bind(wx.EVT_BUTTON, lambda e: abrirWeb(ajustes.URL_DONACIONES))
		cerrar.Bind(wx.EVT_BUTTON, lambda e: self.EndModal(wx.ID_CLOSE))
		self.txtInfo.SetValue(textoAcercaDe(versionBd))
		self.txtInfo.SetInsertionPoint(0)
		self.CentreOnScreen()
		self.txtInfo.SetFocus()
