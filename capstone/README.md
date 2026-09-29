# FMSE Capstone Studio

Default variant: **enterprise financial reconciliation assistant** — ingest bank/export files, reconcile
records, explain discrepancies with evidence, and prepare proposed actions while keeping financial
mutations behind explicit approval. An alternate SRE/MCP variant may be offered.

- `capstone-studio.ipynb` — milestone checklists, validators and completion-record export.
- `templates/milestones.yaml` — the evidence package, one section per EDP milestone review.
- `datasets/` — intentionally imperfect reference data (bank export, ledger entries, vendor master).

No complete implementation is supplied. Public checks are structural and run on the reference data;
unseen/held-out scenarios belong to the optional Phase 2 evaluator. The architecture defense is scored
in the portal with the Architecture Defense Rubric. Aggregate score cannot override a critical
safety/security gate.
