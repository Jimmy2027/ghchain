"""Integration tests for Stack.process_stack / process_commit with the
PR-ref placement flow.

Without a ticket in the title, the commit's title gains a trailing
``(#N)`` ref (GitHub squash-merge style). When the title already links
a ticket, the commit instead gets a ``PR: #N`` trailer.

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
    # Issue-URL construction reads the (bogus) origin remote and would
    # then drive the `gh issue develop` branch-creation flow, which has
    # no remote. Stub it out so tests that use ticketed titles still
    # exercise the trailer-mode placement decision without triggering
    # the linked-issue branch path.
    mocker.patch("ghchain.commit.get_issue_url", return_value=None)
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


def test_fresh_stack_each_commit_gets_pr_ref_in_title(
    fresh_repo, patched_config, mock_gh
):
    """3-commit stack → each commit gains a trailing ` (#N)` in its title.

    None of the seed commits link a ticket in the title, so they all
    end up in title-mode. No ``PR:`` trailer should be added.
    """
    _make_stack(fresh_repo, 3)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    assert len(refreshed.commits) == 3
    for c in refreshed.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" not in msg, (
            f"commit {c.sha[:8]} unexpectedly has PR trailer: {msg!r}"
        )
        assert c.title_pr_ref is not None, (
            f"commit {c.sha[:8]} missing title PR ref: {msg!r}"
        )
        assert c.branch is not None
        # Branch suffix must match the inline title ref.
        assert c.branch == f"hk-{c.title_pr_ref}"


def test_fresh_stack_with_ticket_in_title_gets_trailer(
    fresh_repo, patched_config, mock_gh
):
    """A commit whose title already links a ticket gets a ``PR:`` trailer
    (current trailer-mode behavior). The title is left untouched.
    """
    from pathlib import Path

    Path("README.md").open("a").write("ticketed change\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("fix login bug (#42)\n\nbody")

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    assert len(refreshed.commits) == 1
    c = refreshed.commits[0]
    msg = _read_message(fresh_repo, c.sha)
    # Title-mode ref must NOT be appended when a ticket is already linked.
    assert c.title == "fix login bug (#42)"
    assert c.pr_trailer is not None, f"missing trailer in {msg!r}"
    assert c.branch == f"hk-{c.pr_trailer}"


def test_idempotent_rerun_no_op(fresh_repo, patched_config, mock_gh, mocker):
    """Re-running process_stack on a fully-stamped stack must not amend.

    The seed commits have no ticket, so they land in title-mode. The
    second run exercises the title-ref trust check: each commit's
    ``title_pr_ref`` is validated by ``get_pr_head_branch`` returning
    the matching local branch.
    """
    _make_stack(fresh_repo, 2)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    stack.process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")

    # Trust check: pretend the PR named by each title ref already lives
    # at that commit's branch.
    def head_lookup(pr_id):
        for c in refreshed.commits:
            if c.title_pr_ref == pr_id:
                return c.branch
        return None

    mocker.patch("ghchain.stack.get_pr_head_branch", side_effect=head_lookup)

    shas_before = [c.sha for c in refreshed.commits]
    Stack.create(base_branch="main").process_stack(create_pr=True)
    refreshed_again = Stack.create(base_branch="main")
    shas_after = [c.sha for c in refreshed_again.commits]
    assert shas_before == shas_after, "idempotent re-run must not change SHAs"


def _setup_race_mocks(mocker, predicted: int, actual: int):
    """Common race-condition mocks: predicted PR id but actual differs."""
    from ghchain.pull_request import PR

    mocker.patch("ghchain.stack.get_next_gh_id", return_value=predicted)
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=[])
    mocker.patch("ghchain.stack.get_open_prs", return_value=[], create=True)
    mocker.patch("ghchain.stack.get_pr_head_branch", return_value=None)
    mocker.patch("ghchain.stack.update_pr_descriptions")
    mocker.patch("ghchain.commit.get_issue_url", return_value=None)

    def fake_create_pr(**kwargs):
        return PR(
            pr_id=actual,
            pr_url=f"https://example.com/owner/repo/pull/{actual}",
            pr_status=None,
            head_branch=kwargs["head_branch"],
            body=kwargs["body"],
            title=kwargs["title"],
            commits=[kwargs["commit_sha"]],
        )

    mocker.patch.object(PR, "create_pull_request", side_effect=fake_create_pr)
    mocker.patch("ghchain.stack.click.confirm", return_value=True)


def test_prediction_race_title_mode_repairs_title_and_renames_branch(
    fresh_repo, patched_config, mocker
):
    """Title-mode race: the title's ``(#predicted)`` is rewritten to
    ``(#actual)`` and the branch is renamed."""
    from ghchain.stack import Stack

    _make_stack(fresh_repo, 1)  # no ticket in title → title-mode
    _setup_race_mocks(mocker, predicted=100, actual=105)

    Stack.create(base_branch="main").process_stack(create_pr=True)

    assert "hk-105" in [b.name for b in fresh_repo.branches]
    assert "hk-100" not in [b.name for b in fresh_repo.branches]

    refreshed = Stack.create(base_branch="main")
    c = refreshed.commits[0]
    msg = _read_message(fresh_repo, c.sha)
    assert c.title_pr_ref == 105
    assert "PR: #" not in msg, f"title-mode commit should not carry trailer: {msg!r}"
    assert "(#100)" not in c.title
    assert c.branch == "hk-105"


def test_prediction_race_trailer_mode_repairs_trailer_and_renames_branch(
    fresh_repo, patched_config, mocker
):
    """Trailer-mode race: the ``PR:`` trailer is rewritten and the branch
    is renamed. The title's ticket reference is left untouched."""
    from pathlib import Path

    Path("README.md").open("a").write("ticketed\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("fix login bug (#42)\n\nbody")

    _setup_race_mocks(mocker, predicted=100, actual=105)

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=True)

    assert "hk-105" in [b.name for b in fresh_repo.branches]
    assert "hk-100" not in [b.name for b in fresh_repo.branches]

    refreshed = Stack.create(base_branch="main")
    c = refreshed.commits[0]
    assert c.pr_trailer == 105
    assert c.title == "fix login bug (#42)"
    assert c.branch == "hk-105"


def test_cherry_picked_stale_trailer_is_replaced_with_title_ref(
    fresh_repo, patched_config, mock_gh, mocker
):
    """A stale ``PR: #99`` trailer from a foreign repo whose PR doesn't
    exist here is cleaned up. Because the title has no ticket, the
    locally-predicted PR id lands in title-mode and the stale trailer
    is dropped."""
    _make_stack(fresh_repo, 1)

    fresh_repo.git.commit(
        "--amend",
        "--no-edit",
        "--trailer",
        "PR: #99",
    )

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    c = refreshed.commits[0]
    msg = _read_message(fresh_repo, c.sha)
    assert "PR: #99" not in msg
    assert "PR: #" not in msg, f"stale trailer should be stripped: {msg!r}"
    assert c.title_pr_ref == 100
    assert c.branch == "hk-100"


def test_cherry_picked_stale_trailer_kept_when_ticket_in_title(
    fresh_repo, patched_config, mock_gh, mocker
):
    """If the title has a ticket, the commit is in trailer-mode and the
    stale ``PR: #99`` trailer is replaced with the correct ``PR: #N``."""
    from pathlib import Path

    Path("README.md").open("a").write("ticketed stale\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("fix login bug (#42)\n\nbody")

    fresh_repo.git.commit(
        "--amend",
        "--no-edit",
        "--trailer",
        "PR: #99",
    )

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    c = refreshed.commits[0]
    msg = _read_message(fresh_repo, c.sha)
    assert "PR: #99" not in msg
    assert c.pr_trailer == 100
    assert c.title == "fix login bug (#42)"


def test_fixup_commit_does_not_get_own_pr_ref(
    fresh_repo, patched_config, mock_gh
):
    """Fixup commits are skipped — only the parent owns the PR ref.

    With the default no-ticket seed, the parent ends up in title-mode.
    The fixup commit must have neither a title PR ref nor a trailer.
    """
    _make_stack(fresh_repo, 1)
    Path("README.md").open("a").write("more\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("fixup! commit 0")

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=True)

    refreshed = Stack.create(base_branch="main")
    non_fixup = [c for c in refreshed.commits if not c.is_fixup]
    fixup = [c for c in refreshed.commits if c.is_fixup]
    assert len(non_fixup) == 1 and len(fixup) == 1
    assert non_fixup[0].title_pr_ref is not None
    fixup_msg = _read_message(fresh_repo, fixup[0].sha)
    assert "PR: #" not in fixup_msg
    assert fixup[0].title_pr_ref is None


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

    # No amend happened: messages should carry neither marker.
    for c in stack.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" not in msg
        assert c.title_pr_ref is None


def test_stack_create_falls_back_to_branch_when_sha_mismatch(
    fresh_repo, patched_config, mocker
):
    """When the local commit's SHA differs from the PR's tip SHA (e.g.
    because the commit was amended since the PR was opened), the
    PR is still associated to the commit via the head_branch fallback.

    Regression test for an ``AttributeError: 'NoneType' object has no
    attribute 'pr_id'`` crash where Step 7 tried to recreate the PR and
    ``gh pr create`` rightfully refused with "already exists".
    """
    from pathlib import Path

    Path("README.md").open("a").write("local change\n")
    fresh_repo.index.add(["README.md"])
    fresh_repo.index.commit("local commit\n\nbody.")

    # Pretend a per-commit branch was created for the (now-amended) commit.
    local_sha = fresh_repo.head.commit.hexsha
    fresh_repo.create_head("hk-2874", local_sha)

    # The "remote" PR points at a SHA that doesn't match local.
    from ghchain.pull_request import PR

    stale_sha = "0" * 40
    pr = PR(
        pr_id=2874,
        pr_url="https://example.com/owner/repo/pull/2874",
        pr_status=None,
        head_branch="hk-2874",
        body="body",
        title="local commit",
        commits=[stale_sha],
    )
    mocker.patch("ghchain.pull_request.get_open_prs", return_value=[pr])
    mocker.patch("ghchain.stack.get_open_prs", return_value=[pr], create=True)

    from ghchain.stack import Stack

    stack = Stack.create(base_branch="main")
    assert len(stack.commits) == 1
    assert stack.commits[0].pull_request is not None, (
        "branch-fallback lookup should have matched the existing PR"
    )
    assert stack.commits[0].pull_request.pr_id == 2874


def test_no_create_pr_skips_pr_ref(fresh_repo, patched_config, mock_gh):
    """`ghchain` without -p must NOT add a PR ref in either form — legacy
    branch-creation only."""
    _make_stack(fresh_repo, 2)

    from ghchain.stack import Stack

    Stack.create(base_branch="main").process_stack(create_pr=False)

    refreshed = Stack.create(base_branch="main")
    for c in refreshed.commits:
        msg = _read_message(fresh_repo, c.sha)
        assert "PR: #" not in msg, f"unexpected trailer on commit: {msg!r}"
        assert c.title_pr_ref is None, (
            f"unexpected title PR ref on commit: {msg!r}"
        )
        assert c.branch is not None  # branches are still created
