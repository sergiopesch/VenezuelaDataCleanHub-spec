# MVP Learnings

The Hugging Face MVP was valuable because it tested real public APIs, real
volume, real throttling behavior, and the operational shape of duplicate review.

## Confirmed Volumes

The full public API run used these approximate source totals:

- `sos`: 52,363 records
- `localizados`: 4,448 records
- `venezuela_ayuda_missing`: 49,362 records
- `venezuela_ayuda_checkin`: 168 records

The Hugging Face run promoted:

- 106,348 raw records
- 106,342 normalized persons
- 26,227 duplicate pairs
- 26,040 duplicate groups

## Operational Lessons

- Full runs are long jobs, not UI button actions.
- Public APIs need source-specific throttling.
- SOS rate-limited burst traffic and required `API_WORKERS=1` plus delay.
- Persistent storage is mandatory.
- Report download paths need explicit runtime allowlists when using Gradio.
- One combined run with one promotion is better than repeated promote-per-chunk.
- Repeatable manifests are valuable, but they need approval and versioning.

## Data Lessons

- Names alone are insufficient.
- Cedula, phone, photo URL, image hash, phash, location, status, age, and date
  all add useful evidence.
- Some records have images, but full image download/hashing should be staged.
- Image and face processing must be separate jobs because they are slower and
  operationally more sensitive.
- Human review queues are not optional.

## Architecture Lessons

- DuckDB is excellent for local batch analysis and reports.
- PostgreSQL is needed for production multi-user operations.
- Gradio is useful for an operator/demo UI but not a production mobile API.
- Long-running work needs Temporal or equivalent durable orchestration.
- OpenClaw can help operations, but only through restricted APIs and runbooks.

