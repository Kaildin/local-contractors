"""Resource monitor for ChromeDriver processes.

Tracks RAM and CPU consumption for each chromedriver instance and its
Chrome child processes. Works on both macOS and Linux via psutil.

Usage (standalone — monitor all chrome processes in real time)::

    python -m src.resource_monitor

Programmatic usage::

    from src.resource_monitor import ChromeResourceMonitor

    monitor = ChromeResourceMonitor(driver_pid=driver.service.process.pid)
    monitor.start()           # starts background sampling thread
    stats = monitor.snapshot() # {ram_mb, cpu_pct, pid, children_pids}
    monitor.log_stats()       # writes a log.INFO line
    monitor.stop()            # stops the background thread
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional

try:
    import psutil
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "psutil is required for resource monitoring. "
        "Install it with: pip install psutil>=5.9.0"
    ) from exc

logger = logging.getLogger(__name__)


@dataclass
class ResourceSnapshot:
    """Immutable snapshot of resource usage at a single point in time."""

    driver_pid: int
    ram_mb: float
    cpu_pct: float
    children_pids: List[int] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)

    def __str__(self) -> str:
        children_str = f", children={self.children_pids}" if self.children_pids else ""
        return (
            f"[PID {self.driver_pid}{children_str}] "
            f"RAM={self.ram_mb:.1f} MB  CPU={self.cpu_pct:.1f}%"
        )


class ChromeResourceMonitor:
    """Monitors RAM and CPU for a single chromedriver process tree.

    Args:
        driver_pid: PID of the chromedriver process (from
            ``driver.service.process.pid``).
        sample_interval: seconds between background samples (default 5).
        worker_label: optional string shown in log lines for identification.
    """

    def __init__(
        self,
        driver_pid: int,
        sample_interval: float = 5.0,
        worker_label: str = "",
    ) -> None:
        self.driver_pid = driver_pid
        self.sample_interval = sample_interval
        self.worker_label = worker_label
        self._proc: Optional[psutil.Process] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._last_snapshot: Optional[ResourceSnapshot] = None
        self._peak_ram_mb: float = 0.0

        try:
            self._proc = psutil.Process(driver_pid)
            # First cpu_percent call always returns 0 — reset the counter.
            self._proc.cpu_percent(interval=None)
        except psutil.NoSuchProcess:
            logger.warning(
                f"[ResourceMonitor] PID {driver_pid} not found — "
                "monitoring will be skipped."
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> "ChromeResourceMonitor":
        """Start background sampling thread. Returns self for chaining."""
        if self._proc is None:
            return self
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._sample_loop,
            name=f"chrome-monitor-{self.driver_pid}",
            daemon=True,
        )
        self._thread.start()
        logger.debug(
            f"[ResourceMonitor] Started monitoring PID {self.driver_pid} "
            f"(interval={self.sample_interval}s)"
        )
        return self

    def stop(self) -> None:
        """Stop background sampling thread."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.sample_interval + 2)
        logger.debug(
            f"[ResourceMonitor] Stopped monitoring PID {self.driver_pid}. "
            f"Peak RAM: {self._peak_ram_mb:.1f} MB"
        )

    def snapshot(self) -> Optional[ResourceSnapshot]:
        """Return a fresh point-in-time ResourceSnapshot (blocking, ~0.5 s).

        Returns None if the process no longer exists.
        """
        return self._take_snapshot(cpu_interval=0.5)

    def last_snapshot(self) -> Optional[ResourceSnapshot]:
        """Return the most recent snapshot taken by the background thread."""
        return self._last_snapshot

    def peak_ram_mb(self) -> float:
        """Return the peak RSS RAM (MB) observed since monitoring started."""
        return self._peak_ram_mb

    def log_stats(self, level: int = logging.INFO) -> None:
        """Capture a snapshot and emit it as a log line."""
        snap = self.snapshot()
        prefix = f"[{self.worker_label}] " if self.worker_label else ""
        if snap:
            logger.log(level, f"{prefix}ChromeDriver resources — {snap}")
        else:
            logger.log(
                level,
                f"{prefix}ChromeDriver PID {self.driver_pid} no longer running.",
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _take_snapshot(self, cpu_interval: float = 0.0) -> Optional[ResourceSnapshot]:
        if self._proc is None:
            return None
        try:
            children = self._proc.children(recursive=True)
            all_procs = [self._proc] + children

            total_ram = sum(
                p.memory_info().rss
                for p in all_procs
                if p.is_running()
            ) / 1024 / 1024

            if cpu_interval > 0:
                # Reset counters, wait, then read.
                for p in all_procs:
                    try:
                        p.cpu_percent(interval=None)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                time.sleep(cpu_interval)

            total_cpu = sum(
                p.cpu_percent(interval=None)
                for p in all_procs
                if p.is_running()
            )

            snap = ResourceSnapshot(
                driver_pid=self.driver_pid,
                ram_mb=round(total_ram, 2),
                cpu_pct=round(total_cpu, 2),
                children_pids=[p.pid for p in children],
            )
            if snap.ram_mb > self._peak_ram_mb:
                self._peak_ram_mb = snap.ram_mb
            return snap

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _sample_loop(self) -> None:
        """Background thread: sample every `sample_interval` seconds."""
        # Give Chrome a moment to fully start before first sample.
        time.sleep(2.0)
        while not self._stop_event.is_set():
            snap = self._take_snapshot(cpu_interval=0.0)
            if snap:
                self._last_snapshot = snap
                logger.debug(
                    f"[ResourceMonitor] {self.worker_label or f'PID {self.driver_pid}'} "
                    f"— {snap}"
                )
            self._stop_event.wait(self.sample_interval)


# ---------------------------------------------------------------------------
# Standalone CLI — watch all chrome/chromedriver processes in real time
# ---------------------------------------------------------------------------

def _watch_all_chrome() -> None:  # pragma: no cover
    """Print a live table of all Chrome-related processes (Ctrl+C to quit)."""
    import os

    TARGETS = ("chrome", "chromedriver", "google chrome helper", "chromium")

    print("Watching Chrome processes (Ctrl+C to quit)...\n")
    try:
        while True:
            rows = []
            for proc in psutil.process_iter(
                ["pid", "name", "memory_info", "cpu_percent", "ppid"]
            ):
                try:
                    name = (proc.info["name"] or "").lower()
                    if any(t in name for t in TARGETS):
                        mem_mb = proc.info["memory_info"].rss / 1024 / 1024
                        rows.append(
                            (
                                proc.info["pid"],
                                proc.info["name"],
                                round(mem_mb, 1),
                                proc.info["cpu_percent"],
                                proc.info["ppid"],
                            )
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            os.system("clear")
            print(f"{'PID':<8} {'PPID':<8} {'CPU %':<8} {'RAM (MB)':<12} Name")
            print("-" * 60)
            for pid, name, ram, cpu, ppid in sorted(rows, key=lambda r: r[0]):
                print(f"{pid:<8} {ppid:<8} {cpu:<8.1f} {ram:<12.1f} {name}")
            print(f"\n  Total processes: {len(rows)}")
            time.sleep(2)
    except KeyboardInterrupt:
        print("\nExiting.")


if __name__ == "__main__":  # pragma: no cover
    _watch_all_chrome()
