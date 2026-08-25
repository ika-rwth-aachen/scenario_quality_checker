# Architecture — how the check works

← Back to the [README](../README.md)

## The check pipeline

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

Each stage only runs if the previous one passed, which is why a report can show `-` instead of a
count — see [Reports](reports.md).

## The same pipeline, from a user's point of view

[`quality_checker/webapp/help.md`](../quality_checker/webapp/help.md) — the in-app help served by the
web interface — describes the same stages in end-user terms, and adds a table of the bundled
example scenarios saying which stage and which finding category each one exercises. It is the
runtime copy: it is served by the application, so it is kept where the app can read it rather than
moved here.

## Further reading

- ASAM OpenSCENARIO standard: https://www.asam.net/standards/detail/openscenario/
- esmini simulator: https://github.com/esmini/esmini
