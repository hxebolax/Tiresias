/*
tiresiasNvdaWindow.exe: auxiliar de compatibilidad con NVDA.

Hace dos cosas, cada una opcional:

1. /window: crea la ventana oculta de clase "wxWindowClassNR" y título
   "NVDA". Algunas bibliotecas (por ejemplo Tolk, muy usada en audiojuegos)
   solo usan nvdaControllerClient si existe esa ventana.
2. /serve <punto de NVDA> <punto de Tiresias>: atiende el punto de conexión
   del "NVDA Controller Client" ("NvdaCtlr.<sesión>.<escritorio>") y
   reenvía cada llamada a Tiresias por la interfaz privada TiresiasRelay
   (tiresiasRelay.idl), indicando el proceso que llamó.

Va en un proceso aparte a propósito:

- Cuando NVDA arranca, busca la ventana "NVDA" y cierra (o termina a la
  fuerza) el proceso que la tiene, creyendo que es otra copia de NVDA. Así
  solo se cierra este programa y Tiresias sigue funcionando.
- Un proceso no puede soltar un punto de conexión ncalrpc sin terminar
  (RpcServerUseProtseqEp no tiene operación inversa; ni
  RpcMgmtStopServerListening ni RpcServerUnregisterIf cierran el puerto).
  Al cerrarse este programa el punto queda libre al instante para NVDA,
  que si no lo encuentra libre no puede atender a sus propios componentes.

Uso: tiresiasNvdaWindow.exe <PID de Tiresias> [/window] [/serve <nvda> <tiresias>]
Sin opciones solo crea la ventana (compatibilidad con versiones anteriores).
Termina al recibir WM_QUIT, al cerrarlo Tiresias o cuando termina el
proceso indicado. Código de salida 4: el punto de conexión de NVDA está
ocupado (NVDA está en ejecución).

Archivo escrito para Tiresias.
*/

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <sddl.h>
#include <shellapi.h>
#include <rpc.h>
#include <stdlib.h>
#include <wchar.h>
#include "tiresiasController_rpc.h"
#include "tiresiasRelay_rpc.h"

#define EXIT_ENDPOINT_BUSY 4

static DWORD g_parentPid = 0;
static handle_t g_relay = NULL;

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

/* ------------------------------------------------------------ NvdaController (reenvío) */
error_status_t srv_testIfRunning(handle_t h) {
	return rlyc_relayTestIfRunning(g_relay, callerPid(h));
}

error_status_t srv_speakText(handle_t h, const wchar_t* text) {
	return rlyc_relaySpeakText(g_relay, callerPid(h), text ? text : L"");
}

error_status_t srv_cancelSpeech(handle_t h) {
	return rlyc_relayCancelSpeech(g_relay, callerPid(h));
}

error_status_t srv_brailleMessage(handle_t h, const wchar_t* message) {
	return rlyc_relayBrailleMessage(g_relay, callerPid(h), message ? message : L"");
}

/* ------------------------------------------------------------ NvdaController2 */
error_status_t srv_getProcessId(handle_t h, unsigned long* pid) {
	(void)h;
	if (!pid) {
		return ERROR_INVALID_PARAMETER;
	}
	/* El lector que atiende es Tiresias (este programa solo reenvía). */
	*pid = g_parentPid ? g_parentPid : GetCurrentProcessId();
	return ERROR_SUCCESS;
}

/* speakSsml síncrono: la llamada a Tiresias va en otro hilo; las marcas que
   llegan por la retrollamada del reenvío se pasan al cliente original desde
   este hilo, que es el que tiene el contexto de su llamada. */
typedef struct MarkNode {
	struct MarkNode* next;
	wchar_t text[1];
} MarkNode;

typedef struct {
	CRITICAL_SECTION cs;
	HANDLE event;
	MarkNode* head;
	MarkNode* tail;
	int done;
	error_status_t result;
	unsigned long pid;
	const wchar_t* ssml;
	long symbolLevel;
	long priority;
} SsmlCall;

static __declspec(thread) SsmlCall* t_call = NULL;

error_status_t rlys_relayOnSsmlMarkReached(const wchar_t* mark) {
	SsmlCall* c = t_call;
	MarkNode* node;
	size_t len;
	if (!c) {
		return ERROR_CALL_NOT_IMPLEMENTED;
	}
	len = mark ? wcslen(mark) : 0;
	node = (MarkNode*)malloc(sizeof(MarkNode) + len * sizeof(wchar_t));
	if (!node) {
		return ERROR_OUTOFMEMORY;
	}
	node->next = NULL;
	if (len) {
		wmemcpy(node->text, mark, len);
	}
	node->text[len] = L'\0';
	EnterCriticalSection(&c->cs);
	if (c->tail) {
		c->tail->next = node;
	} else {
		c->head = node;
	}
	c->tail = node;
	LeaveCriticalSection(&c->cs);
	SetEvent(c->event);
	return ERROR_SUCCESS;
}

static DWORD WINAPI ssmlWorker(LPVOID param) {
	SsmlCall* c = (SsmlCall*)param;
	error_status_t res;
	t_call = c;
	res = rlyc_relaySpeakSsml(g_relay, c->pid, c->ssml, c->symbolLevel, c->priority, FALSE);
	t_call = NULL;
	EnterCriticalSection(&c->cs);
	c->result = res;
	c->done = 1;
	LeaveCriticalSection(&c->cs);
	SetEvent(c->event);
	return 0;
}

error_status_t srv_speakSsml(handle_t h, const wchar_t* ssml, const SYMBOL_LEVEL symbolLevel, const SPEECH_PRIORITY priority, const boolean asynchronous) {
	SsmlCall c;
	HANDLE thread;
	error_status_t result;
	unsigned long pid = callerPid(h);
	if (asynchronous) {
		return rlyc_relaySpeakSsml(g_relay, pid, ssml ? ssml : L"", (long)symbolLevel, (long)priority, TRUE);
	}
	ZeroMemory(&c, sizeof(c));
	InitializeCriticalSection(&c.cs);
	c.event = CreateEventW(NULL, FALSE, FALSE, NULL);
	c.pid = pid;
	c.ssml = ssml ? ssml : L"";
	c.symbolLevel = (long)symbolLevel;
	c.priority = (long)priority;
	if (!c.event) {
		DeleteCriticalSection(&c.cs);
		return GetLastError();
	}
	thread = CreateThread(NULL, 0, ssmlWorker, &c, 0, NULL);
	if (!thread) {
		result = GetLastError();
		CloseHandle(c.event);
		DeleteCriticalSection(&c.cs);
		return result;
	}
	for (;;) {
		MarkNode* list;
		int done;
		WaitForSingleObject(c.event, INFINITE);
		EnterCriticalSection(&c.cs);
		list = c.head;
		c.head = c.tail = NULL;
		done = c.done;
		LeaveCriticalSection(&c.cs);
		while (list) {
			MarkNode* next = list->next;
			/* Si el cliente no fijó retrollamada, responde 120: no es un error. */
			rpc_onSsmlMarkReached(list->text);
			free(list);
			list = next;
		}
		if (done) {
			EnterCriticalSection(&c.cs);
			done = c.head == NULL;
			LeaveCriticalSection(&c.cs);
			if (done) {
				break;
			}
		}
	}
	WaitForSingleObject(thread, INFINITE);
	CloseHandle(thread);
	CloseHandle(c.event);
	DeleteCriticalSection(&c.cs);
	return c.result;
}

/* ------------------------------------------------------------ NvdaController3 */
error_status_t srv_isSpeaking(handle_t h, boolean* speaking) {
	if (!speaking) {
		return ERROR_INVALID_PARAMETER;
	}
	return rlyc_relayIsSpeaking(g_relay, callerPid(h), speaking);
}

/* ------------------------------------------------------------ TiresiasController (no se registra aquí) */
error_status_t srv_getApiVersion(handle_t h, unsigned long* version) {
	(void)h;
	(void)version;
	return ERROR_CALL_NOT_IMPLEMENTED;
}

error_status_t srv_speakTextEx(handle_t h, const wchar_t* text, unsigned long flags) {
	(void)h;
	(void)text;
	(void)flags;
	return ERROR_CALL_NOT_IMPLEMENTED;
}

error_status_t srv_pauseSpeech(handle_t h, boolean pause) {
	(void)h;
	(void)pause;
	return ERROR_CALL_NOT_IMPLEMENTED;
}

/* ------------------------------------------------------------ punto de conexión */
static int startServing(const wchar_t* nvdaEndpoint, const wchar_t* tiresiasEndpoint) {
	PSECURITY_DESCRIPTOR sd = NULL;
	ULONG size = 0;
	wchar_t binding[200];
	RPC_STATUS st;
	RPC_IF_HANDLE ifs[3];
	int i;
	if (!nvdaEndpoint || !*nvdaEndpoint || !tiresiasEndpoint || !*tiresiasEndpoint) {
		return 5;
	}
	if (lstrlenW(tiresiasEndpoint) > 150) {
		return 5;
	}
	lstrcpyW(binding, L"ncalrpc:[");
	lstrcatW(binding, tiresiasEndpoint);
	lstrcatW(binding, L"]");
	if (RpcBindingFromStringBindingW((RPC_WSTR)binding, &g_relay) != RPC_S_OK) {
		return 6;
	}
	/* Todos los usuarios y los contenedores de aplicaciones, como NVDA. */
	if (!ConvertStringSecurityDescriptorToSecurityDescriptorW(L"D:(A;;GA;;;WD)(A;;GA;;;AC)", SDDL_REVISION_1, &sd, &size) || !sd) {
		return 7;
	}
	st = RpcServerUseProtseqEpW((RPC_WSTR)L"ncalrpc", RPC_C_PROTSEQ_MAX_REQS_DEFAULT, (RPC_WSTR)nvdaEndpoint, sd);
	if (st != RPC_S_OK) {
		return EXIT_ENDPOINT_BUSY;
	}
	ifs[0] = srv_NvdaController_v1_0_s_ifspec;
	ifs[1] = srv_NvdaController2_v1_0_s_ifspec;
	ifs[2] = srv_NvdaController3_v1_0_s_ifspec;
	for (i = 0; i < 3; i++) {
		st = RpcServerRegisterIf3(ifs[i], NULL, NULL, RPC_IF_AUTOLISTEN | RPC_IF_ALLOW_CALLBACKS_WITH_NO_AUTH, RPC_C_LISTEN_MAX_CALLS_DEFAULT, 0, NULL, sd);
		if (st != RPC_S_OK) {
			return 8;
		}
	}
	/* El descriptor debe seguir vivo mientras se atienda: no se libera. */
	return 0;
}

/* ------------------------------------------------------------ ventana */
static LRESULT CALLBACK wndProc(HWND hwnd, UINT msg, WPARAM wParam, LPARAM lParam) {
	if (msg == WM_DESTROY) {
		PostQuitMessage(0);
		return 0;
	}
	return DefWindowProcW(hwnd, msg, wParam, lParam);
}

static HWND createNvdaWindow(HINSTANCE hInstance) {
	WNDCLASSEXW wc;
	ZeroMemory(&wc, sizeof(wc));
	wc.cbSize = sizeof(wc);
	wc.lpfnWndProc = wndProc;
	wc.hInstance = hInstance;
	wc.lpszClassName = L"wxWindowClassNR";
	if (!RegisterClassExW(&wc)) {
		return NULL;
	}
	/* Ventana de nivel superior sin WS_VISIBLE (FindWindow no encuentra las de solo mensajes). */
	return CreateWindowExW(WS_EX_TOOLWINDOW, L"wxWindowClassNR", L"NVDA", WS_POPUP, 0, 0, 0, 0, NULL, NULL, hInstance, NULL);
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrev, PWSTR cmdLine, int show) {
	HWND hwnd = NULL;
	HANDLE parent = NULL;
	MSG msg;
	int argc = 0;
	int i;
	int wantWindow = 0;
	int anyOption = 0;
	const wchar_t* nvdaEndpoint = NULL;
	const wchar_t* tiresiasEndpoint = NULL;
	LPWSTR* argv;
	(void)hPrev;
	(void)show;
	argv = CommandLineToArgvW(GetCommandLineW(), &argc);
	if (!argv) {
		return 1;
	}
	/* argv[0] es el programa; argv[1], el PID de Tiresias. */
	if (argc > 1) {
		g_parentPid = (DWORD)wcstoul(argv[1], NULL, 10);
	}
	for (i = 2; i < argc; i++) {
		if (lstrcmpiW(argv[i], L"/window") == 0) {
			wantWindow = 1;
			anyOption = 1;
		} else if (lstrcmpiW(argv[i], L"/serve") == 0 && i + 2 < argc) {
			nvdaEndpoint = argv[i + 1];
			tiresiasEndpoint = argv[i + 2];
			anyOption = 1;
			i += 2;
		}
	}
	if (!anyOption) {
		wantWindow = 1;
	}
	if (g_parentPid) {
		parent = OpenProcess(SYNCHRONIZE, FALSE, g_parentPid);
		if (!parent) {
			return 1;
		}
	}
	if (nvdaEndpoint) {
		int res = startServing(nvdaEndpoint, tiresiasEndpoint);
		if (res != 0) {
			return res;
		}
	}
	if (wantWindow) {
		hwnd = createNvdaWindow(hInstance);
		if (!hwnd) {
			return nvdaEndpoint ? 3 : 2;
		}
	}
	(void)cmdLine;
	for (;;) {
		DWORD res = MsgWaitForMultipleObjects(parent ? 1 : 0, parent ? &parent : NULL, FALSE, INFINITE, QS_ALLINPUT);
		if (parent && res == WAIT_OBJECT_0) {
			break;
		}
		while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
			if (msg.message == WM_QUIT) {
				goto done;
			}
			TranslateMessage(&msg);
			DispatchMessageW(&msg);
		}
	}
done:
	if (hwnd && IsWindow(hwnd)) {
		DestroyWindow(hwnd);
	}
	if (parent) {
		CloseHandle(parent);
	}
	LocalFree(argv);
	/* Al terminar el proceso el sistema cierra el puerto del punto de conexión. */
	ExitProcess(0);
	return 0;
}
