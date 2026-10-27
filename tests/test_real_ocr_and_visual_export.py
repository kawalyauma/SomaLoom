"""Real Tesseract and printed visual artifacts using original, synthetic CC0 fixtures."""

from io import BytesIO
from pathlib import Path
from uuid import uuid4
from zipfile import ZipFile

import pymupdf
from app.core.config import get_settings
from app.core.models import extractions, visuals
from app.core.storage import configured_store
from conftest import sign_in
from PIL import Image, ImageDraw, ImageFont
from sqlalchemy import select
from test_agent04 import make_version

from services.export.assets import resolver
from services.export.publishing import export_docx, export_pdf
from services.extraction.engine import extract_bytes


def test_real_scanned_pdf_ocr():
    image = Image.new("RGB", (1200, 500), "white")
    draw = ImageDraw.Draw(image)
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 38)
    draw.text((40, 60), "Water filtration", fill="black", font=font)
    draw.text((40, 140), "A filter traps suspended particles.", fill="black", font=font)
    draw.text((40, 220), "Water may still contain pathogens.", fill="black", font=font)
    png = BytesIO()
    image.save(png, format="PNG")
    pdf = pymupdf.open()
    pdf.new_page(width=600, height=250).insert_image(
        pymupdf.Rect(0, 0, 600, 250), stream=png.getvalue()
    )
    raw = pdf.tobytes()
    pdf.close()
    result = extract_bytes(
        raw, "application/pdf", resource_id=uuid4(), version_id=uuid4(), license="CC0-1.0"
    )
    text = " ".join(b.text or "" for b in result.blocks).lower()
    assert "filtration" in text and "particles" in text and "pathogens" in text
    assert result.pages_processed == 1
    assert all(b.source_ref.page == 1 for b in result.blocks)


def test_reviewed_diagram_map_math_and_multipage_exports(
    db, accounts, monkeypatch, tmp_path, client
):
    tenant = accounts[0][0].id
    monkeypatch.setattr(get_settings(), "storage_root", str(tmp_path))
    version, _block = make_version(
        db, tenant, "An original synthetic school campus map and filter diagram."
    )
    extraction = db.scalar(
        select(extractions.c.id).where(extractions.c.resource_version_id == version)
    )
    store = configured_store()
    ids = []
    font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 22)
    for kind in ["diagram", "map"]:
        image = Image.new("RGB", (850, 420), "white")
        draw = ImageDraw.Draw(image)
        if kind == "diagram":
            draw.text(
                (30, 20), "Model filter: suspended solids are trapped", fill="black", font=font
            )
            draw.polygon([(270, 100), (570, 100), (470, 260), (370, 260)], outline="black", width=4)
            draw.line((315, 170, 520, 170), fill="blue", width=5)
            draw.text((590, 160), "Filter layer", fill="black", font=font)
            draw.line((425, 270, 425, 330), fill="blue", width=5)
            draw.text(
                (180, 360), "Filtered water may still contain pathogens", fill="black", font=font
            )
        else:
            draw.text(
                (25, 20), "Fictional school campus — original teaching map", fill="black", font=font
            )
            draw.rectangle((70, 100, 250, 220), fill="#d6e8f0", outline="black", width=3)
            draw.text((90, 140), "Classrooms", fill="black", font=font)
            draw.rectangle((340, 100, 560, 220), fill="#bde4be", outline="black", width=3)
            draw.text((370, 145), "Garden", fill="black", font=font)
            draw.text((640, 100), "N ↑", fill="black", font=font)
            draw.text(
                (40, 285), "Legend: blue = buildings; green = garden", fill="black", font=font
            )
            draw.text(
                (40, 340), "Illustrative plan; not a geographic survey", fill="black", font=font
            )
        raw = BytesIO()
        image.save(raw, format="PNG")
        aid = uuid4()
        key = f"original-qa/{aid}.png"
        store.put(tenant, key, raw.getvalue())
        db.execute(
            visuals.insert().values(
                id=aid,
                tenant_id=tenant,
                extraction_id=extraction,
                object_key=key,
                kind=kind,
                page=1,
                caption=f"Original QA {kind}",
                provenance={
                    "source_uri": "fixture://somaloom-authored-cc0",
                    "license": "CC0-1.0",
                    "needs_review": True,
                },
            )
        )
        ids.append(aid)
    db.commit()
    client.headers["Origin"] = "http://localhost:3000"
    assert sign_in(client, "reviewer0@example.org").status_code == 200
    for aid in ids:
        response = client.post(
            f"/api/v1/assets/{aid}/review", json={"accuracy_checked": True, "license_checked": True}
        )
        assert response.status_code == 200, response.text
    document = {
        "title": "SYNTHETIC QA: science, mathematics and campus maps",
        "review_state": "approved",
        "evidence_ids": [],
        "body": {
            "sections": [
                {
                    "title": "Fractions and observations",
                    "blocks": [
                        {
                            "id": "equation",
                            "type": "equation",
                            "latex": r"\frac{1}{2}+x^2=\sqrt{9}",
                        },
                        {
                            "id": "table",
                            "type": "table",
                            "rows": [
                                ["Material", "Observation"],
                                ["Sieve", "Some particles are trapped"],
                            ],
                        },
                        {"id": "diagram", "type": "diagram", "asset_ref": str(ids[0])},
                        {"id": "page", "type": "page_break"},
                        {"id": "map", "type": "map", "asset_ref": str(ids[1])},
                        {
                            "id": "explanation",
                            "type": "paragraph",
                            "text": "Original QA explanation: use a model filter safely, observe particles and record limitations. "
                            * 120,
                        },
                        {
                            "id": "reference",
                            "type": "reference",
                            "text": "Source: SomaLoom original QA fixtures, fixture://somaloom-authored-cc0, CC0-1.0. Fictional campus, not national geography.",
                        },
                    ],
                }
            ]
        },
    }
    asset_resolver = resolver(db, tenant)
    docx = export_docx(document, asset_resolver=asset_resolver)
    with ZipFile(BytesIO(docx)) as archive:
        assert len([n for n in archive.namelist() if n.startswith("word/media/")]) == 2
        assert b"<m:f>" in archive.read("word/document.xml")
    pdf = export_pdf(document, asset_resolver=asset_resolver)
    with pymupdf.open(stream=pdf, filetype="pdf") as opened:
        assert len(opened) >= 3
        assert "CC0-1.0" in "".join(p.get_text() for p in opened)
        # The actual image contains the legend; captions also preserve attribution.
    output = Path("verification/representative")
    output.mkdir(parents=True, exist_ok=True)
    (output / "document.pdf").write_bytes(pdf)
    (output / "document.docx").write_bytes(docx)
    with pymupdf.open(stream=pdf, filetype="pdf") as opened:
        for page in opened:
            page.get_pixmap(matrix=pymupdf.Matrix(1, 1)).save(
                output / f"page-{page.number + 1}.png"
            )
    assert sign_in(client, "teacher1@example.org").status_code == 200
    assert client.get(f"/api/v1/assets/{ids[0]}/download").status_code == 404
