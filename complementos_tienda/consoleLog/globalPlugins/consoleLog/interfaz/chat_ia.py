"""Chat de inteligencia artificial sobre la salida de la consola.

Cada turno se presenta como un artículo HTML con el autor como encabezado,
navegable en modo exploración. Cuando llega una respuesta solo se avisa de
que está lista: el foco y la posición de lectura no se mueven.

Teclas: F6 alterna entre el historial y los controles; Control+Intro envía;
J y K anuncian el turno siguiente o anterior (fuera del cuadro de edición);
Escape cierra.
"""

from __future__ import annotations

import os
import threading

import wx

from tiresias.gui.helpers import isAlive, speakMessage
from tiresias.log import getLogger

from .. import avisos, ia
from .. import configuracion as cfg
from ..markdown_html import markdown_a_html
from .webview import WebViewAccesible, formatear_mensaje

log = getLogger("consoleLog")

TITULO_HISTORIAL = "Historial del chat de IA"
MAX_ADJUNTO = 1024 * 1024
AYUDA = (
	"Atajos de teclado del chat de IA:\n\n"
	"• F6: alternar entre el historial HTML y los controles del chat\n"
	"• H o 1 a 6: navegar por los encabezados del historial (modo exploración)\n"
	"• Tabulador: recorrer los enlaces y elementos del documento HTML\n"
	"• J: anunciar el turno siguiente\n"
	"• K: anunciar el turno anterior\n"
	"• Control+Intro: enviar el mensaje\n"
	"• Escape o Alt+F4: cerrar el chat\n\n"
	"Las respuestas en Markdown se presentan como HTML semántico."
)
NOMBRES_CORTOS_PROVEEDOR = {
	"google": "Google AI (claves del complemento)",
	"tiresias": "Proveedor de IA de Tiresias",
	"anthropic": "Anthropic Claude",
	"openai": "OpenAI",
	"gemini": "Google Gemini (Tiresias)",
	"local": "Servidor local",
}


class ChatIADialog(wx.Frame):
	def __init__(self, parent, herramienta, texto_completo: str, seleccionado: str, usar_webview: bool = True) -> None:
		super().__init__(parent, wx.ID_ANY, "Chat con inteligencia artificial", size=(760, 640))
		self.herramienta = herramienta
		self.texto_completo = texto_completo or ""
		self.seleccionado = seleccionado or ""
		self.historial: list[ia.Turno] = []
		self._navegacion: list[str] = []
		self._historial_html: list[str] = []
		self._indice = -1
		self.adjuntos: list[dict] = []
		self._mapa_modelos: dict[int, str] = {}
		self._mapa_proveedores: dict[int, str] = {}
		self._peticion_activa = False
		self._usar_webview = usar_webview
		self._crear_interfaz()
		self._crear_menu()
		self.SetMinSize((520, 420))
		self.Centre()
		self.Bind(wx.EVT_CLOSE, self._al_cerrar)
		wx.CallAfter(self.txt_entrada.SetFocus)
		self._cargar_modelos()

	# ------------------------------------------------------------------ interfaz
	def _crear_interfaz(self) -> None:
		panel = self.panel = wx.Panel(self)
		sizer = wx.BoxSizer(wx.VERTICAL)
		self.vista = WebViewAccesible(panel, titulo=TITULO_HISTORIAL, al_volver=self._enfocar_controles, al_cerrar=self._cerrar_seguro, usar_webview=self._usar_webview)
		sizer.Add(self.vista.control, 1, wx.EXPAND | wx.ALL, 5)
		self.lbl_adjuntos = wx.StaticText(panel, label="Adjuntos: ninguno")
		sizer.Add(self.lbl_adjuntos, 0, wx.LEFT | wx.RIGHT, 10)
		opciones = wx.BoxSizer(wx.HORIZONTAL)
		self.cb_seleccion = wx.CheckBox(panel, label="Usar &selección")
		self.cb_seleccion.SetValue(bool(self.seleccionado))
		self.cb_seleccion.Enable(bool(self.seleccionado))
		self.cb_consola = wx.CheckBox(panel, label="Usar &consola")
		self.btn_adjuntar = wx.Button(panel, label="&Adjuntar .txt...")
		self.btn_reparar = wx.Button(panel, label="Auto-re&parar error")
		self.btn_historial = wx.Button(panel, label="Abrir &historial HTML")
		self.btn_limpiar = wx.Button(panel, label="&Limpiar chat")
		for c in (self.cb_seleccion, self.cb_consola):
			opciones.Add(c, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		opciones.Add(self.btn_adjuntar, 0, wx.ALL, 5)
		opciones.Add(self.btn_reparar, 0, wx.ALL, 5)
		opciones.AddStretchSpacer()
		opciones.Add(self.btn_historial, 0, wx.ALL, 5)
		opciones.Add(self.btn_limpiar, 0, wx.ALL, 5)
		sizer.Add(opciones, 0, wx.EXPAND)
		entrada = wx.BoxSizer(wx.HORIZONTAL)
		etiqueta = wx.StaticText(panel, label="&Mensaje:")
		self.txt_entrada = wx.TextCtrl(panel, size=(-1, 70), style=wx.TE_MULTILINE)
		self.btn_enviar = wx.Button(panel, label="&Enviar (Control+Intro)")
		entrada.Add(etiqueta, 0, wx.ALL | wx.ALIGN_CENTER_VERTICAL, 5)
		entrada.Add(self.txt_entrada, 1, wx.EXPAND | wx.ALL, 5)
		entrada.Add(self.btn_enviar, 0, wx.ALIGN_CENTER_VERTICAL | wx.RIGHT, 5)
		sizer.Add(entrada, 0, wx.EXPAND)
		panel.SetSizer(sizer)
		self.btn_adjuntar.Bind(wx.EVT_BUTTON, self._al_adjuntar)
		self.btn_reparar.Bind(wx.EVT_BUTTON, self._al_reparar)
		self.btn_historial.Bind(wx.EVT_BUTTON, self._al_abrir_historial)
		self.btn_limpiar.Bind(wx.EVT_BUTTON, self._al_limpiar)
		self.btn_enviar.Bind(wx.EVT_BUTTON, self._al_enviar)
		self.Bind(wx.EVT_CHAR_HOOK, self._al_tecla)

	def _crear_menu(self) -> None:
		barra = wx.MenuBar()
		menu = wx.Menu()
		item = menu.Append(wx.ID_ANY, "Gestionar &claves de API de Google (una por línea)...")
		self.Bind(wx.EVT_MENU, self._al_gestionar_claves, item)
		self.menu_proveedor = wx.Menu()
		actual = str(cfg.valor("iaProveedor") or "google")
		for valor, _etiqueta in cfg.PROVEEDORES_IA:
			it = self.menu_proveedor.AppendRadioItem(wx.ID_ANY, NOMBRES_CORTOS_PROVEEDOR.get(valor, valor))
			self._mapa_proveedores[it.GetId()] = valor
			it.Check(valor == actual)
			self.Bind(wx.EVT_MENU, self._al_cambiar_proveedor, it)
		menu.AppendSubMenu(self.menu_proveedor, "&Proveedor")
		self.menu_modelos = wx.Menu()
		menu.AppendSubMenu(self.menu_modelos, "&Modelo")
		item = menu.Append(wx.ID_ANY, "Editar las &instrucciones de sistema...")
		self.Bind(wx.EVT_MENU, self._al_editar_prompt, item)
		self.item_historial = menu.AppendCheckItem(wx.ID_ANY, "Mantener el &historial de la conversación")
		self.item_historial.Check(bool(cfg.valor("iaMantenerHistorial")))
		self.Bind(wx.EVT_MENU, lambda e: cfg.establecer("iaMantenerHistorial", self.item_historial.IsChecked()), self.item_historial)
		menu.AppendSeparator()
		item = menu.Append(wx.ID_CLOSE, "Ce&rrar el chat\tAlt+F4")
		self.Bind(wx.EVT_MENU, lambda e: self.Close(), item)
		barra.Append(menu, "&IA")
		ayuda = wx.Menu()
		item = ayuda.Append(wx.ID_ANY, "&Atajos de teclado...")
		self.Bind(wx.EVT_MENU, self._al_atajos, item)
		barra.Append(ayuda, "A&yuda")
		self.SetMenuBar(barra)

	def _al_atajos(self, _evt) -> None:
		from .dialogos import DialogoTexto

		dlg = DialogoTexto(self, "Atajos de teclado", AYUDA, "&Atajos:", copiar=False)
		dlg.ShowModal()
		dlg.Destroy()

	def _al_tecla(self, evt: wx.KeyEvent) -> None:
		tecla = evt.GetKeyCode()
		foco = self.FindFocus()
		if tecla == wx.WXK_F6 and not evt.HasAnyModifiers():
			if foco is self.vista.control:
				self._enfocar_controles()
			else:
				self.vista.enfocar()
			return
		if tecla in (wx.WXK_RETURN, wx.WXK_NUMPAD_ENTER) and evt.GetModifiers() == wx.MOD_CONTROL:
			self._al_enviar(None)
			return
		if tecla == wx.WXK_ESCAPE and not evt.HasAnyModifiers():
			self.Close()
			return
		if foco is self.txt_entrada or foco is self.vista.control or evt.HasAnyModifiers():
			evt.Skip()
			return
		if tecla in (ord("J"), ord("j")):
			self.navegar(1)
		elif tecla in (ord("K"), ord("k")):
			self.navegar(-1)
		else:
			evt.Skip()

	def _cerrar_seguro(self) -> None:
		if isAlive(self) and not getattr(self, "_cerrando", False):
			self.Close()

	def _enfocar_controles(self) -> None:
		if not isAlive(self):
			return
		if self.cb_seleccion.IsEnabled():
			self.cb_seleccion.SetFocus()
		else:
			self.txt_entrada.SetFocus()

	def navegar(self, direccion: int) -> str:
		if not self._navegacion:
			speakMessage("El historial está vacío.")
			return ""
		total = len(self._navegacion)
		self._indice += direccion
		vuelta = False
		if self._indice >= total:
			self._indice = 0
			vuelta = True
		elif self._indice < 0:
			self._indice = total - 1
			vuelta = True
		if vuelta:
			avisos.pitido(1000, 100)
		mensaje = self._navegacion[self._indice]
		speakMessage(mensaje)
		return mensaje

	# ------------------------------------------------------------------ modelos y opciones
	def _cargar_modelos(self) -> None:
		proveedor = str(cfg.valor("iaProveedor") or "google")
		if proveedor != "google":
			cliente = ia.cliente_actual()
			self._poner_modelos(None, "Modelo: {} (se cambia en las opciones de IA de Tiresias)".format(cliente.modelo() or "predeterminado"))
			return

		def trabajo() -> None:
			try:
				modelos = ia.ListadorModelos().obtener_modelos(ia.cargar_claves())
			except Exception:
				log.debug("consoleLog: no se pudo obtener la lista de modelos", exc_info=True)
				modelos = list(ia.MODELOS_RESERVA)
			wx.CallAfter(self._poner_modelos, modelos, "")

		threading.Thread(target=trabajo, name="consoleLogModelos", daemon=True).start()

	def _poner_modelos(self, modelos: list[str] | None, aviso: str) -> None:
		if not isAlive(self):
			return
		for item in list(self.menu_modelos.GetMenuItems()):
			self.menu_modelos.DestroyItem(item)
		self._mapa_modelos = {}
		if modelos is None:
			item = self.menu_modelos.Append(wx.ID_ANY, aviso)
			item.Enable(False)
			return
		actual = str(cfg.valor("iaModeloGoogle") or cfg.MODELO_GOOGLE_DEFECTO)
		if actual not in modelos:
			modelos = [actual] + list(modelos)
		for m in modelos:
			item = self.menu_modelos.AppendRadioItem(wx.ID_ANY, m)
			self._mapa_modelos[item.GetId()] = m
			item.Check(m == actual)
			self.Bind(wx.EVT_MENU, self._al_cambiar_modelo, item)

	def _al_cambiar_modelo(self, evt) -> None:
		modelo = self._mapa_modelos.get(evt.GetId())
		if modelo:
			cfg.establecer("iaModeloGoogle", modelo)
			speakMessage("Modelo {}".format(modelo))

	def _al_cambiar_proveedor(self, evt) -> None:
		proveedor = self._mapa_proveedores.get(evt.GetId())
		if proveedor:
			cfg.establecer("iaProveedor", proveedor)
			speakMessage(NOMBRES_CORTOS_PROVEEDOR.get(proveedor, proveedor))
			self._cargar_modelos()

	def _al_gestionar_claves(self, _evt) -> None:
		from .dialogos import editar_claves_google

		if editar_claves_google(self):
			try:
				os.remove(ia.ListadorModelos().ruta_cache)
			except OSError:
				pass
			self._cargar_modelos()

	def _al_editar_prompt(self, _evt) -> None:
		from .dialogos import DialogoTextoEditable

		dlg = DialogoTextoEditable(self, "Instrucciones de sistema", "&Instrucciones de sistema para la IA:", str(cfg.valor("iaPromptSistema") or cfg.PROMPT_SISTEMA_DEFECTO), defecto=cfg.PROMPT_SISTEMA_DEFECTO)
		if dlg.ShowModal() == wx.ID_OK:
			cfg.establecer("iaPromptSistema", dlg.GetValue().strip() or cfg.PROMPT_SISTEMA_DEFECTO)
		dlg.Destroy()

	# ------------------------------------------------------------------ contexto
	def _al_adjuntar(self, _evt) -> None:
		from tiresias.gui import messageBox

		with wx.FileDialog(self, "Seleccionar archivos de texto", wildcard="Archivos de texto (*.txt;*.log;*.md)|*.txt;*.log;*.md|Todos los archivos (*.*)|*.*", style=wx.FD_OPEN | wx.FD_FILE_MUST_EXIST | wx.FD_MULTIPLE) as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			rutas = dlg.GetPaths()
		for ruta in rutas:
			nombre = os.path.basename(ruta)
			try:
				if os.path.getsize(ruta) > MAX_ADJUNTO * 4:
					raise ValueError
				with open(ruta, encoding="utf-8", errors="replace") as f:
					contenido = f.read()
				if len(contenido) > MAX_ADJUNTO:
					raise ValueError
			except ValueError:
				messageBox("El archivo {} es demasiado grande (máximo 1 MB).".format(nombre), "Advertencia", wx.OK | wx.ICON_WARNING, self)
				continue
			except OSError as e:
				messageBox("Error al leer {}: {}".format(ruta, e), "Error", wx.OK | wx.ICON_ERROR, self)
				continue
			self.adjuntos.append({"nombre": nombre, "texto": contenido})
		self._actualizar_adjuntos()

	def _actualizar_adjuntos(self) -> None:
		if self.adjuntos:
			self.lbl_adjuntos.SetLabel("Adjuntos: {} archivos ({})".format(len(self.adjuntos), ", ".join(a["nombre"] for a in self.adjuntos)))
		else:
			self.lbl_adjuntos.SetLabel("Adjuntos: ninguno")

	def _al_limpiar(self, _evt) -> None:
		self.vista.limpiar()
		self.historial = []
		self._navegacion = []
		self._historial_html = []
		self._indice = -1
		self.adjuntos = []
		self._actualizar_adjuntos()
		speakMessage("Chat limpiado")

	def actualizar_contexto(self, texto: str, seleccionado: str) -> None:
		if texto:
			self.texto_completo = texto
		if seleccionado:
			self.seleccionado = seleccionado
			self.cb_seleccion.Enable(True)
			self.cb_seleccion.SetValue(True)
			self.agregar_mensaje("Sistema", "Nueva selección detectada de la consola.")

	def agregar_mensaje(self, autor: str, texto: str) -> None:
		if not isAlive(self):
			return
		fragmento = formatear_mensaje(autor, markdown_a_html(texto))
		self._historial_html.append(fragmento)
		self.vista.agregar(fragmento)
		self._navegacion.append("{}: {}".format(autor, texto))

	def _al_abrir_historial(self, _evt) -> None:
		if self.vista.usa_webview:
			self.vista.enfocar()
			return
		if not self._historial_html:
			speakMessage("El historial está vacío.")
			return
		from .informe_ia import abrir_en_navegador

		abrir_en_navegador(TITULO_HISTORIAL, "\n".join(self._historial_html), "historial_chat.html")

	# ------------------------------------------------------------------ peticiones
	def _al_reparar(self, _evt) -> None:
		contexto = self.seleccionado or self.texto_completo[-20000:]
		if not contexto:
			from tiresias.gui import messageBox

			messageBox("No hay contexto para analizar.", "Auto-reparar", wx.OK | wx.ICON_INFORMATION, self)
			return
		if not self.seleccionado:
			self.cb_consola.SetValue(True)
		self.txt_entrada.SetValue(ia.PROMPT_REPARAR)
		self._al_enviar(None)

	def construir_peticion(self, pregunta: str) -> str:
		seleccion = self.seleccionado if self.cb_seleccion.IsChecked() else ""
		consola = self.texto_completo if self.cb_consola.IsChecked() else ""
		return ia.construir_prompt(pregunta, seleccion, consola, self.adjuntos)

	def _al_enviar(self, _evt) -> None:
		from tiresias.gui import messageBox

		if self._peticion_activa:
			speakMessage("Espere a que termine la respuesta anterior.")
			return
		pregunta = self.txt_entrada.GetValue().strip()
		if not pregunta:
			return
		cliente = ia.cliente_actual()
		if not cliente.configurado():
			if str(cfg.valor("iaProveedor")) == "google":
				messageBox("No hay claves de API configuradas. Añádalas en el menú IA, Gestionar claves.", "Error", wx.OK | wx.ICON_ERROR, self)
			else:
				messageBox("El proveedor {} no está configurado. Revise Opciones, Inteligencia artificial de Tiresias.".format(cliente.nombre), "Error", wx.OK | wx.ICON_ERROR, self)
			return
		self.txt_entrada.Clear()
		self._indice = -1
		self.agregar_mensaje("Tú", pregunta)
		final = self.construir_peticion(pregunta)
		turnos = (self.historial[-10:] if cfg.valor("iaMantenerHistorial") else []) + [ia.Turno("user", final)]
		prompt = str(cfg.valor("iaPromptSistema") or cfg.PROMPT_SISTEMA_DEFECTO)
		self._peticion_activa = True
		self._habilitar_entrada(False)
		speakMessage("Enviado. {} está pensando.".format(cliente.nombre))
		threading.Thread(target=self._peticion, args=(cliente, turnos, prompt, final), name="consoleLogChat", daemon=True).start()

	def _habilitar_entrada(self, habilitada: bool) -> None:
		self.txt_entrada.Enable(habilitada)
		self.btn_enviar.Enable(habilitada)
		self.btn_reparar.Enable(habilitada)

	def _peticion(self, cliente, turnos, prompt, final) -> None:
		try:
			respuesta = cliente.chat(turnos, prompt)
		except Exception as e:  # noqa: BLE001
			wx.CallAfter(self._error_peticion, str(e))
			return
		wx.CallAfter(self._fin_peticion, cliente.nombre, respuesta, final)

	def _fin_peticion(self, autor: str, respuesta: str, final: str) -> None:
		if not isAlive(self):
			return
		self._peticion_activa = False
		self._habilitar_entrada(True)
		self.agregar_mensaje(autor, respuesta)
		self.historial.append(ia.Turno("user", final))
		self.historial.append(ia.Turno("model", respuesta))
		# Solo se avisa: no se mueve el foco ni se lee la respuesta entera.
		speakMessage("Respuesta lista. Pulse F6 para leerla.")

	def _error_peticion(self, mensaje: str) -> None:
		if not isAlive(self):
			return
		self._peticion_activa = False
		self._habilitar_entrada(True)
		self.agregar_mensaje("Error", mensaje)
		speakMessage("Error al obtener la respuesta: {}".format(mensaje))

	def _al_cerrar(self, _evt) -> None:
		if getattr(self, "_cerrando", False):
			return
		self._cerrando = True
		try:
			self.herramienta.olvidar_dialogo(self)
		except Exception:
			pass
		self.Destroy()
