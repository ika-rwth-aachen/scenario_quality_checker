# scenario-quality-checker
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

## Outputs
- Per-scenario report: PDF summary and/or CSV detail
- Aggregated report: rollup table across a folder of `.xosc` files

## Installation
Install Python 3.9+ (Conda recommended) and the dependencies.

```bash
conda create -n sqc python=3.9
conda activate sqc
pip install -r requirements.txt
```

## Quick start
Single file with PDF and CSV:

```bash
python -m quality_checker quality_check_single `
  --file-path example_files/envelope_dynamic_error_1.xosc `
  --out-path reports/ `
  --schema-path schemas/ `
  --out-pdf --out-csv
```

Multiple files with per-file and aggregated outputs:

```bash
python -m quality_checker quality_check_multiple `
  --files-path example_files/ `
  --out-path reports/ `
  --schema-path schemas/ `
  --single --aggregated --out-pdf --out-csv
```

## Command reference
The CLI is implemented with Typer and is invoked via `python -m quality_checker`.

### `quality_check_single`
Checks one `.xosc` file and optionally creates reports.

Options:
- `--file-path`: input `.xosc` file (required)
- `--out-path`: output directory for reports (default `reports/single_reports/`)
- `--schema-path`: directory containing `OpenSCENARIO_*.xsd` (default `schemas/`)
- `--out-pdf`: create a PDF report
- `--out-csv`: create a CSV report
- `--print-log`: enable log output

### `quality_check_multiple`
Checks all `.xosc` files in a directory. Optionally creates per-file and aggregated reports.

Options:
- `--files-path`: directory with `.xosc` files (required)
- `--out-path`: output directory for reports (default `reports/`)
- `--schema-path`: directory containing `OpenSCENARIO_*.xsd` (default `schemas/`)
- `--single`: create per-file reports under `reports/single_reports/`
- `--aggregated`: create a combined report across all files
- `--out-pdf`: create PDF report(s)
- `--out-csv`: create CSV report(s)
- `--print-log`: enable log output

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