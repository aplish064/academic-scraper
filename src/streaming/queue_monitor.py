"""
Queue Monitor for backpressure detection.

Monitors queue size in background thread and triggers warnings when queue
exceeds threshold percentage of max capacity.
"""
import queue
import threading
import time
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)


class QueueMonitor:
    """
    Monitors a queue and tracks statistics for backpressure detection.

    Runs in background thread, polling queue size at regular intervals.
    Tracks current size, peak size, average size, and triggers warnings
    when queue exceeds warning threshold.
    """

    def __init__(
        self,
        paper_queue: queue.Queue,
        warning_threshold: int = 9000,
        monitor_interval: float = 5.0
    ):
        """
        Initialize QueueMonitor.

        Args:
            paper_queue: Queue to monitor
            warning_threshold: Percentage (0-100) of maxsize to trigger warning
            monitor_interval: Seconds between monitoring checks
        """
        self.queue = paper_queue
        self.warning_threshold = warning_threshold
        self.monitor_interval = monitor_interval

        # Threading control
        self._stop_event = threading.Event()
        self._monitor_thread = None

        # Statistics tracking (protected by lock)
        self._stats_lock = threading.Lock()
        self._stats = {
            'current_size': 0,
            'peak_size': 0,
            'avg_size': 0.0,
            'warning_triggered': False,
            'warning_count': 0,
            'samples': []  # Keep last 100 samples
        }

    def start(self) -> None:
        """Start background monitoring thread."""
        if self._monitor_thread is not None and self._monitor_thread.is_alive():
            logger.warning("QueueMonitor already running")
            return

        self._stop_event.clear()
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="QueueMonitor"
        )
        self._monitor_thread.start()
        logger.info(f"QueueMonitor started (interval={self.monitor_interval}s)")

    def stop(self) -> None:
        """
        Stop background monitoring thread.

        Waits up to 2x monitor_interval for thread to stop gracefully.
        """
        if self._monitor_thread is None or not self._monitor_thread.is_alive():
            return

        self._stop_event.set()
        self._monitor_thread.join(timeout=self.monitor_interval * 2)

        if self._monitor_thread.is_alive():
            logger.warning("QueueMonitor did not stop gracefully")
        else:
            logger.info("QueueMonitor stopped")

    def is_running(self) -> bool:
        """Check if monitor thread is currently running."""
        return self._monitor_thread is not None and self._monitor_thread.is_alive()

    def _monitor_loop(self) -> None:
        """
        Background thread loop that monitors queue size.

        Runs until stop_event is set, polling queue size at monitor_interval.
        Updates statistics and logs warnings when threshold exceeded.
        """
        while not self._stop_event.is_set():
            # Get current queue size
            current_size = self.queue.qsize()

            # Calculate threshold percentage
            maxsize = self.queue.maxsize or 0
            if maxsize > 0:
                usage_percent = (current_size / maxsize) * 100
            else:
                usage_percent = 0

            # Update statistics atomically
            with self._stats_lock:
                self._stats['current_size'] = current_size

                # Update peak
                if current_size > self._stats['peak_size']:
                    self._stats['peak_size'] = current_size

                # Update samples and average
                self._stats['samples'].append(current_size)
                if len(self._stats['samples']) > 100:
                    self._stats['samples'].pop(0)

                if self._stats['samples']:
                    self._stats['avg_size'] = sum(self._stats['samples']) / len(self._stats['samples'])

                # Check warning threshold
                if usage_percent >= self.warning_threshold:
                    if not self._stats['warning_triggered']:
                        self._stats['warning_triggered'] = True
                        self._stats['warning_count'] += 1
                        logger.warning(
                            f"Queue size {current_size}/{maxsize} "
                            f"({usage_percent:.1f}%) exceeds threshold "
                            f"{self.warning_threshold}%"
                        )
                else:
                    self._stats['warning_triggered'] = False

            # Wait for next interval or stop signal
            self._stop_event.wait(timeout=self.monitor_interval)

    def get_stats(self) -> Dict[str, Any]:
        """
        Get current statistics snapshot.

        Returns:
            Dict with current statistics (copy to avoid external modification)

        Note: current_size and peak_size are updated on-demand from the queue.
        Other stats (avg_size, warning_triggered, etc.) are only updated when
        the monitor thread is running.
        """
        with self._stats_lock:
            stats = self._stats.copy()
            # Always get fresh current_size directly from queue
            current_size = self.queue.qsize()
            stats['current_size'] = current_size

            # Update peak_size on-demand
            if current_size > stats['peak_size']:
                stats['peak_size'] = current_size
                self._stats['peak_size'] = current_size

            return stats
