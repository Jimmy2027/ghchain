from unittest.mock import patch

import pytest

from ghchain.commit import Commit


@patch("ghchain.commit.get_issue_url")
@patch.object(Commit, "update_notes")
def test_extract_issue_url(mock_update_notes, mock_get_issue_url):
    # Mock the get_issue_url function to return a test URL
    mock_get_issue_url.return_value = "https://github.com/your_repo/issues/123"

    # Test cases
    test_cases = [
        {
            "message": "[tag] Fix bug in code (#123)",
            "expected_issue_id": 123,
        },
        {
            "message": "Implement new feature (#456)",
            "expected_issue_id": 456,
        },
        {"message": "Refactor code without issue id", "expected_issue_id": None},
    ]

    for case in test_cases:
        commit = Commit(sha="dummy_sha", message=case["message"])
        issue_id = commit.extract_issue_id()
        assert issue_id == case["expected_issue_id"]


if __name__ == "__main__":
    pytest.main()
