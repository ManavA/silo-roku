"""Host-only durable receipts, sanitized native event journal, and advisory run lock.

Callers own lifecycle policy. This module never starts, stops, or cleans external work.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import re
import tempfile
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path


_RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?\Z")
_INTEGER = re.compile(r"(?:0|[1-9][0-9]*)\Z")
_BYTE_NUMBER = re.compile(r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z")
_UNKNOWN_MS = re.compile(r"(?:-1|0|[1-9][0-9]*)\Z")
_STATES = {"playing", "buffering", "paused", "finished", "error", "stopped"}
_ROLL_FIELDS = {
    "qa_roll_phase": {"g", "src", "local", "kind", "phase", "start", "end", "ms"},
    "qa_roll_work": {"g", "src", "local", "kind", "outcome", "at"},
    "qa_roll_bytes": {"source", "audio", "hash_source", "hash_audio"},
    "qa_roll_ticks": {"count", "total_ms", "max_ms"},
    "qa_roll_demand": {"g", "src", "local", "outcome", "queued_ms", "work_ms"},
    "qa_roll_admit": {"g", "src", "local", "visits", "evicted", "resident"},
}
_ADMISSION_SIGNED = {"lead_ms", "request_end_ms", "victim_first_end_ms", "victim_last_end_ms"}
_ADMISSION_OPTIONAL = {"protected", "deferred", "victim_first", "victim_last", "kind", "gate", "min_lead_ms", "window_ms"} | _ADMISSION_SIGNED
# Every accepted prefix and field is explicit. Unlisted text is rejected without echo.
_FIELDS = {
    "qa_video": {"phase", "state", "position", "wall_ms"},
    "qa_pair": {"refill", "seq", "bytes", "elapsed_ms", "duration_ms"},
    "qa_control": {"event", "position", "from", "target", "elapsed_ms", "wall_ms", "paused_ms"},
    "qa_http_done": {"route", "accept_ms", "header_ms", "first_ms", "last_ms", "close_ms"},
    "qa_http_bytes": {"route", "wire", "expected", "calls", "partials", "retries"},
    "qa_http_loop": {"route", "max_idle_ms", "stop_poll_ms", "loops"},
    "qa_http_io": {"route", "read_ms", "read_calls", "send_ms", "writable_waits"},
    "qa_http_defer": {"episode", "active", "cap", "loops", "wall_ms"},
    "qa_http_defer_end": {"episode", "active", "loops", "wall_ms"},
    "qa_memory": {"stage", "available_kb", "min_available_kb", "usage_pct", "max_usage_pct", "supported"},
    **_ROLL_FIELDS,
}
_FIELDS["qa_roll_admit"] = _ROLL_FIELDS["qa_roll_admit"] | _ADMISSION_OPTIONAL
_DECIMAL_FIELDS = {"position", "target", "from"}
_BYTE_FIELDS = {"source", "audio", "hash_source", "hash_audio", "resident"}


def sanitize_event(raw: str) -> str:
    """Return only canonical allowlisted text; never include rejected input in errors."""
    if not isinstance(raw, str):
        raise ValueError("invalid event")
    parts = raw.split()
    if not parts or parts[0] not in _FIELDS or len(parts) < 2:
        raise ValueError("invalid event")
    seen = set()
    clean = [parts[0]]
    for part in parts[1:]:
        if part.count("=") != 1:
            raise ValueError("invalid event")
        key, value = part.split("=", 1)
        if key not in _FIELDS[parts[0]] or key in seen:
            raise ValueError("invalid event")
        if key == "state":
            if value not in _STATES:
                raise ValueError("invalid event")
        elif parts[0] in _ROLL_FIELDS and key in _BYTE_FIELDS:
            if not _BYTE_NUMBER.fullmatch(value) or not math.isfinite(float(value)):
                raise ValueError("invalid event")
        elif parts[0] == "qa_roll_admit" and key in _ADMISSION_SIGNED:
            if not re.fullmatch(r"-?(?:0|[1-9][0-9]*)", value) or abs(int(value)) > 2147483647:
                raise ValueError("invalid event")
        elif parts[0] == "qa_roll_admit" and key in {"gate", "kind"}:
            if value not in ({"1", "2", "3", "4"} if key == "gate" else {"1", "2"}):
                raise ValueError("invalid event")
        elif (parts[0] == "qa_roll_demand" and key in {"queued_ms", "work_ms"}) or (parts[0] == "qa_roll_admit" and key in {"victim_first", "victim_last"}):
            if not _UNKNOWN_MS.fullmatch(value):
                raise ValueError("invalid event")
        elif not (_NUMBER if key in _DECIMAL_FIELDS else _INTEGER).fullmatch(value):
            raise ValueError("invalid event")
        seen.add(key)
        clean.append(f"{key}={value}")
    required_seen = seen - _ADMISSION_OPTIONAL if parts[0] == "qa_roll_admit" else seen
    if parts[0] in _ROLL_FIELDS and required_seen != _ROLL_FIELDS[parts[0]]:
        raise ValueError("invalid event")
    return " ".join(clean)


def _private_parent(path: Path) -> None:
    missing = []
    directory = path.parent
    while not directory.exists():
        missing.append(directory)
        directory = directory.parent
    for directory in reversed(missing):
        directory.mkdir(mode=0o700, exist_ok=True)
        os.chmod(directory, 0o700)
        _sync_dir(directory)
        _sync_dir(directory.parent)
    os.chmod(path.parent, 0o700)


def _sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _process_start_ticks(pid: int) -> int:
    # Split after comm, which may contain spaces and parentheses.
    stat = Path(f"/proc/{pid}/stat").read_text()
    return int(stat.rsplit(") ", 1)[1].split()[19])


@dataclass(frozen=True)
class ProcessIdentity:
    pid: int
    start_ticks: int

    @classmethod
    def current(cls) -> ProcessIdentity:
        pid = os.getpid()
        return cls(pid, _process_start_ticks(pid))

    def still_running(self) -> bool:
        try:
            return self.start_ticks == _process_start_ticks(self.pid)
        except (FileNotFoundError, ProcessLookupError, ValueError):
            return False


@dataclass(frozen=True)
class RunManifest:
    run_id: str
    artifact_sha256: str
    boot_id: str
    start_mono: float
    deadline_mono: float
    process: ProcessIdentity

    @classmethod
    def create(cls, run_id: str, artifact_sha256: str, lease_seconds: float,
               *, boot_id: str | None = None, now: float | None = None) -> RunManifest:
        if not isinstance(run_id, str) or not _RUN_ID.fullmatch(run_id):
            raise ValueError("invalid run id")
        if not isinstance(artifact_sha256, str) or not _SHA256.fullmatch(artifact_sha256):
            raise ValueError("invalid artifact digest")
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, (int, float)) or not math.isfinite(lease_seconds) or lease_seconds <= 0:
            raise ValueError("invalid lease")
        boot_id = boot_id if boot_id is not None else Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not isinstance(boot_id, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", boot_id):
            raise ValueError("invalid boot id")
        start = time.monotonic() if now is None else now
        if isinstance(start, bool) or not isinstance(start, (int, float)) or not math.isfinite(start) or start < 0:
            raise ValueError("invalid monotonic start")
        deadline = start + lease_seconds
        if not math.isfinite(deadline):
            raise ValueError("invalid deadline")
        return cls(run_id, artifact_sha256, boot_id, float(start), float(deadline),
                   ProcessIdentity.current())

    def expired(self, now: float, boot_id: str) -> bool:
        return boot_id != self.boot_id or now >= self.deadline_mono

    def artifact_matches(self, path: Path) -> bool:
        digest = hashlib.sha256()
        try:
            with Path(path).open("rb") as artifact:
                for chunk in iter(lambda: artifact.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError:
            return False
        return digest.hexdigest() == self.artifact_sha256


def atomic_receipt(path: Path, manifest: RunManifest, payload: dict) -> None:
    """Persist a bound JSON receipt: file fsync, atomic rename, directory fsync."""
    path = Path(path)
    _private_parent(path)
    data = json.dumps({"manifest": asdict(manifest), "payload": payload},
                      allow_nan=False, sort_keys=True, separators=(",", ":")).encode() + b"\n"
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode="wb", dir=path.parent, prefix=".receipt-",
                                         delete=False) as output:
            name = output.name
            os.chmod(name, 0o600)
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        name = None
        _sync_dir(path.parent)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def verify_receipt(path: Path, manifest: RunManifest) -> dict:
    """Reject receipts from another run, artifact, boot, or PID incarnation."""
    try:
        receipt = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError("invalid receipt") from error
    if not isinstance(receipt, dict) or receipt.get("manifest") != asdict(manifest) or not isinstance(receipt.get("payload"), dict):
        raise ValueError("invalid receipt identity")
    return receipt["payload"]


class EventJournal:
    """Append complete sanitized JSONL records and bound un-synced time."""

    def __init__(self, path: Path, *, fsync_interval: float = 1.0, now=time.monotonic):
        if isinstance(fsync_interval, bool) or not isinstance(fsync_interval, (int, float)) or not math.isfinite(fsync_interval) or fsync_interval <= 0:
            raise ValueError("invalid fsync interval")
        self.path = Path(path)
        self.interval = fsync_interval
        self.now = now
        self.output = None
        self.last_sync = None
        self._mutex = threading.Lock()
        self._timer = None
        self._dirty = False
        self._sync_error = None

    def __enter__(self) -> EventJournal:
        _private_parent(self.path)
        try:
            fd = os.open(self.path, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_APPEND, 0o600)
            created = True
        except FileExistsError:
            fd = os.open(self.path, os.O_RDWR | os.O_APPEND)
            created = False
        try:
            os.fchmod(fd, 0o600)
            if created:
                os.fsync(fd)
                _sync_dir(self.path.parent)
            size = os.fstat(fd).st_size
            if size and os.pread(fd, 1, size - 1) != b"\n":
                offset = size
                while offset:
                    start = max(0, offset - 8192)
                    chunk = os.pread(fd, offset - start, start)
                    newline = chunk.rfind(b"\n")
                    if newline >= 0:
                        os.ftruncate(fd, start + newline + 1)
                        break
                    offset = start
                else:
                    os.ftruncate(fd, 0)
                os.fsync(fd)
            self.output = os.fdopen(fd, "ab", buffering=0)
        except BaseException:
            os.close(fd)
            raise
        self.last_sync = self.now()
        return self

    def _schedule_sync(self) -> None:
        if self._timer is None:
            self._timer = threading.Timer(self.interval, self._timer_sync)
            self._timer.daemon = True
            self._timer.start()

    def _timer_sync(self) -> None:
        with self._mutex:
            self._timer = None
            if self.output is not None and self._dirty:
                try:
                    self._flush_locked()
                except OSError as error:
                    self._sync_error = error

    def append(self, elapsed: float, event: str) -> None:
        if self.output is None:
            raise RuntimeError("journal is closed")
        if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
            raise ValueError("invalid elapsed")
        safe_event = sanitize_event(event)
        record = json.dumps({"elapsed": elapsed, "event": safe_event}, separators=(",", ":"))
        with self._mutex:
            if self.output is None:
                raise RuntimeError("journal is closed")
            if self._sync_error is not None:
                raise OSError("journal background sync failed") from self._sync_error
            self.output.write(record.encode() + b"\n")
            self._dirty = True
            if self.now() - self.last_sync >= self.interval:
                self._flush_locked()
            else:
                self._schedule_sync()

    def _flush_locked(self) -> None:
        self.output.flush()
        os.fsync(self.output.fileno())
        self.last_sync = self.now()
        self._dirty = False
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def flush(self) -> None:
        with self._mutex:
            if self.output is None:
                raise RuntimeError("journal is closed")
            if self._sync_error is not None:
                raise OSError("journal background sync failed") from self._sync_error
            self._flush_locked()

    def close(self) -> None:
        with self._mutex:
            if self.output is not None:
                try:
                    self._flush_locked()
                finally:
                    self.output.close()
                    self.output = None
                if self._sync_error is not None:
                    raise OSError("journal background sync failed") from self._sync_error

    def __exit__(self, *_exc) -> None:
        self.close()


def read_events(path: Path) -> tuple[list[dict], bool]:
    """Read analyzer-compatible records; report an incomplete tail, reject bad interior."""
    data = Path(path).read_bytes()
    complete, tail = (data, b"") if data.endswith(b"\n") else data.rsplit(b"\n", 1) if b"\n" in data else (b"", data)
    rows = []
    for index, raw in enumerate(complete.splitlines(), 1):
        try:
            row = json.loads(raw)
            if not isinstance(row, dict) or set(row) != {"elapsed", "event"}:
                raise ValueError
            elapsed = row["elapsed"]
            if isinstance(elapsed, bool) or not isinstance(elapsed, (int, float)) or not math.isfinite(elapsed) or elapsed < 0:
                raise ValueError
            row["event"] = sanitize_event(row["event"])
            rows.append(row)
        except (UnicodeError, json.JSONDecodeError, ValueError, TypeError) as error:
            raise ValueError(f"invalid journal record {index}") from error
    return rows, bool(tail)


class RunLock:
    """Nonblocking flock retries; the kernel releases a killed holder's lock."""

    def __init__(self, path: Path, *, timeout: float, poll_interval: float = 0.01):
        self.path = Path(path)
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout < 0
                or isinstance(poll_interval, bool) or not isinstance(poll_interval, (int, float))
                or not math.isfinite(poll_interval) or poll_interval <= 0):
            raise ValueError("invalid lock timeout")
        self.timeout = timeout
        self.poll_interval = poll_interval
        self.fd = None

    def __enter__(self) -> RunLock:
        _private_parent(self.path)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        os.fchmod(fd, 0o600)
        deadline = time.monotonic() + self.timeout
        try:
            while True:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    self.fd = fd
                    return self
                except BlockingIOError:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError("run lock unavailable")
                    time.sleep(min(self.poll_interval, remaining))
        except BaseException:
            os.close(fd)
            raise

    def __exit__(self, *_exc) -> None:
        if self.fd is not None:
            fcntl.flock(self.fd, fcntl.LOCK_UN)
            os.close(self.fd)
            self.fd = None
