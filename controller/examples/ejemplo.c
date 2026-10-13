/*
Ejemplo de uso de la API de control de Tiresias desde C.

Compilar (Símbolo del sistema de Visual Studio, 64 bits):
	cl /nologo ejemplo.c /I..\include ..\x64\tiresiasControllerClient.lib
Para 32 bits, usa la consola x86 y ..\x86\tiresiasControllerClient.lib.
(Rutas desde data\controller\examples del programa; desde el código fuente,
las bibliotecas están en ..\..\data\controller\x64 y x86.)
Copia tiresiasControllerClient.dll junto al ejecutable.
*/

#include <stdio.h>
#include "tiresiasControllerClient.h"

static error_status_t __stdcall onMark(const wchar_t* mark) {
	wprintf(L"Marca alcanzada: %ls\n", mark);
	return 0;
}

int main(void) {
	unsigned long version = 0;
	error_status_t res = tiresiasController_testIfRunning();
	if (res != 0) {
		printf("No hay ningún lector de pantalla en ejecución (error %lu)\n", res);
		return 1;
	}
	if (tiresiasController_getApiVersion(&version) == 0) {
		printf("Tiresias en ejecución, versión de la API %lu.%lu\n", version >> 16, version & 0xFFFF);
	} else {
		printf("Hay un lector compatible (por ejemplo NVDA), sin funciones propias de Tiresias\n");
	}
	tiresiasController_speakText(L"Hola desde el ejemplo en C.");
	tiresiasController_brailleMessage(L"Ejemplo en braille");
	/* Corta lo que se esté diciendo, deletrea y muestra en braille. */
	tiresiasController_speakTextEx(L"abc", TIRESIAS_SPEAK_INTERRUPT | TIRESIAS_SPEAK_SPELL | TIRESIAS_SPEAK_BRAILLE);
	/* SSML síncrono con marcas: la llamada vuelve al terminar de hablar. */
	tiresiasController_setOnSsmlMarkReachedCallback(onMark);
	tiresiasController_speakSsml(L"<speak>Uno <mark name=\"uno\"/> dos <mark name=\"dos\"/></speak>", SYMBOL_LEVEL_UNCHANGED, SPEECH_PRIORITY_NORMAL, FALSE);
	tiresiasController_setOnSsmlMarkReachedCallback(NULL);
	return 0;
}
