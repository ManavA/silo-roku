"""Host-only QA run supervision. No device or server cleanup adapter lives here.

The watchdog and runner are separate transient systemd user services. A plan is
written before either starts. An interrupted cleanup may be retried; external
cleanup actions are not claimed to be exactly once.

An optional frozen monitor command is read-only: exit 0 means healthy, 75 requests
resource-limit stop, and all other exits/execution failures request monitor-failed
stop. Timeout requests monitor-timeout stop. Output is discarded. The monitor
never restores, logs out, or cleans up: the watchdog records a manifest-bound
stop-request receipt and uses its existing runner-drain and cleanup authority.
A stale/malformed stop request fails closed as invalid-stop-request. Monitor
execution and polling cannot extend the original lease; cleanup retains its
separate original claimed grace.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path

from qa_durable import ProcessIdentity, RunLock, RunManifest, atomic_receipt, verify_receipt


_STOP_REASONS = {"resource-limit", "monitor-failed", "monitor-timeout", "invalid-stop-request"}


def _private_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise
    directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


def _command(value: list[str]) -> list[str]:
    if not isinstance(value, list) or not value or any(
        not isinstance(x, str) or not x or "\x00" in x for x in value
    ):
        raise ValueError("invalid command")
    if not Path(value[0]).is_absolute():
        raise ValueError("command executable must be absolute")
    return value


def prepare(root: Path, run_id: str, artifact: Path, lease_seconds: float,
            runner: list[str], cleanup: list[str], *, cleanup_grace: float = 30.0,
            monitor: list[str] | None = None, monitor_timeout: float = 5.0) -> RunManifest:
    """Freeze private commands and original lease before launching any work."""
    root = Path(root)
    artifact = Path(artifact).resolve(strict=True)
    if not artifact.is_file():
        raise ValueError("invalid artifact")
    if (isinstance(cleanup_grace, bool) or not isinstance(cleanup_grace, (int, float))
            or not math.isfinite(cleanup_grace) or cleanup_grace <= 0):
        raise ValueError("invalid cleanup grace")
    digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
    manifest = RunManifest.create(run_id, digest, lease_seconds)
    if not math.isfinite(manifest.deadline_mono):
        raise ValueError("invalid deadline")
    plan = {"artifact": str(artifact), "runner": _command(runner),
            "cleanup": _command(cleanup), "cleanup_grace": float(cleanup_grace)}
    if monitor is not None:
        if (isinstance(monitor_timeout, bool) or not isinstance(monitor_timeout, (int, float))
                or not math.isfinite(monitor_timeout) or monitor_timeout <= 0):
            raise ValueError("invalid monitor timeout")
        plan.update(monitor=_command(monitor), monitor_timeout=float(monitor_timeout))
    packed = json.dumps(plan, sort_keys=True, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    directory = os.open(root.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
    _private_write(root / "plan.json", packed)
    atomic_receipt(root / "manifest.json", manifest,
                   {"plan_sha256": hashlib.sha256(packed).hexdigest()})
    return manifest


def _checked_manifest(identity: dict) -> RunManifest:
    if not isinstance(identity, dict) or set(identity) != {
        "run_id", "artifact_sha256", "boot_id", "start_mono", "deadline_mono", "process"
    }:
        raise ValueError("invalid supervision plan")
    process_data = identity["process"]
    if not isinstance(process_data, dict) or set(process_data) != {"pid", "start_ticks"}:
        raise ValueError("invalid supervision plan")
    if (not isinstance(identity["run_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,79}", identity["run_id"])
            or not isinstance(identity["artifact_sha256"], str)
            or not re.fullmatch(r"[0-9a-f]{64}", identity["artifact_sha256"])
            or not isinstance(identity["boot_id"], str)
            or not re.fullmatch(r"[A-Za-z0-9-]{1,80}", identity["boot_id"])):
        raise ValueError("invalid supervision plan")
    for field in ("start_mono", "deadline_mono"):
        value = identity[field]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError("invalid supervision plan")
    if identity["start_mono"] < 0 or identity["deadline_mono"] <= identity["start_mono"]:
        raise ValueError("invalid supervision plan")
    for field in ("pid", "start_ticks"):
        value = process_data[field]
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ValueError("invalid supervision plan")
    return RunManifest(**{**identity, "process": ProcessIdentity(**process_data)})


def load_plan(root: Path) -> tuple[RunManifest, dict]:
    root = Path(root)
    try:
        packed = (root / "plan.json").read_bytes()
        stored = json.loads((root / "manifest.json").read_text())
        identity = stored["manifest"]
        manifest = _checked_manifest(identity)
        expected = verify_receipt(root / "manifest.json", manifest)["plan_sha256"]
        plan = json.loads(packed)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as error:
        raise ValueError("invalid supervision plan") from error
    if hashlib.sha256(packed).hexdigest() != expected:
        raise ValueError("plan mismatch")
    required = {"artifact", "runner", "cleanup", "cleanup_grace"}
    if set(plan) not in (required, required | {"monitor", "monitor_timeout"}):
        raise ValueError("invalid supervision plan")
    if "monitor" in plan:
        _command(plan["monitor"])
        value = plan["monitor_timeout"]
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value) or value <= 0):
            raise ValueError("invalid monitor timeout")
    _command(plan["runner"])
    _command(plan["cleanup"])
    if not isinstance(plan["artifact"], str) or not Path(plan["artifact"]).is_absolute():
        raise ValueError("invalid artifact path")
    if (not isinstance(plan["cleanup_grace"], (float, int))
            or isinstance(plan["cleanup_grace"], bool)
            or not math.isfinite(plan["cleanup_grace"]) or plan["cleanup_grace"] <= 0):
        raise ValueError("invalid cleanup grace")
    if not manifest.artifact_matches(Path(plan["artifact"])):
        raise ValueError("artifact mismatch")
    if manifest.boot_id != Path("/proc/sys/kernel/random/boot_id").read_text().strip():
        raise ValueError("boot mismatch")
    if not (math.isfinite(manifest.start_mono) and math.isfinite(manifest.deadline_mono)
            and manifest.deadline_mono > manifest.start_mono):
        raise ValueError("invalid deadline")
    return manifest, plan


def _admit_runner(root: Path, manifest: RunManifest) -> None:
    """Caller holds watch.lock; any cleanup/stop fence forbids new work."""
    for filename in ("stop-request.json", "cleanup-claim.json", "terminal.json"):
        path = root / filename
        if path.exists():
            verify_receipt(path, manifest)
            raise ValueError("run stopping or terminal")


def run_worker(root: Path) -> None:
    """Exec the runner with an independent timer for the original lease.

    Linux preserves ITIMER_REAL across exec. Systemd fences the whole service
    cgroup; the timer also ends this process if the watchdog cannot get a lock.
    """
    manifest, plan = load_plan(root)
    root = Path(root)
    remaining = manifest.deadline_mono - time.monotonic()
    if remaining <= 0:
        raise ValueError("lease expired")
    with RunLock(root / "watch.lock", timeout=remaining):
        _admit_runner(root, manifest)
        if manifest.expired(time.monotonic(), manifest.boot_id):
            raise ValueError("lease expired")
        if (root / "runner-started.json").exists():
            raise ValueError("runner already started")
        atomic_receipt(root / "runner-started.json", manifest,
                       {"process": asdict(ProcessIdentity.current())})
    remaining = manifest.deadline_mono - time.monotonic()
    if remaining <= 0:
        raise ValueError("lease expired")
    signal.signal(signal.SIGALRM, signal.SIG_DFL)
    signal.setitimer(signal.ITIMER_REAL, remaining)
    os.execv(plan["runner"][0], plan["runner"])


def _started_process(root: Path, manifest: RunManifest) -> ProcessIdentity | None:
    path = root / "runner-started.json"
    if not path.exists():
        return None
    try:
        data = verify_receipt(path, manifest)
        return ProcessIdentity(**data["process"])
    except (ValueError, TypeError, KeyError) as error:
        raise ValueError("invalid runner identity") from error


def _bounded_command(command: list[str], remaining: float) -> int:
    """Reap the direct child and fence its dedicated group, including descendants."""
    process = subprocess.Popen(command, start_new_session=True,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        return process.wait(timeout=remaining)
    finally:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait()


def _stop_runner_unit(unit: str, cleanup_deadline: float, now: float) -> bool:
    """Require a completed stop and proof that the exact service cgroup drained."""
    def invoke(*arguments: str) -> subprocess.CompletedProcess:
        remaining = cleanup_deadline - max(now, time.monotonic())
        if remaining <= 0:
            raise TimeoutError("cleanup deadline reached")
        return subprocess.run(["systemctl", "--user", *arguments, unit],
                              timeout=min(remaining, 5), check=False,
                              stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)

    def status() -> dict[str, str]:
        result = invoke("show", "--property=LoadState,ActiveState,ControlGroup")
        fields = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
        if result.returncode != 0 or set(fields) != {"LoadState", "ActiveState", "ControlGroup"}:
            raise ValueError("runner status unavailable")
        return fields

    try:
        before = status()
        invoke("stop")
        after = status()
        if after["ActiveState"] != "inactive" or after["LoadState"] not in {"loaded", "not-found"}:
            return False
        for group in {before["ControlGroup"], after["ControlGroup"]} - {""}:
            if not group.startswith("/") or ".." in Path(group).parts:
                return False
            try:
                events = (Path("/sys/fs/cgroup") / group.lstrip("/") / "cgroup.events").read_text()
            except FileNotFoundError:
                continue
            if "populated 0" not in events.splitlines():
                return False
        return True
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return False


def watch_once(root: Path, *, now: float | None = None, lock_timeout: float = 1.0) -> str:
    """Observe once; claim and execute bounded cleanup when runner dies/lease ends."""
    root = Path(root)
    with RunLock(root / "watch.lock", timeout=lock_timeout):
        manifest, plan = load_plan(root)
        now = time.monotonic() if now is None else now
        terminal = root / "terminal.json"
        if terminal.exists():
            payload = verify_receipt(terminal, manifest)
            return "already-" + payload["stage"]
        started = _started_process(root, manifest)
        expired = manifest.expired(now, manifest.boot_id)
        stop_reason = None
        stop_path = root / "stop-request.json"
        if stop_path.exists():
            try:
                request = verify_receipt(stop_path, manifest)
                if set(request) != {"reason"} or request["reason"] not in _STOP_REASONS:
                    raise ValueError("invalid stop request")
                stop_reason = request["reason"]
            except (OSError, ValueError, TypeError, KeyError):
                stop_reason = "invalid-stop-request"
                atomic_receipt(stop_path, manifest, {"reason": stop_reason})
        if (not expired and stop_reason is None and "monitor" in plan
                and started is not None and started.still_running()):
            remaining = manifest.deadline_mono - max(now, time.monotonic())
            if remaining > 0:
                try:
                    result = _bounded_command(plan["monitor"], min(plan["monitor_timeout"], remaining))
                    if result != 0:
                        stop_reason = "resource-limit" if result == 75 else "monitor-failed"
                except subprocess.TimeoutExpired:
                    stop_reason = "monitor-timeout"
                except OSError:
                    stop_reason = "monitor-failed"
                if stop_reason is not None:
                    atomic_receipt(stop_path, manifest, {"reason": stop_reason})
            now = max(now, time.monotonic())
            expired = manifest.expired(now, manifest.boot_id)
        if not expired and stop_reason is None and (started is None or started.still_running()):
            return "waiting"
        claim_path = root / "cleanup-claim.json"
        if claim_path.exists():
            claim = verify_receipt(claim_path, manifest)
            cleanup_deadline = claim["cleanup_deadline_mono"]
        else:
            cleanup_deadline = min(now, manifest.deadline_mono) + plan["cleanup_grace"]
            atomic_receipt(claim_path, manifest,
                           {"stage": "claimed", "reason": stop_reason or ("lease" if expired else "runner-exit"),
                            "cleanup_deadline_mono": cleanup_deadline})
        # This bound is independent of the playback lease. It only permits cleanup.
        remaining = cleanup_deadline - now
        if remaining <= 0:
            atomic_receipt(terminal, manifest, {"stage": "failed", "reason": "cleanup-timeout"})
            return "failed"
        service = root / "services.json"
        if service.exists():
            services = verify_receipt(service, manifest)
            if not _stop_runner_unit(services["runner"], cleanup_deadline, now):
                return "runner-still-live"
        if started is not None and started.still_running():
            return "runner-still-live"
        remaining = cleanup_deadline - max(now, time.monotonic())
        if remaining <= 0:
            atomic_receipt(terminal, manifest, {"stage": "failed", "reason": "cleanup-timeout"})
            return "failed"
        try:
            result = _bounded_command(plan["cleanup"], remaining)
            if result != 0:
                raise RuntimeError("cleanup failed")
        except (OSError, subprocess.TimeoutExpired, RuntimeError):
            atomic_receipt(terminal, manifest, {"stage": "failed", "reason": "cleanup-failed"})
            return "failed"
        atomic_receipt(terminal, manifest, {"stage": "cleaned"})
        return "cleaned"


def watch(root: Path, *, poll_interval: float = 0.2) -> str:
    while True:
        try:
            result = watch_once(root)
        except TimeoutError:
            result = "waiting"
        if result not in {"waiting", "runner-still-live"}:
            return result
        manifest, _ = load_plan(root)
        deadline = manifest.deadline_mono
        claim = Path(root) / "cleanup-claim.json"
        if claim.exists():
            deadline = verify_receipt(claim, manifest)["cleanup_deadline_mono"]
        time.sleep(max(0.0, min(poll_interval, deadline - time.monotonic())))


def _unit(run_id: str, role: str) -> str:
    return f"roku-qa-{run_id}-{role}.service"


def launch(root: Path) -> tuple[str, str]:
    """Start watchdog first and runner second in distinct transient user cgroups."""
    root = Path(root).resolve()
    manifest, plan = load_plan(root)
    if (root / "services.json").exists():
        raise ValueError("run already launched")
    remaining = manifest.deadline_mono - time.monotonic()
    if remaining <= 0:
        raise ValueError("lease expired")
    with RunLock(root / "watch.lock", timeout=remaining):
        _admit_runner(root, manifest)
        if (root / "services.json").exists():
            raise ValueError("run already launched")
        runner = _unit(manifest.run_id, "runner")
        watchdog = _unit(manifest.run_id, "watchdog")
        python = sys.executable
        script = str(Path(__file__).resolve())
        for role, unit in (("watch", watchdog), ("run", runner)):
            if role == "run":
                _admit_runner(root, manifest)
            remaining = manifest.deadline_mono - time.monotonic()
            if remaining <= 0:
                raise ValueError("lease expired")
            maximum = remaining + plan["cleanup_grace"] + 5 if role == "watch" else remaining
            command = ["systemd-run", "--user", "--collect", "--unit", unit,
                       "--property=Type=exec", "--property=Restart=no",
                       f"--property=RuntimeMaxSec={maximum:.6f}s",
                       python, script, role, str(root)]
            subprocess.run(command, check=True, timeout=min(10, remaining), stdout=subprocess.DEVNULL,
                           stderr=subprocess.DEVNULL)
            if role == "watch":
                atomic_receipt(root / "services.json", manifest,
                               {"runner": runner, "watchdog": watchdog})
        return runner, watchdog


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "launch", "run", "watch"))
    parser.add_argument("root", type=Path)
    parser.add_argument("plan_file", nargs="?", type=Path)
    args = parser.parse_args()
    if args.action == "prepare":
        if args.plan_file is None:
            parser.error("prepare requires a private JSON plan file")
        plan = json.loads(args.plan_file.read_text())
        prepare(args.root, plan["run_id"], Path(plan["artifact"]), plan["lease_seconds"],
                plan["runner"], plan["cleanup"], cleanup_grace=plan["cleanup_grace"],
                monitor=plan.get("monitor"), monitor_timeout=plan.get("monitor_timeout", 5.0))
    elif args.action == "launch":
        launch(args.root)
    elif args.action == "run":
        run_worker(args.root)
    else:
        return 0 if watch(args.root) in {"cleaned", "already-cleaned"} else 1
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(type(error).__name__ + ": supervision operation failed", file=sys.stderr)
        raise SystemExit(1)
