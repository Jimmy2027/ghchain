import pytest
from unittest.mock import patch, MagicMock
from click.testing import CliRunner
from ghchain import cli


def test_main_rebase_onto():
    runner = CliRunner()
    with patch("ghchain.cli.rebase_onto_branch") as mock_rebase:
        result = runner.invoke(cli.main, ["--rebase-onto", "branch"])
        mock_rebase.assert_called_once_with("branch")
        assert result.exit_code == 0


def test_main_status():
    runner = CliRunner()
    with patch("ghchain.cli.print_status") as mock_status:
        result = runner.invoke(cli.main, ["--status"])
        mock_status.assert_called_once()
        assert result.exit_code == 0


def test_main_live_status():
    runner = CliRunner()
    with patch("ghchain.cli.print_status") as mock_status:
        result = runner.invoke(cli.main, ["--live-status"])
        mock_status.assert_called_once_with(base_branch="main", live=True)
        assert result.exit_code == 0


def test_main_run_tests():
    runner = CliRunner()
    with patch("ghchain.cli.get_branch_name_for_pr_id") as mock_get_branch, patch(
        "ghchain.cli.get_current_branch"
    ) as mock_get_current, patch(
        "ghchain.cli.get_pr_url_for_branch"
    ) as mock_get_pr_url, patch("ghchain.cli.update_pr_descriptions") as mock_update_pr:
        mock_get_branch.return_value = "branch"
        mock_get_current.return_value = "current_branch"
        mock_get_pr_url.return_value = "pr_url"
        result = runner.invoke(cli.main, ["--run-tests", "1"])
        mock_get_branch.assert_called_once_with(1)
        mock_get_pr_url.assert_called_once_with("branch")
        mock_update_pr.assert_called_once_with(
            run_tests=("pr_url", "branch"), pr_stack=["pr_url"]
        )
        assert result.exit_code == 0


def test_main_no_commits():
    runner = CliRunner()
    with patch("ghchain.cli.Stack.create") as mock_stack:
        mock_stack.return_value = MagicMock(commits=None)
        result = runner.invoke(cli.main)
        assert "No commits found that are not in main." in result.output
        assert result.exit_code == 0
