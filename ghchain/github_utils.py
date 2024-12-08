import json
import re
import shutil
from typing import Optional


import ghchain
from ghchain.utils import run_command

STACK_LIST_START_MARKER = "<!-- STACK_LIST_START -->"
STACK_LIST_END_MARKER = "<!-- STACK_LIST_END -->"
WORKFLOW_BADGES_START_MARKER = "<!-- WORKFLOW_BADGES_START -->"
WORKFLOW_BADGES_END_MARKER = "<!-- WORKFLOW_BADGES_END -->"


# Verify that gh is installed
if shutil.which("gh") is None:
    raise Exception(
        "gh is not installed. Please install it from https://cli.github.com/"
    )


def run_workflows(workflow_ids: list[str], branch: str) -> list[str]:
    ghchain.logger.info(f"Running workflows for branch {branch}...")
    md_badges = []
    for workflow_id in workflow_ids:
        command = ["gh", "workflow", "run", f"{workflow_id}.yml", "--ref", branch]
        result = run_command(
            command,
            check=True,
        )
        ghchain.logger.debug(result.stdout)
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
    urls = [e for e in repo_url_result.stdout.strip().split('"') if "https" in e]
    if not urls:
        ghchain.logger.error("Failed to get the repository url.")
        raise Exception("Failed to get the repository url.")
    return urls[0]


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


def get_latest_id(which: str) -> int:
    result = run_command(
        ["gh", which, "list", "--json", "number", "--state", "all"],
    )
    prs = json.loads(result.stdout)

    sorted_prs = sorted(prs, key=lambda pr: pr["number"], reverse=True)

    if not sorted_prs:
        return -1

    return sorted_prs[0]["number"]


def get_next_gh_id() -> int:
    return max(get_latest_id("pr"), get_latest_id("issue")) + 1


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


def create_branch_from_issue(issue_id: int, base_commit: str) -> str:
    """
    Create a branch from a GitHub issue and return the branch name.
    """
    # Run the command to create the branch
    result = run_command(["gh", "issue", "develop", str(issue_id)])

    # Check if the command executed successfully
    if result.returncode != 0:
        raise RuntimeError(
            f"Failed to create branch from issue {issue_id}: {result.stderr}"
        )

    # Extract the branch name from the output
    pattern = r"github.com/.*/tree/([^\s]+)"
    match = re.search(pattern, result.stdout)

    if match:
        branch_name = match.group(1)
        # fetch the origin
        ghchain.repo.remotes.origin.fetch()
        # Create a new branch pointing to the base commit
        branch = ghchain.repo.create_head(branch_name, base_commit)

        # Set the branch to track the remote branch
        branch.set_tracking_branch(ghchain.repo.remotes.origin.refs[branch_name])

        # Push the updated branch to the remote
        ghchain.repo.git.push("origin", f"{branch_name}:{branch_name}", force=True)

        return branch_name
    else:
        raise ValueError("Branch name not found in the command output.")
