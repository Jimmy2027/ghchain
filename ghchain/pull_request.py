import json
import re
from dataclasses import dataclass
from typing import Optional

import click

import ghchain
from ghchain.github_utils import (
    STACK_LIST_END_MARKER,
    STACK_LIST_START_MARKER,
    WORKFLOW_BADGES_END_MARKER,
    WORKFLOW_BADGES_START_MARKER,
    get_workflow_pr_string,
    run_workflows,
)
from ghchain.status import PrStatus
from ghchain.utils import run_command


@dataclass
class PR:
    """
    Class representing a github pull request.
    """

    pr_id: int
    pr_url: str
    pr_status: PrStatus | None
    head_branch: str
    body: str
    title: str
    commits: list[str]

    @classmethod
    def create_pull_request(
        cls, base_branch, head_branch, title, body, commit_sha, draft=False
    ) -> Optional["PR"]:
        ghchain.logger.info(
            f"Creating pull request from {head_branch} to {base_branch}."
        )

        # make sure the head branch is up to date
        try:
            ghchain.repo.git.push("origin", head_branch)
        except Exception:
            raise click.ClickException(
                f"Failed to push branch {head_branch} to remote. Please make sure the branch is up to date manually "
                "or run 'ghchain publish'."
            )

        command = [
            "gh",
            "pr",
            "create",
            "--base",
            base_branch,
            "--head",
            head_branch,
            "--title",
            title,
            "--body",
            body,
        ] + (["--draft"] if draft else [])
        result = run_command(command)
        url_match = re.search(r"https://github\.com/.+/pull/\d+", result.stdout)
        if url_match:
            click.echo(
                f"Pull request created: {url_match.group(0)} (Draft: {'Yes' if draft else 'No'})"
            )
            pr_url = url_match.group(0)
            pr_id = int(pr_url.rstrip("/").split("/")[-1])
            return cls(
                pr_url=url_match.group(0),
                pr_id=pr_id,
                pr_status=None,
                head_branch=head_branch,
                body=body,
                title=title,
                commits=[commit_sha],
            )

        click.echo("Failed to create pull request.")
        return None


def get_open_prs() -> list[PR]:
    gh_command = [
        "gh",
        "pr",
        "list",
        "--json",
        "url,headRefName,commits,number,isDraft,latestReviews,reviewDecision,mergeable,statusCheckRollup,title,body",
        "--state",
        "open",
    ]
    result = run_command(gh_command, check=True)
    result_dicts = json.loads(result.stdout)
    return [
        PR(
            pr_status=PrStatus.from_gh_cli_dict(result_dict),
            pr_id=int(result_dict["number"]),
            pr_url=result_dict["url"],
            head_branch=result_dict["headRefName"],
            body=result_dict["body"],
            title=result_dict["title"],
            commits=[commit["oid"] for commit in result_dict["commits"]],
        )
        for result_dict in result_dicts
    ]


def update_pr_stacklist_description(current_body, pr_url, pr_stack: list[PR]) -> str:
    """Update all PRs in the stack with the full stack list in their descriptions."""
    stack_list_lines = []

    for pr in pr_stack:
        # Highlight the current PR with an arrow
        if pr.pr_url == pr_url:
            stack_list_lines.insert(0, f"- -> {pr.pr_url}")
        else:
            stack_list_lines.insert(0, f"- {pr.pr_url}")

    stack_list_md = (
        (
            f"{STACK_LIST_START_MARKER}\nStack from [ghchain]"
            "(https://github.com/Jimmy2027/ghchain) (oldest at the bottom):\n"
        )
        + "\n".join(stack_list_lines)
        + f"\n{STACK_LIST_END_MARKER}"
    )

    if (
        STACK_LIST_START_MARKER in current_body
        and STACK_LIST_END_MARKER in current_body
    ):
        updated_body = re.sub(
            f"{STACK_LIST_START_MARKER}.*?{STACK_LIST_END_MARKER}",
            stack_list_md,
            current_body,
            flags=re.DOTALL,
        )
    else:
        updated_body = f"{current_body}\n\n{stack_list_md}"
    return updated_body


def update_pr_descriptions(pr_stack: list[PR]):
    """
    Update all PRs in the stack with the full stack list in their descriptions, highlighting the current PR.
    run_tests is a tuple of the pr_url and the branch name.
    """
    prs_str = f"{', '.join([f'#{pr.pr_id}' for pr in pr_stack])}"
    ghchain.logger.info(f"Updating PR descriptions of {prs_str}.")

    # TODO: check that I'm the author of the PR
    for pr in pr_stack:
        updated_body = update_pr_stacklist_description(pr.body, pr.pr_url, pr_stack)

        pr.body = updated_body

        run_command(
            ["gh", "pr", "edit", str(pr.pr_id), "--body", updated_body],
            check=True,
        )

        click.echo(f"PR description updated for PR #{pr.pr_id}.")


def run_tests_on_branch(branch: str, pull_request: PR | None = None):
    """
    Runs the configured workflows on the specified branch
    and updates the PR description with the workflow results if a PR URL is provided.

    Args:
        branch (str): The branch on which to run the workflows.
        pull_request: (str | None, optional): The pull request object of the pull request to update.
            If None, the PR description is not updated.

    Returns:
        None
    """
    if not ghchain.config.workflows:
        ghchain.logger.error("No workflows found in the config.")
        return

    md_badges = run_workflows(ghchain.config.workflows, branch)
    if pull_request is None:
        ghchain.logger.debug(
            f"No PR found for branch {branch}. Not updating PR description."
        )
        return
    workflow_string = get_workflow_pr_string(md_badges)

    current_body = pull_request.body

    if (
        WORKFLOW_BADGES_START_MARKER in current_body
        and WORKFLOW_BADGES_END_MARKER in current_body
    ):
        updated_body = re.sub(
            f"{WORKFLOW_BADGES_START_MARKER}.*?{WORKFLOW_BADGES_END_MARKER}",
            workflow_string,
            current_body,
            flags=re.DOTALL,
        )
    else:
        updated_body = f"{current_body}\n{workflow_string}"

    pull_request.body = updated_body

    run_command(
        [
            "gh",
            "pr",
            "edit",
            pull_request.pr_url.split("/")[-1],
            "--body",
            updated_body,
        ],
        check=True,
    )
    ghchain.logger.debug(f"PR description updated for PR {pull_request.pr_url}.")
