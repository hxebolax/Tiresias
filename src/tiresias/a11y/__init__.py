"""APIs de accesibilidad: UI Automation, MSAA/IAccessible2, Java Access Bridge
y eventos del sistema.

Al importar el paquete se registran los valores por defecto de las opciones
de esta área (secciones ``objects``, ``terminal``, ``java`` y ``system``).
"""

from __future__ import annotations

from ..config import registerDefaults

registerDefaults(
	"objects",
	{
		# Usar IAccessible2 en ventanas sin proveedor UIA propio (LibreOffice, Qt…).
		"useIA2": True,
		# Clases de ventana que el usuario quiere leer con MSAA o con UIA.
		"msaaClasses": [],
		"uiaClasses": [],
		# Anunciar los elementos que se añaden o quitan de la selección en listas
		# de selección múltiple sin mover el foco.
		"reportSelectionChanges": True,
		# Anunciar el elemento elegido en las listas de sugerencias.
		"reportSuggestionItems": True,
		# Leer el texto de los diálogos al abrirse.
		"reportDialogText": True,
		# Anunciar la longitud máxima de los campos de edición al recibir el foco.
		"reportMaxLength": True,
		# Aviso de caracteres restantes al escribir (foros 1.17, #7910):
		# "off", "threshold" (al cruzar el umbral y al llegar al límite) o
		# "countdown" (cada carácter dentro del umbral).
		"maxLengthWarning": "threshold",
		# Caracteres restantes a partir de los cuales se avisa.
		"maxLengthWarningThreshold": 10,
		# Anunciar los cambios de orden (aria-sort) de los encabezados de columna.
		"reportSortChanges": True,
		# Anunciar las operaciones de arrastrar y soltar.
		"reportDragDrop": True,
		# Tiempo (ms) a partir del cual un proveedor se considera lento.
		"slowProviderThresholdMs": 800,
	},
)
registerDefaults(
	"terminal",
	{
		# "characters": diferencias por caracteres; "lines": líneas completas.
		"diffAlgorithm": "characters",
		# Leer lo escrito aunque la consola no lo muestre (contraseñas).
		"speakPasswords": False,
		# Máximo de líneas que se leen de una vez cuando aparece mucho texto.
		"maxLinesPerUpdate": 60,
	},
)
registerDefaults(
	"java",
	{
		# Usar Java Access Bridge con las aplicaciones Java.
		"enabled": True,
		# Preguntar si se activa Java Access Bridge cuando aparece una ventana Java sin él.
		"askToEnable": True,
	},
)
registerDefaults(
	"system",
	{
		# Indicar a Windows y a las aplicaciones que hay un lector de pantalla.
		"setScreenReaderFlag": True,
		# Registrar Tiresias como tecnología de asistencia de Windows.
		"registerAsAT": False,
	},
)
