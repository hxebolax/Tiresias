/*
tiresiasControllerServer.dll: servidor RPC de la API de control de Tiresias.

Lo carga Tiresias (Python, 64 bits) con ctypes. El servidor solo traduce
las llamadas RPC a retrollamadas que fija Tiresias con tcs_initialize; toda
la lógica (voz, braille, filtros) vive en Python.

Funciones exportadas (convención __stdcall):

- tcs_initialize(callbacks): registra las interfaces (sin escuchar aún).
- tcs_listen(endpoint): añade un punto de conexión ncalrpc. Devuelve
  RPC_S_DUPLICATE_ENDPOINT si otro proceso (por ejemplo NVDA) ya lo ocupa.
- tcs_terminate(): deja de atender las interfaces.
- tcs_ssmlMarkReached(mark): solo durante speakSsml síncrono y desde el hilo
  de esa llamada: avisa al cliente de que se ha alcanzado una marca.
- tcs_setRelayPid(pid): proceso del auxiliar tiresiasNvdaWindow.exe, el único
  al que se le aceptan llamadas de la interfaz privada TiresiasRelay (el
  auxiliar atiende el punto de conexión de NVDA y reenvía aquí las llamadas
  con el proceso original; ver tiresiasRelay.idl).
- tcs_nvdaTestIfRunning / tcs_nvdaSpeakText / tcs_nvdaCancelSpeech /
  tcs_nvdaBrailleMessage / tcs_nvdaGetProcessId: cliente del punto de
  conexión de NVDA ("NvdaCtlr.<sesión>.<escritorio>"). Tiresias los usa en
  espera para hablar a través de NVDA cuando NVDA tiene preferencia.

Cada retrollamada recibe primero el identificador del proceso que llama.
Archivo escrito para Tiresias.
*/

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <sddl.h>
#include <rpc.h>
#include <stdio.h>
#include <stdlib.h>
#include "tiresiasController_rpc.h"
#include "tiresiasRelay_rpc.h"

typedef unsigned long (__stdcall *TcsTextFunc)(unsigned long pid, const wchar_t* text);
typedef unsigned long (__stdcall *TcsVoidFunc)(unsigned long pid);
typedef unsigned long (__stdcall *TcsSsmlFunc)(unsigned long pid, const wchar_t* ssml, long symbolLevel, long priority, int asynchronous);
typedef unsigned long (__stdcall *TcsBoolOutFunc)(unsigned long pid, int* value);
typedef unsigned long (__stdcall *TcsTextFlagsFunc)(unsigned long pid, const wchar_t* text, unsigned long flags);
typedef unsigned long (__stdcall *TcsBoolInFunc)(unsigned long pid, int value);

/* Debe coincidir con la estructura TcsCallbacks de tiresias/controller/server.py. */
typedef struct {
	unsigned long size;
	TcsTextFunc speakText;
	TcsVoidFunc cancelSpeech;
	TcsTextFunc brailleMessage;
	TcsSsmlFunc speakSsml;
	TcsBoolOutFunc isSpeaking;
	TcsTextFlagsFunc speakTextEx;
	TcsBoolInFunc pauseSpeech;
	TcsVoidFunc testIfRunning;
} TcsCallbacks;

#define TIRESIAS_API_VERSION 0x00010000UL

static TcsCallbacks g_cb;
static volatile LONG g_registered = 0;
static PSECURITY_DESCRIPTOR g_sd = NULL;

#define INTERFACE_COUNT 5
static RPC_IF_HANDLE g_interfaces[INTERFACE_COUNT];
/* Proceso del auxiliar que reenvía las llamadas del punto de conexión de NVDA. */
static volatile LONG g_relayPid = 0;
/* El hilo atiende ahora un relaySpeakSsml (las marcas van por la retrollamada del reenvío). */
static __declspec(thread) int t_inRelaySsml = 0;

void* __RPC_USER midl_user_allocate(size_t size) {
	return malloc(size);
}

void __RPC_USER midl_user_free(void* p) {
	free(p);
}

static unsigned long callerPid(handle_t h) {
	unsigned long pid = 0;
	if (I_RpcBindingInqLocalClientPID(h, &pid) != RPC_S_OK) {
		pid = 0;
	}
	return pid;
}

/* ------------------------------------------------------------ NvdaController */
error_status_t srv_testIfRunning(handle_t h) {
	if (!g_registered) {
		return ERROR_SERVICE_NOT_ACTIVE;
	}
	if (g_cb.testIfRunning) {
		return g_cb.testIfRunning(callerPid(h));
	}
	return ERROR_SUCCESS;
}

error_status_t srv_speakText(handle_t h, const wchar_t* text) {
	if (!g_cb.speakText) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.speakText(callerPid(h), text ? text : L"");
}

error_status_t srv_cancelSpeech(handle_t h) {
	if (!g_cb.cancelSpeech) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.cancelSpeech(callerPid(h));
}

error_status_t srv_brailleMessage(handle_t h, const wchar_t* message) {
	if (!g_cb.brailleMessage) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.brailleMessage(callerPid(h), message ? message : L"");
}

/* ------------------------------------------------------------ NvdaController2 */
error_status_t srv_getProcessId(handle_t h, unsigned long* pid) {
	(void)h;
	if (!pid) {
		return ERROR_INVALID_PARAMETER;
	}
	*pid = GetCurrentProcessId();
	return ERROR_SUCCESS;
}

error_status_t srv_speakSsml(handle_t h, const wchar_t* ssml, const SYMBOL_LEVEL symbolLevel, const SPEECH_PRIORITY priority, const boolean asynchronous) {
	if (!g_cb.speakSsml) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.speakSsml(callerPid(h), ssml ? ssml : L"", (long)symbolLevel, (long)priority, asynchronous ? 1 : 0);
}

/* ------------------------------------------------------------ NvdaController3 */
error_status_t srv_isSpeaking(handle_t h, boolean* speaking) {
	int value = 0;
	error_status_t res;
	if (!speaking) {
		return ERROR_INVALID_PARAMETER;
	}
	if (!g_cb.isSpeaking) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	res = g_cb.isSpeaking(callerPid(h), &value);
	*speaking = value ? 1 : 0;
	return res;
}

/* ------------------------------------------------------------ TiresiasController */
error_status_t srv_getApiVersion(handle_t h, unsigned long* version) {
	(void)h;
	if (!version) {
		return ERROR_INVALID_PARAMETER;
	}
	*version = TIRESIAS_API_VERSION;
	return ERROR_SUCCESS;
}

error_status_t srv_speakTextEx(handle_t h, const wchar_t* text, unsigned long flags) {
	if (!g_cb.speakTextEx) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.speakTextEx(callerPid(h), text ? text : L"", flags);
}

error_status_t srv_pauseSpeech(handle_t h, boolean pause) {
	if (!g_cb.pauseSpeech) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	return g_cb.pauseSpeech(callerPid(h), pause ? 1 : 0);
}

/* ------------------------------------------------------------ TiresiasRelay (privada) */
/* Solo se aceptan llamadas del auxiliar que ha iniciado Tiresias. */
static int relayAllowed(handle_t h) {
	unsigned long caller = callerPid(h);
	return caller != 0 && caller == (unsigned long)g_relayPid;
}

error_status_t rlys_relayTestIfRunning(handle_t h, unsigned long pid) {
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	if (!g_registered) {
		return ERROR_SERVICE_NOT_ACTIVE;
	}
	return g_cb.testIfRunning ? g_cb.testIfRunning(pid) : ERROR_SUCCESS;
}

error_status_t rlys_relaySpeakText(handle_t h, unsigned long pid, const wchar_t* text) {
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	return g_cb.speakText ? g_cb.speakText(pid, text ? text : L"") : ERROR_CALL_NOT_IMPLEMENTED;
}

error_status_t rlys_relayCancelSpeech(handle_t h, unsigned long pid) {
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	return g_cb.cancelSpeech ? g_cb.cancelSpeech(pid) : ERROR_CALL_NOT_IMPLEMENTED;
}

error_status_t rlys_relayBrailleMessage(handle_t h, unsigned long pid, const wchar_t* message) {
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	return g_cb.brailleMessage ? g_cb.brailleMessage(pid, message ? message : L"") : ERROR_CALL_NOT_IMPLEMENTED;
}

error_status_t rlys_relaySpeakSsml(handle_t h, unsigned long pid, const wchar_t* ssml, long symbolLevel, long priority, boolean asynchronous) {
	error_status_t res;
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	if (!g_cb.speakSsml) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	t_inRelaySsml = 1;
	res = g_cb.speakSsml(pid, ssml ? ssml : L"", symbolLevel, priority, asynchronous ? 1 : 0);
	t_inRelaySsml = 0;
	return res;
}

error_status_t rlys_relayIsSpeaking(handle_t h, unsigned long pid, boolean* speaking) {
	int value = 0;
	error_status_t res;
	if (!speaking) {
		return ERROR_INVALID_PARAMETER;
	}
	*speaking = 0;
	if (!relayAllowed(h)) {
		return ERROR_ACCESS_DENIED;
	}
	if (!g_cb.isSpeaking) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	res = g_cb.isSpeaking(pid, &value);
	*speaking = value ? 1 : 0;
	return res;
}

/* ------------------------------------------------------------ cliente de NVDA */
/* Retrollamada de NvdaController2 en el lado cliente: aquí no se usa speakSsml. */
error_status_t srv_onSsmlMarkReached(const wchar_t* mark) {
	(void)mark;
	return ERROR_CALL_NOT_IMPLEMENTED;
}

/* Enlace con "ncalrpc:[NvdaCtlr.<sesión>.<escritorio>]" del hilo que llama. */
static RPC_STATUS nvdaBinding(handle_t* out) {
	DWORD session = 0;
	wchar_t desk[64] = L"Default";
	wchar_t binding[200];
	HDESK hDesk;
	*out = NULL;
	ProcessIdToSessionId(GetCurrentProcessId(), &session);
	hDesk = GetThreadDesktop(GetCurrentThreadId());
	if (hDesk) {
		DWORD needed = 0;
		if (!GetUserObjectInformationW(hDesk, UOI_NAME, desk, sizeof(desk), &needed)) {
			lstrcpynW(desk, L"Default", 64);
		}
	}
	_snwprintf_s(binding, 200, _TRUNCATE, L"ncalrpc:[NvdaCtlr.%lu.%s]", (unsigned long)session, desk);
	return RpcBindingFromStringBindingW((RPC_WSTR)binding, out);
}

#define WITH_NVDA(CALL)                       \
	do {                                      \
		handle_t H = NULL;                    \
		error_status_t _st = nvdaBinding(&H); \
		if (_st != RPC_S_OK) return _st;      \
		_st = (CALL);                         \
		RpcBindingFree(&H);                   \
		return _st;                           \
	} while (0)

error_status_t __stdcall tcs_nvdaTestIfRunning(void) {
	WITH_NVDA(rpc_testIfRunning(H));
}

error_status_t __stdcall tcs_nvdaSpeakText(const wchar_t* text) {
	if (!text) return ERROR_INVALID_PARAMETER;
	WITH_NVDA(rpc_speakText(H, text));
}

error_status_t __stdcall tcs_nvdaCancelSpeech(void) {
	WITH_NVDA(rpc_cancelSpeech(H));
}

error_status_t __stdcall tcs_nvdaBrailleMessage(const wchar_t* text) {
	if (!text) return ERROR_INVALID_PARAMETER;
	WITH_NVDA(rpc_brailleMessage(H, text));
}

error_status_t __stdcall tcs_nvdaGetProcessId(unsigned long* pid) {
	if (!pid) return ERROR_INVALID_PARAMETER;
	*pid = 0;
	WITH_NVDA(rpc_getProcessId(H, pid));
}

/* ------------------------------------------------------------ exportadas */
static RPC_STATUS ensureSecurityDescriptor(void) {
	ULONG size = 0;
	if (g_sd) {
		return RPC_S_OK;
	}
	/* Todos los usuarios y los contenedores de aplicaciones (como NVDA). */
	if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(L"D:(A;;GA;;;WD)(A;;GA;;;AC)", SDDL_REVISION_1, &g_sd, &size) || !g_sd) {
		g_sd = NULL;
		return (RPC_STATUS)GetLastError();
	}
	return RPC_S_OK;
}

RPC_STATUS __stdcall tcs_initialize(const TcsCallbacks* callbacks) {
	RPC_STATUS status;
	int i;
	if (!callbacks || callbacks->size != sizeof(TcsCallbacks)) {
		return ERROR_INVALID_PARAMETER;
	}
	if (g_registered) {
		return RPC_S_ALREADY_LISTENING;
	}
	g_cb = *callbacks;
	status = ensureSecurityDescriptor();
	if (status != RPC_S_OK) {
		return status;
	}
	g_interfaces[0] = srv_NvdaController_v1_0_s_ifspec;
	g_interfaces[1] = srv_NvdaController2_v1_0_s_ifspec;
	g_interfaces[2] = srv_NvdaController3_v1_0_s_ifspec;
	g_interfaces[3] = srv_TiresiasController_v1_0_s_ifspec;
	g_interfaces[4] = rlys_TiresiasRelay_v1_0_s_ifspec;
	for (i = 0; i < INTERFACE_COUNT; i++) {
		status = RpcServerRegisterIf3(
			g_interfaces[i], NULL, NULL,
			RPC_IF_AUTOLISTEN | RPC_IF_ALLOW_CALLBACKS_WITH_NO_AUTH,
			RPC_C_LISTEN_MAX_CALLS_DEFAULT, 0, NULL, g_sd);
		if (status != RPC_S_OK) {
			while (--i >= 0) {
				RpcServerUnregisterIf(g_interfaces[i], NULL, 0);
			}
			return status;
		}
	}
	InterlockedExchange(&g_registered, 1);
	return RPC_S_OK;
}

RPC_STATUS __stdcall tcs_listen(const wchar_t* endpoint) {
	RPC_STATUS status;
	if (!endpoint || !*endpoint) {
		return ERROR_INVALID_PARAMETER;
	}
	status = ensureSecurityDescriptor();
	if (status != RPC_S_OK) {
		return status;
	}
	return RpcServerUseProtseqEpW((RPC_WSTR)L"ncalrpc", RPC_C_PROTSEQ_MAX_REQS_DEFAULT, (RPC_WSTR)endpoint, g_sd);
}

RPC_STATUS __stdcall tcs_terminate(int waitForCalls) {
	RPC_STATUS status = RPC_S_OK;
	RPC_STATUS res;
	int i;
	if (!InterlockedExchange(&g_registered, 0)) {
		return RPC_S_OK;
	}
	for (i = 0; i < INTERFACE_COUNT; i++) {
		res = RpcServerUnregisterIf(g_interfaces[i], NULL, waitForCalls ? 1 : 0);
		if (res != RPC_S_OK) {
			status = res;
		}
	}
	return status;
}

RPC_STATUS __stdcall tcs_ssmlMarkReached(const wchar_t* mark) {
	if (t_inRelaySsml) {
		return rlyc_relayOnSsmlMarkReached(mark ? mark : L"");
	}
	return rpc_onSsmlMarkReached(mark ? mark : L"");
}

void __stdcall tcs_setRelayPid(unsigned long pid) {
	InterlockedExchange(&g_relayPid, (LONG)pid);
}

unsigned long __stdcall tcs_apiVersion(void) {
	return TIRESIAS_API_VERSION;
}

BOOL WINAPI DllMain(HINSTANCE hModule, DWORD reason, LPVOID reserved) {
	(void)hModule;
	(void)reserved;
	if (reason == DLL_PROCESS_DETACH && reserved == NULL && g_sd) {
		LocalFree(g_sd);
		g_sd = NULL;
	}
	return TRUE;
}
