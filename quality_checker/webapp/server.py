"""
Web interface for the Scenario Quality Checker.

Upload an OpenSCENARIO file (optionally with the OpenDRIVE map it references),
get the findings, the dynamics plots and the PDF/CSV reports in the browser.

The checker keeps state in module-level matplotlib figures and writes
intermediate files, so all analysis runs on a single worker thread; the event
loop stays free while a check is in progress.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from ..pdf_report_creator import create_report_multiple
from ..quality_checker import (
    DEFAULT_SCHEMA_PATH,
    FileQualityChecker,
    write_aggregate_csv,
)
from ..thresholds import Thresholds
from .results import PLOT_FILES, serialize_checker, summary_row_json

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parent
STATIC_DIRECTORY = Path(__file__).with_name("static")
EXAMPLE_DIRECTORY = REPOSITORY_ROOT / "example_files"
BRANDING_DIRECTORY = REPOSITORY_ROOT / "assets"

WORK_ROOT = Path(tempfile.gettempdir()) / "scenario-quality-checker-web"
SESSION_COOKIE_NAME = "sqc_session"
SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

ALLOWED_SCENARIO_SUFFIXES = {".xosc"}
ALLOWED_MAP_SUFFIXES = {".xodr", ".xml"}
UPLOAD_CHUNK_BYTES = 1024 * 1024


def _int_from_environment(name, default):
    """Read a positive integer setting from the environment."""
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


MAX_UPLOAD_BYTES = _int_from_environment("SQC_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
MAX_BATCH_FILES = _int_from_environment("SQC_MAX_BATCH_FILES", 50)
MAX_ZIP_UNCOMPRESSED_BYTES = _int_from_environment(
    "SQC_MAX_ZIP_UNCOMPRESSED_BYTES", 200 * 1024 * 1024
)
SESSION_TTL_SECONDS = _int_from_environment("SQC_SESSION_TTL_SECONDS", 3600)
MAX_SESSIONS = _int_from_environment("SQC_MAX_SESSIONS", 200)
RUN_TIMEOUT_SECONDS = _int_from_environment("SQC_RUN_TIMEOUT_SECONDS", 120)
CLEANUP_INTERVAL_SECONDS = 300

# One worker: the checker and matplotlib are not safe to run concurrently, and
# serializing here is cheaper than adding locks around pyplot. The executor is
# owned by the application lifespan, so a restarted app gets a fresh one instead
# of a shut-down pool that rejects every job.
_executor = None


def checker_executor():
    """Return the worker pool that runs the checker, creating it if needed."""
    global _executor
    if _executor is None:
        _executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="sqc-check")
    return _executor


def shutdown_executor():
    """Discard the worker pool so the next run creates a fresh one."""
    global _executor
    if _executor is not None:
        _executor.shutdown(wait=False)
        _executor = None


# ---------------------------------------------------------------------------
# Run and session bookkeeping
# ---------------------------------------------------------------------------


@dataclass
class Run:
    """One checked scenario, kept so plots and reports can be fetched later."""

    run_id: str
    session_id: str
    file_name: str
    directory: Path
    checker: object
    map_info: dict
    plots: list = field(default_factory=list)

    def result(self):
        """Return the structured result for this run."""
        return serialize_checker(
            self.checker, self.run_id, self.file_name, self.plots, self.map_info
        )


@dataclass
class Batch:
    """A group of scenarios checked together, with an aggregated report."""

    batch_id: str
    session_id: str
    directory: Path
    rows: list
    checkers: list


@dataclass
class Session:
    """Per-browser state: the runs it owns and when it was last seen."""

    session_id: str
    last_seen: float = field(default_factory=time.monotonic)
    runs: dict = field(default_factory=dict)
    batches: dict = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)


class SessionStore:
    """In-memory session registry with TTL-based cleanup and a size cap."""

    def __init__(self, ttl_seconds=SESSION_TTL_SECONDS, max_sessions=MAX_SESSIONS):
        self._sessions = {}
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions

    def get_or_create(self, session_id):
        session = self._sessions.get(session_id)
        if session is None:
            self._evict_if_full()
            session = Session(session_id=session_id)
            self._sessions[session_id] = session
        session.last_seen = time.monotonic()
        return session

    def _evict_if_full(self):
        """Drop the least recently used sessions so the store stays bounded."""
        if len(self._sessions) < self._max_sessions:
            return
        self.cleanup_expired()
        while len(self._sessions) >= self._max_sessions:
            oldest = min(self._sessions.values(), key=lambda session: session.last_seen)
            self._sessions.pop(oldest.session_id, None)
            shutil.rmtree(WORK_ROOT / oldest.session_id, ignore_errors=True)

    def cleanup_expired(self):
        """Drop sessions past their TTL and delete their working directories."""
        deadline = time.monotonic() - self._ttl_seconds
        expired = [sid for sid, s in self._sessions.items() if s.last_seen < deadline]
        for session_id in expired:
            self._sessions.pop(session_id, None)
            shutil.rmtree(WORK_ROOT / session_id, ignore_errors=True)
        return expired

    def cleanup_orphaned_directories(self):
        """
        Remove leftover working directories, for example after a restart.

        Only directories that are both unknown to this process and older than the
        session TTL are removed. Being unknown is not enough: another process may
        share the working root - a second worker, a reloaded server, a parallel
        test run - and deleting its freshly written uploads would break requests
        it is still serving.
        """
        if not WORK_ROOT.is_dir():
            return
        deadline = time.time() - self._ttl_seconds
        for directory in WORK_ROOT.iterdir():
            if not directory.is_dir() or directory.name in self._sessions:
                continue
            try:
                if directory.stat().st_mtime >= deadline:
                    continue
            except OSError:
                continue
            shutil.rmtree(directory, ignore_errors=True)


store = SessionStore()


# ---------------------------------------------------------------------------
# Upload handling
# ---------------------------------------------------------------------------


def safe_upload_name(name):
    """Reduce an uploaded filename to a harmless basename."""
    candidate = Path(str(name or "")).name.strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "_", candidate).lstrip(".")
    return candidate or "upload"


def confined_path(base_directory, relative_path, start_directory=None):
    """
    Resolve a scenario-supplied relative path, keeping it inside a directory.

    Args:
        base_directory: Directory the result must stay within.
        relative_path: Untrusted relative path from the scenario file.
        start_directory: Directory the path is relative to, defaults to
            base_directory.
    return: Resolved Path, or None when it would escape base_directory.
    """
    base = base_directory.resolve()
    start = (start_directory or base_directory).resolve()
    try:
        candidate = (start / str(relative_path)).resolve()
    except (OSError, ValueError):
        return None
    if candidate == base or base not in candidate.parents:
        return None
    return candidate


async def store_upload(upload, destination, max_bytes=None):
    """
    Stream an upload to disk, rejecting anything past the size limit.

    Args:
        upload: FastAPI UploadFile.
        destination: Target path; parent directories are created.
        max_bytes: Maximum accepted size, defaults to MAX_UPLOAD_BYTES. Read at
            call time so the limit stays configurable.
    return: Number of bytes written.
    raises HTTPException: 413 when the upload is too large.
    """
    max_bytes = MAX_UPLOAD_BYTES if max_bytes is None else max_bytes
    destination.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    try:
        with destination.open("wb") as target:
            while True:
                chunk = await upload.read(UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"{upload.filename} exceeds the {max_bytes} byte upload limit",
                    )
                target.write(chunk)
    except HTTPException:
        destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        destination.unlink(missing_ok=True)
        raise HTTPException(
            status_code=400, detail=f"Could not store {upload.filename}"
        ) from exc
    finally:
        await upload.close()

    if written == 0:
        destination.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=f"{upload.filename} is empty")
    return written


def require_suffix(name, allowed, kind):
    """Raise 400 unless a filename carries one of the allowed suffixes."""
    suffix = Path(str(name or "")).suffix.lower()
    if suffix not in allowed:
        expected = ", ".join(sorted(allowed))
        raise HTTPException(
            status_code=400,
            detail=f"{kind} must be one of {expected}, got '{suffix or name}'",
        )


def scenario_map_reference(scenario_path):
    """Return the RoadNetwork/LogicFile filepath a scenario references, if any."""
    try:
        root = ET.parse(scenario_path).getroot()
    except Exception:  # noqa: BLE001 - unparsable files are reported by the checker.
        return None
    logic_file = root.find("RoadNetwork/LogicFile")
    if logic_file is None:
        return None
    return logic_file.attrib.get("filepath") or None


async def link_map_upload(map_upload, scenario_path, run_directory):
    """
    Store an uploaded OpenDRIVE file where the scenario expects to find it.

    get_xodr_path() resolves RoadNetwork/LogicFile@filepath relative to the
    scenario's directory, so writing the map to exactly that location makes it
    resolvable whatever the upload happened to be named. The scenario is stored
    one level below the run directory, which keeps the common '../xodr/map.xodr'
    style of reference resolvable without leaving the run directory.

    Args:
        map_upload: Optional UploadFile with the .xodr, may be None.
        scenario_path: Path of the stored scenario file.
        run_directory: Directory owning this run.
    return: Dict describing what happened, for the API response.
    """
    reference = scenario_map_reference(scenario_path)

    if map_upload is None or not map_upload.filename:
        return {
            "uploaded": False,
            "referenced_by_scenario": reference is not None,
            "reference": reference,
            "note": (
                "The scenario references an OpenDRIVE map. Upload it as well to "
                "resolve lane positions and draw the road network."
                if reference
                else None
            ),
        }

    require_suffix(map_upload.filename, ALLOWED_MAP_SUFFIXES, "The map file")

    resolved = (
        confined_path(run_directory, reference, scenario_path.parent)
        if reference
        else None
    )
    target = resolved or scenario_path.parent / safe_upload_name(map_upload.filename)
    await store_upload(map_upload, target)

    linked_as = str(target.relative_to(run_directory))
    if reference is None:
        note = (
            "The scenario does not reference an OpenDRIVE map, so the uploaded "
            "map is not used by the checks."
        )
    elif resolved is None:
        note = (
            f"The scenario references '{reference}', which points outside the "
            f"upload area. The map was stored as '{linked_as}' and is not used."
        )
    else:
        note = None

    return {
        "uploaded": True,
        "referenced_by_scenario": reference is not None,
        "reference": reference,
        "linked_as": linked_as,
        "note": note,
    }


def parse_thresholds(values):
    """Build Thresholds from form values, reporting bad input as HTTP 400."""
    try:
        return Thresholds.from_mapping(values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Running the checker
# ---------------------------------------------------------------------------


def _run_checker(scenario_path, thresholds, work_dir):
    """Run the checker synchronously. Executed on the worker thread."""
    return FileQualityChecker(
        scenario_path,
        DEFAULT_SCHEMA_PATH,
        esmini_path=None,
        print_log=False,
        thresholds=thresholds,
        work_dir=work_dir,
    )


def _render_plots(checker, plot_directory):
    """
    Render the dynamics and path plots for a checker.

    Args:
        checker: FileQualityChecker instance.
        plot_directory: Directory the PNG files are written to.
    return: List of (name, label) pairs for the plots that were produced.
    """
    # Importing here keeps the module import cheap and mirrors how the PDF
    # report creator is used elsewhere.
    from ..pdf_report_creator import plot_dynamics

    if checker.scenario is None or not checker.dynamic_errors:
        return []

    plot_directory.mkdir(parents=True, exist_ok=True)
    accel_errors, accel_warnings, swim_errors, swim_warnings = checker.dynamic_errors
    analyzed_dynamics = {
        "acceleration_errors": accel_errors,
        "acceleration_warnings": accel_warnings,
        "swimangle_errors": swim_errors,
        "swimangle_warnings": swim_warnings,
    }
    try:
        plot_dynamics(checker, analyzed_dynamics, output_dir=plot_directory)
    except Exception as exc:  # noqa: BLE001 - plots are supplementary to the findings.
        logger.warning(f"Could not render plots for {checker.file_path}: {exc}")

    return [
        (name, label)
        for name, label, filename in PLOT_FILES
        if (plot_directory / filename).is_file()
    ]


def _check_scenario(scenario_path, thresholds, run_directory):
    """Run the checker and render its plots. Executed on the worker thread."""
    checker = _run_checker(scenario_path, thresholds, run_directory / "tmp")
    plots = _render_plots(checker, run_directory / "plots")
    return checker, plots


async def in_worker(function, *args):
    """Run blocking work on the single checker thread, with a timeout."""
    loop = asyncio.get_running_loop()
    try:
        return await asyncio.wait_for(
            loop.run_in_executor(checker_executor(), function, *args),
            RUN_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise HTTPException(
            status_code=504,
            detail=f"The check did not finish within {RUN_TIMEOUT_SECONDS} seconds",
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# Application setup
# ---------------------------------------------------------------------------


async def cleanup_loop():
    """Periodically drop expired sessions and any leftover directories."""
    while True:
        await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
        store.cleanup_expired()
        store.cleanup_orphaned_directories()


@asynccontextmanager
async def application_lifespan(app):
    """Prepare the working directory and run the cleanup task."""
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    store.cleanup_orphaned_directories()
    task = asyncio.create_task(cleanup_loop())
    try:
        yield
    finally:
        task.cancel()
        shutdown_executor()


app = FastAPI(
    title="scenario-quality-checker", version="0.1.0", lifespan=application_lifespan
)

STATIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=STATIC_DIRECTORY), name="assets")
if BRANDING_DIRECTORY.is_dir():
    app.mount("/branding", StaticFiles(directory=BRANDING_DIRECTORY), name="branding")


def secure_cookies(request):
    """Set the Secure flag when the request itself arrived over HTTPS."""
    configured = os.environ.get("SQC_SECURE_COOKIES", "auto").lower()
    if configured in {"1", "true", "yes"}:
        return True
    if configured in {"0", "false", "no"}:
        return False
    return request.url.scheme == "https"


@app.middleware("http")
async def bind_session(request, call_next):
    """Attach a session to every request and refresh its cookie."""
    raw_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    session_id = raw_id if SESSION_ID_PATTERN.match(raw_id) else uuid4().hex
    request.state.session = store.get_or_create(session_id)

    response = await call_next(request)
    if raw_id != session_id:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session_id,
            httponly=True,
            samesite="lax",
            secure=secure_cookies(request),
            max_age=SESSION_TTL_SECONDS,
        )
    return response


@app.middleware("http")
async def reject_oversized_requests(request, call_next):
    """Reject too-large uploads before reading the body."""
    if request.method == "POST":
        declared = request.headers.get("content-length")
        limit = MAX_UPLOAD_BYTES * (MAX_BATCH_FILES + 1)
        if declared and declared.isdigit() and int(declared) > limit:
            return JSONResponse(
                {"detail": f"Request body exceeds the {limit} byte limit"},
                status_code=413,
            )
    return await call_next(request)


def session_directory(session):
    """Return (and create) the working directory of a session."""
    directory = WORK_ROOT / session.session_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def get_run(request, run_id):
    """Return a run owned by the requesting session, or raise 404."""
    run = request.state.session.runs.get(run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Unknown run")
    return run


def get_batch(request, batch_id):
    """Return a batch owned by the requesting session, or raise 404."""
    batch = request.state.session.batches.get(batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="Unknown batch")
    return batch


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/")
def index():
    """Serve the single-page frontend."""
    return FileResponse(STATIC_DIRECTORY / "index.html")


@app.get("/favicon.ico")
def favicon():
    """Serve the project icon when the repository assets are available."""
    icon = BRANDING_DIRECTORY / "scenario-quality-checker-logo.svg"
    if not icon.is_file():
        return Response(status_code=404)
    return FileResponse(icon)


@app.get("/api/health")
def health():
    """Report that the service is up."""
    return {"status": "ok", "version": app.version}


@app.get("/api/thresholds")
def thresholds():
    """Return the default threshold values and their units."""
    return {
        "defaults": Thresholds.default().as_dict(),
        "units": {"acceleration": "m/s^2", "sideslip": "rad"},
    }


@app.get("/api/examples")
def examples():
    """List the example scenarios bundled with the tool."""
    if not EXAMPLE_DIRECTORY.is_dir():
        return {"examples": []}
    return {"examples": sorted(path.name for path in EXAMPLE_DIRECTORY.glob("*.xosc"))}


@app.post("/api/checks")
async def check_scenario(
    request: Request,
    scenario: Optional[UploadFile] = File(None),
    map: Optional[UploadFile] = File(None),
    example: Optional[str] = Form(None),
    acceleration_warning: Optional[str] = Form(None),
    acceleration_error: Optional[str] = Form(None),
    sideslip_warning: Optional[str] = Form(None),
    sideslip_error: Optional[str] = Form(None),
):
    """Check one uploaded scenario and return its structured result."""
    session = request.state.session
    limits = parse_thresholds(
        {
            "acceleration_warning": acceleration_warning,
            "acceleration_error": acceleration_error,
            "sideslip_warning": sideslip_warning,
            "sideslip_error": sideslip_error,
        }
    )

    async with session.lock:
        run_id = uuid4().hex
        run_directory = session_directory(session) / run_id
        # One level below the run directory, so a '../maps/x.xodr' reference in
        # the scenario still resolves inside the run directory.
        input_directory = run_directory / "input"
        input_directory.mkdir(parents=True, exist_ok=True)

        if scenario is not None and scenario.filename:
            require_suffix(
                scenario.filename, ALLOWED_SCENARIO_SUFFIXES, "The scenario file"
            )
            file_name = safe_upload_name(scenario.filename)
            scenario_path = input_directory / file_name
            await store_upload(scenario, scenario_path)
        elif example:
            source = EXAMPLE_DIRECTORY / safe_upload_name(example)
            if not source.is_file():
                raise HTTPException(
                    status_code=404, detail=f"Unknown example '{example}'"
                )
            file_name = source.name
            scenario_path = input_directory / file_name
            shutil.copy2(source, scenario_path)
        else:
            raise HTTPException(
                status_code=400,
                detail="Provide a scenario file or the name of an example",
            )

        map_info = await link_map_upload(map, scenario_path, run_directory)
        checker, plots = await in_worker(
            _check_scenario, scenario_path, limits, run_directory
        )

        run = Run(
            run_id=run_id,
            session_id=session.session_id,
            file_name=file_name,
            directory=run_directory,
            checker=checker,
            map_info=map_info,
            plots=plots,
        )
        session.runs[run_id] = run

    return JSONResponse(run.result(), status_code=201)


@app.get("/api/runs/{run_id}")
async def get_run_result(request: Request, run_id: str):
    """
    Return the structured result of an earlier run.

    Batch runs are checked without plots to keep large batches fast, so the
    plots are rendered the first time a single run is opened.
    """
    run = get_run(request, run_id)
    if not run.plots:
        run.plots = await in_worker(_render_plots, run.checker, run.directory / "plots")
    return run.result()


@app.get("/api/runs/{run_id}/plots/{plot_name}.png")
def get_run_plot(request: Request, run_id: str, plot_name: str):
    """Serve one rendered plot of a run."""
    run = get_run(request, run_id)
    filenames = {name: filename for name, _, filename in PLOT_FILES}
    filename = filenames.get(plot_name)
    if filename is None:
        raise HTTPException(status_code=404, detail=f"Unknown plot '{plot_name}'")
    path = run.directory / "plots" / filename
    if not path.is_file():
        raise HTTPException(
            status_code=404, detail=f"Plot '{plot_name}' was not rendered"
        )
    return FileResponse(path, media_type="image/png")


def _build_single_report(run, want_pdf):
    """Create the PDF or CSV report of a run. Executed on the worker thread."""
    reports = run.directory / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    stem = Path(run.file_name).stem
    if want_pdf:
        run.checker.create_single_report(f"Summary of {run.file_name}", reports)
        return reports / f"{stem}.pdf"
    run.checker.create_csv(stem, reports, scenario_name=run.file_name)
    return reports / f"{stem}.csv"


@app.get("/api/runs/{run_id}/report.pdf")
async def get_run_pdf(request: Request, run_id: str):
    """Return the PDF report of a run, generating it on first request."""
    run = get_run(request, run_id)
    path = await in_worker(_build_single_report, run, True)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The PDF report could not be created"
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/runs/{run_id}/report.csv")
async def get_run_csv(request: Request, run_id: str):
    """Return the CSV report of a run, generating it on first request."""
    run = get_run(request, run_id)
    path = await in_worker(_build_single_report, run, False)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The CSV report could not be created"
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)


def _extract_zip(archive_path, destination):
    """
    Extract the scenario and map files from an uploaded archive.

    Args:
        archive_path: Path to the uploaded .zip.
        destination: Directory to extract into.
    return: Sorted list of extracted .xosc paths.
    raises HTTPException: 400 for malformed archives or limit violations.
    """
    wanted = ALLOWED_SCENARIO_SUFFIXES | {".xodr"}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            total_bytes = 0
            members = []
            for info in archive.infolist():
                if info.is_dir() or Path(info.filename).suffix.lower() not in wanted:
                    continue
                target = confined_path(destination, info.filename)
                if target is None:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Archive member '{info.filename}' escapes the upload directory",
                    )
                total_bytes += info.file_size
                if total_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="The archive expands beyond the allowed size",
                    )
                members.append((info, target))

            if len(members) > MAX_BATCH_FILES:
                raise HTTPException(
                    status_code=400,
                    detail=f"The archive holds more than {MAX_BATCH_FILES} files",
                )

            for info, target in members:
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, target.open("wb") as sink:
                    shutil.copyfileobj(source, sink)
    except zipfile.BadZipFile as exc:
        raise HTTPException(
            status_code=400, detail="The archive could not be read"
        ) from exc

    return sorted(
        target
        for _, target in members
        if target.suffix.lower() in ALLOWED_SCENARIO_SUFFIXES
    )


def _check_batch(scenario_paths, thresholds, batch_directory):
    """Check every scenario of a batch. Executed on the worker thread."""
    checkers = []
    for scenario_path in scenario_paths:
        checkers.append(
            _run_checker(scenario_path, thresholds, batch_directory / "tmp")
        )
    return checkers


@app.post("/api/batches")
async def check_batch(
    request: Request,
    scenarios: List[UploadFile] = File(...),
    acceleration_warning: Optional[str] = Form(None),
    acceleration_error: Optional[str] = Form(None),
    sideslip_warning: Optional[str] = Form(None),
    sideslip_error: Optional[str] = Form(None),
):
    """Check several scenarios and return the aggregated summary table."""
    session = request.state.session
    limits = parse_thresholds(
        {
            "acceleration_warning": acceleration_warning,
            "acceleration_error": acceleration_error,
            "sideslip_warning": sideslip_warning,
            "sideslip_error": sideslip_error,
        }
    )

    uploads = [upload for upload in scenarios if upload.filename]
    if not uploads:
        raise HTTPException(
            status_code=400, detail="Provide at least one scenario file"
        )
    if len(uploads) > MAX_BATCH_FILES:
        raise HTTPException(
            status_code=400,
            detail=f"At most {MAX_BATCH_FILES} files can be checked at once",
        )

    async with session.lock:
        batch_id = uuid4().hex
        batch_directory = session_directory(session) / batch_id
        inputs = batch_directory / "inputs"
        inputs.mkdir(parents=True, exist_ok=True)

        scenario_paths = []
        for upload in uploads:
            suffix = Path(upload.filename).suffix.lower()
            if suffix == ".zip":
                archive_path = batch_directory / safe_upload_name(upload.filename)
                await store_upload(upload, archive_path)
                scenario_paths.extend(_extract_zip(archive_path, inputs))
            else:
                require_suffix(
                    upload.filename,
                    ALLOWED_SCENARIO_SUFFIXES | {".xodr"},
                    "Batch files",
                )
                target = inputs / safe_upload_name(upload.filename)
                await store_upload(upload, target)
                if target.suffix.lower() in ALLOWED_SCENARIO_SUFFIXES:
                    scenario_paths.append(target)

        if not scenario_paths:
            raise HTTPException(
                status_code=400, detail="No .xosc files found in the upload"
            )
        if len(scenario_paths) > MAX_BATCH_FILES:
            raise HTTPException(
                status_code=400,
                detail=f"At most {MAX_BATCH_FILES} scenarios can be checked at once",
            )

        checkers = await in_worker(
            _check_batch, scenario_paths, limits, batch_directory
        )

        rows = []
        for scenario_path, checker in zip(scenario_paths, checkers):
            run_id = uuid4().hex
            run_directory = batch_directory / "runs" / run_id
            run_directory.mkdir(parents=True, exist_ok=True)
            session.runs[run_id] = Run(
                run_id=run_id,
                session_id=session.session_id,
                file_name=scenario_path.name,
                directory=run_directory,
                checker=checker,
                map_info={"uploaded": False},
                plots=[],
            )
            rows.append(summary_row_json(checker, run_id, scenario_path.name))

        session.batches[batch_id] = Batch(
            batch_id=batch_id,
            session_id=session.session_id,
            directory=batch_directory,
            rows=rows,
            checkers=list(checkers),
        )

    return JSONResponse(
        {
            "batch_id": batch_id,
            "thresholds": limits.as_dict(),
            "files": rows,
            "downloads": {
                "pdf": f"/api/batches/{batch_id}/report.pdf",
                "csv": f"/api/batches/{batch_id}/report.csv",
            },
        },
        status_code=201,
    )


def _build_batch_report(batch, want_pdf):
    """Create the aggregated PDF or CSV. Executed on the worker thread."""
    reports = batch.directory / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    summary_rows = []
    for checker in batch.checkers:
        row = list(checker.to_summary_row())
        # Report the plain file name; the full path is a server temp location.
        row[0] = Path(row[0]).name
        summary_rows.append(row)
    if want_pdf:
        create_report_multiple("Aggregated report", summary_rows, reports)
        return reports / "aggregate_report.pdf"
    return write_aggregate_csv(summary_rows, reports)


@app.get("/api/batches/{batch_id}/report.pdf")
async def get_batch_pdf(request: Request, batch_id: str):
    """Return the aggregated PDF report of a batch."""
    batch = get_batch(request, batch_id)
    path = await in_worker(_build_batch_report, batch, True)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The aggregated PDF could not be created"
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/batches/{batch_id}/report.csv")
async def get_batch_csv(request: Request, batch_id: str):
    """Return the aggregated CSV report of a batch."""
    batch = get_batch(request, batch_id)
    path = await in_worker(_build_batch_report, batch, False)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The aggregated CSV could not be created"
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)


def main():
    """Run the Scenario Quality Checker web application."""
    import uvicorn

    port = _int_from_environment("SQC_PORT", 8001)
    uvicorn.run("quality_checker.webapp.server:app", host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
