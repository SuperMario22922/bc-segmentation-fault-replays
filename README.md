# Lost Battlecode replays

The downloader saves
**each individual game we lost**, including losses inside a series we won.
Five-game and larger series are inspected game by game. Wins and draws are skipped.
Both team A and team B are handled.

The workflow runs manually from **Actions → Download lost-match replays →
Run workflow**. The hourly schedule is prepared but disabled until a $0 Actions
budget with **Stop usage when budget limit is reached** has been confirmed.
Then uncomment `schedule` in the workflow. GitHub schedules can be delayed when
runners are busy.

## Archive

- `replays/v<version> - <full bot name>/YYYY-MM-DD/M<game-id>.replay`:
  one replay per lost game, grouped by our submission version, full name, and UTC date.
- `replays/index.json`: map, opponent, battle ID, side, ranking mode, path and checksum.
- `replays/state.json`: fully archived series, so later runs only fetch new or unfinished series.

Our submission ID is read from each replay's official header, then matched to
the team's submissions API. This identifies the actual bot that played, including
old queued matches. Names are retained in full; slashes and control characters are
replaced with underscores so they cannot create unintended directories.

The action commits new files back to `main` with GitHub's built-in token.
It retries transient API errors and incomplete series. Existing replays are not
downloaded again. Partial successful downloads are saved even when a run fails.

The API currently exposes only the **latest 200 series** and does not document
pagination. The initial run archives every available loss; regular runs preserve
them as history rolls out of that window. A warning is emitted when the API list
reaches the limit. Losses already outside that window cannot be discovered here.

## Authentication

The private repository uses the Actions secret **`BATTLECODE_API_KEY`**, configured
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

The action uses the standard Ubuntu runner and stores replays in Git rather than
paid Actions artifacts or Git LFS. Hourly polling is about 720–744 runs a month;
routine runs should usually take about one minute, while the initial historical
download takes longer. This uses the repository owner's shared Actions allowance
(2,000 minutes/month on GitHub Free, 3,000 on Pro). Other repositories also use
that allowance. To guarantee zero paid usage, configure an Actions budget of $0
with **Stop usage when budget limit is reached** in the owner's billing settings.
The schedule alone cannot guarantee zero charges if paid overages are enabled.
