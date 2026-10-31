# Arquitectura de Tiresias

Documento para desarrolladores. Describe cómo está organizado el código, cómo
fluyen los eventos y dónde tocar para ampliar el lector.

## 1. Visión general

Tiresias es un lector de pantalla para Windows escrito en Python 3.14 (64 bits).
Obtiene la información de las aplicaciones sobre todo con **UI Automation
(UIA)**; para algunas ventanas usa **MSAA/IAccessible2** o **Java Access
Bridge** (sección 19). No inyecta código en otros procesos.

```
src/
  tiresias.pyw            punto de entrada
  tiresias/
    core.py               arranque, hilos, bucle principal, apagado, reinicio
    queue_handler.py      cola de tareas del hilo del núcleo (y temporizadores)
    paths.py / log.py / i18n.py
    config/               configuración por capas y perfiles (JSON)
    extension_points.py   Action / Filter / Decider
    baseobject.py         propiedades automáticas, @script y gestos
    api.py                estado global: foco, primer plano, navegador, revisión
    events.py             cadena de eventos (complementos → app → modo exploración → objeto)
    presentation.py       qué se dice de un objeto o un texto
    review.py             cursor de revisión (objeto, documento, pantalla)
    a11y/                 cliente UIA, eventos UIA y WinEvent
    objects/              objetos accesibles (base, UIA, comportamientos, roles)
    textinfo/             rangos de texto (desplazamientos y UIA)
    browse/               modo exploración (búfer virtual y navegación rápida)
    mathpres/             matemáticas: MathML, LaTeX, OMML, voz, braille CMU y exploración
    input/                ganchos, teclas, gestos y gestor de entrada
    global_commands.py    órdenes globales
    speech/               API de voz, símbolos, diccionarios, lectura continua
    synth/                controladores de sintetizador (eSpeak NG, OneCore, SAPI 5, Piper)
    audio/                reproductor WASAPI/waveOut, tonos y temas, earcons, división, atenuación, mezclador
    braille/              liblouis y tablas, presentación, entrada braille, órdenes y controladores
    appmodules/           módulos de aplicación incorporados y su gestor
    plugins/              complementos globales
    addons.py             paquetes de complementos (data/addons)
    gui/                  interfaz wxPython (menú, opciones, diálogos, visores)
    ocr.py vision.py magnifier.py clipboard.py labels.py mouse.py typing_echo.py
    formatting.py         anuncio de cambios de formato (fuente, color, página...)
    remote/               acceso remoto compatible con NVDA (protocolo, TLS, servidor, sesiones)
                          y voz por Escritorio remoto (rdp*.py, sección 23)
    console_reader.py     lectura de la consola clásica con la API de consola
    coexist/              convivencia: en espera si NVDA, JAWS o Narrador están activos (sección 25)
data/                     todo lo que el lector necesita o genera (portable), también
                          los binarios de controller, rdp y eSpeak NG (sección 9)
controller/               código C e IDL de la API de control y build.py (binarios en data/controller)
rdp/                      código C del complemento de Escritorio remoto y build.py (binarios en data/rdp)
tools/                    utilidades de compilación
setup_cxfreeze.py         compilación
Tiresias.bat              menú de desarrollo
```

## 2. Hilos

| Hilo | Función |
|---|---|
| Principal | wxPython: menú, bandeja, diálogos. Nunca accede a UIA directamente salvo herramientas de desarrollo. |
| Núcleo (MTA) | Procesa la cola de `queue_handler`: eventos UIA, órdenes, voz. Toda la lógica de accesibilidad vive aquí. |
| Ganchos | Ganchos de bajo nivel de teclado/ratón y WinEvents con su bucle de mensajes. Solo decide si captura una tecla y encola. |
| Eventos UIA | Hilos internos de UIA: los manejadores COM solo encolan. |
| Sintetizadores y audio | Cada sintetizador tiene un hilo de síntesis y cada `WavePlayer` el suyo. |
| Vigilante | Detecta si el núcleo se bloquea (registra las pilas y corta la voz). Mientras el núcleo esté bloqueado, el gancho deja pasar todas las teclas. |

Regla de oro: **cualquier cosa que toque objetos accesibles se ejecuta en el
hilo del núcleo**. Desde otros hilos se usa `queue_handler.queueFunction(func, *args)`
o `queue_handler.callLater(ms, func)`. Desde el núcleo hacia la interfaz se usa
`gui.runOnGui(func)` (equivale a `wx.CallAfter`).

## 3. Flujo de una tecla

1. `input/hooks.py` recibe la tecla (gancho `WH_KEYBOARD_LL`).
2. `input/core.py` actualiza modificadores, reconoce la tecla Tiresias
   (Insert, Insert numérico o Bloq Mayús) y crea un `KeyboardGesture`
   con identificadores como `kb(desktop):tiresias+numpad8` y `kb:tiresias+numpad8`.
3. Busca la orden en la **cadena de resolución** (`InputManager.chain`), que el
   núcleo recalcula al cambiar el foco: complementos globales → módulo de la
   aplicación → modo exploración → objeto con foco → antecesores (solo órdenes
   con `canPropagate`) → órdenes globales.
4. Si hay orden: la tecla se captura y la orden se ejecuta en el núcleo. Las
   órdenes pueden reenviar la tecla con `gesture.send()`.
5. Si no hay orden: la tecla llega a la aplicación; si produce un carácter se
   genera el evento `typedCharacter` (eco de teclado).

El mapa de gestos del usuario (`data/config/gestures.json`) se consulta antes
que los gestos definidos en las clases. `ScriptableObject.getScript` mira por
niveles, cada uno con todos los identificadores del gesto: usuario, gestos de
instancia (`bindGesture`: mapas alternativos como el de JAWS, complementos) y
gestos de clase. Así un `kb:tiresias+pageUp` de instancia vence a un
`kb(desktop):tiresias+pageUp` de la clase.

**AltGr**: Alt derecha solo se trata como AltGr si el sistema acaba de mandar
su Control izquierdo falso (código de exploración `0x21D`); con distribuciones
sin AltGr es una Alt normal. **Modo dormir**: con la aplicación dormida
(`_SleepModeFilter` en la cadena) las teclas no anuncian nada (bloqueos,
teclas de órdenes, eco); `events.executeEvent` actualiza foco y primer plano
pero no ejecuta la cadena de eventos, y `mouse` no lee lo que hay bajo el ratón.

**Registro** (`log.py`): el archivo `logs/tiresias.log` se escribe en un hilo
propio (`QueueHandler`/`QueueListener`): escribir o rotar el archivo no bloquea
el núcleo ni el gancho. `log.flush()` espera a que llegue al disco (lo usa
`crash_log` ante un cierre inesperado) y `log.shutdown()` lo vacía y lo cierra
(reinicio de emergencia del vigilante); al salir normalmente lo hace `atexit`.

Las tres teclas Tiresias vienen activadas (`keyboard.useCapsLockAsModifier`
también es `True`, #11678). Dos pulsaciones seguidas sin otra tecla en medio
envían la tecla real con `_sendNativeModifier` (con la marca
`TIRESIAS_INJECTION_MARK`, que el gancho ignora); para Bloq Mayús además se
actualiza `_capsToggled` y se anuncia el estado.

**Ratón**: el gancho solo guarda la última posición y programa
`_processMouse` cada 80 ms en el núcleo; `mouse.handleMouseMove` mueve la
lupa, la forma del puntero y los tonos de coordenadas al momento. Con
`mouse.reportDelay` > 0 (#11898) la lectura (`mouse._reportAt`) se aplaza con
`queue_handler.callLater` hasta que el puntero lleva ese tiempo quieto
(`_onReportDelayElapsed` vuelve a programarse si hubo movimiento); el gancho no
espera nunca. Los tonos de coordenadas (`mouse.coordinateTone`, escritorio
virtual) también suenan al mover el objeto navegador
(`reviewCursor.audioCoordinatesOnNavigatorMove`,
`GlobalCommands._setNavigator`) y el cursor de revisión
(`reviewCursor.audioCoordinatesOnReviewMove`, `_reviewMove`/`_reviewTo`, con
el rectángulo del carácter o `pointAtStart`), #2559.

## 4. Flujo de un evento

1. UIA notifica (foco, cambio de nombre/valor/estado, notificación, región
   viva, menú, ventana abierta...) en `a11y/uia_handler.py`.
2. En el núcleo se crea el `UIAObject` (con propiedades cacheadas de la
   petición) y se aplican las **clases superpuestas**: `findOverlayClasses`
   del propio objeto, `chooseObjectClass` del módulo de aplicación y de los
   complementos globales.
3. `events.executeEvent(nombre, obj)` recorre la cadena:
   `GlobalPlugin.event_x(obj, nextHandler)` → `AppModule.event_x(obj, nextHandler)` →
   `TreeInterceptor.event_x(obj, nextHandler)` → `obj.event_x()`.
4. Para `gainFocus`, antes se actualiza el estado global (`api`), el primer
   plano, el módulo de aplicación activo (y los perfiles por aplicación), el
   interceptor (modo exploración) y la cadena de órdenes, y se anuncian los
   antecesores nuevos (diálogos, agrupaciones, listas...).
5. **Focos transitorios vacíos** (`events.isTransientContainerFocus`): un
   `gainFocus` en un contenedor genérico (panel, sección, agrupación,
   ventana) sin nombre ni valor, antecesor del foco actual y menos de
   `TRANSIENT_FOCUS_WINDOW` (1 s) después de él, se ignora. Aceptarlo
   descartaría la voz del elemento recién anunciado (su validador de foco
   deja de cumplirse) y el gestor reanudaría desde el principio lo que
   seguía sonando (el primer plano), sin decir nada nuevo. Si el foco
   anterior ha desaparecido o ya pasó el plazo, se acepta.
   Caso concreto en `appmodules/explorer.py`: el panel
   `Windows.UI.Input.InputSite.WindowClass` de Alt+Tab en Windows 11 (clase
   superpuesta `TaskSwitcherInputSite`, `shouldAllowFocusEvent = False`) y,
   con Alt pulsada, ni el primer plano «Conmutación de tareas» ni la lista
   «Aplicaciones en ejecución» se anuncian: solo la ventana elegida.

Las propiedades `_get_x` de los objetos se cachean durante un ciclo del núcleo
(`baseobject.invalidateCaches()` al final de cada ciclo).

## 5. Voz

`speech.speak(secuencia, priority=, origin=, isValid=)` recibe cadenas y
órdenes (`speech/commands.py`). Antes de enviar al sintetizador:

1. `filter_speechSequence` (secuencia completa; el manejador recibe `value`).
2. Idioma (`_LangState` en `speech/api.py`, con `speech/languages.py`): cambios explícitos
   (`LangChangeCommand`) y detección automática (`speech/langdetect.py`: guion
   Unicode y modelo propio de trigramas es/en/fr/de/it/pt, con margen mínimo);
   dialectos (`resolveSwitch`), anuncio del idioma (`reportLanguage`) e idioma
   no admitido por el sintetizador (`reportNotSupportedLanguage`).
3. Por cada cadena (`processText`): `filter_speechText`, entidades HTML,
   normalización Unicode, diccionarios (temporal, del perfil activo, de voz
   —se recarga solo si cambia la voz—, por defecto; tipos `anywhere`, `word`,
   `startOfWord`, `endOfWord`, `partOfWord`, `regex` y entradas desactivables),
   lectura alfanumérica, números (`speech/numbers.py`) y símbolos con la
   **tabla del idioma de lectura** (`symbols.getProcessor(lang)`; `es` y `en`
   en `data/symbols`). En los modos de números por dígitos, pares o tríos,
   `applyNumberMode(text, mode, language)` interpreta antes las cifras unidas
   por puntos o comas con las convenciones del idioma de lectura (decimal «,»
   y miles «.» salvo en `_DECIMAL_POINT_LANGUAGES`, como el inglés): los miles
   se quitan, el decimal se dice con su nombre y lo demás (versiones, IP) con
   el nombre de cada signo; así la voz nunca ve «1.5 0 0» y lo lee como decimal.
   El diccionario del perfil se guarda con `dictionaries.saveProfileDict(nombre, entradas)`
   en el archivo de ese perfil aunque el perfil activo haya cambiado.
4. `pre_speech` y, tras encolar, `pre_speechQueued(speechSequence, priority)`.

`SpeechManager` mantiene una cola por prioridad (`NOW` > `NEXT` > `NORMAL`).
Cada llamada a `speak` es un enunciado; se envían al sintetizador como mucho
dos (el segundo de la misma prioridad, para no dejar huecos) y el siguiente
sale al llegar al índice final del anterior. `NOW` corta lo de menor
prioridad, que se reanuda desde el último índice alcanzado (hay puntos de
reanudación entre frases). Cada enunciado puede llevar un validador
(`isValid`, o el contexto `speech.validWhile`): al cambiar el foco
(`api.post_focusChange`) se descarta lo que ya no es válido
(`cancelExpiredFocusSpeech`); la voz del foco usa `speech.focusValidator`.
Las llamadas, pitidos y sonidos intercalados se convierten en índices; los
cambios de prosodia e idioma se normalizan a estado absoluto
(`_normalizeForSynth`).

Historial: `speech.getHistory()` devuelve `HistoryEntry(time, text, origin)`;
el origen lo fija `speech.speechOrigin(origen)` o `speak(origin=...)`
(foco, notificación, escritura, mensaje, lectura continua, cursor, revisión,
cambio, remoto) y `exportHistory` lo guarda con tabuladores.

Otros módulos: `speech/sayall.py` (líneas, frases o párrafos, sin pausas con
`mergeWithoutPauses`, mayúsculas, tablas con `readTable`, `resume`,
`restart`, `skip`; velocidad propia de la lectura continua con `changeRate`
y `withRate`: según `sayAllRateMode` suma `sayAllRateOffset` o un cambio solo
de la lectura en curso con `RateCommand` en lo que envía, sin tocar los
ajustes del sintetizador ni los perfiles con disparador `sayAll`; el modo
`global` cambia la velocidad de la voz), `speech/voice_schemes.py` (voces por
contexto con `wrapContext`: caret, review, typing, message, menu y dialog,
con prosodia, `VoiceCommand` y `SymbolLevelCommand`; `objectVoiceContext`
decide menú o diálogo en `presentation.speakObject`; esquemas de voz y sonido
por atributo de texto, familia de color, tipo de control y estado, en el modo
exploración con `textDecoration`/`filterSuffix`/`controlSounds` y, con
`voiceSchemeEverywhere`, fuera de él con `objectContext`/`statesContext`
—`presentation._roleHandled`/`_stateHandled` omiten las palabras que
sustituye un sonido— y `decorateTextInfo` en el texto editable).
`VoiceCommand` lo consume `SpeechManager`: cambia de voz solo entre
enunciados (espera a que no haya nada enviado), conserva velocidad, tono y
volumen, vuelve a la voz normal al quedarse sin cola o al cancelar y, si el
usuario cambia la voz mientras tanto, la toma como normal;
`synth.saveCurrentSettings` guarda siempre la voz normal
(`speech.savedSynthSettings`). `SymbolLevelCommand` lo aplica
`_processSequence` cuando la llamada no fija un nivel. Colores (#8674):
`formatting.colorName(colorref, fmt)` añade valores RGB o hexadecimales según
`documentFormatting.colorFormat` (lo usan `describe`, los bordes de celda,
`appmodules/_office.colorName`, Word y Excel); `colorBaseName` da solo el
nombre. `speech/verbosity.py`
(niveles, orden de propiedades, plantillas por rol y mensajes de tutor que usa
`presentation.getObjectSpeech`), `speech/plugin.py` (complemento global
incorporado con las órdenes de voz y los enganches) y `speech/defaults.py`
(opciones nuevas registradas con `registerDefaults`). Interfaz:
`gui/speech_settings.py` (categorías Lectura de texto, Idioma de la voz, Voces y
esquemas, Verbosidad) y `gui/speech_dialogs.py` (alfabeto fonético, esquemas,
plantillas).
Los sintetizadores heredan de `synth.base.AudioSynthDriver`: solo tienen que
implementar `_synthesizeSegment(items, emit, isCancelled)` y producir PCM de 16
bits; la clase base gestiona hilo, cola, cancelación instantánea, índices,
volumen y división del sonido (todo el audio pasa por `audio/wave_player.py`).

Selección automática: `conf["speech"]["synth"] = "auto"` prueba
`synthPriority` (ibmtts → espeak → onecore → sapi5) y después el resto
(incluido `piper` si hay voces instaladas).

Fallos en plena sesión: `AudioSynthDriver` cuenta los errores seguidos y,
al segundo, notifica `synth.base.synthFailed`; además `synth._watchdog`
(cada 3 s en el núcleo) comprueba `isStalled(20)`. En ambos casos
`synth.fallbackFrom(nombre)` carga otro sintetizador sin cambiar la opción
guardada (`speech.synthFallback` lo desactiva). `speech.trimLeadingSilence`
recorta el silencio inicial de cada `speak()` en la clase base.

Sintetizador en espera: `synth.setStandby(bool)` (lo llama `coexist`) marca
la espera y, si el sintetizador tiene `releaseResources()`/`restoreResources()`,
los usa; `_trySet` deja en reposo el que se cargue en espera. Si
`restoreResources` falla, `fallbackFrom`. Eloquence (`data/addons/eloquence`)
lo implementa: en espera no hay proceso de 32 bits (ni siquiera al arrancar:
`__init__` consulta `synth.isStandby()`), los ajustes se guardan en
`_settings` y `_restartEngine` los aplica al reanudar (unos 150 ms).

Eloquence en hilos: los setters (núcleo) solo guardan el valor y marcan
`_dirty` (nada si el valor no cambia, `_requested`); `_applyPendingSettings`
lo aplica en el hilo de síntesis antes del siguiente trozo (también el cambio
de frecuencia y de reproductor, `_switchPlayer`). `_cancelSynthesis` (núcleo)
solo marca y despierta; `ECI_STOP` lo envía el hilo de síntesis. Los valores
de las variantes se leen al arrancar el motor (`_variantDefaults`). Cada trozo
empieza con la anotación de idioma de la voz y `` `vv100`` (la base no envía
los trozos de solo órdenes que restauran idioma y volumen).
`PipeClient.call` usa E/S superpuesta con tiempo de espera (`CALL_TIMEOUT`,
`SLOW_CALL_TIMEOUT`) y cerrojo con tiempo de espera; si vence, cierra la
conexión.

Puente de Eloquence (`synthDrivers/_eci_bridge.py`): `BridgeHost.start()`
lanza SIEMPRE un `rundll32` de 32 bits propio con
`StartHost <PID de Tiresias> tiresias_eci_<PID>_<n>` (número nuevo en cada
arranque) y `PipeClient.connect` comprueba con `GetNamedPipeServerProcessId`
que la tubería es de ese proceso; nunca se conecta a `\\.\pipe\ibmtts_host32`
(la del puente original, que usa el complemento IBMTTS de NVDA). La DLL es
ibmtts-host32-bridge (GPL) modificada: nombre de tubería por parámetro,
mutex, memoria compartida y eventos con ese prefijo (la respuesta de
`SET_BUFFER` trae sus nombres, `bufferObjectNames`) y cierre inmediato al
morir el proceso padre. Código y cambios en `data/addons/eloquence/bridge_src`
(`build.py` compila e instala la DLL; `LEEME_TIRESIAS.txt`). El complemento
Eloquence, con ese código, no está en el repositorio público: se distribuye
aparte en la tienda de complementos (ver `README.md`). Si el puente
muere, `_synthesizeSegment` lanza otro (`_reconnect`, unos 50 ms) y repite el
texto; si no puede, notifica `synthFailed` para cambiar de voz. Pruebas:
`tests/test_eloquence_puente.py` (y `cargo test --lib` en `bridge_src`).

## 6. Modo exploración

`browse/buffer.py` construye un búfer de texto plano a partir del árbol UIA del
documento con **una sola** llamada `BuildUpdatedCache(TreeScope_Subtree)`. Cada
elemento es un `Node` con su rango `[start, end)`; los fragmentos de texto
(`chunks`) apuntan al nodo que los generó. `browse/document.py` implementa el
cursor virtual, la navegación rápida (tabla `QUICK_NAV`), tablas, búsqueda,
lista de elementos, selección y copia, el paso a modo foco y la sincronización
con el foco real. Los cambios de estructura se vigilan con
`StructureChanged` y se reconstruye el búfer conservando la posición.

Para añadir una tecla de navegación rápida basta con añadir una entrada a
`QUICK_NAV` (tecla, identificador, singular, plural, predicado sobre `Node`).
Una tecla vacía crea las órdenes siguiente/anterior sin gesto (se asignan en
«Gestos de entrada»). Los tipos añadidos están en `browse/quicknav.py`; los
que dependen del cursor (vistazo, mismo/distinto estilo, párrafo vertical,
elemento de la lista actual) se resuelven con `dynamicPredicate`.

`BrowseModeDocument` se compone de mezclas:

| Módulo | Contenido |
|---|---|
| `browse/loader.py` (`BufferLoaderMixin`) | Construcción en un hilo propio (MTA) con `isReady` real, indicador de carga y actualización parcial: `onStructureChanged(element)` acumula los elementos cambiados y `VirtualBuffer.spliceSubtree` rehace solo su bloque (las tablas, enteras). |
| `browse/tables.py` (`TableNavigationMixin`) | Celdas combinadas (una celda ocupa todas sus coordenadas en `buffer.tables`), primera/última fila y columna, leer fila/columna, encabezados de `TableItemPattern` y fijados a mano. |
| `browse/extras.py` (`BrowseExtrasMixin`) | Frases, selección por párrafo/página, selección nativa, Tab desde el cursor, anclas, relaciones (`aria-details`, `aria-flowto`, `aria-controls`) y pila de posiciones, búsqueda, regiones vivas, `aria-sort`, inspector, navegación inteligente, lectura rápida, web flexible. |
| `browse/aria.py` | Etiquetas de `aria-haspopup`, `aria-current`, `aria-sort`, orientación, tipo de enlace y roles que el navegador solo da como tipo localizado (DPUB, figura, término...). |
| `browse/style.py` | Formato UIA de un desplazamiento del búfer (`BufferTextInfo.getFormatInfo`), estilo por párrafo y «vistazo». |
| `browse/html_details.py` | Detalles HTML/ARIA (foros 1.18 y 1.20): texto de las imágenes sin alternativo con su nombre de archivo (`graphicText`, atributo IA2 `src` por `a11y/ia2_bridge.py`, sección 19), descripción de grupos y regiones en `extraPrefix` (`containerDescription`, sin repetirla si está dentro), comillas de `<q>` como «cita»/«fin de cita» (`quoteSpeech`; los navegadores solo publican las comillas como hojas de texto), `abbr` de los encabezados (`headerAbbreviation`, `TableNavigationMixin._headerText`) y línea braille con aria-braillelabel (`brailleLabelLine`). `VirtualBuffer._emit` quita los guiones blandos. |
| `browse/textbuffer.py` | `TextPatternBuffer`: búfer de documentos con patrón Text (Word, Outlook, XAML). Conserva la longitud del texto del documento para traducir desplazamientos a rangos (`uiaRangeAt`, `offsetOfRange`). |
| `browse/flexweb.py` | Reglas por sitio (ocultar, inicio de lectura, orden visual) en `config/flexibleWeb.json`, y operaciones de orden de lectura propio (`readingOrder`, por documento o `*` para el sitio). |
| `browse/reading_order.py` | Orden de lectura a mano o con IA (foros 3.10): cada operación fija el orden de los hijos de un contenedor por claves estables (`elementKey`: tipo + id o principio del texto, con número de repetición). `VirtualBuffer.readingOrder` reordena los hijos en `_walk` antes del orden visual; `planMove` mueve un bloque (o el hijo del antecesor común que lo contiene). |

`browse.browseModeKind(obj)` decide el tipo: `tree` (web, Acrobat), `text`
(documentos de solo lectura con patrón Text) o `lazyText` (Word editable:
empieza en modo foco y construye el búfer al pedir el modo exploración).

Unidades de texto: `OffsetsTextInfo` tiene ganchos `_getLineOffsets`,
`_getParagraphOffsets` (según `documentNavigation.paragraphStyle`),
`_getSentenceOffsets` (frases dentro del párrafo) y `_getPageOffsets` (saltos
`\f` o bloques de `linesPerPage` líneas). `BufferTextInfo` une las líneas
cortadas por el búfer (`VirtualBuffer.paragraphBounds`). `UIATextInfo`
emula la unidad frase, que UIA no tiene.

**Líneas de contenedores (#3997, `browseMode.containerLinesApart`).** Si la
opción está activa, `configureBuffer` da al búfer `containerLabels`
(`BrowseModeDocument.containerLineLabels`: prefijo de entrada y etiqueta de
`CONTAINER_EXIT_LABELS`). Tras el recorrido, `VirtualBuffer._insertContainerLines`
inserta una línea al principio y otra al final de cada contenedor y desplaza
nodos y trozos: las líneas quedan dentro del rango del contenedor pero **sin
trozo** (`chunks`), y se guardan en `boundaryLines` (`boundaryAt`,
`boundaryContainersIn`). Consecuencias: `getRangeSpeech` las lee como texto
suelto y ya no antepone el prefijo al primer elemento; `_containerTransitions`
no repite la entrada/salida de un contenedor cuando la línea de origen o la de
destino es una de las suyas; `plainText` las quita al copiar; `contentOffset`
salta por encima (selección nativa, lectura rápida, celda actual de tabla);
`spliceSubtree` las sustituye en las actualizaciones parciales (el recuento
«lista con N» de un antecesor no rehecho se actualiza en la siguiente
reconstrucción completa). No se aplican a `TextPatternBuffer`.

**Filtro de nodos (`buffer.filter_node`).** Al final de `VirtualBuffer._makeNode`,
cuando el nodo ya tiene rol, nombre, estados y las etiquetas del usuario y de
la IA (pero todavía ni hijos ni texto), se pasa por el punto de extensión
`filter_node` con `buffer` y `controlType` (tipo de control UIA). Los
manejadores devuelven el nodo cambiado o `None` para dejarlo fuera con sus
descendientes; lo que cambien en `role` se respeta en `_walk` (un `GROUPING`
vuelto `BUTTON` pasa a ser atómico y emite su nombre; un `STATICTEXT` vuelto
`HEADING2` ocupa su propia línea y se anuncia como encabezado). El búfer lleva
`documentKey` (lo fija `configureBuffer`) para que los manejadores apliquen
reglas por sitio; se llama igual en los sub-búferes de las actualizaciones
parciales. Lo usa el complemento de tienda «Arreglo web»
(`complementos_tienda/arregloWeb`), que guarda por sitio nombres deducidos,
etiquetas de campos, pulsables como botones, encabezados por formato, región
principal y tablas de maquetación.

**Texto tras los enlaces (#11073, `browseMode.breakAfterLinks`).** Sin
disposición en pantalla, un enlace o control empieza línea y deja
`_pendingBreak`: el siguiente `_emit` pega a él la puntuación de cierre y
empieza otra línea para el resto. Con la opción desactivada, tras un enlace no
queda salto pendiente. `BrowseModeDocument.layoutSignature()` se guarda en el
búfer; si las opciones cambian, el documento se reconstruye al recibir el foco
o al guardar/cambiar de perfil.

**Coma y Mayúsculas+coma (#15732).** `nextContainerBoundary` lleva a la última
línea con texto (`containerLastLine`, que es la línea de salida si existe) o al
principio del contenedor **más interno** y, si ya se está allí, dice «final de
lista»/«principio de lista» sin moverse. El salto clásico fuera del contenedor
es `exitContainer` (orden `quickNavContainerExit`, sin gesto).

**Gecko con el puente MSAA→UIA (Thunderbird 102).** Sin proveedor UIA propio,
el puente del sistema convierte cada trozo de texto (`ROLE_SYSTEM_TEXT` sin
«solo lectura») en un `Edit` con valor modificable, y el cuerpo de los correos
se leía «Hola. edición». `objects.uia.looksLikeTextLeaf` (no enfocable,
activado, sin el estado MSAA enfocable ni valor) y `isMsaaProxyProvider`
(`ProviderDescription`, una vez por búfer en `VirtualBuffer._isGeckoMsaaProxy`)
los vuelven `STATICTEXT` en el búfer y en `UIAObject.role`. Firefox con UIA
propio da `Text` y no se toca. `controlSuffix` respeta además la plantilla del
rol (`verbosity.templateFor`): sin `{role}`/`{states}`/`{description}` no los dice.

### Textos que Chromium no publica (1.0.15)

La vista de control de Chromium omite los textos sueltos de un elemento con otros
hijos: `<li><span>listo</span><div>Tarea</div></li>` llega con un solo hijo. El
nombre del elemento sí los contiene, porque sale de su contenido, así que
`buffer.NameGaps` recorre el nombre a la vez que los hijos y emite lo que falta.
Si un hijo no aparece en el nombre (`aria-label`, espacios distintos) deja de
buscar, de modo que nunca inventa texto. Solo se aplica a los roles de
`NAME_FROM_CONTENT_ROLES`.

## 7. Configuración

`config.conf` es un gestor por capas: valores por defecto (`config/schema.py`),
configuración base (`data/config/config.json`, solo lo que difiere de los
valores por defecto) y perfiles (`data/config/profiles/*.json`) activados
manualmente o por disparadores (`app:<proceso>`, `sayAll`). Se lee y escribe
como un diccionario: `conf["speech"]["symbolLevel"] = 200`. Los complementos
registran su sección con `conf.registerDefaults("miSeccion", {...})`.

## 8. Puntos de extensión principales

| Punto | Dónde | Uso |
|---|---|---|
| `speech.pre_speech` | speech/api.py | Ver todo lo que se va a decir |
| `speech.filter_speechText` | speech/api.py | Reescribir texto antes de hablar |
| `speech.filter_speechSequence` | speech/api.py | Reescribir la secuencia completa (cadenas y órdenes) |
| `speech.pre_speechQueued` | speech/api.py | Saber qué se ha encolado y con qué prioridad |
| `speech.pre_speechCanceled` | speech/api.py | Saber cuándo se corta la voz |
| `api.post_focusChange` | api.py | Cambios de foco |
| `api.post_navigatorObjectChange`, `api.post_reviewMove` | api.py | Navegador y revisión |
| `events.post_event` | events.py | Cualquier evento procesado |
| `input.core.decide_executeGesture` | input/core.py | Interceptar teclas |
| `input.core.post_scriptExecuted` | input/core.py | Tras ejecutar una orden |
| `objects.behaviors.post_caretMoved` | objects/behaviors.py | Tras leer el cursor movido por una orden de edición (`obj`, `info`, `unit`), cuando la espera asíncrona del cursor ya ha terminado (también Word) |
| `config.post_configProfileSwitch`, `pre_configSave`, `post_configSave` | config | Configuración |
| `synth.synthChanged`, `synth.base.synthIndexReached`, `synthDoneSpeaking` | synth | Voz |
| `braille.post_displayUpdate` | braille | Lo que se muestra en braille |
| `speech.api.post_speechRequested` | speech/api.py | Texto que se pide hablar (aunque la voz esté desactivada); lo usa el modo braille «mostrar voz» |
| `speech.post_speechPaused` | speech/api.py | Pausa y reanudación de la voz |
| `audio.tones.pre_beep`, `pre_playSound` | audio/tones.py | Cada pitido y cada sonido |
| `input.core.decide_handleRawKey` | input/core.py | Cada tecla en bruto, en el hilo de ganchos (``False`` la captura) |
| `input.core.decide_executeBrailleGesture` | input/core.py | Teclas de la línea braille (``False`` las descarta) |
| `browse.buffer.filter_node` | browse/buffer.py | Cada `Node` del búfer del modo exploración al crearlo (`value`, `buffer`, `controlType`): cambiar lo que se presenta (`role`, `name`, `level`, `landmark`, `layoutTable`, `clickable`, `states`) o devolver `None` para quitarlo con sus descendientes. Se llama en el hilo de construcción, con `buffer.documentKey` como clave del documento; lo usa el complemento «Arreglo web» |

## 9. Datos (`data/`)

| Carpeta | Contenido | ¿Se distribuye? |
|---|---|---|
| `config/` | configuración, perfiles, gestos, símbolos del usuario; copias e informe de la importación de NVDA (`backup_antes_importar/`, sección 25) | No (se crea vacía) |
| `addons/` | complementos instalados (WhatsApp y Eloquence incluidos) | Sí |
| `symbols/` | símbolos en español (`es.json`) y en inglés (`en.json`) y emojis en español (`emoji_es.json`) | Sí |
| `sounds/` | sonidos `.wav` opcionales que sustituyen a los generados (una subcarpeta por tema) | Sí |
| `voices/` | voces Piper descargadas por el usuario (`<clave>/<clave>.onnx` y `.onnx.json`) | No (se crea vacía) |
| `brailleTables/` | tablas braille extra en JSON | Sí |
| `speechDicts/` | diccionarios de voz del usuario | Solo `default.json` si existe |
| `labels/` | etiquetas personalizadas por aplicación | No (se crea vacía) |
| `logs/` | registros | No (se crea vacía) |
| `cache/` | historial del portapapeles, estado de atenuación, copia privada de eSpeak para Piper (`cache/piper`), módulos de comtypes generados en la versión compilada (`cache/comtypes`) | No (se crea vacía) |
| `temp/` | temporales: imágenes del OCR, copias de presentaciones, adjuntos de Outlook abiertos, certificado en memoria. Se vacía al arrancar lo que tenga más de un día (`paths.cleanTempDir`) | No (se crea vacía) |
| `controller/` | API de control: `x64` (servidor, cliente, `tiresiasNvdaWindow.exe`), `x86` (cliente) y, en la versión compilada, `include` y `examples` | Sí |
| `rdp/` | complemento de Escritorio remoto para mstsc (`x64`, `x86`; el programa de pruebas `rdpTestHost.exe` se queda en `rdp/test`) | Sí |
| `synthDrivers/espeak/` | eSpeak NG (`espeak-ng.dll` y `espeak-ng-data`). Solo existe en la versión compilada: la crea `tools/build_data.py` copiando el paquete `espeakng_loader`; en el código fuente no hay esta carpeta | Sí (en la versión compilada) |
| `docs/` | documentación para desarrolladores (`api_control.md`, `desarrollo_complementos.md`), novedades y catálogo local de complementos | Sí (se copia de `docs/` de la raíz) |
| `images/` | icono de la bandeja (`tiresias.ico`, copiado de `resources/`) | Sí |
| `louis/` | liblouis 3.39.0: `liblouis.dll`, `tables/` (más de 250 tablas) y licencia | Sí |
| `locale/` | traducciones de la interfaz: `tiresias.pot` y `<idioma>/LC_MESSAGES/tiresias.po` y `.mo` (los genera `tools/i18n.py`) | Solo los `.mo` |

En `src/tiresias` (y en `lib/tiresias` de la versión compilada) solo hay
código Python; `tests/test_rutas_data.py` lo comprueba.

La copia limpia la hace `tools/build_data.py` al compilar (lista blanca
`INCLUDE` y `PROJECT_FILES`; nunca copia `config`, `logs`, `cache`, `temp`,
`labels` ni las voces descargadas).

**Dos carpetas `data`.** `paths.DATA_DIR` son los datos del usuario (la cambian
`--data`, `TIRESIAS_DATA` y la copia instalada, que usa `%APPDATA%\Tiresias`).
`paths.PROGRAM_DATA_DIR` es siempre la `data` de junto al ejecutable (o de la
raíz del proyecto): de ahí salen los binarios (`paths.controllerBinDir`,
`paths.rdpBinDir`, `paths.espeakDir`), los documentos (`paths.docPath`) y el
icono, aunque se use otra carpeta de datos.

**Desde el código fuente** se usan los mismos sitios: `controller/build.py` y
`rdp/build.py` dejan sus binarios en `data/controller/<arq>` y `data/rdp/<arq>`
(el código C, el IDL y los `.def` siguen en `controller/` y `rdp/`). eSpeak NG
sale, desde el código fuente, del paquete `espeakng_loader` instalado con pip
(`data/synthDrivers` no existe ahí salvo que se cree a mano); en la versión
compilada sale de `data/synthDrivers/espeak`, que crea `tools/build_data.py`
copiando ese paquete, y el paquete no va en `lib` (se excluye en
`setup_cxfreeze.py` para no duplicarlo). `paths.docPath` busca en
`data/docs` y después en `docs/`.

**Fuera de `data` en la versión compilada** solo queda lo que cx_Freeze y
Windows necesitan junto al ejecutable: `Tiresias.exe`,
`Tiresias-depuracion.exe`, `lib/` (bibliotecas de Python y el paquete
`tiresias`, solo código `.pyc`: liblouis y los catálogos están en `data`),
`python3.dll`, `python314.dll` y las DLL del runtime de Visual C++ (el
cargador de Windows las busca junto al ejecutable al crear el proceso, antes de
que Python pueda añadir otra carpeta), las licencias (`LICENSE.txt`,
`LICENSE-vc_redist.txt`, que cx_Freeze deja en `share/licenses` y
`setup_cxfreeze.py` saca a la raíz, y `frozen_application_license.txt`),
`LEEME.txt` y `Manual de usuario.html`. cx_Freeze no permite mover `lib` ni
`python3*.dll`: el ejecutable base los busca en rutas fijas.

**Caché de comtypes.** Los módulos de UIA, MSAA, SAPI y WScript se generan
antes de compilar (`tools/pregenerate_comtypes.py`) y van en
`lib/comtypes/gen`. Si en la versión compilada hiciera falta otro,
`core._useComtypesCache` hace que comtypes lo escriba en `data/cache/comtypes`
(sin eso lo escribiría junto al ejecutable o en `%TEMP%\comtypes_cache`).
Desde el código, comtypes usa su carpeta `comtypes/gen` del entorno virtual.

**Excepciones documentadas** (archivos fuera de `data`, siempre a petición del
usuario o porque el sistema lo exige):

- Configuración del sistema del modo seguro y de la pantalla de inicio de
  sesión: `systemConfig/` junto al ejecutable (`paths.SYSTEM_CONFIG_DIR`, la
  escribe `installer.copyConfigToSystem` con permiso de administrador) y la
  política de empresa, que pone el administrador junto al ejecutable
  (`config/policy.py`).
- Copia instalada: la marca `instalado.json` junto al ejecutable, los datos del
  usuario en `%APPDATA%\Tiresias` (la carpeta de Archivos de programa no se
  puede escribir), los accesos directos y las claves de registro de
  desinstalación, inicio automático y del complemento de Escritorio remoto
  (HKCU).
- Instalador: descomprime el programa en `%TEMP%\TiresiasInstalador` (aún no
  existe ninguna carpeta `data`), y la desinstalación deja en `%TEMP%` un
  `tiresias-desinstalar.cmd` que borra la carpeta del programa (que incluye
  `data`) cuando Tiresias se cierra y luego se borra a sí mismo.
- Java Access Bridge: `%USERPROFILE%\.accessibility.properties`, que Java
  solo lee en esa ruta (`a11y/jab.py`, con confirmación).
- Lo que el usuario guarda o exporta donde elige (gestos exportados, copia
  portable, adjuntos guardados, audio exportado...).

## 10. Limitaciones conocidas y trabajo futuro

- Sin inyección de código: no hay «display model» de aplicaciones GDI muy
  antiguas sin accesibilidad. La revisión de pantalla usa los objetos UIA y, como
  alternativa, la revisión de pantalla por OCR (sección 20).
- Voz por Escritorio remoto solo con clientes Windows x64/x86 que cargan
  complementos DVC de Microsoft (`mstsc`, `msrdc`, Citrix Workspace app,
  Horizon Client, Parallels Client) y Tiresias en los dos extremos; Citrix
  necesita que el administrador permita el canal; sin ARM64 (sección 23).
- Sin `uiAccess`: como cualquier programa portable, no puede leer ventanas de
  administrador si Tiresias no se ejecuta como administrador, ni el escritorio
  seguro (UAC).
- Braille: los controladores de líneas físicas (sección 14) se han probado
  con tramas simuladas, no con hardware real.
- Matemáticas: motor propio (sección 15). El braille CMU cubre lo esencial;
  Firefox y MathType no se han probado en el equipo de desarrollo.
- Acceso remoto sin `uiAccess` ni servicio: el equipo controlado con Tiresias
  no puede simular Control+Alt+Supr ni hablar en el escritorio seguro (UAC,
  pantalla de bloqueo). Ver sección 13.
- Pantalla táctil sin `uiAccess`: los toques se capturan con una ventana
  superpuesta, no con `RegisterPointerInputTarget` (ver sección 12). Las
  interfaces del sistema que Windows coloca por encima de las ventanas
  «siempre encima» (menú Inicio, teclado táctil...) reciben los toques
  directamente. No se ha podido probar con todos los paneles táctiles.


## 11. Gestos y conflictos

`gui/gesture_tools.py` centraliza la captura de combinaciones
(`startCapture`) y la comprobación de conflictos (`checkGesture`,
`confirmAssignment`): combinaciones reservadas por Windows, teclas que escriben
texto o muy usadas por las aplicaciones y gestos ya asignados a otras órdenes.
Lo usan el diálogo «Gestos de entrada» y el de «Tecla del menú de Tiresias».
Los gestos de líneas braille (`br(<controlador>):<teclas>`) se normalizan con
las teclas ordenadas, así que el orden de un acorde no importa.
Los gestos táctiles (`ts:` y `ts(<modo>):`) solo chocan con otros gestos
táctiles; el modo táctil hace el papel de la distribución de teclado.


## 12. Pantalla y panel táctil

Paquete `touch/`:

| Módulo | Función |
|---|---|
| `recognizer.py` | Reconocedor de gestos **puro** (sin Windows): recibe `down`/`move`/`up` de cada dedo con su instante y devuelve `TouchEvent`. `poll(t)` resuelve plazos y `nextDeadline()` dice cuándo volver a llamarlo. Probado en `tests/test_tactil.py` con secuencias sintéticas. |
| `gestures.py` | `TouchGesture` (compatible con el gestor de entrada), identificadores y nombres en español. |
| `overlay.py` | Captura de los toques de la pantalla en un hilo propio («Táctil»). |
| `touchpad.py` | Panel táctil de precisión con Raw Input e informes HID (hilo «Panel táctil»). |
| `explorer.py` | Qué objeto hay bajo el dedo (saltando la superposición) y su lectura. |
| `handler.py` | Activación según la configuración y el hardware, modos táctiles, agrupación de la exploración y paso de los gestos al núcleo. |
| `commands.py` | Órdenes táctiles y gestos por defecto; `install(GlobalCommands)` se llama al final de `global_commands.py`. |
| `win32.py` | Declaraciones Win32 propias y `WindowThread` (ventana con bucle de mensajes). |

### Reconocimiento

Un **grupo** son los dedos que tocan dentro de `holdTime` (0,25 s) desde el
primero. Si todos se levantan antes, sin moverse, es un toque; si se mueven
50 px o más en la misma dirección, un deslizamiento; dos dedos que cambian su
distancia, un pellizco. Si sigue apoyado un solo dedo al cumplirse `holdTime`,
empieza la exploración (`hoverDown`, `hover`, `hoverUp`); con varios dedos
quietos, `hold`. Los toques seguidos con los mismos dedos dentro de
`multiTapTimeout` (configurable, 300 ms) forman `doubleTap`/`tripleTap`; un
toque seguido de un contacto mantenido, `tapAndHold`/`doubleTapAndHold`.
Mientras un dedo explora, un toque breve de otro dedo es `splitTap`. Las
distancias se multiplican por los ppp del sistema / 96.

**Secuencias de dos deslizamientos** (las 12 de NVDA 2026: 4 contrarias y 8
en L, `flickRightThenLeft`, `flickUpThenRight`...):

- *Sin levantar el dedo*: cada contacto guarda su recorrido. Al levantarlo,
  `_classify` busca el punto de giro (el más alejado de la cuerda inicio-fin o,
  si el dedo volvió cerca del inicio, el más alejado del inicio); si ese giro
  se separa al menos media distancia de deslizamiento y los dos tramos miden
  `minFlickDistance` o más en direcciones distintas, es una secuencia. Para
  que quepa, mientras todos los dedos se deslizan rápido el plazo de
  exploración se amplía hasta `continuousFlickTimeout` (0,6 s).
- *Levantando el dedo*: tras un deslizamiento, el reconocedor solo espera
  `sequenceTimeout` (0,3 s) si `sequenceFilter(acción, dedos)` devuelve
  `True`. `TouchHandler.sequenceFilter` lo hace solo con la opción
  `liftedSequentialFlicks` activada y si alguna secuencia que empiece por ese
  deslizamiento tiene orden en `GlobalCommands` o en el mapa del usuario; así
  los deslizamientos simples no se retrasan sin necesidad.

**Gestos de borde**: con `edgeMargin` > 0 y `bounds` (el escritorio virtual,
es decir, la superposición), los deslizamientos y secuencias de un dedo cuyo
contacto empieza a menos de `edgeMargin` píxeles de un borde llevan
`edge`. `TouchGesture` pone primero los identificadores con borde
(`ts(<modo>):leftedge_flickright`, `ts:leftedge_flickright`) y después los
del gesto normal, así que un gesto de borde sin orden hace lo del gesto
normal. Opciones `edgeGestures` (desactivada por defecto) y `edgeMargin`
(24 px a 96 ppp). Los deslizamientos desde el borde que Windows se reserva
(widgets, centro de notificaciones...) no llegan nunca a la superposición:
el sistema los atiende antes. El panel táctil no usa bordes.

### Identificadores y modos

`ts(<modo>):<gesto>` y `ts:<gesto>`, con `<gesto>` = acción con el número de
dedos delante (`2finger_flickDown`). Modos: `object`, `text` y `browse` (solo
disponible si el foco está en un documento en modo exploración; si no, se usa
`object`). Los gestos del panel táctil llevan además `tp(<modo>):` y `tp:`
delante, así que por defecto hacen lo mismo que en la pantalla pero se pueden
reasignar aparte. `input/keys.labelForGesture` delega en
`touch.gestures.labelForIdentifier` para los nombres en español del diálogo
«Gestos de entrada», la paleta y la referencia rápida.

`InputManager.executeTouchGesture(gesture)` (hilo del núcleo) atiende la
captura del diálogo de gestos, la ayuda de entrada (la exploración sigue
funcionando y no se anuncia) y ejecuta la orden. Las órdenes de exploración
llevan `noSpeechInterrupt` para que arrastrar el dedo sobre el mismo objeto no
corte la voz.

### Captura sin uiAccess

`RegisterPointerInputTarget` (lo que usa NVDA instalado) exige el privilegio
*uiAccess*: manifiesto firmado y ejecutable en una carpeta protegida, algo
incompatible con una copia portable (ser administrador no basta). Por eso:

1. Si el proceso tiene uiAccess (`win32.hasUiAccess()`), se registra una
   ventana `HWND_MESSAGE` como destino de los toques y se llama a
   `AccSetRunningUtilityState(ANRUS_TOUCH_MODIFICATION_ACTIVE)`.
2. Si no (lo normal), se crea una **superposición**: ventana `WS_POPUP` del
   tamaño del escritorio virtual con `WS_EX_TOPMOST | WS_EX_LAYERED |
   WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE`, opacidad 1/255 y la propiedad
   `MicrosoftTabletPenServiceProperty` para quitar los gestos del sistema
   sobre ella. Responde `WM_POINTERDOWN/UPDATE/UP` (tipo táctil o lápiz), así
   que Windows no los convierte en clics; `WM_MOUSEACTIVATE` y
   `WM_POINTERACTIVATE` devuelven «no activar». Cada 2 s se vuelve a poner
   encima y se ajusta al escritorio virtual si cambia.
3. **Ratón**: si llega un movimiento real del ratón (no generado desde un
   toque, según `GetMessageExtraInfo`) o Tiresias va a hacer un clic simulado
   (`mouse.click`, `toggleLock` y `scroll` llaman a
   `touch.handler.allowMouseThrough()`), la superposición añade
   `WS_EX_TRANSPARENT` y deja pasar el ratón; tras 2 s sin actividad del ratón
   vuelve a capturar. El cambio desde otro hilo se hace con
   `SendMessageTimeout` a la propia ventana (sin bloqueos entre hilos).
4. **Exploración**: con la superposición encima, `ElementFromPoint` la
   devolvería a ella. `explorer.objectAtPoint` detecta ese caso y busca la
   ventana visible de debajo recorriendo el orden Z (saltando ventanas
   ocultas, encubiertas por DWM o transparentes a la entrada), baja por sus
   ventanas hijas con `ChildWindowFromPointEx` y luego por el árbol UIA
   (`FindAllBuildCache` de los hijos con su rectángulo) quedándose con el más
   pequeño que contiene el punto.
5. **Activar** (doble toque) usa `doAction` del objeto: patrones UIA Invoke,
   Toggle, ExpandCollapse, SelectionItem o la acción por defecto; solo si no
   hay ninguno hace clic en su centro, apartando antes la superposición.

La superposición nunca se crea si no hay pantalla táctil
(`GetSystemMetrics(SM_DIGITIZER)` con `NID_READY` y `SM_MAXIMUMTOUCHES > 0`),
si la opción está desactivada o si Tiresias se inició con `--no-input`.

### Panel táctil de precisión

`touchpad.TouchpadInput` registra con `RegisterRawInputDevices` la página 0x0D
(digitalizador), uso 0x05 (panel táctil) con `RIDEV_INPUTSINK |
RIDEV_DEVNOTIFY` en una ventana `HWND_MESSAGE`. De cada dispositivo lee los
datos preanalizados (`RIDI_PREPARSEDDATA`) y sus capacidades
(`HidP_GetCaps`, `HidP_GetValueCaps`, `HidP_GetButtonCaps`) para construir un
`TouchpadLayout`: colecciones de dedo con X/Y y sus rangos lógicos, identificador
de contacto, «confidence» y la colección del recuento de contactos. Cada
informe se lee con `HidP_GetUsageValue`/`HidP_GetUsages`; `FrameAssembler`
junta los contactos de un fotograma (también en modo híbrido, repartidos en
varios informes), `ContactTracker` produce `down`/`move`/`up` y las
coordenadas se llevan al escritorio virtual para usar los mismos umbrales.
Raw Input solo observa: Windows sigue moviendo el puntero y haciendo sus
gestos; por eso, por defecto, se descartan los gestos de un dedo.

## 13. Acceso remoto

Paquete `remote/`, compatible con el acceso remoto de NVDA 2025.1+ y con el
complemento NVDA Remote (mismo protocolo, mismos servidores). Se ha escrito
desde cero a partir de la especificación del protocolo.

### Protocolo

Mensajes JSON, uno por línea (`\n`), sobre TLS 1.2 o superior; versión de
protocolo 2; puerto estándar 6837 (`remote/protocol.py`). Al conectar, el
cliente envía `protocol_version` y `join` (`channel` = clave,
`connection_type` = `master` si controla o `slave` si es controlado) o
`generate_key`. El servidor responde `channel_joined` (con `clients`) y avisa
a los demás con `client_joined`/`client_left`; después reenvía cada mensaje a
los demás clientes del canal añadiendo `origin`. Mensajes de control: `key`
(`vk_code`, `extended`, `pressed`, `scan_code`), `speak` (`sequence`,
`priority`), `cancel`, `pause_speech`, `tone`, `wave` (`fileName`, y el
campo propio `tiresiasSound`), `display` (`cells`), `braille_input`,
`set_braille_info` (`name`, `numCells`), `set_clipboard_text` (`text`),
`send_SAS`, `motd`, `version_mismatch`, `error`, `ping`.

`remote/serializer.py` traduce las órdenes de voz a la forma de NVDA
(`["PitchCommand", {"_offset": 30, "_multiplier": 1, "isDefault": false}]`)
y de vuelta a `speech.commands`; las órdenes solo locales (índices,
llamadas, pitidos y sonidos intercalados) no viajan dentro de `speak`.

### Capas e hilos

| Módulo | Función | Hilo |
|---|---|---|
| `connection.py` | `LineConnection`: un hilo de E/S por socket TLS; `send()` solo encola y despierta al hilo con un par de sockets | E/S |
| `transport.py` | `RelayTransport`: conexión, saludo, certificados, reconexión cada `reconnectDelay` s | Conector |
| `server.py`, `certs.py` | `RelayServer` (IPv4 + IPv6, un hilo de saludo TLS por conexión) y certificado autofirmado (`cryptography`) | Servidor |
| `session.py` | `LeaderSession` / `FollowerSession`: qué hace cada papel con cada mensaje; no dependen de Tiresias | — |
| `local_machine.py` | `TiresiasMachine`: voz, braille, sonidos, portapapeles, inyección de teclas | Núcleo (teclas: red) |
| `client.py` | `RemoteClient`: conexión, avisos, teclado, ganchos de salida | Núcleo y ganchos |
| `store.py` | `data/config/remote/remoto.json`: preajustes (claves cifradas con DPAPI, `dpapi.py`; las antiguas en claro se migran al cargar), huellas, recientes, conexión automática | — |
| `session_lock.py` | Ventana oculta con `WTSRegisterSessionNotification`: al bloquear la sesión el teclado vuelve al equipo local y al desbloquear se recupera el control remoto; `Windows+L` se detecta además en `_onRawKey` | Aviso de sesión |
| `plugin.py` | Órdenes (complemento global incorporado, categoría «Acceso remoto») | Núcleo |
| `gui/remote_dialogs.py` | Cuadro Conectar, certificado, confirmación, submenú y panel de opciones | Interfaz |

Los mensajes recibidos se pasan al hilo del núcleo con
`queue_handler.queueFunction`, salvo `key`, que se inyecta en seguida desde el
hilo de red con `SendInput` y la marca `winapi.REMOTE_INJECTION_MARK`; el
gancho trata esas teclas como pulsadas por el usuario para que las órdenes de
Tiresias funcionen en el equipo controlado. Nada de la red bloquea el núcleo
ni el gancho: enviar es encolar.

### Equipo controlado (salida)

`RemoteClient` se registra en `speech.pre_speechQueued` (voz ya procesada,
con su prioridad real), `pre_speechCanceled`, `post_speechPaused`,
`tones.pre_beep`, `tones.pre_playSound` y `braille.post_displayUpdate`, y solo
envía si hay algún equipo que controla en el canal. El braille se negocia con
`set_braille_info`: `BrailleHandler.setRemoteNumCells(n, owner)` hace que el
manejador trabaje con la menor línea (o con la remota si no hay línea local).
Cada dueño (`"remote"`, `"rdp"`) pone su tamaño y se usa el menor mayor que 0;
`showRemoteCells(cells, owner)` igual (cada `TiresiasMachine` es un dueño), así
que desconectar uno no borra lo del otro. Un equipo que controla no responde
al `set_braille_info` de otro que controla (evita el bucle con NVDA).

### Equipo que controla (teclado)

`input.core.decide_handleRawKey` recibe cada tecla en el hilo de ganchos.
Mientras se controla el equipo remoto, `RemoteClient._onRawKey` envía la tecla
y la captura. La orden «alternar control» (`Tiresias+Alt+Tab`) se reconoce en
el propio hilo de ganchos (`decide_executeGesture` al ir al remoto y
`findScript` sobre los modificadores enviados al volver), de modo que el
cambio es atómico respecto a las teclas siguientes:

- Al ir al remoto, las teclas aún pulsadas en local (modificadores, tecla
  Tiresias y la principal) quedan en `_localPendingUps`: su liberación la
  procesa el equipo local.
- Al volver al local se envía la liberación de todo lo pulsado en el remoto
  (con `VK_NONE` antes si había Alt o Windows, como NVDA) y la liberación física
  de esas teclas se descarta en local (`_swallowUps`).

Las teclas de la línea braille local se envían como `braille_input` con
`scriptPath` = `["globalCommands", "GlobalCommands", <orden>]`
(`decide_executeBrailleGesture`). Las celdas recibidas se muestran con
`BrailleHandler.showRemoteCells`.

### Certificados

Primero se valida con las autoridades de Windows. Si falla, se lee la huella
SHA-256 del certificado (DER): si está en `trustedCertificates` (clave
`host` o `host:puerto`, como NVDA) se conecta sin validar la cadena pero
exigiendo esa huella; si no, `onCertificateFailed` y el cuadro «Certificado no
verificado» (confiar siempre / solo esta vez / cancelar). Al alojar el
servidor, el propio equipo se conecta a `127.0.0.1` fijando la huella de su
certificado (`data/config/remote/servidor.*`).

### Pruebas

`tests/test_remoto.py` levanta el servidor en `127.0.0.1` (puerto libre),
conecta clientes en el mismo proceso y comprueba voz, teclas, portapapeles,
braille, canales, versión de protocolo, generación de clave, reconexión,
clave incorrecta, TLS y huellas, y la compatibilidad de formato con un
cliente «a mano» que habla exactamente como NVDA. El estado del teclado al
alternar se prueba sin ganchos ni teclas reales.


## 14. Controladores de líneas braille

Paquete `braille/drivers/` (cada módulo define `BrailleDisplayDriver`; el nombre
del módulo es el del controlador y el de los gestos `br(<nombre>):<teclas>`).
`braille/hid_braille.py` se conserva solo por compatibilidad.

| Módulo | Función |
|---|---|
| `hwio.py` | E/S Win32 con ctypes y lectura solapada en un hilo por conexión: `SerialPort` (DCB, tiempos «devolver en cuanto haya un byte»), `HidDevice` (informes, características, `HidP_*`), `BulkDevice` (`ruta\extremo`) y `MemoryTransport` (pruebas). Un fallo de lectura o tres de escritura seguidos llaman una sola vez a `onError`. |
| `ports.py` | Enumeración con SetupAPI: dispositivos USB, HID (atributos en caché por ruta) y puertos COM con su identificador USB o su nombre Bluetooth (`BluetoothGetDeviceInfo`). |
| `base.py` | `HardwareDriver`: conexión en segundo plano y reconexión, `KeyTracker` (el gesto sale al soltar la primera tecla), `buildGesture`, mapa de gestos por defecto y decisor de teclas emuladas. |
| `detect.py` | Detección automática: `findCandidates` (USB antes que Bluetooth, cada dispositivo para el primer controlador que lo reconoce, el estándar HID el último) y el hilo `Detector`. `testConnection` para el botón Probar. |
| `auto.py` | Controlador «Automático»: ocupa el sitio con 0 celdas mientras busca e instala el controlador encontrado con `handler.setDisplay(nombre, persist=False, instance=...)`. |

Un controlador declara sus identificadores (`usbHidIds`, `usbSerialIds`,
`usbBulkIds`, `genericUsbIds`, `bluetoothPrefixes`) e implementa `_connect`
(abrir con `self._open(match, ...)` y esperar la identificación con
`_waitFor`), `_handleData` (hilo de lectura; en serie llegan trozos del flujo
que hay que reensamblar) y `_writeCells`. Las teclas se notifican con
`_keysChanged`, `_keyPressed`/`_keyReleased` o `_fireChord`; el enrutamiento
son tuplas `("routing", i)` y `("routing2", i)`.

Ciclo de vida:

- Línea concreta elegida: el constructor no bloquea; un hilo prueba el puerto
  configurado (`conf["brailleDisplays"]["ports"][nombre]`: `auto`, `usb`,
  `bluetooth`, `COMx` o la ruta de un dispositivo) hasta que conecta. Entonces
  `_activate` (núcleo) asocia los gestos, refresca el gestor y avisa.
- Desconexión: la conexión avisa a `_onIoError`; el controlador queda con 0
  celdas y vuelve a buscar (o, si vino de «Automático», vuelve a «auto»).
- `configName` es el nombre guardado en la configuración (`auto` para las
  detectadas); `core.applyConfiguration` lo usa para no recargar la línea al
  cambiar de perfil.

Gestos: el `gestureMap` (`"teclas": "orden"` o `"kb:tecla"`) se asocia a las
órdenes globales como gestos de instancia de `GlobalCommands` mientras la
línea está activa (el mapa del usuario tiene prioridad y la paleta de órdenes
los muestra). Las teclas emuladas las resuelve un decisor de
`decide_executeBrailleGesture`, que además entrega los gestos braille a la
captura del cuadro Gestos de entrada. Los gestos llevan `dots`/`space` cuando
la combinación es de escritura braille, y `routingIndex(es)`.

Ajustes propios de un controlador: `driverSettings` (tuplas de `DriverSetting`),
guardados en `conf["brailleDisplays"]["settings"][controlador]`, leídos con
`getSetting`/`setSetting`. La categoría «Braille» del cuadro de Opciones crea
un grupo por controlador (`braille_display_dialog.makeDriverSettings`) y, al
guardar, llama a `applySettings()` de la línea activa. Las
órdenes propias de un controlador se definen con `@script` en su clase (el
controlador activo está en la cadena de órdenes).

Interfaz: `gui/braille_display_dialog.py` (diálogo «Seleccionar línea
braille» con puerto, botón Probar y lista de líneas de la detección automática;
y las funciones de los ajustes de cada controlador que usa la categoría
«Braille»). Orden global sin gesto:
`activateBrailleDisplayDialog`.

Pruebas: `tests/braille_sim.py` (`connectSimulated` sustituye `_open` por una
`MemoryTransport` con un «responder» que hace de línea) y
`tests/test_braille_*.py`, una por controlador más `test_braille_drivers.py`
para la infraestructura.


## 15. Órdenes globales adicionales, instancia única y formato

**Órdenes.** `global_commands_extra.py` define `ExtraCommands` con las órdenes
equivalentes a las de NVDA que faltaban (39 conmutadores de formato de
documento generados desde las tablas `DOC_TOGGLES`, 36, y `DOC_CYCLES`, 3; voz,
revisión, ubicación, ratón, apertura de cada panel y herramienta, perfiles,
reinicio, registro...). `install(GlobalCommands)` (al final de
`global_commands.py`) copia en `GlobalCommands` las órdenes y métodos que esa
clase no tenga ya y añade sus gestos con `setdefault`: una orden existente
nunca pierde su tecla. Así el mapa de gestos del usuario (clave
`tiresias.global_commands.GlobalCommands`), la paleta, Gestos de entrada y la
referencia rápida las ven como globales normales. Para añadir un conmutador
de formato basta una fila en `DOC_TOGGLES`.

**Modo dormir por perfil (#3721).** `sleepMode.enabled` en la configuración
activa duerme la aplicación en primer plano (nunca el propio Tiresias).
`applyProfileSleepMode` se ejecuta tras `post_configProfileSwitch` y
`api.post_focusChange`, recuerda qué aplicaciones durmió y respeta que el
usuario las despierte con la orden. Las aplicaciones siempre dormidas son
`appModules.sleepApps`.

**Formato (`formatting.py`).** Además del formato de texto (ahora con
`lineSpacing`, atributo UIA 40040) ofrece: `lineIndentationSpeech` (sangría
de líneas con `ignoreBlankLinesForRLI`, usada por
`presentation.speakLineText`), `linkTypeText`/`linkTypeForElement`/
`linkTypeForObject` (enlace a la misma página), `cellBordersText` (propiedades
UIA OutlineThickness 30164 y OutlineColor 30161) y `shouldReportContainer`
(el modo exploración no anuncia entrada ni salida de contenedores
desactivados).

**Portapapeles.** `clipboard.py` registra un manejador en
`input.core.decide_executeGesture` (hilo de ganchos, solo clasifica la tecla
y encola) para distinguir cortar, copiar y pegar; el sondeo atribuye el
cambio del portapapeles a la última tecla durante 1,5 s.
`api.copyToClip(notify=True)` respeta `clipboard.confirmCopyCommands`.

**Paleta.** `gui.helpers.fuzzyScore` puntúa cada palabra de la búsqueda
(exacta, prefijo, subcadena, una errata, iniciales, letras en orden dentro de
una palabra); `command_palette.filterEntries` ordena por puntuación y puede
filtrar por un gesto capturado («Buscar pulsando las teclas», #7074, con
`gesture_tools.startCaptureWithMessage`).

**Instancia única.** `core.isRunning()` mira la ventana oculta y el mutex
`Tiresias_LectorDePantalla_Instancia`. Por defecto (`--replace`) la copia
nueva cierra la anterior con `WM_CLOSE` y, si no responde en 8 s, termina su
proceso. `--no-replace` sale sin tocarla y `--check-running` devuelve 0 o 1.
El mutex se libera antes de lanzar la copia de un reinicio, y `restart()`
fija `args.safe_mode` al valor pedido (un reinicio normal tras un arranque
sin complementos vuelve a cargarlos). La clave `Run` solo se reescribe al
arrancar y si la ruta cambió (`_refreshStartOnLogon`).

**Cortina y perfiles.** La orden de la cortina guarda el estado en
`vision.screenCurtain` (`setScreenCurtain(persist=True)`), y
`core.applyConfiguration` reaplica cortina, lupa y resaltado al cambiar de
perfil o restaurar la configuración.


## 16. Matemáticas (`mathpres/`)

Motor propio (no usa MathCAT). Todo el texto que produce está en español.

| Módulo | Función |
|---|---|
| `mathml.py` | Análisis tolerante con `html.parser` (entidades HTML, prefijos `m:`, `innerHTML` de navegadores) y normalización: quita `mstyle`/`mpadded`/`semantics`/`mphantom`, convierte `mfenced`, infiere `mrow` y agrupa delimitadores en grupos `mrow` con los atributos internos `_open`/`_close` (paréntesis, corchetes, llaves, barras de valor absoluto y norma). |
| `content.py` | MathML de contenido básico → presentación. |
| `latex.py` | LaTeX → MathML (analizador descendente propio) y MathML → LaTeX. |
| `omml.py` | Ecuaciones de Office (OMML) → MathML. |
| `speech_es.py` | Generador de voz: devuelve cadenas y `Pause`; `toSpeechSequence` las convierte en `BreakCommand`. Verbosidad `breve`/`normal`/`detallado` y estilo `natural`/`estructural`. Las marcas de fin («fin de fracción») se añaden solo si la estructura no termina donde termina su contexto (`_isTrailing`). |
| `braille_cmu.py` | Código Matemático Unificado (ONCE). `BrailleResult.ranges` guarda las celdas de cada nodo para el cursor y los pulsadores. |
| `navigation.py` | `MathNavigator`: hermanos, hijos, padre, celdas de tablas, «dónde estoy». Los `mrow` de contenido de raíces, celdas y delimitadores son transparentes. |
| `providers.py` | Obtención del MathML (ver abajo), portapapeles y caché por `RuntimeId`. |
| `interaction.py` | `MathInteractor` (órdenes de exploración) y `start`/`stop`. |
| `plugin.py` | Complemento global incorporado (`plugins.handler.registerBuiltin`): órdenes globales, delegación de teclas al explorador y superposición `MathObject` para el rol `MATH`. |
| `browse_support.py` | Integración con el búfer del modo exploración. |
| `settings_panel.py` | Categoría «Matemáticas» de Opciones (sección de configuración `math`, registrada con `registerDefaults`). |

**Obtención en Chromium.** UIA expone la estructura de `<math>` (grupos con
`AriaRole` «math») pero no las etiquetas. Chromium publica el contenido de
cada `<math>` en el atributo IA2 `math` (escapado con `\`). Como el elemento
UIA no da acceso a su `IAccessible`, `findMathInWindow` recorre el árbol MSAA
de la ventana `Chrome_RenderWidgetHostHWND` (`AccessibleObjectFromWindow`) y
solo baja por los nodos cuyo rectángulo contiene alguno de los rectángulos
buscados; un nodo con `tag:math` y el mismo rectángulo que el elemento UIA es
la fórmula. El búfer del modo exploración busca todas las fórmulas del
documento en una sola pasada (`browse_support.prefetch`, llamado desde
`VirtualBuffer.build`). El proxy de IA2 lo trae Windows (`ia2comproxy.dll`).
En Firefox se usa `ISimpleDOMNode.innerHTML`, y para imágenes con
`role="math"`, `data-mathml` (Chromium no implementa `ISimpleDOMNode`).
Un texto alternativo o una etiqueta ARIA en LaTeX (Wikipedia) se convierte
con `latex.py`; las imágenes (`GRAPHIC`) con texto alternativo en LaTeX se
tratan como fórmulas. Chromium no publica en la vista de control los
elementos `role="math"` sin hijos (solo etiqueta o `alt`):
`browse_support._findLabelOnlyMath` los busca en la vista completa y
`emitExtras` los inserta en el búfer junto a su hermano visible.

**Word (probado).** En una instancia propia de Word con ecuaciones creadas
por COM, el elemento envolvente del cursor (`TextPattern.GetSelection()` →
`GetEnclosingElement()`, «Ecuación») y los hijos del rango de texto dan
«Word.MathML»; `FindAll` sobre el documento no los devuelve. El modelo de
objetos se obtiene de la ventana `_WwG` del foco con
`AccessibleObjectFromWindow(OBJID_NATIVEOM)`, nunca con `GetActiveObject`
(podría ser otra instancia de Word).

**Word.** Propiedad UIA personalizada «Word.MathML» (GUID
`FA170AB3-3229-4E7C-827F-DD05EE0481D9`, registrada con
`IUIAutomationRegistrar`) y, si no, `Selection.OMaths(1).Range.WordOpenXML`
con la conversión OMML propia. MathType: `MTGetLangStrFromEqn` de la
biblioteca de 64 bits si está instalada.

**Cadena de órdenes.** El complemento de matemáticas es el primer eslabón de
la cadena (`InputManager.chain`). Mientras hay un `MathInteractor`, su
`getScript` devuelve primero las órdenes del explorador; las teclas sin
modificadores que no tienen orden se anulan (`script_ignore`) y las que
llevan Tiresias, Alt, Windows o Control siguen por la cadena. Un
`gainFocus` termina la exploración.

**Braille.** `BraillePresenter.handleCustom(texto, cursor, dueño, selección)`
muestra una región propia; los pulsadores llaman a `dueño.routeTo(índice)`.
Los caracteres braille Unicode (U+2800–U+28FF) pasan sin traducir por
`tables.translate` (tramo `"braille"`), lo que permite mezclar texto y
braille CMU en la línea del modo exploración.

**Modo exploración.** `Role.MATH` es un rol en línea y con prefijo
(«matemáticas»); su texto en el búfer es la lectura de la fórmula. Tecla de
navegación rápida: `0`. Intro o Espacio sobre una fórmula empiezan la
exploración (`activateAt`).

## 17. Núcleo braille (`braille/`)

| Módulo | Contenido |
|---|---|
| `liblouis.py` | Envoltorio ctypes de `louis/liblouis.dll` (liblouis 3.39.0 oficial de 64 bits, LGPL; tablas en `louis/tables`). `translate` devuelve celdas, `brailleToRaw`, `rawToBraille` y cursor; `backTranslate`; `hyphenate`. Cerrojo global (liblouis no es segura entre hilos). Las rutas se pasan completas (nombre corto 8.3 si la carpeta no es ANSI). |
| `tables.py` | Catálogo: tablas de liblouis con nombre en español generado de sus metadatos (`#+language`, `#+contraction`, `#+grade`, `#+dots`, `#+direction`...; #11298) más las propias (`es-comp8`, `es-g1`, JSON). `getTable("auto")` elige la del idioma de la interfaz. Si liblouis falla, la tabla se marca como rota y se usa la propia. `translate(tabla, texto, ...)` aplica normalización Unicode, nombres de emoji, caracteres no definidos y braille Unicode sin traducir, conservando la correspondencia de posiciones. |
| `presenter.py` | `BraillePresenter`, mezclado en `BrailleHandler`: búfer principal (texto, cursor, selección, marcas con puntos 7-8, typeform), ventana según `textWrap`, línea dividida, mensajes, modo «mostrar voz», desplazamiento automático, enrutamiento, propiedades de los objetos (`objectProperties`, orden y abreviaturas configurables) y regiones propias (`handleCustom`). |
| `input.py` | Entrada braille: búfer por palabra, tablas integrales (traducción inmediata con corrección) y contraídas (al pulsar espacio), conmutadores de modificadores, `addKeyboardIdentifiers` (`bk:dot1+dot2`, `bk:dots`) y teclado braille del PC (`PcBrailleKeyboard`, gancho `decide_handleRawKey`, códigos de exploración). |
| `commands.py` | Órdenes braille añadidas a `GlobalCommands` con `install` (como las táctiles). |
| `__init__.py` | Controladores (`setDisplay`, visor espejo, acceso remoto) y conexión de los puntos de extensión en `initialize`. |

**Flujo.** `presentation.speakObject` → `handleObject` (foco/consulta);
`presentation.speakTextInfo` → `handleCaretMove` solo para el cursor del
sistema (la revisión llega por `api.post_reviewMove`, respetando
`tetherTo`); `api.post_navigatorObjectChange` → `handleNavigatorObject`
(seguimiento a la revisión); `events.post_event` → `onEvent` (caret,
textChange, valueChange, typedCharacter... del foco programan
`scheduleFocusUpdate`, que agrupa ráfagas; `liveRegionChange` → mensaje);
`speech.speakMessage` → `handler.message`; `speech.api.post_speechRequested`
→ `onSpeech`; `sayall._updateCursor` → `handleSayAllLine`.

**Ventanas.** `_windowEnd(inicio)` devuelve el fin de la ventana y si lleva
la marca de continuación (puntos 7-8) según `textWrap` (`none`,
`markWordCuts`, `wordBoundaries`, `syllableBoundaries` con
`lou_hyphenate` y `hyph_*.dic`). Avanzar usa ese fin; retroceder,
`_previousWindowStart`; el cursor visible, `_windowForCell`.

**Gestos de líneas.** `InputManager.updateChain` añade
`_BrailleDisplayScripts` (tras el módulo de aplicación): resuelve en cada
búsqueda el controlador activo, así sus órdenes propias y los gestos que el
usuario le asigne entran en la cadena (también los de complementos).
`executeBrailleGesture` añade los identificadores `bk:` antes de buscar; si
nada atiende un acorde de puntos o espacio, lo trata `brailleInput.handler`.

**Visor.** `_writeCells(celdas, texto, etiquetas)`: `etiquetas` es el texto
de cada celda (vacío en las celdas que continúan un carácter) y el visor lo
dibuja alineado; clic o puntero quieto = enrutamiento.

**Opciones** (`conf["braille"]`, registradas en `presenter.DEFAULTS`):
`mode`, `inputTable`, `autoScrollRate`, `reviewRoutingMovesSystemCaret`,
`paragraphStartMarker`, `textWrap` (sustituye a `wordWrap`, que se migra),
`unicodeNormalization`, `speakOnRouting`, `speakOnNavigatingByUnit`,
`reportLiveRegions`, `fontFormattingDisplay`, `showSpellingErrors`,
`showEmojiNames`, `undefinedCharacters`, `splitView`, `followSayAll`,
`markSelectedItem`, `propertyOrder`, `hiddenProperties`,
`roleAbbreviations`, `pcKeyboardDots`; en `conf["brailleViewer"]`:
`routeOnHover`, `hoverDwellTime`, `x`, `y`. Panel:
`gui/braille_panels.py` («Presentación braille»).

**Compilación.** liblouis (`liblouis.dll`, `tables/` y su licencia) está en
`data/louis` (`paths.louisDir`, `liblouis.FOLDER`), tanto desde el código
como en la versión compilada; `tools/build_data.py` lo copia a la `data`
limpia.

## 18. Audio y voces neuronales (`audio/`, `synth/piper*`)

**Reproductor** (`audio/wave_player.py`). `WavePlayer` tiene un hilo
(registrado en MMCSS «Audio») y una salida intercambiable: `_WasapiBackend`
(WASAPI compartido con `AUTOCONVERTPCM`, búfer `audio.bufferSize`) o
`_WaveOutBackend`; si la elegida (`audio.outputMode`) falla, usa la otra. Las
retrollamadas son marcas en tramas: se ejecutan cuando `played()` pasa de
su posición. `stop()` y `pause()` solo dejan peticiones y despiertan al
hilo (el COM de WASAPI solo se toca desde él). Con el dispositivo abierto y
sin audio, los reproductores con `keepAwake` escriben ruido blanco
(`audio.whiteNoiseVolume`) hasta `keepAudioAwakeSeconds`; el ruido en cola se
descarta al llegar voz. Los nombres de dispositivo son los de Core Audio;
waveOut los traduce con `DRV_QUERYFUNCTIONINSTANCEID`. Al cambiar
`OutputSettings.deviceName` cada reproductor reabre su salida en el
siguiente bloque.

**Core Audio** (`audio/core_audio.py`): dispositivos, `IAudioEndpointVolume`,
sesiones de todas las salidas (`getSessions(allDevices=True)`),
`IAudioClient` y `IPolicyConfig` (salida predeterminada). `audio/mixer.py`
agrupa las sesiones por ejecutable (`App`), gestiona micrófono, volumen
general, dispositivos, la comprobación de arranque (#3049) y los avisos de
volumen con `IAudioEndpointVolumeCallback` (los cambios propios llevan el
contexto `EVENT_CONTEXT` y no se anuncian). `audio/manager.py` lo arranca
(`initializeEarly` antes del sonido de inicio). Órdenes en
`audio/commands.py` (`install(GlobalCommands)`), diálogo y paneles en
`gui/audio_dialogs.py`.

**Atenuación** (`audio/ducking.py`): mientras dura, `_rescan` atenúa cada
segundo las sesiones nuevas; `tones.pre_playSound`/`pre_beep` la disparan
con `audio.duckForSounds` (no si los sonidos están desactivados o a volumen
0) y `speech.pre_speechCanceled` la quita al callar la voz. `duck`/`unduck`
solo cambian el estado pedido: el recorrido de sesiones (atenuación, división
del sonido de `sound_split`, sesión propia al abrir el primer flujo con
`wave_player.onFirstStream`) va en el hilo «SesionesAudio» de
`core_audio.runInSessionThread`, nunca en el núcleo (`waitSessionThread`
espera al cerrar). El mezclador cambia volúmenes con
`ducking.sessionVolume`/`setSessionVolume` (sobre el volumen original guardado
en `_saved`). `sound_split` solo devuelve el balance de las demás aplicaciones
al centro si lo había cambiado (`_appliedApps`).

**Reproductor** (`audio/wave_player.py`): si el modo pedido no abre, la
salida de reserva se conserva mientras `audio.outputMode` no cambie
(`_backendFor`); el modo preferido se reintenta al reabrir tras el cierre por
inactividad. Al cerrar la salida por cambio de dispositivo o modo o por un
error, las retrollamadas pendientes (índices) se ejecutan
(`_closeBackend(fireMarks=True)`); solo `stop()` las descarta.

**Sonidos y earcons** (`audio/tones.py`, `audio/earcons.py`). Las recetas
son notas `(hz, ms[, timbre])`; `playSound(nombre, pan)` panoramiza con
potencia constante; un `.wav` en `data/sounds/<tema>` sustituye a la receta
y `exportTheme` genera el tema en WAV. `presentation.speakObject` abre
`earcons.objectContext` (y `speakObjectProperties`, `statesContext`): ahí
suenan rol y estados y, en modo `insteadOfSpeech`, `getObjectSpeech` y
`getStatesText` omiten los textos que ya sonaron (`roleHandled`,
`stateHandled`). Fuera del contexto (copiar, lectura continua) nada cambia.

**Piper** (`synth/piper.py`, `piper_phonemizer.py`, `piper_voices.py`).
eSpeak NG (copia privada de la DLL en `data/cache/piper` para no compartir
estado con el controlador eSpeak) convierte el texto en IPA por frases; los
fonemas se traducen con `phoneme_id_map` (`^`, fonema + `_`, `$`) y el
modelo se ejecuta con onnxruntime (`input`, `input_lengths`, `scales`,
`sid`). La salida se remuestrea a 22 050 Hz con el desplazamiento de tono;
las velocidades por encima de 2,2× se completan con WSOLA
(`audio/timestretch.py`, también usado por el aumento de velocidad de SAPI 5).
`PhonemeCommand` con IPA va directo al modelo. El catálogo y las descargas
(con MD5) están en `piper_voices`; el gestor es `gui/piper_dialog.py`. En la
versión compilada se incluyen los paquetes `onnxruntime` y `numpy`.


## 19. Configuración, interfaz, complementos e instalación

**Configuración** (`config/`):

- `schema.py` define `SCHEMA_VERSION`. Cada archivo guarda `schemaVersion`; al
  cargar, `migrations.migrate()` aplica las funciones de `MIGRATIONS` (para un
  cambio incompatible: subir la versión y añadir `_vN_to_vN+1`).
- `validation.validate()` corrige tipos (con conversiones razonables), rangos
  (`RANGES`) y listas cerradas (`CHOICES`); lo que no se puede arreglar vuelve
  al valor por defecto. Las secciones desconocidas se conservan.
- `_writeJson` guarda la versión anterior como `.bak`; `_readJson` aparta un
  archivo dañado como `.corrupto` y recupera el `.bak` (`conf.recoveredFiles`,
  que `startup` anuncia).
- Capas: valores por defecto, base, perfiles activos y, encima de todo, la capa
  de `policy.json` (`config/policy.py`). `conf.isLocked()` dice si una opción
  está fijada; `ConfigPanel` desactiva su control.
- `conf.readOnly` (modo `--secure`, con `paths.setConfigDir(SYSTEM_CONFIG_DIR)`)
  impide escribir. `--config-path` usa `paths.setConfigDir`.
- Perfiles: `profileMeta.json` guarda `enabled` y `readOnly` de cada perfil;
  `post_triggerChange` avisa de cualquier disparador (lo usa `power.py`). Los
  disparadores `dominio:x` los gestiona el complemento incorporado
  `domain_profiles.py` con la URL del documento (`ValuePattern` del objeto raíz
  del modo exploración). `resetToFactoryDefaults()` se puede deshacer.

**Arranque** (`startup.py`): `runStandaloneCommand` (portable, reparación COM,
instalación silenciosa, desinstalación), `prepareConfiguration` (política,
datos de la copia instalada, carga), `registerBuiltins` tras elegir el idioma
(`domain_profiles`, `ime`, `config_plugin`, `appmodules._gsuite`), `afterCoreStarted` (avisos,
novedades, actualizaciones) y `applyConfiguration` (lo llama
`core.applyConfiguration`).

**Idioma** (`i18n.py`, `tools/i18n.py`): catálogos gettext en
`data/locale/<idioma>/LC_MESSAGES/tiresias.mo` (`paths.localeDir`; el `.pot`
y los `.po` también están en `data/locale`, pero la versión compilada solo
lleva los `.mo`); el español es el
original. `tools/i18n.py todo` extrae, fusiona y compila sin las herramientas
de GNU. Como muchas cadenas se traducen al importar, el idioma se elige antes
de importar la interfaz y cambiarlo requiere reiniciar. Los complementos
incluidos (`data/addons/whatsapp`, `data/addons/eloquence`) usan el `_` de
`tiresias.i18n`: sus cadenas se extraen al mismo catálogo `tiresias.po`.
`tools/i18n.py estado` devuelve 1 si queda alguna cadena sin traducir.

**Interfaz** (`gui/`): `system_dialogs.py` (ajustes rápidos, etiquetas, tienda,
actualización, copia portable, reparación COM, restablecer con deshacer),
`installer_dialogs.py`, `tutorial.py` (usa `input.core.post_scriptExecuted`),
`keyref.py` (referencia de todas las órdenes leyendo las clases),
`context_help.py` (F1: anclas `opt-<sección>-<clave>` del manual) y
`config_panels.py` (paneles nuevos). `ConfigPanel` admite el tipo de campo
`checklist`.

**Cuadro de Opciones** (`gui/settings.py`, revisión 1.0.6): el orden de las
categorías lo da `settings.PANEL_ORDER` (= `context_help.CATEGORY_IDS`), como
en NVDA (General, Voz, Braille, Audio, Visión, Teclado, Ratón, Revisión,
Presentación de objetos, Entrada, Modo exploración, documentos...), con
«Avanzado» al final; `getPanelIds()` lo aplica aunque los módulos registren sus
categorías en otro orden, y pone las de los complementos detrás de
«Aplicaciones». Cada opción (sección y clave) está en una sola categoría; las
categorías unidas a otras (`mixer`, `brailleDisplays`, `uia`, `objects`) se
siguen pudiendo abrir por su identificador (`PANEL_ALIASES`). El botón «Valores
de fábrica de esta categoría» llama a `SettingsPanel.resetToFactory()`: en un
`ConfigPanel` pone cada campo con `conf.defaults` y los controles propios con
`resetExtraToFactory()`; no guarda nada hasta Aceptar o Aplicar. Los controles
propios con ayuda F1 se registran en `panel._helpKeys[control] = (sección,
clave)`. `tests/test_opciones_106.py` comprueba que no hay claves repetidas, que
todas existen y se leen en el código, las teclas rápidas y el manual.

**Avisos** (`gui/message_dialog.py`, #258): ningún aviso de Tiresias usa el
cuadro nativo de Windows. `message_dialog.messageBox(texto, título, estilo,
padre)` sustituye a `wx.MessageBox` (devuelve `wx.OK`/`wx.YES`/`wx.NO`/
`wx.CANCEL`) y `message_dialog.MessageDialog` a `wx.MessageDialog` y
`wx.RichMessageDialog` (`ShowModal` devuelve `wx.ID_*`; admite
`SetYesNoLabels`, `SetOKCancelLabels`, `ShowCheckBox`...). El texto va en un
campo de solo lectura recorrible con el foco inicial; Intro pulsa el botón por
defecto (`wx.NO_DEFAULT`/`wx.CANCEL_DEFAULT` se respetan), Escape responde
Cancelar, No o Aceptar, y la letra subrayada de un botón lo pulsa también sin
Alt. `gui.messageBox`, `settings.showError` y `settings.askYesNo` lo usan; el
código nuevo no debe llamar a `wx.MessageBox`.

**Órdenes y teclado**: `config_plugin.py` (ajustes rápidos, capas con
`inputCore.manager.captureFunc`) y `gesture_layouts.py` (mapa compatible con
JAWS como gestos de instancia; exportar/importar `gestures.json`).

**Complementos**: `addons.API_BACKWARD_COMPAT_TO`, `isUntested`,
`addons.overrideCompatibility`, `inspectPackage()` antes de instalar encima.
`addon_store.py` lee primero el catálogo en línea (`addons.catalogUrl`, la
política o `complementos/catalogo.json` del servidor de distribución) y, si no
hay red o no hay servidor, la copia local (`docs/catalogo_complementos.json`,
en la versión compilada `data/docs/catalogo_complementos.json`, que genera
`tools/make_catalog.py`); descarga con SHA-256 (obligatorio en las descargas
de la red) e instala.

**Instalación**: `installer.py` (instalar, desinstalar, copia portable,
configuración del sistema; todo admite rutas y claves de prueba con
`SystemTargets`). `tools/build_installer.py` empaqueta `dist/Tiresias` en un
ZIP y crea con IExpress `Tiresias-<versión>-instalador.exe`, que lo descomprime
en `%TEMP%\TiresiasInstalador` y ejecuta `Tiresias.exe --install`. Una copia
instalada lleva `instalado.json` y usa `%APPDATA%\Tiresias` como datos
(`paths.isInstalledCopy`, `installer.seedUserData`). `updates.py` comprueba
en hilos propios el manifiesto `actualizacion.json` del servidor de
distribución (`DISTRIBUTION_URL`, `update.serverUrl` o la dirección completa
de `update.checkUrl`; sección 28); `docs/actualizacion.json` es solo la copia
de referencia que deja `tools/publicar.py`. `comrepair.py` vuelve a registrar
las DLL de accesibilidad.
`install()` rechaza una carpeta no vacía que no sea una copia de Tiresias, vacía
`data` solo si la carpeta era una copia instalada y quita los accesos directos
y el inicio automático anteriores si se desmarcan (`startOnLogon=None` no lo
toca). `seedUserData` sobrescribe símbolos, sonidos y tablas cuando cambia la
versión (marca `datos_programa.json` en la carpeta de datos). Las copias
elevadas (`--install-silent`, `--uninstall`, `--repair-com`) reciben
`--no-elevate` para no pedir permiso en bucle; `--all-users 0/1` fija el modo, y
`--launch`/`--start-on-logon` los hace el proceso sin elevar.
`startup.runStandaloneCommand` registra esas órdenes en `logs/ordenes.log`
(en la copia que se actualiza para `--apply-update`, en `%APPDATA%\Tiresias`
para `--install-silent` y en `%TEMP%` para la desinstalación). `--uninstall`
solo cierra la copia en ejecución si su ejecutable está dentro de la carpeta
que se desinstala (`shouldCloseRunning`).

**Vigilante** (`watchdog.py`): el núcleo llama a `CoEnableCallCancellation`; si
se bloquea, el vigilante llama a `CoCancelCall` y, si sigue bloqueado tras
`advanced.watchdogRestartTimeout`, guarda la configuración, inicia otra copia y
termina el proceso.

## 20. Objetos, eventos y API de accesibilidad (`a11y/`, `objects/`)

**Elección de API por ventana** (`a11y/api_choice.py`): `chooseAPI(hwnd)`
devuelve `uia`, `msaa` o `java` y lo guarda en caché (la caché la lee también
el hilo de ganchos con `cachedAPI`). Orden: ventanas `SunAwt*` con JAB →
`objects.uiaClasses` → `BAD_UIA_CLASSES` + `objects.msaaClasses`, la consola
clásica (si `uia.preferUIAForConsoles` es falso) y la cinta `NetUIHWND` de
Office ≤ 2013 → controles comunes y documentos web (siempre UIA, porque el modo
exploración es UIA) → ventanas sin proveedor UIA propio
(`UiaHasServerSideProvider`) que implementan IA2 → UIA. El manejador de foco
UIA descarta el foco de las ventanas que no son UIA (lo resuelve su API y, por
si acaso, `winevents.scheduleFocusCheck`). `objects.uia.getFocusObject()` y
`getObjectFromPoint()` ya devuelven el objeto de la API que corresponda.

**Menús Win32 (`#32768`) de cualquier proceso** (contextuales, desplegables de
la barra, submenús y menú del sistema): siempre MSAA (`api_choice.MENU_CLASS`),
como NVDA. Con un menú abierto el foco del teclado (`hwndFocus`) sigue en el
control que lo abrió y UIA no sigue el foco dentro del menú (`GetFocusedElement`
da la lista); en la 1.0.4 los menús sobre una lista `SysListView32` (escritorio,
Papelera, SocialRSS) solo decían «Contexto menú». Ahora:
- `api_choice.focusWindow(element)`: si el hilo en primer plano está en modo
  menú (`GUI_INMENUMODE`/`GUI_POPUPMENUMODE`) cuenta el menú desplegado más alto
  (`activeMenuWindow`, el submenú si lo hay) y, con solo la barra activa, la
  ventana del elemento del evento o `hwndMenuOwner`. Lo usan el foco UIA (que
  así no repite lo que anuncia MSAA) y `getFocusObject` (el elemento marcado,
  por `accFocus`).
- `winevents.onWinEvent`: el inicio de un menú `#32768` pasa si es del proceso
  del foco o de la ventana activa, aunque el foco sea de una ventana UIA; los
  inicios y finales de menú UIA de ventanas MSAA se descartan (`uia_handler._isMSAAWindow`).
- Elementos: nombre sin el atajo (`«Copiar\tCtrl+C»` → «Copiar»), atajo con la
  letra de acceso («c Ctrl+C»), estados (marcado, no disponible, submenú) y
  posición «N de M» (`_siblingPosition`).
- Pruebas: `tests/test_menus_win32.py` (con `tests/menu_win32_probe.py`: un menú
  wx real de otro proceso, sin activarlo, recorrido con `WM_KEYDOWN` y los
  WinEvents de verdad).

**MSAA e IA2** (`a11y/msaa.py`, `objects/iaccessible.py`): interfaces IA2
declaradas a mano con comtypes (IAccessible2, IAccessibleText,
IAccessibleAction, IAccessibleValue, IAccessibleTableCell; el orden de la
tabla virtual importa). `IAccessibleObject(pacc, childId)` traduce roles,
estados (MSAA + IA2), atributos (`xml-roles`, `level`, `sort`,
`placeholder`…), posición en el grupo y acciones. Texto: `IA2TextInfo` (IA2),
`EditWindowTextInfo` (campos `Edit`/`RichEdit` y derivados con mensajes `EM_*`;
lo usan también los objetos UIA sin patrón Text) y `ConsoleTextInfo`.
**Navegación mixta**: al subir desde MSAA hasta una ventana UIA se devuelve el
objeto UIA de esa ventana; `UIAObject._wrap` convierte los hijos cuya ventana
es MSAA o Java. `a11y/win32ctl.py` lee columnas y encabezados de
`SysListView32` con memoria en el proceso de destino (`VirtualAllocEx`,
estructuras de 32 y 64 bits); los mensajes del sistema (`EM_GETSEL`,
`WM_GETTEXT`) usan punteros locales porque Windows los copia.

**WinEvents** (`a11y/winevents.py`): `WIN_EVENTS` cubre sistema (alerta,
menús, primer plano, escritorio), consola (`EVENT_CONSOLE_*`), objetos
(0x8002–0x8019) e IA2 (0x102–0x121). `onWinEvent` filtra en el hilo de ganchos
sin llamadas entre procesos (caché de API, proceso del foco) y encola; en el
núcleo se crea el objeto con `AccessibleObjectFromEvent` y se despacha:
`gainFocus`, `nameChange`, `valueChange`, `stateChange`, `show`, `hide`,
`selection`, `selectionAdd/Remove/Within`, `caret` (también `OBJID_CARET`),
`menuStart/End`, `alert`, `liveRegionChange`, `textChange`,
`activeDescendantChange` y `sortChange` (atributo IA2 `sort`).

**Eventos UIA nuevos** (`a11y/uia_handler.py`): selección
(añadir/quitar/invalidar), `layoutInvalidated`, arrastrar y soltar,
`activeTextPositionChange`, `sortChange` (cambio de `AriaProperties` del foco,
de sus antecesores o de un encabezado del mismo proceso, #10890) y
`nameChange` de elementos con `LiveSetting` (región viva implícita; no para
las clases `NetUI*` de Office, que publican «asertivo» en todos sus elementos:
`isImplicitLiveRegion`, si no el recuento de palabras de la barra de estado de
Word se leía tras cada palabra escrita). El documento UIA de Word (`_WwG`) no
publica el patrón de valor: `UIAObject._isEditableWordDocument` mira el
atributo de texto `IsReadOnly` del rango del documento (verdadero en la vista
de lectura, la vista protegida y el panel de lectura de Outlook) para darle el
estado editable, y así `browse.browseModeKind` devuelve `lazyText` (modo foco
sin búfer) en Word editable y `text` en los demás. Los eventos de
selección, menús, ventanas y arrastre solo pasan si son del primer plano.
**Proveedores lentos** (#20654): si despachar un evento tarda más de
`objects.slowProviderThresholdMs`, `markSlowProcess` hace que durante 10 s se
descarten en el hilo de UIA los eventos secundarios de ese proceso.

**Java Access Bridge** (`a11y/jab.py`, `objects/jab.py`): carga diferida de
`WindowsAccessBridge-64.dll` al aparecer la primera ventana Java (#20833),
búsqueda en JAVA_HOME, registro, Program Files, PATH y junto al ejecutable;
hilo propio con bucle de mensajes (`Windows_run`); las retrollamadas solo
encolan y se ignoran si la ventana Java no está en primer plano (#14344).
`enableBridge()` usa `jabswitch -enable` o escribe
`~/.accessibility.properties` (siempre preguntando al usuario).

**Sistema** (`a11y/system.py`): `SPI_SETSCREENREADER` al arrancar (se restaura
al salir si estaba desactivado), registro opcional en
`...\Accessibility\ATs\tiresias` (HKCU y HKLM si hay permisos),
`isLockScreenActive()` (WTS + LockApp en primer plano, caché de 0,5 s) y
`isSecureObject()/filterSecure()`, que aplican `events.executeEvent`,
`api.setNavigatorObject`, la navegación de todos los tipos de objeto y
`getObjectFromPoint`. Limitación: sin servicio ni `uiAccess`, el escritorio
seguro (UAC, Ctrl+Alt+Supr, inicio de sesión) no se puede leer; solo se avisa
al entrar y se vuelve a leer el foco al salir.

**Consolas** (`objects/terminal.py`, `console_reader.py`): `Terminal` (rol
`TERMINAL`) guarda la última pantalla por ventana en `_snapshots` (no se lee al
crear el objeto), agrupa eventos (60 ms, como mucho 0,3 s) y calcula el texto
nuevo con `computeNewText` (líneas + caracteres ampliados a palabras). Los
caracteres escritos se encolan y se anuncian solo cuando aparecen en pantalla
(contraseñas). `console_reader.readScreen()` lee solo la ventana visible; si
el proceso ya tiene consola, usa un auxiliar sin consola
(`tiresias.pyw --console-helper`, JSON por tuberías, tiempo de espera).

**Texto editable** (`objects/behaviors.py`): sin `sleep` en el núcleo; tras
enviar la tecla, `_startWatch` comprueba el cursor con `callLater` cada 15 ms
(o al llegar `event_caret`) hasta `caretMovementTimeout`. Frases
(Alt+flechas), Intro en campos multilínea, Mayús+Retroceso/Supr, detección de
selección hecha fuera de Tiresias y cursor virtual para campos sin cursor
accesible (`EditableTextNoCaret`). Otros comportamientos: `Dialog`/`WebDialog`
(`collectDialogText`), `SelectableItem`/`ListContainer` (#1839,
`Control+Tiresias+E`), `Toast`, `ListViewItem`/`UIATableRow`
(`objects/listview.py`, `Control+Tiresias+n`, `Control+Alt+flechas`).
Opciones: secciones `objects`, `terminal`, `java` y `system` (registradas en
`a11y/__init__.py`), en las categorías «Avanzado» (API, consolas, Java y
Windows) y «Presentación de objetos» (anuncios automáticos y campos de edición).

**Longitud máxima y caracteres restantes** (`objects/text_limits.py`, foros
1.17): `reportRemaining` (orden `Tiresias+Control+L` en
`global_commands_extra.py`) y `scheduleCheck`, que `EditableText` y
`EditableTextNoCaret` llaman en `event_typedCharacter` (60 ms después se lee
la longitud y `warningFor` decide el aviso según `objects.maxLengthWarning`
y `maxLengthWarningThreshold`). Chrome devuelve U+FFFC como texto de un
campo vacío: no se cuenta.

**Puente UIA → IAccessible2** (`a11y/ia2_bridge.py`). Comprobado con Chrome y
Edge (2026): UIA no publica `src` de las imágenes, `maxlength`, el idioma en
Firefox ni `abbr`; IA2 sí (`src`, `maxlength`; Firefox además `locale` y
`abbr`; Chrome no implementa `IAccessible2::locale` pero rellena
`UIA_CulturePropertyId` heredado del antecesor con `lang`, y no publica `abbr`
por ninguna API). `iaccessibleForElement` prueba LegacyIAccessible y el
RuntimeId (no en Chromium, donde no llevan al objeto), el foco del documento
(`accFocus`), el punto central y, por último, el **camino de hijos**: la
vista completa de UIA (no la de control: Chrome omite en ella los
contenedores genéricos) coincide hijo a hijo con IA2 desde el documento que
devuelve `AccessibleObjectFromWindow` de la ventana del RuntimeId.
`PathResolver` comprueba el número de hijos en cada nivel, pide el árbol UIA
completo de una vez (`rawPath`) y usa `childAt` (un hijo por llamada, sin
convertir el VARIANT con información de tipos): unos 1 ms por imagen, con un
presupuesto de 1,5 s por construcción del búfer. Lo usan
`UIAObject.IA2WebAttributes`, `maxLength`, `graphicFileName`, `language` y
`tableHeaders` (abbr en Firefox). `getLocale` lee `IA2Locale`.

**Presentación** (`presentation.py`): `objectLanguage` +
`withNameLanguage` leen el nombre del objeto en su idioma
(`presentation.reportObjectLanguage`, con el cambio automático de idioma;
`UIAObject.language` = Culture o IA2 `locale` en Gecko;
`IAccessibleObject.language` = `locale`); `_graphicName` da a las imágenes
sin nombre (o con la invitación de Edge/Chrome) su nombre de archivo y «sin
descripción»; `containerDescription` añade la descripción de grupos y
regiones al anunciar los antecesores del foco
(`presentation.reportGroupDescriptions`). Braille: `objectProperties` usa
`brailleLabel` y `brailleRoleText` (aria-braillelabel y
aria-brailleroledescription, de AriaProperties o de los atributos IA2). Los
guiones blandos se quitan en `speech.processText` y se ocultan en braille
(segmento `hidden` de `braille/tables._segments`).

**Detalles comprobados en la prueba en vivo con ganchos reales:**
- Los documentos UIA editables que no son web ni Word (RichEdit,
  RichTextBox...) tienen rol `EDITABLETEXT` + `MULTILINE`
  (`UIAObject._isPlainEditableDocument`): «edición multilínea», sin tocar el
  modo exploración (`browse.browseModeKind` solo mira `DOCUMENT`).
- `UIATextInfo.pageNumber` devuelve `None` si la «página» es el documento
  entero (controles sin paginación). El último formato y la sangría se
  recuerdan por control con una clave estable (`formatting._stateKey`:
  RuntimeId o ventana), nunca con `id()`.
- Expandir a carácter o palabra con el cursor tras el último carácter deja el
  rango vacío (UIA y `OffsetsTextInfo`): «en blanco», igual que los saltos de
  línea.
- `ime.py` guarda un puntero COM propio al manejador de
  `TextEdit_TextChanged`: si el contador llega a cero al quitar el registro,
  comtypes vacía las interfaces del `COMObject` y el siguiente registro falla.
- La ventana principal oculta (`objects.base.isHiddenMainWindow`) nunca
  acepta el foco (`shouldAllowFocusEvent`). Un menú emergente sin elemento
  marcado toma el foco tras `menuStart` (`_focusMenuIfNeeded`), y
  `menuStart`/`menuEnd` se aceptan del proceso de la ventana activa real.

**Selección, casillas y controles Win32 con MSAA** (regresiones de la 1.0.2/1.0.3):
- `SelectableItem` (`objects/behaviors.py`) no anuncia nada de inmediato: los
  eventos `selection`, `selectionAdd` y `selectionRemove` esperan
  `SELECTION_SETTLE_MS` (120 ms) y se descartan si el foco ha cambiado entretanto
  o hace menos de `SELECTION_FOCUS_WINDOW` (0,3 s). Con las flechas, selección y
  foco llegan en cualquier orden y solo habla el foco. En el elemento con el foco
  (Control+Espacio) se usa `speakObjectProperties(states=True, reason=CHANGE)`,
  que solo dice la diferencia con `presentation._lastStates`: si el `stateChange`
  ya lo dijo, no se repite. La voz de un elemento seleccionado sin foco lleva el
  validador `_focusUnchanged(seq)` (`presentation.speakObject(..., isValid=)`).
- `IAccessibleObject.states` quita el «pulsado» momentáneo de MSAA
  (`_isMomentaryPress`): casillas, botones de opción y botones de la clase
  `Button`. Conservan «pulsado» los botones de barras de herramientas e IA2.
- `ListViewItem.positionInfo` cuenta con `LVM_GETITEMCOUNT` (el recuento de
  hijos MSAA incluye el encabezado). `SysTreeViewItem` oculta el valor MSAA (el
  nivel desde 0) y calcula «N de M» y el nivel con
  `win32ctl.treeViewItemPosition` (`TVM_MAPACCIDTOHTREEITEM`, `TVM_GETNEXTITEM`;
  en ventanas propias, de una vez en el hilo de la interfaz).
- «selección múltiple» (`presentation.reportMultiSelect`) solo en el
  contenedor y al entrar en él (`FOCUSENTERED`); UIA solo toma el estado MSAA
  heredado en `_MULTISELECT_CONTAINERS`. Los botones de opción UIA seleccionados
  tienen también `CHECKED` («marcado»). Pruebas: `tests/test_seleccion_casillas.py`.
- Celdas de las filas (vista Detalles del Explorador de Windows 11 y de los
  diálogos Abrir/Guardar: las flechas llevan el foco UIA del archivo a sus
  columnas `UIProperty`, campos de solo lectura sin cursor). Las órdenes de
  flechas de `EditableTextNoCaret` no usan el cursor virtual en una celda de
  solo lectura cuyo padre es una fila (`_isRowCell`): envían la tecla y habla
  el foco. Antes, 40 ms después cortaban la celda nueva con «en blanco» o un
  carácter de la anterior. Además, `_afterKey` y `_startWatch` guardan el
  número de cambio de foco (`_focusChange`) y no anuncian nada si la tecla ha
  movido el foco. Con arriba/abajo dentro de una columna, la celda dice antes
  el nombre de su fila (`reportFocus`, `_focusHistory`) y `SelectableItem` no
  la anuncia como sugerencia. Esas celdas tienen `presentAsCell` (propiedad de
  `AccObject`, `False` por defecto): `presentation.getObjectSpeech` y
  `braille.presenter.objectProperties` las leen como celdas, «Tipo: Excel.CSV»,
  sin «edición» ni «solo lectura» y sin marcas invisibles de dirección.
- Rejillas: `UIAObject.role` da `TABLECELL` a los `Custom` con GridItem o
  TableItem (DataGridCell de WPF; antes «personalizado pulsable»), y las
  descripciones que son un nombre de tipo .NET o la clase
  (`objects.base.looksLikeTypeName`; «DataGridViewTextBoxCell(DataGridViewCell)»
  de WinForms) no se leen. Pruebas: `tests/test_celdas_filas.py`.

## 21. Visión, OCR, inteligencia artificial y herramientas extra

- `imaging.py`: imagen BGRA común (`Image`), captura (`captureRect`), PNG sin
  dependencias, archivos con `BitmapDecoder`, PDF con `Windows.Data.Pdf`
  (una página por bucle asyncio) y portapapeles (`CF_DIB`, `CF_HDROP`). Con la
  cortina o la lupa activas (`screenIsAltered`) la captura se compone ventana a
  ventana con `PrintWindow` (#19164). Las ventanas propias que se superponen
  (resaltado, lupa) se excluyen de las capturas con `SetWindowDisplayAffinity`.
- `ocr.py`: motores intercambiables (`ENGINES`: Windows OCR y Tesseract por
  línea de órdenes con salida TSV), orígenes (navegador, ventana, pantalla,
  archivo, PDF, portapapeles), refresco del visor y `ContinuousReader`
  (compara líneas con `difflib` y lee solo las nuevas). Todo el trabajo va en
  hilos `OCR*`; los resultados vuelven al núcleo.
- `ocr_document.py`: `OcrDocument` es un `BrowseModeDocument` con
  `fixedBufferKind = "ocr"` y carga síncrona; su `OcrBuffer` crea un nodo por
  palabra con su rectángulo. `gui/ocr_viewer.py` registra el documento en
  `tree_interceptor.runningTable` con el `hwnd` del visor, así el modo
  exploración y el cursor de revisión (modo documento) funcionan sobre el
  resultado. El cursor del cuadro de texto se sincroniza con `onCaretMoved`.
- `magnifier.py`: vistas `fullscreen` (`MagSetFullscreenTransform`), `docked`
  (control «Magnifier» en una ventana registrada como barra de aplicación),
  `lens` y `spotlight` (lente centrada más un velo con `SetWindowRgn`). Las
  vistas en ventana se refrescan con un `wx.Timer` (33 ms). La geometría es
  pura (`computeViewOrigin`, `lensRect`) y se prueba sin pantalla. Todo lo de
  Magnification.dll se ejecuta en el hilo de la interfaz; `terminate` espera a
  la interfaz con `runOnGuiAndWait`.
- `vision.py` + `gui/highlighter.py`: varios rectángulos por grupo
  (`focus`, `navigator`, `browseMode`, `mouse`) con refresco periódico por
  `queue_handler.callLater`; cortina con confirmación, sonido opcional y aviso
  al arrancar (#10692).
- `ai/`: `providers.py` (Anthropic, OpenAI, Gemini y local compatible con
  OpenAI; `urllib` en hilos propios; las respuestas de Claude se reenvían
  completas en `Message.raw`), `keys.py` (DPAPI, `data/config/aiKeys.json`),
  `assistant.py` (sesiones de chat, describir, resumir, preguntar, etiquetas,
  ayuda con el manual, CAPTCHA), `translate.py` (también un filtro
  `speech.filter_speechText` con caché para traducir todo lo que se dice),
  `agent.py` (una acción JSON por paso, confirmación en `gui/ai_dialogs.py`)
  y `camera.py` (MediaCapture + FaceDetector, análisis puro en
  `analyzeFrame`). El panel «Inteligencia artificial» se registra en
  `ai.initialize()`.
- IA sobre páginas y PDF (foros 3.10, 6.3, 6.6, 10.6):
  - `ai/explorer.py`: «explorar la página» (`Tiresias+Mayúsculas+E`); manda
    en una `ChatSession` la estructura del búfer (`bufferStructure`) o de la
    ventana, la tabla de teclas reales (`keyTable` con `gesturesFor` y las
    asignaciones del usuario), el texto y, con `exploreWithScreenshot`, una
    captura.
  - `ai/labelstore.py`: textos generados para elementos sin nombre en
    `data/config/aiLabels.json` (`{ámbito: {huella: texto}}`; ámbito = documento
    para imágenes, sitio para controles). `fingerprint(node)` no depende del
    desplazamiento (tipo, id, URL del enlace, tamaño, contenedor con nombre y
    hermanos iguales previos) y es igual en reconstrucciones parciales.
    `BufferLoaderMixin.configureBuffer` pone `VirtualBuffer.aiLabels`
    (`Lookup`) y `_makeNode` da ese nombre a los nodos sin nombre.
  - `ai/autolabel.py` (`autoLabeler`): escucha `api.post_focusChange` y
    `api.post_reviewMove` (cursor del modo exploración); con `autoLabel`
    activo espera `DWELL_MS`, comprueba que el usuario sigue allí y pide la
    etiqueta en un hilo `IA-autoetiqueta` (una a la vez, máximo por hora,
    una vez por elemento). Guarda con `labels.setLabel` (aplicaciones) o
    `labelstore` + `scheduleRebuild` (búfer).
  - `ai/reading.py`: orden de lectura propuesto por la IA (permuta los hijos
    del contenedor del cursor; confirmación en `ai_dialogs.showOrderConfirm`)
    y `AltTextJob`, que recorre las imágenes sin nombre (ScrollIntoView,
    `callLater`, captura en hilo propio) y guarda en `labelstore`.
  - `ai/captcha.py`: detección local (`captchaNodes`/`detect`) llamada desde
    `BufferLoaderMixin._notifyNewNodes` tras cada construcción o
    actualización parcial y desde `post_focusChange`; `jumpToAudio` (casilla
    → botón de audio → reproducir; en reproducir, `activateAt` + `duck`);
    `duck` baja `WavePlayer.volume` del sintetizador o registra un
    `filter_speechSequence` que calla la voz, y `restoreVoice` lo deshace con
    `callLater`.
- `mouse_keys.py`: complemento global incorporado (`MouseKeysPlugin`) que solo
  responde a las teclas mientras el modo está activo; posiciones por
  aplicación en `data/config/mousePositions.json`.
- `audio_export.py`: usa `AudioSynthDriver.runInWorker` para llamar a
  `_synthesizeSegment` en el hilo del sintetizador y guardar un WAV.
- `vision_commands.py`: órdenes (instaladas en `GlobalCommands`), el menú
  «Visión e IA» y `initialize`/`terminate` (llamados desde `core.py`).

**Voz por RDP/Citrix y display model.** La voz y el braille por Escritorio
remoto (RDP), Citrix y Horizon se hacen con una DLL nativa propia (sección
23), que Citrix Workspace carga por su adaptador de DVC de Microsoft. El
display model GDI no: necesita enganchar las llamadas GDI de otros procesos
(inyectar código). La alternativa es la revisión de pantalla por OCR
(`ocr.screenReview`), que da un documento con la posición de cada palabra, y
el acceso remoto de Tiresias entre equipos.

## 22. Productividad y API de control (`productivity/`, `controller/`)

**Productividad** (`productivity/`): complemento global incorporado
`ProductivityGlobalPlugin` (se registra con `pluginHandler.registerBuiltin` en
`productivity.initialize()`, antes de cargar los complementos). Al ser un
complemento global va el primero en la cadena de eventos y de órdenes: sus
gestos tapan los de módulos de aplicación y modo exploración, así que deben
estar libres en todo el código.

- `text_context.py`: texto completo y cursor del contexto actual
  (`BrowseContext` sobre el búfer del modo exploración, `EditContext` sobre el
  patrón Text del foco; desplazamientos en caracteres desde el principio).
- `text_analyzer.py`: funciones puras (`analyze`, `formatIssues` con tramos
  `UNIT_FORMAT`). Los pares se comprueban por párrafo. El aviso por línea se
  engancha a `objects.behaviors.post_caretMoved` (campos de edición y Word:
  después de que la espera del cursor termine y se lea la línea nueva) y a
  `input.core.post_scriptExecuted` (órdenes síncronas del modo exploración de
  `LINE_SCRIPTS`); solo analiza el párrafo del cursor y encola el sonido
  (`WaveFileCommand`) y la descripción detrás de la lectura de la línea.
- `notifications.py`: historial en memoria y reglas
  (`data/config/reglas_notificaciones.json`). El complemento intercepta
  `event_notification`, `event_liveRegionChange` y `event_windowOpened` de
  ShellExperienceHost: guarda y, según la regla, no llama a `nextHandler`
  (silencio, solo braille) o corta la voz antes.
- `watch.py`: `WatchManager` sondea con `callLater` (objetos por UIA; regiones
  con `imaging.captureRect` + `ocr.recognizeImage` en un hilo propio) y anuncia
  `changedText` (solo lo nuevo).
- `window_find.py`: `FindAllBuildCache` sobre la ventana en primer plano.
- `text_bookmarks.py`: posición + contexto, `relocate` los reubica
  (`data/config/marcadores_texto.json`).
- Interfaz: `gui/productivity_dialogs.py` (historial, reglas, vigilancias,
  marcadores, paneles «Productividad» y «Programas externos»).

**API de control** (`controller/` en la raíz y `src/tiresias/controller/`):
servidor RPC `ncalrpc` compatible con el NVDA Controller Client. El contrato
está en `controller/src/tiresiasController.idl` (interfaces `NvdaController`,
`NvdaController2`, `NvdaController3` con los mismos UUID y orden que NVDA, y
`TiresiasController`, propia). `controller/build.py` compila con MIDL y MSVC
(CRT estático) y deja los binarios en `data/controller` (`paths.controllerBinDir`,
también en la versión compilada): `x64/tiresiasControllerServer.dll` (servidor; lo carga
`tiresias/controller/server.py` con ctypes y llama a las retrollamadas de
`TcsCallbacks` en hilos RPC), `x64|x86/tiresiasControllerClient.dll` (cliente
para desarrolladores; exporta `tiresiasController_*` y `nvdaController_*`,
prueba `TiresiasCtlr.<sesión>.<escritorio>` y luego `NvdaCtlr...`) y
`x64/tiresiasNvdaWindow.exe` (ventana oculta `wxWindowClassNR`/«NVDA» que exige
Tolk, en un proceso aparte porque NVDA mata al dueño de esa ventana al
arrancar).

`tiresias/controller/__init__.py`: los manejadores RPC nunca tocan
accesibilidad, solo encolan en el núcleo (`speech.speak` con origen
«external», `braille.handler.message`). `speakSsml` síncrono espera en el hilo
RPC y reenvía las marcas (`tcs_ssmlMarkReached`) desde ese mismo hilo. El
punto de conexión de NVDA (`NvdaCtlr.*`) no lo abre nunca el proceso de
Tiresias: un punto ncalrpc no se puede soltar sin terminar el proceso
(`RpcMgmtStopServerListening`/`RpcServerUnregisterIf` no cierran el puerto;
comprobado) y NVDA lo necesita libre al arrancar. Lo atiende
`tiresiasNvdaWindow.exe /serve <NvdaCtlr...> <TiresiasCtlr...>`, que reenvía
por la interfaz privada `TiresiasRelay` (`controller/src/tiresiasRelay.idl`,
con el PID original; el servidor solo la acepta del PID fijado con
`tcs_setRelayPid`; las marcas SSML vuelven por la retrollamada
`relayOnSsmlMarkReached` y el auxiliar las entrega desde el hilo de la llamada
original). `_updateWindow` (al aplicar opciones y cada 15 s) arranca, reinicia
o cierra el auxiliar (ventana y/o punto de conexión según las opciones) y no lo
arranca nunca con NVDA en ejecución ni en espera; `releaseNvdaEndpoint` lo
cierra al instante desde la vigilancia de `coexist`. La DLL del servidor
exporta también un cliente de NVDA (`tcs_nvda*`, `server.nvdaClient()`) para
los anuncios en espera. Desactivar la API (o estar en espera) hace que las
llamadas devuelvan 1062. Documentación pública: `docs/api_control.md`.


## 23. Módulos de aplicación (`appmodules/`) y herramientas de sistema

**Carga.** `appmodules/handler.py` elige el módulo por el ejecutable:
`EXECUTABLE_ALIASES` asocia nombres no importables o compartidos
(`notepad++` → `notepadplusplus`, `calculatorapp` → `calculator`,
`searchapp`/`startmenuexperiencehost` → `searchhost`, editores derivados de
VS Code → `code`...; los complementos usan `registerExecutableAlias`). Los
archivos que empiezan por `_` son de apoyo y nunca se cargan como módulo.
`getAppNameFromHost` da el nombre real de las aplicaciones alojadas
(`javaw` por su `-jar` o clase principal, `wwahost` por su AUMID) y
`getAppModuleForObject` (llamado desde `AccObject._get_appModule`) usa el
proceso de la ventana raíz, salvo en `ApplicationFrameHost`, donde toma el
proceso de la `CoreWindow` (Calculadora, Configuración...).

**Puntos de extensión del `AppModule`.** `chooseObjectClass`,
`event_NVDAObject_init(obj)` (tras las superposiciones; puede fijar
propiedades: `obj.name = ...` gracias a `AccObject.allowPropertyOverrides`,
que guarda el valor en `_propOverrides`), `shouldProcessEvent(evento, obj)`
(filtro previo a toda la cadena en `events.executeEvent`), `getStatusBar()` /
`getStatusBarText()` (usados por `api.getStatusBar` y la orden de barra de
estado; `api.statusBarText` incluye el estado de los conmutadores) y
`sleepMode`. El modo dormir permanente se guarda en `appModules.sleepApps`
(`handler.setSleepMode`); convive con el modo dormir por perfil de
`global_commands_extra.py`.

**Office.** `_office.py` obtiene el modelo de objetos con
`AccessibleObjectFromWindow(OBJID_NATIVEOM)` (instancia propia de
`oleacc.dll`, porque otros módulos fijan otros `argtypes` en
`ctypes.oledll.oleacc`) o `GetActiveObject` (Outlook). **Nunca** se llama
desde el núcleo: `callAsync(func, *args, callback, onError, timeout)` ejecuta
en un hilo MTA propio con tiempo máximo y devuelve el resultado por
`queue_handler`; si Office no responde se abandona el hilo (`OfficeBusy`).
Las funciones `om_*` de `_word.py`, `_excel.py` y `_ppt.py` devuelven datos
de Python (no objetos COM) y las de presentación son puras y probadas en
`tests/test_appmodules.py`. Superposiciones: `WordDocument` (ventana `_WwG`,
también en Outlook), `ExcelCell` (`XLSpreadsheetCell`; los títulos se leen por
el patrón Grid de UIA, válido en hojas protegidas), `SlideThumbnail` y
`SlideShowWindow`. Los títulos fijados se guardan en
`data/config/officeHeaders.json` (`_headers.py`), sin tocar los documentos. Las celdas vigiladas de Excel se guardan por ruta del libro en
`data/config/excelWatched.json` (`_watched.py`) y se recuperan al leer la
primera hoja del libro (`AppModule.loadWatched`).

**Peticiones de ofimática (foros 3.3–3.6 y 3.9).**
- Excel (#901): `_excel.om_lineCells` lee la fila o columna activa (Value2 en bloque y `Text` por celda, títulos de la fila/columna fijada) y `om_cellFull` el contenido completo para el visor; la presentación es pura (`lineSpeech`, `lineViewerText`, `cellViewerText`). Opciones `officeExcel.readLineFrom`, `readLineSkipBlank` y `readLineHeaders`.
- Word (#7742): `_word._listData` añade a `om_lineInfo`/`om_listInfo` el inicio (`List.Range.Start`, identifica la lista) y el número de elementos; `listTransition` decide «lista con N elementos» / «fuera de lista» con el inicio guardado en `AppModule._lastList`. `WordDocument.script_caret_moveByParagraph` repite el patrón de las líneas y `om_listItemMove` recorre párrafos con `Next`/`Previous` dentro de la misma lista.
- PowerPoint: el modelo de objetos no da el OMML. `_mathSuspect` marca las formas sospechosas (letras matemáticas o fuente «Cambria Math») y `presentationEquations` lee `ppt/slides/*.xml` del .pptx (del archivo si está guardado, con caché por fecha y tamaño; si no, de una copia `SaveCopyAs` temporal con caché por firma de las formas). `slideXmlEquations` salta `mc:Fallback` y convierte `a14:m` con `mathpres.omml`. `mathpres.plugin.script_interactWithMath` pregunta antes a `appModule.interactWithMath(focus)`, que PowerPoint implementa (`om_mathTargets`).
- Outlook: `om_attachments` (sin los adjuntos ocultos, `PR_ATTACHMENT_HIDDEN`) y `om_saveAttachment` (por `EntryID` e índice comprobando el nombre); abrir guarda en `data\temp\adjuntos\adjunto-*` (`paths.tempDir`) y usa `os.startfile`, salvo extensiones bloqueadas.
- Google Workspace: `appmodules/_gsuite.py` es un complemento global incorporado (`startup.registerBuiltins`). Detecta por URL (`domain_profiles.documentUrl`) o título; superpone `SheetsCellEditor` al editor `waffle-rich-text-editor` y, tras cada tecla de movimiento (que delega en la orden de texto heredada), lee el cuadro de nombre (`t-name-box`) y la barra de fórmulas (edición `cell-input`). `SheetState` aprende las celdas vistas y guarda por hoja (documento y `gid`) la fila/columna de títulos y los títulos en `data/config/googleSheetsHeaders.json`. `AriaGridCell` cubre las cuadrículas ARIA reales (`GridPattern.GetItem`).

**Gráficos.** `_chart.py` convierte el `Chart` de Office (común a Excel, Word y
PowerPoint) en datos de Python (`readChart`) y `ChartNavigator` los recorre
sin volver a Office. `ChartNavigationMixin` (heredado por los `AppModule` de
los tres programas) asocia las flechas, Inicio, Fin, Espacio, Intro, T, E, L y
Escape como **gestos de instancia** del módulo solo mientras se navega; se
quitan al salir o al cambiar el foco (`api.post_focusChange`). Tonos con
`tones.beep` en escala logarítmica (opciones `charts.pointTones` y
`charts.toneDuration`).

**Otros apoyos.** `_chat.py` (`ChatAppModule`: Alt+1..0, filtro de avisos por
categoría y repetición, limitador de ráfagas), `_media.py` (canción nueva por
título de ventana, con temporizador del núcleo), `_ide.py` (IntelliSense y
edición de líneas), `_scintilla.py` (texto de Scintilla con mensajes `SCI_*`
y búfer remoto de `_procmem.py`) y `putty.py` (texto por «Copiar todo» con
restauración del portapapeles).

**Herramientas de sistema.** `system_tools.py` enumera ventanas
(`listWindows`, sin las encubiertas), procesos (`listProcesses`, con psutil,
fuera del núcleo) e iconos de la bandeja (`collectTrayIcons` y
`activateTrayIcon` abren el desplegable de iconos ocultos con temporizadores,
sin bloquear). La interfaz está en `gui/app_dialogs.py` (`ItemListDialog`,
lista con filtro, tipos y acciones, reutilizada por las listas de elementos
de Office) y las opciones en `gui/apps_panel.py` (panel «Aplicaciones»).

## 24. Voz y braille por Escritorio remoto (`remote/rdp*.py`, `rdp/`)

Petición de NVDA #3564 (equivalente a RDAccess, código propio). El Tiresias de
dentro de una sesión RDP envía su salida al Tiresias del equipo cliente por un
canal virtual dinámico llamado `TiresiasRdp`. Los mensajes son los del acceso
remoto (sección 13: JSON por líneas, `remote/serializer.py`) y se reutilizan
`LeaderSession`/`FollowerSession` y `TiresiasMachine`.

```
[sesión remota]                         [equipo cliente]
Tiresias (RdpServerSide)                mstsc.exe + tiresiasRdpClient.dll      Tiresias (RdpClientSide)
FollowerSession --WTSVirtualChannel--> IWTSPlugin/IWTSVirtualChannelCallback --\\.\pipe\TiresiasRdp.<sesión>--> LeaderSession por ventana
            <-- client_joined, set_braille_info, braille_input, (client_left de la DLL) --
```

**DLL** (`rdp/src/tiresiasRdpClient.c`, C sin dependencias, CRT estático;
`python rdp/build.py` compila x64 y x86 con el mismo método que
`controller/build.py` y deja la DLL en `data/rdp/<arq>`, que es la ruta que se
registra; el programa de pruebas queda en `rdp/test/<arq>` y no se distribuye).
Al arrancar con la opción marcada, si el registro apunta a otra ruta (por
ejemplo, la antigua `rdp/<arq>` de antes de la 1.0.2) se vuelve a registrar. Exporta `DllGetClassObject`, `DllCanUnloadNow` y
`TiresiasRdp_GetVersion`; CLSID `{8E634465-D682-43F3-8342-0381D3C85B3E}`.
`IWTSPlugin::Initialize` crea un oyente para `TiresiasRdp`; cada canal aceptado
es un puente con un hilo que conecta (y reconecta cada segundo) como cliente a
la tubería de la sesión de Windows de `mstsc.exe` y copia bytes: tubería →
`IWTSVirtualChannel::Write` en ese hilo; `OnDataReceived` → `WriteFile`
superpuesto (2 s de plazo; si Tiresias no lee, se suelta la tubería). No
interpreta los mensajes, salvo que al perder la tubería escribe en el canal
`client_left` para que el lado remoto deje de enviar y vuelva a hablar.

**Registro** (`remote/rdp_registration.py`, solo HKCU, sin administrador):
`Software\Microsoft\Terminal Server Client\Default\AddIns\TiresiasRdp`
(`Name` = CLSID), `Software\Classes\CLSID\{…}\InprocServer32` (DLL x64) y
`Software\Classes\WOW6432Node\CLSID\{…}\InprocServer32` (DLL x86, la vista de
32 bits de HKCU\Software\Classes\CLSID, comprobado con `KEY_WOW64_32KEY`),
`ThreadingModel=Free`. Solo se escribe cuando el usuario marca
`rdp.receiveFromRemote` (`rdp.syncRegistration`, al guardar el panel, al
arrancar y al cambiar de perfil); al arrancar con la opción desmarcada solo se
borra un registro que apunte a esta copia. `installer.uninstall` llama a
`unregisterIfFrom(carpeta)`. La raíz se cambia con `TIRESIAS_RDP_REGROOT` o
`SystemTargets.rdpRegRoot` (pruebas).

**Python** (`remote/rdp_io.py`: ctypes sin dependencias de Tiresias;
`remote/rdp.py`: lógica):

| Pieza | Función | Hilo |
|---|---|---|
| `OverlappedStream` | `read`/`write` superpuestos interrumpibles con `close()`; con `pduHeader` quita la `CHANNEL_PDU_HEADER` (8 bytes) de cada lectura del canal | quien llama |
| `PipeListener` | `CreateNamedPipe` (byte, `PIPE_REJECT_REMOTE_CLIENTS`, DACL: usuario actual y SYSTEM) y `ConnectNamedPipe`; `GetNamedPipeClientProcessId` da el PID de `mstsc.exe` | Escritorio remoto: tubería |
| `StreamTransport` | interfaz de `RelayTransport` que usan las sesiones; un hilo lee y parte líneas, otro escribe una cola (máx. 1000); `send` nunca bloquea | lectura / escritura |
| `RdpClientSide` | un `_Link` (`LeaderSession` + `RdpMachine`) por conexión; al conectar envía `client_joined` y `set_braille_info`; `api.post_focusChange` decide qué enlace muestra su braille (el del PID en primer plano) y vuelve a anunciar la línea si cambia; `decide_executeBrailleGesture` envía las teclas de la línea como `braille_input` | núcleo |
| `RdpServerSide` | si `isRemoteSession()` (`SM_REMOTESESSION`, `WTSClientProtocolType` = 1 o 2, o sesión de Horizon), `WTSVirtualChannelOpenEx(WTS_CURRENT_SESSION, "TiresiasRdp", WTS_CHANNEL_OPTION_DYNAMIC)` + `WTSVirtualChannelQuery(WTSVirtualFileHandle)` + `DuplicateHandle`; reintentos 5/15/30/60 s; ganchos de salida como el acceso remoto (`pre_speechQueued`, cancelar, pausa, pitidos, sonidos, `post_displayUpdate`) que solo envían mientras hay un «leader» (`client_joined` … `client_left`) | Escritorio remoto: canal; núcleo |
| `RdpMachine` | `TiresiasMachine` sin teclas, portapapeles ni SAS (los lleva RDP); registra «Voz: …» en depuración | núcleo |

`rdp.muteLocalSpeech`: mientras el cliente escucha, `WavePlayer.muted` del
sintetizador actual (se reaplica con `synth.synthChanged`): se sintetiza y se
reproducen índices, por lo que la lectura continua sigue funcionando. También
`tones.setMuted("rdp", True)`: los pitidos y sonidos locales no suenan, pero
`pre_beep`/`pre_playSound` se siguen notificando y llegan al cliente. El
tamaño de la línea del cliente llega con `set_braille_info` →
`BrailleHandler.setRemoteNumCells(n, owner="rdp")` (el acceso remoto usa
`"remote"`; se combinan con el menor mayor que 0). Citrix: `_citrixLock`
serializa `syncCitrix` entre el panel y `_CitrixWatcher`, que comprueba la
parada y la opción antes de registrar.

Opciones: sección `rdp` (`receiveFromRemote` y `citrixClient` falsos,
`sendToClient` y `muteLocalSpeech` verdaderos), panel `gui/rdp_panel.py` («Escritorio remoto»,
después de «Acceso remoto»; ayuda F1 en `rdp-opciones`). Orden sin gesto
`reportRdpStatus` en `remote/plugin.py`. Se inicia y se cierra desde
`remote.initialize()`/`remote.terminate()`.

**Pruebas** (`tests/test_escritorio_remoto.py`): registro bajo
`HKCU\Software\TiresiasPruebas`; tuberías y transporte; lado remoto con un
canal simulado (tubería de mensajes con cabeceras PDU, mensajes en trozos de
1600 bytes); DLL x64 y x86 cargada por `rdp/test/<arq>/rdpTestHost.exe`, que
implementa `IWTSVirtualChannelManager`, `IWTSListener` e `IWTSVirtualChannel`
falsos y comprueba `DllCanUnloadNow` y las referencias al terminar.
`TIRESIAS_RDP_CHANNEL_PIPE=<tubería>` hace que el Tiresias completo use esa
tubería de mensajes como canal (prueba de extremo a extremo sin RDP).

**Citrix, Horizon y otros clientes.** No hace falta el Virtual Channel SDK de
Citrix (gratuito pero propietario, con licencia EULA de Citrix): Citrix
Workspace app para Windows lleva un gestor de DVC (`vddvc0n.dll`, adaptador
«DVCAdapter») que carga complementos `IWTSPlugin` de Microsoft y los
multiplexa sobre canales estáticos ICA; el VDA atiende
`WTSVirtualChannelOpenEx(..., WTS_CHANNEL_OPTION_DYNAMIC)` en la sesión ICA
(guía de arquitectura del Virtual Channel SDK, apartado «Citrix dynamic
virtual channel protocol»). La misma DLL sirve sin cambios.

- Cliente (`rdp.citrixClient`, falso de fábrica, solo con
  `receiveFromRemote`): `CitrixRegistration` escribe en
  `HKCU\Software\Citrix\ICA Client\Engine\Configuration\Advanced\Modules`
  la subclave `DVCPlugin_TiresiasRdp` (`DvcNames=TiresiasRdp`,
  `PluginClassId=<CLSID>`) y añade `TiresiasRdp` a la lista separada por
  comas `DVCAdapter\DvcPlugins` (conserva las demás entradas y el tipo del
  valor). Citrix copia esa configuración al usuario en la primera sesión: si
  falta, el estado es `noSession` y `_CitrixWatcher` (hilo, cada 30 s) la
  vigila, registra y avisa con voz; también repara la entrada si una
  actualización de Citrix la borra. Las claves son las que usa RD Pipe
  (RDAccess de NVDA, AGPL; solo se toman los nombres, no el código). Al
  desmarcar, al desregistrar el COM y en `unregisterIfFrom` se quita.
  `wfica32.exe` es de 32 bits (la DLL x86 en `WOW6432Node`); la app de 64
  bits usa la vista x64. La versión de Microsoft Store no carga complementos.
- Servidor: `rdp_io.remoteKind()` = `citrix` si `WTSClientProtocolType` = 1
  (en escritorios de una sola sesión `SM_REMOTESESSION` puede ser 0);
  `isRemoteSession()` acepta RDP, ICA y Horizon. El canal se abre igual. El
  administrador debe permitirlo: VDA 2407+ directiva «Virtual channel allow
  list for DVC», entrada `<exe>,TiresiasRdp,TiresiasRdp`
  (`rdp.citrixAllowListEntry()`, que el panel muestra y copia; el estado del
  servidor la incluye si el canal no abre). VDA 2109–2402: lista de canales
  estáticos activada de fábrica; se diagnostica con «Virtual channel allow
  list logging».
- Horizon: `RdpRegistration.register` añade `View Enabled` (≤ 2406) y
  `Horizon Enabled` (≥ 2412) = 1 a la clave AddIns (guía del RDPVCBridge SDK
  de Omnissa, gratuito). En el servidor, si existe
  `%SystemRoot%\System32\vdp_rdpvcbridge.dll` y `VDP_IsHorizonSession`, se
  usan `VDP_VirtualChannelOpenEx/Query/Close` y `VDP_FreeMemory`
  (`rdp_io.ChannelApi`). En el cliente el canal vive en un proceso hijo
  (`vmware-remotemks.exe`) de la ventana (`vmware-view.exe` /
  `horizon-client.exe`): `_Link.windowPids` incluye el padre solo si es uno
  de esos (`rdp_io.processInfo`, Toolhelp), nunca el Explorador.
- `msrdc.exe` (Windows App, AVD, Windows 365) y Parallels Client leen la misma
  clave AddIns; en el servidor son sesiones RDP.

Alternativa por red descartada como modo automático: el acceso remoto por
TCP/TLS (sección 13) exige que el VDA salga a un servidor de retransmisión
(cortafuegos corporativos, Citrix Gateway, NAT, latencia); queda documentada
como recurso manual.

Pruebas (`tests/test_escritorio_remoto.py`): `CitrixRegistrationTests`
(configuración de Citrix simulada bajo la raíz de pruebas: estados,
conservación de otros complementos, Horizon, `syncCitrix`, vigilante,
entrada de la directiva), `SessionKindTests` (tipos de sesión con
`mock`, elección WTS/VDP, `openDynamicChannel` con una `ChannelApi` falsa
sobre una tubería real) y `ClientProgramTests` (braille según el proceso en
primer plano, `processInfo`).


## 25. Importador de la configuración de NVDA (`nvda_import.py`)

`nvda_import` convierte la configuración de NVDA en la de Tiresias. Nunca
escribe en la carpeta de NVDA.

- **Lectura** (`NvdaConfig`): `nvda.ini`, `profiles/*.ini`,
  `profileTriggers.ini`, `gestures.ini`, `speechDicts/` (`default.dic`,
  `temp.dic` y `voiceDicts.v1/<sintetizador>/*.dic`), `symbols-<idioma>.dic`
  y las etiquetas de complementos (solo se informa). El formato configobj se
  lee con un lector propio (`parseIni`): no hace falta el paquete `configobj`.
  `resolveFolder` admite la carpeta de NVDA instalado (`%APPDATA%\nvda`), la de
  NVDA portable (`userConfig`), `nvda.ini` o `nvda.exe`.
- **Plan** (`buildPlan` -> `Plan`): la tabla `ROWS` (categoría, sección y
  clave de NVDA, ruta de Tiresias, conversión y valor por defecto de NVDA)
  cubre las opciones directas. `_Mapper` trata aparte el sintetizador
  (`ELOQUENCE_DRIVERS` -> `ibmtts`, con `_ECI_KEYS`; eSpeak, OneCore y SAPI 5),
  las mayúsculas (en NVDA son del sintetizador activo), `NVDAModifierKeys`, la
  línea y las tablas braille, el dispositivo de audio (NVDA guarda el
  identificador; Tiresias, el nombre), los errores ortográficos (máscara de
  bits) y los visores. Toda clave de NVDA que no se consume genera un `Notice`.
  Como `nvda.ini` solo guarda lo que difiere, con `useNvdaDefaults` se aplican
  también los valores por defecto de NVDA de la tabla (no en los perfiles).
  Cada `Change` se valida con `config.validation.coerce` y guarda el valor
  anterior (`old`) para la vista previa y el informe.
- **Gestos**: `SCRIPT_ALIASES` y `tiresiasScriptName` (navegación rápida
  `next*`/`previous*` -> `quickNavNext*`/`quickNavPrev*`) traducen los nombres;
  `_SECTION_CLASSES` elige la clase (órdenes globales, modo exploración,
  edición, acceso remoto, matemáticas) y se comprueba con `script_<nombre>`.
  `translateGesture` normaliza (`nvda` -> `tiresias`). Nunca se importa
  `showGui` ni un gesto que coincida con la tecla del menú de Tiresias o con
  `gesture_tools.RESERVED`; las desasignaciones (`None = ...`) no se aplican.
- **Aplicar** (`applyPlan`): guarda la configuración en memoria, hace la copia
  `data/config/backup_antes_importar/<fecha>/` (configuración y
  `speechDicts`, con `importacion.json`), escribe en la capa base o en un
  perfil nuevo, crea los perfiles y disparadores (`app:`, `sayAll`), añade los
  gestos a `gestures.json`, fusiona los diccionarios y `symbols_user*.json`,
  y deja `informe_importacion_nvda.txt` y `configuracion_desde_nvda.json`.
  `undoLastImport` restaura los archivos escritos y borra los creados.
  `reloadAfterImport` recarga gestos, diccionarios y símbolos y encola
  `core.applyConfiguration`.
- **Entradas**: `gui/nvda_import_dialog.py` (Herramientas y Opciones >
  Generales), la pregunta del primer arranque (`first_run`, ver «Diálogos de
  arranque» más abajo), `--import-nvda-config [carpeta]`,
  `--import-nvda-profile` y `--undo-nvda-import` (`startup.runStandaloneCommand`)
  y `Tiresias.bat importarnvda [codigo|dist] [carpeta]`.
- **Pruebas**: `tests/test_nvda_import.py` (configuraciones de ejemplo
  instalada, portable, con perfiles, gestos, diccionarios y símbolos; equivalencias;
  aplicar en la configuración normal y en un perfil; deshacer; línea de órdenes).

### Diálogos de arranque (`first_run.py`)

- `startup.prepareConfiguration`: si no había `config.json`, `first_run.markFirstRun()`
  pone `general.firstRunStep = "nvda"` (oculta, sin control en Opciones).
- `startup.afterCoreStarted` → `first_run.start(args)` (hilo del núcleo):
  `planSteps(paso, carpetaNvda, showWelcomeDialogAtStartup, readOnly, suppressed)`
  devuelve `["askImport", "welcome"]`, `["welcome"]` o `[]`. `core` ya no abre
  la bienvenida por su cuenta.
- `StartupSequence` (hilo de la interfaz) ejecuta los pasos de uno en uno: la
  bienvenida se crea solo cuando la pregunta ha terminado (con «Sí», después
  de `reloadAfterImport` y de cerrar el resumen), así que sus controles leen
  lo importado. Antes de cada paso, si `coexist.isStandby()`, lo que falta se
  aplaza con `coexist.runWhenActive`.
- `firstRunStep`: `"nvda"` → `"welcome"` al responder (con «Sí» lo guarda
  `applyPlan`; con «No», `setStep` guarda) o al mostrar la bienvenida si no
  hay NVDA → `""` al aceptar la bienvenida (`welcomeAccepted`). En el primer
  arranque la bienvenida sale aunque `showWelcomeDialogAtStartup` sea falso
  (la importación copia el valor de NVDA). `--import-nvda-config` también pasa
  de `"nvda"` a `"welcome"`.
- Pruebas: `tests/test_primer_arranque.py`.


## 26. Convivencia con otros lectores de pantalla (`coexist/`)

Tiresias es para cuando no hay ningún lector profesional activo. Si NVDA,
JAWS, Narrador (u otros marcados en Opciones › Generales) están en
ejecución, Tiresias pasa a **espera**.

**Piezas** (`src/tiresias/coexist/`):

- `detect.py`: `Detector.detect(enabled)` → `[ReaderInfo(id, name, pid, detail, ready, path)]`.
  Win32 puro, unos 6 ms por sondeo. Señales por lector:
  - **NVDA**: proceso `nvda.exe` / `nvda_uiAccess.exe` / `nvda_noUIAccess.exe`
    y ventana `wxWindowClassNR` «NVDA» (`ready`), que solo cuenta si su dueño
    es uno de esos procesos. Así se excluye la ventana de
    `tiresiasNvdaWindow.exe`. `nvda_slave`, `nvdaHelperRemoteLoader` y
    `nvda_eoaProxy` no cuentan. Para distinguir instalado, portable y copia
    temporal se compara la ruta del ejecutable con `InstallDir` de
    `HKLM\...\Uninstall\NVDA` (vistas de 64 y 32 bits) y con `%TEMP%`. Al
    anunciar, además, el controlador: `testIfRunning` y `getProcessId`.
  - **JAWS**: `jfw.exe` y ventana `JFWUI2`.
  - **Narrador**: `Narrator.exe`. `ready` = `HKCU\Software\Microsoft\Narrator\NoRoam\RunningState` = 1.
    El registro solo no basta, porque queda a 1 si Narrador se cierra de golpe.
  - **Otros**:
    - ZoomText/Fusion: `zt.exe`, desactivado por defecto porque con la lupa sola no habla.
    - Dolphin: `snova.exe`, `hal.exe`.
    - System Access: `sa.exe`, `satogo.exe`, desactivado por defecto porque está descatalogado y su nombre es ambiguo.
  - Solo cuentan los procesos de la **misma sesión y del mismo usuario** (SID del token).
    Las copias que Windows lanza como SYSTEM en el escritorio seguro quedan fuera.
    Si no se puede abrir el proceso, cuenta solo si su ventana está en este escritorio.
  - `SPI_GETSCREENREADER` no se usa: lo activan muchas aplicaciones y el propio Tiresias.
- `state.py`: lógica pura, probada con detectores simulados.
  - `Debouncer`: un lector aparece tras 2 sondeos o enseguida si está `ready`, y desaparece tras 2 sondeos.
  - `Coexistence`: estados `active` y `standby`, con `forced`, `yieldEnabled` y las órdenes `force()` y `yieldNow()`.
  - Llama a `Actions.goStandby(reader, initial)` y a `goActive(reason, reader)`.
- `announce.py`: hilo «Anuncios de convivencia» con COM STA. Espera a que el lector esté listo (máximo 30 s) y anuncia por:
  - NVDA: `speakText` y `brailleMessage` con `server.nvdaClient()`.
  - JAWS: `FreedomSci.JawsApi.SayString`.
  - Narrador: `UiaRaiseNotificationEvent` desde una ventana propia (`NotificationWindow`, clase `TiresiasAnunciosUIA`).
    La ventana responde a `WM_GETOBJECT` con un `IRawElementProviderSimple` mínimo (comtypes) mediante `UiaReturnRawElementProvider`.
    Es visible pero de 1×1 y fuera de la pantalla, porque UIA no entrega a otros procesos los eventos de ventanas ocultas (comprobado).
    Se crea para cada anuncio y atiende sus mensajes antes y después.
  - En otro caso, dos tonos suaves.
- `__init__.py`: integración, hilo «Vigilancia de lectores» y opciones `coexist.yieldToOtherReaders` y `coexist.readers`.
  - El hilo sondea cada segundo y no evalúa con el escritorio seguro activo.
  - Si ve NVDA por primera vez, llama a `controller.releaseNvdaEndpoint()` desde ese mismo hilo, antes de que NVDA abra su punto de conexión.
  - Cuando cambia el conjunto estable, encola `_onStableReaders` en el núcleo.
- `plugin.py`: órdenes (complemento incorporado) y `ui.py`.
  - `ui.py` gestiona el icono atenuado, la descripción «en espera», las entradas del menú y el aviso al forzar.
  - También registra la tecla `RegisterHotKey` Control+Alt+Mayúsculas+T, solo en espera.

**Arranque** (`core._initializeCore`): `coexist.initialize()` va justo después de `audioManager.initializeEarly()`. Detecta y fija el estado. Si queda en espera:

- llama a `speech.api.setSuspended(True)`, que corta `speak()` del todo;
- no suena el sonido de inicio;
- `startInput()` no se llama;
- el táctil arranca con `inputAllowed=False`;
- `braille.handler.setDisplay` de una línea real solo guarda la elección;
- `applyScreenReaderFlag` no hace nada;
- el controlador no arranca el auxiliar;
- no se lee el foco;
- la pregunta de NVDA y la bienvenida se aplazan con `runWhenActive` (`first_run`); al activarse, `goActive` ejecuta lo pendiente (`_runPendingOnActive`).

`coexist.afterCoreStarted()` (al final) suspende los eventos UIA, anuncia por el otro lector y arranca la vigilancia.

**Ceder** (`_suspendAll`), en este orden:

1. Cancela la voz y la suspende; `synth.setStandby(True)` deja el sintetizador en reposo (ver «Sintetizador en espera» en el apartado 5).
2. `core.stopInput()`: quita los ganchos y los WinEvents, y `manager.resetState()` olvida modificadores, la tecla Tiresias y la ayuda de entrada.
3. Desactiva el táctil.
4. `uia_handler.suspend()`: llama a `RemoveAllEventHandlers`; los eventos que ya estaban en cola se descartan.
5. Pasa el braille a `noBraille` sin guardar.
6. `a11y.system.releaseScreenReaderFlag()`: deja el indicador como está, porque es del otro lector.
7. `controller.applyConfiguration()` cierra el auxiliar.

**Activarse** (`goActive`) hace lo inverso, sin bloquear el núcleo:

- `_resumeSpeech()`: `synth.setStandby(False)` justo después de `setSuspended(False)`: el sintetizador recupera sus recursos antes del anuncio (si falla, `fallbackFrom` cambia de voz y lo anuncia). Acto seguido, el anuncio de activación.
- El resto (`_resumeSteps()`: entrada, táctil, eventos UIA, braille, indicador de lector de pantalla, auxiliar del controlador y cadena de órdenes) lo ejecuta `_runResumeSteps`, un paso por ciclo del núcleo (`callLater(0, ...)`), para que el vigilante no vea el núcleo parado y se atiendan los eventos entre medias. Si Tiresias vuelve a ceder (o se cierra) a mitad, `_activation` cambia y los pasos pendientes se abandonan.
- `uia_handler.resume()` crea un `_EventHandler` nuevo, porque comtypes da por liberado el anterior tras `RemoveAllEventHandlers`.
- `core.startInput()` arranca el hilo de ganchos; `HookThread` se puede reiniciar.
- Tras el último paso se lee el foco cuando termina de hablar (`_reportFocus`) y se ejecuta lo aplazado (`_runPendingOnActive`).

**Fuera de la espera siguen**:

- la interfaz;
- la API de control: `TiresiasCtlr` responde 1062 para que el cliente pase a NVDA y Tolk elija el lector activo;
- el acceso remoto ya conectado, que no envía voz ni captura teclas;
- el portapapeles y las tareas que no hablan.

**Pruebas**:

- `tests/test_coexistencia.py` cubre el detector simulado, el `Debouncer`, la máquina de estados y el tono de reserva.
- La misma prueba abre y cierra lectores falsos de verdad: una copia de `python.exe` llamada `nvda.exe` o `jfw.exe` que ejecuta `tests/fake_reader.py` con su ventana.
- `tests/coexist_bridge_probe.py` prueba el auxiliar en un escritorio propio, para no tocar el `NvdaCtlr.1.Default` del NVDA real:
  - reenvío;
  - marcas SSML;
  - rechazo de reenvíos de otros procesos;
  - liberación del punto al cerrar y con `WM_QUIT` a la ventana, como hace NVDA.
- Variables solo para pruebas:
  - Con `--exit-after`, Tiresias arranca activo (forzado) para no estorbar las pruebas con NVDA abierto. `TIRESIAS_COEXIST_TEST=1` prueba la espera de verdad.
  - `TIRESIAS_COEXIST_IGNORE_PIDS=<pid,...>` hace que la detección ignore esos procesos; sirve para probar con un NVDA falso sin cerrar el real.
  - `TIRESIAS_COEXIST_ONLY_DIR=<carpeta>`: solo cuentan los lectores cuyo ejecutable está en esa carpeta (el real y los de otras pruebas simultáneas no). Con cualquiera de las dos, el guardián no se inicia salvo con `TIRESIAS_GUARDIAN_TEST=1` (apartado 26.1).
- Línea de órdenes: `--force-active`.

### 26.1. Lector recordado y guardián (`coexist/relaunch.py`, `coexist/guardian.py`)

Objetivo: el usuario nunca se queda sin lector de pantalla.

- **Lector recordado**: `data\config\lectorRecordado.json` (siempre en `DATA_DIR`, aunque haya `--config-path`).
  - `coexist.initialize` y `_onStableReaders` guardan el lector principal en ejecución (`relaunch.rememberReader`): id, nombre, ruta exacta del ejecutable (`Detector` ya da `path` para todos los lectores) y `args`. Los `args` se conservan si es el mismo lector en la misma ruta (las pruebas los usan para el NVDA falso).
  - Se escribe al momento, de forma atómica (`os.replace`), así que sobrevive a un cierre brusco.
  - Lleva también una copia de las opciones que necesita el guardián (`options`: `relaunchOnExit`, `relaunchOnHang`, `hangTimeout`, `readers`); se actualiza al iniciar y en `coexist.applyConfiguration`.
- **Cómo se inicia** (`launchCandidates`, `launchReader`): con `ShellExecuteExW` (respeta uiAccess y elevación).
  - Primero la ruta exacta; para `nvda_uiAccess.exe`/`nvda_noUIAccess.exe`, el `nvda.exe` de la misma carpeta.
  - Solo si esa ruta ya no existe: el NVDA instalado (`nvdaInstallDirs`) o `System32\Narrator.exe`. Los `args` recordados solo se pasan a su propio ejecutable.
  - En pruebas con lectores falsos nunca se recurre a otra ruta (sería el NVDA real del equipo): con `TIRESIAS_RELAUNCH_NO_FALLBACK=1`, `TIRESIAS_COEXIST_IGNORE_PIDS` o `TIRESIAS_COEXIST_ONLY_DIR`.
- **Guardián**: `Tiresias.exe --guardian <pid> --data <carpeta>` (desde código, `pythonw tiresias.pyw --guardian ...`). `tiresias.pyw` lo despacha antes de importar el núcleo: no carga wx ni el núcleo y arranca en unas décimas.
  - Lo inicia `core.main` justo después del mutex de instancia (`guardian.start`), fuera del *job* del padre si se puede (`CREATE_BREAKAWAY_FROM_JOB`). La vigilancia de lectores lo vuelve a iniciar si muere (`ensureRunning`, cada 15 s).
  - En pruebas no se inicia salvo con `TIRESIAS_GUARDIAN_TEST=1`: con `--exit-after` ni con lectores falsos (`TIRESIAS_COEXIST_IGNORE_PIDS`, `TIRESIAS_COEXIST_ONLY_DIR`), porque volvería a abrir el lector falso de otra prueba. `TIRESIAS_NO_GUARDIAN=1` lo desactiva siempre.
  - Crea el mutex `Local\Tiresias_Guardian_<pid>` y espera al proceso con `WaitForSingleObject` (cada 0,5 s).
  - Al terminar Tiresias lee el **marcador** `data\temp\salida_<pid>.txt` y decide con `relaunch.decideExit` (lógica pura):

    | Motivo | Quién lo escribe | Decisión |
    |---|---|---|
    | `user` | `guardian.onProcessExit` al final de `core.main` (salida pedida) | iniciar si la opción está activa y no hay un lector en ejecución |
    | sin marcador (`error`) | nadie: excepción, cierre nativo (0xc0000005...), `TerminateProcess` | igual que `user` |
    | `restart` | `onProcessExit` con `_restartRequested`; `watchdog.emergencyRestart` | esperar a la copia nueva (mutex de instancia o ventana principal) hasta 60 s; si no llega, como un fallo |
    | `replaced` | el guardián, si existe el evento `Local\Tiresias_Sustituida_<pid>` que crea la copia nueva en `core._closeRunningInstance(replacing=True)` | como `restart` |
    | `update` | `updates.startPortableUpdate` (`setExitKind`) | nada: termina enseguida para no bloquear `Tiresias.exe`; la copia que actualiza espera al guardián (`waitGuardianGone`) y hace de red de seguridad (`afterUpdateLaunch`) |
    | `switch` | «Volver a <lector>» (`switchToRememberedReader`): Tiresias inicia el lector al final de `core.main` | nada |

  - Si el marcador existe y el proceso sigue vivo más de 10 s (cierre colgado), actúa igual.
  - Antes de iniciar NVDA espera (3 s) a que termine el `tiresiasNvdaWindow.exe` hijo de ese Tiresias y, si no, lo termina: NVDA necesita libre su punto de conexión.
  - No inicia nada si Windows se está apagando (`SM_SHUTTINGDOWN`). Registro propio: `data\logs\guardian.log`.
  - `--quit` y la desinstalación esperan a que termine el guardián (`waitGuardianGone`) para que sus archivos queden libres.
- **Latido**: memoria compartida `Local\Tiresias_Latido_<pid>` (`relaunch.Heartbeat`), con el último instante en que el núcleo respondía (`QueryUnbiasedInterruptTime`, que no cuenta la suspensión).
  - Lo anota `core._watchdog` cada segundo mientras el núcleo lleve menos de 2 s ocupado; el primer latido arma la detección.
  - Si pasan más de `hangTimeout` segundos, el guardián inicia el lector una vez (`decideHang`) y se rearma cuando vuelve el latido. Tiresias, al recuperarse, detecta el lector y pasa a espera.
- **Interfaz**: Opciones › Generales › «Otros lectores de pantalla» (`relaunchOnExit`, `relaunchOnHang`, `hangTimeout`, cuadro del lector recordado y botón «Olvidar», ayuda F1 con `ConfigPanel._helpKeys`); entrada «Volver a <lector> (cierra Tiresias)» del menú (`coexist/ui.py`) y orden `coexistSwitchBack` sin gesto.
- **Pruebas**: `tests/test_relanzar_lector.py`.
  - Decisiones, archivo, rutas, marcadores, latido y lógica del guardián con un sistema simulado.
  - El proceso `--guardian` de verdad con un «Tiresias» de mentira y un NVDA falso (copia de `pythonw.exe` llamada `nvda.exe` con `nvda._pth`, que ejecuta `tests/fake_reader.py`).
  - Integración con Tiresias real (`--no-input --no-replace --minimal`, `TIRESIAS_COEXIST_TEST=1`): `--quit`, `TerminateProcess` y reinicio (`--restart-after N`, solo para pruebas).
  - El NVDA real (y los lectores falsos de otras pruebas simultáneas) se ignoran con `TIRESIAS_COEXIST_ONLY_DIR=<carpeta de la prueba>` (solo cuentan los lectores cuyo ejecutable está ahí; `Detector.onlyDir`) y `TIRESIAS_COEXIST_IGNORE_PIDS`.
  - Al reiniciar se conservan `--no-input` y `--synth` (`core.restartArguments`).

## 27. Rendimiento en cuadros combinados, relaciones UIA, actualizaciones y Control de aplicaciones

- **Ventanas propias con MSAA** (`a11y/api_choice.py`): las ventanas del proceso de Tiresias se leen siempre con MSAA, como NVDA. Con UIA dentro del mismo proceso, cada flecha en un cuadro combinado de las Opciones producía de 50 a 200 eventos `ElementSelected` repetidos (proxies Win32 de UIA en el propio proceso), y el valor se anunciaba con unos 650 ms de retraso.
  - `uia_handler` descarta en el hilo de UIA todo evento cuyo `ProcessId` cacheado sea el propio (`_isOwnProcess`), sin llamar a UIA. El foco propio deja una comprobación de respaldo (`_ownFocusFallback`).
  - `winevents.WIN_EVENTS` admite un cuarto elemento `True`: `hooks.py` instala esos rangos solo para el propio proceso (sin `WINEVENT_SKIPOWNPROCESS`): foco, nombre, valor, estado, selección, cursor y menús. Sin el foco en Tiresias, de sus ventanas solo pasan los menús emergentes.
- **MSAA de las ventanas propias en el hilo de la interfaz** (`a11y/own_windows.py`). Leer desde el núcleo las ventanas wx de Tiresias era un `SendMessage` al hilo principal por cada dato (`WM_GETOBJECT`, `WM_GETTEXT`…), sin tiempo máximo: con la interfaz ocupada (importando la configuración de NVDA, guardando las Opciones) el núcleo se quedaba esperando, y el RichEdit de los mensajes fallaba con `RPC_E_CANTCALLOUT_ININPUTSYNCCALL` (0x8001010D) dentro de esos mensajes «de entrada síncrona».
  - `msaa.accessibleObjectFromWindow/FromEvent/FromPoint` crean el objeto de una ventana del hilo de la interfaz **en ese hilo** (`own_windows.mustDelegate`) y devuelven un `OwnAccessible`: cada atributo o método se ejecuta en el hilo de la interfaz (`own_windows.call`: `PostMessage` a una ventana de mensajes propia, `TiresiasOwnA11y`, creada en `gui.initialize`) y los punteros que devuelve se envuelven igual. El puntero COM real nunca sale de ese hilo y se libera allí. `accessibleChildren`, `windowFromAccessibleObject`… lo detectan (`own_windows.runWith`); `queryIAccessible2` devuelve `None` (wx no implementa IA2).
  - Tiempo máximo `CALL_TIMEOUT` (0,4 s) y **cortacircuitos**: mientras la tarea atrasada no termina, las llamadas siguientes fallan al instante con `GuiBusyError` (subclase de `OSError`, que el código MSAA ya trata como «sin dato»). Al liberarse la interfaz se vuelve a mirar el foco (`winevents.scheduleFocusCheck`). Si el mensaje se perdió, se reenvía a 1 s y se descarta a 10 s.
  - Las ventanas propias de otros hilos (anuncios para Narrador, superposición táctil) no se leen. `getFocusObject`/`getObjectFromPoint` no recurren a UIA para las propias; `win32ctl.sendMessage` también pasa por el hilo de la interfaz y `winapi.getWindowText` usa `InternalGetWindowText` con las ventanas propias de otro hilo.
  - Latencia de los cuadros combinados de las Opciones: 3–4 ms (medida con una prueba manual fuera del repositorio).
  - Hijos: el objeto «ventana» de una subventana se cambia por su cliente (`_wrapAccessible`), igual que al subir: `collectDialogText` vuelve a leer el texto de los diálogos («Intro responde Sí y Escape, No»).
- **MSAA con ventanas de otros procesos sin bloqueos** (`a11y/msaa.py`): `AccessibleObjectFromWindow/FromEvent` envían `WM_GETOBJECT` sin tiempo máximo, e `IsHungAppWindow` solo marca una aplicación al cabo de 5 s; en una prueba el núcleo se quedó 10 s esperando el foco de una `SysListView32` de otro proceso que creaba ventanas sin atender mensajes. Ahora, con las ventanas de otro proceso, `WM_GETOBJECT` va con `SendMessageTimeout` (`GETOBJECT_TIMEOUT_MS`, 1,5 s; `SMTO_ABORTIFHUNG`) y se convierte con `ObjectFromLresult` o `CreateStdAccessibleObject`; el hijo del evento se resuelve con `accChild`, como oleacc. El hilo que no responde se recuerda `SLOW_WINDOW_SECONDS` (10 s, `markSlowWindow`/`isSlowWindow`) y sus ventanas se omiten al instante salvo que una sonda `WM_NULL` de 50 ms muestre que ya responde. `accessibleObjectFromPoint` hace la misma comprobación antes de preguntar. Pruebas: `tests/test_rev106_final.py` (proceso auxiliar con una lista que deja de atender mensajes).
- **Menús Win32 con MSAA**: un evento de foco de un elemento con submenú da un objeto completo (identificador de hijo 0). `fromEvent` le ponía `objectId = OBJID_CLIENT` y `isSameAs` daba por iguales todos los elementos con submenú: al bajar por el menú de Tiresias no se anunciaban Herramientas, Visión e IA, Complementos… Ahora `objectId` solo se pone si el evento es del propio objeto. Además: posición «3 de 10» (`IAccessibleObject._siblingPosition`, sin separadores; también en listas y pestañas de Windows), elementos de verificación de los menús de Tiresias («no marcado»: Windows no guarda si un elemento es de verificación, la interfaz los anota en `gui.checkableMenuIds`) y de opción (`MFT_RADIOCHECK`). Con un menú abierto, `_checkFocus` no devuelve el foco al control que lo abrió (`_menuStillOpen`, `GUI_INMENUMODE`/`GUI_POPUPMENUMODE`): antes el menú contextual de un campo repetía el diálogo tras cada flecha.
- **Registro de cierres** (`crash_log.py`): `faulthandler.enable()` instala en Windows un manejador vectorizado que anotaba como «Windows fatal exception» cada excepción SEH que COM/RPC lanzan y recogen ellos mismos (cientos de KB por minuto y 7 KB escritos en mitad de cada llamada COM). Ahora, como NVDA, `SetUnhandledExceptionFilter` (solo excepciones que nadie recoge: el proceso se va a cerrar) y un manejador de `SIGABRT` escriben el motivo, el módulo y las pilas de todos los hilos en `fallos.log`; el vigilante usa `crash_log.dumpThreads`. `TIRESIAS_FAULTHANDLER=1` vuelve al `faulthandler` completo para depurar.
- **Importación de NVDA en marcha**: `nvda_import.reloadAfterImport(announce, then)` recarga configuración, gestos, diccionarios y símbolos y aplica la configuración **en el núcleo** (antes, en el hilo de la interfaz mientras el núcleo hablaba); el aviso se dice con la voz nueva y justo después se muestra el resumen del primer arranque (que se lee también con la voz nueva). `synth._trySet` cierra antes el sintetizador anterior si es el mismo controlador: eSpeak y Eloquence tienen estado global en el proceso y cargar el nuevo antes de cerrar el viejo acababa en una violación de acceso.
- **Pruebas**: `tests/test_ventanas_propias.py` (diálogo wx real leído desde un hilo MTA con `tests/own_windows_probe.py`, interfaz ocupada, ventana destruida, menús, cierres reales y gestionados, recarga del mismo sintetizador). En vivo, una prueba manual con teclas reales (fuera del repositorio, en la carpeta de trabajo del desarrollador) recorre el menú de Tiresias, sus submenús y el menú contextual de la paleta de órdenes.
- **Selecciones redundantes**: con el foco en un cuadro combinado UIA cerrado (`_focusComboCollapsed`, que se actualiza con el cambio de `ExpandCollapseState`), las selecciones se descartan en el hilo de UIA: el valor ya llega con su cambio de valor.
- **Campo de un combo editable**: `EditableText._detectSelectionChange` no anuncia como selección el texto nuevo cuando ocupa todo el campo de un cuadro combinado (antes decía «a seleccionado»).
- **Doble liberación de VARIANT** (cierre `0xc0000374`): en `HandlePropertyChangedEvent`, `newValue` es una copia superficial que comtypes liberaba con `VariantClear` y UIA liberaba otra vez. Se pone `newValue.vt = VT_EMPTY` antes de nada.
- **Relaciones con matrices de elementos**: ControllerFor, DescribedBy, FlowsTo, FlowsFrom y AnnotationObjects se leen con `uia_client.elementArray(el, propId, cached=...)`, con los accesores tipados (`CurrentControllerFor`, `CachedFlowsTo`...). LabeledBy se lee con `uia_client.labeledBy`.
  - `UIAObject._prop` redirige a esos accesores.
  - `UIAObject.relationElements(relación)` las devuelve.
  - Nunca se leen como VARIANT.
- **Prueba de estrés**: `tests/uia_stress_relations.py`.
  - Modo `local`: 20 000 llamadas al manejador por su tabla COM. Antes del arreglo terminaba con `0xc0000005`.
  - Modo `edge`: página con `aria-controls` y `aria-describedby`.
- **Actualizaciones**: ver la sección «Servidor de distribución, actualizador y publicación». Si `updates.DISTRIBUTION_URL` (o la opción `update.serverUrl`) está vacía:
  - la comprobación automática no se intenta ni deja mensajes, y la manual explica dónde poner una dirección;
  - la tienda lee la copia local sin ir a la red.
- **Control de aplicaciones** (`app_control.py`): si la importación de comtypes, wx o la interfaz falla por Smart App Control o WDAC (WinError 4551 o el texto del error), `core.main` llama a `app_control.report`. También lo hace el `excepthook` de `log.py` con cualquier excepción así.
  - `report` escribe la explicación en el registro y la muestra con `MessageBoxW`.
  - `Tiresias.bat desbloquear` ejecuta `Unblock-File` recursivo sobre `dist`.
  - `Tiresias.bat firmar` (`tools/sign_dist.py`) firma con signtool y un certificado que se le indica con `TIRESIAS_CERT_PFX` (y `TIRESIAS_CERT_PASSWORD`) o con `TIRESIAS_CERT_THUMBPRINT`. Nunca crea certificados. Un certificado autofirmado no sirve para Smart App Control en otros equipos.

## 28. Servidor de distribución, actualizador y publicación

Esta sección es un resumen. El detalle está en `docs/publicacion.md`.

**Direcciones**
- `updates.DISTRIBUTION_URL` vale `https://xebolax.synology.me/Tiresias`. Es la única constante.
- Tienen preferencia sobre ella la política `distributionUrl` y la opción `update.serverUrl`.
- `distributionFile(rel)` construye las direcciones de los archivos:
  - `actualizacion.json` (`UPDATE_MANIFEST`);
  - `versiones.json`;
  - `complementos/catalogo.json` (`CATALOG_FILE`);
  - `novedades.html`;
  - `descargas/<versión>/`.
- `update.checkUrl` y `addons.catalogUrl`, o las políticas `updateUrl` y `addonCatalogUrl`, sustituyen un solo archivo.
- Las direcciones de los JSON son relativas al JSON y se resuelven con `resolveUrl`. Las absolutas también valen, por ejemplo las de GitHub Releases.

**Red**
- `openUrl` usa `ssl.create_default_context()` con TLS 1.2 o posterior.
- Los JSON se piden con `Cache-Control: no-cache`.
- `_withRetries` hace hasta 3 intentos ante los cortes pasajeros (`ConnectionError`, `RemoteDisconnected`, tiempo agotado). Los errores HTTP y de certificado no se reintentan.
- `download(url, dest, sha256, progress, size=)` comprueba el `Content-Length`, los bytes recibidos y el SHA-256. Si algo falla, borra el `.part`.

**Manifiesto**
- `parseUpdate(data, base, channel, kind, current)` hace tres cosas:
  - elige el canal: el estable y, con `update.channel = "beta"`, también `channels.beta`;
  - compara versiones con `versionKey`: `1.1.0b1` < `1.1.0rc1` < `1.1.0`;
  - elige el paquete según `copyKind()`: `instalada` usa `installer`, `portable` usa `portable` y `codigo` usa `source`.
- Lo devuelve en `UpdateInfo`, con `size`, `minWindows`, `channel` y `package`.
- `supported` compara `minWindows` con `sys.getwindowsversion()`. Si el equipo no la cumple, no se avisa y la comprobación manual lo explica.

**Aplicar la actualización** (`installDownloaded`)
- **`.exe`**: se ejecuta el instalador. Su `--install` cierra esta copia. El diálogo de instalación propone la carpeta y el modo (`AllUsers`) de la instalación registrada.
- **ZIP en una copia portable compilada**:
  1. `startPortableUpdate` descomprime el ZIP con `extractPortable`, que rechaza las rutas que se salen de la carpeta.
  2. Lanza `<nuevo>\Tiresias.exe --apply-update <APP_DIR> --wait-pid <pid>` y llama a `core.requestQuit()`.
  3. En la copia nueva, `startup.runStandaloneCommand` llama a `installer.runApplyUpdate`, que hace esto:
     - `waitForProcess` espera a que termine la copia antigua;
     - `applyPortableUpdate` mueve a `_actualizacion_anterior` lo que se va a sustituir (las entradas del programa, `lib`, `LEGACY_PROGRAM_DIRS`, los archivos sueltos que ya no vienen según `STALE_ROOT_PATTERNS`, como `python313.dll`, y `data/<PROGRAM_DATA_REPLACE>`);
     - copia lo nuevo;
     - actualiza `symbols`, `sounds` y `brailleTables` (los símbolos del usuario están en `config/symbols_user*.json`, que no se toca);
     - copia `speechDicts/default.json` solo si falta;
     - pasa `updateBundledAddons`, el mismo criterio que `seedUserData`;
     - si hay un error, restaura lo movido entrada a entrada y quita lo nuevo; si alguna entrada no se puede restaurar, conserva `_actualizacion_anterior`.
  4. Escribe `data/actualizacion_resultado.json` y abre `Tiresias.exe` en la carpeta de la copia, haya ido bien o mal.
  5. Al arrancar, `updates.reportApplyResult()` (desde `scheduleAutomaticChecks`) avisa si falló. Si fue bien, ya lo anuncia `startup._checkNews`.
- **Otros casos**: se abre la carpeta de la descarga.

**Tienda**
- `addon_store.parseCatalog` usa `_bestVersion`: de `versions` elige la más reciente cuya `minApiVersion` admita `API_VERSION`.
- Si el catálogo en línea falla, se lee la copia local. Sus direcciones relativas se resuelven respecto a la dirección en línea.
- `downloadPackage` comprueba el tamaño y el SHA-256.

**Publicación** (`tools/publicar.py`, `Tiresias.bat publicar`)
- `publish(dest, Release, simulate, repoDocs)` trabaja solo con archivos, así que se puede probar. Se apoya en estas funciones:
  - `updateHistory` y `buildManifest`: reconstruyen `versiones.json` y el manifiesto a partir del historial;
  - `buildCatalog`: reconstruye el catálogo a partir de `complementos/<id>/*.tiresias-addon`;
  - `buildIndex`: genera la portada;
  - `Writer`: solo escribe lo que cambia; con `--simular`, solo lo anuncia.
- `stageProgram` copia `dist\Tiresias` sin los datos del desarrollador ni `PROPRIETARY_ADDONS`. Después busca `ECI.DLL` y `*.syn`, y aborta si los encuentra.
- `build_installer.build(program=, output=, staging=)` y `make_source_zip.build(outDir, extraExclude=)` admiten la copia pública.

**Pruebas**
- `tests/test_publicacion.py`: dos versiones seguidas, idempotencia, simulación, componentes propietarios, URL relativas, canal beta, portada y copia pública.
- `tests/test_actualizaciones.py`: un servidor HTTP local en `[::1]` sirve una publicación generada. Se prueban la comprobación, la descarga con SHA-256 y tamaño, el canal beta, el catálogo con varias versiones, la actualización de complementos, la copia local y la actualización portable (también la restauración).
  - Se usa IPv6 porque en este equipo un filtro de red corta al azar las conexiones locales por IPv4.
