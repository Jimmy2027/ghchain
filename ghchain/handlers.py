import json
import click

from ghchain.config import config, logger
from ghchain.git_utils import (
    checkout_branch,
    create_branch_from_commit,
    create_branch_name,
    git_push,
    update_branch,
)
from ghchain.github_utils import (
    create_pull_request,
    get_latest_pr_id,
    get_pr_url_for_branch,
    run_tests_on_pr,
    update_pr_descriptions,
)
from ghchain.stack import Stack
from ghchain.utils import run_command


def handle_new_branch(
    commit_sha, commit_msg, draft, with_tests, base_branch: str, pr_stack: list
):
    """Handles the creation of a new branch."""
    branch_name = create_branch_name(
        config.branch_name_template, get_latest_pr_id() + 1
    )
    logger.info(f"Creating new branch for commit {commit_sha}: {branch_name}")
    create_branch_from_commit(branch_name, commit_sha)
    git_push(branch_name)
    pr_url = create_pull_request(
        base_branch=base_branch.replace("origin/", ""),
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


def handle_existing_branch(commit_sha, with_tests, stack: Stack, pr_stack: list):
    """Handles updating an existing branch."""
    branch_name: str | None = stack.commit2branch(commit_sha)
    if not branch_name:
        logger.error(f"Branch not found for commit {commit_sha}.")
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


def handle_land(branch):
    """
    Merge the specified branch into the configured base branch.
    """

    run_command(
        ["git", "branch", "-f", config.base_branch.replace("origin/", ""), branch],
        check=True,
    )
    run_command(
        ["git", "push", "origin", config.base_branch.replace("origin/", "")], check=True
    )

    if config.delete_branch_after_merge:
        # List all open PRs targeting the branch to be deleted
        prs = json.loads(
            run_command(
                [
                    "gh",
                    "pr",
                    "list",
                    "--json",
                    "number",
                    "--state",
                    "open",
                    "--base",
                    branch,
                ],
                check=True,
            ).stdout
        )

        # Change the base branch of all those PRs to target the configured base branch
        for pr in prs:
            run_command(
                [
                    "gh",
                    "pr",
                    "edit",
                    str(pr["number"]),
                    "--base",
                    config.base_branch.replace("origin/", ""),
                ],
                check=True,
            )

        # Delete the remote branch
        run_command(["git", "push", "origin", "--delete", branch], check=True)
        # Delete the local branch
        run_command(["git", "branch", "-D", branch], check=True)
