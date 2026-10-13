"""Revisión 1.0.11: auditoría de la inteligencia artificial.

Una o más pruebas por cada corrección (numeradas como los hallazgos de la
auditoría). No se hace ninguna petición real: los servicios se sustituyen por
un servidor HTTP local de pruebas o por dobles, y la interfaz no se muestra.

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest tests.test_rev1011_ia``
"""

from __future__ import annotations

import http.server
import json
import os
import shutil
import socket
import sys
import tempfile
import threading
import time
import types
import unittest
import urllib.error
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import imaging, paths, queue_handler, speech  # noqa: E402
from tiresias.ai import assistant  # noqa: E402  (registra las opciones de «ai»)
from tiresias.ai import agent as agentMod  # noqa: E402
from tiresias.ai import keys, providers, reading, translate  # noqa: E402
from tiresias.ai.providers import PROVIDERS, AIError, Message  # noqa: E402
from tiresias.config import conf  # noqa: E402


def _now(f, *a, **k):
	return f(*a, **k)


class _SyncThread:
	"""Sustituto de ``threading.Thread`` que ejecuta el trabajo en el acto."""

	def __init__(self, target=None, name="", daemon=None, args=(), kwargs=None) -> None:
		self.target = target
		self.args = args
		self.kwargs = kwargs or {}

	def start(self) -> None:
		self.target(*self.args, **self.kwargs)

	def is_alive(self) -> bool:
		return False


class _DataDir:
	"""Carpeta de datos propia (las claves no tocan las del usuario)."""

	def __enter__(self):
		self._old = paths.DATA_DIR
		self.path = tempfile.mkdtemp(prefix="tiresias_ia1011_")
		paths.setDataDir(self.path)
		paths.ensureDataDirs()
		return self

	def __exit__(self, *exc) -> None:
		paths.setDataDir(self._old)
		shutil.rmtree(self.path, ignore_errors=True)


class _Server(http.server.ThreadingHTTPServer):
	# En Windows SO_REUSEADDR permite que dos sockets compartan puerto: se desactiva.
	allow_reuse_address = False
	daemon_threads = True


class MockServer:
	"""Servidor HTTP local. ``script`` es una lista de respuestas, una por petición:
	``(estado, cuerpo, cabeceras)`` o ``"close"`` (corta la conexión sin responder)
	o ``("sleep", segundos)``."""

	def __init__(self, script: list) -> None:
		self.script = list(script)
		self.requests: list[dict] = []
		outer = self

		class Handler(http.server.BaseHTTPRequestHandler):
			def log_message(self, *a) -> None:
				pass

			def do_POST(self) -> None:
				n = int(self.headers.get("Content-Length", 0))
				body = json.loads(self.rfile.read(n) or b"{}")
				outer.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body})
				step = outer.script.pop(0) if outer.script else (500, {"error": {"message": "sin guion"}}, {})
				try:
					if step == "close":
						self.close_connection = True
						self.connection.shutdown(socket.SHUT_RDWR)
						return
					if step[0] == "sleep":
						time.sleep(step[1])
						return
					code, data, headers = step
					raw = json.dumps(data).encode("utf-8")
					self.send_response(code)
					self.send_header("Content-Type", "application/json")
					self.send_header("Content-Length", str(len(raw)))
					for k, v in (headers or {}).items():
						self.send_header(k, v)
					self.send_header("Connection", "close")
					self.end_headers()
					self.wfile.write(raw)
					self.wfile.flush()
					# Cerrar el socket enseguida provoca a veces un reinicio de la
					# conexión (WinError 10054) en el cliente local antes de leer.
					time.sleep(0.05)
				except OSError:
					pass

		self.httpd = _Server(("127.0.0.1", 0), Handler)
		self.url = f"http://127.0.0.1:{self.httpd.server_port}"

	def __enter__(self):
		threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
		return self

	def __exit__(self, *exc) -> None:
		self.httpd.shutdown()
		self.httpd.server_close()


def _ok(text: str = "Hola") -> tuple:
	return (200, {"content": [{"type": "text", "text": text}], "stop_reason": "end_turn"}, {})


class Base(unittest.TestCase):
	def setUp(self) -> None:
		self.spoken: list[str] = []
		self._saved = dict(conf["ai"])
		self.sleeps: list[float] = []
		patches = [
			mock.patch.object(speech, "speakMessage", side_effect=lambda t, *a, **k: self.spoken.append(t)),
			mock.patch.object(speech, "speakText", side_effect=lambda t, *a, **k: self.spoken.append(t)),
			mock.patch.object(speech, "cancelSpeech", lambda *a, **k: None),
			mock.patch.object(queue_handler, "queueFunction", side_effect=_now),
			mock.patch.object(providers, "_sleep", side_effect=lambda s: self.sleeps.append(s)),
		]
		for p in patches:
			p.start()
			self.addCleanup(p.stop)

	def tearDown(self) -> None:
		for k, v in self._saved.items():
			conf["ai"][k] = v

	def anthropic(self, url: str, key: str = "clave-de-prueba"):
		p = PROVIDERS["anthropic"]
		return mock.patch.multiple(p, baseUrl=url), mock.patch.object(keys, "getKey", lambda pid: key)


# ====================================================================== 1. carrera del agente
class AgentRaceTests(Base):
	def setUp(self) -> None:
		super().setUp()
		from tiresias import winapi
		from tiresias.gui import ai_dialogs

		self.confirms: list[str] = []
		self.release = threading.Event()
		test = self

		class Prov:
			name = "Doble"
			isRemote = False

			def isConfigured(self):
				return True

			def chat(self, msgs, system="", maxTokens=0, effort="", **k):
				task = msgs[0].text.split("\n")[0]
				if "VIEJA" in task:
					test.release.wait(5)
				return Message("assistant", '{"action": "click", "x": 1, "y": 2, "explanation": "para %s"}' % task)

		for p in (
			mock.patch.object(ai_dialogs, "showAgentConfirm", side_effect=lambda desc, cb: self.confirms.append(desc)),
			mock.patch.object(ai_dialogs, "closeAgentConfirm", lambda: None),
			mock.patch.object(winapi, "getWindowRect", return_value=(0, 0, 100, 100)),
			mock.patch.object(winapi, "getWindowText", return_value="Bloc de notas"),
			mock.patch.object(imaging, "captureRect", side_effect=lambda r, h=0: imaging.Image(bytes(100 * 100 * 4), 100, 100)),
			mock.patch.object(agentMod, "getProvider", return_value=Prov()),
			mock.patch.object(agentMod.ScreenAgent, "_rootOf", staticmethod(lambda h: h or 1)),
			mock.patch.object(agentMod.ScreenAgent, "_isOwnWindow", staticmethod(lambda h: False)),
			mock.patch.object(agentMod.ScreenAgent, "_currentTarget", lambda self: 1),
		):
			p.start()
			self.addCleanup(p.stop)

	def test_old_answer_is_ignored_after_restart(self) -> None:
		ag = agentMod.ScreenAgent()
		ag.start("tarea VIEJA", 1)
		time.sleep(0.2)
		ag.stop()
		ag.start("tarea NUEVA", 1)
		deadline = time.time() + 5
		while not self.confirms and time.time() < deadline:
			time.sleep(0.02)
		self.release.set()
		time.sleep(0.4)
		self.assertEqual(len(self.confirms), 1)
		self.assertIn("NUEVA", self.confirms[0])
		self.assertEqual(ag.stepCount, 1)
		self.assertTrue(ag.running)

	def test_late_error_does_not_stop_new_task(self) -> None:
		ag = agentMod.ScreenAgent()
		ag.running = True
		ag._gen = 5
		ag._finish("Error tardío", gen=4)
		self.assertTrue(ag.running)
		self.assertNotIn("Error tardío", self.spoken)

	def test_scheduled_step_of_old_task_is_dropped(self) -> None:
		ag = agentMod.ScreenAgent()
		ag.running = True
		ag._gen = 3
		with mock.patch.object(ag, "_nextStep") as step:
			ag._continue(2)
			step.assert_not_called()
			ag._continue(3)
			step.assert_called_once_with()


# ====================================================================== 2. traducir todo lo que se dice
class TranslateSpeechTests(Base):
	def setUp(self) -> None:
		super().setUp()
		with translate._lock:
			translate._cache.clear()
			translate._failed.clear()
			translate._pending.clear()
			translate._queue.clear()
			translate._passthrough.clear()
			translate._pausedUntil = 0.0
		conf["ai"]["translateSpeech"] = True

	def _wait(self, cond, seconds: float = 5.0) -> None:
		deadline = time.time() + seconds
		while not cond() and time.time() < deadline:
			time.sleep(0.02)

	def test_one_at_a_time_and_in_order(self) -> None:
		active = [0]
		peak = [0]
		lock = threading.Lock()

		def fake(text):
			with lock:
				active[0] += 1
				peak[0] = max(peak[0], active[0])
			n = int(text.split()[-1])
			time.sleep(0.02 * (6 - n))
			with lock:
				active[0] -= 1
			return "EN " + text

		with mock.patch.object(translate, "translateText", side_effect=fake):
			out = [translate.speechFilter(f"linea numero {i}") for i in range(6)]
			self._wait(lambda: len(self.spoken) >= 6)
		self.assertEqual(out, [""] * 6)
		self.assertEqual([s.split()[-1] for s in self.spoken], [str(i) for i in range(6)])
		self.assertEqual(peak[0], 1)

	def test_cancelled_speech_drops_queue_and_late_result(self) -> None:
		started = threading.Event()
		release = threading.Event()
		calls = []

		def fake(text):
			calls.append(text)
			started.set()
			release.wait(5)
			return "EN " + text

		with mock.patch.object(translate, "translateText", side_effect=fake):
			translate.speechFilter("primera frase")
			self.assertTrue(started.wait(5))
			translate.speechFilter("segunda frase")
			translate._onSpeechCanceled()
			release.set()
			self._wait(lambda: "primera frase" in translate._cache)
			time.sleep(0.2)
		self.assertEqual(calls, ["primera frase"])
		self.assertEqual(self.spoken, [])
		self.assertNotIn("segunda frase", translate._pending)
		# La traducción tardía se guarda: la próxima vez se dice al instante.
		self.assertEqual(translate.speechFilter("primera frase"), "EN primera frase")

	def test_speech_uses_short_timeout_without_retries(self) -> None:
		calls = []

		class Prov:
			name = "Doble"

			def chat(self, messages, system="", maxTokens=0, effort="", **kwargs):
				calls.append(kwargs)
				return Message("assistant", "Hello")

		with mock.patch.object(translate, "getProvider", return_value=Prov()):
			translate._translateForSpeech("Hola mundo")
			translate.translateText("Hola otra vez")
		self.assertEqual(calls[0], {"timeout": translate.SPEECH_TIMEOUT, "retries": 0})
		self.assertEqual(calls[1], {})
		self.assertEqual(self.spoken, ["Hello"])

	def test_account_error_disables_mode_and_says_original(self) -> None:
		err = AIError("Anthropic Claude rechazó la clave.", 401, "auth")
		with mock.patch.object(translate, "translateText", side_effect=err):
			translate._translateForSpeech("Buenas tardes")
		self.assertFalse(conf["ai"]["translateSpeech"])
		self.assertTrue(any("desactivada" in m and "rechazó la clave" in m for m in self.spoken))
		self.assertEqual(self.spoken[-1], "Buenas tardes")

	def test_network_error_pauses_requests(self) -> None:
		err = AIError("No se pudo conectar con Anthropic Claude.", kind="network")
		with mock.patch.object(translate, "translateText", side_effect=err):
			translate._translateForSpeech("Buenas noches")
		self.assertTrue(conf["ai"]["translateSpeech"])
		self.assertEqual(len([m for m in self.spoken if "en pausa" in m]), 1)
		with mock.patch.object(translate.threading, "Thread") as thr:
			self.assertEqual(translate.speechFilter("Otra frase distinta"), "Otra frase distinta")
		thr.assert_not_called()

	def test_toggle_refuses_without_configuration(self) -> None:
		conf["ai"]["translateSpeech"] = False
		conf["ai"]["provider"] = "openai"
		with mock.patch.object(keys, "getKey", lambda pid: ""):
			translate.toggleTranslateSpeech()
		self.assertFalse(conf["ai"]["translateSpeech"])
		self.assertIn("Falta la clave de OpenAI", self.spoken[-1])


# ====================================================================== 3. respuestas cortadas
class TruncationTests(Base):
	def test_anthropic_partial_text_is_marked(self) -> None:
		data = {"content": [{"type": "text", "text": "Resumen a medi"}], "stop_reason": "max_tokens"}
		p = PROVIDERS["anthropic"]
		with mock.patch.object(type(p), "key", lambda self: "k"), mock.patch.object(type(p), "_post", lambda self, *a: data):
			reply = p.chat([Message("user", "x")])
		self.assertTrue(reply.truncated)
		self.assertEqual(reply.text, "Resumen a medi")

	def test_openai_and_gemini_partial_text_is_marked(self) -> None:
		o = PROVIDERS["openai"]
		g = PROVIDERS["gemini"]
		od = {"choices": [{"message": {"content": "trozo"}, "finish_reason": "length"}]}
		gd = {"candidates": [{"content": {"parts": [{"text": "trozo"}]}, "finishReason": "MAX_TOKENS"}]}
		with mock.patch.object(keys, "getKey", lambda pid: "k"):
			with mock.patch.object(type(o), "_post", lambda self, *a: od):
				self.assertTrue(o.chat([Message("user", "x")]).truncated)
			with mock.patch.object(type(g), "_post", lambda self, *a: gd):
				self.assertTrue(g.chat([Message("user", "x")]).truncated)

	def test_chat_session_says_answer_is_incomplete(self) -> None:
		got = []

		class Prov:
			name = "Doble"

			def chat(self, messages, system=""):
				return Message("assistant", "Mitad", truncated=True)

		s = assistant.ChatSession("t", "s", Prov())
		with mock.patch.object(assistant.threading, "Thread", _SyncThread):
			s.ask("resume", onAnswer=got.append)
		self.assertIn(providers.TRUNCATED_NOTE, got[0])
		self.assertIn(providers.TRUNCATED_NOTE, s.transcript[-1][1])
		# A la API se le reenvía solo el texto del modelo.
		self.assertEqual(s.messages[-1].text, "Mitad")

	def test_default_output_limit_is_large(self) -> None:
		with MockServer([_ok()]) as srv:
			a, k = self.anthropic(srv.url)
			with a, k:
				PROVIDERS["anthropic"].chat([Message("user", "x")])
		self.assertEqual(srv.requests[0]["body"]["max_tokens"], providers.DEFAULT_MAX_TOKENS)
		self.assertGreaterEqual(providers.DEFAULT_MAX_TOKENS, 16000)

	def test_long_translation_is_split_and_marked(self) -> None:
		sent = []

		class Prov:
			def chat(self, messages, system="", maxTokens=0, effort="", **k):
				sent.append(messages[0].text)
				return Message("assistant", "ok", truncated=len(sent) == 2)

		text = ("Una frase de prueba. " * 400 + "\n\n") * 2
		with mock.patch.object(translate, "getProvider", return_value=Prov()):
			result = translate.translateText(text)
		self.assertGreater(len(sent), 1)
		for chunk in translate.splitText(text):
			self.assertLessEqual(len(chunk), translate.CHUNK_CHARS)
		self.assertEqual("".join(translate.splitText(text)), text)
		self.assertIn(translate.INCOMPLETE_NOTE, result)

	def test_reading_order_requires_all_numbers_when_cut(self) -> None:
		self.assertEqual(reading.parseOrder("2, 1, 3", 4), [1, 0, 2, 3])
		self.assertIsNone(reading.parseOrder("2, 1, 3", 4, complete=True))
		self.assertEqual(reading.parseOrder("2, 1, 4, 3", 4, complete=True), [1, 0, 3, 2])

	def test_reading_order_cut_answer_is_not_applied(self) -> None:
		node = types.SimpleNamespace(location=(0, 0, 10, 10), start=0, end=5, children=[], parent=None)
		blocks = [types.SimpleNamespace(location=(0, i * 10, 10, 10), start=0, end=5) for i in range(4)]
		buf = types.SimpleNamespace(text="hola ", nodeAt=lambda c: node, textUnitOf=lambda n: n, root=node)
		doc = types.SimpleNamespace(buffer=buf, caret=0)

		class Prov:
			name = "Doble"

			def isConfigured(self):
				return True

			def chat(self, messages, system="", maxTokens=0, effort=""):
				return Message("assistant", "2, 1, 3", truncated=True)

		with (
			mock.patch.object(assistant, "currentBrowseDocument", return_value=doc),
			mock.patch.object(reading, "chooseContainer", return_value=node),
			mock.patch.object(reading, "textBlocks", return_value=blocks),
			mock.patch.object(assistant, "getProvider", return_value=Prov()),
			mock.patch.object(reading.threading, "Thread", _SyncThread),
			mock.patch.object(reading, "_confirmOrder") as confirm,
		):
			reading.suggestReadingOrder()
		confirm.assert_not_called()
		self.assertIn("se cortó", self.spoken[-1])


# ====================================================================== 4. Gemini: modelo por defecto y 403
class GeminiModelTests(Base):
	def test_default_model_is_current(self) -> None:
		self.assertEqual(conf.defaults["ai"]["geminiModel"], "gemini-3.8-flash")
		self.assertEqual(providers.DEFAULT_GEMINI_MODEL, "gemini-3.8-flash")

	def test_403_is_permission_not_key(self) -> None:
		g = PROVIDERS["gemini"]
		conf["ai"]["geminiModel"] = "gemini-2.5-flash"
		with MockServer([(403, {"error": {"code": 403, "message": "Model access restricted", "status": "PERMISSION_DENIED"}}, {})]) as srv:
			with mock.patch.object(g, "baseUrl", srv.url + "/v1beta"), mock.patch.object(keys, "getKey", lambda pid: "gk"):
				with self.assertRaises(AIError) as cm:
					g.chat([Message("user", "x")])
		self.assertEqual(cm.exception.kind, "permission")
		self.assertIn("gemini-2.5-flash", str(cm.exception))
		self.assertNotIn("rechazó la clave", str(cm.exception))
		self.assertTrue(cm.exception.isAccountProblem)


# ====================================================================== 5. reintentos y mensajes de error
class ErrorHandlingTests(Base):
	def _call(self, script, **kw):
		with MockServer(script) as srv:
			a, k = self.anthropic(srv.url)
			with a, k:
				try:
					return PROVIDERS["anthropic"].chat([Message("user", "x")], **kw), srv
				except AIError as e:
					return e, srv

	def test_overloaded_is_retried(self) -> None:
		over = (529, {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}}, {})
		reply, srv = self._call([over, over, _ok("Por fin")])
		self.assertEqual(reply.text, "Por fin")
		self.assertEqual(len(srv.requests), 3)
		self.assertEqual(self.sleeps, [1.0, 2.0])

	def test_retry_after_is_respected_and_long_waits_are_not(self) -> None:
		limit = (429, {"error": {"type": "rate_limit_error", "message": "Rate limited"}}, {"retry-after": "3"})
		reply, srv = self._call([limit, _ok()])
		self.assertEqual(reply.text, "Hola")
		self.assertEqual(self.sleeps, [3.0])
		self.sleeps.clear()
		long = (429, {"error": {"type": "rate_limit_error", "message": "Rate limited"}}, {"retry-after": "120"})
		err, srv = self._call([long, _ok()])
		self.assertIsInstance(err, AIError)
		self.assertEqual(err.kind, "quota")
		self.assertEqual(len(srv.requests), 1)

	def test_server_error_after_retries_is_spanish(self) -> None:
		bad = (500, {"type": "error", "error": {"type": "api_error", "message": "Internal server error"}}, {})
		err, srv = self._call([bad, bad, bad])
		self.assertEqual(len(srv.requests), 3)
		self.assertEqual(err.kind, "server")
		self.assertIn("problema temporal", str(err))
		self.assertNotIn("Internal server error", str(err))

	def test_retries_zero(self) -> None:
		over = (529, {"error": {"type": "overloaded_error", "message": "Overloaded"}}, {})
		err, srv = self._call([over, _ok()], retries=0)
		self.assertEqual(err.kind, "overloaded")
		self.assertEqual(len(srv.requests), 1)
		self.assertNotIn("Overloaded", str(err))

	def test_billing_is_fatal(self) -> None:
		err, _srv = self._call([(402, {"error": {"type": "billing_error", "message": "Your credit balance is too low"}}, {})])
		self.assertEqual(err.kind, "billing")
		self.assertTrue(err.isFatal and err.isAccountProblem)
		self.assertIn("saldo", str(err))

	def test_gemini_invalid_key_is_auth(self) -> None:
		g = PROVIDERS["gemini"]
		body = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT", "details": [{"reason": "API_KEY_INVALID"}]}}
		with MockServer([(400, body, {})]) as srv:
			with mock.patch.object(g, "baseUrl", srv.url + "/v1beta"), mock.patch.object(keys, "getKey", lambda pid: "gk"):
				with self.assertRaises(AIError) as cm:
					g.chat([Message("user", "x")])
		self.assertEqual(cm.exception.kind, "auth")
		self.assertIn("rechazó la clave", str(cm.exception))

	def test_timeout_message(self) -> None:
		err, _srv = self._call([("sleep", 2.0)], timeout=1)
		self.assertEqual(err.kind, "timeout")
		self.assertIn("no respondió en 1 segundos", str(err))
		self.assertNotIn("timed out", str(err))

	def test_dns_and_refused_messages(self) -> None:
		p = PROVIDERS["anthropic"]
		with mock.patch.object(keys, "getKey", lambda pid: "k"):
			dns = urllib.error.URLError(socket.gaierror(11001, "getaddrinfo failed"))
			with mock.patch.object(providers.urllib.request, "urlopen", side_effect=dns):
				with self.assertRaises(AIError) as cm:
					p.chat([Message("user", "x")])
			self.assertIn("No se encuentra el servidor", str(cm.exception))
			self.assertNotIn("getaddrinfo", str(cm.exception))
			refused = urllib.error.URLError(ConnectionRefusedError(10061, "denegada"))
			with mock.patch.object(providers.urllib.request, "urlopen", side_effect=refused) as op:
				with self.assertRaises(AIError) as cm:
					p.chat([Message("user", "x")])
			self.assertIn("no acepta conexiones", str(cm.exception))
			# Un servidor apagado no se reintenta.
			self.assertEqual(op.call_count, 1)

	def test_non_json_answer(self) -> None:
		class Raw(http.server.BaseHTTPRequestHandler):
			def log_message(self, *a):
				pass

			def do_POST(self):
				self.rfile.read(int(self.headers.get("Content-Length", 0)))
				self.send_response(200)
				self.send_header("Content-Length", "18")
				self.send_header("Connection", "close")
				self.end_headers()
				self.wfile.write(b"<html>proxy</html>")
				self.wfile.flush()
				time.sleep(0.05)

		httpd = _Server(("127.0.0.1", 0), Raw)
		threading.Thread(target=httpd.serve_forever, daemon=True).start()
		try:
			a, k = self.anthropic(f"http://127.0.0.1:{httpd.server_port}")
			with a, k, self.assertRaises(AIError) as cm:
				PROVIDERS["anthropic"].chat([Message("user", "x")])
		finally:
			httpd.shutdown()
			httpd.server_close()
		self.assertIn("no se entiende", str(cm.exception))

	def test_log_scrubs_keys(self) -> None:
		self.assertNotIn("sk-proj-abcdef123", providers.scrub("Incorrect API key provided: sk-proj-abcdef123"))
		self.assertNotIn("mi-clave", providers.scrub("algo mi-clave algo", "mi-clave"))


# ====================================================================== 6. servidor «local» en otro equipo
class LocalServerPrivacyTests(Base):
	def test_is_local_url(self) -> None:
		for url in ("http://localhost:11434/v1", "http://127.0.0.1:1234/v1", "http://[::1]:8080/v1", "http://ollama.localhost/v1"):
			self.assertTrue(providers.isLocalUrl(url), url)
		for url in ("http://192.168.1.20:11434/v1", "https://api.example.com/v1", "", "no es una url"):
			self.assertFalse(providers.isLocalUrl(url), url)

	def test_remote_local_server_asks_and_warns_http(self) -> None:
		from tiresias.gui import ai_dialogs

		conf["ai"]["provider"] = "local"
		conf["ai"]["localUrl"] = "http://192.168.1.20:11434/v1"
		conf["ai"]["imagePrivacyAccepted"] = False
		local = PROVIDERS["local"]
		self.assertTrue(local.isRemote)
		self.assertTrue(local.insecure)
		ran = []
		with mock.patch.object(ai_dialogs, "showPrivacyNotice") as notice:
			assistant.withImagePrivacy(lambda: ran.append(1))
		self.assertEqual(ran, [])
		name, _cb, insecure = notice.call_args.args
		self.assertIn("192.168.1.20", name)
		self.assertTrue(insecure)
		self.assertIn("SIN CIFRAR", ai_dialogs.privacyText(name, True))
		conf["ai"]["localUrl"] = "http://localhost:11434/v1"
		self.assertFalse(local.isRemote)
		assistant.withImagePrivacy(lambda: ran.append(2))
		self.assertEqual(ran, [2])


# ====================================================================== 7. claves con caracteres no válidos
class KeyCharacterTests(Base):
	def test_set_key_cleans_and_rejects(self) -> None:
		with _DataDir():
			keys.setKey("anthropic", " sk-ant-​abc\n123﻿ ")
			self.assertEqual(keys.getKey("anthropic"), "sk-ant-abc123")
			with self.assertRaises(keys.InvalidKeyError) as cm:
				keys.setKey("anthropic", "sk-clavé")
			self.assertNotIn("sk-clavé", str(cm.exception))
			self.assertEqual(keys.getKey("anthropic"), "sk-ant-abc123")

	def test_env_key_is_cleaned(self) -> None:
		with _DataDir(), mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-env-1\r\n"}):
			self.assertEqual(keys.getKey("anthropic"), "sk-env-1")
			self.assertEqual(keys.envKeyVariable("anthropic"), "ANTHROPIC_API_KEY")

	def test_bad_header_never_leaks_key(self) -> None:
		p = PROVIDERS["anthropic"]
		for bad in ("clave\ncon salto", "clave€", "clave​"):
			with mock.patch.object(keys, "getKey", lambda pid, b=bad: b), mock.patch.object(providers.urllib.request, "urlopen") as op:
				with self.assertRaises(AIError) as cm:
					p.chat([Message("user", "x")])
			op.assert_not_called()
			self.assertEqual(cm.exception.kind, "auth")
			self.assertNotIn(bad, str(cm.exception))
			self.assertNotIn("latin-1", str(cm.exception))

	def test_unexpected_error_message_has_no_details(self) -> None:
		class Prov:
			name = "Doble"

			def chat(self, messages, system=""):
				raise ValueError("Invalid header value b'sk-secreta'")

		errors = []
		s = assistant.ChatSession("t", "s", Prov())
		with mock.patch.object(assistant.threading, "Thread", _SyncThread), mock.patch.object(assistant.log, "exception"):
			s.ask("hola", onError=errors.append)
		self.assertNotIn("sk-secreta", errors[0])
		self.assertIn("ValueError", errors[0])


# ====================================================================== 8. modelos de Claude
class ClaudeModelTests(Base):
	def _body(self, model: str, effort: str = "") -> tuple[dict, dict]:
		conf["ai"]["anthropicCustomModel"] = ""
		conf["ai"]["anthropicModel"] = model
		with mock.patch.object(keys, "getKey", lambda pid: "k"):
			return PROVIDERS["anthropic"].buildBody([Message("user", "x")], "", 1000, effort)

	def test_list_has_current_and_old_models(self) -> None:
		ids = [m for m, _l in providers.ANTHROPIC_MODELS]
		for mid in ("claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001"):
			self.assertIn(mid, ids)

	def test_haiku_55_effort_without_fallbacks(self) -> None:
		body, headers = self._body("claude-haiku-5-5", "low")
		self.assertEqual(body["output_config"], {"effort": "low"})
		self.assertNotIn("fallbacks", body)
		self.assertNotIn("anthropic-beta", headers)

	def test_fable_51_explicit_effort_and_fallbacks(self) -> None:
		body, headers = self._body("claude-fable-5-1")
		self.assertEqual(body["output_config"], {"effort": "medium"})
		self.assertEqual(body["fallbacks"], "default")
		self.assertEqual(headers["anthropic-beta"], "server-side-fallback-2026-07-01")

	def test_opus_and_sonnet_keep_fallbacks(self) -> None:
		for model in ("claude-opus-5-5", "claude-sonnet-5-5"):
			body, _h = self._body(model)
			self.assertEqual(body["fallbacks"], "default")

	def test_old_haiku_still_works(self) -> None:
		body, headers = self._body("claude-haiku-4-5-20251001")
		self.assertEqual(body["model"], "claude-haiku-4-5-20251001")
		self.assertNotIn("output_config", body)
		self.assertNotIn("fallbacks", body)

	def test_custom_model_wins(self) -> None:
		conf["ai"]["anthropicModel"] = "claude-opus-5-5"
		conf["ai"]["anthropicCustomModel"] = "  claude-opus-4-8 "
		self.assertEqual(PROVIDERS["anthropic"].model(), "claude-opus-4-8")
		conf["ai"]["anthropicCustomModel"] = ""
		self.assertEqual(PROVIDERS["anthropic"].model(), "claude-opus-5-5")

	def test_panel_choices_show_identifiers(self) -> None:
		from tiresias.gui import ai_dialogs

		choices = dict(ai_dialogs._anthropicModels())
		self.assertIn("claude-haiku-5-5", choices["claude-haiku-5-5"])


# ====================================================================== 9. contexto del servidor local
class LocalContextTests(Base):
	def test_local_limit_is_smaller(self) -> None:
		conf["ai"]["maxContextChars"] = 200000
		conf["ai"]["localMaxContextChars"] = 12000
		self.assertEqual(assistant.contextLimit(PROVIDERS["local"]), 12000)
		self.assertEqual(assistant.contextLimit(PROVIDERS["anthropic"]), 200000)
		conf["ai"]["maxContextChars"] = 5000
		self.assertEqual(assistant.contextLimit(PROVIDERS["local"]), 5000)

	def test_documents_are_cut_to_local_limit(self) -> None:
		conf["ai"]["provider"] = "local"
		conf["ai"]["maxContextChars"] = 200000
		conf["ai"]["localMaxContextChars"] = 3000
		text, cut = assistant._limitedText("x" * 10000)
		self.assertTrue(cut)
		self.assertEqual(len(text), 3000)


# ====================================================================== 10. permiso de imágenes por proveedor
class PrivacyPerProviderTests(Base):
	def test_accepting_one_provider_does_not_cover_another(self) -> None:
		from tiresias.gui import ai_dialogs

		conf["ai"]["imagePrivacyAccepted"] = False
		conf["ai"]["imagePrivacyProviders"] = []
		conf["ai"]["provider"] = "gemini"
		ran = []
		with mock.patch.object(ai_dialogs, "showPrivacyNotice", side_effect=lambda name, cb, insecure=False: cb()):
			assistant.withImagePrivacy(lambda: ran.append("gemini"))
		self.assertEqual(ran, ["gemini"])
		self.assertTrue(assistant.privacyAccepted(PROVIDERS["gemini"]))
		self.assertFalse(assistant.privacyAccepted(PROVIDERS["openai"]))
		conf["ai"]["provider"] = "openai"
		with mock.patch.object(ai_dialogs, "showPrivacyNotice") as notice:
			assistant.withImagePrivacy(lambda: ran.append("openai"))
		notice.assert_called_once()
		self.assertEqual(notice.call_args.args[0], "OpenAI")
		self.assertEqual(ran, ["gemini"])

	def test_old_configuration_keeps_its_permission(self) -> None:
		conf["ai"]["imagePrivacyAccepted"] = True
		conf["ai"]["imagePrivacyProviders"] = []
		self.assertTrue(assistant.privacyAccepted(PROVIDERS["anthropic"]))
		self.assertEqual(conf["ai"]["imagePrivacyProviders"], ["anthropic"])
		self.assertFalse(assistant.privacyAccepted(PROVIDERS["gemini"]))

	def test_unchecking_the_option_asks_again(self) -> None:
		conf["ai"]["imagePrivacyAccepted"] = False
		conf["ai"]["imagePrivacyProviders"] = ["anthropic"]
		self.assertFalse(assistant.privacyAccepted(PROVIDERS["anthropic"]))
		assistant.markPrivacyAccepted(PROVIDERS["gemini"])
		self.assertEqual(conf["ai"]["imagePrivacyProviders"], ["gemini"])


# ====================================================================== 11. el agente no escribe contraseñas
class AgentPasswordTests(Base):
	def _focus(self, protected: bool):
		from tiresias import api
		from tiresias.objects.roles import Role, State

		obj = types.SimpleNamespace(role=Role.PASSWORDEDIT if protected else Role.EDITABLETEXT, states={State.PROTECTED} if protected else set())
		return mock.patch.object(api, "getFocusObject", return_value=obj)

	def test_type_in_password_is_refused_before_asking(self) -> None:
		from tiresias.gui import ai_dialogs

		ag = agentMod.ScreenAgent()
		ag.running = True
		with self._focus(True), mock.patch.object(ai_dialogs, "showAgentConfirm") as confirm, mock.patch.object(ag, "_nextStep") as step:
			ag._handle(agentMod.Action("type", {"text": "1234"}))
		confirm.assert_not_called()
		step.assert_called_once()
		self.assertIn("contraseña", ag.steps[-1])
		self.assertTrue(any("contraseña" in m for m in self.spoken))

	def test_type_is_checked_again_before_acting(self) -> None:
		ag = agentMod.ScreenAgent()
		ag.running = True
		done = []
		ag.executor = lambda action, geom: done.append(action.kind)
		with self._focus(True), mock.patch.object(ag, "_focusTarget"), mock.patch.object(ag, "_nextStep"):
			ag._perform(agentMod.Action("type", {"text": "1234"}), "escribir")
		self.assertEqual(done, [])
		with self._focus(False), mock.patch.object(ag, "_focusTarget"), mock.patch.object(queue_handler, "callLater"):
			ag._perform(agentMod.Action("type", {"text": "hola"}), "escribir")
		self.assertEqual(done, ["type"])


# ====================================================================== 12. esfuerzo en OpenAI
class OpenAIEffortTests(Base):
	def test_reasoning_effort_only_for_reasoning_models(self) -> None:
		o = PROVIDERS["openai"]
		with mock.patch.object(keys, "getKey", lambda pid: "k"):
			conf["ai"]["openaiModel"] = "gpt-5.5"
			body, _h = o.buildBody([Message("user", "x")], "", 2000, "low")
			self.assertEqual(body["reasoning_effort"], "low")
			body, _h = o.buildBody([Message("user", "x")], "", 2000, "")
			self.assertNotIn("reasoning_effort", body)
			conf["ai"]["openaiModel"] = "gpt-4.1-mini"
			body, _h = o.buildBody([Message("user", "x")], "", 2000, "low")
			self.assertNotIn("reasoning_effort", body)
		body, _h = PROVIDERS["local"].buildBody([Message("user", "x")], "", 2000, "low")
		self.assertNotIn("reasoning_effort", body)


# ====================================================================== 13. conexión cortada
class ConnectionResetTests(Base):
	def test_cut_connection_is_retried(self) -> None:
		with MockServer(["close", _ok("Tras el corte")]) as srv:
			a, k = self.anthropic(srv.url)
			with a, k:
				reply = PROVIDERS["anthropic"].chat([Message("user", "x")])
		self.assertEqual(reply.text, "Tras el corte")
		self.assertEqual(len(srv.requests), 2)

	def test_incomplete_read_is_network_and_retryable(self) -> None:
		import http.client

		err = PROVIDERS["anthropic"]._networkError(http.client.IncompleteRead(b"abc"), 90)
		self.assertEqual(err.kind, "network")
		self.assertTrue(err.retryable)


# ====================================================================== 14. Gemini: bloqueos y firmas
class GeminiResponseTests(Base):
	def test_safety_block_is_explained(self) -> None:
		g = PROVIDERS["gemini"]
		data = {"candidates": [{"finishReason": "SAFETY", "safetyRatings": []}]}
		with mock.patch.object(keys, "getKey", lambda pid: "k"), mock.patch.object(type(g), "_post", lambda self, *a: data):
			with self.assertRaises(AIError) as cm:
				g.chat([Message("user", "x")])
		self.assertEqual(cm.exception.kind, "refusal")
		self.assertIn("seguridad", str(cm.exception))

	def test_thought_signatures_are_sent_back(self) -> None:
		g = PROVIDERS["gemini"]
		parts = [{"text": "pensando", "thought": True}, {"text": "Un perro.", "thoughtSignature": "FIRMA"}]
		data = {"candidates": [{"content": {"role": "model", "parts": parts}, "finishReason": "STOP"}]}
		with mock.patch.object(keys, "getKey", lambda pid: "k"), mock.patch.object(type(g), "_post", lambda self, *a: data):
			reply = g.chat([Message("user", "x")])
			self.assertEqual(reply.text, "Un perro.")
			body, _h = g.buildBody([Message("user", "x"), reply, Message("user", "¿De qué color?")], "", 100)
		self.assertEqual(body["contents"][1], {"role": "model", "parts": parts})


# ====================================================================== 15. reducción de imágenes
class ScaleDownTests(unittest.TestCase):
	def test_fullhd_keeps_more_resolution(self) -> None:
		img = imaging.Image(bytes(1920 * 1080 * 4), 1920, 1080, 3, 4)
		small = imaging.scaleDown(img, imaging.AI_MAX_SIDE)
		self.assertEqual((small.width, small.height), (1568, 882))
		self.assertEqual((small.left, small.top), (3, 4))
		self.assertEqual(len(small.data), 1568 * 882 * 4)

	def test_pixels_are_averaged(self) -> None:
		# 4x2 -> 2x1: cada píxel nuevo es la media de un bloque de 2x2.
		px = [(0, 0, 0, 255), (100, 100, 100, 255), (200, 0, 0, 255), (0, 0, 0, 255), (100, 100, 100, 255), (0, 0, 0, 255), (0, 0, 0, 255), (0, 0, 200, 255)]
		img = imaging.Image(bytes(v for p in px for v in p), 4, 2)
		small = imaging.scaleDown(img, 2)
		self.assertEqual((small.width, small.height), (2, 1))
		self.assertEqual(list(small.data[:4]), [50, 50, 50, 255])
		self.assertEqual(list(small.data[4:]), [50, 0, 50, 255])

	def test_small_images_unchanged(self) -> None:
		img = imaging.Image(bytes(10 * 10 * 4), 10, 10)
		self.assertIs(imaging.scaleDown(img, 20), img)


# ====================================================================== 16. menú y estado de las claves
class MenuAndKeyStateTests(Base):
	def test_menu_has_translation_tools(self) -> None:
		from tiresias.vision_commands import menuActions

		funcs = [f for _g, _l, f in menuActions()]
		self.assertIn(translate.copyLastTranslation, funcs)
		self.assertIn(translate.cycleTargetLanguage, funcs)

	def test_key_state_mentions_environment_variable(self) -> None:
		from tiresias.gui import ai_dialogs

		with _DataDir(), mock.patch.dict(os.environ, {"OPENAI_API_KEY": "sk-x"}, clear=False):
			self.assertIn("OPENAI_API_KEY", ai_dialogs.keyStateLabel("openai"))
		with _DataDir(), mock.patch.dict(os.environ, {"GEMINI_API_KEY": "", "GOOGLE_API_KEY": ""}):
			self.assertEqual(ai_dialogs.keyStateLabel("gemini"), "no hay ninguna guardada")


# ====================================================================== 17. etiquetado automático tras corregir la clave
class AutoLabelResetTests(Base):
	def test_permission_error_stops_and_reset_restarts(self) -> None:
		from tiresias.ai import autolabel

		lab = autolabel.AutoLabeler()
		cand = autolabel.Candidate(key=("obj", "app", "k"), rect=(10, 10, 20, 20), hwnd=0, isGraphic=False, info="")
		lab._times.append(1.0)
		lab._failed(cand, AIError("sin permiso", 403, "permission"), 1.0)
		self.assertTrue(lab._stopped)
		lab.resetErrors()
		self.assertFalse(lab._stopped)
		self.assertEqual(lab._pausedUntil, 0.0)

	def test_request_uses_per_provider_privacy(self) -> None:
		from tiresias.ai import autolabel

		lab = autolabel.AutoLabeler()
		cand = autolabel.Candidate(key=("obj", "app", "k2"), rect=(10, 10, 20, 20), hwnd=0, isGraphic=False, info="")
		conf["ai"]["imagePrivacyAccepted"] = True
		conf["ai"]["imagePrivacyProviders"] = ["anthropic"]
		gem = PROVIDERS["gemini"]
		with mock.patch.object(assistant, "checkProvider", return_value=gem), mock.patch.object(assistant, "withImagePrivacy") as ask:
			self.assertFalse(lab.request(cand))
		ask.assert_called_once()


# ====================================================================== 19. cámara
class CameraTests(Base):
	def test_toggle_while_stopping(self) -> None:
		from tiresias.ai import camera

		fc = camera.FaceCheck()
		fc.running = True
		fc._stop.set()
		with mock.patch.object(camera.threading, "Thread") as thr:
			fc.toggle()
		thr.assert_not_called()
		self.assertIn("se está deteniendo", self.spoken[-1])


# ====================================================================== panel de opciones
class PanelTests(Base):
	@classmethod
	def setUpClass(cls) -> None:
		try:
			import wx
		except ImportError:  # pragma: no cover
			raise unittest.SkipTest("sin wxPython") from None
		cls.app = wx.App.Get() or wx.App(False)

	def _panel(self):
		import wx

		from tiresias.gui import ai_dialogs

		frame = wx.Frame(None)
		self.addCleanup(frame.Destroy)
		return ai_dialogs.AiPanel(frame)

	def test_translate_speech_without_service_is_turned_off(self) -> None:
		from tiresias.gui import settings

		with _DataDir(), mock.patch.object(keys, "getKey", lambda pid: ""):
			conf["ai"]["provider"] = "openai"
			panel = self._panel()
			panel.setControlValue("translateSpeech", True)
			with mock.patch.object(settings, "showError") as err:
				panel.onSave()
		self.assertFalse(conf["ai"]["translateSpeech"])
		err.assert_called_once()
		self.assertIn("desactivada", err.call_args.args[0])

	def test_invalid_key_is_not_saved_nor_shown(self) -> None:
		from tiresias.gui import settings

		with _DataDir():
			panel = self._panel()
			panel._keyCtrls["anthropic"].SetValue("sk-clavé")
			with mock.patch.object(settings, "showError") as err:
				panel.onSave()
			self.assertFalse(keys.hasStoredKey("anthropic"))
		self.assertNotIn("sk-clavé", err.call_args.args[0])
		self.assertIn("caracteres", err.call_args.args[0])

	def test_local_url_is_validated(self) -> None:
		from tiresias.gui import settings

		with _DataDir():
			panel = self._panel()
			panel.getControl("localUrl").SetValue("192.168.1.20:11434/v1")
			with mock.patch.object(settings, "showError") as err:
				self.assertFalse(panel.isValid())
		err.assert_called_once()


if __name__ == "__main__":
	unittest.main()
