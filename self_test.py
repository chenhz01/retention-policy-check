#!/usr/bin/env python3
"""Self-test for retention-policy-check. Pure stdlib. Run: python self_test.py"""
import contextlib
import io
import json
import os
import shutil
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import retention_policy_check as rpc  # noqa: E402

NOW = "2026-10-11T00:00:00+00:00"
TESTS = []


def test(name):
    def deco(fn):
        TESTS.append((name, fn))
        return fn
    return deco


def expect_check_error(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except rpc.CheckError:
        return
    raise AssertionError("expected CheckError")


def wf(text, name="f"):
    d = tempfile.mkdtemp()
    p = os.path.join(d, name)
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return d, p


def rec(rid, policy, ts):
    return {"id": rid, "policy": policy, "timestamp": ts}


def days_before(days, base="2026-10-11T00:00:00Z"):
    from datetime import datetime, timedelta, timezone
    t = datetime(2026, 10, 11, tzinfo=timezone.utc) - timedelta(days=days)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------- functional unit tests ----------------

@test("policy_flat_days_format")
def _():
    assert rpc.load_policy.__name__ == "load_policy"
    d, p = wf(json.dumps({"logs": 30}))
    try:
        assert rpc.load_policy(p) == {"logs": 30}
    finally:
        shutil.rmtree(d)


@test("policy_object_format")
def _():
    d, p = wf(json.dumps({"logs": {"retain_days": 30, "owner": "ops"}}))
    try:
        assert rpc.load_policy(p) == {"logs": 30}
    finally:
        shutil.rmtree(d)


@test("fresh_record_compliant")
def _():
    policies = {"logs": 30}
    r = rpc.scan([rec("a", "logs", days_before(1))], policies, rpc.parse_timestamp(NOW))
    assert r["overdue"] == [] and r["errors"] == []


@test("old_record_overdue")
def _():
    r = rpc.scan([rec("a", "logs", days_before(40))], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert len(r["overdue"]) == 1 and r["overdue"][0]["age_days"] > 30


@test("boundary_exact_retain_days_not_overdue")
def _():
    r = rpc.scan([rec("a", "logs", days_before(30))], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["overdue"] == []


@test("boundary_one_second_over")
def _():
    ts = "2026-09-10T23:59:59Z"  # 30.0000115 days before NOW
    r = rpc.scan([rec("a", "logs", ts)], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert len(r["overdue"]) == 1


@test("per_policy_stats_counted")
def _():
    records = [rec("a", "logs", days_before(1)), rec("b", "logs", days_before(99))]
    r = rpc.scan(records, {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["per_policy"]["logs"] == {"total": 2, "overdue": 1}


@test("z_suffix_parsed")
def _():
    ts = rpc.parse_timestamp("2026-01-01T00:00:00Z")
    assert ts.tzinfo is not None


@test("naive_timestamp_treated_as_utc")
def _():
    a = rpc.parse_timestamp("2026-01-01T00:00:00")
    b = rpc.parse_timestamp("2026-01-01T00:00:00Z")
    assert a == b


@test("offset_timestamp_normalized")
def _():
    a = rpc.parse_timestamp("2026-01-01T08:00:00+08:00")
    b = rpc.parse_timestamp("2026-01-01T00:00:00Z")
    assert a == b


@test("jsonl_records_loaded")
def _():
    d, p = wf(json.dumps(rec("a", "logs", days_before(1))) + "\n" +
              json.dumps(rec("b", "logs", days_before(2))) + "\n")
    try:
        records, errors = rpc.load_records(p)
        assert len(records) == 2 and errors == []
    finally:
        shutil.rmtree(d)


@test("jsonl_blank_lines_skipped")
def _():
    d, p = wf(json.dumps(rec("a", "x", NOW)) + "\n\n\n")
    try:
        records, errors = rpc.load_records(p)
        assert len(records) == 1 and errors == []
    finally:
        shutil.rmtree(d)


@test("cli_end_to_end_overdue_exit_1")
def _():
    d1, pp = wf(json.dumps({"logs": 30}))
    d2, rp = wf(json.dumps([rec("a", "logs", days_before(99))]))
    try:
        assert rpc.main([rp, "--policy", pp, "--now", NOW]) == 1
    finally:
        shutil.rmtree(d1), shutil.rmtree(d2)


@test("cli_clean_exit_0")
def _():
    d1, pp = wf(json.dumps({"logs": 30}))
    d2, rp = wf(json.dumps([rec("a", "logs", days_before(1))]))
    try:
        assert rpc.main([rp, "--policy", pp, "--now", NOW]) == 0
    finally:
        shutil.rmtree(d1), shutil.rmtree(d2)


# ---------------- exception-path tests ----------------

@test("policy_negative_days_raises")
def _():
    d, p = wf(json.dumps({"logs": -5}))
    try:
        expect_check_error(rpc.load_policy, p)
    finally:
        shutil.rmtree(d)


@test("policy_zero_days_raises")
def _():
    d, p = wf(json.dumps({"logs": 0}))
    try:
        expect_check_error(rpc.load_policy, p)
    finally:
        shutil.rmtree(d)


@test("policy_bool_days_raises")
def _():
    d, p = wf(json.dumps({"logs": True}))
    try:
        expect_check_error(rpc.load_policy, p)
    finally:
        shutil.rmtree(d)


@test("policy_corrupt_json_raises")
def _():
    d, p = wf("{oops")
    try:
        expect_check_error(rpc.load_policy, p)
    finally:
        shutil.rmtree(d)


@test("policy_missing_file_raises")
def _():
    expect_check_error(rpc.load_policy, os.path.join(tempfile.mkdtemp(), "gone.json"))


@test("records_corrupt_json_array_raises")
def _():
    d, p = wf("[{broken")
    try:
        expect_check_error(rpc.load_records, p)
    finally:
        shutil.rmtree(d)


@test("records_invalid_jsonl_line_reported")
def _():
    d, p = wf(json.dumps(rec("a", "x", NOW)) + "\nnot json\n")
    try:
        records, errors = rpc.load_records(p)
        assert len(records) == 1 and len(errors) == 1
    finally:
        shutil.rmtree(d)


@test("unknown_policy_flagged")
def _():
    r = rpc.scan([rec("a", "ghost", days_before(1))], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert any("unknown policy" in e["error"] for e in r["errors"])


@test("bad_timestamp_flagged")
def _():
    r = rpc.scan([rec("a", "logs", "not-a-date")], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert any("bad timestamp" in e["error"] for e in r["errors"])


@test("numeric_timestamp_flagged")
def _():
    r = rpc.scan([rec("a", "logs", 12345)], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["errors"] and not r["overdue"]


@test("non_object_record_flagged")
def _():
    r = rpc.scan(["just a string"], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert any("not an object" in e["error"] for e in r["errors"])


@test("missing_id_still_checked")
def _():
    r = rpc.scan([{"policy": "logs", "timestamp": days_before(1)}],
                 {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["checked"] == 1


@test("bad_now_option_exit_2")
def _():
    d1, pp = wf(json.dumps({"logs": 30}))
    d2, rp = wf(json.dumps([]))
    try:
        assert rpc.main([rp, "--policy", pp, "--now", "yesterday"]) == 2
    finally:
        shutil.rmtree(d1), shutil.rmtree(d2)


# ---------------- extreme-edge tests ----------------

@test("empty_records_clean_report")
def _():
    r = rpc.scan([], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["checked"] == 0 and r["overdue"] == [] and r["errors"] == []


@test("empty_records_file")
def _():
    d, p = wf("")
    try:
        records, errors = rpc.load_records(p)
        assert records == [] and errors == []
    finally:
        shutil.rmtree(d)


@test("future_timestamp_anomaly")
def _():
    r = rpc.scan([rec("a", "logs", "2027-01-01T00:00:00Z")], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert len(r["anomalies"]) == 1 and r["overdue"] == []


@test("unicode_record_id")
def _():
    r = rpc.scan([rec("记录-🚀", "logs", days_before(99))], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["overdue"][0]["id"] == "记录-🚀"


@test("microsecond_timestamps_ok")
def _():
    r = rpc.scan([rec("a", "logs", "2026-10-10T12:00:00.123456+00:00")],
                 {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["overdue"] == []


@test("very_old_record_epoch")
def _():
    r = rpc.scan([rec("a", "logs", "1970-01-01T00:00:00Z")], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["overdue"][0]["age_days"] > 20000


@test("many_records_bulk_scan")
def _():
    records = [rec("r%d" % i, "logs", days_before(i % 100)) for i in range(1000)]
    r = rpc.scan(records, {"logs": 30}, rpc.parse_timestamp(NOW))
    # ages 0..99 repeated 10x each; ages 31..99 are overdue -> 69 distinct ages * 10 records
    assert r["checked"] == 1000 and len(r["overdue"]) == 690
    assert r["per_policy"]["logs"]["overdue"] == 690


@test("json_report_parseable")
def _():
    d1, pp = wf(json.dumps({"logs": 30}))
    d2, rp = wf(json.dumps([rec("a", "logs", days_before(99))]))
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rpc.main([rp, "--policy", pp, "--now", NOW, "--json"])
        data = json.loads(buf.getvalue())
        assert data["overdue"][0]["id"] == "a"
    finally:
        shutil.rmtree(d1), shutil.rmtree(d2)


@test("format_report_lists_overdue_lines")
def _():
    r = rpc.scan([rec("a", "logs", days_before(99))], {"logs": 30}, rpc.parse_timestamp(NOW))
    text = rpc.format_report(r)
    assert "OVERDUE a" in text


@test("policy_many_entries")
def _():
    d, p = wf(json.dumps({("p%d" % i): i + 1 for i in range(50)}))
    try:
        policies = rpc.load_policy(p)
        assert len(policies) == 50
    finally:
        shutil.rmtree(d)


@test("exactly_retain_days_not_overdue")
def _():
    r = rpc.scan([rec("edge", "logs", days_before(30))], {"logs": 30}, rpc.parse_timestamp(NOW))
    assert r["overdue"] == [] and r["errors"] == []


@test("per_policy_counts_track_multiple_policies")
def _():
    records = [rec("a", "logs", days_before(90)), rec("b", "db", days_before(1))]
    r = rpc.scan(records, {"logs": 30, "db": 7}, rpc.parse_timestamp(NOW))
    assert r["per_policy"]["logs"] == {"total": 1, "overdue": 1}
    assert r["per_policy"]["db"] == {"total": 1, "overdue": 0}


@test("scan_report_is_json_serializable")
def _():
    r = rpc.scan([rec("x", "logs", days_before(99))], {"logs": 30}, rpc.parse_timestamp(NOW))
    json.dumps(r, ensure_ascii=False)


@test("empty_records_file_json_array")
def _():
    d1, pp = wf(json.dumps({"logs": 30}))
    d2, rp = wf("[]")
    try:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert rpc.main([rp, "--policy", pp, "--now", NOW, "--json"]) == 0
        data = json.loads(buf.getvalue())
        assert data["checked"] == 0
    finally:
        shutil.rmtree(d1), shutil.rmtree(d2)


def main():
    passed = failed = 0
    for name, fn in TESTS:
        try:
            fn()
            passed += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print("FAIL %s: %r" % (name, exc))
    print("passed=%d failed=%d total=%d" % (passed, failed, passed + failed))
    print("SUMMARY: PASS %d/%d" % (passed, passed + failed))
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
