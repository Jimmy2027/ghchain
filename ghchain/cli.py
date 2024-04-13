"""Console script for ghchain."""

import click

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
    print_status,
    update_pr_descriptions,
)
from ghchain.config import config

pr_stack = []


@click.command()
@click.option(
    "--default-base-branch",
    default="main",
    help="Default base branch for the first PR.",
)
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
@click.option("--rebase-onto", default=None)
def main(
    default_base_branch, draft, with_tests, rebase_onto, run_tests, status, live_status
):
    """
    From your dev branch, gather all commits that are not in the default base branch (main).
    For each commit, create a new branch based on the previous branch with the next commit,
      push the branch to origin and create a PR.

    How to:
    Update a commit in the stack: git commit --amend --no-edit on the branch with the commit.
    Then from your dev branch, run `ghchain --rebase-onto <branch>`
    """
    if rebase_onto:
        rebase_onto_branch(rebase_onto)
        return

    if status or live_status:
        print_status(
            stack=Stack.create(base_branch=default_base_branch), live=live_status
        )
        return

    if run_tests:
        # Run the workflows for the specified branch
        if run_tests.isdigit():
            branch_name = get_branch_name_for_pr_id(int(run_tests))
        else:
            branch_name = get_current_branch() if run_tests == "." else run_tests

        pr_url = get_pr_url_for_branch(branch_name)
        if not pr_url:
            click.echo(f"No open PR found for branch '{branch_name}'.")
            return
        update_pr_descriptions(run_tests=(pr_url, branch_name), pr_stack=[pr_url])
        return

    update_base_branch(default_base_branch)

    stack = Stack.create(base_branch=default_base_branch)

    if not stack.commits:
        click.echo("No commits found that are not in main.")
        return

    for commit_sha, commit_msg in stack.commit2message.items():
        click.echo(f"Processing commit: {commit_sha} - {commit_msg}")
        if commit_sha in stack.commits_without_branch:
            branch_name = create_branch_name(
                config.branch_name_template, get_latest_pr_id() + 1
            )
            checkout_new_branch(branch_name, commit_sha)
            set_upstream_to_origin(branch_name)
            git_push(branch_name)
            pr_url = create_pull_request(
                base_branch=default_base_branch,
                head_branch=branch_name,
                title=commit_msg,
                body=commit_msg,
                draft=draft,
                run_tests=with_tests,
            )
        else:
            branch_name: str = stack.commit2branch(commit_sha)
            checkout_branch(branch_name)
            update_branch(branch_name)
            pr_url = get_pr_url_for_branch(branch_name)

        if pr_url:
            pr_stack.append(pr_url)
            update_pr_descriptions(
                run_tests=(pr_url, branch_name) if with_tests else None,
                pr_stack=pr_stack,
            )
            default_base_branch = branch_name
        if not click.confirm(
            "Do you want to continue with the next commit?", default=True
        ):
            break
        checkout_branch(default_base_branch)

    checkout_branch(stack.dev_branch)
    click.echo("All Done!")
