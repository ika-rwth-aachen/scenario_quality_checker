/* Render the detailed result of one checked scenario. */

const CATEGORY_LABELS = {
  xsd: "Schema",
  entity_definition: "Entities",
  init_position: "Initial positions",
  intersection: "Initial positions",
  in_out: "Entities",
  position_resolution: "Map",
  acceleration: "Dynamics",
  sideslip: "Dynamics",
};

function statusBadges(status) {
  const badges = element("div", "badges");
  const entries = [
    ["XML loadable", status.xml_loadable],
    ["Schema valid", status.xsd_valid],
    ["Scenario parsed", status.scenario_parsed],
  ];
  entries.forEach(([label, ok]) => {
    badges.appendChild(element("span", `badge ${ok ? "ok" : "bad"}`, `${label}: ${ok ? "yes" : "no"}`));
  });
  return badges;
}

function countBadges(counts) {
  const badges = element("div", "badges");
  badges.appendChild(
    element("span", `badge ${counts.errors ? "bad" : "ok"}`, `${counts.errors} errors`)
  );
  badges.appendChild(
    element("span", `badge ${counts.warnings ? "warn" : "ok"}`, `${counts.warnings} warnings`)
  );
  return badges;
}

function metadataList(metadata) {
  const list = element("dl", "meta");
  const roadUsers = metadata.road_users;
  const byType = Object.entries(roadUsers.by_type || {})
    .map(([type, count]) => `${count} ${type}`)
    .join(", ");

  const rows = [
    ["OpenSCENARIO version", metadata.version || "-"],
    ["Author", metadata.author || "-"],
    ["Created", metadata.date || "-"],
    ["Road users", byType ? `${roadUsers.total} (${byType})` : String(roadUsers.total)],
  ];
  rows.forEach(([label, value]) => {
    list.appendChild(element("dt", null, label));
    list.appendChild(element("dd", null, value));
  });
  return list;
}

function findingItem(finding) {
  const item = element("li", `finding ${finding.severity}`);
  item.appendChild(
    element("span", "finding-message", `${CATEGORY_LABELS[finding.category] || finding.category}: ${finding.message}`)
  );

  const details = [];
  if (finding.peak_value !== undefined) {
    let detail = `peak ${formatNumber(finding.peak_value)} ${finding.unit}`;
    if (finding.peak_time !== undefined) detail += ` at t = ${formatNumber(finding.peak_time)} s`;
    details.push(detail);
  }
  if (finding.threshold !== undefined) {
    details.push(`${finding.severity} limit ${formatNumber(finding.threshold)} ${finding.unit || ""}`.trim());
  }
  if (details.length) {
    item.appendChild(element("span", "finding-detail", details.join(" · ")));
  }
  return item;
}

function findingsSection(result) {
  const container = document.createDocumentFragment();
  const showErrors = $("#show-errors").checked;
  const showWarnings = $("#show-warnings").checked;

  const groups = [
    ["Problems", "error", showErrors],
    ["Warnings", "warning", showWarnings],
  ];

  let rendered = 0;
  groups.forEach(([title, severity, visible]) => {
    if (!visible) return;
    const findings = result.findings.filter((finding) => finding.severity === severity);
    if (!findings.length) return;
    rendered += findings.length;
    container.appendChild(element("h3", null, `${title} (${findings.length})`));
    const list = element("ul", "findings");
    findings.forEach((finding) => list.appendChild(findingItem(finding)));
    container.appendChild(list);
  });

  if (!rendered) {
    container.appendChild(
      element("p", "placeholder", result.findings.length ? "Nothing to show for the selected severities." : "No issues found.")
    );
  }
  return container;
}

/*
 * The charts carry information no alternative text can reasonably restate, so
 * the peak values behind them are listed as text and the CSV is named as the
 * full data equivalent. The <img> itself is alt="" because the <figcaption>
 * already names it -- repeating the label would announce it twice.
 */
function plotsSummary(findings) {
  const peaks = findings.filter((finding) => finding.peak_value !== undefined);
  const text = peaks.length
    ? `Peaks in this scenario: ${peaks
        .map((finding) => `${CATEGORY_LABELS[finding.category] || finding.category} ${formatNumber(finding.peak_value)} ${finding.unit || ""}`.trim())
        .join("; ")}. Download the CSV report below for the full series.`
    : "No threshold peaks were recorded. Download the CSV report below for the full series.";
  return element("p", "plots-summary", text);
}

function plotsSection(plots, findings) {
  const container = document.createDocumentFragment();
  if (!plots.length) return container;
  container.appendChild(element("h3", null, "Dynamics"));
  container.appendChild(plotsSummary(findings));
  const grid = element("div", "plots");
  plots.forEach((plot) => {
    const figure = element("figure");
    const image = element("img");
    image.src = plot.url;
    image.alt = "";
    image.loading = "lazy";
    const caption = element("figcaption", null, plot.label);
    caption.id = `plot-caption-${plot.name}`;
    figure.setAttribute("aria-labelledby", caption.id);
    figure.appendChild(image);
    figure.appendChild(caption);
    const wrapper = element("div", "plot");
    wrapper.appendChild(figure);
    grid.appendChild(wrapper);
  });
  container.appendChild(grid);
  return container;
}

function downloadButton(label, url, filename) {
  const button = element("button", "download", label);
  button.type = "button";
  button.onclick = async () => {
    button.disabled = true;
    setStatus(`Preparing ${filename}…`, true);
    try {
      const response = await api(url, {}, false);
      await downloadResponse(response, filename);
      setStatus("");
    } catch (error) {
      setError(error.message);
      setStatus("");
    } finally {
      button.disabled = false;
    }
  };
  return button;
}

/** Render one scenario result into the result panel. */
function renderSingle(result, backLink = null) {
  $("#result-title").textContent = result.file_name;
  setDocumentTitle(result.file_name);
  $("#result-actions").hidden = false;

  const target = $("#result");
  target.replaceChildren();

  if (backLink) target.appendChild(backLink);
  target.appendChild(statusBadges(result.status));
  target.appendChild(countBadges(result.counts));
  target.appendChild(metadataList(result.metadata));

  if (result.map && result.map.note) {
    target.appendChild(element("p", "note", result.map.note));
  }

  target.appendChild(findingsSection(result));
  target.appendChild(plotsSection(result.plots, result.findings));

  const stem = result.file_name.replace(/\.xosc$/i, "");
  const downloads = element("div", "downloads");
  downloads.appendChild(downloadButton("Download PDF report", result.downloads.pdf, `${stem}.pdf`));
  downloads.appendChild(downloadButton("Download CSV report", result.downloads.csv, `${stem}.csv`));
  target.appendChild(downloads);
}

/* Re-render on severity filter changes, keeping the current result. */
["#show-errors", "#show-warnings"].forEach((selector) => {
  $(selector).onchange = () => {
    if (state.result) renderSingle(state.result, state.backLink ? state.backLink() : null);
  };
});
