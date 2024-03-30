import json
import re
import subprocess
from typing import Optional, Tuple

import click

from ghchain.config import Config
from ghchain.utils import run_command

STACK_LIST_START_MARKER = "<!-- STACK_LIST_START -->"
STACK_LIST_END_MARKER = "<!-- STACK_LIST_END -->"
WORKFLOW_BADGES_START_MARKER = "<!-- WORKFLOW_BADGES_START -->"
WORKFLOW_BADGES_END_MARKER = "<!-- WORKFLOW_BADGES_END -->"


def run_workflows(workflow_ids: list[str], branch: str) -> list[str]:
    click.echo(f"Running workflows for branch {branch}...")
    md_badges = []
    for workflow_id in workflow_ids:
        command = ["gh", "workflow", "run", f"{ workflow_id }.yml", "--ref", branch]
        result = run_command(
            command,
            check=True,
        )
        print(result.stdout)
        repo_url = get_repo_url()

        md_badges.append(
            (
                f"[![{workflow_id}]({repo_url}/actions/workflows/{workflow_id}.yml/badge.svg"
                f"?branch={branch})]({repo_url}/actions/workflows/{workflow_id}.yml)"
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


def create_pull_request(
    config, base_branch, head_branch, title, body, draft=False, run_tests=False
):
    if run_tests:
        md_badges = run_workflows(config.workflows, head_branch)

        workflow_string = get_workflow_pr_string(md_badges)
        body += f"\n{workflow_string}"

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


def update_pr_descriptions(
    config: Config, run_tests: Optional[Tuple[str, str]], pr_stack
):
    """Update all PRs in the stack with the full stack list in their descriptions, highlighting the current PR."""
    for pr_url in pr_stack:
        stack_list_lines = []

        current_pr_number = pr_url.split("/")[-1]

        for pr in pr_stack:
            # Highlight the current PR with an arrow
            if pr == pr_url:
                stack_list_lines.insert(0, f"- -> {pr}")
            else:
                stack_list_lines.insert(0, f"- {pr}")

        stack_list_md = (
            f"{STACK_LIST_START_MARKER}\nStack from [ghchain](https://github.com/Jimmy2027/ghchain) (oldest at the bottom):\n"
            + "\n".join(stack_list_lines)
            + f"\n{STACK_LIST_END_MARKER}"
        )

        current_body = get_pr_body(current_pr_number)

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

        if run_tests and run_tests[0] == pr_url:
            # TODO need to check that the PR corresponds to the branch_name
            md_badges = run_workflows(config.workflows, run_tests[1])
            workflow_str = get_workflow_pr_string(md_badges)

            if (
                WORKFLOW_BADGES_START_MARKER in current_body
                and WORKFLOW_BADGES_END_MARKER in current_body
            ):
                updated_body = re.sub(
                    f"{WORKFLOW_BADGES_START_MARKER}.*?{WORKFLOW_BADGES_END_MARKER}",
                    workflow_str,
                    current_body,
                    flags=re.DOTALL,
                )
            else:
                updated_body += f"\n{workflow_str}"

        subprocess.run(
            ["gh", "pr", "edit", current_pr_number, "--body", updated_body],
            check=True,
        )

        click.echo(f"PR description updated for PR #{current_pr_number}.")


def get_pr_url_for_branch(branch_name):
    result = subprocess.run(
        ["gh", "pr", "list", "--json", "url,headRefName", "--state", "open"],
        stdout=subprocess.PIPE,
        text=True,
    )
    prs = json.loads(result.stdout)
    return next((pr["url"] for pr in prs if pr["headRefName"] == branch_name), None)
