"""Superficie HTML accesible para wxPython (chat e informes de IA).

Adaptación propia de la idea de «wx-accessible-webview» (Copyright (c) 2026
Taylor Arndt y Community Access, licencia MIT; aviso en
``LICENCIAS_TERCEROS.txt``) que usaba el complemento original:

- documento HTML semántico (artículos con encabezado por turno, listas,
  tablas, código) que Tiresias recorre en modo exploración (H, 1 a 6, Tab...);
- región viva de estado para avisos breves («Respuesta lista») sin mover el
  foco ni forzar la lectura del contenido;
- F6 vuelve a los controles nativos y Escape cierra la ventana, también
  desde dentro del documento;
- los enlaces http y https se abren en el navegador predeterminado;
- si WebView2 no está disponible se usa un cuadro de texto de solo lectura.
"""

from __future__ import annotations

import html
import json

import wx

from ..markdown_html import html_a_texto

ESTILOS = """
:root { color-scheme: light dark; }
html, body { margin: 0; padding: 0; }
body { font-family: system-ui, Segoe UI, Arial, sans-serif; font-size: 1.05rem; line-height: 1.6; padding: 12px 16px; }
article { margin: 0 0 14px; padding: 10px 12px; border: 1px solid GrayText; border-radius: 8px; }
article h2 { font-size: 1rem; margin: 0 0 6px; }
pre { padding: 10px; overflow-x: auto; white-space: pre-wrap; word-break: break-word; border: 1px solid GrayText; }
code { font-family: ui-monospace, Consolas, monospace; }
blockquote { border-left: 4px solid GrayText; padding-left: 1rem; }
table { border-collapse: collapse; margin: .6rem 0; }
th, td { border: 1px solid GrayText; padding: .4rem .6rem; text-align: left; }
a { color: LinkText; }
:focus { outline: 2px solid Highlight; outline-offset: 2px; }
.visually-hidden { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (forced-colors: active) { article, th, td { border-color: CanvasText; } blockquote { border-left-color: CanvasText; } }
"""

ESQUEMA_ACCION = "consolelog-action://"


def formatear_mensaje(autor: str, cuerpo_html: str) -> str:
	"""Turno semántico: artículo con el autor como encabezado."""
	return '<article aria-label="{a}"><h2>{t}</h2>{c}</article>'.format(a=html.escape(autor, quote=True), t=html.escape(autor), c=cuerpo_html)


def documento(titulo: str, contenido: str, anunciar_contenido: bool = False) -> str:
	region_viva = ' aria-live="polite"' if anunciar_contenido else ""
	script = """
(function(){
 var contenido=document.getElementById('contenido');
 var estado=document.getElementById('estado');
 window.__consoleLogA11y={
  agregar:function(h){var t=document.createElement('div');t.innerHTML=h;while(t.firstChild){contenido.appendChild(t.firstChild);}},
  contenido:function(h){contenido.innerHTML=h;},
  estado:function(s){estado.textContent=s;},
  focus:function(){contenido.focus();}
 };
 document.addEventListener('keydown',function(e){
  var accion=null;
  if(e.key==='F6'){accion='volver';}
  else if(e.key==='Escape'){accion='cerrar';}
  if(accion){e.preventDefault();window.location.href='""" + ESQUEMA_ACCION + """'+accion;}
 });
})();
"""
	return (
		'<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
		'<meta name="viewport" content="width=device-width, initial-scale=1">'
		"<title>{t}</title><style>{s}</style></head><body>"
		'<div id="estado" role="status" aria-live="polite" class="visually-hidden"></div>'
		'<main id="contenido"{r} tabindex="0">{c}</main>'
		"<script>{j}</script></body></html>"
	).format(t=html.escape(titulo), s=ESTILOS, r=region_viva, c=contenido, j=script)


def webview_disponible() -> bool:
	try:
		import wx.html2 as webview

		return bool(webview.WebView.IsBackendAvailable(webview.WebViewBackendEdge))
	except Exception:
		return False


class WebViewAccesible:
	"""Documento HTML con región viva, alternativa de texto y puentes F6/Escape."""

	def __init__(self, parent, *, titulo: str, al_volver=None, al_cerrar=None, enlaces_externos: bool = True, anunciar_contenido: bool = False, contenido_inicial: str = "", usar_webview: bool = True) -> None:
		self._titulo = titulo
		self._al_volver = al_volver
		self._al_cerrar = al_cerrar
		self._anunciar = anunciar_contenido
		self._enlaces_externos = enlaces_externos
		self._listo = False
		self._pendientes: list = []
		self._quiere_foco = False
		self._web = None
		self._fallback = None
		if usar_webview and webview_disponible():
			try:
				import wx.html2 as webview

				self._web = webview.WebView.New(parent, backend=webview.WebViewBackendEdge)
				self._web.SetName(titulo)
				self._web.Bind(webview.EVT_WEBVIEW_LOADED, self._al_cargar)
				self._web.Bind(webview.EVT_WEBVIEW_NAVIGATING, self._al_navegar)
				self._web.Bind(webview.EVT_WEBVIEW_NEWWINDOW, self._al_ventana_nueva)
				self._web.SetPage(documento(titulo, contenido_inicial, anunciar_contenido), "")
			except Exception:
				self._web = None
		if self._web is None:
			self._fallback = wx.TextCtrl(parent, style=wx.TE_MULTILINE | wx.TE_READONLY | wx.TE_RICH2 | wx.TE_NOHIDESEL)
			self._fallback.SetName(titulo)
			self._fallback.SetValue(html_a_texto(contenido_inicial))
			self._fallback.Bind(wx.EVT_KEY_DOWN, self._tecla_fallback)

	@property
	def control(self):
		return self._web if self._web is not None else self._fallback

	@property
	def usa_webview(self) -> bool:
		return self._web is not None

	def agregar(self, fragmento: str) -> None:
		if self._fallback is not None:
			f = self._fallback
			inicio, fin = f.GetSelection()
			posicion = f.GetInsertionPoint()
			al_final = f.HasFocus() and posicion >= f.GetLastPosition()
			separador = "\n\n" if f.GetLastPosition() > 0 else ""
			f.AppendText(separador + html_a_texto(fragmento))
			if not al_final:
				f.SetSelection(inicio, fin)
				if inicio == fin:
					f.SetInsertionPoint(posicion)
			return
		self._hacer("agregar", fragmento)

	def contenido(self, fragmento: str) -> None:
		if self._fallback is not None:
			self._fallback.SetValue(html_a_texto(fragmento))
			return
		self._hacer("contenido", fragmento)

	def estado(self, texto: str) -> None:
		if self._web is not None:
			self._hacer("estado", texto)

	def limpiar(self) -> None:
		if self._fallback is not None:
			self._fallback.Clear()
		else:
			self.contenido("")

	def enfocar(self) -> None:
		self.control.SetFocus()
		if self._web is not None:
			if self._listo:
				self._ejecutar("window.__consoleLogA11y.focus();")
			else:
				self._quiere_foco = True

	def _hacer(self, tipo: str, carga) -> None:
		if self._listo:
			self._despachar(tipo, carga)
		else:
			self._pendientes.append((tipo, carga))

	def _despachar(self, tipo: str, carga) -> None:
		self._ejecutar("window.__consoleLogA11y.{}({});".format(tipo, json.dumps(carga)))

	def _ejecutar(self, script: str) -> None:
		try:
			self._web.RunScriptAsync(script)
		except Exception:
			try:
				self._web.RunScript(script)
			except Exception:
				pass

	def _al_cargar(self, _evento) -> None:
		self._listo = True
		pendientes, self._pendientes = self._pendientes, []
		for tipo, carga in pendientes:
			self._despachar(tipo, carga)
		if self._quiere_foco:
			self._quiere_foco = False
			self.enfocar()

	def _al_navegar(self, evento) -> None:
		url = evento.GetURL() or ""
		minuscula = url.lower()
		if minuscula.startswith(ESQUEMA_ACCION):
			evento.Veto()
			accion = minuscula[len(ESQUEMA_ACCION):].rstrip("/")
			if accion == "volver" and self._al_volver:
				wx.CallAfter(self._al_volver)
			elif accion == "cerrar" and self._al_cerrar:
				wx.CallAfter(self._al_cerrar)
			return
		if self._listo and minuscula.startswith(("http://", "https://")):
			evento.Veto()
			if self._enlaces_externos:
				import webbrowser

				webbrowser.open(url)

	def _al_ventana_nueva(self, evento) -> None:
		url = evento.GetURL() or ""
		if url.lower().startswith(("http://", "https://")) and self._enlaces_externos:
			import webbrowser

			webbrowser.open(url)

	def _tecla_fallback(self, evento) -> None:
		tecla = evento.GetKeyCode()
		if tecla == wx.WXK_F6 and self._al_volver:
			self._al_volver()
		elif tecla == wx.WXK_ESCAPE and self._al_cerrar:
			self._al_cerrar()
		else:
			evento.Skip()
