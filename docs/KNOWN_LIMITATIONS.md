# Known limitations and release blockers

- Real Codex/API inference is BLOCKED pending a dedicated application credential and independently isolated Codex runner. CLI help/flags and internal mocks are not real-provider acceptance. Do not copy the mobile agent login or AWS role into provider containers.
- Real Telegram import is BLOCKED pending test bot credentials, authorized chat and reachable authenticated webhook. No arbitrary historical Telegram access is claimed.
- Official Uganda P5 curriculum material and educator acceptance are not supplied. QA curricula and authored passages are explicitly synthetic/enrichment; they are not presented as official curricula or genuine student documents.
- Semantic search is disabled without an independently provisioned embedding key/model. Keyword mode is explicitly reported; synthetic relevance tests are not a human-validated retrieval benchmark.
- OCR, layout and mathematical extraction have conservative confidence/review flags. Handwriting, complex multi-column/vector-only diagrams, ambiguous map labels and unsupported OMML/LaTeX need review. No unreadable region is filled with invented content.
- AI family validation checks structure, citations, marks, timing and coverage; it cannot prove scientific truth, source entailment, teaching suitability or general symbolic mathematics.
- Reviewed visual export supports bitmap originals with attribution. Arbitrary remote assets, unresolved visual_needed instructions and unsupported equations fail publication preflight. Political/geographical accuracy requires educator review.
- Public hostname/DNS and a publicly trusted TLS certificate remain owner-supplied. Private staging uses Session Manager and a self-signed localhost certificate; it is not an unrestricted public beta.
- Monitoring heartbeat/timeout recovery is implemented. Alert delivery, load/capacity tests, browser/device coverage and every external live integration require their own acceptance evidence.
- Upload transport is bounded and multi-file, not resumable. The browser uses durable asynchronous exports; the synchronous publishing API remains for compatibility. Explicit export cancellation is not yet exposed in the UI.
- Source-management and generation UI are connected. Advanced revision diff, targeted regeneration, sophisticated question-bank authoring UI and broad accessibility audits remain incomplete.
- Production rollback must use a verified backup/restore path or roll-forward. Feature migration downgrade intentionally removes feature tables; never apply it to live data without approval and a verified backup.

No production-readiness claim or overall completion percentage is made. See RELEASE_ACCEPTANCE.md for evidence and gates.
