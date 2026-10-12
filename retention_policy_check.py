#!/usr/bin/env python3
"""retention-policy-check: declared data-retention policy vs actual timestamps.

Scans records (JSON array or JSONL) against a declared policy file, computes
record age, and reports overdue records, per-policy stats, and data errors.
Deterministic: pass --now to fix "today". Pure standard library.
"""
import argparse
import json
import sys
from datetime import datetime, timezone

SECONDS_PER_DAY = 86400.0


class CheckError(Exception):
    """Raised for unreadable or malformed inputs."""


def load_policy(path):
    """Accept {"name": days} or {"name": {"retain_days": days, ...}}."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except OSError as exc:
        raise CheckError("cannot read policy file: %s" % exc)
    except json.JSONDecodeError as exc:
        raise CheckError("policy file is not valid JSON: %s" % exc)
    if not isinstance(data, dict) or not data:
        raise CheckError("policy must be a non-empty JSON object")
    policies = {}
    for name, spec in data.items():
        if isinstance(spec, dict):
            retain = spec.get("retain_days")
        else:
            retain = spec
        if not isinstance(retain, int) or isinstance(retain, bool) or retain <= 0:
            raise CheckError("policy %r needs a positive integer retain_days" % name)
        policies[name] = retain
    return policies


def load_records(path):
    """Accept a JSON array or JSON Lines; returns list of dicts."""
    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise CheckError("cannot read records file: %s" % exc)
    except UnicodeDecodeError:
        raise CheckError("records file is not valid UTF-8")
    records, errors = [], []
    stripped = text.lstrip()
    if stripped.startswith("["):
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise CheckError("records file is not valid JSON: %s" % exc)
        if not isinstance(data, list):
            raise CheckError("records JSON must be an array")
        return data, errors
    for lineno, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError as exc:
            errors.append({"line": lineno, "error": "invalid JSON line: %s" % exc})
    return records, errors


def parse_timestamp(value):
    """Parse ISO-8601; 'Z' suffix allowed; naive treated as UTC. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def scan(records, policies, now_utc, errors=None):
    """Return compliance report dict."""
    errors = list(errors or [])
    overdue, per_policy = [], {name: {"total": 0, "overdue": 0} for name in policies}
    anomalies = []
    checked = 0
    for idx, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append({"record": idx, "error": "record is not an object"})
            continue
        checked += 1
        rid = record.get("id", "<missing-id>")
        policy_name = record.get("policy")
        if policy_name not in policies:
            errors.append({"record": idx, "id": rid,
                           "error": "unknown policy %r" % str(policy_name)})
            continue
        try:
            ts = parse_timestamp(record.get("timestamp"))
        except (ValueError, TypeError) as exc:
            errors.append({"record": idx, "id": rid, "error": "bad timestamp: %s" % exc})
            continue
        per_policy[policy_name]["total"] += 1
        age_days = (now_utc - ts).total_seconds() / SECONDS_PER_DAY
        if age_days < 0:
            anomalies.append({"id": rid, "policy": policy_name,
                              "detail": "future timestamp: %s" % record.get("timestamp")})
            continue
        retain = policies[policy_name]
        if age_days > retain:
            per_policy[policy_name]["overdue"] += 1
            overdue.append({"id": rid, "policy": policy_name,
                            "age_days": round(age_days, 2), "retain_days": retain})
    return {
        "now": now_utc.isoformat(),
        "checked": checked,
        "compliant": checked - len(overdue) - sum(1 for e in errors if "record" in e and "policy" not in e) if checked else 0,
        "overdue": overdue,
        "anomalies": anomalies,
        "errors": errors,
        "per_policy": per_policy,
    }


def format_report(report):
    lines = ["retention check @ %s" % report["now"],
             "checked: %d, overdue: %d, errors: %d, anomalies: %d" % (
                 report["checked"], len(report["overdue"]),
                 len(report["errors"]), len(report["anomalies"]))]
    for item in report["overdue"]:
        lines.append("OVERDUE %s (policy %s): %.2f days > %d retain" % (
            item["id"], item["policy"], item["age_days"], item["retain_days"]))
    for item in report["anomalies"]:
        lines.append("ANOMALY %s: %s" % (item["id"], item["detail"]))
    for item in report["errors"]:
        lines.append("ERROR %s" % json.dumps(item, ensure_ascii=False))
    for name, stats in sorted(report["per_policy"].items()):
        lines.append("policy %s: %d/%d overdue" % (name, stats["overdue"], stats["total"]))
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="retention-policy-check", description=__doc__)
    parser.add_argument("records", help="records file: JSON array or JSONL")
    parser.add_argument("--policy", required=True, help="policy JSON file")
    parser.add_argument("--now", help="ISO-8601 'today' (default: real now, UTC)")
    parser.add_argument("--json", action="store_true", help="emit JSON report")
    args = parser.parse_args(argv)
    try:
        policies = load_policy(args.policy)
        records, file_errors = load_records(args.records)
        if args.now:
            try:
                now_utc = parse_timestamp(args.now)
            except ValueError:
                raise CheckError("--now is not a valid ISO-8601 timestamp: %r" % args.now)
        else:
            now_utc = datetime.now(timezone.utc)
        report = scan(records, policies, now_utc, errors=file_errors)
    except CheckError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else format_report(report))
    return 0 if not (report["overdue"] or report["errors"] or report["anomalies"]) else 1


if __name__ == "__main__":
    sys.exit(main())
