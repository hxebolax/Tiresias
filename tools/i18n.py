"""Catálogos de traducción de la interfaz de Tiresias (gettext).

Uso::

	python tools/i18n.py extraer      genera data/locale/tiresias.pot
	python tools/i18n.py actualizar   fusiona el .pot con cada tiresias.po
	python tools/i18n.py compilar     crea los .mo a partir de los .po
	python tools/i18n.py estado       cuenta las cadenas sin traducir
	python tools/i18n.py todo         extraer + actualizar + compilar

Las cadenas se extraen de ``_("...")``, ``ngettext("...", "...", n)`` y
``pgettext("contexto", "...")`` en ``src/tiresias`` y en los complementos de
``data/addons``. El español es el idioma original: no tiene catálogo.

No necesita las herramientas de GNU gettext: el análisis usa ``ast`` y el
compilador de ``.mo`` está aquí mismo.
"""

from __future__ import annotations

import ast
import datetime
import os
import struct
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src", "tiresias")
ADDONS = os.path.join(ROOT, "data", "addons")
#: Los catálogos son datos: van en data/locale (el código queda en src).
LOCALE = os.path.join(ROOT, "data", "locale")
DOMAIN = "tiresias"
POT = os.path.join(LOCALE, DOMAIN + ".pot")

FUNCS = {"_": ("msgid",), "ngettext": ("msgid", "plural"), "pgettext": ("ctx", "msgid"), "npgettext": ("ctx", "msgid", "plural")}


class Message:
	def __init__(self, msgid: str, plural: str | None = None, ctx: str | None = None) -> None:
		self.msgid = msgid
		self.plural = plural
		self.ctx = ctx
		self.locations: list[str] = []
		self.msgstr: list[str] = [""]
		self.comments: list[str] = []
		self.fuzzy = False

	@property
	def key(self) -> tuple[str | None, str]:
		return (self.ctx, self.msgid)


# ====================================================================== extracción
def _strConst(node: ast.AST) -> str | None:
	if isinstance(node, ast.Constant) and isinstance(node.value, str):
		return node.value
	# Concatenación implícita ya resuelta por ast; también "a" + "b".
	if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
		a, b = _strConst(node.left), _strConst(node.right)
		if a is not None and b is not None:
			return a + b
	return None


def _funcName(node: ast.AST) -> str | None:
	if isinstance(node, ast.Name):
		return node.id
	if isinstance(node, ast.Attribute):
		return node.attr
	return None


def extractFile(path: str, rel: str, catalog: dict) -> int:
	try:
		with open(path, encoding="utf-8") as f:
			tree = ast.parse(f.read(), path)
	except (SyntaxError, UnicodeDecodeError) as e:
		print(f"AVISO: no se pudo analizar {rel}: {e}", file=sys.stderr)
		return 0
	count = 0
	for node in ast.walk(tree):
		if not isinstance(node, ast.Call):
			continue
		name = _funcName(node.func)
		spec = FUNCS.get(name or "")
		if spec is None or len(node.args) < len(spec):
			continue
		values = {}
		ok = True
		for role, arg in zip(spec, node.args):
			s = _strConst(arg)
			if s is None:
				ok = False
				break
			values[role] = s
		if not ok or not values.get("msgid"):
			continue
		key = (values.get("ctx"), values["msgid"])
		msg = catalog.get(key)
		if msg is None:
			msg = catalog[key] = Message(values["msgid"], values.get("plural"), values.get("ctx"))
		loc = f"{rel}:{node.lineno}"
		if loc not in msg.locations:
			msg.locations.append(loc)
		count += 1
	return count


def extract() -> dict:
	catalog: dict = {}
	for base, prefix in ((SRC, "src/tiresias"), (ADDONS, "data/addons")):
		for root, dirs, files in os.walk(base):
			dirs[:] = sorted(d for d in dirs if d not in ("__pycache__", "locale"))
			for fn in sorted(files):
				if fn.endswith(".py"):
					full = os.path.join(root, fn)
					rel = prefix + "/" + os.path.relpath(full, base).replace(os.sep, "/")
					extractFile(full, rel, catalog)
	return catalog


# ====================================================================== formato .po
def _escape(s: str) -> str:
	return s.replace("\\", "\\\\").replace('"', '\\"').replace("\t", "\\t").replace("\r", "\\r").replace("\n", "\\n")


def _unescape(s: str) -> str:
	out = []
	i = 0
	while i < len(s):
		c = s[i]
		if c == "\\" and i + 1 < len(s):
			n = s[i + 1]
			out.append({"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\"}.get(n, n))
			i += 2
			continue
		out.append(c)
		i += 1
	return "".join(out)


def _poString(keyword: str, value: str) -> str:
	if "\n" in value.rstrip("\n") or value.count("\n") > 1:
		parts = value.split("\n")
		lines = [f'{keyword} ""']
		for i, p in enumerate(parts):
			piece = p + ("\n" if i < len(parts) - 1 else "")
			if piece:
				lines.append(f'"{_escape(piece)}"')
		return "\n".join(lines)
	return f'{keyword} "{_escape(value)}"'


def header(lang: str | None) -> str:
	now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M+0000")
	lines = [
		f"Project-Id-Version: Tiresias {_version()}",
		f"POT-Creation-Date: {now}",
		"MIME-Version: 1.0",
		"Content-Type: text/plain; charset=UTF-8",
		"Content-Transfer-Encoding: 8bit",
		"Plural-Forms: nplurals=2; plural=(n != 1);",
	]
	if lang:
		lines.insert(1, f"Language: {lang}")
	return "\n".join(lines) + "\n"


def _version() -> str:
	sys.path.insert(0, os.path.join(ROOT, "src"))
	try:
		import tiresias

		return tiresias.VERSION
	except Exception:
		return ""


def writePo(path: str, catalog: dict, lang: str | None, template: bool = False) -> None:
	os.makedirs(os.path.dirname(path), exist_ok=True)
	out = []
	out.append("# Catálogo de traducción de Tiresias." if template else f"# Traducción de Tiresias ({lang}).")
	out.append('msgid ""')
	out.append('msgstr ""')
	for line in header(lang).splitlines():
		out.append(f'"{_escape(line)}\\n"')
	out.append("")
	for msg in sorted(catalog.values(), key=lambda m: (m.locations[0] if m.locations else "~", m.msgid)):
		for c in msg.comments:
			out.append(f"#. {c}")
		if msg.locations:
			out.append("#: " + " ".join(msg.locations[:6]))
		flags = ["python-brace-format"] if "{" in msg.msgid else []
		if msg.fuzzy and not template:
			flags.insert(0, "fuzzy")
		if flags:
			out.append("#, " + ", ".join(flags))
		if msg.ctx is not None:
			out.append(_poString("msgctxt", msg.ctx))
		out.append(_poString("msgid", msg.msgid))
		if msg.plural is not None:
			out.append(_poString("msgid_plural", msg.plural))
			strs = msg.msgstr if not template else ["", ""]
			strs = (strs + ["", ""])[:2]
			for i, s in enumerate(strs):
				out.append(_poString(f"msgstr[{i}]", s))
		else:
			out.append(_poString("msgstr", "" if template else msg.msgstr[0]))
		out.append("")
	with open(path, "w", encoding="utf-8", newline="\n") as f:
		f.write("\n".join(out))


def readPo(path: str) -> dict:
	"""Lee un .po: {(contexto, msgid): Message}. Sin la cabecera."""
	catalog: dict = {}
	with open(path, encoding="utf-8-sig") as f:
		lines = f.read().splitlines()
	entry: dict = {}
	current: str | None = None
	fuzzy = False
	locs: list[str] = []

	def flush() -> None:
		nonlocal entry, fuzzy, locs
		if "msgid" in entry and entry["msgid"] != "":
			msg = Message(entry["msgid"], entry.get("msgid_plural"), entry.get("msgctxt"))
			if msg.plural is not None:
				msg.msgstr = [entry.get(f"msgstr[{i}]", "") for i in range(2)]
			else:
				msg.msgstr = [entry.get("msgstr", "")]
			msg.fuzzy = fuzzy
			msg.locations = locs
			catalog[msg.key] = msg
		entry = {}
		fuzzy = False
		locs = []

	for raw in lines + [""]:
		line = raw.strip()
		if not line:
			flush()
			current = None
			continue
		if line.startswith("#,"):
			fuzzy = "fuzzy" in line
			continue
		if line.startswith("#:"):
			locs += line[2:].split()
			continue
		if line.startswith("#"):
			continue
		if line.startswith('"'):
			if current is not None:
				entry[current] = entry.get(current, "") + _unescape(line[1:-1])
			continue
		keyword, _sp, rest = line.partition(" ")
		if keyword in ("msgctxt", "msgid") and ("msgstr" in entry or any(k.startswith("msgstr[") for k in entry)):
			flush()
		current = keyword
		entry[current] = _unescape(rest.strip()[1:-1])
	return catalog


# ====================================================================== compilación .mo
def compileMo(catalog: dict, path: str, lang: str) -> int:
	"""Escribe un .mo (formato de GNU gettext). Devuelve el número de cadenas traducidas."""
	entries: dict[bytes, bytes] = {}
	entries[b""] = header(lang).encode("utf-8")
	count = 0
	for msg in catalog.values():
		if msg.fuzzy or not any(msg.msgstr):
			continue
		key = msg.msgid
		if msg.plural is not None:
			key = key + "\0" + msg.plural
			value = "\0".join(s or (msg.msgid if i == 0 else msg.plural) for i, s in enumerate(msg.msgstr))
		else:
			value = msg.msgstr[0]
		if msg.ctx is not None:
			key = msg.ctx + "\x04" + key
		entries[key.encode("utf-8")] = value.encode("utf-8")
		count += 1
	keys = sorted(entries)
	ids = b""
	strs = b""
	offsets = []
	for k in keys:
		offsets.append((len(ids), len(k), len(strs), len(entries[k])))
		ids += k + b"\0"
		strs += entries[k] + b"\0"
	n = len(keys)
	keyStart = 7 * 4 + 16 * n
	valueStart = keyStart + len(ids)
	koffsets: list[int] = []
	voffsets: list[int] = []
	for o1, l1, o2, l2 in offsets:
		koffsets += [l1, o1 + keyStart]
		voffsets += [l2, o2 + valueStart]
	data = struct.pack("Iiiiiii", 0x950412DE, 0, n, 7 * 4, 7 * 4 + n * 8, 0, 0)
	data += struct.pack(f"{len(koffsets)}i", *koffsets) + struct.pack(f"{len(voffsets)}i", *voffsets)
	data += ids + strs
	os.makedirs(os.path.dirname(path), exist_ok=True)
	with open(path, "wb") as f:
		f.write(data)
	return count


# ====================================================================== órdenes
def languages() -> list[str]:
	try:
		return sorted(d for d in os.listdir(LOCALE) if os.path.isfile(os.path.join(LOCALE, d, "LC_MESSAGES", DOMAIN + ".po")))
	except OSError:
		return []


def poPath(lang: str) -> str:
	return os.path.join(LOCALE, lang, "LC_MESSAGES", DOMAIN + ".po")


def cmdExtract() -> dict:
	catalog = extract()
	writePo(POT, catalog, None, template=True)
	print(f"{len(catalog)} cadenas en {os.path.relpath(POT, ROOT)}")
	return catalog


def cmdUpdate(catalog: dict | None = None) -> None:
	catalog = catalog if catalog is not None else readPo(POT)
	for lang in languages():
		old = readPo(poPath(lang))
		merged: dict = {}
		for key, msg in catalog.items():
			new = Message(msg.msgid, msg.plural, msg.ctx)
			new.locations = msg.locations
			prev = old.get(key)
			if prev is not None:
				new.msgstr = prev.msgstr
				new.fuzzy = prev.fuzzy
			merged[key] = new
		writePo(poPath(lang), merged, lang)
		missing = sum(1 for m in merged.values() if not any(m.msgstr))
		print(f"{lang}: {len(merged)} cadenas, {missing} sin traducir")


def cmdCompile() -> None:
	for lang in languages():
		catalog = readPo(poPath(lang))
		n = compileMo(catalog, os.path.join(LOCALE, lang, "LC_MESSAGES", DOMAIN + ".mo"), lang)
		print(f"{lang}: {n} cadenas compiladas")


def cmdStatus() -> int:
	total = len(readPo(POT)) if os.path.isfile(POT) else len(extract())
	worst = 0
	for lang in languages():
		cat = readPo(poPath(lang))
		missing = sum(1 for m in cat.values() if not any(m.msgstr) or m.fuzzy)
		worst = max(worst, missing)
		print(f"{lang}: {len(cat) - missing} de {total} traducidas ({missing} pendientes)")
	return 1 if worst else 0


def main(argv: list[str]) -> int:
	cmd = argv[1] if len(argv) > 1 else "todo"
	if cmd == "extraer":
		cmdExtract()
	elif cmd == "actualizar":
		cmdUpdate()
	elif cmd == "compilar":
		cmdCompile()
	elif cmd == "estado":
		return cmdStatus()
	elif cmd == "todo":
		cmdUpdate(cmdExtract())
		cmdCompile()
	else:
		print(__doc__)
		return 2
	return 0


if __name__ == "__main__":
	sys.exit(main(sys.argv))
