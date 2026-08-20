# scenario.quality.checker

<img src="assets/scenario-quality-checker-logo.svg" width="400px" style="margin: 10px;">

**Find schema, consistency and motion-dynamics problems in ASAM OpenSCENARIO `.xosc` files — from the command line, in the browser, or in CI.**

[![tests](https://github.com/ika-rwth-aachen/scenario_quality_checker/actions/workflows/ci.yml/badge.svg)](https://github.com/ika-rwth-aachen/scenario_quality_checker/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%20%7C%203.11-blue)](https://www.python.org/)
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

- **Schema validation** against the bundled ASAM OpenSCENARIO schemas (0.9, 1.0, 1.1, 1.2, 1.3) — the
  version is read from the file header and the matching XSD is picked automatically.
- **Consistency checks**: entities used but never defined, duplicate or geometrically intersecting
  init positions, add/remove events that do not match the initial or parked entities.
- **Motion-dynamics checks**: acceleration and sideslip ("swim") angle peaks against configurable
  warning and error limits.
- **Optional simulation**: point the checker at an [esmini](https://github.com/esmini/esmini) binary
  and the dynamics checks use simulated trajectories instead of the static trajectory definitions.
- **Reports**: per-scenario PDF and CSV, plus an aggregated rollup across a whole folder.
- **Web interface**: upload a scenario, read findings and plots in the browser, download the reports.
  Nothing is persisted — every upload lives in a per-session temporary directory.

## Installation

Requires **Python ≥ 3.9** (CI covers 3.9 and 3.11). Everything else is installed for you.

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
environment, call them directly. Pinned dependency sets are also available as `requirements.txt` and
`requirements-web.txt`.

Optional: an [esmini](https://github.com/esmini/esmini) executable for simulation-based dynamics.

## Quickstart

Check one of the bundled example scenarios and write both reports:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path example_files/envelope_dynamic_error_1.xosc \
  --out-path reports/ \
  --out-pdf --out-csv --print-log
```

Output:

```text
2026-08-20 12:19:27.183 | INFO | quality_checker.quality_checker:__init__:130 - Starting analysis of example_files/envelope_dynamic_error_1.xosc
2026-08-20 12:19:27.204 | INFO | quality_checker.quality_checker:__init__:137 - XML is loadable
2026-08-20 12:19:28.594 | INFO | quality_checker.quality_checker:__init__:144 - XSD is valid
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:create_single_report:1260 - Report created: reports
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:create_csv:1327 - CSV report created at reports/envelope_dynamic_error_1.xosc.csv
2026-08-20 12:19:30.620 | INFO | quality_checker.quality_checker:quality_check_single:1398 - Analysis completed for example_files/envelope_dynamic_error_1.xosc.
OpenSCENARIO version detected: 1.1
```

You now have `reports/envelope_dynamic_error_1.pdf` (summary with plots) and
`reports/envelope_dynamic_error_1.xosc.csv` (machine-readable findings). Output directories are
created automatically. Drop `--print-log` for a quiet run.

## Usage

Two commands, available as `scenario-quality-checker <command>` or
`python -m quality_checker <command>`:

| Command | Purpose |
| --- | --- |
| `quality_check_single` | Check one `.xosc` file |
| `quality_check_multiple` | Check every `.xosc` file in a directory, optionally with a rollup |

### `quality_check_single`

| Option | Default | Meaning |
| --- | --- | --- |
| `--file-path` | *(required)* | Input `.xosc` file |
| `--out-path` | `reports/single_reports/` | Output directory for reports |
| `--out-pdf` | off | Write the PDF report |
| `--out-csv` | off | Write the CSV report |
| `--print-log` | off | Emit progress logging |
| `--schema-path` | bundled `quality_checker/schemas/` | Directory containing `OpenSCENARIO_*.xsd` |
| `--esmini-path` | *(none)* | Path to an `esmini` executable; enables simulation-based dynamics |

### `quality_check_multiple`

| Option | Default | Meaning |
| --- | --- | --- |
| `--files-path` | *(required)* | Directory containing `.xosc` files (non-recursive) |
| `--out-path` | `reports/` | Output directory for reports |
| `--single` | off | Write a per-file report into `{out-path}/single_reports/` |
| `--aggregated` | off | Write a combined report across all files |
| `--out-pdf` / `--out-csv` | off | Formats to write (applies to both report kinds) |
| `--print-log` | off | Emit progress logging |
| `--schema-path` | bundled `quality_checker/schemas/` | Directory containing `OpenSCENARIO_*.xsd` |
| `--esmini-path` | *(none)* | Path to an `esmini` executable; enables simulation-based dynamics |

### Options accepted by both

| Option | Default | Meaning |
| --- | --- | --- |
| `--acceleration-warning` | `9.8` m/s² | Acceleration warning limit |
| `--acceleration-error` | `29.4` m/s² | Acceleration error limit |
| `--sideslip-warning` | `0.1` rad | Sideslip (swim) angle warning limit |
| `--sideslip-error` | `0.2` rad | Sideslip (swim) angle error limit |
| `--work-dir` | `./results/tmp` | Directory for intermediate files |

Omitted limits fall back to the defaults in `quality_checker/config.py`. A warning limit must be
positive and must not exceed its matching error limit, otherwise the run fails with a `ValueError`.

## Examples

**Screen a folder and get a rollup table.** Per-file reports plus one aggregated PDF/CSV:

```bash
uv run scenario-quality-checker quality_check_multiple \
  --files-path example_files/ \
  --out-path reports/ \
  --single --aggregated \
  --out-pdf --out-csv
```

**Tighten the dynamics limits for a comfort-focused review.** Flag anything above 4 m/s²:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path example_files/envelope_dynamic_error_2.xosc \
  --out-path reports/ --out-csv \
  --acceleration-warning 2.5 \
  --acceleration-error 4.0
```

**Judge the dynamics from a simulation instead of the written trajectories.** With `--esmini-path`
the scenario is run headless (`esmini --headless --csv_logger <log> --osc <scenario>`) and the logged
trajectories feed the dynamics checks and plots:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path example_files/envelope_scenario_loadable.xosc \
  --out-path reports/ --out-pdf \
  --esmini-path /opt/esmini/bin/esmini
```

## Output and how to read it

### Where files land

| Run | File |
| --- | --- |
| Single, PDF | `{out-path}/<scenario-stem>.pdf` |
| Single, CSV | `{out-path}/<scenario-file>.csv` (keeps the `.xosc` in the name) |
| Multiple, aggregated | `{out-path}/aggregate_report.pdf`, `{out-path}/aggregate_data.csv` |
| Multiple, per file | `{out-path}/single_reports/` |

### Per-scenario CSV

Metadata first, then the findings grouped by category. Empty categories mean nothing was found:

```csv
scenario_file,example_files/envelope_dynamic_error_1.xosc
xml_loadable,True
xsd_valid,True
version,1.1
author,christoph.glasmacher@ika.rwth-aachen.de
date,23.10.2024
simulation_status,not done
car,17
total,17

file_errors
missing_entity_definitions
identical_initposition_entities
intersecting_entities
missing_in
position_resolution_warnings

dynamic_errors
acceleration_errors
acceleration_warnings
swimangle_errors
swimangle_warnings
o_2
```

Read that as: the file is schema-valid OpenSCENARIO 1.1 with 17 cars, no structural problems, and
one dynamics warning — entity `o_2` exceeded the sideslip warning limit. `simulation_status` is
`not done` unless you passed `--esmini-path`.

### Aggregated CSV

One row per scenario, six fixed columns. `-` means the stage was never reached, because an earlier
stage failed:

```csv
scenario_file,xml_loadable,xsd_valid,simulation_status,n_file_errors,n_dynamic_errors
example_files/envelope_xsd_valid_v1-2.xosc,True,True,not done,0,0
example_files/envelope_file_error_1.xosc,True,True,not done,2,1
example_files/envelope_xsd_not_valid_1.xosc,True,False,not done,-,-
example_files/envelope_xml_not_loadable.xosc,False,False,not done,-,-
```

### Exit codes

> [!IMPORTANT]
> **Findings do not change the exit code.** Both commands exit `0` whether the scenario is clean or
> full of errors; a non-zero exit means the tool itself failed (bad threshold values, failed esmini
> run). If you want CI to fail on findings, parse `aggregate_data.csv` and decide there — for
> example, fail when any row has a non-zero `n_file_errors` or `n_dynamic_errors`.
>
> Two input mistakes are also silent: a `--files-path` that is not a directory logs an error and
> produces no reports, and a `--file-path` that does not exist is reported as `xml_loadable,False`.
> Both still exit `0`.

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

### What the web interface offers

- **Single scenario**: upload one `.xosc`, optionally with the OpenDRIVE map it references, and get
  the status, metadata, findings grouped by severity (each dynamics finding with the entity, its
  measured peak, the time of the peak and the limit it exceeded), the four plots, and the PDF/CSV
  report.
- **Batch**: upload several `.xosc` files or one `.zip` and get the aggregated table, the aggregated
  PDF/CSV, and a drill-down into any single file.
- **Thresholds**: override the acceleration and sideslip limits per run without affecting anyone else
  using the same server.
- **Examples**: check any of the bundled `example_files/` without uploading.

### HTTP API

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/health` | Service status |
| GET | `/api/thresholds` | Default limits and their units |
| GET | `/api/examples` | Names of the bundled example scenarios |
| POST | `/api/checks` | Check one scenario (`scenario`, optional `map`, optional `example`, optional limits) |
| GET | `/api/runs/{id}` | Structured result of a run |
| GET | `/api/runs/{id}/plots/{name}.png` | One plot: `speed`, `acceleration`, `swimangle`, `paths` |
| GET | `/api/runs/{id}/report.pdf` \| `report.csv` | Report for a run |
| POST | `/api/batches` | Check several scenarios (`scenarios`, optional limits) |
| GET | `/api/batches/{id}/report.pdf` \| `report.csv` | Aggregated report |

Runs are readable only by the browser session that created them.

```console
$ curl -s localhost:8001/api/thresholds
{"defaults":{"acceleration_warning":9.8,"acceleration_error":29.4,"sideslip_warning":0.1,"sideslip_error":0.2},"units":{"acceleration":"m/s^2","sideslip":"rad"}}
```

### Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SQC_PORT` | `8001` | Port to serve on |
| `SQC_MAX_UPLOAD_BYTES` | `20971520` | Per-file upload limit |
| `SQC_MAX_BATCH_FILES` | `50` | Files accepted in one batch |
| `SQC_MAX_ZIP_UNCOMPRESSED_BYTES` | `209715200` | Expanded size limit for archives |
| `SQC_SESSION_TTL_SECONDS` | `3600` | How long results stay available |
| `SQC_MAX_SESSIONS` | `200` | Concurrent sessions kept before evicting the least recently used |
| `SQC_RUN_TIMEOUT_SECONDS` | `120` | Time limit for a single check |
| `SQC_SECURE_COOKIES` | `auto` | `auto` follows the request scheme; `true`/`false` force it |

The server binds `0.0.0.0`. Checks run on a single worker thread, because the checker and matplotlib
keep global state. Put the app behind a reverse proxy and run several containers if you need
throughput. Instances may share the working root (`$TMPDIR/scenario-quality-checker-web`): each
session owns its own subdirectory, and startup cleanup only removes leftovers older than
`SQC_SESSION_TTL_SECONDS`, so a restart never deletes a sibling instance's uploads.

## How it works

1. **XML + XSD validation** — the file is parsed as XML, the OpenSCENARIO version is read from the
   header (`revMajor`/`revMinor`), and the matching `OpenSCENARIO_<version>.xsd` validates it.
2. **Scenario parsing** — `scenariogeneration` parses the scenario into entities, init actions and
   trajectories. Parameter declarations outside the storyboard are expanded first so the parser sees
   concrete values.
3. **Consistency checks** — entities referenced by the storyboard must be defined, initial positions
   are compared for duplicates and geometric overlaps, add/remove events are checked against the
   initial and parked entities.
4. **Dynamics checks** — speed, acceleration and sideslip angle are derived from positions over time
   for trajectory events, and entities crossing a threshold are reported as warnings or errors. With
   `--esmini-path`, a headless simulation supplies the trajectories instead, which also covers
   actions other than `TrajectoryAction`.

## Troubleshooting

| Symptom | Cause and fix |
| --- | --- |
| The command runs but no PDF/CSV appears | Reporting is opt-in — add `--out-pdf` and/or `--out-csv`. For `quality_check_multiple` you also need `--single` and/or `--aggregated`. |
| The command finishes instantly and the report says `xml_loadable,False` | A path that does not exist is treated like an unreadable file rather than rejected — no error, exit `0`. Check the spelling; paths are relative to your working directory, so run the examples from the repository root. |
| `xsd_valid` is `False` and nothing else is reported | Structural and dynamics checks only run on schema-valid files. Fix the schema errors listed in the PDF/CSV first. |
| The version in the header is not 0.9–1.3 | Only the bundled schemas are supported. Add your own XSD to a directory and point `--schema-path` at it. |
| `ModuleNotFoundError: No module named 'fastapi'` | The web extra is not installed — `uv sync --extra web` or `pip install ".[web]"`. |
| `[Errno 98] Address already in use` | Port 8001 is taken; set `SQC_PORT` to a free port. |
| Matplotlib errors on a headless machine/server | Set `MPLBACKEND=Agg` (the Docker image does this already). |
| `Simulator command failed with exit code …` | `--esmini-path` does not point at a working esmini binary, or esmini cannot load the scenario's OpenDRIVE map. |
| Nothing happens for a `--files-path` typo | A non-directory path logs an error and exits `0`. Check the path. |

## Development

```bash
pip install ".[web,dev]"
pytest -q
```

CI runs the same suite on Python 3.9 and 3.11 (`.github/workflows/ci.yml`). The code base is
formatted and linted with [ruff](https://docs.astral.sh/ruff/), which is not part of the `dev`
extra — install it separately (`pip install ruff` or `uvx ruff`) if you want to run it.

## Contributing

There is no separate contributing guide yet. Please open an issue for bugs and feature requests, and
keep pull requests focused: add or update tests under `tests/`, run `pytest -q` (and `ruff check .`)
before pushing, and add an example `.xosc` to `example_files/` when you add a new kind of check.

## License

MIT — see [LICENSE](LICENSE). Third-party licenses are listed in
[LICENSE-3rdparty](LICENSE-3rdparty).

## Reference

- ASAM OpenSCENARIO standard: https://www.asam.net/standards/detail/openscenario/
- esmini simulator: https://github.com/esmini/esmini

# Acknowledgements

This package is developed as part of the [SYNERGIES project](https://synergies-ccam.eu).

<img src="assets/synergies.svg" style="width:2in" />

Funded by the European Union. Views and opinions expressed are however those of the author(s) only and do not necessarily reflect those of the European Union or European Climate, Infrastructure and Environment Executive Agency (CINEA). Neither the European Union nor the granting authority can be held responsible for them.

<img src="assets/funded_by_eu.svg" style="width:4in" />


# Notice

> [!IMPORTANT]
> The project is open-sourced and maintained by the [**Institute for Automotive Engineering (ika) at RWTH Aachen University**](https://www.ika.rwth-aachen.de/).
> We cover a wide variety of research topics within our [*Vehicle Intelligence & Automated Driving*](https://www.ika.rwth-aachen.de/en/competences/fields-of-research/vehicle-intelligence-automated-driving.html) domain.
> If you would like to learn more about how we can support your automated driving or robotics efforts, feel free to reach out to us!
> :email: ***opensource@ika.rwth-aachen.de***
