# src/streaming/xml_parser.py
import time
from typing import Dict, Any
from lxml import etree


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

        # Extract venue (journal/conference name)
        venue_elem = element.find('venue')
        venue = venue_elem.text if venue_elem is not None else None

        # Extract DOI
        doi_elem = element.find('doi')
        doi = doi_elem.text if doi_elem is not None else None

        # Extract electronic edition (EE) URL
        ee_elem = element.find('ee')
        ee = ee_elem.text if ee_elem is not None else None

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

        return {
            'paper_id': paper_id,
            'authors': authors,
            'title': title,
            'year': year,
            'venue': venue,
            'doi': doi,
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
