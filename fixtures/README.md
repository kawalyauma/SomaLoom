# Teaching Studio test fixtures

The deterministic fixture factory in `tests/test_teaching_studio.py` supplies **all four output types** with a fictional teacher-provided outcome and original sample on water filtration. It uses the label `teacher-supplied-2026`, not an NCDC Ugandan curriculum code.

A primary mathematics demonstration additionally uses native LaTeX, a table and a licensed visual-asset reference. This mechanical validation fixture is **not** a claim that the water-filtration outcome belongs to a mathematics syllabus.

Before production use, Agent 4 must provide curriculum-authorized and tenant-filtered real outcomes, evidence and visual permissions. Tests do not call external AI providers or claim official curriculum verification.
