import json
import time
from dataclasses import dataclass
from typing import Optional

from rich.console import Console
from rich.live import Live
from rich.table import Table

from ghchain.config import config
from ghchain.stack import Stack
from ghchain.github_utils import get_pr_id_for_branch
from ghchain.utils import run_command


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
                f"{workflow_yml_fn}.yml",
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
class StatusCheck:
    completedAt: str
    conclusion: str
    detailsUrl: str
    name: str
    startedAt: str
    status: str
    workflowName: str


@dataclass
class PrStatus:
    branchname: str
    pr_id: int
    review_decision: bool
    is_draft: bool
    is_mergeable: bool
    title: str
    workflow_statuses: Optional[list[WorkflowStatus]] = None
    status_checks: Optional[dict[str, StatusCheck]] = None

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
            [
                "gh",
                "pr",
                "view",
                pr_id,
                "--json",
                "reviewDecision,isDraft,mergeable,statusCheckRollup,title",
            ],
        )
        result_dict = json.loads(result.stdout)

        return cls(
            branchname=branchname,
            pr_id=int(pr_id),
            workflow_statuses=workflow_statuses,
            review_decision=result_dict["reviewDecision"],
            is_draft=result_dict["isDraft"],
            is_mergeable=result_dict["mergeable"],
            status_checks={
                status["name"]: StatusCheck(
                    **{
                        k: V
                        for k, V in status.items()
                        if k in StatusCheck.__annotations__
                    }
                )
                for status in result_dict["statusCheckRollup"]
            }
            if result_dict["statusCheckRollup"]
            else None,
            title=result_dict["title"],
        )


@dataclass
class StatusRow:
    branch: str
    pr_id: int
    review_decision: Optional[str]
    is_draft: bool
    workflow_status: str
    status_checks: str
    title: str

    @staticmethod
    def status2color(status: str, conclusion: str):
        status = status.lower()
        conclusion = conclusion.lower()

        if conclusion == "success":
            return "bright_green"
        elif status in ["queued", "in_progress"] or conclusion == "neutral":
            return "yellow"
        else:
            return "bright_red"

    @classmethod
    def from_pr_status(cls, pr_status: PrStatus):
        workflow_status_str = ""
        for workflow_status in pr_status.workflow_statuses:
            if workflow_status:
                color = cls.status2color(
                    workflow_status.status, workflow_status.conclusion
                )
                workflow_status_str += (
                    f"[bold {color}]{workflow_status.workflow_yml_fn}[/]:"
                    " {workflow_status.status, workflow_status.conclusion}\n"
                )

        status_check_str = ""
        if pr_status.status_checks:
            for status_check in pr_status.status_checks.values():
                color = cls.status2color(status_check.status, status_check.conclusion)
                status_check_str += (
                    f"[bold {color}]{status_check.name}[/]:"
                    " {status_check.status, status_check.conclusion}\n"
                )

        return cls(
            branch=pr_status.branchname,
            pr_id=pr_status.pr_id,
            review_decision=pr_status.review_decision,
            is_draft=pr_status.is_draft,
            workflow_status=workflow_status_str,
            status_checks=status_check_str,
            title=pr_status.title,
        )

    def to_row(self):
        review_decision_color = (
            "bright_green" if self.review_decision == "APPROVED" else "default"
        )
        return [
            f"[bold gray]{self.branch}[/]\n\t{self.title}",
            str(self.pr_id),
            f"[bold {review_decision_color}]{self.review_decision}[/]",
            str(self.is_draft),
            self.workflow_status,
            self.status_checks,
        ]


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

    def create_table_data(self):
        table_data = []

        for pr_status in self.pr_statuses:
            if not pr_status:
                continue

            table_data.append(StatusRow.from_pr_status(pr_status).to_row())

        return table_data

    def get_status_table(self):
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Branch", style="dim", width=30)
        table.add_column("PR ID", style="dim", width=6)
        table.add_column("Review Decision", style="dim", width=20)
        table.add_column("Draft", style="dim", width=8)
        table.add_column("Workflow Status", style="dim", width=30)
        table.add_column("Status Checks", style="dim", width=30)  # New column

        table_data = self.create_table_data()

        for i, row in enumerate(table_data):
            table.add_row(*row)
            # add a divider between rows, except for the last row
            if i < len(table_data) - 1:
                table.add_row("-----", "-----", "-----", "-----", "-----", "-----")

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
