# Lost Battlecode replays

GitHub Actions checks the team's Battlecode history every hour and saves
**each individual game we lost**, including losses inside a series we won.
Five-game and larger series are inspected game by game. Wins and draws are skipped.
Both team A and team B are handled.

The workflow also runs manually from **Actions → Download lost-match replays →
Run workflow**. GitHub schedules can be delayed when runners are busy.

## Archive

- `replays/v<version> - <full bot name>/YYYY-MM-DD/M<game-id>.replay`:
  one replay per lost game, grouped by our submission version, full name, and UTC date.
- `replays/index.json`: map, opponent, battle ID, side, ranking mode, path and checksum.
- `replays/state.json`: fully archived series, so later runs only fetch new or unfinished series.

Our submission ID is read from each replay's official header, then matched to
the team's submissions API. This identifies the actual bot that played, including
old queued matches. Names are retained in full; slashes and control characters are
replaced with underscores so they cannot create unintended directories.

Some tournament replays contain the team name instead of a submission ID.
Their losses go in `replays/version unknown - <replay bot name>/YYYY-MM-DD/`.
Their version and submission ID are recorded as `null` in the index; no version
is guessed from upload times.

## Repository files

- `.github/workflows/download-losses.yml`: hourly and manual download jobs, with automatic commits.
- `scripts/download_losses.py`: API access, loss filtering, replay downloads, index, and saved state.
- `scripts/replay_header.py`: reads our bot ID from the replay header for version grouping.
- `tests/test_download_losses.py`: series filtering, both team sides, pending games, redirects, and headers.
- `AGENTS.md`: points contributors to this README for the directory and file structure.

The action commits new files back to `main` with GitHub's built-in token.
It retries transient API errors and incomplete series. Existing replays are not
downloaded again. Partial successful downloads are saved even when a run fails.

The API currently exposes only the **latest 200 series** and does not document
pagination. The initial run archives every available loss; regular runs preserve
them as history rolls out of that window. A warning is emitted when the API list
reaches the limit. Losses already outside that window cannot be discovered here.

## Authentication

The repository uses the Actions secret **`BATTLECODE_API_KEY`**, configured
from the existing team key. Replace it under **Settings → Secrets and variables →
Actions** if the key is rotated. The key is never committed. Authorization is
stripped before following any replay redirect to a signed download URL.

## Local use

Requires Python 3.10 or later, with no third party packages:

```sh
export BATTLECODE_API_KEY='your team key'
python3 scripts/download_losses.py
python3 -m unittest discover -s tests -v
```

Scheduling and token permissions follow the
[GitHub Actions workflow documentation](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).

## Cost

This repository is public. The standard Ubuntu GitHub Actions runner is free
for public repositories. Replays are stored in ordinary Git; this workflow does
not use paid Actions artifacts, Git LFS, or larger runners. The owner's Actions
budget is also $0 with **Stop usage when budget limit is reached** enabled.

See [GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions).
