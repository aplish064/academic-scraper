"""
Semantic Scholar 数据源适配器
"""
from .base import DataSourceAdapter
from config import DATA_SOURCES


class SemanticAdapter(DataSourceAdapter):
    """Semantic Scholar 数据源适配器"""

    def __init__(self):
        config = DATA_SOURCES['semantic']
        super().__init__('semantic', config)

    def get_statistics_sql(self) -> str:
        """获取统计查询SQL"""
        return """
            SELECT
                uniqHLL12(doi) as total_papers,
                uniqHLL12(author_id) as unique_authors,
                uniqHLL12(journal) as unique_journals,
                0 as unique_institutions,
                0 as fwci_sum,
                0 as fwci_count
            FROM academic_db.semantic
            SETTINGS max_threads=1, max_execution_time=30
        """

    def get_date_field(self) -> str:
        return self.get_field('date') or 'publication_date'

    def get_journal_field(self) -> str:
        return self.get_field('journal') or 'journal'

    def get_author_field(self) -> str:
        return self.get_field('author') or 'author_id'

    def get_venue_field(self) -> str:
        return self.get_field('venue') or 'journal'

    def get_doi_field(self) -> str:
        return self.get_field('doi') or 'doi'

    def get_citation_field(self) -> str:
        return self.get_field('citation_count') or 'citation_count'

    def get_tag_field(self) -> str:
        return self.get_field('tag') or 'tag'
