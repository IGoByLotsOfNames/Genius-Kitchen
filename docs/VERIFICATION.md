# Checks and measurements

[← Back to Genius Kitchen](../README.md)

Genius Kitchen has a native desktop interface, a local browser interface and portable Windows packaging. Each needs a different kind of check. The integrated source was rechecked on 2 October 2026 on Windows with Python 3.12.14. Earlier packaging and browser-interaction records supplied with the upgrade are identified separately below. Subsequent remote runs appear in [GitHub Actions](https://github.com/IGoByLotsOfNames/Genius-Kitchen/actions).

## What was checked

| Layer | Recorded checks | What they establish |
| --- | --- | --- |
| Desktop and shared core | 83 passing tests, zero skips, rerun against a fresh regular installation | Validation, expiry boundaries, malformed files, injected storage failures, deterministic ranking, real Tk callbacks, package resources, demo isolation and benchmark logic |
| Local browser backend | 26 passing HTTP/CLI tests, rerun against the integrated source | Request validation, inventory operations, persistence, revision handling and local application behavior |
| Browser frontend logic | 12 passing async regression tests rerun: ten top-level cases and two subtests | Real JavaScript handlers exercised in a Node VM with controlled requests and minimal DOM mocks |
| Supplied packaged browser executable | 53 HTTP/resource/shutdown assertions, rerun against the prebuilt artifact | The frozen application's core module origins, recipe data hashes, static assets and HTTP/lifecycle behavior; static assets agree with the integrated source |
| Packaged desktop executable | Real hidden Tk smoke checks recorded in the supplied upgrade | Initialization, bundled recipes, Add/Remove callbacks, saved inventory and reloading in the actual frozen executable |
| Earlier direct browser session | Targeted functional and responsive review recorded in the supplied upgrade | CRUD, validation, persistence, search, recipes, narrow layout, backup round trip and shutdown in a real browser |
| Fresh integration walkthrough | Sample pantry, recipe details, Add/Remove and one narrow viewport | Nine ingredients and six recipes loaded; fresh milk moved pancake coverage from 75% to 100%, and removing that occurrence restored 75%; no horizontal page overflow at 390 × 844 |

These scopes overlap and should remain separate. A unit test, a frontend subtest and a packaged-resource assertion are different units of evidence. Node VM checks cover handler logic; direct browser checks cover the visible interactions. Neither establishes comprehensive accessibility or long-term reliability.

The new [core integration record](evidence/integration/core-validation.json) and [browser integration record](evidence/integration/browser-validation.json) identify the source hashes and rerun results. The browser executable was the supplied prebuilt artifact, not a new build of the integrated commit. Its SHA-256 and the checked resource identities appear in that record.

The retained [desktop test log](evidence/2026-10-02/validation/tests.txt), [GUI smoke log](evidence/2026-10-02/validation/gui_smoke.txt) and [window-close check](evidence/2026-10-02/validation/normal_close.txt) preserve the earlier core snapshot. The [browser tests](../web/tests/test_server.py), [frontend regression tests](../web/tests/test_frontend.cjs), [desktop artifact verifier](../desktop/verify_desktop.py) and [browser artifact verifier](../web/verify_web.py) make the corresponding checks repeatable.

The [fresh browser walkthrough](evidence/integration/ui-walkthrough.json) records a targeted sample session. It opened the Banana Oat Pancakes dialog at 75% coverage with milk missing and instructions visible, added fresh Milk (1 litre, Dairy, expiring on the session date), and verified ten inventory items with 100% coverage. Removing that newly added occurrence returned the pantry to nine items and coverage to 75%.

The same session checked a 390 × 844 viewport: document width was 375 pixels against an inner width of 390 pixels, with no horizontal page overflow. The three README screenshots capture the actual pantry, recipe-detail dialog and narrow layout using synthetic data. This fresh walkthrough did not repeat the entire earlier CRUD, backup/import and long-use checklist.

## Run the source checks

From the repository root, use a Python 3.11+ environment with Tk support for the desktop suite:

```sh
python -m pip install -e ".[dev]"
python -m unittest discover -s tests -v
python -m unittest discover -s web/tests -v
node --test web/tests/test_frontend.cjs
```

The Node command is a development check; Node is not required to use the browser application. Linux desktop checks require a graphical display or Xvfb. [TESTING.txt](TESTING.txt) explains the GUI requirement, installed-package checks, linting and coverage commands. The workflow also checks that the core bundled under `web/core/` agrees with the root package used by the desktop.

For an isolated desktop sample without opening a window:

```sh
python demo.py --check
```

To exercise the real hidden Tk interaction path:

```sh
python -I -B demo.py --smoke-test
```

The [desktop guide](../desktop/RUN_ME.txt) and [browser build guide](../web/BUILD.txt) describe Windows executable builds and their verifiers. The supplied application checks were run on the build computer. A separate clean Windows machine, extended sessions and a broad accessibility review remain useful next checks.

## The recipe-matching baseline

The retained benchmark is a dated baseline supplied on 2 October 2026. Its saved samples, summary arithmetic, exact inputs and matching-source fingerprints were checked. It does not establish a before/after speedup.

| Scenario | Recipes | Mean ms/call | Median ms/call | Sample SD ms |
| --- | ---: | ---: | ---: | ---: |
| Bundled | 6 | 0.024974 | 0.024429 | 0.003263 |
| Synthetic | 100 | 0.542641 | 0.517862 | 0.097074 |
| Synthetic | 1,000 | 6.857010 | 6.918655 | 0.497885 |
| Synthetic | 10,000 | 92.300083 | 97.645771 | 11.628827 |

The timed function includes name normalization, ingredient scanning, match allocation, sorting and selection of the top ten results. Startup, imports, JSON loading, pantry extraction/expiry filtering, GUI rendering and correctness checks are outside the interval.

Five sequential fresh processes each use three warmups, calibration toward a 50 ms batch and seven measured batches per scenario. Each batch records an average milliseconds-per-call value; the headline statistics are calculated across the five process means. The sample SD describes between-process dispersion, not individual-request tail latency.

Synthetic catalogs use seed `20261002`, a fixed pantry of 48 names and recipes with six to twelve distinct ingredients drawn from a 256-name vocabulary. The catalog sizes are nested prefixes of a shuffled catalog. The six bundled recipes use a different pantry and distribution. An untimed reference using set operations and exact fractions checks rankings before and after timing.

Recorded environment: Windows 11, Python 3.12.14, AMD64, with 16 logical CPUs reported. The run used one computer; power mode and AC/battery conditions were not established. These values are a reproducibility record for the matcher rather than a guarantee of whole-application response time.

- [Summary](evidence/2026-10-02/benchmark/summary.txt)
- [Results and provenance](evidence/2026-10-02/benchmark/results.json)
- [Raw batches](evidence/2026-10-02/benchmark/samples.csv)
- [Exact inputs](evidence/2026-10-02/benchmark/inputs.json)
- [Evidence notes](evidence/2026-10-02/PROVENANCE.txt)

Replay correctness or collect a new measurement from the repository root:

```sh
python -B benchmarks/recipe_matching.py --check --inputs docs/evidence/2026-10-02/benchmark/inputs.json
python -B benchmarks/recipe_matching.py --inputs docs/evidence/2026-10-02/benchmark/inputs.json
```

New measurements go to a new result directory. [BENCHMARKING.txt](BENCHMARKING.txt) describes the procedure and interpretation in full.

## Boundaries worth keeping visible

The bundled catalog contains six illustrative recipes. Ingredient-name coverage does not establish sufficient quantities, nutritional suitability or food safety. No household waste-reduction or adoption measurement is claimed.

The JSON store assumes one process per inventory file. Browser tabs share one local server and use revision checks for stale changes; cross-process synchronization and power-loss recovery are not established. Portable Windows builds are unsigned, and the native desktop's hidden Tk tests do not establish visual quality or accessibility.

AI-assisted development is documented in the [project story](ORIGINAL_PROJECT.md). The tests and measurements describe the resulting software; recipe matching itself uses no runtime AI model.
