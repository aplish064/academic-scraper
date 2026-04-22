# src/streaming/xml_parser.py
import time
from typing import Dict, Any
from lxml import etree
from .ccf_mapping import get_ccf_classification


class XMLStreamingParser:
    """Streaming XML parser with backpressure and checkpointing."""

    # Paper type tags to parse from DBLP XML
    PAPER_TAGS = {
        'article', 'inproceedings', 'proceedings', 'book',
        'incollection', 'phdthesis', 'mastersthesis'
    }

    def __init__(
        self,
        xml_path: str,
        paper_queue,
        checkpoint_manager,
        checkpoint_interval: int = 10000,
        backpressure_threshold: float = 0.9
    ):
        """Initialize XML streaming parser.

        Args:
            xml_path: Path to DBLP XML file
            paper_queue: Queue to put parsed papers into
            checkpoint_manager: ThreadSafeCheckpointManager instance
            checkpoint_interval: Save checkpoint every N papers
            backpressure_threshold: Queue fill ratio (0.0-1.0) to trigger backpressure
        """
        self.xml_path = xml_path
        self.paper_queue = paper_queue
        self.checkpoint_manager = checkpoint_manager
        self.checkpoint_interval = checkpoint_interval
        self.backpressure_threshold = backpressure_threshold
        self.queue_maxsize = paper_queue.maxsize

    def _extract_paper_data(self, element: etree.Element) -> Dict[str, Any]:
        """Extract paper data from XML element.

        Args:
            element: lxml Element representing a paper

        Returns:
            Dict with paper_id, authors, title, year, venue, doi, etc.
        """
        paper_id = element.get('key')

        # Extract authors
        authors = [
            author.text
            for author in element.findall('author')
            if author.text
        ]

        # Extract title and year
        title_elem = element.find('title')
        title = title_elem.text if title_elem is not None else None

        year_elem = element.find('year')
        year = year_elem.text if year_elem is not None else None

        # Extract venue/journal based on element type
        # DBLP uses different fields for different publication types
        venue = None
        if element.tag == 'article':
            # Articles use <journal>
            venue_elem = element.find('journal')
            venue = venue_elem.text if venue_elem is not None and venue_elem.text else None
        elif element.tag in ['inproceedings', 'incollection', 'proceedings', 'book']:
            # Conferences and collections use <booktitle>
            venue_elem = element.find('booktitle')
            venue = venue_elem.text if venue_elem is not None and venue_elem.text else None

        # Extract DOI from <ee> tag (not <doi>)
        doi = None
        ee_elem = element.find('ee')
        if ee_elem is not None and ee_elem.text:
            ee_text = ee_elem.text
            # Extract DOI from URLs like "https://doi.org/10.1007/..."
            if 'doi.org/' in ee_text:
                # Extract DOI from URL
                import re
                doi_match = re.search(r'doi\.org/([0-9.]+/[0-9]+)', ee_text)
                if doi_match:
                    doi = doi_match.group(1)
            elif ee_text.startswith('http') and '/' in ee_text:
                # Use last part of URL as DOI fallback
                parts = ee_text.rstrip('/').split('/')
                if parts:
                    last_part = parts[-1]
                    # Check if it looks like a DOI (contains numbers)
                    if re.search(r'\d+', last_part):
                        doi = last_part

        # Extract electronic edition (EE) URL (full URL)
        ee = ee_elem.text if ee_elem is not None and ee_elem is not None else None

        # Extract volume
        volume_elem = element.find('volume')
        volume = volume_elem.text if volume_elem is not None else None

        # Extract number
        number_elem = element.find('number')
        number = number_elem.text if number_elem is not None else None

        # Extract pages
        pages_elem = element.find('pages')
        pages = pages_elem.text if pages_elem is not None else None

        # Extract publisher
        publisher_elem = element.find('publisher')
        publisher = publisher_elem.text if publisher_elem is not None else None

        # Infer venue_type from XML element tag
        venue_type = 'unknown'
        if element.tag == 'inproceedings':
            venue_type = 'conference'
        elif element.tag == 'article':
            venue_type = 'journal'
        elif element.tag in ['proceedings', 'book']:
            venue_type = 'book'
        elif element.tag in ['phdthesis', 'mastersthesis']:
            venue_type = 'thesis'
        elif element.tag == 'incollection':
            venue_type = 'book_chapter'

        # Get CCF classification from venue name
        ccf_class = None
        if venue:
            ccf_info = get_ccf_classification(venue)
            if ccf_info:
                ccf_class = ccf_info["ccf_class"]

        return {
            'paper_id': paper_id,
            'authors': authors,
            'title': title,
            'year': year,
            'venue': venue,  # Extracted from journal or booktitle based on element type
            'venue_type': venue_type,  # Inferred from XML element tag
            'ccf_class': ccf_class,  # CCF classification from venue name
            'doi': doi,  # Extracted from ee tag URLs
            'ee': ee,
            'volume': volume,
            'number': number,
            'pages': pages,
            'publisher': publisher
        }

    def _apply_backpressure(self):
        """Apply backpressure by sleeping when queue is nearly full."""
        current_size = self.paper_queue.qsize()
        fill_ratio = current_size / self.queue_maxsize

        if fill_ratio >= self.backpressure_threshold:
            # Queue is nearly full, sleep to allow consumer to catch up
            time.sleep(1)

    def parse(self) -> int:
        """Parse XML file and stream papers to queue.

        Returns:
            Number of papers parsed and queued
        """
        count = 0

        try:
            # Use iterparse for streaming with constant memory
            context = etree.iterparse(
                self.xml_path,
                events=('end',),
                recover=True  # Continue on parsing errors
            )

            for event, element in context:
                try:
                    # Only process paper type elements
                    if element.tag not in self.PAPER_TAGS:
                        continue

                    # Extract paper data
                    paper_data = self._extract_paper_data(element)

                    # Only queue papers with both paper_id and authors
                    if paper_data['paper_id'] and paper_data['authors']:
                        # Apply backpressure before putting to queue
                        self._apply_backpressure()

                        # Put to queue (blocking if full)
                        self.paper_queue.put(paper_data)
                        count += 1

                        # Save checkpoint periodically
                        if count % self.checkpoint_interval == 0:
                            chunk_id = count // self.checkpoint_interval
                            self.checkpoint_manager.mark_chunk_complete(chunk_id)

                    # Clear element to free memory (only after processing)
                    element.clear()

                    # Also clear previous siblings to free memory
                    while element.getprevious() is not None:
                        del element.getparent()[0]

                except Exception as e:
                    # Log error but continue parsing
                    print(f"Error processing element: {e}")
                    continue

        except Exception as e:
            print(f"Fatal parsing error: {e}")
            raise

        return count
