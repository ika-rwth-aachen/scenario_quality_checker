# Reports and output

← Back to the [README](../README.md)

What the checker writes, how to read it, and what the exit code does and does not tell you.

## Where files land

| Run | File |
| --- | --- |
| Single, PDF | `{out-path}/<scenario-stem>.pdf` |
| Single, CSV | `{out-path}/<scenario-file>.csv` (keeps the `.xosc` in the name) |
| Multiple, aggregated | `{out-path}/aggregate_report.pdf`, `{out-path}/aggregate_data.csv` |
| Multiple, per file | `{out-path}/single_reports/` |

Output directories are created automatically. Reporting is opt-in — see
[CLI reference](cli-reference.md) for the `--out-pdf`, `--out-csv`, `--single` and `--aggregated`
flags.

## Per-scenario CSV

Metadata first, then the findings grouped by category. Empty categories mean nothing was found:

```csv
scenario_file,quality_checker/example_files/envelope_dynamic_error_1.xosc
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

## Aggregated CSV

One row per scenario, six fixed columns. `-` means the stage was never reached, because an earlier
stage failed:

```csv
scenario_file,xml_loadable,xsd_valid,simulation_status,n_file_errors,n_dynamic_errors
quality_checker/example_files/envelope_xsd_valid_v1-2.xosc,True,True,not done,0,0
quality_checker/example_files/envelope_file_error_1.xosc,True,True,not done,2,1
quality_checker/example_files/envelope_xsd_not_valid_1.xosc,True,False,not done,-,-
quality_checker/example_files/envelope_xml_not_loadable.xosc,False,False,not done,-,-
```

## Exit codes

> [!IMPORTANT]
> **Findings do not change the exit code.** Both commands exit `0` whether the scenario is clean or
> full of errors; a non-zero exit means the tool itself failed (bad threshold values, failed esmini
> run). If you want CI to fail on findings, parse `aggregate_data.csv` and decide there — for
> example, fail when any row has a non-zero `n_file_errors` or `n_dynamic_errors`.
>
> Two input mistakes are also silent: a `--files-path` that is not a directory logs an error and
> produces no reports, and a `--file-path` that does not exist is reported as `xml_loadable,False`.
> Both still exit `0`.

## See also

- [CLI reference](cli-reference.md) — the flags that decide which of these files are written
