"""Definiciones de ventana: gestiona las regiones de pantalla y su modo de lectura.

Abre un diálogo para crear, editar, activar, desactivar y eliminar regiones
(se guardan entre sesiones) y para ver el informe de las regiones sobre el
texto del visor: contenido de cada región activa, cambios en las
monitorizadas y el tamaño recomendado para el contenido.
"""

from __future__ import annotations

from ..definiciones_ventana import NOMBRES_MODOS, GestorDefinicionesVentana
from . import HerramientaBase, MetadatosHerramienta


def informe_definiciones(gestor: GestorDefinicionesVentana, texto: str) -> str:
	if not texto:
		return "No hay texto para analizar."
	lineas = texto.splitlines()
	ancho_max = max((len(linea) for linea in lineas), default=0)
	partes = [gestor.obtener_resumen(), "", "=== Texto analizado ===", "Líneas totales: {}".format(len(lineas)), "Ancho máximo: {} caracteres".format(ancho_max), ""]
	activas = gestor.obtener_definiciones_activas()
	if activas:
		partes.append("=== Contenido de las regiones activas ===")
		for d in activas:
			contenido = d.extraer_texto(texto)
			partes += ["", "--- {} ({}) ---".format(d.nombre, NOMBRES_MODOS.get(d.modo, d.modo)), contenido if contenido.strip() else "(región vacía)"]
	else:
		partes += ["No hay regiones activas. Active alguna definición para ver su contenido.", "", "Definiciones disponibles:"]
		for clave in gestor.listar_definiciones():
			d = gestor.obtener_definicion(clave)
			if d:
				partes.append("  • [{}]: {}".format(clave, d.obtener_descripcion()))
	cambios = gestor.detectar_cambios(texto)
	if cambios:
		partes += ["", "=== Cambios detectados ==="]
		for clave, nuevo in cambios.items():
			d = gestor.obtener_definicion(clave)
			partes += ["Cambio en «{}»:".format(d.nombre if d else clave), nuevo]
	partes += [
		"",
		"=== Sugerencias ===",
		"• Para aplicar filtros de silencio, active las definiciones correspondientes.",
		"• Las definiciones predefinidas están desactivadas por defecto.",
		"• Puede ajustar las filas y columnas según el tamaño de su terminal.",
	]
	if lineas:
		partes += ["", "Tamaño recomendado para este contenido: filas 1-{}, columnas 1-{}".format(len(lineas), ancho_max)]
	return "\n".join(partes)


class HerramientaDefinicionesVentana(HerramientaBase):
	METADATOS = MetadatosHerramienta(
		nombre="Definiciones de ventana",
		version="1.0.0",
		descripcion="Gestiona regiones de pantalla con modos de lectura personalizados",
		autor="Héctor J. Benítez Corredera",
		categoria="desarrollo",
	)

	def _gestor(self) -> GestorDefinicionesVentana:
		complemento = getattr(self, "complemento", None)
		gestor = getattr(complemento, "definiciones", None)
		if gestor is None:
			gestor = GestorDefinicionesVentana()
		return gestor

	@property
	def gestor(self) -> GestorDefinicionesVentana:
		return self._gestor()

	def ejecutar(self, **kwargs):
		visor = kwargs.get("visor")
		texto = self.texto_de(kwargs, preferir_seleccion=False)
		if visor is None:
			return informe_definiciones(self._gestor(), texto)
		from ..interfaz.dialogos import DefinicionesDialog

		dlg = DefinicionesDialog(visor, self._gestor(), texto)
		dlg.ShowModal()
		dlg.Destroy()
		return None
