# Durable generation tracking

`/work` lists saved generation requests with status filters and pagination. `/work?job=<generation-id>` opens a permanent tracking view containing the saved class/subject/term/week/lesson, topics, timestamps, progress, activity, classified errors, retry/cancel actions and the finished document link. New submissions redirect there after the server has persisted them. The page polls every four seconds while visible and refreshes on focus; closing the page does not affect the job.

API: `GET /api/v1/generations` and `GET /api/v1/generations/{id}/activity`. Teachers see their own request list; school administrators see workspace requests. All queries are school-scoped. Read access to a request follows the existing school's document access, while cancel/retry ownership rules remain enforced server-side.

Activity entries are stored in existing `generation_jobs.parameters.activity`; no migration is needed. Submission, worker stage transitions, failure, completion, retry and cancellation append timestamped entries. Old requests are recovered from their persisted timestamps and current status without inventing past intermediate events. Terminal states set by timeout recovery are also reflected in the tracking view.

Worker stages now distinguish source research from AI drafting. A failed request retains its selection and error; retry reuses it. Existing retry limits apply. Provider failures remain failures and never appear as completed documents.

Deploy the API, web and worker code together. Preserve active workers until their current jobs finish when replacing containers. Tests: `tests/test_generation_history.py` covers durable details, tenant and requester scope, legacy requests, finished document links, stage events, retry and cancellation. Existing selection and master-scheme tests also run.
