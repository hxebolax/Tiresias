@echo off
rem ======================================================================
rem  Tiresias - lector de pantalla
rem  Herramienta de desarrollo: entorno, requisitos, ejecucion y compilacion
rem
rem  Uso:  Tiresias.bat              (menu)
rem        Tiresias.bat entorno      (crear entorno virtual)
rem        Tiresias.bat requisitos   (instalar o actualizar requisitos)
rem        Tiresias.bat ejecutar     (ejecutar desde codigo)
rem        Tiresias.bat depurar      (ejecutar con consola y registro detallado)
rem        Tiresias.bat compilar     (compilar con cx_Freeze en dist\Tiresias)
rem        Tiresias.bat complementos (empaquetar complementos .tiresias-addon)
rem        Tiresias.bat zip          (crear el ZIP portable a partir de dist)
rem        Tiresias.bat fuente       (crear el ZIP del codigo fuente con complementos)
rem        Tiresias.bat limpiar      (borrar compilacion y temporales)
rem        Tiresias.bat todo         (entorno + requisitos + compilar + complementos + zip + fuente)
rem        Tiresias.bat pruebas      (ejecutar las pruebas automaticas)
rem        Tiresias.bat instalador   (compilar y crear el instalador .exe en dist)
rem        Tiresias.bat traducciones (extraer y compilar los catalogos de idioma)
rem        Tiresias.bat importarnvda [codigo^|dist] [carpeta de NVDA]
rem                                  (importar la configuracion de NVDA en data)
rem        Tiresias.bat desbloquear  (quitar la marca de la web a dist: Smart App Control)
rem        Tiresias.bat firmar       (firmar dist con signtool y un certificado propio)
rem        Tiresias.bat publicar [opciones]
rem                                  (publicar la version en el servidor de distribucion:
rem                                   tools\publicar.py --help; Eloquence segun tools\publicar.json)
rem ======================================================================
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul
cd /d "%~dp0"

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
set "PYW=%VENV%\Scripts\pythonw.exe"
set "PYVER=3.14"

if /i "%~1"=="publicar" goto :publicarargs
if not "%~1"=="" goto :despachar

:menu
cls
echo.
echo   ==============================================
echo     TIRESIAS - lector de pantalla (desarrollo)
echo   ==============================================
echo.
echo     1. Crear el entorno virtual (.venv)
echo     2. Instalar o actualizar los requisitos
echo     3. Ejecutar Tiresias desde el codigo
echo     4. Ejecutar en modo depuracion (consola y registro detallado)
echo     5. Compilar con cx_Freeze (portable en dist\Tiresias)
echo     6. Empaquetar los complementos (.tiresias-addon)
echo     7. Crear el ZIP portable
echo     F. Crear el ZIP del codigo fuente ^(con complementos^)
echo     I. Crear el instalador ^(Tiresias-version-instalador.exe^)
echo     T. Actualizar los catalogos de traduccion
echo     N. Importar la configuracion de NVDA ^(en data del codigo o de dist^)
echo     D. Desbloquear dist ^(quitar la marca de la web: Smart App Control^)
echo     S. Firmar dist con signtool ^(certificado propio^)
echo     P. Publicar en el servidor de distribucion
echo     8. Limpiar compilacion y archivos temporales
echo     9. Hacerlo todo (entorno, requisitos, compilar, complementos, ZIP y codigo fuente)
echo     0. Salir
echo.
set "op="
set /p "op=  Elige una opcion y pulsa Intro: "
if "%op%"=="1" (call :entorno & pause & goto menu)
if "%op%"=="2" (call :requisitos & pause & goto menu)
if "%op%"=="3" (call :ejecutar & goto menu)
if "%op%"=="4" (call :depurar & pause & goto menu)
if "%op%"=="5" (call :compilar & pause & goto menu)
if "%op%"=="6" (call :complementos & pause & goto menu)
if "%op%"=="7" (call :zip & pause & goto menu)
if /i "%op%"=="F" (call :fuente & pause & goto menu)
if /i "%op%"=="I" (call :instalador & pause & goto menu)
if /i "%op%"=="T" (call :traducciones & pause & goto menu)
if /i "%op%"=="N" (call :importarnvda & pause & goto menu)
if /i "%op%"=="D" (call :desbloquear & pause & goto menu)
if /i "%op%"=="S" (call :firmar & pause & goto menu)
if /i "%op%"=="P" (call :publicar & pause & goto menu)
if "%op%"=="8" (call :limpiar & pause & goto menu)
if "%op%"=="9" (call :todo & pause & goto menu)
if "%op%"=="0" exit /b 0
goto menu

rem ----------------------------------------------------------------------
:despachar
rem  Opcion de la linea de ordenes. El "exit /b" va fuera de cualquier bloque entre
rem  parentesis: dentro de un bloque con mas ordenes detras, cmd devuelve 0 aunque falle.
for %%o in (entorno requisitos ejecutar depurar compilar complementos zip fuente limpiar todo pruebas instalador traducciones importarnvda desbloquear firmar) do (
	if /i "%~1"=="%%o" goto :despacharopcion
)
echo Opcion desconocida: %~1
exit /b 1

:despacharopcion
call :%~1 %2 %3
exit /b %errorlevel%

:publicarargs
rem  "publicar" con todas sus opciones (tools\publicar.py --help).
call :comprobarentorno || exit /b 1
set "ARGS=%*"
"%PY%" -X utf8 tools\publicar.py !ARGS:*publicar=!
exit /b %errorlevel%

rem ----------------------------------------------------------------------
:buscarpython
set "BASEPY="
where py >nul 2>nul && (
	py -%PYVER% -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 else 1)" >nul 2>nul && set "BASEPY=py -%PYVER%"
)
if not defined BASEPY (
	where python >nul 2>nul && (
		python -c "import struct,sys; sys.exit(0 if struct.calcsize('P')==8 and sys.version.startswith('%PYVER%.') else 1)" >nul 2>nul && set "BASEPY=python"
	)
)
if not defined BASEPY (
	echo.
	echo  ERROR: no se encontro Python %PYVER% de 64 bits.
	echo  Descargalo de https://www.python.org/downloads/ y marca "Add python.exe to PATH".
	exit /b 1
)
exit /b 0

:comprobarentorno
if not exist "%PY%" (
	echo  El entorno virtual no existe. Creandolo...
	call :entorno || exit /b 1
	call :requisitos || exit /b 1
	exit /b 0
)
call :versionentorno && exit /b 0
echo  El entorno virtual no es de Python %PYVER%. Se vuelve a crear...
call :entorno || exit /b 1
call :requisitos || exit /b 1
exit /b 0

:versionentorno
rem  0 si el entorno virtual existe y es de Python %PYVER% (los paquetes compilados dependen de la version).
if not exist "%PY%" exit /b 1
"%PY%" -c "import sys; sys.exit(0 if sys.version.startswith('%PYVER%.') else 1)" >nul 2>nul
exit /b %errorlevel%

rem ----------------------------------------------------------------------
:entorno
call :buscarpython || exit /b 1
set "LIMPIAR="
if exist "%PY%" (
	call :versionentorno || set "LIMPIAR=--clear"
)
if defined LIMPIAR echo  El entorno anterior es de otra version de Python: se vacia.
echo  Creando el entorno virtual con %BASEPY% ...
%BASEPY% -m venv %LIMPIAR% "%VENV%" || (echo  ERROR creando el entorno. & exit /b 1)
"%PY%" -m pip install --upgrade pip
echo  Entorno virtual creado en %VENV%
exit /b 0

:requisitos
call :versionentorno || (call :entorno || exit /b 1)
echo  Instalando requisitos...
"%PY%" -m pip install --upgrade -r requirements.txt || (echo  ERROR instalando requisitos. & exit /b 1)
"%PY%" tools\pregenerate_comtypes.py
echo  Requisitos instalados.
exit /b 0

:ejecutar
call :comprobarentorno || exit /b 1
echo  Iniciando Tiresias...
start "" "%PYW%" "%~dp0src\tiresias.pyw"
exit /b 0

:depurar
call :comprobarentorno || exit /b 1
echo  Iniciando Tiresias en modo depuracion (Control+C o Tiresias+Q para salir)...
"%PY%" -X utf8 "%~dp0src\tiresias.pyw" --debug
exit /b 0

:compilar
call :comprobarentorno || exit /b 1
echo  Generando envolturas COM...
"%PY%" tools\pregenerate_comtypes.py
echo  Compilando con cx_Freeze (puede tardar unos minutos)...
"%PY%" setup_cxfreeze.py build_exe || (echo  ERROR en la compilacion. & exit /b 1)
echo.
echo  Listo: dist\Tiresias\Tiresias.exe
exit /b 0

:complementos
call :comprobarentorno || exit /b 1
"%PY%" tools\package_addons.py
exit /b 0

:zip
call :comprobarentorno || exit /b 1
if not exist "dist\Tiresias\Tiresias.exe" (
	echo  Primero hay que compilar ^(opcion 5^).
	exit /b 1
)
rem  Sin los datos del desarrollador (config, logs, voces...): la misma copia limpia que publicar.
"%PY%" -X utf8 -c "import os,shutil,sys; sys.path[:0]=['tools','src']; import publicar,tiresias; tmp=os.path.join('dist','zip_tmp','Tiresias'); publicar.stageProgram(os.path.join('dist','Tiresias'),tmp,includeProprietary=True); out=publicar.makePortableZip(tmp,os.path.join('dist','Tiresias-'+tiresias.VERSION+'-portable.zip')); shutil.rmtree(os.path.dirname(tmp),ignore_errors=True); print('ZIP creado en',out)" || (echo  ERROR creando el ZIP. & exit /b 1)
exit /b 0

:fuente
call :comprobarentorno || exit /b 1
"%PY%" -X utf8 tools\make_source_zip.py
exit /b %errorlevel%

:limpiar
echo  Borrando compilacion y temporales...
if exist "build" rmdir /s /q "build"
if exist "dist" rmdir /s /q "dist"
for /d /r "src" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
for /d /r "data\addons" %%d in (__pycache__) do if exist "%%d" rmdir /s /q "%%d"
echo  Hecho.
exit /b 0

:todo
call :entorno || exit /b 1
call :requisitos || exit /b 1
call :compilar || exit /b 1
call :complementos
call :zip
call :fuente
exit /b 0
:pruebas
call :comprobarentorno || exit /b 1
"%PY%" -X utf8 -m unittest discover -v tests
exit /b %errorlevel%

:traducciones
call :comprobarentorno || exit /b 1
"%PY%" -X utf8 tools\i18n.py todo
exit /b %errorlevel%

:instalador
call :comprobarentorno || exit /b 1
echo  Compilando las traducciones...
"%PY%" -X utf8 tools\i18n.py compilar
echo  Empaquetando los complementos y el catalogo...
"%PY%" -X utf8 tools\package_addons.py
"%PY%" -X utf8 tools\make_catalog.py
call :compilar || exit /b 1
echo  Creando el instalador...
"%PY%" -X utf8 tools\build_installer.py || (echo  ERROR creando el instalador. & exit /b 1)
"%PY%" -X utf8 tools\make_catalog.py
exit /b 0

:importarnvda
rem  %1: codigo (data del codigo fuente) o dist (data de dist\Tiresias); %2: carpeta de NVDA (opcional,
rem  tambien NVDA portable). Sin carpeta se usa la de NVDA instalado (carpeta nvda de APPDATA).
call :comprobarentorno || exit /b 1
set "DESTINO=%~1"
if not defined DESTINO (
	echo.
	echo   Donde se importa la configuracion de NVDA:
	echo     1. data del codigo fuente
	echo     2. data de la version compilada ^(dist\Tiresias\data^)
	set /p "DESTINO=  Elige 1 o 2 y pulsa Intro: "
)
if "!DESTINO!"=="1" set "DESTINO=codigo"
if "!DESTINO!"=="2" set "DESTINO=dist"
set "DATOS=%~dp0data"
if /i "!DESTINO!"=="dist" (
	if not exist "dist\Tiresias" (
		echo  Primero hay que compilar ^(opcion 5^).
		exit /b 1
	)
	set "DATOS=%~dp0dist\Tiresias\data"
) else if /i not "!DESTINO!"=="codigo" (
	echo  Destino desconocido: !DESTINO! ^(usa codigo o dist^)
	exit /b 1
)
set "CARPETANVDA=%~2"
if not defined CARPETANVDA if not "%~1"=="" goto :importarnvda_ejecutar
if not defined CARPETANVDA set /p "CARPETANVDA=  Carpeta de NVDA (Intro: la de NVDA instalado): "
:importarnvda_ejecutar
echo  Importando la configuracion de NVDA en !DATOS! ...
if defined CARPETANVDA (
	"%PY%" -X utf8 "%~dp0src\tiresias.pyw" --data "!DATOS!" --import-nvda-config "!CARPETANVDA!"
) else (
	"%PY%" -X utf8 "%~dp0src\tiresias.pyw" --data "!DATOS!" --import-nvda-config
)
exit /b !errorlevel!

rem ----------------------------------------------------------------------
:desbloquear
rem  Quita la marca de la web (Zone.Identifier) a todo dist: Smart App Control y
rem  WDAC bloquean las DLL sin firmar descargadas de Internet.
if not exist "dist" (
	echo  No existe la carpeta dist ^(compila primero^).
	exit /b 1
)
echo  Desbloqueando los archivos de dist ...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%~dp0dist' -Recurse -Force | Unblock-File"
if errorlevel 1 (echo  ERROR desbloqueando. & exit /b 1)
echo  Hecho. Si Smart App Control sigue bloqueando Tiresias, hay que firmarlo ^(opcion firmar^).
exit /b 0

:publicar
rem  Publica la version compilada en la carpeta web (ver docs\publicacion.md).
call :comprobarentorno || exit /b 1
"%PY%" -X utf8 tools\publicar.py
exit /b !errorlevel!

:firmar
rem  Firma los .exe, .dll y .pyd de dist\Tiresias con signtool. Nunca crea certificados:
rem  usa TIRESIAS_CERT_PFX (y TIRESIAS_CERT_PASSWORD) o TIRESIAS_CERT_THUMBPRINT.
call :comprobarentorno || exit /b 1
"%PY%" -X utf8 tools\sign_dist.py %1
exit /b !errorlevel!
