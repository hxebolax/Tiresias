# Investigación: funciones que piden los usuarios ciegos de Windows (foros, competidores, necesidades especiales)

Proyecto: Tiresias (lector de pantalla en Python, clon de NVDA). Fecha de la investigación: 2026-10-06.

## Notas de método

- Excluido a propósito porque ya lo cubrió el estudio anterior: historial de voz, descripción de imágenes con IA, OCR multimotor, mezclador/silencio de micrófono, división de sonido, etiquetas personalizadas, marcadores de posición, historial del portapapeles, traducción, navegación por palabra/frase/sangría, earcons, navegación circular, resumen de página, lectura de URL, ratón por teclado, lista de la bandeja del sistema, módulos de aplicación de Office/WhatsApp/Teams, braille con liblouis, eco de escritura, tutorial, modo portátil, acceso remoto, MathCAT, cortina de pantalla, paleta de órdenes, perfiles por sitio, niveles de verbosidad, AltGr, teclado numérico híbrido, detección de idioma, lectura de números y TTS neuronal. Cuando una función nueva es una variante de algo de esa lista, se marca como **[AMPLÍA X]** y solo se describe la parte nueva.
- "(vía buscador)" significa que el dato sale solo del fragmento o resumen que devolvió el buscador. Algunas páginas no se pudieron abrir porque devolvieron 403: freedomscientific.com, support.freedomscientific.com, blog.freedomscientific.com, applevis.com (salvo el espejo atlas-entry), forum.audiogames.net y la página de Tahoe en applevis.
- Las URL de issues de GitHub (github.com/nvaccess/nvda/issues/N) se han construido con el número y el título que aparecen en los listados de GitHub que sí se visitaron:
  - https://github.com/nvaccess/nvda/issues?q=is%3Aissue%20state%3Aopen%20label%3Afeature%20sort%3Areactions-%2B1-desc (páginas 1 y 2)
  - ...sort%3Acomments-desc
  - ...label%3Ap3...
  El número que acompaña a cada issue es el recuento de reacciones o comentarios que mostraba el listado. Son aproximados: el fetcher no siempre distingue entre comentarios y reacciones.
- Escala de demanda: ALTA = la piden muchos y lo dicen muchas fuentes; MEDIA = hay hilos o issues con cierta actividad; BAJA = nicho o una sola fuente.

---

## 0. Contexto de demanda (datos duros)

- **Encuesta WebAIM n.º 11** (publicada el 29-09-2026), página visitada: https://webaim.org/projects/screenreadersurvey11/
  - JAWS sube al 55 % como lector principal, frente al 41 % en 2024; NVDA baja al 32,9 %.
  - El 85,6 % dice que los PDF probablemente le darán problemas de accesibilidad.
  - Usos de la IA: generar descripciones o texto alternativo (60,1 %) y resumir páginas o documentos (37,1 %).
  - El 83,9 % cree que mejorar las webs tendría más impacto que mejorar la tecnología de apoyo.
  - Por regiones, NVDA domina en Asia (77,4 %) y en África/Oriente Medio (83 %).
- **Encuesta WebAIM n.º 10** (2024), visitada: https://webaim.org/projects/screenreadersurvey10/
  - El CAPTCHA sigue siendo el problema número 1.
  - El 71,6 % navega sobre todo por encabezados.
  - El 72 % usa más de un lector de escritorio; el 26,5 % lo hace "por funciones" que el otro no tiene.
- **AppleVis, hilo "grudging respect for narrator"** (espejo visitado: https://atlas-entry.applevis.com/comment/188478): se elogian los gestos táctiles de Narrador y su rendimiento en Excel. Se echa en falta el cursor virtual palabra a palabra, la búsqueda por primera letra en listas y la coherencia del foco.
- **AppleVis, "Necessary NVDA 2026 Add-Ons"** (espejo visitado: https://atlas-entry.applevis.com/comment/208222): complementos más recomendados en 2026: Vision Assistant Pro (OCR e IA con Gemini, preguntas de seguimiento, OCR de PDF), Mozilla Apps Enhancements, Resource Monitor, Say Product Name and Version y Screenshots Wizard.
- **AccessWorld, "Essential NVDA addons"** (visitado: https://afb.org/blog/entry/accessworld-classics-editors-list-essential-nvda-addons): Speech History, Remote Support, Golden Cursor y **LION (OCR en vivo)**.
- **Línea base de NVDA 2026.2 y 2026.3 (para no duplicar)** (visitado: https://www.nvaccess.org/?p=33428 y https://www.nvaccess.org/?p=33468): NVDA ya trae lupa integrada, desplazamiento automático del braille (NVDA+Alt+K/L/J), NVDA+X para repetir lo último dicho, gestos táctiles de borde y de doble deslizamiento, y OCR compatible con la cortina de pantalla.

---

## 1. Navegación web y de documentos

### 1.1 Smart Navigation (navegación inteligente)
- **Producto**: JAWS. **Tecla**: INSERT+X alterna entre los niveles Desactivado, Controles, Tablas y Controles+Tablas.
- **Comportamiento**: en aplicaciones web, PDF y tablas, las flechas dejan de moverse por carácter o palabra y saltan por control o por elemento de tabla, agrupando los controles de una misma "línea" visual. Reduce las pulsaciones en webs con muchos formularios.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-internet-web-browsing-hotkey-shortcuts (visitado); niveles (vía buscador): https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-using-smart-navigation
- **Demanda**: MEDIA. Se valora en entornos corporativos con aplicaciones web densas.

### 1.2 Skim Reading (lectura rápida) y su resumen
- **Producto**: JAWS. **Teclas**: CTRL+INSERT+FLECHA ABAJO inicia; CTRL+SHIFT+INSERT+FLECHA ABAJO abre el diálogo.
- **Comportamiento**:
  - Lee solo la primera línea o la primera frase de cada párrafo.
  - Admite "reglas de texto": leer solo los párrafos que contienen una palabra o un atributo (negrita, color...).
  - Genera un **Skim Reading Summary**, una lista navegable de lo encontrado que permite saltar a cada coincidencia.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkeys (visitado); (vía buscador) https://support.freedomscientific.com/SurfsUp/14-SkimReading.htm; https://training.vispero.com/four-classic-jaws-features-that-can-transform-your-workflow/ (visitado; Vispero la presenta como "función clásica" en 2026).
- **Demanda**: MEDIA. NVDA solo tiene "permitir lectura rápida en Decir todo", que no filtra por reglas.

### 1.3 Smart Glance (lo que destaca visualmente)
- **Producto**: JAWS. **Teclas**: Y / SHIFT+Y para el siguiente o anterior "glance highlight"; INSERT+CTRL+Y abre la lista.
- **Comportamiento**: analiza la página y ordena el texto según lo raro que es su color, fuente o atributo. Lo menos frecuente se considera "destacado" (precios, avisos, ofertas), lo que permite encontrar lo que el diseñador resaltó visualmente.
- **Fuentes** (vía buscador): https://vi.ie/whats-new-in-jaws-and-fusion-2023/; https://aph.org/access-academy-handouts/whats-new-in-jaws-zoomtext-and-fusion-2023; https://training.vispero.com/learn-how-to-personalize-your-web-experience-with-jaws/ (visitado).
- **Demanda**: BAJA-MEDIA. Es única de JAWS y es una buena idea para webs mal etiquetadas.

### 1.4 Flexible Web: ocultar elementos y empezar a leer en un punto
- **Producto**: JAWS. **Tecla**: INSERT+SPACE, X abre el asistente.
- **Comportamiento**: el usuario oculta zonas (anuncios, iframes, barras) y define dónde empieza la lectura de una página (por ejemplo, el primer H1 o la región main). Se guarda como regla por sitio y se aplica en cada visita.
- **Fuentes**: (vía buscador) https://blog.freedomscientific.com/flexible-web-clear-the-clutter-harness-the-power; https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-internet-web-browsing-hotkey-shortcuts (visitado).
- **Demanda**: MEDIA. **[AMPLÍA perfiles por sitio]**: lo nuevo es ocultar elementos y fijar el punto de inicio.

### 1.5 Navegación por artículos (tecla O)
- **Producto**: JAWS. **Teclas**: O / SHIFT+O; CTRL+INSERT+O lista los artículos.
- **Comportamiento**: salta entre elementos `<article>` y roles de feed, lo que permite recorrer publicaciones de Reddit, foros o redes sociales una a una.
- **Fuentes**: (vía buscador) comentario de un usuario de r/Blind recogido en el resumen de búsqueda: echaba de menos la O de JAWS en NVDA y dice que es "mucho más fiable". Issue #15687 "NVDA does not read the article element in Chromium-based browsers" (listado GitHub visitado).
- **Demanda**: MEDIA-ALTA entre usuarios que vienen de JAWS.

### 1.6 Estabilidad en feeds sociales (Facebook/Reddit)
- **Producto**: JAWS 2026, actualización de septiembre de 2026.
- **Comportamiento**: la tecla H recorre los posts de forma consistente y JAWS ya no salta el foco al hacer scroll infinito. Para Tiresias, la idea es mantener la posición en el búfer virtual cuando se carga contenido dinámico.
- **Fuente**: https://training.vispero.com/download-the-september-update-of-jaws-zoomtext-and-fusion-2026/ (visitado).
- **Demanda**: MEDIA. Es una queja clásica con el scroll infinito.

### 1.7 No leer la página automáticamente y anunciar sus estadísticas al cargar
- **Producto**: JAWS 2026, actualización de diciembre.
- **Comportamiento**: por defecto ya no empieza "Decir todo" al cargar una página. En su lugar anuncia el título y el número de regiones, encabezados y enlaces, y deja el foco arriba.
- **Opción**: Settings Center > Web/HTML/PDFs > Reading.
- **Fuente**: https://training.vispero.com/download-the-december-update-of-jaws-zoomtext-and-fusion-2026/ (visitado).
- **Demanda**: MEDIA. **[AMPLÍA resumen de página]**: lo nuevo es que el anuncio sea automático al cargar.

### 1.8 Pestañas (tabs ARIA) en la lista de elementos y con tecla rápida
- **Producto**: petición para NVDA.
- **Comportamiento**: añadir "Pestañas" a la lista de elementos (NVDA+F7) y una tecla rápida libre (se proponen j, y o z); al activarla se enfoca la pestaña y se muestra su panel.
- **Fuentes**: https://groups.google.com/a/nvaccess.org/g/nvda-users/c/4Lpr1jxqbo8/m/cB-NyAewCwAJ (visitado, mayo de 2026); issue #20245 (listado GitHub visitado).
- **Demanda**: MEDIA y reciente. Quentin Christensen (NV Access) la considera razonable.

### 1.9 Elementos clicables en la lista de elementos y tecla para recorrerlos
- **Producto**: petición para NVDA, issue #14429.
- **Comportamiento**: listar y saltar entre elementos con manejador de clic que no son enlaces ni botones (los típicos `<div>` clicables).
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA-MEDIA.

### 1.10 Listas de definiciones expuestas correctamente
- **Producto**: NVDA, issue #3858 (unas 31 reacciones o comentarios, el issue de tipo "feature" más votado).
- **Comportamiento**: anunciar `<dl>`, `<dt>` y `<dd>` como lista con términos y definiciones, con su número de elementos y navegación propia.
- **Fuente**: listado GitHub visitado.
- **Demanda**: ALTA dentro de GitHub.

### 1.11 Saltar al elemento controlado (aria-controls) y seguir el flujo (aria-flowto)
- **Producto**: VoiceOver Mac (VO-J salta al elemento enlazado); JAWS también admite aria-controls.
- **Peticiones para NVDA**: #8983 "Support for aria-controls" (unas 23); #4049 "ARIA Flowto regions are not announced or traversable in Browse Mode" (unas 20).
- **Comportamiento**: desde un botón, pestaña o combobox, una tecla lleva al panel que controla; flowto permite seguir el orden de lectura alternativo que define el autor.
- **Fuentes**: listado GitHub visitado; VO-J (vía buscador): https://support.apple.com/en-us/guide/voiceover/hear-hints-and-information-mchlp2701/10/mac/13.0
- **Demanda**: MEDIA.

### 1.12 Preguntar si continuar desde el principio cuando "Buscar" no encuentra más
- **Producto**: petición para NVDA, issue #4637 (unas 25).
- **Comportamiento**: al llegar al final sin más coincidencias, ofrecer "¿Buscar desde el principio?". Encaja con **[AMPLÍA navegación circular]**.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 1.13 Limitar la navegación por elementos de lista a la lista actual
- **Producto**: petición para NVDA, issue #8193 (unos 18 comentarios). Narrador ya tiene I / SHIFT+I para el siguiente o anterior elemento de lista en modo de exploración (febrero de 2025).
- **Comportamiento**: la tecla de "siguiente elemento de lista" no sale de la lista en la que estás; además, coma y punto saltan al inicio y al fin del contenedor.
- **Fuentes**: listado GitHub visitado; https://support.microsoft.com/en-us/windows/complete-guide-to-narrator-e4397a0d-ef4f-b386-d8ae-c172f109bdb1 (visitado).
- **Demanda**: MEDIA.

### 1.14 Anunciar líneas en blanco entre párrafos en modo exploración
- **Producto**: petición para NVDA, issue #19392.
- **Comportamiento**: al bajar línea a línea, decir "en blanco" donde hay separación visual, como hace JAWS. Útil para maquetar y revisar formato.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA.

### 1.15 Indicador de carga de página
- **Producto**: petición para NVDA, issue #16960.
- **Comportamiento**: un sonido o tono continuo mientras la página carga y un aviso al terminar.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA-MEDIA.

### 1.16 Señal sonora al llegar al límite
- **Producto**: petición para NVDA, issue #13612.
- **Comportamiento**: un sonido distinto cuando el cursor de revisión u objeto llega al borde (principio o fin) en lugar de repetir texto. **[AMPLÍA earcons]**.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA-MEDIA.

### 1.17 Anunciar maxlength y caracteres restantes en campos de texto
- **Producto**: petición para NVDA, issue #7910 (unas 15).
- **Comportamiento**: informar del máximo de caracteres de un campo (por ejemplo, "máximo 280") y opcionalmente cuántos quedan.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 1.18 Mostrar imágenes sin texto alternativo en todas las aplicaciones
- **Producto**: petición para NVDA, issue #7412 (unas 16).
- **Comportamiento**: opción para que las imágenes sin alt no se oculten, sino que se anuncien como "gráfico" con su nombre de archivo, para poder etiquetarlas o describirlas.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 1.19 Leer el texto alternativo en el idioma de la página
- **Producto**: petición para NVDA, issue #20254 (reciente).
- **Comportamiento**: aplicar el `lang` de la página o del elemento también a los atributos alt y aria-label. **[AMPLÍA detección de idioma]**.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA en entornos multilingües, como el español.

### 1.20 Otros detalles de ARIA y HTML pedidos en GitHub para NVDA
- abbr en `<th>` (#3566); aria-describedby en grupos en modo exploración (#12718, unas 22); anunciar cambios de aria-sort fuera del foco (#10890); elemento `<q>` (#14654); guiones blandos (#9343, unas 39); aria-braille* (#11829).
- **Fuente**: listados GitHub visitados.
- **Demanda**: MEDIA. Son detalles baratos de implementar que suman fidelidad.

### 1.21 Solo anunciar los encabezados de tabla al usar las teclas de tabla
- **Producto**: petición para NVDA, issue #4087. Relacionada: #1004, "tratar la primera fila o columna como encabezados".
- **Comportamiento**: no repetir encabezados al leer con flechas normales; sí al moverse con CTRL+ALT+flechas. Además, poder marcar manualmente la fila o columna de títulos, como hace JAWS con INSERT+ALT+CTRL+C y R.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

---

## 2. Voz, lectura continua y presentación de la información

### 2.1 Decir todo por frase o por párrafo, con velocidad y avance rápido durante la lectura
- **Producto**: JAWS. **Tecla**: INSERT+FLECHA ABAJO.
- **Comportamiento**:
  - Ajuste "Say All By": por líneas con o sin pausa, por frase o por párrafo.
  - Durante la lectura, RE PÁG y AV PÁG suben o bajan la velocidad solo para Decir todo.
  - FLECHA DERECHA avanza y FLECHA IZQUIERDA retrocede sin detener la lectura.
- **Fuente** (vía buscador): https://www.tpgi.com/how-jaws-reads-text; https://nelowvision.com/how-to-customize-jaws-screen-reader-for-maximum-efficiency-essential-settings-and-configuration-tips-for-enhanced-productivity/
- **Petición relacionada para NVDA**: #4944 "say all: adjust length of voice pauses for several text units".
- **Demanda**: MEDIA-ALTA. Es un hábito muy arraigado en quienes vienen de JAWS.

### 2.2 Speech on Demand (voz solo a petición)
- **Producto**: JAWS. **Tecla**: INSERT+SPACE, S.
- **Comportamiento**: solo habla con las órdenes explícitas de lectura (carácter, palabra o línea actual, título de ventana). Moverse con flechas o tabulador no habla. Pensado para usuarios de braille o de baja visión, y tiene opción de mantener o silenciar los sonidos.
- **Fuentes**: (vía buscador) https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-use-speech-on-demand-to-stop-jaws-speech; https://training.vispero.com/learn-more-do-more-new-features-in-jaws-toggle-jaws-sounds-in-speech-on-demand/
- **Demanda**: MEDIA. NVDA tiene "voz desactivada" o "pitidos", que no es lo mismo.

### 2.3 Voces por contexto
- **Producto**: JAWS.
- **Comportamiento**: voz, tono, velocidad y puntuación distintos para cada contexto: cursor del PC, cursor JAWS o de revisión, eco de teclado, mensajes y tutor, y menús y diálogos. Por defecto, el cursor JAWS usa la voz "Glen" con tono más grave. Permite saber de oído de dónde viene el texto.
- **Fuente** (vía buscador): https://www.nomensa.com/blog/how-to-configure-jaws-individual-voice-settings
- **Demanda**: MEDIA. Encaja muy bien con Eloquence, la voz por defecto de Tiresias, que tiene 8 voces.

### 2.4 Esquemas de voz y sonido
- **Producto**: JAWS, en el Speech and Sounds Manager.
- **Comportamiento**: perfiles que asignan voz o sonido a atributos (negrita, cursiva, color, enlaces, estados, tipos de control). Trae esquemas como "Classic" y "Proofreading (atributos y color)" y se cambian con una orden. En revisión de cambios, por ejemplo, las eliminaciones se leen con voz aguda y las inserciones con voz grave.
- **Fuentes**: (vía buscador) https://support.freedomscientific.com/SurfsUp/18-SpeechSoundsSchemes.htm; https://sastltd.zohodesk.eu/portal/en/kb/articles/configure-jaws-to-announce-font-colour-and-other-attributes; https://training.vispero.com/four-classic-jaws-features-that-can-transform-your-workflow/ (visitado).
- **Petición relacionada para NVDA**: #4089 "Trigger a Sound for Control Types and States".
- **Demanda**: MEDIA. **[AMPLÍA earcons]**: lo nuevo son los esquemas con nombre y la asignación de voces a atributos.

### 2.5 Personalizar el orden y la selección de propiedades anunciadas por tipo de control
- **Producto**: Narrador, enero de 2026. **Tecla**: Narrador+ALT+P.
- **Comportamiento**: para cada tipo de control (casilla, botón, deslizador...) el usuario elige qué propiedades oír (nombre, rol, estado, posición) y en qué orden, por ejemplo el estado antes que la etiqueta. En los PC Copilot+ se puede pedir en lenguaje natural, como "no anuncies la posición".
- **Petición para NVDA**: #7232 "Allow users to change the order in which object properties are reported in speech and braille" (unas 31).
- **Fuentes**: https://support.microsoft.com/en-us/windows/complete-guide-to-narrator-e4397a0d-ef4f-b386-d8ae-c172f109bdb1 (visitado); listado GitHub visitado.
- **Demanda**: ALTA. Es de las peticiones más votadas en GitHub y ya existe en Narrador.

### 2.6 Mensajes de tutor y pistas con retardo
- **Producto**: VoiceOver Mac (pistas tras un retardo; VO-SHIFT-H para oírlas); JAWS (tutor messages, como "para activar pulse espacio").
- **Comportamiento**: tras una pausa en un control, se dice cómo usarlo o su tooltip. El nivel se puede configurar (ninguno, solo los personalizados o todos).
- **Fuente** (vía buscador): https://support.apple.com/en-us/guide/voiceover/hear-hints-and-information-mchlp2701/10/mac/13.0
- **Demanda**: MEDIA, sobre todo para principiantes.

### 2.7 Descripciones de caracteres personalizables y retardo configurable
- **Producto**: peticiones para NVDA: #6811 "Customizable Character Descriptions" (unos 17); #13967 "Default time delay for Delayed descriptions ... is too long" (unas 27).
- **Comportamiento**: editar el alfabeto fonético (por ejemplo "a de Antonio" o "alfa"), definirlo por idioma y ajustar en milisegundos cuánto tarda la descripción diferida.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 2.8 Voz personal o clonada como voz del lector
- **Producto**: VoiceOver en macOS Sequoia. Personal Voice se puede usar como voz de VoiceOver.
- **Comportamiento**: el usuario graba frases y el sistema crea una voz local que el lector puede usar.
- **Fuente** (vía buscador): https://applevis.com/comment/174212
- **Demanda**: BAJA, aunque llamativa.

### 2.9 Cambio de tono al controlar un equipo remoto
- **Producto**: VoiceOver en macOS Tahoe.
- **Comportamiento**: cuando se controla otro Mac por Compartir pantalla, VoiceOver cambia de tono para que se sepa si se está en el equipo local o en el remoto. **[AMPLÍA acceso remoto]**.
- **Fuente** (vía buscador): https://www.applevis.com/blog/macos-tahoe-new-features-changes-improvements-bugs-blind-deafblind-low-vision-users
- **Demanda**: BAJA-MEDIA.

### 2.10 Anunciar cortar, copiar y pegar
- **Producto**: JAWS anuncia las operaciones del portapapeles de Windows. Petición para NVDA: #19042 "Have NVDA announce cut, copy, paste actions" (unos 35 comentarios, tercera en debate).
- **Comportamiento**: decir "copiado", "cortado" o "pegado", opcionalmente con un resumen del texto. **[AMPLÍA historial del portapapeles]**: lo nuevo es la confirmación hablada.
- **Fuente**: listado GitHub visitado.
- **Demanda**: ALTA en GitHub.

### 2.11 Visor de voz con tamaño de letra ajustable
- **Producto**: petición para NVDA, issue #8388. Narrador tiene una ventana de transcripción en vivo (Speech recap, Narrador+ALT+X) pensada para formadores y personas con hipoacusia.
- **Fuentes**: listado GitHub visitado; https://support.microsoft.com/en-us/windows/complete-guide-to-narrator-e4397a0d-ef4f-b386-d8ae-c172f109bdb1 (visitado).
- **Demanda**: BAJA (formadores).

---

## 3. Ofimática y edición

### 3.1 Text Analyzer (revisión de incoherencias)
- **Producto**: JAWS. **Teclas**: ALT+WINDOWS+I para la siguiente incoherencia (con SHIFT, la anterior); INSERT+SPACE, A activa "describir todas las incoherencias".
- **Comportamiento**: avisa con voz o sonido de paréntesis o comillas sin cerrar, espacios dobles, espacios antes de puntuación, cambios de formato incoherentes y mayúsculas raras, en cualquier editor o web. Es más que el corrector ortográfico.
- **Fuentes** (vía buscador): https://training.vispero.com/proof-documents-faster-and-more-efficiently-with-jaws-text-analyzer/; https://aph.org/access-academy-handouts/jaws-text-analyzer-resource; https://training.vispero.com/four-classic-jaws-features-that-can-transform-your-workflow/ (visitado).
- **Demanda**: MEDIA. Los usuarios señalan falsos positivos cuando un paréntesis se cierra en la línea siguiente.

### 3.2 Listas de errores ortográficos, revisiones y comentarios en Word
- **Producto**: JAWS.
- **Teclas**:
  - ALT+SHIFT+L: lista de errores ortográficos.
  - INSERT+F7: palabra mal escrita y sugerencia.
  - INSERT+SHIFT+R: revisiones (control de cambios).
  - CTRL+SHIFT+APÓSTROFO: lista de comentarios.
  - WINDOWS+PUNTO Y COMA: visor virtual de comentarios, notas al pie y revisiones.
- **Comportamiento**: diálogos de lista que llevan a cada error, cambio o comentario.
- **Fuente** (vía buscador): https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkey-shortcuts-for-microsoft-word
- **Demanda**: ALTA en el ámbito laboral. **[AMPLÍA módulos de Office]**.

### 3.3 Tratar viñetas y numeraciones de Word como listas
- **Producto**: petición para NVDA, issue #7742 (unos 18 comentarios). Narrador lo incorporó en octubre de 2025 (anuncia las listas y navega por elementos con CTRL+FLECHA ARRIBA o ABAJO).
- **Fuentes**: listado GitHub visitado; guía de Narrador visitada.
- **Demanda**: MEDIA.

### 3.4 Excel: celdas vigiladas, títulos de fila y columna, filas completas
- **Producto**: JAWS.
- **Teclas**:
  - ALT+CTRL+SHIFT+1 a 6: definir celdas vigiladas.
  - CTRL+SHIFT+M: listarlas.
  - INSERT+ALT+SHIFT+C y R: decir el título de columna y de fila.
  - INSERT+ALT+CTRL+C y R: definir la fila o columna de títulos.
  - Rangos con nombre "ColumnTitle" y "RowTitle" para lectura automática.
  - INSERT+SHIFT+V (JAWS 2026): ver el contenido de una celda multilínea en el visor virtual.
- **Peticiones para NVDA**: #901 "[Excel] read entire row/column"; #20383 "whole column or row selected".
- **Fuentes**: (vía buscador) https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkeys-for-microsoft-excel; https://sastltd.zohodesk.eu/portal/en/kb/articles/setting-jaws-to-automatically-read-excel-column-and-row-titles; https://nelowvision.com/low-vision-software-updates-for-2025/ (visitado); listado GitHub visitado.
- **Demanda**: ALTA en el trabajo.

### 3.5 Títulos de fila y columna en Google Docs y Sheets
- **Producto**: JAWS 2026, actualización de marzo. Las mismas órdenes, INSERT+ALT+SHIFT+C y R, funcionan en Google Workspace.
- **Fuente**: https://training.vispero.com/download-the-march-update-of-jaws-zoomtext-and-fusion-2026/ (visitado).
- **Demanda**: MEDIA (educación).

### 3.6 PowerPoint: leer en modo presentación y aviso de ecuaciones
- **Producto**: JAWS 2026, actualización de agosto.
- **Comportamiento**: al pulsar F5 lee el contenido de la diapositiva en curso. Si una diapositiva contiene ecuaciones lo indica, y con INTRO las abre en el Math Viewer.
- **Fuente**: https://training.vispero.com/download-the-august-update-of-jaws-zoomtext-and-fusion-2026/ (visitado).
- **Petición relacionada para NVDA**: #17605 (se sigue leyendo la diapositiva vieja al presentar).
- **Demanda**: MEDIA.

### 3.7 Virtual Ribbon (cinta como menú clásico)
- **Producto**: JAWS (se activa en Quick Settings buscando "Ribbon").
- **Comportamiento**: presenta la cinta de Office como menús jerárquicos: ALT entra, FLECHAS ARRIBA y ABAJO recorren los grupos, INTRO entra en un grupo y ESC sale.
- **Fuente** (vía buscador): https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-navigating-the-microsoft-office-ribbon-menu
- **Demanda**: BAJA-MEDIA (usuarios veteranos).

### 3.8 Leer la barra de estado, incluido el estado de los conmutadores
- **Producto**: Narrador, marzo de 2026, con Narrador+\. Petición para NVDA: #5687 "Report status bar should report state of toggles".
- **Fuentes**: guía de Narrador visitada; listado GitHub visitado.
- **Demanda**: BAJA. NVDA+FIN ya existe, pero la petición es sobre el estado de los conmutadores.

### 3.9 Outlook: leer las cabeceras del mensaje con ALT+1 a 6 y acceder a los adjuntos con INSERT+A
- **Producto**: JAWS 2026.
- **Fuente**: https://nelowvision.com/low-vision-software-updates-for-2025/ (visitado).
- **Demanda**: MEDIA. **[AMPLÍA módulos de Office]**.

### 3.10 Ajustar el orden de lectura de los PDF
- **Producto**: JAWS. Webinar de septiembre de 2026: ajustar el orden de lectura, saltar a una página, formularios y tablas, y generar alt para imágenes del PDF.
- **Fuente**: https://training.vispero.com/learn-how-to-work-more-effectively-with-pdfs-and-jaws/ (visitado).
- **Demanda**: ALTA. Según WebAIM n.º 11, el 85,6 % tiene problemas con los PDF. Idea para Tiresias: reordenar por columnas o con heurística o IA cuando el PDF no está etiquetado.

---

## 4. Sistema, configuración y productividad

### 4.1 Teclas por capas
- **Producto**: JAWS. **Tecla**: INSERT+SPACE y después una letra que abre una "capa".
- **Comportamiento**: capas como O (OCR), P (Picture Smart), V (volumen y sonido), T (tablas), F (Face in View), H (historial), C (portapapeles), S (voz a petición), X (Flexible Web), R (Research It) y F1 (Companion). Dentro de cada capa, "?" lista sus órdenes. Libera combinaciones de teclas y se puede descubrir sin memorizar.
- **Fuentes**: (vía buscador) https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-using-layered-keystrokes-to-access-features; https://bits-acb.org/bits-member-content/basics-with-bits-fs-companion-and-layered-keystrokes-for-april-11-2026/; Dolphin también usa capas (CAPS LOCK+SPACE).
- **Demanda**: MEDIA-ALTA. Es una solución estructural a la escasez de atajos (NVDA #20245 menciona que faltan letras). **[Distinto de la paleta de órdenes]**.

### 4.2 Quick Settings y Settings Center con búsqueda
- **Producto**: JAWS. **Teclas**: INSERT+V para Quick Settings y INSERT+F6 para Settings Center.
- **Comportamiento**: ambos tienen un cuadro de búsqueda: se escribe "ribbon" o "puntuación" y el árbol se filtra hasta la opción, que se cambia con ESPACIO. Los ajustes pueden ser por aplicación.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkeys (visitado); https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-navigating-the-microsoft-office-ribbon-menu (vía buscador).
- **Demanda**: MEDIA. El diálogo de opciones de NVDA no tiene búsqueda.

### 4.3 Research It (consultas rápidas)
- **Producto**: JAWS. **Teclas**: INSERT+SPACE, R; INSERT+WINDOWS+R usa la fuente principal.
- **Comportamiento**: consulta la palabra o frase actual o escrita (diccionario, Wikipedia, tiempo, noticias, bolsa, deportes) y muestra el resultado en un visor de resultados accesible.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkeys (visitado); descripción (vía buscador) en https://www.freedomscientific.com/training/jaws/frequently-asked-questions/
- **Demanda**: BAJA-MEDIA.

### 4.4 Historial de notificaciones con reglas
- **Producto**:
  - JAWS (Notification History Manager, en la capa INSERT+SPACE, N; 2023 añadió reglas con expresiones regulares; se guarda en Notification.rules.json).
  - Dolphin SuperNova 25.01 (Notification Finder: CAPS LOCK+SPACE, F3).
  - TalkBack 16 (en braille: mostrar los toasts y notificaciones, cerrarlos con el punto 8 y revisar las perdidas).
- **Comportamiento**: guarda todas las notificaciones de Windows para revisarlas después. Las reglas permiten silenciarlas, cambiar cómo se anuncian o solo registrarlas según la aplicación o el texto.
- **Fuentes**: (vía buscador) https://sastltd.zohodesk.eu/portal/en/kb/articles/manually-reset-jaws-notification-history-or-rules; https://blog.freedomscientific.com/fscast-216-a-demo-of-the-new-jaws-notification-history-manager-and-a-visit-with-richard-oehm; https://yourdolphin.com/product/version?id=640 (visitado); https://support.google.com/accessibility/android/answer/16294093 (visitado).
- **Demanda**: ALTA. Está en tres competidores; NVDA solo lo tiene mediante complementos.

### 4.5 Vigilar regiones u objetos
- **Producto**: Dolphin ("monitor markers" para notificaciones, descargas y mensajería); JAWS (celdas vigiladas, frames). Petición para NVDA: #498 "Add ability to bookmark objects, and monitor them for changes" (unas 12).
- **Comportamiento**: el usuario marca un objeto o una región de pantalla y el lector anuncia sus cambios aunque el foco esté en otro sitio, por ejemplo el progreso de una descarga, un contador o un chat.
- **Fuentes**: https://yourdolphin.com/ScreenReader/Features (visitado); listado GitHub visitado.
- **Demanda**: MEDIA-ALTA.

### 4.6 Asistente de voz para manejar el lector
- **Producto**: JAWS Voice Assistant, "Hey Sharky". También se activa con INSERT+ALT+SPACE.
- **Comportamiento**: órdenes habladas como "qué hora es", "fecha", "bandeja del sistema", "lista de ventanas", "batería", "cambiar ajustes de voz" o "reiniciar JAWS". Viene desactivado por defecto y se activa en Utilidades.
- **Fuente** (vía buscador): https://www.freedomscientific.com/?p=12896; https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-information-on-using-voice-assistant (visitado, solo enlaces).
- **Relacionado**: Narrador se integra con Acceso por voz para dictar y dar órdenes (febrero de 2024, guía visitada).
- **Demanda**: BAJA-MEDIA (movilidad reducida y principiantes).

### 4.7 Asistente de IA sobre el propio lector y las aplicaciones
- **Producto**:
  - JAWS FSCompanion, renombrado Vispero Companion en marzo de 2026. **Tecla**: INSERT+SPACE, F1; se abre en el Results Viewer.
  - Dolphin "AI Help".
- **Comportamiento**: preguntas en lenguaje natural ("¿cómo acepto los cambios en Word con JAWS?") y respuesta con pasos y atajos concretos sacados de la documentación.
- **Fuentes**: https://training.vispero.com/download-the-december-update-of-fusion-suite-2025/ (visitado); https://nelowvision.com/low-vision-software-updates-for-2025/ (visitado); https://yourdolphin.com/ScreenReader/Features (visitado).
- **Demanda**: MEDIA y creciente. **[AMPLÍA tutorial]**: lo nuevo es la ayuda en lenguaje natural.

### 4.8 Agente de IA que ejecuta tareas
- **Producto**: JAWS/Fusion, anunciado en el FSCast n.º 268 (marzo de 2026) "para el verano de 2026".
- **Comportamiento**: el agente usa primitivas (enfocar, escribir, hacer clic, navegar) sobre el árbol de accesibilidad más una captura de pantalla. Tiene un botón de parada de emergencia y pide confirmación humana antes de las acciones arriesgadas.
- **Fuentes**: https://training.vispero.com/wp-content/uploads/2026/04/FSCast268-march2026Transcript.htm (visitado); (vía buscador) https://training.vispero.com/vispero-connect-june-2026-product-updates-agentic-ai-and-the-corporate-side-of-accessibility/
- **Demanda**: emergente.

### 4.9 Cuentas y sincronización de ajustes en la nube
- **Producto**: JAWS 2026. Cloud Settings Sync está en el Early Adopter Program; desde septiembre de 2026 también sincroniza las voces Vocalizer y muestra el estado de sincronización en la línea de estado.
- **Comportamiento**: los atajos, ajustes y configuración de braille te acompañan a cualquier equipo donde inicies sesión.
- **Fuentes**: https://training.vispero.com/download-the-september-update-of-jaws-zoomtext-and-fusion-2026/ (visitado); (vía buscador) https://blog.freedomscientific.com/whats-new-in-jaws-zoomtext-and-fusion-2026/
- **Demanda**: MEDIA. Hubo quejas porque la cuenta obligatoria se impuso con prisas (FSCast n.º 268). Para Tiresias, mejor una sincronización opcional, por ejemplo con un archivo en OneDrive o Dropbox. **[AMPLÍA modo portátil]**.

### 4.10 Mapa de teclas que emula a JAWS
- **Producto**: Dolphin SuperNova (conjuntos que emulan JAWS en versión de sobremesa y de portátil, más ZoomText y Fusion).
- **Comportamiento**: se cambia el juego de atajos completo para que quien viene de JAWS conserve su memoria muscular.
- **Fuente**: https://kb.yourdolphin.com/knowledge/jaws-emulation-hotkey-set (visitado).
- **Demanda**: MEDIA-ALTA. Según WebAIM n.º 11, JAWS es el lector principal del 55 %, así que hay mucha migración posible.

### 4.11 Tecla modificadora personalizada
- **Producto**: petición para NVDA, issue #16607.
- **Comportamiento**: poder usar cualquier tecla como modificador del lector, no solo INSERT o BLOQ MAYÚS.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA-MEDIA.

### 4.12 Detectar conflictos de atajos y filtrar los atajos personalizados
- **Producto**: peticiones para NVDA:
  - #15242: avisar de colisiones de gestos entre complementos al cargarlos (unas 21).
  - #4900: filtrar en el diálogo de gestos los que están personalizados.
  - #18872: decir el nombre del complemento en la ayuda de entrada.
  - #7074: localizar una orden pulsando sus teclas (unos 18).
- **Fuente**: listados GitHub visitados.
- **Demanda**: MEDIA. NVDA 2026.3 mejoró el diálogo de gestos, pero estas peticiones siguen abiertas.

### 4.13 Modo corporativo o administrado
- **Producto**: petición para NVDA, issue #16599 (unos 22 comentarios).
- **Comportamiento**: configuración bloqueada o impuesta por el administrador (complementos permitidos, sin actualizaciones automáticas, política centralizada). En AppleVis se cita que las empresas prefieren JAWS porque el sistema abierto de complementos choca con su política de seguridad.
- **Fuentes**: listado GitHub visitado; (vía buscador) https://applevis.com/comment/172143
- **Demanda**: MEDIA. Es clave para entrar en empresas y en la administración.

### 4.14 Arrancar el lector en la pantalla de inicio de sesión con una tecla
- **Producto**: petición para NVDA, issue #3868 (unos 11). También #17210, arrancar con los complementos desactivados mediante un atajo.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 4.15 Anunciar la semana laboral
- **Producto**: JAWS 2026. **Tecla**: CTRL+INSERT+F12 pulsado dos veces.
- **Fuente**: https://nelowvision.com/low-vision-software-updates-for-2025/ (visitado).
- **Demanda**: BAJA. Es trivial de implementar.

### 4.16 Soporte específico para aplicaciones nuevas de Windows 11
- **Producto**: Dolphin SuperNova 25.01 añadió lectura y ampliación de la barra de Acceso por voz, de la app Copilot y de la Herramienta Recortes. También admite WinSCP, REAPER y Microsoft 365 Remote Console (25.02).
- **Fuentes**: https://yourdolphin.com/product/version?id=640 (visitado); https://yourdolphin.com/product/version?id=652 (visitado).
- **Demanda**: MEDIA. Windows 11 cambió el menú Inicio, el Explorador y Configuración, y hay usuarios a los que les cuesta (vía buscador: https://www.blindcanadians.ca/post/making-the-switch-to-windows-11).

### 4.17 Copia portátil en carpetas con versión y copiando los complementos
- **Producto**: peticiones para NVDA: #18953 (carpetas con número de versión; unos 27 comentarios) y #2467 (copiar los complementos instalados).
- **Fuente**: listados GitHub visitados.
- **Demanda**: BAJA-MEDIA. **[AMPLÍA modo portátil]**.

---

## 5. Ratón, pantalla, táctil y exploración espacial

### 5.1 Mouse Echo (leer lo que hay bajo el ratón)
- **Producto**: JAWS, en Settings Center > Mouse Echo; ZoomText y Fusion. Dolphin ("Read Text Under Mouse").
- **Comportamiento**: al mover el ratón lee el texto que hay debajo. Se puede configurar la unidad (palabra, línea o párrafo) y el retardo. NVDA tiene seguimiento del ratón, pero con menos opciones.
- **Fuente** (vía buscador): https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-enable-mouse-echo
- **Demanda**: BAJA-MEDIA (baja visión).

### 5.2 Mover el ratón al seguir la revisión plana
- **Producto**: petición para NVDA, issue #788 (unas 17).
- **Comportamiento**: opción para que el puntero acompañe siempre al cursor de revisión, de modo que se pueda hacer clic directamente. JAWS lo hace con su cursor JAWS.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA. **[AMPLÍA Golden Cursor]**.

### 5.3 Touch Cursor
- **Producto**: JAWS. **Tecla**: SHIFT+NUM PAD PLUS.
- **Comportamiento**: recorre los elementos de UI Automation en orden espacial con las flechas, como el táctil de una tableta pero desde el teclado. Sirve en aplicaciones modernas sin foco lógico.
- **Fuente**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-hotkeys (visitado).
- **Demanda**: BAJA.

### 5.4 Comandos con el touchpad
- **Producto**: VoiceOver Mac (Trackpad Commander, gestos de uno a varios dedos sobre el trackpad). Petición para NVDA: #3358 "Add the ability to use a Multitouch trackpad" (unas 17).
- **Comportamiento**: usar el touchpad de precisión del portátil como pantalla táctil virtual o con gestos asignables (deslizar para el siguiente elemento, rotor, etc.).
- **Fuentes**: (vía buscador) https://applevis.com/guides/voiceover-gestures-use-multi-touch-trackpad-macos; listado GitHub visitado.
- **Demanda**: MEDIA. En AppleVis se dice que los gestos táctiles de NVDA son mediocres comparados con los de Narrador (https://atlas-entry.applevis.com/comment/188478, visitado).

### 5.5 Buscar texto en pantalla en cualquier aplicación
- **Producto**: TalkBack (Screen search, en el menú de TalkBack); Dolphin (Find con el Dolphin Cursor); JAWS (buscar con el cursor JAWS).
- **Comportamiento**: buscar una cadena en todo lo visible de la ventana actual (no solo en documentos o en modo exploración) y llevar allí el cursor de revisión o el foco.
- **Fuentes**: https://support.google.com/accessibility/android/answer/6007066?hl=en (vía buscador); https://yourdolphin.com/ScreenReader/Features (visitado).
- **Demanda**: MEDIA.

### 5.6 Leer aplicaciones sin modelo de pantalla
- **Producto**: JAWS Scan Cursor, desde 2020, para aplicaciones donde no funciona el modelo de pantalla fuera de la vista (OSM). Petición para NVDA: #19390 "Improve Display Model (GDI Hooking) to support graphics/symbols and undetected text in legacy apps" (unas 11).
- **Comportamiento**: un cursor de revisión que trabaja sobre una "lectura" de la pantalla cuando ni UIA ni GDI ofrecen texto.
- **Fuentes**: (vía buscador) https://training.vispero.com/learn-more-do-more-new-features-in-jaws-the-jaws-scan-cursor/; hilo visitado https://atlas-entry.applevis.com/forum/windows/jaws-question-jaws-scan-cursor (usuarios de ProTranscribe y Surfshark se quejan de que el Scan Cursor se rompió en JAWS 2025 y 2026); listado GitHub visitado.
- **Demanda**: MEDIA (aplicaciones heredadas y profesionales).

### 5.7 Sonificación de imágenes
- **Producto**: complemento AudioScreen para NVDA (NV Access, Michael Curran).
- **Comportamiento**: al pasar el dedo o el ratón por una imagen se oyen tonos. En el modo HSV, el tono indica el color (del azul grave al rojo agudo) y el volumen el brillo. Permite explorar gráficos y fotos espacialmente.
- **Fuentes** (vía buscador): https://www.nvaccess.org/audioScreen/; https://groups.google.com/a/nvaccess.org/g/nvda-users/c/eCk_MPa2boM (aviso de 2026 sobre el complemento).
- **Demanda**: BAJA, aunque es única y de bajo coste.

### 5.8 Explorar una imagen por zonas
- **Producto**: VoiceOver iOS (Image Explorer y reconocimiento de pantalla). TalkBack (Describe image con preguntas de seguimiento).
- **Comportamiento**: tras describir la imagen, se pueden recorrer los objetos detectados con su posición ("arriba a la izquierda: una taza").
- **Fuente** (vía buscador): https://mcmw.abilitynet.org.uk/how-to-use-voiceover-the-screen-reader-in-ios-26-on-your-iphone-or-ipad
- **Demanda**: BAJA-MEDIA. **[AMPLÍA descripción con IA]**.

### 5.9 Atajo para activar o desactivar el resaltado visual
- **Producto**: petición para NVDA, issue #11405 (unas 11).
- **Comportamiento**: una tecla para encender o apagar el resaltado del foco y del navegador. Útil para formadores y usuarios con resto visual.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA.

### 5.10 Clic derecho desde el cursor de revisión
- **Producto**: petición para NVDA, issue #3987. JAWS lo hace con el cursor JAWS y NUM PAD *.
- **Fuente**: listado GitHub visitado.
- **Demanda**: BAJA.

---

## 6. OCR, visión e IA (solo la parte no cubierta)

### 6.1 OCR continuo o en segundo plano que lee solo lo que cambia
- **Producto**:
  - JAWS Background OCR. Desde diciembre de 2025, INSERT+SPACE, O, INTRO es contextual: en YouTube o en una pantalla compartida de Teams o Zoom activa el OCR en segundo plano y deja el cursor invisible sobre el vídeo o la diapositiva.
  - Complemento LION para NVDA (NVDA+ALT+L): OCR periódico de una zona que solo lee el texto nuevo.
- **Uso**: subtítulos incrustados de vídeo y streaming, juegos inaccesibles y diapositivas compartidas.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-changes-to-convenient-ocr-in-2025-product (visitado); https://afb.org/blog/entry/accessworld-classics-editors-list-essential-nvda-addons (visitado); LION (vía buscador): https://forum.audiogames.net/post/512280/
- **Demanda**: ALTA. LION es uno de los cuatro complementos "esenciales" de AccessWorld. **[AMPLÍA OCR multimotor]**: lo nuevo es el modo continuo con diferencias y el contexto automático.

### 6.2 OCR contextual en una sola tecla y salidas especiales
- **Producto**: JAWS Convenient OCR, con la capa INSERT+SPACE, O:
  - A: cámara o escáner (PEARL o escáner plano).
  - F: archivo de imagen seleccionado.
  - D: el PDF abierto.
  - R: de imagen a documento de Word.
  - W: ventana.
  - S: pantalla completa.
  - C: control.
  - Q: cancelar.
  - ?: ayuda.
- **Fuente**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-convenient-ocr-layered-hotkeys (visitado).
- **Demanda**: MEDIA. Lo nuevo frente al estudio anterior es la entrada desde escáner o cámara, la salida a Word o .txt y el reconocimiento de PDF desde el explorador.

### 6.3 Etiquetado automático con IA (AI Labeler)
- **Producto**: JAWS 2026, ya activo por defecto.
- **Teclas**: INSERT+G etiqueta o propone una etiqueta para un gráfico o control. CTRL+INSERT+TAB o INSERT+SPACE, ALT+L abren el Label Manager.
- **Comportamiento**: nombra automáticamente más del 90 % de los botones, enlaces y gráficos sin etiqueta. Desde diciembre genera descripciones de una o dos frases y guarda la etiqueta para futuras visitas.
- **Fuentes**: https://training.vispero.com/download-the-july-update-of-fusion-suite-2025/ (visitado); https://training.vispero.com/download-the-december-update-of-jaws-zoomtext-and-fusion-2026/ (visitado); (vía buscador) https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-using-ai-labeler-for-poorly-labeled-elements-early-adopter-program
- **Petición relacionada para NVDA**: #17332 "Object Labeler Functionality" (unas 11).
- **Demanda**: ALTA. **[AMPLÍA etiquetas personalizadas]**: lo nuevo es la sugerencia automática con IA.

### 6.4 Comprobar la posición de la cara antes de una videollamada
- **Producto**:
  - JAWS Face in View. **Teclas**: INSERT+SPACE, F, O activa; F, D descripción detallada; F, L brillo; F, P fondo; F, C cambiar de cámara; F, U confianza.
  - Dolphin Face Position (SuperNova 25.04). **Teclas**: CAPS LOCK+SPACE, Q, P; ALT+P posición; ALT+D distancia; ALT+L luz; ALT+B fondo; CTRL+S guardar foto; campo "Ask AI".
- **Comportamiento**: vigila con la cámara si la cara está centrada, la distancia y la luz, y avisa si te inclinas o baja la luz. No funciona durante la llamada porque necesita la cámara.
- **Fuentes**: (vía buscador) https://vi.ie/use-jaws-to-stay-in-the-centre-of-your-video-calls/; https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-face-in-view-hotkeys; https://yourdolphin.com/product/version?id=667 (visitado).
- **Demanda**: MEDIA. Teletrabajo; dos competidores ya la tienen.

### 6.5 Reconocimiento en vivo con la cámara
- **Producto**: VoiceOver iOS 18 y 26 (Live Recognition: personas, puertas, texto, muebles, escenas).
- **Comportamiento**: en Windows sería con la webcam: describir lo que tiene delante (un documento en papel, un objeto). Encaja con la entrada de cámara del OCR.
- **Fuente** (vía buscador): https://www.afb.org/blog/entry/ios-26-accessibility-features
- **Demanda**: BAJA en escritorio.

### 6.6 Explorar la página con IA y hacer preguntas de seguimiento
- **Producto**: JAWS 2026 Page Explorer. **Tecla**: INSERT+SHIFT+E.
- **Comportamiento**: resumen con IA del contenido, del diseño visual y consejos para navegar la página; después se pueden hacer preguntas de seguimiento. Según Vispero, permite moverse "hasta un 25 % más rápido" por aplicaciones web complejas.
- **Fuentes**: (vía buscador) https://blog.freedomscientific.com/whats-new-in-jaws-zoomtext-and-fusion-2026/; https://training.vispero.com/wp-content/uploads/2026/04/FSCast268-march2026Transcript.htm (visitado).
- **Demanda**: ALTA. WebAIM n.º 11: el 37,1 % usa IA para resumir páginas. **[AMPLÍA resumen de página]**: lo nuevo es el mapa de diseño y las preguntas de seguimiento.

---

## 7. Braille y sordoceguera

### 7.1 Split Braille (línea braille dividida)
- **Producto**: JAWS 2024. **Tecla**: ALT+INSERT+V abre "Select Braille View" (en la Focus, SHIFT IZQUIERDO+puntos 1-2-7).
- **Comportamiento**: divide la línea braille en dos regiones con una doble barra en medio: a la izquierda la posición actual y a la derecha otra vista. Vistas disponibles:
  - texto en búfer;
  - anotaciones;
  - indicadores de atributos;
  - historial de voz;
  - traducción;
  - cursor JAWS;
  - texto de la ventana;
  - vistas propias de Excel, Outlook, PowerPoint y Teams.
- **Fuentes** (vía buscador): https://blog.freedomscientific.com/join-us-for-an-in-depth-look-at-the-split-braille-feature-in-jaws; https://nelowvision.com/software-updates-for-jaws-zoomtext-and-fusion-2024/
- **Demanda**: MEDIA (usuarios de braille avanzados).

### 7.2 Braille multilínea y gráficos táctiles
- **Producto**: JAWS 2026 (soporte multilínea); Monarch de APH (10 líneas de 32 celdas); Dot Pad X. JAWS y NVDA ya los admiten como texto, pero no como gráficos.
- **Comportamiento**: mostrar varias líneas a la vez (tablas, código) y, en el futuro, gráficos táctiles de imágenes o diagramas.
- **Fuentes** (vía buscador): https://www.aph.org/blog/a-historic-leap-monarch-gains-multiline-screen-reader-support-and-premieres-first-public-ebraille-book/; https://media.aph.org/app/uploads/2026/02/Major-Monarch-Update-Unlocks-Most-Requested-Features-2.3.26.pdf; https://doubletaponair.com/page-explorer-ai-labeller-inside-jaws-2026s-smartest-tools-2/
- **Demanda**: MEDIA y creciente (educación).

### 7.3 Indicar la selección con los puntos 7 y 8
- **Producto**: petición para NVDA, issue #1953 (unas 16).
- **Comportamiento**: subrayar con los puntos 7 y 8 el elemento seleccionado en listas, menús y texto seleccionado.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA entre usuarios de braille.

### 7.4 Descripción braille de los emojis
- **Producto**: petición para NVDA, issue #9213 (unas 18).
- **Comportamiento**: mostrar en braille el nombre del emoji ("cara sonriente") en lugar de un símbolo ilegible.
- **Fuente**: listado GitHub visitado.
- **Demanda**: MEDIA.

### 7.5 Mensajes del sistema en braille con historial
- **Producto**: TalkBack 16.
- **Comportamiento**: los toasts y notificaciones aparecen en la línea braille; el punto 8 o un pulsador de enrutamiento los cierra, y ESPACIO+puntos 1-3-4-5-7-8 abre los que se perdieron. **[Combina con 4.4]**.
- **Fuente**: https://support.google.com/accessibility/android/answer/16294093 (visitado).
- **Demanda**: MEDIA.

### 7.6 Transcripción en vivo de una conversación a braille (sordociegos)
- **Producto**: iOS 26 Braille Access (transcripciones en tiempo real en la línea braille, archivos BRF, cálculo en Nemeth).
- **Comportamiento**: en Windows sería captar el micrófono o el audio del sistema, por ejemplo con Live Captions o reconocimiento de voz, y enviar el texto a la línea braille en tiempo real.
- **Fuentes** (vía buscador): https://www.helenkeller.org/ios-26-braille-access/; https://www.afb.org/blog/entry/ios-26-accessibility-features
- **Demanda**: BAJA en número, pero crítica para las personas sordociegas.

### 7.7 Línea braille HID sin controladores
- **Producto**: Narrador (mayo de 2026, conectar por USB y usar sin configurar); Dolphin 25.04 (controlador "USB Braille Standard (HID)").
- **Fuentes**: (vía buscador) https://blogs.windows.com/windows-insider/2026/05/22/announcing-new-builds-for-22-may-2026/; https://yourdolphin.com/product/version?id=667 (visitado).
- **Demanda**: MEDIA. NVDA ya tiene soporte HID; Tiresias lo heredaría si clona los controladores de NVDA.

---

## 8. Reuniones y comunicación

### 8.1 Modos de alerta en reuniones de Zoom o Teams
- **Producto**: complemento Zoom Accessibility Enhancements para NVDA. **Tecla**: NVDA+SHIFT+A cicla entre "todas", "pitido", "silencio" y "personalizado".
- **Comportamiento**: atajos para activar o desactivar cada tipo de aviso: entra o sale un participante, sala de espera, te silencia el anfitrión, compartir pantalla, grabación, chat público o privado, manos levantadas, control remoto...
- **Fuente** (vía buscador): https://addons.nvda-project.org/addons/zoomEnhancements.ar.html; https://www.perkins.org/resource/nvda-zoom-accessibility-add/
- **Demanda**: MEDIA-ALTA (teletrabajo). **[AMPLÍA módulos de aplicación de Teams]**.

### 8.2 Leer los últimos N mensajes de cualquier chat con ALT o CTRL más un número
- **Producto**: scripts de Doug Lee para JAWS (Adobe Connect: ALT+1 el más reciente, ALT+2 el anterior...); complemento de Skype para NVDA (CTRL+0 a 9; doble pulsación para copiar). Petición antigua para NVDA: #640, "búferes de mensajes por ventana".
- **Comportamiento**: genérico para cualquier aplicación de chat: guardar los últimos mensajes recibidos por ventana y leerlos con ALT+1 a 0 sin mover el foco.
- **Fuentes**: (vía buscador) https://dlee.org/teams/; https://github.com/Neurrone/nvda-skype; listado GitHub visitado.
- **Demanda**: MEDIA.

### 8.3 OCR de la pantalla compartida en reuniones
- **Producto**: JAWS. INSERT+SPACE, O, INTRO en Teams o Zoom activa el OCR en segundo plano sobre lo compartido; Picture Smart describe la pantalla compartida en Zoom.
- **Fuentes**: https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-changes-to-convenient-ocr-in-2025-product (visitado); https://training.vispero.com/download-the-december-update-of-fusion-suite-2025/ (visitado).
- **Demanda**: MEDIA-ALTA. **[Combina con 6.1]**.

---

## 9. Libros, documentos largos y multimedia

### 9.1 EPUB: navegar por regiones y saltos de página
- **Producto**: JAWS 2026.
- **Teclas**: R / SHIFT+R recorren más de 20 tipos de región (capítulo, apéndice, glosario...). GUION salta entre los separadores de página y anuncia "página N".
- **Fuente**: https://nelowvision.com/low-vision-software-updates-for-2025/ (visitado).
- **Demanda**: MEDIA (estudiantes). Thorium ofrece navegación por páginas impresas y un "dónde estoy" con la ruta de encabezados (vía buscador: https://daisy.org/info-help/guidance-training/reading-systems/thorium-epub-reader-quick-start-guide).

### 9.2 Lector de libros y servicios de audiolibros integrado
- **Producto**: Dolphin, con EasyReader incluido: más de 40 servicios de libros hablados, DAISY, sincronización Windows/iOS/Android, radio, pódcast y RSS. System Access también integraba servicios de este tipo.
- **Fuente**: https://yourdolphin.com/ScreenReader/Features (visitado).
- **Demanda**: BAJA-MEDIA. En España, la integración con la biblioteca de la ONCE o con Tiflolibros sería un elemento diferenciador (sin fuente directa de demanda; es una inferencia).

### 9.3 Lectura en segundo plano
- **Producto**: ZoomText y Fusion (Background Reader).
- **Comportamiento**: se selecciona un texto y, con un atajo, se lee mientras se trabaja en otra cosa; se puede pausar y avanzar o retroceder por palabra o frase. Usa un canal de voz independiente del foco.
- **Fuente** (vía buscador): https://nelowvision.com/product/zoomtext-magnifierreader-single-user/
- **Demanda**: BAJA-MEDIA.

### 9.4 Exportar texto a audio con la voz del lector
- **Producto**: ZoomText Recorder.
- **Comportamiento**: convierte un documento, una web o un correo en un archivo de audio con la voz elegida, para escucharlo en el móvil.
- **Fuente** (vía buscador): https://nelowvision.com/product/zoomtext-magnifierreader-single-user/
- **Demanda**: BAJA-MEDIA. Es fácil de implementar con SAPI o con Eloquence.

### 9.5 Vista de lectura reformateada
- **Producto**: ZoomText DocReader (en "cinta" o "teleprompter", con resaltado palabra a palabra); iOS 26 Accessibility Reader; JAWS con Immersive Reader de Edge.
- **Fuentes** (vía buscador): https://nelowvision.com/product/zoomtext-magnifierreader-single-user/; https://www.afb.org/blog/entry/ios-26-accessibility-features
- **Demanda**: BAJA (baja visión; NVDA 2026.2 ya trae lupa).

---

## 10. Juegos, desarrollo y necesidades especializadas

### 10.1 API para que otras aplicaciones hablen a través del lector
- **Producto**:
  - NVDA Controller Client (speakText, braille, cancel, speakSsml; la versión 2.0 añade getProcessId).
  - Tolk y UniversalSpeech, que detectan el lector activo (NVDA, JAWS, SuperNova, System Access, ZoomText o SAPI).
  - UnityAccessibilityLib 2.0 (enero de 2026) para mods de juegos de Unity.
- **Para Tiresias**: exponer una DLL o servicio compatible con nvdaControllerClient (o registrarse como NVDA ante Tolk) para que miles de audiojuegos y mods (Hearthstone Access, Say the Spire...) funcionen sin cambios.
- **Fuentes** (vía buscador): https://github.com/ndarilek/tolk; https://github.com/qtnc/UniversalSpeech; https://www.mintlify.com/nvaccess/nvda/development/advanced/controller-client; https://www.nuget.org/packages/UnityAccessibilityLib; https://caniplaythat.com/2020/04/15/gaming-without-sight-removing-the-video-from-videogames/
- **Demanda**: ALTA en la comunidad de audiojuegos. Es imprescindible para no quedar fuera.

### 10.2 Consola y terminal
- **Producto**: complemento Console Toolkit de Tony Malykh para NVDA.
- **Comportamiento**:
  - Habla las líneas nuevas en tiempo real, interrumpiendo en lugar de encolar.
  - Pitido grave cuando se actualiza la consola.
  - CTRL+V forzado dentro de sesiones SSH.
  - NVDA+E: editar la línea de comandos en un diálogo accesible; ESC la actualiza e INTRO la ejecuta.
- **Petición relacionada**: #19503 "Windows Terminal: Cursor tracking out of sync and reading errors over SSH".
- **Fuentes**: (vía buscador) https://addons.nvda-project.org/addons/consoleToolkit.en.html; listado GitHub visitado.
- **Demanda**: MEDIA-ALTA entre desarrolladores ciegos.

### 10.3 Resaltado sintáctico auditivo (voice-lock)
- **Producto**: Emacspeak.
- **Comportamiento**: asigna voces distintas a construcciones sintácticas (comentarios, palabras clave, cadenas), para "oír" el resaltado de sintaxis. Lo complementa con iconos auditivos de menos de 0,5 s para los eventos.
- **Fuente** (vía buscador): https://emacspeak.sourceforge.net/raman/publications/chi96-emacspeak/node7.html
- **Demanda**: BAJA, aunque es valiosa para programadores. **[Combina con 2.3 y 2.4]**.

### 10.4 Señales sonoras de error, punto de interrupción y bloque plegado, y vista accesible
- **Producto**: VS Code (accessibility signals; "Accessible View", un editor de texto plano de solo lectura con el contenido de un panel complejo).
- **Comportamiento**: suenan al pasar por una línea con error o aviso, al llegar a un punto de interrupción, cuando falla o termina una tarea, cuando se da una orden inválida en la terminal o cuando hay una región plegada. Para Tiresias: una orden genérica que abra el texto del objeto actual en una vista de texto navegable, al estilo del visor virtual de JAWS.
- **Fuente** (vía buscador): https://bobbyhadz.com/blog/turn-off-sound-vscode; https://skills.sh/microsoft/vscode/accessibility
- **Demanda**: MEDIA. **[AMPLÍA earcons]**: lo nuevo es la vista accesible.

### 10.5 Producción musical y partituras
- **Producto**: REAPER con OSARA (NVDA y JAWS); SuperNova 25.02 añadió soporte para REAPER; MuseScore tiene vista braille de la partitura compás a compás y entrada braille con S D F J K L.
- **Fuentes**: https://yourdolphin.com/product/version?id=652 (visitado); (vía buscador) https://musescore.org/en/node/323036; https://www.hypebot.com/what-it-actually-takes-to-read-music-without-sight-and-what-ai-can-help-solve.md
- **Demanda**: BAJA, aunque es una comunidad muy activa.

### 10.6 Ayuda con CAPTCHA
- **Contexto**: según WebAIM n.º 10, el CAPTCHA es el problema número 1 desde hace 14 años. La cookie de accesibilidad de hCaptcha exige registrarse, caduca a las 24 horas y falla en navegadores con mucha privacidad.
- **Idea legítima para Tiresias**: detectar y anunciar que hay un CAPTCHA, ofrecer saltar al reto de audio, bajar la voz del lector mientras suena ese audio y guiar en el uso de la cookie de accesibilidad. No implica resolverlo automáticamente.
- **Fuentes**: https://webaim.org/projects/screenreadersurvey10/ (visitado); (vía buscador) https://friendlycaptcha.com/insights/hcaptcha-accessibility/
- **Demanda**: ALTA como problema; la solución que pueda aportar el lector es parcial.

### 10.7 Leer subtítulos de vídeo
- **Producto**: LION (OCR continuo); extensiones como Speak YouTube Subtitles; JAWS con el OCR en segundo plano en YouTube.
- **Fuentes** (vía buscador): https://forum.audiogames.net/post/512280/; https://sastltd.zohodesk.eu/portal/en/kb/articles/jaws-changes-to-convenient-ocr-in-2025-product (visitado).
- **Demanda**: MEDIA-ALTA (series y anime con subtítulos en otro idioma, sobre todo en la comunidad hispanohablante). **[Combina con 6.1]**.

### 10.8 Información del sistema y de la aplicación
- **Producto**: complementos Resource Monitor (RAM, versión de Windows, espacio en disco) y Say Product Name and Version, ambos entre los más recomendados en 2026.
- **Fuente**: https://atlas-entry.applevis.com/comment/208222 (visitado).
- **Demanda**: MEDIA. Es barato de integrar en el núcleo.

---

## 11. Citas breves de usuarios (menos de 15 palabras)

- Sobre Narrador frente a NVDA o JAWS (AppleVis, https://atlas-entry.applevis.com/comment/188478):
  - "Narrator will truncate items and not read them in their entirety"
  - "Focus randomly jumps all over the place on certain web pages"
- Sobre el soporte de JAWS en el hilo del Scan Cursor (https://atlas-entry.applevis.com/forum/windows/jaws-question-jaws-scan-cursor): "they didn't do any kind of follow-up about it"
- En el FSCast n.º 268 se recogen las quejas de que la cuenta obligatoria se impuso con prisas y de que Page Explorer quedó al principio fuera de la edición Home Annual, decisión que luego se revirtió. Es un argumento a favor de un lector libre y sin cuenta.

## 12. Cobertura en español

No se encontró contenido indexado de nvda.es, de la lista nvdaes@groups.io, de Tiflolibros ni del CIDAT de la ONCE con peticiones concretas de funciones; las búsquedas en español devolvieron solo páginas genéricas. Fuentes encontradas:
- https://web.ua.es/es/accesibilidad/tecnologias-accesibles/lector-de-pantalla.html (vía buscador): los afiliados a la ONCE tienen JAWS gratis a través del CIDAT. Esto explica que en España domine JAWS y que un mapa de teclas compatible con JAWS (4.10) sea especialmente valioso.
- https://educacion.once.es/tiflotecnologia/3-ayudas-tecnicas-acceso-a-la-informacion/3-2-ordenador/3-2-1-accesibilidad-sin-vision-a-los-sistemas/3-2-1-a-lectores-de-pantalla/nvda/at_download/tiflo_file (vía buscador): ficha de la ONCE sobre NVDA.
- La Asociación Comunidad Hispanohablante de NVDA mantiene nvda.es desde 2017 y se constituyó como asociación en 2020 (vía buscador: https://pretalx.com/pycones-2024/talk/PPXYJJ/).

Recomendación: preguntar directamente en lista@nvdaes.groups.io, porque sus archivos no aparecen en los buscadores.

## 13. Fuentes de fiabilidad dudosa (para no usar como prueba)

- https://www.disabilityworld.org/articles/screen-reader-roadmap-2026/ (visitado): sus cuotas de mercado y afirmaciones como "conformidad con ARIA 1.3" o "TalkBack 15 multi-finger" no cuadran con otras fuentes y parece contenido generado automáticamente.
