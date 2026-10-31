"""Opciones del Arreglo web (sección ``arregloWeb`` de la configuración)."""

from __future__ import annotations

SECTION = "arregloWeb"
#: Identificador de la categoría en el cuadro de Opciones.
PANEL_ID = "arregloWeb"
PANEL_TITLE = "Arreglo web"

DEFAULTS = {
	# Aplicar al cargar cada página los arreglos guardados para su sitio.
	"aplicarGuardados": True,
	# Anunciar por voz el resumen de problemas antes de abrir la lista.
	"informeVoz": True,
	# Buscar textos que parecen encabezados (tamaño de letra y negrita): consulta el formato de la página.
	"encabezadosDeducidos": True,
	# Presentar como botón los elementos genéricos pulsables.
	"pulsablesComoBotones": True,
	# Ofrecer describir con los proveedores de IA de Tiresias las imágenes sin texto alternativo.
	"describirImagenesIA": True,
	# Máximo de imágenes que se describen con IA en cada tanda.
	"maxImagenesIA": 8,
}


def registerDefaults() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECTION, DEFAULTS)


def get(key: str):
	"""Valor de una opción (el de fábrica si el guardado no es válido)."""
	from tiresias.config import conf

	try:
		value = conf[SECTION][key]
	except KeyError:
		return DEFAULTS[key]
	default = DEFAULTS[key]
	if isinstance(default, bool):
		return bool(value)
	if isinstance(default, int):
		try:
			return max(1, min(50, int(value)))
		except (TypeError, ValueError):
			return default
	return value


def set(key: str, value) -> None:  # noqa: A001
	from tiresias.config import conf

	conf[SECTION][key] = value


def panelClass():
	"""Categoría «Arreglo web» del cuadro de Opciones (se crea al usarla: necesita wx)."""
	from tiresias.gui import settings as S

	class ArregloWebPanel(S.ConfigPanel):
		title = PANEL_TITLE
		section = SECTION
		fields = [
			S.Bool("aplicarGuardados", "&Aplicar al cargar cada página los arreglos guardados de su sitio"),
			S.Bool("informeVoz", "Anunciar por &voz el resumen de problemas antes de abrir la lista"),
			S.Bool("encabezadosDeducidos", "Buscar textos que parecen &encabezados por su tamaño o negrita"),
			S.Bool("pulsablesComoBotones", "Proponer presentar como &botón los elementos pulsables"),
			S.Bool("describirImagenesIA", "Ofrecer describir con &IA las imágenes sin texto alternativo"),
			S.Int("maxImagenesIA", "&Máximo de imágenes que se describen con IA en cada tanda:", 1, 50),
		]

	return ArregloWebPanel


def registerPanel() -> None:
	from tiresias.gui import settings as S

	S.registerPanel(PANEL_ID, PANEL_TITLE, panelClass())


def unregisterPanel() -> None:
	from tiresias.gui import settings as S

	S.unregisterPanel(PANEL_ID)
