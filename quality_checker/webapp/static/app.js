/* Shared helpers, mode switching, threshold handling and form submission. */

const $ = (selector) => document.querySelector(selector);

const state = {
  mode: "single",
  defaults: null,
  result: null,
  batch: null,
  // Rendered once and kept: the notice is a packaged file that cannot change
  // while the page is open.
  privacyNotice: null,
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

/* #status is role="status" and #error is role="alert", so writing to them is
   what announces progress and failures to a screen reader. */

function setStatus(text, loading = false) {
  const status = $("#status");
  status.textContent = text;
  status.classList.toggle("loading", loading);
}

function setError(message) {
  const element = $("#error");
  element.textContent = message || "";
  element.hidden = !message;
  if (!message) clearInvalid();
}

const PAGE_TITLE = "scenario quality checker";

/** Keep the tab title in sync with what the result panel shows. */
function setDocumentTitle(subject) {
  document.title = subject ? `${subject} · ${PAGE_TITLE}` : PAGE_TITLE;
}

/** Build an element with optional class, text and children. */
function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

/** Em dash for "no value", used by every formatter so they agree. */
const NO_VALUE = "—";

function formatNumber(value, digits = 3) {
  if (value === null || value === undefined) return NO_VALUE;
  return Number(value).toPrecision(digits).replace(/\.?0+$/, "") || String(value);
}

/** Reset the result panel to its initial empty state. */
function clearResult(titleText = "Result") {
  state.result = null;
  state.batch = null;
  state.backLink = null;
  $("#result-title").textContent = titleText;
  $("#result-actions").hidden = true;
  $("#result").replaceChildren(
    element("p", "placeholder", "Upload an OpenSCENARIO file to see its findings, dynamics plots and reports.")
  );
  setDocumentTitle(null);
}

/*
 * A fresh result replaces the panel wholesale, so keyboard and screen reader
 * users are moved to its heading rather than left on the submit button.
 */
function focusResult() {
  $("#result-title").focus();
}

/* --- Mode switching --------------------------------------------------- */

const TABS = ["#tab-single", "#tab-batch"];
const MODES = ["single", "batch"];

function setMode(mode, moveFocus = false) {
  state.mode = mode;
  MODES.forEach((name, index) => {
    const tab = $(TABS[index]);
    const selected = name === mode;
    tab.classList.toggle("active", selected);
    tab.setAttribute("aria-selected", String(selected));
    // Roving tabindex: only the selected tab is a Tab stop, arrows do the rest.
    tab.tabIndex = selected ? 0 : -1;
    if (selected && moveFocus) tab.focus();
  });
  $("#single-inputs").hidden = mode !== "single";
  $("#batch-inputs").hidden = mode !== "batch";
  $("#submit").textContent = mode === "single" ? "Check quality" : "Check all files";
  setError("");
}

TABS.forEach((selector, index) => {
  $(selector).addEventListener("click", () => setMode(MODES[index]));
});

/* Arrow/Home/End navigation, as expected of a role="tablist". */
$('[role="tablist"]').addEventListener("keydown", (event) => {
  const current = MODES.indexOf(state.mode);
  let next = null;
  if (event.key === "ArrowRight") next = (current + 1) % MODES.length;
  else if (event.key === "ArrowLeft") next = (current - 1 + MODES.length) % MODES.length;
  else if (event.key === "Home") next = 0;
  else if (event.key === "End") next = MODES.length - 1;
  if (next === null) return;
  event.preventDefault();
  setMode(MODES[next], true);
});

/* --- Thresholds ------------------------------------------------------- */

const THRESHOLD_FIELDS = {
  acceleration_warning: "#acceleration-warning",
  acceleration_error: "#acceleration-error",
  sideslip_warning: "#sideslip-warning",
  sideslip_error: "#sideslip-error",
};

const THRESHOLD_STORAGE_KEY = "sqc.thresholds";

function applyThresholds(values) {
  Object.entries(THRESHOLD_FIELDS).forEach(([name, selector]) => {
    $(selector).value = values[name];
  });
  syncThresholdBadge();
  saveThresholds();
}

/** Names of the thresholds the user has moved away from the server defaults. */
function changedThresholds() {
  return Object.entries(THRESHOLD_FIELDS).filter(([name, selector]) => {
    const value = $(selector).value;
    return value !== "" && Number(value) !== state.defaults[name];
  });
}

/* The <details> is collapsed by default, so a modified threshold would
   otherwise silently change the outcome of a check. */
function syncThresholdBadge() {
  const badge = $("#thresholds-badge");
  if (!state.defaults) {
    badge.hidden = true;
    return;
  }
  const count = changedThresholds().length;
  badge.textContent = count ? `${count} modified` : "";
  badge.hidden = count === 0;
}

/** Only send thresholds the user actually changed. */
function thresholdFormData(data) {
  changedThresholds().forEach(([name, selector]) => data.append(name, $(selector).value));
}

function saveThresholds() {
  const values = {};
  Object.entries(THRESHOLD_FIELDS).forEach(([name, selector]) => {
    values[name] = $(selector).value;
  });
  try {
    localStorage.setItem(THRESHOLD_STORAGE_KEY, JSON.stringify(values));
  } catch (error) {
    /* Private browsing or a full quota: thresholds simply do not persist. */
  }
}

function storedThresholds() {
  try {
    return JSON.parse(localStorage.getItem(THRESHOLD_STORAGE_KEY) || "null");
  } catch (error) {
    return null;
  }
}

$("#reset-thresholds").onclick = () => applyThresholds(state.defaults);

Object.values(THRESHOLD_FIELDS).forEach((selector) => {
  $(selector).addEventListener("input", () => {
    syncThresholdBadge();
    saveThresholds();
  });
});

async function loadThresholds() {
  const payload = await api("/api/thresholds");
  state.defaults = payload.defaults;
  // A stored set wins, so a reload keeps whatever the user last worked with.
  applyThresholds({ ...payload.defaults, ...(storedThresholds() || {}) });
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

/*
 * An uploaded scenario wins over the example. The select stays enabled rather
 * than disabled: a disabled control drops out of the accessibility tree and
 * out of the tab order, so its explanation would never be reachable.
 */
function syncExampleAvailability() {
  const hasScenario = $("#scenario-input").files.length > 0;
  $("#example-hint").textContent = hasScenario
    ? "Ignored: the uploaded file will be checked instead of an example."
    : "Used when no OpenSCENARIO file is uploaded.";
  $("#example-input").classList.toggle("inert-choice", hasScenario);
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

/* --- Validation ------------------------------------------------------- */

let invalidControl = null;

/** Drop the invalid marking from whichever control last carried it. */
function clearInvalid() {
  if (!invalidControl) return;
  invalidControl.removeAttribute("aria-invalid");
  if (invalidControl.getAttribute("aria-describedby") === "error") {
    invalidControl.removeAttribute("aria-describedby");
  }
  invalidControl = null;
}

/* #error is the only place a message is shown, so the offending control has to
   point at it explicitly to satisfy "errors are identified programmatically". */
function markInvalid(control) {
  clearInvalid();
  if (!control) return;
  control.setAttribute("aria-invalid", "true");
  if (!control.hasAttribute("aria-describedby")) {
    control.setAttribute("aria-describedby", "error");
  }
  invalidControl = control;
  /* The threshold fields live in a collapsed <details>; focusing a control
     inside one moves focus somewhere the user cannot see. */
  const collapsed = control.closest("details:not([open])");
  if (collapsed) collapsed.open = true;
  control.focus();
}

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
    const error = new Error("Choose an OpenSCENARIO file or one of the examples.");
    error.control = $("#scenario-input");
    throw error;
  }
  if (map) data.append("map", map);
  thresholdFormData(data);

  const result = await api("/api/checks", { method: "POST", body: data });
  state.result = result;
  renderSingle(result);
  return `${result.file_name}: ${result.counts.errors} problems, ${result.counts.warnings} warnings.`;
}

async function submitBatch() {
  const files = $("#batch-input").files;
  if (!files.length) {
    const error = new Error("Choose one or more scenario files, or a .zip archive.");
    error.control = $("#batch-input");
    throw error;
  }

  const data = new FormData();
  Array.from(files).forEach((file) => data.append("scenarios", file));
  thresholdFormData(data);

  const batch = await api("/api/batches", { method: "POST", body: data });
  state.batch = batch;
  renderBatch(batch);
  return `Batch checked: ${batch.files.length} scenarios.`;
}

/* A form that fails constraint validation never fires submit, so the click is
   caught here to explain why rather than appearing to do nothing. */
$("#submit").addEventListener("click", () => {
  const form = $("#check-form");
  if (!form.checkValidity()) {
    const invalid = form.querySelector(":invalid");
    setError(invalid ? invalid.validationMessage : "Please correct the highlighted fields.");
    markInvalid(invalid);
  }
});

$("#check-form").onsubmit = async (event) => {
  event.preventDefault();
  setError("");
  $("#submit").disabled = true;
  setStatus("Checking…", true);
  try {
    const summary = state.mode === "single" ? await submitSingle() : await submitBatch();
    setStatus(summary);
    focusResult();
  } catch (error) {
    // The panel would otherwise keep a result that no longer matches the form.
    clearResult();
    setError(error.message);
    setStatus("");
    markInvalid(error.control || null);
  } finally {
    $("#submit").disabled = false;
  }
};

/* --- Data privacy ----------------------------------------------------- */

/* The notice is rendered from a Markdown file shipped with the application and
   rendered server-side with embedded HTML disabled, so it is trusted markup -
   which is what makes innerHTML the right assignment here. */
async function showDataPrivacyNotice() {
  const content = $("#data-privacy-content");
  if (!state.privacyNotice) {
    try {
      state.privacyNotice = (await api("/api/data-privacy")).html;
    } catch (error) {
      // Reported inside the dialog: the notice is what the user came for, and
      // the header status line is easy to miss once the dialog covers it.
      content.replaceChildren(
        element("p", "error", `Could not load the notice: ${error.message}`)
      );
      $("#data-privacy-dialog").showModal();
      return;
    }
  }
  content.innerHTML = state.privacyNotice;
  $("#forget-session-status").textContent = "";
  $("#data-privacy-dialog").showModal();
}

$("#data-privacy").addEventListener("click", showDataPrivacyNotice);
$("#close-data-privacy").addEventListener("click", () =>
  $("#data-privacy-dialog").close()
);

/* Erasure on request, rather than only after the retention period. The server
   drops the session directory and clears the cookie; the page then has to let
   go of the results it is still showing, because their run ids are gone. */
$("#forget-session").addEventListener("click", async () => {
  const button = $("#forget-session");
  const status = $("#forget-session-status");
  button.disabled = true;
  status.textContent = "Deleting…";
  try {
    await api("/api/session", { method: "DELETE" });
    clearResult();
    FILE_INPUTS.forEach(([inputSelector]) => {
      $(inputSelector).value = "";
    });
    syncFileInputs();
    setError("");
    setStatus("");
    status.textContent = "Your uploads and reports have been deleted.";
  } catch (error) {
    status.textContent = `Could not delete: ${error.message}`;
  } finally {
    button.disabled = false;
  }
});

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
