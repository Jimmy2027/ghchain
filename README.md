# ghchain

ghchain automates the creation of chained pull requests for each commit in your development branch, facilitating a clear and organized review process.
This tool is heavily inspired by [ghstack](https://github.com/ezyang/ghstack) and further details on the concept of stacked pull requests can be found in [this blog post](https://stacking.dev/).

# Features

-   **Automated Branch Creation**: Creates a new branch for each commit on your development branch.
-   **Pull Request Management**: Automatically creates a GitHub pull request for each branch, stacking them sequentially for streamlined review.
-   **Configurable Workflows**: Supports custom GitHub Actions workflows via `.ghchain.toml` for automated testing and checks.
-   **Dynamic Branch Naming**: Configurable branch naming schemes to match your project's conventions.

> [!CAUTION]
> Running `ghchain` with multiple branches containing the same commit may lead to conflicts or errors.

# Configuration

Configure ghchain using a .ghchain.toml file in the root of your repository.
Current configuration options include:

```toml
workflows = []  # List of GitHub Actions workflows to run with the tests flags
base_branch = "origin/main"  # Base branch for the PRs
branch_name_template = "{git_config_author}-{pr_id}"  # Template for naming branches, customizable to include author name and a PR identifier.
delete_branch_after_merge = true  # Whether to delete the branch after the PR is merged
log_file = "path/to/ghchain.log"  # Path to the log file
log_level = "INFO"  # Logging level

```

# Usage

Assuming your development branch mydev has multiple commits you want to create PRs for:

```bash
ghchain process-commits
```

This command creates a new branch for each commit and a corresponding PR on GitHub, stacking each PR onto the branch of the previous commit.

## Advanced Options

-   **\--draft**: Creates each pull request in draft mode.
-   **\--with-tests**: Run the github workflows that are specified in the .ghchain.toml config of the repository.
-   **\--run-tests**: Run the github workflows that are specified in the .ghchain.toml config of the repository for the specified branch. If '.' is passed, the current branch will be used.

## Usage Example

Let's say that you're working on your dev branch `mydev` and you've cleaned up your changes into 4 commits:

```
git log main..mydev

>> commit 64bd042e9d7be39a180bcb7d0a788c23b75682fd (HEAD -> mydev)
>> Author: Hendrik Klug
>> Date:   Sat Apr 13 14:27:25 2042 +0200
>>
>>     commit 3
>>
>> commit 80edccef17a7086b7a90b03bf18a5c763adf741f
>> Author: Hendrik Klug
>> Date:   Sat Apr 13 14:27:25 2042 +0200
>>
>>     commit 2
>>
>> commit b64c30667ad23847e981e4c9bafe8eee3ffb0881
>> Author: Hendrik Klug
>> Date:   Sat Apr 13 14:27:25 2042 +0200
>>
>>     commit 1
>>
>> commit 51d6204578eacb3ee78fd1488e367e37bb20b492
>> Author: Hendrik Klug
>> Date:   Sat Apr 13 14:27:25 2042 +0200
>>
>>     commit 0

```

You would like to make the life of the reviewer easier by creating a pull request for each commit.
Running `ghchain process-commits` will create a new branch for each commit and create a pull request for each of those branches:

```
git log main..mydev

commit 64bd042e9d7be39a180bcb7d0a788c23b75682fd (HEAD -> mydev, origin/hk-136, hk-136)
Author: Hendrik Klug
Date:   Sat Apr 13 14:27:25 2042 +0200

    commit 3

commit 80edccef17a7086b7a90b03bf18a5c763adf741f (origin/hk-135, hk-135)
Author: Hendrik Klug
Date:   Sat Apr 13 14:27:25 2042 +0200

    commit 2

commit b64c30667ad23847e981e4c9bafe8eee3ffb0881 (origin/hk-134, hk-134)
Author: Hendrik Klug
Date:   Sat Apr 13 14:27:25 2042 +0200

    commit 1

commit 51d6204578eacb3ee78fd1488e367e37bb20b492 (origin/hk-133, hk-133)
Author: Hendrik Klug
Date:   Sat Apr 13 14:27:25 2042 +0200

    commit 0

```

> [!NOTE]
> The `with-tests` flag can also be passed to `ghchain process-commits`. If it is passed all workflows defined in the `.ghchain.toml` file will be run for each commit.

The pull requests then look like the following (see [my test repo](https://github.com/HendrikKlug-synthara/mytest/pulls) for reference):
![](static/prs_view.png)

A single pull request, with the `with-tests` flag passed, will look like this:
![](static/pr_view.png)

### Fixing commits

Your reviewer is verry happy with your small pull request, but would like you to fix a small issue in `commit 1`.
You stash your new changes from `mydev` and checkout the branch `hk-134`.
You fix the issue with either `git commit --amend` or `git commit --fixup b64c30667ad23847e981e4c9bafe8eee3ffb0881` and push the changes.

To rebase your whole stack on top of the new commit, you can checkout your `mydev` bracnh and run `ghchain rebase hk-134`.
This will run a `git rebase --update-refs hk-134` and push the changes to the remote, hence updating your pull requests.

### Checking status of stack

`ghchain` provides a `status` command to check the status of the stack:

```console
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Branch                         ┃ PR ID  ┃ Review Decision      ┃ Draft    ┃ Workflow Status                ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ hk-136                         │ 136    │                      │ False    │                                │
│                                │        │                      │          │ workflow_1: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│                                │        │                      │          │ workflow_2: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│ hk-135                         │ 135    │                      │ False    │                                │
│                                │        │                      │          │ workflow_1: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│                                │        │                      │          │ workflow_2: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│ hk-134                         │ 134    │                      │ False    │                                │
│                                │        │                      │          │ workflow_1: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│                                │        │                      │          │ workflow_2: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│ hk-133                         │ 133    │                      │ False    │                                │
│                                │        │                      │          │ workflow_1: ('completed',      │
│                                │        │                      │          │ 'success')                     │
│                                │        │                      │          │ workflow_2: ('completed',      │
│                                │        │                      │          │ 'success')                     │
└────────────────────────────────┴────────┴──────────────────────┴──────────┴────────────────────────────────┘
```

You can also run `ghchain status --live` which refreshes the status every minute.

## Installation

### pip

```bash
pip install git+https://github.com/Jimmy2027/ghchain.git
```

### portage

`ghchain` is available via [Jimmy's overlay](https://github.com/Jimmy2027/overlay/blob/ae539a3c98d3e95fb0cfa8945344ff705c0537a1/dev-python/ghchain/ghchain-9999.ebuild).
Either enable the repo or copy the ebuild to your local overlay.

Then run:

```bash
emerge -av ghchain
```
