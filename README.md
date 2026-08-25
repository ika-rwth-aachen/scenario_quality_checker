# scenario.quality.checker

<img src="quality_checker/assets/scenario-quality-checker-logo.svg" width="400px" style="margin: 10px;">

**Find schema, consistency and motion-dynamics problems in ASAM OpenSCENARIO `.xosc` files — from the command line, in the browser, or in CI.**

[![tests](https://github.com/ika-rwth-aachen/scenario_quality_checker/actions/workflows/ci.yml/badge.svg)](https://github.com/ika-rwth-aachen/scenario_quality_checker/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10%20%7C%203.11-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)
![version](https://img.shields.io/badge/version-0.2.0-informational)

## Why use this

A scenario that opens in an editor is not necessarily a scenario a simulator can run. Files drift out
of schema, reference entities that were never defined, place two vehicles on top of each other, or
describe trajectories that imply physically impossible accelerations. The quality checker catches all
of that before you spend simulation time on it, and writes a PDF you can hand to a reviewer and a CSV
you can diff or aggregate. It is built for scenario authors and reviewers who need a quick, repeatable
verdict on one file or a whole folder.

## Key features

- **Schema validation** against the bundled ASAM OpenSCENARIO schemas (0.9, 1.0, 1.1, 1.2, 1.3).
- **Consistency checks** for undefined entities, duplicate or intersecting init positions, and
  add/remove events that do not match the scenario.
- **Motion-dynamics checks** on acceleration and sideslip ("swim") angle, against configurable limits.
- **Optional simulation** — point at an [esmini](https://github.com/esmini/esmini) binary and the
  dynamics checks use simulated trajectories instead of the static definitions.
- **Reports**: per-scenario PDF and CSV, plus an aggregated rollup across a whole folder.
- **Web interface** for uploading a scenario and reading findings and plots in the browser.

## Installation

Requires **Python ≥ 3.10** (CI covers 3.10 and 3.11). Everything else is installed for you.

With [uv](https://docs.astral.sh/uv/getting-started/installation/) (recommended — creates `.venv`
from the lockfile):

```bash
uv sync                 # CLI only
uv sync --extra web     # CLI + web interface
```

With pip:

```bash
pip install ".[web]"    # drop [web] for the CLI only
```

Both give you two console scripts, `scenario-quality-checker` and `scenario-quality-checker-web`.
With uv, prefix commands with `uv run` (no activation needed); with pip in an activated
environment, call them directly.

Optional: an [esmini](https://github.com/esmini/esmini) executable for simulation-based dynamics.

## Quickstart

Check one of the bundled example scenarios and write both reports:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path quality_checker/example_files/envelope_dynamic_error_1.xosc \
  --out-path reports/ \
  --out-pdf --out-csv --print-log
```

Output:

```text
2026-08-20 12:19:27.183 | INFO | quality_checker.quality_checker:__init__:130 - Starting analysis of quality_checker/example_files/envelope_dynamic_error_1.xosc
2026-08-20 12:19:27.204 | INFO | quality_checker.quality_checker:__init__:137 - XML is loadable
2026-08-20 12:19:28.594 | INFO | quality_checker.quality_checker:__init__:144 - XSD is valid
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:create_single_report:1260 - Report created: reports
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:create_csv:1327 - CSV report created at reports/envelope_dynamic_error_1.xosc.csv
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:quality_check_single:1398 - Analysis completed for quality_checker/example_files/envelope_dynamic_error_1.xosc.
OpenSCENARIO version detected: 1.1
```

You now have `reports/envelope_dynamic_error_1.pdf` (summary with plots) and
`reports/envelope_dynamic_error_1.xosc.csv` (machine-readable findings). Output directories are
created automatically. Drop `--print-log` for a quiet run.

If a run produces nothing, or produces something you did not expect, see
[Troubleshooting](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/troubleshooting.md).

## Usage

Two commands, available as `scenario-quality-checker <command>` or
`python -m quality_checker <command>`:

| Command | Purpose |
| --- | --- |
| `quality_check_single` | Check one `.xosc` file |
| `quality_check_multiple` | Check every `.xosc` file in a directory, optionally with a rollup |

Screen a whole folder and get per-file reports plus one aggregated PDF/CSV:

```bash
uv run scenario-quality-checker quality_check_multiple \
  --files-path quality_checker/example_files/ \
  --out-path reports/ \
  --single --aggregated \
  --out-pdf --out-csv
```

Every option, its default, and further worked examples (custom thresholds, esmini-backed dynamics)
are in the
[CLI reference](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/cli-reference.md).

## Reports

| Run | File |
| --- | --- |
| Single, PDF | `{out-path}/<scenario-stem>.pdf` |
| Single, CSV | `{out-path}/<scenario-file>.csv` (keeps the `.xosc` in the name) |
| Multiple, aggregated | `{out-path}/aggregate_report.pdf`, `{out-path}/aggregate_data.csv` |
| Multiple, per file | `{out-path}/single_reports/` |

> [!IMPORTANT]
> **Findings do not change the exit code.** Both commands exit `0` whether the scenario is clean or
> full of errors; a non-zero exit means the tool itself failed. If you want CI to fail on findings,
> parse `aggregate_data.csv` and decide there.

The CSV formats, field by field, and the full exit-code behaviour are in
[Reports](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/reports.md).

## Web interface

A self-contained web app: upload a scenario and read the findings, the dynamics plots and the reports
in the browser. No scenario data is persisted — every upload lives in a per-session temporary
directory that is removed once the session expires.

```bash
uv sync --extra web
uv run scenario-quality-checker-web
```

Then open <http://localhost:8001>. Set `SQC_PORT` to serve a different port. (Equivalent:
`uv run python -m quality_checker.webapp.server`.)

With Docker:

```bash
docker compose -f docker/docker-compose.yml up --build
```

The feature set, the HTTP API and all configuration variables are documented in
[Web interface](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/web-interface.md).
**Before exposing the app to anyone, read
[Deployment](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/deployment.md)** —
session affinity, TLS and the imprint duty are requirements, not suggestions.

## How it works

1. **XML + XSD validation** — the version is read from the file header and the matching schema validates it.
2. **Scenario parsing** — parameters are expanded, then entities, init actions and trajectories are parsed.
3. **Consistency checks** — undefined entities, overlapping start positions, unmatched add/remove events.
4. **Dynamics checks** — acceleration and sideslip peaks against the configured limits.

Each stage runs only if the previous one passed. The full description is in
[Architecture](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/architecture.md).

## Documentation

| Document | Contents |
| --- | --- |
| [CLI reference](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/cli-reference.md) | Every command-line option, defaults, and worked examples |
| [Reports](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/reports.md) | Output locations, the two CSV formats, exit codes |
| [Web interface](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/web-interface.md) | Features, HTTP API, environment variables |
| [Deployment](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/deployment.md) | Hardening, session affinity, legal notices |
| [Architecture](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/architecture.md) | The check pipeline, stage by stage |
| [Troubleshooting](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/troubleshooting.md) | Symptoms and fixes |
| [Development and contributing](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/contributing.md) | Test suite, linting, how to open a good PR |

Three further Markdown files are served by the running web app itself — the in-app
[Help](quality_checker/webapp/help.md), [About](quality_checker/webapp/about.md) and
[Data privacy](quality_checker/webapp/data_privacy.md) dialogs.

## Development

```bash
pip install ".[web,dev]"
pytest -q
```

CI runs the same suite on Python 3.10 and 3.11, and gates `ruff check .` and `ruff format --check .`.
See [Development and contributing](https://github.com/ika-rwth-aachen/scenario_quality_checker/blob/main/docs/contributing.md)
for what a good pull request looks like.

## License

MIT — see [LICENSE](LICENSE). Third-party licenses are listed in
[LICENSE-3rdparty](LICENSE-3rdparty).

## Acknowledgements

This package is developed as part of the [SYNERGIES project](https://synergies-ccam.eu).

<img src="quality_checker/assets/synergies.svg" style="width:2in" />

Funded by the European Union. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union or European Climate, Infrastructure and Environment Executive Agency (CINEA). Neither the European Union nor the granting authority can be held responsible for them.

<img src="quality_checker/assets/funded_by_eu.svg" style="width:4in" />

## Notice

> [!IMPORTANT]
> The project is open-sourced and maintained by the [**Institute for Automotive Engineering (ika) at RWTH Aachen University**](https://www.ika.rwth-aachen.de/).
> We cover a wide variety of research topics within our [*Vehicle Intelligence & Automated Driving*](https://www.ika.rwth-aachen.de/en/competences/fields-of-research/vehicle-intelligence-automated-driving.html) domain.
> If you would like to learn more about how we can support your automated driving or robotics efforts, feel free to reach out to us!
> :email: ***opensource@ika.rwth-aachen.de***
