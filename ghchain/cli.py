"""Console script for ghchain."""

import click


@click.group(invoke_without_command=True)
@click.option(
    "-p",
    "--create-pr",
    is_flag=True,
    help="If set to True, a pull request will be opened for every commit.",
)
@click.option(
    "--draft",
    is_flag=True,
    help="Create the pull request as a draft. This flag sets --create-pr to True.",
)
@click.option(
    "--with-tests",
    is_flag=True,
    help="Run the github workflows that are specified in the .ghchain.toml config of the repository.",
)
@click.pass_context
def ghchain_cli(ctx, create_pr, draft, with_tests):
    """
    Create a branch for each commit in the stack that doesn't already have one.
    Optionally, create a PR for each branch and run the github workflows that
    are specified in the .ghchain.toml config of the repository.

    Usage:

    ghchain: will create a branch for each commit in the stack that doesn't already have one
    and push it to the remote.

    ghchain --create-pr: will create a branch for each commit in the stack that doesn't already have one,
    push it to the remote and create a PR for each branch.

    ghchain --draft: will create a branch for each commit in the stack that doesn't already have one,
    push it to the remote and create a draft PR for each branch.

    ghchain --with-tests: will create a branch for each commit in the stack that doesn't already have one,
    push it to the remote and run the github workflows that are specified in the
    .ghchain.toml config of the repository.
    """

    from ghchain.stack import Stack

    if ctx.invoked_subcommand is None:
        if draft:
            # when draft is passed, we know that the user wants to publish the PRs
            create_pr = True
        stack = Stack.create()
        for commit in stack.commits:
            stack.process_commit(commit, create_pr, draft, with_tests)

    elif ctx.invoked_subcommand == "help":
        click.echo(ctx.get_help())


@ghchain_cli.command()
@click.argument("commit_sha", type=str)
@click.option(
    "-p",
    "--create-pr",
    is_flag=True,
    help="If set to True, a pull request will be opened for the commit.",
)
@click.option(
    "--draft",
    is_flag=True,
    help="Create the pull request as a draft. This flag sets --create-pr to True.",
)
@click.option(
    "--with-tests",
    is_flag=True,
    help="Run the github workflows that are specified in the .ghchain.toml config of the repository.",
)
def process_commit(commit_sha, create_pr, draft, with_tests):
    """
    Process a single commit by its SHA.
    """
    from ghchain.stack import Stack

    stack = Stack.create()
    commit = next((c for c in stack.commits if c.sha == commit_sha), None)
    if draft:
        # when draft is passed, we know that the user wants to publish the PRs
        create_pr = True
    if commit:
        stack.process_commit(commit, create_pr, draft, with_tests)
    else:
        click.echo(f"Commit with SHA {commit_sha} not found.")


@ghchain_cli.command()
def refresh():
    """
    Update the commit notes with the PR/ workflow statuses for the commits in the stack.
    """
    from ghchain.stack import Stack

    Stack.create(with_workflow_status=True)


@ghchain_cli.command()
@click.option(
    "--branch",
    "-b",
    type=str,
    default=None,
    help=("The target branch to which the configured base branch will be updated."),
)
def land(branch):
    """
    Merge the specified branch into the configured base branch.
    """
    from ghchain.git_utils import get_current_branch
    from ghchain.handlers import handle_land

    branch_name = get_current_branch() if branch == "." or not branch else branch
    handle_land(branch_name)


@ghchain_cli.command()
@click.argument(
    "target",
    type=str,
)
@click.option(
    "--interactive",
    "-i",
    is_flag=True,
    help=(
        "Do an interactive rebase. This will allow you to edit "
        "the commit messages and the order of the commits between branches."
    ),
)
def rebase(target, interactive):
    """
    Rebase the current branch onto branch, using 'update-refs' and push every updated branch to the remote.
    """
    from ghchain.git_utils import rebase_onto_target

    rebase_onto_target(target, interactive=interactive)


@ghchain_cli.command()
@click.option(
    "--branch",
    "-b",
    type=str,
    default=None,
    help=("Branch name or PR ID to run the github workflows for."),
)
def run_workflows(branch):
    """
    Run the github workflows that are specified in the .ghchain.toml config of the repository for the specified branch.
    If '.' or nothing is passed, the current branch will be used.
    """
    import ghchain
    from ghchain.git_utils import get_current_branch
    from ghchain.github_utils import (
        get_branch_name_for_pr_id,
    )
    from ghchain.pull_request import PR, get_open_prs, run_tests_on_branch

    branch_name = (
        get_branch_name_for_pr_id(int(branch))
        if branch.isdigit()
        else get_current_branch()
        if branch == "." or not branch
        else branch
    )

    if not branch_name:
        ghchain.logger.error(f"Branch {branch} not found.")
        return

    branches_to_pr: dict[str, PR] = {pr.head_branch: pr for pr in get_open_prs()}

    pull_request = branches_to_pr.get(branch_name)
    if not pull_request:
        ghchain.logger.warning(
            f"Branch {branch_name} not found or does not have a pull request associated with it. "
            "Running the test without updating the PR description."
        )

    run_tests_on_branch(branch=branch_name, pull_request=pull_request)


@ghchain_cli.command()
def fix_refs():
    """
    If you messed up your stack with a rebase and lost the connections between the commits and the branches,
    this command will attempt to fix it.
    If you notice the mistake soon enough, you can switch back to your previous ref using reflog... If not,
    this function might help.
    """
    import subprocess

    from ghchain.git_utils import get_commit_message_to_branch_mapping, run_command
    from ghchain.stack import Stack

    stack = Stack.create()

    commit_msg_to_branch = get_commit_message_to_branch_mapping()
    for commit in stack.commits:
        if not commit.branch:
            branch = commit_msg_to_branch.get(commit.message)
            if branch:
                # Ask user if they want to reset the branch to the commit
                if click.confirm(
                    f"Do you want to reset the branch '{branch}' to the commit '{commit.sha}'?"
                    f"\n Commit message:\n{commit.message}"
                ):
                    try:
                        # Reset the branch to the commit
                        run_command(
                            ["git", "branch", "-f", branch, commit.sha], check=True
                        )
                        click.echo(
                            f"Branch '{branch}' has been reset to commit '{commit.sha}'."
                        )
                    except subprocess.CalledProcessError as e:
                        click.echo(
                            f"Failed to reset branch '{branch}' to commit '{commit.sha}': {e}"
                        )
                else:
                    click.echo(
                        f"Skipped resetting branch '{branch}' to commit '{commit.sha}'."
                    )

    click.echo("Finished attempting to fix refs.")


@ghchain_cli.command()
def publish():
    """
    Publish all updated branches in the stack to the remote.
    """
    from ghchain.stack import Stack

    stack = Stack.create()
    stack.publish()


###############################
# Fixup commands
###############################

STATE_FILE = ".ghchain_fixup_state"


@ghchain_cli.group()
def fixup():
    """
    Commands to fixup a commit and rebase the stack.

    Wrapper around "git rebase --onto <bottom-branch> <old-base> <top-branch>" to rebase
    the stack onto a modified commit.

    Example usage:

      \b
      1. To fix a commit of branch 'feature-branch':
         $ ghchain fixup start feature-branch

      \b
      2. Make your changes and stage them:
         $ git add <modified-files>
         $ git commit --amend --no-edit

      \b
      3. Complete the fixup and rebase the stack:
         $ ghchain fixup done
    """
    pass


@fixup.command()
@click.argument("ref")
def start(ref):
    """
    Start the fixup process for a specific commit or branch.
    To fixup a commit, pass the commit SHA. If the commit has a branch associated with it,
    the branch will not be update!
    To fixup a branch, pass the branch name.
    """
    import json
    from pathlib import Path

    import ghchain
    from ghchain import logger

    state_file = Path(STATE_FILE)

    # Check if a fixup state file already exists
    if state_file.exists():
        if not click.confirm(
            "A fixup state file already exists. Do you want to delete it and start a new fixup? "
            "This will remove the previous state and reset the process."
        ):
            return
        state_file.unlink()

    repo = ghchain.repo
    is_branch = ref in [branch.name for branch in repo.branches]

    current_branch = repo.active_branch
    logger.warning(
        f"Using current branch: {current_branch.name} as top branch."
        " This branch and all intermediate branches will be rebased."
    )

    if is_branch:
        repo.git.checkout(ref)
        base = repo.commit(ref)
    else:
        repo.git.checkout(ref)
        base = repo.commit(ref)

    state_file.write_text(
        json.dumps(
            {
                "old_base": base.hexsha,
                "top_branch": current_branch.name,
            }
        )
    )
    click.echo(f"Checked out {ref}. Make your changes and stage them.")


@fixup.command()
@click.option(
    "-p",
    "--publish",
    is_flag=True,
    help="Publish all updated branches in the stack to the remote after rebasing.",
)
def done(publish):
    """
    Complete the fixup process and rebase the stack. Optionally publish the updated branches.
    """
    import json
    import subprocess
    import sys
    from pathlib import Path

    import ghchain
    from ghchain.stack import Stack
    from ghchain.utils import run_command

    state_file = Path(STATE_FILE)
    if not state_file.exists():
        click.echo(
            "No fixup state found. Run `ghchain fixup <commit-or-branch>` first."
        )
        return

    state = json.loads(state_file.read_text())
    old_base = state["old_base"]
    top_branch = state["top_branch"]

    # check that anything is changed
    if not ghchain.repo.index.diff(old_base):
        click.echo("No changes detected. Nothing to fixup.")
        return

    if ghchain.repo.index.diff("HEAD"):
        click.echo("Found staged changes. Amending the last commit.")
        run_command(["git", "commit", "--amend", "--no-edit"], check=True)

    repo = ghchain.repo
    new_base = repo.head.commit.hexsha

    click.echo("Rebasing the stack...")
    try:
        run_command(
            [
                "git",
                "rebase",
                "--onto",
                new_base,
                old_base,
                top_branch,
                "--update-refs",
            ],
            check=True,
        )
    except subprocess.CalledProcessError:
        click.echo("Failed to rebase the stack.")
        click.echo("Finish the rebase manually. Deleting the fixup state file.")
        state_file.unlink()
        sys.exit(1)

    # Checkout the top branch again
    repo.git.checkout(top_branch)

    state_file.unlink()
    click.echo("Fixup complete. Stack updated successfully.")

    if publish:
        click.echo("Publishing updated branches...")

        stack = Stack.create()
        stack.publish()
        click.echo("All updated branches have been published.")


if __name__ == "__main__":
    ghchain_cli()
