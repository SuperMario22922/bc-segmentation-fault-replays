#!/usr/bin/env python3
"""Archive individual lost games from Battlecode series. No third party packages."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import sys
import time
import urllib.error
import urllib.request
from replay_header import bot_ids


class StripAuthRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is not None:
            redirected.remove_header("Authorization")
        return redirected


class API:
    def __init__(self, key, base="https://game.battlecode.au/api/v1", interval=0.65):
        self.key, self.base, self.interval = key, base, interval
        self.next_request = 0.0
        self.opener = urllib.request.build_opener(StripAuthRedirect())

    def fetch(self, path):
        for attempt in range(4):
            time.sleep(max(0, self.next_request - time.monotonic()))
            self.next_request = time.monotonic() + self.interval
            req = urllib.request.Request(
                f"{self.base}/{path}",
                headers={"Authorization": f"Bearer {self.key}", "User-Agent": "Battlecode-loss-archive/1"},
            )
            try:
                with self.opener.open(req, timeout=90) as response:
                    return response.read()
            except urllib.error.HTTPError as error:
                if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                    raise RuntimeError(f"Request {path} failed (HTTP {error.code})") from None
                retry = error.headers.get("Retry-After", "")
                delay = min(120, int(retry)) if retry.isdigit() else 2 ** (attempt + 1)
                time.sleep(delay)
            except (urllib.error.URLError, TimeoutError, OSError):
                if attempt == 3:
                    raise RuntimeError(f"Request {path} failed (network error)") from None
                time.sleep(2 ** (attempt + 1))

    def get(self, path):
        try:
            return json.loads(self.fetch(path))
        except (ValueError, UnicodeError):
            raise RuntimeError(f"Request {path} returned invalid JSON") from None


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


def archive(api, root):
    root = Path(root)
    index_path, state_path = root / "index.json", root / "state.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {"games": {}}
    state = json.loads(state_path.read_text()) if state_path.exists() else {"completed_battles": []}
    completed = set(state["completed_battles"])
    team_id = api.get("team")["team"]["id"]
    if state.get("team_id", team_id) != team_id:
        raise RuntimeError("The API key belongs to a different team than this archive")
    state["team_id"] = team_id
    battles = api.get("battles?limit=200")
    submissions = {str(s["id"]): s for s in api.get("submissions")}
    if len(battles) == 200:
        print("Warning: the API exposes at most 200 recent series; older unarchived history may be unavailable.")
    count, errors = 0, []
    for battle in reversed(battles):
        battle_id = battle["id"]
        if battle_id in completed:
            continue
        try:
            detail = api.get(f"battles/{battle_id}")
            match = detail["match"]
            if match["teamAId"] == team_id:
                side, opponent = "a", detail["teamBName"]
            elif match["teamBId"] == team_id:
                side, opponent = "b", detail["teamAName"]
            else:
                raise RuntimeError(f"Battle {battle_id} does not belong to this team")
            all_done = bool(detail["games"])
            for game in detail["games"]:
                # A won series can contain losses; never filter by series outcome.
                if game["status"] != "completed":
                    all_done = False
                    continue
                winner = (game.get("winner") or "").lower()
                if winner not in ("a", "b") or winner == side:
                    continue
                if not game["hasReplay"]:
                    all_done = False
                    continue
                game_id = game["id"]
                date = (battle.get("at") or match["requestedAt"])[:10]
                existing = index["games"].get(str(game_id))
                target = root / existing["path"] if existing else root / ".missing"
                if not target.exists() or target.stat().st_size == 0:
                    payload = api.fetch(f"battles/{game_id}/replay")
                    if not payload or payload.lstrip().startswith((b"<", b"{")):
                        raise RuntimeError(f"Game {game_id} returned an empty or invalid replay")
                    try:
                        played_id = bot_ids(payload)[0 if side == "a" else 1]
                    except (ValueError, IndexError, KeyError, struct.error, OSError):
                        raise RuntimeError(f"Cannot read the replay header for game {game_id}") from None
                    if played_id not in submissions and played_id.isdecimal():
                        try:
                            submissions[played_id] = api.get(f"submissions/{played_id}")
                        except RuntimeError:
                            pass
                    submission = submissions.get(played_id)
                    if submission is None:
                        # Tournament exports can use a team name, not a submission ID.
                        # Archive the loss without inventing its bot version.
                        submission = {"id": None, "version": None,
                                      "name": played_id or "unidentified bot"}
                        print(f"M{game_id}: submission version unavailable in replay/API", flush=True)
                    # Preserve the full name, replacing only filesystem separators.
                    name = re.sub(r'[/\\\x00-\x1f]', '_', submission["name"])
                    version = f"v{submission['version']}" if submission["version"] is not None else "version unknown"
                    folder = f"{version} - {name}"
                    relative = Path(folder) / date / f"M{game_id}.replay"
                    target = root / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    temporary = target.with_suffix(".replay.tmp")
                    temporary.write_bytes(payload)
                    temporary.replace(target)
                    count += 1
                    print(f"Downloaded M{game_id}: {game['mapName']} vs {opponent}", flush=True)
                else:
                    relative = Path(existing["path"])
                    played_id = existing.get("replay_bot_id", str(existing["submission_id"]))
                    submission = submissions.get(str(existing["submission_id"]), {
                        "id": existing["submission_id"], "version": existing["version"],
                        "name": existing["bot_name"],
                    })
                index["games"][str(game_id)] = {
                    "battle_id": battle_id, "map": game["mapName"], "opponent": opponent,
                    "our_side": side, "ranked": match["ranked"], "date": date,
                    "path": relative.as_posix(), "bytes": target.stat().st_size,
                    "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
                    "submission_id": submission["id"], "version": submission["version"],
                    "bot_name": submission["name"],
                    "replay_bot_id": played_id,
                }
            if all_done:
                completed.add(battle_id)
        except (RuntimeError, KeyError, TypeError, ValueError) as error:
            errors.append(battle_id)
            print(f"Battle {battle_id}: {error}", file=sys.stderr, flush=True)
        finally:
            state["completed_battles"] = sorted(completed)
            write_json(index_path, index)
            write_json(state_path, state)
    print(f"Downloaded {count} new lost-game replays; {len(index['games'])} archived in total.")
    if errors:
        raise RuntimeError(f"Could not fully archive {len(errors)} series; the next run will retry them")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("replays"))
    args = parser.parse_args()
    key = os.environ.get("BATTLECODE_API_KEY", "").strip()
    if not key:
        parser.error("Set the BATTLECODE_API_KEY environment variable or repository secret")
    try:
        archive(API(key), args.output)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
