"""Versioned, source-linked extraction payload; additive adapter to contracts.v1."""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field


class BlockType(StrEnum):
    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    equation = "equation"
    figure = "figure"
    map = "map"
    diagram = "diagram"
    chart = "chart"
    illustration = "illustration"
    exercise = "exercise"
    footnote = "footnote"


class SourceRef(BaseModel):
    resource_id: UUID
    version_id: UUID
    page: int = Field(ge=1)
    bbox: tuple[float, float, float, float] | None = None
    order: int = Field(ge=0)
    source_uri: str | None = None


class ExtractedBlock(BaseModel):
    id: UUID
    type: BlockType
    page: int = Field(ge=1)
    order: int = Field(ge=0)
    text: str | None = None
    latex: str | None = None
    table: list[list[str]] | None = None
    asset_id: UUID | None = None
    bbox: tuple[float, float, float, float] | None = None
    heading_path: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_review: bool = False
    source_ref: SourceRef
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedAsset(BaseModel):
    id: UUID
    type: BlockType
    page: int = Field(ge=1)
    object_key: str
    caption: str | None = None
    labels: list[str] = Field(default_factory=list)
    bbox: tuple[float, float, float, float] | None = None
    width: int | None = None
    height: int | None = None
    dpi: int | None = None
    checksum_sha256: str
    license: str
    attribution: str | None = None
    needs_review: bool = True
    confidence: float = Field(ge=0, le=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExtractedDocument(BaseModel):
    schema_version: str = "extraction.v1"
    resource_id: UUID
    version_id: UUID
    sha256: str
    blocks: list[ExtractedBlock] = Field(default_factory=list)
    assets: list[ExtractedAsset] = Field(default_factory=list)
    processing_warnings: list[str] = Field(default_factory=list)
    pages_processed: int = 0
    pages_total: int = 0
    partial: bool = False


def stable_id(version_id: UUID, category: str, page: int, order: int) -> UUID:
    """Deterministic IDs allow safe retries and deduplication."""
    return uuid5(NAMESPACE_URL, f"somaloom:{version_id}:{category}:{page}:{order}")


def add_block(
    doc: ExtractedDocument,
    type: BlockType,
    page: int,
    *,
    text: str | None = None,
    latex: str | None = None,
    table: list[list[str]] | None = None,
    asset_id: UUID | None = None,
    bbox: tuple[float, float, float, float] | None = None,
    confidence: float = 1.0,
    needs_review: bool = False,
    heading_path: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    source_uri: str | None = None,
) -> ExtractedBlock:
    order = len(doc.blocks)
    source = SourceRef(
        resource_id=doc.resource_id,
        version_id=doc.version_id,
        page=page,
        bbox=bbox,
        order=order,
        source_uri=source_uri,
    )
    block = ExtractedBlock(
        id=stable_id(doc.version_id, "block", page, order),
        type=type,
        page=page,
        order=order,
        text=text,
        latex=latex,
        table=table,
        asset_id=asset_id,
        bbox=bbox,
        heading_path=list(heading_path or []),
        confidence=confidence,
        needs_review=needs_review,
        source_ref=source,
        metadata=metadata or {},
    )
    doc.blocks.append(block)
    return block


def semantic_sections(doc: ExtractedDocument) -> list[dict[str, Any]]:
    """Make sections without splitting a figure from its surrounding blocks."""
    sections: list[dict[str, Any]] = []
    for block in doc.blocks:
        if block.type == BlockType.heading or not sections:
            sections.append(
                {
                    "heading": block.text if block.type == BlockType.heading else None,
                    "block_ids": [],
                    "pages": [],
                }
            )
        section = sections[-1]
        section["block_ids"].append(str(block.id))
        if block.page not in section["pages"]:
            section["pages"].append(block.page)
    return sections
