# benchmarks/recipe_matching.py
"""Measure warm recipe ranking in sequential fresh Python processes.

Use --check to validate inputs/results without collecting timings.
All reported latency samples are batch-derived per-call averages, not individual
request timings. See docs/BENCHMARKING.txt for the measurement protocol.
"""

from __future__ import annotations

import argparse
import csv
import gc
import hashlib
import json
import os
import platform
import random
import statistics
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path
from time import get_clock_info, perf_counter_ns

from genius_kitchen import models, recipes
from genius_kitchen.models import Recipe
from genius_kitchen.recipes import load_bundled_recipes, match_recipes

SEED = 20261002
SIZES = (100, 1_000, 10_000)
LIMIT = 10
MAX_CALLS = 131_072


@dataclass
class Case:
    name: str
    pantry: set[str]
    recipes: tuple[Recipe, ...]


def fingerprint(value) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def build_inputs(seed: int = SEED) -> list[dict]:
    rng = random.Random(seed)
    vocabulary = [f"ingredient-{index:03d}" for index in range(256)]
    pantry = sorted(rng.sample(vocabulary, 48))
    catalog = [
        {
            "name": f"Recipe {index:05d}",
            "ingredients": rng.sample(vocabulary, rng.randint(6, 12)),
            "instructions": ["Synthetic benchmark record; not a cooking recipe."],
        }
        for index in range(max(SIZES))
    ]
    # Avoid presenting the sorter with names already ordered inside score ties.
    rng.shuffle(catalog)
    cases = [
        {
            "name": "bundled",
            "pantry": ["rice", "egg", "carrot", "onion", "garlic", "tomato"],
            "recipes": [asdict(recipe) for recipe in load_bundled_recipes()],
        }
    ]
    cases.extend(
        {"name": f"synthetic-{size}", "pantry": pantry, "recipes": catalog[:size]} for size in SIZES
    )
    # Use exactly the same JSON-compatible types in the controller and workers.
    return json.loads(json.dumps(cases))


def parse_case(raw: dict) -> Case:
    if not isinstance(raw.get("name"), str) or not raw["name"].strip():
        raise ValueError("Each benchmark scenario needs a name")
    if not isinstance(raw.get("pantry"), list) or any(
        not isinstance(name, str) or not name.strip() for name in raw["pantry"]
    ):
        raise ValueError("A pantry must be a JSON array of nonblank names")
    if not isinstance(raw.get("recipes"), list) or not raw["recipes"]:
        raise ValueError("Each benchmark scenario needs a nonempty recipe array")
    case = Case(
        raw["name"], set(raw["pantry"]), tuple(Recipe.from_dict(row) for row in raw["recipes"])
    )
    if len({recipe.name for recipe in case.recipes}) != len(case.recipes):
        raise ValueError("Benchmark recipe names must be unique")
    for recipe in case.recipes:
        if not recipe.ingredients or len(set(recipe.ingredients)) != len(recipe.ingredients):
            raise ValueError("Benchmark recipes require nonempty, unique ingredient lists")
    return case


def signature(matches) -> list:
    return [
        (match.recipe.name, match.available, match.missing, match.coverage) for match in matches
    ]


def reference_signature(case: Case) -> list:
    """Independent untimed oracle: set arithmetic and exact rational ordering."""
    available = {name.strip().casefold() for name in case.pantry}
    rows = []
    for recipe in case.recipes:
        required = set(recipe.ingredients)
        present = required & available
        missing = required - available
        score = Fraction(len(present), len(required))
        rows.append((score, len(missing), recipe.name, recipe, present, missing))
    rows.sort(key=lambda row: (-row[0], row[1], row[2]))
    return [
        (
            name,
            tuple(x for x in recipe.ingredients if x in present),
            tuple(x for x in recipe.ingredients if x in missing),
            float(score),
        )
        for score, _, name, recipe, present, missing in rows[:LIMIT]
    ]


def validate_result(case: Case, expected: list) -> None:
    if signature(match_recipes(case.pantry, case.recipes, limit=LIMIT)) != expected:
        raise RuntimeError(f"Ranking disagrees with the reference result: {case.name}")


def describe_case(raw: dict, case: Case, expected: list) -> dict:
    lengths = [len(recipe.ingredients) for recipe in case.recipes]
    available = {name.strip().casefold() for name in case.pantry}
    overlap = [
        len(set(recipe.ingredients) & available) / len(recipe.ingredients)
        for recipe in case.recipes
    ]
    return {
        "name": case.name,
        "recipe_count": len(case.recipes),
        "pantry_count": len(case.pantry),
        "normalized_pantry_count": len(available),
        "ingredient_count_min": min(lengths),
        "ingredient_count_max": max(lengths),
        "ingredient_count_mean": statistics.mean(lengths),
        "mean_recipe_overlap": statistics.mean(overlap),
        "input_sha256": fingerprint(raw),
        "expected_result_sha256": fingerprint(expected),
    }


def timed_batch(case: Case, calls: int, *, clock=None) -> int:
    if calls < 1:
        raise ValueError("A timed batch needs at least one call")
    clock = perf_counter_ns if clock is None else clock
    start = clock()
    for _ in range(calls):
        match_recipes(case.pantry, case.recipes, limit=LIMIT)
    elapsed = clock() - start
    if elapsed < 0:
        raise RuntimeError("The performance clock moved backwards")
    return elapsed


def calibrate(case: Case, target_ns: int, *, timer=None) -> tuple[int, int]:
    timer = timed_batch if timer is None else timer
    calls = 1
    while True:
        elapsed = timer(case, calls)
        if elapsed >= target_ns or calls >= MAX_CALLS:
            return calls, elapsed
        calls *= 2


def sample_stats(values: list[float]) -> dict:
    if len(values) < 2:
        raise ValueError("At least two samples are required for sample variance")
    return {
        "mean_ms": statistics.mean(values),
        "median_ms": statistics.median(values),
        "sample_stdev_ms": statistics.stdev(values),
        "sample_variance_ms2": statistics.variance(values),
        "min_ms": min(values),
        "max_ms": max(values),
    }


def source_metadata() -> dict:
    project = Path(__file__).resolve().parents[1]
    sources = {}
    for module in (models, recipes):
        location = Path(module.__file__).resolve()
        sources[module.__name__] = {
            "sha256": hashlib.sha256(location.read_bytes()).hexdigest(),
            "origin": "checkout/src"
            if location.is_relative_to(project / "src")
            else "installed package",
        }
    sources["benchmark"] = {"sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    return sources


def worker(raw_cases: list[dict], index: int, seed: int, samples: int, target_ms: int) -> dict:
    gc.enable()
    order = list(range(len(raw_cases)))
    random.Random(seed + index).shuffle(order)
    result = {
        "index": index,
        "order": [raw_cases[i]["name"] for i in order],
        "sources": source_metadata(),
        "inputs_sha256": fingerprint(raw_cases),
        "cases": [],
    }
    for case_index in order:
        raw = raw_cases[case_index]
        case = parse_case(raw)
        expected = reference_signature(case)
        validate_result(case, expected)
        for _ in range(3):
            match_recipes(case.pantry, case.recipes, limit=LIMIT)
        calls, calibration_ns = calibrate(case, target_ms * 1_000_000)
        elapsed = [timed_batch(case, calls) for _ in range(samples)]
        validate_result(case, expected)
        per_call_ms = [value / calls / 1_000_000 for value in elapsed]
        result["cases"].append(
            {
                **describe_case(raw, case, expected),
                "calls_per_batch": calls,
                "calibration_elapsed_ns": calibration_ns,
                "target_reached": calibration_ns >= target_ms * 1_000_000,
                "elapsed_ns": elapsed,
                "per_call_ms": per_call_ms,
                "within_process": sample_stats(per_call_ms),
            }
        )
    return result


def summarize(workers: list[dict], names: list[str]) -> list[dict]:
    summary = []
    for name in names:
        cases = [next(case for case in run["cases"] if case["name"] == name) for run in workers]
        hashes = {(case["input_sha256"], case["expected_result_sha256"]) for case in cases}
        if len(hashes) != 1:
            raise RuntimeError(f"Workers did not use identical inputs/results: {name}")
        # Each process gets one vote, even when calibration chose a different batch size.
        means = [statistics.mean(case["per_call_ms"]) for case in cases]
        summary.append(
            {
                "name": name,
                "recipe_count": cases[0]["recipe_count"],
                "process_means_ms": means,
                "between_process": sample_stats(means),
            }
        )
    return summary


def save_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def write_reports(output: Path, report: dict) -> None:
    with (output / "samples.csv").open("w", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream)
        writer.writerow(["process", "case", "batch", "calls", "elapsed_ns", "per_call_ms"])
        for run in report["workers"]:
            for case in run["cases"]:
                for batch, elapsed in enumerate(case["elapsed_ns"]):
                    writer.writerow(
                        [
                            run["index"],
                            case["name"],
                            batch,
                            case["calls_per_batch"],
                            elapsed,
                            case["per_call_ms"][batch],
                        ]
                    )
    lines = [
        "Warm recipe ranking: completed measurement",
        "Unit: milliseconds per call, derived from timed batches.",
        "Dispersion below is across process means; it is not request-tail latency.",
        "Case | recipes | mean ms | median ms | sample SD ms | sample variance ms^2",
    ]
    for case in report["summary"]:
        stats = case["between_process"]
        lines.append(
            f"{case['name']} | {case['recipe_count']} | {stats['mean_ms']:.6f} | {stats['median_ms']:.6f} | {stats['sample_stdev_ms']:.6f} | {stats['sample_variance_ms2']:.9f}"
        )
    lines.extend(
        [
            "",
            "Baseline only: no before/after speedup is claimed.",
            "Synthetic cases use one fixed pantry/distribution; bundled data is a separate scenario.",
            "Excludes loading, JSON parsing, pantry extraction, GUI rendering and process startup.",
            "Full samples, provenance and parameters: results.json; exact inputs: inputs.json.",
        ]
    )
    if any(not case["target_reached"] for run in report["workers"] for case in run["cases"]):
        lines.append(
            "WARNING: at least one calibration hit the call cap before reaching the target duration."
        )
    text = "\n".join(lines) + "\n"
    (output / "summary.txt").write_text(text, encoding="utf-8")
    print(text)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="validate all scenarios without timing or creating result files",
    )
    parser.add_argument(
        "--output-dir", type=Path, help="new directory for results; refuses to overwrite"
    )
    parser.add_argument(
        "--inputs", type=Path, help="replay a saved inputs.json instead of generating cases"
    )
    parser.add_argument("--seed", type=int, default=SEED)
    parser.add_argument("--processes", type=positive_int, default=5)
    parser.add_argument("--samples", type=positive_int, default=7)
    parser.add_argument("--target-ms", type=positive_int, default=50)
    parser.add_argument("--worker-input", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--worker-index", type=int, default=0, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.processes < 2 or args.samples < 2:
        parser.error("processes and samples must each be at least 2 to report sample variance")
    if args.check and args.worker_input:
        parser.error("--check cannot be combined with internal worker mode")
    if args.worker_input:
        raw = json.loads(args.worker_input.read_text(encoding="utf-8"))
        print(json.dumps(worker(raw, args.worker_index, args.seed, args.samples, args.target_ms)))
        return
    raw = (
        json.loads(args.inputs.read_text(encoding="utf-8"))
        if args.inputs
        else build_inputs(args.seed)
    )
    if not isinstance(raw, list) or not raw:
        parser.error("inputs must be a nonempty JSON array of scenarios")
    cases = [parse_case(item) for item in raw]
    if len({case.name for case in cases}) != len(cases):
        parser.error("scenario names must be unique")
    if args.check:
        for item in raw:
            case = parse_case(item)
            expected = reference_signature(case)
            validate_result(case, expected)
            print(json.dumps(describe_case(item, case, expected)))
        print("Validation passed. No timing samples collected or result files written.")
        return
    output = args.output_dir or Path("benchmark-results") / datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%S%fZ"
    )
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    input_path = output / "inputs.json"
    save_json(input_path, raw)
    clock = get_clock_info("perf_counter")
    report = {
        "schema_version": 1,
        "complete": False,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "metric": "warm match_recipes latency; batch-derived ms per call",
        "python": sys.version,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "logical_cpus": os.cpu_count(),
        },
        "clock": {
            "implementation": clock.implementation,
            "resolution_seconds": clock.resolution,
            "monotonic": clock.monotonic,
        },
        "parameters": {
            "seed": args.seed,
            "processes": args.processes,
            "samples": args.samples,
            "target_ms": args.target_ms,
            "limit": LIMIT,
            "warmup_calls": 3,
            "max_batch_calls": MAX_CALLS,
            "gc_enabled": True,
            "pythonhashseed": "0",
        },
        "sources": source_metadata(),
        "inputs_sha256": fingerprint(raw),
        "workers": [],
    }
    save_json(output / "results.json", report)
    environment = os.environ.copy()
    environment.update(PYTHONHASHSEED="0", PYTHONDONTWRITEBYTECODE="1")
    for index in range(args.processes):
        print(f"Running process {index + 1}/{args.processes}...", flush=True)
        command = [
            sys.executable,
            "-B",
            str(Path(__file__).resolve()),
            "--worker-input",
            str(input_path),
            "--worker-index",
            str(index),
            "--seed",
            str(args.seed),
            "--samples",
            str(args.samples),
            "--target-ms",
            str(args.target_ms),
        ]
        try:
            completed = subprocess.run(
                command,
                env=environment,
                text=True,
                encoding="utf-8",
                capture_output=True,
                check=True,
                timeout=180,
            )
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            detail = exc.stderr or str(exc)
            if isinstance(detail, bytes):
                detail = detail.decode("utf-8", errors="replace")
            report["failure"] = {"process": index, "detail": detail}
            save_json(output / "results.json", report)
            raise RuntimeError(
                f"Benchmark worker {index} failed; partial results are incomplete: {detail}"
            ) from exc
        run = json.loads(completed.stdout)
        if run["sources"] != report["sources"]:
            raise RuntimeError("Source changed or differs between controller and worker")
        if run["inputs_sha256"] != report["inputs_sha256"]:
            raise RuntimeError("Inputs changed between controller and worker")
        report["workers"].append(run)
        save_json(output / "results.json", report)
    report["summary"] = summarize(report["workers"], [item["name"] for item in raw])
    report["complete"] = True
    report["finished_utc"] = datetime.now(timezone.utc).isoformat()
    save_json(output / "results.json", report)
    write_reports(output, report)
    print(f"Saved results to: {output}")


if __name__ == "__main__":
    main()
