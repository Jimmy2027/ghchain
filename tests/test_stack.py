import os
import subprocess
from pathlib import Path

import pytest
from git import Repo
from loguru import logger

from ghchain import config
from ghchain.git_utils import create_branch_name
from ghchain.stack import (
    Stack,
    get_current_branch,
)


@pytest.fixture
def temp_git_repo(monkeypatch, tmp_path):
    origin_cwd = os.getcwd()
    try:
        os.chdir(tmp_path)
        logger.info(f"Setting up temporary directory: {tmp_path}")

        # Initialize a git repository
        subprocess.run(["git", "init"], cwd=tmp_path, check=True)

        # Configure user name and email for the temporary repo
        subprocess.run(
            ["git", "config", "user.name", "Test User"], cwd=tmp_path, check=True
        )
        subprocess.run(
            ["git", "config", "user.email", "test@example.com"],
            cwd=tmp_path,
            check=True,
        )

        # Create initial commit
        initial_file = Path(tmp_path) / "initial_file.txt"
        initial_file.write_text("Initial content")
        subprocess.run(["git", "add", "initial_file.txt"], cwd=tmp_path, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit"], cwd=tmp_path, check=True
        )

        # Monkeypatch the repo object
        repo = Repo(tmp_path)
        monkeypatch.setattr("ghchain.repo", repo)

        yield tmp_path

    finally:
        os.chdir(origin_cwd)


def run_git_command(command, cwd):
    result = subprocess.run(
        command, cwd=cwd, check=True, capture_output=True, text=True
    )
    return result.stdout.strip()


def test_get_current_branch(temp_git_repo):
    branch = get_current_branch()
    assert branch == "master"


def test_stack_create(temp_git_repo):
    # Create a new branch and commit
    run_git_command(["git", "checkout", "-b", "feature"], temp_git_repo)
    new_file = Path(temp_git_repo) / "new_file.txt"
    new_file.write_text("New content")
    run_git_command(["git", "add", "new_file.txt"], temp_git_repo)
    run_git_command(["git", "commit", "-m", "Add new file"], temp_git_repo)

    stack = Stack.create(base_branch="master")
    assert stack.dev_branch == "feature"
    assert stack.base_branch == "master"
    assert len(stack.commits) == 1
    assert stack.commits[0].sha == run_git_command(
        ["git", "rev-parse", "HEAD"], temp_git_repo
    )
    assert stack.commits[0].message == "Add new file"


@pytest.mark.parametrize("create_pr", [True, False])
@pytest.mark.parametrize("draft", [True, False])
@pytest.mark.parametrize("with_tests", [True, False])
def test_create_branches_for_commits(
    temp_git_repo, monkeypatch, create_pr, draft, with_tests
):
    def mock_get_latest_pr_id_generator():
        start_id = 42
        while True:
            yield start_id
            start_id += 1

    mock_get_latest_pr_id_gen = mock_get_latest_pr_id_generator()

    def mock_get_latest_pr_id():
        return next(mock_get_latest_pr_id_gen)

    monkeypatch.setattr("ghchain.stack.get_next_gh_id", mock_get_latest_pr_id)
    monkeypatch.setattr("ghchain.stack.git_push", lambda branch: None)
    monkeypatch.setattr(
        "ghchain.stack.create_pull_request", lambda *args, **kwargs: "_42"
    )
    monkeypatch.setattr(
        "ghchain.stack.update_pr_descriptions", lambda *args, **kwargs: None
    )
    monkeypatch.setattr("ghchain.stack.run_tests_on_pr", lambda *args, **kwargs: None)

    # Create a new branch and commit
    run_git_command(["git", "checkout", "-b", "feature"], temp_git_repo)
    for i in range(3):
        new_file = Path(temp_git_repo) / f"new_file_{i}.txt"
        new_file.write_text(f"New content {i}")
        run_git_command(["git", "add", new_file.name], temp_git_repo)
        run_git_command(["git", "commit", "-m", f"Add new file {i}"], temp_git_repo)

    stack = Stack.create(base_branch="master")
    for commit in stack.commits:
        stack.process_commit(commit, create_pr, draft, with_tests)

    # Check that a branch was created for the commit
    commit = stack.commits[0]
    assert len(commit.branches) == 3
    branch_name = create_branch_name(config.branch_name_template, 43)
    assert branch_name in commit.branches

    assert len(stack.commits[1].branches) == 2
    assert len(stack.commits[-1].branches) == 1


if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s", "-k test_create_branches_for_commits"])
