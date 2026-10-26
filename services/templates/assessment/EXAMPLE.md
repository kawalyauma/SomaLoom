# Assessment templates and examples

Agent 7 stores schema-compliant content in the bank rather than rendered HTML.
The student JSON envelope has: schema_version, document_type, audience=student,
title, school_name, term, duration_minutes, total_marks, instructions, page_size=A4,
sections[].title / total_marks / questions[]. Each question contains only its
number, stem, marks, options, available diagram IDs, LaTeX and response space.

The teacher envelope is a **different projection** (audience=teacher), containing
mark allocations, correct options, acceptable responses, stepwise working,
rubric, provenance and explanations. Never combine them into one PDF.

Use the synthetic `tests/test_assessments.py` fixtures to generate an exam,
a class test, a quiz, a numerical problem and a reviewed diagram question.
All example identifiers are random in tests, not actual Uganda schools or textbooks.
