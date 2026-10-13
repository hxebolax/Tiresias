"""Opciones del complemento «Visor de consola» (sección ``consoleLog`` de la configuración).

Todas las preferencias viven en la configuración de Tiresias (perfiles,
valores de fábrica, guardado al salir...). Lo que no es una preferencia
(definiciones de ventana, claves cifradas de Google AI, caché de modelos,
historiales HTML) se guarda en ``data\\addonsData\\consoleLog``.
"""

from __future__ import annotations

import os

ADDON_ID = "consoleLog"
SECCION = "consoleLog"
#: Categoría de las órdenes en «Gestos de entrada».
CATEGORIA = "Visor de consola"

PROMPT_SISTEMA_DEFECTO = "Eres un asistente útil y experto en depuración de código y análisis de logs de consola."
MODELO_GOOGLE_DEFECTO = "gemini-3.6-flash"
#: Modelos retirados que se migran al modelo predeterminado.
PREFIJOS_MODELOS_RETIRADOS = ("gemini-1.5", "gemini-2.0")

#: Herramientas del menú «Plugins» del visor (identificador del módulo).
HERRAMIENTAS_DEFECTO = [
	"clic_derecho",
	"copiar_salida",
	"historial_comandos",
	"extractor_datos",
	"filtro_log",
	"json_beauty",
	"timestamp_converter",
	"base64_decoder",
	"calculadora_express",
	"resumen_actividad",
	"google_ai",
	"stacktrace_analyzer",
	"monitor_recursos",
	"ai_report_generator",
	"jwt_decoder",
	"sql_formatter",
	"atributos_ansi",
	"analizador_indentacion",
	"definiciones_ventana",
	"estadisticas_log",
	"lineas_unicas",
	"tabla_delimitada",
	"analisis_unicode",
]

DEFAULTS: dict = {
	# --- visual y seguimiento
	"recordarTamano": True,
	"ancho": 800,
	"alto": 600,
	"posX": -1,
	"posY": -1,
	"maximizado": True,
	"fuenteMonoespaciada": True,
	"tamanoFuente": 10,
	"sonidosSeguimiento": True,
	"sonidosAlActualizar": False,
	"proteccionRafagas": False,
	"intervaloSeguimiento": 750,
	"conservarHistorial": True,
	"limiteMilesCaracteres": 5000,
	"categorizarHerramientas": True,
	# --- procesamiento de texto
	"habilitarProcesamiento": True,
	"limpiarAnsi": True,
	"condensarSimbolos": False,
	"simbolosACondensar": "-_=!",
	"detectarIndentacion": False,
	"nivelPuntuacion": 2,
	"procesarBidi": False,
	"procesarEmoji": False,
	"detectarTerminal": True,
	"usarPerfilTerminal": True,
	# --- lanzador
	"lanzadorRecordarUltima": False,
	"lanzadorUltimaOpcion": "",
	"lanzadorMostrarNoDisponibles": False,
	# --- herramientas
	"herramientasHabilitadas": list(HERRAMIENTAS_DEFECTO),
	# --- alertas
	"alertasHabilitadas": True,
	"alertasPatrones": ["ERROR", "CRITICAL", "FATAL"],
	"alertasVoz": True,
	"alertasSonido": True,
	# --- inteligencia artificial
	"iaProveedor": "google",
	"iaModeloGoogle": MODELO_GOOGLE_DEFECTO,
	"iaMantenerHistorial": True,
	"iaPromptSistema": PROMPT_SISTEMA_DEFECTO,
}

#: Intervalo de seguimiento permitido (milisegundos).
INTERVALO_MIN = 250
INTERVALO_MAX = 10000

#: Proveedores del chat y de los informes de IA: (valor, etiqueta).
PROVEEDORES_IA = [
	("google", "Google AI con las claves del complemento (varias claves y lista de modelos)"),
	("tiresias", "El proveedor configurado en Opciones, Inteligencia artificial de Tiresias"),
	("anthropic", "Anthropic Claude (clave y modelo de las opciones de IA de Tiresias)"),
	("openai", "OpenAI (clave y modelo de las opciones de IA de Tiresias)"),
	("gemini", "Google Gemini (clave y modelo de las opciones de IA de Tiresias)"),
	("local", "Servidor local, Ollama o LM Studio (opciones de IA de Tiresias)"),
]

#: Niveles de puntuación de los anuncios del complemento: (valor, etiqueta).
NIVELES_PUNTUACION = [
	(0, "Ninguno"),
	(1, "Alguno"),
	(2, "Mayoría"),
	(3, "Todo"),
]


def registrarValores() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECCION, DEFAULTS)
	migrarModelo()


def opciones():
	"""Sección de la configuración (diccionario vivo)."""
	from tiresias.config import conf

	return conf[SECCION]


def valor(clave: str):
	try:
		return opciones()[clave]
	except Exception:
		return DEFAULTS.get(clave)


def establecer(clave: str, nuevo) -> None:
	try:
		opciones()[clave] = nuevo
	except Exception:
		pass


def migrarModelo() -> None:
	"""Los modelos de Gemini retirados se cambian por el predeterminado."""
	modelo = str(valor("iaModeloGoogle") or "")
	if not modelo or modelo.startswith(PREFIJOS_MODELOS_RETIRADOS):
		establecer("iaModeloGoogle", MODELO_GOOGLE_DEFECTO)


def maxCaracteres() -> int:
	"""Límite del documento del visor en caracteres (0 = sin límite)."""
	try:
		return max(0, int(valor("limiteMilesCaracteres"))) * 1000
	except (TypeError, ValueError):
		return 5_000_000


def intervalo() -> int:
	try:
		ms = int(valor("intervaloSeguimiento"))
	except (TypeError, ValueError):
		ms = 750
	return max(INTERVALO_MIN, min(INTERVALO_MAX, ms))


def herramientasHabilitadas() -> list[str]:
	lista = valor("herramientasHabilitadas")
	return [str(x) for x in lista] if isinstance(lista, (list, tuple)) else list(HERRAMIENTAS_DEFECTO)


def patronesAlerta() -> list[str]:
	lista = valor("alertasPatrones")
	if not isinstance(lista, (list, tuple)):
		return []
	return [str(p).strip() for p in lista if str(p).strip()]


def carpetaDatos() -> str:
	"""``data\\addonsData\\consoleLog`` (se crea si no existe)."""
	from tiresias import paths

	return paths.addonDataDir(ADDON_ID)


def rutaDatos(nombre: str) -> str:
	return os.path.join(carpetaDatos(), nombre)
