"""Diálogos del Arreglo web (necesitan wx; se importan al usarlos).

- :class:`DialogoInforme`: lista de problemas con casillas; aplica los
  marcados o todos, va al elemento, describe imágenes con IA, copia el
  informe.
- :class:`DialogoSitios`: sitios con arreglos guardados y sus reglas, para
  quitarlos.
"""

from __future__ import annotations

from typing import Any, Callable

import wx

from tiresias.gui.helpers import addLabel, bringToFront, runOnGui

from . import almacen, analisis, arreglos


class DialogoInforme(wx.Dialog):
	def __init__(self, doc: Any, sitio: str, problemas: list[analisis.Problema], aplicar: Callable[[list[analisis.Problema], bool], None], describirIA: Callable[[list], None] | None = None, guardarPorDefecto: bool = True) -> None:
		super().__init__(None, title=f"Arreglo web: {sitio or 'documento'}", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self.doc = doc
		self.sitio = sitio
		self.problemas = list(problemas)
		self._aplicar = aplicar
		self._describirIA = describirIA
		sizer = wx.BoxSizer(wx.VERTICAL)
		resumen = wx.StaticText(self, label=analisis.resumen(self.problemas, sitio))
		resumen.Wrap(560)
		sizer.Add(resumen, 0, wx.ALL, 6)
		addLabel(self, sizer, "&Problemas encontrados (marca los arreglos que quieres aplicar):")
		self.lista = wx.CheckListBox(self, choices=[p.texto() for p in self.problemas], size=(600, 300))
		for i, p in enumerate(self.problemas):
			if p.tieneArreglo:
				self.lista.Check(i, True)
		if self.problemas:
			self.lista.SetSelection(0)
		sizer.Add(self.lista, 1, wx.EXPAND | wx.ALL, 6)
		self.guardar = wx.CheckBox(self, label="&Guardar los arreglos para este sitio (se aplican solos la próxima vez)")
		self.guardar.SetValue(bool(guardarPorDefecto))
		sizer.Add(self.guardar, 0, wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		self.btnAplicar = wx.Button(self, label="&Aplicar los marcados")
		self.btnAplicar.Bind(wx.EVT_BUTTON, lambda evt: self.aplicar(False))
		self.btnTodos = wx.Button(self, label="Aplicar &todos")
		self.btnTodos.Bind(wx.EVT_BUTTON, lambda evt: self.aplicar(True))
		self.btnIr = wx.Button(self, label="&Ir al elemento")
		self.btnIr.Bind(wx.EVT_BUTTON, lambda evt: self.irAlElemento())
		self.btnIA = wx.Button(self, label="&Describir las imágenes con IA")
		self.btnIA.Bind(wx.EVT_BUTTON, lambda evt: self.describirImagenes())
		self.btnIA.Enable(describirIA is not None and any(p.tipo == "imagenSinAlt" for p in self.problemas))
		self.btnCopiar = wx.Button(self, label="&Copiar el informe")
		self.btnCopiar.Bind(wx.EVT_BUTTON, lambda evt: self.copiarInforme())
		cerrar = wx.Button(self, wx.ID_CANCEL, "Cerrar")
		for b in (self.btnAplicar, self.btnTodos, self.btnIr, self.btnIA, self.btnCopiar, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.lista.Bind(wx.EVT_LISTBOX_DCLICK, lambda evt: self.irAlElemento())
		self.CentreOnScreen()

	def marcados(self) -> list[analisis.Problema]:
		return [p for i, p in enumerate(self.problemas) if self.lista.IsChecked(i) and p.tieneArreglo]

	def aplicar(self, todos: bool) -> None:
		elegidos = [p for p in self.problemas if p.tieneArreglo] if todos else self.marcados()
		guardar = self.guardar.GetValue()
		self.Destroy()
		self._aplicar(elegidos, guardar)

	def irAlElemento(self) -> None:
		i = self.lista.GetSelection()
		if i == wx.NOT_FOUND or self.problemas[i].node is None:
			wx.Bell()
			return
		offset = self.problemas[i].offset
		doc = self.doc
		self.Destroy()
		from tiresias import queue_handler

		queue_handler.queueFunction(doc.moveToOffsetFromGui, offset)

	def describirImagenes(self) -> None:
		if self._describirIA is None:
			return
		nodos = [p.node for p in self.problemas if p.tipo == "imagenSinAlt" and p.node is not None]
		self.Destroy()
		self._describirIA(nodos)

	def copiarInforme(self) -> None:
		from tiresias import api, queue_handler

		texto = analisis.informeTexto(self.problemas, self.sitio)
		queue_handler.queueFunction(api.copyToClip, texto, True)


def mostrarInforme(doc: Any, sitio: str, problemas: list, aplicar: Callable, describirIA: Callable | None, guardarPorDefecto: bool) -> None:
	def _show() -> None:
		dlg = DialogoInforme(doc, sitio, problemas, aplicar, describirIA, guardarPorDefecto)
		dlg.Show()
		bringToFront(dlg)
		dlg.lista.SetFocus()

	runOnGui(_show)


class DialogoSitios(wx.Dialog):
	"""Sitios con arreglos guardados; permite quitar reglas sueltas o todo un sitio."""

	def __init__(self, alCambiar: Callable[[str], None] | None = None) -> None:
		super().__init__(None, title="Arreglo web: arreglos guardados", style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER)
		self._alCambiar = alCambiar
		sizer = wx.BoxSizer(wx.VERTICAL)
		addLabel(self, sizer, "&Sitios con arreglos:")
		self.sitios = wx.ListBox(self, size=(480, 120))
		self.sitios.Bind(wx.EVT_LISTBOX, lambda evt: self.mostrarSitio())
		sizer.Add(self.sitios, 0, wx.EXPAND | wx.ALL, 6)
		addLabel(self, sizer, "&Arreglos del sitio:")
		self.reglas = wx.ListBox(self, size=(480, 180))
		sizer.Add(self.reglas, 1, wx.EXPAND | wx.ALL, 6)
		botones = wx.BoxSizer(wx.HORIZONTAL)
		quitar = wx.Button(self, label="&Quitar el arreglo")
		quitar.Bind(wx.EVT_BUTTON, lambda evt: self.quitarRegla())
		quitarSitio = wx.Button(self, label="Quitar &todo el sitio")
		quitarSitio.Bind(wx.EVT_BUTTON, lambda evt: self.quitarSitio())
		cerrar = wx.Button(self, wx.ID_CANCEL, "Cerrar")
		for b in (quitar, quitarSitio, cerrar):
			botones.Add(b, 0, wx.ALL, 4)
		sizer.Add(botones, 0, wx.ALIGN_RIGHT | wx.ALL, 4)
		self.SetSizerAndFit(sizer)
		self.SetEscapeId(wx.ID_CANCEL)
		self.Bind(wx.EVT_BUTTON, lambda evt: self.Destroy(), id=wx.ID_CANCEL)
		self.Bind(wx.EVT_CLOSE, lambda evt: self.Destroy())
		self.cargar()
		self.CentreOnScreen()

	def cargar(self, seleccionar: str | None = None) -> None:
		datos = almacen.sitios()
		self.claves = sorted(datos)
		self.sitios.Set([f"{s} ({n})" for s in self.claves for n in (datos[s],)] or ["(ningún sitio con arreglos)"])
		if self.claves:
			i = self.claves.index(seleccionar) if seleccionar in self.claves else 0
			self.sitios.SetSelection(i)
		self.mostrarSitio()

	@property
	def sitio(self) -> str | None:
		i = self.sitios.GetSelection()
		return self.claves[i] if self.claves and i != wx.NOT_FOUND else None

	def mostrarSitio(self) -> None:
		s = self.sitio
		lista = almacen.listaDe(s) if s else []
		self.reglas.Set([arreglos.describirRegla(r) for r in lista] or ["(sin arreglos)"])
		if lista:
			self.reglas.SetSelection(0)

	def quitarRegla(self) -> None:
		s = self.sitio
		i = self.reglas.GetSelection()
		if not s or i == wx.NOT_FOUND:
			wx.Bell()
			return
		regla = almacen.quitarRegla(s, i)
		if regla is not None and regla.get("tipo") == "ocultar":
			_quitarOcultaFlex(s, regla)
		self.cargar(s)
		if self._alCambiar is not None:
			self._alCambiar(s)

	def quitarSitio(self) -> None:
		s = self.sitio
		if not s:
			wx.Bell()
			return
		for regla in almacen.quitarSitio(s):
			if regla.get("tipo") == "ocultar":
				_quitarOcultaFlex(s, regla)
		self.cargar()
		if self._alCambiar is not None:
			self._alCambiar(s)


def _quitarOcultaFlex(sitio: str, regla: dict) -> None:
	"""Quita de la web flexible la regla de ocultación que puso el arreglo."""
	try:
		from tiresias.browse import flexweb

		flex = regla.get("flex") or {}
		clave = regla.get("doc") or ("https://" + sitio + "/")
		ocultas = flexweb.rulesFor(clave).hidden
		for i, r in enumerate(ocultas):
			if r == flex:
				flexweb.removeHidden(clave, i)
				break
	except Exception:
		pass


def mostrarSitios(alCambiar: Callable[[str], None] | None = None) -> None:
	def _show() -> None:
		dlg = DialogoSitios(alCambiar)
		dlg.Show()
		bringToFront(dlg)
		dlg.sitios.SetFocus()

	runOnGui(_show)
