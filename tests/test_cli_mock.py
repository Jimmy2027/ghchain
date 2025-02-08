import os
from pathlib import Path

import pytest
from click.testing import CliRunner
from git import Repo


@pytest.fixture
def git_repo(mocker, tmp_path):
    os.chdir(tmp_path)
    repo = Repo.init(tmp_path)

    repo.git.checkout(b="main")
    # make an initial commit
    with open("README.md", "w") as f:
        f.write("Initial commit\n")
    repo.index.add(["README.md"])
    repo.index.commit("Initial commit")
    repo.git.checkout(b="dev")

    # set ghchain.repo to the repo object
    mocker.patch("ghchain.repo", repo)
    return repo


@pytest.fixture
def create_stack(git_repo):
    """Change the README.md file 4 times and commit each change."""
    for i in range(4):
        with open("README.md", "a") as f:
            f.write(f"line {i}\n")
        git_repo.index.add(["README.md"])
        git_repo.index.commit(f"commit {i}\nThis is a test commit.")
    return git_repo


@pytest.fixture
def patch_config(mocker, git_repo):
    """
    Overwrite the .ghchain with a custom configuration for testing.
    """
    from ghchain.config import Config

    mytest_config = """\
 base_branch = "main"
 """
    ghchain_config = Path(git_repo.working_dir) / ".ghchain.toml"
    ghchain_config.write_text(mytest_config)
    config = Config.from_toml(ghchain_config)
    mocker.patch("ghchain.config", config)


def test_fix_refs_on_dev_branch(mocker, create_stack, patch_config):
    import ghchain
    from ghchain import cli

    git_repo = create_stack

    # mock get_open_prs to return an empty list
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=[])
    # mock get_next_gh_id to return 42
    mocker.patch("ghchain.github_utils.get_next_gh_id", return_value=42)
    # mock ghchain.stack.git_push to do nothing
    mocker.patch("ghchain.stack.git_push")

    cli_runner = CliRunner()

    # create a branch for every commit
    result = cli_runner.invoke(cli.ghchain_cli, [])

    assert result.exit_code == 0, f"Error: {result.output}"

    # change the first commit with a fixup and a rebase
    git_repo.git.checkout("main")
    with open("myfile.md", "w") as f:
        f.write("Hello\n")
    git_repo.index.add(["myfile.md"])
    # ammend the last commit
    git_repo.git.commit("--amend", "--no-edit")
    git_repo.git.checkout("dev")
    git_repo.git.rebase("main")

    # run ghchain fix-refs
    result = cli_runner.invoke(cli.ghchain_cli, ["fix-refs"], input="y\n" * 4)

    stack = ghchain.stack.Stack.create()

    for commit in stack.commits:
        assert commit.branch


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
