"""Preserve structured native equations, never hallucinate image-to-LaTeX recognition."""
from __future__ import annotations

import re
from dataclasses import dataclass

SUPERSCRIPTS = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻", "0123456789+-")
MATH_TOKENS = ("=", "±", "√", "∑", "∫", "≤", "≥", "≠", "\\frac", "\\sqrt")
SIMPLE_FRACTION = re.compile(r"(?<![\w}])(\d+|[a-zA-Z])\s*/\s*(\d+|[a-zA-Z])(?![\w{])")
SIMPLE_POWER = re.compile(r"([a-zA-Z0-9])\s*\^\s*([a-zA-Z0-9]|\{[^{}]+\})")
ALLOWED_COMMANDS = {
    "frac", "dfrac", "tfrac", "sqrt", "sum", "int", "lim", "sin", "cos", "tan",
    "pi", "theta", "alpha", "beta", "gamma", "delta", "Delta", "lambda", "mu",
    "sigma", "times", "cdot", "div", "pm", "leq", "geq", "neq", "infty",
    "left", "right", "begin", "end", "mathrm", "text", "overline", "vec",
    "hat", "bar", "circ", "angle", "perp", "parallel", "to",
}
SAFE_ENVS = {"matrix", "bmatrix", "pmatrix", "cases", "aligned", "align", "gathered"}


@dataclass(frozen=True)
class EquationAnalysis:
    latex: str | None
    confidence: float
    valid: bool
    needs_review: bool
    warning: str | None = None


def is_equation(text: str) -> bool:
    t = text.strip()
    return (bool(t) and len(t) < 300 and
            (any(token in t for token in MATH_TOKENS) or
             bool(re.search(r"\w\s*\^\s*[\w{]", t))) and
            bool(re.search(r"[\dA-Za-z\\∑∫√]", t)))


def _balanced(value: str) -> bool:
    stack: list[str] = []
    for char in value:
        if char == "{":
            stack.append(char)
        elif char == "}":
            if not stack:
                return False
            stack.pop()
    return not stack


def _normalize_superscripts(value: str) -> str:
    return re.sub(r"([a-zA-Z0-9)])([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)",
                  lambda m: m.group(1) + "^{" + m.group(2).translate(SUPERSCRIPTS) + "}",
                  value)


def analyze_equation(source: str, *, is_ocr: bool = False) -> EquationAnalysis:
    text = source.strip().strip("$").strip()
    if not text or len(text) > 4000:
        return EquationAnalysis(None, 0, False, True, "empty_or_oversized_equation")
    text = _normalize_superscripts(text)
    for a, b in {"×": r"\times ", "÷": r"\div ", "·": r"\cdot ",
                 "√": r"\sqrt", "π": r"\pi ", "θ": r"\theta ",
                 "≤": r"\leq ", "≥": r"\geq ", "≠": r"\neq ",
                 "±": r"\pm ", "∑": r"\sum ", "∫": r"\int "}.items():
        text = text.replace(a, b)
    if "\\" not in text:
        text = SIMPLE_FRACTION.sub(lambda m: r"\frac{" + m[1] + "}{" + m[2] + "}", text)
        text = SIMPLE_POWER.sub(lambda m: m[1] + "^{" + m[2].strip("{}") + "}", text)
    commands = re.findall(r"\\([a-zA-Z]+)", text)
    unknown = set(commands) - ALLOWED_COMMANDS
    # Validation is conservative: syntax checks are not proof of mathematical fidelity.
    ok = _balanced(text) and not unknown
    environments = re.findall(r"\\(?:begin|end)\{([^}]+)\}", text)
    if environments and (any(e not in SAFE_ENVS for e in environments) or
                         len(re.findall(r"\\begin", text)) != len(re.findall(r"\\end", text))):
        ok = False
    confidence = (0.50 if is_ocr else 0.88) if ok else 0.15
    return EquationAnalysis(text if ok else None, confidence, ok,
                            is_ocr or not ok,
                            "ocr_equation_requires_review" if is_ocr else
                            ("unsupported_math_syntax" if not ok else None))


def check_math_rendering(latex: str) -> tuple[bool, str | None]:
    """Optional independent rendering syntax check using matplotlib MathText."""
    try:
        from matplotlib.mathtext import MathTextParser
    except ImportError:
        return False, "matplotlib_not_installed"
    try:
        MathTextParser("path").parse(f"${latex}$")
        return True, None
    except Exception:
        return False, "mathtext_render_failed_or_unsupported"
