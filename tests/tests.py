import json
import os
import subprocess

import pytest
from click.testing import CliRunner

from ghchain import cli
from ghchain.config import logger
from ghchain.git_utils import get_all_branches
from ghchain.stack import Stack
from ghchain.utils import run_command


@pytest.fixture(scope="session")
def setup_mytest_repo(tmpdir_factory):
    temp_dir = tmpdir_factory.mktemp("shared_temp_dir")
    os.chdir(temp_dir)
    logger.info(f"Current working directory: {os.getcwd()}")
    subprocess.run(
        ["git", "clone", "https://github.com/HendrikKlug-synthara/mytest.git", "."],
        capture_output=True,
        text=True,
        cwd=os.getcwd(),
        check=True,
    )

    if "GH_TOKEN" in os.environ:
        command = (
            f"git remote set-url origin "
            f"https://x-access-token:{os.environ['GH_TOKEN']}@"
            f"github.com/HendrikKlug-synthara/mytest.git"
        )
        subprocess.run(command, shell=True, check=True)
    return temp_dir


@pytest.fixture
def cli_runner(setup_mytest_repo):
    runner = CliRunner()
    yield runner, setup_mytest_repo


@pytest.fixture(scope="function")
def repo_cleanup():
    """Fixture to clean up the repository before tests."""
    cleanup_repo()
    yield


def cleanup_repo():
    """Delete all current branches and pull requests and create a new branch mydev."""
    run_command(["git", "checkout", "main"])
    run_command(["git", "reset", "--hard", "464397e0bf88c66ea09fd05448ad6847c230c2fe"])
    run_command(["git", "push", "-f"])

    branches = set(get_all_branches()) - {"main"}

    for branch in branches:
        run_command(["git", "branch", "-D", branch])
        run_command(["git", "push", "origin", "--delete", branch])

    prs_json = run_command(
        ["gh", "pr", "list", "--json", "url"],
    ).stdout

    prs = json.loads(prs_json)
    for pr in prs:
        pr_url = pr["url"]
        run_command(
            ["gh", "pr", "close", pr_url, "-d"],
        )

    run_command(["git", "checkout", "main"])
    run_command(["git", "checkout", "-b", "mydev"])


def create_stack():
    """Change the README.md file 4 times and commit each change."""
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        run_command(["git", "add", "README.md"])
        run_command(["git", "commit", "-m", f"commit {i}"])


@pytest.mark.order(1)
@pytest.mark.parametrize("run_workflows", [False, True])
def test_process_commits(cli_runner, repo_cleanup, run_workflows):
    cli_runner, _ = cli_runner

    create_stack()

    if run_workflows:
        result = cli_runner.invoke(cli.process_commits, ["--with-tests"])
    else:
        result = cli_runner.invoke(cli.process_commits)

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

    assert result.exit_code == 0


@pytest.mark.order(1)
def test_rebase(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    # Stack is up to date with origin/main
    create_stack()
    cli_runner.invoke(cli.process_commits)

    stack = Stack.create(base_branch="main")
    bottom_branch = stack.branches[-1]

    run_command(["git", "checkout", bottom_branch])
    run_command(["touch", "new_file"])
    run_command(["git", "add", "new_file"])
    run_command(["git", "commit", "-m", "new file"])
    run_command(["git", "push"])
    run_command(["git", "checkout", "-"])
    result = cli_runner.invoke(cli.rebase, [bottom_branch])

    assert result.exit_code == 0

    stack = Stack.create()
    assert len(stack.commits) == 5


@pytest.mark.order(1)
def test_land(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    create_stack()
    cli_runner.invoke(cli.process_commits)

    stack = Stack.create(base_branch="main")
    branch_to_land = stack.branches[-1]
    runner = CliRunner()
    result = runner.invoke(cli.land, ["-b", branch_to_land])

    # assert that the repo has 3 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 3, f"Expected 3 pull requests, got {len(prs)}"

    assert result.exit_code == 0


@pytest.mark.order(2)
def test_multiple_commits_per_pr(cli_runner, repo_cleanup):
    """
    Test process commits when there are commits added to a pr.
    """
    cli_runner, _ = cli_runner

    # Stack is up to date with origin/main
    create_stack()
    cli_runner.invoke(cli.process_commits)

    stack = Stack.create(base_branch="main")
    bottom_branch = stack.branches[-1]

    run_command(["git", "checkout", bottom_branch])
    run_command(["touch", "new_file"])
    run_command(["git", "add", "new_file"])
    run_command(["git", "commit", "-m", "fixup! new file"])
    run_command(["git", "push"])
    run_command(["git", "checkout", "-"])
    cli_runner.invoke(cli.rebase, [bottom_branch])

    stack = Stack.create()

    result = cli_runner.invoke(cli.process_commits)

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

    assert result.exit_code == 0


@pytest.mark.order(2)
def test_main_out_of_date(cli_runner, repo_cleanup):
    """
    Test that process commits works also if the local main branch is out of date.
    """
    cli_runner, _ = cli_runner

    # Stack is up to date with origin/main
    create_stack()

    run_command(["git", "checkout", "main"])
    run_command(["git", "reset", "--hard", "HEAD~2"])
    run_command(["git", "checkout", "-"])

    result = cli_runner.invoke(cli.process_commits)

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

    assert result.exit_code == 0


if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s", "-k test_rebase"])
