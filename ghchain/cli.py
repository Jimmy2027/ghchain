"""Console script for ghchain."""

import click

from ghchain.git_utils import (
    checkout_branch,
    checkout_new_branch,
    create_branch_name,
    get_commits_not_in_base_branch,
    get_current_branch,
    git_push,
    local_branch_exists,
    rebase_onto_branch,
    set_upstream_to_origin,
    update_base_branch,
    update_branch,
)
from ghchain.github_utils import (
    create_pull_request,
    get_branch_name_for_pr_id,
    get_pr_url_for_branch,
    print_status,
    update_pr_descriptions,
)

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
def main(default_base_branch, draft, with_tests, rebase_onto, run_tests, status):
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

    if status:
        commits = get_commits_not_in_base_branch(base_branch=default_base_branch)
        print_status(commits)
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

    base_branch = default_base_branch
    update_base_branch(base_branch)

    commits = get_commits_not_in_base_branch(base_branch=default_base_branch)

    if not commits:
        click.echo("No commits found that are not in main.")
        return

    for commit_sha, commit_msg in commits:
        click.echo(f"Processing commit: {commit_sha} - {commit_msg}")
        branch_name = create_branch_name(commit_msg)

        checkout_branch(base_branch)
        update_branch(base_branch)

        if local_branch_exists(branch_name):
            click.echo(
                f"Local branch '{branch_name}' already exists. Checking for existing PR..."
            )
            pr_url = get_pr_url_for_branch(branch_name)
            if not pr_url:
                click.echo(
                    f"No open PR found for branch '{branch_name}'. You may need to create a PR manually."
                )
                continue
        else:
            checkout_new_branch(branch_name, commit_sha)
            set_upstream_to_origin(branch_name)
            git_push(branch_name)
            pr_url = create_pull_request(
                base_branch,
                branch_name,
                branch_name,
                commit_msg,
                draft,
                with_tests,
            )
        if pr_url:
            pr_stack.append(pr_url)
            update_pr_descriptions(
                run_tests=(pr_url, branch_name) if with_tests else None,
                pr_stack=pr_stack,
            )
            base_branch = branch_name
        if not click.confirm(
            "Do you want to continue with the next commit?", default=True
        ):
            break
        checkout_branch(default_base_branch)
