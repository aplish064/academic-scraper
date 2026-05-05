"""
Patents data source adapter.
"""
from .base import DataSourceAdapter
from config import DATA_SOURCES


class PatentsAdapter(DataSourceAdapter):
    """Patents data source adapter."""

    def __init__(self):
        config = DATA_SOURCES['patents']
        super().__init__('patents', config)

    def get_statistics_sql(self) -> str:
        return """
            SELECT
                (SELECT count() FROM patent_db.patents) as total_papers,
                (
                    SELECT uniqHLL12(inventor_name)
                    FROM patent_db.patent_inventors
                    WHERE inventor_name != ''
                ) as unique_authors,
                (
                    SELECT uniqHLL12(assignee_name)
                    FROM patent_db.patent_assignees
                    WHERE assignee_name != ''
                ) as unique_journals,
                0 as unique_institutions,
                0 as fwci_sum,
                0 as fwci_count
            SETTINGS max_threads=4, max_execution_time=30
        """

    def get_date_field(self) -> str:
        return self.get_field('date') or 'grant_date'

    def get_journal_field(self) -> str:
        return self.get_field('journal') or 'assignees'

    def get_author_field(self) -> str:
        return self.get_field('author') or 'inventors'

    def get_venue_field(self) -> str:
        return self.get_field('venue') or 'assignees'

    def get_doi_field(self) -> str:
        return self.get_field('doi') or 'patent_id'

    def get_citation_field(self) -> str:
        return self.get_field('citation_count') or 'num_cited_by'

    def get_category_field(self) -> str:
        return self.get_field('cpc_codes') or 'cpc_codes'

    def format_date_query(self, field: str = None) -> str:
        date_field = field or self.get_date_field()
        return f"formatDateTime({date_field}, '%Y-%m')"
