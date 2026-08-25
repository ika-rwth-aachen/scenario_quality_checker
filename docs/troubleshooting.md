# Troubleshooting

← Back to the [README](../README.md)

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
| Nothing happens for a `--files-path` typo | A non-directory path logs an error and exits `0`. See [Exit codes](reports.md#exit-codes) for the full behaviour. |

## See also

- [CLI reference](cli-reference.md) — every option and its default
- [Reports](reports.md) — what gets written where, and why the exit code is always `0`
- [Web interface](web-interface.md) — configuration of the browser application
