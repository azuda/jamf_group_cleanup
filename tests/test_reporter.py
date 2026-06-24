import os
import reporter
from resolver import ResolvedMerge
from executor import MergeResult


def _make_resolved(source_name="Old Group", target_name="New Group",
                   source_is_smart=False, group_type="computer",
                   delta=None, already_present=None, target_members=None):
    delta = delta or [101, 102]
    already_present = already_present or []
    target_members = target_members or []
    return ResolvedMerge(
        source_id=1, source_name=source_name, source_is_smart=source_is_smart,
        source_members=delta + already_present,
        target_id=2, target_name=target_name, target_members=target_members,
        group_type=group_type, delta=delta, already_present=already_present,
    )


def _make_result(status, members_added=None, error=None, **resolved_kwargs):
    return MergeResult(
        resolved=_make_resolved(**resolved_kwargs),
        status=status,
        members_added=members_added or [],
        error=error,
    )


# ── print_dry_run ────────────────────────────────────────────────────────────

def test_dry_run_prints_source_and_target(capsys):
    resolved = [_make_resolved(source_name="Old Group", target_name="New Group")]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "Old Group" in out
    assert "New Group" in out


def test_dry_run_prints_member_counts(capsys):
    resolved = [_make_resolved(delta=[101, 102], already_present=[103])]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "2" in out  # delta count
    assert "1" in out  # already_present count


def test_dry_run_shows_smart_label(capsys):
    resolved = [_make_resolved(source_is_smart=True)]
    reporter.print_dry_run(resolved)
    out = capsys.readouterr().out
    assert "smart" in out.lower()


# ── print_results ────────────────────────────────────────────────────────────

def test_results_shows_ok(capsys):
    results = [_make_result("OK", members_added=[101, 102])]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "2" in out


def test_results_shows_skip(capsys):
    results = [_make_result("SKIP")]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[SKIP]" in out


def test_results_shows_fail_with_error(capsys):
    results = [_make_result("FAIL", error="PUT 500: server error")]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "500" in out


def test_results_summary_counts(capsys):
    results = [
        _make_result("OK", members_added=[101]),
        _make_result("SKIP"),
        _make_result("FAIL", error="err"),
    ]
    reporter.print_results(results)
    out = capsys.readouterr().out
    assert "1 succeeded" in out
    assert "1 skipped" in out
    assert "1 failed" in out


# ── write_log ────────────────────────────────────────────────────────────────

def test_write_log_creates_file(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("OK", members_added=[101])]
    reporter.write_log(results, log_path)
    assert os.path.exists(log_path)


def test_write_log_contains_status(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("OK", members_added=[101, 102])]
    reporter.write_log(results, log_path)
    content = open(log_path).read()
    assert "OK" in content
    assert "Old Group" in content


def test_write_log_records_errors(tmp_path):
    log_path = str(tmp_path / "test.log")
    results = [_make_result("FAIL", error="PUT 500: oops")]
    reporter.write_log(results, log_path)
    content = open(log_path).read()
    assert "PUT 500" in content


# ── scope reporter tests ──────────────────────────────────────────────────────
import io
import pytest
from unittest.mock import patch
from scope_resolver import ResolvedScope, ScopedObject
from scope_executor import ScopeResult


def _make_rs(objects=None):
    return ResolvedScope(
        source_id=1, source_name="Old Group",
        target_id=2, target_name="New Group",
        group_type="computer",
        objects=objects or [],
    )


def _make_obj(object_type="policy", already=False):
    return ScopedObject(
        object_id=10, object_name="Deploy Software",
        object_type=object_type, in_inclusions=True, in_exclusions=False,
        target_already_present=already,
    )


# ── print_scope_dry_run ───────────────────────────────────────────────────────

def test_dry_run_shows_header(capsys):
    reporter.print_scope_dry_run([])
    out = capsys.readouterr().out
    assert "DRY RUN" in out


def test_dry_run_counts_by_type(capsys):
    policy_obj = _make_obj("policy")
    profile_obj = _make_obj("osx_profile")
    rs = _make_rs([policy_obj, profile_obj])
    reporter.print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "Old Group" in out
    assert "New Group" in out
    assert "1" in out  # count appears


def test_dry_run_shows_already_has_target(capsys):
    rs = _make_rs([_make_obj(already=True)])
    reporter.print_scope_dry_run([rs])
    out = capsys.readouterr().out
    assert "Already has target" in out or "no-op" in out


# ── print_scope_results ───────────────────────────────────────────────────────

def test_scope_results_ok(capsys):
    obj = _make_obj()
    rs = _make_rs([obj])
    result = ScopeResult(resolved=rs, status="OK", objects_updated=[obj])
    reporter.print_scope_results([result])
    out = capsys.readouterr().out
    assert "[OK]" in out
    assert "Old Group" in out
    assert "1 object" in out or "1" in out


def test_scope_results_skip(capsys):
    rs = _make_rs([])
    result = ScopeResult(resolved=rs, status="SKIP")
    reporter.print_scope_results([result])
    out = capsys.readouterr().out
    assert "[SKIP]" in out


def test_scope_results_fail(capsys):
    rs = _make_rs([_make_obj()])
    result = ScopeResult(resolved=rs, status="FAIL", error="PUT 500: error")
    reporter.print_scope_results([result])
    out = capsys.readouterr().out
    assert "[FAIL]" in out
    assert "PUT 500" in out


def test_scope_results_summary(capsys):
    rs = _make_rs()
    results = [
        ScopeResult(resolved=rs, status="OK", objects_updated=[]),
        ScopeResult(resolved=rs, status="SKIP"),
        ScopeResult(resolved=rs, status="FAIL", error="err"),
    ]
    reporter.print_scope_results(results)
    out = capsys.readouterr().out
    assert "1 succeeded" in out
    assert "1 skipped" in out
    assert "1 failed" in out


# ── write_scope_log ───────────────────────────────────────────────────────────

def test_write_scope_log_creates_file(tmp_path):
    obj = _make_obj()
    rs = _make_rs([obj])
    result = ScopeResult(resolved=rs, status="OK", objects_updated=[obj])
    log_path = str(tmp_path / "test.log")
    reporter.write_scope_log([result], log_path)
    content = open(log_path).read()
    assert "OK" in content
    assert "Old Group" in content
    assert "Deploy Software" in content
    assert "DEPRECATED" in content


def test_write_scope_log_skip_no_deprecated(tmp_path):
    rs = _make_rs([])
    result = ScopeResult(resolved=rs, status="SKIP")
    log_path = str(tmp_path / "test.log")
    reporter.write_scope_log([result], log_path)
    content = open(log_path).read()
    assert "DEPRECATED" not in content
