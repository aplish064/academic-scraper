# src/streaming/checkpoint_manager.py
import os
import json
import time
from typing import Dict, Any, List
from threading import RLock


class ThreadSafeCheckpointManager:
    """Thread-safe checkpoint manager with atomic saves for crash recovery."""

    def __init__(self, checkpoint_path: str):
        """Initialize checkpoint manager with path and thread lock."""
        self.checkpoint_path = checkpoint_path
        self._lock = RLock()
        self._ensure_checkpoint_exists()

    def _ensure_checkpoint_exists(self):
        """Create checkpoint file with default structure if it doesn't exist."""
        with self._lock:
            if not os.path.exists(self.checkpoint_path):
                default_data = {
                    'parsed_chunks': [],
                    'author_progress': {
                        'total_queued': 0,
                        'queried': 0,
                        'processed': 0
                    },
                    'db_stats': {
                        'authors_written': 0,
                        'papers_written': 0
                    },
                    'last_updated': time.time()
                }
                self._save_atomic(default_data)

    def save_checkpoint(self, data: Dict[str, Any]):
        """Save checkpoint data with timestamp."""
        with self._lock:
            data['last_updated'] = time.time()
            self._save_atomic(data)

    def _save_atomic(self, data: Dict[str, Any]):
        """Atomically save data to checkpoint file using temp file + rename."""
        temp_path = self.checkpoint_path + '.tmp'
        with open(temp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.rename(temp_path, self.checkpoint_path)

    def load_checkpoint(self) -> Dict[str, Any]:
        """Load and return checkpoint data."""
        with self._lock:
            with open(self.checkpoint_path, 'r') as f:
                return json.load(f)

    def mark_chunk_complete(self, chunk_id: int):
        """Mark a chunk as complete and persist to disk."""
        with self._lock:
            checkpoint = self.load_checkpoint()
            if chunk_id not in checkpoint['parsed_chunks']:
                checkpoint['parsed_chunks'].append(chunk_id)
            self.save_checkpoint(checkpoint)

    def is_chunk_complete(self, chunk_id: int) -> bool:
        """Check if a chunk has been completed."""
        with self._lock:
            checkpoint = self.load_checkpoint()
            return chunk_id in checkpoint['parsed_chunks']

    def update_progress(self, component: str, progress: Dict[str, Any]):
        """Merge progress updates into component dict and save."""
        with self._lock:
            checkpoint = self.load_checkpoint()
            if component not in checkpoint:
                checkpoint[component] = {}
            checkpoint[component].update(progress)
            self.save_checkpoint(checkpoint)

    def get_parsed_chunks(self) -> List[int]:
        """Return list of completed chunk IDs."""
        with self._lock:
            checkpoint = self.load_checkpoint()
            return checkpoint['parsed_chunks'].copy()
