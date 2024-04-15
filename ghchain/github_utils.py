import json
import re
import subprocess
from dataclasses import dataclass
import time
from typing import Optional, Tuple
from rich.live import Live

import click
from rich.console import Console
from rich.table import Table

from ghchain.config import config
from ghchain.git_utils import Stack
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

        workflow_overview_url = (
            f"{repo_url}/actions/workflows/{workflow_id}.yml?query=branch%3A{ branch }"
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


def create_pull_request(
    base_branch, head_branch, title, body, draft=False, run_tests=False
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
        f"{STACK_LIST_START_MARKER}\nStack from [ghchain](https://github.com/Jimmy2027/ghchain) (oldest at the bottom):\n"
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


def update_pr_descriptions(run_tests: Optional[Tuple[str, str]], pr_stack):
    """
    Update all PRs in the stack with the full stack list in their descriptions, highlighting the current PR.
    run_tests is a tuple of the pr_url and the branch name.
    """
    for pr_url in pr_stack:
        current_pr_number = pr_url.split("/")[-1]
        current_body = get_pr_body(current_pr_number)

        updated_body = update_pr_stacklist_description(current_body, pr_url, pr_stack)

        if run_tests and run_tests[0] == pr_url:
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


def get_branch_name_for_pr_id(pr_id) -> Optional[str]:
    result = subprocess.run(
        ["gh", "pr", "list", "--json", "headRefName,number", "--state", "open"],
        stdout=subprocess.PIPE,
        text=True,
    )
    prs = json.loads(result.stdout)
    return next((pr["headRefName"] for pr in prs if pr["number"] == pr_id), None)


def get_pr_url_for_branch(branch_name) -> Optional[str]:
    result = subprocess.run(
        ["gh", "pr", "list", "--json", "url,headRefName", "--state", "open"],
        stdout=subprocess.PIPE,
        text=True,
    )
    prs = json.loads(result.stdout)
    return next((pr["url"] for pr in prs if pr["headRefName"] == branch_name), None)


def get_pr_url_for_id(pr_id) -> Optional[str]:
    result = subprocess.run(
        ["gh", "pr", "list", "--json", "url,number", "--state", "open"],
        stdout=subprocess.PIPE,
        text=True,
    )
    prs = json.loads(result.stdout)
    return next((pr["url"] for pr in prs if pr["number"] == pr_id), None)


def get_latest_pr_id() -> int:
    result = subprocess.run(
        ["gh", "pr", "list", "--json", "number", "--state", "all"],
        stdout=subprocess.PIPE,
        text=True,
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


@dataclass
class WorkflowStatus:
    status: str
    conclusion: str
    name: str
    branch: str
    commit: str
    event: str
    id: str
    elapsed: str
    timestamp: str
    workflow_yml_fn: str

    @classmethod
    def from_line(cls, line: str, workflow_yml_fn: str):
        status, conclusion, name, branch, commit, event, id, elapsed, timestamp = (
            line.split("\t")
        )
        return cls(
            status=status,
            conclusion=conclusion,
            name=name,
            branch=branch,
            commit=commit,
            event=event,
            id=id,
            elapsed=elapsed,
            timestamp=timestamp,
            workflow_yml_fn=workflow_yml_fn,
        )

    @classmethod
    def create(cls, workflow_yml_fn: str, branchname: str):
        result = run_command(
            [
                "gh",
                "run",
                "list",
                "--workflow",
                f"{ workflow_yml_fn }.yml",
                "-b",
                branchname,
            ],
            check=True,
        )
        lines = result.stdout.splitlines()
        if lines:
            line = result.stdout.splitlines()[0]
            return WorkflowStatus.from_line(line, workflow_yml_fn)
        return None


@dataclass
class PrStatus:
    branchname: str
    pr_id: int
    review_decision: bool
    is_draft: bool
    is_mergeable: bool
    workflow_statuses: Optional[list[WorkflowStatus]] = None

    @classmethod
    def from_branchname(cls, branchname: str):
        pr_id = get_pr_id_for_branch(branchname)
        if not pr_id:
            return None
        workflow_statuses = []
        for workflow in config.workflows:
            workflow_statuses.append(WorkflowStatus.create(workflow, branchname))

        # TODO: add statusCheckRollup
        result = run_command(
            ["gh", "pr", "view", pr_id, "--json", "reviewDecision,isDraft,mergeable"],
        )
        result_dict = json.loads(result.stdout)

        return cls(
            branchname=branchname,
            pr_id=int(pr_id),
            workflow_statuses=workflow_statuses,
            review_decision=result_dict["reviewDecision"],
            is_draft=result_dict["isDraft"],
            is_mergeable=result_dict["mergeable"],
        )


@dataclass
class StackStatus:
    pr_statuses: list[PrStatus]
    stack: Optional[Stack] = None

    @classmethod
    def from_stack(cls, stack: Stack):
        pr_statuses = []
        for branch in stack.branches:
            pr_statuses.append(PrStatus.from_branchname(branch))

        return cls(pr_statuses=pr_statuses, stack=stack)

    def get_status_table(self):
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Branch", style="dim", width=30)
        table.add_column("PR ID", style="dim", width=6)
        table.add_column("Review Decision", style="dim", width=20)
        table.add_column("Draft", style="dim", width=8)
        table.add_column("Workflow Status", style="dim", width=30)

        for pr_status in self.pr_statuses:
            if not pr_status:
                continue
            if not pr_status.workflow_statuses:
                continue
            review_decision_color = (
                "bright_green" if pr_status.review_decision == "APPROVED" else "default"
            )
            table.add_row(
                f"[bold gray]{ pr_status.branchname }[/]",
                str(pr_status.pr_id),
                f"[bold {review_decision_color}]{pr_status.review_decision}[/]",
                str(pr_status.is_draft),
                "",
            )
            for workflow_status in pr_status.workflow_statuses:
                if not workflow_status:
                    continue
                color = (
                    "bright_green"
                    if workflow_status.conclusion == "success"
                    else "bright_red"
                )
                table.add_row(
                    "",
                    "",
                    "",
                    "",
                    f"[bold {color}]{workflow_status.workflow_yml_fn}[/]: {workflow_status.status, workflow_status.conclusion}",
                )
        return table

    def print_status(self):
        console = Console()
        console.print(self.get_status_table())


def print_status(base_branch: str = "main", live: bool = False):
    if live:
        with Live(
            StackStatus.from_stack(
                Stack.create(base_branch=base_branch)
            ).get_status_table(),
            refresh_per_second=1,
        ) as live_context:
            while True:
                time.sleep(60)
                live_context.console.clear()
                live_context.update(
                    StackStatus.from_stack(
                        Stack.create(base_branch=base_branch)
                    ).get_status_table()
                )
        return
    StackStatus.from_stack(Stack.create(base_branch=base_branch)).print_status()
    return
