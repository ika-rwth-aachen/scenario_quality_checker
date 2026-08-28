"""
Request size limits checked over a real HTTP connection.

TestClient cannot express a chunked upload faithfully: it reads the body it is
given into one piece and hands the application a single ASGI message. That is
enough to show the Content-Length check being bypassed, but not that the server
stops reading. These tests therefore speak HTTP on a socket against a real
uvicorn, which is the only way to see the body being cut off mid-transfer -
the property that separates counting the body from parsing all of it first.
"""

import contextlib
import re
import socket
import threading
import time

import pytest
import uvicorn
from loguru import logger

from quality_checker.webapp.server import app

BOUNDARY = b"----scenario-quality-checker-test"
LIMIT = 4096
CHUNK_BYTES = 64 * 1024
# Enough larger than the limit that "was the body cut off?" is not a judgement
# call: refusing early reads a rounding error of this, draining it reads all.
OVERSIZE_BYTES = 32 * 1024 * 1024


def multipart_body(payload, filename=b"big.xosc"):
    """Build a multipart body for a single scenario field."""
    return (
        b"--" + BOUNDARY + b"\r\n"
        b'Content-Disposition: form-data; name="scenario"; filename="'
        + filename
        + b'"\r\n'
        b"Content-Type: application/xml\r\n\r\n" + payload + b"\r\n"
        b"--" + BOUNDARY + b"--\r\n"
    )


@pytest.fixture(scope="module")
def live_server():
    """Run the application on a real port for the length of this module."""

    class Server(uvicorn.Server):
        def install_signal_handlers(self):
            """Do nothing: this server is not running on the main thread."""

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]

    server = Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    assert server.started, "the test server did not come up"

    try:
        yield port
    finally:
        server.should_exit = True
        thread.join(timeout=10)


def chunked_post(port, body, chunk_bytes=CHUNK_BYTES):
    """
    POST a body with Transfer-Encoding: chunked and no Content-Length.

    Args:
        port: Port the test server listens on.
        body: Complete request body to send in chunks.
        chunk_bytes: Size of each chunk on the wire.
    return: The response head, up to the blank line.
    """
    connection = socket.create_connection(("127.0.0.1", port), timeout=10)
    connection.sendall(
        b"POST /api/checks HTTP/1.1\r\n"
        b"Host: 127.0.0.1\r\n"
        b"Content-Type: multipart/form-data; boundary=" + BOUNDARY + b"\r\n"
        b"Transfer-Encoding: chunked\r\n"
        b"\r\n"
    )

    # A refused request may be closed on us mid-write, which is the server
    # behaving correctly rather than a failure of the test.
    with contextlib.suppress(BrokenPipeError, ConnectionResetError):
        for start in range(0, len(body), chunk_bytes):
            piece = body[start : start + chunk_bytes]
            connection.sendall(b"%x\r\n" % len(piece) + piece + b"\r\n")
        connection.sendall(b"0\r\n\r\n")

    received = b""
    with contextlib.suppress(OSError):
        while b"\r\n\r\n" not in received:
            part = connection.recv(65536)
            if not part:
                break
            received += part
    connection.close()

    return received.split(b"\r\n\r\n")[0].decode("latin-1")


@pytest.fixture
def audit_log():
    """Collect the audit lines the server writes, from whatever thread."""
    lines = []
    sink = logger.add(lambda message: lines.append(str(message)), level="WARNING")
    try:
        yield lines
    finally:
        logger.remove(sink)


def test_a_chunked_upload_is_refused_before_the_body_is_read(
    live_server, audit_log, monkeypatch
):
    """
    An oversized chunked body must be cut off, not parsed and then rejected.

    Reading it all first is the whole problem: the multipart parser holds form
    fields in memory and spools every file part to a temporary file, so a body
    with no declared length could cost the service far more than the ceiling
    before any of the application's own code ran. A 413 alone does not show
    that - the per-file budget produces one too, after the damage is done - so
    the assertion that matters is how much of the body the server took in.
    """
    from quality_checker.webapp import server

    monkeypatch.setattr(server, "MAX_REQUEST_BYTES", LIMIT)
    body = multipart_body(b"x" * OVERSIZE_BYTES)

    head = chunked_post(live_server, body)

    assert "413" in head.splitlines()[0]

    refusals = [line for line in audit_log if "event=request_too_large" in line]
    assert refusals, "the size limit did not refuse the request"
    received = int(re.search(r"received=(\d+)", refusals[-1]).group(1))
    # The limit can only be seen to be exceeded by reading the message that
    # exceeds it, and the server decides how much of the wire that message
    # covers, so the exact figure is not the server's to promise. What is
    # promised is the order of magnitude: a fraction of the body, not all of it.
    assert received < len(body) / 100, (
        f"read {received} of {len(body)} bytes before refusing; "
        "the body is being drained rather than cut off"
    )


def test_a_chunked_upload_within_the_limit_is_accepted(live_server):
    """The wire-level path must still serve an ordinary upload."""
    scenario = (
        b'<?xml version="1.0"?>\n<OpenSCENARIO><Description>ok</Description>'
        b"</OpenSCENARIO>\n"
    )

    head = chunked_post(live_server, multipart_body(scenario))

    # The scenario is deliberately not a valid one - it is the transfer that is
    # under test, so anything but a refusal of the body itself is a pass.
    assert "413" not in head.splitlines()[0]
