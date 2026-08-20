# scenario.quality.checker

<img src="assets\scenario-quality-checker-logo.svg" width="400px" style="margin: 10px;">

Analyze ASAM OpenSCENARIO `.xosc` files for structural, schema, and motion issues, then generate PDF and CSV reports for single files or batches. The tool is designed for scenario authors and reviewers who need a quick, repeatable way to validate scenarios and spot common mistakes before simulation.

## What it does
At a high level, the checker:
- Tries to load the file as XML and validates it against the matching OpenSCENARIO 1.x schema.
- Parses the scenario into a structured model to access entities, storyboard content, and trajectories.
- Runs a set of consistency and dynamics checks.
- Produces a human-readable PDF summary and/or a machine-readable CSV with the findings.

## What it checks
- XML loadability and OpenSCENARIO schema validation (OpenSCENARIO 1.x)
- Scenario parsing with `scenariogeneration`
- Entity bookkeeping: missing definitions, duplicate or intersecting init positions, add/remove consistency
- Motion quality: acceleration and swim angle warnings/errors

## How it works (short walkthrough)
1. XML + XSD validation
   - The file is parsed as XML.
   - The OpenSCENARIO version is read from the header (`revMajor`/`revMinor`).
   - The matching `OpenSCENARIO_<version>.xsd` file is used to validate the XML.
2. Scenario parsing
   - The scenario is parsed using `scenariogeneration` to access entities, init actions, and trajectories.
   - Parameter declarations outside the storyboard are expanded so the parser sees concrete values.
3. Consistency checks
   - Entities referenced by the storyboard must be defined.
   - Initial positions are compared to detect duplicates or geometric overlaps.
   - Add/remove events are checked against initial and parked entities.
4. Dynamics checks
   - For trajectory events, speed, acceleration, and swim angle are derived from positions over time.
   - Entities crossing threshold values are reported as warnings or errors.
   - If available, a simulation can be conducted to assess more than TrajectoryActions. Therefore, esmini hat to be used.

## Outputs
- Per-scenario report: PDF summary and/or CSV detail
- Aggregated report: rollup table across a folder of `.xosc` files
- Web interface: findings, plots and reports in the browser (see below)

## Installation
Dependencies are managed with [uv](https://docs.astral.sh/uv/getting-started/installation/). Install uv, then sync the environment (this creates `.venv` and installs the locked dependencies):

```bash
uv sync
```

To also install the web interface extras:

```bash
uv sync --extra web
```

All commands below are run through `uv run`, which uses the `.venv` created by
`uv sync` without requiring it to be activated. If you prefer an activated
environment, use `source .venv/bin/activate` (`.venv\Scripts\activate` on
Windows) and drop the `uv run` prefix.

## Quick start
Single file with PDF and CSV:

```bash
uv run python -m quality_checker quality_check_single \
  --file-path example_files/envelope_dynamic_error_1.xosc \
  --out-path reports/ \
  --schema-path quality_checker/schemas/ \
  --out-pdf \
  --out-csv
```

Multiple files with per-file and aggregated outputs:

```bash
uv run python -m quality_checker quality_check_multiple \
  --files-path example_files/ \
  --out-path reports/ \
  --schema-path quality_checker/schemas/ \
  --single \
  --aggregated \
  --out-pdf \
  --out-csv
```

## Command reference
The CLI is implemented with Typer and is invoked via `uv run python -m quality_checker`.

### `quality_check_single`
Checks one `.xosc` file and optionally creates reports.

Options:
- `--file-path`: input `.xosc` file (required)
- `--out-path`: output directory for reports (default `reports/single_reports/`)
- `--schema-path`: directory containing `OpenSCENARIO_*.xsd` (default `quality_checker/schemas/`)
- `--out-pdf`: create a PDF report
- `--out-csv`: create a CSV report
- `--print-log`: enable log output
- `--esmini-path`: optional path to an `esmini` executable. If provided,
  the checker runs a short, headless simulation of the scenario and uses
  the resulting trajectories for the dynamic checks and trajectory plots
  instead of only relying on the static trajectory definitions from the
  `.xosc` file.

### `quality_check_multiple`
Checks all `.xosc` files in a directory. Optionally creates per-file and aggregated reports.

Options:
- `--files-path`: directory with `.xosc` files (required)
- `--out-path`: output directory for reports (default `reports/`)
- `--schema-path`: directory containing `OpenSCENARIO_*.xsd` (default `quality_checker/schemas/`)
- `--single`: create per-file reports under `reports/single_reports/`
- `--aggregated`: create a combined report across all files
- `--out-pdf`: create PDF report(s)
- `--out-csv`: create CSV report(s)
- `--print-log`: enable log output
- `--esmini-path`: optional path to an `esmini` executable. If provided,
  each scenario is also simulated headless and the resulting trajectories
  are used for dynamic checks and trajectory plots.

### Common options
Both commands also accept:

- `--work-dir`: directory for intermediate files (default `./results/tmp`)
- `--acceleration-warning`, `--acceleration-error`: acceleration limits in m/s²
- `--sideslip-warning`, `--sideslip-error`: sideslip (swim) angle limits in rad

Omitted limits fall back to the values in `quality_checker/config.py`.

## Web interface
The checker also ships a self-contained web application: upload a scenario and
read the findings, the dynamics plots and the reports in the browser. No
scenario data is persisted — every upload lives in a per-session temporary
directory that is removed once the session expires.

```bash
uv sync --extra web
uv run python -m quality_checker.webapp.server
```

Then open http://localhost:8001. Set `SQC_PORT` to serve a different port.

With Docker:

```bash
docker compose -f docker/docker-compose.yml up --build
```

### What the web interface offers
- **Single scenario**: upload one `.xosc`, optionally with the OpenDRIVE map it
  references, and get the status, metadata, findings grouped by severity (each
  dynamics finding with the entity, its measured peak, the time of the peak and
  the limit it exceeded), the four plots, and the PDF/CSV report.
- **Batch**: upload several `.xosc` files or one `.zip` and get the aggregated
  table, the aggregated PDF/CSV, and a drill-down into any single file.
- **Thresholds**: override the acceleration and sideslip limits per run without
  affecting anyone else using the same server.
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

Checks run on a single worker thread, because the checker and matplotlib keep
global state. Put the app behind a reverse proxy and run several containers if
you need throughput. Instances may share the working root
(`$TMPDIR/scenario-quality-checker-web`): each session owns its own subdirectory,
and startup cleanup only removes leftovers older than `SQC_SESSION_TTL_SECONDS`,
so a restart never deletes a sibling instance's uploads.

## Output locations
Make sure `--out-path` exists when running `quality_check_single`.

- Single file:
  - PDF: `{out-path}/<scenario-stem>.pdf`
  - CSV: `{out-path}/<scenario-file>.csv` (note: includes the `.xosc` extension)
- Multiple files (aggregated):
  - PDF: `{out-path}/aggregate_report.pdf`
  - CSV: `{out-path}/aggregate_data.csv`
- Multiple files (single reports):
  - `{out-path}/single_reports/` (PDF/CSV per file)


## Reference
ASAM OpenSCENARIO standard: https://www.asam.net/standards/detail/openscenario/
Esmini simulator: https://github.com/esmini/esmini


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
