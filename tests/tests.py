import json
import os
import subprocess
import time
from pathlib import Path

import pytest
from click.testing import CliRunner
from git import Repo

import ghchain
from ghchain import cli
from ghchain.config import Config, logger
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
def patch_git_repo(monkeypatch, setup_mytest_repo):
    repo = Repo(setup_mytest_repo)
    monkeypatch.setattr("ghchain.repo", repo)


@pytest.fixture
def patch_config(monkeypatch, setup_mytest_repo):
    """
    Overwrite the .ghchain with a custom configuration for testing.
    """
    mytest_config = """\
 workflows = ["workflow_1", "workflow_2"]
 branch_name_template = "hk-{pr_id}"
 log_level = "TRACE"
 issue_pattern = "\\\\(#(\\\\d+)\\\\)"
 """
    ghchain_config = Path(setup_mytest_repo) / ".ghchain.toml"
    ghchain_config.write_text(mytest_config)
    config = Config.from_toml(ghchain_config)
    monkeypatch.setattr("ghchain.config", config)


@pytest.fixture
def cli_runner(setup_mytest_repo, patch_git_repo, patch_config):
    runner = CliRunner()
    yield runner, setup_mytest_repo


@pytest.fixture(scope="function")
def repo_cleanup():
    """Fixture to clean up the repository before tests."""
    cleanup_repo()
    yield


def commit_fixup(branch):
    run_command(["git", "checkout", branch])
    run_command(["touch", "new_file"])
    run_command(["git", "add", "new_file"])
    run_command(["git", "commit", "-m", "fixup! new file"])
    run_command(["git", "push"])
    run_command(["git", "checkout", "-"])


def cleanup_repo():
    """Delete all current branches and pull requests and create a new branch mydev."""
    run_command(["git", "checkout", "main"])
    run_command(["git", "reset", "--hard", "464397e0bf88c66ea09fd05448ad6847c230c2fe"])
    run_command(["git", "push", "-f"])

    local_branches = set(get_all_branches()) - {"main"}
    remote_branches = set(get_all_branches(remote=True)) - {"main"}

    for branch in local_branches:
        run_command(["git", "branch", "-D", branch])
    for branch in remote_branches:
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
        run_command(["git", "commit", "-m", f"commit {i}\nThis is a test commit."])


@pytest.mark.order(1)
@pytest.mark.parametrize("create_pr", [True, False])
@pytest.mark.parametrize("draft", [True, False])
@pytest.mark.parametrize("with_tests", [True, False])
def test_process_commits(cli_runner, repo_cleanup, create_pr, draft, with_tests):
    cli_runner, _ = cli_runner

    create_stack()

    args = []
    if create_pr:
        args.append("--create-pr")
    if draft:
        args.append("--draft")
    if with_tests:
        args.append("--with-tests")

    result = cli_runner.invoke(cli.ghchain_cli, args)
    if result.exit_code != 0:
        print(result.output)

    assert (
        result.exit_code == 0
    ), f"Command failed with exit code {result.exit_code}\n{result.output}"

    stack = Stack.create()
    assert len(stack.commits) == 4
    if create_pr or draft:
        for commit in stack.commits:
            assert commit.branch is not None

    # assert that the repo has 4 open pull requests
    if create_pr or draft:
        prs = run_command(["gh", "pr", "list", "--json", "baseRefName"]).stdout
        prs = json.loads(prs)
        assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

        branches = (["main"] + [commit.branch for commit in stack.commits[:-1]])[::-1]
        for idx, pr in enumerate(prs):
            assert pr["baseRefName"] == branches[idx]


@pytest.mark.order(1)
def test_rebase(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    # Stack is up to date with origin/main
    create_stack()
    result = cli_runner.invoke(cli.ghchain_cli)

    assert result.exit_code == 0

    stack = Stack.create(base_branch="main")
    bottom_branch = stack.branches[0]

    commit_fixup(bottom_branch)
    result = cli_runner.invoke(cli.rebase, [bottom_branch])

    assert result.exit_code == 0

    stack = Stack.create()
    assert len(stack.commits) == 5


@pytest.mark.order(1)
def test_land(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    create_stack()

    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])
    assert result.exit_code == 0

    stack = Stack.create(base_branch="main")
    branch_to_land = stack.branches[0]
    runner = CliRunner()
    result = runner.invoke(cli.land, ["-b", branch_to_land])
    assert result.exit_code == 0

    # assert that the repo has 3 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 3, f"Expected 3 pull requests, got {len(prs)}"


@pytest.mark.order(1)
def test_land_local_out_of_date(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    create_stack()

    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])
    assert result.exit_code == 0

    # make the branch to merge out of date with remote
    stack = Stack.create(base_branch="main")
    bottom_branch = stack.branches[0]
    bottom_commit = stack.commits[0].sha
    commit_fixup(bottom_branch)
    # reset the branch to the original commit
    run_command(["git", "checkout", bottom_branch])
    run_command(["git", "reset", "--hard", bottom_commit])
    run_command(["git", "checkout", "-"])

    runner = CliRunner()
    result = runner.invoke(cli.land, ["-b", bottom_branch], input="y\n")
    assert result.exit_code == 0

    # assert that the repo has 3 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 3, f"Expected 3 pull requests, got {len(prs)}"


@pytest.mark.order(1)
def test_land_no_local_branch(cli_runner, repo_cleanup):
    cli_runner, _ = cli_runner

    create_stack()

    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])
    assert result.exit_code == 0

    # make the branch to merge out of date with remote
    stack = Stack.create(base_branch="main")
    bottom_branch = stack.branches[0]

    # delete the local branch
    run_command(["git", "branch", "-D", bottom_branch])

    runner = CliRunner()
    result = runner.invoke(cli.land, ["-b", bottom_branch], input="y\n")
    assert result.exit_code == 0

    # assert that the repo has 3 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 3, f"Expected 3 pull requests, got {len(prs)}"


@pytest.mark.order(2)
def test_multiple_commits_per_pr(cli_runner, repo_cleanup):
    """
    Test process commits when there are commits added to a pr.
    """
    cli_runner, _ = cli_runner

    # Stack is up to date with origin/main
    create_stack()
    cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])

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

    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])
    assert result.exit_code == 0

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"


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

    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])

    # assert that the repo has 4 open pull requests
    prs = run_command(["gh", "pr", "list", "--json", "url"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"

    assert result.exit_code == 0


@pytest.mark.order(2)
@pytest.mark.parametrize("with_prs", [True, False])
def test_run_tests(cli_runner, repo_cleanup, with_prs):
    """
    Test the run-tests command.
    Run the workflows for the first commit in the stack.
    """
    cli_runner, _ = cli_runner

    # create stack
    create_stack()
    command_args = ["--create-pr"] if with_prs else []
    result = cli_runner.invoke(cli.ghchain_cli, command_args)
    assert result.exit_code == 0

    stack = Stack.create()
    result = cli_runner.invoke(cli.run_workflows, ["-b", stack.commits[0].branch])

    time.sleep(30)
    stack = Stack.create(with_workflow_status=True)

    # verify that the commit notes have been updated
    assert (
        "[[workflow_statuses]]" in stack.commits[0].notes
    ), f"Expected [[workflow_statuses]] in notes, got {stack.commits[0].notes}"

    # Verify that the PR message has been updated
    if with_prs:
        assert (
            "# Workflow Results" in stack.commits[0].pull_request.body
        ), "PR message not updated."

    assert result.exit_code == 0


@pytest.mark.order(1)
def test_linked_issue(cli_runner, repo_cleanup):
    """
    Test that commits with a linked issue in the message are correctly detected
    and the branch is linked to the corresponding GitHub issue.
    """
    cli_runner, _ = cli_runner

    # Step 1: Create a new GitHub issue
    issue_title = "Test issue for linking"
    issue_body = "This issue is created for testing branch linking in ghchain."
    issue_creation_result = run_command(
        [
            "gh",
            "issue",
            "create",
            "--title",
            issue_title,
            "--body",
            issue_body,
        ],
    )
    assert (
        issue_creation_result.returncode == 0
    ), f"Issue creation failed: {issue_creation_result.stderr}"

    # Extract the issue number from the output
    issue_url = issue_creation_result.stdout.strip()
    issue_id = int(issue_url.split("/")[-1])

    # Step 2: Create a commit with a linked issue reference
    run_command(["git", "checkout", "mydev"])
    with open("README.md", "a") as f:
        f.write("This commit is linked to an issue.\n")
    run_command(["git", "add", "README.md"])
    commit_message = f"Add feature linked to issue (#{issue_id})"
    run_command(["git", "commit", "-m", commit_message])

    # Step 3: Run ghchain to process the commit
    result = cli_runner.invoke(cli.ghchain_cli)
    assert (
        result.exit_code == 0
    ), f"Command failed with exit code {result.exit_code}\n{result.output}"

    # Step 4: Check that the commit was processed correctly
    stack = Stack.create()
    assert len(stack.commits) == 1, "Expected 1 commit in the stack"

    commit = stack.commits[0]
    assert (
        commit.issue_url == issue_url
    ), f"Expected issue_id {issue_url}, got {commit.issue_url}"
    assert commit.branch is not None, "Expected branch to be created for the commit"

    # Step 5: Verify that the branch is linked to the GitHub issue
    issue_branches = run_command(
        ["gh", "issue", "develop", "--list", str(issue_id)]
    ).stdout
    assert issue_branches.split("\t")[0] == commit.branch, (
        f"Expected branch {commit.branch} to be linked to issue {issue_id}, "
        f"got {issue_branches}"
    )


@pytest.mark.order(1)
def test_stack_with_mixed_branch_states(cli_runner, repo_cleanup):
    """
    Test ghchain CLI behavior on a stack where:
    - First branch is pushed to origin.
    - Second and third branches are local only.
    - Fourth branch is up to date with origin.
    """
    cli_runner, _ = cli_runner

    # Create a stack with 4 commits
    create_stack()

    # Push the first branch to origin
    branches = []

    commits = list(ghchain.repo.iter_commits("HEAD", max_count=5))
    commits.reverse()  # Start from the oldest commit

    for i, commit in enumerate(commits, 0):
        branch_name = f"branch-{i}"
        branch = ghchain.repo.create_head(branch_name, commit)
        branch.checkout()
        branches.append(branch_name)

    # checkout mydev branch
    ghchain.repo.git.checkout("mydev")

    stack = Stack.create(base_branch="main")

    first_branch = stack.branches[0]
    ghchain.repo.git.push("origin", first_branch)

    # Push the fourth branch to origin
    fourth_branch = stack.branches[3]
    ghchain.repo.git.push("origin", fourth_branch)

    # Run ghchain CLI on this stack
    result = cli_runner.invoke(cli.ghchain_cli, ["--create-pr"])
    assert (
        result.exit_code == 0
    ), f"ghchain CLI failed with exit code {result.exit_code}\n{result.output}"

    # Check PRs for the branches
    prs = run_command(["gh", "pr", "list", "--json", "baseRefName"]).stdout
    prs = json.loads(prs)
    assert len(prs) == 4, f"Expected 4 pull requests, got {len(prs)}"


@pytest.mark.order(1)
def test_fixup(cli_runner, repo_cleanup):
    """
    Test that fixup commits are correctly processed.
    """
    cli_runner, tempdir = cli_runner

    repo = Repo(tempdir)
    current_branch = repo.active_branch

    # Create a stack with 4 commits
    create_stack()

    # Run ghchain CLI to process the commits
    result = cli_runner.invoke(cli.ghchain_cli)

    stack = Stack.create()
    # Start the fixup process
    result = cli_runner.invoke(cli.fixup, ["start", stack.commits[0].branch])

    assert result.exit_code == 0
    assert tempdir.join(".ghchain_fixup_state").exists()

    run_command(["touch", "new_file"])
    run_command(["git", "add", "new_file"])

    # run the fixup done command
    result = cli_runner.invoke(cli.fixup, ["done"])

    assert result.exit_code == 0
    assert not tempdir.join(".ghchain_fixup_state").exists()

    assert tempdir.join("new_file").exists()
    assert repo.active_branch == current_branch


if __name__ == "__main__":
    pytest.main(["-v", __file__, "-s", "-x", "-k test_run_tests[True]"])
