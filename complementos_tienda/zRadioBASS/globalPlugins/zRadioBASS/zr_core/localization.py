# -*- coding: utf-8 -*-
# Copyright (C) 2025-2026 Héctor J. Benítez Corredera <xebolax@gmail.com>
# Este archivo está cubierto por la Licencia Pública General GNU.

"""Nombres en español de países e idiomas (la API los da en inglés)."""

from __future__ import annotations

import unicodedata

#: Código ISO 3166-1 → nombre del país en español.
COUNTRIES_ES: dict[str, str] = {
	"AD": "Andorra", "AE": "Emiratos Árabes Unidos", "AF": "Afganistán", "AG": "Antigua y Barbuda",
	"AI": "Anguila", "AL": "Albania", "AM": "Armenia", "AO": "Angola", "AQ": "Antártida",
	"AR": "Argentina", "AS": "Samoa Americana", "AT": "Austria", "AU": "Australia", "AW": "Aruba",
	"AX": "Islas Åland", "AZ": "Azerbaiyán", "BA": "Bosnia y Herzegovina", "BB": "Barbados",
	"BD": "Bangladés", "BE": "Bélgica", "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Baréin",
	"BI": "Burundi", "BJ": "Benín", "BL": "San Bartolomé", "BM": "Bermudas", "BN": "Brunéi",
	"BO": "Bolivia", "BQ": "Caribe Neerlandés", "BR": "Brasil", "BS": "Bahamas", "BT": "Bután",
	"BW": "Botsuana", "BY": "Bielorrusia", "BZ": "Belice", "CA": "Canadá", "CC": "Islas Cocos",
	"CD": "República Democrática del Congo", "CF": "República Centroafricana", "CG": "Congo",
	"CH": "Suiza", "CI": "Costa de Marfil", "CK": "Islas Cook", "CL": "Chile", "CM": "Camerún",
	"CN": "China", "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "CV": "Cabo Verde",
	"CW": "Curazao", "CX": "Isla de Navidad", "CY": "Chipre", "CZ": "República Checa",
	"DE": "Alemania", "DJ": "Yibuti", "DK": "Dinamarca", "DM": "Dominica",
	"DO": "República Dominicana", "DZ": "Argelia", "EC": "Ecuador", "EE": "Estonia",
	"EG": "Egipto", "EH": "Sáhara Occidental", "ER": "Eritrea", "ES": "España", "ET": "Etiopía",
	"FI": "Finlandia", "FJ": "Fiyi", "FK": "Islas Malvinas", "FM": "Micronesia", "FO": "Islas Feroe",
	"FR": "Francia", "GA": "Gabón", "GB": "Reino Unido", "GD": "Granada", "GE": "Georgia",
	"GF": "Guayana Francesa", "GG": "Guernsey", "GH": "Ghana", "GI": "Gibraltar", "GL": "Groenlandia",
	"GM": "Gambia", "GN": "Guinea", "GP": "Guadalupe", "GQ": "Guinea Ecuatorial", "GR": "Grecia",
	"GT": "Guatemala", "GU": "Guam", "GW": "Guinea-Bisáu", "GY": "Guyana", "HK": "Hong Kong",
	"HN": "Honduras", "HR": "Croacia", "HT": "Haití", "HU": "Hungría", "ID": "Indonesia",
	"IE": "Irlanda", "IL": "Israel", "IM": "Isla de Man", "IN": "India", "IQ": "Irak", "IR": "Irán",
	"IS": "Islandia", "IT": "Italia", "JE": "Jersey", "JM": "Jamaica", "JO": "Jordania", "JP": "Japón",
	"KE": "Kenia", "KG": "Kirguistán", "KH": "Camboya", "KI": "Kiribati", "KM": "Comoras",
	"KN": "San Cristóbal y Nieves", "KP": "Corea del Norte", "KR": "Corea del Sur", "KW": "Kuwait",
	"KY": "Islas Caimán", "KZ": "Kazajistán", "LA": "Laos", "LB": "Líbano", "LC": "Santa Lucía",
	"LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Liberia", "LS": "Lesoto", "LT": "Lituania",
	"LU": "Luxemburgo", "LV": "Letonia", "LY": "Libia", "MA": "Marruecos", "MC": "Mónaco",
	"MD": "Moldavia", "ME": "Montenegro", "MF": "San Martín", "MG": "Madagascar", "MH": "Islas Marshall",
	"MK": "Macedonia del Norte", "ML": "Malí", "MM": "Myanmar", "MN": "Mongolia", "MO": "Macao",
	"MP": "Islas Marianas del Norte", "MQ": "Martinica", "MR": "Mauritania", "MS": "Montserrat",
	"MT": "Malta", "MU": "Mauricio", "MV": "Maldivas", "MW": "Malaui", "MX": "México", "MY": "Malasia",
	"MZ": "Mozambique", "NA": "Namibia", "NC": "Nueva Caledonia", "NE": "Níger", "NF": "Isla Norfolk",
	"NG": "Nigeria", "NI": "Nicaragua", "NL": "Países Bajos", "NO": "Noruega", "NP": "Nepal",
	"NR": "Nauru", "NU": "Niue", "NZ": "Nueva Zelanda", "OM": "Omán", "PA": "Panamá", "PE": "Perú",
	"PF": "Polinesia Francesa", "PG": "Papúa Nueva Guinea", "PH": "Filipinas", "PK": "Pakistán",
	"PL": "Polonia", "PM": "San Pedro y Miquelón", "PR": "Puerto Rico", "PS": "Palestina",
	"PT": "Portugal", "PW": "Palaos", "PY": "Paraguay", "QA": "Catar", "RE": "Reunión",
	"RO": "Rumania", "RS": "Serbia", "RU": "Rusia", "RW": "Ruanda", "SA": "Arabia Saudí",
	"SB": "Islas Salomón", "SC": "Seychelles", "SD": "Sudán", "SE": "Suecia", "SG": "Singapur",
	"SH": "Santa Elena", "SI": "Eslovenia", "SK": "Eslovaquia", "SL": "Sierra Leona",
	"SM": "San Marino", "SN": "Senegal", "SO": "Somalia", "SR": "Surinam", "SS": "Sudán del Sur",
	"ST": "Santo Tomé y Príncipe", "SV": "El Salvador", "SX": "Sint Maarten", "SY": "Siria",
	"SZ": "Esuatini", "TC": "Islas Turcas y Caicos", "TD": "Chad", "TG": "Togo", "TH": "Tailandia",
	"TJ": "Tayikistán", "TL": "Timor Oriental", "TM": "Turkmenistán", "TN": "Túnez", "TO": "Tonga",
	"TR": "Turquía", "TT": "Trinidad y Tobago", "TV": "Tuvalu", "TW": "Taiwán", "TZ": "Tanzania",
	"UA": "Ucrania", "UG": "Uganda", "US": "Estados Unidos", "UY": "Uruguay", "UZ": "Uzbekistán",
	"VA": "Ciudad del Vaticano", "VC": "San Vicente y las Granadinas", "VE": "Venezuela",
	"VG": "Islas Vírgenes Británicas", "VI": "Islas Vírgenes de los Estados Unidos", "VN": "Vietnam",
	"VU": "Vanuatu", "WF": "Wallis y Futuna", "WS": "Samoa", "XK": "Kosovo", "YE": "Yemen",
	"YT": "Mayotte", "ZA": "Sudáfrica", "ZM": "Zambia", "ZW": "Zimbabue",
}

#: Nombre en español → código.
COUNTRIES_ES_REVERSE: dict[str, str] = {v: k for k, v in COUNTRIES_ES.items()}

#: Países que se muestran primero en la pestaña General (como en el original).
COMMON_COUNTRIES = ["ES", "MX", "AR", "CO", "CL", "PE", "VE", "EC", "US", "GB", "FR", "DE", "IT", "BR", "PT"]

#: Código especial de la pestaña General para «Todas las populares».
TOP_CODE = "TOP"

#: Idioma de la API (en inglés, minúsculas) → nombre en español.
LANGUAGES_ES: dict[str, str] = {
	"spanish": "Español", "english": "Inglés", "french": "Francés", "german": "Alemán",
	"italian": "Italiano", "portuguese": "Portugués", "brazilian portuguese": "Portugués de Brasil",
	"russian": "Ruso", "chinese": "Chino", "mandarin": "Mandarín", "cantonese": "Cantonés",
	"japanese": "Japonés", "korean": "Coreano", "arabic": "Árabe", "dutch": "Neerlandés",
	"polish": "Polaco", "turkish": "Turco", "greek": "Griego", "swedish": "Sueco",
	"norwegian": "Noruego", "danish": "Danés", "finnish": "Finlandés", "czech": "Checo",
	"slovak": "Eslovaco", "slovenian": "Esloveno", "croatian": "Croata", "serbian": "Serbio",
	"bosnian": "Bosnio", "macedonian": "Macedonio", "albanian": "Albanés", "hungarian": "Húngaro",
	"romanian": "Rumano", "moldovan": "Moldavo", "ukrainian": "Ucraniano", "belarusian": "Bielorruso",
	"bulgarian": "Búlgaro", "lithuanian": "Lituano", "latvian": "Letón", "estonian": "Estonio",
	"icelandic": "Islandés", "irish": "Irlandés", "gaelic": "Gaélico", "scottish gaelic": "Gaélico escocés",
	"welsh": "Galés", "breton": "Bretón", "basque": "Euskera", "catalan": "Catalán",
	"valencian": "Valenciano", "galician": "Gallego", "asturian": "Asturiano", "occitan": "Occitano",
	"corsican": "Corso", "sardinian": "Sardo", "maltese": "Maltés", "luxembourgish": "Luxemburgués",
	"frisian": "Frisón", "afrikaans": "Afrikáans", "swahili": "Suajili", "amharic": "Amárico",
	"hausa": "Hausa", "yoruba": "Yoruba", "igbo": "Igbo", "zulu": "Zulú", "xhosa": "Xhosa",
	"somali": "Somalí", "hebrew": "Hebreo", "yiddish": "Yidis", "persian": "Persa", "farsi": "Persa",
	"kurdish": "Kurdo", "pashto": "Pastún", "urdu": "Urdu", "hindi": "Hindi", "bengali": "Bengalí",
	"bangla": "Bengalí", "punjabi": "Panyabí", "gujarati": "Guyaratí", "marathi": "Maratí",
	"tamil": "Tamil", "telugu": "Telugu", "kannada": "Canarés", "malayalam": "Malayalam",
	"sinhala": "Cingalés", "nepali": "Nepalí", "thai": "Tailandés", "lao": "Lao", "khmer": "Jemer",
	"burmese": "Birmano", "vietnamese": "Vietnamita", "indonesian": "Indonesio", "malay": "Malayo",
	"filipino": "Filipino", "tagalog": "Tagalo", "javanese": "Javanés", "mongolian": "Mongol",
	"kazakh": "Kazajo", "uzbek": "Uzbeko", "azerbaijani": "Azerí", "armenian": "Armenio",
	"georgian": "Georgiano", "tatar": "Tártaro", "quechua": "Quechua", "guarani": "Guaraní",
	"aymara": "Aimara", "nahuatl": "Náhuatl", "maya": "Maya", "esperanto": "Esperanto",
	"latin": "Latín", "creole": "Criollo", "haitian creole": "Criollo haitiano", "papiamento": "Papiamento",
	"tibetan": "Tibetano", "uyghur": "Uigur", "multilingual": "Multilingüe", "international": "Internacional",
}

#: Nombre en español → idioma de la API.
LANGUAGES_ES_REVERSE: dict[str, str] = {}
for _k, _v in LANGUAGES_ES.items():
	LANGUAGES_ES_REVERSE.setdefault(_v, _k)


def _fold(text: str) -> str:
	return "".join(c for c in unicodedata.normalize("NFD", text.casefold()) if unicodedata.category(c) != "Mn")


def get_country_name(code: str, language: str = "es") -> str:
	"""Nombre del país en español (el código tal cual si no se conoce)."""
	if not code:
		return ""
	if language == "es":
		return COUNTRIES_ES.get(code.upper(), code)
	return code


def get_language_name(lang: str, ui_language: str = "es") -> str:
	"""Nombre del idioma en español (el de la API con mayúscula inicial si no se conoce)."""
	if not lang:
		return ""
	if ui_language == "es":
		known = LANGUAGES_ES.get(lang.lower().strip())
		if known:
			return known
	return lang[:1].upper() + lang[1:]


def get_country_code(name: str, language: str = "es") -> str:
	"""Código ISO de un país a partir de su nombre en español (sin importar tildes ni mayúsculas)."""
	if language != "es" or not name:
		return ""
	if name in COUNTRIES_ES_REVERSE:
		return COUNTRIES_ES_REVERSE[name]
	folded = _fold(name.strip())
	for code, country in COUNTRIES_ES.items():
		if _fold(country) == folded:
			return code
	if len(name.strip()) == 2 and name.strip().upper() in COUNTRIES_ES:
		return name.strip().upper()
	return ""


def get_language_api_name(name: str) -> str:
	"""Idioma de la API a partir del nombre en español («Español» → ``spanish``)."""
	if not name:
		return ""
	folded = _fold(name.strip())
	for api, es in LANGUAGES_ES.items():
		if _fold(es) == folded:
			return api
	return name.strip().lower()


def sorted_countries() -> list[tuple[str, str]]:
	"""``(código, nombre)`` de todos los países ordenados por su nombre en español."""
	return sorted(COUNTRIES_ES.items(), key=lambda kv: _fold(kv[1]))
