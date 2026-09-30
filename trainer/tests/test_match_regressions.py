"""Regression coverage for match scheduling, adjudication and process ownership."""

import json
import math
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from xiangqi_nnue import match


class MatchRegressionTests(unittest.TestCase):
    def record(self, **changes):
        fields = dict(game_id=0, opening=match.Opening(match.INITIAL_FEN, ()),
                      nodes=10, engine_red="candidate", engine_black="opponent",
                      result="red_win")
        fields.update(changes)
        return match.GameRecord(**fields)

    def test_large_match_statistics_remain_finite_and_scale(self):
        for counts in ((7000, 2000, 1000), (1000, 2000, 7000), (0, 10000, 0)):
            with self.subTest(counts=counts):
                value = match.sprt_llr(*counts)
                self.assertTrue(math.isfinite(value))
                self.assertAlmostEqual(value, 1000 * match.sprt_llr(
                    *(count // 1000 for count in counts)))
        self.assertGreater(match.sprt_llr(7000, 2000, 1000), 0)

    def test_summary_rejects_missing_ambiguous_and_unfinished_candidates(self):
        for record, candidate in (
            (self.record(), "absent"),
            (self.record(engine_black="candidate"), "candidate"),
            (self.record(result="ongoing"), "candidate"),
            (self.record(result="unknown"), "candidate"),
        ):
            with self.subTest(record=record, candidate=candidate):
                with self.assertRaises(ValueError):
                    match.summarize_records([record], candidate)

    def test_candidate_wins_after_color_reversal(self):
        records = [self.record(), self.record(engine_red="opponent",
                   engine_black="candidate", result="black_win")]
        self.assertEqual(match.summarize_records(records, "candidate")["wins"], 2)

    def test_last_allowed_move_preserves_referee_win(self):
        for kind, reason in (("red_win", "checkmate"), ("black_win", "stalemate"),
                             ("draw", "natural_limit"), ("ongoing", "")):
            with self.subTest(kind=kind):
                rules = Mock()
                rules.snapshot.side_effect = [
                    {"result": {"kind": "ongoing", "reason": ""},
                     "sideToMove": "red", "fen": match.INITIAL_FEN},
                    {"result": {"kind": kind, "reason": reason}},
                ]
                red, black = Mock(), Mock()
                red.name, black.name = "candidate", "opponent"
                red.search.return_value = match.SearchResult(move="a0a1")
                record = match.play_game(rules, {"red": red, "black": black},
                    match.Opening(match.INITIAL_FEN, ()), nodes=10, max_plies=1, game_id=0)
                self.assertEqual(record.result, "draw" if kind == "ongoing" else kind)
                self.assertEqual(record.reason, "max_plies" if kind == "ongoing" else reason)

    def test_custom_opening_is_loaded_before_random_moves(self):
        rules = Mock()
        rules.snapshot.return_value = {"result": {"kind": "ongoing"},
                                       "legalMoves": ["a0a1"], "fen": "after-move"}
        openings = match.generate_openings(rules, seed=1, count=1, plies=1,
                                          initial_fen="custom-fen")
        rules.load_fen.assert_called_once_with("custom-fen")
        self.assertLess(rules.mock_calls.index(unittest.mock.call.load_fen("custom-fen")),
                        rules.mock_calls.index(unittest.mock.call.snapshot()))
        self.assertEqual(openings[0].fen, "after-move")

    def test_every_opening_is_paired_with_reversed_colors_in_archives(self):
        for games in (1, 4, 5):
            with self.subTest(games=games), tempfile.TemporaryDirectory() as directory:
                red, black = Mock(), Mock()
                red.name, black.name = "candidate", "opponent"
                openings = [match.Opening(f"fen-{i}", ()) for i in range((games + 1) // 2)]

                def play(rules, engines, opening, **options):
                    return self.record(game_id=options["game_id"], opening=opening,
                        engine_red=engines["red"].name, engine_black=engines["black"].name,
                        result="draw")

                with patch.object(match, "NativeRulesClient"), \
                     patch.object(match, "generate_openings", return_value=openings) as generate, \
                     patch.object(match, "play_game", side_effect=play):
                    summary = match.run_match(rules_command="rules", engines={"red": red, "black": black},
                        seed=42, games=games, opening_plies=4, nodes=10, max_plies=2,
                        out_dir=directory, candidate="candidate")
                self.assertEqual(generate.call_args.kwargs["count"], (games + 1) // 2)
                records = [json.loads(line) for line in
                           (Path(directory) / "games.jsonl").read_text().splitlines()]
                self.assertEqual(summary["games"], games)
                for i, record in enumerate(records):
                    self.assertEqual(record["opening_fen"], openings[i // 2].fen)
                    self.assertEqual(record["engine_red"], "candidate" if i % 2 == 0 else "opponent")
                    self.assertTrue((Path(directory) / f"game-{i:04d}.pgn").is_file())

    def test_invalid_candidate_fails_before_referee_or_output_creation(self):
        red, black = Mock(), Mock()
        red.name, black.name = "candidate", "opponent"
        with tempfile.TemporaryDirectory() as directory, patch.object(match, "NativeRulesClient") as rules:
            output = Path(directory) / "not-created"
            with self.assertRaises(ValueError):
                match.run_match(rules_command="rules", engines={"red": red, "black": black},
                    seed=1, games=2, opening_plies=0, nodes=10, max_plies=2,
                    out_dir=output, candidate="typo")
            rules.assert_not_called()
            self.assertFalse(output.exists())


class MatchCliTests(unittest.TestCase):
    def argv(self, *extra):
        return ["match", "--engine", "engine.exe", "--rules-engine", "rules.exe",
                "--out-dir", "unused", *extra]

    def test_default_names_distinguish_mirror_players(self):
        def engine(*args, **kwargs):
            result = Mock()
            result.name = kwargs["name"]
            return result
        with patch("sys.argv", self.argv()), patch.object(match, "UciEngine", side_effect=engine), \
             patch.object(match, "run_match", return_value={}) as run, patch("builtins.print"):
            match.main()
        options = run.call_args.kwargs
        self.assertEqual(options["candidate"], "engine-1")
        self.assertEqual(options["engines"]["black"].name, "engine-2")
        for player in options["engines"].values():
            player.close.assert_called_once_with()

    def test_failed_second_launch_closes_first_player(self):
        first = Mock()
        with patch("sys.argv", self.argv()), \
             patch.object(match, "UciEngine", side_effect=[first, RuntimeError("launch failed")]):
            with self.assertRaisesRegex(RuntimeError, "launch failed"):
                match.main()
        first.close.assert_called_once_with()

    def test_bad_arguments_do_not_launch_engines(self):
        for extra in (("--candidate", "typo"), ("--games", "0"),
                      ("--engine-name", "a", "--engine-name", "b", "--engine-name", "c")):
            with self.subTest(extra=extra), patch("sys.argv", self.argv(*extra)), \
                 patch.object(match, "UciEngine") as engine, patch("sys.stderr"):
                with self.assertRaises(SystemExit):
                    match.main()
                engine.assert_not_called()


if __name__ == "__main__":
    unittest.main()
