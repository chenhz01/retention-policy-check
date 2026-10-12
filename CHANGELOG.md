# Changelog

## v0.1.2 (2026-10-12)

Round-13 fix pass (self_test rc=1, 1 failure; <40 cases):

- test correction (test was wrong): many_records_bulk_scan expected 69
  overdue records, but 1000 records cycle ages 0..99 (each age repeated 10x),
  so ages 31..99 produce 69*10=690 overdue records; expectation fixed to 690
  and per_policy cross-check added
- tests added: exact retain-days boundary is not overdue, multi-policy
  per_policy stats, JSON-serializable report, empty records array via CLI
- self tests: 41/41 PASS (37 -> 41)


## v0.1.1 (2026-10-11)

Round-2 content iteration (self-review driven):

- test coverage: 43 -> 53 self tests (+23.3%), adding bool-retain rejection,
  invalid-JSONL reporting, numeric timestamps, microsecond stamps, epoch-age
  and 50-policy bulk loading
- documentation: README notes duplicate-ID non-deduplication and the
  naive-timestamp UTC assumption

## v0.1.0 (2026-10-11)

Initial release:

- policy loader: flat and object formats, positive-int validation
- record loader: JSON array or JSONL, per-line error recovery
- scan: overdue list, per-policy stats, anomalies (future ts), errors
- ISO-8601 parsing with Z/offset/naive-as-UTC normalization
- CLI: --policy --now --json; exit 0/1/2 discipline
- self_test.py: 43 tests across functional / exception-path / extreme-edge
