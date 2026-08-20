"""
Web interface for the Scenario Quality Checker.

Upload an OpenSCENARIO file (optionally with the OpenDRIVE map it references),
get the findings, the dynamics plots and the PDF/CSV reports in the browser.

The checker keeps state in module-level matplotlib figures and writes
intermediate files, so all analysis runs on a single worker thread; the event
loop stays free while a check is in progress.

The service is anonymous by design, which makes resource discipline the main
security control: every limit here exists because the input is untrusted and
the analysis worker is shared by everyone.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from loguru import logger

from .. import safe_xml
from ..config import int_from_environment
from ..pdf_report_creator import create_report_multiple
from ..quality_checker import (
    DEFAULT_SCHEMA_PATH,
    FileQualityChecker,
    ScenarioExpansionError,
    write_aggregate_csv,
)
from ..thresholds import Thresholds
from .results import PLOT_FILES, serialize_checker, summary_row_json

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
STATIC_DIRECTORY = Path(__file__).with_name("static")

WORK_ROOT = Path(tempfile.gettempdir()) / "scenario-quality-checker-web"
SESSION_COOKIE_NAME = "sqc_session"
SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{32}$")

ALLOWED_SCENARIO_SUFFIXES = {".xosc"}
ALLOWED_MAP_SUFFIXES = {".xodr", ".xml"}
UPLOAD_CHUNK_BYTES = 1024 * 1024
ZIP_CHUNK_BYTES = 1024 * 1024


def bundled_directory(name, environment_name):
    """
    Locate a directory shipped with the package, whatever the install layout.

    Resolution order is an explicit environment override, then the package data
    installed next to the code, then the source checkout. Deriving the path
    from the parent of the package instead would point at site-packages under a
    normal pip install, so what got served would depend on how the package
    happened to be installed.

    Args:
        name: Directory name inside the package.
        environment_name: Environment variable that overrides the location.
    return: Path, which may not exist; callers check before serving from it.
    """
    override = os.environ.get(environment_name)
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_dir():
            return candidate.resolve()
        logger.warning(
            f"{environment_name} does not point at a directory, falling back to "
            f"the bundled '{name}'"
        )

    try:
        packaged = Path(str(resources.files("quality_checker") / name))
        if packaged.is_dir():
            return packaged
    except (ModuleNotFoundError, TypeError, OSError, NotADirectoryError):
        pass

    return PACKAGE_ROOT / name


EXAMPLE_DIRECTORY = bundled_directory("example_files", "SQC_EXAMPLE_DIR")
BRANDING_DIRECTORY = bundled_directory("assets", "SQC_BRANDING_DIR")

MAX_UPLOAD_BYTES = int_from_environment("SQC_MAX_UPLOAD_BYTES", 20 * 1024 * 1024)
MAX_BATCH_FILES = int_from_environment("SQC_MAX_BATCH_FILES", 50)
MAX_ZIP_UNCOMPRESSED_BYTES = int_from_environment(
    "SQC_MAX_ZIP_UNCOMPRESSED_BYTES", 200 * 1024 * 1024
)
# A member that expands by more than this factor is a compression bomb, not a
# scenario. Plain XML compresses well, but nowhere near this well.
MAX_ZIP_COMPRESSION_RATIO = int_from_environment("SQC_MAX_ZIP_COMPRESSION_RATIO", 200)

SESSION_TTL_SECONDS = int_from_environment("SQC_SESSION_TTL_SECONDS", 3600)
MAX_SESSIONS = int_from_environment("SQC_MAX_SESSIONS", 200)
# A session that was active this recently is never evicted to make room for a
# new one: losing a working user's results is worse than refusing a newcomer.
SESSION_EVICTION_GRACE_SECONDS = int_from_environment(
    "SQC_SESSION_EVICTION_GRACE_SECONDS", 120
)
MAX_RUNS_PER_SESSION = int_from_environment("SQC_MAX_RUNS_PER_SESSION", 100)
MAX_BATCHES_PER_SESSION = int_from_environment("SQC_MAX_BATCHES_PER_SESSION", 10)

RUN_TIMEOUT_SECONDS = int_from_environment("SQC_RUN_TIMEOUT_SECONDS", 120)
# How many checks may be waiting for the single worker before new ones are
# refused. Queueing without a bound turns one slow scenario into an outage for
# everybody behind it; shedding load with 503 keeps the service answering.
MAX_QUEUED_CHECKS = int_from_environment("SQC_MAX_QUEUED_CHECKS", 8)

# An absolute ceiling on a request body. The per-file limit multiplied by the
# batch limit is around a gigabyte with the defaults, which is far more than
# any real batch and far more than the container has memory for.
MAX_REQUEST_BYTES = min(
    int_from_environment("SQC_MAX_REQUEST_BYTES", 256 * 1024 * 1024),
    MAX_UPLOAD_BYTES * (MAX_BATCH_FILES + 1),
)


def _rate_limit_from_environment(default=60):
    """
    Read the rate limit, where 0 explicitly disables it.

    int_from_environment() rejects non-positive values so a typo cannot silently
    remove a limit. Here 0 is a meaningful setting - "the proxy handles this" -
    so it needs its own parser.

    Args:
        default: Value used when unset or unparsable.
    return: int, 0 meaning no limit.
    """
    try:
        value = int(os.environ.get("SQC_RATE_LIMIT_REQUESTS", default))
    except (TypeError, ValueError):
        return default
    return max(value, 0)


RATE_LIMIT_REQUESTS = _rate_limit_from_environment()
RATE_LIMIT_WINDOW_SECONDS = int_from_environment("SQC_RATE_LIMIT_WINDOW_SECONDS", 60)
CLEANUP_INTERVAL_SECONDS = 300

#: Sent on every response. The frontend loads no third-party asset of any kind,
#: so the strictest useful policy applies unchanged - there is nothing to
#: allowlist. 'frame-ancestors' is what stops the app being framed for
#: clickjacking; the legacy X-Frame-Options header repeats it for old browsers.
CONTENT_SECURITY_POLICY = "; ".join(
    (
        "default-src 'self'",
        "base-uri 'self'",
        "form-action 'self'",
        "frame-ancestors 'none'",
        "object-src 'none'",
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "connect-src 'self'",
    )
)
HSTS_VALUE = "max-age=31536000; includeSubDomains"

# One worker: the checker and matplotlib are not safe to run concurrently, and
# serializing here is cheaper than adding locks around pyplot. The executor is
# owned by the application lifespan, so a restarted app gets a fresh one instead
# of a shut-down pool that rejects every job.
_executor = None

# Checks handed to the worker and not yet finished. Only mutated from the event
# loop thread, so a plain integer is enough.
_in_flight = 0


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

    def add_run(self, run):
        """
        Register a run, dropping the oldest ones past the per-session cap.

        Every run pins a whole checker - trajectory frames included - until the
        session expires, so an unbounded run dictionary is a slow memory leak
        that only a session TTL an hour away ever cleans up.

        Args:
            run: Run to remember.
        return: None.
        """
        self.runs[run.run_id] = run
        while len(self.runs) > MAX_RUNS_PER_SESSION:
            _, evicted = _pop_oldest(self.runs)
            shutil.rmtree(evicted.directory, ignore_errors=True)

    def add_batch(self, batch):
        """
        Register a batch, dropping the oldest ones past the per-session cap.

        Args:
            batch: Batch to remember.
        return: None.
        """
        self.batches[batch.batch_id] = batch
        while len(self.batches) > MAX_BATCHES_PER_SESSION:
            # Only the aggregated view is forgotten. The directory stays until
            # the session ends, because the individual runs of the batch live
            # underneath it and may still be open in the browser.
            _pop_oldest(self.batches)


def _pop_oldest(mapping):
    """
    Remove and return the first-inserted entry of a dict.

    Args:
        mapping: Dict to evict from; insertion order is the age order.
    return: (key, value) of the removed entry.
    """
    key = next(iter(mapping))
    return key, mapping.pop(key)


class SessionStore:
    """In-memory session registry with TTL-based cleanup and a size cap."""

    def __init__(
        self,
        ttl_seconds=SESSION_TTL_SECONDS,
        max_sessions=MAX_SESSIONS,
        eviction_grace_seconds=SESSION_EVICTION_GRACE_SECONDS,
    ):
        self._sessions = {}
        self._ttl_seconds = ttl_seconds
        self._max_sessions = max_sessions
        self._eviction_grace_seconds = eviction_grace_seconds

    def touch(self, session_id):
        """
        Return an existing session and mark it as used, or None.

        Args:
            session_id: Identifier taken from the request cookie.
        return: Session or None. A cookie value the store does not know is
            never adopted as a session id, which is what keeps an attacker from
            planting one in a victim's browser.
        """
        session = self._sessions.get(session_id)
        if session is not None:
            session.last_seen = time.monotonic()
        return session

    def get_or_create(self, session_id):
        """
        Return the session for an id, creating it when the store has room.

        Args:
            session_id: Identifier to create or look up.
        return: Session.
        raises SessionCapacityError: The store is full of active sessions.
        """
        session = self._sessions.get(session_id)
        if session is None:
            self._evict_if_full()
            session = Session(session_id=session_id)
            self._sessions[session_id] = session
        session.last_seen = time.monotonic()
        return session

    def _evict_if_full(self):
        """
        Make room for one more session, refusing rather than evicting the live.

        Only sessions idle past the grace period are candidates. Without that
        scope, roughly MAX_SESSIONS cookie-less requests would evict every
        session in use, deleting working directories and making other people's
        in-flight results unreachable.

        Args:
            None
        return: None.
        raises SessionCapacityError: Every session is still active.
        """
        if len(self._sessions) < self._max_sessions:
            return
        self.cleanup_expired()

        idle_before = time.monotonic() - self._eviction_grace_seconds
        while len(self._sessions) >= self._max_sessions:
            candidates = [
                session
                for session in self._sessions.values()
                if session.last_seen < idle_before
            ]
            if not candidates:
                raise SessionCapacityError()
            oldest = min(candidates, key=lambda session: session.last_seen)
            self._sessions.pop(oldest.session_id, None)
            shutil.rmtree(WORK_ROOT / oldest.session_id, ignore_errors=True)

    def forget(self, session_id):
        """
        Drop one session and delete its working directory.

        Args:
            session_id: Session to remove.
        return: True when a session was removed.
        """
        removed = self._sessions.pop(session_id, None) is not None
        shutil.rmtree(WORK_ROOT / session_id, ignore_errors=True)
        return removed

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


class SessionCapacityError(Exception):
    """Raised when every session slot is held by an active session."""


store = SessionStore()


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


class RateLimiter:
    """
    Fixed-window request counter per client address.

    The expensive endpoints are anonymous and each one can occupy the single
    analysis worker for the whole run timeout, so without a limit one client
    can hold the service for everybody. This is deliberately simple and
    in-process: a reverse proxy is the better place for it, but the application
    must not be wide open when nobody configured one.
    """

    #: Upper bound on tracked addresses, so the limiter cannot itself be used
    #: to grow memory without bound.
    MAX_TRACKED_CLIENTS = 10_000

    def __init__(self, limit=None, window_seconds=None):
        self._limit = RATE_LIMIT_REQUESTS if limit is None else limit
        self._window = (
            RATE_LIMIT_WINDOW_SECONDS if window_seconds is None else window_seconds
        )
        self._counters = {}

    def allow(self, client):
        """
        Count one request and report whether it stays within the limit.

        Args:
            client: Client address, or None when it is unknown.
        return: True when the request may proceed.
        """
        if self._limit <= 0:
            return True

        now = time.monotonic()
        window_start = now - (now % self._window)
        key = client or "unknown"

        started, count = self._counters.get(key, (window_start, 0))
        if started < window_start:
            started, count = window_start, 0

        count += 1
        self._counters[key] = (started, count)
        if len(self._counters) > self.MAX_TRACKED_CLIENTS:
            self._forget_stale(window_start)
        return count <= self._limit

    def _forget_stale(self, window_start):
        """Drop counters from earlier windows to bound the tracking table."""
        stale = [
            key
            for key, (started, _) in self._counters.items()
            if started < window_start
        ]
        for key in stale:
            self._counters.pop(key, None)
        if len(self._counters) > self.MAX_TRACKED_CLIENTS:
            self._counters.clear()

    def reset(self):
        """Forget every counter. Used by tests."""
        self._counters.clear()


rate_limiter = RateLimiter()

#: Endpoints that create state and occupy the analysis worker.
RATE_LIMITED_PATHS = ("/api/checks", "/api/batches")


# ---------------------------------------------------------------------------
# Request budget and audit logging
# ---------------------------------------------------------------------------


class RequestBudget:
    """Total number of bytes a single request is allowed to write to disk."""

    def __init__(self, limit=None):
        self.limit = MAX_REQUEST_BYTES if limit is None else limit
        self.used = 0

    def spend(self, count):
        """
        Account for bytes read from the request body.

        Args:
            count: Number of bytes just read.
        return: None.
        raises HTTPException: 413 once the request exceeds its total budget.
        """
        self.used += count
        if self.used > self.limit:
            raise HTTPException(
                status_code=413,
                detail=f"The request body exceeds the {self.limit} byte limit",
            )


def request_budget(request):
    """Return the byte budget of a request, creating it on first use."""
    budget = getattr(request.state, "budget", None)
    if budget is None:
        budget = RequestBudget()
        request.state.budget = budget
    return budget


def request_id(request):
    """Return the correlation id of a request, if the middleware set one."""
    return getattr(request.state, "request_id", "-")


def session_id_of(request):
    """Return the session id bound to a request, for log lines."""
    return getattr(request.state, "session_id", "-")


def audit(request, event, detail=""):
    """
    Log a security-relevant rejection.

    Uploaded content is never logged - only what was refused and why, tied to
    the correlation id the client also sees, so a user-reported error can be
    found in the log.

    Args:
        request: Incoming request.
        event: Short machine-readable event name.
        detail: Extra context; must not contain file contents.
    return: None.
    """
    client = request.client.host if request.client else "-"
    logger.warning(
        f"request={request_id(request)} session={session_id_of(request)} "
        f"client={client} event={event} {detail}".strip()
    )


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


async def store_upload(upload, destination, max_bytes=None, budget=None):
    """
    Stream an upload to disk, rejecting anything past the size limit.

    Args:
        upload: FastAPI UploadFile.
        destination: Target path; parent directories are created.
        max_bytes: Maximum accepted size, defaults to MAX_UPLOAD_BYTES. Read at
            call time so the limit stays configurable.
        budget: Optional RequestBudget counting bytes across every file of the
            request, so a chunked body that omits Content-Length cannot get
            past the per-request ceiling by splitting itself up.
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
                if budget is not None:
                    budget.spend(len(chunk))
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
        root = safe_xml.parse(scenario_path).getroot()
    except Exception:  # noqa: BLE001 - unparsable files are reported by the checker.
        return None
    logic_file = root.find("RoadNetwork/LogicFile")
    if logic_file is None:
        return None
    return logic_file.attrib.get("filepath") or None


async def link_map_upload(map_upload, scenario_path, run_directory, budget=None):
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
        budget: Optional RequestBudget for the whole request.
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
    await store_upload(map_upload, target, budget=budget)

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


def _release_slot(future):
    """
    Free the worker slot once the job really finished.

    Args:
        future: The executor future that just completed.
    return: None.
    """
    global _in_flight
    _in_flight -= 1
    try:
        # Retrieving the exception keeps asyncio from reporting it as never
        # consumed when the request already gave up on this job.
        future.exception()
    except (asyncio.CancelledError, asyncio.InvalidStateError):
        pass


#: Checker failures that are the uploader's fault and can be reported verbatim,
#: mapped to the status code they deserve. Everything else is an internal
#: failure and is reported as a correlation id instead.
INPUT_ERRORS = (
    (ScenarioExpansionError, 413),
    (safe_xml.UnsafeXmlError, 400),
    (safe_xml.ParseError, 400),
)


async def in_worker(request, function, *args):
    """
    Run blocking work on the single checker thread.

    The timeout bounds the HTTP response, not the work: a thread in a
    ThreadPoolExecutor cannot be cancelled, so a scenario that never terminates
    keeps the only worker busy even after the client got its 504. That is why
    the queue is capped - requests that would pile up behind such a job are
    refused immediately instead of waiting for a worker that is not coming.

    Args:
        request: Incoming request, used for the correlation id in error logs.
        function: Callable to run on the worker thread.
        *args: Arguments for the callable.
    return: Whatever the callable returned.
    raises HTTPException: 503 when the queue is full, 504 on timeout, 4xx for
        bad input, 500 with a correlation id for anything else.
    """
    global _in_flight

    if _in_flight >= MAX_QUEUED_CHECKS:
        audit(request, "queue_full", f"in_flight={_in_flight}")
        raise HTTPException(
            status_code=503,
            detail="The service is busy checking other scenarios. Try again shortly.",
        )

    loop = asyncio.get_running_loop()
    future = loop.run_in_executor(checker_executor(), function, *args)
    _in_flight += 1
    future.add_done_callback(_release_slot)

    try:
        # Shielded, so the timeout does not cancel the future the slot
        # accounting depends on; the work is released when it truly ends.
        return await asyncio.wait_for(asyncio.shield(future), RUN_TIMEOUT_SECONDS)
    except asyncio.TimeoutError as exc:
        audit(request, "check_timeout", f"limit={RUN_TIMEOUT_SECONDS}s")
        raise HTTPException(
            status_code=504,
            detail=(f"The check did not finish within {RUN_TIMEOUT_SECONDS} seconds"),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        for error_type, status_code in INPUT_ERRORS:
            if isinstance(exc, error_type):
                audit(request, "bad_scenario", f"type={type(exc).__name__}")
                raise HTTPException(status_code=status_code, detail=str(exc)) from exc

        # Anything else is a bug or an unexpected library failure. The text can
        # carry server paths and library internals, so it goes to the log and
        # the client gets an id to quote instead.
        logger.opt(exception=exc).error(
            f"request={request_id(request)} session={session_id_of(request)} "
            f"event=check_failed"
        )
        raise HTTPException(
            status_code=500,
            detail=(
                "The scenario could not be checked because of an internal error. "
                f"Reference: {request_id(request)}"
            ),
        ) from exc


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
    title="scenario-quality-checker", version="0.2.0", lifespan=application_lifespan
)

STATIC_DIRECTORY.mkdir(parents=True, exist_ok=True)
app.mount("/assets", StaticFiles(directory=STATIC_DIRECTORY), name="assets")
if BRANDING_DIRECTORY.is_dir():
    app.mount("/branding", StaticFiles(directory=BRANDING_DIRECTORY), name="branding")


def secure_cookies(request):
    """
    Decide whether the session cookie carries the Secure flag.

    'auto' derives the answer from the request scheme. Behind a TLS-terminating
    proxy that scheme is only right when uvicorn is told to trust the proxy's
    forwarded headers, which main() does; X-Forwarded-Proto is consulted as a
    fallback for other servers. Trusting a spoofed value here can only turn the
    flag on, never off, so the failure mode is a cookie the browser refuses to
    send over plaintext - not one it leaks.

    Args:
        request: Incoming request.
    return: True when the Secure flag must be set.
    """
    configured = os.environ.get("SQC_SECURE_COOKIES", "auto").lower()
    if configured in {"1", "true", "yes"}:
        return True
    if configured in {"0", "false", "no"}:
        return False
    if request.url.scheme == "https":
        return True
    forwarded = request.headers.get("x-forwarded-proto", "")
    return forwarded.split(",")[0].strip().lower() == "https"


@app.middleware("http")
async def bind_session(request, call_next):
    """
    Attach the session of a request, without creating one for every caller.

    A session is only materialised by a request that actually creates state.
    Minting one on any GET made session creation free and unauthenticated, so a
    few hundred cookie-less requests could evict every session in use.
    """
    raw_id = request.cookies.get(SESSION_COOKIE_NAME, "")
    session = store.touch(raw_id) if SESSION_ID_PATTERN.match(raw_id) else None
    request.state.session = session
    # An id the client supplied but this process does not know is never
    # adopted: a fresh one is minted if and when state is created. That is what
    # keeps a cookie planted in someone's browser from becoming their session.
    request.state.session_id = session.session_id if session else uuid4().hex

    response = await call_next(request)

    session = getattr(request.state, "session", None)
    if session is not None:
        # Refreshed on every response, so the cookie in the browser expires at
        # the same time as the server-side session rather than an hour after it
        # was first issued.
        response.set_cookie(
            SESSION_COOKIE_NAME,
            session.session_id,
            httponly=True,
            samesite="lax",
            secure=secure_cookies(request),
            max_age=SESSION_TTL_SECONDS,
        )
    return response


@app.middleware("http")
async def throttle_and_limit_size(request, call_next):
    """Refuse abusive or oversized requests before reading the body."""
    if request.method == "POST":
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > MAX_REQUEST_BYTES:
            audit(request, "request_too_large", f"declared={declared}")
            return JSONResponse(
                {"detail": f"Request body exceeds the {MAX_REQUEST_BYTES} byte limit"},
                status_code=413,
            )

        if request.url.path in RATE_LIMITED_PATHS:
            client = request.client.host if request.client else None
            if not rate_limiter.allow(client):
                audit(request, "rate_limited", f"path={request.url.path}")
                return JSONResponse(
                    {
                        "detail": (
                            "Too many checks from this address. "
                            f"At most {RATE_LIMIT_REQUESTS} per "
                            f"{RATE_LIMIT_WINDOW_SECONDS} seconds."
                        )
                    },
                    status_code=429,
                    headers={"Retry-After": str(RATE_LIMIT_WINDOW_SECONDS)},
                )

    return await call_next(request)


@app.middleware("http")
async def request_context(request, call_next):
    """
    Give every request an identity and every response its security headers.

    Registered last, so it is the outermost middleware: a request refused by the
    throttle below still comes back with the headers and the correlation id.
    """
    request.state.request_id = uuid4().hex[:12]
    request.state.budget = RequestBudget()

    response = await call_next(request)

    response.headers["X-Request-ID"] = request.state.request_id
    response.headers.setdefault("Content-Security-Policy", CONTENT_SECURITY_POLICY)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")
    # Only meaningful over HTTPS, and actively unhelpful when announced over
    # plaintext, so it follows the same detection as the cookie flag.
    if secure_cookies(request):
        response.headers.setdefault("Strict-Transport-Security", HSTS_VALUE)
    return response


def session_directory(session):
    """Return (and create) the working directory of a session."""
    directory = WORK_ROOT / session.session_id
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def create_session(request):
    """
    Return the session of a request, creating it on first stateful use.

    Args:
        request: Incoming request.
    return: Session.
    raises HTTPException: 503 when no session slot can be freed.
    """
    session = getattr(request.state, "session", None)
    if session is not None:
        return session
    try:
        session = store.get_or_create(request.state.session_id)
    except SessionCapacityError as exc:
        audit(request, "session_capacity", f"max={MAX_SESSIONS}")
        raise HTTPException(
            status_code=503,
            detail="The service is at capacity. Try again in a few minutes.",
        ) from exc
    request.state.session = session
    return session


def get_run(request, run_id):
    """Return a run owned by the requesting session, or raise 404."""
    session = getattr(request.state, "session", None)
    run = session.runs.get(run_id) if session else None
    if run is None:
        audit(request, "run_not_found", f"run={safe_upload_name(run_id)}")
        raise HTTPException(status_code=404, detail="Unknown run")
    return run


def get_batch(request, batch_id):
    """Return a batch owned by the requesting session, or raise 404."""
    session = getattr(request.state, "session", None)
    batch = session.batches.get(batch_id) if session else None
    if batch is None:
        audit(request, "batch_not_found", f"batch={safe_upload_name(batch_id)}")
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
    """
    Report that the service is up.

    Deliberately says nothing else: the version would tell an unauthenticated
    caller which advisories apply to this deployment.
    """
    return {"status": "ok"}


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
    limits = parse_thresholds(
        {
            "acceleration_warning": acceleration_warning,
            "acceleration_error": acceleration_error,
            "sideslip_warning": sideslip_warning,
            "sideslip_error": sideslip_error,
        }
    )
    session = create_session(request)
    budget = request_budget(request)

    async with session.lock:
        run_id = uuid4().hex
        run_directory = session_directory(session) / run_id
        # One level below the run directory, so a '../maps/x.xodr' reference in
        # the scenario still resolves inside the run directory.
        input_directory = run_directory / "input"
        input_directory.mkdir(parents=True, exist_ok=True)

        if scenario is not None and scenario.filename:
            try:
                require_suffix(
                    scenario.filename, ALLOWED_SCENARIO_SUFFIXES, "The scenario file"
                )
            except HTTPException:
                audit(request, "rejected_suffix", "field=scenario")
                raise
            file_name = safe_upload_name(scenario.filename)
            scenario_path = input_directory / file_name
            try:
                await store_upload(scenario, scenario_path, budget=budget)
            except HTTPException as exc:
                if exc.status_code == 413:
                    audit(request, "upload_too_large", "field=scenario")
                raise
        elif example:
            source = EXAMPLE_DIRECTORY / safe_upload_name(example)
            if not source.is_file():
                audit(request, "unknown_example", f"name={safe_upload_name(example)}")
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

        map_info = await link_map_upload(
            map, scenario_path, run_directory, budget=budget
        )
        checker, plots = await in_worker(
            request, _check_scenario, scenario_path, limits, run_directory
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
        session.add_run(run)

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
        run.plots = await in_worker(
            request, _render_plots, run.checker, run.directory / "plots"
        )
    return run.result()


@app.get("/api/runs/{run_id}/plots/{plot_name}.png")
def get_run_plot(request: Request, run_id: str, plot_name: str):
    """Serve one rendered plot of a run."""
    run = get_run(request, run_id)
    filenames = {name: filename for name, _, filename in PLOT_FILES}
    filename = filenames.get(plot_name)
    if filename is None:
        audit(request, "unknown_plot", f"name={safe_upload_name(plot_name)}")
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
    path = await in_worker(request, _build_single_report, run, True)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The PDF report could not be created"
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/runs/{run_id}/report.csv")
async def get_run_csv(request: Request, run_id: str):
    """Return the CSV report of a run, generating it on first request."""
    run = get_run(request, run_id)
    path = await in_worker(request, _build_single_report, run, False)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The CSV report could not be created"
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)


def _copy_zip_member(archive, info, target, remaining):
    """
    Extract one archive member, stopping the moment it outgrows its budget.

    The declared size in the central directory is chosen by whoever built the
    archive, so it can only ever be a hint. The limit that matters is on bytes
    actually written, checked while writing them.

    Args:
        archive: Open ZipFile.
        info: ZipInfo of the member to extract.
        target: Path to write to.
        remaining: Bytes still allowed across the whole archive.
    return: Number of bytes written.
    raises HTTPException: 413 when the member exceeds the remaining budget or
        expands far beyond its compressed size.
    """
    # A member cannot legitimately expand by more than this from its own
    # compressed size; well beyond it means a bomb, whatever the header claims.
    ratio_limit = max(info.compress_size, 1) * MAX_ZIP_COMPRESSION_RATIO
    written = 0
    with archive.open(info) as source, target.open("wb") as sink:
        while True:
            chunk = source.read(ZIP_CHUNK_BYTES)
            if not chunk:
                break
            written += len(chunk)
            if written > remaining or written > ratio_limit:
                raise HTTPException(
                    status_code=413,
                    detail="The archive expands beyond the allowed size",
                )
            sink.write(chunk)
    return written


def _extract_zip(archive_path, destination, request=None):
    """
    Extract the scenario and map files from an uploaded archive.

    Args:
        archive_path: Path to the uploaded .zip.
        destination: Directory to extract into.
        request: Optional request, for audit logging of rejections.
    return: Sorted list of extracted .xosc paths.
    raises HTTPException: 400 for malformed archives or limit violations.
    """
    wanted = ALLOWED_SCENARIO_SUFFIXES | {".xodr"}
    try:
        with zipfile.ZipFile(archive_path) as archive:
            declared_bytes = 0
            members = []
            for info in archive.infolist():
                if info.is_dir() or Path(info.filename).suffix.lower() not in wanted:
                    continue
                target = confined_path(destination, info.filename)
                if target is None:
                    if request is not None:
                        # A member pointing outside the upload directory is a
                        # deliberate attack, not a mistake; it is worth alerting on.
                        audit(request, "zip_path_traversal", "member=<redacted>")
                    raise HTTPException(
                        status_code=400,
                        detail=f"Archive member '{info.filename}' escapes the upload directory",
                    )
                # A cheap early reject on the declared sizes. It is a hint, not
                # the enforcement point - see _copy_zip_member.
                declared_bytes += info.file_size
                if declared_bytes > MAX_ZIP_UNCOMPRESSED_BYTES:
                    if request is not None:
                        audit(request, "zip_too_large", "stage=declared")
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

            written_bytes = 0
            for info, target in members:
                target.parent.mkdir(parents=True, exist_ok=True)
                try:
                    written_bytes += _copy_zip_member(
                        archive,
                        info,
                        target,
                        MAX_ZIP_UNCOMPRESSED_BYTES - written_bytes,
                    )
                except HTTPException:
                    # Do not leave the partially written member behind.
                    target.unlink(missing_ok=True)
                    if request is not None:
                        audit(request, "zip_too_large", "stage=written")
                    raise
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

    session = create_session(request)
    budget = request_budget(request)

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
                await store_upload(upload, archive_path, budget=budget)
                scenario_paths.extend(_extract_zip(archive_path, inputs, request))
            else:
                try:
                    require_suffix(
                        upload.filename,
                        ALLOWED_SCENARIO_SUFFIXES | {".xodr"},
                        "Batch files",
                    )
                except HTTPException:
                    audit(request, "rejected_suffix", "field=scenarios")
                    raise
                target = inputs / safe_upload_name(upload.filename)
                await store_upload(upload, target, budget=budget)
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
            request, _check_batch, scenario_paths, limits, batch_directory
        )

        rows = []
        for scenario_path, checker in zip(scenario_paths, checkers):
            run_id = uuid4().hex
            run_directory = batch_directory / "runs" / run_id
            run_directory.mkdir(parents=True, exist_ok=True)
            session.add_run(
                Run(
                    run_id=run_id,
                    session_id=session.session_id,
                    file_name=scenario_path.name,
                    directory=run_directory,
                    checker=checker,
                    map_info={"uploaded": False},
                    plots=[],
                )
            )
            rows.append(summary_row_json(checker, run_id, scenario_path.name))

        session.add_batch(
            Batch(
                batch_id=batch_id,
                session_id=session.session_id,
                directory=batch_directory,
                rows=rows,
                checkers=list(checkers),
            )
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
    path = await in_worker(request, _build_batch_report, batch, True)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The aggregated PDF could not be created"
        )
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.get("/api/batches/{batch_id}/report.csv")
async def get_batch_csv(request: Request, batch_id: str):
    """Return the aggregated CSV report of a batch."""
    batch = get_batch(request, batch_id)
    path = await in_worker(request, _build_batch_report, batch, False)
    if not path.is_file():
        raise HTTPException(
            status_code=500, detail="The aggregated CSV could not be created"
        )
    return FileResponse(path, media_type="text/csv", filename=path.name)


@app.delete("/api/session")
def clear_session(request: Request):
    """
    Forget everything this browser session uploaded, immediately.

    Waiting out the session TTL is the only alternative, which is not much of
    an answer for someone who wants their scenario off the server now.
    """
    session = getattr(request.state, "session", None)
    if session is None:
        return {"cleared": False}
    store.forget(session.session_id)
    request.state.session = None
    response = JSONResponse({"cleared": True})
    response.delete_cookie(SESSION_COOKIE_NAME, httponly=True, samesite="lax")
    return response


def main():
    """Run the Scenario Quality Checker web application."""
    import uvicorn

    port = int_from_environment("SQC_PORT", 8001)
    # Behind a TLS-terminating proxy the request scheme is http on the wire, so
    # without this the Secure cookie flag would never be set in exactly the
    # topology the README recommends. Only the listed peers are trusted; set
    # SQC_FORWARDED_ALLOW_IPS to the proxy's address.
    forwarded_allow_ips = os.environ.get("SQC_FORWARDED_ALLOW_IPS", "127.0.0.1")
    uvicorn.run(
        "quality_checker.webapp.server:app",
        host="0.0.0.0",
        port=port,
        proxy_headers=True,
        forwarded_allow_ips=forwarded_allow_ips,
    )


if __name__ == "__main__":
    main()
