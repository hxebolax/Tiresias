# Estudio de necesidades de usuarios de lectores de pantalla en Windows

**Base para el diseño de Tiresias**. Fecha: 6 de octubre de 2026.

Versiones de referencia: NVDA 2026.2 (estable), NVDA 2026.3 (beta), NVDA 2027.1 (rama de desarrollo `master`, copia local en `adjuntos/nvda`).

---

## 1. Resumen ejecutivo

NVDA es el lector de pantalla más usado del mundo fuera de Norteamérica y Australia. En la encuesta WebAIM n.º 11 (julio-agosto de 2026) es el lector principal del 77,4 % de los encuestados de Asia, del 83 % de África y Oriente Medio y del **67,2 % de Sudamérica**, y su índice de satisfacción es el más alto (96,7 %). A pesar de eso, el uso de NVDA como lector principal **bajó del 37,7 % (2024) al 32,9 % (2026)**, mientras JAWS subió del 40,5 % al 55,0 %. El dato coincide con un periodo en que JAWS añadió funciones de IA (Picture Smart AI, FS/Vispero Companion, Page Explorer y AI Labeler), que NVDA todavía no tiene de forma nativa.

Del análisis de incidencias de GitHub, el changelog oficial, el catálogo de la tienda de complementos, las encuestas WebAIM y diversos foros salen siete conclusiones:

1. **La IA es ya una función básica.** Según WebAIM n.º 11, el 60,1 % de los usuarios usa IA para describir imágenes y solo el 8,2 % no usa IA para ninguna tarea. NVDA integró un descriptor de imágenes local (PR #18475), lo **revirtió** en enero de 2026 (PR #19425) por su baja calidad y su consumo de RAM, y ahora lo está rediseñando (ADR #20641). La tienda de NVDA tiene unos 24 complementos relacionados con IA.
2. **La calidad de voz preocupa mucho.** eSpeak NG suena robótico. El adaptador no oficial que permite usar las voces naturales de Narrador (NaturalVoiceSAPIAdapter) tiene unas 964 estrellas en GitHub, muchas más que cualquier complemento de NVDA. La incidencia #13288, sobre voces naturales, sigue abierta.
3. **Muchas funciones viven en complementos y se rompen cada año.** NVDA rompe la API de complementos en todas las versiones .1 (2024.1, 2025.1, 2026.1 y también 2027.1). El 6 de mayo de 2026 solo **113 de 397 complementos (28,4 %)** eran compatibles con NVDA 2026.1.
4. **Funciones que JAWS tiene desde hace años y NVDA no tiene, o acaba de incorporar:** historial de voz completo (JAWS lo tiene desde 2013; NVDA solo tiene "repetir/copiar lo último" desde 2026.2-2026.3), búsqueda de comandos o paleta (JAWS desde 2015; NVDA #17209 abierta), configuración por sitio web (JAWS desde 2016; NVDA #4442 abierta desde 2014), etiquetas personalizadas de controles (#17332), marcadores de posición, cinta virtual y niveles de verbosidad (#46, abierta desde 2008).
5. **La navegación web tiene errores de larga duración.** La incidencia abierta con más votos es #3858 (listas de definición, de 2014). También pesan las lecturas dobles en diálogos (#8971), `aria-controls` (#8983), los párrafos pegados (#17514) y la falta de navegación circular (#11085).
6. **Persisten bloqueos y falta de rendimiento.** Hay casos en Excel (#15281), en proveedores UIA lentos (#20654), al recargar la configuración (#14872) y en controles RichEdit (#14285).
7. **Se necesita gestionar el audio y la entrada.** NVDA ya incluye la división de sonido (desde 2024.2), pero sigue faltando controlar el volumen de otras aplicaciones, cambiar el dispositivo de salida y silenciar el micrófono (#16056, con 40 comentarios). También faltan AltGr (#10767), una tecla modificadora configurable (#16607) y un teclado numérico híbrido en la distribución de portátil (#16479).

**Recomendación principal para Tiresias:** construir un núcleo con una API de extensiones estable, que no se rompa cada año, e incluir desde el principio lo que hoy la gente obtiene a través de complementos: historial de voz, capa de IA multiproveedor, OCR multimotor, mezclador de audio, etiquetas y marcadores, paleta de comandos, perfiles por sitio web y aplicación, y voces neuronales locales.

---

## 2. Metodología y fuentes

### 2.1 Procedimiento

| Fuente | Qué se hizo | Volumen |
|---|---|---|
| GitHub `nvaccess/nvda`, incidencias | Consultas a la API de búsqueda de GitHub ordenadas por reacciones, por "+1" y por número de comentarios. Se cruzaron las abiertas, las que tienen la etiqueta `feature` y las cerradas como completadas. | 2.221 incidencias abiertas; 220 abiertas con etiqueta `feature`; 243 cerradas con `feature` |
| GitHub `nvaccess/nvda`, Discussions | GraphQL, ordenado por interacciones | 365 discusiones |
| Changelog oficial | Lectura de las secciones "New Features" de 2024.1 a 2026.2 en la web y de 2026.3 y 2027.1 en el `changes.md` local | 9 versiones |
| Catálogo de la tienda de complementos | Descarga del JSON `addonStore.nvaccess.org/en/all/2026.2.0.json` y clasificación por palabras clave | 499 entradas, 414 identificadores únicos |
| WebAIM | Encuestas n.º 10 (dic. 2023-ene. 2024, 1.539 respuestas) y n.º 11 (jul.-ago. 2026, 1.780 respuestas) | — |
| JAWS / Vispero | Cronología oficial de JAWS, artículos sobre JAWS 2025 y 2026 | — |
| Foros y blogs | nvda.groups.io (a través de los fragmentos que devuelve el buscador), el wiki "Switching from JAWS to NVDA", Blind Access Journal (febrero de 2026), AccessWorld/AFB, el hilo de estadísticas de nvda-users, nvda.es y AudioGames | — |

**Limitaciones:**
- La comunidad de NVDA casi no usa las reacciones de GitHub: la incidencia más votada solo tiene 23. Por eso se usó el **número de comentarios** como indicador complementario de demanda.
- Reddit bloqueó el acceso automatizado. Los archivos de groups.io (nvda@nvda.groups.io y lista@nvdaes.groups.io) exigen JavaScript o registro, así que sus hilos solo se citan a través de los fragmentos que devuelve el buscador.
- La tienda de NV Access no publica cifras de descargas, de modo que la popularidad de los complementos se deduce de recomendaciones editoriales, estrellas en GitHub y menciones en debates.
- No se ha inventado ningún número de incidencia. Todos los citados se comprobaron con la API de GitHub.

**Qué significa "Python puro" en este documento:** Python con `ctypes`, `comtypes`, `pywin32` o `winrt` y DLL del sistema o de terceros ya compiladas (por ejemplo liblouis u onnxruntime), sin escribir código C/C++ propio que haya que inyectar en otros procesos. Cuando una función necesita *hooks* en proceso (como el display model GDI o los búferes virtuales de alto rendimiento de NVDA), se marca como "No".

### 2.2 URLs principales

- Incidencias de NVDA: https://github.com/nvaccess/nvda/issues (consultas `sort=reactions`, `sort=comments` y `label:feature`)
- Discussions de NVDA: https://github.com/nvaccess/nvda/discussions
- Changelog de NVDA: https://download.nvaccess.org/documentation/changes.html
- Catálogo de la tienda: https://addonStore.nvaccess.org/en/all/2026.2.0.json
- WebAIM n.º 10: https://webaim.org/projects/screenreadersurvey10/
- WebAIM n.º 11: https://webaim.org/projects/screenreadersurvey11/
- Estadísticas de compatibilidad de complementos con 2026.1: https://groups.google.com/a/nvaccess.org/g/nvda-users/c/F3Rav4HvBgE
- Wiki "Switching from JAWS to NVDA": https://github.com/nvaccess/nvda/wiki/SwitchingFromJawsToNVDA
- Un usuario de JAWS prueba NVDA durante una semana: https://blindaccessjournal.com/2026/02/one-week-with-nvda-a-jaws-users-immersion-journey/
- Complementos esenciales según AccessWorld: https://www.afb.org/blog/entry/accessworld-classics-editors-list-essential-nvda-addons
- Cronología de JAWS: https://vispero.com/jaws-timeline/
- JAWS 2026 (Page Explorer y AI Labeler): https://doubletaponair.com/page-explorer-ai-labeller-inside-jaws-2026s-smartest-tools/
- Narrador, descripciones de imagen enriquecidas: https://blogs.windows.com/windows-insider/2025/07/18/announcing-windows-11-insider-preview-build-26200-5710-dev-channel
- NaturalVoiceSAPIAdapter: https://github.com/gexgd0419/NaturalVoiceSAPIAdapter
- Comunidad hispanohablante de NVDA: https://nvda.es/descargas/complementos/ y https://nvda.es/descargas/complementos/complementos-de-pago/
- Hilos de nvda.groups.io (vía buscador): https://nvda.groups.io/g/nvda/topic/how_different_is_nvda/28834743 y https://nvda.groups.io/g/nvda/topic/question_about_nvda/106359072

### 2.3 Funciones que ya forman parte del núcleo de NVDA (2024-2026)

Esta tabla evita presentar como carencias cosas que NVDA ya resolvió.

| Versión | Función que entró en el núcleo | Origen o incidencia |
|---|---|---|
| 2019.x | Cortina de pantalla | #7857 |
| 2024.1 | Modo de voz "a petición"; modo de selección nativa en Firefox; acciones masivas en la tienda | #481 (antes, el complemento NoBeepsSpeechMode) |
| 2024.2 | División de sonido (*sound split*); modo braille "mostrar la salida de voz"; nuevas teclas de navegación rápida (párrafo, mismo estilo, etc.) | #12985 (de Tony's Enhancements), #15998 |
| 2024.3 | Normalización Unicode en voz y braille; aviso de actualizaciones de complementos | #11570, #16466 |
| 2024.4 | Tiempo configurable para pulsaciones múltiples; atributos de fuente separados para voz y braille | #11929 |
| 2025.1 | **Acceso remoto** (antes el complemento NVDA Remote); actualización automática de complementos en segundo plano; refresco de OCR; selección nativa en Chromium | #4390, #3208 |
| 2025.2 | Informe del idioma del texto; títulos 7-9; Windows Voice Access | #17664 |
| 2026.1 | **NVDA de 64 bits con Python 3.13**; MathCAT integrado; SAPI5 de 64 bits; lectura automática tras el OCR; errores ortográficos señalados con sonido | #18323, #19432 |
| 2026.2 | **Lupa integrada**; repetir lo último dicho (NVDA+x; con doble pulsación lo muestra en un mensaje navegable); desplazamiento automático en braille; navegación web táctil | #19228, #625, #3424 |
| 2026.3 (beta) | **Copiar lo último dicho** (NVDA+control+x); historial en el diálogo Buscar; navegación por oraciones ampliada; "decir todo" por oraciones; segmentación de palabras con ICU y para chino; navegación rápida a elementos pulsables; enrutado múltiple en braille | #19385, #8482, #18901, #13420, #18735, #14429 |

También se retiró soporte. Desde 2026.1 NVDA exige Windows 10 o posterior, no funciona en Windows de 32 bits ni en Windows 10 ARM, y ya no es compatible con MathPlayer.

---

## 3. Quejas y carencias más frecuentes de NVDA

### 3.1 Voz y audio

**a) Calidad y naturalidad de la voz.**
- La incidencia #13288, que pide soporte para las voces naturales de Windows 11, sigue abierta con la etiqueta `blocked/needs-external-fix`.
- La discusión #17933 propone integrar un TTS neuronal local (Piper, Kokoro, etc.).
- El adaptador no oficial **NaturalVoiceSAPIAdapter** tiene unas 964 estrellas en GitHub. Su propio README avisa de que puede dejar de funcionar con cualquier actualización de Windows, porque Microsoft no permite oficialmente ese uso.
- nvda.es ofrece **17 complementos de síntesis**, cuatro de ellos de pago (Tiflotecnia, Acapela, Code Factory Eloquence/Vocalizer y Nuance Vocalizer). Esto indica que la oferta gratuita en español no satisface a todos.
- En la tienda oficial hay voces neuronales en complementos (`sonataSherpaVoices`, `NVDAKittenTTS`, `dengjen_neural_voices`).

*Propuesta para Tiresias:* incluir de serie un motor neuronal **local** (Piper o sherpa-onnx con ONNX Runtime), con voces en español de España y de Latinoamérica descargables. Mantener además OneCore, SAPI5 de 64 bits y eSpeak NG como alternativa de baja latencia. Medir la latencia hasta el primer audio como objetivo de calidad.

**b) Historial de voz.**
- La petición #625, de 2010, se resolvió parcialmente en 2026.2: NVDA+x repite lo último. En 2026.3 llega la copia (#19385).
- El **historial navegable completo** (#18400, "Native Speech History", 28 comentarios) sigue abierto con prioridad p4.
- El complemento *Speech History* es el primero de la lista de complementos esenciales de AccessWorld. Es uno de los que se rompieron con 2026.1 según el hilo de estadísticas.
- JAWS tiene historial de voz desde 2013.

*Propuesta:* historial nativo con unas 500 entradas, navegación hacia atrás y adelante, búsqueda, filtro por origen (notificación, foco, escritura), copia y exportación, y un modo "solo notificaciones", equivalente al Notification History de JAWS.

**c) Idiomas y números.**
- La detección automática de idioma por rangos Unicode (#2990, de 2013, con 77 comentarios) sigue abierta. Existe el complemento `enhancedLanguageDetection`.
- La lectura de números dígito a dígito (#4273, 79 comentarios) también sigue abierta. La discusión #18398 pide deletrear indicativos alfanuméricos.

*Propuesta:* detectar el idioma por guion de escritura y por modelo ligero, algo vital para quien alterna español e inglés. Ofrecer modos de lectura de números (completo, por dígitos, por grupos) asignables a perfiles.

**d) Verbosidad.**
- La petición de niveles de verbosidad (#46) está abierta **desde 2008**.
- Cambiar el orden en que se anuncian las propiedades de un objeto (#7232, 31 comentarios) también sigue abierto.
- Se pide acortar anuncios como "encabezado nivel 2" (#17483) y anunciar las acciones de cortar, copiar y pegar (#19042, 35 comentarios).
- Un usuario de JAWS que probó NVDA una semana echó en falta reacción hablada al copiar y guardar, y una **velocidad de voz independiente para el eco de teclado** (Blind Access Journal, 2026).

*Propuesta:* niveles de verbosidad predefinidos (principiante, intermedio, experto) y plantillas de anuncio editables por rol, con orden y texto configurables. Velocidad propia para el eco de escritura. Confirmaciones de portapapeles activables.

**e) Gestión del audio del sistema.**
- La división de sonido ya está en el núcleo desde 2024.2.
- Siguen abiertos el volumen de las demás aplicaciones (discusión #16049), **silenciar el micrófono** (#16056, 40 comentarios) y un atajo para cambiar de dispositivo de salida (#8801).
- En la tienda hay unos 21 complementos de audio y volumen, como `audioManager`, `volumeManager`, `unmute`, `enhancedDuck` y `selectorSalidaAudioNVDA` (este último, de la comunidad hispana).

*Propuesta:* mezclador integrado con volumen por aplicación, cambio de dispositivo, silencio del micrófono con confirmación sonora y atenuación configurable. Se puede hacer en Python con `pycaw` o `comtypes` sobre WASAPI.

**f) Señales sonoras ("earcons") y audio espacial.**
- Hay complementos que lo cubren: *Earcons and speech rules*, *Unspoken-ng 3D Audio*, *Advanced Audio Themes* y *Object Location Tones*.
- Están abiertas las peticiones de sonidos por tipo de control (#4089) y de un aviso sonoro al llegar a un límite (#13612).
- En nvda.groups.io algunos usuarios señalan que JAWS ofrece "muchas más opciones" para indicar elementos web mediante sonidos.

*Propuesta:* temas de sonido nativos (rol, estado, límites, carga de página) con audio posicional opcional.

### 3.2 Navegación web

- **Errores ARIA y HTML de larga duración:**
  - #3858, listas de definición: la incidencia abierta más votada, de 2014.
  - #8971, NVDA lee dos veces el contenido de los diálogos.
  - #8983, soporte de `aria-controls`.
  - #17514, NVDA pega párrafos cuando el CSS usa `display:block` en `::before`.
  - #19453, regiones duplicadas en modales.
  - #17662, `aria-live="assertive"` no interrumpe la voz como debería.
  - #9168, roles DPUB (31 comentarios).
- **Navegación circular:** al llegar al último encabezado NVDA se detiene (#11085, abierta). El complemento *screen wrapping* cubre la carencia y el wiki "Switching from JAWS" lo recomienda.
- **Configuración por sitio web:** #4442 (31 comentarios, abierta desde 2014). En JAWS existe desde 2016. También se pide asociar diccionarios a perfiles (#3656).
- **Resumen de la página al cargar:** hoy lo cubre el complemento *Page Reporter*. JAWS 2026 añade *Page Explorer*, que resume la página con IA. También se pide un indicador de carga (#16960).
- **Diferencias con JAWS** que citan quienes migran:
  - Leer la URL sin mover el foco.
  - Inspeccionar los atributos de un elemento (Shift+Insert+F1 en JAWS).
  - El modo de formularios semiautomático: el usuario de Blind Access Journal se quedaba atascado en el modo equivocado.
  - Que la navegación por artículos no tenga tecla asignada por defecto (wiki).
- **Lista de elementos:** se piden pestañas (#20245) y elementos pulsables (#14429; la navegación rápida llega en 2026.3).
- **Aplicaciones web complejas** como Google Docs o editores Monaco: la discusión #15995 propone un puente de accesibilidad en JavaScript. Existe el complemento *WebAccess*.

*Propuesta para Tiresias:*
- Modo exploración con navegación circular configurable y resumen hablado al cargar.
- Perfiles por dominio que incluyan ajustes, diccionarios, etiquetas y marcadores.
- Comando para leer la URL y un inspector de elementos.
- Detección automática de formularios con "modo bloqueado".
- Un banco de pruebas propio con los casos ARIA citados arriba.

### 3.3 Aplicaciones específicas

- **Microsoft Office:**
  - Excel se congela con NVDA (#15281).
  - "Decir todo" no recorre la hoja (#6624).
  - Faltan los encabezados en hojas protegidas (#18537).
  - En Word, las viñetas no se tratan como listas (#7742).
  - Las tablas de PowerPoint no se anuncian (#5350).
  - En Outlook se pide no leer automáticamente la primera línea (#15310).
  - Complementos que cubren huecos: *Outlook Extended* y *Ribbon Menu* (equivalente a la cinta virtual de JAWS).
- **Mensajería y Electron:** Teams lee dos veces las tarjetas adaptativas (#14448). WhatsApp y Discord con navegación rápida se congelan y disparan la CPU (#18507). Hay complementos específicos: `whatsAppNG`, `accessibleDiscord` y `telegramDesktop`.
- **Terminales:** se leen líneas invisibles con `less` y `more` (#13157) y NVDA se cuelga con mucho texto (#20902). Existe el complemento *Terminal Access*.
- **Java e IDE:** límites de palabra incorrectos en Java (#16374). Complementos: `IntelliJImproved` y *Notepad++*.
- **Controles sin etiqueta:**
  - La petición de un etiquetador de objetos existe desde 2012 (#2111, trasladada a #17332, que tiene 4 reacciones).
  - Lo cubre el complemento *Custom Labels*.
  - JAWS 2026 añade **AI Labeler**, que etiqueta campos automáticamente.
- **Gestión de ventanas:** se pide un cambio rápido de ventanas y aplicaciones (#9460). Lo cubren los complementos *SysTrayList* (bandeja del sistema), *Win Wizard*, *Task Switcher* y *Windows App Essentials*.
- **Aplicaciones antiguas:** se pide mejorar el display model GDI (#19390). JAWS usa un controlador de vídeo propio.

*Propuesta:* un sistema de módulos por aplicación declarativo, en YAML o Python, para que la comunidad pueda corregir aplicaciones sin tocar el núcleo. Etiquetas personalizadas nativas, con propuesta automática por IA. Lista de la bandeja del sistema y de ventanas. Módulos prioritarios: Office, Outlook, WhatsApp, Teams, terminal y VS Code.

### 3.4 Configuración y usabilidad

- **Paleta de comandos o buscador de órdenes** (#17209): 5 reacciones y 26 comentarios. JAWS tiene "Command Search" desde 2015.
- **Conflictos de gestos:**
  - Se pide avisar al sobrescribir un gesto (#3605) y detectar colisiones entre complementos (#15242, 21 comentarios).
  - Existe el complemento *Check Input Gestures*.
  - NVDA 2026.3 por fin permite editar un gesto existente (#10983).
- **Teclado:**
  - Soporte de AltGr (#10767, 36 comentarios).
  - Tecla modificadora personalizada (#16607).
  - Teclado numérico nativo en la distribución de portátil (#16479, 25 comentarios). Lo cubre el complemento *Numpad Nav Mode*.
  - Hacer opcional el anuncio de los cambios de distribución (#1676, 38 comentarios).
- **Perfiles:**
  - Bloquear perfiles (discusión #17415).
  - Que el guardado automático no sea la opción por defecto (discusión #13256). Existe el complemento *Readonly Profiles*.
- **Aprendizaje:** se pide un tutorial para usuarios nuevos (#7242). Las voces de los foros echan en falta los mensajes de ayuda de JAWS; el complemento *Command Helper* "no llega a ese nivel". JAWS 2025 añadió *FS Companion*, un asistente de IA que responde preguntas sobre JAWS y Office.
- **Entornos corporativos:** se pide un modo corporativo (#16599, 22 comentarios). En la discusión #16295 se recuerda que muchas empresas no dejan instalar complementos.
- **Arranque:** se pide no hablar al arrancar (#19118) y un atajo para arrancar sin complementos (#17210).

*Propuesta:*
- Paleta de comandos con búsqueda difusa (*fuzzy*) que también ejecute comandos sin gesto asignado.
- Editor de gestos con detección de conflictos.
- Soporte de AltGr y modificador configurable, con el teclado numérico en modo híbrido.
- Perfiles de solo lectura.
- Tutorial interactivo y asistente de ayuda con IA.
- Directivas corporativas mediante un archivo de política.

### 3.5 Rendimiento y estabilidad

- **Bloqueos:**
  - Al recargar la configuración (#14872, 35 comentarios).
  - Unos 5 segundos cuando un proveedor UIA es lento (#20654, de 2026).
  - Excel (#15281).
  - Cierre al mantener pulsada la flecha abajo en documentos grandes (#13334).
  - Visual Studio, Thunderbird y Cheat Engine (#17889, #18315, #20230).
- **Latencia y procesamiento de eventos:** latencia de la voz que desaparece cuando hay un diálogo de NVDA abierto (#19551). Se propone limitar los eventos procesados (#11077) y optimizar el arranque (#18857).
- NVDA 2026.3 introduce una caché en segundo plano y recuperación ante aplicaciones que no responden. Eso confirma que el problema es estructural.

*Propuesta:* arquitectura con un **hilo de voz aislado**, que nunca se bloquee por COM o UIA, y llamadas entre procesos con tiempos de espera y cancelación. Cola de eventos con coalescencia y prioridad por objeto de interés. Un *watchdog* que recupere el control en menos de un segundo. Métricas de latencia integradas. En Python es viable siempre que se separe la recepción de eventos UIA en hilos MTA dedicados.

### 3.6 Braille

- La encuesta WebAIM n.º 10 indica que el 38 % usa braille.
- Peticiones abiertas:
  - Orden configurable de las propiedades en braille (#7232).
  - Varias pantallas braille a la vez (#6614).
  - Descripción braille de emojis (#9213).
  - Cómo mostrar los caracteres no definidos (#8702).
  - Encabezados de Excel en braille (#6901).
  - Atributos de fuente con los puntos 7 y 8 (#7097).
- *Braille Extender*, el complemento más completo, se quedó incompatible con 2026.1.
- JAWS ofrece *Split Braille*, que divide la línea en dos regiones.

*Propuesta:* liblouis mediante `ctypes`, orden y abreviaturas configurables por rol, división de la línea, soporte para pantallas multilínea y DotPad, y emojis descritos.

### 3.7 OCR e IA

- **IA en JAWS y en Narrador:**
  - JAWS: Picture Smart AI (2024), FS Companion (2025), Page Explorer y AI Labeler (2026) y Face in View, que guía el encuadre de la cámara.
  - Narrador ofrece descripciones de imagen enriquecidas en los equipos Copilot+ (Narrador + Ctrl + D).
- **Historia de la IA en NVDA:**
  - Integró un descriptor local (PR #18475, septiembre de 2025).
  - Lo revirtió (PR #19425, enero de 2026) porque generaba "subtítulos de baja calidad de un modelo de hace 3 años" y dependía de numpy, que consumía mucha RAM.
  - El ADR #20641 propone reintegrarlo con Qwen 3.5 0.8B en ONNX, que tarda aproximadamente un minuto por descripción.
- **Demanda según WebAIM n.º 11:**
  - 60,1 % usa IA para describir imágenes.
  - 49,7 % la usa para analizar imágenes complejas.
  - 40,6 % la usa como guía en tareas en línea.
  - 37,1 % la usa para resumir páginas o documentos.
- **Complementos de IA:** *AI Content Describer* trabaja con GPT, Gemini, Claude, Grok, Pixtral y modelos locales. *Vision Assistant Pro* traduce, describe la pantalla y analiza vídeo. El usuario de JAWS de Blind Access Journal destacó *Vision Assistant Pro* como lo mejor que encontró. *Computer Use* controla aplicaciones a partir de instrucciones.
- **OCR:**
  - NVDA usa Windows OCR, con refresco desde 2025.1 y lectura automática desde 2026.1.
  - Se pide elegir el motor (#17406, 15 comentarios), PaddleOCR (#18663), corregir el orden en textos de derecha a izquierda (#20475), respetar el orden en tablas (#13478) y procesar archivos completos (#12981).
  - Complementos: *NAO* (OCR avanzado con PDF), *LION* (OCR continuo para subtítulos), *Tesseract OCR* y *Xinyi OCR*.
  - JAWS tiene Convenient OCR desde 2011, con PDF y escáner.

*Propuesta:*
- Una **capa de proveedores de IA** desacoplada del núcleo: local con ONNX y nube con clave propia del usuario.
- Comandos para describir el control, la ventana, la pantalla o un archivo, con preguntas de seguimiento por chat.
- Resumen de la página o del documento.
- Sugerencia automática de etiquetas para controles.
- Ayuda contextual con IA sobre el propio Tiresias.
- **OCR multimotor** (Windows OCR, Tesseract o PaddleOCR) para pantalla, archivo, PDF y portapapeles, con modo continuo para subtítulos.
- Privacidad explícita: avisar siempre de cuándo sale una imagen del equipo.

### 3.8 Portabilidad, instalación y acceso remoto

- **Copias portátiles:** se piden nombres de carpeta con la versión (#18953, 27 comentarios). Los complementos siguen ocupando disco tras desinstalar (#6869, 23 comentarios).
- **Requisitos:** desde 2026.1 solo Windows 10 u 11 de 64 bits. Se pide que funcione con Wine (#11027).
- **Acceso remoto:**
  - Ya está en el núcleo desde 2025.1.
  - Se piden preajustes de conexión (#20583).
  - Sigue abierto **enviar la voz por canales RDP** (#3564, 79 comentarios), algo crítico en empresas con Citrix o escritorio remoto. Existe el complemento *RDAccess*.

*Propuesta:* modo portátil de primera clase, con configuración junto al ejecutable y sin necesidad de ser administrador. Separar claramente las limitaciones de UIAccess que tiene la copia portátil. Acceso remoto con preajustes. A medio plazo, canal RDP virtual. Desinstalación limpia.

### 3.9 Complementos y ecosistema

- **Roturas de compatibilidad:** NVDA rompe la compatibilidad de complementos todos los años (2024.1, 2025.1, 2026.1 y 2027.1, según el `changes.md` local). El 6 de mayo de 2026 solo 113 de 397 complementos estables (28,4 %) funcionaban con 2026.1. *Speech History*, *Braille Extender* y el complemento de Audacity quedaron afectados.
- En la discusión #16295, varios colaboradores piden **limitar las roturas anuales** y recuerdan que hay usuarios con más de 50 complementos instalados.
- La tienda tiene 414 identificadores. Por temática: unos 35 de portapapeles, 24 de IA, 20 de OCR, 17 de traducción, 21 de audio y 37 de voces.

*Propuesta:* API pública con versionado semántico y desaprobación a lo largo de dos versiones mayores. Capa de compatibilidad. Manifiesto con permisos declarados (red, portapapeles, inyección). Detección de conflictos al cargar. Opción de arrancar sin extensiones. Política corporativa para extensiones aprobadas.

---

## 4. Complementos populares que indican carencias del núcleo

| Complemento | Qué aporta | Estado en el núcleo de NVDA | Conclusión para Tiresias |
|---|---|---|---|
| Speech History (J. Scholes) | Historial navegable y copia | Parcial: repetir en 2026.2 y copiar en 2026.3. El historial (#18400) sigue abierto | Nativo y completo |
| NVDA Remote | Control remoto | Núcleo desde 2025.1 | Nativo, con preajustes |
| Sound Splitter / Tony's Enhancements | Dividir canales; volumen de otras aplicaciones | División en núcleo desde 2024.2; volumen y micrófono, no | Mezclador completo |
| AI Content Describer / Vision Assistant Pro | Descripción con IA y chat | No (revertido; ADR #20641) | Capa de IA nativa |
| NAO / LION / Tesseract OCR | OCR avanzado, continuo y de archivos | OCR de Windows básico | OCR multimotor |
| Golden Cursor | Ratón por teclado y posiciones guardadas | No | Nativo |
| Custom Labels | Etiquetar controles | No (#17332) | Nativo, con IA |
| Place Markers | Marcadores y búsqueda en documentos | No (#498 abierta) | Nativo, por sitio |
| Clip Contents Designer / ClipHistory / Clipspeak | Portapapeles acumulativo, historial, anuncios | No (#19042 abierta) | Nativo |
| Instant Translate | Traducción de selección o portapapeles | No | Integrado en la capa de IA o traducción |
| WordNav / SentenceNav / IndentNav / BrowserNav | Navegación por palabra (camelCase), oración, sangría, columnas | Parcial: oraciones e ICU en 2026.3; sangría y camelCase, no (#16467, #16237) | Nativo |
| Earcons and speech rules / Unspoken-ng / Object Location Tones | Sonidos por rol y posición 3D | No | Temas sonoros nativos |
| Screen wrapping / Page Reporter | Navegación circular; resumen de página | No (#11085) | Nativo |
| SysTrayList / Win Wizard / Task Switcher | Bandeja del sistema, ventanas, procesos | No (#9460) | Nativo |
| Numpad Nav Mode / Check Input Gestures | Teclado numérico híbrido; conflictos de gestos | No (#16479, #15242) | Nativo |
| Readonly Profiles | Perfiles que no se guardan solos | No | Nativo |
| Character Information | Información Unicode del carácter | Parcial | Nativo |
| Easy Table Navigator / Columns Review | Tablas con flechas; listas con columnas | Parcial | Capa de tablas |
| Enhanced Touch Gestures | Gestos táctiles | En gran parte en el núcleo (2026.2-2026.3) | Prioridad baja |
| Outlook Extended / Ribbon Menu / Notepad++ / WhatsApp NG / Windows App Essentials | Mejoras por aplicación | No | Módulos de aplicación oficiales |
| MathCAT | Matemáticas | Núcleo desde 2026.1 | Integrar MathCAT |
| Focus Highlight / Screen Curtain / Magnifier | Funciones visuales | Núcleo | Integrar más adelante |
| NaturalVoiceSAPIAdapter (no es un complemento) | Voces naturales de Microsoft | No (#13288) | Voces neuronales locales |

---

## 5. Tabla priorizada de funciones nativas para Tiresias

Esfuerzo: **B** = bajo (días), **M** = medio (semanas), **A** = alto (meses).

| # | Función | Prioridad | Esfuerzo | ¿Python puro? | Evidencia principal |
|---|---|---|---|---|---|
| 1 | Núcleo de voz con hilo aislado, cola con prioridades y cancelación inmediata | Alta | A | Sí | #19551, #20654, #14872 |
| 2 | Voces: OneCore, SAPI5 de 64 bits, eSpeak NG y **TTS neuronal local** (Piper o sherpa-onnx) | Alta | M | Sí (ONNX Runtime) | #13288, disc. #17933, NaturalVoiceSAPIAdapter |
| 3 | Historial de voz completo (navegar, buscar, copiar, exportar, filtrar notificaciones) | Alta | B | Sí | #18400, #625, AccessWorld |
| 4 | Capa de IA multiproveedor (local y nube): describir control, ventana, pantalla o archivo, con chat de seguimiento | Alta | M | Sí | WebAIM n.º 11 (60,1 %), PR #18475/#19425, ADR #20641 |
| 5 | OCR multimotor (Windows OCR, Tesseract, PaddleOCR) de pantalla, archivo, PDF y portapapeles, con modo continuo | Alta | M | Sí | #17406, #18663, #12981, NAO, LION |
| 6 | API de extensiones estable con versionado semántico y capa de compatibilidad | Alta | M | Sí | 28,4 % compatible con 2026.1; disc. #16295 |
| 7 | Modo exploración web (UIA/IA2) con navegación rápida y circular | Alta | A | Sí, con matices de rendimiento | #11085, wiki JAWS→NVDA |
| 8 | Banco de pruebas ARIA (listas de definición, diálogos, `aria-controls`, live regions) | Alta | M | Sí | #3858, #8971, #8983, #17662, #17514 |
| 9 | Paleta de comandos con búsqueda difusa | Alta | B | Sí | #17209; JAWS Command Search |
| 10 | Mezclador de audio: división, volumen por aplicación, dispositivo de salida, silencio del micrófono | Alta | M | Sí (pycaw/WASAPI) | #16056, disc. #16049, #8801 |
| 11 | Perfiles por aplicación **y por dominio web**, con diccionarios y modo de solo lectura | Alta | M | Sí | #4442, #3656, disc. #17415 |
| 12 | Etiquetas personalizadas de controles, con sugerencia de IA | Alta | M | Sí | #17332 (#2111), JAWS AI Labeler |
| 13 | Teclado: AltGr, modificador configurable, teclado numérico híbrido, detección de conflictos | Alta | M | Sí (hook de teclado con ctypes) | #10767, #16607, #16479, #15242 |
| 14 | Detección automática de idioma (por guion de escritura y modelo ligero) | Alta | M | Sí | #2990 (77 comentarios) |
| 15 | Niveles de verbosidad y plantillas de anuncio editables por rol | Media | M | Sí | #46, #7232, #17483 |
| 16 | Portapapeles: historial, anuncio de cortar, copiar y pegar, añadir al portapapeles | Media | B | Sí | #19042; ClipHistory, clipContentsDesigner |
| 17 | Marcadores de posición y búsqueda con historial en documentos y webs | Media | B | Sí | #498; Place Markers; #8482 |
| 18 | Navegación por palabra (camelCase, snake_case), oración, párrafo y sangría | Media | M | Sí | #16237, #16467; WordNav, IndentNav |
| 19 | Lectura de números (completa, por dígitos, alfanumérica) | Media | B | Sí | #4273, disc. #18398 |
| 20 | Temas sonoros y audio posicional por rol, estado y límites | Media | M | Sí | #4089, #13612; Earcons, Unspoken-ng |
| 21 | Resumen de página al cargar e indicador de carga | Media | B | Sí | Page Reporter, #16960, JAWS Page Explorer |
| 22 | Leer la URL sin mover el foco e inspector de atributos del elemento | Media | B | Sí | Wiki JAWS→NVDA, Blind Access Journal |
| 23 | Ratón por teclado y puntos guardados por aplicación | Media | B | Sí | Golden Cursor |
| 24 | Bandeja del sistema, lista de ventanas y procesos, cambio rápido | Media | B | Sí | #9460; SysTrayList, Win Wizard |
| 25 | Módulos de aplicación: Office (Excel, Outlook, cinta), WhatsApp, Teams, terminal, VS Code | Media | A | Sí | #15281, #6624, #14448, #13157 |
| 26 | Braille con liblouis: orden configurable, emojis, división de la línea | Media | A | Sí (DLL de liblouis) | #7232, #9213, #6614 |
| 27 | Velocidad propia para el eco de teclado y confirmaciones de acciones | Media | B | Sí | Blind Access Journal |
| 28 | Traducción instantánea de selección o portapapeles | Media | B | Sí | Instant Translate; 17 complementos de traducción |
| 29 | Tutorial interactivo, ayuda de entrada y asistente de ayuda con IA | Media | M | Sí | #7242; JAWS FS Companion |
| 30 | Modo portátil de primera clase y política corporativa | Media | M | Sí | #18953, #16599, #6869 |
| 31 | Acceso remoto con preajustes y braille remoto | Baja | A | Sí (sockets/TLS) | #4390 (núcleo en NVDA), #20583 |
| 32 | Resumen e interrogación de la página web con IA | Baja | M | Sí | WebAIM n.º 11 (37,1 %), Page Explorer |
| 33 | Cortina de pantalla | Baja | B | Sí (Magnification API) | Paridad con NVDA |
| 34 | Matemáticas con MathCAT | Baja | M | Sí (biblioteca de MathCAT) | #18323 |
| 35 | Voz por canal virtual de RDP o Citrix | Baja | A | No (requiere componente nativo en el servidor) | #3564 (79 comentarios) |
| 36 | Display model GDI para aplicaciones antiguas | Baja | A | No (hooks inyectados) | #19390 |
| 37 | Gestos de panel táctil multitáctil | Baja | M | Sí | #3358 |

---

## 6. Conclusiones

1. **Tiresias no debe limitarse a copiar NVDA; puede ofrecer de serie lo que NVDA reparte en complementos.** La señal más clara de lo que el núcleo de NVDA no cubre son los complementos más recomendados: historial de voz, IA, OCR avanzado, etiquetas, marcadores, portapapeles, mezclador y navegación avanzada.
2. **La IA decide hoy qué lector elige la gente.** La recuperación de JAWS en WebAIM n.º 11 coincide con sus funciones de IA. NVDA retiró su primer intento por mala calidad y por el coste de los recursos. Tiresias puede adelantarse con una capa de IA modular, con proveedores locales y en la nube, que respete la privacidad y no engorde el instalador.
3. **La estabilidad de la API pesa tanto como las funciones.** Que el 71,6 % de los complementos quede inservible al publicarse una versión destruye valor para el usuario. Comprometerse con una API estable es una ventaja competitiva directa.
4. **La experiencia hispana importa.** Sudamérica es región NVDA (67,2 %). La comunidad hispana depende de voces de pago o de soluciones no oficiales para tener voz natural, y alterna constantemente español e inglés. Las voces neuronales locales en español y la detección de idioma deben ser prioridad alta.
5. **El rendimiento debe ser un principio de arquitectura y no un parche.** Los bloqueos de NVDA vienen de llamadas entre procesos que bloquean. En Python, Tiresias debe aislar el hilo de voz y aplicar tiempos de espera a todas las llamadas COM y UIA desde el primer día.
6. **Hay que medir.** Conviene que Tiresias incluya desde el inicio telemetría opcional y anónima de latencia, un registro de bloqueos y un banco de pruebas web basado en las incidencias citadas, para no repetir los problemas de NVDA.
