"""El eco de teclado acepta teclas que producen varios caracteres a la vez."""

import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from tiresias import typing_echo  # noqa: E402
from tiresias.config import conf  # noqa: E402


class VariosCaracteresTests(unittest.TestCase):
	def test_acento_que_no_se_combina(self) -> None:
		conf.load()
		with mock.patch.object(typing_echo, "_modeActive", return_value=False):
			# Antes: TypeError en unicodedata.category con «´a».
			typing_echo.onTypedCharacter(None, "´a")
		self.assertEqual([c for _t, c in list(typing_echo._recent)[-2:]], ["´", "a"])


if __name__ == "__main__":
	unittest.main()
