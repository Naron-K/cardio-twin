"""
Tests for the monthly WebSocket bandwidth allowance.

The host bills bytes, not requests: 264 MB an hour per open page, 5 GB a month,
then $0.15 a GB with no spend limit.  These tests pin the meter's arithmetic,
its month boundary, its persistence and the stream behaviour that turns live
data off before the bill starts.

Run from the backend/ directory:
    pytest tests/test_usage_limit.py -q
"""

import json
import time
from datetime import date, datetime, timezone

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import main
from main import app
from usage_meter import UsageMeter

_FAST = "/ws/feedback?tick_ms=20"
_SLOW = "/ws/feedback?tick_ms=200"
_FIXED = datetime(2026, 5, 15, 12, 0, tzinfo=timezone.utc)


def _fixed_now() -> datetime:
    return _FIXED


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


# ── Counting, thresholds and the month ──────────────────────────────

def test_add_counts_bytes():
    meter = UsageMeter(1_000)
    meter.add(10)
    meter.add(25)
    assert meter.used_bytes == 35


def test_near_starts_at_eighty_percent():
    meter = UsageMeter(1_000)
    meter.add(799)
    assert meter.near is False
    meter.add(1)
    assert meter.near is True


def test_over_starts_at_the_limit():
    meter = UsageMeter(1_000)
    meter.add(999)
    assert meter.over is False
    meter.add(1)
    assert meter.over is True


def test_disabled_meter_is_never_near_or_over():
    meter = UsageMeter(0)
    meter.add(10 ** 12)
    assert meter.enabled is False
    assert meter.near is False
    assert meter.over is False


def test_month_rollover_starts_at_zero():
    clock = {"now": datetime(2026, 1, 31, 23, 59, tzinfo=timezone.utc)}

    def now() -> datetime:
        return clock["now"]

    meter = UsageMeter(1_000, now=now)
    meter.add(500)
    assert meter.used_bytes == 500

    clock["now"] = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)
    assert meter.used_bytes == 0


def test_negative_and_non_integer_adds_raise():
    meter = UsageMeter(1_000)
    for bad in (-1, 1.5, "7", None):
        with pytest.raises(ValueError):
            meter.add(bad)


def test_the_count_is_exactly_the_sum_of_adds():
    meter = UsageMeter(10 ** 9, now=_fixed_now)
    total = 0
    for n in (0, 1, 17, 999, 123_456):
        meter.add(n)
        total += n
        assert meter.used_bytes == total


# ── Persistence ─────────────────────────────────────────────────────

def test_persistence_round_trip(tmp_path):
    path = tmp_path / "usage.json"
    first = UsageMeter(1_000, path=path, now=_fixed_now)
    first.add(123)
    first.flush()

    second = UsageMeter(1_000, path=path, now=_fixed_now)
    assert second.used_bytes == 123


@pytest.mark.parametrize("body", [
    {"month": "2026-04", "used_bytes": 99},   # another month
    {"month": "2026-05", "used_bytes": -5},   # negative count
    {"month": "2026-05", "used_bytes": "20"},  # wrong type
    {"month": "2026-05"},                     # missing count
])
def test_unusable_history_starts_at_zero(tmp_path, body):
    path = tmp_path / "usage.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    meter = UsageMeter(1_000, path=path, now=_fixed_now)
    assert meter.used_bytes == 0


def test_corrupt_json_starts_at_zero(tmp_path):
    path = tmp_path / "usage.json"
    path.write_text("{not json", encoding="utf-8")
    meter = UsageMeter(1_000, path=path, now=_fixed_now)
    assert meter.used_bytes == 0


def test_missing_file_starts_at_zero(tmp_path):
    meter = UsageMeter(1_000, path=tmp_path / "absent.json", now=_fixed_now)
    assert meter.used_bytes == 0


def test_flush_to_an_unwritable_path_does_not_raise(tmp_path):
    # A file used as a directory makes the atomic write impossible.
    blocker = tmp_path / "blocker"
    blocker.write_text("not a directory", encoding="utf-8")
    meter = UsageMeter(1_000, path=blocker / "usage.json", now=_fixed_now)
    meter.add(5)
    meter.flush()
    meter.flush()


def test_resumes_on_january_after_december():
    meter = UsageMeter(
        1_000,
        now=lambda: datetime(2026, 12, 20, tzinfo=timezone.utc),
    )
    assert meter.resumes_on() == date(2027, 1, 1)


# ── Environment ────────────────────────────────────────────────────

@pytest.mark.parametrize("value", ["abc", "-1", "nan", "inf", "", "0"])
def test_from_env_disables_unusable_limits(monkeypatch, tmp_path, value):
    monkeypatch.setenv("CARDIOTWIN_MONTHLY_GB", value)
    monkeypatch.setenv("CARDIOTWIN_USAGE_FILE", str(tmp_path / "usage.json"))
    meter = UsageMeter.from_env()
    assert meter.enabled is False
    assert meter.snapshot()["limit_gb"] is None


def test_from_env_unset_is_disabled(monkeypatch, tmp_path):
    monkeypatch.delenv("CARDIOTWIN_MONTHLY_GB", raising=False)
    monkeypatch.setenv("CARDIOTWIN_USAGE_FILE", str(tmp_path / "usage.json"))
    meter = UsageMeter.from_env()
    assert meter.enabled is False


def test_from_env_reads_gigabytes(monkeypatch, tmp_path):
    monkeypatch.setenv("CARDIOTWIN_MONTHLY_GB", "4.5")
    monkeypatch.setenv("CARDIOTWIN_USAGE_FILE", str(tmp_path / "usage.json"))
    meter = UsageMeter.from_env()
    assert meter.enabled is True
    assert meter.snapshot()["limit_gb"] == 4.5


# ── Stream behaviour ───────────────────────────────────────────────

def test_connection_refused_when_limit_already_used(monkeypatch, tmp_path):
    meter = UsageMeter(1_000, path=tmp_path / "usage.json")
    meter.add(1_000)
    monkeypatch.setattr(main, "usage", meter)

    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect(_FAST) as ws:
                ws.receive_json()

        assert excinfo.value.code == main.STREAM_LIMIT_CLOSE
        assert "resumes" in excinfo.value.reason
        assert _streams(client) == 0


def test_limit_crossed_mid_stream_closes(monkeypatch, tmp_path):
    meter = UsageMeter(20_000, path=tmp_path / "usage.json")
    monkeypatch.setattr(main, "usage", meter)

    with TestClient(app) as client:
        frames = 0
        code = None
        with client.websocket_connect(_FAST) as ws:
            try:
                while frames < 50:
                    ws.receive_json()
                    frames += 1
            except WebSocketDisconnect as exc:
                code = exc.code

        assert frames >= 1, "no frame arrived before the limit closed the stream"
        assert code == main.STREAM_LIMIT_CLOSE
        assert meter.over is True
        assert _wait_for_streams(client, 0) == 0


def test_near_the_limit_sends_exactly_one_notice(monkeypatch, tmp_path):
    # 10 MB leaves enough headroom for the 30 frames below while starting near.
    meter = UsageMeter(10_000_000, path=tmp_path / "usage.json")
    meter.add(8_000_000)
    monkeypatch.setattr(main, "usage", meter)

    notices = []
    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            for _ in range(30):
                message = ws.receive_json()
                if message.get("code") == "usage_warning":
                    notices.append(message)

    assert len(notices) == 1
    assert notices[0]["type"] == "notice"
    assert notices[0]["level"] == "warning"


def test_disabled_meter_sends_no_notice(monkeypatch, tmp_path):
    meter = UsageMeter(0, path=tmp_path / "usage.json")
    monkeypatch.setattr(main, "usage", meter)

    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            for _ in range(30):
                message = ws.receive_json()
                assert message.get("code") != "usage_warning"


def test_counted_bytes_match_the_frames_received(monkeypatch, tmp_path):
    meter = UsageMeter(10 ** 9, path=tmp_path / "usage.json")
    monkeypatch.setattr(main, "usage", meter)

    lengths = []
    with TestClient(app) as client:
        with client.websocket_connect(_SLOW) as ws:
            for _ in range(5):
                text = ws.receive_text()
                lengths.append(len(text.encode("utf-8")))
            # Let the fifth send finish accounting before reading the meter;
            # the next frame is still ~150 ms away.
            time.sleep(0.05)
            counted = meter.used_bytes

    expected = sum(lengths)
    assert abs(counted - expected) <= expected * 0.02


def test_health_includes_usage(monkeypatch, tmp_path):
    meter = UsageMeter(5_000_000_000, path=tmp_path / "usage.json")
    monkeypatch.setattr(main, "usage", meter)

    with TestClient(app) as client:
        body = client.get("/health").json()

    assert body["status"] == "ok"
    assert "streams" in body
    assert body["usage"]["limit_gb"] == 5.0
    assert body["usage"]["used_gb"] == 0.0
    assert body["usage"]["month"] == datetime.now(timezone.utc).strftime("%Y-%m")


# ── Thinning ───────────────────────────────────────────────────────

def test_emit_every_skips_whole_cycles(monkeypatch, tmp_path):
    meter = UsageMeter(10 ** 12, path=tmp_path / "usage.json")
    monkeypatch.setattr(main, "usage", meter)
    monkeypatch.setattr(main, "STREAM_EMIT_EVERY", 5)

    with TestClient(app) as client:
        with client.websocket_connect(_FAST) as ws:
            first = ws.receive_json()
            second = ws.receive_json()

    gap = second["cycle_report"]["cycle"] - first["cycle_report"]["cycle"]
    assert gap == 5
