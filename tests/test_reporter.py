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
