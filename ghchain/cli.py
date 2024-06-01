"""Console script for ghchain."""

from typing import Optional

import click

from ghchain.config import config, logger
from ghchain.git_utils import (
    Stack,
    checkout_branch,
    checkout_new_branch,
    create_branch_name,
    get_current_branch,
    git_push,
    rebase_onto_branch,
    set_upstream_to_origin,
    update_base_branch,
    update_branch,
)
from ghchain.github_utils import (
    create_pull_request,
    get_branch_name_for_pr_id,
    get_latest_pr_id,
    get_pr_url_for_branch,
    run_tests_on_pr,
    update_pr_descriptions,
)
from ghchain.status import print_status

pr_stack = []


@click.command()
@click.option("--draft", is_flag=True, help="Create the pull request as a draft.")
@click.option("--status", is_flag=True, help="Print the status of the PRs")
@click.option(
    "--live-status",
    is_flag=True,
    help="Print the status of the PRs, updating every minute.",
)
@click.option(
    "--with-tests",
    is_flag=True,
    help="Run the github workflows that are specified in the .ghchain.toml config of the repository.",
)
@click.option(
    "--run-tests",
    type=str,
    default=None,
    help=(
        "Run the github workflows that are specified in the .ghchain.toml "
        "config of the repository for the specified branch. If '.' is passed,"
        " the current branch will be used."
    ),
)
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
def main(
    draft,
    with_tests,
    rebase_onto,
    interactive_rebase_onto,
    run_tests,
    status,
    live_status,
):
    """
    From your dev branch, gather all commits that are not in the default base branch (main).
    For each commit, create a new branch based on the previous branch with the next commit,
      push the branch to origin and create a PR.

    How to:
    Update a commit in the stack: git commit --amend --no-edit on the branch with the commit.
    Then from your dev branch, run `ghchain --rebase-onto <branch>`
    """
    try:
        default_base_branch = config.base_branch
        if handle_rebasing(interactive_rebase_onto, rebase_onto):
            return
        if handle_status(status, live_status, default_base_branch):
            return
        if handle_run_tests(run_tests):
            return

        # If none of the above options are provided, process commits
        process_commits(draft, with_tests, default_base_branch)
        click.echo("All Done!")
    except Exception as e:
        logger.error(f"An error occurred: {e}")
        raise click.Abort()


def handle_rebasing(interactive_rebase_onto, rebase_onto):
    """Handles the rebasing options."""
    if interactive_rebase_onto:
        rebase_onto_branch(interactive_rebase_onto, interactive=True)
        return True
    elif rebase_onto:
        rebase_onto_branch(rebase_onto)
        return True
    return False


def handle_status(status, live_status, base_branch):
    """Handles the status printing options."""
    if status or live_status:
        print_status(base_branch=base_branch, live=live_status)
        return True
    return False


def handle_run_tests(run_tests):
    """Handles the run-tests option."""
    if run_tests:
        branch_name = (
            get_branch_name_for_pr_id(int(run_tests))
            if run_tests.isdigit()
            else get_current_branch()
            if run_tests == "."
            else run_tests
        )
        pr_url = get_pr_url_for_branch(branch_name)
        if not pr_url:
            click.echo(f"No open PR found for branch '{branch_name}'.")
            return True
        run_tests_on_pr(pr_url, branch_name)
        return True
    return False


def update_base_branch_if_needed(default_base_branch):
    """Updates the base branch if needed."""
    # TODO: if the base branch has been updated, we should update the stack
    update_base_branch(default_base_branch)


def process_commits(draft: bool, with_tests: bool, base_branch: str):
    """Processes commits and creates PRs for each."""
    stack = Stack.create(base_branch=base_branch)
    if not stack.commits:
        click.echo("No commits found that are not in main.")
        return

    pr_created = False
    for commit_sha, commit_msg in stack.commit2message.items():
        logger.info(f"Processing commit: {commit_sha} - {commit_msg}")
        if commit_sha in stack.commits_without_branch:
            base_branch = handle_new_branch(
                commit_sha, commit_msg, draft, with_tests, base_branch
            )
            pr_created = True
        else:
            base_branch = handle_existing_branch(commit_sha, with_tests, stack)

        if pr_created and not click.confirm(
            "Do you want to continue with the next commit?", default=True
        ):
            break
        checkout_branch(base_branch)

    checkout_branch(stack.dev_branch)


def handle_new_branch(commit_sha, commit_msg, draft, with_tests, base_branch: str):
    """Handles the creation of a new branch."""
    branch_name = create_branch_name(
        config.branch_name_template, get_latest_pr_id() + 1
    )
    logger.info(f"Creating new branch for commit {commit_sha}: {branch_name}")
    checkout_new_branch(branch_name, commit_sha)
    set_upstream_to_origin(branch_name)
    git_push(branch_name)
    pr_url = create_pull_request(
        base_branch=base_branch,
        head_branch=branch_name,
        title=commit_msg,
        body=commit_msg,
        draft=draft,
    )
    if pr_url:
        pr_stack.append(pr_url)
        update_pr_descriptions(
            pr_stack=pr_stack,
        )
        if with_tests:
            run_tests_on_pr(pr_url, branch_name)

    return branch_name


def handle_existing_branch(commit_sha, with_tests, stack: Stack):
    """Handles updating an existing branch."""
    branch_name: Optional[str] = stack.commit2branch(commit_sha)
    if not branch_name:
        click.echo(f"Branch not found for commit {commit_sha}.")
        raise click.Abort()

    checkout_branch(branch_name)
    update_branch(branch_name)
    pr_url = get_pr_url_for_branch(branch_name)

    if pr_url:
        pr_stack.append(pr_url)
        update_pr_descriptions(
            pr_stack=pr_stack,
        )
        if with_tests:
            run_tests_on_pr(pr_url, branch_name)
    return branch_name
