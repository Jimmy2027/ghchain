#!/usr/bin/env python

"""Tests for `ghchain` package."""

from pathlib import Path

from ghchain.git_utils import rebase_onto_branch

my_test_repo = Path("~/ssrc/mytest").expanduser()
import os

os.chdir(my_test_repo)
import json
import subprocess

import pytest
from click.testing import CliRunner

from ghchain import cli

dev_branch = "mydev"


def setup_repo():
    # git checkout main
    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "reset", "--hard", "origin/main"])

    # delete mydev local and remote branches
    for branch in {"mydev", "commit_0", "commit_1", "commit_2", "commit_3"}:
        subprocess.run(["git", "branch", "-D", branch])
        subprocess.run(["git", "push", "origin", "--delete", branch])

    # delete all pr's in mytest repo using github api
    prs_json = subprocess.run(
        ["gh", "pr", "list", "--json", "url"], capture_output=True, text=True
    ).stdout

    prs = json.loads(prs_json)

    for pr in prs:
        pr_url = pr["url"]
        subprocess.run(
            ["gh", "pr", "close", pr_url, "-d"], capture_output=True, text=True
        )

    # create new branch mydev
    subprocess.run(["git", "checkout", "main"])
    subprocess.run(["git", "checkout", "-b", "mydev"])


def create_test_stack(run_workflows=False):
    setup_repo()

    # change the README.md file 4 times and commit each change
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        subprocess.run(["git", "add", "README.md"])
        subprocess.run(["git", "commit", "-m", f"commit {i}"])

    runner = CliRunner()
    if run_workflows:
        return runner.invoke(cli.main, ["--with-tests"])
    else:
        return runner.invoke(cli.main)


def change_stack_with_conflict():
    subprocess.run(["git", "checkout", "commit_0"])
    # insert a line in the README.md file
    with open("README.md", "a") as f:
        f.write("line 5\n")
    subprocess.run(["git", "add", "README.md"])
    subprocess.run(["git", "commit", "--amend", "--no-edit"])
    subprocess.run(["git", "push", "origin", "commit_0", "--force"])

    subprocess.run(["git", "checkout", "mydev"])


@pytest.mark.parametrize("run_workflows", [True, False])
def test_ghchain(run_workflows):
    result = create_test_stack(run_workflows)

    assert result.exit_code == 0


def test_rebase():
    # create the test stack, then checkout branch with commit 0 and amend no edit the commit
    # then run ghchain --rebase-onto mydev
    result = create_test_stack(False)
    change_stack_with_conflict()
    # you will have to resolve the conflict manually...
    rebase_onto_branch("commit_0")


def test_run_workflows():
    # result = create_test_stack(True)
    CliRunner().invoke(cli.main, ["--run-tests"])


if __name__ == "__main__":
    test_ghchain(True)
    # test_run_workflows()
