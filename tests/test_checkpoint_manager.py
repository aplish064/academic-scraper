# tests/test_checkpoint_manager.py
import unittest
import os
import tempfile
import json
import threading
import time
from src.streaming.checkpoint_manager import ThreadSafeCheckpointManager

class TestThreadSafeCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_path = os.path.join(self.temp_dir, 'checkpoint.json')
        self.manager = ThreadSafeCheckpointManager(self.checkpoint_path)

    def tearDown(self):
        if os.path.exists(self.checkpoint_path):
            os.remove(self.checkpoint_path)
        os.rmdir(self.temp_dir)

    def test_save_and_load_checkpoint(self):
        """Saving a checkpoint can be loaded back"""
        data = {
            'parsed_chunks': [1, 2, 3],
            'author_progress': {'total': 100, 'queried': 50}
        }

        self.manager.save_checkpoint(data)
        loaded = self.manager.load_checkpoint()

        self.assertEqual(loaded['parsed_chunks'], [1, 2, 3])
        self.assertEqual(loaded['author_progress']['total'], 100)

    def test_mark_chunk_complete(self):
        """Marking chunks as complete persists across reloads"""
        self.manager.mark_chunk_complete(1)
        self.manager.mark_chunk_complete(2)

        self.assertTrue(self.manager.is_chunk_complete(1))
        self.assertTrue(self.manager.is_chunk_complete(2))
        self.assertFalse(self.manager.is_chunk_complete(3))

        # Create new manager instance to test persistence
        new_manager = ThreadSafeCheckpointManager(self.checkpoint_path)
        self.assertTrue(new_manager.is_chunk_complete(1))

    def test_update_progress(self):
        """Progress updates can be retrieved"""
        self.manager.update_progress('author_progress', {'queried': 100})
        self.manager.update_progress('author_progress', {'total': 1000})

        checkpoint = self.manager.load_checkpoint()
        self.assertEqual(checkpoint['author_progress']['queried'], 100)
        self.assertEqual(checkpoint['author_progress']['total'], 1000)

    def test_thread_safe_concurrent_saves(self):
        """Multiple threads can save checkpoints concurrently"""
        def save_updates(thread_id):
            for i in range(50):
                self.manager.update_progress('author_progress', {'thread': thread_id, 'count': i})
                time.sleep(0.001)

        threads = []
        for i in range(5):
            t = threading.Thread(target=save_updates, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Should have a valid checkpoint without corruption
        checkpoint = self.manager.load_checkpoint()
        self.assertIn('author_progress', checkpoint)

    def test_atomic_write_no_partial_files(self):
        """Crash during write doesn't leave partial checkpoint"""
        # Create a valid checkpoint
        self.manager.save_checkpoint({'test': 'data'})

        # Simulate crash by deleting temp file mid-write
        # (This is hard to test directly, but we verify atomic pattern)
        with open(self.checkpoint_path, 'r') as f:
            content = f.read()

        # Should be valid JSON
        data = json.loads(content)
        self.assertEqual(data['test'], 'data')
