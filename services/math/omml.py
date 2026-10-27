"""Conservative converter for an explicitly supported subset of Office Math OMML.

Unknown layouts remain original OMML in metadata with needs_review=True.
"""

from __future__ import annotations


def _tag(element):
    return element.tag.rsplit("}", 1)[-1]


def _children(element, name):
    return [c for c in element if _tag(c) == name]


def _first(element, name):
    return next(iter(_children(element, name)), None)


def _convert(element):
    tag = _tag(element)
    if tag == "t":
        return element.text or ""
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sub", "sup", "deg"}:
        return "".join(_convert(c) for c in element)
    if tag == "r":
        return "".join(_convert(c) for c in element if _tag(c) == "t")
    if tag == "f":
        num, den = _first(element, "num"), _first(element, "den")
        if num is None or den is None:
            raise ValueError("incomplete_fraction")
        return r"\frac{" + _convert(num) + "}{" + _convert(den) + "}"
    if tag in {"sSup", "sSub", "sSubSup"}:
        base = _first(element, "e")
        if base is None:
            raise ValueError("missing_script_base")
        value = "{" + _convert(base) + "}"
        sub, sup = _first(element, "sub"), _first(element, "sup")
        if sub is not None:
            value += "_{" + _convert(sub) + "}"
        if sup is not None:
            value += "^{" + _convert(sup) + "}"
        return value
    if tag == "rad":
        base, deg = _first(element, "e"), _first(element, "deg")
        if base is None:
            raise ValueError("missing_radical")
        return (
            r"\sqrt[" + _convert(deg) + "]{" + _convert(base) + "}"
            if deg is not None and _convert(deg)
            else r"\sqrt{" + _convert(base) + "}"
        )
    if tag in {"rPr", "ctrlPr", "fPr", "sSupPr", "sSubPr", "sSubSupPr", "radPr"}:
        return ""
    raise ValueError(f"unsupported_omml_node:{tag}")


def omml_to_latex(element) -> str | None:
    try:
        value = _convert(element)
        return value if value.strip() else None
    except (ValueError, TypeError):
        return None
