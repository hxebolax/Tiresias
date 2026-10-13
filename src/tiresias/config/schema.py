"""Valores por defecto de la configuración de Tiresias.

Cada sección es un diccionario. Las claves desconocidas que aparezcan en el
archivo del usuario se conservan (los complementos pueden añadir sus propias
secciones con :func:`tiresias.config.registerDefaults`).
"""

from __future__ import annotations

import copy

#: Versión del esquema. Se guarda en cada archivo (``schemaVersion``) y permite
#: migrar las configuraciones antiguas (ver :mod:`tiresias.config.migrations`).
SCHEMA_VERSION = 3

DEFAULTS: dict = {
	"general": {
		# "auto": idioma de Windows si hay traducción; si no, español.
		"language": "auto",
		"saveConfigurationOnExit": True,
		"askToExit": True,
		"playStartAndExitSounds": True,
		"logLevel": "INFO",
		"showWelcomeDialogAtStartup": True,
		"startOnLogon": False,
		# Usar la copia instalada en el inicio de sesión y en las pantallas seguras
		# (UAC, Ctrl+Alt+Supr). Lo que vale es el registro de Windows (HKLM): esta
		# clave lo refleja y permite fijarla con la política (tiresias.secure_screens).
		"startOnLogonScreen": False,
		"announceStartup": True,
		# Impide que la pantalla se apague durante la lectura continua.
		"preventDisplayTurningOff": True,
		# Versión con la que se ejecutó Tiresias por última vez (novedades).
		"lastRunVersion": "",
		"showNewsAfterUpdate": True,
		# Primer arranque a medias (tiresias.first_run): "nvda" falta preguntar si se
		# importa la configuración de NVDA; "welcome" falta la bienvenida; "" terminado.
		"firstRunStep": "",
	},
	"speech": {
		# "auto" elige el mejor sintetizador disponible (Eloquence si está el
		# complemento, luego eSpeak NG, OneCore y SAPI 5).
		"synth": "auto",
		"synthPriority": ["ibmtts", "espeak", "onecore", "sapi5"],
		"symbolLevel": 100,
		"trustVoiceLanguage": True,
		"autoLanguageSwitching": True,
		"autoDialectSwitching": False,
		"capitalPitchChange": 30,
		"sayCapitalForCapitals": False,
		"beepForCapitals": False,
		"useSpellingFunctionality": True,
		"delayedCharacterDescriptions": False,
		# #13967: 1000 ms resultaba lento; 500 ms basta para no solaparse con la letra.
		"delayedCharacterDescriptionsDelay": 500,
		"unicodeNormalization": False,
		"reportNormalizedForCharacterNavigation": True,
		"speakEmojiNames": True,
		"condenseRepeatedSymbols": True,
		"repeatedSymbolsThreshold": 4,
		"speechMode": "talk",
		"speechHistorySize": 500,
		# Ajustes por sintetizador: {nombre: {"voice": ..., "rate": ...}}
		"synths": {},
	},
	"audio": {
		"soundVolume": 100,
		"soundVolumeFollowsVoice": False,
		"playSounds": True,
		"soundTheme": "default",
		"soundSplitMode": "off",
		"soundSplitApplyToOtherApps": True,
		"duckingMode": "off",
		"duckingLevel": 30,
		"outputDevice": "",
		"keepAudioAwakeSeconds": 30,
	},
	"keyboard": {
		"layout": "desktop",
		"useInsertAsModifier": True,
		"useNumpadInsertAsModifier": True,
		# Las tres teclas Tiresias vienen activadas (#11678); dos pulsaciones
		# seguidas de Bloq Mayús siguen cambiando el bloqueo de mayúsculas.
		"useCapsLockAsModifier": True,
		"speakTypedCharacters": "always",
		"speakTypedWords": "off",
		"speechInterruptForCharacters": True,
		"speechInterruptForEnter": True,
		"allowSkimReadingInSayAll": False,
		"beepForLowercaseWithCapsLock": True,
		"speakCommandKeys": False,
		"alertForSpellingErrors": True,
		"handleInjectedKeys": True,
		"multiPressTimeout": 500,
		"announceToggleKeys": True,
		# Anunciar los cambios de idioma o distribución del teclado (NVDA #1676).
		"announceInputLanguageChanges": True,
		# Mapa de gestos: "tiresias" (propio) o "jaws" (emula las teclas de JAWS).
		"gestureLayout": "tiresias",
		# Teclas por capas (tecla de capas seguida de una letra).
		"layersEnabled": True,
		"layerTimeout": 5,
	},
	"mouse": {
		"enableMouseTracking": True,
		"mouseTextUnit": "paragraph",
		"reportObjectRoleOnMouseEnter": False,
		"audioCoordinatesOnMouseMove": False,
		"audioCoordinatesMinPitch": 220,
		"audioCoordinatesMaxPitch": 880,
		"ignoreInjectedMouseInput": False,
		"reportMouseShapeChanges": False,
		# Milisegundos que el puntero tiene que estar quieto antes de leer lo
		# que hay debajo (0 = leer en cuanto se mueve, #11898).
		"reportDelay": 0,
	},
	"touch": {
		# Interacción táctil (pantalla táctil). Solo se activa si el equipo
		# tiene pantalla táctil; sin ella este valor no tiene efecto.
		"enabled": True,
		# Escritura táctil: levantar el dedo sobre una tecla del teclado táctil la pulsa.
		"touchTyping": False,
		"textUnit": "line",
		"multiTapTimeout": 300,
		# Gestos en el panel táctil de precisión (Raw Input).
		"touchpadEnabled": False,
		"touchpadSingleFinger": False,
		# Secuencias de dos deslizamientos levantando el dedo entre ellos
		# (sin levantarlo se reconocen siempre).
		"liftedSequentialFlicks": False,
		# Gestos de borde: deslizamientos que empiezan a menos de edgeMargin
		# píxeles (a 96 ppp) de un borde de la pantalla.
		"edgeGestures": False,
		"edgeMargin": 24,
	},
	"reviewCursor": {
		"followFocus": True,
		"followCaret": True,
		"followMouse": False,
		"simpleReviewMode": True,
		# Tonos de coordenadas (alto = arriba, paneo = horizontal) al mover el
		# objeto navegador y al mover el cursor de revisión (#2559).
		"audioCoordinatesOnNavigatorMove": False,
		"audioCoordinatesOnReviewMove": False,
	},
	"presentation": {
		"reportTooltips": True,
		"reportHelpBalloons": True,
		"reportKeyboardShortcuts": True,
		"reportObjectPositionInformation": True,
		"guessObjectPositionInformationWhenUnavailable": False,
		"reportObjectDescriptions": True,
		# Descripción (aria-describedby) de grupos y regiones al entrar (#12718).
		"reportGroupDescriptions": True,
		# Nombre de los objetos en su idioma con el cambio automático (foros 1.19).
		"reportObjectLanguage": True,
		"reportDynamicContentChanges": True,
		"reportAutoSuggestionsWithSound": True,
		"reportNotifications": True,
		"progressBarOutputMode": "beep",
		"reportBackgroundProgressBars": False,
		# Intervalos (en porcentaje) entre anuncios de las barras de progreso.
		"progressBarSpeechInterval": 10,
		"progressBarBeepInterval": 1,
		"progressBarBeepMinHz": 110,
		"announceFocusAncestors": True,
		# Anunciar «selección múltiple» en las listas que la admiten.
		"reportMultiSelect": True,
		# Nivel de verbosidad: beginner, normal o expert (ver speech/verbosity.py).
		"verbosity": "normal",
	},
	"documentFormatting": {
		"detectFormatAfterCursor": False,
		"reportFontName": False,
		"reportFontSize": False,
		"reportFontAttributes": False,
		"reportSuperscriptsAndSubscripts": False,
		"reportEmphasis": False,
		"reportHighlight": True,
		"reportColor": False,
		# Cómo se dicen los colores (#8674): "name", "nameAndRgb" o "nameAndHex".
		"colorFormat": "name",
		"reportStyle": False,
		"reportAlignment": False,
		"reportSpellingErrors": True,
		"reportPage": True,
		"reportLineNumber": False,
		"reportLineIndentation": "off",
		"reportParagraphIndentation": False,
		"reportLinks": True,
		"reportGraphics": True,
		"reportHeadings": True,
		"reportLists": True,
		"reportBlockQuotes": True,
		# Comillas de <q> como «cita» y «fin de cita» (#14654).
		"reportQuotes": True,
		# Abreviatura (abbr) de los encabezados de tabla (#3566).
		"useHeaderAbbreviations": True,
		"reportLandmarks": True,
		"reportArticles": False,
		"reportFrames": True,
		"reportTables": True,
		"reportTableHeaders": True,
		"reportTableCellCoords": True,
		"reportComments": True,
		"reportRevisions": True,
		"reportClickable": True,
		"reportGroupings": True,
		# Interlineado (sencillo, 1,5 líneas, doble...) de los documentos.
		"reportLineSpacing": False,
		# Las líneas en blanco no cambian la sangría anunciada.
		"ignoreBlankLinesForRLI": False,
		# Bordes de las celdas: "off", "styles" (grosor) o "colorsAndStyles".
		"reportCellBorders": "off",
		# Tipo de enlace: «en esta página» para los anclas de la misma página.
		"reportLinkType": True,
		# Figuras y sus rótulos.
		"reportFigures": True,
		# aria-details, aria-flowto y aria-controls («tiene detalles»...).
		"reportDetails": True,
	},
	"browseMode": {
		"maxLineLength": 100,
		"linesPerPage": 25,
		"useScreenLayout": True,
		"enableOnPageLoad": True,
		"autoSayAllOnPageLoad": True,
		"includeLayoutTables": False,
		"autoPassThroughOnFocusChange": True,
		"autoPassThroughOnCaretMove": False,
		"autoFocusFocusableElements": False,
		"passThroughAudioIndication": True,
		"trapNonCommandGestures": True,
		"quickNavWrap": True,
		"reportLiveRegions": True,
		"scrollIntoView": True,
		"rememberPositionPerPage": True,
		"singleLetterNavigation": True,
		# --- Ampliaciones del modo exploración ---
		# Modo exploración también en documentos UIA (Word, Outlook, Acrobat...).
		"uiaDocuments": True,
		# Imágenes sin texto alternativo (#7412).
		"reportUnlabeledGraphics": False,
		# Nombre de archivo de las imágenes sin texto alternativo (#7412, foros 1.18).
		"reportGraphicFileNames": True,
		# La selección del modo exploración se refleja en el documento.
		"nativeSelectionMode": True,
		# Las flechas se saltan las líneas en blanco (#4904).
		"skipBlankLines": False,
		# La tecla I solo recorre los elementos de la lista actual (#8193).
		"listItemWithinList": False,
		# Un clic del ratón mueve el cursor virtual (#4896).
		"clickMovesCaret": True,
		# Al activar un enlace a un ancla de la página, el cursor va al destino.
		"followAnchors": True,
		# Indicación mientras carga el documento (#16960): "off", "beep" o "speech".
		"loadingIndicator": "beep",
		# Resumen hablado al cargar (encabezados, enlaces, regiones, formularios).
		"reportPageSummary": False,
		# Anunciar el modo al entrar en otro documento.
		"announceModeOnDocumentChange": True,
		# Entrada y salida de regiones al mover el foco (#10420).
		"reportLandmarksOnFocusChange": True,
		# Las regiones vivas asertivas interrumpen la voz (#17662).
		"assertiveLiveRegionsInterrupt": True,
		# Entrada y salida de contenedores («lista con 3 elementos», «fuera de
		# lista») en una línea propia del búfer (#3997).
		"containerLinesApart": False,
		# Sin disposición en pantalla, el texto que sigue a un enlace empieza
		# otra línea (#11073); desactivada, sigue en la línea del enlace.
		"breakAfterLinks": True,
	},
	"documentNavigation": {
		# Estilo de párrafo: "application", "singleLineBreak" o "multiLineBreak".
		"paragraphStyle": "application",
		# Qué encuentra la tecla P: "role" (párrafos marcados), "text" (párrafos
		# de texto según la expresión regular) o "both".
		"paragraphQuickNav": "both",
		# Un párrafo «de texto» termina en un signo de puntuación final.
		"textParagraphRegex": r"[^\s].*[.!?:;»\")\]…](\s|$)",
		"textParagraphMinLength": 20,
	},
	"inputComposition": {
		# Composición de entrada (IME de chino, japonés, coreano...).
		"reportCompositionStringChanges": True,
		"reportCompositionFinalized": True,
		"announceSelectedCandidate": True,
		"autoReportAllCandidates": True,
	},
	"braille": {
		"display": "noBraille",
		"translationTable": "auto",
		"expandAtCursor": True,
		"showCursor": True,
		"cursorBlink": True,
		"cursorBlinkRate": 500,
		"cursorShapeFocus": 0xC0,
		"cursorShapeReview": 0xFF,
		"messageTimeout": 4,
		"showMessages": "timeout",
		"tetherTo": "auto",
		"readByParagraph": False,
		"focusContextPresentation": "changedContext",
		"showSelection": True,
		"interruptSpeechWhileScrolling": True,
		"numCellsForViewer": 40,
	},
	"vision": {
		"screenCurtain": False,
		"highlightFocus": False,
		"highlightNavigator": False,
		"highlightBrowseMode": False,
		"highlightColor": "#FF0000",
		"highlightThickness": 4,
	},
	"magnifier": {
		"level": 2.0,
		"followFocus": True,
		"followCaret": True,
		"followReview": True,
		"followMouse": True,
		# Vistas, filtros de color y demás opciones de la lupa: magnifier.py.
		"step": 0.5,
		"panStep": 10,
		"enableAtStartup": False,
	},
	"ocr": {
		"language": "",
		"autoRefresh": False,
		"autoRefreshInterval": 1500,
		"autoSayAll": False,
	},
	"clipboard": {
		"historyEnabled": True,
		"historySize": 50,
		"announceCopy": True,
		"persistHistory": False,
		# Confirmar «Copiado al portapapeles» en las órdenes de Tiresias (#9273).
		"confirmCopyCommands": True,
		# Distinguir cortar, copiar y pegar al usar sus teclas (#19042).
		"announceCutCopyPaste": True,
		# Leer el texto pegado (#10709).
		"announcePastedText": False,
	},
	"sleepMode": {
		# Activo en la configuración (normalmente en un perfil asociado a una
		# aplicación): la aplicación en primer plano queda en modo dormir (#3721).
		# (Las aplicaciones siempre dormidas están en appModules.sleepApps.)
		"enabled": False,
	},
	"uia": {
		"preferUIAForConsoles": True,
		"connectionTimeout": 2000,
		# "selective": solo cambios del foco, barras de progreso y controles con
		# valor; "global": cambios de nombre y descripción de cualquier objeto.
		"eventRegistration": "selective",
		# Anunciar notificaciones de aplicaciones que no están en primer plano
		# (desactivado por defecto, como NVDA: cortaban lo que se estaba leyendo).
		"notificationsFromBackground": False,
		# Respetar la prioridad de las notificaciones (sustituir las antiguas).
		"honorNotificationProcessing": True,
	},
	"advanced": {
		"enableScratchpad": False,
		"debugCategories": [],
		"playErrorSound": False,
		"watchdogTimeout": 6,
		# Recuperación del núcleo bloqueado: "off", "cancel" (cancela las
		# llamadas COM pendientes) o "restart" (cancela y, si no basta, reinicia).
		"watchdogRecovery": "restart",
		"watchdogRestartTimeout": 30,
		"eventCoalesceMs": 20,
	},
	"speechViewer": {
		"showAtStartup": False,
		"rememberPosition": True,
		# [x, y, ancho, alto] (vacío: posición por defecto).
		"position": [],
	},
	"brailleDisplays": {
		# Puerto de cada controlador de línea: "auto", "usb", "bluetooth", "COMx"
		# o la ruta de un dispositivo concreto.
		"ports": {},
		# Controladores que la detección automática no prueba.
		"excludedFromAuto": [],
		# La detección automática busca también líneas Bluetooth.
		"detectBluetooth": True,
		# Detectar chips USB-serie genéricos (pueden ser otros aparatos).
		"detectGenericUsb": False,
		# Avisar por voz al conectar o desconectar la línea.
		"announceConnection": True,
		# BRLTTY: servidor BrlAPI (host:puerto).
		"brlapiServer": "127.0.0.1:4101",
		# Ajustes propios de cada controlador: {controlador: {clave: valor}}
		# (los declara ``HardwareDriver.driverSettings``).
		"settings": {},
	},
	"brailleViewer": {
		"showAtStartup": False,
	},
	"addons": {
		"disabled": [],
		# Complementos que se cargan aunque no se hayan probado con esta versión.
		"overrideCompatibility": [],
		# Catálogo de la tienda de complementos (URL o ruta de archivo).
		"catalogUrl": "",
		"autoCheckUpdates": True,
	},
	"update": {
		# Comprobación de actualizaciones de Tiresias.
		"autoCheck": True,
		"checkUrl": "",
		"intervalHours": 24,
		"lastCheck": 0,
		"skippedVersion": "",
		# Origen de las actualizaciones y de la tienda (1.0.13): "ambos" (servidor
		# del proyecto y GitHub), "servidor", "github" o "propio" (serverUrl).
		"origin": "ambos",
		# Servidor propio (vacío: updates.DISTRIBUTION_URL). Ver updates.currentOrigin.
		"serverUrl": "",
		# Canal de actualizaciones: "estable" o "beta".
		"channel": "estable",
	},
	"labels": {
		"enabled": True,
	},
}


def getDefaults() -> dict:
	return copy.deepcopy(DEFAULTS)
