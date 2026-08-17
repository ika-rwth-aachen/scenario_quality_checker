/* Shared helpers, mode switching, threshold handling and form submission. */

const $ = (selector) => document.querySelector(selector);

const state = {
  mode: "single",
  defaults: null,
  result: null,
  batch: null,
};

/** Fetch wrapper that turns API error payloads into thrown Errors. */
async function api(path, options = {}, parseJson = true) {
  const response = await fetch(path, options);
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch (error) {
      /* Keep the status text when the body is not JSON. */
    }
    throw new Error(detail);
  }
  return parseJson ? response.json() : response;
}

/** Save a fetched Response to disk under the given filename. */
async function downloadResponse(response, filename) {
  const url = URL.createObjectURL(await response.blob());
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function setStatus(text, loading = false) {
  const status = $("#status");
  status.textContent = text;
  status.classList.toggle("loading", loading);
}

function setError(message) {
  const element = $("#error");
  element.textContent = message || "";
  element.hidden = !message;
}

/** Build an element with optional class, text and children. */
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined) return "-";
  return Number(value).toPrecision(digits).replace(/\.?0+$/, "") || String(value);
}

/* --- Mode switching --------------------------------------------------- */

function setMode(mode) {
  state.mode = mode;
  $("#tab-single").classList.toggle("active", mode === "single");
  $("#tab-batch").classList.toggle("active", mode === "batch");
  $("#single-inputs").hidden = mode !== "single";
  $("#batch-inputs").hidden = mode !== "batch";
  $("#submit").textContent = mode === "single" ? "Check quality" : "Check all files";
  setError("");
}

$("#tab-single").onclick = () => setMode("single");
$("#tab-batch").onclick = () => setMode("batch");

/* --- Thresholds ------------------------------------------------------- */

const THRESHOLD_FIELDS = {
  acceleration_warning: "#acceleration-warning",
  acceleration_error: "#acceleration-error",
  sideslip_warning: "#sideslip-warning",
  sideslip_error: "#sideslip-error",
};

function applyThresholds(values) {
  Object.entries(THRESHOLD_FIELDS).forEach(([name, selector]) => {
    $(selector).value = values[name];
  });
}

/** Only send thresholds the user actually changed. */
function thresholdFormData(data) {
  Object.entries(THRESHOLD_FIELDS).forEach(([name, selector]) => {
    const value = $(selector).value;
    if (value !== "" && Number(value) !== state.defaults[name]) {
      data.append(name, value);
    }
  });
}

$("#reset-thresholds").onclick = () => applyThresholds(state.defaults);

async function loadThresholds() {
  const payload = await api("/api/thresholds");
  state.defaults = payload.defaults;
  applyThresholds(payload.defaults);
}

async function loadExamples() {
  const payload = await api("/api/examples");
  const select = $("#example-input");
  payload.examples.forEach((name) => {
    select.appendChild(element("option", null, name)).value = name;
  });
}

/* --- File inputs ------------------------------------------------------ */

/*
 * A native file input cannot be unselected, so each one gets an explicit
 * Remove button. The buttons are type="button": inside a form a bare button
 * submits, which would start a check instead of clearing the field.
 */

const FILE_INPUTS = [
  ["#scenario-input", "#scenario-remove"],
  ["#map-input", "#map-remove"],
  ["#batch-input", "#batch-remove"],
];

/** An uploaded scenario wins over the example, so show that the list is inert. */
function syncExampleAvailability() {
  const hasScenario = $("#scenario-input").files.length > 0;
  // A disabled select keeps its value, so removing the file restores the choice.
  $("#example-input").disabled = hasScenario;
  $("#example-hint").hidden = !hasScenario;
}

/** Reveal each Remove button only while its input holds a file. */
function syncFileInputs() {
  FILE_INPUTS.forEach(([inputSelector, buttonSelector]) => {
    $(buttonSelector).hidden = $(inputSelector).files.length === 0;
  });
  syncExampleAvailability();
}

FILE_INPUTS.forEach(([inputSelector, buttonSelector]) => {
  $(inputSelector).addEventListener("change", () => {
    setError("");
    syncFileInputs();
  });
  $(buttonSelector).addEventListener("click", () => {
    $(inputSelector).value = "";
    setError("");
    syncFileInputs();
  });
});

/* --- Submission ------------------------------------------------------- */

async function submitSingle() {
  const data = new FormData();
  const scenario = $("#scenario-input").files[0];
  const map = $("#map-input").files[0];
  const example = $("#example-input").value;

  if (scenario) {
    data.append("scenario", scenario);
  } else if (example) {
    data.append("example", example);
  } else {
    throw new Error("Choose an OpenSCENARIO file or one of the examples.");
  }
  if (map) data.append("map", map);
  thresholdFormData(data);

  const result = await api("/api/checks", { method: "POST", body: data });
  state.result = result;
  renderSingle(result);
}

async function submitBatch() {
  const files = $("#batch-input").files;
  if (!files.length) throw new Error("Choose one or more scenario files, or a .zip archive.");

  const data = new FormData();
  Array.from(files).forEach((file) => data.append("scenarios", file));
  thresholdFormData(data);

  const batch = await api("/api/batches", { method: "POST", body: data });
  state.batch = batch;
  renderBatch(batch);
}

/* A form that fails constraint validation never fires submit, so the click is
   caught here to explain why rather than appearing to do nothing. */
$("#submit").addEventListener("click", () => {
  const form = $("#check-form");
  if (!form.checkValidity()) {
    const invalid = form.querySelector(":invalid");
    setError(invalid ? invalid.validationMessage : "Please correct the highlighted fields.");
  }
});

$("#check-form").onsubmit = async (event) => {
  event.preventDefault();
  setError("");
  $("#submit").disabled = true;
  setStatus("Checking…", true);
  try {
    if (state.mode === "single") {
      await submitSingle();
    } else {
      await submitBatch();
    }
    setStatus("");
  } catch (error) {
    setError(error.message);
    setStatus("");
  } finally {
    $("#submit").disabled = false;
  }
};

/* --- Startup ---------------------------------------------------------- */

// A reload can restore a previous file selection, so start from the real state.
syncFileInputs();

(async () => {
  try {
    await Promise.all([loadThresholds(), loadExamples()]);
  } catch (error) {
    setError(`Could not reach the server: ${error.message}`);
  }
})();
