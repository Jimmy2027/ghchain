from unittest import mock

import pytest
from ghchain.stack import (
    Commit,
    Stack,
    get_current_branch,
)


def test_get_current_branch(mock_repo):
    mock_repo.active_branch.name = "feature_branch"
    branch = get_current_branch()
    assert branch == "feature_branch"


def test_stack_create(mock_repo):
    mock_repo.git.branch.return_value = "* master\n  develop"
    mock_repo.git.log.return_value = "sha1 commit message\nsha2 another commit message"
    mock_repo.active_branch.name = "feature_branch"

    stack = Stack.create(base_branch="main")
    assert stack.dev_branch == "feature_branch"
    assert stack.base_branch == "main"
    assert len(stack.commits) == 2
    assert stack.commits[0].sha == "sha1"
    assert stack.commits[0].message == "commit message"


@mock.patch("ghchain.git_utils.create_branch_name")
@mock.patch("ghchain.github_utils.get_next_gh_id")
@mock.patch("ghchain.git_utils.git_push")
@mock.patch("ghchain.github_utils.create_pull_request")
@mock.patch("ghchain.github_utils.update_pr_descriptions")
@mock.patch("ghchain.github_utils.run_tests_on_pr")
def test_process_commit(
    mock_run_tests,
    mock_update_pr_descriptions,
    mock_create_pr,
    mock_git_push,
    mock_get_next_gh_id,
    mock_create_branch_name,
):
    # Setup
    mock_get_next_gh_id.return_value = 42
    mock_create_branch_name.return_value = "branch-42"

    commit1 = Commit(sha="sha1", message="commit message 1", branches=set())
    commit2 = Commit(sha="sha2", message="commit message 2", branches=set())
    stack = Stack(commits=[commit1, commit2], dev_branch="feature", base_branch="main")

    # Test process_commit without create_pr
    pr_created = stack.process_commit(commit1, create_pr=False)
    assert not pr_created
    assert "branch-42" in commit1.branches
    assert "branch-42" in commit2.branches

    # Test process_commit with create_pr
    mock_create_pr.return_value = "https://github.com/user/repo/pull/1"
    pr_created = stack.process_commit(
        commit2, create_pr=True, draft=True, with_tests=True
    )
    assert pr_created
    assert "branch-42" in commit2.branches
    assert commit2.pr_url == "https://github.com/user/repo/pull/1"
    mock_run_tests.assert_called_with(
        "branch-42", "https://github.com/user/repo/pull/1"
    )


if "__main__" == __name__:
    pytest.main(["-v", __file__, "-s", "-k test_process_commit", "-x"])
