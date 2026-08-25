# Web interface

← Back to the [README](../README.md)

The full feature set, HTTP API and configuration of the browser application. For installing and
starting it, see the *Web interface* section of the [README](../README.md). For running it in front
of real users, see [Deployment](deployment.md).

## What the web interface offers

- **Single scenario**: upload one `.xosc`, optionally with the OpenDRIVE map it references, and get
  the status, metadata, findings grouped by severity (each dynamics finding with the entity, its
  measured peak, the time of the peak and the limit it exceeded), the four plots, and the PDF/CSV
  report.
- **Batch**: upload several `.xosc` files or one `.zip` and get the aggregated table, the aggregated
  PDF/CSV, and a drill-down into any single file.
- **Thresholds**: override the acceleration and sideslip limits per run without affecting anyone else
  using the same server.
- **Examples**: check any of the bundled `quality_checker/example_files/` without uploading.
- **Help**: an in-app dialog explaining the check stages, the finding categories, the bundled
  examples and where the default thresholds come from, served from `quality_checker/webapp/help.md`.
- **About**: what the tool does, how to contribute, and the SYNERGIES acknowledgement, served from
  `quality_checker/webapp/about.md`.

## HTTP API

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
| DELETE | `/api/session` | Forget this session's uploads and results immediately |

Runs are readable only by the browser session that created them.

```console
$ curl -s localhost:8001/api/thresholds
{"defaults":{"acceleration_warning":9.8,"acceleration_error":29.4,"sideslip_warning":0.1,"sideslip_error":0.2},"units":{"acceleration":"m/s^2","sideslip":"rad"}}
```

## Configuration

| Variable | Default | Meaning |
| --- | --- | --- |
| `SQC_PORT` | `8001` | Port to serve on |
| `SQC_MAX_UPLOAD_BYTES` | `20971520` | Per-file upload limit |
| `SQC_MAX_BATCH_FILES` | `50` | Files accepted in one batch |
| `SQC_MAX_ZIP_UNCOMPRESSED_BYTES` | `209715200` | Expanded size limit for archives |
| `SQC_MAX_ZIP_COMPRESSION_RATIO` | `200` | Refuse archive members expanding further than this |
| `SQC_MAX_REQUEST_BYTES` | `268435456` | Absolute ceiling on one request body |
| `SQC_SESSION_TTL_SECONDS` | `3600` | How long results stay available |
| `SQC_MAX_SESSIONS` | `200` | Concurrent sessions before the least recently used are evicted |
| `SQC_SESSION_EVICTION_GRACE_SECONDS` | `120` | A session active this recently is never evicted |
| `SQC_MAX_RUNS_PER_SESSION` | `100` | Runs kept per session before the oldest are dropped |
| `SQC_MAX_BATCHES_PER_SESSION` | `10` | Batches kept per session |
| `SQC_RUN_TIMEOUT_SECONDS` | `120` | Time limit for a single check |
| `SQC_MAX_QUEUED_CHECKS` | `8` | Checks queued for the worker before new ones get 503 |
| `SQC_RATE_LIMIT_REQUESTS` | `60` | Checks accepted per address per window (`0` disables) |
| `SQC_RATE_LIMIT_WINDOW_SECONDS` | `60` | Length of the rate-limit window |
| `SQC_SECURE_COOKIES` | `auto` | `auto` follows the request scheme; `true`/`false` force it |
| `SQC_FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-*` headers are trusted |
| `SQC_MAX_PARAMETER_SUBSTITUTIONS` | `50000` | Parameter references resolved per scenario |
| `SQC_MAX_PROCESSED_SCENARIO_BYTES` | `67108864` | Size limit after parameter expansion |
| `SQC_EXAMPLE_DIR` / `SQC_BRANDING_DIR` | bundled | Override where examples and branding are served from |

The server binds `0.0.0.0`. Checks run on a single worker thread, because the checker and matplotlib
keep global state. Instances may share the working root (`$TMPDIR/scenario-quality-checker-web`):
each session owns its own subdirectory, and startup cleanup only removes leftovers older than
`SQC_SESSION_TTL_SECONDS`, so a restart never deletes a sibling instance's uploads.

> [!IMPORTANT]
> Some of these variables carry deployment obligations — `SQC_FORWARDED_ALLOW_IPS` and
> `SQC_SECURE_COOKIES` in particular, and `SQC_RUN_TIMEOUT_SECONDS` does less than its name
> suggests. Read [Deployment](deployment.md) before exposing the app to anyone.

## See also

- [Deployment](deployment.md) — hardening, session affinity, and the legal notices
- [Troubleshooting](troubleshooting.md) — startup and headless-rendering problems
