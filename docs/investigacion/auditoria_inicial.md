# Auditoría de completitud de Tiresias frente a NVDA

**Fecha:** 6 de octubre de 2026.
**Tipo:** auditoría de solo lectura. No se ha modificado ningún archivo del proyecto.

**Referencias:**
- **NVDA:** `adjuntos\nvda\source` (rama 2027.1 dev).
- **Tiresias:** `src\tiresias` (90 módulos, unas 27.400 líneas) y `data\addons` (eloquence, whatsapp).

**Rutas:** salvo que se indique otra cosa, son relativas a `src\tiresias\`.

**Estados:**
- **HECHO:** equivalente funcional.
- **PARCIAL:** existe, pero falta algo concreto, que se indica.
- **FALTA:** no existe.

**Fuera de alcance:** no se audita el acceso remoto, la pantalla táctil ni las matemáticas (se implementan aparte).

**Método:** comparación orden por orden, opción por opción y módulo por módulo, con grep y lectura del código. Cada fila lleva su evidencia `archivo:línea`. Se verificaron a mano los hallazgos más delicados (AltGr, `--replace`, el paquete `braille/drivers`, ProgressBar, `enableOnPageLoad`, el reinicio en modo seguro, la cortina y la lista de frameworks del modo exploración).

---

## 0. Resumen ejecutivo

La base es sólida:
- gestor de voz con índices en hilo propio;
- eSpeak, OneCore, SAPI 5 y Eloquence;
- teclado con tecla Tiresias, distribución de portátil, ayuda de entrada y mapa de gestos editable con detección de conflictos;
- perfiles con disparadores por aplicación y de lectura continua;
- modo exploración UIA con búfer propio, navegación rápida, lista de elementos, marcadores y búsqueda;
- diccionarios con expresiones regulares, símbolos y emojis;
- historial de voz y de portapapeles, y paleta de órdenes;
- cortina, lupa a pantalla completa, resaltado y OCR de Windows;
- división del sonido y atenuación;
- braille HID básico.

Las carencias grandes son estas:

1. **Arquitectura solo UIA.** No hay IAccessible/IA2, Java Access Bridge, display model (GDI) ni modelo de objetos de Office. Firefox y Thunderbird dependen del UIA de Gecko. LibreOffice, Acrobat, las apps Java y las apps antiguas quedan mudas o pobres. No hay módulos de Excel, Word, Outlook ni PowerPoint.
2. **Escritorio seguro.** No hay pantallas seguras (UAC ni inicio de sesión), ni instalador, ni UIAccess, ni protección en LockApp. Esto último es un problema de seguridad: la navegación de objetos puede salir de la pantalla de bloqueo.
3. **Braille muy por detrás de NVDA:**
   - sin liblouis (solo 2 tablas propias), sin braille contraído, sin tabla de entrada y sin detección automática;
   - un único controlador (HID estándar), frente a los más de 20 de NVDA;
   - el braille no se actualiza al escribir;
   - los mensajes de `ui.message` no llegan a la línea;
   - el tether tiene errores.
4. **Unas 90 órdenes globales de NVDA no existen.** Entre ellas: todos los conmutadores `toggleReport*` de formato, 17 órdenes braille, los conmutadores de la lupa y del OCR, `toggleSpeechViewer`/`toggleBrailleViewer`, los diálogos de opciones restantes, las órdenes de la rueda del ratón y la revisión de selección y símbolo.
5. **Navegación de documentos incompleta:**
   - modo exploración solo para FrameworkId Chrome, Gecko y MicrosoftEdge (no en Word ni PDF);
   - en tablas faltan primera/última fila o columna, leer fila o columna, celdas combinadas y encabezados reales;
   - no hay navegación por frases, estilos de párrafo ni lectura continua por frases;
   - no hay aria-details ni anotaciones;
   - no hay selección nativa;
   - el búfer se carga de forma síncrona.
6. **Infraestructura sin hacer:**
   - comprobación de actualizaciones;
   - tienda de complementos en línea;
   - catálogos de traducción de la interfaz (el idioma de la interfaz es de solo lectura);
   - validación y versión del esquema de configuración;
   - IME y composición de entrada;
   - prioridades reales de la cola de voz y voz cancelable.

Además hay **errores y código a medias** concretos (sección 11). Los principales:
- `_hasAltGr()` siempre devuelve True;
- el paquete `braille/drivers` no existe;
- el braille pierde la línea configurada si no está conectada al arrancar;
- la caché de ProgressBar es por instancia;
- `enableOnPageLoad` casi no hace nada;
- `speech.outputDevice` es una opción muerta;
- `--replace` no tiene efecto;
- «Reiniciar» tras un arranque seguro vuelve a arrancar sin complementos;
- `setStartOnLogon` escribe en el registro cada 15 s.

---

## 1. Órdenes globales (`globalCommands.py`, 267 scripts) frente a `global_commands.py` y `browse\document.py`

### 1.1 Órdenes de NVDA que Tiresias tiene (HECHO, a veces con otro nombre)

- **Entrada y teclado:** toggleInputHelp, passNextKeyThrough, toggleSpeakTypedCharacters/Words, toggleSpeakCommandKeys, toggleReportDynamicContentChanges, toggleCaretMovesReviewCursor, toggleFocusMovesNavigatorObject y toggleCurrentAppSleepMode.
- **Lectura:**
  - reportCurrentLine, reportCurrentSelection, sayAll, reportFormatting (solo en el cursor), reportCurrentFocus, title, speakForeground;
  - reportStatusLine: una sola orden con pulsaciones repetidas, que sustituye a readStatusLine, spellStatusLine y copyStatusLine;
  - reportFocusObjectAccelerator, reportLinkDestination (con dos pulsaciones lo muestra en ventana), dateTime, say_battery_status (como sayBatteryStatus), reportClipboardText y reportAppModuleInfo;
  - navigatorObject_devInfo (como navigatorObjectDevInfo).
- **Voz:** speechMode, cycleSpeechSymbolLevel, repeatLastSpokenInformation, copyLastSpokenInformation y el anillo de ajustes (increase, decrease, large, next, previous).
- **Navegación de objetos y revisión:**
  - las de navegación de objetos y revisión: navigatorObject_current, parent, next, previous, firstChild, nextInFlow, previousInFlow, toFocus y moveFocus; review_activate; navigatorObject_currentDimensions y caretPos_currentDimensions;
  - todas las review_* de carácter, palabra, línea, página, inicio y fin, y review_sayAll;
  - reviewMode_next/previous y review_markStartForCopy/review_copy.
- **Ratón:** left/rightMouseClick, toggleLeft/RightMouseButton, moveMouseToNavigatorObject, moveNavigatorObjectToMouse y toggleMouseTracking.
- **Configuración:**
  - toggleProgressBarOutput, showGui y quit;
  - abrir paneles: activateGeneral, Synthesizer, Voice, BrailleSettings, AudioSettings, KeyboardSettings, MouseSettings, ObjectPresentation, BrowseMode, DocumentFormatting y ConfigProfilesDialog;
  - saveConfiguration y revertConfiguration;
  - activatePythonConsole y reloadPlugins.
- **Visión, audio y braille:**
  - recognizeWithUwpOcr (como recognizeWithOcr) y toggleScreenCurtain;
  - toggleMagnifier, zoomIn/zoomOut y pan* con sus bordes (como magnifier*);
  - cycleSoundSplit y cycleAudioDuckingMode;
  - braille_toggleTether, braille_scrollBack/Forward, braille_routeTo, braille_previous/nextLine y braille_enter;
  - moveToParentTreeInterceptor y toggleVirtualBufferPassThrough (como toggleFocusMode en el búfer).
- **Extras de Tiresias:** speechHistory, commandPalette, windowList, clipboardHistory, labelNavigatorObject, recognizeScreenWithOcr, toggleFocusHighlight y magnifierInvertColors.

### 1.2 Órdenes de NVDA que FALTAN o están a medias en Tiresias

| Grupo | Orden NVDA | Estado | Nota y archivos de Tiresias |
|---|---|---|---|
| Formato de documento | toggleReportFontName, FontSize, FontAttributes, SuperscriptsAndSubscripts, Revisions, Emphasis, HighlightedText, Color, Alignment, Style, SpellingErrors, Page, LineNumber, LineIndentation, ignoreBlankLinesForReportLineIndentation, ParagraphIndentation, LineSpacing, Tables, TableHeaders, TableCellCoords, CellBorders, Links, LinkType, Graphics, Comments, Lists, Headings, Groupings, BlockQuotes, Landmarks, Articles, Frames, Clickable, Figures | FALTA | Hay que añadir conmutadores en global_commands.py con `_toggleSetting`/`_cycle` sobre `conf["documentFormatting"]`. Las opciones LineSpacing, CellBorders, LinkType, Figures e ignoreBlankLines tampoco existen en schema.py. |
| Voz | cycleSpeechAutomaticLanguageSwitching, toggleDelayedCharacterDescriptions, speech_cycleUnicodeNormalization, toggleReportCLDR, firstValueSynthRing, lastValueSynthRing, toggleSpeakingOnNavigatingByUnit, reportCaretLanguage | FALTA | global_commands.py, synth/__init__.py (anillo), presentation.py |
| Revisión | review_currentSymbol, review_startOfSelection, review_endOfSelection, review_moveToStartMarkedForCopy, reviewCursorToStatusLine | FALTA | global_commands.py, review.py |
| Ubicación | reportReviewCursorLocation, reportCurrentNavigatorObjectLocation, reportCaretLocation, reportFocusObjectLocation | PARCIAL | Solo existen navigatorObject_currentDimensions y caretPos_currentDimensions (global_commands.py:560-584). |
| Formato | reportFormattingAtReview, showFormattingAtReview, showFormattingAtCaret, reportOrShowFormattingAtCaret, reportDetailsSummary | PARCIAL / FALTA | reportFormatting solo funciona en el cursor del sistema (global_commands.py:169). En modo exploración, `BufferTextInfo.getFormatInfo` devuelve {} (textinfo/__init__.py:106). NVDA+d (detalles) no existe. |
| Ratón | mouseScrollUp/Down/Left/Right, toggleMouseAudioCoordinates, toggleMouseTextResolution | FALTA | `mouse.scroll` existe (mouse.py:53) pero nadie lo usa. |
| Herramientas | log_markStartThenCopy, openUserConfigurationDirectory, restart, toggleSpeechViewer, toggleBrailleViewer, activateAddonsManager, reportLinkDestinationInWindow | FALTA como orden | Solo están en el menú (gui/__init__.py:226-238). `log.markStart` existe (log.py:40) pero no tiene orden. |
| Diálogos | activateBrailleDisplayDialog, ReviewCursorDialog, VisionSettings, MagnifierSettings, WindowsOCRSettings, AdvancedSettings, Default/Voice/TemporaryDictionaryDialog, SpeechSymbolsDialog, InputGesturesDialog, PrivacyAndSecurity, InputComposition, AddonStoreSettings | FALTA | Los paneles existen (salvo composición de entrada y tienda): faltan los scripts. |
| Perfiles | reportActiveConfigurationProfile, toggleConfigProfileTriggers | FALTA | `conf.triggersEnabled` existe (config/__init__.py:155). |
| Teclado | toggleKeyboardLayout | FALTA | — |
| Revisión simple | toggleSimpleReviewMode | FALTA | La opción existe (schema reviewCursor.simpleReviewMode). |
| Lupa | cycleFilters, toggleFollowMouse, toggleFollowSystemFocus, toggleFollowReview, toggleFollowNavigatorObject, toggleAllFollow, cycleTrackingModes, showEntireScreenOverview, moveMouseToView | FALTA | magnifier.py |
| OCR y cortina | cycleOcrLanguage, toggleAutomaticRefreshOfRecogResult, reportScreenCurtainState | FALTA | ocr.py, vision.py |
| Navegación | cycleParagraphStyle | FALTA | No hay estilos de párrafo. |
| Braille | toggleBrailleMode, braille_cycleReviewRoutingMovesSystemCaret, toggleFocusContextPresentation, toggleShowCursor, toggleSpeakOnRouting, cycleCursorShape, cycleShowMessages, cycleShowSelection, cycleUnicodeNormalization, toggleBrailleAutoScroll, increase/decreaseBrailleAutoScrollRate, toggleReportSpellingErrorsInBraille, braille_reportFormatting, braille_selectRange, braille_toFocus, braille_dots, braille_eraseLastCell, braille_translate, los 10 braille_toggle* de modificadores | FALTA | Ver la sección 5. |
| Desarrollo | test_navigatorDisplayModelText, startWxInspectionTool | FALTA | No aplica sin display model; poca prioridad. |
| Matemáticas, remoto y táctil | interactWithMath, *Remote*, touch_*, sendKeys, sendSAS | Fuera de alcance | — |

---

## 2. Voz, símbolos, diccionarios y sintetizadores

| Funcionalidad NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Modos de voz | HECHO | speech/api.py:44-56, 278-306 | No existe `excludedSpeechModes`. El tono de los pitidos está fijo en 800 Hz (`beepSpeechModePitch`, api.py:304). |
| Órdenes de voz | PARCIAL | speech/commands.py:26-110 | Falta ConfigProfileTriggerCommand. EndUtterance se convierte en Break(1) (api.py:161). WaveFile solo admite nombres de sonido. Rate, Volume y Phoneme nunca se emiten. |
| Prioridades NOW/NEXT/NORMAL | PARCIAL | api.py:59-62, 308 | NOW solo cancela todo y NEXT no se usa. No hay colas por prioridad ni reanudación de lo interrumpido. |
| Voz cancelable (cancelExpiredFocusSpeech) | FALTA | — | — |
| Deletreo (tono, pitido y «mayúscula») | HECHO | api.py:370-412 | Es global, no por sintetizador. |
| Descripción retardada de caracteres | PARCIAL | api.py:430-434 | El `callLater` no se cancela al moverse, así que las descripciones se acumulan. |
| Cambio automático de idioma y dialecto | PARCIAL | presentation.py:414-456; browse/document.py:384-426 | Solo en líneas y en modo exploración: no en palabra, carácter, lectura continua fuera del modo exploración ni mensajes. Faltan reportLanguage y reportNotSupportedLanguage. SAPI 5 ignora LangChange. |
| trustVoiceLanguage | PARCIAL | api.py:257-275 | Pone los símbolos a 0 en lugar de cargar la tabla del idioma de la voz. |
| Leer todo por frases y sin pausas (speechWithoutPauses) | FALTA | speech/sayall.py:50 | Solo por líneas, con un `speak()` por línea. |
| Lectura rápida (skim) en leer todo | PARCIAL | input/core.py:320, 419-420 | Solo con 4 órdenes del modo exploración, y al reanudar siempre usa CURSOR_CARET. |
| Leer todo en tablas | FALTA | — | — |
| Extensiones (filter_speechSequence, post_speechPaused, pre_speechQueued) | PARCIAL | api.py:66-70 | Solo hay pre_speech, pre_speechCanceled y filter_speechText. |
| speech/shortcutKeys (teclas de acceso habladas) | FALTA | presentation.py:260 | Se leen en bruto. |
| trimLeadingSilence | FALTA | — | — |
| Símbolos por idioma | PARCIAL | speech/symbols.py:146-156 (solo es.json) | No hay tablas por idioma ni símbolos complejos por regex. |
| CLDR (emojis) | PARCIAL | data/symbols/emoji_es.json; symbols.py:169-175 | Solo español y sin orden de activación. |
| Descripciones de caracteres | PARCIAL | symbols.py:55-100 | Tabla fija en español. |
| Diccionarios por defecto, de voz y temporal (regex, mayúsculas, palabra) | HECHO | speech/dictionaries.py; gui/config_dialogs.py:1110-1289 | Falta «Quitar todo». No se recarga el diccionario de voz si la voz cambia desde el anillo (synth/__init__.py:136-140). |
| speechDictionaries integrados (diccionarios extra elegibles) | FALTA | — | — |
| Retroceso a otro sintetizador si falla en uso | PARCIAL | synth/__init__.py:94-112 | Solo al cargar; base.py:315 solo registra el error. |
| eSpeak | HECHO | synth/espeak.py | PhonemeCommand sin IPA (espeak.py:305). El aumento de velocidad es ×3, no Sonic. |
| OneCore | PARCIAL | synth/onecore.py | Sin VolumeCommand; PitchCommand incoherente con el de eSpeak (onecore.py:101). |
| SAPI 5 | PARCIAL | synth/sapi5.py:146-173 | Ignora LangChange y Volume; sin aumento de velocidad. |
| SAPI 4 / MSSP | FALTA | synth/__init__.py:22 | — |
| TTS neuronal local (Piper, sherpa-onnx) | FALTA | — | Fila 2 del estudio. |

## 3. Audio

| Funcionalidad | Estado | Evidencia | Qué falta |
|---|---|---|---|
| nvwave / WASAPI | PARCIAL | audio/wave_player.py | Usa waveOut. Los nombres de dispositivo se cortan a 32 caracteres (wave_player.py:33). |
| keepAudioAwake / ruido blanco | PARCIAL | wave_player.py:364-384 | Falta `whiteNoiseVolume`: solo mantiene abierto el dispositivo. |
| Atenuación (ducking) | PARCIAL | audio/ducking.py | Se emula bajando el volumen de cada sesión. Las sesiones nuevas no se atenúan y los sonidos o pitidos no la disparan. |
| División del sonido | PARCIAL | audio/sound_split.py | Faltan `includedSoundSplitModes`. Solo actúa sobre el dispositivo por defecto. |
| Mezclador: volumen por aplicación, silenciar micrófono, atajo para cambiar de dispositivo | FALTA | audio/core_audio.py:54-59 (ISimpleAudioVolume ya envuelto) | Fila 10 del estudio. |

## 4. Teclado, entrada y ratón

| Funcionalidad | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Teclas modificadoras, doble pulsación, inyectadas, teclas de bloqueo, teclado numérico, portátil, ayuda de entrada, mapa de gestos y diálogo de gestos con conflictos | HECHO | input/core.py, input/gestures.py, gui/config_dialogs.py:819-1106, gui/gesture_tools.py:140-160 | El diálogo de gestos no incluye gestos braille ni teclas emuladas. |
| AltGr | PARCIAL (esbozo) | input/core.py:194-197 (`_hasAltGr` siempre True) | Detectar de verdad la distribución con AltGr (VkKeyScanEx o GetKeyboardLayout) y permitir gestos con AltGr. |
| Teclado numérico híbrido en portátil (fila 13) | FALTA | — | — |
| Tecla modificadora configurable arbitraria (fila 13) | FALTA | input/core.py:133-139 | Solo Insert, Insert del teclado numérico y Bloq Mayús. |
| IME y composición de entrada | FALTA | input/core.py:242 (ToUnicodeEx sin tener en cuenta el IME) | Panel, eventos TSF/IMM y candidatos. |
| Teclas de sistema emuladas | FALTA | — | — |
| Etiquetas de teclas | HECHO | input/keys.py:148-260 | Solo en español. |
| Coordenadas de audio del ratón | PARCIAL | mouse.py:57-66 | Faltan detección de brillo, desenfoque y volumen mínimo y máximo. |
| Rueda del ratón | FALTA | mouse.py:53 sin uso | — |

## 5. Braille

**Resumen.** No hay liblouis. Solo existen las tablas `es-comp8` y `es-g1` y tablas JSON del usuario (braille/tables.py:195-312). No hay braille contraído, tabla de entrada, detección automática (bdDetect) ni hwIo. Solo hay tres controladores: noBraille, viewer y hidBraille.

| Funcionalidad NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Regiones (mainBuffer, messageBuffer, NVDAObjectRegion, TextInfoRegion) | PARCIAL | braille/__init__.py:127-602 | Una sola región plana. |
| Propiedades del objeto | PARCIAL | braille/__init__.py:359-394 | Faltan descripción, atajo, nivel, coordenadas de tabla, la mayoría de estados, current y placeholder. |
| TextInfoRegion | PARCIAL | braille/__init__.py:446-482 | No muestra campos ni formato. **No se actualiza al escribir** (event_caret se descarta en braille/__init__.py:489; base.py:522-526 está vacío). |
| Modo exploración en braille | PARCIAL | browse/document.py:495-499 | Texto bruto sin marcas de rol. |
| Contexto del foco | PARCIAL | braille/__init__.py:396-440 | No se muestra en controles con texto (sale en la línea 422). |
| Tether | PARCIAL / ERROR | presentation.py:491; braille/__init__.py:411, 484-491 | Los movimientos de revisión se tratan como foco. Con tether «revisión» no se muestra el objeto navegador. |
| Modo «mostrar voz» y toggleBrailleMode | FALTA | — | — |
| Desplazamiento automático | FALTA | — | — |
| wordWrap / textWrap | PARCIAL | braille/__init__.py:282-287, 529-549 | No se aplica al desplazar. Faltan los modos y la marca de continuación. |
| showSelection | PARCIAL | braille/__init__.py:304-309 | No se actualiza al seleccionar con Mayúsculas+flechas. |
| showMessages y messageTimeout | PARCIAL | braille/__init__.py:500-520 | `speech.speakMessage` no envía al braille: el único que llama es input/core.py:565. |
| readByParagraph | PARCIAL | braille/__init__.py:455, 556, 572 | El movimiento y el enrutamiento usan línea. Falta paragraphStartMarker. |
| Enrutamiento | PARCIAL | braille/__init__.py:563-591 | En modo exploración siempre activa. reviewRoutingMovesSystemCaret, speakOnRouting y selectRange no existen. |
| Normalización Unicode en braille | FALTA | tables.py:210-224 | Las letras descompuestas salen como celda llena. |
| Formato en braille y errores ortográficos | FALTA | — | — |
| Regiones vivas en braille | FALTA | — | — |
| Tablas (liblouis, más de 100 tablas, automática) y braille contraído | FALTA | braille/tables.py | — |
| Entrada braille | PARCIAL / ERRORES | input/core.py:383-386, 491-520 | Sin búfer ni traducción. Espacio+puntos sin orden asignada escribe una letra. En es-comp8 el punto 7 siempre se trata como mayúscula (no se pueden escribir @ [ \ ] ^ ¿ ¡ €). En es-g1 no hay signo de número ni de mayúscula. |
| Entrada contraída, translate, eraseLastCell y dots como órdenes, conmutadores de modificadores, braille_toFocus | FALTA / PARCIAL | input/core.py:504-509 (punto 7 = Retroceso y punto 8 = Intro fijos en código) | — |
| Visor braille | PARCIAL | gui/braille_viewer.py | Texto desalineado respecto a las celdas (braille/__init__.py:317, 325). Faltan enrutar al pasar el ratón y recordar la posición. No hay orden para abrirlo. |
| bdDetect, desconexión y reconexión, selección de puerto | FALTA | hid_braille.py:378-391, 434, 460-467 | Usa solo `paths[0]`. El bucle de lectura sale sin avisar. |
| Controladores: Alva, Baum, BrailleNote, BrailliantB, EcoBraille, Eurobraille, Freedom Scientific, HandyTech, Hedo, HIMS, Lilli, Nattiq, NLS eReader, Papenmeier, Seika, SuperBraille, Albatross, DotPad, BRLTTY | FALTA | — | Solo funcionan las líneas que usan HID braille estándar. |
| Líneas de varias filas | FALTA | hid_braille.py:303 | — |
| Puntos de extensión braille | PARCIAL | braille/__init__.py:26 | Solo existe post_displayUpdate. |
| Scripts de controladores de complementos | PARCIAL / ERROR | input/core.py:99-119 | El controlador no entra en la cadena de órdenes, así que su gestureMap no se consulta. |

## 6. Modo exploración, documentos y tablas

| Funcionalidad NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Ámbito del modo exploración | PARCIAL | browse/__init__.py:6 | Solo FrameworkId Chrome, Gecko y MicrosoftEdge. Ni Word, ni PDF, ni otros documentos UIA. |
| Navegación rápida básica (h, 1-6, k, v, u, f, e, l, i, t, b, m, s, r, c, x, g, q, n, d, o, p) | HECHO | browse/document.py:65-95 | — |
| Encabezados de nivel 7-9 | PARCIAL | document.py:66-71 | Faltan las teclas 7, 8 y 9. |
| Anotación (a), error ortográfico (w), deslizador, pulsable, agrupación, figura, botón de alternar, barra de progreso, matemáticas, párrafo vertical, mismo estilo / distinto estilo, referencia | FALTA | document.py:91, 93 (a = artículo, w = pestaña: chocan con NVDA) | — |
| Párrafo de texto (p) | PARCIAL | document.py:90 | Busca por rol, sin `textParagraphRegex`. |
| Leer todo con navegación rápida (resumeSayAll) | PARCIAL | document.py:581-611 | — |
| Saltar al final del contenedor (,) | PARCIAL | document.py:872-875 | Se queda dentro del contenedor. |
| Frases (Alt+flechas) | FALTA | textinfo/__init__.py:163-173 (helper sin usar); objects/uia_text.py:23 (frase = párrafo) | — |
| Estilos de párrafo y cycleParagraphStyle | FALTA | document.py:605-632 (heurística propia) | — |
| Alt+flechas cedidas al control (combos) | FALTA | — | — |
| Seleccionar por página o párrafo | FALTA | — | — |
| Modo de selección nativa | FALTA | — | — |
| Buscar | PARCIAL | document.py:979-1019 | Sin historial. La interfaz no permite distinguir mayúsculas y no selecciona lo encontrado. |
| Modo foco fijado a mano, Escape cedido, más roles de paso automático, anuncio del modo al entrar en un documento | FALTA / PARCIAL | document.py:807-827, 1172-1177 | — |
| Activar con clic de ratón de respaldo | PARCIAL | document.py:772-774 | — |
| Tab desde el cursor virtual (_tabOverride) | FALTA | — | — |
| Mover el cursor a un ancla (scrollTo) | FALTA | — | — |
| Carga en segundo plano e isReady | FALTA | document.py:197-227; tree_interceptor.py:39-41 | — |
| Actualización incremental del búfer | PARCIAL | document.py:229-248 | Se reconstruye entero. `_dirty` solo se consume en la raíz (línea 1152). |
| enableOnPageLoad | PARCIAL / ERROR | document.py:1191 | No hace que el documento empiece en modo foco. |
| Alternar distribución en pantalla (NVDA+v) e incluir tablas de diseño | FALTA (orden) | gui/settings.py:1082 | — |
| Tipo de enlace (reportLinkType), aria-sort, subtipos de aria-haspopup, aria-current con valor | FALTA / PARCIAL | buffer.py:443-450 | — |
| Regiones vivas con cortés o asertiva | PARCIAL | objects/base.py:448-458 | P_LIVESETTING no se usa (uia_client.py:101). |
| Detalles, aria-details, anotaciones y descripción larga | FALTA | — | — |
| Tablas: fila y columna siguiente o anterior | PARCIAL | document.py:913-976 | Sin celdas combinadas y sin actualizar el braille. |
| Tablas: primera y última fila o columna, leer fila o columna, leer todo en tabla | FALTA | — | — |
| Encabezados de tabla | PARCIAL | document.py:944-951 | Heurística por fila 1 o columna 1 en lugar de HeaderItems. Es un booleano. |
| Coordenadas de celda al moverse con flechas | PARCIAL | document.py:384-431 | — |
| Lista de elementos | HECHO | gui/browse_dialogs.py | Faltan puntos de referencia anidados. |
| Documentos compuestos | FALTA | — | Solo IA2. |

## 7. Objetos, eventos y manejadores de API

| Funcionalidad NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| IAccessible, IA2, MSAA y WinEvents | FALTA | a11y/winevents.py:19-28 (solo para volver a comprobar el foco) | Firefox, Thunderbird, Chromium IA2, LibreOffice, Acrobat, Qt, Delphi y wx. |
| Elegir UIA o MSAA por ventana (isGood/BadUIAWindow) | FALTA | — | — |
| Java Access Bridge | FALTA | — | — |
| Display model (GDI) | FALTA | — | — |
| Consola clásica | PARCIAL | console_reader.py:65-96; behaviors.py:254-306 | Faltan EVENT_CONSOLE_*, TextInfo del búfer, diff por caracteres, supresión de contraseñas y cola de caracteres. Posible lectura doble en Windows Terminal (notificación + diff). |
| easeOfAccess y pantallas seguras (logonui, lockapp) | FALTA | winevents.py:61-72 (solo avisa) | Hueco de seguridad en LockApp. |
| IME (inputComposition, candidatos) | FALTA | — | — |
| Eventos UIA | PARCIAL | uia_handler.py | itemStatus, menuStart/End, windowOpened y selection se registran y se ignoran. Faltan layoutInvalidated, drag-drop, activeTextPosition, show/hide, selección MSAA y caret MSAA. nameChange solo para el foco. Las notificaciones no filtran por primer plano ni por NotificationProcessing. |
| EditableText | PARCIAL | behaviors.py:101-198 | Falta Intro (caret_newLine), frases, Mayúsculas+Retroceso/Supr y detección automática de selección. Hay espera activa en el hilo del núcleo (behaviors.py:42-56). |
| Campo sin TextPattern | PARCIAL | behaviors.py:236-251 | Solo flechas arriba y abajo. |
| Sugerencias (SearchField, SuggestionsList) | PARCIAL | base.py:461-477 | — |
| ProgressBar | PARCIAL / ERROR | behaviors.py:309-341 | La caché es por instancia y el intervalo está fijo. |
| Dialog | PARCIAL | behaviors.py:344-364 | — |
| Toast (Win11) y WebDialog | FALTA / PARCIAL | appmodules/shellexperiencehost.py | — |
| RowWithFakeNavigation, RowWithoutCellObjects y columnas de SysListView | FALTA | — | Tablas y listas en modo foco. |
| Clases UIA específicas: Excel, Word completo, VisualStudio, sysListView y correcciones de winConsoleUIA | FALTA / PARCIAL | uia.py:711-761 | — |
| Edit y RichEdit por mensajes, Scintilla (Notepad++), modelo de objetos de Excel y Word | FALTA | — | — |
| Alias de ejecutables (notepad++, calculatorapp, searchapp, shellhost, textinputhost…) | FALTA | appmodules/handler.py:25-26 | — |
| getAppNameFromHost (javaw, wwahost) | PARCIAL | objects/base.py:175-211 | Solo WebView2 y CEF. |
| event_NVDAObject_init, filtros de eventos por app y barra de estado por app | FALTA | — | — |

**Módulos de aplicación.** Tiresias solo tiene `explorer` (mínimo), `searchhost`, `shellexperiencehost`, `startmenuexperiencehost` y el complemento WhatsApp, que supera al de NVDA.

Faltan:
- **Office:** excel, winword, outlook y powerpnt.
- **Desarrollo y terminales:** code (con riesgo de que el editor entre en modo exploración), devenv, eclipse, putty/mintty/securecrt/ttermpro, notepad (Win11) y notepadPlusPlus.
- **Comunicaciones:** teams, thunderbird, hxmail, skype, zoom, lync y mirc.
- **Sistema:** textinputhost (emojis, historial Win+V, candidatos IME), lockapp, logonui, calculator (sin anuncio duplicado), taskmgr, mmc, systemsettings, csrss, dllhost, openwith y voiceaccess.
- **Multimedia y lectura:** foobar2000, winamp, spotify, itunes, kindle, poedit y totalcmd.
- **Otros:** soffice, javaw, wwahost y unos 20 módulos menores.

`explorer` está a medias: le faltan el botón de inicio, la bandeja, la vista de tareas (Alt+Tab), los flyouts y las columnas de detalles.

## 8. Opciones de configuración y diálogo de opciones

| Sección o opción NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| general.language | PARCIAL | gui/settings.py:622 (solo lectura); i18n.py | No hay catálogos `locale`, selector ni diálogo de reinicio. |
| logLevel | PARCIAL | settings.py:445 | Faltan los niveles OFF, IO, DEBUGWARNING y UNREDACTED. |
| preventDisplayTurningOff | FALTA | — | — |
| Pantallas seguras, copiar la configuración al sistema, estadísticas de uso | FALTA | — | — |
| speech: beepSpeechModePitch, excludedSpeechModes, reportLanguage, reportNotSupportedLanguage, trimLeadingSilence, sayAllReadingUnit, speechDictionaries, symbolDictionaries | FALTA / PARCIAL | — | capPitch, sayCap, beepCap y spelling son globales, no por sintetizador. |
| audio: whiteNoiseVolume, includedSoundSplitModes | FALTA | — | — |
| braille: mode, inputTable, autoScrollRate, reviewRoutingMovesSystemCaret, paragraphStartMarker, textWrap, unicodeNormalization, speakOnRouting, speakOnNavigatingByUnit, reportLiveRegions, fontFormattingDisplay, excludedDisplays, port | FALTA | — | — |
| screenCurtain: warnOnLoad, playToggleSounds | FALTA | vision.py:92 | — |
| magnifier: magnifiedView, filtro de grises, followNavigatorObject, fullscreenMode | FALTA | — | followReviewCursor está unido a followCaret. enableAtStartup no tiene efecto inmediato. |
| presentation: reportMultiSelect, intervalos de porcentaje y beepMinHZ | FALTA / PARCIAL | presentation.py:55; behaviors.py:338-340 | — |
| mouse: detectBrightness, blurFactor, min/maxVolume | FALTA | — | — |
| virtualBuffers: textParagraphRegex, findHistory, nativeSelectionMode | FALTA | — | enableOnPageLoad está a medias. |
| documentFormatting | PARCIAL | formatting.py | Faltan reportTransparentColor, reportLineSpacing, ignoreBlankLinesForRLI, indentToneDuration, reportCellBorders, reportLinkType, reportBookmarks y reportFigures. fontAttributeReporting, reportSpellingErrors y reportTableHeaders son booleanos. Las opciones estructurales solo actúan en modo exploración. |
| documentNavigation (paragraphStyle, segmentación de palabras) | FALTA | — | Panel completo. |
| UIA: enabled, useInMSExcel, allowInMSWord/Chromium, eventRegistration | FALTA | — | winConsoleImplementation es un booleano. |
| annotations, terminals, inputComposition | FALTA | — | Secciones completas. |
| editableText.caretMoveTimeoutMs | PARCIAL | behaviors.py:33 | Fijo en código. |
| featureFlag.cancelExpiredFocusSpeech | FALTA | — | playErrorSound solo cubre excepciones en órdenes. |
| debugLog | PARCIAL | settings.py:1249 | Texto libre sin validar, en lugar de casillas. |
| Posición de los visores de voz y braille, enrutar al pasar el ratón | FALTA | — | — |
| addonStore (automaticUpdates, canales, servidor) | FALTA | — | — |
| Esquema de configuración: versión, profileUpgrader, validación de tipos y rangos | FALTA | config/__init__.py:264-278 | — |
| Configuración del sistema y modo --secure | FALTA | — | — |
| applyConfiguration al cambiar de perfil | PARCIAL | core.py:440-471 | No reaplica la cortina, la lupa ni el resaltado. |
| Perfiles por dominio web, diccionarios por perfil, perfiles de solo lectura | FALTA | Los diccionarios son globales: speech/dictionaries.py:121-127 | — |
| Paneles «Composición de entrada», «Navegación por documentos» y «Tienda» | FALTA | — | Avanzado y Privacidad están a medias. Falta la ayuda contextual F1. |

## 9. Menú, diálogos, complementos, instalación y actualización

| Funcionalidad NVDA | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Entradas del menú de Tiresias | HECHO | gui/__init__.py:205-252 | Todas tienen la función de respuesta implementada. |
| Crear copia portable desde la interfaz, instalar, herramienta de reparación COM | FALTA | — | Solo existe `Tiresias.bat` (desarrollo). |
| Ayuda: Novedades, Licencia, Bienvenida (en el menú), Buscar actualización | FALTA | gui/__init__.py:242-244 | `gui.showWelcome` existe (gui/__init__.py:530) pero no está en el menú. |
| Referencia rápida de órdenes | PARCIAL | gui/__init__.py:626-653 | Solo órdenes globales. |
| Acerca de | PARCIAL | config_dialogs.py:1532-1560 | Falta «Copiar número de versión». |
| Restablecer valores de fábrica en el menú | PARCIAL | settings.py:1257 | Solo como botón y con Tiresias+Ctrl+R pulsado tres veces. |
| Diálogo de salida: reiniciar con depuración, o sin complementos y con depuración | FALTA | gui/__init__.py:319-377 | — |
| Reiniciar | ERROR | core.py:381-386, 431-432 | Tras arrancar en modo seguro, reinicia otra vez en modo seguro. |
| Tienda en línea: catálogo, actualizaciones y canales | FALTA | — | Solo gestor local (config_dialogs.py:521-712). |
| Compatibilidad de complementos | PARCIAL | addons.py:93-99 | lastTestedApiVersion no se usa. No hay «activar de todos modos». Una instalación encima de otra reemplaza sin preguntar (addons.py:326-336). |
| Comprobación de actualizaciones | FALTA | — | No hay código de red. |
| Línea de órdenes | PARCIAL | core.py:40-55 | Faltan --check-running, --log-file, --lang, --minimal, --secure, --no-logging, --no-sr-flag, --install*, --create-portable, --launcher y --ease-of-access. `--replace` tiene default=True y no tiene efecto. |
| Marca de lector de pantalla (SPI_SETSCREENREADER) | FALTA | — | Las aplicaciones no saben que hay un lector activo. |
| NVDAState, winVersion, garbageHandler, nvda_slave | FALTA | — | — |
| Watchdog | PARCIAL | core.py:345-370 | Detecta bloqueos, pero no recupera el núcleo ni cancela llamadas COM. |

## 10. Visión, lupa y OCR

| Funcionalidad | Estado | Evidencia | Qué falta |
|---|---|---|---|
| Resaltado | PARCIAL | vision.py:99-141 | Un solo rectángulo (con el navegador activo no se resalta el foco), sin refresco periódico. Solo se entera de los cambios de navegador en `_setNavigator` (global_commands.py:425). |
| Cortina | PARCIAL | vision.py:50-96 | Faltan warnOnLoad, playToggleSounds y reportScreenCurtainState. Al alternarla con la orden no se actualiza `conf`. |
| Lupa | PARCIAL | magnifier.py | Faltan las vistas acoplada, lente y fija, el filtro de grises, los modos de seguimiento (centro, borde, relativo), el seguimiento del navegador y la vista general. |
| OCR | PARCIAL | ocr.py; gui/ocr_viewer.py | El resultado es un TextCtrl, no un documento navegable con revisión. La lectura automática no usa leer todo. No hay marco contentRecog ni otros motores. Faltan las órdenes cycleOcrLanguage y toggleAutomaticRefresh. |

---

## 11. Código a medio hacer, opciones muertas y errores dentro de Tiresias

**Marcadores TODO/FIXME/XXX:** no hay ninguno en `src\tiresias` ni en `data\addons`.

**NotImplementedError:** todos están en clases base abstractas, que es lo correcto:
- textinfo/__init__.py:62-96, 209;
- synth/base.py:180, 183, 261;
- braille/__init__.py:45;
- braille/tables.py:192;
- gui/settings.py:216;
- tree_interceptor.py:65.

**Métodos vacíos** (`pass` o solo docstring): ver la sección 7 (eventos vacíos en objects/base.py:445-546).

### 11.1 Esbozos y errores funcionales

1. `input/core.py:194-197`: `_hasAltGr()` siempre devuelve True. En distribuciones sin AltGr, Alt derecho + tecla nunca ejecuta órdenes.
2. `braille/__init__.py:111`: importa `braille.drivers.<nombre>`, pero el paquete `braille/drivers` no existe.
3. `braille/__init__.py:612`: si la línea no está conectada al arrancar, `setDisplay("noBraille")` persiste y sobrescribe `conf["braille"]["display"]`.
4. `presentation.py:491`: `handleCaretMove` también se llama en movimientos de revisión, lo que rompe el tether, la forma del cursor y el enrutamiento.
5. El braille no sigue al escribir: event_caret se descarta (braille/__init__.py:489), base.py:522-526 está vacío y los borrados solo hablan.
6. `braille.showMessages` y `messageTimeout` casi no tienen efecto: el único que llama a `handler.message` es input/core.py:565.
7. Entrada braille (input/core.py:383-386, 511-516):
   - espacio+puntos sin orden asignada escribe un carácter;
   - el punto 7 siempre se trata como mayúscula;
   - en es-g1 no se pueden escribir dígitos ni mayúsculas.
8. `hid_braille.py`:
   - solo usa `paths[0]`;
   - el bucle de lectura sale sin aviso;
   - solo usa la primera tecla de enrutamiento;
   - `leftSpace`/`rightSpace` no casan con los gestos `space+...`;
   - `check()` abre todos los dispositivos HID cada vez.
9. `input/core.py:99-119`: los controladores braille (ScriptableObject) no están en la cadena de órdenes, así que sus gestos se ignoran.
10. `objects/behaviors.py:309-341`: la caché `_lastPercent` de ProgressBar es por instancia y se crea un objeto nuevo por evento (uia_handler.py:159). Resultado: no se deduplica y hay pitido o voz en cada actualización de las barras en segundo plano.
11. `objects/behaviors.py:42-56, 84-94, 192`: espera activa con `time.sleep` en el hilo del núcleo, de hasta 250 ms por tecla.
12. `objects/behaviors.py:260-261`: Terminal lee todas las líneas visibles en `initOverlayClass` cada vez que se crea el objeto.
13. `a11y/uia_handler.py:226-239`: las notificaciones no filtran por primer plano ni por NotificationProcessing. Posible lectura doble en Windows Terminal.
14. `a11y/uia_handler.py:126-128`: StructureChanged ignora el `sender` y avisa a todos.
15. `appmodules/searchhost.py` y `startmenuexperiencehost.py`: son código idéntico. `event_selection` no llama a `nextHandler`.
16. `speech/api.py:430-434`: las descripciones retardadas de caracteres no se cancelan.
17. Al cambiar la voz desde el anillo no se recarga el diccionario de voz (synth/__init__.py:136-140).
18. `browse/document.py:619`: ternario redundante (`self.caret if direction > 0 else self.caret`). Es lógica sin terminar para el párrafo anterior.
19. `browse/document.py:1005`: `find()` admite `caseSensitive`, pero la interfaz nunca lo pasa. `_lastFind` se guarda en cada documento por separado.
20. `browse/document.py:1108`: la lista de elementos incluye las tablas de diseño; la tecla t no.
21. `browse/document.py:209-212`: un COMError al reconstruir el búfer se ignora sin reintento.
22. `textinfo/__init__.py`:
    - `UNIT_PARAGRAPH` es igual a la línea (245-251);
    - `UNIT_PAGE` es el documento entero (252-254);
    - `_getOffsetFromPoint` devuelve 0 (224-225);
    - en objects/uia_text.py:23, la frase es igual al párrafo.
23. `core.py:46`: `--replace` con `default=True` no tiene efecto. El mutex se crea pero no se comprueba (core.py:94).
24. `core.py:381-386`: `restart(safeMode=False)` no borra `args.safe_mode`.
25. `core.py:279-286`: `_periodicCleanup` reescribe la clave Run del registro cada 15 s cuando `startOnLogon` está activo.
26. `addons.py:94`: `lastTestedApiVersion` se lee pero no se usa. `addons.py:326-336` reinstala sin confirmar.
27. `vision.py:96`: alternar la cortina con la orden no actualiza `conf`. `applyConfiguration` no reaplica la cortina, la lupa ni el resaltado al cambiar de perfil.
28. `console_reader.py:60-62`: el lector de consola no funciona si Tiresias tiene consola propia (modo depuración).
29. `data/addons/whatsapp/appModules/whatsapp_root.py`:
    - atributos sin usar: `_lastMessageCount` (:255), `_recording` (:263) y `_readCount` (:264);
    - sondeo cada 1,2 s (:794-806) que sigue en segundo plano.

### 11.2 Opciones de configuración muertas o que no hacen lo que dicen

Se comprobaron todas las claves de schema.py. Todas se leen en algún sitio salvo la primera de la lista.

| Opción | Problema |
|---|---|
| `speech.outputDevice` | **Muerta.** Se escribe en settings.py:926 y 1620, pero nunca se lee. Duplica `audio.outputDevice`. |
| `browseMode.enableOnPageLoad` | Su única lectura es document.py:1191 (lectura continua automática). No impide que el documento empiece en modo exploración. |
| `presentation.verbosity` | Solo quita la posición al recibir el foco (presentation.py:278-280). Equivale a `reportObjectPositionInformation`. |
| `keyboard.passNonCommandKeysInBrowseMode` | Duplica `browseMode.trapNonCommandGestures` invertida (input/core.py:334). |
| `uia.reportNotifications` y `presentation.reportNotifications` | Controlan lo mismo desde dos paneles. |
| `general.language` | Visible pero de solo lectura, y sin catálogos. |
| `speech.trustVoiceLanguage` | Pone el nivel de símbolos a 0 en lugar de cambiar de tabla. |
| `magnifier.followCaret` | Mezcla cursor del sistema y revisión. |
| `magnifier.enableAtStartup` | Solo actúa al arrancar. |
| `vision.highlightFocus` | Se anula cuando `highlightNavigator` está activo (vision.py:127). |
| `audio.duckingMode="speaking"` | Los sonidos y pitidos no lo disparan. |
| `braille.readByParagraph`, `wordWrap`, `showMessages`, `messageTimeout`, `showSelection` | A medias (sección 5). |
| `browseMode.reportLiveRegions` | Solo filtra con Chrome, Gecko o MicrosoftEdge (objects/base.py:453). |
| `uia.connectionTimeout` y `braille.numCellsForViewer` | Solo se leen al arrancar, sin avisar de que hace falta reiniciar. |
| `advanced.playErrorSound` | Solo cubre excepciones en órdenes. |
| `advanced.debugCategories` | Texto libre sin validar. |

### 11.3 Código muerto

- vision.py:41-48 (`_magnification`);
- speech/api.py:445-446 (`speakLanguage`);
- mouse.py:53 (`scroll`);
- log.py:40-50 (`markStart`, sin orden);
- speech/commands.py:71-82 (Rate, Volume y Phoneme nunca se emiten);
- `Priority.NEXT`;
- speech/sayall.py:30 y 140 (`generation`, `finished`);
- presentation.py:218-219 (rama `pass`);
- global_commands.py:613-614 (`if ... direction == 0: pass`);
- gui/ocr_viewer.py:44-48;
- `ListContainer` vacío (behaviors.py:367);
- constantes UIA sin uso en a11y/uia_client.py: P_LIVESETTING, P_DESCRIBEDBY, P_FLOWSTO, PAT_TEXTEDIT, E_INVOKED, E_ELEMENTADDED/REMOVEDFROMSELECTION, E_SELECTIONINVALIDATED, E_WINDOWCLOSED, E_MENUMODESTART/END y E_ACTIVETEXTPOSITIONCHANGED;
- TREE_PROPERTIES pide propiedades que `buffer._makeNode` no usa (SIZEOFSET, POSITIONINSET, LEVEL, HELPTEXT, ISOFFSCREEN…) y no pide GRIDITEMROWSPAN ni COLUMNSPAN.

### 11.4 Manual

Se cotejaron las combinaciones Tiresias+… del manual (`manual\manual_usuario.html`) con los gestos del código. No se encontraron órdenes documentadas que no existan.

---

## 12. Tabla de la sección 5 de `docs\estudio_necesidades_usuarios.md` (37 funciones)

| # | Función | Estado | Evidencia y qué falta |
|---|---|---|---|
| 1 | Núcleo de voz con hilo aislado, prioridades y cancelación | PARCIAL | Hay un hilo de síntesis (synth/base.py:244) y Priority (speech/api.py:59-62). NOW solo cancela (api.py:308) y NEXT no se usa. No hay colas por prioridad ni voz cancelable. |
| 2 | OneCore, SAPI 5, eSpeak y TTS neuronal | PARCIAL | Existen synth/onecore.py, sapi5.py, espeak.py y data/addons/eloquence. No hay Piper ni sherpa-onnx (grep vacío). |
| 3 | Historial de voz completo | PARCIAL | gui/history_dialogs.py:37-160 permite buscar, copiar, exportar y borrar. speech/api.py:73 guarda solo (hora, texto): no hay origen, ni filtro, ni «solo notificaciones». |
| 4 | Capa de IA multiproveedor | FALTA | No hay ningún código de IA ni de red. |
| 5 | OCR multimotor de pantalla, archivo, PDF y portapapeles, continuo | PARCIAL | ocr.py:202-296 (OCR de Windows sobre el navegador o la pantalla, con refresco). Faltan Tesseract, Paddle, archivo, PDF y portapapeles. |
| 6 | API de extensiones estable con semver | PARCIAL | addons.py:23-24, 93-99 (minApiVersion). No se usa lastTestedApiVersion. No hay desaprobación, capa de compatibilidad, permisos ni detección de conflictos al cargar. |
| 7 | Modo exploración con navegación rápida y circular | PARCIAL | browse/document.py:65-95, 851-855 (circular). Solo en Chrome, Gecko y Edge por UIA, sin IA2. Faltan 15 tipos y la navegación avanzada de tablas. |
| 8 | Banco de pruebas ARIA | FALTA | tests/ solo contiene test_basico.py. |
| 9 | Paleta de órdenes difusa | PARCIAL | gui/command_palette.py:186-263 ejecuta también órdenes sin gesto. La búsqueda es por subcadenas de palabras (gui/helpers.py:81-83), no difusa. |
| 10 | Mezclador: división, volumen por app, dispositivo, micrófono | PARCIAL | Hay división (audio/sound_split.py), atenuación y elección de dispositivo (settings.py:911). No hay volumen por app, silencio del micrófono ni atajo de dispositivo. |
| 11 | Perfiles por app y dominio, diccionarios, solo lectura | PARCIAL | Disparadores por app (appmodules/handler.py:148-150) y de lectura continua. No hay perfiles por dominio, los diccionarios no van en el perfil (speech/dictionaries.py:121-127) y no hay perfiles de solo lectura. |
| 12 | Etiquetas personalizadas con IA | PARCIAL | labels.py y global_commands.py:586. No hay sugerencia por IA ni gestor de etiquetas; solo modo foco y objetos UIA. |
| 13 | AltGr, modificador configurable, teclado numérico híbrido, conflictos | PARCIAL | Detección de conflictos HECHA (gui/gesture_tools.py:140-160). AltGr es un esbozo (input/core.py:194). No hay modificador arbitrario ni teclado numérico híbrido. |
| 14 | Detección automática de idioma | FALTA | Solo idioma marcado por UIA o HTML (presentation.py:414-456). No hay detección por guion ni por modelo. |
| 15 | Niveles de verbosidad y plantillas por rol | PARCIAL | `presentation.verbosity` normal o baja (presentation.py:278); en la práctica solo quita la posición. No hay plantillas ni orden configurable. |
| 16 | Portapapeles: historial, anunciar cortar/copiar/pegar, añadir | PARCIAL | Historial y aviso «Copiado» (clipboard.py:56-75). No distingue cortar ni pegar, no hay «añadir al portapapeles» y el aviso salta con cualquier cambio. |
| 17 | Marcadores y búsqueda con historial | PARCIAL | Marcadores en modo exploración (browse/document.py:1021-1094). La búsqueda no tiene historial ni opción de mayúsculas en la interfaz. No hay marcadores en documentos editables. |
| 18 | Navegación por palabra camelCase, oración, párrafo y sangría | PARCIAL | Hay párrafo (heurístico). Faltan frases, camelCase o snake_case y navegación por sangría. |
| 19 | Lectura de números | PARCIAL | Solo dígito a dígito (speech/api.py:245-254). Faltan los modos por grupos y alfanumérico. |
| 20 | Temas sonoros y audio posicional | PARCIAL | Tema de sonidos (audio/tones.py:105-195). No hay sonidos por rol ni estado, ni audio posicional. |
| 21 | Resumen de página e indicador de carga | FALTA | La carga es síncrona y no hay resumen. |
| 22 | Leer la URL sin mover el foco e inspector | PARCIAL | Destino del enlace (global_commands.py:239) e información para desarrolladores (global_commands.py:322). No hay orden para la URL de la página ni inspector de atributos ARIA. |
| 23 | Ratón por teclado y puntos guardados | FALTA | Solo clic, bloqueo y mover el ratón al navegador. |
| 24 | Bandeja del sistema, ventanas y procesos | PARCIAL | Lista de ventanas (global_commands.py:976-1004). Faltan la bandeja y los procesos. |
| 25 | Módulos de Office, WhatsApp, Teams, terminal y VS Code | PARCIAL | WhatsApp HECHO (data/addons/whatsapp). Terminal a medias (behaviors.py:254-306). Faltan Office, Outlook, Teams y VS Code. |
| 26 | Braille con liblouis, orden configurable, emojis, división de la línea | FALTA (en lo esencial) | Solo tablas propias (braille/tables.py). No hay liblouis ni ninguna de las otras tres cosas. |
| 27 | Velocidad propia del eco de teclado y confirmaciones | PARCIAL | Confirmaciones de copiar y guardar (api.py:183, global_commands.py:938). No hay velocidad de voz propia para el eco (typing_echo.py). |
| 28 | Traducción instantánea | FALTA | — |
| 29 | Tutorial, ayuda de entrada y asistente de IA | PARCIAL | Ayuda de entrada (global_commands.py:90) y bienvenida (config_dialogs.py:1471). No hay tutorial ni asistente. |
| 30 | Modo portátil de primera clase y política corporativa | PARCIAL | Portable con `--data` (paths.py). No hay política, pantallas seguras ni modo de solo lectura. |
| 31 | Acceso remoto | Fuera de alcance | Se implementa aparte. |
| 32 | Resumen e interrogación de la web con IA | FALTA | — |
| 33 | Cortina de pantalla | HECHO | vision.py:50-96; global_commands.py:1025. Faltan detalles menores (sección 10). |
| 34 | MathCAT | Fuera de alcance | Se implementa aparte. |
| 35 | Voz por canal RDP o Citrix | FALTA | — |
| 36 | Display model GDI | FALTA | — |
| 37 | Gestos táctiles | Fuera de alcance | Se implementa aparte. |

**Recuento:**
- HECHO: 1 (fila 33).
- PARCIAL: 23.
- FALTA: 10 (filas 4, 8, 14, 21, 23, 26, 28, 32, 35 y 36).
- Fuera de alcance: 3 (filas 31, 34 y 37).
