# tests/test_author_matcher.py
import unittest
import pandas as pd
from unittest.mock import Mock, MagicMock, patch
from src.streaming.author_matcher import StreamingAuthorMatcher
from src.streaming.author_cache import ThreadSafeAuthorCache
from src.streaming.checkpoint_manager import ThreadSafeCheckpointManager
import tempfile
import os

class TestStreamingAuthorMatcher(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.checkpoint_path = os.path.join(self.temp_dir, 'checkpoint.json')
        self.checkpoint_manager = ThreadSafeCheckpointManager(self.checkpoint_path)
        self.author_cache = ThreadSafeAuthorCache()

        # Mock database client
        self.db_client = Mock()

        # Mock CSrankings data
        self.csrankings_data = pd.DataFrame({
            'name': ['Alice Smith', 'Bob Jones'],
            'affiliation': ['MIT', 'Stanford'],
            'homepage': ['http://alice.com', 'http://bob.com'],
            'scholarid': ['ABC123', 'DEF456'],
            'orcid': ['0000-0001', '0000-0002']
        })

        self.matcher = StreamingAuthorMatcher(
            author_cache=self.author_cache,
            checkpoint_manager=self.checkpoint_manager,
            csrankings_data=self.csrankings_data,
            db_client=self.db_client
        )

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_query_single_author_success(self):
        """Querying an author successfully returns data"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'hits': {
                        'hit': [{
                            'info': {
                                'url': 'https://dblp.org/alice',
                                'notes': {
                                    'note': [
                                        {'@text': 'Orcid: 0000-0001-2345-6789'}
                                    ]
                                },
                                'persons': {
                                    'person': [{
                                        'orcid': '0000-0001-2345-6789'
                                    }]
                                }
                            }
                        }]
                    }
                }
            }
            mock_get.return_value = mock_response

            result = self.matcher._query_author_api('Alice Smith')

            self.assertIsNotNone(result)
            self.assertEqual(result['url'], 'https://dblp.org/alice')
            self.assertEqual(result['orcid'], '0000-0001-2345-6789')

    def test_query_single_author_not_found(self):
        """Querying non-existent author returns None"""
        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 404
            mock_get.return_value = mock_response

            result = self.matcher._query_author_api('Nonexistent Author')

            self.assertIsNone(result)

    def test_write_author_to_database(self):
        """Writing author to database calls correct INSERT"""
        author_data = {
            'name': 'Alice Smith',
            'dblp_url': 'https://dblp.org/alice',
            'orcid': '0000-0001-2345-6789',
            'papers': ['p1', 'p2']
        }

        self.matcher._write_author_to_db(author_data)

        self.db_client.execute.assert_called_once()
        call_args = self.db_client.execute.call_args
        self.assertIn('INSERT', call_args[0][0])

    def test_process_batch_of_authors(self):
        """Processing a batch queries authors and writes to database"""
        # Add authors to cache
        self.author_cache.add_paper({'paper_id': 'p1', 'authors': ['Alice Smith']})
        self.author_cache.add_paper({'paper_id': 'p2', 'authors': ['Bob Jones']})

        with patch('requests.get') as mock_get:
            mock_response = Mock()
            mock_response.status_code = 200
            mock_response.json.return_value = {
                'result': {
                    'hits': {
                        'hit': [{
                            'info': {
                                'url': 'https://dblp.org/test',
                                'notes': {'note': []},
                                'persons': {'person': []}
                            }
                        }]
                    }
                }
            }
            mock_get.return_value = mock_response

            stats = self.matcher.process_batch({'Alice Smith', 'Bob Jones'})

            self.assertEqual(stats['queried'], 2)
            self.assertEqual(stats['written'], 2)
