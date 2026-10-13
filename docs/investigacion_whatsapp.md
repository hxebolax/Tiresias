# Investigación: complemento de WhatsApp Desktop (WebView2) para Tiresias

Fecha de la investigación: 2026-10-06.
Objetivo: reunir la información necesaria para diseñar el complemento de ejemplo de Tiresias que haga WhatsApp Desktop para Windows totalmente usable con lector de pantalla.

Convención usada en todo el documento:

- **[verificado]**: aparece literalmente en código fuente o documentación citada.
- **[sin verificar]**: deducción, traducción probable o dato no confirmado en una fuente. Hay que comprobarlo con Inspect.exe o Accessibility Insights sobre la app instalada antes de usarlo en código.

---

## 0. Datos clave del objetivo

| Dato | Valor | Fuente |
|---|---|---|
| Paquete instalado | `5319275A.51895FA4EA97F`, versión 2.2638.102.0 | Usuario |
| **Canal de ese paquete** | **WhatsApp Beta**. El canal estable es `5319275A.WhatsAppDesktop_cv1g1gvanyjgm` | [verificado] `policy.py` del complemento WhatsApp Companion |
| AUMID de Beta | `5319275A.51895FA4EA97F_cv1g1gvanyjgm!App` | [verificado] mismo archivo |
| AUMID del canal estable | `5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App` | [verificado] mismo archivo |
| Proceso | `WhatsApp.Root.exe`. NVDA lo trata como el app module `whatsapp_root` (appName `whatsapp.root`) | [verificado] NVDA `source/appModules/whatsapp_root.py`, WhatsAppNG |
| Origen web cargado | `https://web.whatsapp.com` (es literalmente WhatsApp Web dentro de WebView2) | [verificado] Companion `policy.py` (`EXPECTED_ORIGIN`) y changelog 1.2.16 de nvda-whatsapp-unified |
| Ventana de llamadas | Ventana nativa WinUI 3: clase de ventana `WinUIDesktopWin32WindowClass`, FrameworkId `XAML` | [verificado] Companion `wwpCallSupport/runtime.py` y `compact.py` |
| Transición | Beta WebView2 desde julio de 2025 y despliegue forzado en el canal estable entre noviembre y diciembre de 2025 | README de WhatsApp Desktop Enhancer y Notebookcheck |
| Soporte en NVDA | NVDA 2026.x añadió `appModules/whatsapp_root.py` con `disableBrowseModeByDefault = True` (#19655, para WhatsApp 2.2584.3.0 o posterior) | [verificado] código local `adjuntos/nvda/source/appModules/whatsapp_root.py` y `user_docs/en/changes.md` |

Conclusión: WhatsApp ya no es una app UWP/XAML. Es un documento Chromium (WebView2/Edge). Los identificadores UIA del antiguo cliente nativo (`ChatsList`, `BubbleListItem`, `InputBarTextBox`, etc.) **ya no existen**, salvo en la ventana de llamadas, que sigue siendo XAML.

---

## 1. Atajos de teclado nativos de WhatsApp

### 1.1 WhatsApp Desktop WebView2 (la versión actual, lo que hay que respetar)

Fuentes: la tabla `WEBVIEW_SHORTCUT_KEYS` del userscript WhatsApp Web Plus 2.6.91 (que indica que son los atajos "for WhatsApp in WebView2") y los README de WhatsApp Desktop Enhancer y WhatsAppNG. Las tres fuentes coinciden. **[verificado]**

| Acción | Atajo WebView2 | Atajo en WhatsApp Web (navegador), como referencia |
|---|---|---|
| Marcar como no leído | `Ctrl+Shift+U` | `Ctrl+Alt+Shift+U` |
| Silenciar chat | `Ctrl+Shift+M` | `Ctrl+Alt+Shift+M` |
| Archivar chat | `Ctrl+Shift+A` | `Ctrl+Alt+Shift+E` |
| Fijar chat | `Ctrl+Alt+Shift+P` | `Ctrl+Alt+Shift+P` |
| Buscar (global) | `Ctrl+Alt+/` | `Ctrl+Alt+/` |
| Buscar en el chat | `Ctrl+Shift+F` | `Ctrl+Shift+F` |
| Nuevo chat | `Ctrl+Alt+N` | `Ctrl+Alt+N` |
| Chat siguiente | `Ctrl+]` | `Ctrl+Alt+Shift+]` |
| Chat anterior | `Ctrl+[` | `Ctrl+Alt+Shift+[` |
| Añadir chat a lista o etiquetar (Business) | `Ctrl+Cmd+Shift+L` según la tabla, lo que parece una errata de Mac. En el navegador es `Ctrl+Alt+Shift+L` | `Ctrl+Alt+Shift+L` |
| Cerrar chat | `Escape` | `Escape` |
| Nuevo grupo | `Ctrl+Shift+N` | `Ctrl+Alt+Shift+N` |
| Perfil e info | `Ctrl+Alt+P` | `Ctrl+Alt+P` |
| Más velocidad de la nota de voz seleccionada | `Shift+.` | `Shift+.` |
| Menos velocidad de la nota de voz | `Shift+,` | `Shift+,` |
| Ajustes | `Alt+S` | `Ctrl+Alt+,` |
| Panel de emojis | `Ctrl+Alt+E` | `Ctrl+Alt+E` |
| Panel de GIF | `Ctrl+Alt+G` | `Ctrl+Alt+G` |
| Panel de stickers | `Ctrl+Alt+S` | `Ctrl+Alt+S` |
| Búsqueda extendida | `Alt+K` | `Alt+K` |
| Bloquear la app | `Alt+L` | `Ctrl+Alt+L` |
| Abrir info del chat | `Alt+I` | `Alt+I` |
| Bloquear chat | `Ctrl+Shift+B` | `Ctrl+Shift+B` |
| Responder | `Alt+R` | `Alt+R` |
| Responder en privado | `Ctrl+Alt+R` | `Ctrl+Alt+R` |
| Reenviar | `Ctrl+Alt+D` | `Ctrl+Alt+D` |
| Destacar mensaje | `Alt+8` | `Alt+8` |
| Menú de adjuntar | `Alt+A` | `Alt+A` |
| Empezar a grabar una nota de voz (PTT) | `Ctrl+Alt+Shift+R` | `Ctrl+Alt+Shift+R` |
| Pausar la grabación | `Alt+P` | `Alt+P` |
| Enviar la nota de voz | `Ctrl+Enter` | `Ctrl+Enter` |
| Editar el último mensaje | `Ctrl+Flecha arriba` | `Cmd+Flecha arriba` (Mac) |
| Zoom +, -, restablecer | `Ctrl++`, `Ctrl+-`, `Ctrl+0` | (navegador) |
| Abrir el chat N de la lista | `Ctrl+1` a `Ctrl+9` | (no listado) |

**Durante una llamada**, en la ventana de llamada [verificado: userscript y README del Companion]:

| Acción | Atajo |
|---|---|
| Cámara sí/no | `Ctrl+Alt+V` |
| Micrófono sí/no | `Ctrl+Alt+M` |
| Reacciones | `Ctrl+Alt+R` |
| Levantar o bajar la mano | `Ctrl+Alt+H` |
| Compartir pantalla | `Ctrl+Alt+S` |
| Colgar | `Ctrl+Alt+W` |

Nota: `Ctrl+Alt+R`, `Ctrl+Alt+S` y `Ctrl+Alt+D` cambian de significado según el contexto (chat o llamada).

Otras teclas útiles dentro del documento [verificado en complementos]:

- En un mensaje, **flecha derecha o izquierda** recorre sus botones internos: nombre o foto del remitente, mensaje citado, reaccionar, menú "…" y demás. Lo dice el propio WhatsApp en la pista "For more options, press left or right arrow key to access context menu". En la lista de chats, las flechas laterales entran en los botones de la fila.
- **Flechas arriba y abajo** recorren las filas de la lista de chats y de la lista de mensajes.

### 1.2 Atajos históricos (como referencia; ya no aplican)

- **Cliente nativo UWP/WinUI (2021 a 2025)**, según XDA (feb. 2023): `Ctrl+N` nuevo chat, `Ctrl+F` buscar, `Ctrl+Shift+E` archivar, `Ctrl+Shift+D` borrar chat, `Ctrl+Shift+P` fijar, `Ctrl+Tab` y `Ctrl+Shift+Tab` para chat siguiente o anterior, `Ctrl+P` perfil, `Ctrl+,` ajustes, `Ctrl+E`, `Ctrl+G` y `Ctrl+S` para emoji, GIF y stickers.
- **WhatsApp Web en navegador (2023)**: borrar chat con `Ctrl+Alt+Backspace` y chat siguiente o anterior con `Ctrl+Alt+Tab` y `Ctrl+Alt+Shift+Tab`. **[sin verificar]** si siguen vigentes en WebView2. **No hay atajo nativo documentado para borrar un chat en WebView2.**

### 1.3 Teclas que WebView2 o el navegador interno pueden interpretar

El userscript las marca como `RESERVED_SHORTCUTS`. Tiresias debe **consumirlas** cuando las use y no dejarlas pasar si no quiere su efecto:

- `Ctrl+R` y `Ctrl+F5`: recargar la página. En WebView2 recargaría WhatsApp; **[sin verificar]** si las aceleradoras del navegador están activas en esta app.
- `Alt+Flecha izquierda` y `Alt+Flecha derecha`: atrás y adelante.
- `Alt+Inicio`, `Alt+F`, `Alt+E`, `Alt+D`, `Ctrl+Shift+T/N/W` y similares.

### 1.4 Problemas con el teclado español

**[sin verificar, pero muy probable]**

- **AltGr equivale a Ctrl+Alt.** En el teclado español, `AltGr+E` produce €, `AltGr+2` produce @ y `AltGr+3` produce #. Por eso **nunca hay que asignar `Ctrl+Alt+dígito` ni `Ctrl+Alt+E`** en el complemento, porque romperían la escritura.
- Además, el `Ctrl+Alt+E` nativo (panel de emojis) podría dispararse al escribir €. El userscript comprueba `getModifierState("AltGraph")` precisamente para esto.
- `Ctrl+]` y `Ctrl+[` son incómodos en la distribución española, porque los corchetes requieren AltGr. Conviene ofrecer una reasignación, por ejemplo `Alt+Flecha arriba/abajo`, como hace WhatsApp Web Plus.

---

## 2. Complementos existentes: comparativa

### 2.1 Inventario

| Complemento | Autor | Versión de WhatsApp | Estado | Código |
|---|---|---|---|---|
| **WhatsApp Desktop Enhancer** (`whatsAppEnhancer`) | mrido1 | WebView2 | Tienda NVDA, v26.8.24 | github.com/starkrush123/WhatsApp-Enhancer |
| **WhatsApp NG** (`whatsAppNG`, "WhatsApp Desktop accessibility enhancements") | Nuno Costa (nunotfc) | WebView2 | Tienda NVDA, v1.8.1 | github.com/nunotfc/WhatsAppNG |
| **WhatsApp Companion** (WhatsApp Web Plus Companion) | Muhammad Gagah | WebView2, Stable y Beta | Fuera de la tienda; activo (oct. 2026) | github.com/muhammadGagah/whatsapp-web-plus-companion |
| **WhatsApp Web Plus** (userscript de Tampermonkey) | Muhammad Gagah | WhatsApp Web en navegador; también se inyecta en WebView2 mediante el Companion | v2.6.91 (4-oct-2026) | github.com/muhammadGagah/whatsapp-web-plus y Greasy Fork #587557 |
| nvda-whatsapp-unified ("WhatsApp Unificado") | Leonardo D. Bernardes | WebView2 y Web | Personal, en desarrollo | github.com/LeonardoDBernardes/nvda-whatsapp-unified |
| WhatsAppAccess | Victor Bandala | WebView2 | Mínimo: solo fuerza el modo foco | github.com/VictorBandala/WhatsAppAccess |
| Dextop WhatsApp Voice Dual / dextop-whatsapp-voice | nicoalfaro2026 / UlisesMilani | WebView2 | Mejora la grabación de audio mediante argumentos de WebView2 | GitHub |
| WhatsApp Image Description | Emmanuel Asamoah | Desktop | Tienda. `Alt+I` describe una imagen con IA; **choca con el `Alt+I` nativo** (info del chat) | github.com/jasonpython50/whatsappImageDescriber |
| WhatsApp Normalizer | Matheus Lima | Desktop | Tienda. Normaliza caracteres Unicode "decorativos" | github.com/MLMatheus/whatsapp-normalizer |
| **WhatsAppPlus** (`whatsAppPlus`) | Kostya Gladkiy (Ucrania) | **UWP antiguo** | Tienda v2.1.0; no funciona con WebView2 | github.com/Kostya-Gladkiy/WhatsAppPlus |
| whatsapp (comunidad hispana) | **Gerardo Kessler** (gera.ar) | **UWP antiguo** | Hasta jun. 2025 | github.com/gera-ar/whatsapp |
| WhatsApp-desktop (comunidad hispana) | **Gerardo Kessler** | **Electron antiguo** (era WhatsApp Web; clases CSS parecidas a las actuales) | Hasta feb. 2025 | github.com/gera-ar/WhatsApp-desktop |
| Whatsapp_simple | Ángel (rayo-alcantar) | UWP antiguo | 2024 | github.com/rayo-alcantar/Whatsapp_simple |
| nvda-whatsapp | James Scholes | WinUI Beta antiguo | 2025 | github.com/jscholes/nvda-whatsapp |
| whatsapp_enhansements | sulaiman-alqusaimi | UWP | 2022 | GitHub |

No se encontraron complementos llamados "zWhatsApp", "wtsapp" ni "Accessible WhatsApp". El "WhatsAppPlus" de la tienda es de Kostya Gladkiy, no de Gerardo Kessler; Gerardo es autor de los complementos `whatsapp` y `WhatsApp-desktop`.

### 2.2 Funciones por complemento (versión WebView2)

| Función | Enhancer (mrido1) | NG (Nuno Costa) | Unificado (Leonardo) | WhatsApp Web Plus + Companion |
|---|---|---|---|---|
| Forzar o bloquear el modo foco | Sí (bloqueo de `NVDA+Espacio`) | Sí (opción) | Sí | El Companion hereda el app module de NVDA |
| Ir a la lista de chats | No | `Alt+1` | `Alt+1` | `Alt+1` |
| Ir al último mensaje o a la lista de mensajes | No | `Alt+2` | `Alt+2` | `Alt+2` |
| Ir al primer mensaje no leído | No | No | No | `Alt+3` |
| Ir al cuadro de edición o alternar con los mensajes | No | `Alt+D` | `Alt+D` | `Alt+Shift+D` (alterna) |
| Leer el título del chat y el monitor de actividad (escribiendo, en línea) | No | No | No | `Alt+T`; doble pulsación activa el monitor |
| Reproducir o pausar una nota de voz | `Enter` | `Enter` (también vídeo) | `Enter` | `Enter` o `Espacio` (opcional) |
| Menú contextual del mensaje | `Shift+Enter` | `Shift+Enter` | `Shift+Enter` | (nativo con flechas) |
| Reaccionar | No | `Ctrl+Shift+Enter` | `Ctrl+Shift+Enter` | No |
| Copiar el mensaje | `Ctrl+C` | `Ctrl+C` | `Ctrl+C` | Desde el lector de mensajes |
| Leer el mensaje completo ("Leer más") | `Alt+C` (ventana de texto) | `Ctrl+R` (habla) y `Alt+Enter` (ventana navegable) | `Ctrl+R`, `Alt+Enter`, `Alt+C` | `Alt+Shift+C` (lector) y `Shift+Enter` (expandir "Leer más") |
| Filtrar números de teléfono | Sí (lista de chats y mensajes por separado) | Sí (ídem) | Sí (`Ctrl+Shift+E`) | "Privacy Mode" (`Alt+Shift+N`) |
| Quitar la pista "For more options…" | Sí | Sí (`NVDA+Shift+H`) | Sí | Sí |
| Quitar el prefijo "Maybe/Talvez" de contactos desconocidos | No | Sí ("Talvez") | Sí | Sí (Maybe, Mungkin, Talvez) |
| Evitar el doble anuncio en la lista de chats | Sí (ventana de 0,25 s) | Sí (convierte SECTION en LISTITEM) | Sí | Sí ("reduce announcements") |
| Quitar la semántica de tabla ("fila", "celda", "1 de N") | Sí (convierte SECTION, ROW y CELL en PANE) | Parcial | Sí | Reescribe roles grid/row/gridcell |
| Revisar el último texto hablado | `NVDA+flechas` | No | Sí | No |
| Menús o diálogos virtuales (ajustes) | Sí (flechas y `Ctrl+Enter`) | No | Sí | Ajustes propios (`Shift+F8`) |
| Lectura automática de mensajes nuevos | No | No | No | Sí (`Alt+Shift+L`) |
| Chat anterior o siguiente con otras teclas | No | No | Protege `←/→` en la lista | `Alt+↑/↓` (remapeable) |
| Grabar una nota de voz | No | No | No | `Alt+M` (remapeable) |
| Aceptar o rechazar llamadas | No | No | `Alt+Shift+C` (menú de llamada) | `Ctrl+Alt+A` y `Ctrl+Alt+D` |
| Controles de la llamada en curso | No | No | No | `Ctrl+Alt+V/M/R/H/S/W` (pulsa botones XAML) |
| Cerrar el reproductor o la promo | No | No | No | `Alt+0` |
| Pestañas Chats, Estados, Comunidades, Canales y Meta AI | No | No | No | `Alt+Shift+1` a `Alt+Shift+5` |
| Lectura limpia de Estados | No | No | No | Sí |
| Modo de interfaz limpia o alto contraste | No | No | No | `Alt+Shift+8` y `Alt+Shift+9` |

Funciones del **WhatsAppPlus de Kostya (UWP)** que conviene recuperar:

- `Alt+1` chats, `Alt+2` último mensaje, `Alt+3` etiqueta "mensajes no leídos", `Alt+D` alternar edición.
- `Alt+T` nombre y estado del chat, `Ctrl+Shift+P` perfil.
- `Alt+Shift+C` y `Alt+Shift+V` para llamada de voz y videollamada; `NVDA+Alt+Y` y `NVDA+Alt+N` para aceptar y rechazar.
- `Alt+A` micrófono, `Alt+V` cámara.
- `Ctrl+R` grabar y enviar nota de voz, `Ctrl+D` descartar, `Ctrl+Shift+D` pausar.
- `Ctrl+S` velocidad de reproducción, `Alt+P` pausar la reproducción, `Alt+U` progreso de la descarga.
- `Alt+Supr` borrar, `Alt+R` responder, `Alt+F` reenviar, `Alt+S` destacar, `Alt+Retroceso` editar, `Alt+Shift+R` marcar como leído.
- `Ctrl+C` copiar, `Alt+C` ver texto, `Alt+L` lectura en vivo, `Ctrl+Espacio` modo de selección, `Alt+H` ayuda, `Ctrl+Shift+E` quitar números.

Funciones de **Gerardo Kessler** (comunidad hispana, versiones antiguas) que el público hispano espera:

- **`Alt+1` a `Alt+9`: leer los últimos mensajes** del chat abierto (el N-ésimo desde el final).
- **`Alt+Enter`** enfoca el mensaje que se acaba de leer.
- `Alt+Flecha izquierda` alterna entre la lista de mensajes y el cuadro de edición.
- `Ctrl+R` graba y envía una nota de voz; `Ctrl+T` dice el tiempo de reproducción o de grabación.
- `Ctrl+Shift+C` copia, `Alt+Flecha abajo` pulsa "Leer más", `Ctrl+Shift+V` reproduce el vídeo.
- `Ctrl+Shift+T` dice el nombre del chat, `Ctrl+Shift+R` activa o desactiva el filtro de números.

### 2.3 Cómo lo implementan

- **Enhancer, NG y Unificado** usan NVDA sobre **IAccessible2** (`Ia2Web`), no UIA. Identifican elementos así:
  - Por **rol**: SECTION (86) es el mensaje; TABLE y TABLECELL son la lista de chats; LIST, BUTTON y SLIDER según el caso.
  - Por la clase CSS en `IA2Attributes['class']`: `focusable-list-item` marca una fila de mensaje y `copyable-text` el texto copiable. También usan clases ofuscadas que cambian con cada versión, como `fd365im1` para el cuadro de edición.
  - Por `xml-roles == "grid"` para la lista de chats.
  - Por **geometría** (lista a menos de 450 px de la izquierda, con ancho menor de 500).
  - Por **rutas de hijos fijas** desde la ventana, por ejemplo `[0,0,0,0,3,3,1,3,0,0,0]` para la lista de chats. Son frágiles.
- **Reproducir una nota de voz** (NG y Unificado): dentro de la fila del mensaje buscan un `SLIDER` o `PROGRESSBAR` y pulsan (`doAction`) el último botón anterior a él, que es el de reproducir. Para distinguir un vídeo, comprueban si el nombre del primer botón contiene una duración `\d+:\d{2}`.
- **"Leer más"**: buscan un botón con estado `COLLAPSED` o un enlace que va tras un texto `…`, lo activan y releen el texto a los 150 ms.
- **Menú contextual**: botón con estado COLLAPSED o EXPANDED (`aria-haspopup`). Si no lo hay, toman el último botón de la fila. Para **reaccionar**, toman el botón siguiente al de menú.
- **WhatsApp Companion** usa otra técnica, más potente pero invasiva:
  1. Escribe temporalmente en `HKCU\Software\Policies\Microsoft\Edge\WebView2\AdditionalBrowserArguments` un valor con el **nombre del AUMID** (por ejemplo `5319275A.51895FA4EA97F_cv1g1gvanyjgm!App`) y el dato `--remote-debugging-port=<puerto>`.
  2. Lanza WhatsApp por su AUMID.
  3. Se conecta por **Chrome DevTools Protocol** a `127.0.0.1` (`/json/version`, `/json/list`, websocket `/devtools/page/...`) y valida el origen `https://web.whatsapp.com`.
  4. Inyecta el userscript con `Page.addScriptToEvaluateOnNewDocument` y `Runtime.evaluate`.
  5. Restaura el valor del registro.

  Con esto tiene acceso completo al DOM (incluidos los `data-testid`). La primera vez puede pedir permisos de administrador para "reparar" la ACL de esa clave de directiva. **Riesgo**: mientras dura, el puerto de depuración expone la sesión de WhatsApp a cualquier proceso local.
- **Llamadas (Companion)**: localiza la ventana `WinUIDesktopWin32WindowClass` del proceso, busca con UIA puro botones (`UIA_ButtonControlTypeId`) o casillas (`CheckBox`, control type 50002) por **nombre exacto**, y los pulsa con `InvokePattern` o `TogglePattern`. La vista compacta se detecta con un `ListViewItem` de nombre `WhatsApp.PeerStreamVm` (FrameworkId `XAML`).

---

## 3. Identificadores de UIA y del DOM

### 3.1 Cómo se traduce el DOM de Chromium a UIA

Fuente: Chromium `ui/accessibility/platform/ax_platform_node_win.cc`, rama main. **[verificado]**

| Propiedad UIA | Origen en el DOM |
|---|---|
| `AutomationId` | Atributo HTML **`id`** (`GetAuthorUniqueId`). La raíz del documento devuelve `"RootWebArea"` |
| `ClassName` | Atributo HTML **`class`** (`kClassName`) |
| `AriaRole` | Rol ARIA o implícito (`grid`, `row`, `gridcell`, `textbox`, `button`, `slider`…) |
| `AriaProperties` | Cadena con los `aria-*` (por ejemplo `checked=…;expanded=…`) |
| `Name` | `aria-label`, `aria-labelledby` o contenido |
| `FullDescription` | `aria-description` |
| `ControlType` | `grid` → **DataGrid**; `row` → **DataItem** (TreeItem dentro de treegrid); `gridcell` y `cell` → **DataItem**; `listitem` → ListItem; `listbox` → List; `option` → ListItem; `textbox` y contenteditable → **Edit**; `slider` → Slider; `button` → Button; `status` → StatusBar; `log`, `region`, `main`, `navigation`, `section`, `generic`, `group` y `header` → **Group**; documento → **Document** |

**Importante: los atributos `data-*` (incluido `data-testid`) NO se exponen en UIA ni en IA2.** Solo se pueden usar con inyección por CDP (como el Companion) o como pista para entender la estructura. Lo que Tiresias puede usar por UIA es: `id` (AutomationId), `class` (ClassName), roles ARIA, `aria-label` (Name), estados y patrones. **[sin verificar]** que WebView2 tenga activo el proveedor UIA nativo de Chromium en esta app (Edge sí lo tiene); hay que confirmarlo con Inspect: FrameworkId `"Chrome"` y propiedades `AriaRole` rellenas.

### 3.2 Estructura de WhatsApp Web, la misma que en WebView2

Fuente principal: `SELECTORS` y otras funciones del userscript WhatsApp Web Plus 2.6.91 (mantenido en 2026 y probado en WebView2 mediante el Companion). **[verificado en esa fuente]**. La columna UIA es lo que cabe esperar según el mapeo de 3.1.

| Elemento | Selector DOM | Cómo encontrarlo por UIA |
|---|---|---|
| Barra de navegación (Chats, Estados, Comunidades, Canales, Meta AI) | `[data-testid="navbar-primary-section"] button[aria-label="Chats"\|"Status"\|"Updates in Status"\|"Communities"\|"Channels"\|"Meta AI"]` | Botones con esos Name (en inglés). En español: "Chats", "Estados" o "Novedades", "Comunidades", "Canales", "Meta AI" **[sin verificar]** |
| Panel lateral | `div#side` | **AutomationId `side`** |
| Contenedor desplazable de la lista de chats | `#pane-side` | **AutomationId `pane-side`** |
| Lista de chats | `[data-testid="chat-list"]`, o `[aria-label="Chat list"][role="grid"]` (en indonesio "Daftar chat") | ControlType DataGrid y AriaRole `grid`, con **Name "Chat list"**. En español probablemente "Lista de chats" **[sin verificar]** |
| Fila de chat | `div[role="row"]` dentro de la lista; contiene `[role="gridcell"]` > elemento con `[tabindex][aria-selected]` | DataItem `row` > DataItem `gridcell` > elemento enfocable con `SelectionItem.IsSelected` |
| Partes de la fila | `cell-frame-container`, `cell-frame-title`, `cell-frame-primary-detail` (hora), `cell-frame-secondary` (vista previa), `last-msg-status` (estado del último mensaje), `cell-frame-label` (todos `data-testid`) | No visibles por UIA salvo como hijos de texto |
| Botón "…" de la fila | `[data-testid="context-btn"]` | Botón con aria-haspopup (estado COLLAPSED) |
| Caja de búsqueda | `#side input[role="textbox"][type="text"]` o `[data-testid="chat-list-search-container"] input` | Edit dentro de AutomationId `side`. Etiqueta probable "Search or start a new chat" o "Buscar un chat o iniciar uno nuevo" **[sin verificar]** |
| Panel del chat | `div#main` | **AutomationId `main`** |
| Cabecera del chat (título) | `header [data-testid="conversation-info-header-chat-title"]`, `header [data-testid="chat-title"]` o `header [title]` | Group `header` dentro de `main`; el primer texto o botón es el título, y debajo aparece el subtítulo (estado, "escribiendo…") |
| Contenedor de mensajes | `[data-testid="conversation-panel-messages"]` | Group dentro de `main`. El rol se puede ver con AriaRole; WhatsApp Web Plus le fuerza `grid` |
| Fila de mensaje | `div[role="row"]` que contiene **`.focusable-list-item`** (con `data-id` y `tabindex`) | DataItem `row` > elemento con **ClassName que contiene `focusable-list-item`** (por IA2 aparece como SECTION) |
| Mensaje virtualizado | `[data-testid^="conv-msg-"][data-id] > [data-virtualized="true"]` | Las filas fuera de la vista existen pero vacías, así que no se puede leer todo el historial sin desplazarse |
| Contenedor de la burbuja | `[data-testid="msg-container"]` | |
| Metadatos del mensaje | `.copyable-text[data-pre-plain-text]`; `data-pre-plain-text` contiene `"[HH:MM, D/M/AAAA] Remitente: "` (formato **[sin verificar]**, uso habitual) | **ClassName contiene `copyable-text`** |
| Texto del mensaje | `.copyable-text[data-pre-plain-text] [data-testid="selectable-text"]` | Texto dentro de `copyable-text` |
| Pies de foto | `[data-testid~="image-caption"]`, `video-caption`, `document-caption` | |
| Hora | `[data-testid="msg-meta"] [data-testid="msg-time"]` | |
| Iconos de estado | `data-icon="msg-check"` (enviado), `msg-dblcheck` (entregado), `msg-dblcheck-ack` (leído), `msg-time` (pendiente) | Texto o nombre del icono: "Sent", "Delivered", "Read", "Pending" |
| Mensaje citado | `[data-testid="quoted-message"]` | Botón "Mensaje citado" (portugués "Mensagem citada", observado en Unificado) |
| Autor (grupos) | `[data-testid="author"]` | |
| Menú del mensaje | `[data-testid="icon-down-context"][role="button"][aria-label]` | Botón con aria-haspopup |
| "Leer más" | `[data-testid="caption-read-more-button"]`; en la versión antigua, la clase `read-more-button` | Botón o enlace tras `…`. En inglés "Read more"; en español probablemente "Leer más" **[sin verificar]** |
| Nota de voz | `[data-testid="msg-container"]` con `[data-testid="ptt-status"]` o `[data-icon="ptt-status"]`; progreso `[role="slider"][aria-valuemin][aria-valuemax][aria-valuenow]`; también un `<audio>` | **Slider** (RangeValue) precedido por un **Button** de reproducir |
| Cuadro de edición | `div#main footer div[contenteditable="true"]` | **Edit** dentro de `footer` de AutomationId `main`. Name histórico "Type a message"; en español probablemente "Escribe un mensaje" **[sin verificar]** |
| Divisor de no leídos | Texto que coincide con `unread messages?` o `new messages?` | Texto "N unread messages"; en español "N mensajes no leídos" **[sin verificar]** |
| Diálogos | `[role="dialog"]`, `[role="alertdialog"]`, `[aria-modal="true"]` | ControlType Window o Pane con IsDialog |
| Menús | `[role="menu"]`, `menuitem`, `menuitemcheckbox`, `menuitemradio` | Menu y MenuItem |
| Regiones vivas | `[aria-live="polite"]`, `[role="status"]`, `[role="log"]` | Útiles para eventos LiveRegionChanged |
| Visor de medios o reproductor | `[data-testid="media-viewer-modal"]` o `[data-testid="move_resize_component"]`; botón de cierre `button[aria-label="Close"]` o `[data-icon="x"]` | Botón "Close" o "Cerrar" **[sin verificar en ES]** |
| Llamada entrante (web) | `[data-testid="voip-container-incoming-video-call"]` o `voip-container-audio-call` | |
| Estados | `status-player-uie`, `status-player-contact-name`, `status-text`, `status-image`, `status-video`, `ptt-status`, `status-progress-bar-segment` | |

### 3.3 Textos de la interfaz que se ven en Name

| Concepto | Inglés [verificado] | Español | Fuente del inglés |
|---|---|---|---|
| Pista añadida a cada mensaje | "For more options, press left or right arrow key to access context menu" | Empieza por "Para más opciones…" (el prefijo "Para más" aparece en las regex de los complementos). Texto completo **[sin verificar]** | WhatsApp Web Plus (`getMessageContextInstructionRegex`); Enhancer y NG |
| Prefijo de contacto no guardado | "Maybe" (pt "Talvez", id "Mungkin") | "Quizás" o "Quizá" **[sin verificar]** | WhatsApp Web Plus y NG |
| Prefijo de participante | "Participant" | "Participante" **[sin verificar]** | WhatsApp Web Plus |
| Estados de entrega | "Pending", "Sent", "Delivered", "Read" | "Pendiente", "Enviado", "Entregado", "Leído" **[sin verificar]** | WhatsApp Web Plus (`DELIVERY_STATUS_DEFINITIONS`) |
| Escribiendo | "typing…" | "escribiendo…" **[sin verificar]** | WhatsApp Web Plus |
| Grabando audio | "recording audio…" | "grabando audio…" **[sin verificar]** | WhatsApp Web Plus |
| En línea | "online" | "en línea" **[sin verificar]** | WhatsApp Web Plus |
| No leídos | "N unread message(s)" o "new messages" | "N mensajes no leídos" **[sin verificar]** | WhatsApp Web Plus |
| Búsquedas recientes y borrar todo | "Recent searches", "Clear all" | "Búsquedas recientes", "Borrar todo" (incluidas en las regex del userscript) | WhatsApp Web Plus |
| Promoción de la app | "Download WhatsApp for Windows" | **[sin verificar]** | WhatsApp Web Plus |
| Lista de chats | "Chat list" | "Lista de chats" **[sin verificar]** | WhatsApp Web Plus |
| Botones de llamada (XAML) | "Accept call", "Answer call", "Decline call", "Reject call", "Toggle camera", "Turn camera on/off", "Mute", "Unmute", "Mute microphone", "Unmute microphone", "Reactions", "React" (casilla), "Raise hand", "Lower hand", "Screen share", "Share screen", "Start screen sharing" o "Stop screen sharing" (casilla), "End call" | Desconocidos. El Companion deja al usuario añadir etiquetas por idioma, lo que sugiere que no están traducidas en origen o que varían | Companion `wwpCallSupport/labels.py` |

**Recomendación:** implementar todas las cadenas como tablas por idioma ampliables por el usuario (lo hacen WhatsApp Web Plus y el Companion), comparar sin distinguir mayúsculas y minúsculas, y aceptar `…` o `...`.

### 3.4 Identificadores del cliente nativo UWP/WinUI (solo histórico)

[verificado en Kostya WhatsAppPlus, gera-ar/whatsapp, rayo-alcantar y jscholes; **obsoletos en WebView2**]

- **Listas**: `ChatList` y `ChatsList` (lista de chats), `ChatsListItem`, `MessagesList`, `BubbleListItem` (mensaje).
- **Pestañas**: `rpMasterTitlebar` (TabControl).
- **Título y edición**: `TitleButton` (cabecera del chat), `InputBarTextBox` (edición).
- **Contenido del mensaje**: `TextBlock` + `ReadMore`, `NameTextBlock`, `PushNameTextBlock`, `ForwardedHeader`, `ReactionBubble`, `Duration`, `Scrubber`, `TitleTextBlock`, `OpenButton`, `Text`.
- **Notas de voz**: `PlaybackSpeedButton`, `IconTextBlock` (reproducir), `RightButton` y `SendVoiceMessageButton` (grabar y enviar), `PttDeleteButton`, `PttPauseButton`, `PttResumeButton`, `PttTimer`.
- **Botones de la cabecera y del chat**: `AttachButton`, `SettingsButton`, `AudioCallButton`, `VideoCallButton`, `BackButton`, `CloseButton`.
- **Llamada**: `MicMuteButton`, `ActivateVideoButton`.
- **Otros**: `EmojiList`. Ventana `Windows.UI.Core.CoreWindow`.

Nota: el complemento Unificado todavía prueba `ChatList`, `Navigation`, `ChatSearch`, `MessagesList`, `Conversation` y `MessageList` como AutomationId antes de recurrir a la heurística. Esos nombres no existen en el DOM de WhatsApp Web, así que **[sin verificar]** que funcione alguno.

---

## 4. Quejas habituales de los usuarios ciegos (WhatsApp WebView2)

1. **Conflicto entre modo navegación y modo foco**: NVDA activaba el modo navegación y se rompían `Ctrl+F` y la escritura. NVDA 2026 lo corrige por defecto; Enhancer, NG y WhatsAppAccess lo forzaban. *Tiresias: no usar buffer virtual en este proceso y tratarlo como una aplicación.*
2. **Foco inestable**: el foco se queda "pegado" en elementos de lista, se pierde al enviar o hay que salir y volver con Tab al cuadro de edición. Las flechas a veces no leen el texto escrito. Fuentes: README de Enhancer y el hilo de nvda-users.
3. **Verborrea**:
   - La pista "For more options, press left or right arrow key…" en cada mensaje y fila.
   - El **doble anuncio** de cada fila de la lista de chats.
   - Semántica de tabla ("fila", "celda", "1 de 20").
   - Números de teléfono de contactos no guardados.
   - El prefijo "Maybe/Quizás".
   - Notas de voz que anuncian "Voice message 0:12" y otros datos sueltos.
4. **Mensajes largos truncados** con "…" y un botón "Leer más" difícil de alcanzar.
5. **Copiar un mensaje** obliga a pasar por el menú contextual (no hay `Ctrl+C` directo). Fuente: AppleVis.
6. **Notas de voz**: para reproducir hay que llegar al botón; no hay atajo de reproducción, de pausa ni para conocer la posición; la velocidad solo con `Shift+.` y `Shift+,` sin respuesta verbal. Históricamente, la avalancha de eventos UIA al escuchar notas de voz bloqueaba NVDA (#14888, #15169 en el changelog de NVDA).
7. **Llamadas**: cuesta aceptarlas, sobre todo con otros programas abiertos (AppleVis). Ocurren en una ventana nativa aparte y la vista compacta oculta los controles. Al moverse con flechas dentro de los mensajes, el foco puede escaparse a los botones de llamada de la cabecera, y **WebView2 llega a iniciar la llamada al recibir el foco** (problema conocido del complemento Unificado).
8. **Lentitud y exceso de tabulaciones**: reenviar o seleccionar varios destinatarios es engorroso (AppleVis).
9. **Menús, ajustes y diálogos** poco navegables en modo foco; NVDA pierde el modo foco dentro de los menús (#7836). Enhancer los convierte en "menús virtuales".
10. **Los complementos antiguos dejaron de funcionar**, porque desaparecieron los AutomationId UWP.
11. **Lista de mensajes virtualizada**: solo se exponen los mensajes visibles.
12. **Elementos que roban el foco**: reproductor flotante, visor de medios, banner "Download WhatsApp for Windows".
13. **Clases CSS ofuscadas** (`x1xp8n7a`, `fd365im1`…) que cambian con cada versión y rompen los complementos.
14. El equipo de accesibilidad de WhatsApp **no responde** a las incidencias (nvda-users).
15. Conflictos de teclas con AltGr en distribuciones no inglesas **[sin verificar]**, y entre complementos (por ejemplo `Alt+I`).

---

## 5. Propuesta para el complemento de WhatsApp de Tiresias

### 5.1 Principios de diseño

- **Activación**: cuando el proceso en primer plano sea `WhatsApp.Root.exe`, venga del paquete `5319275A.WhatsAppDesktop_*` o `5319275A.51895FA4EA97F_*`, y la ventana sea WinUI con un documento Chrome dentro. La ventana de llamada (`WinUIDesktopWin32WindowClass` con controles XAML) se trata como un contexto aparte.
- **Sin buffer virtual**: modo aplicación siempre. Las flechas pasan a WhatsApp, que gestiona su propio roving tabindex.
- **Localizar elementos por criterios estables, en este orden**:
  1. AutomationId HTML: `side`, `main`, `pane-side`.
  2. AriaRole y ControlType: grid, row, gridcell, slider, textbox/Edit.
  3. ClassName estable: `focusable-list-item`, `copyable-text`.
  4. Name localizado mediante tablas ampliables.
  5. Último recurso: geometría (por ejemplo, la lista a la izquierda).

  **Nunca rutas de hijos fijas ni clases ofuscadas.**
- **Cache**: guardar los elementos raíz (`side`, `main`, la lista de chats y la lista de mensajes) y revalidarlos.
- **Usar patrones UIA**: Invoke en botones, Toggle en casillas, RangeValue en el slider de voz, ExpandCollapse en los menús, SelectionItem en las filas y LiveRegionChanged en los avisos.
- **Filtro de habla**: una capa de "reescritura de nombres" que se aplica a los nombres del proceso antes de hablar y de enviar a braille:
  - quitar la pista de opciones;
  - quitar los teléfonos (`\+\d[()\d\s‬-]{8,}`) de forma configurable, por separado para chats y mensajes;
  - quitar el prefijo "Maybe/Quizás";
  - suprimir los roles "fila/celda" y la posición "x de y";
  - eliminar duplicados en menos de 250 ms.
- **Inyección por CDP**: modo avanzado opcional y **desactivado por defecto**, al estilo del Companion. Daría acceso a `data-testid` y permitiría leer el historial virtualizado. Hay que avisar del riesgo del puerto de depuración y restaurar siempre el registro.
- Todas las cadenas de WhatsApp en tablas por idioma (es y en de serie), ampliables por el usuario.

### 5.2 Funciones propuestas

1. Modo aplicación forzado y "revisión del último texto hablado".
2. Navegación rápida a la lista de chats, al último mensaje, al primer no leído y al cuadro de edición, con retorno al último mensaje enfocado.
3. **Lectura de los últimos N mensajes sin mover el foco** (estilo Gerardo Kessler); con doble pulsación, enfocar ese mensaje.
4. Anuncio del título del chat con su estado (en línea, escribiendo, última vez).
5. **Monitor de actividad**: avisar de "escribiendo…" o "grabando audio…" y de los cambios de estado de entrega del último mensaje enviado (Enviado → Entregado → Leído).
6. **Lectura automática de mensajes nuevos** en el chat abierto, activable y desactivable, con detección de filas nuevas en el contenedor de mensajes (StructureChanged o LiveRegion).
7. Mensajes:
   - reproducir o pausar la nota de voz (`Enter` sobre el mensaje);
   - posición y duración del audio (leídas del slider);
   - velocidad (reenvía `Shift+.` y `Shift+,` y anuncia la nueva velocidad leyendo el botón);
   - abrir el menú contextual; reaccionar;
   - copiar el texto limpio;
   - ver el mensaje completo expandiendo "Leer más" en una ventana de texto navegable;
   - abrir el adjunto o enlace.
8. Atajos amigables para el teclado español: chat anterior y siguiente (reenvían `Ctrl+[` y `Ctrl+]`); grabar, pausar, enviar y descartar notas de voz con respuesta verbal.
9. **Llamadas**: llamada de voz y videollamada desde la cabecera; aceptar y rechazar entrantes; en llamada, reenviar los atajos nativos y anunciar el resultado (por ejemplo "micrófono silenciado").
10. Protección contra llamadas accidentales: si el foco cae en un botón de llamada de la cabecera por moverse con flechas desde un mensaje, devolverlo.
11. Menús y diálogos: anunciarlos bien y mantener el modo aplicación; navegación virtual de opciones en los paneles de ajustes problemáticos.
12. Cerrar el reproductor flotante, el visor de medios o el banner promocional.
13. Ayuda: lista de atajos del complemento y de los atajos nativos de WhatsApp.
14. Ajustes: filtros de teléfonos (chats y mensajes), filtro de pistas, prefijo "Quizás", lectura automática, monitor de actividad, duplicados, verbosidad de la hora y del estado de entrega, y modo CDP avanzado.

### 5.3 Mapa de teclas propuesto

Todas las teclas solo actúan cuando WhatsApp está en primer plano. Las que dependen del contexto (marcadas "en mensaje") **pasan la tecla a WhatsApp** si el foco no está donde corresponde. Se evitan los atajos nativos de 1.1 y las combinaciones `Ctrl+Alt+dígito/letra` que equivalen a AltGr en el teclado español.

| Tecla | Acción | Contexto | Conflicto nativo |
|---|---|---|---|
| `Alt+1` | Ir a la lista de chats (chat seleccionado) | Global | Ninguno |
| `Alt+2` | Ir al último mensaje del chat abierto | Global | Ninguno |
| `Alt+3` | Ir al primer mensaje no leído (divisor) | Global | Ninguno |
| `Alt+D` | Alternar entre el cuadro de edición y el último mensaje enfocado | Global | Ninguno en WebView2 (en un navegador sería la barra de direcciones) |
| `Alt+Shift+1` a `Alt+Shift+9` | Leer el mensaje N contando desde el final, sin mover el foco; con doble pulsación, enfocarlo | Chat abierto | Ninguno (el Companion usa `Alt+Shift+1` a `5` para las pestañas, pero es otro complemento) |
| `Alt+T` | Título y estado del chat; con doble pulsación, activar o desactivar el monitor de actividad | Chat abierto | Ninguno |
| `Alt+Flecha arriba` / `Alt+Flecha abajo` | Chat anterior o siguiente (envía `Ctrl+[` o `Ctrl+]`) y anuncia el chat | Global | Ninguno |
| `Enter` | Reproducir o pausar la nota de voz o el vídeo del mensaje | En mensaje | Pasa la tecla si no es un mensaje multimedia |
| `Shift+Enter` | Abrir el menú contextual del mensaje | En mensaje | En el cuadro de edición (salto de línea) pasa la tecla |
| `Ctrl+Shift+Enter` | Reaccionar al mensaje | En mensaje | Ninguno |
| `Ctrl+C` | Copiar el texto limpio del mensaje | En mensaje | En el cuadro de edición pasa la tecla |
| `Alt+C` | Mensaje completo en una ventana de texto (expande "Leer más") | En mensaje | Ninguno |
| `Alt+Shift+T` | Posición y duración de la nota de voz en curso o tiempo de grabación | Chat | Ninguno |
| `Shift+.` / `Shift+,` | (nativo) cambiar la velocidad; Tiresias anuncia la nueva | En mensaje de voz | Se envía la tecla nativa |
| `Alt+M` | Empezar a grabar una nota de voz (envía `Ctrl+Alt+Shift+R`); si ya se está grabando, enviarla (`Ctrl+Enter`) | Chat | Ninguno |
| `Alt+Shift+M` | Descartar la grabación (pulsa el botón de borrar) | Grabando | Ninguno |
| `Alt+P` | (nativo) pausar la grabación; Tiresias lo anuncia | Grabando | Nativo |
| `Alt+Shift+C` | Llamada de voz al chat abierto | Chat abierto | Ninguno |
| `Alt+Shift+V` | Videollamada al chat abierto | Chat abierto | Ninguno |
| `Ctrl+Alt+A` / `Ctrl+Alt+D` | Aceptar o rechazar una llamada entrante | **Solo** con llamada entrante; si no, pasa la tecla (`Ctrl+Alt+D` es "Reenviar") | Contextual |
| `Ctrl+Alt+V/M/R/H/S/W` | (nativos de llamada) Tiresias los anuncia | Ventana de llamada | Nativo |
| `Alt+Shift+L` | Lectura automática de mensajes nuevos sí/no | Global | Ninguno |
| `Ctrl+Shift+E` | Filtro de números de teléfono sí/no (en chats o mensajes según el foco) | Global | Ninguno en WebView2 (convención de WhatsAppPlus) |
| `Alt+Shift+H` | Pistas de uso ("Para más opciones…") sí/no | Global | Ninguno |
| `Alt+0` | Cerrar el reproductor flotante, el visor de medios o el banner | Global | Ninguno |
| `Alt+H` | Ayuda: atajos del complemento y nativos | Global | Ninguno |
| `Alt+Shift+S` | Ajustes del complemento | Global | Ninguno (`Alt+S` es Ajustes de WhatsApp) |

Teclas que **no** hay que capturar, porque son nativas: `Alt+R`, `Alt+I`, `Alt+K`, `Alt+L`, `Alt+S`, `Alt+A`, `Alt+8`, `Alt+P`, `Ctrl+1` a `Ctrl+9`, `Ctrl+]`, `Ctrl+[`, `Ctrl+Shift+U/M/A/F/N/B`, `Ctrl+Alt+N/P/E/G/S/R/D/` y `Ctrl+Alt+Shift+P/R/L`, `Ctrl+Flecha arriba`, `Ctrl+Enter` y `Escape`.

Teclas que conviene evitar aunque estén libres en WhatsApp: `Ctrl+R` y `F5` (recargarían WebView2 si se dejan pasar), `Alt+Flecha izquierda` y `Alt+Flecha derecha` (atrás y adelante), y `Ctrl+Alt+dígito` (AltGr).

### 5.4 Verificaciones pendientes con la app instalada

Antes de programar, conviene volcar el árbol UIA de WhatsApp 2.2638.102.0 (Inspect.exe o un script de Tiresias que recorra el árbol registrando ControlType, AutomationId, ClassName, AriaRole, AriaProperties y FrameworkId; **sin registrar Name** si se quiere proteger la privacidad). Hay que confirmar:

1. Que el documento expone FrameworkId `Chrome` y que AutomationId `side`, `main` y `pane-side` existen.
2. El Name real en español de: la lista de chats, el cuadro de edición, la búsqueda, la pista de opciones, los estados de entrega, "escribiendo…", "en línea", el divisor de no leídos, "Leer más", el botón de reproducir y el slider de las notas de voz, los botones de llamada de voz y vídeo de la cabecera, y los botones de la ventana de llamada.
3. Si la clase `focusable-list-item` aparece en el ClassName UIA de los mensajes.
4. Si `Ctrl+R`, `F5` o `Alt+Flecha izquierda` tienen efecto en WebView2 (aceleradoras activadas o no).
5. Si `AltGr+E` (€) abre el panel de emojis de WhatsApp.
6. Si existe un atajo nativo para borrar un chat en WebView2.

---

## 6. Fuentes

- NVDA (código local): `adjuntos/nvda/source/appModules/whatsapp_root.py`; `user_docs/en/changes.md` (#19655, #14888, #15169).
- WhatsApp Web Plus 2.6.91 (userscript, licencia MIT): https://greasyfork.org/scripts/587557-whatsapp-web-plus y https://github.com/muhammadGagah/whatsapp-web-plus (`SELECTORS`, `WEBVIEW_SHORTCUT_KEYS`, `DEFAULT_KEYS`, `RESERVED_SHORTCUTS`, regex de estados).
- WhatsApp Companion: https://github.com/muhammadGagah/whatsapp-web-plus-companion (`policy.py`, `registry.py`, `cdp.py`, `wwpCallSupport/*`, `readme.md`, `docs/detailed-guide.md`).
- WhatsApp Desktop Enhancer (mrido1): https://github.com/starkrush123/WhatsApp-Enhancer (`addon/appModules/whatsapp_root.py`, readme).
- WhatsApp NG (Nuno Costa): https://github.com/nunotfc/WhatsAppNG (`addon/appModules/whatsapp_root.py`, README).
- nvda-whatsapp-unified: https://github.com/LeonardoDBernardes/nvda-whatsapp-unified (README, changelog, `appModules/whatsapp_root.py`).
- WhatsAppAccess: https://github.com/VictorBandala/WhatsAppAccess
- WhatsAppPlus (Kostya Gladkiy, UWP): https://github.com/Kostya-Gladkiy/WhatsAppPlus
- Gerardo Kessler: https://github.com/gera-ar/whatsapp (UWP) y https://github.com/gera-ar/WhatsApp-desktop (Electron)
- Whatsapp_simple: https://github.com/rayo-alcantar/Whatsapp_simple
- nvda-whatsapp (James Scholes): https://github.com/jscholes/nvda-whatsapp
- Dextop WhatsApp Voice Dual: https://github.com/nicoalfaro2026/dextop-whatsapp-voice-dual
- Metadatos de la tienda de NVDA: https://github.com/nvaccess/addon-datastore (`addons/whatsAppEnhancer`, `whatsAppNG`, `whatsAppPlus`, `whatsapp-normalizer`, `whatsappImageDescriber`).
- Mapeo UIA de Chromium: https://chromium.googlesource.com/chromium/src/+/refs/heads/main/ui/accessibility/platform/ax_platform_node_win.cc
- Atajos 2023 (UWP y navegador): https://www.xda-developers.com/whatsapp-keyboard-shortcuts/
- Quejas de usuarios: https://groups.google.com/a/nvaccess.org/g/nvda-users/c/Gp9BmqTaB50 ; https://applevis.com/comment/199729 (hilo "WhatsApp Update").
- Contexto de la migración: https://www.notebookcheck.net/WhatsApp-ditches-native-Windows-11-app-in-favor-of-Microsoft-WebView2.1063682.0.html
