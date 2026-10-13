"""Pruebas del soporte de matemáticas (motor propio de Tiresias).

Ejecutar con: ``.venv\\Scripts\\python.exe -X utf8 -m unittest discover -s tests -q``
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "src"))

from tiresias import paths  # noqa: E402

if not os.environ.get("TIRESIAS_TEST_DATA"):
	_TMP = tempfile.mkdtemp(prefix="tiresias_mates_")
	if os.path.isdir(os.path.join(ROOT, "data", "symbols")):
		shutil.copytree(os.path.join(ROOT, "data", "symbols"), os.path.join(_TMP, "symbols"), dirs_exist_ok=True)
	paths.setDataDir(_TMP)
	paths.ensureDataDirs()

from tiresias import mathpres  # noqa: E402
from tiresias.config import conf  # noqa: E402
from tiresias.mathpres import braille_cmu, latex, mathml, navigation, omml, providers, speech_es  # noqa: E402


def say(src: str, verbosity: str = "normal", style: str = "natural", pauses: bool = False, capitals: bool = True) -> str:
	"""Texto hablado de un MathML o de un LaTeX (si no empieza por «<»)."""
	mm = src if src.lstrip().startswith("<") else latex.latexToMathML(src)
	opts = speech_es.SpeechOptions(verbosity=verbosity, style=style, sayCapitals=capitals)
	return speech_es.nodeText(mathml.parse(mm), opts, pauses=pauses)


def cmu(src: str) -> str:
	mm = src if src.lstrip().startswith("<") else latex.latexToMathML(src)
	return braille_cmu.toUnicode(braille_cmu.translate(mathml.parse(mm)).cells)


QUADRATIC = "<math><mi>x</mi><mo>=</mo><mfrac><mrow><mo>−</mo><mi>b</mi><mo>±</mo><msqrt><msup><mi>b</mi><mn>2</mn></msup><mo>−</mo><mn>4</mn><mi>a</mi><mi>c</mi></msqrt></mrow><mrow><mn>2</mn><mi>a</mi></mrow></mfrac></math>"


# ====================================================================== MathML
class ParseTests(unittest.TestCase):
	def test_namespace_prefix(self) -> None:
		root = mathml.parse('<m:math xmlns:m="http://www.w3.org/1998/Math/MathML"><m:mi>x</m:mi><m:mo>+</m:mo><m:mn>1</m:mn></m:math>')
		self.assertEqual(root.tag, "math")
		self.assertEqual([c.tag for c in root.children[0].children], ["mi", "mo", "mn"])

	def test_entities_and_invisible(self) -> None:
		root = mathml.parse("<math><mi>x</mi><mo>&InvisibleTimes;</mo><mi>y</mi></math>")
		self.assertEqual(root.children[0].children[1].text, "⁢")

	def test_extraneous_prefix_and_xml_decl(self) -> None:
		root = mathml.parse('<?xml version="1.0"?><!-- c --><p>texto</p><math><mn>2</mn></math>')
		self.assertEqual(root.children[0].tag, "mn")

	def test_math_alphanumerics(self) -> None:
		root = mathml.parse("<math><mi>𝑥</mi><mi>𝐯</mi><mi>ℝ</mi></math>")
		kids = root.children[0].children
		self.assertEqual(kids[0].text, "x")
		self.assertEqual((kids[1].text, kids[1].get("mathvariant")), ("v", "bold"))
		self.assertEqual(kids[2].text, "R")
		self.assertEqual(kids[2].get("mathvariant"), "double-struck")

	def test_mfenced_and_groups(self) -> None:
		root = mathml.parse("<math><mfenced><mi>a</mi><mi>b</mi></mfenced></math>")
		g = root.children[0]
		self.assertTrue(g.isFenced)
		self.assertEqual((g.get("_open"), g.get("_close")), ("(", ")"))

	def test_fence_grouping_absolute_values(self) -> None:
		root = mathml.parse(latex.latexToMathML("|x-1|+|y|"))
		row = root.children[0]
		self.assertTrue(row.children[0].isFenced)
		self.assertTrue(row.children[2].isFenced)
		self.assertEqual(row.children[0].get("_open"), "|")

	def test_set_builder_bar_not_grouped(self) -> None:
		root = mathml.parse(latex.latexToMathML(r"\{x \mid x>0\}"))
		g = root.children[0]
		self.assertEqual(g.get("_open"), "{")
		self.assertTrue(any(k.isMo("|") for k in g.fenceContent.children))

	def test_wrappers_removed(self) -> None:
		root = mathml.parse('<math><mstyle displaystyle="true"><mpadded><mi>x</mi></mpadded></mstyle><mphantom><mi>z</mi></mphantom></math>')
		self.assertEqual(root.children[0].tag, "mi")

	def test_semantics_keeps_presentation(self) -> None:
		root = mathml.parse('<math><semantics><msup><mi>x</mi><mn>2</mn></msup><annotation encoding="application/x-tex">x^2</annotation></semantics></math>')
		self.assertEqual(root.children[0].tag, "msup")

	def test_inferred_mrow(self) -> None:
		root = mathml.parse("<math><msqrt><mi>x</mi><mo>+</mo><mn>1</mn></msqrt></math>")
		self.assertEqual(root.children[0].children[0].tag, "mrow")

	def test_serialize_roundtrip(self) -> None:
		root = mathml.parse(QUADRATIC)
		again = mathml.parse(root.toMathML())
		self.assertEqual(again.toMathML(), root.toMathML())


class ContentMathMLTests(unittest.TestCase):
	def test_plus(self) -> None:
		self.assertEqual(say("<math><apply><plus/><ci>x</ci><cn>1</cn></apply></math>"), "x más 1")

	def test_power_eq(self) -> None:
		self.assertEqual(say("<math><apply><eq/><apply><power/><ci>x</ci><cn>2</cn></apply><cn>4</cn></apply></math>"), "x al cuadrado igual a 4")

	def test_root_degree(self) -> None:
		self.assertEqual(say("<math><apply><root/><degree><cn>3</cn></degree><ci>x</ci></apply></math>"), "raíz cúbica de x")

	def test_rational(self) -> None:
		self.assertEqual(say('<math><cn type="rational">1<sep/>3</cn></math>'), "un tercio")

	def test_integral(self) -> None:
		text = say("<math><apply><int/><bvar><ci>x</ci></bvar><lowlimit><cn>0</cn></lowlimit><uplimit><ci>a</ci></uplimit><apply><sin/><ci>x</ci></apply></apply></math>")
		self.assertEqual(text, "integral desde 0 hasta a de seno de x d x")

	def test_divide_and_minus(self) -> None:
		self.assertEqual(say("<math><apply><divide/><ci>a</ci><ci>b</ci></apply></math>"), "a sobre b")
		self.assertEqual(say("<math><apply><minus/><ci>a</ci><ci>b</ci></apply></math>"), "a menos b")


# ====================================================================== voz
class SpeechTests(unittest.TestCase):
	def test_quadratic_levels(self) -> None:
		self.assertEqual(
			say(QUADRATIC),
			"x igual a fracción con numerador menos b más menos raíz cuadrada de b al cuadrado menos 4 a c fin de raíz y denominador 2 a",
		)
		self.assertEqual(
			say(QUADRATIC, "breve"),
			"x igual a fracción menos b más menos raíz de b al cuadrado menos 4 a c fin raíz sobre 2 a fin fracción",
		)
		self.assertEqual(
			say(QUADRATIC, "detallado"),
			"x igual a inicio de fracción numerador menos b más menos inicio de raíz cuadrada b al cuadrado menos 4 a c fin de raíz denominador 2 a fin de fracción",
		)

	def test_quadratic_structural(self) -> None:
		text = say(QUADRATIC, style="estructural")
		self.assertTrue(text.startswith("x igual a inicio de fracción menos b más menos inicio de raíz cuadrada"))
		self.assertTrue(text.endswith("sobre 2 a fin de fracción"))

	def test_pauses_as_commas(self) -> None:
		self.assertIn("fin de raíz, y denominador", say(QUADRATIC, pauses=True))

	def test_simple_fractions(self) -> None:
		cases = {
			r"\frac{1}{2}": "un medio",
			r"\frac{3}{4}": "tres cuartos",
			r"\frac{2}{3}": "dos tercios",
			r"\frac{5}{8}": "cinco octavos",
			r"\frac{1}{10}": "un décimo",
			r"\frac{7}{12}": "siete doceavos",
			r"\frac{3}{100}": "tres centésimos",
			r"\frac{5}{2}": "cinco medios",
		}
		for tex, expected in cases.items():
			with self.subTest(tex=tex):
				self.assertEqual(say(tex), expected)

	def test_other_fractions(self) -> None:
		self.assertEqual(say(r"\frac{x}{y}"), "x sobre i griega")
		self.assertEqual(say(r"\frac{a}{b}"), "a sobre b")
		self.assertEqual(say(r"\frac{25}{31}"), "25 sobre 31")
		self.assertEqual(say(r"\frac{x+1}{x-1}"), "fracción con numerador x más 1 y denominador x menos 1")
		self.assertEqual(say(r"\frac{x+1}{x-1}+2"), "fracción con numerador x más 1 y denominador x menos 1 fin de fracción más 2")
		self.assertEqual(say(r"\frac{x+1}{x-1}", "breve"), "fracción x más 1 sobre x menos 1 fin fracción")
		self.assertEqual(say(r"\frac{x+1}{2}", "detallado"), "inicio de fracción numerador x más 1 denominador 2 fin de fracción")

	def test_mixed_number(self) -> None:
		self.assertEqual(say("<math><mn>2</mn><mo>&#x2064;</mo><mfrac><mn>3</mn><mn>4</mn></mfrac></math>"), "2 y tres cuartos")

	def test_powers(self) -> None:
		cases = {
			"x^2": "x al cuadrado",
			"x^3": "x al cubo",
			"x^4": "x a la cuarta",
			"x^{10}": "x a la décima",
			"x^{12}": "x elevado a 12",
			"x^n": "x elevado a n",
			"e^{-x}": "e elevado a menos x",
			"2^{n+1}": "2 elevado a n más 1",
			"2^{n+1}-1": "2 elevado a n más 1 fin del exponente menos 1",
			"A^{-1}": "A mayúscula elevado a menos 1",
			"(x+1)^2": "abre paréntesis x más 1 cierra paréntesis al cuadrado",
		}
		for tex, expected in cases.items():
			with self.subTest(tex=tex):
				self.assertEqual(say(tex), expected)
		self.assertEqual(say("x^n", "breve"), "x a la n")
		self.assertEqual(say("x^4", "detallado"), "x elevado a la cuarta potencia")

	def test_special_superscripts(self) -> None:
		self.assertEqual(say("f'(x)"), "f prima de x")
		self.assertEqual(say("f''(x)"), "f doble prima de x")
		self.assertEqual(say(r"30^\circ"), "30 grados")
		self.assertEqual(say(r"1^\circ"), "1 grado")
		self.assertEqual(say("A^T"), "A mayúscula traspuesta")
		self.assertEqual(say(r"\sin^{-1} x"), "arco seno de x")
		self.assertEqual(say("f^{-1}(x)"), "f inversa de x")

	def test_roots(self) -> None:
		self.assertEqual(say(r"\sqrt{2}"), "raíz cuadrada de 2")
		self.assertEqual(say(r"\sqrt{x+1}"), "raíz cuadrada de x más 1")
		self.assertEqual(say(r"\sqrt{x+1}+3"), "raíz cuadrada de x más 1 fin de raíz más 3")
		self.assertEqual(say(r"\sqrt[3]{8}"), "raíz cúbica de 8")
		self.assertEqual(say(r"\sqrt[4]{x}"), "raíz cuarta de x")
		self.assertEqual(say(r"\sqrt[n]{x}"), "raíz enésima de x")
		self.assertEqual(say(r"\sqrt[12]{x}"), "raíz de índice 12 de x")
		self.assertEqual(say(r"\sqrt{x+1}", "detallado"), "inicio de raíz cuadrada x más 1 fin de raíz")

	def test_subscripts(self) -> None:
		self.assertEqual(say("x_1"), "x sub 1")
		self.assertEqual(say("x_1", "detallado"), "x subíndice 1")
		self.assertEqual(say("a_{n+1}=a_n+2"), "a sub n más 1 fin del subíndice igual a a sub n más 2")
		self.assertEqual(say("x_i^2"), "x sub i al cuadrado")
		self.assertEqual(say(r"\log_2 8"), "logaritmo en base 2 de 8")

	def test_functions(self) -> None:
		self.assertEqual(say(r"\sin x"), "seno de x")
		self.assertEqual(say(r"\cos^2 x"), "coseno al cuadrado de x")
		self.assertEqual(say(r"\ln(x+1)"), "logaritmo neperiano de abre paréntesis x más 1 cierra paréntesis")
		self.assertEqual(say("f(x)=x^2"), "f de x igual a x al cuadrado")
		self.assertEqual(say("g(x,y)"), "g de x coma i griega")
		self.assertEqual(say(r"\tan\theta"), "tangente de theta")

	def test_sums_integrals_limits(self) -> None:
		self.assertEqual(say(r"\sum_{i=1}^{n} i"), "sumatorio desde i igual a 1 hasta n de i")
		self.assertEqual(say(r"\prod_{k=1}^{n} k"), "productorio desde k igual a 1 hasta n de k")
		self.assertEqual(say(r"\int_0^1 x^2\,dx"), "integral desde 0 hasta 1 de x al cuadrado d x")
		self.assertEqual(say(r"\int f(x)\,dx"), "integral de f de x d x")
		self.assertEqual(say(r"\oint_C F"), "integral de línea cerrada sobre C mayúscula de F mayúscula")
		self.assertEqual(say(r"\lim_{x\to 0} \frac{\sin x}{x} = 1"), "límite cuando x tiende a 0 de fracción con numerador seno de x y denominador x fin de fracción igual a 1")
		self.assertEqual(say(r"\lim_{n\to\infty} a_n"), "límite cuando n tiende a infinito de a sub n")
		self.assertEqual(say(r"\sum_{x \in A} x"), "sumatorio para x pertenece a A mayúscula de x")

	def test_derivatives(self) -> None:
		self.assertEqual(say(r"\frac{dy}{dx}"), "derivada de i griega respecto de x")
		self.assertEqual(say(r"\frac{d^2 y}{dx^2}"), "derivada segunda de i griega respecto de x")
		self.assertEqual(say(r"\frac{\partial f}{\partial x}"), "derivada parcial de f respecto de x")
		self.assertEqual(say(r"\frac{dy}{dx}", "breve"), "d i griega sobre d x")

	def test_matrices(self) -> None:
		m = r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}"
		self.assertEqual(say(m), "matriz de 2 por 2 fila 1 a b fila 2 c d fin de la matriz")
		self.assertEqual(say(m, pauses=True), "matriz de 2 por 2, fila 1 a, b, fila 2 c, d, fin de la matriz")
		self.assertEqual(say(m, "breve"), "matriz de 2 por 2 a b c d")
		self.assertEqual(say(m, "detallado"), "matriz de 2 por 2 fila 1 columna 1 a columna 2 b fila 2 columna 1 c columna 2 d fin de la matriz")
		self.assertEqual(say(r"\begin{vmatrix} 1 & 2 \\ 3 & 4 \end{vmatrix}"), "determinante de 2 por 2 fila 1 1 2 fila 2 3 4 fin del determinante")
		self.assertEqual(say(r"\begin{pmatrix} 1 \\ 2 \\ 3 \end{pmatrix}"), "vector columna de 3 componentes 1 2 3 fin del vector")
		self.assertEqual(say(r"\begin{bmatrix} 1 & 2 & 3 \end{bmatrix}"), "vector fila de 3 componentes 1 2 3 fin del vector")

	def test_cases_and_systems(self) -> None:
		text = say(r"|x| = \begin{cases} x & x \geq 0 \\ -x & x < 0 \end{cases}")
		self.assertEqual(text, "valor absoluto de x igual a 2 casos caso 1 x si x mayor o igual que 0 caso 2 menos x si x menor que 0 fin de los casos")
		text = say(r"\begin{aligned} x+y &= 3 \\ x-y &= 1 \end{aligned}")
		self.assertTrue(text.startswith("sistema de 2 ecuaciones ecuación 1 x más i griega igual a 3 ecuación 2"))

	def test_sets_and_logic(self) -> None:
		self.assertEqual(say(r"\{1, 2, 3\}"), "el conjunto 1 coma 2 coma 3")
		self.assertEqual(say(r"\{\}"), "el conjunto vacío")
		self.assertEqual(say(r"\{x \in \mathbb{R} \mid x > 0\}"), "el conjunto de los x pertenece a los números reales tales que x mayor que 0")
		self.assertEqual(say(r"A \cup B = \emptyset"), "A mayúscula unión B mayúscula igual a conjunto vacío")
		self.assertEqual(say(r"A \subseteq B"), "A mayúscula contenido o igual a B mayúscula")
		self.assertEqual(say(r"\forall x \in \mathbb{N}"), "para todo x pertenece a los números naturales")
		self.assertEqual(say(r"\exists x"), "existe x")
		self.assertEqual(say(r"p \Rightarrow q"), "p implica q")
		self.assertEqual(say(r"p \Leftrightarrow q"), "p si y solo si q")
		self.assertEqual(say(r"\neg p \lor q"), "no p o q")
		self.assertEqual(say(r"p \land q"), "p y q")

	def test_arrows_and_relations(self) -> None:
		self.assertEqual(say(r"f: A \to B"), "f dos puntos A mayúscula en B mayúscula")
		self.assertEqual(say(r"x \to 0"), "x tiende a 0")
		self.assertEqual(say(r"a \leftarrow b"), "a flecha a la izquierda b")
		self.assertEqual(say(r"a \neq b"), "a distinto de b")
		self.assertEqual(say(r"a \leq b"), "a menor o igual que b")
		self.assertEqual(say(r"a \geq b"), "a mayor o igual que b")
		self.assertEqual(say(r"a \approx b"), "a aproximadamente igual a b")
		self.assertEqual(say(r"a \equiv b"), "a idéntico a b")
		self.assertEqual(say(r"a \perp b"), "a perpendicular a b")

	def test_greek(self) -> None:
		self.assertEqual(say(r"\alpha + \beta = \gamma"), "alfa más beta igual a gamma")
		self.assertEqual(say(r"\Delta x"), "delta mayúscula x")
		self.assertEqual(say(r"\Delta x", "breve"), "delta x")
		self.assertEqual(say(r"2\pi r"), "2 pi r")
		self.assertEqual(say(r"\varepsilon \lambda \mu \omega"), "épsilon lambda mi omega")

	def test_letters_and_capitals(self) -> None:
		self.assertEqual(say("y=mx+b"), "i griega igual a m x más b")
		self.assertEqual(say("A+B", capitals=False), "A más B")
		self.assertEqual(say(r"\mathbf{v}"), "v negrita")
		self.assertEqual(say(r"\mathbb{Z}"), "los números enteros")

	def test_numbers(self) -> None:
		self.assertEqual(say("3.14"), "3 coma 14")
		self.assertEqual(say("3{,}5"), "3 coma 5")
		self.assertEqual(say("<math><mn>1.000.000</mn></math>"), "1000000")
		self.assertEqual(say("<math><mn>2,25</mn></math>"), "2 coma 25")
		self.assertEqual(say("-3"), "menos 3")

	def test_parentheses_nested(self) -> None:
		self.assertEqual(say("2(x+(y-1))"), "2 abre paréntesis x más abre paréntesis i griega menos 1 cierra paréntesis cierra paréntesis")
		self.assertEqual(say("2(x+(y-1))", "breve"), "2 paréntesis x más paréntesis i griega menos 1 cierra cierra")
		self.assertEqual(say("[a,b]"), "abre corchete a coma b cierra corchete")
		self.assertEqual(say("(a+b)(a-b)"), "abre paréntesis a más b cierra paréntesis por abre paréntesis a menos b cierra paréntesis")

	def test_absolute_norm_floor(self) -> None:
		self.assertEqual(say("|x|"), "valor absoluto de x")
		self.assertEqual(say("|x-1|+2"), "valor absoluto de x menos 1 fin del valor absoluto más 2")
		self.assertEqual(say(r"\|v\|"), "norma de v")
		self.assertEqual(say(r"\lfloor x \rfloor"), "parte entera por defecto de x")

	def test_misc_operators(self) -> None:
		self.assertEqual(say("n!"), "n factorial")
		self.assertEqual(say(r"50\%"), "50 por ciento")
		self.assertEqual(say(r"a \cdot b \times c \div d"), "a por b por c entre d")
		self.assertEqual(say(r"\binom{n}{k}"), "el número combinatorio n sobre k")
		self.assertEqual(say(r"\vec{v}"), "vector v")
		self.assertEqual(say(r"\bar{x}"), "x barra")
		self.assertEqual(say(r"\hat{u}"), "u sombrero")
		self.assertEqual(say(r"\dot{x}"), "x punto")
		self.assertEqual(say(r"a_1, a_2, \ldots, a_n"), "a sub 1 coma a sub 2 coma puntos suspensivos coma a sub n")

	def test_units(self) -> None:
		self.assertEqual(say(r"5\,\mathrm{cm}"), "5 centímetros")
		self.assertEqual(say(r"1\,\mathrm{km}"), "1 kilómetro")
		self.assertEqual(say(r"9{,}8\,\mathrm{m}/\mathrm{s}^2"), "9 coma 8 metros por segundos cuadrados")
		self.assertEqual(say(r"20\,\mathrm{kg}"), "20 kilogramos")
		self.assertEqual(say("<math><mn>3</mn><mtext>h</mtext></math>"), "3 horas")
		self.assertEqual(say('<math><mn>1</mn><mi class="MathML-Unit">km</mi></math>'), "1 kilómetro")

	def test_enclose_and_text(self) -> None:
		self.assertEqual(say(r"\boxed{x}"), "recuadro x fin de recuadro")
		self.assertEqual(say(r"x \text{ si } x>0"), "x si x mayor que 0")

	def test_speech_sequence_has_breaks(self) -> None:
		from tiresias.speech.commands import BreakCommand

		seq = speech_es.toSpeechSequence(speech_es.speakNode(mathml.parse(QUADRATIC)))
		self.assertTrue(any(isinstance(i, BreakCommand) for i in seq))
		self.assertTrue(all(isinstance(i, (str, BreakCommand)) for i in seq))


# ====================================================================== LaTeX
class LatexTests(unittest.TestCase):
	def tree(self, tex: str) -> mathml.MathNode:
		return mathml.parse(latex.latexToMathML(tex))

	def test_structures(self) -> None:
		self.assertEqual(self.tree(r"\frac{a}{b}").children[0].tag, "mfrac")
		self.assertEqual(self.tree(r"\sqrt[3]{x}").children[0].tag, "mroot")
		self.assertEqual(self.tree(r"x_i^2").children[0].tag, "msubsup")
		self.assertEqual(self.tree(r"\sum_{i=1}^n i").children[0].children[0].tag, "munderover")
		self.assertEqual(self.tree(r"\int_0^1 f").children[0].children[0].tag, "msubsup")
		self.assertEqual(self.tree(r"\lim_{x\to0} f").children[0].children[0].tag, "munder")

	def test_matrix_env(self) -> None:
		g = self.tree(r"\begin{bmatrix} 1 & 0 \\ 0 & 1 \end{bmatrix}").children[0]
		self.assertTrue(g.isFenced)
		self.assertEqual(g.fenceContent.tag, "mtable")
		self.assertEqual(len(g.fenceContent.children), 2)

	def test_left_right(self) -> None:
		g = self.tree(r"\left( \frac{a}{b} \right)").children[0]
		self.assertTrue(g.isFenced)
		self.assertEqual(g.fenceContent.tag, "mfrac")

	def test_wikipedia_alttext(self) -> None:
		self.assertEqual(say(r"{\displaystyle x^{2}+1}"), "x al cuadrado más 1")

	def test_delimiters(self) -> None:
		self.assertEqual(say("$x^2$"), "x al cuadrado")
		self.assertEqual(say(r"\[x^2\]"), "x al cuadrado")

	def test_unknown_command(self) -> None:
		self.assertIn("foo", say(r"\foo{x}"))

	def test_to_latex(self) -> None:
		cases = {
			r"\frac{a}{b}": r"\frac{a}{b}",
			r"\sqrt[3]{x+1}": r"\sqrt[3]{x+1}",
			r"x^{2}": "x^2",
			r"x_i^2": "x_i^2",
			r"\alpha+\beta": r"\alpha+\beta",
			r"\sum_{i=1}^{n} i": r"\sum_{i=1}^n i",
			r"\lim_{x\to 0} f": r"\lim_{x\to 0}f",
			r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}": r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}",
			r"\vec{v}": r"\vec{v}",
			r"\mathbb{R}": r"\mathbb{R}",
			r"\sin x": r"\sin x",
			r"\binom{n}{k}": r"\binom{n}{k}",
			r"30^\circ": r"30^\circ",
		}
		for tex, expected in cases.items():
			with self.subTest(tex=tex):
				self.assertEqual(latex.toLatex(self.tree(tex)), expected)

	def test_latex_roundtrip_speech(self) -> None:
		for tex in (r"\frac{x+1}{x-1}", r"\int_0^1 x^2\,dx", r"\sqrt{b^2-4ac}", r"\begin{vmatrix} 1 & 2 \\ 3 & 4 \end{vmatrix}"):
			with self.subTest(tex=tex):
				again = latex.toLatex(self.tree(tex))
				self.assertEqual(say(again), say(tex))

	def test_linear_text(self) -> None:
		self.assertEqual(speech_es.nodeText(mathml.parse(latex.linearTextToMathML("x² + y₁"))), "x al cuadrado más i griega sub 1")


# ====================================================================== OMML
OMML_QUADRATIC = (
	'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:r><m:t>x</m:t></m:r><m:r><m:t>=</m:t></m:r>'
	"<m:f><m:num><m:r><m:t>-b±</m:t></m:r><m:rad><m:radPr><m:degHide m:val=\"1\"/></m:radPr><m:deg/><m:e><m:sSup><m:e><m:r><m:t>b</m:t></m:r></m:e>"
	"<m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup><m:r><m:t>-4ac</m:t></m:r></m:e></m:rad></m:num><m:den><m:r><m:t>2a</m:t></m:r></m:den></m:f></m:oMath>"
)


class OmmlTests(unittest.TestCase):
	def test_quadratic(self) -> None:
		mm = omml.ommlToMathML(OMML_QUADRATIC)
		self.assertEqual(len(mm), 1)
		self.assertEqual(say(mm[0]), say(QUADRATIC))

	def test_nary_func_delimiter_matrix(self) -> None:
		xml = (
			'<m:oMathPara xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:oMath>'
			'<m:nary><m:naryPr><m:chr m:val="∑"/><m:limLoc m:val="undOvr"/></m:naryPr><m:sub><m:r><m:t>i=1</m:t></m:r></m:sub><m:sup><m:r><m:t>n</m:t></m:r></m:sup>'
			"<m:e><m:sSub><m:e><m:r><m:t>a</m:t></m:r></m:e><m:sub><m:r><m:t>i</m:t></m:r></m:sub></m:sSub></m:e></m:nary>"
			"</m:oMath></m:oMathPara>"
		)
		self.assertEqual(say(omml.ommlToMathML(xml)[0]), "sumatorio desde i igual a 1 hasta n de a sub i")
		xml2 = (
			'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
			'<m:func><m:fName><m:r><m:rPr><m:sty m:val="p"/></m:rPr><m:t>sin</m:t></m:r></m:fName><m:e><m:r><m:t>x</m:t></m:r></m:e></m:func>'
			"</m:oMath>"
		)
		self.assertEqual(say(omml.ommlToMathML(xml2)[0]), "seno de x")
		xml3 = (
			'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:d><m:e>'
			"<m:m><m:mr><m:e><m:r><m:t>1</m:t></m:r></m:e><m:e><m:r><m:t>0</m:t></m:r></m:e></m:mr>"
			"<m:mr><m:e><m:r><m:t>0</m:t></m:r></m:e><m:e><m:r><m:t>1</m:t></m:r></m:e></m:mr></m:m></m:e></m:d></m:oMath>"
		)
		self.assertTrue(say(omml.ommlToMathML(xml3)[0]).startswith("matriz de 2 por 2"))

	def test_fraction_types_and_accents(self) -> None:
		xml = (
			'<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math">'
			'<m:f><m:fPr><m:type m:val="noBar"/></m:fPr><m:num><m:r><m:t>n</m:t></m:r></m:num><m:den><m:r><m:t>k</m:t></m:r></m:den></m:f>'
			"</m:oMath>"
		)
		root = mathml.parse(omml.ommlToMathML(xml)[0])
		self.assertEqual(root.children[0].get("linethickness"), "0")
		acc = '<m:oMath xmlns:m="http://schemas.openxmlformats.org/officeDocument/2006/math"><m:acc><m:accPr><m:chr m:val="̅"/></m:accPr><m:e><m:r><m:t>x</m:t></m:r></m:e></m:acc></m:oMath>'
		self.assertEqual(say(omml.ommlToMathML(acc)[0]), "x barra")


# ====================================================================== braille
class BrailleCMUTests(unittest.TestCase):
	def test_numbers(self) -> None:
		self.assertEqual(cmu("<math><mn>12</mn></math>"), "⠼⠁⠃")
		self.assertEqual(cmu("<math><mn>3,5</mn></math>"), "⠼⠉⠂⠑")
		self.assertEqual(cmu("<math><mn>1.000.000</mn></math>"), "⠼⠁⠄⠚⠚⠚⠄⠚⠚⠚")

	def test_letters(self) -> None:
		self.assertEqual(cmu("x+y"), "⠭⠖⠽")
		self.assertEqual(cmu("A"), "⠨⠁")
		self.assertEqual(cmu(r"\alpha"), "⠈⠁")
		self.assertEqual(cmu(r"\Omega"), "⠨⠈⠺")
		# Punto 5 entre un número y una letra de la a a la j.
		self.assertEqual(cmu("2a"), "⠼⠃⠐⠁")
		self.assertEqual(cmu("2x"), "⠼⠃⠭")

	def test_operations_relations(self) -> None:
		self.assertEqual(cmu("a-b"), "⠁⠤⠃")
		self.assertEqual(cmu(r"a\times b"), "⠁⠦⠃")
		self.assertEqual(cmu(r"a\cdot b"), "⠁⠄⠃")
		self.assertEqual(cmu(r"a\div b"), "⠁⠲⠃")
		self.assertEqual(cmu("a=b"), "⠁⠶⠃")
		self.assertEqual(cmu(r"a\neq b"), "⠁⠘⠶⠃")
		self.assertEqual(cmu("a<b"), "⠁⠪⠃")
		self.assertEqual(cmu("a>b"), "⠁⠕⠃")
		self.assertEqual(cmu(r"a\leq b"), "⠁⠪⠶⠃")
		self.assertEqual(cmu(r"a\geq b"), "⠁⠕⠶⠃")
		self.assertEqual(cmu(r"a\pm b"), "⠁⠖⠒⠤⠃")
		self.assertEqual(cmu(r"x\in A"), "⠭⠣⠂⠨⠁")

	def test_fences(self) -> None:
		self.assertEqual(cmu("(a)"), "⠣⠁⠜")
		self.assertEqual(cmu("[a]"), "⠷⠁⠾")
		self.assertEqual(cmu(r"\{a\}"), "⠐⠇⠁⠸⠂")
		self.assertEqual(cmu("|a|"), "⠸⠁⠸")

	def test_fractions(self) -> None:
		self.assertEqual(cmu(r"\frac{3}{4}"), "⠼⠉⠲")
		self.assertEqual(cmu(r"\frac{1}{2}"), "⠼⠁⠆")
		self.assertEqual(cmu(r"\frac{a}{b}"), "⠁⠲⠃")
		self.assertEqual(cmu(r"\frac{a+b}{c}"), "⠢⠁⠖⠃⠔⠲⠉")
		self.assertEqual(cmu(r"\frac{a}{b+c}"), "⠁⠲⠢⠃⠖⠉⠔")

	def test_scripts(self) -> None:
		self.assertEqual(cmu("x^2"), "⠭⠡⠼⠃")
		self.assertEqual(cmu("x_1"), "⠭⠌⠼⠁")
		self.assertEqual(cmu("x^{n+1}"), "⠭⠡⠢⠝⠖⠼⠁⠔")
		self.assertEqual(cmu("x_i^2"), "⠭⠌⠊⠡⠼⠃")
		self.assertEqual(cmu("f'"), "⠋⠳")
		self.assertEqual(cmu(r"30^\circ"), "⠼⠉⠚⠴")

	def test_roots(self) -> None:
		self.assertEqual(cmu(r"\sqrt{2}"), "⠫⠱⠼⠃")
		self.assertEqual(cmu(r"\sqrt{x+1}"), "⠫⠱⠢⠭⠖⠼⠁⠔")
		self.assertEqual(cmu(r"\sqrt[3]{x}"), "⠫⠼⠉⠱⠭")

	def test_big_operators_and_functions(self) -> None:
		self.assertEqual(cmu(r"\sum_{i=1}^{n} i"), "⠨⠈⠎⠊⠶⠼⠁⠒⠝⠱⠊")
		self.assertEqual(cmu(r"\int_0^1 x"), "⠯⠼⠚⠒⠼⠁⠱⠭")
		self.assertEqual(cmu(r"\lim_{x\to 0} f"), "⠇⠊⠍⠄⠭⠒⠂⠼⠚⠱⠋")
		self.assertEqual(cmu(r"\sin x"), "⠎⠊⠝⠄⠭")
		self.assertEqual(cmu(r"\infty"), "⠼⠳")

	def test_matrix_rows(self) -> None:
		self.assertEqual(cmu(r"\begin{pmatrix} a & b \\ c & d \end{pmatrix}"), "⠠⠣⠁⠀⠃⠠⠜⠀⠠⠣⠉⠀⠙⠠⠜")

	def test_ranges_for_navigation(self) -> None:
		root = mathml.parse(latex.latexToMathML(r"x+\frac{a}{b}"))
		res = braille_cmu.translate(root)
		frac = next(n for n in root.iter() if n.tag == "mfrac")
		self.assertEqual(res.rangeOf(frac), (2, 5))
		self.assertIs(res.nodeAt(4, root).text, "b")

	def test_table_passthrough(self) -> None:
		from tiresias.braille import tables

		t = tables.translate(tables.getTable("es-comp8"), "a⠼⠁b")
		self.assertEqual(t.cells[1:3], [0x3C, 0x01])


# ====================================================================== navegación
class NavigationTests(unittest.TestCase):
	def setUp(self) -> None:
		self.nav = navigation.MathNavigator(mathml.parse(QUADRATIC))
		self.opts = speech_es.SpeechOptions()

	def text(self, withLabel: bool = True) -> str:
		return speech_es.toText(self.nav.speechFor(options=self.opts, withLabel=withLabel), pauses=False)

	def test_walk(self) -> None:
		nav = self.nav
		self.assertTrue(nav.moveDown())
		self.assertEqual(self.text(), "x")
		self.assertTrue(nav.moveNext())
		self.assertEqual(self.text(), "igual a")
		self.assertTrue(nav.moveNext())
		self.assertEqual(nav.current.tag, "mfrac")
		self.assertFalse(nav.moveNext())
		self.assertTrue(nav.moveDown())
		self.assertTrue(self.text().startswith("numerador menos b"))
		self.assertEqual(nav.whereAmI(), "numerador de la fracción")
		self.assertTrue(nav.moveNext())
		self.assertEqual(self.text(), "denominador 2 a")
		self.assertTrue(nav.movePrevious())
		self.assertTrue(nav.moveDown())
		self.assertEqual(self.text(), "menos")
		self.assertTrue(nav.moveLast())
		self.assertEqual(nav.current.tag, "msqrt")
		self.assertTrue(nav.moveDown())
		self.assertEqual(self.text(), "b al cuadrado")
		self.assertEqual(nav.whereAmI(), "dentro de la raíz cuadrada, numerador de la fracción")
		self.assertTrue(nav.moveDown())
		self.assertEqual(self.text(), "base b")
		self.assertTrue(nav.moveNext())
		self.assertEqual(self.text(), "exponente 2")
		self.assertTrue(nav.moveUp())
		self.assertTrue(nav.moveUp())
		self.assertEqual(nav.current.tag, "msqrt")
		self.assertTrue(nav.moveTop())
		self.assertIsNone(nav.parent())
		self.assertFalse(nav.moveUp())
		self.assertTrue(nav.moveBack())
		self.assertEqual(nav.current.tag, "msqrt")

	def test_home_end(self) -> None:
		self.nav.moveDown()
		self.assertTrue(self.nav.moveLast())
		self.assertEqual(self.nav.current.tag, "mfrac")
		self.assertTrue(self.nav.moveFirst())
		self.assertEqual(self.text(), "x")

	def test_describe(self) -> None:
		self.nav.moveDown()
		self.nav.moveLast()
		self.assertTrue(self.nav.describe(options=self.opts).startswith("fracción, numerador"))

	def test_matrix_cells(self) -> None:
		nav = navigation.MathNavigator(mathml.parse(latex.latexToMathML(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}")))
		self.assertTrue(nav.moveDown())
		self.assertEqual(speech_es.toText(nav.speechFor(withLabel=True), False), "fila 1 1 2")
		self.assertTrue(nav.moveDown())
		self.assertEqual(nav.cellPosition(), (1, 1))
		self.assertTrue(nav.moveCell(1, 0))
		self.assertEqual(nav.cellPosition(), (2, 1))
		self.assertTrue(nav.moveCell(0, 1))
		self.assertEqual(nav.current.textContent(), "4")
		self.assertFalse(nav.moveCell(0, 1))
		self.assertFalse(nav.moveCell(1, 0))
		self.assertEqual(nav.whereAmI(), "columna 2 de la fila, fila 2 de la matriz de 2 por 2")

	def test_fenced_content_is_transparent(self) -> None:
		nav = navigation.MathNavigator(mathml.parse(latex.latexToMathML("2(x+1)")))
		nav.moveDown()
		nav.moveNext()
		self.assertTrue(nav.current.isFenced)
		nav.moveDown()
		self.assertEqual(nav.current.text, "x")
		self.assertTrue(nav.moveUp())
		self.assertTrue(nav.current.isFenced)


# ====================================================================== exploración interactiva
class _Gesture:
	def __init__(self, gid: str, mods: tuple = ()) -> None:
		from tiresias.baseobject import normalizeGestureId

		self.identifiers = [normalizeGestureId(gid)]
		self.modifiers = frozenset(mods)

	def send(self) -> None:
		pass


class InteractionTests(unittest.TestCase):
	def setUp(self) -> None:
		from tiresias import speech
		from tiresias.mathpres import interaction, plugin

		self.spoken: list[str] = []
		self._handler = lambda sequence=None, **kw: self.spoken.append(" ".join(s for s in sequence if isinstance(s, str)))
		speech.pre_speech.register(self._handler)
		self.copied: list[str] = []
		from tiresias import api

		self._origCopy = api.copyToClip
		api.copyToClip = lambda text, notify=False: (self.copied.append(text), True)[1]
		self.interaction = interaction
		self.plugin = plugin.MathGlobalPlugin()
		self.assertTrue(interaction.start(QUADRATIC))

	def tearDown(self) -> None:
		from tiresias import api, speech

		speech.pre_speech.unregister(self._handler)
		api.copyToClip = self._origCopy
		self.interaction.stop(silent=True)
		conf["math"]["verbosity"] = "normal"

	def press(self, gid: str, mods: tuple = ()) -> None:
		func = self.plugin.getScript(_Gesture(gid, mods))
		self.assertIsNotNone(func, gid)
		func(_Gesture(gid, mods))

	def test_navigation_keys(self) -> None:
		self.assertIn("explorando fórmula", self.spoken[0])
		self.press("kb:downArrow")
		self.assertEqual(self.spoken[-1], "x")
		self.press("kb:end")
		self.press("kb:downArrow")
		self.assertTrue(self.spoken[-1].startswith("numerador"))
		self.press("kb:enter")
		self.assertEqual(self.spoken[-1], "numerador de la fracción")
		self.press("kb:escape")
		self.assertIsNone(self.interaction.getInteractor())

	def test_unbound_keys(self) -> None:
		# Las letras no hacen nada; las órdenes con Tiresias siguen su camino.
		func = self.plugin.getScript(_Gesture("kb:q"))
		self.assertEqual(func.__name__, "script_ignore")
		self.assertIsNot(getattr(self.plugin.getScript(_Gesture("kb:tiresias+t", ("tiresias",))), "__self__", None), self.interaction.getInteractor())

	def test_copy_formats(self) -> None:
		self.press("kb:l")
		self.assertTrue(self.copied[-1].startswith("x=\\frac{-b\\pm"))
		self.press("kb:m")
		self.assertTrue(self.copied[-1].startswith("<math"))
		self.press("kb:t")
		self.assertTrue(self.copied[-1].startswith("x igual a fracción"))

	def test_verbosity_cycle(self) -> None:
		self.press("kb:v")
		self.assertEqual(conf["math"]["verbosity"], "detallado")
		self.assertIn("verbosidad detallada", " ".join(self.spoken))

	def test_focus_change_exits(self) -> None:
		self.plugin.event_gainFocus(object(), lambda: None)
		self.assertIsNone(self.interaction.getInteractor())
		self.assertIsNone(self.plugin.getScript(_Gesture("kb:downArrow")))


# ====================================================================== obtención y API
class ProviderTests(unittest.TestCase):
	def test_ia2_attributes(self) -> None:
		attrs = providers.parseIA2Attributes(r"display:block math;tag:math;math:<mi>x</mi><mo>\=</mo><mn>1</mn>;")
		self.assertEqual(attrs["tag"], "math")
		self.assertEqual(attrs["math"], "<mi>x</mi><mo>=</mo><mn>1</mn>")

	def test_text_detection(self) -> None:
		self.assertEqual(providers.mathMlFromAnyText(r"\frac{1}{2}")[1], "latex")
		self.assertEqual(providers.mathMlFromAnyText("<math><mi>x</mi></math>")[1], "mathml")
		self.assertEqual(providers.mathMlFromAnyText(OMML_QUADRATIC)[1], "omml")
		self.assertEqual(providers.mathMlFromAnyText("x² + 1 = 5")[1], "texto")
		self.assertEqual(providers.mathMlFromAnyText("hola")[0], None)
		self.assertIsNotNone(providers.mathMlFromText(r"{\displaystyle \sqrt{2}}"))
		self.assertIsNone(providers.mathMlFromText("raíz de dos"))

	def test_public_api(self) -> None:
		self.assertEqual(mathpres.getSpeechText("<math><mfrac><mn>1</mn><mn>2</mn></mfrac></math>"), "un medio")
		self.assertEqual(mathpres.getBrailleForMathMl("<math><msqrt><mn>2</mn></msqrt></math>"), "⠫⠱⠼⠃")
		seq = mathpres.getSpeechForMathMl(QUADRATIC)
		self.assertTrue(seq and isinstance(seq[0], str))
		self.assertIn("<mfrac>", mathpres.mathMlFromLatex(r"\frac{a}{b}"))

	def test_config_defaults(self) -> None:
		self.assertEqual(conf["math"]["verbosity"], "normal")
		self.assertIn(conf["math"]["browseMode"], ("speech", "interactive"))


class BrowseBrailleLineTests(unittest.TestCase):
	"""La línea braille del modo exploración con una fórmula partida en dos líneas."""

	def _doc(self, caret: int):
		from tiresias.browse.buffer import Node, VirtualBuffer
		from tiresias.mathpres import browse_support
		from tiresias.objects.roles import Role

		buf = VirtualBuffer(None)
		text1 = "Texto "
		mathText = "x igual a un\nmedio"
		buf.text = text1 + mathText + " fin\n"
		ms = len(text1)
		me = ms + len(mathText)
		t = Node()
		t.role = Role.STATICTEXT
		t.start, t.end = 0, ms
		m = Node()
		m.role = Role.MATH
		m.start, m.end = ms, me
		t2 = Node()
		t2.role = Role.STATICTEXT
		t2.start, t2.end = me, len(buf.text)
		buf.nodes = [t, m, t2]
		buf.chunks = [(0, ms, t), (ms, me, m), (me, len(buf.text), t2)]
		buf._chunkStarts = [c[0] for c in buf.chunks]
		buf._mathByNode = {id(m): "<math><mi>x</mi><mo>=</mo><mfrac><mn>1</mn><mn>2</mn></mfrac></math>"}

		class Doc:
			pass

		doc = Doc()
		doc.buffer = buf
		doc.caret = caret
		return doc, browse_support

	def test_formula_shown_once(self) -> None:
		doc, bs = self._doc(caret=0)
		s, e = doc.buffer.lineBounds(0)
		text1, cur1 = bs.brailleLine(doc, s, e)
		second = doc.buffer.text.index("medio")
		doc.caret = second
		s2, e2 = doc.buffer.lineBounds(second)
		text2, cur2 = bs.brailleLine(doc, s2, e2)
		self.assertEqual(text1.rstrip("\n"), "Texto ⠭⠶⠼⠁⠆ fin")
		self.assertEqual(text1, text2)
		self.assertEqual(cur1, 0)
		self.assertEqual(cur2, len("Texto "))
		self.assertEqual(text1.count("⠭"), 1)

	def test_latex_alt_detection(self) -> None:
		from tiresias.mathpres import browse_support

		self.assertTrue(browse_support.isLatexAlt(r"{\displaystyle x^{2}+1}"))
		self.assertTrue(browse_support.isLatexAlt(r"\frac{a}{b}"))
		self.assertFalse(browse_support.isLatexAlt("raíz de dos"))
		self.assertFalse(browse_support.isLatexAlt("Foto de la playa"))


class BrowseIntegrationTests(unittest.TestCase):
	def test_quick_nav_key(self) -> None:
		from tiresias.browse.document import QUICK_NAV
		from tiresias.browse.buffer import Node
		from tiresias.objects.roles import Role

		# Los tipos sin tecla («») se asignan desde «Gestos de entrada».
		keys = [q[0] for q in QUICK_NAV if q[0]]
		self.assertEqual(len(keys), len(set(keys)), "letras de navegación rápida repetidas")
		entry = next(q for q in QUICK_NAV if q[1] == "math")
		self.assertEqual(entry[0], "0")
		n = Node()
		n.role = Role.MATH
		self.assertTrue(entry[4](n))


if __name__ == "__main__":
	unittest.main()
