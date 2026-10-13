/*
 * tiresiasSapi32.exe: proceso auxiliar de 32 bits de Tiresias para las voces
 * SAPI 5 de 32 bits y los motores SAPI 4 (que solo existen en 32 bits).
 *
 * Tiresias es de 64 bits y no puede cargar en su proceso los motores de voz de
 * 32 bits. Este programa los carga, sintetiza en memoria (PCM de 16 bits,
 * 22050 Hz, mono) y devuelve el audio por la salida estándar. Tiresias lo
 * reproduce con su propio reproductor (corte inmediato, volumen, división del
 * sonido...). No reproduce nada por los altavoces.
 *
 * Uso: tiresiasSapi32.exe sapi5|sapi4 [--parent PID]
 *
 * Protocolo (entrada y salida estándar, binario, little-endian). Cada trama:
 *   u32 longitud (bytes que siguen) | u8 tipo | datos
 *
 * Peticiones de Tiresias:
 *   'H'                                  -> 'h' texto UTF-8 «mode=..;protocol=..;rate=..;bits=16;channels=1»
 *   'L'                                  -> 'l' líneas UTF-8 «id\tnombre\tidioma\textra\n»
 *   'V' id UTF-8                         -> 'v' i32 hresult | texto UTF-8 (SAPI 4: rangos de la voz)
 *   'S' u32 seq | u32 flags | u32 rate | u32 pitch | texto UTF-8
 *        flags: bit 0 = «rate» válido, bit 1 = «pitch» válido.
 *        SAPI 5: rate = velocidad de la voz (-10..10, ISpVoice::SetRate); el tono va en el XML.
 *        SAPI 4: valores del motor para ITTSAttributes::SpeedSet y PitchSet.
 *                                        -> 'a' u32 seq | PCM ...   y al final  'd' u32 seq | i32 hresult | u8 cancelado
 *   'C' u32 seq   callar: se cancela todo enunciado con número <= seq (se atiende al instante)
 *   'Q'           terminar
 *
 * Si Tiresias termina (la tubería se cierra o su proceso muere), el auxiliar
 * también termina.
 */

#define COBJMACROS
#define WIN32_LEAN_AND_MEAN
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <objbase.h>
#include <mmreg.h>
#include <sapi.h>
#include <stdlib.h>
#include <string.h>
#include <wchar.h>
#include <stdio.h>

#define PROTOCOL_VERSION 1
#define OUT_RATE 22050
#define MAX_FRAME (8u * 1024u * 1024u)
#define MAX_AUDIO_CHUNK 32768u
#define WM_ENGINE_NOTIFY (WM_APP + 2)
/* Segundos sin ninguna actividad del motor a partir de los que se da por colgado. */
#define ENGINE_IDLE_TIMEOUT_MS 15000
#define FLAG_RATE 1u
#define FLAG_PITCH 2u

/* ------------------------------------------------------------------ estado global */
static HANDLE g_in, g_out;
static CRITICAL_SECTION g_outLock;
static DWORD g_workerTid;
static HANDLE g_cmdEvent;
static CRITICAL_SECTION g_cmdLock;
static volatile LONG g_cancelUpTo = 0;
static volatile LONG g_curSeq = 0;
static volatile LONG g_quit = 0;
static int g_mode = 5;

typedef struct Cmd {
	struct Cmd *next;
	DWORD len;
	BYTE data[1];
} Cmd;
static Cmd *g_cmdHead, *g_cmdTail;

static BOOL isCancelled(LONG seq) {
	return g_quit || seq <= g_cancelUpTo;
}

/* ------------------------------------------------------------------ salida */
static BOOL writeAll(const void *buf, DWORD n) {
	const BYTE *p = (const BYTE *)buf;
	while (n) {
		DWORD done = 0;
		if (!WriteFile(g_out, p, n, &done, NULL) || done == 0)
			return FALSE;
		p += done;
		n -= done;
	}
	return TRUE;
}

static void sendFrame(BYTE type, const void *a, DWORD alen, const void *b, DWORD blen) {
	BYTE hdr[5];
	DWORD len = 1 + alen + blen;
	BOOL ok;
	memcpy(hdr, &len, 4);
	hdr[4] = type;
	EnterCriticalSection(&g_outLock);
	ok = writeAll(hdr, 5) && (alen == 0 || writeAll(a, alen)) && (blen == 0 || writeAll(b, blen));
	LeaveCriticalSection(&g_outLock);
	if (!ok) {
		/* Tiresias ya no lee: no tiene sentido seguir. */
		TerminateProcess(GetCurrentProcess(), 3);
	}
}

static void sendAudio(LONG seq, const BYTE *pcm, DWORD n) {
	while (n) {
		DWORD chunk = n > MAX_AUDIO_CHUNK ? MAX_AUDIO_CHUNK : n;
		if (isCancelled(seq))
			return;
		sendFrame('a', &seq, 4, pcm, chunk);
		pcm += chunk;
		n -= chunk;
	}
}

static void sendDone(LONG seq, HRESULT hr, BOOL cancelled) {
	BYTE buf[9];
	memcpy(buf, &seq, 4);
	memcpy(buf + 4, &hr, 4);
	buf[8] = cancelled ? 1 : 0;
	sendFrame('d', buf, 9, NULL, 0);
}

static void sendUtf8(BYTE type, const void *prefix, DWORD plen, const WCHAR *text) {
	int n = text && *text ? WideCharToMultiByte(CP_UTF8, 0, text, -1, NULL, 0, NULL, NULL) : 0;
	char *buf = NULL;
	if (n > 1) {
		buf = (char *)malloc(n);
		if (buf)
			WideCharToMultiByte(CP_UTF8, 0, text, -1, buf, n, NULL, NULL);
	}
	sendFrame(type, prefix, plen, buf, buf ? (DWORD)(n - 1) : 0);
	free(buf);
}

static WCHAR *utf8ToWide(const BYTE *s, DWORD n) {
	int w = n ? MultiByteToWideChar(CP_UTF8, 0, (const char *)s, (int)n, NULL, 0) : 0;
	WCHAR *out = (WCHAR *)calloc((size_t)w + 1, sizeof(WCHAR));
	if (out && w)
		MultiByteToWideChar(CP_UTF8, 0, (const char *)s, (int)n, out, w);
	return out;
}

/* Texto dinámico (para la lista de voces). */
typedef struct {
	WCHAR *p;
	size_t len, cap;
} WBuf;

static void wbAppend(WBuf *b, const WCHAR *s) {
	size_t n = s ? wcslen(s) : 0;
	if (b->len + n + 1 > b->cap) {
		size_t cap = (b->cap ? b->cap * 2 : 1024);
		WCHAR *np;
		while (cap < b->len + n + 1)
			cap *= 2;
		np = (WCHAR *)realloc(b->p, cap * sizeof(WCHAR));
		if (!np)
			return;
		b->p = np;
		b->cap = cap;
	}
	if (n)
		memcpy(b->p + b->len, s, n * sizeof(WCHAR));
	b->len += n;
	b->p[b->len] = 0;
}

/* Añade un campo sin tabuladores ni saltos de línea. */
static void wbField(WBuf *b, const WCHAR *s) {
	WCHAR tmp[2] = {0, 0};
	if (!s)
		return;
	for (; *s; s++) {
		tmp[0] = (*s == L'\t' || *s == L'\r' || *s == L'\n') ? L' ' : *s;
		wbAppend(b, tmp);
	}
}

/* ------------------------------------------------------------------ bucle de mensajes */
static void s4_deliverNotify(WPARAM kind, LPARAM arg);

/* Atiende los mensajes de la cola del hilo (los motores SAPI 4 lo necesitan). */
static void pumpMessages(void) {
	MSG msg;
	while (PeekMessageW(&msg, NULL, 0, 0, PM_REMOVE)) {
		if (msg.message == WM_QUIT) {
			InterlockedExchange(&g_quit, 1);
			continue;
		}
		if (msg.hwnd == NULL && msg.message == WM_ENGINE_NOTIFY) {
			s4_deliverNotify(msg.wParam, msg.lParam);
			continue;
		}
		TranslateMessage(&msg);
		DispatchMessageW(&msg);
	}
}

/* ================================================================== SAPI 5 */
/* Flujo de salida propio: SAPI escribe aquí y el audio sale al instante. */
static ULONGLONG g_streamPos = 0;

static HRESULT STDMETHODCALLTYPE os_QueryInterface(IStream *This, REFIID riid, void **ppv) {
	if (!ppv)
		return E_POINTER;
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IStream) || IsEqualIID(riid, &IID_ISequentialStream)) {
		*ppv = This;
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}
static ULONG STDMETHODCALLTYPE os_AddRef(IStream *This) { (void)This; return 2; }
static ULONG STDMETHODCALLTYPE os_Release(IStream *This) { (void)This; return 1; }
static HRESULT STDMETHODCALLTYPE os_Read(IStream *This, void *pv, ULONG cb, ULONG *pcbRead) {
	(void)This; (void)pv; (void)cb;
	if (pcbRead)
		*pcbRead = 0;
	return E_NOTIMPL;
}
static HRESULT STDMETHODCALLTYPE os_Write(IStream *This, const void *pv, ULONG cb, ULONG *pcbWritten) {
	LONG seq = g_curSeq;
	(void)This;
	if (pv && cb && !isCancelled(seq))
		sendAudio(seq, (const BYTE *)pv, cb);
	g_streamPos += cb;
	if (pcbWritten)
		*pcbWritten = cb;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE os_Seek(IStream *This, LARGE_INTEGER move, DWORD origin, ULARGE_INTEGER *newPos) {
	LONGLONG base = 0, target;
	(void)This;
	if (origin == STREAM_SEEK_CUR || origin == STREAM_SEEK_END)
		base = (LONGLONG)g_streamPos;
	else if (origin != STREAM_SEEK_SET)
		return STG_E_INVALIDFUNCTION;
	target = base + move.QuadPart;
	if (target < 0)
		return STG_E_INVALIDFUNCTION;
	g_streamPos = (ULONGLONG)target;
	if (newPos)
		newPos->QuadPart = g_streamPos;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE os_SetSize(IStream *This, ULARGE_INTEGER size) { (void)This; (void)size; return S_OK; }
static HRESULT STDMETHODCALLTYPE os_CopyTo(IStream *This, IStream *pstm, ULARGE_INTEGER cb, ULARGE_INTEGER *r, ULARGE_INTEGER *w) {
	(void)This; (void)pstm; (void)cb; (void)r; (void)w;
	return E_NOTIMPL;
}
static HRESULT STDMETHODCALLTYPE os_Commit(IStream *This, DWORD flags) { (void)This; (void)flags; return S_OK; }
static HRESULT STDMETHODCALLTYPE os_Revert(IStream *This) { (void)This; return S_OK; }
static HRESULT STDMETHODCALLTYPE os_LockRegion(IStream *This, ULARGE_INTEGER o, ULARGE_INTEGER cb, DWORD t) {
	(void)This; (void)o; (void)cb; (void)t;
	return STG_E_INVALIDFUNCTION;
}
static HRESULT STDMETHODCALLTYPE os_UnlockRegion(IStream *This, ULARGE_INTEGER o, ULARGE_INTEGER cb, DWORD t) {
	(void)This; (void)o; (void)cb; (void)t;
	return STG_E_INVALIDFUNCTION;
}
static HRESULT STDMETHODCALLTYPE os_Stat(IStream *This, STATSTG *st, DWORD flags) {
	(void)This; (void)flags;
	if (!st)
		return E_POINTER;
	memset(st, 0, sizeof(*st));
	st->type = STGTY_STREAM;
	st->cbSize.QuadPart = g_streamPos;
	st->grfMode = STGM_WRITE;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE os_Clone(IStream *This, IStream **pp) {
	(void)This;
	if (pp)
		*pp = NULL;
	return E_NOTIMPL;
}

static IStreamVtbl g_outStreamVtbl = {
	os_QueryInterface, os_AddRef, os_Release, os_Read, os_Write, os_Seek, os_SetSize,
	os_CopyTo, os_Commit, os_Revert, os_LockRegion, os_UnlockRegion, os_Stat, os_Clone,
};
static IStream g_outStream = {&g_outStreamVtbl};

static ISpVoice *g_voice = NULL;
static ISpStream *g_spStream = NULL;

static HRESULT s5_init(void) {
	HRESULT hr;
	WAVEFORMATEX wfx;
	if (g_voice)
		return S_OK;
	hr = CoCreateInstance(&CLSID_SpVoice, NULL, CLSCTX_ALL, &IID_ISpVoice, (void **)&g_voice);
	if (FAILED(hr))
		return hr;
	hr = CoCreateInstance(&CLSID_SpStream, NULL, CLSCTX_ALL, &IID_ISpStream, (void **)&g_spStream);
	if (FAILED(hr))
		goto fail;
	memset(&wfx, 0, sizeof(wfx));
	wfx.wFormatTag = WAVE_FORMAT_PCM;
	wfx.nChannels = 1;
	wfx.nSamplesPerSec = OUT_RATE;
	wfx.wBitsPerSample = 16;
	wfx.nBlockAlign = 2;
	wfx.nAvgBytesPerSec = OUT_RATE * 2;
	hr = ISpStream_SetBaseStream(g_spStream, &g_outStream, &SPDFID_WaveFormatEx, &wfx);
	if (FAILED(hr))
		goto fail;
	hr = ISpVoice_SetOutput(g_voice, (IUnknown *)g_spStream, TRUE);
	if (FAILED(hr))
		goto fail;
	/* El volumen lo aplica el reproductor de Tiresias. */
	ISpVoice_SetVolume(g_voice, 100);
	ISpVoice_SetRate(g_voice, 0);
	return S_OK;
fail:
	if (g_spStream) {
		ISpStream_Release(g_spStream);
		g_spStream = NULL;
	}
	ISpVoice_Release(g_voice);
	g_voice = NULL;
	return hr;
}

static void s5_term(void) {
	if (g_voice) {
		ISpVoice_Speak(g_voice, NULL, SPF_ASYNC | SPF_PURGEBEFORESPEAK, NULL);
		ISpVoice_WaitUntilDone(g_voice, 500);
		ISpVoice_SetOutput(g_voice, NULL, FALSE);
		ISpVoice_Release(g_voice);
		g_voice = NULL;
	}
	if (g_spStream) {
		ISpStream_Release(g_spStream);
		g_spStream = NULL;
	}
}

static void s5_list(void) {
	ISpObjectTokenCategory *cat = NULL;
	IEnumSpObjectTokens *en = NULL;
	ULONG count = 0, i;
	WBuf out = {0};
	WCHAR uiLang[16];
	HRESULT hr = CoCreateInstance(&CLSID_SpObjectTokenCategory, NULL, CLSCTX_ALL, &IID_ISpObjectTokenCategory, (void **)&cat);
	swprintf(uiLang, 16, L"%x", (unsigned)GetUserDefaultUILanguage());
	if (SUCCEEDED(hr))
		hr = ISpObjectTokenCategory_SetId(cat, SPCAT_VOICES, FALSE);
	if (SUCCEEDED(hr))
		hr = ISpObjectTokenCategory_EnumTokens(cat, NULL, NULL, &en);
	if (SUCCEEDED(hr))
		hr = IEnumSpObjectTokens_GetCount(en, &count);
	for (i = 0; SUCCEEDED(hr) && i < count; i++) {
		ISpObjectToken *tok = NULL;
		ISpDataKey *attrs = NULL;
		WCHAR *id = NULL, *desc = NULL, *lang = NULL;
		if (FAILED(IEnumSpObjectTokens_Item(en, i, &tok)) || !tok)
			continue;
		if (FAILED(ISpObjectToken_GetId(tok, &id)) || !id) {
			ISpObjectToken_Release(tok);
			continue;
		}
		if (FAILED(ISpObjectToken_GetStringValue(tok, uiLang, &desc)) || !desc || !*desc) {
			if (desc)
				CoTaskMemFree(desc);
			desc = NULL;
			ISpObjectToken_GetStringValue(tok, NULL, &desc);
		}
		if (SUCCEEDED(ISpObjectToken_OpenKey(tok, L"Attributes", &attrs)) && attrs) {
			ISpDataKey_GetStringValue(attrs, L"Language", &lang);
			ISpDataKey_Release(attrs);
		}
		wbField(&out, id);
		wbAppend(&out, L"\t");
		wbField(&out, desc && *desc ? desc : id);
		wbAppend(&out, L"\t");
		wbField(&out, lang);
		wbAppend(&out, L"\t\n");
		CoTaskMemFree(id);
		if (desc)
			CoTaskMemFree(desc);
		if (lang)
			CoTaskMemFree(lang);
		ISpObjectToken_Release(tok);
	}
	if (en)
		IEnumSpObjectTokens_Release(en);
	if (cat)
		ISpObjectTokenCategory_Release(cat);
	sendUtf8('l', NULL, 0, out.p);
	free(out.p);
}

static void s5_setVoice(const WCHAR *id) {
	ISpObjectToken *tok = NULL;
	HRESULT hr = s5_init();
	if (SUCCEEDED(hr))
		hr = CoCreateInstance(&CLSID_SpObjectToken, NULL, CLSCTX_ALL, &IID_ISpObjectToken, (void **)&tok);
	if (SUCCEEDED(hr))
		hr = ISpObjectToken_SetId(tok, NULL, id, FALSE);
	if (SUCCEEDED(hr))
		hr = ISpVoice_SetVoice(g_voice, tok);
	if (tok)
		ISpObjectToken_Release(tok);
	sendUtf8('v', &hr, 4, L"");
}

static void s5_speak(LONG seq, DWORD flags, DWORD rate, const WCHAR *text) {
	BOOL cancelled = FALSE;
	HRESULT hr = s5_init();
	if (FAILED(hr)) {
		sendDone(seq, hr, FALSE);
		return;
	}
	InterlockedExchange(&g_curSeq, seq);
	if (isCancelled(seq)) {
		sendDone(seq, S_OK, TRUE);
		return;
	}
	if (flags & FLAG_RATE) {
		/* Velocidad base en la voz, no en el XML: algunos motores (Eloquence)
		   no atienden <rate> y otros suman las dos. */
		LONG r = (LONG)rate;
		ISpVoice_SetRate(g_voice, r < -10 ? -10 : (r > 10 ? 10 : r));
	}
	hr = ISpVoice_Speak(g_voice, text, SPF_ASYNC | SPF_IS_XML, NULL);
	if (FAILED(hr)) {
		sendDone(seq, hr, FALSE);
		return;
	}
	for (;;) {
		hr = ISpVoice_WaitUntilDone(g_voice, 20);
		if (hr == S_OK || FAILED(hr))
			break;
		pumpMessages();
		if (isCancelled(seq)) {
			/* Callar: se descarta lo pendiente en lugar de esperar al final del trozo. */
			ISpVoice_Speak(g_voice, NULL, SPF_ASYNC | SPF_PURGEBEFORESPEAK, NULL);
			ISpVoice_WaitUntilDone(g_voice, 1000);
			cancelled = TRUE;
			hr = S_OK;
			break;
		}
	}
	sendDone(seq, FAILED(hr) ? hr : S_OK, cancelled || isCancelled(seq));
}

/* ================================================================== SAPI 4 */
/* Definiciones de speech.h (SAPI 4), que ya no viene en el SDK de Windows. */
typedef unsigned __int64 QWORD, *PQWORD;
typedef struct {
	PVOID pData;
	DWORD dwSize;
} SDATA, *PSDATA;
#define TTSI_NAMELEN 262
#define LANG_LEN 64
typedef struct {
	LANGID LanguageID;
	WCHAR szDialect[LANG_LEN];
} LANGUAGEW;
typedef struct {
	GUID gEngineID;
	WCHAR szMfgName[TTSI_NAMELEN];
	WCHAR szProductName[TTSI_NAMELEN];
	GUID gModeID;
	WCHAR szModeName[TTSI_NAMELEN];
	LANGUAGEW language;
	WCHAR szSpeaker[TTSI_NAMELEN];
	WCHAR szStyle[TTSI_NAMELEN];
	WORD wGender;
	WORD wAge;
	DWORD dwFeatures;
	DWORD dwInterfaces;
	DWORD dwEngineFeatures;
} TTSMODEINFOW;

#define CHARSET_TEXT 0
#define TTSDATAFLAG_TAGGED 1
#define TTSFEATURE_VOLUME 2
#define TTSFEATURE_SPEED 4
#define TTSFEATURE_PITCH 8
#define TTSATTR_MINPITCH 0
#define TTSATTR_MAXPITCH 0xFFFF
#define TTSATTR_MINSPEED 0
#define TTSATTR_MAXSPEED 0xFFFFFFFF
#define TTSATTR_MINVOLUME 0
#define TTSATTR_MAXVOLUME 0xFFFFFFFF

#define AUDERR_NOTENOUGHDATA ((HRESULT)0x80040201L)
#define AUDERR_WAVEFORMATNOTSUPPORTED ((HRESULT)0x80040202L)
#define AUDERR_WAVEDEVICEBUSY ((HRESULT)0x80040203L)
#define AUDERR_NEEDWAVEFORMAT ((HRESULT)0x80040302L)
#define AUDERR_INVALIDNOTIFYSINK ((HRESULT)0x80040319L)
#define AUDERR_ALREADYCLAIMED ((HRESULT)0x8004031DL)
#define AUDERR_NOTCLAIMED ((HRESULT)0x8004031EL)
#define AUDERR_ALREADYSTARTED ((HRESULT)0x80040320L)

static const GUID CLSID_TTSEnumerator = {0xD67C0280, 0xC743, 0x11cd, {0x80, 0xE5, 0x00, 0xAA, 0x00, 0x3E, 0x4B, 0x50}};
static const GUID IID_ITTSEnumW = {0x6B837B20, 0x4A47, 0x101B, {0x93, 0x1A, 0x00, 0xAA, 0x00, 0x47, 0xBA, 0x4F}};
static const GUID IID_ITTSCentralW = {0x28016060, 0x4A47, 0x101B, {0x93, 0x1A, 0x00, 0xAA, 0x00, 0x47, 0xBA, 0x4F}};
static const GUID IID_ITTSAttributesW = {0x1287A280, 0x4A47, 0x101B, {0x93, 0x1A, 0x00, 0xAA, 0x00, 0x47, 0xBA, 0x4F}};
static const GUID IID_ITTSBufNotifySink = {0xE4963D40, 0xC743, 0x11cd, {0x80, 0xE5, 0x00, 0xAA, 0x00, 0x3E, 0x4B, 0x50}};
static const GUID IID_ITTSNotifySinkW = {0xC0FA8F40, 0x4A46, 0x101B, {0x93, 0x1A, 0x00, 0xAA, 0x00, 0x47, 0xBA, 0x4F}};
static const GUID IID_IAudio = {0xF546B340, 0xC743, 0x11cd, {0x80, 0xE5, 0x00, 0xAA, 0x00, 0x3E, 0x4B, 0x50}};
static const GUID IID_IAudioDest = {0x2EC34DA0, 0xC743, 0x11cd, {0x80, 0xE5, 0x00, 0xAA, 0x00, 0x3E, 0x4B, 0x50}};
static const GUID IID_IAudioDestNotifySink = {0xACB08C00, 0xC743, 0x11cd, {0x80, 0xE5, 0x00, 0xAA, 0x00, 0x3E, 0x4B, 0x50}};

/* Interfaces del motor (las llamamos nosotros). */
typedef struct ITTSCentralW ITTSCentralW;
typedef struct {
	HRESULT(STDMETHODCALLTYPE *QueryInterface)(ITTSCentralW *, REFIID, void **);
	ULONG(STDMETHODCALLTYPE *AddRef)(ITTSCentralW *);
	ULONG(STDMETHODCALLTYPE *Release)(ITTSCentralW *);
	HRESULT(STDMETHODCALLTYPE *Inject)(ITTSCentralW *, LPCWSTR);
	HRESULT(STDMETHODCALLTYPE *ModeGet)(ITTSCentralW *, TTSMODEINFOW *);
	HRESULT(STDMETHODCALLTYPE *Phoneme)(ITTSCentralW *, int, DWORD, SDATA, PSDATA);
	HRESULT(STDMETHODCALLTYPE *PosnGet)(ITTSCentralW *, PQWORD);
	HRESULT(STDMETHODCALLTYPE *TextData)(ITTSCentralW *, int, DWORD, SDATA, PVOID, IID);
	HRESULT(STDMETHODCALLTYPE *ToFileTime)(ITTSCentralW *, PQWORD, FILETIME *);
	HRESULT(STDMETHODCALLTYPE *AudioPause)(ITTSCentralW *);
	HRESULT(STDMETHODCALLTYPE *AudioResume)(ITTSCentralW *);
	HRESULT(STDMETHODCALLTYPE *AudioReset)(ITTSCentralW *);
	HRESULT(STDMETHODCALLTYPE *Register)(ITTSCentralW *, PVOID, IID, DWORD *);
	HRESULT(STDMETHODCALLTYPE *UnRegister)(ITTSCentralW *, DWORD);
} ITTSCentralWVtbl;
struct ITTSCentralW {
	const ITTSCentralWVtbl *lpVtbl;
};

typedef struct ITTSEnumW ITTSEnumW;
typedef struct {
	HRESULT(STDMETHODCALLTYPE *QueryInterface)(ITTSEnumW *, REFIID, void **);
	ULONG(STDMETHODCALLTYPE *AddRef)(ITTSEnumW *);
	ULONG(STDMETHODCALLTYPE *Release)(ITTSEnumW *);
	HRESULT(STDMETHODCALLTYPE *Next)(ITTSEnumW *, ULONG, TTSMODEINFOW *, ULONG *);
	HRESULT(STDMETHODCALLTYPE *Skip)(ITTSEnumW *, ULONG);
	HRESULT(STDMETHODCALLTYPE *Reset)(ITTSEnumW *);
	HRESULT(STDMETHODCALLTYPE *Clone)(ITTSEnumW *, ITTSEnumW **);
	HRESULT(STDMETHODCALLTYPE *Select)(ITTSEnumW *, GUID, ITTSCentralW **, IUnknown *);
} ITTSEnumWVtbl;
struct ITTSEnumW {
	const ITTSEnumWVtbl *lpVtbl;
};

typedef struct ITTSAttributesW ITTSAttributesW;
typedef struct {
	HRESULT(STDMETHODCALLTYPE *QueryInterface)(ITTSAttributesW *, REFIID, void **);
	ULONG(STDMETHODCALLTYPE *AddRef)(ITTSAttributesW *);
	ULONG(STDMETHODCALLTYPE *Release)(ITTSAttributesW *);
	HRESULT(STDMETHODCALLTYPE *PitchGet)(ITTSAttributesW *, WORD *);
	HRESULT(STDMETHODCALLTYPE *PitchSet)(ITTSAttributesW *, WORD);
	HRESULT(STDMETHODCALLTYPE *RealTimeGet)(ITTSAttributesW *, DWORD *);
	HRESULT(STDMETHODCALLTYPE *RealTimeSet)(ITTSAttributesW *, DWORD);
	HRESULT(STDMETHODCALLTYPE *SpeedGet)(ITTSAttributesW *, DWORD *);
	HRESULT(STDMETHODCALLTYPE *SpeedSet)(ITTSAttributesW *, DWORD);
	HRESULT(STDMETHODCALLTYPE *VolumeGet)(ITTSAttributesW *, DWORD *);
	HRESULT(STDMETHODCALLTYPE *VolumeSet)(ITTSAttributesW *, DWORD);
} ITTSAttributesWVtbl;
struct ITTSAttributesW {
	const ITTSAttributesWVtbl *lpVtbl;
};

typedef struct IAudioDestNotifySink IAudioDestNotifySink;
typedef struct {
	HRESULT(STDMETHODCALLTYPE *QueryInterface)(IAudioDestNotifySink *, REFIID, void **);
	ULONG(STDMETHODCALLTYPE *AddRef)(IAudioDestNotifySink *);
	ULONG(STDMETHODCALLTYPE *Release)(IAudioDestNotifySink *);
	HRESULT(STDMETHODCALLTYPE *AudioStop)(IAudioDestNotifySink *, WORD);
	HRESULT(STDMETHODCALLTYPE *AudioStart)(IAudioDestNotifySink *);
	HRESULT(STDMETHODCALLTYPE *FreeSpace)(IAudioDestNotifySink *, DWORD, BOOL);
	HRESULT(STDMETHODCALLTYPE *BookMark)(IAudioDestNotifySink *, DWORD, BOOL);
} IAudioDestNotifySinkVtbl;
struct IAudioDestNotifySink {
	const IAudioDestNotifySinkVtbl *lpVtbl;
};

/* ---- estado de SAPI 4 */
enum { AS_INVALID = 0, AS_UNCLAIMED, AS_CLAIMED, AS_STARTED };
enum { NOTIFY_AUDIOSTART = 1, NOTIFY_AUDIOSTOP, NOTIFY_FREESPACE, NOTIFY_BOOKMARK };

static struct {
	CRITICAL_SECTION lock;
	int state;
	WAVEFORMATEX wfx;
	IAudioDestNotifySink *sink;
	QWORD written;
	DWORD level;
	FILETIME startTime;
	QWORD startBytes;
	/* Conversión a 22050 Hz, 16 bits, mono. */
	double rsPos;
	short rsPrev;
} g_audio;

static struct {
	ITTSEnumW *enumerator;
	ITTSCentralW *central;
	ITTSAttributesW *attrs;
	DWORD sinkKey;
	BOOL sinkRegistered;
	TTSMODEINFOW modes[256];
	ULONG modeCount;
	BOOL listed;
	DWORD features;
	/* Seguimiento del enunciado en curso. */
	volatile LONG finalMark;
	volatile LONG finalReached;
	volatile LONG textDone;
	volatile LONG claimedThisSeq;
	volatile LONG unclaimedThisSeq;
	volatile LONG lastActivity;
} g_s4;

static void s4_touch(void) {
	InterlockedExchange(&g_s4.lastActivity, (LONG)GetTickCount());
}

static void s4_queueNotify(int kind, DWORD arg) {
	PostThreadMessageW(g_workerTid, WM_ENGINE_NOTIFY, (WPARAM)kind, (LPARAM)arg);
}

static void s4_deliverNotify(WPARAM kind, LPARAM arg) {
	IAudioDestNotifySink *sink;
	EnterCriticalSection(&g_audio.lock);
	sink = g_audio.sink;
	if (sink)
		sink->lpVtbl->AddRef(sink);
	LeaveCriticalSection(&g_audio.lock);
	if (!sink)
		return;
	switch ((int)kind) {
	case NOTIFY_AUDIOSTART:
		sink->lpVtbl->AudioStart(sink);
		break;
	case NOTIFY_AUDIOSTOP:
		sink->lpVtbl->AudioStop(sink, (WORD)arg);
		break;
	case NOTIFY_FREESPACE:
		sink->lpVtbl->FreeSpace(sink, (DWORD)arg, FALSE);
		break;
	case NOTIFY_BOOKMARK:
		sink->lpVtbl->BookMark(sink, (DWORD)arg, FALSE);
		break;
	}
	sink->lpVtbl->Release(sink);
}

static DWORD s4_bufferBytes(void) {
	/* SAPI 4 pide un búfer de al menos dos segundos. El audio no se reproduce:
	   se envía a Tiresias al instante, así que el búfer siempre está libre. */
	DWORD b = g_audio.wfx.nAvgBytesPerSec * 2;
	return b ? b : 88200;
}

/* PCM del motor -> 22050 Hz, 16 bits, mono. */
static void s4_emitPcm(LONG seq, const BYTE *buf, DWORD size) {
	const WAVEFORMATEX *w = &g_audio.wfx;
	DWORD ch = w->nChannels ? w->nChannels : 1;
	DWORD bytesPerSample = w->wBitsPerSample / 8;
	DWORD frameBytes = ch * bytesPerSample;
	DWORD frames, i;
	short *mono;
	if (!frameBytes || isCancelled(seq))
		return;
	frames = size / frameBytes;
	if (!frames)
		return;
	mono = (short *)malloc(frames * sizeof(short));
	if (!mono)
		return;
	for (i = 0; i < frames; i++) {
		const BYTE *f = buf + i * frameBytes;
		int acc = 0;
		DWORD c;
		for (c = 0; c < ch; c++) {
			if (bytesPerSample == 1)
				acc += ((int)f[c] - 128) << 8;
			else
				acc += (short)(f[c * 2] | (f[c * 2 + 1] << 8));
		}
		mono[i] = (short)(acc / (int)ch);
	}
	if (w->nSamplesPerSec == OUT_RATE) {
		sendAudio(seq, (const BYTE *)mono, frames * 2);
	} else {
		double step = (double)w->nSamplesPerSec / OUT_RATE;
		double t = g_audio.rsPos;
		size_t cap = (size_t)(frames / step) + 8, n = 0;
		short *out = (short *)malloc(cap * sizeof(short));
		if (out) {
			while (t < (double)frames - 1.0 && n < cap) {
				int idx = (int)(t < 0 ? -1 : (int)t);
				double frac = t - idx;
				double a = idx < 0 ? g_audio.rsPrev : mono[idx];
				double b = mono[idx + 1];
				out[n++] = (short)(a + (b - a) * frac);
				t += step;
			}
			g_audio.rsPos = t - frames;
			g_audio.rsPrev = mono[frames - 1];
			sendAudio(seq, (const BYTE *)out, (DWORD)(n * 2));
			free(out);
		}
	}
	free(mono);
}

/* ---- IAudio + IAudioDest propios (un único objeto estático) */
static HRESULT STDMETHODCALLTYPE au_QueryInterface(void *This, REFIID riid, void **ppv);
static ULONG STDMETHODCALLTYPE au_AddRef(void *This) { (void)This; return 2; }
static ULONG STDMETHODCALLTYPE au_Release(void *This) { (void)This; return 1; }

static HRESULT STDMETHODCALLTYPE au_Flush(void *This) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_LevelGet(void *This, DWORD *p) {
	(void)This;
	if (!p)
		return E_POINTER;
	*p = g_audio.level;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_LevelSet(void *This, DWORD v) {
	(void)This;
	g_audio.level = v;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_PassNotify(void *This, PVOID p, IID iid) {
	IAudioDestNotifySink *old;
	(void)This;
	if (!IsEqualIID(&iid, &IID_IAudioDestNotifySink))
		return AUDERR_INVALIDNOTIFYSINK;
	if (p)
		((IAudioDestNotifySink *)p)->lpVtbl->AddRef((IAudioDestNotifySink *)p);
	EnterCriticalSection(&g_audio.lock);
	old = g_audio.sink;
	g_audio.sink = (IAudioDestNotifySink *)p;
	LeaveCriticalSection(&g_audio.lock);
	if (old)
		old->lpVtbl->Release(old);
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_PosnGet(void *This, PQWORD p) {
	(void)This;
	if (!p)
		return E_POINTER;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	*p = g_audio.written;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_Claim(void *This) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (g_audio.state != AS_UNCLAIMED)
		return AUDERR_ALREADYCLAIMED;
	g_audio.state = AS_CLAIMED;
	InterlockedExchange(&g_s4.claimedThisSeq, 1);
	s4_touch();
	s4_queueNotify(NOTIFY_AUDIOSTART, 0);
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_UnClaim(void *This) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (g_audio.state == AS_UNCLAIMED)
		return AUDERR_NOTCLAIMED;
	/* Todo lo escrito ya se ha «reproducido» (se envió a Tiresias). */
	g_audio.state = AS_UNCLAIMED;
	if (g_s4.claimedThisSeq)
		InterlockedExchange(&g_s4.unclaimedThisSeq, 1);
	s4_touch();
	s4_queueNotify(NOTIFY_AUDIOSTOP, 0); /* IANSRSN_NODATA */
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_Start(void *This) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (g_audio.state == AS_STARTED)
		return AUDERR_ALREADYSTARTED;
	if (g_audio.state != AS_CLAIMED)
		return AUDERR_NOTCLAIMED;
	GetSystemTimeAsFileTime(&g_audio.startTime);
	g_audio.startBytes = g_audio.written;
	g_audio.state = AS_STARTED;
	s4_touch();
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_Stop(void *This) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (g_audio.state == AS_STARTED)
		g_audio.state = AS_CLAIMED;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_TotalGet(void *This, PQWORD p) {
	return au_PosnGet(This, p);
}
static HRESULT STDMETHODCALLTYPE au_ToFileTime(void *This, PQWORD pq, FILETIME *ft) {
	ULARGE_INTEGER u;
	(void)This;
	if (!pq || !ft)
		return E_INVALIDARG;
	if (g_audio.state == AS_INVALID || !g_audio.wfx.nAvgBytesPerSec)
		return AUDERR_NEEDWAVEFORMAT;
	u.LowPart = g_audio.startTime.dwLowDateTime;
	u.HighPart = g_audio.startTime.dwHighDateTime;
	u.QuadPart += (ULONGLONG)((LONGLONG)(*pq - g_audio.startBytes) * 10000000LL / (LONGLONG)g_audio.wfx.nAvgBytesPerSec);
	ft->dwLowDateTime = u.LowPart;
	ft->dwHighDateTime = u.HighPart;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_WaveFormatGet(void *This, PSDATA d) {
	void *p;
	(void)This;
	if (!d)
		return E_POINTER;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	p = CoTaskMemAlloc(sizeof(WAVEFORMATEX));
	if (!p)
		return E_OUTOFMEMORY;
	memcpy(p, &g_audio.wfx, sizeof(WAVEFORMATEX));
	d->pData = p;
	d->dwSize = sizeof(WAVEFORMATEX);
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_WaveFormatSet(void *This, SDATA d) {
	WAVEFORMATEX w;
	(void)This;
	/* SAPI 4 usa 18 bytes (sin el relleno final). */
	if (!d.pData || d.dwSize < 18)
		return E_INVALIDARG;
	memset(&w, 0, sizeof(w));
	memcpy(&w, d.pData, 18);
	if (g_audio.state != AS_INVALID) {
		if (memcmp(&w, &g_audio.wfx, 18) == 0)
			return S_OK;
		return AUDERR_WAVEDEVICEBUSY;
	}
	if (w.wFormatTag != WAVE_FORMAT_PCM || (w.wBitsPerSample != 8 && w.wBitsPerSample != 16) || w.nChannels < 1 ||
	    w.nChannels > 2 || w.nSamplesPerSec < 4000 || w.nSamplesPerSec > 96000)
		return AUDERR_WAVEFORMATNOTSUPPORTED;
	if (!w.nBlockAlign)
		w.nBlockAlign = (WORD)(w.nChannels * w.wBitsPerSample / 8);
	if (!w.nAvgBytesPerSec)
		w.nAvgBytesPerSec = w.nSamplesPerSec * w.nBlockAlign;
	g_audio.wfx = w;
	g_audio.state = AS_UNCLAIMED;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_FreeSpace(void *This, DWORD *bytes, BOOL *eof) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (bytes)
		*bytes = s4_bufferBytes();
	if (eof)
		*eof = FALSE;
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_DataSet(void *This, PVOID buf, DWORD size) {
	(void)This;
	if (!buf)
		return E_INVALIDARG;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	if (g_audio.state == AS_UNCLAIMED)
		return AUDERR_NOTCLAIMED;
	if (size > s4_bufferBytes())
		return AUDERR_NOTENOUGHDATA;
	s4_emitPcm(g_curSeq, (const BYTE *)buf, size);
	g_audio.written += size;
	s4_touch();
	s4_queueNotify(NOTIFY_FREESPACE, s4_bufferBytes());
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE au_BookMark(void *This, DWORD id) {
	(void)This;
	if (g_audio.state == AS_INVALID)
		return AUDERR_NEEDWAVEFORMAT;
	/* La marca se alcanza en cuanto se escribe: el audio ya ha salido. */
	s4_queueNotify(NOTIFY_BOOKMARK, id);
	return S_OK;
}

typedef struct {
	void *QueryInterface, *AddRef, *Release;
	void *Flush, *LevelGet, *LevelSet, *PassNotify, *PosnGet, *Claim, *UnClaim, *Start, *Stop, *TotalGet, *ToFileTime,
	    *WaveFormatGet, *WaveFormatSet;
} IAudioVtbl_;
typedef struct {
	void *QueryInterface, *AddRef, *Release;
	void *FreeSpace, *DataSet, *BookMark;
} IAudioDestVtbl_;

static const IAudioVtbl_ g_audioVtbl = {
	(void *)au_QueryInterface, (void *)au_AddRef, (void *)au_Release, (void *)au_Flush, (void *)au_LevelGet,
	(void *)au_LevelSet, (void *)au_PassNotify, (void *)au_PosnGet, (void *)au_Claim, (void *)au_UnClaim,
	(void *)au_Start, (void *)au_Stop, (void *)au_TotalGet, (void *)au_ToFileTime, (void *)au_WaveFormatGet,
	(void *)au_WaveFormatSet,
};
static const IAudioDestVtbl_ g_audioDestVtbl = {
	(void *)au_QueryInterface, (void *)au_AddRef, (void *)au_Release, (void *)au_FreeSpace, (void *)au_DataSet,
	(void *)au_BookMark,
};
static struct {
	const IAudioVtbl_ *audio;
	const IAudioDestVtbl_ *dest;
} g_audioObj = {&g_audioVtbl, &g_audioDestVtbl};

static HRESULT STDMETHODCALLTYPE au_QueryInterface(void *This, REFIID riid, void **ppv) {
	(void)This;
	if (!ppv)
		return E_POINTER;
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IAudio)) {
		*ppv = &g_audioObj.audio;
		return S_OK;
	}
	if (IsEqualIID(riid, &IID_IAudioDest)) {
		*ppv = &g_audioObj.dest;
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}

/* ---- ITTSNotifySinkW y ITTSBufNotifySink propios */
static HRESULT STDMETHODCALLTYPE ns_QueryInterface(void *This, REFIID riid, void **ppv) {
	if (!ppv)
		return E_POINTER;
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_ITTSNotifySinkW)) {
		*ppv = This;
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}
static HRESULT STDMETHODCALLTYPE ns_AttribChanged(void *This, DWORD a) { (void)This; (void)a; return S_OK; }
static HRESULT STDMETHODCALLTYPE ns_AudioStart(void *This, QWORD t) { (void)This; (void)t; s4_touch(); return S_OK; }
static HRESULT STDMETHODCALLTYPE ns_AudioStop(void *This, QWORD t) { (void)This; (void)t; s4_touch(); return S_OK; }
static HRESULT STDMETHODCALLTYPE ns_Visual(void *This, QWORD t, WCHAR a, WCHAR b, DWORD f, void *m) {
	(void)This; (void)t; (void)a; (void)b; (void)f; (void)m;
	return S_OK;
}
static const struct {
	void *QueryInterface, *AddRef, *Release, *AttribChanged, *AudioStart, *AudioStop, *Visual;
} g_notifyVtbl = {
	(void *)ns_QueryInterface, (void *)au_AddRef, (void *)au_Release, (void *)ns_AttribChanged,
	(void *)ns_AudioStart, (void *)ns_AudioStop, (void *)ns_Visual,
};
static struct {
	const void *vtbl;
} g_notifySink = {&g_notifyVtbl};

static HRESULT STDMETHODCALLTYPE bs_QueryInterface(void *This, REFIID riid, void **ppv) {
	if (!ppv)
		return E_POINTER;
	if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_ITTSBufNotifySink)) {
		*ppv = This;
		return S_OK;
	}
	*ppv = NULL;
	return E_NOINTERFACE;
}
static HRESULT STDMETHODCALLTYPE bs_TextDataDone(void *This, QWORD t, DWORD f) {
	(void)This; (void)t; (void)f;
	InterlockedExchange(&g_s4.textDone, 1);
	s4_touch();
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE bs_TextDataStarted(void *This, QWORD t) { (void)This; (void)t; s4_touch(); return S_OK; }
static HRESULT STDMETHODCALLTYPE bs_BookMark(void *This, QWORD t, DWORD mark) {
	(void)This; (void)t;
	if ((LONG)mark == g_s4.finalMark)
		InterlockedExchange(&g_s4.finalReached, 1);
	s4_touch();
	return S_OK;
}
static HRESULT STDMETHODCALLTYPE bs_WordPosition(void *This, QWORD t, DWORD p) { (void)This; (void)t; (void)p; return S_OK; }
static const struct {
	void *QueryInterface, *AddRef, *Release, *TextDataDone, *TextDataStarted, *BookMark, *WordPosition;
} g_bufVtbl = {
	(void *)bs_QueryInterface, (void *)au_AddRef, (void *)au_Release, (void *)bs_TextDataDone,
	(void *)bs_TextDataStarted, (void *)bs_BookMark, (void *)bs_WordPosition,
};
static struct {
	const void *vtbl;
} g_bufSink = {&g_bufVtbl};

/* ---- operaciones de SAPI 4 */
static HRESULT s4_enum(void) {
	HRESULT hr;
	if (g_s4.enumerator)
		return S_OK;
	hr = CoCreateInstance(&CLSID_TTSEnumerator, NULL, CLSCTX_ALL, &IID_ITTSEnumW, (void **)&g_s4.enumerator);
	if (FAILED(hr))
		g_s4.enumerator = NULL;
	return hr;
}

static HRESULT s4_fetchModes(void) {
	HRESULT hr = s4_enum();
	if (FAILED(hr))
		return hr;
	g_s4.modeCount = 0;
	g_s4.enumerator->lpVtbl->Reset(g_s4.enumerator);
	while (g_s4.modeCount < 256) {
		ULONG fetched = 0;
		hr = g_s4.enumerator->lpVtbl->Next(g_s4.enumerator, 1, &g_s4.modes[g_s4.modeCount], &fetched);
		if (hr != S_OK || fetched != 1)
			break;
		g_s4.modeCount++;
	}
	g_s4.listed = TRUE;
	return S_OK;
}

static void s4_list(void) {
	WBuf out = {0};
	ULONG i;
	s4_fetchModes();
	for (i = 0; i < g_s4.modeCount; i++) {
		const TTSMODEINFOW *m = &g_s4.modes[i];
		WCHAR guid[64], name[TTSI_NAMELEN * 2 + 8], lang[16], feat[16];
		StringFromGUID2(&m->gModeID, guid, 64);
		if (m->szProductName[0] && wcscmp(m->szProductName, m->szModeName) != 0)
			swprintf(name, sizeof(name) / sizeof(WCHAR), L"%.261s - %.261s", m->szModeName, m->szProductName);
		else
			swprintf(name, sizeof(name) / sizeof(WCHAR), L"%.261s", m->szModeName);
		swprintf(lang, 16, L"%x", (unsigned)m->language.LanguageID);
		swprintf(feat, 16, L"%x", (unsigned)m->dwFeatures);
		wbField(&out, guid);
		wbAppend(&out, L"\t");
		wbField(&out, name);
		wbAppend(&out, L"\t");
		wbField(&out, lang);
		wbAppend(&out, L"\t");
		wbField(&out, feat);
		wbAppend(&out, L"\n");
	}
	sendUtf8('l', NULL, 0, out.p);
	free(out.p);
}

static void s4_release(void) {
	IAudioDestNotifySink *old;
	if (g_s4.central) {
		g_s4.central->lpVtbl->AudioReset(g_s4.central);
		if (g_s4.sinkRegistered)
			g_s4.central->lpVtbl->UnRegister(g_s4.central, g_s4.sinkKey);
		g_s4.sinkRegistered = FALSE;
	}
	if (g_s4.attrs) {
		g_s4.attrs->lpVtbl->Release(g_s4.attrs);
		g_s4.attrs = NULL;
	}
	if (g_s4.central) {
		/* Algunos motores no admiten dos ITTSCentral a la vez: se suelta antes de crear otro. */
		g_s4.central->lpVtbl->Release(g_s4.central);
		g_s4.central = NULL;
	}
	pumpMessages();
	EnterCriticalSection(&g_audio.lock);
	old = g_audio.sink;
	g_audio.sink = NULL;
	g_audio.state = AS_INVALID;
	memset(&g_audio.wfx, 0, sizeof(g_audio.wfx));
	g_audio.level = 0xFFFFFFFF;
	LeaveCriticalSection(&g_audio.lock);
	if (old)
		old->lpVtbl->Release(old);
}

static void s4_term(void) {
	s4_release();
	if (g_s4.enumerator) {
		g_s4.enumerator->lpVtbl->Release(g_s4.enumerator);
		g_s4.enumerator = NULL;
	}
}

/* Selecciona un modo (voz) y averigua los márgenes de velocidad, tono y volumen. */
static void s4_setVoice(const WCHAR *id) {
	WCHAR info[256] = L"";
	GUID mode = GUID_NULL;
	ULONG i;
	HRESULT hr = S_OK;
	const TTSMODEINFOW *m = NULL;
	if (!g_s4.listed)
		hr = s4_fetchModes();
	if (SUCCEEDED(hr))
		hr = CLSIDFromString((LPCOLESTR)id, &mode);
	if (SUCCEEDED(hr)) {
		for (i = 0; i < g_s4.modeCount; i++) {
			if (IsEqualGUID(&g_s4.modes[i].gModeID, &mode)) {
				m = &g_s4.modes[i];
				break;
			}
		}
		if (!m)
			hr = E_INVALIDARG;
	}
	if (SUCCEEDED(hr)) {
		s4_release();
		hr = g_s4.enumerator->lpVtbl->Select(g_s4.enumerator, mode, &g_s4.central, (IUnknown *)&g_audioObj.audio);
		if (FAILED(hr))
			g_s4.central = NULL;
	}
	if (SUCCEEDED(hr) && g_s4.central) {
		size_t len = 0;
		g_s4.features = m->dwFeatures;
		if (SUCCEEDED(g_s4.central->lpVtbl->Register(g_s4.central, &g_notifySink, IID_ITTSNotifySinkW, &g_s4.sinkKey)))
			g_s4.sinkRegistered = TRUE;
		if (FAILED(g_s4.central->lpVtbl->QueryInterface(g_s4.central, &IID_ITTSAttributesW, (void **)&g_s4.attrs)))
			g_s4.attrs = NULL;
		if (g_s4.attrs) {
			ITTSAttributesW *a = g_s4.attrs;
			DWORD d0 = 0, dmin = 0, dmax = 0;
			WORD w0 = 0, wmin = 0, wmax = 0;
			if ((m->dwFeatures & TTSFEATURE_SPEED) && SUCCEEDED(a->lpVtbl->SpeedGet(a, &d0))) {
				a->lpVtbl->SpeedSet(a, TTSATTR_MINSPEED);
				a->lpVtbl->SpeedGet(a, &dmin);
				a->lpVtbl->SpeedSet(a, TTSATTR_MAXSPEED);
				a->lpVtbl->SpeedGet(a, &dmax);
				/* ViaVoice (y quizá otros) no lleva bien la velocidad máxima. */
				if (dmax > dmin + 1)
					dmax -= 1;
				a->lpVtbl->SpeedSet(a, d0);
				if (dmax > dmin)
					len += swprintf(info + len, 256 - len, L"rate=%lu,%lu,%lu;", dmin, dmax, d0);
			}
			if ((m->dwFeatures & TTSFEATURE_PITCH) && SUCCEEDED(a->lpVtbl->PitchGet(a, &w0))) {
				a->lpVtbl->PitchSet(a, TTSATTR_MINPITCH);
				a->lpVtbl->PitchGet(a, &wmin);
				a->lpVtbl->PitchSet(a, TTSATTR_MAXPITCH);
				a->lpVtbl->PitchGet(a, &wmax);
				a->lpVtbl->PitchSet(a, w0);
				if (wmax > wmin)
					len += swprintf(info + len, 256 - len, L"pitch=%u,%u,%u;", wmin, wmax, w0);
			}
			if ((m->dwFeatures & TTSFEATURE_VOLUME) && SUCCEEDED(a->lpVtbl->VolumeGet(a, &d0))) {
				a->lpVtbl->VolumeSet(a, TTSATTR_MINVOLUME);
				a->lpVtbl->VolumeGet(a, &dmin);
				a->lpVtbl->VolumeSet(a, TTSATTR_MAXVOLUME);
				a->lpVtbl->VolumeGet(a, &dmax);
				/* El volumen del usuario lo aplica Tiresias: el motor, al máximo. */
				if ((dmax & 0xFFFF) > (dmin & 0xFFFF))
					len += swprintf(info + len, 256 - len, L"volume=%lu,%lu;", dmin & 0xFFFF, dmax & 0xFFFF);
			}
		}
		pumpMessages();
	}
	sendUtf8('v', &hr, 4, info);
}

static void s4_speak(LONG seq, DWORD flags, DWORD rate, DWORD pitch, const WCHAR *text) {
	WCHAR *buf;
	size_t n;
	SDATA d;
	HRESULT hr;
	BOOL cancelled = FALSE;
	if (!g_s4.central) {
		if (!g_s4.listed)
			s4_fetchModes();
		if (g_s4.modeCount) {
			WCHAR guid[64];
			StringFromGUID2(&g_s4.modes[0].gModeID, guid, 64);
			/* s4_setVoice envía su propia respuesta 'v': Tiresias la descarta. */
			s4_setVoice(guid);
		}
		if (!g_s4.central) {
			sendDone(seq, E_FAIL, FALSE);
			return;
		}
	}
	InterlockedExchange(&g_curSeq, seq);
	if (isCancelled(seq)) {
		sendDone(seq, S_OK, TRUE);
		return;
	}
	if (g_s4.attrs) {
		/* Cada vez: las etiquetas del texto cambian estos valores en el motor. */
		if ((flags & FLAG_RATE) && (g_s4.features & TTSFEATURE_SPEED))
			g_s4.attrs->lpVtbl->SpeedSet(g_s4.attrs, rate);
		if ((flags & FLAG_PITCH) && (g_s4.features & TTSFEATURE_PITCH))
			g_s4.attrs->lpVtbl->PitchSet(g_s4.attrs, (WORD)pitch);
	}
	n = wcslen(text) + 64;
	buf = (WCHAR *)malloc(n * sizeof(WCHAR));
	if (!buf) {
		sendDone(seq, E_OUTOFMEMORY, FALSE);
		return;
	}
	/* Pausa mínima y marca final: algunos motores terminan justo tras el texto
	   e ignoran lo que venga después. */
	swprintf(buf, n, L"%s\\Pau=1\\\\Mrk=%ld\\", text, seq);
	g_audio.rsPos = 0;
	g_audio.rsPrev = 0;
	InterlockedExchange(&g_s4.finalMark, seq);
	InterlockedExchange(&g_s4.finalReached, 0);
	InterlockedExchange(&g_s4.textDone, 0);
	InterlockedExchange(&g_s4.claimedThisSeq, 0);
	InterlockedExchange(&g_s4.unclaimedThisSeq, 0);
	s4_touch();
	d.pData = buf;
	d.dwSize = (DWORD)((wcslen(buf) + 1) * sizeof(WCHAR));
	hr = g_s4.central->lpVtbl->TextData(g_s4.central, CHARSET_TEXT, TTSDATAFLAG_TAGGED, d, &g_bufSink, IID_ITTSBufNotifySink);
	if (FAILED(hr)) {
		free(buf);
		sendDone(seq, hr, FALSE);
		return;
	}
	for (;;) {
		MsgWaitForMultipleObjects(0, NULL, FALSE, 20, QS_ALLINPUT);
		pumpMessages();
		if (g_s4.finalReached)
			break;
		if (g_s4.textDone && g_s4.unclaimedThisSeq && g_audio.state == AS_UNCLAIMED)
			break;
		if (isCancelled(seq)) {
			DWORD until;
			g_s4.central->lpVtbl->AudioReset(g_s4.central);
			/* Se atienden las notificaciones de la cancelación antes del siguiente enunciado. */
			until = GetTickCount() + 150;
			while ((LONG)(until - GetTickCount()) > 0) {
				MsgWaitForMultipleObjects(0, NULL, FALSE, 10, QS_ALLINPUT);
				pumpMessages();
			}
			cancelled = TRUE;
			break;
		}
		if ((DWORD)(GetTickCount() - (DWORD)g_s4.lastActivity) > ENGINE_IDLE_TIMEOUT_MS) {
			g_s4.central->lpVtbl->AudioReset(g_s4.central);
			hr = HRESULT_FROM_WIN32(ERROR_TIMEOUT);
			break;
		}
	}
	free(buf);
	sendDone(seq, FAILED(hr) ? hr : S_OK, cancelled || isCancelled(seq));
}

/* ================================================================== órdenes */
static void handleCommand(const BYTE *data, DWORD len) {
	BYTE type = data[0];
	const BYTE *p = data + 1;
	DWORD n = len - 1;
	switch (type) {
	case 'H': {
		WCHAR info[160];
		swprintf(info, 160, L"mode=%s;protocol=%d;rate=%d;bits=16;channels=1;pid=%lu", g_mode == 4 ? L"sapi4" : L"sapi5",
		         PROTOCOL_VERSION, OUT_RATE, GetCurrentProcessId());
		sendUtf8('h', NULL, 0, info);
		break;
	}
	case 'L':
		if (g_mode == 4)
			s4_list();
		else
			s5_list();
		break;
	case 'V': {
		WCHAR *id = utf8ToWide(p, n);
		if (id) {
			if (g_mode == 4)
				s4_setVoice(id);
			else
				s5_setVoice(id);
			free(id);
		}
		break;
	}
	case 'S': {
		LONG seq;
		DWORD flags, rate, pitch;
		WCHAR *text;
		if (n < 16)
			break;
		memcpy(&seq, p, 4);
		memcpy(&flags, p + 4, 4);
		memcpy(&rate, p + 8, 4);
		memcpy(&pitch, p + 12, 4);
		if (isCancelled(seq)) {
			sendDone(seq, S_OK, TRUE);
			break;
		}
		text = utf8ToWide(p + 16, n - 16);
		if (!text) {
			sendDone(seq, E_OUTOFMEMORY, FALSE);
			break;
		}
		if (g_mode == 4)
			s4_speak(seq, flags, rate, pitch, text);
		else
			s5_speak(seq, flags, rate, text);
		free(text);
		break;
	}
	default:
		break;
	}
}

static Cmd *popCommand(void) {
	Cmd *c;
	EnterCriticalSection(&g_cmdLock);
	c = g_cmdHead;
	if (c) {
		g_cmdHead = c->next;
		if (!g_cmdHead)
			g_cmdTail = NULL;
	}
	LeaveCriticalSection(&g_cmdLock);
	return c;
}

static DWORD WINAPI workerProc(LPVOID ready) {
	MSG msg;
	PeekMessageW(&msg, NULL, WM_USER, WM_USER, PM_NOREMOVE);
	CoInitialize(NULL);
	SetEvent((HANDLE)ready);
	while (!g_quit) {
		Cmd *c;
		DWORD r = MsgWaitForMultipleObjects(1, &g_cmdEvent, FALSE, INFINITE, QS_ALLINPUT);
		if (r == WAIT_OBJECT_0 + 1 || r == WAIT_OBJECT_0)
			pumpMessages();
		while (!g_quit && (c = popCommand()) != NULL) {
			handleCommand(c->data, c->len);
			free(c);
			pumpMessages();
		}
	}
	if (g_mode == 4)
		s4_term();
	else
		s5_term();
	CoUninitialize();
	return 0;
}

static DWORD WINAPI parentWatch(LPVOID h) {
	WaitForSingleObject((HANDLE)h, INFINITE);
	/* Tiresias ha terminado (aunque sea de golpe): el auxiliar también. */
	TerminateProcess(GetCurrentProcess(), 0);
	return 0;
}

static BOOL readAll(void *buf, DWORD n) {
	BYTE *p = (BYTE *)buf;
	while (n) {
		DWORD got = 0;
		if (!ReadFile(g_in, p, n, &got, NULL) || got == 0)
			return FALSE;
		p += got;
		n -= got;
	}
	return TRUE;
}

int wmain(int argc, wchar_t **argv) {
	HANDLE ready, worker;
	int i;
	/* Sin cuadros de diálogo de error si un motor falla: el usuario no los vería. */
	SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
	SetDllDirectoryW(L"");
	for (i = 1; i < argc; i++) {
		if (_wcsicmp(argv[i], L"sapi4") == 0)
			g_mode = 4;
		else if (_wcsicmp(argv[i], L"sapi5") == 0)
			g_mode = 5;
		else if (_wcsicmp(argv[i], L"--parent") == 0 && i + 1 < argc) {
			DWORD pid = (DWORD)wcstoul(argv[++i], NULL, 10);
			HANDLE h = pid ? OpenProcess(SYNCHRONIZE, FALSE, pid) : NULL;
			if (h) {
				HANDLE t = CreateThread(NULL, 0, parentWatch, h, 0, NULL);
				if (t)
					CloseHandle(t);
			} else if (pid) {
				return 2;
			}
		}
	}
	g_in = GetStdHandle(STD_INPUT_HANDLE);
	g_out = GetStdHandle(STD_OUTPUT_HANDLE);
	if (!g_in || g_in == INVALID_HANDLE_VALUE || !g_out || g_out == INVALID_HANDLE_VALUE)
		return 1;
	InitializeCriticalSection(&g_outLock);
	InitializeCriticalSection(&g_cmdLock);
	InitializeCriticalSection(&g_audio.lock);
	g_audio.level = 0xFFFFFFFF;
	g_cmdEvent = CreateEventW(NULL, FALSE, FALSE, NULL);
	ready = CreateEventW(NULL, TRUE, FALSE, NULL);
	worker = CreateThread(NULL, 0, workerProc, ready, 0, &g_workerTid);
	if (!worker || !g_cmdEvent || !ready)
		return 1;
	WaitForSingleObject(ready, 10000);
	for (;;) {
		DWORD len;
		Cmd *c;
		if (!readAll(&len, 4) || len < 1 || len > MAX_FRAME)
			break;
		c = (Cmd *)malloc(sizeof(Cmd) + len);
		if (!c)
			break;
		c->next = NULL;
		c->len = len;
		if (!readAll(c->data, len)) {
			free(c);
			break;
		}
		if (c->data[0] == 'C') {
			/* Callar se atiende aquí mismo, aunque el hilo de voz esté ocupado. */
			if (len >= 5) {
				LONG seq, cur;
				memcpy(&seq, c->data + 1, 4);
				do {
					cur = g_cancelUpTo;
					if (seq <= cur)
						break;
				} while (InterlockedCompareExchange(&g_cancelUpTo, seq, cur) != cur);
			}
			free(c);
			continue;
		}
		if (c->data[0] == 'Q') {
			free(c);
			break;
		}
		EnterCriticalSection(&g_cmdLock);
		if (g_cmdTail)
			g_cmdTail->next = c;
		else
			g_cmdHead = c;
		g_cmdTail = c;
		LeaveCriticalSection(&g_cmdLock);
		SetEvent(g_cmdEvent);
	}
	InterlockedExchange(&g_quit, 1);
	SetEvent(g_cmdEvent);
	PostThreadMessageW(g_workerTid, WM_NULL, 0, 0);
	WaitForSingleObject(worker, 3000);
	/* Sin esperar a que los motores se descarguen (alguno se cuelga al hacerlo). */
	TerminateProcess(GetCurrentProcess(), 0);
	return 0;
}
