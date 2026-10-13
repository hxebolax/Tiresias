# Tiresias, lector de pantalla para Windows

Tiresias es un lector de pantalla para Windows 10 y 11 escrito en Python 3.14
(64 bits) con código propio. Se inspira en NVDA y añade lo que más piden sus
usuarios (ver `docs/estudio_necesidades_usuarios.md` y `docs/investigacion/`).
Versión actual: **1.0.13**. Interfaz en español e inglés.

- Web del proyecto (descargas, novedades, manual y tienda de complementos):
  **https://xebolax.synology.me/Tiresias/**
- Código fuente: **https://github.com/hxebolax/Tiresias**

> **Un proyecto conceptual.** Tiresias es un proyecto experimental, hecho en
> gran parte con ayuda de inteligencia artificial, para explorar cómo podría
> ser un lector de pantalla que atienda las peticiones de sus usuarios. No
> pretende sustituir a NVDA, JAWS ni al Narrador: si dependes de un lector de
> pantalla para trabajar o estudiar, usa uno de ellos como lector principal.

## Índice

- [Funciones principales](#funciones-principales)
- [Requisitos](#requisitos)
- [Empezar: clonar, preparar el entorno y ejecutar](#empezar-clonar-preparar-el-entorno-y-ejecutar)
- [Tiresias.bat: todas las opciones](#tiresiasbat-todas-las-opciones)
- [Compilar el programa y el instalador](#compilar-el-programa-y-el-instalador)
- [Pruebas automáticas](#pruebas-automáticas)
- [Estructura del repositorio](#estructura-del-repositorio)
- [Complementos](#complementos)
- [Qué no está en el repositorio y por qué](#qué-no-está-en-el-repositorio-y-por-qué)
- [Argumentos de la línea de órdenes](#argumentos-de-la-línea-de-órdenes)
- [Publicar una versión](#publicar-una-versión)
- [Documentación](#documentación)
- [Licencia y componentes de terceros](#licencia-y-componentes-de-terceros)

## Funciones principales

- **Lectura de Windows y sus aplicaciones** con UI Automation, MSAA,
  IAccessible2 y Java Access Bridge (elige la API de cada ventana): foco,
  navegación de objetos, cursor de revisión, ratón, consolas, listas con
  columnas, notificaciones y pantalla de bloqueo protegida.
- **Modo exploración** para páginas web y documentos: navegación rápida con
  letras, tablas (celdas combinadas, leer fila o columna), lista de elementos,
  búsqueda, marcadores, lectura rápida, vistazo y web flexible.
- **Voz**: eSpeak NG (incluido), voces OneCore, SAPI 5 (también de 32 bits) y
  SAPI 4, **voces neuronales Piper** sin conexión (gestor de descargas), voces
  neuronales de Microsoft y Eloquence (complementos de la tienda). Prioridades,
  cambio automático de idioma, números, verbosidad, plantillas por tipo de
  control, voces por contexto, esquemas de voz y sonido, diccionarios,
  historial y cambio automático de sintetizador si falla.
- **Audio**: WASAPI o waveOut, división del sonido, atenuación, sonidos de los
  controles con audio posicional y **mezclador** (volumen por aplicación,
  micrófono, dispositivos).
- **Braille** con **liblouis** (más de 250 tablas), entrada braille (también
  contraído y desde el teclado del PC), visor braille y **controladores de
  líneas** USB y Bluetooth con detección automática: Baum y compatibles,
  Eurobraille, Freedom Scientific, Handy Tech, HIMS, HumanWare (BrailleNote,
  Brailliant BI/B), Optelec ALVA, Papenmeier, Seika, Seika Notetaker, BRLTTY y
  HID estándar.
- **Acceso remoto** compatible con NVDA Remote y con el acceso remoto de NVDA,
  y **voz y braille por Escritorio remoto** (RDP) con un complemento nativo
  para `mstsc.exe`.
- **Pantalla y panel táctil**: exploración con el dedo, gestos de varios
  dedos, modos táctiles y gestos en el panel táctil de precisión.
- **Matemáticas**: MathML, LaTeX y ecuaciones de Word; lectura natural,
  exploración paso a paso y braille matemático CMU.
- **Visión**: cortina de pantalla, resaltado de varios colores y lupa (cuatro
  vistas y filtros). **OCR** de ventanas, imágenes, PDF y portapapeles,
  revisión de pantalla por OCR y lectura continua de subtítulos.
- **Inteligencia artificial** (Anthropic, OpenAI, Gemini o servidor local):
  describir, resumir, traducir, etiquetas sugeridas, CAPTCHA, agente con
  confirmación y comprobación de la cámara. Las claves las pone cada usuario
  en su configuración: el repositorio no lleva ninguna.
- **Productividad**: analizador de texto, historial y reglas de
  notificaciones, vigilancias, búsqueda en cualquier ventana, marcadores de
  texto, ratón por teclado y guardar texto como audio.
- **API de control** compatible con el NVDA Controller Client: los audiojuegos
  y programas hechos para NVDA (nvdaControllerClient, Tolk...) hablan con
  Tiresias. API propia documentada en `docs/api_control.md`.
- **Aplicaciones**: Word, Excel, PowerPoint (y sus gráficos), Outlook,
  Thunderbird, Teams, Zoom, Discord, Telegram, Slack, editores de código,
  Explorador, Calculadora, foobar2000, Winamp, PuTTY, LibreOffice, Kindle y el
  complemento **WhatsApp accesible**.
- **Configuración**: perfiles (por aplicación, por sitio web, lectura
  continua), gestos de entrada con comprobación de conflictos, mapa de gestos
  compatible con JAWS, teclas por capas, ajustes rápidos, paleta de órdenes,
  tutorial, ayuda contextual con F1, política corporativa y modo seguro.
- **Distribución**: copia portable (todo en `data`), instalador propio,
  actualizaciones, tienda de complementos y complementos `.tiresias-addon`.

La tecla Tiresias es Insert (también Insert del teclado numérico o Bloq Mayús,
según la configuración). El menú se abre con `Tiresias+M` o
`Tiresias+Aplicaciones`.

> Si otro lector de pantalla (NVDA, JAWS, Narrador) está funcionando, Tiresias
> arranca en espera y no captura ninguna tecla hasta que lo cierres
> (`--force-active` lo arranca activo igualmente).

## Requisitos

Para ejecutar Tiresias desde el código y compilarlo:

- **Windows 10 u 11 de 64 bits.**
- **Python 3.14 de 64 bits** (https://www.python.org/downloads/). Al
  instalarlo, marca «Add python.exe to PATH» (o usa el lanzador `py`).
- **Git**, para clonar el repositorio (o descarga el ZIP desde GitHub).

Las dependencias de Python están en `requirements.txt` (wxPython, comtypes,
PyWinRT, psutil, cryptography, onnxruntime, numpy, cx_Freeze y
`espeakng-loader`, que trae eSpeak NG). `Tiresias.bat` las instala en un
entorno virtual propio, `.venv`.

Solo para **recompilar los binarios nativos** (no hace falta para ejecutar ni
para compilar el programa, porque ya están compilados en `data`):

- **Visual Studio** con las herramientas de C++ (MSVC) para x64 y x86 y el
  **SDK de Windows** (MIDL), para `controller/`, `rdp/` y `sapi32_host/`.
- **Rust** (con el destino `i686-pc-windows-msvc`), solo para el puente de 32
  bits de Eloquence, que no está en este repositorio (ver
  [Qué no está en el repositorio y por qué](#qué-no-está-en-el-repositorio-y-por-qué)).

Opcional: **Tesseract** (motor de OCR alternativo). No se incluye: lo instala
el usuario.

## Empezar: clonar, preparar el entorno y ejecutar

```
git clone https://github.com/hxebolax/Tiresias.git
cd Tiresias
Tiresias.bat entorno
Tiresias.bat requisitos
Tiresias.bat ejecutar
```

- `Tiresias.bat entorno` crea el entorno virtual `.venv` con Python 3.14 de
  64 bits.
- `Tiresias.bat requisitos` instala `requirements.txt` y genera las envolturas
  COM (`tools/pregenerate_comtypes.py`).
- `Tiresias.bat ejecutar` arranca Tiresias desde el código (`src/tiresias.pyw`,
  sin consola). `Tiresias.bat depurar` lo arranca con consola y registro
  detallado.

Si se ejecuta directamente una opción que necesita el entorno y este no existe
(o es de otra versión de Python), `Tiresias.bat` lo crea e instala los
requisitos antes. Sin argumentos, `Tiresias.bat` muestra un menú.

Desde el código, Tiresias guarda su configuración, registros y caché en la
carpeta `data` del repositorio (esas carpetas no se suben: están en
`.gitignore`). Para probar sin tocar tu configuración, usa otra carpeta de
datos con `--data`. Prueba segura, sin ganchos de teclado ni voz (compatible
con otro lector de pantalla en ejecución):

```
.venv\Scripts\python.exe -X utf8 src\tiresias.pyw --data C:\ruta\a\una\copia\de\data --no-input --synth silence --debug --exit-after 8
```

eSpeak NG: desde el código se usa el del paquete `espeakng_loader` (lo instala
`requirements.txt`); al compilar, `tools/build_data.py` lo copia a
`data\synthDrivers\espeak` de la versión compilada. Si se deja una copia
propia de eSpeak NG en `data\synthDrivers\espeak` (con `espeak-ng.dll` y
`espeak-ng-data`), se usa esa (y no se sube al repositorio).

## Tiresias.bat: todas las opciones

Sin argumentos, `Tiresias.bat` muestra un menú; con un argumento, ejecuta esa
opción directamente (`Tiresias.bat compilar`) y devuelve un código de salida
distinto de 0 si falla.

| Menú | Argumento | Qué hace |
|---|---|---|
| 1 | `entorno` | Crea el entorno virtual `.venv` con Python 3.14 de 64 bits. |
| 2 | `requisitos` | Instala o actualiza `requirements.txt` y genera las envolturas COM (`tools/pregenerate_comtypes.py`). |
| 3 | `ejecutar` | Ejecuta Tiresias desde el código (`src/tiresias.pyw`, sin consola). |
| 4 | `depurar` | Ejecuta con consola y registro detallado (`--debug`). |
| 5 | `compilar` | Compila con cx_Freeze en `dist\Tiresias` (`Tiresias.exe` y `Tiresias-depuracion.exe`, runtimes de Visual C++, `data` limpia con eSpeak NG, liblouis, traducciones, `controller`, `rdp`, `docs` e icono, manual, licencias y LEEME). |
| 6 | `complementos` | Empaqueta los complementos de `data/addons` en `dist\complementos\*.tiresias-addon`. |
| 7 | `zip` | Crea `dist\Tiresias-<versión>-portable.zip` a partir de `dist\Tiresias` (sin datos del desarrollador). |
| F | `fuente` | Crea el ZIP del código fuente con los complementos (`tools/make_source_zip.py`). |
| I | `instalador` | Compila las traducciones, empaqueta los complementos, genera el catálogo, compila y crea `dist\Tiresias-<versión>-instalador.exe` (IExpress, `tools/build_installer.py`). |
| T | `traducciones` | Extrae, fusiona y compila los catálogos de idioma (`tools/i18n.py todo`). |
| N | `importarnvda [codigo\|dist] [carpeta]` | Importa la configuración de NVDA (la instalada o la de la carpeta indicada) en `data` del código fuente o de `dist\Tiresias`. |
| D | `desbloquear` | Quita la marca de la web a `dist` (Smart App Control). |
| S | `firmar [carpeta]` | Firma `dist\Tiresias` con signtool y un certificado propio (`tools/sign_dist.py`). |
| 8 | `limpiar` | Borra `build`, `dist` y las carpetas `__pycache__`. |
| 9 | `todo` | Entorno, requisitos, compilar, complementos, ZIP portable y ZIP del código fuente. |
| — | `pruebas` | Ejecuta las pruebas automáticas (`python -m unittest discover -v tests`). |
| P | `publicar` | Publica la versión compilada en el servidor de distribución (`tools/publicar.py`): ver [Publicar una versión](#publicar-una-versión). |

Otras herramientas de `tools/`: `build_data.py` (copia limpia de `data`),
`build_installer.py` (instalador), `make_source_zip.py` (ZIP del código
fuente), `package_addons.py` (paquetes de los complementos),
`pregenerate_comtypes.py` (envolturas COM), `sign_dist.py` (firma),
`make_catalog.py` (copia local del catálogo de la tienda,
`docs/catalogo_complementos.json`), `publicar.py` (publicación) e `i18n.py`
(`extraer`, `actualizar`, `compilar`, `estado`, `todo`).

## Compilar el programa y el instalador

```
Tiresias.bat compilar
```

compila con cx_Freeze (`setup_cxfreeze.py`) en `dist\Tiresias`. Al terminar,
`tools/build_data.py` prepara una carpeta `data` limpia con solo lo que el
programa necesita (sin configuración, registros ni voces del desarrollador) y
avisa si falta algún binario. Para preparar esa carpeta a mano en cualquier
otra carpeta:

```
.venv\Scripts\python.exe tools\build_data.py C:\ruta\de\destino
```

El instalador (`dist\Tiresias-<versión>-instalador.exe`) se crea con
`Tiresias.bat instalador`: compila las traducciones, empaqueta los
complementos, genera el catálogo, compila y crea un autoextraíble con IExpress
(incluido en Windows) que abre el diálogo de instalación accesible de
Tiresias. `Tiresias.bat zip` crea la copia portable en ZIP.

Resultado de la compilación:

```
Tiresias.exe, Tiresias-depuracion.exe     ejecutables
lib\                                      Python y el paquete tiresias (cx_Freeze)
python3.dll, python314.dll, *140*.dll     Python y runtime de Visual C++ (deben ir junto al .exe)
LICENSE.txt, LICENSE-vc_redist.txt, frozen_application_license.txt, LEEME.txt, Manual de usuario.html
data\                                     todo lo demás: addons, brailleTables, cache, config,
                                          controller, docs, images, labels, locale, logs, louis,
                                          rdp, sounds, speechDicts, symbols, synthDrivers, temp, voices
```

Fuera de `data` solo queda lo que cx_Freeze y Windows necesitan junto al
ejecutable. Las excepciones (configuración del sistema del modo seguro, datos
de la copia instalada en `%APPDATA%\Tiresias`, instalador...) están en
`docs/arquitectura.md`, sección 9.

Firma: `Tiresias.bat firmar` usa un certificado propio indicado con variables
de entorno (`TIRESIAS_CERT_PFX` y `TIRESIAS_CERT_PASSWORD`, o
`TIRESIAS_CERT_THUMBPRINT`). El repositorio no contiene certificados ni
contraseñas.

### Binarios nativos ya compilados

Para que cualquiera pueda ejecutar y compilar Tiresias sin Visual Studio, el
repositorio incluye ya compilados (con el CRT estático, sin dependencias del
runtime de Visual C++) los binarios propios de Tiresias, junto a su código:

| Binario | Código | Para qué |
|---|---|---|
| `data/controller/x64` y `x86` (`tiresiasControllerServer.dll`, `tiresiasControllerClient.dll` y `.lib`, `tiresiasNvdaWindow.exe`) | `controller/` | API de control compatible con el NVDA Controller Client. |
| `data/rdp/x64` y `x86` (`tiresiasRdpClient.dll`) | `rdp/` | Voz y braille por Escritorio remoto. |
| `rdp/test/x64` y `x86` (`rdpTestHost.exe`) | `rdp/src/rdpTestHost.c` | Solo para las pruebas (no se distribuye). |
| `data/synthDrivers/sapi32/tiresiasSapi32.exe` | `sapi32_host/` | Voces SAPI 5 de 32 bits y SAPI 4. |
| `data/louis/liblouis.dll` y `data/louis/tables` | https://github.com/liblouis/liblouis (3.39.0, sin cambios) | Braille. |

Para recompilar los propios (necesitan Visual Studio con C++ y el SDK de
Windows; los scripts buscan `vcvarsall.bat` con `vswhere` o la variable
`VCVARSALL`):

```
.venv\Scripts\python.exe controller\build.py        (x64 y x86; o «x64» / «x86»)
.venv\Scripts\python.exe rdp\build.py               (x64 y x86; o «x64» / «x86»)
.venv\Scripts\python.exe sapi32_host\build.py       (x86)
```

## Pruebas automáticas

```
Tiresias.bat pruebas
```

o, con el entorno ya creado:

```
set TIRESIAS_NO_GUARDIAN=1
.venv\Scripts\python.exe -X utf8 -m unittest discover tests
```

Las pruebas usan carpetas de datos temporales y no tocan la configuración. Las
que necesitan algo que no está en el repositorio (Eloquence, la voz Álvaro,
hardware concreto, Visual Studio...) se saltan con un mensaje que explica qué
falta.

## Estructura del repositorio

| Carpeta o archivo | Contenido |
|---|---|
| `src/tiresias.pyw` | Punto de entrada. |
| `src/tiresias/` | Código del lector, solo Python (ver `docs/arquitectura.md`). |
| `data/` | Datos del programa: complementos incluidos (`addons/whatsapp`), símbolos (`symbols`), traducciones (`locale`, con los `.po` y el `.pot`), liblouis (`louis`) y los binarios ya compilados (`controller`, `rdp`, `synthDrivers/sapi32`). Al usar Tiresias desde el código, aquí se crean también los datos del usuario (`config`, `logs`, `cache`, `temp`, `voices`, `labels`, `speechDicts`, `addonsData`...), que no se suben. |
| `complementos_tienda/` | Complementos que se publican en la tienda (ver [Complementos](#complementos)). |
| `controller/` | Código en C de la API de control: servidor RPC, bibliotecas cliente de 32 y 64 bits, ventana auxiliar «NVDA» para Tolk, cabecera `include/tiresiasControllerClient.h`, ejemplos en C y Python y `build.py`. |
| `rdp/` | Código en C del complemento de canal virtual dinámico para el cliente de Escritorio remoto y su programa de pruebas (`rdp/test`). |
| `sapi32_host/` | Código en C del auxiliar de 32 bits para SAPI 5 de 32 bits y SAPI 4. |
| `tests/` | Pruebas automáticas (`unittest`). |
| `tools/` | Herramientas de compilación, datos, instalador, catálogo, firma, publicación y traducciones. |
| `docs/` | Documentación para desarrolladores (ver [Documentación](#documentación)). |
| `manual/` | Manual de usuario (`manual_usuario.html`). |
| `resources/` | Icono del programa. |
| `Tiresias.bat` | Herramienta de desarrollo (entorno, ejecutar, compilar, pruebas...). |
| `setup_cxfreeze.py` | Configuración de la compilación con cx_Freeze. |
| `requirements.txt` | Dependencias de Python. |
| `LEEME.txt` | Guía rápida que acompaña a la versión compilada. |
| `LICENSE.txt` | Licencia (GPL v2 o posterior) y componentes de terceros. |

## Complementos

Los complementos se instalan en `data/addons` (y se empaquetan como
`.tiresias-addon`). Guardan sus datos en `data/addonsData/<id>`
(`paths.addonDataDir`) y pueden añadir entradas al menú Herramientas con
`gui.registerToolsMenuItem`. Cómo crearlos: `docs/desarrollo_complementos.md`.

### Incluido con el programa

- **WhatsApp accesible** (`data/addons/whatsapp`): WhatsApp para Windows
  (WebView2) con atajos, lectura de mensajes, notas de voz y llamadas.

### De la tienda (`complementos_tienda/`)

Se publican en la tienda de complementos de la web del proyecto; Tiresias los
instala desde el menú Complementos, «Tienda de complementos...». Para
probarlos desde el código, copia la carpeta del complemento a `data/addons`
(o instala su paquete `.tiresias-addon`).

| Carpeta | Complemento |
|---|---|
| `NeuralVoices` | Voces neuronales de Microsoft: motor para las voces neuronales sin conexión del Speech SDK de Microsoft (incluye sus bibliotecas, sin ninguna voz). |
| `TraductorAvanzadoPro` | Traductor Avanzado Pro: traducción con Google Translate, DeepL, Microsoft Translator, LibreTranslate y otros servicios. |
| `audiocinemateca` | Audiocinemateca: el catálogo de audiocinemateca.com (películas, series y documentales con audiodescripción). |
| `consoleLog` | Visor de consola: consultar, seguir, buscar, copiar y guardar la salida de las consolas de Windows. |
| `resourceMonitor` | Monitor de recursos: procesador, memoria, discos y otros recursos del equipo. |
| `zRadioBASS` | zRadio BASS: radios en línea con el motor de audio BASS. |
| `zUtilidades` | zUtilidades: lanzador de aplicaciones y otras utilidades para Windows. |

## Qué no está en el repositorio y por qué

- **Eloquence** (`data/addons/eloquence`): incluye bibliotecas propietarias de
  IBM/Nuance (`ECI.DLL` y los archivos `.SYN`), que no se pueden redistribuir
  con una licencia libre. Se distribuye aparte, en la tienda de complementos,
  junto con el código fuente del puente de 32 bits que usa
  (ibmtts-host32-bridge de David CM, GPL v2, en una versión modificada para
  Tiresias: carpeta `bridge_src` del complemento). Sin Eloquence, la voz por
  defecto es eSpeak NG.
- **La voz neuronal Álvaro** (`NeuralVoices-voz-Alvaro`): es un modelo
  propietario de Microsoft. Se distribuye aparte, en la tienda. El motor
  «Voces neuronales de Microsoft» sí está, sin voces.
- **Voces Piper**: se descargan desde el gestor de voces de Tiresias; cada una
  tiene su licencia en su ficha.
- **eSpeak NG** como carpeta: lo instala el paquete `espeakng_loader`.
- **Los datos del usuario** (configuración, perfiles, registros, caché,
  temporales, voces descargadas, etiquetas, diccionarios, copias de seguridad
  de la importación de NVDA...), los entornos virtuales, las compilaciones
  (`dist`, `build`) y el material de estudio. Ver `.gitignore`.

## Argumentos de la línea de órdenes

`tiresias.pyw` y `Tiresias.exe` admiten:

| Argumento | Función |
|---|---|
| `--data <carpeta>` | Carpeta de datos alternativa. |
| `-c`, `--config-path <carpeta>` | Carpeta de configuración alternativa. |
| `--lang <idioma>` | Idioma de la interfaz para esta sesión (`es`, `en`, `auto`). |
| `--debug` | Registro detallado y salida por consola. |
| `--debug-logging` | Registro de depuración en esta sesión (sin consola). |
| `--log-level <nivel>` | Nivel de registro: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` u `OFF`. |
| `--synth <nombre>` | Fuerza un sintetizador (`ibmtts`, `espeak`, `onecore`, `sapi5`, `piper`, `silence`) sin cambiar la configuración. |
| `--no-sounds` | Sin sonidos de inicio y salida. |
| `-m`, `--minimal` | Sin sonidos, sin icono de notificación, sin bienvenida ni mensaje de inicio. |
| `--safe-mode`, `--disable-addons` | Arranca sin complementos. |
| `-s`, `--secure` | Modo seguro: configuración del sistema de solo lectura, sin complementos, consola ni acceso a archivos. |
| `-r`, `--replace` | Sustituye a la copia en ejecución (comportamiento por defecto). |
| `--no-replace` | No arranca si ya hay una copia en ejecución. |
| `-k`, `--check-running` | Solo comprueba si Tiresias está en ejecución (código 0 sí, 1 no). |
| `--quit` | Cierra la copia en ejecución y sale. |
| `--create-portable --portable-path <carpeta>` | Crea una copia portable y sale (`--portable-no-config`, `--portable-no-addons`). |
| `--install` | Arranca Tiresias y muestra el instalador. |
| `--install-silent` | Instala sin preguntar y sale (`--install-dir`, `--launch`, `--no-desktop-shortcut`, `--no-start-menu`, `--start-on-logon`). |
| `--uninstall`, `--uninstall-silent` | Desinstala (con o sin confirmación). |
| `--apply-update <carpeta> --wait-pid <pid>` | Lo usa el actualizador de la copia portable: espera a que termine ese proceso, actualiza la copia de la carpeta y la vuelve a abrir. |
| `--import-nvda-config [carpeta]` | Importa la configuración de NVDA (la instalada o la de la carpeta, también NVDA portable) y sale; con `--import-nvda-profile <nombre>`, en un perfil nuevo. |
| `--undo-nvda-import` | Deshace la última importación de la configuración de NVDA y sale. |
| `--force-active` | Arranca activo aunque haya otro lector de pantalla en ejecución. |
| `--repair-com` | Repara los registros COM de accesibilidad y sale (administrador). |
| `--copy-config-to-system <carpeta>` | Copia esa configuración a la del sistema (la del modo seguro) y sale (administrador). |
| `--no-input` | No instala los ganchos de teclado y ratón (pruebas). |
| `--exit-after <segundos>` | Sale automáticamente tras N segundos (pruebas). |
| `--restart-after <segundos>` | Se reinicia automáticamente tras N segundos (pruebas del guardián). |

## Publicar una versión

Las actualizaciones, la tienda de complementos, las novedades y el manual se
sirven desde la web del proyecto, **https://xebolax.synology.me/Tiresias/**.
`Tiresias.bat publicar` (`tools/publicar.py`) genera esa web en una carpeta
local: la indicada con `--destino`, con `"destino"` en `tools/publicar.json` o
con la variable de entorno `TIRESIAS_WEB`.

1. Sube `VERSION` en `src/tiresias/__init__.py` y escribe `docs/novedades.html`.
2. Ejecuta `Tiresias.bat compilar` y, si hay certificado, `Tiresias.bat firmar`.
3. Ejecuta `Tiresias.bat publicar --simular --notas "Resumen corto"` para ver qué hará.
4. Ejecuta `Tiresias.bat publicar --notas "Resumen corto"`.

`publicar` es idempotente: no duplica versiones y conserva las anteriores.
Las opciones están en `Tiresias.bat publicar --help`. Todas las direcciones
del cliente salen de una sola constante, `updates.DISTRIBUTION_URL`; la opción
«Servidor de distribución» de Opciones la sustituye.

Los componentes propietarios (Eloquence y la voz Álvaro) nunca van dentro del
instalador, el portable ni el código fuente públicos; `tools/publicar.json`
decide si se publican aparte en la tienda (que avisa de que son propietarios
antes de instalarlos). La responsabilidad de esas licencias es de quien
publica. Todo el detalle está en `docs/publicacion.md`.

## Documentación

- `manual/manual_usuario.html`: manual completo para el usuario final (se
  copia junto al ejecutable como «Manual de usuario.html»).
- `docs/novedades.html`: novedades de cada versión (menú Ayuda, Novedades).
- `docs/arquitectura.md`: arquitectura interna para desarrolladores.
- `docs/desarrollo_complementos.md`: cómo crear complementos.
- `docs/api_control.md`: API de control para juegos y programas.
- `docs/publicacion.md`: cómo publicar, estructura del servidor de
  distribución y formatos.
- `docs/estudio_necesidades_usuarios.md`: estudio de carencias de NVDA.
- `docs/investigacion_whatsapp.md`: investigación para el complemento de
  WhatsApp.
- `docs/catalogo_complementos.json`: copia local del catálogo de la tienda.
- `docs/actualizacion.json`: copia del manifiesto de actualización publicado.
- `docs/investigacion/`: investigación de partida y seguimiento (peticiones
  del GitHub de NVDA, foros y otros lectores, inventario de NVDA y auditoría
  inicial).

## Licencia y componentes de terceros

El código de Tiresias se distribuye con la **Licencia Pública General de GNU,
versión 2 o (a tu elección) cualquier versión posterior** (`LICENSE.txt`).

| Componente | Uso | Licencia |
|---|---|---|
| Python | Lenguaje y biblioteca estándar | PSF |
| wxPython | Interfaz | wxWindows Library Licence |
| comtypes | COM (UI Automation, SAPI 5, MSAA/IA2) | MIT |
| winrt (PyWinRT) | OneCore, OCR, PDF, cámara | MIT |
| psutil | Lista de procesos | BSD de 3 cláusulas |
| eSpeak NG (espeakng-loader) | Sintetizador y fonemas de Piper | GPL v3 |
| liblouis 3.39.0 | Traducción braille y tablas (`data/louis`) | LGPL 2.1 o posterior |
| onnxruntime | Inferencia de las voces Piper | MIT |
| numpy | Audio de Piper | BSD |
| cryptography | TLS y certificados del acceso remoto | Apache 2.0 o BSD |
| cffi | Dependencia de cryptography | MIT |
| cx_Freeze | Compilación (no se distribuye) | PSF |
| Voces Piper | Descargadas por el usuario | La de cada voz, en su ficha `MODEL_CARD` |
| NVDA Controller Client | Solo se reproducen la interfaz y los UUID de su RPC; implementación propia | — |
| Controladores braille adaptados de NVDA y diseño del auxiliar SAPI 4 | Ver `LICENSE.txt` | GPL v2 (o posterior) |
| Speech SDK de Microsoft (complemento NeuralVoices) | Voces neuronales de Microsoft | Términos de Microsoft (`complementos_tienda/NeuralVoices/sdk/LICENCIA_SPEECH_SDK.txt`) |
| BASS (zRadioBASS, audiocinemateca) | Audio de esos complementos | Licencia de Un4seen (en cada complemento) |
| Puente ibmtts-host32-bridge (David CM), modificado | Eloquence de 32 bits (solo en el complemento de la tienda; no está en el repositorio) | GPL v2 |
| Eloquence / ETI-Eloquence | Voz del complemento de la tienda (no está en el repositorio) | Propietaria (de sus titulares; requiere licencia válida) |
