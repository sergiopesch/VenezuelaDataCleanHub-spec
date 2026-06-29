# Multimodal Review Policy

This project may eventually use AI to assist reviewers with image-heavy records.
That work must be staged carefully. The goal is reviewer assistance, not
autonomous identity decisions.

## Allowed Near-Term Uses

Allowed research and prototype work, using synthetic or explicitly approved
data only:

- OCR or visual text extraction from images.
- Image quality checks.
- Detection of duplicated image files using SHA-256.
- Perceptual hash matching for near-duplicate images.
- Reviewer-facing summaries that explain why a record needs attention.
- OpenClaw runbook summaries for failed image-processing jobs.

## Not Allowed Without Separate Approval

The following require a separate policy, approval workflow, retention plan, and
audit model before implementation:

- Face recognition.
- Face embeddings.
- Biometric search.
- Automated identity merge decisions.
- Raw image export.
- Sending unredacted sensitive images or payloads to an external AI provider.

## Identity Authority

AI, OCR, image hashes, perceptual hashes, face detection, or biometric models
must never be the final identity authority. They can create evidence for human
review. They cannot approve a promotion, merge people, or override policy.

## OpenClaw Boundary

OpenClaw may help operate approved image-processing runbooks:

- summarize safe counters
- diagnose job failures
- open GitHub issues
- request human approval

OpenClaw must not read raw images, approve biometric processing, alter identity
records, or bypass OPA.

## Token Sponsorship Framing

If OpenAI token sponsorship is pursued, the initial work should be limited to a
synthetic-data multimodal review prototype with:

- no real personal data
- no autonomous identity decisions
- redacted prompts and outputs
- model/version tracking
- audit events
- documented reviewer workflow

The ask should be framed as operational and reviewer assistance for a secure
humanitarian data-cleanup platform.
