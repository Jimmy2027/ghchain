"""Integration tests for Stack.process_stack / process_commit with the
PR: #N trailer flow.

Uses a real local git repo (no network); mocks every `gh`-touching helper
and the PR creation entrypoint.
"""

import os
from itertools import count
from pathlib import Path

import pytest
from git import Repo

import ghchain


@pytest.fixture
def fresh_repo(mocker, tmp_path):
    """Initialize a repo with main → dev branches and a local bare remote."""
    bare_path = tmp_path / "bare.git"
    Repo.init(bare_path, bare=True)

    work_path = tmp_path / "work"
    work_path.mkdir()
    os.chdir(work_path)
    repo = Repo.init(work_path)
    repo.git.config("user.email", "test@example.com")
    repo.git.config("user.name", "Test User")
    repo.create_remote("origin", str(bare_path))

    repo.git.checkout(b="main")
    Path(work_path / "README.md").write_text("hello\n")
    repo.index.add(["README.md"])
    repo.index.commit("initial commit")
    repo.git.push("origin", "main")
    repo.git.checkout(b="dev")
    mocker.patch("ghchain.repo", repo)
    return repo


@pytest.fixture
def patched_config(mocker, fresh_repo):
    from ghchain.config import Config

    cfg = Config(
        base_branch="main",
        remote="origin",
        branch_name_template="hk-{pr_id}",
        log_level="INFO",
    )
    mocker.patch("ghchain.config", cfg)
    return cfg


def _make_stack(repo: Repo, n: int):
    """Add `n` commits to the current branch with distinct messages."""
    for i in range(n):
        Path("README.md").open("a").write(f"line {i}\n")
        repo.index.add(["README.md"])
        repo.index.commit(f"commit {i}\n\nbody for commit {i}.")


@pytest.fixture
def mock_gh(mocker):
    """Mock every gh-touching helper. Returns a dict of MagicMock handles
    so tests can override per-case behavior.

    The default behavior:
      - get_next_gh_id returns 100, then 101, ... on each call.
      - get_open_prs returns [] (no existing PRs).
      - get_pr_head_branch returns None (PR doesn't exist).
      - update_pr_descriptions is a no-op.
      - PR.create_pull_request returns a PR object whose pr_id matches
        the requested head_branch's id suffix (so the prediction is
        always correct).
      - ghchain.repo.git.push is allowed to fail silently (no real remote).
    """
    pr_id_counter = count(100)

    def fake_next_gh_id():
        return next(pr_id_counter)

    mocker.patch("ghchain.stack.get_next_gh_id", side_effect=fake_next_gh_id)
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=[])
    mocker.patch("ghchain.stack.get_open_prs", return_value=[], create=True)
    head_branch_mock = mocker.patch(
        "ghchain.stack.get_pr_head_branch", return_value=None
    )
    update_pr_descriptions_mock = mocker.patch("ghchain.stack.update_pr_descriptions")

    # PR.create_pull_request -> PR object with pr_id matching predicted id
    from ghchain.pull_request import PR

    def fake_create_pr(
        base_branch,
        head_branch,
        title,
        body,
        commit_sha,
        draft=False,
        linked_issue=None,
    ):
        # By default, "actual" PR id is the suffix of head_branch (hk-<N>).
        suffix = head_branch.rsplit("-", 1)[-1]
        pr_id = int(suffix) if suffix.isdigit() else 1
        return PR(
            pr_id=pr_id,
            pr_url=f"https://example.com/owner/repo/pull/{pr_id}",
            pr_status=None,
            head_branch=head_branch,
            body=body,
            title=title,
            commits=[commit_sha],
            linked_issue=linked_issue,
        )

    create_pr_mock = mocker.patch.object(
        PR, "create_pull_request", side_effect=fake_create_pr
    )

    # Auto-confirm interactive prompts.
    mocker.patch("ghchain.stack.click.confirm", return_value=True)

    return {
        "create_pr": create_pr_mock,
        "head_branch": head_branch_mock,
        "update_pr_descriptions": update_pr_descriptions_mock,
    }


def _read_message(repo: Repo, sha: str) -> str:
    return repo.git.log("-1", "--format=%B", sha)


def test_fresh_stack_each_commit_gets_trailer(
    fresh_repo, patched_config, mock_gh
):
    """3-commit stack → each commit gains a `PR: #N` trailer matching its branch."""
    _make_stack(fresh_repo, 3)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    # After process_stack, the stack has been refreshed; each commit
    # should have a unique PR trailer and an associated branch.
    refreshed = Stack.create(base_branch="main")
    assert len(refreshed.commits) == 3
    for c in refreshed.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" in msg, f"commit {c.sha[:8]} missing PR trailer: {msg!r}"
        assert c.branch is not None
        # Branch suffix must match the trailer.
        trailer_id = c.pr_trailer
        assert c.branch == f"hk-{trailer_id}"


def test_idempotent_rerun_no_op(fresh_repo, patched_config, mock_gh, mocker):
    """Re-running process_stack on a fully-stamped stack must not amend."""
    _make_stack(fresh_repo, 2)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    # Trust check: pretend the PR for each branch already lives at that branch.
    refreshed = Stack.create(base_branch="main")

    def head_lookup(pr_id):
        for c in refreshed.commits:
            if c.pr_trailer == pr_id:
                return c.branch
        return None

    mocker.patch("ghchain.stack.get_pr_head_branch", side_effect=head_lookup)

    # Simulate the PRs being already open so the create-PR path is skipped.
    from ghchain.pull_request import PR

    open_prs = [
        PR(
            pr_id=c.pr_trailer,
            pr_url=f"https://example.com/owner/repo/pull/{c.pr_trailer}",
            pr_status=None,
            head_branch=c.branch,
            body=c.message,
            title=c.message.split("\n")[0],
            commits=[c.sha],
        )
        for c in refreshed.commits
    ]
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=open_prs)

    shas_before = [c.sha for c in refreshed.commits]
    Stack.create(base_branch="main").process_stack(create_pr=True)
    refreshed_again = Stack.create(base_branch="main")
    shas_after = [c.sha for c in refreshed_again.commits]
    assert shas_before == shas_after, "idempotent re-run must not change SHAs"


def test_prediction_race_repairs_trailer_and_renames_branch(
    fresh_repo, patched_config, mocker
):
    """When the actual PR id differs from prediction, trailer and branch are repaired."""
    from ghchain.pull_request import PR
    from ghchain.stack import Stack

    _make_stack(fresh_repo, 1)

    # Predict 100, but GitHub actually assigns 105 (race).
    mocker.patch("ghchain.stack.get_next_gh_id", return_value=100)
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=[])
    mocker.patch("ghchain.stack.get_open_prs", return_value=[], create=True)
    mocker.patch("ghchain.stack.get_pr_head_branch", return_value=None)
    mocker.patch("ghchain.stack.update_pr_descriptions")

    def fake_create_pr(**kwargs):
        return PR(
            pr_id=105,
            pr_url="https://example.com/owner/repo/pull/105",
            pr_status=None,
            head_branch=kwargs["head_branch"],
            body=kwargs["body"],
            title=kwargs["title"],
            commits=[kwargs["commit_sha"]],
        )

    mocker.patch.object(PR, "create_pull_request", side_effect=fake_create_pr)
    mocker.patch("ghchain.stack.click.confirm", return_value=True)

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    # Branch should have been renamed to hk-105 (and hk-100 deleted locally).
    assert "hk-105" in [b.name for b in fresh_repo.branches]
    assert "hk-100" not in [b.name for b in fresh_repo.branches]

    refreshed = Stack.create(base_branch="main")
    assert refreshed.commits[0].pr_trailer == 105
    assert refreshed.commits[0].branch == "hk-105"


def test_cherry_picked_stale_trailer_is_restamped(
    fresh_repo, patched_config, mock_gh, mocker
):
    """A `PR: #99` trailer from a foreign repo whose PR doesn't exist
    here must be replaced with the locally-predicted PR id."""
    _make_stack(fresh_repo, 1)

    # Inject a stale trailer onto the only commit.
    fresh_repo.git.commit(
        "--amend",
        "--no-edit",
        "--trailer",
        "PR: #99",
    )

    # The stale PR #99 doesn't exist (head_branch lookup → None, default).
    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    # The trailer must have been replaced (predicted starts at 100).
    assert refreshed.commits[0].pr_trailer == 100
    msg = _read_message(fresh_repo, refreshed.commits[0].sha)
    assert "PR: #99" not in msg
    assert "PR: #100" in msg


def test_fixup_commit_does_not_get_own_trailer(
    fresh_repo, patched_config, mock_gh
):
    """Fixup commits are skipped — only the parent owns the trailer."""
    _make_stack(fresh_repo, 1)
    # Add a fixup commit pointing at HEAD.
    Path("README.md").open("a").write("more\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("fixup! commit 0")

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    # Stack has two commits: a non-fixup and a fixup. Only the non-fixup
    # gets a PR trailer.
    non_fixup = [c for c in refreshed.commits if not c.is_fixup]
    fixup = [c for c in refreshed.commits if c.is_fixup]
    assert len(non_fixup) == 1 and len(fixup) == 1
    assert non_fixup[0].pr_trailer is not None
    fixup_msg = _read_message(fresh_repo, fixup[0].sha)
    assert "PR: #" not in fixup_msg


def test_worktree_conflict_aborts_before_amend(
    fresh_repo, patched_config, mock_gh, mocker
):
    """If a per-commit branch is held in another worktree, abort cleanly."""
    _make_stack(fresh_repo, 2)

    # Pre-create the branches matching what process_stack will predict,
    # so the conflict check has something to flag.
    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    # Manually attach branch names to commits so they end up in `stack.branches`.
    stack.commits[0].branch = "hk-100"
    stack.commits[1].branch = "hk-101"
    fresh_repo.create_head("hk-100", stack.commits[0].sha)
    fresh_repo.create_head("hk-101", stack.commits[1].sha)

    # Pretend hk-100 is checked out in another worktree.
    mocker.patch(
        "ghchain.stack.get_branches_in_other_worktrees",
        return_value={"hk-100"},
    )

    import click

    with pytest.raises(click.ClickException) as excinfo:
        stack.process_stack(create_pr=True)
    assert "hk-100" in str(excinfo.value.message)

    # No amend happened: the original messages should not contain a trailer.
    for c in stack.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" not in msg


def test_no_create_pr_skips_trailer(fresh_repo, patched_config, mock_gh):
    """`ghchain` without -p must NOT add trailers — legacy branch-creation only."""
    _make_stack(fresh_repo, 2)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=False)

    refreshed = Stack.create(base_branch="main")
    for c in refreshed.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" not in msg, f"unexpected trailer on commit: {msg!r}"
        assert c.branch is not None  # branches are still created
