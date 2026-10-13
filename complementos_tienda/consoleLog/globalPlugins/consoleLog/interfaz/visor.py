"""Visor accesible de la consola.

Un cuadro de texto de solo lectura con la captura de la consola, menús,
búsqueda, ir a línea, guardado en UTF-8, herramientas y seguimiento en tiempo
real. El seguimiento aplica solo la diferencia entre capturas sin mover el
foco, el cursor, la selección ni el desplazamiento: si se está leyendo una
línea anterior, todo se queda donde estaba; si se estaba al final, se sigue
el final.
"""

from __future__ import annotations

import os
import time

import wx

from tiresias.gui.helpers import bringToFront, speakMessage
from tiresias.log import getLogger

from .. import avisos
from .. import configuracion as cfg
from ..herramientas import nombre_categoria
from ..procesador_texto import DetectorIndentacion, FiltroPuntuacion
from ..seguimiento import adaptar_intervalo, calcular_actualizacion, normalizar_captura, recortar_documento, trasladar_posicion

log = getLogger("consoleLog")

AYUDA_ATAJOS = (
	"Atajos de teclado del visor de consola:\n\n"
	"• Alt: activar la barra de menús\n"
	"• Control+F: buscar texto dentro del visor\n"
	"• F3: buscar la coincidencia siguiente\n"
	"• Mayúsculas+F3: buscar la coincidencia anterior\n"
	"• Control+Mayúsculas+F: activar o desactivar el seguimiento automático\n"
	"• Control+G: ir a una línea\n"
	"• Control+P: abrir las opciones del complemento\n"
	"• Control+S: guardar el contenido como archivo de texto (UTF-8)\n"
	"• Control+C: copiar el texto seleccionado\n"
	"• Control+A: seleccionar todo el texto\n"
	"• F1: anunciar la posición del cursor (línea y columna)\n"
	"• F2: mostrar esta ayuda\n"
	"• F5: actualizar el contenido capturando de nuevo la consola\n"
	"• Control+Fin: ir al final (lo más reciente)\n"
	"• Escape: cerrar el visor\n\n"
	"Las herramientas del menú Plugins usan el texto seleccionado; si no hay selección, todo el documento.\n\n"
	"El seguimiento añade los cambios en segundo plano. Si está leyendo una línea anterior, se conservan el "
	"cursor, la selección, el desplazamiento y el foco; solo se sigue el final si ya estaba allí. "
	"El intervalo, el historial, las alertas y los sonidos se configuran en Archivo, Opciones."
)


class VisorConsola(wx.Frame):
	def __init__(self, complemento, contenido: str, destino, identidad, gestor_lectores, etiqueta: str = "") -> None:
		titulo = "Visor de consola"
		if etiqueta:
			titulo = "{} — {}".format(titulo, etiqueta)
		super().__init__(None, wx.ID_ANY, titulo, size=(800, 600))
		self._complemento = complemento
		self._destino = destino
		self._identidad = identidad
		self._gestor_lectores = gestor_lectores
		self._contenido, _descartados = recortar_documento(normalizar_captura(contenido), cfg.maxCaracteres())
		self._ultima_captura = self._contenido
		self._ultima_busqueda = ""
		self._automatico = False
		self._lectura_activa = False
		self._cerrando = False
		self._inicio_refresco = 0.0
		self._intervalo_actual = cfg.intervalo()
		self._linea_anterior = -1
		self._indentacion_anterior = ""
		self._mapa_herramientas: dict[int, str] = {}

		self._crear_interfaz()
		self._crear_menu()
		self._configurar_eventos()
		self._timer = wx.Timer(self)
		self.Bind(wx.EVT_TIMER, self._al_refrescar, self._timer)

		self._texto.SetValue(self._contenido)
		self._texto.SetInsertionPoint(0)
		self._aplicar_configuracion()
		self._actualizar_barra_estado()

	# ------------------------------------------------------------------ interfaz
	def _crear_interfaz(self) -> None:
		sizer = wx.BoxSizer(wx.VERTICAL)
		self._texto = wx.TextCtrl(self, wx.ID_ANY, size=(800, 600), style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
		self._texto.SetName("Contenido de la consola")
		sizer.Add(self._texto, 1, wx.EXPAND | wx.ALL, 2)
		self._barra_estado = self.CreateStatusBar(3)
		self._barra_estado.SetStatusWidths([150, 150, -1])
		self.SetSizer(sizer)
		# El ajuste debe ir antes de la barra de menús para que Alt la active bien.
		sizer.Fit(self)

	def _crear_menu(self) -> None:
		barra = wx.MenuBar()
		archivo = wx.Menu()
		self._item(archivo, "&Guardar como...\tCtrl+S", self._al_guardar, wx.ID_SAVEAS)
		archivo.AppendSeparator()
		self._item(archivo, "&Opciones...\tCtrl+P", self._al_abrir_opciones)
		archivo.AppendSeparator()
		self._item(archivo, "&Salir\tAlt+F4", self._al_salir, wx.ID_EXIT)
		barra.Append(archivo, "&Archivo")

		edicion = wx.Menu()
		self._item(edicion, "&Copiar\tCtrl+C", self._al_copiar, wx.ID_COPY)
		self._item(edicion, "&Seleccionar todo\tCtrl+A", self._al_seleccionar_todo, wx.ID_SELECTALL)
		edicion.AppendSeparator()
		self._item(edicion, "&Buscar...\tCtrl+F", self._al_buscar, wx.ID_FIND)
		self._item(edicion, "Buscar s&iguiente\tF3", lambda e: self._buscar_siguiente_anterior("adelante"))
		self._item(edicion, "Buscar &anterior\tShift+F3", lambda e: self._buscar_siguiente_anterior("atras"))
		barra.Append(edicion, "&Edición")

		ver = wx.Menu()
		self._item(ver, "&Posición actual\tF1", self._al_mostrar_posicion)
		self._item(ver, "&Ir a línea...\tCtrl+G", self._al_ir_a_linea)
		ver.AppendSeparator()
		self._item(ver, "&Actualizar contenido\tF5", self._al_refrescar, wx.ID_REFRESH)
		ver.AppendSeparator()
		self.item_seguimiento = ver.AppendCheckItem(wx.ID_ANY, "&Seguimiento automático\tCtrl+Shift+F")
		self.Bind(wx.EVT_MENU, self._al_conmutar_seguimiento, self.item_seguimiento)
		barra.Append(ver, "&Ver")

		self._menu_herramientas = wx.Menu()
		self._crear_menu_herramientas(self._menu_herramientas)
		barra.Append(self._menu_herramientas, "&Plugins")

		ayuda = wx.Menu()
		self._item(ayuda, "&Atajos de teclado\tF2", self._al_mostrar_atajos, wx.ID_HELP)
		self._item(ayuda, "&Documentación del complemento", self._al_documentacion)
		barra.Append(ayuda, "A&yuda")
		self.SetMenuBar(barra)

	def _item(self, menu: wx.Menu, etiqueta: str, accion, ident: int = wx.ID_ANY) -> wx.MenuItem:
		item = menu.Append(ident, etiqueta)
		self.Bind(wx.EVT_MENU, accion, item)
		return item

	def _crear_menu_herramientas(self, menu: wx.Menu) -> None:
		gestor = self._complemento.herramientas
		self._mapa_herramientas = {}
		entradas = []
		for nombre in sorted(gestor.listar_plugins_cargados()):
			if nombre == "clic_derecho":
				continue
			h = gestor.obtener_plugin(nombre)
			meta = h.obtener_metadatos() if h else None
			if meta:
				entradas.append((nombre_categoria(meta.categoria), meta.nombre, nombre))
		if not entradas:
			vacio = menu.Append(wx.ID_ANY, "No hay plugins habilitados")
			vacio.Enable(False)
			return
		if not cfg.valor("categorizarHerramientas"):
			for _cat, etiqueta, nombre in sorted(entradas, key=lambda e: e[1].lower()):
				item = menu.Append(wx.ID_ANY, etiqueta)
				self._mapa_herramientas[item.GetId()] = nombre
				self.Bind(wx.EVT_MENU, self._al_ejecutar_herramienta, item)
			return
		categorias: dict[str, list] = {}
		for cat, etiqueta, nombre in entradas:
			categorias.setdefault(cat, []).append((etiqueta, nombre))
		for cat in sorted(categorias, key=str.lower):
			sub = wx.Menu()
			for etiqueta, nombre in sorted(categorias[cat], key=lambda e: e[0].lower()):
				item = sub.Append(wx.ID_ANY, etiqueta)
				self._mapa_herramientas[item.GetId()] = nombre
				self.Bind(wx.EVT_MENU, self._al_ejecutar_herramienta, item)
			menu.AppendSubMenu(sub, cat)

	def _actualizar_menu_herramientas(self) -> None:
		barra = self.GetMenuBar()
		for i in range(barra.GetMenuCount()):
			if barra.GetMenuLabelText(i) == "Plugins":
				nuevo = wx.Menu()
				self._crear_menu_herramientas(nuevo)
				viejo = barra.Replace(i, nuevo, "&Plugins")
				self._menu_herramientas = nuevo
				if viejo is not None:
					viejo.Destroy()
				break

	def _configurar_eventos(self) -> None:
		self.Bind(wx.EVT_CLOSE, self._al_cerrar)
		self.Bind(wx.EVT_CHAR_HOOK, self._al_char_hook)
		self._texto.Bind(wx.EVT_KEY_UP, self._al_soltar_tecla)
		self._texto.Bind(wx.EVT_LEFT_UP, self._actualizar_barra_estado)

	def _al_char_hook(self, evento: wx.KeyEvent) -> None:
		if evento.GetKeyCode() == wx.WXK_ESCAPE and not evento.HasAnyModifiers():
			self.Close()
			return
		evento.Skip()

	def _al_soltar_tecla(self, evento) -> None:
		self._actualizar_barra_estado()
		if cfg.valor("detectarIndentacion") and evento.GetKeyCode() in (wx.WXK_UP, wx.WXK_DOWN, wx.WXK_PAGEUP, wx.WXK_PAGEDOWN, wx.WXK_HOME, wx.WXK_END):
			self._anunciar_indentacion()
		evento.Skip()

	def _anunciar_indentacion(self) -> None:
		_ok, _x, y = self._texto.PositionToXY(self._texto.GetInsertionPoint())
		if y == self._linea_anterior:
			return
		self._linea_anterior = y
		linea = self._texto.GetLineText(y)
		descripcion = DetectorIndentacion.detectar_indentacion(linea) if linea.strip() else ""
		if descripcion and descripcion != self._indentacion_anterior:
			self._indentacion_anterior = descripcion
			speakMessage(descripcion)

	def _actualizar_barra_estado(self, evento=None) -> None:
		try:
			_ok, x, y = self._texto.PositionToXY(self._texto.GetInsertionPoint())
			self._barra_estado.SetStatusText("Línea: {} de {}".format(y + 1, self._texto.GetNumberOfLines()), 0)
			self._barra_estado.SetStatusText("Col: {}".format(x + 1), 1)
		except RuntimeError:
			pass
		if evento is not None:
			evento.Skip()

	def _estado(self, texto: str) -> None:
		try:
			self._barra_estado.SetStatusText(texto, 2)
		except RuntimeError:
			pass

	# ------------------------------------------------------------------ herramientas
	def _al_ejecutar_herramienta(self, evento) -> None:
		nombre = self._mapa_herramientas.get(evento.GetId())
		if nombre:
			self.ejecutar_herramienta(nombre)

	def ejecutar_herramienta(self, nombre: str):
		from tiresias.gui import messageBox

		from . import dialogos

		h = self._complemento.herramientas.obtener_plugin(nombre)
		if h is None:
			return None
		meta = h.obtener_metadatos()
		titulo = meta.nombre if meta else "Resultado de la herramienta"
		try:
			resultado = h.ejecutar(texto=self._texto.GetValue(), seleccionado=self._texto.GetStringSelection(), visor=self, complemento=self._complemento, destino=self._destino, tipo_consola=self._destino.tipo if self._destino else "")
		except Exception as e:  # noqa: BLE001
			log.exception("consoleLog: error ejecutando la herramienta %s", nombre)
			messageBox("No se pudo ejecutar la herramienta: {}".format(e), "Error", wx.OK | wx.ICON_ERROR, self)
			return None
		if nombre == "extractor_datos" and isinstance(resultado, dict):
			from ..herramientas.extractor_datos import como_lista, valor_de_elemento

			elementos = como_lista(resultado)
			if not elementos:
				messageBox("No se han podido extraer URL, rutas de archivos ni direcciones IP del contenido actual.", "Extractor de datos", wx.OK | wx.ICON_INFORMATION, self)
				return resultado
			self._mostrar_lista(elementos, "Extractor de datos", "&Seleccione un elemento:", valor_de_elemento, "Dato copiado")
		elif nombre == "json_beauty" and isinstance(resultado, list):
			if not resultado:
				messageBox("No se detectó ningún bloque JSON válido en la salida.", "Embellecedor de JSON", wx.OK | wx.ICON_INFORMATION, self)
				return resultado
			dlg = dialogos.DialogoJSON(self, resultado)
			dlg.ShowModal()
			dlg.Destroy()
		elif nombre == "copiar_salida":
			if resultado:
				self._estado("Contenido copiado")
				speakMessage("Contenido copiado")
			else:
				self._estado("Error al copiar")
				speakMessage("Error al copiar el contenido")
		elif isinstance(resultado, str):
			dlg = dialogos.DialogoTexto(self, titulo, resultado)
			dlg.ShowModal()
			dlg.Destroy()
		elif isinstance(resultado, list):
			if not resultado:
				messageBox("No se encontraron resultados para esta acción.", titulo, wx.OK | wx.ICON_INFORMATION, self)
			else:
				self._mostrar_lista([str(r) for r in resultado], titulo, "&Seleccione un elemento de la lista:")
		return resultado

	def _mostrar_lista(self, elementos: list[str], titulo: str, mensaje: str, valor=None, aviso: str = "Copiado al portapapeles") -> None:
		from . import dialogos

		dlg = dialogos.DialogoLista(self, titulo, mensaje, elementos, valor)
		if dlg.ShowModal() == wx.ID_OK and dlg.copiado:
			self._estado(aviso)
			speakMessage(aviso)
		dlg.Destroy()

	# ------------------------------------------------------------------ archivo y edición
	def _al_guardar(self, _evento) -> None:
		from . import dialogos

		if dialogos.guardar_texto(self, self._texto.GetValue(), "Guardar contenido"):
			self._estado("Archivo guardado")

	def _al_salir(self, _evento) -> None:
		self.Close()

	def _al_copiar(self, _evento) -> None:
		inicio, fin = self._texto.GetSelection()
		if inicio == fin:
			speakMessage("No hay texto seleccionado")
			return
		self._texto.Copy()

	def _al_seleccionar_todo(self, _evento) -> None:
		self._texto.SetSelection(-1, -1)

	def _al_buscar(self, _evento) -> None:
		with wx.TextEntryDialog(self, "&Texto a buscar:", "Buscar", self._ultima_busqueda) as dlg:
			if dlg.ShowModal() == wx.ID_OK:
				self._ultima_busqueda = dlg.GetValue()
				self.buscar(self._ultima_busqueda, "adelante")

	def _buscar_siguiente_anterior(self, direccion: str) -> None:
		if not self._ultima_busqueda:
			self._al_buscar(None)
		else:
			self.buscar(self._ultima_busqueda, direccion)

	def buscar(self, texto: str, direccion: str) -> int:
		"""Busca sin distinguir mayúsculas; da la vuelta al llegar al final. Devuelve la posición o -1."""
		if not texto:
			return -1
		contenido = self._texto.GetValue().lower()
		objetivo = texto.lower()
		inicio, fin = self._texto.GetSelection()
		if direccion == "adelante":
			desde = fin if fin > inicio else self._texto.GetInsertionPoint()
			pos = contenido.find(objetivo, desde)
			if pos == -1:
				pos = contenido.find(objetivo, 0)
		else:
			hasta = inicio if fin > inicio else self._texto.GetInsertionPoint()
			pos = contenido.rfind(objetivo, 0, hasta)
			if pos == -1:
				pos = contenido.rfind(objetivo)
		if pos != -1:
			self._texto.SetSelection(pos, pos + len(objetivo))
			self._texto.ShowPosition(pos)
			avisos.pitido(500, 50)
			self._actualizar_barra_estado()
		else:
			speakMessage("No se encontró: {}".format(texto))
		return pos

	def _al_ir_a_linea(self, _evento) -> None:
		total = self._texto.GetNumberOfLines()
		with wx.TextEntryDialog(self, "Ir a línea (1-{}):".format(total), "Ir a línea") as dlg:
			if dlg.ShowModal() != wx.ID_OK:
				return
			valor = dlg.GetValue().strip()
		if not self.ir_a_linea(valor):
			avisos.pitido(200, 100)

	def ir_a_linea(self, valor) -> bool:
		try:
			linea = int(valor) - 1
		except (TypeError, ValueError):
			return False
		if not 0 <= linea < self._texto.GetNumberOfLines():
			return False
		pos = self._texto.XYToPosition(0, linea)
		self._texto.SetInsertionPoint(pos)
		self._texto.ShowPosition(pos)
		self._actualizar_barra_estado()
		return True

	def _al_mostrar_posicion(self, _evento) -> None:
		_ok, x, y = self._texto.PositionToXY(self._texto.GetInsertionPoint())
		speakMessage("Línea {}, columna {}".format(y + 1, x + 1))

	def _al_mostrar_atajos(self, _evento) -> None:
		from . import dialogos

		dlg = dialogos.DialogoTexto(self, "Ayuda de atajos", AYUDA_ATAJOS, "&Atajos:", copiar=False)
		dlg.ShowModal()
		dlg.Destroy()

	def _al_documentacion(self, _evento) -> None:
		ruta = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))), "doc", "es", "readme.html")
		try:
			os.startfile(ruta)
		except OSError:
			speakMessage("No se encontró la documentación del complemento")

	# ------------------------------------------------------------------ opciones
	def _al_abrir_opciones(self, _evento) -> None:
		from .opciones import AjustesDialog

		dlg = AjustesDialog(self)
		try:
			dlg.ShowModal()
		finally:
			dlg.Destroy()
		# Aplicar también lo que cambie desde las Opciones de Tiresias.
		self.aplicar_cambios()

	def aplicar_cambios(self) -> None:
		if self._cerrando:
			return
		self._aplicar_configuracion()
		self._actualizar_menu_herramientas()
		if self.item_seguimiento.IsChecked():
			base = cfg.intervalo()
			if base != self._intervalo_actual:
				self._intervalo_actual = base
				self._timer.Start(base)

	def _aplicar_configuracion(self) -> None:
		mono = bool(cfg.valor("fuenteMonoespaciada"))
		try:
			tamano = max(8, min(30, int(cfg.valor("tamanoFuente"))))
		except (TypeError, ValueError):
			tamano = 10
		fuente = wx.Font(tamano, wx.FONTFAMILY_TELETYPE if mono else wx.FONTFAMILY_DEFAULT, wx.FONTSTYLE_NORMAL, wx.FONTWEIGHT_NORMAL, faceName="Consolas" if mono else "")
		self._texto.SetFont(fuente)
		self._texto.Refresh()

	def restaurar_geometria(self) -> None:
		"""Tamaño y posición guardados (o maximizada, como el original)."""
		if not cfg.valor("recordarTamano"):
			self.Maximize()
			return
		try:
			ancho, alto = int(cfg.valor("ancho")), int(cfg.valor("alto"))
			x, y = int(cfg.valor("posX")), int(cfg.valor("posY"))
		except (TypeError, ValueError):
			ancho, alto, x, y = 800, 600, -1, -1
		self.SetSize((max(400, ancho), max(300, alto)))
		if x >= 0 and y >= 0 and wx.Display.GetFromPoint(wx.Point(x + 20, y + 20)) != wx.NOT_FOUND:
			self.SetPosition((x, y))
		else:
			self.Centre()
		if cfg.valor("maximizado"):
			self.Maximize()

	def _guardar_geometria(self) -> None:
		if not cfg.valor("recordarTamano"):
			return
		try:
			maximizada = self.IsMaximized()
			cfg.establecer("maximizado", bool(maximizada))
			if not maximizada and not self.IsIconized():
				ancho, alto = self.GetSize()
				x, y = self.GetPosition()
				cfg.establecer("ancho", int(ancho))
				cfg.establecer("alto", int(alto))
				cfg.establecer("posX", int(x))
				cfg.establecer("posY", int(y))
		except RuntimeError:
			pass

	# ------------------------------------------------------------------ seguimiento
	def _al_refrescar(self, evento) -> None:
		"""Vuelve a capturar la consola original (F5 o temporizador)."""
		automatico = isinstance(evento, wx.TimerEvent)
		if self._cerrando or self._lectura_activa:
			# Se omite el ciclo si la captura anterior sigue en curso.
			return
		self._automatico = automatico
		debe_sonar = bool(cfg.valor("sonidosSeguimiento"))
		if automatico and not cfg.valor("sonidosAlActualizar"):
			debe_sonar = False
		if debe_sonar:
			avisos.pitido(800, 100)
		if not automatico:
			self._estado("Actualizando contenido...")
		self._lectura_activa = True
		self._inicio_refresco = time.monotonic()
		iniciada = self._gestor_lectores.leer_consola(
			self._destino,
			self._finalizar_refresco,
			self._al_error_refresco,
			emitir_beep=False,
			procesar=self._complemento.preparador(self._destino),
		)
		if not iniciada:
			self._lectura_activa = False

	def _finalizar_refresco(self, captura) -> None:
		self._lectura_activa = False
		if self._cerrando:
			return
		self._adaptar_intervalo()
		texto = getattr(captura, "texto", captura)
		if not texto:
			self._estado("No se recibió contenido nuevo")
			return
		self.aplicar_captura(texto, getattr(captura, "sin_filtrar", texto))

	def aplicar_captura(self, texto: str, sin_filtrar: str | None = None):
		"""Aplica una captura nueva conservando cursor, selección y desplazamiento."""
		nueva = normalizar_captura(texto)
		nueva, _d = recortar_documento(nueva, cfg.maxCaracteres())
		anterior = self._ultima_captura
		act = calcular_actualizacion(self._contenido, anterior, nueva, bool(cfg.valor("conservarHistorial")))
		self._ultima_captura = nueva
		self._complemento.vigilar_regiones(sin_filtrar if sin_filtrar is not None else nueva)
		if act is None:
			self._estado("Sin cambios")
			return None
		ini_sel, fin_sel = self._texto.GetSelection()
		posicion = self._texto.GetInsertionPoint()
		al_final = posicion >= self._texto.GetLastPosition() - 1
		scroll = self._texto.GetScrollPos(wx.VERTICAL)
		self._texto.Replace(act.inicio, act.fin, act.texto)
		self._contenido = self._texto.GetValue()
		self._procesar_alertas(act, anterior, nueva)
		recortado, eliminados = recortar_documento(self._contenido, cfg.maxCaracteres())
		if eliminados:
			self._texto.Remove(0, eliminados)
			self._contenido = recortado
		if al_final:
			self._texto.SetInsertionPointEnd()
			self._texto.ShowPosition(self._texto.GetLastPosition())
		else:
			ini_sel, fin_sel, posicion = (max(0, trasladar_posicion(p, act) - eliminados) for p in (ini_sel, fin_sel, posicion))
			maximo = self._texto.GetLastPosition()
			if ini_sel != fin_sel:
				self._texto.SetSelection(min(ini_sel, maximo), min(fin_sel, maximo))
			else:
				self._texto.SetInsertionPoint(min(posicion, maximo))
			self._texto.SetScrollPos(wx.VERTICAL, scroll)
		self._actualizar_barra_estado()
		self._estado("Añadidos {} caracteres".format(act.nuevos_caracteres))
		debe_sonar = bool(cfg.valor("sonidosSeguimiento"))
		if self._automatico and not cfg.valor("sonidosAlActualizar"):
			debe_sonar = False
		if debe_sonar:
			avisos.pitido(1200, 100)
		return act

	def _al_error_refresco(self, error: str) -> None:
		from tiresias.gui import messageBox

		self._lectura_activa = False
		if self._cerrando:
			return
		siguiendo = self.item_seguimiento.IsChecked()
		if siguiendo:
			self._intervalo_actual = min(cfg.INTERVALO_MAX, max(1000, self._intervalo_actual * 2))
			self._timer.Start(self._intervalo_actual)
		self._estado("Error al actualizar")
		if not siguiendo:
			messageBox("No se pudo actualizar el contenido: {}".format(error), "Error", wx.OK | wx.ICON_ERROR, self)

	def _procesar_alertas(self, act, anterior: str, nueva: str) -> None:
		"""Busca los patrones de alerta solo en el texto nuevo (una alerta por captura)."""
		if not cfg.valor("alertasHabilitadas"):
			return
		patrones = [p.lower() for p in cfg.patronesAlerta()]
		if not patrones:
			return
		if act.reinicio:
			vistas = set(anterior.splitlines())
			lineas = [linea for linea in nueva.splitlines() if linea not in vistas]
		else:
			lineas = act.texto.splitlines()
		for linea in lineas[-5:]:
			minuscula = linea.lower()
			if any(p in minuscula for p in patrones):
				if cfg.valor("alertasSonido"):
					avisos.sonidoAlerta()
				if cfg.valor("alertasVoz"):
					filtro = FiltroPuntuacion(int(cfg.valor("nivelPuntuacion") or 0))
					avisos.anunciar("Alerta detectada: {}".format(filtro.filtrar(linea.strip())))
				return

	def _al_conmutar_seguimiento(self, _evento) -> None:
		self.establecer_seguimiento(self.item_seguimiento.IsChecked())

	def establecer_seguimiento(self, activo: bool) -> None:
		self.item_seguimiento.Check(activo)
		sonidos = bool(cfg.valor("sonidosSeguimiento"))
		if activo:
			intervalo = cfg.intervalo()
			self._intervalo_actual = intervalo
			self._timer.Start(intervalo)
			self._estado("Seguimiento activado ({} ms)".format(intervalo))
			speakMessage("Seguimiento activado")
			if sonidos:
				avisos.pitido(1000, 50)
		else:
			self._timer.Stop()
			self._estado("Seguimiento desactivado")
			speakMessage("Seguimiento desactivado")
			if sonidos:
				avisos.pitido(500, 50)

	def _adaptar_intervalo(self) -> None:
		if self._cerrando or not self._inicio_refresco or not self.item_seguimiento.IsChecked():
			return
		duracion = int((time.monotonic() - self._inicio_refresco) * 1000)
		objetivo = adaptar_intervalo(cfg.intervalo(), self._intervalo_actual, duracion, cfg.INTERVALO_MAX)
		if objetivo != self._intervalo_actual:
			self._intervalo_actual = objetivo
			self._timer.Start(objetivo)

	# ------------------------------------------------------------------ ciclo de vida
	def mostrar(self) -> None:
		self.restaurar_geometria()
		self.Show()
		bringToFront(self)
		self._texto.SetFocus()

	def _al_cerrar(self, _evento) -> None:
		self._cerrar()

	def _cerrar(self) -> None:
		if self._cerrando:
			return
		self._cerrando = True
		try:
			if self._timer.IsRunning():
				self._timer.Stop()
		except RuntimeError:
			pass
		self._gestor_lectores.cancelar_lectura()
		self._guardar_geometria()
		self._complemento.desregistrar_visor(self._identidad, self)
		self._destino = None
		self.Destroy()

	def activar(self) -> None:
		"""Restaura y trae al frente el visor ya abierto de esta consola."""
		if self._cerrando:
			return
		bringToFront(self)
		self._texto.SetFocus()

	def cerrar_desde_complemento(self) -> None:
		self._cerrar()

	@property
	def texto_control(self) -> wx.TextCtrl:
		return self._texto
