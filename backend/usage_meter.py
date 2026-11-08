"""
Monthly bandwidth accounting for the live WebSocket streams.

The dashboard's stream is not free: measured on the live host, one frame is
7.1 KB, at 10 frames/s that is 264 MB per hour per open page.  The host strips
WebSocket compression, so bytes sent are bytes billed.  The plan includes 5 GB
a month and bills $0.15 a GB above that, with no spend limit.  This meter makes
the dashboard stop its own live data before the host starts charging extra.

The honest limit: without a persistent disk the usage file disappears on a
deploy or restart.  The count starts over then, so the month can be overshot.
Persisting to a mounted volume (CARDIOTWIN_USAGE_FILE) closes that gap.
"""

import json
import math
import os
import tempfile
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable, Optional


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class UsageMeter:
    """Count bytes sent in the current UTC month and persist the count."""

    def __init__(
        self,
        limit_bytes: int,
        path: Optional[Path] = None,
        warn_ratio: float = 0.8,
        now: Callable[[], datetime] = _utc_now,
        flush_every_s: float = 60.0,
    ):
        self._limit = int(limit_bytes)
        self._path = Path(path) if path is not None else None
        self._warn_ratio = warn_ratio
        self._now = now
        self._flush_every_s = flush_every_s
        self._used = 0
        self._month = self._month_key()
        # A flush is allowed once per period; explicit flush() always writes.
        self._last_flush = time.monotonic()
        self._crossed = False
        self._flush_error_printed = False
        self._restore()

    # ── Clock and month ──────────────────────────────────────────────

    def _utc(self) -> datetime:
        moment = self._now()
        # A naive clock is treated as UTC so the month key never depends on
        # the machine's local timezone.
        if moment.tzinfo is None:
            return moment.replace(tzinfo=timezone.utc)
        return moment.astimezone(timezone.utc)

    def _month_key(self) -> str:
        return self._utc().strftime("%Y-%m")

    def _roll_if_needed(self) -> None:
        current = self._month_key()
        if current == self._month:
            return
        # A new month starts a new allowance.  The crossed flag resets too, so
        # the next crossing still flushes immediately.
        self._month = current
        self._used = 0
        self._crossed = False

    # ── State ────────────────────────────────────────────────────────

    @property
    def enabled(self) -> bool:
        return self._limit > 0

    @property
    def used_bytes(self) -> int:
        # Reading is the moment the caller can cross into a new month, so the
        # roll lives here rather than only in add().
        self._roll_if_needed()
        return self._used

    @property
    def over(self) -> bool:
        return self.enabled and self.used_bytes >= self._limit

    @property
    def near(self) -> bool:
        return self.enabled and self.used_bytes >= self._limit * self._warn_ratio

    # ── Counting ─────────────────────────────────────────────────────

    def add(self, n: int) -> None:
        # bool is an int subclass but never a byte count, and floats would
        # silently round; both are programming errors worth refusing.
        if isinstance(n, bool) or not isinstance(n, int) or n < 0:
            raise ValueError(f"usage count must be a non-negative int, got {n!r}")

        self._roll_if_needed()
        was_over = self.over
        self._used += n

        # Crossing the limit is the one moment the count must be durable right
        # away: after this the stream closes, and a restart must not un-spend
        # the month.  The flag keeps it to once per month.
        if not was_over and self.over and not self._crossed:
            self._crossed = True
            self.flush()
            return

        # Between crossings the file is a nicety, not a contract, so cap how
        # often it is written — a flush per frame would make the meter the
        # bottleneck.
        if (self._path is not None
                and time.monotonic() - self._last_flush >= self._flush_every_s):
            self.flush()

    def flush(self) -> None:
        if self._path is None:
            return

        self._roll_if_needed()
        payload = {"month": self._month, "used_bytes": self._used}
        try:
            # Same directory as the target, so os.replace stays atomic on one
            # filesystem.  A partial write can never be mistaken for a count.
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent),
                prefix=self._path.name,
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(payload, fh)
                os.replace(tmp_name, self._path)
            except Exception:
                try:
                    os.unlink(tmp_name)
                except OSError:
                    pass
                raise
        except OSError as e:
            # A full disk or read-only volume must not stop the stream.  One
            # line, once, so the log says what happened without repeating it
            # on every frame.
            self._last_flush = time.monotonic()
            if not self._flush_error_printed:
                self._flush_error_printed = True
                print(f"[usage] could not write {self._path}: {e}")
            return

        self._last_flush = time.monotonic()

    def _restore(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            # Anything unexpected is treated as "no usable history": a count
            # that cannot be trusted is worse than starting the month at zero.
            if not isinstance(data, dict):
                return
            if data.get("month") != self._month:
                return
            used = data.get("used_bytes")
            if isinstance(used, bool) or not isinstance(used, int) or used < 0:
                return
            self._used = used
        except Exception:
            # Missing file, unreadable disk, corrupt JSON, wrong types — all
            # start from zero and none may raise on a stream's path.
            return

    # ── Reporting ────────────────────────────────────────────────────

    def resumes_on(self) -> date:
        """First day of the next UTC month."""
        today = self._utc()
        year = today.year + (1 if today.month == 12 else 0)
        month = 1 if today.month == 12 else today.month + 1
        return date(year, month, 1)

    def snapshot(self) -> dict:
        used = self.used_bytes
        return {
            "month": self._month,
            "used_gb": round(used / 1e9, 3),
            "limit_gb": round(self._limit / 1e9, 3) if self.enabled else None,
        }

    @classmethod
    def from_env(cls) -> "UsageMeter":
        raw = os.environ.get("CARDIOTWIN_MONTHLY_GB")
        limit = 0
        if raw is not None:
            try:
                gb = float(raw)
                # Zero, negatives, NaN and infinities are not an allowance;
                # refusing them keeps `over` from becoming true immediately.
                if not math.isfinite(gb) or gb <= 0:
                    raise ValueError(raw)
                limit = round(gb * 1e9)
            except (TypeError, ValueError):
                print(
                    f"[usage] CARDIOTWIN_MONTHLY_GB={raw!r} is not a usable "
                    "positive number of GB; monthly limit off"
                )
                limit = 0

        path_raw = os.environ.get("CARDIOTWIN_USAGE_FILE")
        path = (Path(path_raw) if path_raw
                else Path(tempfile.gettempdir()) / "cardiotwin_usage.json")
        return cls(limit_bytes=limit, path=path)
