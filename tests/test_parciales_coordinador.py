"""Comprobaciones de conjunto tras completar las peticiones parciales."""

import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "src")
if SRC not in sys.path:
	sys.path.insert(0, SRC)


class WordLineMoveTests(unittest.TestCase):
	def test_word_document_helpers_exist(self):
		"""Todo ``self._metodo(`` que usa WordDocument tiene que existir (antes faltaba _waitForCaretMovement)."""
		from tiresias.appmodules import winword
		from tiresias.objects import behaviors

		path = winword.__file__
		with open(path, encoding="utf-8") as f:
			source = f.read()
		start = source.index("class WordDocument")
		end = source.find("\nclass ", start + 1)
		body = source[start:end if end > 0 else len(source)]
		missing = sorted(
			name for name in set(re.findall(r"self\.(_[A-Za-z]\w*)\(", body))
			# WordDocument se superpone a un objeto de texto editable (EditableText).
			if not hasattr(winword.WordDocument, name) and not hasattr(behaviors.EditableText, name)
		)
		self.assertEqual(missing, [])


if __name__ == "__main__":
	unittest.main()
