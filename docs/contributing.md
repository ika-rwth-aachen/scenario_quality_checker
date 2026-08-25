# Development and contributing

← Back to the [README](../README.md)

## Setting up

```bash
pip install ".[web,dev]"
pytest -q
```

CI runs the same suite on Python 3.10 and 3.11 (`.github/workflows/ci.yml`). The code base is
formatted and linted with [ruff](https://docs.astral.sh/ruff/), which is part of the `dev` extra and
gated in CI: `ruff check .` and `ruff format --check .` must both pass.

## Contributing

There is no separate contributing guide yet. Please open an issue for bugs and feature requests, and
keep pull requests focused:

- add or update tests under `tests/`;
- run `pytest -q` and `ruff check .` before pushing (see *Setting up* above);
- add an example `.xosc` to [`quality_checker/example_files/`](../quality_checker/example_files/)
  when you add a new kind of check.

The project is maintained by the [Institute for Automotive Engineering (ika) at RWTH Aachen
University](https://www.ika.rwth-aachen.de/) and released under the MIT license — see
[LICENSE](../LICENSE). The in-app *About* dialog,
[`quality_checker/webapp/about.md`](../quality_checker/webapp/about.md), carries the same invitation
for users who only ever see the web interface.

## Documentation that ships with the application

Three Markdown files under `quality_checker/webapp/` are served by the running web app rather than
being reference documentation, so they live next to the code that reads them:

| File | Served as |
| --- | --- |
| [`webapp/help.md`](../quality_checker/webapp/help.md) | The in-app **Help** dialog |
| [`webapp/about.md`](../quality_checker/webapp/about.md) | The in-app **About** dialog |
| [`webapp/data_privacy.md`](../quality_checker/webapp/data_privacy.md) | The **Data privacy** dialog |

`data_privacy.md` quotes the server's default limits, and
`tests/test_webapp.py::test_data_privacy_notice_documents_application_processing` asserts on those
figures — see [Deployment](deployment.md#legal-notices) before changing them.
