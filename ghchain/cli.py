"""Console script for ghchain."""

import click


@click.group()
def ghchain_cli():
    pass


@ghchain_cli.command()
@click.option("--draft", is_flag=True, help="Create the pull request as a draft.")
@click.option(
    "--with-tests",
    is_flag=True,
    help="Run the github workflows that are specified in the .ghchain.toml config of the repository.",
)
def process_commits(draft, with_tests):
    """Processes commits and creates PRs for each."""
    from ghchain.config import config, logger
    from ghchain.git_utils import checkout_branch
    from ghchain.handlers import handle_existing_branch, handle_new_branch
    from ghchain.stack import Stack

    base_branch = config.base_branch
    stack = Stack.create(base_branch=base_branch)
    if not stack.commits:
        logger.info("No commits found that are not in main.")
        return

    pr_created = False
    pr_stack = []
    for commit_sha, commit_msg in stack.commit2message.items():
        logger.info(f"Processing commit: {commit_sha} - {commit_msg}")
        if commit_sha in stack.commits_without_branch:
            base_branch = handle_new_branch(
                commit_sha, commit_msg, draft, with_tests, base_branch, pr_stack
            )
            pr_created = True
        else:
            base_branch = handle_existing_branch(
                commit_sha, with_tests, stack, pr_stack
            )

        if pr_created and not click.confirm(
            "Do you want to continue with the next commit?", default=True
        ):
            break
        checkout_branch(base_branch)

    checkout_branch(stack.dev_branch)


@ghchain_cli.command()
@click.option(
    "--branch",
    "-b",
    type=str,
    default=None,
    help=("The branch to which the configured base branch will be updated."),
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
        "the commit messages and the order of the commits."
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
    from ghchain.config import config
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
def run_tests(branch):
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
    run_tests_on_pr(pr_url, branch_name)


if __name__ == "__main__":
    ghchain_cli()
