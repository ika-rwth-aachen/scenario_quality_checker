# scenario.quality.checker data processing

This information supplements the general scenario.center data privacy policy linked
above. It describes processing performed by scenario.quality.checker itself. The operator
of a deployed instance must verify that the general policy applies to its hosting
environment and adapt this supplement if configuration or processing differs.

## Technically necessary session cookie

scenario.quality.checker sets the session cookie `sqc_session`. It contains a randomly
generated identifier and is used exclusively to separate the uploads, check results, and
reports of concurrent browser sessions. It is not used for analytics, advertising, or
cross-site tracking. The cookie is marked `HttpOnly` and `SameSite=Lax`, receives the
`Secure` attribute for HTTPS requests, and expires together with the server-side session.

The cookie is only issued once a request actually creates state. Simply opening the page
or reading the bundled example list does not start a session.

## Uploaded scenarios, maps, and reports

- Uploaded OpenSCENARIO and OpenDRIVE files, the rendered dynamics plots, and the
  generated PDF and CSV reports are stored in a session-specific directory below the
  system temporary directory.
- Sessions and their files are deleted 1 hour after the last request by default. Leftover
  directories from an interrupted run are swept on the same schedule. The deployment
  operator can configure a different retention period.
- At most 100 single checks and 10 batches are kept per session by default. Older ones
  are discarded together with their files.
- Uploads are limited to 20 MiB per file and 50 files per batch by default. A `.zip`
  archive may expand to at most 200 MiB, and one request may carry at most 256 MiB in
  total. The deployment operator can configure all of these limits.
- File contents are never written to the application log.

## Deleting your data immediately

The **Delete my uploads now** button in this dialog ends the session at once: the
server-side session is forgotten, its directory with all uploads, plots, and reports is
deleted, and the session cookie is removed from your browser. Waiting for the retention
period to elapse is not necessary.

## Logs and abuse prevention

The service is anonymous, so it limits how often a single network address may start a
check. For that purpose the application keeps a counter per IP address in memory for the
duration of the current time window, by default 60 checks per 60 seconds. The counters
are not persisted.

When a request is refused - because it was too large, malformed, or over the rate limit -
the application logs the reason together with a correlation identifier, the session
identifier, and the client IP address. Uploaded content is never part of such a log
entry.

Hosting infrastructure and reverse proxies may additionally process access-log data such
as IP address, time, requested URL, and browser information. The general ika data privacy
policy describes this processing for ika-operated infrastructure.

## No third-party services

scenario.quality.checker does not include analytics or advertising services and does not
load fonts, scripts, or other application resources from third parties. The content
security policy sent with every response permits resources from this application only.

## Controller and your rights

The session cookie and the temporary processing described above are necessary to provide
the interactive application requested by the user. The applicable legal basis, controller,
recipients, and contact options are determined by the operator of the deployed instance.
For an ika-operated deployment, consult the linked general ika data privacy policy,
including its sections on website provision, session cookies, storage, and data-subject
rights.
