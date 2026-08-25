# Deployment

← Back to the [README](../README.md)

Everything that has to be true before the web interface faces real users. The environment variables
referenced here are documented in [Web interface](web-interface.md#configuration).

## Deploying it safely

The application is anonymous by design and accepts files from anyone who can reach it. These are not
optional extras — the deployment is not sound without them.

- **Session affinity is required across replicas.** Sessions, runs and batches live in the memory of
  one process. Running several containers behind a round-robin proxy makes users hit an instance
  that has never heard of their run, so they get sporadic 404s on their own results. Either pin a
  session to an instance (sticky sessions on the `sqc_session` cookie) or run a single instance.
- **Terminate TLS and set `SQC_FORWARDED_ALLOW_IPS` to the proxy's address.** Behind a proxy the
  request arrives over plain HTTP, so without this the server cannot tell that the user is on HTTPS
  and the session cookie never gets the `Secure` flag. Setting `SQC_SECURE_COOKIES=true` forces the
  flag on regardless and is the right setting for any HTTPS deployment.
- **Limit request bodies and rates at the proxy too.** The app enforces its own limits
  (`SQC_MAX_REQUEST_BYTES`, `SQC_RATE_LIMIT_REQUESTS`, `SQC_MAX_QUEUED_CHECKS`) so that a
  misconfigured deployment is not wide open, but a proxy sheds that traffic far more cheaply.
- **Run the container as shipped.** `docker/docker-compose.yml` sets `read_only`, `cap_drop: [ALL]`,
  `no-new-privileges`, and CPU, memory and PID limits; the image runs as an unprivileged user. The
  app writes only under `/tmp`, which is a tmpfs.

Two limits are worth knowing precisely, because the names promise more than they deliver:

- `SQC_RUN_TIMEOUT_SECONDS` **bounds the HTTP response, not the work.** A thread in a thread pool
  cannot be cancelled, so a scenario that never terminates keeps the single worker busy after the
  client has already received its 504. `SQC_MAX_QUEUED_CHECKS` is what limits the damage: further
  checks are refused with 503 instead of queueing behind a worker that is not coming back. Killing
  such a check outright would require running the checker in a separate process.
- **CSRF protection rests entirely on `SameSite=Lax`.** There is no CSRF token. The exposure is
  small — a cross-site POST simply arrives without the cookie and creates a fresh, empty session —
  but anything that loosens `SameSite` or introduces cross-origin use needs an origin check or a
  token added at the same time.

## Legal notices

The header carries an **Imprint** link to <https://scenario.center/imprint/> and a **Data privacy**
dialog. The dialog links the general policy at <https://scenario.center/privacy-policy/> and, below
it, renders [`quality_checker/webapp/data_privacy.md`](../quality_checker/webapp/data_privacy.md) — a
supplement describing only what this application itself processes: the `sqc_session` cookie, where
uploads and reports are stored, how long they are kept, the upload limits, and what the audit log
records. The dialog also offers **Delete my uploads now**, which calls `DELETE /api/session` to drop
the session directory and the cookie immediately instead of waiting out `SQC_SESSION_TTL_SECONDS`.

Two things follow for anyone deploying this:

- **The imprint duty attaches to whoever runs the instance.** Outside an ika-operated deployment the
  linked scenario.center imprint is the wrong publisher, and the link has to be repointed.
- **The supplement quotes the defaults from `webapp/server.py`.** Changing `SQC_SESSION_TTL_SECONDS`,
  `SQC_MAX_UPLOAD_BYTES` or `SQC_MAX_BATCH_FILES` makes the notice inaccurate, so edit the Markdown
  in the same change. `tests/test_webapp.py::test_data_privacy_notice_documents_application_processing`
  asserts on those figures so the drift shows up as a failing test rather than as a wrong statement
  to users.

## See also

- [Web interface](web-interface.md) — the full environment-variable table and the HTTP API
