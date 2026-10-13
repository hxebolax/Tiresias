# Publicación de Tiresias: actualizador y tienda de complementos

Desde la 1.0.13, Tiresias se actualiza y descarga sus complementos de **dos orígenes**, y `tools/publicar.py` publica en los dos a la vez:

- **El servidor del proyecto**: una carpeta web estática con unos JSON y los archivos de descarga. Es una carpeta del equipo de quien publica (indicada en `tools/publicar.local.json`, que no se sube al repositorio); Synology Drive la sincroniza con el NAS, que la sirve en **https://xebolax.synology.me/Tiresias/**. Tiene todo, también los complementos propietarios de la tienda (Eloquence y la voz Álvaro).
- **GitHub**: las versiones (releases) del repositorio público **https://github.com/hxebolax/Tiresias**, publicadas con la herramienta `gh` (apartado 7). Tiene lo mismo **menos los complementos propietarios**, que nunca se publican en GitHub.

En Tiresias, la opción «Origen de las actualizaciones y de la tienda» elige de dónde leer (apartado 4). Por defecto consulta los dos.

## 1. Publicar una versión paso a paso

1. Sube la versión en `src/tiresias/__init__.py` (`VERSION` y `VERSION_TUPLE`) y escribe las novedades en `docs/novedades.html`.
2. Compila: `Tiresias.bat compilar` (deja el programa en `dist\Tiresias`).
3. Opcional, pero recomendado: firma con `Tiresias.bat firmar` (ver el apartado 6).
4. Prueba primero sin escribir nada:
   ```
   Tiresias.bat publicar --simular --notas "Resumen corto de las novedades"
   ```
   La simulación no llama a `gh`: lista lo que haría en GitHub (versiones que crearía, archivos que subiría y las notas de la versión).
5. Publica (en el servidor y en GitHub, según `tools/publicar.json`):
   ```
   Tiresias.bat publicar --notas "Resumen corto de las novedades"
   ```
   Para publicar en uno solo: `--solo-servidor` (o `--sin-github`) o `--solo-github`.
6. Espera a que Synology Drive sincronice (de segundos a pocos minutos) y comprueba:
   - https://xebolax.synology.me/Tiresias/actualizacion.json
   - https://github.com/hxebolax/Tiresias/releases (la versión nueva, «distribucion» y «complementos»);
   - en Tiresias, menú Ayuda, «Buscar actualización...»;
   - la tienda de complementos.

### Qué hace `tools/publicar.py`

1. Empaqueta los complementos de `data\addons`, sin los propietarios (ver el apartado 5).
2. Prepara la **copia pública** del programa en `dist\publicacion\publica\Tiresias`. Es una copia de `dist\Tiresias` sin estas cosas:
   - los datos del desarrollador: `data\config`, `logs`, `cache`, `temp`, `labels`, `voices`, `speechDicts\voices` y `addons\pending.json`, además de `instalado.json` y `systemConfig` (`tools/build_installer.py` excluye la misma lista);
   - `data\addons\eloquence`.

   Después comprueba que no queda ningún `ECI.DLL` ni ningún `.SYN`, y escribe en `data\docs\catalogo_complementos.json` el catálogo que se va a publicar.
3. Desde esa copia genera:
   - el ZIP portable;
   - el instalador (IExpress, con `tools/build_installer.py`). Antes de usarlo, lo verifica.
   - el ZIP del código fuente (`tools/make_source_zip.py`, sin `data/addons/eloquence`).
4. Publica en el destino y reconstruye los JSON y la portada. Solo escribe los archivos que cambian.
5. Actualiza `docs\catalogo_complementos.json` y `docs\actualizacion.json` del repositorio, salvo con `--sin-docs` (y con `--solo-github`, que no toca el servidor).
6. Si toca GitHub, lo publica allí con `gh` (apartado 7). Antes de compilar nada comprueba que `gh` está instalado, tiene sesión y ve el repositorio; si no, se detiene con un mensaje claro.

### Opciones

| Opción | Efecto |
|---|---|
| `--destino CARPETA` | Carpeta publicada. Por defecto, la variable `TIRESIAS_WEB` o el valor `destino` de `tools/publicar.local.json` (archivo de este equipo que no se sube al repositorio; por ejemplo `{"destino": "D:\\web\\Tiresias"}`). |
| `--simular` | Construye los paquetes, pero en el destino no escribe ni borra nada: solo lista lo que haría. |
| `--canal estable\|beta` | Canal de la versión. Las beta van en `channels.beta` del manifiesto. |
| `--notas "..."` | Texto corto que se ve en el aviso de actualización y en la portada. |
| `--min-windows 10.0.10240` | Versión mínima de Windows. Los equipos más antiguos no reciben la actualización. |
| `--programa CARPETA` | Programa compilado. Por defecto, `dist\Tiresias`. |
| `--incluir-propietario` | Publica también Eloquence. Pide confirmación (ver el apartado 5). |
| `--acepto-responsabilidad` | Con `--incluir-propietario`, no pregunta. Sirve para scripts. |
| `--sin-instalador` | No genera el instalador; solo el portable y el código. |
| `--sin-docs` | No toca `docs\` del repositorio. |
| `--sin-propietario` | Variante pública sin Eloquence, aunque `tools/publicar.json` diga lo contrario. |
| `--config ARCHIVO` | Configuración de la publicación. Por defecto, `tools/publicar.json`: `incluirPropietario`, `propietariosEnTienda`, `destino` y `github`. |
| `--solo-servidor` | Publica solo en el servidor, aunque `tools/publicar.json` pida también GitHub. |
| `--sin-github` | Lo mismo que `--solo-servidor`. |
| `--solo-github` | Publica solo en GitHub (no escribe en el destino ni en `docs\`). Funciona aunque `github.publicar` sea `false`. |
| `--repositorio PROPIETARIO/NOMBRE` | Otro repositorio de GitHub. Por defecto, `github.repo` de `tools/publicar.json` (`hxebolax/Tiresias`). |

**Idempotencia:**
- `versiones.json`, el manifiesto y el catálogo se reconstruyen a partir de lo ya publicado más lo nuevo.
- Publicar dos veces la misma versión no la duplica: sustituye sus archivos si han cambiado.
- Publicar una versión nueva conserva las anteriores en `descargas\<versión>\` y en el historial.
- Los archivos idénticos no se reescriben, así que Synology Drive no vuelve a subirlos.
- En GitHub pasa lo mismo: volver a publicar una versión sustituye (`--clobber`) solo los recursos que han cambiado y actualiza sus notas; los JSON de «distribucion» se sustituyen siempre.

## 2. Estructura del servidor

```
Tiresias/
├── index.html                    portada accesible (español, sin JavaScript)
├── actualizacion.json            manifiesto que lee el actualizador
├── versiones.json                historial de versiones publicadas
├── novedades.html                copia de docs/novedades.html
├── .htaccess                     tipos MIME y sin caché en los JSON (solo Apache)
├── manual/
│   └── index.html                manual de usuario
├── descargas/
│   └── 1.0.2/
│       ├── Tiresias-1.0.2-instalador.exe       (+ .sha256)
│       ├── Tiresias-1.0.2-portable.zip         (+ .sha256)
│       └── Tiresias-1.0.2-codigo-fuente.zip    (+ .sha256)
└── complementos/
    ├── catalogo.json             catálogo de la tienda
    └── whatsapp/
        └── whatsapp-1.0.0.tiresias-addon       (+ .sha256)
```

- Los `.sha256` tienen el formato de `sha256sum` en modo binario (`<suma> *<archivo>`), el mismo que el resto de la web del usuario.
- **Servidor web:** el NAS sirve con **nginx**. Lo dicen las cabeceras: `Server: nginx`, listados «Index of» y error 403 para los archivos que empiezan por punto.
  - nginx no lee `.htaccess`.
  - nginx ya sirve `.json` como `application/json` y los tipos desconocidos (`.tiresias-addon`, `.sha256`) como `application/octet-stream`. Es lo correcto.
  - Envía `ETag` y `Last-Modified`. El cliente pide los JSON con `Cache-Control: no-cache`, así que siempre se revalidan.
  - El `.htaccess` se deja por si Web Station pasa a Apache. No hace daño: nginx no lo sirve (devuelve 403) y GitHub Pages lo ignora.

## 3. Formatos

Todas las direcciones son **relativas al JSON que las contiene**. El cliente las resuelve con `updates.resolveUrl`.

### `actualizacion.json`

```json
{
	"format": "tiresias-actualizacion",
	"formatVersion": 1,
	"version": "1.0.2",
	"date": "2026-10-07",
	"url": "descargas/1.0.2/Tiresias-1.0.2-instalador.exe",
	"sha256": "…",
	"size": 98765432,
	"minWindows": "10.0.10240",
	"notes": "Resumen corto",
	"notesUrl": "novedades.html",
	"installer": {"url": "descargas/1.0.2/Tiresias-1.0.2-instalador.exe", "sha256": "…", "size": 98765432},
	"portable": {"url": "descargas/1.0.2/Tiresias-1.0.2-portable.zip", "sha256": "…", "size": 87654321},
	"source": {"url": "descargas/1.0.2/Tiresias-1.0.2-codigo-fuente.zip", "sha256": "…", "size": 1234567},
	"channels": {"beta": {"version": "1.1.0b1", "...": "los mismos campos"}}
}
```

- El primer nivel es el canal **estable**. `url`, `sha256` y `size` repiten los del instalador, por compatibilidad.
- `channels.beta` solo aparece si hay una beta más reciente que la estable. La reciben quienes elijan el canal «beta» en Opciones.
- Paquete según el tipo de copia:
  - copia instalada: `installer`;
  - portable: `portable`;
  - ejecución desde el código: `source`.

### `versiones.json`

```json
{
	"format": "tiresias-versiones",
	"formatVersion": 1,
	"versions": [
		{
			"version": "1.0.2", "channel": "estable", "date": "2026-10-07",
			"minWindows": "10.0.10240", "notes": "…", "notesUrl": "novedades.html",
			"proprietary": false,
			"files": {
				"installer": {"name": "…", "url": "descargas/1.0.2/…", "sha256": "…", "size": 0},
				"portable": {"…": "…"}, "source": {"…": "…"}
			}
		}
	]
}
```

Va ordenado de la versión más reciente a la más antigua: `1.1.0` > `1.1.0rc1` > `1.1.0b1` > `1.0.9`. `proprietary` indica que esa versión se publicó con `--incluir-propietario`.

### `complementos/catalogo.json`

Es el mismo formato que lee la tienda (`addon_store.parseCatalog`):

```json
{
	"format": "tiresias-catalogo",
	"version": 1,
	"addons": [
		{
			"id": "whatsapp", "name": "WhatsApp accesible", "version": "1.1.0",
			"author": "…", "description": "…",
			"minApiVersion": "1.0", "lastTestedApiVersion": "1.0",
			"url": "whatsapp/whatsapp-1.1.0.tiresias-addon", "sha256": "…", "size": 14199,
			"homepage": "", "changelog": "…", "date": "2026-10-07", "proprietary": false,
			"versions": [
				{"version": "1.1.0", "url": "…", "sha256": "…", "size": 0, "minApiVersion": "1.0", "lastTestedApiVersion": "1.0", "changelog": "…", "date": "…"},
				{"version": "1.0.0", "...": "…"}
			]
		}
	]
}
```

- El primer nivel describe la versión más reciente. `versions` guarda todas las publicadas.
- La tienda ofrece la más reciente cuya `minApiVersion` admita la versión de Tiresias instalada. Así, una versión que necesita un Tiresias más nuevo no deja sin actualizaciones a los demás.
- La copia local `docs/catalogo_complementos.json` (en el programa, `data\docs`) tiene el mismo contenido. Si el servidor no responde, la tienda la usa y resuelve sus direcciones respecto al catálogo en línea.

## 4. El cliente

`src/tiresias/updates.py`:

- `DISTRIBUTION_URL = "https://xebolax.synology.me/Tiresias"` es el servidor del proyecto. De ella salen:
  - `actualizacion.json`;
  - `complementos/catalogo.json`;
  - `novedades.html`;
  - `descargas/...`.

  Vacía, la compilación no tiene distribución oficial: no se consulta ni el servidor ni GitHub.
- `GITHUB_URL = "https://github.com"` y `GITHUB_REPO = "hxebolax/Tiresias"` son GitHub (vacío: no se usa). Las direcciones salen de `githubDistributionUrl()` y `githubAssetUrl()`.
- **Origen** (opción **Opciones > Actualizaciones y complementos > Origen de las actualizaciones y de la tienda**, `update.origin`):
  - `ambos` (por defecto, «Servidor del proyecto y GitHub»): consulta los dos a la vez (`fetchAll`, 10 s por origen, `ORIGIN_TIMEOUT`);
  - `servidor` («Solo el servidor del proyecto»);
  - `github` («Solo GitHub»);
  - `propio` («Servidor propio»): la dirección de **Dirección del servidor propio** (`update.serverUrl`).
- **Compatibilidad:**
  - una configuración anterior con `update.serverUrl` escrita pasa a `propio` al cargarla (`config/migrations.py`, `_updateOrigin`), y `updates.currentOrigin()` la trata igual aunque no se haya migrado;
  - la política `distributionUrl` fija el origen a ese servidor (y Opciones desactiva el origen y la dirección);
  - las opciones `update.checkUrl` y `addons.catalogUrl`, o las políticas `updateUrl` y `addonCatalogUrl`, siguen teniendo prioridad para un solo archivo (`updateOrigins()`, `catalogOrigins()`).
- **Actualizaciones con los dos orígenes** (`checkForUpdate`):
  - gana la versión más alta del canal; con la misma, el servidor del proyecto (el preferido), y la de GitHub queda como réplica (`UpdateInfo.mirrors`);
  - un origen que no responde o publica un manifiesto no válido se ignora sin avisar (queda en el registro); solo si fallan los dos se muestra el error;
  - `downloadUpdate` descarga del preferido y, si falla (o el SHA-256 no coincide), de la réplica. Cada descarga se comprueba con su propio SHA-256, que es obligatorio en red.
- **Tienda con los dos orígenes** (`addon_store.fetchCatalog` y `mergeCatalogs`):
  - por identificador gana la versión más alta; con la misma, el servidor del proyecto;
  - los complementos que solo están en el servidor (los propietarios) siguen apareciendo;
  - `downloadPackage` usa el otro origen si falla la descarga y allí está **el mismo paquete** (el mismo SHA-256).
  - Si no responde ninguno, se usa la copia local. Con «Solo GitHub», esa copia se ve como el catálogo de GitHub: sin propietarios y con los paquetes en la versión «complementos».
- **Novedades:** en el manifiesto del servidor, `notesUrl` es `novedades.html`; en el de GitHub, la página de la versión (`https://github.com/hxebolax/Tiresias/releases/tag/v<versión>`), con las mismas novedades. El manual y las novedades del menú Ayuda son locales.
- **Redirecciones:** GitHub redirige cada descarga a otro dominio (`release-assets.githubusercontent.com` u `objects.githubusercontent.com`). `urllib` la sigue; `openUrl` rechaza las que acaban en `http` cuando se pidió `https`. `resolveUrl` admite las URL absolutas `https` de otros hosts que hay en los JSON de GitHub, y el SHA-256 se comprueba sobre lo descargado, venga de donde venga.
- Con la constante rellena, la comprobación automática (`update.autoCheck`, cada `update.intervalHours`) y el aviso de complementos (`addons.autoCheckUpdates`) funcionan por defecto. Si el usuario o la política los desactiva, no se hacen.
- **HTTPS:** se usa `ssl.create_default_context()`, que verifica el certificado y el nombre con los certificados raíz de Windows, también en la versión compilada. Exige TLS 1.2 o posterior.
  - El certificado del NAS es de Let's Encrypt y cubre `xebolax.synology.me` y `*.xebolax.synology.me`. Verificado.
- **Descarga:** comprueba el tamaño (`Content-Length` y bytes recibidos) y el SHA-256. Si algo no coincide, borra el archivo parcial.
  - Si la conexión se corta, lo intenta hasta 3 veces en total.
  - Los JSON se piden con `Cache-Control: no-cache`.
- **Cómo se aplica la actualización:**
  - **Copia instalada:** se descarga el instalador y se ejecuta. Su `Tiresias.exe --install` cierra la copia en marcha y muestra el diálogo de instalación. Ese diálogo propone la carpeta instalada y el modo «para todos» o «solo para mí» que ya tenía, y actualiza conservando la configuración de `%APPDATA%\Tiresias`.
  - **Copia portable:**
    1. Se descarga el ZIP portable y se descomprime en `data\cache\actualizaciones`. Se comprueba que ninguna ruta del ZIP se salga de esa carpeta.
    2. Se lanza el `Tiresias.exe` nuevo con `--apply-update <carpeta> --wait-pid <pid>` y Tiresias se cierra.
    3. El nuevo espera a que termine el antiguo y ejecuta `installer.applyPortableUpdate`. Mueve los archivos del programa a `_actualizacion_anterior`, copia los nuevos y conserva todo esto:
       - `config`, perfiles, registros y etiquetas;
       - `symbols/user.json` y `speechDicts`;
       - los complementos del usuario. Los complementos incluidos solo se actualizan si son más nuevos; Eloquence se conserva aunque la versión pública no lo traiga.
    4. Si algo falla, restaura lo que había movido.
    5. Al terminar, haya ido bien o mal, vuelve a abrir Tiresias para que el usuario no se quede sin lector. El resultado queda en `data\actualizacion_resultado.json`:
       - si falló, Tiresias lo dice al arrancar;
       - si fue bien, Tiresias dice «se ha actualizado a la versión…».
  - **Desde el código:** se descarga el ZIP del código fuente y se abre su carpeta.
  - Al descargar con urllib, Windows no añade la marca de la web (Zone.Identifier). Por eso Smart App Control no trata los archivos de la actualización como descargados de Internet.

## 5. AVISO LEGAL: Eloquence y otros componentes propietarios

El complemento **Eloquence** (`data\addons\eloquence`) contiene bibliotecas **propietarias de IBM/Nuance**: `ECI.DLL` y los archivos `.SYN` de cada idioma, copiados de una instalación con licencia. Publicarlos en una web pública sería **redistribuir software propietario** sin permiso. Por eso:

- **Por defecto**, `publicar.py`:
  - no publica Eloquence en el catálogo;
  - si ya estaba publicado, lo retira (borra `complementos/eloquence`);
  - genera el instalador, el portable y el código fuente desde una copia **sin Eloquence**.

  Además se protege así:
  - aborta si encuentra un `ECI.DLL` o un `.SYN` en la copia pública o en los ZIP;
  - trata como propietario cualquier complemento que los contenga, aunque se llame de otra forma (lista `PROPRIETARY_ADDONS` y patrones `PROPRIETARY_PATTERNS` de `tools/publicar.py`).
- **En la versión pública la voz es eSpeak NG.**
  - `speech.synth = "auto"` recorre `synthPriority` (`ibmtts`, `espeak`, `onecore`, `sapi5`).
  - Sin el complemento, el controlador `ibmtts` no existe y se elige eSpeak NG, que va incluido en `data\synthDrivers\espeak`.
  - Comprobado arrancando la copia pública compilada: el registro dice «Sintetizador: espeak».
- **Quien actualiza una copia que ya tenía Eloquence lo conserva.** El actualizador portable y el instalador nunca borran complementos del usuario.
- **Decisiones registradas en `tools/publicar.json`.**
  - `"incluirPropietario"`: con `true`, el instalador, el portable y el código fuente llevan Eloquence (sin preguntar, con aviso en la consola). `--sin-propietario` fuerza la variante pública para una publicación concreta.
  - `"propietariosEnTienda"`: con `true`, los complementos propietarios se publican **solo en la tienda** aunque el programa vaya sin ellos. Son propietarios Eloquence (`PROPRIETARY_ADDONS`), cualquier complemento con `ECI.DLL` o `.SYN`, y cualquiera con `"proprietary": true` en su manifiesto (la voz neuronal Álvaro de Microsoft, en `complementos_tienda`). El catálogo los marca con `"proprietary": true`, la portada lo dice junto a cada uno y la tienda de Tiresias avisa y pide confirmación antes de instalarlos. Las carpetas propietarias de `complementos_tienda` nunca van al ZIP del código fuente público.
  - **Estado actual (desde la 1.0.9):** `incluirPropietario` es `false` (el usuario quiere poder distribuir Tiresias) y `propietariosEnTienda` es `true` (el usuario quiere Eloquence y la voz Álvaro en la tienda y asume la responsabilidad de sus licencias). La portada dice que las descargas no incluyen Eloquence y que se instala desde la tienda. Las descargas 1.0.2 a 1.0.8, que sí lo incluían, siguen en el servidor y en `versiones.json`, pero la portada ya no las lista: con descargas libres, `buildIndex` oculta las versiones anteriores marcadas `"proprietary": true` (decisión del usuario).
  - El archivo también admite `"destino"`, una carpeta publicada distinta de la de por defecto, y `"github"` (apartado 7).
  - **En GitHub nunca**, decida lo que decida `propietariosEnTienda`: el catálogo y la versión «complementos» de GitHub van siempre sin complementos propietarios, y la variante del programa con Eloquence no se publica allí (decisión del usuario, 13 de octubre de 2026). La tienda de Tiresias los sigue mostrando porque los toma del servidor del proyecto.
- **`--incluir-propietario`** publica también Eloquence y las descargas completas:
  - variante `dist\publicacion\completa`;
  - las entradas quedan marcadas con `"proprietary": true`.

  Antes muestra el aviso y pide escribir «ASUMO LA RESPONSABILIDAD», o `--acepto-responsabilidad` en scripts. **Quien publica asume toda la responsabilidad legal.** Lo razonable es hacerlo solo en un servidor privado: una red local o una carpeta con contraseña.

## 6. Firma de código y Smart App Control

- Tiresias se compila con cx_Freeze y lleva muchas DLL y `.pyd` sin firmar.
  - En equipos con **Smart App Control** (Windows 11) o con **WDAC**, los archivos sin firmar que llegan de Internet (con la marca Zone.Identifier) pueden bloquearse.
  - **SmartScreen** avisa de los ejecutables poco conocidos.
- **`Tiresias.bat firmar`** (`tools/sign_dist.py`) firma con signtool todos los `.exe`, `.dll` y `.pyd` de `dist\Tiresias`.
  - Usa un certificado propio: `TIRESIAS_CERT_PFX` (con `TIRESIAS_CERT_PASSWORD`) o `TIRESIAS_CERT_THUMBPRINT`. Nunca crea certificados.
  - Hay que firmar **antes** de `publicar`, para que el instalador, el portable y la copia pública salgan de archivos firmados.
- **Política:**
  - Solo un certificado de firma de código de una entidad reconocida evita los bloqueos en equipos ajenos. Puede ser OV, EV o Azure Trusted Signing.
  - Un certificado autofirmado solo vale en equipos donde se haya instalado ese certificado.
- **Mientras no haya certificado:**
  - la portada y el manual explican qué hacer si Windows avisa;
  - quien descargue el ZIP con el navegador puede quitar la marca con «Desbloquear» en las propiedades del archivo, antes de descomprimirlo;
  - `Tiresias.bat desbloquear` hace lo mismo con `dist`.
  - Las actualizaciones automáticas no llevan la marca (urllib no la pone), así que les afecta menos.
- Si Smart App Control bloquea una DLL al arrancar, `app_control.report` lo explica con un mensaje hablado y en el registro.

## 7. GitHub (desde la 1.0.13)

### Estructura

Todo va en las **versiones (releases)** de `hxebolax/Tiresias`. Las URL fijas tienen la forma `https://github.com/hxebolax/Tiresias/releases/download/<etiqueta>/<archivo>`:

| Versión (etiqueta) | Contenido | Cómo se marca |
|---|---|---|
| `v<versión>` (p. ej. `v1.0.13`) | `Tiresias-<v>-instalador.exe`, `Tiresias-<v>-portable.zip`, `Tiresias-<v>-codigo-fuente.zip` y sus `.sha256`. Notas: las novedades de esa versión de `docs/novedades.html` en Markdown y la lista de descargas con su SHA-256. | Estable: «Latest» si es la estable más alta. Beta: prerelease. |
| `distribucion` | `actualizacion.json`, `versiones.json` y `catalogo.json`. Se sustituyen en cada publicación. | Prerelease (nunca sale como «la última»). |
| `complementos` | `<id>-<versión>.tiresias-addon` y su `.sha256`, **sin los complementos propietarios**. | Prerelease. |

Direcciones que lee el cliente:
- manifiesto: https://github.com/hxebolax/Tiresias/releases/download/distribucion/actualizacion.json
- catálogo: https://github.com/hxebolax/Tiresias/releases/download/distribucion/catalogo.json

Los JSON de GitHub tienen el mismo formato que los del servidor (apartado 3), con dos diferencias:
- las `url` son **absolutas** (`https://github.com/hxebolax/Tiresias/releases/download/v1.0.13/Tiresias-1.0.13-instalador.exe`, `.../download/complementos/whatsapp-1.1.0.tiresias-addon`), porque GitHub redirige cada descarga a otro dominio y una dirección relativa se resolvería mal;
- `notesUrl` es la página de la versión: `https://github.com/hxebolax/Tiresias/releases/tag/v1.0.13`.

**Los complementos propietarios nunca van a GitHub** (decisión del usuario): ni Eloquence (`PROPRIETARY_ADDONS`, o cualquier paquete con `ECI.DLL` o `.SYN`) ni los marcados `"proprietary": true` (la voz Álvaro). El motor NeuralVoices sí. Tampoco la variante del programa con Eloquence: con `--incluir-propietario` o `incluirPropietario: true` hay que publicar con `--solo-servidor`. Los ZIP portable y de código fuente se revisan otra vez antes de subirlos.

### Configuración

En `tools/publicar.json`:

```json
"github": {"repo": "hxebolax/Tiresias", "publicar": true}
```

- Sin la sección, o con `"publicar": false`, solo se publica en el servidor, como antes.
- `--solo-servidor` / `--sin-github` y `--solo-github` mandan sobre la configuración.

### Qué hace `publicar.py` en GitHub (`publishGithub`)

1. Comprueba `gh` (`gh --version`, `gh auth status`, `gh repo view`). Si falta, no tiene sesión o no ve el repositorio, se detiene **antes de compilar nada** con un mensaje que dice qué hacer.
2. Lee de «distribucion» el `versiones.json` y el `catalogo.json` ya publicados (`gh release download`). Son el estado de GitHub.
3. **Versión del programa**: crea `v<versión>` con los tres paquetes y sus `.sha256` (`gh release create`). Si ya existe, actualiza el título y las notas (`gh release edit`) y sube con `--clobber` solo los paquetes que han cambiado.
4. **Complementos**: junta los paquetes de esta publicación y las versiones anteriores ya publicadas en el servidor (`<destino>\complementos\<id>\`), quita los propietarios y sube a «complementos» los nuevos o cambiados. El catálogo conserva también las versiones que ya estaban en GitHub.
5. **Distribución** (lo último, para que el manifiesto nunca apunte a archivos que aún no están): sube `actualizacion.json`, `versiones.json` y `catalogo.json` con `--clobber`.

Con `--simular` no se llama a `gh` en ningún momento: se lista cada orden que se ejecutaría y se muestran las notas de la versión. Como no lee el estado de GitHub, la simulación supone que no hay nada publicado.

### La primera vez

1. Que el repositorio `hxebolax/Tiresias` exista y tenga al menos un commit en la rama principal: `gh release create` crea la etiqueta `v<versión>` sobre esa rama.
2. `gh auth status` debe decir que hay sesión en github.com con permiso `repo`.
3. Prueba: `Tiresias.bat publicar --simular`.
4. Publica: `Tiresias.bat publicar --notas "..."`. Se crean las tres versiones; «distribucion» y «complementos» se crean solas si no existen.
5. Comprueba en https://github.com/hxebolax/Tiresias/releases que:
   - la versión `v<versión>` sale como «Latest» con sus seis archivos;
   - «distribucion» y «complementos» salen como «Pre-release»;
   - en «complementos» no hay ni Eloquence ni la voz Álvaro.

   Abre https://github.com/hxebolax/Tiresias/releases/download/distribucion/actualizacion.json en el navegador: debe descargarse el JSON.
6. En Tiresias 1.0.13 (opción por defecto), «Buscar actualización...» y la tienda leen los dos orígenes. Las copias 1.0.12 y anteriores solo conocen el servidor del proyecto, así que el servidor debe seguir publicándose.

Límites de GitHub: cada recurso de una versión, menos de 2 GB; no hay límite práctico de tamaño total.
