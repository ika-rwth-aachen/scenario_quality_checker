/* Render the aggregated table of a batch and the drill-down into one file. */

const BATCH_COLUMNS = [
  ["Scenario file", (row) => row.file_name],
  ["XML", (row) => (row.xml_loadable ? "ok" : "failed")],
  ["Schema", (row) => (row.xsd_valid ? "ok" : "failed")],
  ["File issues", (row) => formatCount(row.n_file_errors)],
  ["Dynamic issues", (row) => formatCount(row.n_dynamic_errors)],
  ["Problems", (row) => row.n_errors],
  ["Warnings", (row) => row.n_warnings],
];

function formatCount(value) {
  return value === null || value === undefined ? NO_VALUE : value;
}

/** Open one file of the batch in the detailed single view. */
async function openBatchRow(row) {
  setStatus(`Loading ${row.file_name}…`, true);
  try {
    const result = await api(`/api/runs/${row.run_id}`);
    state.result = result;
    state.backLink = () => {
      const back = element("div", "back-link");
      const button = element("button", "secondary", "← Back to the batch summary");
      button.type = "button";
      button.onclick = () => {
        renderBatch(state.batch);
        focusResult();
      };
      back.appendChild(button);
      return back;
    };
    renderSingle(result, state.backLink());
    setStatus(`${result.file_name}: ${result.counts.errors} problems, ${result.counts.warnings} warnings.`);
    focusResult();
  } catch (error) {
    setError(error.message);
    setStatus("");
  }
}

/** Render the aggregated summary table of a batch. */
function renderBatch(batch) {
  state.batch = batch;
  state.result = null;
  state.backLink = null;

  $("#result-title").textContent = `Batch of ${batch.files.length} scenarios`;
  setDocumentTitle(`Batch of ${batch.files.length}`);
  $("#result-actions").hidden = true;

  const target = $("#result");
  target.replaceChildren();

  const totals = batch.files.reduce(
    (sum, row) => ({ errors: sum.errors + row.n_errors, warnings: sum.warnings + row.n_warnings }),
    { errors: 0, warnings: 0 }
  );
  target.appendChild(countBadges(totals));
  target.appendChild(element("p", "placeholder", "Select a file name to see its findings and plots."));

  const scroll = element("div", "table-scroll");
  const table = element("table");
  table.appendChild(
    element("caption", "visually-hidden", "Checked scenarios. Select a file name to open its findings.")
  );
  const head = element("thead");
  const headRow = element("tr");
  BATCH_COLUMNS.forEach(([label]) => {
    const cell = element("th", null, label);
    cell.scope = "col";
    headRow.appendChild(cell);
  });
  head.appendChild(headRow);
  table.appendChild(head);

  const body = element("tbody");
  batch.files.forEach((row) => {
    const tableRow = element("tr");
    BATCH_COLUMNS.forEach(([label, accessor]) => {
      const cell = element("td");
      if (label === "Scenario file") {
        /* A real button rather than a click handler on the <tr>: it is
           reachable by Tab, operable with Enter and Space, gets a focus ring
           and announces itself -- none of which a clickable row does. */
        const open = element("button", "row-open", String(accessor(row)));
        open.type = "button";
        open.onclick = () => openBatchRow(row);
        cell.appendChild(open);
      } else {
        cell.textContent = String(accessor(row));
      }
      if (label === "Problems" && row.n_errors) cell.className = "count-error";
      if (label === "Warnings" && row.n_warnings) cell.className = "count-warning";
      tableRow.appendChild(cell);
    });
    body.appendChild(tableRow);
  });
  table.appendChild(body);
  scroll.appendChild(table);
  target.appendChild(scroll);

  const downloads = element("div", "downloads");
  downloads.appendChild(
    downloadButton("Download aggregated PDF", batch.downloads.pdf, "aggregate_report.pdf")
  );
  downloads.appendChild(
    downloadButton("Download aggregated CSV", batch.downloads.csv, "aggregate_data.csv")
  );
  target.appendChild(downloads);
}
