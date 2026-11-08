"""
Tests for the /ws/feedback stream lifecycle.

A stream has to end when nobody is on the other end: a tab that vanishes
without closing, or one that stops reading, must not leave a control loop
running for the life of the process.  Normal endings — a closed tab, the
health poll — must also stay out of the log, because a log that is mostly
those two things hides the failures worth reading.

Run from the backend/ directory:
    pytest tests/test_ws_lifecycle.py -q
"""

import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
from main import app
from streaming_runtime import StreamingRuntime

_FAST = "/ws/feedback?tick_ms=20"

# The same format uvicorn's access logger uses.
_ACCESS_MSG = '%s - "%s %s HTTP/%s" %d'


def _streams(client: TestClient) -> int:
    """The open-stream count /health reports."""
    return client.get("/health").json()["streams"]


def _wait_for_streams(client: TestClient, expected: int, timeout: float = 3.0) -> int:
    """Poll /health until the count settles, or the deadline passes."""
    deadline = time.monotonic() + timeout
    count = _streams(client)
    while count != expected and time.monotonic() < deadline:
        time.sleep(0.05)
        count = _streams(client)
    return count


def _access_record(msg, args) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, msg, args, None,
    )


# ── Silence reaps a vanished client ──────────────────────────────────

def test_silence_closes_the_stream(monkeypatch):
    """A client that never sends anything is closed with STREAM_SILENT_CLOSE."""
    monkeypatch.setattr(main, "STREAM_SILENCE_S", 0.3)

    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            deadline = time.monotonic() + 5.0
            frames = 0
            try:
                while time.monotonic() < deadline:
                    ws.receive_json()
                    frames += 1
            except WebSocketDisconnect as exc:
                code = exc.code
            else:
                pytest.fail("stream did not close after going silent")

    assert code == main.STREAM_SILENT_CLOSE
    assert frames < 50, f"took {frames} frames to reap a silent client"


def test_keepalive_holds_the_stream_open(monkeypatch):
    """Traffic from the client resets the silence timer, so the page survives."""
    monkeypatch.setattr(main, "STREAM_SILENCE_S", 0.5)

    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            end = time.monotonic() + 1.5
            try:
                while time.monotonic() < end:
                    ws.send_json({"type": "keepalive"})
                    ws.receive_json()
                    time.sleep(0.1)
            except WebSocketDisconnect:
                pytest.fail("stream closed even though keepalives kept arriving")


# ── Open-stream count ────────────────────────────────────────────────

def test_health_counts_open_streams():
    """Zero with no page, one while a page is open, zero after it closes."""
    with TestClient(app) as client:
        assert _streams(client) == 0

        with client.websocket_connect(_FAST) as ws:
            ws.receive_json()
            assert _streams(client) == 1

        assert _wait_for_streams(client, 0) == 0


# ── A normal close is not a failure ──────────────────────────────────

def test_quiet_close_prints_no_traceback(capfd):
    """Closing a tab is the normal ending, so it must not look like a crash."""
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            for _ in range(3):
                ws.receive_json()

        assert _wait_for_streams(client, 0) == 0

    captured = capfd.readouterr()
    output = captured.out + captured.err
    assert "control loop died" not in output
    assert "Traceback" not in output


# ── Runtime: requested stop vs real failure ──────────────────────────

def test_request_stop_from_emit_ends_the_loop_cleanly():
    """request_stop() is safe inside emit: the loop exits and error stays None."""
    async def scenario():
        async def emit(_result):
            rt.request_stop()

        rt = StreamingRuntime(lambda sample: sample, emit=emit, period_s=0.01)
        task = rt.start()
        rt.submit("sample")
        await asyncio.wait_for(task, timeout=1.0)
        return rt

    rt = asyncio.run(scenario())
    assert rt.error is None
    assert rt.running is False


def test_a_failing_emit_still_sets_runtime_error():
    """The quiet path must not swallow a real failure — it still reports loudly."""
    async def scenario():
        async def emit(_result):
            raise ValueError("frame could not be sent")

        rt = StreamingRuntime(lambda sample: sample, emit=emit, period_s=0.01)
        task = rt.start()
        rt.submit("sample")
        try:
            await asyncio.wait_for(task, timeout=1.0)
        except ValueError:
            pass
        await rt.stop()
        return rt

    rt = asyncio.run(scenario())
    assert isinstance(rt.error, ValueError)


# ── Health-check access-log filter ───────────────────────────────────

def test_filter_drops_the_health_access_line():
    record = _access_record(
        _ACCESS_MSG, ("10.0.0.1:1", "GET", "/health", "1.1", 200),
    )
    assert main._QuietHealthChecks().filter(record) is False


def test_filter_keeps_other_access_lines():
    record = _access_record(
        _ACCESS_MSG, ("10.0.0.1:1", "GET", "/api/schema", "1.1", 200),
    )
    assert main._QuietHealthChecks().filter(record) is True


def test_filter_passes_a_record_it_cannot_format():
    """An odd record must not make the filter itself raise."""
    record = _access_record("%s %s", ("only one",))
    assert main._QuietHealthChecks().filter(record) is True


def test_filter_is_installed_on_uvicorn_access():
    logger = logging.getLogger("uvicorn.access")
    assert any(isinstance(f, main._QuietHealthChecks) for f in logger.filters)
