import json
import re
from typing import Optional

import click

from ghchain.config import config, logger
from ghchain.utils import run_command

STACK_LIST_START_MARKER = "<!-- STACK_LIST_START -->"
STACK_LIST_END_MARKER = "<!-- STACK_LIST_END -->"
WORKFLOW_BADGES_START_MARKER = "<!-- WORKFLOW_BADGES_START -->"
WORKFLOW_BADGES_END_MARKER = "<!-- WORKFLOW_BADGES_END -->"


def run_workflows(workflow_ids: list[str], branch: str) -> list[str]:
    logger.info(f"Running workflows for branch {branch}...")
    md_badges = []
    for workflow_id in workflow_ids:
        command = ["gh", "workflow", "run", f"{workflow_id}.yml", "--ref", branch]
        result = run_command(
            command,
            check=True,
        )
        logger.debug(result.stdout)
        repo_url = get_repo_url()

        workflow_overview_url = (
            f"{repo_url}/actions/workflows/{workflow_id}.yml?query=branch%3A{branch}"
        )

        md_badges.append(
            (
                f"[![{workflow_id}]({repo_url}/actions/workflows/{workflow_id}.yml/badge.svg"
                f"?branch={branch})]({workflow_overview_url})"
            )
        )
    return md_badges


def get_repo_url() -> str:
    """
    Get the https url of the repository
    """
    repo_url_result = run_command(
        ["gh", "repo", "view", "--json", "url"],
    )
    # weird hack because I didn't get the --jq '.url' to work
    return [e for e in repo_url_result.stdout.strip().split('"') if "https" in e][0]


def create_pull_request(base_branch, head_branch, title, body, draft=False):
    logger.info(f"Creating pull request from {head_branch} to {base_branch}.")

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
        return url_match.group(0)
    click.echo("Failed to create pull request.")
    return None


def get_pr_body(pr_number):
    result = run_command(
        ["gh", "pr", "view", pr_number, "--json", "body"],
    )
    return json.loads(result.stdout)["body"] if result.stdout else ""


def get_workflow_pr_string(md_badges: list[str]):
    workflow_header = "# Workflow Results"
    return "\n".join(
        [
            WORKFLOW_BADGES_START_MARKER,
            workflow_header,
            *md_badges,
            WORKFLOW_BADGES_END_MARKER,
        ]
    )


def update_pr_stacklist_description(current_body, pr_url, pr_stack) -> str:
    """Update all PRs in the stack with the full stack list in their descriptions."""
    stack_list_lines = []

    for pr in pr_stack:
        # Highlight the current PR with an arrow
        if pr == pr_url:
            stack_list_lines.insert(0, f"- -> {pr}")
        else:
            stack_list_lines.insert(0, f"- {pr}")

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


def run_tests_on_pr(pr_url: str, branch: str):
    md_badges = run_workflows(config.workflows, branch)
    workflow_string = get_workflow_pr_string(md_badges)

    current_body = get_pr_body(pr_url.split("/")[-1])

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

    run_command(
        ["gh", "pr", "edit", pr_url.split("/")[-1], "--body", updated_body],
        check=True,
    )
    click.echo(f"PR description updated for PR {pr_url}.")


def update_pr_descriptions(pr_stack: list[str]):
    """
    Update all PRs in the stack with the full stack list in their descriptions, highlighting the current PR.
    run_tests is a tuple of the pr_url and the branch name.
    """
    pr_url_to_id = {pr: pr.split("/")[-1] for pr in pr_stack}
    prs_str = f"{', '.join([f'#{pr_url_to_id[pr_url]}' for pr_url in pr_stack])}"
    logger.info(f"Updating PR descriptions of {prs_str}.")

    # TODO: check that I'm the author of the PR
    for pr_url in pr_stack:
        current_pr_number = pr_url_to_id[pr_url]
        current_body = get_pr_body(current_pr_number)

        updated_body = update_pr_stacklist_description(current_body, pr_url, pr_stack)

        run_command(
            ["gh", "pr", "edit", current_pr_number, "--body", updated_body],
            check=True,
        )

        click.echo(f"PR description updated for PR #{current_pr_number}.")


def get_branch_name_for_pr_id(pr_id) -> Optional[str]:
    result = run_command(
        ["gh", "pr", "list", "--json", "headRefName,number", "--state", "open"],
    )
    prs = json.loads(result.stdout)
    return next((pr["headRefName"] for pr in prs if pr["number"] == pr_id), None)


def get_pr_url_for_branch(branch_name) -> Optional[str]:
    result = run_command(
        ["gh", "pr", "list", "--json", "url,headRefName", "--state", "open"],
    )
    prs = json.loads(result.stdout)
    return next((pr["url"] for pr in prs if pr["headRefName"] == branch_name), None)


def get_pr_url_for_id(pr_id) -> Optional[str]:
    result = run_command(
        ["gh", "pr", "list", "--json", "url,number", "--state", "open"],
    )
    prs = json.loads(result.stdout)
    return next((pr["url"] for pr in prs if pr["number"] == pr_id), None)


def get_latest_pr_id() -> int:
    result = run_command(
        ["gh", "pr", "list", "--json", "number", "--state", "all"],
    )
    prs = json.loads(result.stdout)

    sorted_prs = sorted(prs, key=lambda pr: pr["number"], reverse=True)

    if not sorted_prs:
        return -1

    return sorted_prs[0]["number"]


def get_pr_id_for_branch(branch_name) -> Optional[str]:
    pr_url = get_pr_url_for_branch(branch_name)
    if pr_url:
        return pr_url.split("/")[-1]
    return None


def get_pr_approval(pr_id) -> bool:
    result = run_command(
        ["gh", "pr", "view", pr_id, "--json", "reviewDecision"],
    )
    return json.loads(result.stdout)["reviewDecision"] == "APPROVED"


def get_pr_isdraft(pr_id) -> bool:
    result = run_command(
        ["gh", "pr", "view", pr_id, "--json", "isDraft"],
    )
    return json.loads(result.stdout)["isDraft"]
