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
@click.option(
    "--branch",
    "-b",
    type=str,
    default=None,
    help=("The target branch to which the configured base branch will be updated."),
)
def refresh(branch):
    """
    Merge the specified branch into the configured base branch.
    """
    from ghchain.stack import Stack

    Stack.create()


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
    from ghchain.git_utils import get_current_branch
    from ghchain.github_utils import (
        get_branch_name_for_pr_id,
        get_pr_url_for_branch,
        run_tests_on_branch,
    )

    branch_name = (
        get_branch_name_for_pr_id(int(branch))
        if branch.isdigit()
        else get_current_branch()
        if branch == "." or not branch
        else branch
    )
    pr_url = get_pr_url_for_branch(branch_name)

    run_tests_on_branch(branch=branch_name, pr_url=pr_url)


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


if __name__ == "__main__":
    ghchain_cli()
