import os
import subprocess
from pathlib import Path

import pytest
from git import Repo
from loguru import logger

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


if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s", "-k test_create_branches_for_commits"])
