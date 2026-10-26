"""Creates a reproducible mixed textbook passage and its structured output.

Usage: python -m services.extraction.demo --output /tmp/somaloom-demo
"""
from __future__ import annotations

import argparse
import base64
import io
from pathlib import Path
from uuid import uuid4

from PIL import Image, ImageDraw

from services.extraction.engine import extract_bytes


def passage() -> bytes:
    image = Image.new("RGB", (1200, 900), "white")
    draw = ImageDraw.Draw(image)
    draw.rectangle((150, 150, 1000, 650), outline="black", width=10)
    draw.line((150, 650, 1000, 150), fill="black", width=12)
    out = io.BytesIO()
    image.save(out, "PNG")
    data = base64.b64encode(out.getvalue()).decode()
    html = f"""<!doctype html><html><body>
    <h1>Chapter 1: Introduction to Energy</h1>
    <p>Energy is the capacity to do work. A moving object has kinetic energy.</p>
    <figure><img src="data:image/png;base64,{data}"
      alt="Figure 1: Diagram of a moving object"><figcaption>Figure 1:
      Diagram of a moving object</figcaption></figure>
    <h2>Table 1: Energy Examples</h2>
    <table><tr><th>Object</th><th>Energy type</th></tr>
      <tr><td>Moving bicycle</td><td>Kinetic energy</td></tr>
      <tr><td>Battery</td><td>Chemical energy</td></tr></table>
    <p>Mathematically, kinetic energy can be calculated using:</p>
    <math><annotation encoding="application/x-tex">E = \\frac{1}{2} m v^2</annotation></math>
    <h2>Exercise 1</h2><p>Calculate the kinetic energy of a moving object.</p>
    </body></html>"""
    return html.encode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/tmp/somaloom-demo"))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    assets = {}
    src = passage()
    result = extract_bytes(src, "text/html", resource_id=uuid4(), version_id=uuid4(),
                           license="CC0-demo-synthetic",
                           put_asset=lambda key, raw: assets.setdefault(key, raw))
    (output / "passage.html").write_bytes(src)
    (output / "document.json").write_text(result.model_dump_json(indent=2))
    for key, raw in assets.items():
        target = output / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    kinds = {b.type.value for b in result.blocks}
    assert {"heading", "paragraph", "figure", "table", "equation"}.issubset(kinds), kinds
    assert any(b.latex for b in result.blocks if b.type.value == "equation")
    print(f"Wrote passage, {len(result.blocks)} blocks, {len(result.assets)} assets to {output}")


if __name__ == "__main__":
    main()
