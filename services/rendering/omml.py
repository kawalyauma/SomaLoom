"""Conservative LaTeX -> editable Office Math XML conversion.

Supports common school math, not arbitrary TeX macros; rejects unsupported
commands rather than printing misleading plain text or screenshots.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
ET.register_namespace("m", NS)
SYMBOLS = {
    "times": "×",
    "cdot": "·",
    "div": "÷",
    "pm": "±",
    "neq": "≠",
    "leq": "≤",
    "geq": "≥",
    "pi": "π",
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "theta": "θ",
    "Delta": "Δ",
    "mu": "μ",
    "infty": "∞",
    "sin": "sin",
    "cos": "cos",
    "tan": "tan",
    "log": "log",
    "ln": "ln",
    "sum": "∑",
    "int": "∫",
    "rightarrow": "→",
    "Rightarrow": "⇒",
    "approx": "≈",
}


def _element(name: str, parent: ET.Element | None = None) -> ET.Element:
    if parent is None:
        return ET.Element(f"{{{NS}}}{name}")
    return ET.SubElement(parent, f"{{{NS}}}{name}")


def _run(text: str, normal: bool = False) -> ET.Element:
    node = _element("r")
    if normal:
        props = _element("rPr", node)
        _element("nor", props).set(f"{{{NS}}}val", "1")
    t = _element("t", node)
    if text != text.strip():
        t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    t.text = text
    return node


class _Parser:
    def __init__(self, src: str):
        self.src = src.strip().strip("$")
        self.i = 0

    def _peek(self) -> str:
        return self.src[self.i : self.i + 1]

    def _group(self) -> list[ET.Element]:
        if self._peek() != "{":
            raise ValueError("Math command requires a braced group")
        self.i += 1
        parts = self._sequence("}")
        if self._peek() != "}":
            raise ValueError("Unclosed math group")
        self.i += 1
        return parts

    @staticmethod
    def _wrap(name: str, parts: list[ET.Element], parent: ET.Element):
        el = _element(name, parent)
        for part in parts:
            el.append(part)

    def _command(self) -> list[ET.Element]:
        self.i += 1
        command = re.match(r"[A-Za-z]+", self.src[self.i :])
        if not command:
            if self.i < len(self.src):
                char = self.src[self.i]
                self.i += 1
                if char in {",", ";", ":", " ", "!"}:
                    return [
                        _run({",": "\u2009", ";": "\u2005", ":": "\u2005", " ": " ", "!": ""}[char])
                    ]
                return [_run(char)]
            raise ValueError("Dangling LaTeX backslash")
        word = command.group()
        self.i += len(word)
        if word in {"text", "mathrm"}:
            if self._peek() != "{":
                raise ValueError("Math text requires a braced group")
            end = self.src.find("}", self.i + 1)
            if end < 0:
                raise ValueError("Unclosed math text")
            literal = self.src[self.i + 1 : end]
            if "\\" in literal or "{" in literal:
                raise ValueError("Nested commands in math text are unsupported")
            self.i = end + 1
            return [_run(literal, normal=True)]
        if word in {"quad", "qquad"}:
            return [_run("\u2003" * (2 if word == "qquad" else 1))]
        if word == "frac":
            numerator, denominator = self._group(), self._group()
            f = _element("f")
            self._wrap("num", numerator, f)
            self._wrap("den", denominator, f)
            return [f]
        if word == "sqrt":
            degree = None
            if self._peek() == "[":
                end = self.src.find("]", self.i)
                if end == -1:
                    raise ValueError("Unclosed radical degree")
                degree = self.src[self.i + 1 : end]
                self.i = end + 1
            parts = self._group()
            rad = _element("rad")
            self._wrap("deg", [_run(degree)] if degree else [], rad)
            self._wrap("e", parts, rad)
            return [rad]
        if word == "begin":
            start = self.i
            self._group()
            name = self.src[start + 1 : self.i - 1]
            if name not in {"matrix", "pmatrix", "bmatrix"}:
                raise ValueError("Unsupported matrix environment")
            end_marker = r"\end{" + name + "}"
            end = self.src.find(end_marker, self.i)
            if end < 0:
                raise ValueError("Unclosed matrix")
            raw = self.src[self.i : end]
            self.i = end + len(end_marker)
            matrix = _element("m")
            rows = re.split(r"\\\\", raw)
            widths = set()
            for row in rows:
                values = row.split("&")
                widths.add(len(values))
                mrow = _element("mr", matrix)
                for value in values:
                    expr = _Parser(value.strip())._sequence()
                    self._wrap("e", expr, mrow)
            if len(widths) != 1:
                raise ValueError("Inconsistent matrix widths")
            if name != "matrix":
                delim = _element("d")
                props = _element("dPr", delim)
                beg = _element("begChr", props)
                beg.set("val", "(" if name == "pmatrix" else "[")
                ending = _element("endChr", props)
                ending.set("val", ")" if name == "pmatrix" else "]")
                self._wrap("e", [matrix], delim)
                return [delim]
            return [matrix]
        if word in {"left", "right"}:
            ch = self._peek()
            if ch:
                self.i += 1
                return [_run(ch)]
            return []
        if word in SYMBOLS:
            return [_run(SYMBOLS[word])]
        raise ValueError("Unsupported LaTeX command: " + word)

    def _sequence(self, until: str = "") -> list[ET.Element]:
        result: list[ET.Element] = []
        while self.i < len(self.src) and (not until or self._peek() != until):
            c = self._peek()
            if c.isspace():
                self.i += 1
                continue
            if c == "\\":
                parts = self._command()
            elif c == "{":
                parts = self._group()
            elif c in "^_":
                self.i += 1
                if not result:
                    raise ValueError("Superscript or subscript without base")
                base = result.pop()
                if self._peek() == "{":
                    exponent = self._group()
                else:
                    if not self._peek():
                        raise ValueError("Missing exponent or subscript")
                    exponent = [_run(self._peek())]
                    self.i += 1
                kind = "sSup" if c == "^" else "sSub"
                el = _element(kind)
                self._wrap("e", [base], el)
                self._wrap("sup" if c == "^" else "sub", exponent, el)
                result.append(el)
                continue
            elif c == "}":
                raise ValueError("Unmatched closing brace")
            else:
                self.i += 1
                parts = [_run(c)]
            result.extend(parts)
        return result


def latex_to_omml(latex: str) -> ET.Element:
    if not latex or len(latex) > 10000:
        raise ValueError("Equation is empty or too long")
    parser = _Parser(latex)
    result = _element("oMath")
    for expression in parser._sequence():
        result.append(expression)
    return result
