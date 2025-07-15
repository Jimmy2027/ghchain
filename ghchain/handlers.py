import json
import click
import ghchain
import textwrap
from ghchain.utils import run_command


def handle_land(branch):
    """
    Merge the specified branch into the configured base branch.
    This will close the corresponding PRs, close any linked issues,
    and delete the branch if configured to do so.
    """

    if (
        branch not in ghchain.repo.branches
        or ghchain.repo.branches[branch].commit
        != ghchain.repo.remotes[ghchain.config.remote].refs[branch].commit
    ):
        # if the branch is not up to date, pull the latest changes
        if click.confirm(
            f"The local branch '{branch}' is out of date with the remote. Do you want to update it?"
        ):
            try:
                run_command(
                    ["git", "fetch", ghchain.config.remote, f"{branch}:{branch}"],
                    check=True,
                )
            except Exception as e:
                ghchain.logger.error(
                    f"Failed to pull the latest changes from the remote: {e}"
                )
                return
        else:
            ghchain.logger.error(
                f"Branch '{branch}' is not up to date with the remote. Aborting."
            )
            return

    # update the base branch locally and push it to origin
    run_command(
        [
            "git",
            "branch",
            "-f",
            ghchain.config.base_branch.replace(f"{ghchain.config.remote}/", ""),
            branch,
        ],
        check=True,
    )
    run_command(
        [
            "git",
            "push",
            ghchain.config.remote,
            ghchain.config.base_branch.replace(f"{ghchain.config.remote}/", ""),
        ],
        check=True,
    )

    # Close linked issues for the PR associated with this branch
    try:
        # Retrieve PR number for this branch
        pr_data = json.loads(
            run_command(
                ["gh", "pr", "view", branch, "--json", "number"], check=True
            ).stdout
        )
        pr_number = pr_data["number"]
        ghchain.logger.info(f"Found PR #{pr_number} for branch '{branch}'.")
    except Exception as e:
        ghchain.logger.error(f"Failed to get PR number for branch '{branch}': {e}")
        pr_number = None

    if pr_number:
        # GraphQL query to fetch linked issues that will be closed by this PR
        query = textwrap.dedent("""
            query ($owner: String!, $repo: String!, $pr: Int!) {
                repository(owner: $owner, name: $repo) {
                    pullRequest(number: $pr) {
                        closingIssuesReferences(first: 100) {
                            nodes {
                                number
                            }
                        }
                    }
                }
            }
        """)
        try:
            # Execute the GraphQL query via gh CLI
            output = run_command(
                [
                    "gh",
                    "api",
                    "graphql",
                    "-F",
                    f"owner={ghchain.repo.owner}",
                    "-F",
                    f"repo={ghchain.repo.name}",
                    "-F",
                    f"pr={pr_number}",
                    "-f",
                    f"query={query}",
                    "--jq",
                    ".data.repository.pullRequest.closingIssuesReferences.nodes[].number",
                ],
                check=True,
            ).stdout.strip()

            if output:
                # Each line is an issue number
                issue_numbers = output.splitlines()
                for issue in issue_numbers:
                    ghchain.logger.info(
                        f"Closing linked issue #{issue} for PR #{pr_number}"
                    )
                    run_command(["gh", "issue", "close", issue], check=False)
            else:
                ghchain.logger.info("No linked issues found for this PR.")
        except Exception as e:
            ghchain.logger.error(
                f"Failed to close linked issues for PR #{pr_number}: {e}"
            )

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
                ghchain.config.base_branch.replace("origin/", ""),
            ],
            # Don't check here because sometimes GitHub updates the PRs faster than the CLI
            check=False,
        )

    # Delete the branch locally and on the remote if configured to do so
    if ghchain.config.delete_branch_after_merge:
        run_command(["git", "branch", "-D", branch], check=False)
        run_command(
            ["git", "push", ghchain.config.remote, "--delete", branch], check=False
        )
