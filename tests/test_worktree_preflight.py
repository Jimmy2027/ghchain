"""Tests for ghchain.git_utils.get_branches_in_other_worktrees()."""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from ghchain.git_utils import get_branches_in_other_worktrees


def _mock_proc(stdout: str):
    proc = MagicMock()
    proc.stdout = stdout
    proc.returncode = 0
    return proc


def test_no_other_worktrees(tmp_path):
    main = tmp_path / "main"
    main.mkdir()
    porcelain = f"worktree {main}\nHEAD aaaaaaa\nbranch refs/heads/main\n\n"
    toplevel = _mock_proc(f"{main}\n")
    wt_list = _mock_proc(porcelain)

    with patch("ghchain.git_utils.run_command", side_effect=[wt_list, toplevel]):
        assert get_branches_in_other_worktrees() == set()


def test_one_other_worktree(tmp_path):
    main = tmp_path / "main"
    other = tmp_path / "feature"
    main.mkdir()
    other.mkdir()
    porcelain = (
        f"worktree {main}\nHEAD aaaaaaa\nbranch refs/heads/main\n\n"
        f"worktree {other}\nHEAD bbbbbbb\nbranch refs/heads/hk-42\n\n"
    )
    toplevel = _mock_proc(f"{main}\n")
    wt_list = _mock_proc(porcelain)

    with patch("ghchain.git_utils.run_command", side_effect=[wt_list, toplevel]):
        assert get_branches_in_other_worktrees() == {"hk-42"}


def test_detached_worktree_ignored(tmp_path):
    main = tmp_path / "main"
    detached = tmp_path / "detached"
    main.mkdir()
    detached.mkdir()
    porcelain = (
        f"worktree {main}\nHEAD aaaaaaa\nbranch refs/heads/main\n\n"
        f"worktree {detached}\nHEAD ccccccc\ndetached\n\n"
    )
    toplevel = _mock_proc(f"{main}\n")
    wt_list = _mock_proc(porcelain)

    with patch("ghchain.git_utils.run_command", side_effect=[wt_list, toplevel]):
        # detached worktrees don't pin a branch, so they don't conflict
        assert get_branches_in_other_worktrees() == set()


def test_multiple_other_worktrees(tmp_path):
    main = tmp_path / "main"
    a = tmp_path / "a"
    b = tmp_path / "b"
    for p in (main, a, b):
        p.mkdir()

    porcelain = (
        f"worktree {main}\nHEAD aaaaaaa\nbranch refs/heads/dev\n\n"
        f"worktree {a}\nHEAD bbbbbbb\nbranch refs/heads/hk-1\n\n"
        f"worktree {b}\nHEAD ccccccc\nbranch refs/heads/hk-2\n\n"
    )
    toplevel = _mock_proc(f"{main}\n")
    wt_list = _mock_proc(porcelain)

    with patch("ghchain.git_utils.run_command", side_effect=[wt_list, toplevel]):
        assert get_branches_in_other_worktrees() == {"hk-1", "hk-2"}
