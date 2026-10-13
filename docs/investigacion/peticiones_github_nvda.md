# Peticiones de funcionalidad abiertas en nvaccess/nvda (GitHub)

Fecha de extracción: 2026-10-06. Fuente: API REST de GitHub (`repos/nvaccess/nvda/issues?state=open`, 2221 issues abiertas + 16 PR abiertas), búsqueda `search/issues`, GraphQL de Discussions (208 discusiones en Ideas/General/Announcement/Polls) y milestones.

Formato: `#NÚMERO | título | comentarios | reacciones | año creación | resumen`. Ordenado dentro de cada área por demanda (reacciones*2 + comentarios). Excluidos los números ya cubiertos en el estudio previo (ver sección final).

Nota: el repositorio tiene 220 issues abiertas con etiqueta `feature` y 153 con `enhancement`; muchas peticiones antiguas (migradas de Trac) no tienen etiqueta, por lo que se añadieron por heurística de título. En NVDA las reacciones son bajas (la mayoría 0-5); los comentarios son mejor indicador de interés.


## Voz / síntesis / verbosidad / diccionarios (77)

#3805 | Read HTML entities, unicode characters, other symbols | 55 | 0 | 2014 | Leer entidades HTML, caracteres Unicode y otros símbolos poco comunes (nombres Unicode) en lugar de omitirlos.
#8065 | NVDA word echo reports half words when an existing word is edited | 36 | 0 | 2018 | Eco de palabras: no anunciar medias palabras al editar una palabra existente; anunciar la palabra completa resultante.
#13967 | Default time delay for Delayed descriptions for characters on cursor movement is too long | 27 | 1 | 2022 | Reducir el retardo por defecto de la descripción diferida de caracteres.
#3286 | Optional reporting of capitals while reading full text (not just characters) | 28 | 0 | 2013 | Opción para indicar mayúsculas (decir "cap"/tono) también al leer texto continuo, no sólo carácter a carácter.
#13519 | NVDA can automatically locate character description from locale of the same family | 22 | 0 | 2022 | Usar descripciones de caracteres de un locale de la misma familia cuando falten.
#15301 | Make NVDA announce shortcut letters by letter name, not as though in a sentence | 17 | 1 | 2023 | Anunciar las letras de atajo (accesos rápidos) con el nombre de la letra, no como si formaran parte de una frase.
#19657 | GUI Improvements for Speech Dictionary Entry Types | 19 | 0 | 2026 | Mejoras de interfaz para los tipos de entrada del diccionario de voz (anywhere, palabra completa, regex, nuevos tipos).
#13431 | Tab characters should be considered blank | 15 | 1 | 2022 | Tratar los caracteres de tabulación como "en blanco" al leer líneas.
#6811 | [Feature Request] Customizable Character Descriptions | 17 | 0 | 2017 | Descripciones de caracteres (deletreo fonético) personalizables por el usuario.
#16676 | Always speak dashes when in combinations with numbers and currency symbols | 17 | 0 | 2024 | Hablar siempre los guiones en combinación con números y símbolos de moneda.
#16345 | Collapse of more than three dots into "padding dots" symbol cannot be disabled | 17 | 0 | 2024 | Permitir desactivar el colapso de más de tres puntos en el símbolo "puntos de relleno".
#20487 | Please add a phonetic phoneme option to the NVDA dicspeech dictionaries dialogue | 16 | 0 | 2026 | Añadir opción de fonemas/notación fonética (IPA/SSML phoneme) en el diálogo de diccionarios de voz.
#17617 | When the option "Delayed descriptions for characters on cursor movement" is selected, use speech and Braille output when the Braille display performs braille cursor jumps. | 16 | 0 | 2025 | Descripción diferida de caracteres por voz y braille.
#4252 | Provide more options for manipulating speech dictionary entries | 14 | 0 | 2014 | Más opciones para manipular entradas del diccionario de voz (reordenar, copiar, importar/exportar).
#20605 | Make the announcement number of repeated symbols configurable instead of always being more than 3 | 12 | 0 | 2026 | Hacer configurable el umbral de repetición de símbolos (hoy siempre >3) — PR #20940 en curso.
#10318 | Request: pause between reading different types of information | 12 | 0 | 2019 | Insertar pausa entre distintos tipos de información de un elemento (nombre, rol, atajo, posición).
#3283 | Formatting attributes should be seperated with a comma sign | 12 | 0 | 2013 | Separar atributos de formato con comas al anunciarlos.
#13565 | NVDA and Punctuation | 10 | 0 | 2022 | Puntuación y eco de palabras: no partir palabras en apóstrofos ni otros símbolos al hablar palabras escritas.
#3762 | Ability to reset punctuation / symbol pronunciation to default.  Was: Reset ALL settings | 10 | 0 | 2014 | Poder restablecer la pronunciación de puntuación/símbolos a valores de fábrica.
#13915 | Create option "NVDA is considered idle after X ms", low priority speech is announced after idle. | 10 | 0 | 2022 | Opción "NVDA se considera inactivo tras X ms": anunciar voz de baja prioridad tras la inactividad.
#13660 | Add Enable/Disable for Individual Dictionary Entries | 9 | 0 | 2022 | Habilitar/deshabilitar entradas individuales del diccionario sin borrarlas.
#4599 | Make default pronunciation of some symbols more intuitive | 9 | 0 | 2014 | Pronunciaciones por defecto más intuitivas para algunos símbolos.
#11756 | Skim reading: add easy commands to control the speech speed | 1 | 4 | 2020 | Lectura rápida (skim): comandos sencillos para subir/bajar velocidad durante say all.
#13031 | Spoken key commands are interrupted by resulting events of the key command | 9 | 0 | 2021 | Los comandos hablados no deben ser interrumpidos por los eventos que ellos mismos provocan.
#14651 | speech dialog: convurt the (Say cap before capitals) and (beep for capitals) check boxes in to a single combo box | 7 | 1 | 2023 | Diálogo de voz: convertir casillas "decir cap"/"pitido mayúsculas" en un combo de opciones.
#2478 | A filter edit field for the speech dictionaries | 8 | 0 | 2012 | Campo de filtro/búsqueda en el diálogo de diccionarios de voz.
#1398 | an independent option for spelling rate | 8 | 0 | 2011 | Opción de velocidad independiente para el deletreo.
#7107 | make settings synth or profile dependent | 8 | 0 | 2017 | Hacer los ajustes de voz dependientes del sintetizador o del perfil.
#8822 | suggestion, give a possibility to automatically spell the characters in phonetic form | 8 | 0 | 2018 | Deletreo automático con alfabeto fonético.
#5194 | Feature request: Please add Greek alphabet to symbols file | 7 | 0 | 2015 | Añadir el alfabeto griego al archivo de símbolos.
#4738 | Changing speeds for different languages | 7 | 0 | 2014 | Velocidades de voz distintas para cada idioma.
#406 | Each NVDA language should have a prefered voice | 7 | 0 | 2010 | Voz preferida configurada por idioma (cambio automático a esa voz).
#13840 | Feature Request: Compile Mbrola phonemes in Espeak-ng | 7 | 0 | 2022 | Compilar fonemas MBROLA dentro de eSpeak NG.
#3279 | NVDA doesn't say "new line" | 7 | 0 | 2013 | Decir "nueva línea" al pulsar Intro en un editor.
#8057 | Ignore punctuation level when moving by word or greater, and the new caret location starts on punctuation | 7 | 0 | 2018 | Ignorar nivel de puntuación al moverse por palabra o más cuando el caret cae en un signo.
#19264 | possible control over speech interrupt conditions when focus changes (without keyboard input) | 7 | 0 | 2025 | Control de cuándo se interrumpe la voz al cambiar el foco sin pulsar teclas.
#15458 | When reassigning media keys to other key functions, Speech manager should not cancel speech before another key is pressed to make sure the synth driver can handle the complete speech sequence from the last key | 7 | 0 | 2023 | Al reasignar teclas multimedia, no cancelar la voz antes de ejecutar el comando.
#4944 | NVDA say all: add the ability to adjust length of voice pauses for several text units | 6 | 0 | 2015 | Say all: ajustar la duración de las pausas por unidad de texto (frase, párrafo...).
#3736 | Suggestion: allow some pause between the cell content and cell address. | 6 | 0 | 2013 | Pausa entre contenido de celda y su coordenada.
#2992 | An ability to report Unicode name of a currently selected character | 6 | 0 | 2013 | Comando para anunciar el nombre Unicode del carácter actual.
#1593 | Move "Use spelling functionality if supported" setting into sapi4 and sapi5 | 6 | 0 | 2011 | Mover la opción "usar funcionalidad de deletreo" a los drivers SAPI4/SAPI5.
#3188 | Language switching for object reporting | 5 | 0 | 2013 | Cambio automático de idioma también para el anuncio de objetos/controles.
#16431 | Add temporary speech rate setting | 5 | 0 | 2024 | Ajuste temporal de velocidad de voz (no persistente).
#9955 | add parameters for customizing oneCore voices | 5 | 0 | 2019 | Parámetros adicionales para personalizar voces OneCore.
#8237 | Respect "spelling functionality" setting for Windows OneCore voices | 5 | 0 | 2018 | Respetar la opción "usar funcionalidad de deletreo" con voces OneCore.
#4578 | New variant of Edward Voice | 5 | 0 | 2014 | Nueva variante de voz (Edward) para eSpeak.
#16165 | Support the Raul OneCore voice on windows 10 | 5 | 0 | 2024 | Soportar la voz OneCore Raul en Windows 10.
#18985 | Recognize Amharic language numerals | 5 | 0 | 2025 | Reconocer numerales del idioma amhárico.
#11486 | adding musical symbols like notes etc into a dictionary | 4 | 0 | 2020 | Añadir símbolos musicales (notas, etc.) al diccionario de símbolos.
#11751 | NVDA should be able to change the intonation when reporting formatting changes | 0 | 2 | 2020 | Cambiar entonación (tono) al anunciar cambios de formato en vez de verbalizarlos.
#4086 | Different Voice Contexts | 4 | 0 | 2014 | Contextos de voz: voz/parámetros distintos para mensajes, atajos, encabezados de tabla, etc.
#17780 | Silence trimming should trim even more when using one core | 4 | 0 | 2025 | Recorte de silencio más agresivo con OneCore para reducir latencia.
#19638 | Reinstating or Modernizing NV Speech Player (Klatt-based synthesis) within NVDA | 2 | 1 | 2026 | Reintegrar/modernizar NV Speech Player (síntesis Klatt) en NVDA.
#4029 | Add a option to read punctuations when inputting them. | 4 | 0 | 2014 | Leer los signos de puntuación al teclearlos.
#12765 | add choices for how NVDA indicates that text is contained within a track change | 4 | 0 | 2021 | Opciones para indicar texto dentro de control de cambios (voz, sonido, tono).
#1343 | NVDA should have also an object dictionary | 4 | 0 | 2011 | Diccionario de objetos: renombrar roles/estados estándar (casilla, botón...) por idioma o usuario.
#9158 | Add ♩, ♪, ♫ and ♬ to the "symbols.dic" | 3 | 0 | 2019 | Añadir ♩ ♪ ♫ ♬ a symbols.dic.
#20692 | Add context menu support to the symbols list | 3 | 0 | 2026 | Menú contextual en la lista de símbolos (PR #20910 en curso).
#13951 | Add gestures for increase / decrease speech rate | 3 | 0 | 2022 | Gestos dedicados para aumentar/disminuir la velocidad de voz.
#11717 | Make character limit in browse mode smarter | 1 | 1 | 2020 | Límite de caracteres más inteligente en modo exploración (no cortar a mitad de palabra/frase).
#6615 | Ability to have different settings for the different voices of a synthesizer | 2 | 0 | 2016 | Ajustes diferentes para cada voz de un mismo sintetizador.
#19499 | Indicate when typing into a text control has no effect | 2 | 0 | 2026 | Indicar cuando escribir en un control de texto no tiene efecto.
#7750 | Let users decide the order of rules in the list of speech dictionary | 1 | 0 | 2017 | Permitir al usuario decidir el orden de aplicación de reglas del diccionario.
#12239 | Could we get Language Specific Speech Dictionaries | 1 | 0 | 2021 | Diccionarios de voz específicos por idioma (se aplican según el idioma del texto).
#10486 | Option to restore default symbol pronunciation and speech dictionary? | 1 | 0 | 2019 | Opción para restaurar los valores por defecto de símbolos y diccionarios de voz.
#13561 | Don't change dialect when reading a "parent" language | 1 | 0 | 2022 | No cambiar de dialecto cuando el texto está marcado con el idioma "padre" (p.ej. en vs en-GB).
#19649 | Feature Request: Enable Rate Boost feature for SAPI4 synthesizers | 1 | 0 | 2026 | Activar "rate boost" (aumento de velocidad) para sintetizadores SAPI4.
#20708 | Add option for speech viewer to show what is sent to the synthesizer | 1 | 0 | 2026 | Visor de voz: opción para mostrar exactamente lo enviado al sintetizador.
#20324 | media keys should not interrupt speech | 1 | 0 | 2026 | Las teclas multimedia no deben interrumpir la voz.
#8546 | Add abbreviation dictionaries for each language and make them disable by the user | 1 | 0 | 2018 | Diccionarios de abreviaturas por idioma desactivables por el usuario.
#14198 | support ssml in speech dictionary to make it possible to fix pronuntiation issues of onecore and sapi5 voices | 0 | 0 | 2022 | Admitir SSML en el diccionario de voz para corregir pronunciaciones de OneCore/SAPI.
#20693 | Remove all editing combo and edit boxes, and add a new edit symbol dialog | 0 | 0 | 2026 | Rediseñar el diálogo de símbolos: quitar campos de edición y crear diálogo "editar símbolo" (hito 2028.1).
#17257 | Add Emacspeak's voice lock feature | 0 | 0 | 2024 | "Voice lock" estilo Emacspeak: cambiar tono/velocidad según el tipo de elemento o formato.
#19909 | Improve consistency of voice parameters for eSpeak NG in NVDA (Voice vs Language vs Variant) | 0 | 0 | 2026 | Coherencia de parámetros de eSpeak NG (voz vs idioma vs variante).
#20554 | NVDA+x does not always repeat ALL of the last spoken information | 0 | 0 | 2026 | NVDA+x (repetir última frase) debe repetir TODA la última información hablada.
#12383 | Give move to Browse / Focus mode announcement a top priority | 0 | 0 | 2021 | Dar prioridad máxima al anuncio de cambio de modo exploración/foco.
#20954 | Allow the 512-character selection reporting threshold to be configurable | 0 | 0 | 2026 | Hacer configurable el umbral de 512 caracteres para leer la selección.

## Teclado / entrada / gestos (29)

#11678 | Configuration: Consider enabling all available NVDA keys by default | 24 | 0 | 2020 | Habilitar por defecto todas las teclas NVDA disponibles (Insert, Insert numérico, Bloq Mayús).
#10709 | Adding function to speak pasted text | 23 | 0 | 2020 | Función para hablar el texto pegado.
#7074 | Suggestion, possibility to locate a nvda command when pressing the keys | 18 | 0 | 2017 | Localizar un comando de NVDA pulsando sus teclas (búsqueda inversa en gestos).
#8123 | Allow excluding a key stroke from a profile in input gestures dialog | 16 | 0 | 2018 | Excluir una pulsación de un perfil desde el diálogo de gestos.
#7314 | Split out global commands into distinct scripts | 16 | 0 | 2017 | Dividir los comandos globales en scripts distintos (p.ej. leer línea vs deletrear línea).
#6565 | NVDA disables tools that display pressed key strokes | 14 | 0 | 2016 | Compatibilidad con herramientas que muestran pulsaciones (NVDA las inutiliza).
#18188 | Announce Fn key toggle state for the benefit of machines that pass this information to the OS | 12 | 0 | 2025 | Anunciar el estado de la tecla Fn en equipos que lo exponen.
#10775 | Input Gestures: Allow Configuration of all Gestures via the Input Gestures Dialog irrespective of Context | 5 | 3 | 2020 | Configurar todos los gestos desde el diálogo de gestos independientemente del contexto/app.
#3687 | InputGestures: A facility to allow definition of layered gestures via an input capture method | 11 | 0 | 2013 | Gestos en capas (layered) mediante método de captura de entrada.
#15951 | Add ability to ONLY echo keys | 11 | 0 | 2023 | Opción para hacer eco sólo de teclas de comando (no de caracteres).
#3868 | Start NVDA on logon screen with a keyboard command | 11 | 0 | 2014 | Iniciar NVDA en la pantalla de inicio de sesión con un comando de teclado.
#10302 | Add ability to search the Input gesture dialog by keystroke | 10 | 0 | 2019 | Buscar en el diálogo de gestos de entrada por pulsación de tecla.
#10872 | Input Gestures Dialog: Don't allow Duplicate Gestures for the same command to be Defined | 8 | 1 | 2020 | No permitir definir gestos duplicados para el mismo comando (PR #20890 aprobado).
#13024 | Compile a list of NVDA commands unbound by default | 8 | 1 | 2021 | Compilar lista de comandos de NVDA sin asignar por defecto.
#12511 | Speak out loud, or make a sound when the "Insert" key is active. | 10 | 0 | 2021 | Hablar o sonar cuando la tecla Insert (modo sobrescribir) está activa.
#16138 | When the command key is pressed, the modifier key is still passed to other programs. | 9 | 0 | 2024 | Al pulsar un comando NVDA, no pasar la tecla modificadora a otros programas.
#4900 | Input gestures dialog: Filter to only show customised entries | 8 | 0 | 2015 | Filtro para mostrar sólo los gestos personalizados.
#4093 | Ability to Automatically Turn Off the Numlock | 8 | 0 | 2014 | Desactivar automáticamente Bloq Num.
#16242 | Feature suggestion: NVDA automatically cancel reporting of current application title after selecting character from chinese input  | 8 | 0 | 2024 | IME asiático: cancelar el anuncio del título de la app tras elegir un candidato.
#11233 | Allow creation of gestures  set as a modifers for add-ons | 6 | 0 | 2020 | Permitir a complementos definir gestos modificadores (capas).
#20202 | ordinary keys in windows speaking. | 6 | 0 | 2026 | Anunciar también las teclas ordinarias (todas las teclas) al pulsarlas.
#7414 | Enhancement: Identify non-text clipboard contents | 5 | 0 | 2017 | Identificar contenido no textual del portapapeles (imagen, archivos).
#18872 | Announce Add-on Name in Input Help Mode for Add-on Specific Gestures | 3 | 1 | 2025 | En ayuda de entrada, anunciar el nombre del complemento que define el gesto.
#20754 | Allow the ability to distinguish between key presses and key repeats | 4 | 0 | 2026 | Distinguir pulsaciones de repeticiones automáticas de tecla (hito 2026.3).
#11641 | Input Gestures: Add the ability for individual gestures to be reset to factory defaults | 1 | 0 | 2020 | Restablecer gestos individuales a los valores de fábrica.
#15325 | Add function to generate current list of input gestures | 1 | 0 | 2023 | Función para generar la lista actual de gestos de entrada.
#10982 | Input Gestures Dialog: Allow the selection of either Desktop or Laptop Keyboard Layouts when defining a Gesture | 0 | 0 | 2020 | Elegir distribución sobremesa/portátil al definir gestos.
#19474 | Add keypress visualizer | 0 | 0 | 2026 | Visualizador de pulsaciones de teclas (para baja visión/formación).
#20889 | Allow "Beep if typing lowercase letters when caps lock is on" to optionally only apply in text fields | 0 | 0 | 2026 | Pitido de minúsculas con Bloq Mayús activo sólo en campos de texto.

## Modo exploración / web / ARIA (74)

#4896 | Click to move focus & system carat in web pages | 40 | 3 | 2015 | Clic del ratón mueve el foco y el caret del sistema en páginas web (baja visión).
#4049 | ARIA Flowto regions are not announced or traversable in Browse Mode | 20 | 4 | 2014 | Anunciar y permitir recorrer regiones ARIA flowto en modo exploración.
#6283 | NVDA does not pronounce "aria-orientation" attribute | 17 | 5 | 2016 | Anunciar el atributo aria-orientation.
#10890 | aria-sort changes not announced when the change is not on the focused element | 13 | 6 | 2020 | Anunciar cambios de aria-sort aunque no estén en el elemento con foco.
#4637 | NVDA Find dialog: if a next occurence of the entered text is not found, ask the user if they would like to begin searching from the top | 25 | 0 | 2014 | Buscar: si no hay más coincidencias, preguntar si volver al principio.
#3997 | Virtual buffer: An option to put container entry/leaving announcement (e.g. list of N items) on a separate line | 15 | 4 | 2014 | Opción para anunciar entrada/salida de contenedores (lista de N elementos) en línea separada.
#7910 | No announcement of maxlength | 15 | 4 | 2018 | Anunciar el atributo maxlength de campos de entrada.
#18422 | Pull functionality of the "Enhanced Find Dialog - Modification" addon into NVDA core | 20 | 1 | 2025 | Integrar en el núcleo el complemento "Enhanced Find Dialog" (diálogo de búsqueda mejorado).
#4904 | Skipping empty lines in browse mode | 20 | 0 | 2015 | Saltar líneas vacías en modo exploración.
#15732 | Redisign the container navigation in browse mode to avoid loss of information for the user | 18 | 0 | 2023 | Rediseñar la navegación por contenedores para no perder información.
#11073 | Issue displaying text after links when the Screen Layout mode is turned off | 18 | 0 | 2020 | Mostrar correctamente el texto tras enlaces con el modo de disposición de pantalla desactivado.
#9273 | Option to disable the announcement "Copied to clipboard" | 18 | 0 | 2019 | Opción para desactivar el anuncio "copiado al portapapeles".
#8193 | Limit list item quick navigation to current list | 18 | 0 | 2018 | Limitar la navegación rápida por elementos de lista a la lista actual.
#7412 | Allow The User to Choose to See Images That Have No Alt Text In All Applications | 16 | 1 | 2017 | Permitir mostrar imágenes sin texto alternativo en todas las aplicaciones.
#10420 | Entering and exiting landmarks | 18 | 0 | 2019 | Anunciar la entrada y salida de landmarks.
#12009 | Modal dialogs/overlays not recognized as superceding page content | 16 | 1 | 2021 | Reconocer diálogos modales/superposiciones como sustitutos del contenido de la página (ADR requerido).
#8377 | Native date field control not understood (Web) | 18 | 0 | 2018 | Soportar el control nativo de fecha (input date).
#6499 | In Browse mode, an easier key should be bound to find, find next, and find previous. | 18 | 0 | 2016 | Tecla más sencilla para buscar / buscar siguiente / anterior en modo exploración.
#3566 | ABBR attribute on TH elements not supported | 17 | 0 | 2013 | Soportar el atributo abbr en celdas TH.
#18206 | Feature request: Make browse mode available everywhere | 15 | 1 | 2025 | Hacer el modo exploración disponible en cualquier lugar (cualquier ventana/control).
#14654 | Support of the q element in an HTML document | 3 | 6 | 2023 | Soportar el elemento <q> (citas en línea).
#16426 | Find dialog improvement: allow to search by regexp | 14 | 0 | 2024 | Diálogo Buscar: permitir expresiones regulares.
#904 | When performing a say all on webpages, the screen should scroll along with the speech | 13 | 0 | 2010 | Desplazar la pantalla al ritmo de la voz en say all (baja visión).
#3773 | Reading text selected by mouse cursor in browsers | 13 | 0 | 2014 | Leer el texto seleccionado con el ratón en navegadores.
#17216 | Report emphasis (`<em>`) and strong importance (`<strong>`) in browsers | 11 | 1 | 2024 | Anunciar énfasis (<em>) y fuerte importancia (<strong>).
#9122 | NVDA browse mode doesn't support aria-modal attribute | 10 | 1 | 2019 | Soportar aria-modal en modo exploración.
#13293 | Support quick nav for spelling errors in more situations | 7 | 2 | 2022 | Navegación rápida por errores ortográficos en más situaciones.
#8079 | Consider temporarily freezing dynamic pages with virtual buffers | 11 | 0 | 2018 | Congelar temporalmente páginas dinámicas en el búfer virtual.
#12078 | NVDA does not identify page title change in Single page Apps(SPA) | 11 | 0 | 2021 | Detectar el cambio de título de página en aplicaciones de una sola página (SPA).
#20877 | Add support for ARIA DPub roles | 10 | 0 | 2026 | Soporte de roles ARIA DPub (nuevo ADR en revisión, relacionado con #9168).
#7320 | Make use of the error quick navigation command in browse mode on the web | 10 | 0 | 2017 | Usar el comando de navegación rápida de errores en web.
#8874 | NVDA does not use the lang attribute when announcing the title attribute of an element | 2 | 4 | 2018 | Usar el atributo lang al anunciar el atributo title.
#49 | Announce shortcut keys after the content for some roles | 10 | 0 | 2010 | Anunciar las teclas de atajo después del contenido para algunos roles.
#16415 | Make the command nvda+k to report overwritten link text on first press | 10 | 0 | 2024 | NVDA+K: anunciar el texto sobreescrito del enlace con la primera pulsación.
#9527 | Quick navigation to font attributes | 9 | 0 | 2019 | Navegación rápida por atributos de fuente.
#1004 | A mode that allows the user to have the top row and/or left column of a table treated as headings | 9 | 0 | 2010 | Tratar la primera fila/columna de una tabla como encabezados (definido por el usuario).
#13940 | Navigate to aria-details target and return to initial location | 9 | 0 | 2022 | Navegar al destino de aria-details y volver al punto inicial.
#19217 | A feature to skip blank lines | 7 | 0 | 2025 | Función para saltar líneas en blanco.
#7744 | Feature: navigation between element atributes such as color, font, style and other document formatting atributes. | 7 | 0 | 2017 | Navegación por atributos de elemento (color, fuente, estilo).
#20729 | Announce AsyncContentLoaded UIA event (or equivalent) from Chromium to support Navigation API / SPAs | 7 | 0 | 2026 | Anunciar AsyncContentLoaded (UIA) de Chromium para la Navigation API / SPAs.
#19392 | Report blank lines between paragraphs when navigating line by line in browse mode | 4 | 1 | 2025 | Anunciar líneas en blanco entre párrafos al navegar por líneas.
#12656 | NVDA does not offer an expansion for abbr elements | 2 | 2 | 2021 | Ofrecer la expansión de los elementos <abbr>.
#11033 | Add support for ARIA role code | 4 | 1 | 2020 | Soporte del rol ARIA code.
#14311 | script to navigate between form invalid fields. | 6 | 0 | 2022 | Script para navegar entre campos de formulario inválidos.
#19941 | Ability to jump directly to the main content of a web document | 6 | 0 | 2026 | Saltar directamente al contenido principal de un documento web.
#19498 | Indicate when attempting to navigate past the top or bottom of a document | 6 | 0 | 2026 | Indicar cuando se intenta navegar más allá del inicio o final del documento.
#3554 | Enhancement: NVDA should read  the nearest heading for an item /element in browse mode | 6 | 0 | 2013 | Leer el encabezado más cercano a un elemento en modo exploración.
#16648 | Summary of the preceeding heading structure when navigating directly to a heading of a given level | 6 | 0 | 2024 | Resumen de la estructura de encabezados precedente al saltar a un encabezado.
#9823 | aria-setsize when set to -1 should suppress stating the total number of items.  | 6 | 0 | 2019 | aria-setsize=-1 debe suprimir el total de elementos.
#20805 | Browse Mode: Add forward/backward position stack | 5 | 0 | 2026 | Pila de posiciones atrás/adelante en modo exploración.
#16734 | Ability to manually check the current heading, region or frame in a structured document | 5 | 0 | 2024 | Consultar manualmente el encabezado, región o marco actual.
#13795 | Implementation of aria-details with multiple IDs? | 4 | 0 | 2022 | Implementar aria-details con varios IDs.
#7135 | NVDA does not announce title for modal dialog in web when pressed insert+T  | 4 | 0 | 2017 | Anunciar el título del diálogo modal web con NVDA+T.
#10783 | Recognise common URLs (when no exposed name or description provided) | 4 | 0 | 2020 | Reconocer URLs comunes cuando no hay nombre ni descripción.
#11939 | Can't navigate by spelling errors in multiline text boxes on Chrome | 3 | 0 | 2020 | Navegar por errores ortográficos en áreas de texto multilínea en Chrome.
#4087 | Option to only Announce Table Headers when Using Table Navigation Keys | 3 | 0 | 2014 | Opción para anunciar sólo encabezados de tabla con la navegación de tablas.
#19303 | Option to toggle reporting of landmark types | 3 | 0 | 2025 | Opción para alternar el anuncio de tipos de landmark.
#3877 | Feature to move the caret in browse mode while maintaining the selection | 3 | 0 | 2014 | Mover el caret en modo exploración manteniendo la selección.
#9272 | Provide (audio/braille) indication of activity while loading web page | 3 | 0 | 2019 | Indicación (audio/braille) de actividad mientras carga una página.
#14411 | Consider respecting custom PosInSet and SetSize values on lists | 3 | 0 | 2022 | Respetar valores personalizados de aria-posinset/aria-setsize en listas.
#14332 | aria-rowcount and aria-colcount not being announced for element with role="grid" | 3 | 0 | 2022 | Anunciar aria-rowcount y aria-colcount en role=grid.
#10755 | suggestion option to report only the number of photos / graphics on a web page when the figures are close to each other | 3 | 0 | 2020 | Opción para anunciar sólo el número de imágenes de una página.
#18151 | Turn off reading of alt text descriptions on web pages | 3 | 0 | 2025 | Opción para desactivar la lectura de textos alternativos.
#18311 | Report aria shortcut key at the end | 3 | 0 | 2025 | Anunciar el atajo ARIA (aria-keyshortcuts) al final.
#18488 | Add direct shortcut keys for specific element types (e.g. headings, links) in the Elements List | 2 | 0 | 2025 | Atajos directos por tipo de elemento en la Lista de elementos.
#17045 | Treat the `<pre>` element as a container element | 2 | 0 | 2024 | Tratar <pre> como elemento contenedor.
#16678 | Min and max value not read out for <meter> element | 2 | 0 | 2024 | Leer valores mínimo y máximo del elemento <meter>.
#19074 | Let NVDA announce document formats when selecting text on the web | 1 | 0 | 2025 | Anunciar formatos del documento al seleccionar texto en la web.
#19490 | NVDA only reads the first idref in aria-errormessage | 1 | 0 | 2026 | Leer todos los idrefs de aria-errormessage, no sólo el primero.
#17449 | Make Repetitive Elements Clear in Element List | 1 | 0 | 2024 | Hacer claros los elementos repetidos en la Lista de elementos.
#14710 | Incremental find | 0 | 0 | 2023 | Búsqueda incremental.
#14028 | Support page movement in browse mode | 0 | 0 | 2022 | Movimiento por páginas en modo exploración.
#18225 | NVDA ignores TH's aria-label and aria-labelledby | 0 | 0 | 2025 | Respetar aria-label y aria-labelledby en TH.
#18436 | Request for gesture for "Same page link" | 0 | 0 | 2025 | Gesto de navegación rápida para "enlace a la misma página".

## Aplicaciones Office (Word, Excel, PowerPoint, Outlook, LibreOffice, Google Docs) (87)

#8674 | Add RGB values for colors to formatting reporting | 30 | 0 | 2018 | Añadir valores RGB de colores al informe de formato.
#7538 | Individual keys to find comments and changes | 22 | 0 | 2017 | Teclas individuales para buscar comentarios y cambios (revisiones).
#11161 | Mail clients: report only the content of message body when opening an email with enter or with the mouse | 20 | 0 | 2020 | Clientes de correo: leer sólo el cuerpo del mensaje al abrirlo.
#5909 | Keyboard shortcut to report text of footnotes in ms Word documents | 17 | 0 | 2016 | Atajo para leer el texto de notas al pie en Word.
#8148 | Browse Mode in LibreOffice Writer | 16 | 0 | 2018 | Modo exploración en LibreOffice Writer.
#11232 | Hotkey to navigate to a spesified cell in a table | 15 | 0 | 2020 | Atajo para saltar a una celda específica de una tabla.
#4251 | Gesture for announcing MS Word current line and cahracter positions | 13 | 0 | 2014 | Gesto para anunciar línea y posición de carácter actual en Word.
#4629 | Reading Column & Row Titles before the content | 12 | 0 | 2014 | Leer títulos de fila y columna antes del contenido de la celda.
#18756 | Feature request: reporting underline color | 12 | 0 | 2025 | Anunciar el color del subrayado.
#4336 | Improvement for reading comments in MS Word | 11 | 0 | 2014 | Mejorar la lectura de comentarios en Word.
#651 | make Extensions Manager in OpenOffice accessible | 11 | 0 | 2010 | LibreOffice/OpenOffice: gestor de extensiones accesible.
#4634 | outlook2010: Include checkbox in list item | 10 | 0 | 2014 | Outlook: incluir el estado de la casilla en el elemento de lista.
#5558 | Excel: Formulas and comments not shown in Elements list dialog | 9 | 0 | 2015 | Excel: mostrar fórmulas y comentarios en la lista de elementos.
#7877 | PowerPoint: Support for announcing animated textual content after they appear | 9 | 0 | 2017 | PowerPoint: anunciar texto animado cuando aparece.
#4987 | Indentation level not reported in Microsoft powerPoint 2013 | 6 | 1 | 2015 | PowerPoint: anunciar nivel de sangría.
#4021 | Powerpoint doesn't report alignment and other formatting info | 8 | 0 | 2014 | PowerPoint: anunciar alineación y otro formato.
#4906 | MSWord:  no information about the inserted merged fields is given and the fields are read just like plain text. | 8 | 0 | 2015 | Word: informar sobre campos combinados insertados.
#4133 | Commands to Navigate trhough tables Should Work in OpenOffice and LibreOffice. | 8 | 0 | 2014 | LibreOffice: comandos de navegación por tablas.
#6915 | LibreOffice Writer: provide speech and braille feedback for common shortcut keys | 8 | 0 | 2017 | LibreOffice Writer: feedback para atajos comunes.
#7700 | LibreOffice Writer: Comments not indicated or reported in Writer | 8 | 0 | 2017 | LibreOffice Writer: indicar y leer comentarios.
#901 | [Excel] read entire row/column | 7 | 0 | 2010 | Excel: leer fila o columna completa.
#3462 | Hotkey for reporting useful table cell info like coordinates | 7 | 0 | 2013 | Atajo para información útil de la celda (coordenadas, etc.).
#7899 | SUPPORT FOR FORMULA IN MICROSOFT EXCEL | 7 | 0 | 2018 | Soporte de fórmulas en Excel.
#3501 | PowerPoint 2010: level of bulleted list item isn't announced | 7 | 0 | 2013 | PowerPoint: anunciar nivel de viñeta.
#13419 | Report "Small caps" and "All caps" formatting in Word | 7 | 0 | 2022 | Word: anunciar formato versalitas y todo mayúsculas (PR #20922 en curso).
#2010 | added support to detect border in word | 7 | 0 | 2011 | Word: detectar bordes.
#4717 | Ms Word: Less verbosity when reading editor revisions by character or word | 6 | 0 | 2014 | Word: menos verbosidad al leer revisiones por carácter o palabra.
#9145 | Add a way to move to the next not empty cell in Excel | 6 | 0 | 2019 | Excel: ir a la siguiente celda no vacía.
#10949 | Report when a slide is hidden in PowerPoint | 6 | 0 | 2020 | PowerPoint: anunciar diapositiva oculta.
#4912 | Providing way to read the message headers in a received message from anywhere in a message will be helpful to those who work with emails extensively. | 6 | 0 | 2015 | Leer las cabeceras del mensaje recibido desde cualquier lugar.
#4274 | support for reading slides with open office 4.1 | 6 | 0 | 2014 | LibreOffice/OpenOffice: leer diapositivas de Impress.
#16997 | Excel: Report hidden cells | 5 | 0 | 2024 | Excel: anunciar celdas ocultas.
#6480 | Excel: announce "wrapped" where text is wrapped in a cell (just as overflowing or cropped is announced) | 5 | 0 | 2016 | Excel: anunciar "ajustado" cuando el texto de la celda se ajusta.
#6428 | new feature request- provide information in print preview in MS Excel | 5 | 0 | 2016 | Excel: información en vista previa de impresión.
#7858 | Allow chart navigation in excel, word and power point by signal tones like the tones for reporting progress bars | 3 | 1 | 2017 | Navegar gráficos (Excel/Word/PowerPoint) con tonos de audio.
#8049 | Report "has notes" on slides when navigating with up and down arrow in MS PowerPoint | 5 | 0 | 2018 | PowerPoint: anunciar "tiene notas" al navegar diapositivas.
#8025 | Add support for screen layout in MS Power point | 5 | 0 | 2018 | PowerPoint: soporte del modo de disposición de pantalla.
#6944 | Enhanced support for form controls in MS Word | 5 | 0 | 2017 | Word: mejor soporte de controles de formulario.
#4186 | MS Word feature request to reach out to objects on a document. | 5 | 0 | 2014 | Word: llegar a objetos del documento.
#7067 | Enhancement: In MS Office, always announce ribbon section when using control+arrows | 5 | 0 | 2017 | Office: anunciar la sección de la cinta con Ctrl+flechas.
#5453 | Giving OpenOffice and LibreOffice same features as those added to MSOffice | 5 | 0 | 2015 | LibreOffice: mismas funciones que las añadidas a MS Office.
#19626 | Table navigation commands reporting the whole row or column while navigating in table | 4 | 0 | 2026 | Comandos de tabla que lean la fila o columna completa mientras se navega.
#8875 | Feature request: Always announce negative numbers in Excel | 4 | 0 | 2018 | Excel: anunciar siempre números negativos.
#7108 | NVDA does not report when control+a selects all cells in a worksheet | 4 | 0 | 2017 | Excel: anunciar cuando Ctrl+A selecciona todas las celdas.
#9740 | Add ability to navigate to objects in Word with "o" in Browse mode | 2 | 1 | 2019 | Word: navegar a objetos con "o" en modo exploración.
#20057 | Request for improvements in browse mode while working in Microsoft Word | 4 | 0 | 2026 | Mejoras del modo exploración en Word.
#15279 | Use NVDA+k to Report link destination in Excel | 4 | 0 | 2023 | Excel: NVDA+K para anunciar el destino del enlace.
#19509 | Play auto-suggestion sound in Outlook composition fields (To/CC/BCC) | 4 | 0 | 2026 | Outlook: sonido de autosugerencia en campos Para/CC/CCO.
#5687 | Report status bar should report state of toggles | 4 | 0 | 2016 | Barra de estado: anunciar el estado de los conmutadores.
#6643 | Allow moving to form fields in MS word. | 3 | 0 | 2016 | Word: moverse a campos de formulario.
#17570 | Cross references In MS Word only reported as links | 3 | 0 | 2024 | Word: referencias cruzadas anunciadas como tales, no sólo como enlaces.
#8029 | Outlook 2016 calendar: Use MSAA to announce timeslot and appointment information | 3 | 0 | 2018 | Outlook: calendario vía MSAA (franjas y citas).
#19155 | LibreOffice Writer.  When spell check is opened or moves to a new word, it gives a very verbose description of what spell check is | 3 | 0 | 2025 | LibreOffice Writer: corrector ortográfico menos verboso.
#20383 | Improve reporting whole column or row selected in Excel | 0 | 1 | 2026 | Excel: mejorar el anuncio de fila/columna entera seleccionada.
#7044 | Feature suggestion: Read current cell when F4 is pressed in Excel | 2 | 0 | 2017 | Excel: leer la celda actual al pulsar F4.
#6702 | reading charts and graphs in google sheets and libreoffice calc | 2 | 0 | 2017 | Leer gráficos en Google Sheets y LibreOffice Calc.
#11300 | Report sections in PowerPoint (Office 365, and I think from 2016 onwards) | 2 | 0 | 2020 | PowerPoint: anunciar secciones.
#5362 | Microsoft Office Powerpoint: provide speech and Braille feedback for common actions (like Microsoft Office Word) | 2 | 0 | 2015 | PowerPoint: retroalimentación de voz y braille para acciones comunes.
#8565 | Add support for forms in MS Word | 2 | 0 | 2018 | Word: soporte de formularios.
#8564 | Microsoft Word: announce diagram type for diagrams instead of "embeded object" | 2 | 0 | 2018 | Word: anunciar tipo de diagrama en vez de "objeto incrustado".
#6815 | Word: Announce list item level? | 2 | 0 | 2017 | Word: anunciar nivel de elemento de lista.
#19883 | Feature for selecting a sentence in Microsoft word | 2 | 0 | 2026 | Word: seleccionar una frase.
#11018 | Outlook: Announce Selection State of Categories when Focused | 2 | 0 | 2020 | Outlook: anunciar el estado de selección de categorías.
#11038 | all Hotkeys should speak in Microsoft-Word | 2 | 0 | 2020 | Word: que todas las teclas rápidas hablen su efecto.
#12080 | Incorporate support for Elements List in Google Docs | 2 | 0 | 2021 | Google Docs: soporte de la Lista de elementos.
#12725 | Please have NVDA read column headers first in Microsoft excel | 1 | 0 | 2021 | Excel: leer primero los encabezados de columna.
#8739 | Feature idea: Option to automatically read footnotes and comments during navigation or say all. | 1 | 0 | 2018 | Opción para leer automáticamente notas al pie y comentarios durante la navegación o say all.
#8923 | Excel: Report Frozen column/row | 1 | 0 | 2018 | Excel: anunciar filas/columnas inmovilizadas.
#8963 | Report name for named cells in Excel | 1 | 0 | 2018 | Excel: anunciar el nombre de celdas con nombre.
#18590 | Add on demand reporting of tables in Excel | 1 | 0 | 2025 | Excel: anuncio bajo demanda de tablas.
#8270 | Excel: Enhance the elements list to allow performing additional operations on sheets | 1 | 0 | 2018 | Excel: lista de elementos con operaciones adicionales sobre hojas.
#9146 | Add a way to list all text fields in the Excel elements list. | 1 | 0 | 2019 | Excel: listar todos los campos de texto en la lista de elementos.
#6715 | Announce edit state in Excel when F2 is pressed | 1 | 0 | 2017 | Excel: anunciar el estado de edición al pulsar F2.
#12719 | NVDA not reading PowerPoint Outline view (just reads linefeed) | 1 | 0 | 2021 | PowerPoint: leer la vista Esquema.
#7752 | Add support for all browse mode navigation keys in MS Office products and improve navigation by Tab in forms | 1 | 0 | 2017 | Todas las teclas de navegación del modo exploración en Office.
#6142 | Setting up smart art in Word | 1 | 0 | 2016 | Word: SmartArt accesible.
#6622 | MS Office: provide speech and braille feedback for numpad Insert, Extended Insert | 1 | 0 | 2016 | Office: feedback de voz y braille para Insert / Insert extendido.
#19169 | Report status of "Automatic spell checking" in LibreOffice writer when toggled | 1 | 0 | 2025 | LibreOffice Writer: anunciar el estado del corrector automático al alternarlo.
#8024 | in Power Point, Add feature to NVDA to report the position of elements in centimeters rather than points. | 0 | 0 | 2018 | PowerPoint: posición de elementos en centímetros.
#13865 | Add support for reporting border style formatting in MS Word tables | 0 | 0 | 2022 | Word: anunciar estilo de bordes en tablas.
#14277 | Report presence of list and number of items in Word as happens on the web | 0 | 0 | 2022 | Word: anunciar presencia de lista y número de elementos como en la web.
#12748 | Report when selection crosses a table boundary in Word | 0 | 0 | 2021 | Word: anunciar cuando la selección cruza un límite de tabla.
#16184 | Add reading long description back to NVDA+d in Word | 0 | 0 | 2024 | Word: volver a leer la descripción larga con NVDA+D.
#20916 | Separate background pattern announcements from color announcements | 0 | 0 | 2026 | Separar el anuncio del patrón de fondo del color.
#20931 | Improve the presentation of Word comments and replies in the browsable message | 0 | 0 | 2026 | Word: mejorar la presentación de comentarios y respuestas en el mensaje navegable.
#19955 | Request for a keyboard shortcut to jump between native speech and math cat speech in Microsoft word | 0 | 0 | 2026 | Word: atajo para alternar entre voz matemática nativa y MathCAT.
#10757 | Support reading comments in word online | 0 | 0 | 2020 | Word Online: leer comentarios.

## Otras aplicaciones / Windows (29)

#6309 | Give NVDA the ability to detect time until full charge. | 14 | 0 | 2016 | Batería: anunciar el tiempo hasta carga completa.
#11124 | Word navigation hotkeys provide no spoken feedback in terminals | 12 | 0 | 2020 | Terminales: feedback hablado de las teclas de navegación por palabra.
#4651 | provide speech and Braille feedback for common actions in VLC Media Player | 10 | 0 | 2014 | VLC: retroalimentación de voz y braille para acciones comunes.
#640 | Different message buffers for each window in Miranda chat client | 9 | 0 | 2010 | Miranda: búferes de mensajes distintos por ventana.
#6835 | TerminalModules | 9 | 0 | 2017 | "TerminalModules": módulos por programa dentro de terminales (vim, etc.).
#7227 | Enhancement: sound or ui.message is needed while printscreen key is pressed | 8 | 0 | 2017 | Sonido o mensaje al pulsar la tecla Imprimir Pantalla.
#6095 | Command prompt tab completion | 7 | 0 | 2016 | Símbolo del sistema: anunciar autocompletado con Tab.
#14643 | bring to nvda new features for use in whatsapp | 6 | 0 | 2023 | WhatsApp: nuevas funciones de accesibilidad.
#8850 | add browse mode support OneNote store APP | 6 | 0 | 2018 | OneNote (Store): soporte de modo exploración.
#19181 | NVDA announces the Desktop window as program manager and fails to announce desktop names | 6 | 0 | 2025 | Escritorio: anunciar nombres de escritorios virtuales en vez de "Program Manager".
#20092 | [Feature from Add-on] Integrate the "Charging Notifier" add-on functionality into NVDA | 4 | 1 | 2026 | Integrar la funcionalidad del complemento "Charging Notifier".
#19542 | Announce Precision Touchpad status changes | 6 | 0 | 2026 | Anunciar cambios de estado del touchpad de precisión.
#11411 | Requesting accessibility enhancement app module for Unigram | 5 | 0 | 2020 | AppModule para Unigram (Telegram).
#10861 | Implement selectionContainer design pattern for lists and tree views | 5 | 0 | 2020 | VS Code: patrón selectionContainer para listas y árboles.
#11509 | Opening Windows 10 Action Center should focus and speak first actionable item | 5 | 0 | 2020 | Centro de actividades: enfocar y leer el primer elemento accionable.
#18411 | Reporting progress of file copy (progress bar / details) in Windows 10 / 11 | 5 | 0 | 2025 | Anunciar el progreso de copias de archivos en Windows 10/11.
#7871 | Automatic subtitle reading in Subtitle Editor | 4 | 0 | 2017 | Subtitle Editor: lectura automática de subtítulos.
#17842 | No feedback when moving Window (alt+space, m, then arrows) | 4 | 0 | 2025 | Feedback al mover ventanas (Alt+Espacio, M, flechas).
#9959 | Support Kaomoji and symbols in Windows 10 / 11 Emoji panel | 4 | 0 | 2019 | Panel de emojis: soportar kaomoji y símbolos.
#11385 | Ability to turn off Zoom alerts | 4 | 0 | 2020 | Poder desactivar alertas de Zoom.
#20222 | NVDA should speak current calculation mode in windows calculator | 3 | 0 | 2026 | Calculadora de Windows: anunciar el modo de cálculo actual.
#16911 | Support NVDA table navigation in Microsoft Loop tables | 3 | 0 | 2024 | Microsoft Loop: navegación por tablas.
#12580 | improve the readability of the AnyDesk application  | 2 | 0 | 2021 | AnyDesk: mejorar legibilidad.
#8248 | improvements in cisco jabber | 2 | 0 | 2018 | Cisco Jabber: mejoras.
#17861 | Duxbury: better user experience | 2 | 0 | 2025 | Duxbury: mejor experiencia de usuario.
#6660 | Visual Studio: Announce new current line when line is removed with control+l | 2 | 0 | 2016 | Visual Studio: anunciar la nueva línea actual tras Ctrl+L.
#6771 | NVDA Should Read Extra Clocks On System Tray | 2 | 0 | 2017 | Leer relojes adicionales de la bandeja del sistema.
#19731 | No feedback when resizing windows via System Menu (Alt+Space > Size) | 1 | 0 | 2026 | Feedback al redimensionar ventanas desde el menú de sistema.
#17689 | Treat all-space "blank" lines in console applications as blank | 0 | 0 | 2025 | Consola: tratar líneas sólo con espacios como en blanco.

## Braille (53)

#16566 | Nvda no longer supports newer BRLTTY versions | 22 | 0 | 2024 | Soportar versiones nuevas de BRLTTY (p2).
#11298 | Use liblouis metadata for braille table descriptions | 18 | 1 | 2020 | Usar metadatos de Liblouis para las descripciones de tablas braille.
#4105 | Introduce role-based braille mapper | 19 | 0 | 2014 | Mapeador braille basado en roles (personalizar abreviaturas de roles).
#4775 | Support for HandyTech Active Tactile Control | 18 | 0 | 2015 | Soporte para HandyTech Active Tactile Control (ATC).
#2736 | support for Japanese braille | 16 | 0 | 2012 | Soporte de braille japonés.
#1953 | Indicate if focused item is selected using dots 7 and 8 | 16 | 0 | 2011 | Indicar con puntos 7 y 8 si el elemento enfocado está seleccionado.
#7887 | Add the possibility to turn off displaying element status and type on braille displays | 12 | 0 | 2018 | Poder desactivar la presentación de tipo y estado del elemento en braille.
#18064 | Extending Braille context output by table/grid headers in browse and focus mode | 12 | 0 | 2025 | Contexto braille con encabezados de tabla/grid en modos exploración y foco.
#4097 | Make braille_previousLine and braille_nextLine functional outside of text content | 11 | 0 | 2014 | Hacer funcionar línea anterior/siguiente braille fuera de contenido de texto.
#11497 | Native support for Braille Me display | 11 | 0 | 2020 | Soporte nativo de la pantalla Braille Me.
#11829 | support for aria-braille* properties | 9 | 1 | 2020 | Soportar propiedades aria-braillelabel / aria-brailleroledescription.
#8843 | Detect disconnected braille devices and close them immediately | 10 | 0 | 2018 | Detectar pantallas braille desconectadas y cerrarlas inmediatamente.
#13312 | add ASCII Liblouis Braille table | 10 | 0 | 2022 | Añadir tabla braille ASCII de Liblouis.
#6587 | Improve braille support in spreadsheets and tables | 9 | 0 | 2016 | Mejorar el braille en hojas de cálculo y tablas.
#6785 | Show extra editing information from Word in braille | 9 | 0 | 2017 | Mostrar información extra de edición de Word en braille.
#4195 | Announcement of row/column headers to braille display | 8 | 0 | 2014 | Mostrar encabezados de fila/columna en braille.
#9098 | Implement BRLTTY and braille displays which connect via BRLTTY into automatic braille display detection | 8 | 0 | 2018 | Integrar BRLTTY y sus pantallas en la detección automática.
#20726 | Add optional spacing between Chinese text, Latin letters, and numbers in Chinese braille output | 8 | 0 | 2026 | Espaciado opcional entre texto chino, letras latinas y números en braille chino.
#7335 | Allow different object names for speech and braille | 7 | 0 | 2017 | Nombres de objeto distintos para voz y braille.
#11396 | Add the ability to automatically pan Braille displays | 7 | 0 | 2020 | Paneo automático de la línea braille (parcialmente cubierto por autoscroll en 2026.2).
#4601 | Braille dictionary support | 7 | 0 | 2014 | Soporte de diccionarios braille.
#5944 | A request: browse mode with screen layout mode and braille. | 7 | 0 | 2016 | Modo exploración con disposición de pantalla y braille.
#14785 | Add ability to specify which document formatting properties are reported in Braille | 6 | 0 | 2023 | Especificar qué propiedades de formato se muestran en braille.
#4911 | reporting allignment and indentation on a braille display | 6 | 0 | 2015 | Mostrar alineación y sangría en la línea braille.
#6483 | Enable more braille keys via BRLTTY | 6 | 0 | 2016 | Habilitar más teclas braille vía BRLTTY.
#9615 | allow setting dot firmness for the esys 16, 24, 40, 80 displays from the settings dialogq | 6 | 0 | 2019 | Ajustar la firmeza de puntos de las pantallas Esys desde los ajustes.
#15697 | Advancing braille should dismiss alerts | 2 | 2 | 2023 | Avanzar la línea braille debe descartar las alertas.
#2757 | enhance braille scroll in multiline controls | 5 | 0 | 2012 | Mejor desplazamiento braille en controles multilínea.
#8582 | Browse mode: Cell coordinates aren't shown in braille when "Tables" is disabled | 4 | 0 | 2018 | Mostrar coordenadas de celda en braille aunque "Tablas" esté desactivado.
#10674 | one handed mode on braille display  | 4 | 0 | 2020 | Modo a una mano en la línea braille.
#17891 | key repeat for braille gestures | 4 | 0 | 2025 | Repetición de tecla para gestos braille.
#17601 | Add exceptions for Braille unicode normalization | 4 | 0 | 2025 | Excepciones para la normalización Unicode en braille.
#8517 | Add the ability to set up half seconds timeout steps for braille messages | 4 | 0 | 2018 | Timeouts de mensajes braille en pasos de medio segundo.
#18984 | Language switching for braille output | 2 | 0 | 2025 | Cambio de idioma (tabla) para la salida braille.
#14242 | Add Bluetooth COM Port supports for Seika v3/v5/v80 Braille display | 2 | 0 | 2022 | Soporte de puertos COM Bluetooth para Seika v3/v5/v80.
#14146 | Show formatting on Braille viewer raw text line | 2 | 0 | 2022 | Mostrar formato en la línea de texto crudo del visor braille.
#6966 | Add an "expand to computer braille at the cursor, only in edit fields" option | 1 | 0 | 2017 | Expandir a braille computerizado bajo el cursor sólo en campos de edición.
#6955 | We need a delete last word command for braille input! | 1 | 0 | 2017 | Comando para borrar la última palabra en entrada braille.
#13917 | Add Braille device button emulation to Braille viewer | 1 | 0 | 2022 | Emulación de botones de dispositivo braille en el visor braille.
#15976 | Adding Liblouis Braille tables including Māori | 1 | 0 | 2023 | Añadir tablas Liblouis incluyendo maorí.
#16759 | Separate object information reporting into speech and braille | 0 | 0 | 2024 | Separar el reporte de información de objetos entre voz y braille.
#16758 | Separate table information reporting into speech and braille | 0 | 0 | 2024 | Separar el reporte de información de tablas entre voz y braille.
#16757 | Separate document information reporting into speech and braille | 0 | 0 | 2024 | Separar el reporte de información de documento entre voz y braille.
#16756 | Separate element type reporting into speech and braille | 0 | 0 | 2024 | Separar el reporte del tipo de elemento entre voz y braille.
#19479 | Add an ability to switch between chosen input and output braille tables | 0 | 0 | 2026 | Alternar entre tablas braille de entrada/salida elegidas.
#12237 | Support for the Orbit 40 | 0 | 0 | 2021 | Soporte de Orbit Reader 40.
#20023 | Braille display sleep mode | 0 | 0 | 2026 | Modo reposo de pantalla braille (ADR en revisión).
#20274 | Say All Braille and Speech Synchronization | 0 | 0 | 2026 | Sincronización de voz y braille durante say all (ADR requerido).
#18294 | Improve the braille viewer to support multiline displays | 0 | 0 | 2025 | Visor braille con soporte de pantallas multilínea.
#13237 | Multicellulaire braille cursor for multicellulaire characters | 0 | 0 | 2022 | Cursor braille multicelda para caracteres multicelda.
#19843 | Proposed NVDA Core APIs: Braille Mirror and Direct Braille | 0 | 0 | 2026 | APIs núcleo propuestas: Braille Mirror y Direct Braille.
#20736 | ADR: Generate the braille table registry from liblouis metadata | 0 | 0 | 2026 | ADR: generar el registro de tablas braille desde metadatos de liblouis.
#16801 | Supporting aria-braille-input to allow web authors to accept Unicode braille input | 0 | 0 | 2024 | Soportar aria-braille-input para entrada braille Unicode en la web.

## Audio / sonidos (17)

#3049 | forcing unmute and volume of sound card | 54 | 0 | 2013 | Forzar desmutear y fijar volumen de la tarjeta de sonido.
#7769 | Voice Synthesizer crackling when CPU load high, any way to improve this? | 28 | 0 | 2017 | Evitar crujidos del sintetizador con carga alta de CPU.
#6427 | Volume and mute enhancements | 23 | 0 | 2016 | Mejoras de volumen y silencio.
#2559 | Option to play audio coordinate when using object navigation | 20 | 0 | 2012 | Coordenadas de audio al navegar objetos.
#18435 | Add white noise parameter to audio settings to keep audio alive | 17 | 0 | 2025 | Parámetro de "ruido blanco" para mantener viva la salida de audio (evitar cortes iniciales).
#10116 | A selection of tones for NVDA. | 14 | 0 | 2019 | Selección de tonos/sonidos para NVDA.
#16052 | Feature request: add command to adjust volume of all applications except for NVDA | 12 | 0 | 2024 | Comando para ajustar el volumen de todas las aplicaciones salvo NVDA.
#9308 | Change the default beepSpeechModePitch value to 880 Hz (note A5) | 12 | 0 | 2019 | Cambiar el tono por defecto del modo pitidos a 880 Hz.
#13818 | Select audio output channels | 11 | 0 | 2022 | Seleccionar canales de salida de audio.
#18836 | retain synthasiser settings when changing audio device output | 10 | 0 | 2025 | Conservar ajustes del sintetizador al cambiar el dispositivo de salida.
#6683 | Play a different sound when switching to browse mode if single letter nav is off | 8 | 0 | 2016 | Sonido distinto al pasar a modo exploración con navegación de una letra desactivada.
#11294 | Add option to play audio files instead of word expressions | 6 | 0 | 2020 | Reproducir archivos de audio en lugar de expresiones habladas.
#16695 | Add themes interface for sounds | 5 | 0 | 2024 | Interfaz de temas de sonidos.
#4285 | audio indication for start or end of document | 5 | 0 | 2014 | Indicación sonora de inicio o fin de documento.
#10886 | Allow Beep Speech Mode Pitch To Be Configured More Intuatively | 3 | 0 | 2020 | Configurar el tono del modo pitidos de forma más intuitiva.
#5752 | Do not duck audio for sndvol.exe | 1 | 0 | 2016 | No atenuar el audio para sndvol.exe.
#18190 | Add ability to change the amount of audio ducking | 0 | 0 | 2025 | Ajustar la cantidad de atenuación (ducking).

## OCR / visión / IA / lupa (magnifier) / resaltado / cortina (33)

#10692 | Report status of screen curtain at startup when "Play a sound when toggling screen curtain" is disabled. | 24 | 0 | 2020 | Anunciar el estado de la cortina al inicio si el sonido está desactivado.
#16281 | OFFER: SMART IMAGE RECOGNITION | 16 | 0 | 2024 | Reconocimiento inteligente de imágenes (oferta de integración).
#18662 | Integrate the Windows Machine Learning framework to run ONNX models. | 16 | 0 | 2025 | Integrar Windows Machine Learning para ejecutar modelos ONNX.
#11405 | Add gesture (keystroke) to toggle Visual Highlight, Enable Highlighting (formerly focus highlight) | 11 | 2 | 2020 | Gesto para alternar el resaltado visual.
#10656 | Recommendation for OCR feature | 8 | 2 | 2019 | Recomendaciones para la función OCR.
#19317 | Remove Screen curtain temporary mode | 12 | 0 | 2025 | Eliminar el modo temporal de la cortina de pantalla.
#19495 | Add mouse input support to keyboard gestures | 11 | 0 | 2026 | Lupa: soporte de entrada de ratón en los gestos de teclado.
#20418 | Magnifier - A toggle setting to enable or disable color filtering | 9 | 0 | 2026 | Lupa: conmutador para activar/desactivar filtros de color.
#7380 | Recognition of texts in whole documents. | 7 | 0 | 2017 | Reconocimiento de texto de documentos completos.
#19492 | Add the ability to adjust the zoom increment/decrement value | 7 | 0 | 2026 | Lupa: ajustar el incremento/decremento de zoom.
#19338 | Add the ability to translate AI image descriptions | 6 | 0 | 2025 | Traducir las descripciones de imagen generadas por IA.
#19053 | Include confidence level in image descriptions | 6 | 0 | 2025 | Incluir el nivel de confianza en las descripciones de imagen.
#10576 | warn the user when attempting to screenshot blackness | 6 | 0 | 2019 | Avisar al intentar capturar pantalla con la cortina activada (captura negra).
#20360 | Magnifier: treat focus and caret separately | 0 | 3 | 2026 | Lupa: tratar foco y caret por separado.
#20182 | Create a pre-set list of preferred zoom levels | 6 | 0 | 2026 | Lupa: lista predefinida de niveles de zoom preferidos.
#17577 | Highlighter: customize the highlighter style | 5 | 0 | 2025 | Resaltador: personalizar el estilo.
#17558 | automatic ocr on elements without description. | 2 | 1 | 2024 | OCR automático en elementos sin descripción.
#20685 | Magnifier: Don't move view when scrolling with mouse wheel | 4 | 0 | 2026 | Lupa: no mover la vista al desplazar con la rueda del ratón.
#20060 | NVDA Magnifier - Moving the view should be smoother | 4 | 0 | 2026 | Lupa: movimiento de la vista más suave.
#20780 | ADR: Provide alternative OCR engines through an isolated add-on provider architecture | 1 | 1 | 2026 | ADR: motores OCR alternativos mediante arquitectura de proveedores en complementos.
#9035 | Add an ability to assign custom highlight without writing an appmodule. | 3 | 0 | 2018 | Asignar resaltado personalizado sin escribir un appModule.
#14200 | Add ability to highlight spoken text | 3 | 0 | 2022 | Resaltar el texto hablado.
#19244 | OCR: Supports high-accuracy recognition results. | 2 | 0 | 2025 | OCR: resultados de reconocimiento de alta precisión.
#19337 | Add the ability to manage AI image description models | 2 | 0 | 2025 | Gestionar los modelos de IA de descripción de imágenes.
#19081 | Add ability to read image descriptions in browse mode | 2 | 0 | 2025 | Leer descripciones de imagen en modo exploración.
#17576 | Highlighter: Supports highlighting mouse objects | 2 | 0 | 2025 | Resaltador: resaltar los objetos bajo el ratón.
#20774 | Magnifier supports smooth edges of images and text | 2 | 0 | 2026 | Lupa: suavizado de bordes de imágenes y texto.
#13900 | show image/background while screen curtain is enabled | 1 | 0 | 2022 | Mostrar imagen/fondo con la cortina de pantalla activada.
#19709 | Magnifier - Possibility to define the color of the borders when True Center feature is used | 1 | 0 | 2026 | Lupa: definir el color de los bordes en el modo True Center.
#7415 | Support find commands in content recognition results | 0 | 0 | 2017 | Soportar comandos de búsqueda en resultados de reconocimiento de contenido.
#18661 | contentRecog: Use the mouse to select the recognition area and perform recognition & OCR | 0 | 0 | 2025 | Reconocimiento: seleccionar el área con el ratón y hacer OCR.
#17375 | Video description | 0 | 0 | 2024 | Audiodescripción de vídeo.
#20112 | Magnifier: Directly discard coordinates outside the visible screen. | 0 | 0 | 2026 | Lupa: descartar coordenadas fuera de la pantalla visible.

## Configuración / perfiles / interfaz / instalación / actualizaciones (57)

#3721 | Sleep mode part of profile configuration request | 58 | 0 | 2013 | Modo dormir como parte de la configuración de un perfil.
#14593 | configuration profiles: add an option for any created profile to disable and enable specificly only that profile, raather than checking or unchecking the box to disable or enable all of the profiles together | 25 | 0 | 2023 | Perfiles: activar/desactivar individualmente cada perfil.
#2257 | Less intrusive automatic update notifications | 20 | 0 | 2012 | Notificaciones de actualización automática menos intrusivas.
#258 | Text from NVDA native dialogs should be placed in separate read-only fields for improved keyboard access | 19 | 0 | 2010 | Texto de diálogos nativos de NVDA en campos de solo lectura navegables.
#15894 | Improve control validation in the settings dialog | 18 | 0 | 2023 | Mejor validación de controles en el diálogo de ajustes.
#16341 | Portable creation from installer should offer option to copy current config | 18 | 0 | 2024 | Crear copia portable desde el instalador copiando la configuración actual.
#4892 | Settings should be removed from configuration profiles when equal to normal configuration | 17 | 0 | 2015 | Eliminar de los perfiles los ajustes iguales a la configuración normal.
#4253 | Allow cloning of profiles | 17 | 0 | 2014 | Clonar perfiles de configuración.
#3584 | Added NVDA Shortcuts Information to NVDA Menu | 15 | 0 | 2013 | Mostrar atajos de NVDA en el menú NVDA.
#17366 | allow the user to say a custom message when a profile is started | 12 | 0 | 2024 | Decir un mensaje personalizado al activar un perfil.
#16683 | Support Windows 10/11 Dark Mode | 8 | 2 | 2024 | Soporte de modo oscuro de Windows 10/11 en la interfaz (p2).
#13568 | More config dialogs in NVDA settings should have descriptive text | 11 | 0 | 2022 | Más texto descriptivo en los diálogos de ajustes.
#9284 | Tools for system administrators and corporate environments | 11 | 0 | 2019 | Herramientas para administradores de sistemas y entornos corporativos.
#3596 | multilinguality of installer | 11 | 0 | 2013 | Instalador multilingüe.
#8487 | Add more options for managing individual settings | 10 | 0 | 2018 | Más opciones de gestión de ajustes individuales (perfil/global, restablecer).
#11847 | User should be notified when NVDA turns off a user setting "behind the scenes" - regardless of what that setting might be | 10 | 0 | 2020 | Notificar cuando NVDA desactiva un ajuste del usuario internamente.
#8128 | NVDA Speech Viewer Makes Accessibility Testing Difficult to Copy Screenshot of Problem Element and its Bad Speech Output, Please Add a Caption Panel with Adjustable Text Size and Panel Size Options Similar to VoiceOver for macOS | 6 | 2 | 2018 | Visor de voz: facilitar capturas en pruebas de accesibilidad.
#9686 | Add additional ways to restart NVDA | 10 | 0 | 2019 | Formas adicionales de reiniciar NVDA.
#18772 | Back up and restore config feature | 9 | 0 | 2025 | Copia de seguridad y restauración de la configuración.
#7747 | Flexible ring of settings | 8 | 0 | 2017 | Anillo de ajustes flexible (elegir qué ajustes contiene).
#8388 | Enhance Speech Viewer to Let User Adjust Font Size | 6 | 1 | 2018 | Visor de voz: ajustar tamaño de fuente.
#5026 | Add colors to speech viewer | 8 | 0 | 2015 | Visor de voz: colores.
#14274 | Display information on new features to users after the update | 8 | 0 | 2022 | Mostrar novedades al usuario tras actualizar.
#6788 | Implement an Advanced configuration editor for NVDA | 7 | 0 | 2017 | Editor de configuración avanzada.
#7674 | Read the descriptions of options in settings | 7 | 0 | 2017 | Leer descripciones de las opciones de ajustes.
#17869 | Feature request:Add acceleration keys to some menu items | 7 | 0 | 2025 | Teclas aceleradoras en elementos de menú.
#814 | Add a "Remove" button that would allow the user to remove the system configuration for NVDA | 7 | 0 | 2010 | Botón para eliminar la configuración de sistema de NVDA.
#4472 | Add a hotkey to apply to all configuration. | 6 | 0 | 2014 | Atajo para aplicar un cambio a toda la configuración (todos los perfiles).
#6969 | Feature request: Provide a way to back up configurations | 6 | 0 | 2017 | Forma de hacer copia de seguridad de configuraciones.
#9804 | Synth Settings Ring: Remember last Focused Setting | 6 | 0 | 2019 | Anillo de ajustes: recordar el último ajuste enfocado.
#16327 | Button to clear speech viewer, option to log time relative to opening speech viewer | 6 | 0 | 2024 | Visor de voz: botón limpiar y tiempos relativos.
#12973 | give the user a graphical interface that allows the creation of automated routines  | 6 | 0 | 2021 | Interfaz gráfica para crear rutinas automatizadas (macros).
#1690 | Add documentation hints to the welcome dialog | 6 | 0 | 2011 | Pistas de documentación en el diálogo de bienvenida.
#11674 | Secure Screens: Allow configuration to be loaded from a custom directory | 5 | 0 | 2020 | Pantallas seguras: cargar la configuración desde un directorio personalizado.
#11629 | Installer: Add checkbox to optionally start NVDA after a successful installation, rather than performing this automatically | 5 | 0 | 2020 | Instalador: casilla para iniciar NVDA tras instalar.
#11262 | Add option to set hotkey on start menu shortcut instead of desktop shortcut | 5 | 0 | 2020 | Asignar el atajo al acceso del menú Inicio en lugar del escritorio.
#8157 | suggestion, allow you to link a profile to a specific document | 4 | 0 | 2018 | Asociar un perfil a un documento concreto.
#18029 | Notify user when settings are applied | 2 | 1 | 2025 | Notificar al usuario cuando se aplican los ajustes.
#11129 | Change default configuration folder in registry | 4 | 0 | 2020 | Cambiar la carpeta de configuración por defecto vía registro.
#16500 | Feature request: search in settings | 1 | 1 | 2024 | Búsqueda dentro de los ajustes.
#14555 | Dark Mode for help menu documents | 3 | 0 | 2023 | Modo oscuro para los documentos de ayuda.
#17356 | Use a hyper-legible font in NVDA | 3 | 0 | 2024 | Usar una fuente hiperlegible en NVDA.
#3772 | Speech Viewer: Indicate when an utterance would interrupt the previous utterance | 3 | 0 | 2014 | Visor de voz: indicar cuándo una locución interrumpe la anterior.
#8514 | Option to set up the period time for checking for available updates (including usage statistics) | 3 | 0 | 2018 | Configurar la periodicidad de comprobación de actualizaciones.
#18018 | Add Group Policy Object to control update behavior | 3 | 0 | 2025 | Directivas de grupo (GPO) para controlar las actualizaciones.
#10651 | Installer: Add Choice to Start NVDA after Logging onto Windows for the Current User | 3 | 0 | 2019 | Instalador: elegir iniciar NVDA tras el inicio de sesión del usuario actual.
#2467 | A checkbox to also copy installed add-ons when creating a portable copy of NVDA | 3 | 0 | 2012 | Casilla para copiar complementos al crear copia portable.
#18954 | Feature Request: Suggesting NVDA Change Its Directory Structure for Storing Files | 3 | 0 | 2025 | Cambiar la estructura de directorios donde NVDA guarda archivos (portable).
#14769 | Jump to the coresponding settings category even when the settings dialog is open | 2 | 0 | 2023 | Saltar a la categoría de ajustes aunque el diálogo ya esté abierto.
#16565 | NVDA User Configuration syncing via NV Access account | 2 | 0 | 2024 | Sincronizar la configuración del usuario mediante cuenta NV Access.
#18303 | Add a more useful mechanism for modifying the secure mode config | 2 | 0 | 2025 | Mecanismo más útil para modificar la configuración de modo seguro.
#20619 | Feature: CLI argument to start after I sign in | 2 | 0 | 2026 | Argumento CLI para "iniciar tras iniciar sesión".
#12688 | Speech Viewer - allows to save speech viewer output into a file | 1 | 0 | 2021 | Visor de voz: guardar la salida en un archivo.
#15072 | Allow to download NVDA update in background | 1 | 0 | 2023 | Descargar la actualización de NVDA en segundo plano.
#16659 | Provide a way to externally check for updates | 1 | 0 | 2024 | Comprobar actualizaciones externamente (CLI/API).
#13532 | Sleep mode should give an indication when activated | 1 | 0 | 2022 | El modo dormir debe dar indicación al activarse.
#9321 | Allow editing of inactive profiles | 0 | 0 | 2019 | Editar perfiles inactivos.

## Navegación / cursor de revisión / objetos (20)

#1839 | Global plugin: report selected items in lists | 33 | 0 | 2011 | Anunciar los elementos seleccionados en listas.
#15093 | Needed key strokes to report text from the beginning of line to the cursor, and from the cursor to the end of the line | 26 | 0 | 2023 | Teclas para leer desde el inicio de línea hasta el cursor y desde el cursor al final.
#5488 | Extend the "Read active window" command to be able to spell the information, as well as to copy it to clipboard | 18 | 0 | 2015 | "Leer ventana activa": poder deletrearla y copiarla al portapapeles.
#19405 | Missing command to read current paragraph | 14 | 0 | 2025 | Comando para leer el párrafo actual.
#18371 | Add a gesture to read all active progress bars and scroll bars in the foreground application. | 10 | 0 | 2025 | Gesto para leer todas las barras de progreso y desplazamiento activas.
#13977 | allow the user to associate personal help text with a window or control | 9 | 0 | 2022 | Asociar texto de ayuda personal a una ventana o control.
#4100 | Command to Jump to the Last Object When Using Object Navigation | 8 | 0 | 2014 | Comando para saltar al último objeto en navegación de objetos.
#16048 | Add ability to search for objects in the window where the focus or navigator object is located | 8 | 0 | 2024 | Buscar objetos en la ventana del foco/navegador.
#18915 | Line boundaries should be treated consistently by review commands | 8 | 0 | 2025 | Tratar los límites de línea de forma consistente en comandos de revisión.
#6746 | Features suggestion to add a third state to NVDA+7 (Focus moves navigator object) | 7 | 0 | 2017 | Tercer estado para NVDA+7 (el foco mueve el objeto navegador).
#18431 | Allow cycling through review modes rather than just moving to next or previous. | 5 | 1 | 2025 | Ciclar entre modos de revisión en vez de sólo siguiente/anterior.
#10320 | Request: ability to bring up and read tooltips without a mouse | 6 | 0 | 2019 | Mostrar y leer tooltips sin ratón.
#4789 | Allow say all to read all items in lists | 5 | 0 | 2015 | Say all que lea todos los elementos de listas.
#19362 | Restrict object navigation to current window | 1 | 2 | 2025 | Restringir la navegación de objetos a la ventana actual.
#3987 | emulate the right click of mouse on review cursor. | 4 | 0 | 2014 | Emular clic derecho en la posición del cursor de revisión.
#18372 | NVDA should read all progress bars in the foreground window | 4 | 0 | 2025 | Leer todas las barras de progreso de la ventana en primer plano.
#7749 | Lock navigation or review mode | 3 | 0 | 2017 | Bloquear el modo de navegación o revisión.
#20120 | Feature from Add-on] Add a virtual text review window | 0 | 1 | 2026 | Ventana virtual de revisión de texto (integrar complemento).
#7855 | Allow NVDAs find function to work outside browse mode, based on review cursor scope | 1 | 0 | 2017 | Buscar fuera del modo exploración usando el ámbito del cursor de revisión.
#19363 | Consider adding a cycle handler for changing navigation paterns between object navigation and system focus / cursor | 0 | 0 | 2025 | Ciclo para cambiar el patrón de navegación (objetos / revisión).

## Notificaciones / anuncios automáticos (6)

#17520 | Sometimes it is necessary to disable the reporting of window title changes by NVDA | 9 | 0 | 2024 | Poder desactivar el anuncio de cambios de título de ventana.
#16564 | Add a "Notifications" settings panel, to include settings for various real-time notifications | 8 | 0 | 2024 | Panel de ajustes "Notificaciones" para avisos en tiempo real.
#10265 | Screen curtain global command: report state on first press | 7 | 0 | 2019 | Comando de cortina de pantalla: anunciar el estado con la primera pulsación.
#5031 | create option to set intervals for progress bar announcement | 5 | 0 | 2015 | Configurar intervalos de anuncio de barras de progreso.
#4301 | Report when switching to a new tab if not otherwise reported | 5 | 0 | 2014 | Anunciar el cambio a una nueva pestaña si no se reporta.
#8345 | automatic announcement of frame update | 2 | 0 | 2018 | Anuncio automático de actualización de marcos.

## Ratón / táctil (20)

#11898 | Small delay option for reporting under the mouse | 19 | 0 | 2020 | Retardo opcional para anunciar lo que hay bajo el ratón.
#6048 | Mouse Over Elements | 18 | 0 | 2016 | Anunciar elementos al pasar el ratón por encima (mouse over).
#788 | Automatically move mouse with flat review | 17 | 0 | 2010 | Mover el ratón automáticamente con la revisión plana.
#19276 | Support native mouse tracking in Chromium 142+ (UIA enabled by default) | 13 | 1 | 2025 | Rastreo del ratón nativo en Chromium 142+ (UIA activado por defecto).
#15197 | Cannot respond to plugging or unplugging of touchscreen devices during NVDA operation. | 13 | 0 | 2023 | Responder a conexión/desconexión de pantallas táctiles en marcha.
#19540 | Add a new mouse setting "System focus follows mouse" | 12 | 0 | 2026 | Nuevo ajuste "el foco del sistema sigue al ratón".
#19799 | Add new mouse option: Enable mouse tracking in Speech on Demand | 10 | 0 | 2026 | Activar el rastreo del ratón en el modo "voz bajo demanda".
#18361 | Give the user a way to label unknown mouse pointers | 7 | 0 | 2025 | Permitir etiquetar punteros de ratón desconocidos.
#3929 | Make mouse tracking use display model, when other methods of text retrieval fail | 7 | 0 | 2014 | Rastreo del ratón con el modelo de pantalla cuando fallen otros métodos.
#3779 | Introduce a "pass through" mode for touch gestures | 7 | 0 | 2014 | Modo "paso directo" (pass through) para gestos táctiles.
#11857 |  Away to select copy and paste text using only touch gestures for NVDA  | 6 | 0 | 2020 | Seleccionar, copiar y pegar texto sólo con gestos táctiles.
#10319 | Request: Mouse hover states shortcut key (and current setting) | 5 | 0 | 2019 | Atajo para alternar estados hover y conocer el ajuste actual.
#4769 | improvements in support of touch screen NVDA | 5 | 0 | 2015 | Mejoras en el soporte de pantallas táctiles.
#19372 | Implement a delay/timeout for mouse tracking to speak only on mouse stop/hover | 4 | 0 | 2025 | Retardo/timeout para que el rastreo del ratón hable sólo al detenerse.
#18362 | add a gesture to allow the user to read the shape of the current mouse pointer. | 3 | 0 | 2025 | Gesto para leer la forma del puntero del ratón.
#3802 | remember different mouse positions, so the mouse can be ruted to them later | 3 | 0 | 2014 | Recordar posiciones del ratón para enrutar el puntero más tarde.
#17830 | Feature request: In the browser, reports the URL of the linked element pointed to by the mouse. | 3 | 0 | 2025 | Anunciar la URL del enlace bajo el ratón en el navegador.
#8480 | Improve clarity of mouse routing commands | 2 | 0 | 2018 | Mayor claridad en los comandos de enrutamiento del ratón.
#20382 | Move the browse mode cursor by element, instead of using object navigation when navigating by all elements in browse touch mode | 2 | 0 | 2026 | Táctil: mover el cursor de exploración por elemento en vez de navegación de objetos.
#18461 | NVDA Touchscreen support needs refinements | 0 | 0 | 2025 | Refinamientos del soporte táctil.

## Complementos / sistema / API / acceso remoto (39)

#14430 | Add-on store:  don't interrupt user for addon install tasks when exiting. | 18 | 0 | 2022 | Tienda: no interrumpir al usuario con tareas de instalación al salir.
#17763 | Function to copy list of add-ons from store | 15 | 0 | 2025 | Tienda: copiar la lista de complementos.
#20374 | Add base language field to add-on manifest, add ability to filter out unlocalised add-ons from store | 14 | 0 | 2026 | Campo de idioma base en el manifiesto y filtrar complementos no localizados (ADR).
#10248 | Improve appModules to be able to maintain support for several versions of an app | 14 | 0 | 2019 | AppModules capaces de soportar varias versiones de una aplicación.
#5960 | Allow appModules to specify custom tab orders | 12 | 1 | 2016 | AppModules con orden de tabulación personalizado.
#18278 | Add ability to report program name and version information | 13 | 0 | 2025 | Comando para anunciar nombre y versión del programa.
#18450 | Migrate from NSIS to WiX or InnoSetup | 13 | 0 | 2025 | Migrar el instalador de NSIS a WiX o InnoSetup.
#6822 | Add support for configuration and add-on inheritance | 6 | 2 | 2017 | Herencia de configuración y complementos.
#20151 | Allow add-ons to overwrite core script functions | 10 | 0 | 2026 | Permitir a complementos sobrescribir scripts del núcleo.
#9845 | App modules: if two or more add-ons use the same app module, the one loaded later will be used | 10 | 0 | 2019 | Varios complementos con el mismo appModule (hoy gana el último).
#20402 | Hide add-ons from the add-on store | 9 | 0 | 2026 | Tienda: ocultar complementos.
#12586 | Extend context help capability to add-ons | 9 | 0 | 2021 | Extender la ayuda contextual a complementos.
#13526 | Create NVDA's com object as NVDA Controller library equivalent | 9 | 0 | 2022 | Objeto COM de NVDA equivalente a la librería Controller.
#15633 | Feature Request: Show download progress bar when downloading add-ons | 8 | 0 | 2023 | Tienda: barra de progreso de descarga.
#17541 | Add an option to use system notifications for NVDA add-on updates | 6 | 1 | 2024 | Usar notificaciones del sistema para actualizaciones de complementos.
#13454 | Add ability to read documentation before installing add-ons | 7 | 0 | 2022 | Tienda: leer la documentación antes de instalar.
#12945 | ControllerClient: implement pause/resume speech and speaking of single characters | 7 | 0 | 2021 | ControllerClient: pausa/reanudar voz y hablar caracteres sueltos.
#4467 | improvement in NVDA recovery | 7 | 0 | 2014 | Recuperación de NVDA cuando deja de responder (estilo JAWS).
#20843 | ADR: Gracefully degrade when optional Windows capabilities are unavailable | 7 | 0 | 2026 | ADR: degradar con elegancia si faltan capacidades opcionales de Windows.
#15947 | addon store: Don't reset filters when switching tabs | 4 | 1 | 2023 | Tienda: no restablecer filtros al cambiar de pestaña.
#18292 | SEND File in Remote Access | 6 | 0 | 2025 | Acceso remoto: enviar archivos.
#19445 | Add a status bar to the Add-on Store | 1 | 2 | 2026 | Tienda: barra de estado.
#19537 | NVDA fails to launch in Windows PE environment with no error output | 5 | 0 | 2026 | Arrancar en Windows PE.
#18136 | Confirmation Dialogs for NVDA Remote Control Actions | 5 | 0 | 2025 | Acceso remoto: diálogos de confirmación para acciones.
#17784 | Add end-to-end encryption to Remote | 5 | 0 | 2025 | Acceso remoto: cifrado de extremo a extremo (hito 2027.1).
#16278 | Proposal: add-on categories in the add-on store | 4 | 0 | 2024 | Tienda: categorías de complementos.
#15948 | addon store: don't filter out incompatible addons in the update tab | 4 | 0 | 2023 | Tienda: no filtrar complementos incompatibles en la pestaña de actualizaciones.
#20265 | When installing an update for an add-on check to see if it is also installed for the system configuration and if so offer to update that as well. | 4 | 0 | 2026 | Al actualizar un complemento, comprobar si también está en la configuración de sistema.
#18968 | Allow quick reestablishment of NVDA Remote connection established at startup | 4 | 0 | 2025 | Acceso remoto: restablecimiento rápido de la conexión iniciada al arrancar.
#5780 | Allow add-ons to bundle Configuration profiles | 3 | 0 | 2016 | Permitir que los complementos incluyan perfiles de configuración.
#18449 | Migrate from py2exe to pyInstaller | 3 | 0 | 2025 | Migrar de py2exe a PyInstaller.
#12895 | give nvda the ability to easily tell you which add-ons are slowing nvda to load, or are consuming too many resources  | 2 | 0 | 2021 | Indicar qué complementos ralentizan la carga o consumen recursos.
#14592 | License acceptance dialog when installing an add-on | 2 | 0 | 2023 | Diálogo de aceptación de licencia al instalar un complemento.
#19444 | Indicate add-on size in Add-on Store | 0 | 1 | 2026 | Indicar el tamaño de cada complemento.
#18103 | Add option to enable software SAS generation from NVDA | 2 | 0 | 2025 | Acceso remoto: generar SAS (Ctrl+Alt+Supr) por software.
#20673 | Make the Host edit box in the remote access settings dialog an editable combo box, same as the connect dialog, to be able to save multiple hosts | 1 | 0 | 2026 | Acceso remoto: campo Host como combo editable con historial.
#17870 | Feature request: Supports specifying update channels for multiple Add-ons at the same time | 0 | 0 | 2025 | Asignar canal de actualización a varios complementos a la vez.
#19899 | Remote access: Add a type input_gesture to execute gesture on follower's side | 0 | 0 | 2026 | Acceso remoto: ejecutar un gesto en el equipo controlado.
#17884 | remote: add documentation on how to connect to computers on the same network without using a relay server | 0 | 0 | 2025 | Acceso remoto: documentar conexión en la misma red sin servidor.

## Rendimiento (6)

#6437 | UIA handler: add ability for plugins and other subsystems to request event tracking for specific objects | 10 | 0 | 2016 | UIA: permitir que plugins pidan seguimiento de eventos para objetos concretos.
#14399 | Profile switching is slow as NVDA freezes when connecting to a Braille device using Bluetooth | 9 | 0 | 2022 | Cambio de perfil lento por conexión Bluetooth con pantalla braille.
#20936 | Focus changes in web browsers make many avoidable calls to the browser | 0 | 0 | 2026 | Cambios de foco en navegadores: evitar muchas llamadas innecesarias al navegador.
#20935 | Typed characters and synthesizer notifications wait for NVDA's delayed core pump | 0 | 0 | 2026 | Caracteres tecleados y notificaciones del sintetizador esperan al core pump retardado.
#20439 | Split mouse and keyboard hook message loops into independent threads | 0 | 0 | 2026 | Separar los bucles de mensajes de hooks de ratón y teclado en hilos independientes.
#16682 | CONTROL+ALT+N shortcut much slower at starting NVDA than other methods | 0 | 0 | 2024 | Ctrl+Alt+N tarda mucho más en arrancar NVDA que otros métodos.

## Milestones / roadmap

Milestones abiertos (API `repos/nvaccess/nvda/milestones?state=open`): **2026.3** (#94, 13 abiertos / 259 cerrados), **2027.1** (#91, 12 abiertos / 47 cerrados), **2027.2** (#97, 3 abiertos), **2028.1** (#98, 2 abiertos). Milestones cerrados recientes: 2026.2 (342), 2026.1 (501), 2025.3.2, 2025.2 (288), 2025.1 (698).

GitHub Projects de la organización nvaccess: no accesibles con el token disponible (requiere scope `read:project`). No hay roadmap público verificable vía API; el roadmap real se infiere de milestones, etiquetas ADR y PR abiertas.

### Elementos abiertos en milestones

- 2027.1: #17784 cifrado de extremo a extremo en Acceso remoto (p2); #19743/#19744/#19745 eliminar pickle (seguridad); #19295 hacer internos los paneles de ajustes; #20757 ciclo de vida coherente de ajustes de drivers/proveedores al cambiar de perfil; #17640 refactor addonHandler; #20730 instalador como API privada; #19781 quitar appModule de Skype; #20788 actualizar dependencias; #19634 GUI en pantallas seguras; #20840 portable en rutas largas.
- 2026.3 (actual): sobre todo la nueva **Lupa nativa** (#20360 foco y caret por separado, #20358 seguir cursor de exploración, #20415, #20290, #20636, #20860, #19528, #20518), #20754 distinguir pulsación vs repetición de tecla, #20823 nombres de opciones de ajuste de texto braille, #20118 error al copiar ajustes, #20846 Chromium 153 IA2 (p1).
- 2027.2: PR #20922 versalitas (small caps), PR #20910 menú contextual en lista de símbolos, PR #19122 Bluetooth LE para DotPad.
- 2028.1: #20693 nuevo diálogo de edición de símbolos + PR #20892 rediseño del diálogo de pronunciación de símbolos.

### ADR (decisiones de arquitectura) abiertas: señales de roadmap

- #20641 ADR: integrar modelos avanzados de descripción de imágenes en el núcleo (34 com, needs-changes) [ya cubierto]
- #20877 ADR: roles ARIA DPub
- #20843 ADR: degradar con elegancia sin capacidades opcionales de Windows
- #20736 ADR: registro de tablas braille desde metadatos de liblouis
- #20023 ADR: modo reposo de pantalla braille
- #19868 ADR: cifrado E2E del protocolo de acceso remoto
- #20780 ADR: motores OCR alternativos mediante proveedores en complementos
- ADR requerido: #20374 (idioma base de complementos), #20274 (sincronización voz/braille en say all), #20265, #19338 (traducir descripciones IA), #18663 (PaddleOCR) [cubierto], #12009 (diálogos modales), #9168 [cubierto], #7232 [cubierto], #6272 (comandos de revisión en matemáticas), #46 [cubierto].

### Funcionalidades recién incorporadas en NVDA (PR fusionadas; útil para saber qué ya existe)

- 2026.3 (fusionadas): #20665 modo de selección nativa en modo exploración; #20664/#20630 Windows Graphics Capture para reconocimiento con cortina/lupa; #20628 navegación rápida por elementos clicables; #20603 segmentación de frases ICU; #20379 segmentación de palabras ICU; #20183/#20642 segmentación de palabras china (y en braille); #20551 gestos táctiles de borde de pantalla; #20527 copiar última locución al portapapeles; #20526 editar gestos existentes; #20484 historial de búsqueda en Buscar; #20435 menú contextual en perfiles; #20424 menú contextual en diccionarios; #20426 pantallas myBraille; #20372 resaltado visual en navegación matemática web; #20250/#20028 enrutamiento múltiple braille; #20238 comando ratón a vista de lupa; #20186/#20146/#20145 ajuste de texto braille por sílabas y marcas de continuación; #20179 isSpeaking en controller client; #20086 gestos táctiles de doble flick; #19473 ventana de lupa fija; #20555 WinUSB para HIMS.
- 2026.2: #19228 implementación de la Lupa; #19126 autoscroll braille; #19963 gestos de pellizco; #19871 scripts MathCAT; #19795 pausa de puntuación OneCore; #19718 reiniciar Windows tras actualización; #19593 true center; #19575 deshacer restablecimiento de fábrica; #19558 diccionarios de voz en complementos; #19517 más tipos de entrada de diccionario; #19414 navegación web táctil por elementos; #19398 navegación por deslizadores; #19349 gesto para cambiar distribución de teclado; #19309 búsqueda difusa en la tienda; #19767 estado de cortina.
- 2026.1: #19432/#19541 sintetizadores SAPI4/SAPI5 de 32 bits vía host (NVDA 64 bits); #19700 voz matemática nativa de Word; #19310 navegación por notas al pie/final en Word; #19282 alternar coordenadas de audio del ratón; #19150 leer resultado de reconocimiento automáticamente; #18974 resultados VirusTotal en la tienda; #18816 changelog en la tienda; #18735 navegación por palabras en chino; #18641 errores ortográficos en braille; #18475 descripciones de imagen con IA local (luego revertido en #19425 y retomado vía ADR #20641).


## Open PRs adding features (upcoming)

Sólo hay 16 PR abiertas (NV Access cierra/fusiona rápido). Formato: `#PR | borrador | creada | autor | título | etiquetas`.

#20959 | draft=true | 2026-10-06 | SaschaCowley | Add character mode to OneCore synth | 
#20958 | draft=false | 2026-10-06 | eilatc | Chromium: don't report the document when the focused element is removed and focus moves on shortly after | 
#20953 | draft=false | 2026-10-05 | pre-commit-ci[bot] | Pre-commit auto-update | 
#20952 | draft=false | 2026-10-05 | nvdaes | Fix: braille automatic scrolling can be disabled immediately after pressing NVDA+alt+k | 
#20940 | draft=true | 2026-10-03 | Efury1 | Make repeated symbol count threshold configurable | 
#20939 | draft=false | 2026-10-03 | LeonarddeR | Fix redundant table start markers in braille in Word with UIA enabled that cause parts of cells to disappear | 
#20924 | draft=false | 2026-10-02 | LeonarddeR | Add unit tests for comment threads in Word via UIA | 
#20922 | draft=false | 2026-10-01 | burrm | Small caps implementation | blocked
#20910 | draft=false | 2026-10-01 | amirmahdifard | Added context menu and keyboard shortcut to symbols list | blocked
#20892 | draft=false | 2026-09-27 | amirmahdifard | redesigned the symbol pronunciation dialog | blocked,api-breaking-change,blocked/needs-product-decision
#20890 | draft=false | 2026-09-25 | theshippeys | Fix for creating duplicate gesture for same script | conceptApproved
#20833 | draft=true | 2026-09-11 | seanbudd | Delay loading JAB | 
#20831 | draft=true | 2026-09-11 | SaschaCowley | Don't send CharacterModeCommand when unsupported by the synthesizer | conceptApproved
#20796 | draft=true | 2026-09-06 | nvdaes | Use nvaccess/nvdaL10n repo as a submodule | blocked
#20760 | draft=true | 2026-08-29 | michaelDCurran | Enhance UIA remote ops code by moving to a Python extension, adding support for GUIDs, and support for elif. | conceptApproved
#19122 | draft=true | 2025-10-20 | bramd | Add Bluetooth Low Energy support for DotPad braille displays | conceptApproved,merge-early

Relevantes para funcionalidades: #20959 modo carácter en OneCore; #20940 umbral configurable de símbolos repetidos (issue #20605); #20922 versalitas; #20910 menú contextual en lista de símbolos; #20892 rediseño del diálogo de símbolos; #20890 evitar gestos duplicados (issue #10872); #20833 carga diferida de Java Access Bridge; #20831 no enviar CharacterModeCommand si no se soporta; #20760 operaciones remotas UIA como extensión Python; #19122 Bluetooth LE para DotPad; #20958 Chromium: no anunciar el documento cuando el foco se elimina y se mueve enseguida.


## Discussions ideas

Obtenidas vía GraphQL (categoría Ideas: 109 discusiones). Formato: `#N | título | votos | comentarios | fecha`. Ordenadas por votos*2+comentarios. Nota: algunas son issues convertidas a discusión (comparten numeración).

#14912 | Add-on store discussion | 1 | 52 | 2023-05-08
#17491 | Add a decider extension point to suppress key echo | 1 | 43 | 2024-11-29
#14734 | How can NVDa screen readers work and access with mobile game development tool BuildBox to help visually impaired developers make use of everything to get projects done in no time . | 1 | 36 | 2021-04-18
#15965 | change the license to MIT | 1 | 32 | 2023-12-23
#20566 | Exploring NVDA for Android: Leveraging Open-Source TalkBack Architecture and Native Engine Integration | 10 | 12 | 2026-07-27
#17415 | Redesign profile handling in NVDA so users can lock / unlock them | 2 | 27 | 2024-11-18
#14795 | Seeking community feedback: Disallow add-ons to run on secure screens. | 1 | 29 | 2022-05-11
#13738 | Find functionality for log viewer | 1 | 29 | 2015-02-17
#15995 | Feature request: build JavaScript accessibility bridge to improve accessibility of web applications | 4 | 19 | 2024-01-01
#14942 | There should be a command to toggle high verbosity on and off in browse mode | 1 | 21 | 2023-05-18
#14919 | Windows 10: Battery status script change to make it report time till fully charged | 1 | 18 | 2015-08-01
#13445 | Request: option for NVDA to not speak in response when Global Media keys are pressed | 1 | 18 | 2022-03-02
#15299 | Reconsider NVDA code style, linting and auto formatting | 4 | 11 | 2023-08-15
#15996 | Feature request: add more QuickNav command in browse mode | 2 | 14 | 2023-12-29
#16049 | Feature request: Add audio volume control and sound split commands | 1 | 15 | 2024-01-12
#17515 | Provide access to graphics written to the screen | 1 | 14 | 2011-02-17
#16304 | [Project] Convert NVDA to 64 bit | 2 | 10 | 2024-03-15
#16241 | Improve security perception for NVDA add-ons | 1 | 12 | 2024-02-29
#20413 | Reconsidering NVDA's default global gestures through the Magnifier case | 5 | 3 | 2026-06-28
#17474 | Excel: add a way to report cell size / content size | 1 | 11 | 2024-11-22
#13256 | automatic saving of settings on exit should not be the default | 1 | 11 | 2022-01-16
#18209 | Timing for release of NVDA Add-Ons to the Add-On Store during beta testing . . . | 1 | 10 | 2025-05-27
#17933 | Integrate a High-Quality Text-to-Speech Engine for Natural Speech Output | 4 | 4 | 2025-04-10
#17259 | What to speak when whole text selection is cancelled | 1 | 10 | 2024-10-04
#14629 | include many new espeak variants in attachment | 1 | 10 | 2023-02-09
#13922 | Suggestion for more efficient window and application switching | 1 | 10 | 2022-07-16
#20283 | Add links or key information to the settings screens? | 1 | 9 | 2026-06-04
#14855 | NVDA and StationPlaylist radio automation software | 1 | 9 | 2023-04-20
#16403 | allow NVDA to interrupt speech when dynamic screen content refreshes | 1 | 9 | 2024-04-16
#18718 | Experimenting with pypy and nuitka | 1 | 8 | 2025-08-15
#19544 | managing add-ons for secure screens | 1 | 8 | 2026-02-02
#18770 | Limit automatic detection of Braille Displays that use generic USB IDs that might match other devices | 1 | 8 | 2025-07-26
#16139 | Adding a new language Kazakh (Kazakhstan) | 1 | 8 | 2024-02-07
#15117 | Feature Request: Once the add-on download from the Add-on Store is finished, a sound notification should be triggered to alert the user. | 1 | 8 | 2023-06-28
#14761 | make NVDA updatable without administrative rights (same behaveour as Mozilla applications) | 1 | 7 | 2017-07-28
#16879 | Implement some useful braille features | 1 | 7 | 2018-02-18
#14781 | Seeking Community advise: make mathematical Equations more accessible | 2 | 5 | 2023-03-31
#15600 | Allow contributors to claim credit for contributions in the change log entry | 3 | 3 | 2023-10-11
#19679 | Expand "Say all with review" to read beyond the current object | 1 | 6 | 2026-02-01
#16782 | Add multi Modal LLM Support | 2 | 4 | 2024-07-01
#15673 | Introduce precommit hooks | 1 | 6 | 2023-09-04
#12517 | A nvda specific pypi repo for addon update and download | 3 | 2 | 2021-06-04
#14762 | NVDA support for GoToMeeting & WebEx | 1 | 6 | 2021-03-08
#19496 | Clarify / fix the list of supported languages | 1 | 5 | 2026-01-19
#17538 | Redesign the document formating settings panel so it allows for more flexible reporting style and reporting output | 1 | 5 | 2024-12-11
#18131 | Make keyboard gestures processing layout independent | 1 | 5 | 2025-05-14
#14757 | improve behaveour of NVDA in QT applications such as MuseScore, Virtualbox, VLC, Caliber and others | 1 | 5 | 2023-03-28
#12553 | Can we choose which saved settings to apply to the secure screen? | 1 | 5 | 2021-06-15
#18245 | ARM NVDA | 1 | 4 | 2025-06-13
#19543 | Make sure the lib\version\x86\synthDriverHost-runtime folder only includes what it needs | 1 | 4 | 2026-02-02
#18671 | Add a split view mode for braille displays | 2 | 2 | 2025-08-08
#18174 | Can something be done to keep the sound card on in ultrabook computers? | 1 | 4 | 2025-05-27
#16900 | Reassign shortcuts to multi-layer gestures (a single keyboard shortcut can perform different functions based on the number of times it is pressed) | 1 | 4 | 2024-07-20
#16397 | Suggestion: NVDA troubleshoot the startup process to avoid extreme situations that may cause users to be unable to use it | 1 | 4 | 2024-04-05
#15399 | Error Sounds: Consider enabling for release builds where Log Level has been set to Debug | 1 | 4 | 2020-09-19
#13822 | improving ESpeak-ng for NVDA | 1 | 4 | 2022-06-20
#14787 | custom Llama 7B gpt4all large language model AI for NVDA | 1 | 4 | 2023-04-04
#14497 | Feedback on Braille Pc keyboard typing | 1 | 4 | 2023-01-02
#13427 | A survey is needed to see if good defaults are being used | 1 | 4 | 2022-03-04
#20215 | Research on the feasibility of using string hashing as the skeleton and unit ID for XLIFF files | 1 | 3 | 2026-05-25
#19845 | Making NvDA codebase more accessible, creating more components under documentations for issues/pr labels related to it. | 2 | 1 | 2026-03-25
#19735 | Issues requiring a Windows Restart after an install | 1 | 3 | 2026-03-03
#19726 | Proposal: Temporary Repository Bifurcation (Fork) for 32-bit Architecture Support during 64-bit Transition | 1 | 3 | 2026-02-28
#19104 | Change default for braille attribute indication to 'Braille tags' | 1 | 3 | 2025-09-22
#18462 | Improve Multi-Line Braille Support | 1 | 3 | 2025-07-02
#15716 | Input gesture for periodically refresh recognized content Windows OCR | 1 | 3 | 2023-10-30
#14763 | When selecting a long paragraph, nvda could speak the first few words and last few words, instead of just saying number of words | 1 | 3 | 2023-03-23
#14344 | Ignore Java access bridge events when not focused inside the Java window | 1 | 3 | 2022-11-02
#13844 | Remove the NVDA menu on secure screens | 1 | 3 | 2022-06-26
#17248 | Contracted Braille Input Issues | 1 | 3 | 2018-03-04
#20896 | # NVDA’s Magnifier is real now. But how close is it to being a complete screen magnifier? | 1 | 2 | 2026-09-28
#20228 | Survey table | 1 | 2 | 2026-05-27
#19547 | TripleTalk USB synthesizer driver | 2 | 0 | 2026-02-02
#18583 | Flattened object navigation | 1 | 2 | 2025-07-29
#18195 | It can be a solution to the reading problem of objects and texts under mouse cursor. | 1 | 2 | 2025-05-31
#18132 | Accessibility API handlers (long-term): provide similar interfaces/modules between different API handlers | 1 | 2 | 2021-11-25
#18010 | I think speech interupt for typed characters should be checked by default. | 1 | 2 | 2025-04-24
#17653 | NVDA's Hiding of 0-width, 0-height Controls in Browse Mode is Problematic | 1 | 2 | 2025-01-25
#16723 | Browse Mode maximum character | 1 | 2 | 2024-06-19
#15738 | Enhanced OCR Options for a More Flexible Experience | 1 | 2 | 2023-11-03
#15561 | NVDA should handle nested landmarks | 1 | 2 | 2023-09-27
#14999 | Add-on Store: More friendly organization of the Actions/context menu | 1 | 2 | 2023-06-08
#14941 | NVDA reads the first line of websites and emails with browse mode turned off | 1 | 2 | 2023-05-20
#14106 | Define a way to test NVDA's interaction with Windows features and aps | 2 | 0 | 2022-09-05
#14014 | espeak ng suggestions with klatt synthesis variants, and some tips to improve the default NVDA voice. | 1 | 2 | 2022-08-12
#13861 | Change punctuation pauses for Microsoft voices | 2 | 0 | 2022-06-30
#13726 | Allow installation of incompatible add-ons | 1 | 2 | 2022-05-23
#20865 | A Vision for NVDA Beyond Windows: Bringing a Powerful Screen Reader to Linux | 1 | 1 | 2026-09-17
#19545 | Thoughts on keeping last x spoken items for NVDA-x double press | 1 | 1 | 2026-02-02
#19201 | A brief analysis of a web page not based on artificial intelligence. | 1 | 1 | 2025-11-06
#19200 | Intelligent screen reading | 1 | 1 | 2025-11-06
#16762 | Available Python modules in NVDA's runtime environment | 1 | 1 | 2024-06-27
#16090 | Some web pages are incorrectly divided into paragraphs | 1 | 1 | 2024-01-24
#15889 | The NVDA browser nav addon should be implimented into NVDA. | 1 | 1 | 2023-12-07
#15706 | NVDA code base: employ structural pattern matching to make the code more readable | 1 | 1 | 2023-10-29
#15095 | Feature Request: Adopting the status text from the older version of the Add-on Manager offers a more accurate representation of the current state of the add-on, as well as its condition after an NVDA restart. | 1 | 1 | 2023-06-28
#15062 | Ability To Browse By Static Text In Web Content | 1 | 1 | 2023-06-22
#14796 | Windows 10/11: submit the NVDA installer executable to revamped Microsoft Store | 1 | 1 | 2021-11-14
#14022 | Pitch based cues for line length to help navigate large documents | 1 | 1 | 2022-08-16
#14064 | Keeping sound settings together | 1 | 1 | 2022-08-23
#12516 | Python virtual environment install is not deterministic | 1 | 1 | 2021-06-04
#20863 | Proposal: Learn from WorldVoice to improve NVDA speech features | 1 | 0 | 2026-09-17
#19526 | Enhancements to forms' support in the elements list | 1 | 0 | 2026-01-28
#18750 | Updating NVDA's Help Menu | 1 | 0 | 2025-08-19
#18745 | NVDA's display model should be improved. | 1 | 0 | 2025-08-18
#16154 | Feature Request: NVDA does not read Ballot Box (Check box, unchecked) Unicode character U+2610 | 1 | 0 | 2024-02-09
#15683 | suggestion for nvda dictionary | 1 | 0 | 2023-10-25
#14780 | settings history | 1 | 0 | 2023-04-01

### Otras discusiones (General/Announcement) con contenido de peticiones o roadmap

#15014 | Announcement | Planned Translation System Changes | 7 | 26 | 2023-06-15
#16600 | General | Current state of UIA implementation.  Was: Corporate mode for NVDA | 1 | 19 | 2024-05-21
#15167 | General | Task: let us say goodbye to unsupported Windows releases in NVDA 2024.1 | 2 | 16 | 2023-07-12
#17734 | General | All symbols are not sent to sapi 5 tts | 1 | 17 | 2024-12-16
#18166 | General | Feature request: Improve NVDA performance with sound cards | 1 | 16 | 2025-05-24
#17255 | General | Should NVAccess Join the Public Review of the New GitHub Issues Experience? | 2 | 12 | 2024-10-07
#18574 | Announcement | Proposed update to the NVDA license to GPL-2 "or later" | 4 | 3 | 2025-07-29
#20934 | General | NvDA and Terminal, an Overview and constructive discussion | 3 | 4 | 2026-10-02
#18747 | General | Inventorize launcher growth | 2 | 6 | 2025-08-18
#16713 | General | Navigate to header control items of win32 list controls in report mode | 3 | 2 | 2024-06-13
#20000 | General | NVDA at 20: celebrating, reflecting, envisioning, acting | 3 | 1 | 2026-04-22
#20075 | General | Windows 10 support in NVDA | 1 | 4 | 2026-05-06
#20214 | General | TeamTalk VoiceOver Client – Introduction & Collaboration | 1 | 3 | 2026-05-25
#19841 | General | Discussion about touchpad gesture implementation details | 1 | 3 | 2026-03-24
#19388 | General | NVDA doesn’t announce row headers on columns that precede the row header’s column | 1 | 3 | 2025-12-09
#16460 | Announcement | Request for contributors - Reducing high priority issues | 2 | 1 | 2024-04-29

## Already-covered numbers seen

Números del estudio previo y su estado actual (no incluidos en las listas principales):

#18400 | issue abierta | Native Speech History in NVDA | 28 com | 3 reac
#13288 | issue abierta | nvda support for new natural sounding voices in windows 11 dev build | 16 com | 5 reac
#17933 | discusión (Ideas) | Integrate a High-Quality Text-to-Speech Engine for Natural Speech Output | 4 com | 4 votos
#2990 | issue abierta | Automatic language detection based on unicode ranges | 77 com | 0 reac
#4273 | issue abierta | option to read numbers as individual digits | 79 com | 0 reac
#18398 | discusión (General) | Add a spell alpha/numeric option to speak things like ham calls such as ka9nuc correctly as k a 9 n u c. | 13 com | 1 votos
#46 | issue abierta | Verbosity levels | 18 com | 0 reac
#7232 | issue abierta | Allow users to change the order in which object properties are reported in speech and braille | 31 com | 1 reac
#17483 | issue abierta | ability to shorten longer announcements on web pages like heading level x, etc. | 14 com | 0 reac
#19042 | issue abierta | Have NVDA announce cut, copy, paste actions | 35 com | 0 reac
#16049 | discusión (Ideas) | Feature request: Add audio volume control and sound split commands | 15 com | 1 votos
#16056 | issue abierta | Feature request: mute microphone command | 40 com | 0 reac
#8801 | issue abierta | give the availability of a shortcut key to change from one sound output to another | 13 com | 0 reac
#4089 | issue abierta | Trigger a Sound for Control Types and States | 1 com | 0 reac
#13612 | issue abierta | Adding an audio cue if nvda cursor has reached the boundary | 8 com | 1 reac
#3858 | issue abierta | Definition lists not exposed correctly | 31 com | 23 reac
#8971 | issue abierta | NVDA repeats dialog content twice in Browsers | 12 com | 14 reac
#8983 | issue abierta | Support for aria-controls | 23 com | 14 reac
#17514 | issue abierta | in NVDA and chromium browsers,  NVDA sticks paragraphs together when display: block is present in ::before and ::after | 5 com | 13 reac
#19453 | issue abierta | NVDA announces landmark regions multiple times in modal dialogs (header/content/footer duplicated) | 2 com | 4 reac
#17662 | issue abierta | NVDA Does Not Interrupt aria-live="assertive" Announcements Properly | 3 com | 2 reac
#9168 | issue abierta | Add support for DPUB ARIA roles | 31 com | 3 reac
#11085 | issue abierta | Wrap the focus and the virtual cursor in browse mode to the first or last element after reaching the last or first element with quick navigation key | 13 com | 1 reac
#4442 | issue abierta | Add a profile trigger to associate with a website | 31 com | 0 reac
#3656 | issue abierta | Allow attaching speech dictionaries to profiles | 25 com | 0 reac
#16960 | issue abierta | Feature request for web page loading indicator | 6 com | 1 reac
#20245 | issue abierta | Addition of "Tabs" to the Links List (Elements List) Dialog | 5 com | 3 reac
#14429 | issue abierta | add clickable items to elements list dialog and shortcut for mooving between clickable items in html pages | 3 com | 1 reac
#15995 | discusión (Ideas) | Feature request: build JavaScript accessibility bridge to improve accessibility of web applications | 19 com | 4 votos
#15281 | issue abierta | [bug]: excel starts to freeze when nvda is running | 24 com | 0 reac
#6624 | issue abierta | Change Say All behaviour in Excel to read entire worksheet from current point when not in edit mode | 26 com | 0 reac
#18537 | issue abierta | Excel 2019: NVDA fails to report table row/column headers in protected sheets | 18 com | 0 reac
#7742 | issue abierta | Allow enumerations and bullets in MS Word to be treated as lists by NVDA, even though "lists" in document formating is deactivated | 18 com | 0 reac
#5350 | issue abierta | Reporting Tables in Microsoft Powerpoint | 15 com | 0 reac
#15310 | issue abierta | add option for NVDA to not automatically read first line of an email in outlook | 27 com | 0 reac
#14448 | issue abierta | MS Teams: Adaptive Card Details are read two times by NVDA screen reader. | 29 com | 0 reac
#18507 | issue abierta | NVDA Freezes and High CPU Usage in WhatsApp Beta and Discord with Fast Navigation | 3 com | 0 reac
#13157 | issue abierta | windows terminal: NVDA reads invisible lines when using pagers such as less and more | 25 com | 0 reac
#20902 | issue abierta | hang with lots of text being sent to a terminal window | 4 com | 0 reac
#16374 | issue abierta | NVDA incorrectly identifies word boundaries in Java applications | 29 com | 0 reac
#17332 | issue abierta | Object Labeler Functionality (updated feature request) | 11 com | 4 reac
#9460 | issue abierta | Quicker switching of windows and applications | 15 com | 0 reac
#19390 | issue abierta | Improve Display Model (GDI Hooking) to support graphics/symbols and undetected text in legacy apps | 11 com | 3 reac
#17209 | issue abierta | NVDA Command Palette | 26 com | 5 reac
#3605 | issue abierta | Warn user when overriding a pre-existing input gesture | 6 com | 1 reac
#15242 | issue abierta | Have NVDA report keyboard shortcut/input gesture collisions for add-ons at load time | 21 com | 1 reac
#10767 | issue abierta | Add support for AltGr in keyboard shortcuts | 36 com | 0 reac
#16607 | issue abierta | Custom NVDA Modifier Key | 8 com | 1 reac
#16479 | issue abierta | Use the windows native numpad functionality when keyboard is set to laptop layout in NVDA | 25 com | 0 reac
#1676 | issue abierta | Announcement of keyboard layout changes depending on context should be optional. | 38 com | 0 reac
#17415 | discusión (Ideas) | Redesign profile handling in NVDA so users can lock / unlock them | 27 com | 2 votos
#13256 | discusión (Ideas) | automatic saving of settings on exit should not be the default | 11 com | 1 votos
#7242 | issue abierta | New idea: Offer a tutorial for new users on welcome screen | 18 com | 0 reac
#16599 | issue abierta | Corporate mode for NVDA | 22 com | 1 reac
#16295 | discusión (General) | Feature suggestions/development/maintenance: bringing ideas/features/code from add-ons to NVDA Core | 8 com | 2 votos
#19118 | issue abierta | Option to not speak on startup (like have 'speechmode = off' on app start) | 16 com | 0 reac
#17210 | issue abierta | Add a keyboard shortcut to start NVDA with add-ons disabled | 2 com | 5 reac
#14872 | issue abierta | NVDA freeze while reloading the configuration | 35 com | 0 reac
#20654 | issue abierta | NVDA freezes for ~5 seconds when a typed character reaches a slow UIA provider | 19 com | 1 reac
#13334 | issue abierta | Holding down the down arrow in a large document causes nvda to crash and exit | 16 com | 0 reac
#17889 | issue abierta | NVDA freezes when an exception is thrown in a .NET program in Visual studio | 8 com | 0 reac
#18315 | issue abierta | Thunderbird 139 crashing causing NVDA to freeze, NVDA log included | 14 com | 0 reac
#20230 | issue abierta | nvda still freezes when using cheat engine | 10 com | 0 reac
#19551 | issue abierta | TTS Latency Occurs During Normal Navigation But Disappears When an NVDA Dialog is Open | 14 com | 1 reac
#11077 | issue abierta | Restrict most event processing to objects of interest to the user | 15 com | 0 reac
#18857 | issue abierta | Optimise NVDA startup time | 7 com | 2 reac
#6614 | issue abierta | Allow NVDA to control multiple braille displays at the same time | 15 com | 1 reac
#9213 | issue abierta | Provide Braille description of emoji | 18 com | 1 reac
#8702 | issue abierta | Show ⠀, ⠿, ⣿, a question mark or the hexadecimal value (Liblouis 3.8 style, HUC8, HUC6) for undefined characters in braille | 24 com | 0 reac
#6901 | issue abierta | Excel column/row headers are not displayed in braille | 21 com | 0 reac
#7097 | issue abierta | Braille indication of font attributes using dots 7/8 | 15 com | 0 reac
#20641 | issue abierta | ADR: Integrate Advanced Image Description Models into NVDA Core | 34 com | 0 reac
#17406 | issue abierta | Content recognition (NVDA+R): let users choose from a list of available content recognition engines/strategies | 15 com | 1 reac
#18663 | issue abierta | Integrate PaddleOCR as an alternative OCR engine | 11 com | 0 reac
#20475 | issue abierta | Windows OCR reads RTL text (Arabic/Hebrew) in reverse order (LTR). Proposed algorithmic fix. | 4 com | 0 reac
#13478 | issue abierta | NVDA OCR recognizes tables and text with long spaces in between in a wrong order | 6 com | 0 reac
#12981 | issue abierta | Allow sending an entire file to ocr  | 2 com | 0 reac
#18953 | issue abierta | Enhance 'Create Portable Copy' to use versioned folder names (eg NVDA-2025.3) | 27 com | 0 reac
#6869 | issue abierta | Add-ons use disk space after NVDA is uninstalled | 23 com | 1 reac
#11027 | issue abierta | Wine support | 28 com | 0 reac
#20583 | issue abierta | NVDA Remote needs preset options? | 17 com | 0 reac
#3564 | issue abierta | add support for sending speech over remote desktop protocol channels | 79 com | 0 reac
#498 | issue abierta | Add ability to bookmark objects, and monitor them for changes | 12 com | 0 reac
#16467 | issue abierta | Feature request: add new navigation pattern by indentation | 18 com | 0 reac
#16237 | issue abierta | Feature Request: Add word navigation to NVDA | 49 com | 0 reac
#3358 | issue abierta | Add the ability to use a Multitouch trackpad | 17 com | 0 reac
#18901 | issue abierta | Universal Availability of Sentence Navigation | 13 com | 0 reac

No encontrados como issue abierta ni discusión (probablemente cerrados/implementados o PR fusionados): #625, #2111, #10983, #18475, #19425, #4390, #8482, #13420, #18735, #19385, #19228, #3424

Estado verificado de los no encontrados: #625 cerrado (completado 2025-12, tecla para leer última locución); #2111 cerrado 2024-10 (Object Labeler; sigue abierto #17332); #10983 cerrado 2026-07 (editar gestos existentes); #18475 PR fusionada (IA local) y #19425 PR que la revirtió; #4390 cerrado 2025-03 (NVDA Remote integrado); #8482 cerrado 2026-08 (historial de búsqueda); #13420 cerrado 2022; #18735 PR fusionada (palabras en chino); #19385 cerrado 2026-07 (copiar última frase al portapapeles); #19228 PR fusionada (Lupa); #3424 cerrado 2026-03 (navegación web táctil por elementos).


## Archivos TSV de referencia (misma carpeta)

- raw_github_candidates.tsv: 977 issues abiertas candidatas (etiqueta feature/enhancement/feature-* o heurística de título), con flag covered.
- raw_github_selected_features.tsv: selección final clasificada por área con resumen en español.
- raw_github_open_prs.tsv: 16 PR abiertas.
- raw_github_discussions.tsv: 208 discusiones (Ideas/General/Announcement/Polls).
- all_open.jsonl: volcado completo de las 2237 issues+PR abiertas (número, título, comentarios, reacciones, fechas, etiquetas, inicio del cuerpo).

