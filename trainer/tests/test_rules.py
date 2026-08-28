import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from xiangqi_nnue.rules import NativeRulesClient, RulesProtocolError


class RulesTests(unittest.TestCase):
    def make_client(self, directory):
        source = textwrap.dedent(
            """
            import json, sys
            ply = 0
            for line in sys.stdin:
                request = json.loads(line)
                method = request["method"]
                if method == "quit":
                    data = {"quitting": True}
                elif method == "playMove" and request.get("move") != "a0a1":
                    print(json.dumps({"id":request["id"],"ok":False,"error":"illegal"}), flush=True)
                    continue
                else:
                    if method == "newGame": ply = 0
                    if method == "playMove": ply += 1
                    data = {"fen":f"9/9/9/9/9/9/9/9/9/9 {'w' if ply % 2 == 0 else 'b'} - - 0 1","legalMoves":["a0a1"],"result":{"kind":"ongoing","reason":""}}
                print(json.dumps({"id":request["id"],"ok":True,"data":data}), flush=True)
                if method == "quit": break
            """
        )
        script = Path(directory) / "fake_rules.py"
        script.write_text(source, encoding="utf-8")
        return NativeRulesClient([sys.executable, "-u", script], timeout=2)

    def test_request_ids_and_moves(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_client(directory) as client:
                self.assertEqual(client.snapshot()["sideToMove"] if "sideToMove" in client.snapshot() else "red", "red")
                self.assertIn(" b ", client.play_move("a0a1")["fen"])

    def test_engine_error_is_raised(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.make_client(directory) as client:
                with self.assertRaisesRegex(RulesProtocolError, "illegal"):
                    client.play_move("bad")


if __name__ == "__main__":
    unittest.main()
