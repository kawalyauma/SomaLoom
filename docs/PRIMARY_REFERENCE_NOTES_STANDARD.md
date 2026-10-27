# SomaLoom Primary SST & Science Reference Notes Standard

**Status:** Implementation on `feat/pupil-notes-sst-science`. Tests are committed but **not run** in this GitHub-only environment; staging review required before deployment.

## Educational presentation target

Reference examples inspected by the product owner:

- *Excel Primary Five SST Notes, All Terms* (213-page document): topic/subtopic heading hierarchy, meanings, short standalone facts, enumerations for roles/causes/advantages, comparison tables, maps, and end-of-topic exercises.
- *Paramount P6 Science, Terms 2–3* (161-page document): definitions, characteristics and functions, labeled drawings, classification flowcharts, experiments and short factual bullet lists.

These sources are **layout/style examples only**. Do not copy their prose, photographs, maps, diagrams or tables without suitable rights. Some pages contain outdated names and facts or transcription errors. Factual claims must be checked against authorized, reliable and current sources.

## Source of truth and mode selection

The generating AI should follow this standard automatically when:
- the document family is `lesson_notes`; and
- the school curriculum topic's canonical subject is Social Studies (SST) or Science.

The API obtains the canonical subject from the tenant-scoped topic table and records it under `spec.planning_scope.source_subject_name`; user-supplied display names cannot override that canonical field. The shared `teaching.v1` schema and the other three teaching document families are unchanged.

## Editorial requirements

1. A bold meaningful topic/subtopic heading.
2. One- or two-sentence definition, in simple correct English.
3. One separate fact or answer per bullet and per newline; no paragraph disguising a list.
4. Detailed **coverage of all permitted evidence-supported concepts**, including several grouped subtopics in a comprehensive document. Thorough means *more useful facts*, not more words in each sentence.
5. SST: geography, public institutions, locations, causes and effects, importance, comparison tables and accurate map requests.
6. Science: groups/classes, structure, characteristics, functions, adaptations, procedure-observation-conclusion, labeled scientific diagrams and appropriate equations.
7. Avoid material that belongs in a lesson plan (repetitive teacher scripts, multi-paragraph reflections, long introductions). Keep the explanatory/learning section dominant; exercises and references remain.
8. Produce authentic citations from the provided evidence, flag unsupported or outdated facts, and leave `review_status=needs_review`.
9. When approved visuals do not exist, use a precise `visual_needed` request rather than inventing assets.
10. Never pad thin schemes into a fake comprehensive book. Search more sources or report a gap.
11. Do not plagiarize the publisher references.

**Example original output**

### SST — Government of Uganda
**Meaning**
- Government consists of people and institutions responsible for public affairs.
- Uganda has central and local government.
**Some roles**
- To maintain law and order.
- To provide public services.
- To protect citizens.

### Science — Classification of plants
**Flowering plants**
- Flowering plants produce flowers.
- They reproduce through seeds.
**Non-flowering plants**
- Ferns and mosses reproduce by spores.
- Conifers produce seeds in cones.

These examples are illustrative, not source-backed book extracts.

## Quality gate

For SST/Science notes, the explanation section must have at least **3** (`concise`), **5** (`standard`) or **8** (`comprehensive`) distinct newline-separated factual bullets. Missing bullets are a **validation error**. Long facts (over 32 words), dense explanatory paragraphs (over 65 words) and one-source evidence are **review warnings**. These are structural/editorial checks, not automated proof of factual truth.

When evidence is thin, the generator must report `teaching_quality_validation_failed` rather than silently producing narrative-only notes that appear ready to publish.

## Rendering

- The browser document preview now renders every newline-separated list fact as its own `<li>`.
- PDF and DOCX exporters already split list blocks on newlines to print separate bullets.
- Review and approval permissions remain unchanged.

## Tests / staging

Run locally on a clone or development EC2, **not through GitHub-hosted CI**:

    pytest -q tests/test_reference_notes_style.py tests/test_teaching_studio.py tests/test_agent8_publishing.py
    ruff check services/templates/teaching services/generation/families.py services/validators/teaching tests/test_reference_notes_style.py
    ruff format --check services/templates/teaching services/generation/families.py services/validators/teaching tests/test_reference_notes_style.py
    cd apps/web && npm ci && npm run typecheck && npm run build

Next, generate *P5 SST — Government of Uganda* and *P6 Science — Classification of Plants* using approved source material. Ask a Ugandan primary teacher to check every factual claim, the level of detail, vocabulary, coverage and rendered bullets/tables/visuals. Export both PDF and DOCX, compare page layouts with the reference documents and make adjustments.

Do not merge or deploy until tests and academic review are complete. `deploy/notesug-codex` is left unchanged.
