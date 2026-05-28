"""Tests for ghchain.github_utils.get_next_gh_id."""

import json
from unittest.mock import MagicMock, patch

from ghchain.github_utils import get_latest_id, get_next_gh_id


def _mock_gh_response(numbers: list[int]):
    """Build a mock subprocess.CompletedProcess with a JSON list of {number: N}."""
    proc = MagicMock()
    proc.stdout = json.dumps([{"number": n} for n in numbers])
    proc.returncode = 0
    return proc


def test_get_latest_id_empty_returns_minus_one():
    with patch("ghchain.github_utils.run_command", return_value=_mock_gh_response([])):
        assert get_latest_id("pr") == -1
        assert get_latest_id("issue") == -1


def test_get_next_gh_id_empty_repo_returns_one():
    """Regression: empty repo (no issues, no PRs) must return 1, not 0.

    Prior bug: max(-1, -1) + 1 = 0 — a "next PR id" of zero is never valid
    on GitHub, breaking branch-name templating that uses {pr_id}.
    """
    with patch("ghchain.github_utils.run_command", return_value=_mock_gh_response([])):
        assert get_next_gh_id() == 1


def test_get_next_gh_id_normal_case():
    """Highest of PRs and issues, plus one."""
    call_counter = {"n": 0}
    pr_response = _mock_gh_response([5, 3, 1])
    issue_response = _mock_gh_response([7, 4, 2])

    def fake_run(*args, **kwargs):
        call_counter["n"] += 1
        return pr_response if call_counter["n"] == 1 else issue_response

    with patch("ghchain.github_utils.run_command", side_effect=fake_run):
        assert get_next_gh_id() == 8


def test_get_next_gh_id_only_issues():
    pr_response = _mock_gh_response([])
    issue_response = _mock_gh_response([3])

    call_counter = {"n": 0}

    def fake_run(*args, **kwargs):
        call_counter["n"] += 1
        return pr_response if call_counter["n"] == 1 else issue_response

    with patch("ghchain.github_utils.run_command", side_effect=fake_run):
        assert get_next_gh_id() == 4


def test_get_next_gh_id_only_prs():
    pr_response = _mock_gh_response([9])
    issue_response = _mock_gh_response([])

    call_counter = {"n": 0}

    def fake_run(*args, **kwargs):
        call_counter["n"] += 1
        return pr_response if call_counter["n"] == 1 else issue_response

    with patch("ghchain.github_utils.run_command", side_effect=fake_run):
        assert get_next_gh_id() == 10
