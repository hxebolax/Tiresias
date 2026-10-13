"""Ajustes, constantes y estado compartido del complemento Audiocinemateca.

Las opciones se guardan en la configuración de Tiresias (sección
``audiocinemateca``); los datos que genera el complemento (catálogo,
favoritos, historial, listas, estadísticas, marcas de visualización,
registro de descargas y credenciales cifradas) van en
``data\\addonsData\\audiocinemateca``.
"""

from __future__ import annotations

import copy
import os

ADDON_ID = "audiocinemateca"
SECCION = "audiocinemateca"
NOMBRE = "Audiocinemateca"
CATEGORIA_ORDENES = "Audiocinemateca"
VERSION_COMPLEMENTO = "1.0.0"
#: Versión del complemento original de NVDA del que procede este.
VERSION_ORIGINAL = "2.0 (2026.03.11)"

# ---------------------------------------------------------------- direcciones
URL_CATALOGO = "https://audiocinemateca.com/system/files/catalogo/catalogo.json.bz2"
URL_VERSION = "https://audiocinemateca.com/system/files/catalogo/version.json.gz"
URL_BASE = "https://audiocinemateca.com/"
URL_DONACIONES = "https://audiocinemateca.com/donaciones"
URL_WEB = "https://www.audiocinemateca.com/"

# ---------------------------------------------------------------- listas de opciones
LISTA_VELOCIDAD = [
	"0.75", "0.80", "0.85", "0.90", "0.95",
	"1.0",
	"1.05", "1.10", "1.15", "1.20", "1.25",
	"1.30", "1.35", "1.40", "1.45", "1.50",
	"1.75", "2.0",
]
LISTA_ATRASAR = ["1 segundo", "5 segundos", "15 segundos", "30 segundos", "1 minuto"]
LISTA_ADELANTAR = [
	"1 segundo", "5 segundos", "15 segundos", "30 segundos",
	"1 minuto", "5 minutos", "10 minutos", "15 minutos",
]
#: Índice de la lista de atrasar/adelantar -> segundos.
DICT_TIEMPO = {0: 1, 1: 5, 2: 15, 3: 30, 4: 60, 5: 300, 6: 600, 7: 900}
LISTA_RESULTADOS = ["10 resultados", "15 resultados", "20 resultados", "25 resultados"]
DICT_RESULTADOS = {0: 10, 1: 15, 2: 20, 3: 25}

#: Filtros de búsqueda (nombre visible) y el campo del catálogo que usan.
LISTA_FILTROS = [
	"Título", "Año", "Género", "País", "Director", "Guion", "Música",
	"Fotografía", "Reparto", "Productora", "Narración", "Sinopsis",
]
CAMPOS_FILTRO = [
	"titulo", "anio", "genero", "pais", "director", "guion", "musica",
	"fotografia", "reparto", "productora", "narracion", "sinopsis",
]

#: Categorías del catálogo: (clave, nombre en plural, nombre en singular).
CATEGORIAS = [
	("peliculas", "Películas", "Película"),
	("series", "Series", "Serie"),
	("documentales", "Documentales", "Documental"),
	("cortometrajes", "Cortometrajes", "Cortometraje"),
]
CLAVES_CATEGORIA = [c[0] for c in CATEGORIAS]


def nombreCategoria(clave: str, singular: bool = True) -> str:
	for c, plural, sing in CATEGORIAS:
		if c == clave:
			return sing if singular else plural
	return ""


# ---------------------------------------------------------------- ecualizador
#: Frecuencias centrales (Hz). El ecualizador DX8 de BASS admite de 80 a 16000 Hz.
EQ_BANDAS = [80, 230, 910, 3600, 14000]
EQ_NOMBRES = ["80 Hz", "230 Hz", "910 Hz", "3.6 kHz", "14 kHz"]
EQ_ANCHO_BANDA = 12.0
EQ_MIN = -15
EQ_MAX = 15
#: Preajustes (nombre, ganancias en dB), en el orden en que se muestran.
EQ_PRESETS = [
	("Normal", [0, 0, 0, 0, 0]),
	("Voz clara", [0, 0, 4, 6, 2]),
	("Cine", [3, 1, 0, 2, 4]),
	("Música", [4, 2, 0, 2, 4]),
	("Graves", [6, 4, 0, -2, -4]),
	("Agudos", [-4, -2, 0, 4, 6]),
]

# ---------------------------------------------------------------- temporizador de sueño
TEMPORIZADOR_OPCIONES = [
	("Desactivar", 0), ("15 minutos", 15), ("30 minutos", 30), ("45 minutos", 45),
	("1 hora", 60), ("1 hora y media", 90), ("2 horas", 120), ("Personalizado", -1),
]

# ---------------------------------------------------------------- opciones guardadas
DEFECTO = {
	"hablar": True,
	"resultados": 0,
	"atrasar": 2,
	"adelantar": 3,
	"volumen": 50,
	"velocidad": 5,
	"ecualizadorActivo": False,
	"ecualizadorValores": [0, 0, 0, 0, 0],
	"dispositivo": "",
	"carpetaDescargas": "",
}


def registrarDefectos() -> None:
	from tiresias.config import conf

	conf.registerDefaults(SECCION, copy.deepcopy(DEFECTO))


def get(clave: str):
	"""Valor de una opción (el de fábrica si no se puede leer la configuración)."""
	try:
		from tiresias.config import conf

		valor = conf[SECCION][clave]
	except Exception:
		valor = copy.deepcopy(DEFECTO[clave])
	return _validar(clave, valor)


def put(clave: str, valor) -> None:
	from tiresias.config import conf

	conf[SECCION][clave] = valor


def _validar(clave: str, valor):
	"""Corrige valores fuera de rango (configuraciones dañadas o antiguas)."""
	limites = {
		"resultados": len(LISTA_RESULTADOS) - 1,
		"atrasar": len(LISTA_ATRASAR) - 1,
		"adelantar": len(LISTA_ADELANTAR) - 1,
		"velocidad": len(LISTA_VELOCIDAD) - 1,
		"volumen": 100,
	}
	if clave in limites:
		try:
			valor = int(valor)
		except (TypeError, ValueError):
			return DEFECTO[clave]
		return max(0, min(limites[clave], valor))
	if clave == "ecualizadorValores":
		if not isinstance(valor, list) or len(valor) != len(EQ_BANDAS):
			return list(DEFECTO[clave])
		try:
			return [max(EQ_MIN, min(EQ_MAX, int(v))) for v in valor]
		except (TypeError, ValueError):
			return list(DEFECTO[clave])
	if clave in ("hablar", "ecualizadorActivo"):
		return bool(valor)
	return valor


def restaurarDefecto() -> None:
	"""Pone todas las opciones del complemento con sus valores de fábrica."""
	for clave, valor in DEFECTO.items():
		put(clave, copy.deepcopy(valor))


def hablarActivo() -> bool:
	return bool(get("hablar"))


def velocidadActual() -> float:
	return float(LISTA_VELOCIDAD[get("velocidad")])


def segundosAtrasar() -> int:
	return DICT_TIEMPO.get(get("atrasar"), 15)


def segundosAdelantar() -> int:
	return DICT_TIEMPO.get(get("adelantar"), 30)


def cantidadResultados() -> int:
	return DICT_RESULTADOS.get(get("resultados"), 10)


# ---------------------------------------------------------------- carpetas
def dirDatos() -> str:
	"""Carpeta de datos del complemento (``data\\addonsData\\audiocinemateca``)."""
	from tiresias import paths

	return paths.addonDataDir(ADDON_ID)


def rutaDatos(nombre: str) -> str:
	return os.path.join(dirDatos(), nombre)


def raizComplemento() -> str:
	"""Carpeta del complemento instalado (la que contiene ``manifest.json``)."""
	return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def rutaDocumentacion() -> str:
	return os.path.join(raizComplemento(), "doc", "es", "readme.html")


# ---------------------------------------------------------------- estado de la sesión
class Estado:
	"""Estado compartido entre la ventana, las órdenes globales y el reproductor."""

	ventanaAbierta = False
	opcionesAbiertas = False
	usuario = ""
	contrasena = ""
	temporizadorActivo = False
	temporizadorMinutos = 0


estado = Estado()


def hayCredenciales() -> bool:
	return bool(estado.usuario and estado.contrasena)
