# tests/test_benchmark.py
"""Benchmark plumbing uses simulated clocks, never performance measurements."""

import csv
import io
import json
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from benchmarks import recipe_matching as benchmark
from genius_kitchen.models import Recipe
from genius_kitchen.recipes import match_recipes


def small_inputs():
    return [
        {
            "name": "small",
            "pantry": ["egg", "rice"],
            "recipes": [
                {"name": "Complete", "ingredients": ["egg"], "instructions": ["Cook"]},
                {"name": "Partial", "ingredients": ["rice", "onion"], "instructions": ["Cook"]},
            ],
        }
    ]


def worker_result(values, calls_per_batch):
    return {
        "cases": [
            {
                "name": "small",
                "recipe_count": 2,
                "input_sha256": "same-input",
                "expected_result_sha256": "same-result",
                "per_call_ms": values,
                "calls_per_batch": calls_per_batch,
            }
        ]
    }


class BenchmarkInputTests(unittest.TestCase):
    def test_seeded_inputs_are_reproducible_nested_and_shuffled(self):
        with patch.object(benchmark, "SIZES", (5, 12, 25)):
            first = benchmark.build_inputs(seed=100)
            repeated = benchmark.build_inputs(seed=100)
            different = benchmark.build_inputs(seed=101)
        self.assertEqual(first, repeated)
        self.assertNotEqual(benchmark.fingerprint(first), benchmark.fingerprint(different))
        synthetic = first[1:]
        self.assertEqual([len(case["recipes"]) for case in synthetic], [5, 12, 25])
        self.assertEqual(synthetic[0]["recipes"], synthetic[2]["recipes"][:5])
        self.assertEqual(synthetic[1]["recipes"], synthetic[2]["recipes"][:12])
        self.assertEqual(synthetic[0]["pantry"], synthetic[2]["pantry"])
        names = [row["name"] for row in synthetic[2]["recipes"]]
        self.assertNotEqual(names, sorted(names))
        for raw in first:
            benchmark.parse_case(raw)

    def test_oracle_orders_fractional_scores_and_detects_wrong_results(self):
        case = benchmark.Case(
            "oracle",
            {" EGG ", "rice"},
            (
                Recipe("Zulu", ("egg", "onion"), ("Cook",)),
                Recipe("More missing", ("egg", "rice", "onion", "carrot"), ("Cook",)),
                Recipe("Alpha", ("rice", "carrot"), ("Cook",)),
                Recipe("Complete", ("rice",), ("Cook",)),
            ),
        )
        expected = benchmark.reference_signature(case)
        self.assertEqual(
            expected,
            [
                ("Complete", ("rice",), (), 1.0),
                ("Alpha", ("rice",), ("carrot",), 0.5),
                ("Zulu", ("egg",), ("onion",), 0.5),
                ("More missing", ("egg", "rice"), ("onion", "carrot"), 0.5),
            ],
        )
        # Ingredient presence statistics must use the same identity normalization.
        description = benchmark.describe_case({"name": "oracle"}, case, expected)
        self.assertEqual(description["mean_recipe_overlap"], 0.625)
        benchmark.validate_result(case, expected)
        wrong_order = tuple(reversed(match_recipes(case.pantry, case.recipes)))
        with patch.object(benchmark, "match_recipes", return_value=wrong_order):
            with self.assertRaisesRegex(RuntimeError, "reference result: oracle"):
                benchmark.validate_result(case, expected)

    def test_benchmark_rejects_inputs_that_violate_oracle_assumptions(self):
        valid = small_inputs()[0]
        first = valid["recipes"][0]
        invalid_recipes = (
            [first, first],
            [{**first, "ingredients": []}],
            [{**first, "ingredients": ["egg", "EGG"]}],
        )
        for recipes in invalid_recipes:
            with self.subTest(recipes=recipes), self.assertRaises(ValueError):
                benchmark.parse_case({**valid, "recipes": recipes})


class BenchmarkMeasurementLogicTests(unittest.TestCase):
    def setUp(self):
        self.case = benchmark.parse_case(small_inputs()[0])

    def test_timed_batch_invokes_exact_number_of_calls_and_returns_nanoseconds(self):
        clock = Mock(side_effect=[10_000, 10_700])
        with patch.object(benchmark, "match_recipes", return_value=()) as matcher:
            elapsed = benchmark.timed_batch(self.case, 3, clock=clock)
        self.assertEqual(elapsed, 700)
        self.assertEqual(clock.call_count, 2)
        self.assertEqual(matcher.call_count, 3)
        for call in matcher.call_args_list:
            self.assertEqual(call.args, (self.case.pantry, self.case.recipes))
            self.assertEqual(call.kwargs, {"limit": benchmark.LIMIT})

    def test_timed_batch_rejects_invalid_counts_and_backward_clock(self):
        for calls in (0, -1):
            clock = Mock(side_effect=AssertionError("invalid batches must not read a clock"))
            with self.subTest(calls=calls), self.assertRaises(ValueError):
                benchmark.timed_batch(self.case, calls, clock=clock)
            clock.assert_not_called()
        with patch.object(benchmark, "match_recipes", return_value=()):
            with self.assertRaisesRegex(RuntimeError, "backwards"):
                benchmark.timed_batch(self.case, 1, clock=Mock(side_effect=[20, 10]))

    def test_calibration_doubles_until_target_or_cap_using_fake_timer(self):
        timer = Mock(side_effect=lambda case, calls: calls * 10)
        self.assertEqual(benchmark.calibrate(self.case, 35, timer=timer), (4, 40))
        self.assertEqual([call.args[1] for call in timer.call_args_list], [1, 2, 4])
        capped_timer = Mock(return_value=1)
        with patch.object(benchmark, "MAX_CALLS", 4):
            self.assertEqual(benchmark.calibrate(self.case, 100, timer=capped_timer), (4, 1))
        self.assertEqual([call.args[1] for call in capped_timer.call_args_list], [1, 2, 4])

    def test_statistics_use_sample_variance_and_require_multiple_samples(self):
        stats = benchmark.sample_stats([1, 2, 6])
        self.assertEqual(stats["mean_ms"], 3)
        self.assertEqual(stats["median_ms"], 2)
        self.assertEqual(stats["sample_variance_ms2"], 7)
        self.assertAlmostEqual(stats["sample_stdev_ms"] ** 2, 7)
        self.assertEqual((stats["min_ms"], stats["max_ms"]), (1, 6))
        for values in ([], [1]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                benchmark.sample_stats(values)

    def test_summary_weights_processes_equally_despite_different_batch_sizes(self):
        workers = [worker_result([1, 3], 1), worker_result([8, 10], 1_000)]
        result = benchmark.summarize(workers, ["small"])[0]
        self.assertEqual(result["process_means_ms"], [2, 9])
        self.assertEqual(result["between_process"]["mean_ms"], 5.5)
        self.assertEqual(result["between_process"]["sample_variance_ms2"], 24.5)

    def test_summary_rejects_mismatched_inputs_or_expected_results(self):
        for key in ("input_sha256", "expected_result_sha256"):
            workers = [worker_result([1, 3], 1), worker_result([8, 10], 1)]
            workers[1]["cases"][0][key] = "different"
            with (
                self.subTest(key=key),
                self.assertRaisesRegex(RuntimeError, "identical inputs/results"),
            ):
                benchmark.summarize(workers, ["small"])


class BenchmarkCommandTests(unittest.TestCase):
    def test_complete_report_with_fake_timers_and_no_real_subprocess(self):
        raw = small_inputs()

        def simulate_worker(command, **kwargs):
            index = int(command[command.index("--worker-index") + 1])
            result = benchmark.worker(raw, index, seed=100, samples=2, target_ms=50)
            return SimpleNamespace(stdout=json.dumps(result))

        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "simulated-run"
            with (
                patch.object(benchmark, "build_inputs", return_value=raw),
                patch.multiple(
                    benchmark.platform,
                    system=Mock(return_value="TestOS"),
                    release=Mock(return_value="Test release"),
                    machine=Mock(return_value="Test machine"),
                    processor=Mock(return_value="Simulated CPU"),
                ),
                patch.object(benchmark.subprocess, "run", side_effect=simulate_worker) as spawn,
                patch.object(benchmark, "calibrate", return_value=(2, 50_000_000)),
                patch.object(
                    benchmark,
                    "timed_batch",
                    side_effect=[2_000_000, 4_000_000, 6_000_000, 8_000_000],
                ),
                patch.object(
                    benchmark, "perf_counter_ns", side_effect=AssertionError("no real timing")
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                benchmark.main(["--output-dir", str(output), "--processes", "2", "--samples", "2"])
            report = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertTrue(report["complete"])
            self.assertEqual(spawn.call_count, 2)
            self.assertEqual(report["summary"][0]["process_means_ms"], [1.5, 3.5])
            self.assertEqual(report["summary"][0]["between_process"]["sample_variance_ms2"], 2)
            for run in report["workers"]:
                self.assertEqual(run["inputs_sha256"], report["inputs_sha256"])
            with (output / "samples.csv").open(encoding="utf-8", newline="") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual([float(row["per_call_ms"]) for row in rows], [1, 2, 3, 4])
            self.assertIn("not request-tail latency", (output / "summary.txt").read_text())

    def test_controller_rejects_changed_input_fingerprint(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "changed-inputs"
            fake_result = {"sources": benchmark.source_metadata(), "inputs_sha256": "changed"}
            with (
                patch.object(benchmark, "build_inputs", return_value=small_inputs()),
                patch.multiple(
                    benchmark.platform,
                    system=Mock(return_value="TestOS"),
                    release=Mock(return_value="Test release"),
                    machine=Mock(return_value="Test machine"),
                    processor=Mock(return_value="Simulated CPU"),
                ),
                patch.object(
                    benchmark.subprocess,
                    "run",
                    return_value=SimpleNamespace(stdout=json.dumps(fake_result)),
                ),
                patch.object(
                    benchmark, "perf_counter_ns", side_effect=AssertionError("no real timing")
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                with self.assertRaisesRegex(RuntimeError, "Inputs changed"):
                    benchmark.main(["--output-dir", str(output), "--processes", "2"])
            report = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertFalse((output / "summary.txt").exists())

    def test_failed_worker_leaves_an_incomplete_report_without_summary(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new-run"
            failure = benchmark.subprocess.CalledProcessError(1, ["fake-worker"])
            fake_clock = SimpleNamespace(
                implementation="fake-clock", resolution=1e-9, monotonic=True
            )
            with (
                patch.object(benchmark, "build_inputs", return_value=small_inputs()),
                patch.object(benchmark, "get_clock_info", return_value=fake_clock),
                patch.object(benchmark.subprocess, "run", side_effect=failure) as spawn,
                patch.object(
                    benchmark, "perf_counter_ns", side_effect=AssertionError("no real timing")
                ),
                patch.multiple(
                    benchmark.platform,
                    system=Mock(return_value="TestOS"),
                    release=Mock(return_value="test-release"),
                    machine=Mock(return_value="test-machine"),
                    processor=Mock(return_value="test-processor"),
                ),
                patch("sys.stdout", io.StringIO()),
            ):
                with self.assertRaisesRegex(RuntimeError, "partial results are incomplete"):
                    benchmark.main(["--output-dir", str(output), "--processes", "2"])
                spawn.assert_called_once()
            report = json.loads((output / "results.json").read_text(encoding="utf-8"))
            self.assertFalse(report["complete"])
            self.assertEqual(report["workers"], [])
            self.assertEqual(report["failure"]["process"], 0)
            self.assertNotIn("summary", report)
            self.assertFalse((output / "summary.txt").exists())
            self.assertEqual(
                json.loads((output / "inputs.json").read_text(encoding="utf-8")), small_inputs()
            )

    def test_check_validates_without_timing_processes_or_filesystem_writes(self):
        output = io.StringIO()
        forbidden = []
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(benchmark, "build_inputs", return_value=small_inputs())
            )
            stack.enter_context(patch("sys.stdout", output))
            for owner, name in (
                (benchmark, "perf_counter_ns"),
                (benchmark, "get_clock_info"),
                (benchmark, "timed_batch"),
                (benchmark, "calibrate"),
                (benchmark, "worker"),
                (benchmark, "save_json"),
                (benchmark, "write_reports"),
                (benchmark.subprocess, "run"),
                (Path, "mkdir"),
                (Path, "open"),
                (Path, "write_text"),
            ):
                forbidden.append(
                    stack.enter_context(
                        patch.object(
                            owner, name, side_effect=AssertionError(f"--check must not call {name}")
                        )
                    )
                )
            benchmark.main(["--check"])
            for operation in forbidden:
                operation.assert_not_called()
        self.assertIn("Validation passed. No timing samples collected", output.getvalue())
        self.assertIn('"name": "small"', output.getvalue())

        # Hidden worker flags must not bypass --check's no-measurement guarantee.
        with (
            patch.object(benchmark, "worker") as worker,
            patch.object(benchmark, "timed_batch") as timer,
            patch.object(benchmark.subprocess, "run") as spawn,
            patch.object(Path, "read_text") as read,
            patch("sys.stderr", io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as stopped:
                benchmark.main(["--check", "--worker-input", "not-read.json"])
            self.assertEqual(stopped.exception.code, 2)
            worker.assert_not_called()
            timer.assert_not_called()
            spawn.assert_not_called()
            read.assert_not_called()

    def test_existing_output_directory_is_refused_without_overwriting_files(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            existing = path / "results.json"
            existing.write_bytes(b"existing results")
            with (
                patch.object(benchmark, "build_inputs", return_value=small_inputs()),
                patch.object(benchmark, "save_json") as save,
                patch.object(benchmark.subprocess, "run") as spawn,
                patch.object(benchmark, "get_clock_info") as clock,
            ):
                with self.assertRaises(FileExistsError):
                    benchmark.main(["--output-dir", str(path)])
                save.assert_not_called()
                spawn.assert_not_called()
                clock.assert_not_called()
            self.assertEqual(existing.read_bytes(), b"existing results")
            self.assertEqual(list(path.iterdir()), [existing])


if __name__ == "__main__":
    unittest.main()
