# tests/test_queue_monitor.py
import unittest
import queue
import time
import threading
from src.streaming.queue_monitor import QueueMonitor

class TestQueueMonitor(unittest.TestCase):
    def setUp(self):
        self.paper_queue = queue.Queue(maxsize=100)
        # Use faster monitoring interval for tests (0.5s instead of 5s)
        self.monitor = QueueMonitor(self.paper_queue, warning_threshold=90, monitor_interval=0.5)

    def tearDown(self):
        if self.monitor.is_running():
            self.monitor.stop()

    def test_monitor_detects_queue_size(self):
        """Monitor tracks queue size over time"""
        # Add 50 items
        for i in range(50):
            self.paper_queue.put(i)

        stats = self.monitor.get_stats()
        self.assertEqual(stats['current_size'], 50)

    def test_warning_threshold_detection(self):
        """Monitor logs warning when queue exceeds threshold"""
        self.monitor.start()
        time.sleep(0.1)  # Let monitor start

        # Fill to 95% (exceeds 90% threshold)
        for i in range(95):
            self.paper_queue.put(i)

        time.sleep(0.6)  # Wait for monitor cycle

        stats = self.monitor.get_stats()
        self.assertTrue(stats['warning_triggered'])

    def test_peak_size_tracking(self):
        """Monitor tracks peak queue size"""
        for i in range(70):
            self.paper_queue.put(i)

        stats = self.monitor.get_stats()
        self.assertEqual(stats['peak_size'], 70)

        # Add more
        for i in range(10):
            self.paper_queue.put(i)

        stats = self.monitor.get_stats()
        self.assertEqual(stats['peak_size'], 80)

    def test_monitor_stops_cleanly(self):
        """Monitor can be started and stopped"""
        self.monitor.start()
        self.assertTrue(self.monitor.is_running())

        self.monitor.stop()
        self.assertFalse(self.monitor.is_running())

    def test_background_thread_updates_stats(self):
        """Background thread continuously updates stats"""
        self.monitor.start()
        time.sleep(0.1)

        for i in range(60):
            self.paper_queue.put(i)

        time.sleep(0.6)  # Wait for monitor cycle
        stats = self.monitor.get_stats()

        self.assertGreater(stats['avg_size'], 0)
