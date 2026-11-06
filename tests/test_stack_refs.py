import os
from pathlib import Path

import pytest
from git import Repo

from ghchain.config import Config

SLASHED_BRANCH = "user/feature"


@pytest.fixture
def stack_repo(mocker, tmp_path):
    """
    main <- c0 (dev)
    c0 carries a slashed branch, a fake remote branch and a ref to a tree.
    """
    os.chdir(tmp_path)
    repo = Repo.init(tmp_path)
    repo.git.checkout(b="main")

    Path("README.md").write_text("init\n")
    repo.index.add(["README.md"])
    repo.index.commit("init")

    repo.git.checkout(b="dev")
    Path("README.md").write_text("change\n")
    repo.index.add(["README.md"])
    commit = repo.index.commit("change")

    repo.git.branch(SLASHED_BRANCH, commit.hexsha)
    repo.git.update_ref(f"refs/remotes/origin/{SLASHED_BRANCH}", commit.hexsha)

    # Tools such as Codex store checkpoint refs that point at trees.
    repo.git.update_ref("refs/codex/checkpoint", commit.tree.hexsha)

    mocker.patch("ghchain.repo", repo)
    mocker.patch("ghchain.config", Config(base_branch="main", remote="origin"))
    mocker.patch("ghchain.stack.get_open_prs", return_value=[])
    return repo


def test_slashed_branch_names(stack_repo):
    from ghchain.stack import Stack

    stack = Stack.create()

    assert len(stack.commits) == 1
    commit = stack.commits[0]
    assert commit.branch == SLASHED_BRANCH
    assert commit.remote_branches == [f"origin/{SLASHED_BRANCH}"]


def test_download_slashed_branch(stack_repo, mocker):
    from ghchain.stack import Stack

    stack = Stack.create()
    git = mocker.patch.object(stack_repo, "git")

    stack.download()

    git.checkout.assert_called_once_with(SLASHED_BRANCH)
    git.pull.assert_called_once_with("--rebase", "origin", SLASHED_BRANCH)
