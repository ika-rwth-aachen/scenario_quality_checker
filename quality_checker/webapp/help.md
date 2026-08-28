# scenario.quality.checker help

scenario.quality.checker reads an OpenSCENARIO file (`.xosc`), validates it against the
ASAM OpenSCENARIO schema, looks for structural problems in the scenario description, and
checks whether the described motion is physically plausible. The result is a list of
findings, four dynamics plots, and a PDF and CSV report.

## What the checker does

The check runs in stages, and each stage only runs if the previous one passed. This is what
the three status badges above the findings mean, and why a batch row can show `-` instead
of a count.

1. **XML loadable** - the file parses as XML at all.
2. **Schema valid** - the file is validated against the ASAM OpenSCENARIO schema matching
   the version declared in its own header. Schemas for OpenSCENARIO 0.9, 1.0, 1.1, 1.2 and
   1.3 are bundled with the application.
3. **Scenario parsed** - the scenario is loaded and its parameter declarations are expanded,
   which is what makes the metadata and the checks below available.
4. **Checks** - the structural checks and the dynamics checks described under
   *Reading the result*.

## Checking a single scenario

1. Choose an OpenSCENARIO file. Only `.xosc` is accepted, at most 20 MiB.
2. Optionally add the OpenDRIVE map, `.xodr` or `.xml`. It is needed to resolve lane
   positions and to draw the road network. Without it, every lane position that cannot be
   resolved is reported as a **Map** warning.
3. Optionally open **Thresholds** to change the limits used for this run.
4. Press **Check quality**.

An uploaded map is stored under exactly the path the scenario names in
`RoadNetwork/LogicFile`, so a relative reference such as `../xodr/map.xodr` resolves. When
that cannot work, the result panel says so:

- the scenario references a map, but none was uploaded - upload it to resolve lane
  positions and draw the road network;
- a map was uploaded, but the scenario references none - the map is not used by the checks;
- the reference points outside the upload area - the map is stored, but not used.

## Trying a bundled example

Leave the file picker empty, pick an entry from **&hellip; or pick a bundled example**, and
press **Check quality**. An uploaded file always takes precedence: as soon as one is
selected, the example dropdown is ignored.

The example names say which stage they exercise, so you can pick the kind of finding you
want to see:

| Name | What it shows |
| --- | --- |
| `envelope_xml_loadable`, `envelope_xml_not_loadable` | the first stage passing and failing |
| `envelope_xsd_not_valid_1` &hellip; `_6` | schema violations - the check stops at stage 2 |
| `envelope_xsd_valid_v1-0` &hellip; `v1-3` | schema-clean files in each supported OpenSCENARIO version |
| `envelope_scenario_loadable` | a file that reaches every stage |
| `envelope_file_error_1` &hellip; `_5` | structural findings - undeclared entities, identical or overlapping start positions, missing add or remove actions |
| `envelope_dynamic_error_1`, `_2` | acceleration and sideslip-angle limits being exceeded |

Examples are checked without a map, so lane-position **Map** warnings are expected and are
not a defect of the example.

## Checking several scenarios at once

The **Batch** tab takes several `.xosc` files and at most one `.zip` archive - at most 50
files in total, and the archive may expand to at most 200 MiB. A selection holding a second
archive is refused. Every `.xosc` in the selection is checked and summarised in one table.

The table repeats the stages as columns. A `-` in the error or warning columns means the
stage was never reached because an earlier one failed. Selecting a row opens the full
single-scenario view for that file; the aggregated PDF and CSV cover the whole batch.

## Reading the result

**Status badges** report the three stages above. **Counts** show how many errors and
warnings were found in total; the *Errors* and *Warnings* checkboxes only filter the list
that is displayed and do not re-run the check. **Metadata** lists the OpenSCENARIO version,
the author, the creation date, and the road users by type as declared in the file.

Each finding is prefixed with the category it belongs to:

| Category | Meaning |
| --- | --- |
| Schema | the file violates the OpenSCENARIO schema for the version it declares |
| Entities | an entity is used in the story without being declared, or it appears or disappears without a matching add or remove action |
| Initial positions | two entities start at the identical position, or their bounding boxes overlap at the start of the scenario |
| Map | a lane position could not be resolved, usually because the OpenDRIVE map is missing or invalid |
| Dynamics | the acceleration or the sideslip angle of an entity exceeded a limit |

A dynamics finding names the entity, its peak value, the time of that peak, and the limit it
crossed. A value above the error limit is reported as an error, a value above the warning
limit as a warning.

The **Dynamics** plots show speed, acceleration, sideslip angle and the vehicle paths. The
CSV report contains the full time series behind them.

In the web interface the dynamics are derived from the trajectories declared in the
scenario, not from a simulation. This is why `simulation_status` always reads `not done`.

Each check offers a **PDF** and a **CSV** report for download, and a batch additionally
offers the aggregated pair.

## Thresholds and where the defaults come from

| Limit | Default | Source |
| --- | --- | --- |
| Acceleration warning | 9.8 m/s&sup2; | frequently used as the physical limit, about 1 g |
| Acceleration error | 29.4 m/s&sup2; | Commission Implementing Regulation (EU) 2022/1426 of 5 August 2022, Annex III, 1.3.2 |
| Sideslip angle warning | 0.1 rad | [World Electric Vehicle Journal 12(1), 42](https://www.mdpi.com/2032-6653/12/1/42) |
| Sideslip angle error | 0.2 rad | [IET Intelligent Transport Systems, 10.1049/iet-its.2020.0385](https://ietresearch.onlinelibrary.wiley.com/doi/10.1049/iet-its.2020.0385) |

Values entered under **Thresholds** apply only to your own run and do not affect anyone else
using the same server. **Reset to defaults** restores the values in this table.

## Limits and your data

Uploads are limited to 20 MiB per file and 50 files per batch, and one address may start at
most 60 checks per minute. Uploads, plots and reports are stored in a temporary directory
for the duration of your session and are deleted about an hour after your last request.

The **Data privacy** button in the header describes this processing in full, and its
**Delete my uploads now** action removes everything immediately.

## If something goes wrong

- *"&hellip; must be one of &hellip;"* - the file has the wrong extension. Scenarios must be
  `.xosc`, maps `.xodr` or `.xml`.
- *"&hellip; exceeds the &hellip; byte upload limit"* or *"Request body exceeds &hellip;"* -
  the file or the whole selection is too large. Split the batch or reduce the file.
- *"&hellip; is empty"* - the selected file has no content.
- *"Too many checks from this address"* - the rate limit was reached. Wait for the current
  minute to pass.
- *"The service is at capacity"* - too many checks are running. Try again in a few minutes.
- *"Provide a scenario file or the name of an example"* - neither a file nor an example was
  selected.
- A check that reports no schema at all - the `revMajor` and `revMinor` in the file header
  are outside the bundled OpenSCENARIO versions 0.9 to 1.3.