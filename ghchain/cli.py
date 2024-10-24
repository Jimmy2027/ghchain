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
    """

    from ghchain.stack import Stack

    if ctx.invoked_subcommand is None:
        if draft:
            # when draft is passed, we know that the user wants to publish the PRs
            create_pr = True
        stack = Stack.create()
        for commit in stack.commits:
            pr_created = stack.process_commit(commit, create_pr, draft, with_tests)

            if pr_created and not click.confirm(
                "Do you want to continue with the next commit?", default=True
            ):
                break

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
    "--live",
    "-l",
    is_flag=True,
    help="Print the status of the PRs, updating every minute.",
)
def status(live):
    """Print the status of the PRs"""
    from ghchain import config
    from ghchain.status import print_status

    default_base_branch = config.base_branch
    print_status(base_branch=default_base_branch, live=live)


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
        run_tests_on_pr,
    )

    branch_name = (
        get_branch_name_for_pr_id(int(branch))
        if branch.isdigit()
        else get_current_branch()
        if branch == "." or not branch
        else branch
    )
    pr_url = get_pr_url_for_branch(branch_name)
    if not pr_url:
        click.echo(f"No open PR found for branch '{branch_name}'.")
        return
    run_tests_on_pr(branch=branch_name, pr_url=pr_url)


if __name__ == "__main__":
    ghchain_cli()
