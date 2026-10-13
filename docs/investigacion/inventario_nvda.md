# Inventario exhaustivo de órdenes y opciones de NVDA

Fuente: copia local `adjuntos/nvda` (rama `master`, versión de desarrollo **NVDA 2027.1**, `buildVersion.py`: version_year=2027, version_major=1; esquema de configuración v25). Generado el 6-10-2026 por análisis AST de `source/**/*.py` (todas las funciones `script_*`, decoradores `@script`, diccionarios `__gestures` y llamadas `qn()` de `browseMode.py`) y de `source/config/configSpec.py`. Las descripciones en español proceden de la traducción oficial `source/locale/es/LC_MESSAGES/nvda.po`; si no hay traducción se deja el texto inglés.

Notación de gestos: `kb:` teclado (ambas distribuciones), `kb(desktop):` sobremesa, `kb(laptop):` portátil, `ts:` pantalla táctil, `br(...)`: braille, `bk:` entrada braille. `NVDA` = tecla modificadora. Banderas: `speakOnDemand=True` (habla en modo de voz «a petición»), `allowInSleepMode=True` (funciona en modo dormir), `resumeSayAllMode` (no interrumpe «decir todo»).

**Totales:** 509 funciones `script_` en 43 archivos; 267 órdenes globales; 37 tipos de navegación rápida (cada uno con orden siguiente/anterior, más encabezados de nivel 1-9); 333 claves de configuración.

## 1. Órdenes globales (`globalCommands.py`)

### 1.1 Audio — 2 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `cycleAudioDuckingMode` | `kb:NVDA+shift+d` | Navega por los modos de atenuación de audio, que determinan cuándo NVDA baja el volumen de otros sonidos |  |
| `cycleSoundSplit` | `kb:NVDA+alt+s` | Recorre modos de separación de sonido |  |

### 1.2 Entrada (Input) — 3 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleInputHelp` | `kb:NVDA+1` | Activa o desactiva la ayuda de entrada. Cuando se active, con cualquier entrada tal como la pulsación de una tecla en el teclado te dirá qué script se asocia con esa entrada, si hay alguno. | speakOnDemand=True |
| `toggleKeyboardLayout` | — | Cambia entre la distribución del teclado de ordenador de sobremesa y la de portátil |  |
| `passNextKeyThrough` | `kb:NVDA+f2` | La siguiente tecla que sea pulsada no será manipulada por NVDA, será dejada pasar directamente a Windows. |  |

### 1.3 (sin categoría: solo asignables o internas) — 10 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleCurrentAppSleepMode` | `kb(desktop):NVDA+shift+s`, `kb(laptop):NVDA+shift+z` | Activa o desactiva el modo silencioso para la aplicación activa. | allowInSleepMode=True |
| `quit` | `kb:NVDA+q` | ¡sale de NVDA! |  |
| `restart` | — | ¡Reinicia NVDA! |  |
| `showGui` | `kb:NVDA+n`, `ts:2finger_double_tap` | Muestra el menú de NVDA |  |
| `test_navigatorDisplayModelText` | `kb(desktop):NVDA+control+f2` | — |  |
| `recognizeWithUwpOcr` | `kb:NVDA+r` | Reconoce el contenido del navegador de objetos actual con el OCR de Windows |  |
| `cycleOcrLanguage` | — | Recorre los idiomas disponibles para el OCR de Windows |  |
| `toggleAutomaticRefreshOfRecogResult` | — | Conmutar la actualización periódica de un resultado del OCR de Windows |  |
| `toggleScreenCurtain` | `kb:NVDA+control+escape` | Cambia el estado de la cortina de pantalla, permite hacer que la pantalla se ponga negra o que se desactive para mostrar su contenido. Si se pulsa una vez, la cortina de pantalla se habilita hasta que se reinicie NVDA. Si se pulsa dos veces, la cortina de pantalla se habilita hasta que la deshabilites |  |
| `reportScreenCurtainState` | — | Indica el estado de la cortina de pantalla. | speakOnDemand=True |

### 1.4 Cursor del sistema (System caret) — 11 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `reportCurrentLine` | `kb(desktop):NVDA+upArrow`, `kb(laptop):NVDA+l` | Informa de la línea actual bajo el cursor de la aplicación. Pulsando esta tecla dos veces rápidamente deletreará la línea actual. Pulsándola tres veces deletreará la línea utilizando descripciones de caracteres. | speakOnDemand=True |
| `reportCurrentSelection` | `kb(desktop):NVDA+shift+upArrow`, `kb(laptop):NVDA+shift+s` | Anuncia la selección actual en los controles de edición y documentos. Pulsando dos veces deletrea esta información. Pulsando tres veces la deletrea utilizando descripciones de caracteres. Pulsando cuatro veces la muestra en un mensaje explorable. | speakOnDemand=True |
| `reportCaretLocation` | — | Anuncia la ubicación del texto en el cursor, o la ubicación del objeto enfocado actualmente si no hay cursor. | speakOnDemand=True |
| `caretPos_currentDimensions` | `kb:NVDA+numpadDelete`, `kb(laptop):NVDA+delete` | Anuncia la ubicación del texto o del objeto en la posición del cursor del sistema. Si se pulsa dos veces se pueden obtener más detalles. | speakOnDemand=True |
| `sayAll` | `kb(desktop):NVDA+downArrow`, `kb(laptop):NVDA+a` | Lee desde el cursor del sistema hasta el fin del texto, moviendo el cursor a la vez | speakOnDemand=True |
| `reportFormattingAtCaret` | — | Anuncia información de formato para el texto bajo el cursor. | speakOnDemand=True |
| `showFormattingAtCaret` | — | Presenta, en modo exploración, información de formato para el texto bajo el cursor. |  |
| `reportOrShowFormattingAtCaret` | `kb:NVDA+f` | Anuncia la información de formato para el texto bajo el cursor. Si se pulsa dos veces, presenta la información en modo exploración | speakOnDemand=True |
| `reportDetailsSummary` | `kb:NVDA+d` | Anunciar el resumen de cualquier detalle de la anotación en el cursor del sistema. | speakOnDemand=True |
| `cycleParagraphStyle` | — | Recorre los estilos de navegación por párrafos |  |
| `reportCaretLanguage` | — | Indica el idioma del texto bajo el cursor. Si se pulsa dos veces, presenta la información en modo exploración | speakOnDemand=True |

### 1.5 Ratón (Mouse) — 13 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `leftMouseClick` | `kb:numpadDivide`, `kb(laptop):NVDA+[` | Hace clic con el botón izquierdo una vez en la posición actual del ratón |  |
| `rightMouseClick` | `kb:numpadMultiply`, `kb(laptop):NVDA+]` | Hace clic con el botón derecho una vez en la posición actual del ratón |  |
| `toggleLeftMouseButton` | `kb:shift+numpadDivide`, `kb(laptop):NVDA+control+[` | Bloquea o desbloquea el botón izquierdo del ratón |  |
| `toggleRightMouseButton` | `kb:shift+numpadMultiply`, `kb(laptop):NVDA+control+]` | Bloquea o desbloquea el botón derecho del ratón |  |
| `mouseScrollUp` | — | Desplaza arriba en la posición del ratón |  |
| `mouseScrollDown` | — | Desplaza abajo en la posición del ratón |  |
| `mouseScrollLeft` | — | Desplaza a la izquierda en la posición del ratón |  |
| `mouseScrollRight` | — | Desplaza a la derecha en la posición del ratón |  |
| `moveMouseToNavigatorObject` | `kb:NVDA+numpadDivide`, `kb(laptop):NVDA+shift+m` | Desplaza el puntero del ratón al navegador de objetos actual |  |
| `moveNavigatorObjectToMouse` | `kb:NVDA+numpadMultiply`, `kb(laptop):NVDA+shift+n` | Pone el navegador de objetos en el objeto actual bajo el puntero del ratón y lo verbaliza |  |
| `toggleMouseTracking` | `kb:NVDA+m` | Activa y desactiva el anunciado de información cuando el ratón se mueve |  |
| `toggleMouseAudioCoordinates` | — | Conmuta los pitidos que anuncian las coordenadas del ratón según éste se mueva |  |
| `toggleMouseTextResolution` | — | Cambia la cantidad de texto que se verbalizará cuando el ratón se mueva |  |

### 1.6 Estado del sistema (System status) — 3 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `dateTime` | `kb:NVDA+f12` | Si se pulsa una vez, anuncia la hora actual. Si se pulsa dos veces, anuncia la fecha actual | speakOnDemand=True |
| `say_battery_status` | `kb:NVDA+shift+b` | Anuncia el estado de la batería y el tiempo restante si la fuente externa de alimentación no está enchufada | speakOnDemand=True |
| `reportClipboardText` | `kb:NVDA+c` | Anuncia el texto en el portapapeles de Windows. Pulsando dos veces deletrea esta información. Pulsando tres veces la deletrea utilizando descripciones de caracteres. | speakOnDemand=True |

### 1.7 Voz (Speech) — 21 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `firstValueSynthRing` | — | Establece el primer valor de la opción actual en el anillo de opciones del sintetizador |  |
| `lastValueSynthRing` | — | Establece el último valor de la opción actual en el anillo de opciones del sintetizador |  |
| `increaseSynthSetting` | `kb(desktop):NVDA+control+upArrow`, `kb(laptop):NVDA+shift+control+upArrow` | Aumenta la opción actualmente activa en el anillo de opciones del sintetizador |  |
| `increaseLargeSynthSetting` | `kb(desktop):NVDA+control+pageUp`, `kb(laptop):NVDA+shift+control+pageUp` | Aumenta la opción actualmente activa en el anillo de opciones del sintetizador en un paso mayor |  |
| `decreaseSynthSetting` | `kb(desktop):NVDA+control+downArrow`, `kb(laptop):NVDA+control+shift+downArrow` | Disminuye la opción actualmente activa en el anillo de opciones del sintetizador |  |
| `decreaseLargeSynthSetting` | `kb(desktop):NVDA+control+pageDown`, `kb(laptop):NVDA+control+shift+pageDown` | Disminuye la opción actualmente activa en el anillo de opciones del sintetizador en un paso mayor |  |
| `nextSynthSetting` | `kb(desktop):NVDA+control+rightArrow`, `kb(laptop):NVDA+shift+control+rightArrow` | Se mueve a la siguiente opción disponible en el anillo de opciones del sintetizador |  |
| `previousSynthSetting` | `kb(desktop):NVDA+control+leftArrow`, `kb(laptop):NVDA+shift+control+leftArrow` | Se mueve a la opción anterior disponible en el anillo de opciones del sintetizador |  |
| `toggleSpeakTypedCharacters` | `kb:NVDA+2` | Recorre las opciones de cuándo pronunciar los caracteres tecleados. |  |
| `toggleSpeakTypedWords` | `kb:NVDA+3` | Recorre las opciones de cuándo pronunciar las palabras escritas. |  |
| `toggleSpeakCommandKeys` | `kb:NVDA+4` | Activa y desactiva la verbalización de las teclas de órdenes |  |
| `cycleSpeechAutomaticLanguageSwitching` | — | Recorre las opciones posibles para Cambio automático de idiomas: desactivado, sólo idioma e idioma y dialecto. |  |
| `cycleSpeechSymbolLevel` | `kb:NVDA+p` | Se mueve por los niveles de verbalización de símbolos, que determinan qué símbolos se verbalizarán |  |
| `toggleDelayedCharacterDescriptions` | — | Activa y desactiva las descripciones retrasadas de caracteres con el movimiento del cursor |  |
| `speechMode` | `kb:NVDA+s` | Recorre los modos de voz. |  |
| `toggleProgressBarOutput` | `kb:NVDA+u` | Conmuta entre pitidos, voz, pitidos y voz, y desactivado, para el anunciado de actualizaciones de la barra de progreso |  |
| `toggleReportDynamicContentChanges` | `kb:NVDA+5` | Activa y desactiva el anunciado de los cambios de contenido dinámico, tales como texto nuevo en la consola dos de windows |  |
| `toggleReportCLDR` | — | Activa y desactiva el anunciado de los caracteres CLDR, tales como los emojis |  |
| `speech_cycleUnicodeNormalization` | — | Recorre los estados de la normalización Unicode de voz |  |
| `repeatLastSpokenInformation` | `kb:NVDA+x` | Repite la última información que se ha verbalizado. Si pulsas dos veces, se muestra en un mensaje que se puede leer. | speakOnDemand=True |
| `copyLastSpokenInformation` | `kb:NVDA+control+x` | Copia la última información pronunciada al portapapeles. |  |

### 1.8 Formateado de Documentos (Document formatting) — 35 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleReportFontName` | — | Activa o desactiva el anunciado de cambios de la fuente |  |
| `toggleReportFontSize` | — | Activa y desactiva el anunciado de los cambios en el tamaño de la fuente |  |
| `toggleReportFontAttributes` | — | Recorre los atributos de fuente anunciando entre voz, braille, voz y braille y desactivado. |  |
| `toggleReportSuperscriptsAndSubscripts` | — | Activa y desactiva el anunciado de superíndices y subíndices |  |
| `toggleReportRevisions` | — | Activa y desactiva el anunciado de revisiones |  |
| `toggleReportEmphasis` | — | Activa y desactiva el anunciado del énfasis |  |
| `toggleReportHighlightedText` | — | Activa y desactiva el anunciado de texto resaltado |  |
| `toggleReportColor` | — | Activa y desactiva el anunciado de colores |  |
| `toggleReportAlignment` | — | Activa y desactiva el anunciado de la alineación del texto |  |
| `toggleReportStyle` | — | Activa y desactiva el anunciado de cambios de estilo |  |
| `toggleReportSpellingErrors` | — | Recorre las opciones de cómo anunciar los errores ortográficos o de gramática |  |
| `toggleReportSpellingErrorsInBraille` | — | Conmuta el anunciado de errores ortográficos o de gramática en braille |  |
| `toggleReportPage` | — | Activa y desactiva el anunciado de página |  |
| `toggleReportLineNumber` | — | Activa y desactiva el anunciado de números de línea |  |
| `toggleReportLineIndentation` | — | Se mueve a través de las opciones de sangría de línea |  |
| `toggleignoreBlankLinesForReportLineIndentation` | — | Activa y desactiva ignorar líneas en blanco para el anunciado de sangría de líneas |  |
| `toggleReportParagraphIndentation` | — | Activa y desactiva el anunciado de la sangría de párrafo |  |
| `toggleReportLineSpacing` | — | Activa y desactiva el anunciado de espaciado de línea |  |
| `toggleReportTables` | — | Activa y desactiva el anunciado de tablas |  |
| `toggleReportTableHeaders` | — | Recorre los modos posibles para anunciar las cabeceras de las filas y columnas de la tabla |  |
| `toggleReportTableCellCoords` | — | Activa y desactiva el anunciado de coordenadas de celdas en tablas |  |
| `toggleReportCellBorders` | — | Se mueve por las opciones de borde de la celda |  |
| `toggleReportLinks` | — | Activa y desactiva el anunciado de enlaces |  |
| `toggleReportLinkType` | — | Activa y desactiva el anunciado del tipo de enlace |  |
| `toggleReportGraphics` | — | Activa y desactiva el anunciado de gráficos |  |
| `toggleReportComments` | — | Activa y desactiva el anunciado de comentarios |  |
| `toggleReportLists` | — | Activa y desactiva el anunciado de listas |  |
| `toggleReportHeadings` | — | Activa y desactiva el anunciado de encabezados |  |
| `toggleReportGroupings` | — | Activa y desactiva el anunciado de agrupaciones |  |
| `toggleReportBlockQuotes` | — | Activa y desactiva el anunciado de citas |  |
| `toggleReportLandmarks` | — | Activa y desactiva el anunciado de regiones |  |
| `toggleReportArticles` | — | Activa y desactiva el anunciado de artículos |  |
| `toggleReportFrames` | — | Activa y desactiva el anunciado de marcos |  |
| `toggleReportClickable` | — | Activa y desactiva el anunciado de si es cliqueable |  |
| `toggleReportFigures` | — | Activa y desactiva la lectura de figuras y rótulos |  |

### 1.9 Braille — 26 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleBrailleAutoScroll` | `kb:NVDA+alt+k` | Activa o desactiva el desplazamiento automático en braille |  |
| `increaseBrailleAutoScrollRate` | `kb:NVDA+alt+l` | Aumenta la velocidad de desplazamiento automático del braille |  |
| `decreaseBrailleAutoScrollRate` | `kb:NVDA+alt+j` | Disminuye la velocidad de desplazamiento automático del braille |  |
| `braille_toggleTether` | `kb:NVDA+control+t` | Conmutar el seguimiento de braille entre el foco y la posición de revisión |  |
| `toggleBrailleMode` | `kb:NVDA+alt+t` | Conmuta modo braille |  |
| `braille_cycleReviewRoutingMovesSystemCaret` | — | Recorre los estados de movimiento del cursor del sistema cuando se mueve el cursor de revisión en braille |  |
| `braille_toggleFocusContextPresentation` | — | Conmuta la forma en la que la información de contexto se presenta en braille |  |
| `braille_toggleShowCursor` | — | Activa o desactiva el cursor braille |  |
| `braille_toggleSpeakOnRouting` | — | Conmutar la verbalización del carácter bajo el cursor al enrutar el cursor en el texto |  |
| `toggleSpeakingOnNavigatingByUnit` | — | Activa y desactiva la verbalización cuando se lee por líneas o por párrafos con el braille |  |
| `braille_cycleCursorShape` | — | Se mueve a través de las formas del cursor braille |  |
| `braille_cycleShowMessages` | — | Recorre los modos de mostrar mensajes en braille |  |
| `braille_cycleShowSelection` | — | Recorre los estados de mostrar la selección braille |  |
| `braille_cycleUnicodeNormalization` | — | Recorre los estados de la normalización Unicode braille |  |
| `braille_scrollBack` | — | Desplaza la línea braille hacia atrás | bypassInputHelp=True |
| `braille_scrollForward` | — | Desplaza la línea braille hacia adelante | bypassInputHelp=True |
| `braille_routeTo` | — | Lleva el cursor hacia el objeto bajo la celda braille o lo activa |  |
| `braille_reportFormatting` | — | Anuncia información de formato para el texto bajo esta celda braille |  |
| `braille_selectRange` | — | Selecciona el texto desde la primera celda braille hasta la última |  |
| `braille_previousLine` | — | Mueve la pantalla braille a la línea anterior |  |
| `braille_nextLine` | — | Mueve la pantalla braille a la línea siguiente |  |
| `braille_dots` | `bk:dots` | Introduce puntos braille a través del teclado braille |  |
| `braille_toFocus` | — | Mueve la pantalla braille al foco actual |  |
| `braille_eraseLastCell` | `bk:dot7` | Borra la última celda o carácter braille introducido |  |
| `braille_enter` | `bk:dot8` | Transcribe cualquier entrada braille y pulsa la tecla intro |  |
| `braille_translate` | `bk:dot7+dot8` | Transcribe cualquier entrada braille |  |

### 1.10 Revisión de texto (Text review) — 28 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `reviewMode_next` | `kb:NVDA+numpad7`, `kb(laptop):NVDA+pageUp`, `ts(object):2finger_flickUp` | Cambia al siguiente modo de revisión (es decir: objeto, documento o pantalla) y coloca la posición de revisión en el punto del navegador de objetos |  |
| `reviewMode_previous` | `kb:NVDA+numpad1`, `kb(laptop):NVDA+pageDown`, `ts(object):2finger_flickDown` | Cambia al modo de revisión anterior (es  decir: objeto, documento o pantalla) y coloca la posición de revisión en el punto del navegador de objetos |  |
| `review_top` | `kb:shift+numpad7`, `kb(laptop):NVDA+control+home` | Mueve el cursor de revisión a la línea superior del navegador de objetos actual y la verbaliza |  |
| `review_previousLine` | `kb:numpad7`, `kb(laptop):NVDA+upArrow`, `ts(text):flickUp` | Mueve el cursor de revisión a la línea anterior del navegador de objetos actual y la verbaliza | resumeSayAllMode=sayAll.CURSOR.REVIEW |
| `review_currentLine` | `kb:numpad8`, `kb(laptop):NVDA+shift+.` | Anuncia la línea del navegador de objetos actual donde esté situado el cursor de revisión. Si esta tecla se pulsa dos veces, la línea actual se deletreará. Pulsándola tres veces se deletreará la línea utilizando descripciones fonéticas. | speakOnDemand=True |
| `review_nextLine` | `kb:numpad9`, `kb(laptop):NVDA+downArrow`, `ts(text):flickDown` | Mueve el cursor de revisión a la siguiente línea del navegador de objetos actual y la verbaliza | resumeSayAllMode=sayAll.CURSOR.REVIEW |
| `review_previousPage` | `kb:NVDA+pageUp`, `kb(laptop):NVDA+shift+pageUp` | Mueve el cursor de revisión a la página anterior del navegador de objetos actual y la verbaliza | resumeSayAllMode=sayAll.CURSOR.REVIEW |
| `review_nextPage` | `kb:NVDA+pageDown`, `kb(laptop):NVDA+shift+pageDown` | Mueve el cursor de revisión a la siguiente página del navegador de objetos actual y la verbaliza | resumeSayAllMode=sayAll.CURSOR.REVIEW |
| `review_bottom` | `kb:shift+numpad9`, `kb(laptop):NVDA+control+end` | Mueve el cursor de revisión a la línea inferior del navegador de objetos actual y la verbaliza |  |
| `review_previousWord` | `kb:numpad4`, `kb(laptop):NVDA+control+leftArrow`, `ts(text):2finger_flickLeft` | Mueve el cursor de revisión a la palabra anterior del navegador de objetos actual y la verbaliza |  |
| `review_currentWord` | `kb:numpad5`, `kb(laptop):NVDA+control+.`, `ts(text):hoverUp` | Verbaliza la palabra del navegador de objetos actual donde esté situado el cursor de revisión. Pulsando dos veces deletrea la palabra. Pulsando tres veces verbaliza la palabra utilizando descripción de caracteres | speakOnDemand=True |
| `review_nextWord` | `kb:numpad6`, `kb(laptop):NVDA+control+rightArrow`, `ts(text):2finger_flickRight` | Mueve el cursor de revisión a la siguiente palabra del navegador de objetos actual y la verbaliza |  |
| `review_startOfLine` | `kb:shift+numpad1`, `kb(laptop):NVDA+home` | Mueve el cursor de revisión al primer carácter de la línea donde se sitúe en el navegador de objetos actual y la verbaliza |  |
| `review_previousCharacter` | `kb:numpad1`, `kb(laptop):NVDA+leftArrow`, `ts(text):flickLeft` | Mueve el cursor de revisión al carácter anterior del navegador de objetos actual y lo verbaliza |  |
| `review_currentCharacter` | `kb:numpad2`, `kb(laptop):NVDA+.` | Anuncia el carácter del navegador de objetos actual donde esté situado el cursor de revisión. Pulsando dos veces anuncia una descripción o ejemplo de ese carácter. Pulsando tres veces anuncia el valor numérico del carácter en decimal y hexadecimal | speakOnDemand=True |
| `review_nextCharacter` | `kb:numpad3`, `kb(laptop):NVDA+rightArrow`, `ts(text):flickRight` | Mueve el cursor de revisión al siguiente carácter del navegador de objetos actual y lo verbaliza |  |
| `review_endOfLine` | `kb:shift+numpad3`, `kb(laptop):NVDA+end` | Mueve el cursor de revisión al último carácter de la línea donde se sitúe en el navegador de objetos actual y lo verbaliza |  |
| `review_startOfSelection` | `kb:NVDA+alt+home` | Mueve el cursor de revisión al primer carácter de la selección y lo verbaliza |  |
| `review_endOfSelection` | `kb:NVDA+alt+end` | Mueve el cursor de revisión al último carácter de la selección y lo verbaliza |  |
| `review_currentSymbol` | — | Anuncia el símbolo donde esté colocado el cursor de revisión. Presionado dos veces, muestra el símbolo y el texto utilizado para verbalizarlo en modo exploración | speakOnDemand=True |
| `review_sayAll` | `kb:numpadPlus`, `kb(laptop):NVDA+shift+a`, `ts(text):3finger_flickDown` | Lee desde el cursor de revisión hasta el final del texto actual, moviendo el cursor de revisión según lo haga | speakOnDemand=True |
| `reportFormattingAtReview` | — | Anuncia información de formato para la posición actual del cursor de revisión. | speakOnDemand=True |
| `showFormattingAtReview` | — | Presenta, en modo exploración, información de formato para la posición del cursor de revisión actual. |  |
| `reportFormatting` | `kb:NVDA+shift+f` | Anuncia la información de formato para la posición actual del cursor de revisión. Si se pulsa dos veces, presenta la información en modo exploración | speakOnDemand=True |
| `toggleCaretMovesReviewCursor` | `kb:NVDA+6` | Activa y desactiva el movimiento del cursor de revisión debido al movimiento del cursor del sistema. |  |
| `review_markStartForCopy` | `kb:NVDA+f9` | Marca la posición actual del cursor de revisión como el comienzo del texto a ser seleccionado o copiado |  |
| `review_moveToStartMarkedForCopy` | `kb:NVDA+shift+F9` | Mueve el cursor de revisión a la posición marcada como inicio del texto a seleccionar o copiar |  |
| `review_copy` | `kb:NVDA+f10` | Si se pulsa una vez, el texto de la marca puesta anteriormente e incluyendo la posición actual del cursor de revisión se selecciona. Si se pulsa dos veces, el texto se copia al portapapeles |  |

### 1.11 Navegación de objetos (Object navigation) — 16 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleSimpleReviewMode` | — | Activa y desactiva el modo de revisión simple |  |
| `navigatorObject_current` | `kb:NVDA+numpad5`, `kb(laptop):NVDA+shift+o` | Anuncia el navegador de objetos actual. Pulsando dos veces deletrea esta información,y pulsando tres veces Copia el nombre y el valor de este objeto al portapapeles | speakOnDemand=True |
| `reportReviewCursorLocation` | — | Anuncia información de la ubicación del texto en el cursor de revisión, o de la ubicación del navegador de objetos si no hay texto bajo el cursor de revisión. | speakOnDemand=True |
| `reportCurrentNavigatorObjectLocation` | — | Anuncia información sobre la ubicación del navegador de objetos actual. | speakOnDemand=True |
| `navigatorObject_currentDimensions` | `kb:NVDA+shift+numpadDelete`, `kb(laptop):NVDA+shift+delete` | Anuncia información acerca de la posición del texto u objeto en el cursor de revisión. Al pulsar dos veces podrá proporcionar más detalles. | speakOnDemand=True |
| `navigatorObject_toFocus` | `kb:NVDA+numpadMinus`, `kb(laptop):NVDA+backspace` | Pone el navegador de objetos en el foco actual y el cursor de revisión en la posición del cursor de sistema dentro de él si es posible. |  |
| `navigatorObject_moveFocus` | `kb:NVDA+shift+numpadMinus`, `kb(laptop):NVDA+shift+backspace` | Pulsado una vez pone el foco del teclado en el navegador de objetos, pulsado dos veces pone el cursor del sistema en la posición del cursor de revisión |  |
| `navigatorObject_parent` | `kb:NVDA+numpad8`, `kb(laptop):NVDA+shift+upArrow`, `ts(object):flickup` | Mueve el navegador de objetos al objeto que lo contenga |  |
| `navigatorObject_next` | `kb:NVDA+numpad6`, `kb(laptop):NVDA+shift+rightArrow`, `ts(object):2finger_flickright` | Mueve el navegador de objetos al siguiente objeto |  |
| `navigatorObject_previous` | `kb:NVDA+numpad4`, `kb(laptop):NVDA+shift+leftArrow`, `ts(object):2finger_flickleft` | Mueve el navegador de objetos al objeto anterior |  |
| `navigatorObject_firstChild` | `kb:NVDA+numpad2`, `kb(laptop):NVDA+shift+downArrow`, `ts(object):flickdown` | Mueve el navegador de objetos al primer objeto dentro de él |  |
| `review_activate` | `kb:NVDA+numpadEnter`, `kb(laptop):NVDA+enter`, `ts:double_tap` | Lleva a cabo la acción predeterminada en el navegador de objetos actual (ejemplo: pulsar si es un botón). |  |
| `reviewCursorToStatusLine` | — | Lee la barra de estado de la aplicación actual y pone el navegador de objetos en ella. |  |
| `toggleFocusMovesNavigatorObject` | `kb:NVDA+7` | Activa y desactiva el movimiento del navegador de objetos debido a cambios del foco |  |
| `navigatorObject_nextInFlow` | `ts(object):flickright`, `kb:NVDA+numpad3`, `kb(laptop):shift+NVDA+]` | Se desplaza al siguiente objeto en una vista plana de la jerarquía de navegación de objetos |  |
| `navigatorObject_previousInFlow` | `ts(object):flickleft`, `kb:NVDA+numpad9`, `kb(laptop):shift+NVDA+[` | Se desplaza al objeto anterior en una vista plana en  la jerarquía del navegador de objetos |  |

### 1.12 Foco del sistema (System focus) — 10 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `reportFocusObjectLocation` | — | Anuncia la ubicación del objeto enfocado actualmente. | speakOnDemand=True |
| `moveToParentTreeInterceptor` | `kb:NVDA+control+space` | Mueve el foco fuera del objeto integrado actual y dentro del documento que lo contenga |  |
| `reportCurrentFocus` | `kb:NVDA+tab` | Anuncia el objeto con el foco. Si se pulsa dos veces, deletrea la información. Pulsando tres veces la deletrea utilizando descripciones de caracteres. | speakOnDemand=True |
| `readStatusLine` | — | Lee la barra de estado de la aplicación actual. | speakOnDemand=True |
| `spellStatusLine` | — | Deletrea la barra de estado de la aplicación actual. | speakOnDemand=True |
| `copyStatusLine` | — | Copia el contenido de la barra de estado de la aplicación actual al portapapeles. |  |
| `reportStatusLine` | `kb(desktop):NVDA+end`, `kb(laptop):NVDA+shift+end` | Lee la barra de estado de la aplicación actual. Si se pulsa dos veces, deletrea la información. Si se pulsa tres veces, copia la barra de estado en el portapapeles | speakOnDemand=True |
| `reportFocusObjectAccelerator` | `kb:shift+numpad2`, `kb(laptop):NVDA+control+shift+.` | Anuncia el atajo de teclado del objeto actualmente enfocado | speakOnDemand=True |
| `title` | `kb:NVDA+t` | Anuncia el título de la aplicación o ventana en primer plano actuales. Si se presionó dos veces, deletrea el título. Si se presionó tres veces, copia el título al portapapeles | speakOnDemand=True |
| `speakForeground` | `kb:NVDA+b` | Lee todos los controles de la ventana activa | speakOnDemand=True |

### 1.13 Modo Exploración (Browse mode) — 1 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleVirtualBufferPassThrough` | `kb:NVDA+space` | Conmuta entre el modo exploración y el modo foco. Cuando esté en el modo foco, las teclas pasarán directamente a través de la aplicación, permitiéndote interactuar directamente con un control. Cuando esté en modo exploración, puedes navegar por el documento con el cursor, teclas rápidas de navegación, etc. |  |

### 1.14 Herramientas (Tools) — 12 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `startWxInspectionTool` | — | Abre la herramienta de inspección WX GUI. Utilizada para obtener más información acerca del estado de los componentes de la Interfaz Gráfica de Usuario. |  |
| `navigatorObject_devInfo` | `kb:NVDA+f1` | Envía información al registro acerca del actual navegador de objetos, lo cual es útil para desarrolladores, y activa el visualizador del registro para que la información pueda ser examinada. |  |
| `log_markStartThenCopy` | `kb:NVDA+control+shift+f1` | Marca el final actual del registro como el inicio del fragmento a ser copiado en el portapapeles pulsando otra vez. |  |
| `openUserConfigurationDirectory` | — | Abre el directorio de configuración de NVDA del usuario actual. |  |
| `reportAppModuleInfo` | `kb:NVDA+control+f1` | Verbaliza el nombre de fichero de la aplicación activa junto con el nombre del módulo de aplicación cargado actualmente | speakOnDemand=True |
| `activatePythonConsole` | `kb:NVDA+control+z` | Activa la Consola Python de NVDA, principalmente útil para desarrolladores |  |
| `activateAddonsManager` | — | Activa la Tienda de Complementos de NVDA para instalar y gestionar paquetes de complementos para NVDA |  |
| `toggleSpeechViewer` | — | Activa o desactiva el Visualizador de voz de NVDA, una ventana flotante que te permite ver todo el texto que esté verbalizando NVDA actualmente |  |
| `toggleBrailleViewer` | — | Activa y desactiva el visualizador de braille de NVDA, una ventana flotante que permite ver la salida en braille y el equivalente en texto de cada carácter braille |  |
| `reloadPlugins` | `kb:NVDA+control+f3` | Recarga los módulos de aplicación y las extensiones globales sin reiniciar NVDA, lo cual puede ser útil para desarrolladores |  |
| `reportLinkDestination` | `kb:NVDA+k` | Anuncia la URL de destino del enlace en el navegador de objetos. Si se pulsa dos veces, muestra la URL en una ventana para una revisión más fácil. | speakOnDemand=True |
| `reportLinkDestinationInWindow` | — | Muestra la URL de destino del enlace bajo el cursor o el foco en una ventana, en lugar de sólo verbalizarlo. Puede ser preferible para los usuarios de braille. |  |

### 1.15 Configuración (Configuration) — 29 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `activateGeneralSettingsDialog` | `kb:NVDA+control+g` | Muestra las opciones generales de NVDA |  |
| `activateSynthesizerDialog` | `kb:NVDA+control+s` | Muestra el diálogo de selección de sintetizadores de NVDA |  |
| `activateVoiceDialog` | `kb:NVDA+control+v` | Muestra las opciones de voz de NVDA |  |
| `activateBrailleDisplayDialog` | `kb:NVDA+control+a` | Muestra el diálogo de selección de las pantallas braille de NVDA |  |
| `activateBrailleSettingsDialog` | — | Muestra las opciones de Braille de NVDA |  |
| `activateAudioSettingsDialog` | `kb:NVDA+control+u` | Muestra las opciones de audio de NVDA |  |
| `activatePrivacyAndSecuritySettings` | — | Muestra la configuración de privacidad y seguridad de NVDA |  |
| `activateVisionSettingsDialog` | — | Muestra las opciones de visión de NVDA |  |
| `activateKeyboardSettingsDialog` | `kb:NVDA+control+k` | Muestra las opciones de Teclado de NVDA |  |
| `activateMouseSettingsDialog` | `kb:NVDA+control+m` | Muestra las opciones del Ratón de NVDA |  |
| `activateReviewCursorDialog` | — | Muestra las opciones de Cursor de Revisión de NVDA |  |
| `activateInputCompositionDialog` | — | Muestra las opciones de composición de entrada de NVDA |  |
| `activateObjectPresentationDialog` | `kb:NVDA+control+o` | Muestra las opciones de presentación de Objetos de NVDA |  |
| `activateBrowseModeDialog` | `kb:NVDA+control+b` | Muestra las opciones del modo Exploración de NVDA |  |
| `activateDocumentFormattingDialog` | `kb:NVDA+control+d` | Muestra las opciones de formateado de documentos de NVDA |  |
| `activateRemoteAccessSettings` | — | Muestra las opciones de acceso remoto |  |
| `activateAddonStoreSettings` | — | Muestra las opciones de la tienda de complementos de NVDA |  |
| `activateWindowsOCRSettings` | — | Muestra las opciones del OCR de Windows de NVDA |  |
| `activateAdvancedSettings` | — | Muestra las opciones avanzadas de NVDA |  |
| `activateDefaultDictionaryDialog` | — | Muestra el diálogo Diccionario predeterminado de NVDA |  |
| `activateVoiceDictionaryDialog` | — | Muestra el diálogo Diccionario específico por Voces de NVDA |  |
| `activateTemporaryDictionaryDialog` | — | Muestra el diálogo diccionario temporal de NVDA |  |
| `activateSpeechSymbolsDialog` | — | Muestra el diálogo Pronunciación de Símbolos de NVDA |  |
| `activateInputGesturesDialog` | — | Muestra el diálogo Gestos de Entrada de NVDA |  |
| `activateMagnifierSettingsDialog` | `kb:NVDA+control+w` | Muestra las opciones del magnificador de NVDA |  |
| `reportActiveConfigurationProfile` | — | Anuncia el nombre del perfil de configuración actual de NVDA | speakOnDemand=True |
| `saveConfiguration` | `kb:NVDA+control+c` | Guarda la configuración actual de NVDA |  |
| `revertConfiguration` | `kb:NVDA+control+r` | Pulsando una vez lleva la configuración actual al estado guardado más recientemente. Pulsando tres veces lleva a los valores predeterminados de fábrica. |  |
| `toggleConfigProfileTriggers` | — | Habilita y deshabilita todos los disparadores del perfil de configuración. La deshabilitación permanece en efecto hasta que NVDA se reinicie |  |

### 1.16 Teclas de sistema del teclado emuladas (Emulated system keyboard keys) — 11 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `braille_toggleShift` | — | Conmuta virtualmente la tecla shift para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleControl` | — | Conmuta virtualmente la tecla control para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleAlt` | — | Conmuta virtualmente la tecla alt para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleWindows` | — | Conmuta virtualmente la tecla Windows izquierda para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleNVDAKey` | — | Conmuta virtualmente la tecla NVDA para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleControlShift` | — | Conmuta virtualmente las teclas de control y mayúsculas para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleAltShift` | — | Conmuta virtualmente las teclas alt y shift para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleWindowsShift` | — | Conmuta virtualmente las teclas Windows izquierda y shift para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleNVDAKeyShift` | — | Conmuta virtualmente las teclas NVDA y shift para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleControlAlt` | — | Conmuta virtualmente las teclas control y alt para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |
| `braille_toggleControlAltShift` | — | Conmuta virtualmente las teclas control, alt y  shift para emular un atajo de teclado con la entrada braille | bypassInputHelp=True |

### 1.17 Pantalla táctil (Touch screen) — 6 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleTouchSupport` | `kb:NVDA+control+alt+t` | Conmuta el soporte de interacción táctil |  |
| `touch_changeMode` | `ts:3finger_tap` | Se mueve entre los modos táctiles disponibles |  |
| `touch_newExplore` | `ts:tap`, `ts:hoverDown` | Anuncia el objeto y contenido directamente bajo el dedo |  |
| `touch_explore` | `ts:hover` | Anuncia el objeto nuevo o el contenido bajo el dedo si es diferente a donde estuviera el dedo anteriormente |  |
| `touch_hoverUp` | `ts:hoverUp` | — |  |
| `touch_rightClick` | `ts:tapAndHold` | Hace clic con el botón derecho una vez en la posición actual del ratón. Normalmente esto se utiliza para activar un menú de contexto. |  |

### 1.18 Perfiles de configuración (Configuration profiles) — 1 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `activateConfigProfilesDialog` | `kb:NVDA+control+p` | Muestra el diálogo de Perfiles de configuración de NVDA |  |

### 1.19 Navegación de matemáticas (Math navigation) — 1 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `interactWithMath` | `kb:NVDA+alt+m` | Comienza la interacción con el contenido matemático |  |

### 1.20 Magnificador (Magnifier) — 20 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleMagnifier` | `kb:NVDA+shift+w` | Activar y desactivar el magnificador |  |
| `zoomIn` | `kb:NVDA+shift+=` | Aumentar el nivel de ampliación |  |
| `zoomOut` | `kb:NVDA+shift+-` | Reducir el nivel de ampliación |  |
| `panLeft` | `kb:nvda+alt+leftArrow` | Desplazar la vista ampliada hacia la izquierda |  |
| `panRight` | `kb:nvda+alt+rightArrow` | Desplazar la vista ampliada hacia la derecha |  |
| `panUp` | `kb:nvda+alt+upArrow` | Desplazar la vista ampliada hacia arriba |  |
| `panDown` | `kb:nvda+alt+downArrow` | Desplazar la vista ampliada hacia abajo |  |
| `panToLeftEdge` | `kb:nvda+shift+alt+leftArrow` | Desplazar la vista ampliada hacia el borde izquierdo |  |
| `panToRightEdge` | `kb:nvda+shift+alt+rightArrow` | Desplazar la vista ampliada hacia el borde derecho |  |
| `panToTopEdge` | `kb:nvda+shift+alt+upArrow` | Desplazar la vista ampliada hacia el borde supèrior |  |
| `panToBottomEdge` | `kb:nvda+shift+alt+downArrow` | Desplazar la vista ampliada hacia el borde inferior |  |
| `moveMouseToView` | — | Mueve el cursor del ratón al centro de la vista ampliada |  |
| `cycleFilters` | `kb:NVDA+shift+i` | Recorrer los filtros de color |  |
| `toggleFollowMouse` | — | Activar o desactivar el seguimiento del ratón con el magnificador |  |
| `toggleFollowSystemFocus` | — | Activar o desactivar el seguimiento del foco del sistema con el magnificador |  |
| `toggleFollowReview` | — | Activar o desactivar el seguimiento del cursor de revisión con el magnificador |  |
| `toggleFollowNavigatorObject` | — | Activar o desactivar el seguimiento del navegador de objetos con el magnificador |  |
| `toggleAllFollow` | — | Activar o desactivar todas las opciones de seguimiento del magnificador |  |
| `cycleTrackingModes` | — | Recorrer los modos de seguimiento |  |
| `showEntireScreenOverview` | `kb:NVDA+shift+l` | Mostrar temporalmente una vista general de toda la pantalla |  |

### 1.21 Acceso Remoto (Remote Access) — 8 órdenes

| Script | Gestos por defecto | Descripción (es) | Banderas |
|---|---|---|---|
| `toggleRemoteMute` | — | Silencia o reactiva la voz procedente del equipo remoto |  |
| `pushClipboard` | — | Envía los contenidos del portapapeles al equipo remoto |  |
| `copyRemoteLink` | — | Copia al portapapeles un enlace a la sesión remota actual |  |
| `disconnectFromRemote` | — | Se desconecta de la sesión actual de acceso remoto |  |
| `connectToRemote` | — | Se conecta a un equipo remoto |  |
| `toggleRemoteConnection` | `kb:NVDA+alt+r` | Conmuta la conexión del acceso remoto |  |
| `sendKeys` | `kb:NVDA+alt+tab` | Alterna el control de teclado entre el equipo local y el remoto |  |
| `sendSAS` | — | Enviar control+alt+supr al ordenador controlado. |  |

## 2. Navegación rápida en modo exploración (`browseMode.py`, `qn()`)

Cada tipo genera `script_next<Tipo>` (tecla) y `script_previous<Tipo>` (Mayús+tecla); los que no tienen tecla quedan sin asignar pero disponibles en Gestos de entrada. Además `_addQuickNavHeading(range(1,10))` crea encabezados de nivel 1-9 (teclas 1-6 asignadas; 7-9 sin asignar). Si no hay elemento se anuncia «no hay siguiente …». La columna «Táctil» indica si figura en el rotor táctil de exploración.

| Tipo | Tecla | Descripción siguiente (es) | Etiqueta táctil |
|---|---|---|---|
| `heading` | `h` | se mueve al siguiente encabezado | encabezados |
| `table` | `t` | se mueve a la siguiente tabla | tablas |
| `link` | `k` | se mueve al enlace siguiente | enlaces |
| `visitedLink` | `v` | se mueve al siguiente enlace visitado | enlaces visitados |
| `unvisitedLink` | `u` | se mueve al siguiente enlace sin visitar | enlaces no visitados |
| `formField` | `f` | se mueve al siguiente campo de formulario | campos de formulario |
| `list` | `l` | se mueve a la lista siguiente | listas |
| `listItem` | `i` | se mueve al siguiente elemento de lista | elementos de lista |
| `button` | `b` | se mueve al siguiente botón | botones |
| `edit` | `e` | se mueve al siguiente campo de edición | campos de edición |
| `frame` | `m` | se mueve al siguiente marco | marcos |
| `separator` | `s` | se mueve al siguiente separador | separadores |
| `radioButton` | `r` | se mueve al siguiente botón de opción | botones de opción |
| `comboBox` | `c` | se mueve al siguiente cuadro combinado | cuadros combinados |
| `checkBox` | `x` | se mueve a la siguiente casilla de verificación | casillas de verificación |
| `graphic` | `g` | se mueve al siguiente gráfico | gráficos |
| `blockQuote` | `q` | se mueve a la siguiente cita | citas |
| `notLinkBlock` | `n` | salta adelante pasando un bloque de enlaces | bloques sin enlaces |
| `landmark` | `d` | se mueve a la siguiente región | marcadores |
| `embeddedObject` | `o` | se mueve al siguiente objeto integrado | objetos empotrados |
| `annotation` | `a` | se mueve a la siguiente anotación | anotaciones |
| `error` | `w` | se mueve al siguiente error | errores |
| `slider` | sin asignar | va al siguiente deslizador | deslizadores |
| `clickable` | sin asignar | se mueve al siguiente elemento en el que se puede hacer clic | elementos en los que se puede hacer clic |
| `article` | sin asignar | se mueve al siguiente artículo | artículos |
| `grouping` | sin asignar | se mueve a la siguiente agrupación | grupos |
| `tab` | sin asignar | se mueve a la siguiente pestaña | pestañas |
| `figure` | sin asignar | se mueve a la figura siguiente | figuras |
| `menuItem` | sin asignar | se mueve al siguiente elemento de menú | elementos de menú |
| `toggleButton` | sin asignar | se mueve al siguiente botón conmutable | botones conmutables |
| `progressBar` | sin asignar | se mueve a la siguiente barra de progreso | barras de progreso |
| `math` | sin asignar | se mueve a la siguiente fórmula matemática | fórmulas matemáticas |
| `textParagraph` | `p` | se mueve al siguiente párrafo de texto | párrafos de texto |
| `verticalParagraph` | sin asignar | se mueve al siguiente párrafo alineado verticalmente | párrafos verticales |
| `sameStyle` | sin asignar | se mueve al siguiente texto del mismo estilo | mismo estilo |
| `differentStyle` | sin asignar | se mueve al siguiente texto de diferente estilo | estilo diferente |
| `reference` | sin asignar | va a la siguiente referencia | referencias |

## 3. Órdenes de modos, documentos, objetos y aplicaciones

Incluye también los scripts internos sin descripción (interceptan teclas nativas para anunciar el resultado: p. ej. flechas en campos editables, Ctrl+B en Word). Un clon debe reproducir ese comportamiento aunque no aparezcan en el diálogo Gestos de entrada.

### 3.1 `browseMode.py` — 18

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrowseModeTreeInterceptor | `trapNonCommandGesture` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeTreeInterceptor | `toggleSingleLetterNav` | `kb:NVDA+shift+space` | Activa y desactiva la navegación con una sola letra. Cuando esté activada, las teclas solas en modo Exploración saltan a varios tipos de elementos en la página. Cuando esté desactivada, estas teclas se pasan a la aplicación |
| BrowseModeTreeInterceptor | `elementsList` | `kb:NVDA+f7` | Enumera diversos tipos de elementos en este documento |
| BrowseModeTreeInterceptor | `activatePosition` | `kb:enter`, `kb:numpadEnter`, `kb:space` | Activa el objeto actual en el documento |
| BrowseModeTreeInterceptor | `passThrough` | `kb:control+enter`, `kb:control+numpadEnter`, `kb:shift+enter`, `kb:shift+numpadEnter`, `kb:control+shift+enter`, `kb:control+shift+numpadEnter`, `kb:alt+enter`, `kb:alt+numpadEnter`, `kb:applications`, `kb:shift+applications`, `kb:shift+f10` | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeTreeInterceptor | `disablePassThrough` | `kb:escape` | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeTreeInterceptor | `nextBrowseElement` | `ts(browse):flickDown` | Selecciona el siguiente tipo de elemento para la navegación táctil del modo exploración |
| BrowseModeTreeInterceptor | `prevBrowseElement` | `ts(browse):flickUp` | Selecciona el anterior tipo de elemento para la navegación táctil del modo exploración |
| BrowseModeTreeInterceptor | `nextSelectedElement` | `ts(browse):flickRight` | Va al siguiente elemento del tipo seleccionado en la navegación táctil del modo exploración |
| BrowseModeTreeInterceptor | `prevSelectedElement` | `ts(browse):flickLeft` | Va al anterior elemento del tipo seleccionado en la navegación táctil del modo exploración |
| BrowseModeDocumentTreeInterceptor | `activateLongDesc` | — | Muestra la descripción larga en esta posición si se encuentra una. |
| BrowseModeDocumentTreeInterceptor | `collapseOrExpandControl` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeDocumentTreeInterceptor | `tab` | `kb:tab` | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeDocumentTreeInterceptor | `shiftTab` | `kb:shift+tab` | (interno: deja pasar la tecla y anuncia el resultado) |
| BrowseModeDocumentTreeInterceptor | `moveToStartOfContainer` | `kb:shift+,` | Se mueve al comienzo de un elemento contenedor, tal como una lista o una tabla |
| BrowseModeDocumentTreeInterceptor | `movePastEndOfContainer` | `kb:,` | Se desplaza más allá del elemento contenedor, como en una lista o en una tabla |
| BrowseModeDocumentTreeInterceptor | `toggleScreenLayout` | `kb:NVDA+v` | Activa y desactiva si la disposición de la pantalla se conserva mientras se procesa el contenido del documento |
| BrowseModeDocumentTreeInterceptor | `toggleNativeAppSelectionMode` | `kb:NVDA+shift+f10` | Activa y desactiva el modo de selección nativa |

### 3.2 `cursorManager.py` — 35

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| CursorManager | `find` | `kb:NVDA+Control+f` | encontrar una cadena de texto desde la posición actual del cursor |
| CursorManager | `findNext` | `kb:NVDA+f3` | encontrar la siguiente aparición de la cadena de texto introducida previamente desde la posición actual del cursor |
| CursorManager | `findPrevious` | `kb:NVDA+shift+f3` | encontrar la aparición anterior de la cadena de texto previamente introducida desde la posición actual del cursor |
| CursorManager | `moveByPage_back` | `kb:pageUp` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByPage_forward` | `kb:pageDown` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByCharacter_back` | `kb:leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByCharacter_forward` | `kb:rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByWord_back` | `kb:control+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByWord_forward` | `kb:control+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByLine_back` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByLine_forward` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveBySentence_back` | `kb:alt+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveBySentence_forward` | `kb:alt+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByParagraph_back` | `kb:control+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `moveByParagraph_forward` | `kb:control+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `startOfLine` | `kb:home` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `endOfLine` | `kb:end` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `topOfDocument` | `kb:control+home` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `bottomOfDocument` | `kb:control+end` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectCharacter_forward` | `kb:shift+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectCharacter_back` | `kb:shift+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectWord_forward` | `kb:shift+control+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectWord_back` | `kb:shift+control+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectLine_forward` | `kb:shift+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectLine_back` | `kb:shift+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectPage_forward` | `kb:shift+pageDown` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectPage_back` | `kb:shift+pageUp` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectParagraph_forward` | `kb:shift+control+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectParagraph_back` | `kb:shift+control+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectToBeginningOfLine` | `kb:shift+home` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectToEndOfLine` | `kb:shift+end` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectToTopOfDocument` | `kb:shift+control+home` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectToBottomOfDocument` | `kb:shift+control+end` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `selectAll` | `kb:control+a` | (interno: deja pasar la tecla y anuncia el resultado) |
| CursorManager | `copyToClipboard` | `kb:control+c` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.3 `documentBase.py` — 13

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| DocumentWithTableNavigation | `nextRow` | `kb:control+alt+downArrow` | se mueve a la siguiente fila de la tabla |
| DocumentWithTableNavigation | `previousRow` | `kb:control+alt+upArrow` | se mueve a la fila anterior de la tabla |
| DocumentWithTableNavigation | `nextColumn` | `kb:control+alt+rightArrow` | se mueve a la siguiente columna de la tabla |
| DocumentWithTableNavigation | `previousColumn` | `kb:control+alt+leftArrow` | se mueve a la columna anterior de la tabla |
| DocumentWithTableNavigation | `firstRow` | `kb:control+alt+pageUp` | se mueve a la primera fila de la tabla |
| DocumentWithTableNavigation | `lastRow` | `kb:control+alt+pageDown` | se mueve a la última fila de la tabla |
| DocumentWithTableNavigation | `firstColumn` | `kb:control+alt+home` | se mueve a la primera columna de la tabla |
| DocumentWithTableNavigation | `lastColumn` | `kb:control+alt+end` | se mueve a la última columna de la tabla |
| DocumentWithTableNavigation | `sayAllRow` | `kb:NVDA+control+alt+rightArrow` | Lee la fila horizontalmente desde la celda actual hacia la derecha hasta la última celda de la fila. |
| DocumentWithTableNavigation | `sayAllColumn` | `kb:NVDA+control+alt+downArrow` | Lee la columna verticalmente desde la celda actual hacia abajo hasta la última celda de la columna. |
| DocumentWithTableNavigation | `speakRow` | `kb:NVDA+control+alt+leftArrow` | Lee la fila actual horizontalmente de izquierda a derecha sin mover el cursor del sistema. |
| DocumentWithTableNavigation | `speakColumn` | `kb:NVDA+control+alt+upArrow` | Lee la columna actual verticalmente de arriba a abajo sin mover el cursor del sistema. |
| DocumentWithTableNavigation | `toggleIncludeLayoutTables` | — | Activa y desactiva la inclusión de tablas de diseño en modo exploración |

### 3.4 `editableText.py` — 14

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| EditableText | `caret_newLine` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_moveByLine` | `kb:upArrow`, `kb:downArrow`, `kb:pageUp`, `kb:pageDown`, `kb:control+home`, `kb:control+end` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_moveByCharacter` | `kb:leftArrow`, `kb:rightArrow`, `kb:home`, `kb:end` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_moveByWord` | `kb:control+leftArrow`, `kb:control+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_moveByParagraph` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_previousSentence` | `kb:alt+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_nextSentence` | `kb:alt+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_backspaceCharacter` | `kb:backspace`, `kb:shift+backspace` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_backspaceWord` | `kb:control+backspace` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_deleteCharacter` | `kb:delete`, `kb:shift+delete`, `kb:numpadDelete`, `kb:shift+numpadDelete` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_deleteWord` | `kb:control+delete`, `kb:control+numpadDelete` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_previousParagraph` | `kb:control+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableText | `caret_nextParagraph` | `kb:control+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| EditableTextWithoutAutoSelectDetection | `caret_changeSelection` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.5 `NVDAObjects\behaviors.py` — 9

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| EnhancedTermTypedCharSupport | `flush_queuedChars` | `kb:enter`, `kb:numpadEnter`, `kb:tab`, `kb:control+c`, `kb:control+d`, `kb:control+pause` | Flushes the typed word buffer and queue of typedCharacter events if present. Since these gestures clear the current word/line, we should flush the queue to avoid erroneously reporting these chars. |
| RowWithFakeNavigation | `moveToNextColumn` | `kb:control+alt+rightArrow` | Mueve el navegador de objetos a la siguiente columna |
| RowWithFakeNavigation | `moveToPreviousColumn` | `kb:control+alt+leftArrow` | Mueve el navegador de objetos a la columna anterior |
| RowWithFakeNavigation | `moveToNextRow` | `kb:control+alt+downArrow` | Mueve el navegador de objetos y el foco a la siguiente fila |
| RowWithFakeNavigation | `moveToPreviousRow` | `kb:control+alt+upArrow` | Mueve el navegador de objetos y el foco a la fila anterior |
| RowWithFakeNavigation | `moveToFirstColumn` | `kb:Control+Alt+Home` | Mueve el navegador de objetos a la primera columna |
| RowWithFakeNavigation | `moveToLastColumn` | `kb:Control+Alt+End` | Mueve el navegador de objetos a la última columna |
| RowWithFakeNavigation | `moveToFirstRow` | `kb:Control+Alt+PageUp` | Mueve el navegador de objetos y el foco a la primera fila |
| RowWithFakeNavigation | `moveToLastRow` | `kb:Control+Alt+PageDown` | Mueve el navegador de objetos y el foco a la última fila |

### 3.6 `contentRecog\recogUi.py` — 6

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| RecogResultNVDAObject | `activatePosition` | `kb:enter`, `kb:space` | Activa el texto en el cursor si es posible |
| RecogResultNVDAObject | `exit` | `kb:escape` | Descarta el resultado del reconocimiento |
| RecogResultNVDAObject | `find` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| RecogResultNVDAObject | `findNext` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| RecogResultNVDAObject | `findPrevious` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| RefreshableRecogResultNVDAObject | `refreshBuffer` | `kb:NVDA+f5` | Refrescar el resultado del reconocimiento |

### 3.7 `virtualBuffers\__init__.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| VirtualBuffer | `refreshBuffer` | `kb:NVDA+f5` | Refresca el contenido del documento |

### 3.8 `mathPres\__init__.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| MathInteractionNVDAObject | `exit` | `kb:escape` | Sale de la interacción matemática |

### 3.9 `mathPres\MathCAT\MathCAT.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| MathCATInteraction | `rawdataToClip` | `kb:control+c` | Copiar el foco de navegación al portapapeles |

### 3.10 `NVDAObjects\IAccessible\SysMonthCal32.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| SysMonthCal32 | `valueChange` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.11 `NVDAObjects\IAccessible\msOffice.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| SDMSymbols | `selectGraphic` | `kb:downArrow`, `kb:upArrow`, `kb:home`, `kb:end`, `kb:leftArrow`, `kb:rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.12 `NVDAObjects\IAccessible\mscandui.py` — 4

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| MSCandUI21_candidateMenuItem | `nextItem` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| MSCandUI21_candidateMenuItem | `previousItem` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| MSCandUI21_candidateMenuItem | `changePage` | `kb:pageDown`, `kb:pageUp`, `kb:leftArrow`, `kb:rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| MSCandUI21_candidateMenuItem | `activate` | `kb:space`, `kb:enter` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.13 `NVDAObjects\IAccessible\qt.py` — 2

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| TableCell | `nextColumn` | `kb:tab`, `kb:rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| TableCell | `previousColumn` | `kb:shift+tab`, `kb:leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.14 `NVDAObjects\IAccessible\sysListView32.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| GroupingItem | `collapseOrExpand` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.15 `NVDAObjects\IAccessible\winword.py` — 10

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| WordDocument | `setColumnHeader` | `kb:NVDA+shift+c` | Establecer encabezado de columna. Pulsando una vez se establecerá esta celda como la primera cabecera de columna para cualquier celda más abajo y a la derecha de ella dentro de esta tabla. Pulsando dos veces olvidará la cabecera de columna actual para esta celda. |
| WordDocument | `setRowHeader` | `kb:NVDA+shift+r` | Establecer encabezado de fila. Si se pulsa una vez, esta celda se convertirá en el primer encabezado de fila para cualquier celda situada por debajo y a la derecha de ella dentro de esta tabla. Pulsando dos veces se olvidará el encabezado de fila actual para esta celda. |
| WordDocument | `reportCurrentComment` | `kb:NVDA+alt+c` | Anuncia el texto del comentario donde esté colocado el cursor del sistema.Si se pulsa dos veces, presenta la información en modo exploración. |
| WordDocument | `nextRow` | `kb:control+alt+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `previousRow` | `kb:control+alt+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `nextColumn` | `kb:control+alt+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `previousColumn` | `kb:control+alt+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `nextParagraph` | `kb:control+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `previousParagraph` | `kb:control+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `updateBrailleAndReviewPosition` | `kb:control+v`, `kb:control+x`, `kb:control+y`, `kb:control+z`, `kb:alt+backspace` | Helper script to update braille and review position. |

### 3.16 `NVDAObjects\UIA\excel.py` — 2

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| ExcelCell | `showCellAppearanceInfo` | `kb:NVDA+o` | Muestra un mensaje explorable enumerando información acerca del aspecto de una celda tal como los colores de contorno y de relleno, rotación y tamaño |
| ExcelCell | `reportComment` | `kb:NVDA+alt+c` | Anuncia la nota o hilo de comentarios en la celda actual |

### 3.17 `NVDAObjects\UIA\wordDocument.py` — 4

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| WordBrowseModeDocument | `tab` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `reportCurrentComment` | `kb:NVDA+alt+c` | Anuncia el texto del comentario donde esté colocado el cursor del sistema. Si se pulsa dos veces, presenta la información en un mensaje explorable |
| WordDocument | `setColumnHeader` | `kb:NVDA+shift+c` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `setRowHeader` | `kb:NVDA+shift+r` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.18 `NVDAObjects\window\_msOfficeChart.py` — 7

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| OfficeChartElementBase | `reportCurrentChartElementWithExtraInfo` | `kb:NVDA+d` | (interno: deja pasar la tecla y anuncia el resultado) |
| OfficeChartElementBase | `reportCurrentChartElementColor` | `kb:NVDA+f` | (interno: deja pasar la tecla y anuncia el resultado) |
| OfficeChartElementList | `previousElement` | `kb(laptop):leftArrow`, `kb(desktop):leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| OfficeChartElementList | `nextElement` | `kb(laptop):rightArrow`, `kb(desktop):rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| OfficeChart | `activatePosition` | `kb:enter`, `kb(desktop):numpadEnter`, `kb:space` | Conmuta entre el modo exploración y el modo foco. Cuando esté en el modo foco, las teclas pasarán directamente a través de la aplicación, permitiéndote interactuar directamente con un control. Cuando esté en modo exploración, puedes navegar por el documento con el cursor, teclas rápidas de navegación, etc. |
| OfficeChart | `disablePassThrough` | `kb:escape` | (interno: deja pasar la tecla y anuncia el resultado) |
| OfficeChartElementSeries | `reportColor` | `kb:NVDA+5` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.19 `NVDAObjects\window\excel.py` — 31

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| ExcelBrowseModeTreeInterceptor | `moveLeft` | `kb:leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `moveRight` | `kb:rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `moveUp` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `moveDown` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `startOfColumn` | `kb:control+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `startOfRow` | `kb:control+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `endOfRow` | `kb:control+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `endOfColumn` | `kb:control+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelBrowseModeTreeInterceptor | `elementsList` | — | Enumera varios tipos de elementos en esta hoja de cálculo |
| ExcelWorksheet | `changeActiveCell` | `kb:tab`, `kb:shift+tab`, `kb:enter`, `kb:numpadEnter`, `kb:shift+enter`, `kb:shift+numpadEnter` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelWorksheet | `changeSelection` | `kb:upArrow`, `kb:downArrow`, `kb:leftArrow`, `kb:rightArrow`, `kb:control+upArrow`, `kb:control+downArrow`, `kb:control+leftArrow`, `kb:control+rightArrow`, `kb:home`, `kb:end`, `kb:control+home`, `kb:control+end`, `kb:shift+upArrow`, `kb:shift+downArrow`, `kb:shift+leftArrow`, `kb:shift+rightArrow`, `kb:shift+control+upArrow`, `kb:shift+control+downArrow`, `kb:shift+control+leftArrow`, `kb:shift+control+rightArrow`, `kb:shift+home`, `kb:shift+end`, `kb:shift+control+home`, `kb:shift+control+end`, `kb:shift+space`, `kb:control+space`, `kb:pageUp`, `kb:pageDown`, `kb:shift+pageUp`, `kb:shift+pageDown`, `kb:alt+pageUp`, `kb:alt+pageDown`, `kb:alt+shift+pageUp`, `kb:alt+shift+pageDown`, `kb:control+shift+8`, `kb:control+pageUp`, `kb:control+pageDown`, `kb:control+a`, `kb:control+v`, `kb:shift+f11`, `kb:control+y`, `kb:control+z`, `kb:alt+backspace` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelWorksheet | `toggleBold` | `kb:control+b`, `kb:control+2` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelWorksheet | `toggleItalic` | `kb:control+i`, `kb:control+3` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelWorksheet | `toggleUnderline` | `kb:control+u`, `kb:control+4` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelWorksheet | `toggleStrikethrough` | `kb:control+5` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelCell | `openDropdown` | `kb:alt+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelCell | `setColumnHeader` | `kb:NVDA+shift+c` | Establece la celda actual como el comienzo de encabezado de columna. Pulsando una vez establecerá esta celda como el primer encabezado de columna para cualquier celda inferior y a la derecha dentro de esta región. Pulsando dos veces olvidará el actual encabezado de columna para esta celda. |
| ExcelCell | `setRowHeader` | `kb:NVDA+shift+r` | Establece la celda actual como inicio del encabezado de fila. Pulsando una vez se establecerá esta celda como la primera cabecera de fila para cualquier celda inferior y a la derecha de ella dentro de esta región. Pulsando dos veces se olvidará la cabecera de fila actual para esta celda. |
| ExcelCell | `reportComment` | `kb:NVDA+alt+c` | Anuncia la nota en la celda actual. Si se pulsa dos veces, presenta la información en modo exploración |
| ExcelCell | `editComment` | `kb:shift+f2` | Abrir el diálogo de edición de notas |
| ExcelDropdown | `selectionChange` | `kb:downArrow`, `kb:upArrow`, `kb:leftArrow`, `kb:rightArrow`, `kb:home`, `kb:end` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelDropdown | `closeDropdown` | `kb:escape`, `kb:enter`, `kb:space` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControl | `doAction` | `kb:enter`, `kb:space`, `kb(desktop):numpadEnter` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlListBox | `moveUp` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlListBox | `moveDown` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlDropDown | `moveUp` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlDropDown | `moveDown` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlScrollBar | `moveUpSmall` | `kb:upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlScrollBar | `moveDownSmall` | `kb:downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlScrollBar | `moveUpLarge` | `kb:pageUp` | (interno: deja pasar la tecla y anuncia el resultado) |
| ExcelFormControlScrollBar | `moveDownLarge` | `kb:pageDown` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.20 `NVDAObjects\window\winConsole.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| WinConsole | `caret_backspaceCharacter` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| WinConsole | `close` | `kb:alt+f4` | (interno: deja pasar la tecla y anuncia el resultado) |
| WinConsole | `flush_queuedChars` | `kb:enter`, `kb:numpadEnter`, `kb:tab`, `kb:control+c`, `kb:control+d`, `kb:control+pause` | Flushes the typed word buffer if present. Since these gestures clear the current word/line, we should flush the current words buffer to avoid erroneously reporting words that already have been processed. |

### 3.21 `NVDAObjects\window\winword.py` — 21

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| WordDocumentTreeInterceptor | `nextRow` | `kb:control+alt+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocumentTreeInterceptor | `previousRow` | `kb:control+alt+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocumentTreeInterceptor | `nextColumn` | `kb:control+alt+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocumentTreeInterceptor | `previousColumn` | `kb:control+alt+leftArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleBold` | `kb:control+b` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleItalic` | `kb:control+i`, `kb:control+shift+i` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleUnderline` | `kb:control+u`, `kb:control+shift+u`, `kb:control+shift+d` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleCaps` | `kb:control+shift+k` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `changeCase` | `kb:shift+f3` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleAlignment` | `kb:control+l`, `kb:control+e`, `kb:control+r`, `kb:control+j` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `changeParagraphLeftIndent` | `kb:control+m`, `kb:control+shift+m`, `kb:control+t`, `kb:control+shift+t` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleSuperscriptSubscript` | `kb:control+=`, `kb:control+shift+=` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `moveParagraphDown` | `kb:alt+shift+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `moveParagraphUp` | `kb:alt+shift+upArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `increaseDecreaseOutlineLevel` | `kb:alt+shift+rightArrow`, `kb:alt+shift+leftArrow`, `kb:control+shift+n`, `kb:control+alt+1`, `kb:control+alt+2`, `kb:control+alt+3` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `increaseDecreaseFontSize` | `kb:control+[`, `kb:control+]`, `kb:control+shift+,`, `kb:control+shift+.` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `toggleDisplayNonprintingCharacters` | `kb:control+shift+8` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `tab` | `kb:tab`, `kb:shift+tab` | A script for the tab key which: * if in a table, announces the newly selected cell or new cell where the caret is, or * If not in a table, announces the distance of the caret from the left edge of the document, and any remaining text on that line. |
| WordDocument | `changeLineSpacing` | `kb:control+1`, `kb:control+2`, `kb:control+5` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `changeParagraphSpacing` | `kb:control+0` | (interno: deja pasar la tecla y anuncia el resultado) |
| WordDocument | `caret_moveByCell` | `kb:alt+home`, `kb:alt+end`, `kb:alt+pageUp`, `kb:alt+pageDown` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.22 `appModules\azardi20.py` — 2

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AzardiTreeViewItem | `enter` | `kb:enter` | (interno: deja pasar la tecla y anuncia el resultado) |
| AzardiTreeViewItem | `contextMenu` | `kb:applications` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.23 `appModules\calc.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| Display | `executeAndRead` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.24 `appModules\calculator.py` — 2

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AppModule | `calculatorResult` | `_calculatorResultGestures` | (interno: deja pasar la tecla y anuncia el resultado) |
| AppModule | `doNotAnnounceCalculatorResults` | `[f'kb:{i}' for i in range(10)][f'kb:numLockNumpad{i}' for i in range(10)]` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.25 `appModules\eclipse.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| EclipseTextArea | `closeAutocompleter` | `kb:enter`, `kb:escape` | (interno: deja pasar la tecla y anuncia el resultado) |
| EclipseTextArea | `readDocumentation` | `kb:nvda+d` | Intenta leer la documentación del elemento de autocompletado seleccionado. |
| EclipseTextArea | `completeInstruction` | `kb:tab` | Performs a standard autocompletion with the `TAB` key, like in other editors. |

### 3.26 `appModules\excel.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrokenDataValidationSysListView32 | `close` | `kb:enter`, `kb:space`, `kb:escape` | Correct focus when the user presses Enter, Space or Escape. |

### 3.27 `appModules\foobar2000.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AppModule | `reportRemainingTime` | `kb:control+shift+r` | Anuncia el tiempo restante de la pista actualmente en reproducción, si hay alguna |
| AppModule | `reportElapsedTime` | `kb:control+shift+e` | Anuncia el tiempo transcurrido de la pista actualmente en reproducción, si hay alguna |
| AppModule | `reportTotalTime` | `kb:control+shift+t` | Anuncia la duración de la pista actualmente en reproducción, si hay alguna |

### 3.28 `appModules\kindle.py` — 6

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BookPageViewTreeInterceptor | `moveByPage_forward` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BookPageViewTreeInterceptor | `moveByPage_back` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BookPageViewTreeInterceptor | `showSelectionOptions` | `kb:control+c`, `kb:applications`, `kb:shift+f10` | Muestra opciones relativas al texto seleccionado o al texto en el cursor |
| BookPageViewTreeInterceptor | `find` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BookPageViewTreeInterceptor | `findNext` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| BookPageViewTreeInterceptor | `findPrevious` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.29 `appModules\logonui.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| XPPasswordField | `changeUser` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.30 `appModules\miranda32.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AppModule | `readMessage` | `[f'kb:NVDA+control+{n}' for n in range(1, MessageHistoryLength + 1)]` | Mostrar uno de los mensajes recientes |
| mirandaIMContactList | `changeItem` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| mirandaIMButton | `doDefaultAction` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.31 `appModules\nvda.py` — 5

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| NvdaPythonConsoleUIOutputClear | `clearOutput` | `kb:control+l` | Borrar el panel de salida |
| NvdaPythonConsoleUIOutputCtrl | `moveToNextResult` | `kb:alt+downArrow` | Se mueve al resultado siguiente |
| NvdaPythonConsoleUIOutputCtrl | `moveToPrevResult` | `kb:alt+upArrow` | Se mueve al resultado anterior |
| NvdaPythonConsoleUIOutputCtrl | `selectToResultEnd` | `kb:alt+downArrow+shift` | Seleccionar hasta el final del resultado actual |
| NvdaPythonConsoleUIOutputCtrl | `selectToResultStart` | `kb:alt+shift+upArrow` | Seleccionar hasta el comienzo del resultado actual |

### 3.32 `appModules\outlook.py` — 5

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| REListBox20W_CheckBox | `checkbox` | `kb:space` | (interno: deja pasar la tecla y anuncia el resultado) |
| AddressBookEntry | `moveByEntry` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| ContactEditField | `hide` | `kb:escape` | The auto-complete list is getting closed, set focus back to the edit field. |
| MailViewerTreeInterceptor | `tab` | `kb:tab`, `kb:shift+tab` | (interno: deja pasar la tecla y anuncia el resultado) |
| BaseOutlookWordDocument | `tab` | `kb:tab`, `kb:shift+tab` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.33 `appModules\poedit.py` — 4

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AppModule | `reportAutoCommentsWindow` | `kb:control+shift+a` | Anuncia cualquier nota para los traductores. Si se pulsa dos veces, presenta las notas en modo exploración |
| AppModule | `reportCommentsWindow` | `kb:control+shift+c` | Anuncia cualquier comentario en la ventana comentarios. Si se pulsa dos veces, presenta el comentario en modo exploración |
| AppModule | `reportOldSourceText` | `kb:control+shift+o` | Anunciar el texto fuente anterior, si lo hay. Si se pulsa dos veces, presenta el texto en modo Exploración |
| AppModule | `reportTranslationWarning` | `kb:control+shift+w` | Informa de un problema de traducción, si lo hay. Si se pulsa dos veces, presenta la advertencia en modo exploración |

### 3.34 `appModules\powerpnt.py` — 8

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| DocumentWindow | `selectionChange` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| PpObject | `selectionChange` | `kb:escape` | (interno: deja pasar la tecla y anuncia el resultado) |
| Shape | `moveHorizontal` | `kb:leftArrow`, `kb:rightArrow`, `kb:shift+leftArrow`, `kb:shift+rightArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| Shape | `moveVertical` | `kb:upArrow`, `kb:downArrow`, `kb:shift+upArrow`, `kb:shift+downArrow` | (interno: deja pasar la tecla y anuncia el resultado) |
| ChartShape | `enterChart` | `kb:enter`, `kb:space` | (interno: deja pasar la tecla y anuncia el resultado) |
| TextFrame | `caret_backspaceCharacter` | — | (interno: deja pasar la tecla y anuncia el resultado) |
| SlideShowTreeInterceptor | `toggleNotesMode` | — | Alterna entre anunciar las notas del orador o el contenido de la diapositiva actual. Esto no cambia lo que es visible en la pantalla, sino sólo lo que puede leer el usuario con NVDA |
| SlideShowTreeInterceptor | `slideChange` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.35 `appModules\soffice.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| SymphonyDocument | `changeTextFormatting` | `kb:control+0`, `kb:control+1`, `kb:control+2`, `kb:control+3`, `kb:control+4`, `kb:control+5`, `kb:control+b`, `kb:control+d`, `kb:control+i`, `kb:control+u`, `kb:control+shift+p`, `kb:control+shift+b`, `kb:control+l`, `kb:control+e`, `kb:control+r`, `kb:control+j`, `kb:control+[`, `kb:control+]` | Reset time and enable announcement of newly changed state/text of toolbar items related to text formatting. See also :func:`SymphonyButton.event_stateChange` and :func:`SymphonyText.event_valueChange`. |

### 3.36 `appModules\vipmud.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| AppModule | `readMessage` | `[f'kb:control+{n}' for n in range(1, historyLength + 1)]` | Mostrar uno de los mensajes recientes |

### 3.37 `appModules\winamp.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| winampMainWindow | `shuffleToggle` | `kb:s` | (interno: deja pasar la tecla y anuncia el resultado) |
| winampMainWindow | `repeatToggle` | `kb:r` | (interno: deja pasar la tecla y anuncia el resultado) |
| winampPlaylistEditor | `changeItem` | — | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.38 `appModules\winword.py` — 3

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| WinwordWordDocument | `changeViewType` | `kb:control+alt+o`, `kb:control+alt+p` | (interno: deja pasar la tecla y anuncia el resultado) |
| WinwordWordDocument | `toggleChangeTracking` | `kb:control+shift+e` | (interno: deja pasar la tecla y anuncia el resultado) |
| WinwordWordDocument | `collapseOrExpandHeading` | `kb:alt+shift+-`, `kb:alt+shift+=`, `kb:alt+shift+numpadPlus`, `kb:alt+shift+numpadMinus`, `kb:numLock+shift+alt+numpadPlus`, `kb:numLock+shift+alt+numpadMinus` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.39 `brailleDisplayDrivers\alva.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrailleDisplayDriver | `toggleHidKeyboardInput` | `br(alva):t1+spEnter` | Conmuta la simulación de teclado HID |

### 3.40 `brailleDisplayDrivers\eurobraille\driver.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrailleDisplayDriver | `toggleHidKeyboardInput` | `br(eurobraille.esytime):l1+joystick1Down`, `br(eurobraille):switch1Left+joystick1Down`, `br(eurobraille.esytime):l8+joystick1Down`, `br(eurobraille):switch1Right+joystick1Down` | Conmuta la simulación de teclado HID |

### 3.41 `brailleDisplayDrivers\freedomScientific.py` — 2

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrailleDisplayDriver | `toggleLeftWizWheelAction` | `br(freedomScientific):leftWizWheelPress` | (interno: deja pasar la tecla y anuncia el resultado) |
| BrailleDisplayDriver | `toggleRightWizWheelAction` | `br(freedomScientific):rightWizWheelPress` | (interno: deja pasar la tecla y anuncia el resultado) |

### 3.42 `brailleDisplayDrivers\handyTech.py` — 1

| Clase | Script | Gestos | Descripción (es) / comportamiento |
|---|---|---|---|
| BrailleDisplayDriver | `toggleBrailleInput` | `br(handytech):space+b1+b3+b4`, `br(handytech):leftSpace+b1+b3+b4`, `br(handytech):rightSpace+b1+b3+b4`, `br(handytech.easybraille):left+b1+b3+b4`, `br(handytech.easybraille):right+b1+b3+b4`, `br(handytech):space+dot1+dot2+dot7` | Conmutar entrada braille |

## 4. Opciones de configuración (`configSpec.py`, esquema v25)

Formato: clave = tipo(valor por defecto) · etiqueta del diálogo (es) cuando se pudo deducir del código de `gui/` · comentario del código. `featureFlag` = opción de tres estados (Predeterminado/Activado/Desactivado) con comportamiento por defecto indicado. `__many__` = subsección repetida por sintetizador, pantalla braille o proveedor de visión.

### [(raíz)] — 1 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
|  | `schemaVersion` | `integer(min=0, default={latestSchemaVersion})` |  | NVDA Configuration File |

### [general] — 7 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| general | `language` | `string(default="Windows")` | Idioma de NVDA (requiere reiniciar): |  |
| general | `saveConfigurationOnExit` | `boolean(default=True)` | Guardar configuración al salir de NVDA |  |
| general | `askToExit` | `boolean(default=true)` | Mostrar opciones cuando se salga de NVDA |  |
| general | `playStartAndExitSounds` | `boolean(default=true)` | Reproducir sonidos al iniciar o al salir de NVDA |  |
| general | `loggingLevel` | `string(default="INFO")` |  | possible log levels are DEBUG_UNREDACTED, DEBUG, IO, DEBUGWARNING, INFO and OFF |
| general | `showWelcomeDialogAtStartup` | `boolean(default=true)` | Mostrar este diálogo cuando se inicie NVDA |  |
| general | `preventDisplayTurningOff` | `boolean(default=true)` | Evitar que la pantalla se apague durante leer todo o leer con el braille |  |

### [speech] — 21 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| speech | `synth` | `string(default=auto)` |  | The synthesizer to use |
| speech | `symbolLevel` | `integer(default=100)` | Nivel de Puntuación y símbolos: | symbolLevel: One of the characterProcessing.SymbolLevel values. |
| speech | `trustVoiceLanguage` | `boolean(default=true)` | Confiar en el idioma de la voz al procesar caracteres y símbolos |  |
| speech | `unicodeNormalization` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| speech | `reportNormalizedForCharacterNavigation` | `boolean(default=true)` | Anunciar 'Normalizado' al navegar por caracteres |  |
| speech | `symbolDictionaries` | `string_list(default=list("cldr"))` |  |  |
| speech | `speechDictionaries` | `string_list(default=list("default", "voice"))` |  |  |
| speech | `beepSpeechModePitch` | `integer(default=10000,min=50,max=11025)` |  |  |
| speech | `autoLanguageSwitching` | `boolean(default=true)` | Cambio automático de idioma (cuando esté soportado) |  |
| speech | `autoDialectSwitching` | `boolean(default=false)` | Cambio automático de dialecto (cuando esté soportado) |  |
| speech | `reportLanguage` | `boolean(default=false)` | Indicar cambios de idioma durante la lectura |  |
| speech | `reportNotSupportedLanguage` | `option("speech", "beep", "off", default="speech")` | Retraso en las descripciones para caracteres con el movimiento del cursor |  |
| speech | `delayedCharacterDescriptions` | `boolean(default=false)` | Retraso en las descripciones para caracteres con el movimiento del cursor |  |
| speech | `excludedSpeechModes` | `int_list(default=list())` | Modos disponibles en la orden recorrer modos de voz: |  |
| speech | `trimLeadingSilence` | `boolean(default=true)` | Recortar los silencios en el audio de la voz |  |
| speech | `useWASAPIForSAPI4` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| speech | `sayAllReadingUnit` | `featureFlag(optionsEnum="SayAllReadingUnitFlag", behaviorOfDefault="sentence")` |  |  |
| speech/__many__ | `capPitchChange` | `integer(default=30,min=-100,max=100)` |  |  |
| speech/__many__ | `sayCapForCapitals` | `boolean(default=false)` |  |  |
| speech/__many__ | `beepForCapitals` | `boolean(default=false)` |  |  |
| speech/__many__ | `useSpellingFunctionality` | `boolean(default=true)` |  |  |

### [audio] — 8 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| audio | `outputDevice` | `string(default=default)` | Dispositivo de salida de audio: |  |
| audio | `audioDuckingMode` | `integer(default=0)` | Modo de Atenuación de audio: |  |
| audio | `soundVolumeFollowsVoice` | `boolean(default=false)` | El volumen de los sonidos de NVDA sigue al volumen de la voz |  |
| audio | `soundVolume` | `integer(default=100, min=0, max=100)` | Volumen de los sonidos de NVDA |  |
| audio | `audioAwakeTime` | `integer(default=30, min=0, max=3600)` |  |  |
| audio | `whiteNoiseVolume` | `integer(default=0, min=0, max=100)` |  |  |
| audio | `soundSplitState` | `integer(default=0)` | Modo separación de sonido: |  |
| audio | `includedSoundSplitModes` | `int_list(default=list(0, 2, 3))` | Modos disponibles en la orden 'Recorrer modo de separación de sonido': |  |

### [braille] — 30 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| braille | `display` | `string(default=auto)` |  |  |
| braille | `mode` | `option("followCursors", "speechOutput", default="followCursors")` |  |  |
| braille | `translationTable` | `string(default=auto)` |  |  |
| braille | `inputTable` | `string(default=auto)` |  |  |
| braille | `expandAtCursor` | `boolean(default=true)` | Expandir a braille computerizado para la palabra en el cursor |  |
| braille | `showCursor` | `boolean(default=true)` | Mostrar cursor |  |
| braille | `cursorBlink` | `boolean(default=true)` | Parpadeo del cursor |  |
| braille | `cursorBlinkRate` | `integer(default=500,min=200,max=2000)` | Velocidad del parpadeo del cursor (en MS) |  |
| braille | `cursorShapeFocus` | `integer(default=192,min=1,max=255)` | Forma del cursor para el foco: |  |
| braille | `cursorShapeReview` | `integer(default=128,min=1,max=255)` | Forma del cursor para la revisión: |  |
| braille | `showMessages` | `integer(0, 2, default=1)` | Mostrar mensajes | How braille display will show messages 0: Disabled, 1: Use timeout, 2: Show indefinitely |
| braille | `messageTimeout` | `integer(default=4, min=1, max=20)` | Duración de mensajes (en seg) | Timeout after the message will disappear from braille display |
| braille | `autoScrollRate` | `float(default=10, min=1, max=20)` |  | Rate for automatic scroll (cells/sec) |
| braille | `tetherTo` | `option("auto", "focus", "review", default="auto")` | Braille sigue: |  |
| braille | `reviewRoutingMovesSystemCaret` | `featureFlag(optionsEnum="ReviewRoutingMovesSystemCaretFlag", behaviorOfDefault="NEVER")` |  |  |
| braille | `readByParagraph` | `boolean(default=false)` | Leer por párrafos |  |
| braille | `paragraphStartMarker` | `option("", " ", "¶", default="")` | Marca de comienzo de párrafo: |  |
| braille | `wordWrap` | `boolean(default=true)` |  | Deprecated in 2026.3 |
| braille | `textWrap` | `featureFlag(optionsEnum="BrailleTextWrapFlag", behaviorOfDefault="AT_WORD_BOUNDARIES")` |  |  |
| braille | `unicodeNormalization` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="disabled")` |  |  |
| braille | `useChineseWordSegmentation` | `boolean(default=True)` | Utilizar segmentación de palabras en Chino |  |
| braille | `focusContextPresentation` | `option("changedContext", "fill", "scroll", default="changedContext")` | Presentación de contexto para el foco: |  |
| braille | `interruptSpeechWhileScrolling` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| braille | `speakOnRouting` | `boolean(default=false)` | Verbalizar carácter al enrutar el cursor en el texto |  |
| braille | `speakOnNavigatingByUnit` | `boolean(default=false)` | Verbalizar al navegar por líneas o párrafos |  |
| braille | `showSelection` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| braille | `reportLiveRegions` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| braille | `fontFormattingDisplay` | `featureFlag(optionsEnum="FontFormattingBrailleModeFlag", behaviorOfDefault="LIBLOUIS")` |  |  |
| braille/auto | `excludedDisplays` | `string_list(default=list("dotPad"))` |  |  |
| braille/__many__ | `port` | `string(default="")` |  |  |

### [vision] — 1 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| vision/__many__ | `enabled` | `boolean(default=false)` |  |  |

### [magnifier] — 10 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| magnifier | `enabled` | `boolean(default=false)` |  |  |
| magnifier | `magnifiedView` | `string(default="fullscreen")` |  |  |
| magnifier | `zoom` | `integer(min=100, max=5000, default=200)` |  |  |
| magnifier | `filter` | `string(default="normal")` |  |  |
| magnifier | `followMouse` | `boolean(default=True)` |  |  |
| magnifier | `followSystemFocus` | `boolean(default=True)` |  |  |
| magnifier | `followReviewCursor` | `boolean(default=True)` |  |  |
| magnifier | `followNavigatorObject` | `boolean(default=True)` |  |  |
| magnifier | `panStep` | `integer(min=1, max=100, default=10)` |  |  |
| magnifier | `fullscreenMode` | `string(default="center")` |  |  |

### [presentation] — 14 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| presentation | `reportKeyboardShortcuts` | `boolean(default=true)` | Anunciar teclas de atajo de los objetos |  |
| presentation | `reportObjectPositionInformation` | `boolean(default=true)` | Anunciar información de posición del objeto |  |
| presentation | `guessObjectPositionInformationWhenUnavailable` | `boolean(default=false)` |  |  |
| presentation | `reportMultiSelect` | `boolean(default=false)` | Anunciar cuando los objetos admiten selección múltiple |  |
| presentation | `reportTooltips` | `boolean(default=false)` | Anunciar consejos |  |
| presentation | `reportHelpBalloons` | `boolean(default=true)` | Anunciar notificaciones |  |
| presentation | `reportObjectDescriptions` | `boolean(default=True)` | Anunciar descripciones de objeto |  |
| presentation | `reportDynamicContentChanges` | `boolean(default=True)` | Anunciar cambios de contenido dinámico |  |
| presentation | `reportAutoSuggestionsWithSound` | `boolean(default=True)` | Reproducir un sonido al aparecer una autosugerencia |  |
| presentation/progressBarUpdates | `reportBackgroundProgressBars` | `boolean(default=false)` | Anunciar barras de progreso en segundo plano |  |
| presentation/progressBarUpdates | `progressBarOutputMode` | `string(default="beep")` | Salida de la barra de progreso: | output modes are beep, speak, both, or off |
| presentation/progressBarUpdates | `speechPercentageInterval` | `integer(default=10)` |  |  |
| presentation/progressBarUpdates | `beepPercentageInterval` | `integer(default=1)` |  |  |
| presentation/progressBarUpdates | `beepMinHZ` | `integer(default=110)` |  |  |

### [mouse] — 12 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| mouse | `enableMouseTracking` | `boolean(default=True) #must be true for any of the other settings to work` | Habilitar seguimiento del Ratón |  |
| mouse | `mouseTextUnit` | `string(default="paragraph")` | Unidad de resolución de texto: |  |
| mouse | `reportObjectRoleOnMouseEnter` | `boolean(default=False)` | Anunciar objeto cuando el ratón entre en él |  |
| mouse | `audioCoordinatesOnMouseMove` | `boolean(default=False)` | Reproducir audio cuando se mueva el ratón |  |
| mouse | `audioCoordinates_detectBrightness` | `boolean(default=False)` | El brillo controla el volúmen en las coordenadas del audio |  |
| mouse | `audioCoordinates_blurFactor` | `integer(default=3)` |  |  |
| mouse | `audioCoordinates_minVolume` | `float(default=0.1)` |  |  |
| mouse | `audioCoordinates_maxVolume` | `float(default=1.0)` |  |  |
| mouse | `audioCoordinates_minPitch` | `integer(default=220)` |  |  |
| mouse | `audioCoordinates_maxPitch` | `integer(default=880)` |  |  |
| mouse | `reportMouseShapeChanges` | `boolean(default=false)` | Anunciar cambios en la forma del ratón |  |
| mouse | `ignoreInjectedMouseInput` | `boolean(default=false)` | Ignorar entrada del ratón desde otras aplicaciones |  |

### [speechViewer] — 7 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| speechViewer | `showSpeechViewerAtStartup` | `boolean(default=false)` |  |  |
| speechViewer | `autoPositionWindow` | `boolean(default=True)` |  |  |
| speechViewer | `x` | `integer()` |  | Values for positioning the window. Defaults are not used. They should not be read if autoPositionWindow is Tru |
| speechViewer | `y` | `integer()` |  |  |
| speechViewer | `width` | `integer()` |  |  |
| speechViewer | `height` | `integer()` |  |  |
| speechViewer | `displays` | `string_list()` |  |  |

### [brailleViewer] — 8 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| brailleViewer | `showBrailleViewerAtStartup` | `boolean(default=false)` |  |  |
| brailleViewer | `shouldHoverRouteToCell` | `boolean(default=false)` |  |  |
| brailleViewer | `secondsOfHoverToActivate` | `float(min=0.0, default=1.0)` |  |  |
| brailleViewer | `defaultCellCount` | `integer(min=20, max=160, default=40)` |  | Devices with 40 cells are quite common. |
| brailleViewer | `autoPositionWindow` | `boolean(default=True)` |  |  |
| brailleViewer | `x` | `integer()` |  | Values for positioning the window. Defaults are not used. They should not be read if autoPositionWindow is Tru |
| brailleViewer | `y` | `integer()` |  |  |
| brailleViewer | `displays` | `string_list()` |  |  |

### [keyboard] — 12 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| keyboard | `NVDAModifierKeys` | `integer(1, 7, default=6)` | Seleccionar Teclas Modificadoras de NVDA | NVDAModifierKeys: Integer value combining single-bit value: 1: CapsLock 2: NumpadInsert 4: ExtendedInsert Defa |
| keyboard | `keyboardLayout` | `string(default="desktop")` | Disposición del teclado: |  |
| keyboard | `speakTypedCharacters` | `integer(default=1,min=0,max=2)` | Verbalizar caracteres al escribir: | 0: Off, 1: Only in edit controls, 2: Always |
| keyboard | `speakTypedWords` | `integer(default=0,min=0,max=2)` | Verbalizar palabras al escribir: | 0: Off, 1: Only in edit controls, 2: Always |
| keyboard | `beepForLowercaseWithCapslock` | `boolean(default=true)` | Pitar si se teclean letras minúsculas cuando el Bloqueo de Mayúsculas esté activado |  |
| keyboard | `speakCommandKeys` | `boolean(default=false)` | Verbalizar teclas de órdenes |  |
| keyboard | `speechInterruptForCharacters` | `boolean(default=true)` | Interrupción de voz para caracteres escritos |  |
| keyboard | `speechInterruptForEnter` | `boolean(default=true)` | Interrupción de voz para la tecla INTRO |  |
| keyboard | `allowSkimReadingInSayAll` | `boolean(default=False)` | Permitir Lectura Superficial en Verbalizar Todo |  |
| keyboard | `alertForSpellingErrors` | `boolean(default=True)` | Reproducir sonido para errores ortográficos mientras se escribe |  |
| keyboard | `handleInjectedKeys` | `boolean(default=true)` | Manejar teclas desde otras aplicaciones |  |
| keyboard | `multiPressTimeout` | `integer(default=500, min=100, max=20000)` | Tiempo de espera para la pulsación de varias teclas (ms): |  |

### [virtualBuffers] — 14 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| virtualBuffers | `maxLineLength` | `integer(default=100)` | Máximo de caracteres en una línea |  |
| virtualBuffers | `linesPerPage` | `integer(default=25)` | número de líneas por página |  |
| virtualBuffers | `useScreenLayout` | `boolean(default=True)` | Utilizar diseño de pantalla (cuando esté soportado) |  |
| virtualBuffers | `autoPassThroughOnFocusChange` | `boolean(default=true)` | Modo Foco automático para cambios del foco |  |
| virtualBuffers | `autoPassThroughOnCaretMove` | `boolean(default=false)` | Modo foco automático para el movimiento del cursor |  |
| virtualBuffers | `passThroughAudioIndication` | `boolean(default=true)` | Indicación Audible de los modos foco y exploración |  |
| virtualBuffers | `autoSayAllOnPageLoad` | `boolean(default=true)` | Verbalizar Todo automáticamente al cargar la página |  |
| virtualBuffers | `trapNonCommandGestures` | `boolean(default=true)` | Capturar todo lo que no sean órdenes de gestos para que no alcance el documento |  |
| virtualBuffers | `enableOnPageLoad` | `boolean(default=true)` | Activar el modo Exploración al cargar la página |  |
| virtualBuffers | `loadChromiumVBufOnBusyState` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| virtualBuffers | `textParagraphRegex` | `string(default="{configDefaults.DEFAULT_TEXT_PARAGRAPH_REGEX}")` | Expresión regular para la navegación de párrafos de texto |  |
| virtualBuffers | `browseModeTouchNavigationElements` | `string_list(default=list("heading", "link", "formField", "list", "table"))` | Elementos de navegación táctil: | Element types available for cycling in browse touch mode. |
| virtualBuffers | `findHistory` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |
| virtualBuffers | `nativeSelectionMode` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="disabled")` |  |  |

### [touch] — 3 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| touch | `enabled` | `boolean(default=true)` | Habilitar soporte de interacción táctil |  |
| touch | `touchTyping` | `boolean(default=False)` | Modo escritura Táctil |  |
| touch | `edgeGestures` | `boolean(default=False)` | Activar gestos de límite |  |

### [documentFormatting] — 39 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| documentFormatting | `detectFormatAfterCursor` | `boolean(default=false)` | Anunciar cambios de formato después del cursor (puede causar un retraso) | These settings affect what information is reported when you navigate to text where the formatting  or placemen |
| documentFormatting | `reportFontName` | `boolean(default=false)` | Nombre de la fuente |  |
| documentFormatting | `reportFontSize` | `boolean(default=false)` | Tamaño de la fuente |  |
| documentFormatting | `fontAttributeReporting` | `integer(0, 3, default=0)` | Atributos de la fuente | 0: Off, 1: Speech, 2: Braille, 3: Speech and Braille |
| documentFormatting | `reportRevisions` | `boolean(default=true)` | Revisiones del Editor |  |
| documentFormatting | `reportEmphasis` | `boolean(default=false)` | Énfasis |  |
| documentFormatting | `reportHighlight` | `boolean(default=true)` | Texto resaltado (marcado) |  |
| documentFormatting | `reportSuperscriptsAndSubscripts` | `boolean(default=false)` | Superíndices y subíndices |  |
| documentFormatting | `reportColor` | `boolean(default=False)` | Colores |  |
| documentFormatting | `reportTransparentColor` | `boolean(default=False)` | Anunciar valores de transparencia de color |  |
| documentFormatting | `reportAlignment` | `boolean(default=false)` | Alineación |  |
| documentFormatting | `reportLineSpacing` | `boolean(default=false)` | espaciado de línea |  |
| documentFormatting | `reportStyle` | `boolean(default=false)` | Estilo |  |
| documentFormatting | `reportSpellingErrors2` | `integer(min=0, max=7, default=1)` | Reproducir sonido para errores ortográficos mientras se escribe | Bitwise combination of none, some or all values of ReportSpellingErrors 1: Speech, 2: Sound, 4: Braille |
| documentFormatting | `reportPage` | `boolean(default=true)` | Páginas |  |
| documentFormatting | `reportLineNumber` | `boolean(default=False)` | Números de línea |  |
| documentFormatting | `reportLineIndentation` | `integer(0, 3, default=0)` | Anunciado de sangría de línea: | 0: Off, 1: Speech, 2: Tones, 3: Both Speech and Tones |
| documentFormatting | `ignoreBlankLinesForRLI` | `boolean(default=False)` | Ignorar líneas en blanco para el anunciado de sangría de líneas |  |
| documentFormatting | `indentToneDuration` | `integer(min=10, max=2000, default=40)` | Duración del tono para sangría (ms): | Duration of indentation beeps, in milliseconds |
| documentFormatting | `reportParagraphIndentation` | `boolean(default=False)` | Sangría de párrafo |  |
| documentFormatting | `reportTables` | `boolean(default=true)` | Tablas |  |
| documentFormatting | `includeLayoutTables` | `boolean(default=False)` | Incluir tablas de diseño |  |
| documentFormatting | `reportTableHeaders` | `integer(0, 3, default=1)` | Cabeceras | 0: Off, 1: Rows and columns, 2: Rows, 3: Columns |
| documentFormatting | `reportTableCellCoords` | `boolean(default=True)` | Coordenadas de celdas |  |
| documentFormatting | `reportCellBorders` | `integer(0, 2, default=0)` | Bordes de celdas: | 0: Off, 1: style, 2: color and style |
| documentFormatting | `reportLinks` | `boolean(default=true)` | Enlaces |  |
| documentFormatting | `reportLinkType` | `boolean(default=true)` | Tipo de enlace |  |
| documentFormatting | `reportGraphics` | `boolean(default=True)` | Gráficos |  |
| documentFormatting | `reportComments` | `boolean(default=true)` | Comentarios |  |
| documentFormatting | `reportBookmarks` | `boolean(default=true)` | Marcadores |  |
| documentFormatting | `reportLists` | `boolean(default=true)` | Listas |  |
| documentFormatting | `reportHeadings` | `boolean(default=true)` | Encabezados |  |
| documentFormatting | `reportBlockQuotes` | `boolean(default=true)` | Citas |  |
| documentFormatting | `reportGroupings` | `boolean(default=true)` | Agrupaciones |  |
| documentFormatting | `reportLandmarks` | `boolean(default=true)` | Regiones ARIA y regiones |  |
| documentFormatting | `reportArticles` | `boolean(default=false)` | Artículos |  |
| documentFormatting | `reportFrames` | `boolean(default=true)` | Marcos |  |
| documentFormatting | `reportFigures` | `boolean(default=true)` | Figuras y rótulos |  |
| documentFormatting | `reportClickable` | `boolean(default=true)` | Cliqueable |  |

### [documentNavigation] — 3 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| documentNavigation | `initWordSegForUnusedLang` | `boolean(default=false)` |  | Hidden option to eagerly initialize Chinese word segmentation even when the current languages do not use it. |
| documentNavigation | `wordSegmentationStandard` | `featureFlag(optionsEnum="WordNavigationUnitFlag", behaviorOfDefault="Auto")` |  |  |
| documentNavigation | `paragraphStyle` | `featureFlag(optionsEnum="ParagraphNavigationFlag", behaviorOfDefault="application")` |  |  |

### [reviewCursor] — 4 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| reviewCursor | `simpleReviewMode` | `boolean(default=True)` | Modo de revisión simple |  |
| reviewCursor | `followFocus` | `boolean(default=True)` | Seguir al foco del sistema |  |
| reviewCursor | `followCaret` | `boolean(default=True)` | Seguir al Cursor del Sistema |  |
| reviewCursor | `followMouse` | `boolean(default=False)` | Seguir al cursor del ratón |  |

### [UIA] — 7 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| UIA | `enabled` | `boolean(default=true)` |  |  |
| UIA | `useInMSExcelWhenAvailable` | `boolean(default=false)` | Utilizar UI Automation para acceder a controles en hojas de cálculo de Microsoft Excel cuando esté disponible |  |
| UIA | `winConsoleImplementation` | `option("auto", "legacy", "UIA", default="auto")` |  |  |
| UIA | `eventRegistration` | `option("auto", "selective", "global", default="auto")` |  |  |
| UIA | `allowInChromium` | `integer(0, 3, default=0)` |  | 0:default, 1:Only when necessary, 2:yes, 3:no |
| UIA | `allowInMSWord` | `integer(0, 3, default=0)` |  | 0:default (where suitable), 1:Only when necessary, 2: where suitable, 3: always |
| UIA | `enhancedEventProcessing` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="enabled")` |  |  |

### [annotations] — 2 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| annotations | `reportDetails` | `boolean(default=true)` | Anunciar 'tiene detalles' para anotaciones estructuradas |  |
| annotations | `reportAriaDescription` | `boolean(default=true)` | Anunciar siempre aria-description |  |

### [terminals] — 4 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| terminals | `speakPasswords` | `boolean(default=false)` | Verbalizar contraseñas en todas las terminales mejoradas (puede mejorar el rendimiento) |  |
| terminals | `keyboardSupportInLegacy` | `boolean(default=True)` | Utilizar el soporte mejorado de caracteres al escribir en la Consola de Windows heredada cuando esté disponible |  |
| terminals | `diffAlgo` | `option("auto", "dmp", "difflib", default="auto")` |  |  |
| terminals | `wtStrategy` | `featureFlag(optionsEnum="WindowsTerminalStrategyFlag", behaviorOfDefault="diffing")` |  |  |

### [update] — 5 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| update | `autoCheck` | `boolean(default=true)` | Buscar automáticamente las actualizaciones de NVDA |  |
| update | `startupNotification` | `boolean(default=true)` | Avisar de una actualización pendiente al arrancar |  |
| update | `allowUsageStats` | `boolean(default=false)` | Permitir a NV Access recolectar estadísticas de uso de NVDA |  |
| update | `askedAllowUsageStats` | `boolean(default=false)` | Recordármelo más tarde |  |
| update | `serverURL` | `string(default="")` |  |  |

### [inputComposition] — 5 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| inputComposition | `autoReportAllCandidates` | `boolean(default=True)` | Anunciar automáticamente todos los candidatos disponibles |  |
| inputComposition | `announceSelectedCandidate` | `boolean(default=True)` | Anunciar candidato seleccionado |  |
| inputComposition | `alwaysIncludeShortCharacterDescriptionInCandidateName` | `boolean(default=True)` | Incluir siempre descripción corta de carácter cuando se anuncien candidatos |  |
| inputComposition | `reportReadingStringChanges` | `boolean(default=True)` | Anunciar cambios en la cadena de lectura |  |
| inputComposition | `reportCompositionStringChanges` | `boolean(default=True)` | Anunciar cambios en la cadena de composición |  |

### [debugLog] — 19 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| debugLog | `hwIo` | `boolean(default=false)` |  |  |
| debugLog | `MSAA` | `boolean(default=false)` |  |  |
| debugLog | `UIA` | `boolean(default=false)` |  |  |
| debugLog | `audioDucking` | `boolean(default=false)` |  |  |
| debugLog | `gui` | `boolean(default=false)` |  |  |
| debugLog | `louis` | `boolean(default=false)` |  |  |
| debugLog | `timeSinceInput` | `boolean(default=false)` |  |  |
| debugLog | `vision` | `boolean(default=false)` |  |  |
| debugLog | `speech` | `boolean(default=false)` |  |  |
| debugLog | `speechManager` | `boolean(default=false)` |  |  |
| debugLog | `synthDriver` | `boolean(default=false)` |  |  |
| debugLog | `nvwave` | `boolean(default=false)` |  |  |
| debugLog | `annotations` | `boolean(default=false)` |  |  |
| debugLog | `events` | `boolean(default=false)` |  |  |
| debugLog | `garbageHandler` | `boolean(default=false)` |  |  |
| debugLog | `remoteClient` | `boolean(default=False)` |  |  |
| debugLog | `externalPythonDependencies` | `boolean(default=False)` |  |  |
| debugLog | `bdDetect` | `boolean(default=False)` |  |  |
| debugLog | `magnifier` | `boolean(default=False)` |  |  |

### [uwpOcr] — 4 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| uwpOcr | `language` | `string(default="")` | Idioma de reconocimiento: |  |
| uwpOcr | `autoRefresh` | `boolean(default=false)` | Refrescar periódicamente el contenido reconocido |  |
| uwpOcr | `autoRefreshInterval` | `integer(default=1500, min=100)` |  |  |
| uwpOcr | `autoSayAllOnResult` | `boolean(default=false)` | Leer todo automáticamente en el resultado |  |

### [editableText] — 1 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| editableText | `caretMoveTimeoutMs` | `integer(min=0, max=2000, default=100)` | Tiempo de espera de movimiento del cursor del sistema (en ms) |  |

### [development] — 1 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| development | `enableScratchpadDir` | `boolean(default=false)` | Habilitar la carga de código personalizado desde el directorio Developer Scratchpad |  |

### [featureFlag] — 3 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| featureFlag | `cancelExpiredFocusSpeech` | `integer(0, 2, default=0)` | Intentar cancelar la voz para eventos del foco caducados: | 0:default, 1:yes, 2:no |
| featureFlag | `playErrorSound` | `integer(0, 2, default=0)` | Reproducir un sonido para los errores registrados: | 0: Only in test versions, 1: Yes, 2: No |
| featureFlag | `speechDictsUseModernRegex` | `featureFlag(optionsEnum="BoolFlag", behaviorOfDefault="disabled")` |  |  |

### [addonStore] — 4 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| addonStore | `automaticUpdates` | `option("notify", "update", "disabled", default="notify")` | Actualizaciones automáticas: |  |
| addonStore | `allowIncompatibleUpdates` | `boolean(default=false)` | Permitir que las actualizaciones automáticas instalen complementos incompatibles |  |
| addonStore | `baseServerURL` | `string(default="")` |  |  |
| addonStore | `defaultUpdateChannel` | `integer(0, 6, default=0)` | canal de actualizaciones predeterminado: | UpdateChannel values: same channel (default), any channel, do not update, stable, beta  dev, beta, dev |

### [remote] — 12 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| remote | `enabled` | `boolean(default=False)` |  |  |
| remote/connections | `lastConnected` | `string_list(default=list())` |  |  |
| remote/controlServer | `autoconnect` | `boolean(default=False)` |  |  |
| remote/controlServer | `selfHosted` | `boolean(default=False)` |  |  |
| remote/controlServer | `connectionMode` | `integer(default=0, min=0, max=1)` |  | 0: follower, 1: leader |
| remote/controlServer | `host` | `string(default="")` |  |  |
| remote/controlServer | `port` | `integer(default=6837)` |  |  |
| remote/controlServer | `key` | `string(default="")` |  |  |
| remote/seenMOTDs | `__many__` | `string(default="")` |  |  |
| remote/trustedCertificates | `__many__` | `string(default="")` |  |  |
| remote/ui | `confirmDisconnectAsFollower` | `boolean(default=True)` |  |  |
| remote/ui | `muteOnLocalControl` | `boolean(default=False)` |  |  |

### [math] — 68 claves

MathCAT (matemáticas). Se listan claves agrupadas por subsección:

- **math/speech**: `impairment`=option("LearningDisability", "Blindness", "LowVision", defau; `language`=string(default="en"); `verbosity`=option("Terse", "Medium", "Verbose", default="Medium"); `mathRate`=integer(default=100, min=10, max=100); `pauseFactor`=integer(default=100, min=0, max=1056); `speechSound`=option("None", "Beep", default="None"); `subjectArea`=string(default="General"); `chemistry`=option("SpellOut", "AsCompound", "Off", default="SpellOut"); `mathSpeak`=string(default="Verbose")
- **math/speech.speechOverrides**: `capitalLetters`=string(default=""); `leftParen`=string(default=""); `rightParen`=string(default="")
- **math/speech.ClearSpeak**: `capitalLetters`=string(default="Auto"); `absoluteValue`=string(default="Auto"); `fractions`=string(default="Auto"); `exponents`=string(default="Auto"); `roots`=string(default="Auto"); `functions`=string(default="Auto"); `trig`=string(default="Auto"); `log`=string(default="Auto"); `impliedTimes`=string(default="Auto"); `paren`=string(default="Auto"); `matrix`=string(default="Auto"); `multiLineLabel`=string(default="Auto"); `multiLineOverview`=string(default="Auto"); `multiLinePausesBetweenColumns`=string(default="Short"); `sets`=string(default="Auto"); `multSymbolX`=string(default="Auto"); `multSymbolDot`=string(default="Auto"); `triangleSymbol`=string(default="Auto"); `ellipses`=string(default="Auto"); `verticalLine`=string(default="Auto"); `setMemberSymbol`=string(default="Auto"); `prime`=string(default="Auto"); `combinationPermutation`=string(default="Auto"); `bar`=string(default="Auto")
- **math/__many__**: `speechStyle`=string(default="")
- **math/navigation**: `navMode`=option("Enhanced", "Simple", "Character", default="Enhanced"; `resetNavMode`=boolean(default=false); `overview`=boolean(default=false); `resetOverview`=boolean(default=true); `navVerbosity`=option("Terse", "Medium", "Verbose", default="Medium"); `autoZoomOut`=boolean(default=true); `copyAs`=option("MathML", "LaTeX", "ASCIIMath", "Speech", default="Ma
- **math/braille**: `brailleCode`=string(default="Auto"); `brailleNavHighlight`=option("Off", "FirstChar", "EndPoints", "All", default="EndP; `useSpacesAroundAllOperators`=boolean(default=false)
- **math/braille.nemeth**: `sansSerif`=string(default="⠠⠨"); `bold`=string(default="⠸"); `doubleStruck`=string(default="⠨"); `script`=string(default="⠈"); `italic`=string(default="⠨")
- **math/braille.UEB**: `startMode`=string(default="Grade2"); `useSpacesAroundAllOperators`=string(default=false); `doubleStruck`=string(default="⠈"); `fraktur`=string(default="⠈"); `sansSerif`=string(default="⠈⠼"); `greekVariant`=string(default="⠨")
- **math/braille.vietnam**: `useDropNumbers`=boolean(default=false); `doubleStruck`=string(default="⠈"); `fraktur`=string(default="⠈"); `sansSerif`=string(default="⠈⠼"); `greekVariant`=string(default="⠸")
- **math/braille.LaTeX**: `useShortName`=boolean(default=false)
- **math/other**: `decimalSeparators`=string(default="."); `blockSeparators`=string(default=", \u00a0\u202f"); `decimalSeparator`=string(default="Auto"); `useWordNativeMath`=boolean(default=false)

### [screenCurtain] — 3 claves

| Sección | Clave | Tipo (defecto) | Etiqueta GUI (es) | Nota |
|---|---|---|---|---|
| screenCurtain | `enabled` | `boolean(default=false)` |  |  |
| screenCurtain | `warnOnLoad` | `boolean(default=true)` |  |  |
| screenCurtain | `playToggleSounds` | `boolean(default=true)` |  |  |

## 5. Ajustes que no están en `configSpec.py` pero sí en NVDA

- **Ajustes de voz por sintetizador** (`synthDriverHandler.py`, se guardan en `[speech][<sintetizador>]`): Idioma, Voz, Variante, Velocidad, Aumento de velocidad (*rate boost*), Volumen, Tono, Entonación (*inflection*). Además, por sintetizador: cambio de tono para mayúsculas (`capPitchChange`, %), decir «mayúscula» antes de mayúsculas, pitido para mayúsculas y usar la función de deletreo. Todos forman el **anillo de ajustes del sintetizador** (NVDA+Ctrl+flechas; en portátil NVDA+Mayús+Ctrl+flechas), que también tiene «primer y último valor» (`firstValueSynthRing`/`lastValueSynthRing`, sin gesto).
- **Ajustes de la pantalla braille por controlador** (`[braille][<driver>]`): puerto y los ajustes propios de cada driver.
- **Proveedores de visión** (`[vision][<proveedor>]`): resaltado visual (resaltar foco, navegador y cursor de exploración, con colores) y cortina de pantalla.
- **Diccionarios de voz** (archivos `speechDicts/*.dic`): por defecto, por voz y temporal. Cada entrada: patrón, sustitución, comentario, «distinguir mayúsculas», tipo «En cualquier lugar», «Palabra completa», «Expresión regular» (más la opción `speechDictsUseModernRegex`).
- **Pronunciación de símbolos y puntuación** (`symbols-<idioma>.dic` del usuario): símbolo, sustitución, nivel (ninguno, algo, mucho, todo, carácter), preservar (nunca, siempre, solo si está por debajo del nivel). Diccionario CLDR de emojis activable (`toggleReportCLDR`).
- **Gestos de entrada** (`gestures.ini`): asignar, quitar, restaurar valores por defecto, buscar en el diálogo por nombre; captura de teclas emuladas («Teclas de sistema del teclado emuladas»: se puede asignar una tecla de NVDA para que envíe otra tecla de Windows).
- **Perfiles de configuración** (`profiles/*.ini`, `profileTriggers.ini`): manual o con disparador por aplicación (`app:<nombre>`) y por «Decir todo»; activación por gesto (cada perfil aparece en Gestos de entrada); desactivar temporalmente todos los disparadores (`toggleConfigProfileTriggers`); renombrar, borrar; ajustes que no se guardan en perfiles: idioma de NVDA, guardar al salir, gestos, diccionarios por defecto.
- **Ventanas guardadas**: posición y pantalla del visor de voz y del visor braille (`speechViewer`, `brailleViewer`); el visor braille admite «pasar el ratón para enrutar» (`shouldHoverRouteToCell`, `secondsOfHoverToActivate`).
- **Política del sistema**: `HKLM\SOFTWARE\NVDA` `forceSecureMode`, `serviceDebug`; clave `configInLocalAppData`; parámetros de línea de órdenes (verificados en `source/argsParsing.py`): `-q/--quit`, `-k/--check-running`, `-f/--log-file`, `-l/--log-level`, `-c/--config-path`, `--lang`, `-m/--minimal`, `-s/--secure`, `--disable-addons`, `--debug-logging`, `--no-logging`, `--no-sr-flag`, `--install`, `--install-silent`, `--enable-start-on-logon`, `--copy-portable-config`, `--create-portable`, `--create-portable-silent`, `--portable-path`, `--launcher`, `--ease-of-access`, `-n`, `-d`. (Lista tomada del Manual del usuario, sección «Command Line Options»; contrastar con `source/argsParsing.py`.)

## 6. Menú de NVDA (NVDA+N) y herramientas

Preferencias: Opciones…, Diccionarios de voz (por defecto, de voz, temporal), Pronunciación de puntuación/símbolos, Gestos de entrada, Perfiles de configuración, Tienda de complementos. Herramientas: Ver registro, Visor de voz, Visor braille, Consola de Python, Crear copia portátil, Herramienta de reparación de accesibilidad del sistema (COM Registration Fixing Tool), Recargar plugins. Ayuda: Manual del usuario, Referencia rápida de órdenes, Novedades, Sitio web de NV Access, Licencia, Colaboradores, Diálogo de bienvenida, Buscar actualización, Ayuda/formación/soporte, Tienda NV Access, Acerca de. Raíz: Donar, Guardar configuración, Revertir a la configuración guardada, Instalar actualización pendiente, Instalar NVDA, Salir (con diálogo de salida: salir, reiniciar, reiniciar sin complementos, reiniciar con registro de depuración, instalar actualización pendiente).

## 7. Funciones de NVDA que un clon suele pasar por alto (lista de verificación)

Comprobadas en el código o en el Manual del usuario de la copia local. Marcar en Tiresias cada una como hecha/no hecha.

1. **Pulsaciones múltiples** con significado distinto: 1× informa, 2× deletrea, 3× deletrea fonéticamente (línea, palabra, carácter, foco, título, barra de estado, selección, portapapeles). en `review_currentCharacter` 2× da la descripción o ejemplo del carácter y 3× su valor numérico decimal y hexadecimal; 2× en `dateTime` da la fecha; `title` 2× deletrea y 3× copia el título; `reportStatusLine` 3× copia la barra de estado; `navigatorObject_current` 3× copia nombre y valor del objeto; 2× en `reportFormatting` abre un mensaje navegable (`showFormattingAtCaret`).
2. **Modo de voz** de 4 estados (`speechMode`, NVDA+S): hablar, a petición (solo órdenes con `speakOnDemand`), pitidos, desactivada; con exclusión configurable de modos del ciclo (`excludedSpeechModes`).
3. **Modo dormir por aplicación** (NVDA+Mayús+S) y órdenes que siguen funcionando en él (`allowInSleepMode`).
4. **Ayuda de entrada** (NVDA+1) que anuncia el nombre y la categoría de cada gesto sin ejecutarlo, incluidos los gestos braille y táctiles.
5. **Pasar la siguiente tecla** (NVDA+F2) y **teclas de sistema emuladas** asignables.
6. **Mensajes navegables** (`ui.browseableMessage`): formato, destino de enlace (`reportLinkDestinationInWindow`), lo último dicho (2× NVDA+X), resumen de detalles.
7. **Barra de estado**: leer, deletrear, copiar, llevar el cursor de revisión (`readStatusLine`, `spellStatusLine`, `copyStatusLine`, `reviewCursorToStatusLine`).
8. **Ubicación**: dimensiones/posición del navegador y del cursor (NVDA+Supr del teclado numérico; 2× da la posición relativa), y `reportReviewCursorLocation`, `reportCaretLocation`, `reportFocusObjectLocation`.
9. **Revisión de texto**: ir al inicio/fin de la selección con el cursor de revisión (NVDA+Alt+Inicio/Fin), marcar inicio para copiar (NVDA+F9), ir a la marca (NVDA+Mayús+F9), copiar desde la marca (NVDA+F10; 2× copia sin formato extra), modo de revisión simple, tres modos de revisión (objeto, documento, pantalla) y leer símbolo actual (`review_currentSymbol`).
10. **Navegación de objetos en flujo** (`navigatorObject_nextInFlow`/`previousInFlow`, NVDA+3/9 del teclado numérico): recorrido lineal plano de la jerarquía.
11. **Mover el foco al navegador** (NVDA+Mayús+Menos) y 2× mover el cursor del sistema a la posición del cursor de revisión.
12. **Activar** el objeto navegador (NVDA+Intro del teclado numérico) y **clic con el ratón** sin mover el foco, bloquear botones (Mayús+Barra/Asterisco), rueda del ratón (4 órdenes sin gesto).
13. **Coordenadas de audio del ratón** con tono por altura y volumen por brillo de la imagen (`audioCoordinates_detectBrightness`), forma del puntero, objeto al entrar el ratón, resolución de texto bajo el ratón (carácter, palabra, línea, párrafo), ignorar ratón inyectado.
14. **Barras de progreso**: pitido, voz, ambos o apagado; intervalos; barras en segundo plano; frecuencia mínima.
15. **Audio**: atenuación (*ducking*: nunca, al hablar o sonidos, siempre — NVDA+Mayús+D, solo instalado), volumen de sonidos siguiendo a la voz, **tiempo de mantener el dispositivo despierto** (`audioAwakeTime`) y **ruido blanco** (`whiteNoiseVolume`) para que los dispositivos Bluetooth no corten la primera sílaba; recortar silencio inicial (`trimLeadingSilence`), WASAPI para SAPI4.
16. **Voz**: descripciones de caracteres diferidas (`delayedCharacterDescriptions`), anunciar «normalizado», «confiar en el idioma de la voz» para símbolos, informar del cambio de idioma y del idioma no soportado (voz/pitido/nada), cambio automático de dialecto, `reportCaretLanguage`.
17. **Teclado**: pitido al escribir minúsculas con Bloq Mayús, interrumpir con caracteres y con Intro, hojear en «decir todo» (*skim reading*: las flechas no detienen «decir todo», `allowSkimReadingInSayAll`), anunciar teclas de órdenes, sonido para errores ortográficos al escribir, manejar teclas inyectadas, tiempo de pulsación múltiple, 3 teclas NVDA elegibles (Insert, Insert numérico, Bloq Mayús) con doble pulsación que envía la tecla original.
18. **Presentación de objetos**: atajos, posición («3 de 7»), adivinar posición, selección múltiple, sugerencias (*tooltips*), notificaciones, descripciones, cambios de contenido dinámico (NVDA+5), sonido de autosugerencias.
19. **Modo exploración**: diseño de pantalla (NVDA+V), página de 25 líneas y 100 caracteres, «decir todo» al cargar, modo foco automático por foco y por cursor, indicación sonora de modos, capturar teclas que no son órdenes, desactivar la navegación por una letra (NVDA+Mayús+Espacio), **selección nativa** (NVDA+Mayús+F10), refrescar documento (NVDA+F5), saltar al inicio/fin del contenedor (coma, Mayús+coma), descripción larga (`activateLongDesc`), lista de elementos (NVDA+F7), buscar con historial (NVDA+Ctrl+F, NVDA+F3, NVDA+Mayús+F3), párrafo de texto por expresión regular (P), estilo de párrafo (`cycleParagraphStyle`: salto de línea simple o múltiple), elemento de rotor táctil configurable.
20. **Tablas**: Ctrl+Alt+flechas/Inicio/Fin/RePág/AvPág (primera/última fila y columna), leer fila/columna desde la celda (`sayAllRow`, `sayAllColumn`) y completa sin mover (`speakRow`, `speakColumn`), fijar encabezados de fila/columna en Word y Excel (NVDA+Mayús+C/R; 2× borra), incluir tablas de maquetación (`toggleIncludeLayoutTables`).
21. **Formato del documento**: 35 interruptores sin gesto asignado (uno por cada elemento de formato, incluidos bordes de celdas, revisiones, resaltado, superíndices, enlaces con tipo, clicables, figuras), indentación por voz/tonos/ambos con duración del tono, ignorar líneas en blanco, detectar formato después del cursor.
22. **Anotaciones**: «tiene detalles», `aria-description` siempre, resumen de detalles (NVDA+D) para comentarios y notas al pie.
23. **OCR de Windows**: reconocer navegador (NVDA+R), idioma, ciclo de idioma, refresco periódico con intervalo, «decir todo» tras el resultado; el resultado es un documento navegable con búsqueda y clic sobre el texto (Intro hace clic en la posición).
24. **Braille**: atar a foco/revisión/automático (NVDA+Ctrl+T), modo «salida de voz» (NVDA+Alt+T), desplazamiento automático (NVDA+Alt+K/J/L), leer por párrafo, marcador de inicio de párrafo, ajuste de palabras, presentación de contexto del foco (llenar/desplazar/solo cambios), mostrar selección, formas del cursor, parpadeo y su velocidad, mensajes (desactivados/con tiempo/indefinidos) y su tiempo, expandir a braille informático en el cursor, enrutado que mueve el cursor del sistema (nunca/solo con modo exploración/siempre), hablar al enrutar, hablar al navegar por línea o párrafo, atributos de fuente en braille (etiquetas o marcas liblouis), regiones vivas en braille, interrumpir la voz al desplazar, segmentación de palabras chinas, detección automática de pantallas con exclusiones, **entrada braille** con teclas modificadoras conmutables (Ctrl, Alt, Windows, NVDA y combinaciones con Mayúsculas), traducción de la palabra o del bloque (punto 7+8), borrar última celda, Intro, selección de rango braille, ir al foco, informar formato bajo la celda.
25. **Visión**: resaltado visual con colores por cursor, cortina de pantalla temporal (1×) o permanente (2×) con aviso al cargar y sonidos, **lupa** (`_magnifier/`: vistas pantalla completa, acoplada y lente, más modo «foco» *spotlight*; modo de pantalla completa centrado/bordes; filtros normal/escala de grises/invertido; seguimiento de ratón, foco, revisión y navegador; vista general de la pantalla NVDA+Mayús+L; mover el ratón a la vista; zoom 1×-50×).
26. **Gestión**: guardar (NVDA+Ctrl+C) o revertir (NVDA+Ctrl+R; 3× restaura valores de fábrica, verificado en `globalCommands.py`) la configuración, recargar plugins (NVDA+Ctrl+F3), información del módulo de aplicación (NVDA+Ctrl+F1, 2× copia), información de desarrollador del navegador (NVDA+F1), marcar registro y copiar (NVDA+Ctrl+Mayús+F1), abrir carpeta de configuración, consola de Python (NVDA+Ctrl+Z), herramienta de inspección wx, sonido para errores registrados.
27. **Entrada de composición (IME)**: anunciar todos los candidatos, candidato seleccionado, descripción corta del carácter, cambios en la cadena de lectura y composición.
28. **Terminales**: algoritmo de diferencias (difflib/DMP), hablar contraseñas, soporte de escritura mejorado en la consola heredada, estrategia para Windows Terminal (diferencias o notificaciones UIA).
29. **UIA avanzado**: registro selectivo/global de eventos, procesamiento mejorado de eventos, UIA en Excel/Word/Chromium (por defecto, solo si es necesario, sí, no), cancelar voz de focos caducados, tiempo de espera del movimiento del cursor (100 ms).
30. **Acceso remoto**: conectar/desconectar (NVDA+Alt+R), enviar teclas al equipo remoto (NVDA+Alt+Tab), enviar Ctrl+Alt+Supr, enviar portapapeles, copiar enlace, silenciar el remoto, modo líder/seguidor, servidor propio, certificados confiables, mensaje del día, confirmar desconexión, silenciar al controlar localmente.
31. **Tienda de complementos**: actualizaciones automáticas (notificar/actualizar/desactivadas), canal por defecto y por complemento (estable, beta, desarrollo, externo), permitir actualizaciones incompatibles, espejo (*mirror*) del servidor, reseñas, novedades por complemento, gestión de incompatibles.
32. **Matemáticas (MathCAT)**: interactuar (NVDA+Alt+M), estilo de habla (ClearSpeak, SimpleSpeak…), verbosidad, modos de navegación (enriquecido, simple, carácter), copiar como MathML/LaTeX/ASCIIMath/voz, código braille (Nemeth, UEB, CMU, etc.), resaltado de navegación en braille; 68 claves en `[math]`.
33. **Varios**: batería (NVDA+Mayús+B), fecha/hora (NVDA+F12), portapapeles (NVDA+C), primer plano (NVDA+B: lee la ventana completa), título (NVDA+T), destino de enlace (NVDA+K), idioma bajo el cursor, impedir el apagado de la pantalla durante «decir todo», diálogo de bienvenida, estadísticas de uso, sonidos de inicio y salida.
