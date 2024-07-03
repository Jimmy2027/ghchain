"""Console script for ghchain."""

import click

from ghchain.config import config, logger
from ghchain.git_utils import (
    Stack,
    checkout_branch,
    get_current_branch,
    rebase_onto_branch,
)
from ghchain.github_utils import (
    get_branch_name_for_pr_id,
    get_pr_url_for_branch,
    run_tests_on_pr,
)
from ghchain.handlers import handle_existing_branch, handle_new_branch
from ghchain.status import print_status


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
    default_base_branch = config.base_branch
    stack = Stack.create(base_branch=default_base_branch)
    if not stack.commits:
        logger.info("No commits found that are not in main.")
        return

    pr_created = False
    pr_stack = []
    for commit_sha, commit_msg in stack.commit2message.items():
        logger.info(f"Processing commit: {commit_sha} - {commit_msg}")
        if commit_sha in stack.commits_without_branch:
            base_branch = handle_new_branch(
                commit_sha, commit_msg, draft, with_tests, default_base_branch, pr_stack
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
    "--rebase-onto",
    default=None,
    help=(
        "Rebase the current branch onto another branch, using 'update-refs'"
        "and push every updated branch to the remote."
    ),
)
@click.option(
    "--interactive-rebase-onto",
    default=None,
    help=(
        "Rebase the current branch onto another branch interactively, using 'update-refs'"
        "and push every updated branch to the remote."
    ),
)
def rebase(interactive_rebase_onto, rebase_onto):
    """Handles the rebasing options."""
    if interactive_rebase_onto:
        rebase_onto_branch(interactive_rebase_onto, interactive=True)
    elif rebase_onto:
        rebase_onto_branch(rebase_onto)


@ghchain_cli.command()
@click.option("--status", is_flag=True, help="Print the status of the PRs")
@click.option(
    "--live-status",
    is_flag=True,
    help="Print the status of the PRs, updating every minute.",
)
def status(status, live_status):
    """Handles the status printing options."""
    default_base_branch = config.base_branch
    if status or live_status:
        print_status(base_branch=default_base_branch, live=live_status)


@ghchain_cli.command()
@click.option(
    "--branch",
    "-b",
    type=str,
    default=None,
    help=(
        "Run the github workflows that are specified in the .ghchain.toml config"
        "of the repository for the specified branch."
    ),
)
def run_tests(branch):
    """
    Run the github workflows that are specified in the .ghchain.toml config of the repository for the specified branch.
    If '.' or nothing is passed, the current branch will be used.
    """
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
