from ghchain.stack import (
    Stack,
    find_branches_with_commit,
    get_commits_not_in_base_branch,
    get_current_branch,
)


def test_find_branches_with_commit(mock_repo):
    mock_repo.git.branch.return_value = "* master\n  develop"
    branches = find_branches_with_commit("some_commit_sha")
    assert branches == ["master", "develop"]


def test_get_commits_not_in_base_branch(mock_repo):
    mock_repo.git.log.return_value = (
        "sha1 commit message\nsha2 fixup! another commit message"
    )
    commits = get_commits_not_in_base_branch("base_branch")
    assert commits == [["sha1", "commit message"]]


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
