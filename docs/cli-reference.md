# CLI reference

← Back to the [README](../README.md)

Complete option reference for the two command-line commands. For a first run, see the Quickstart in
the [README](../README.md).

Both commands are available as `scenario-quality-checker <command>` or
`python -m quality_checker <command>`:

| Command | Purpose |
| --- | --- |
| `quality_check_single` | Check one `.xosc` file |
| `quality_check_multiple` | Check every `.xosc` file in a directory, optionally with a rollup |

## `quality_check_single`

| Option | Default | Meaning |
| --- | --- | --- |
| `--file-path` | *(required)* | Input `.xosc` file |
| `--out-path` | `reports/single_reports/` | Output directory for reports |
| `--out-pdf` | off | Write the PDF report |
| `--out-csv` | off | Write the CSV report |
| `--print-log` | off | Emit progress logging |
| `--schema-path` | bundled `quality_checker/schemas/` | Directory containing `OpenSCENARIO_*.xsd` |
| `--esmini-path` | *(none)* | Path to an `esmini` executable; enables simulation-based dynamics |

## `quality_check_multiple`

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

## Options accepted by both

| Option | Default | Meaning |
| --- | --- | --- |
| `--acceleration-warning` | `9.8` m/s² | Acceleration warning limit |
| `--acceleration-error` | `29.4` m/s² | Acceleration error limit |
| `--sideslip-warning` | `0.1` rad | Sideslip (swim) angle warning limit |
| `--sideslip-error` | `0.2` rad | Sideslip (swim) angle error limit |
| `--work-dir` | `./results/tmp` | Directory for intermediate files |

Omitted limits fall back to the defaults in `quality_checker/config.py`. A warning limit must be
positive and must not exceed its matching error limit, otherwise the run fails with a `ValueError`.

## Worked examples

**Tighten the dynamics limits for a comfort-focused review.** Flag anything above 4 m/s²:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path quality_checker/example_files/envelope_dynamic_error_2.xosc \
  --out-path reports/ --out-csv \
  --acceleration-warning 2.5 \
  --acceleration-error 4.0
```

**Judge the dynamics from a simulation instead of the written trajectories.** With `--esmini-path`
the scenario is run headless (`esmini --headless --csv_logger <log> --osc <scenario>`) and the logged
trajectories feed the dynamics checks and plots:

```bash
uv run scenario-quality-checker quality_check_single \
  --file-path quality_checker/example_files/envelope_scenario_loadable.xosc \
  --out-path reports/ --out-pdf \
  --esmini-path /opt/esmini/bin/esmini
```

The scenarios used above live in [`quality_checker/example_files/`](../quality_checker/example_files/).

## Pinned requirements for pip-only workflows

`uv.lock` is the single source of pinned versions; export it with
`uv export --extra web -o requirements.txt` if a pip-only workflow needs a pinned set.

## See also

- [Reports](reports.md) — where the output lands, the CSV formats, and exit-code behaviour
- [Troubleshooting](troubleshooting.md) — what to do when a run produces nothing
