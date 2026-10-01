import gzip
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from download_losses import API, archive
from replay_header import bot_ids


def replay(a="101", b="202"):
    # Single-segment Replay struct: two data words and five pointer fields.
    words = [2 << 32 | 5 << 48, 2, 0, 0, 0, 0, 0, 0]
    tail = bytearray()
    for field, text in [(4, a), (5, b)]:
        raw = text.encode() + b"\0"
        destination = 8 + len(tail) // 8
        words[field] = 1 | (destination - field - 1) << 2 | 2 << 32 | len(raw) << 35
        tail.extend(raw + bytes((-len(raw)) % 8))
    raw = struct.pack("<II", 0, len(words) + len(tail) // 8)
    raw += struct.pack(f"<{len(words)}Q", *words) + tail
    packed = bytearray()
    for pos in range(0, len(raw), 8):
        word = raw[pos:pos + 8]
        tag = sum(1 << i for i, byte in enumerate(word) if byte)
        packed.append(tag)
        packed.extend(byte for byte in word if byte)
        if tag in (0, 255):
            packed.append(0)
    return bytes(packed)


class FakeAPI:
    def __init__(self, side):
        self.side = side
        self.downloads = []
        self.pending = False

    def get(self, path):
        if path == "team": return {"team": {"id": 1000}}
        if path == "submissions": return [{"id": 101, "version": 7, "name": "Full bot name / trial"}]
        if path == "battles?limit=200": return [{"id": 10, "at": "2026-10-01T12:00:00Z", "outcome": "win"}]
        return {
            "match": {"teamAId": 1000 if self.side == "a" else 9,
                      "teamBId": 1000 if self.side == "b" else 9, "ranked": True,
                      "requestedAt": "2026-10-01T12:00:00Z"},
            "teamAName": "ours" if self.side == "a" else "opponent",
            "teamBName": "ours" if self.side == "b" else "opponent",
            "games": [{"id": i, "status": "running" if self.pending and i == 14 else "completed",
                       "winner": self.side if i in (10, 11, 12) else ("b" if self.side == "a" else "a"),
                       "hasReplay": True, "mapName": "Autarky"} for i in range(10, 15)],
        }

    def fetch(self, path):
        self.downloads.append(path)
        return replay("101", "202") if self.side == "a" else replay("202", "101")


class Tests(unittest.TestCase):
    def test_header_and_gzip(self):
        self.assertEqual(bot_ids(replay()), ("101", "202"))
        self.assertEqual(bot_ids(gzip.compress(replay())), ("101", "202"))

    def test_individual_losses_in_won_five_game_series_both_sides(self):
        for side in ("a", "b"):
            with self.subTest(side=side), tempfile.TemporaryDirectory() as directory:
                api = FakeAPI(side)
                self.assertEqual(archive(api, directory), 2)
                self.assertEqual(api.downloads, ["battles/13/replay", "battles/14/replay"])
                folder = Path(directory) / "v7 - Full bot name _ trial" / "2026-10-01"
                self.assertTrue((folder / "M13.replay").exists())
                self.assertEqual(archive(api, directory), 0)
                self.assertEqual(len(api.downloads), 2)
                index = json.loads((Path(directory) / "index.json").read_text())
                self.assertEqual(index["games"]["13"]["bot_name"], "Full bot name / trial")

    def test_pending_game_retried_without_redownloading_other_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            api = FakeAPI("a")
            api.pending = True
            self.assertEqual(archive(api, directory), 1)
            api.pending = False
            self.assertEqual(archive(api, directory), 1)
            self.assertEqual(api.downloads, ["battles/13/replay", "battles/14/replay"])

    def test_draw_not_downloaded(self):
        api = FakeAPI("a")
        original = api.get
        def get(path):
            result = original(path)
            if path == "battles/10":
                for game in result["games"]: game["winner"] = None
            return result
        api.get = get
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(archive(api, directory), 0)
            self.assertEqual(api.downloads, [])

    def test_tournament_team_name_archived_without_guessing_version(self):
        api = FakeAPI("b")
        api.fetch = lambda path: replay("", "segmentation fault")
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(archive(api, directory), 2)
            folder = Path(directory) / "version unknown - segmentation fault" / "2026-10-01"
            self.assertTrue((folder / "M13.replay").exists())
            index = json.loads((Path(directory) / "index.json").read_text())
            self.assertIsNone(index["games"]["13"]["version"])
            self.assertEqual(index["games"]["13"]["replay_bot_id"], "segmentation fault")
            self.assertEqual(archive(api, directory), 0)

    def test_redirect_does_not_forward_authorization(self):
        received = []
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                received.append((self.path, self.headers.get("Authorization")))
                if self.path != "/signed":
                    self.send_response(302)
                    self.send_header("Location", "/signed")
                else:
                    self.send_response(200)
                self.end_headers()
                if self.path == "/signed": self.wfile.write(b"replay")
            def log_message(self, *args): pass
        server = HTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            api = API("test-key", base=f"http://127.0.0.1:{server.server_port}", interval=0)
            self.assertEqual(api.fetch("replay"), b"replay")
            self.assertEqual(received, [("/replay", "Bearer test-key"), ("/signed", None)])
        finally:
            server.shutdown()
            server.server_close()
            thread.join()
