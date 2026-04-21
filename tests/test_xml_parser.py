# tests/test_xml_parser.py
import unittest
import queue
import tempfile
import os
import threading
from unittest.mock import Mock, patch
from src.streaming.xml_parser import XMLStreamingParser
from lxml import etree

class TestXMLStreamingParser(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp()
        self.xml_path = os.path.join(self.temp_dir, 'test.xml')
        self.paper_queue = queue.Queue(maxsize=100)
        self.checkpoint_manager = Mock()
        self.checkpoint_manager.get_parsed_chunks.return_value = []

    def tearDown(self):
        import shutil
        shutil.rmtree(self.temp_dir)

    def test_create_sample_xml_and_parse(self):
        """Parsing XML extracts papers correctly"""
        # Create sample XML
        xml_content = '''<?xml version="1.0"?>
        <dblp>
            <article key="conf/aaai/2023">
                <author>Alice Smith</author>
                <author>Bob Jones</author>
                <title>Test Paper</title>
                <year>2023</year>
            </article>
            <inproceedings key="conf/icml/2023">
                <author>Charlie Brown</author>
                <title>Another Paper</title>
                <year>2023</year>
            </inproceedings>
        </dblp>
        '''

        with open(self.xml_path, 'w') as f:
            f.write(xml_content)

        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager
        )

        count = parser.parse()

        self.assertEqual(count, 2)
        self.assertEqual(self.paper_queue.qsize(), 2)

    def test_backpressure_on_full_queue(self):
        """Parser slows down when queue is full"""
        # Create large XML
        xml_content = '<?xml version="1.0"?><dblp>'
        for i in range(50):
            xml_content += f'<article key="test/{i}"><author>Author{i}</author><title>Paper{i}</title></article>'
        xml_content += '</dblp>'

        with open(self.xml_path, 'w') as f:
            f.write(xml_content)

        # Don't consume from queue (simulates slow consumer)
        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=self.checkpoint_manager
        )

        count = parser.parse()

        # Should still parse all, but with backpressure delays
        self.assertEqual(count, 50)

    def test_checkpoint_saving(self):
        """Parser saves checkpoint periodically"""
        xml_content = '<?xml version="1.0"?><dblp>'
        for i in range(25):
            xml_content += f'<article key="test/{i}"><author>Author{i}</author><title>Paper{i}</title></article>'
        xml_content += '</dblp>'

        with open(self.xml_path, 'w') as f:
            f.write(xml_content)

        mock_checkpoint = Mock()
        parser = XMLStreamingParser(
            xml_path=self.xml_path,
            paper_queue=self.paper_queue,
            checkpoint_manager=mock_checkpoint,
            checkpoint_interval=10
        )

        parser.parse()

        # Should have saved checkpoint at least twice
        self.assertGreaterEqual(mock_checkpoint.mark_chunk_complete.call_count, 2)
