"""
arXiv 数据源适配器
"""
from typing import Dict
from .base import DataSourceAdapter
from config import DATA_SOURCES


class ArXivAdapter(DataSourceAdapter):
    """arXiv 数据源适配器"""

    def __init__(self):
        config = DATA_SOURCES['arxiv']
        super().__init__('arxiv', config)

    def get_statistics_sql(self) -> str:
        """获取统计查询SQL - arXiv 使用特殊的统计查询"""
        return """
            SELECT
                count() as total_papers,
                uniqExact(author) as unique_authors,
                0 as unique_journals,
                0 as unique_institutions,
                0 as fwci_sum,
                0 as fwci_count
            FROM academic_db.arxiv
            SETTINGS max_execution_time=30
        """

    def get_date_field(self) -> str:
        return self.get_field('date') or 'published'

    def get_journal_field(self) -> str:
        return self.get_field('journal') or 'journal_ref'

    def get_author_field(self) -> str:
        return self.get_field('author') or 'author'

    def get_venue_field(self) -> str:
        return self.get_field('venue') or 'journal_ref'

    def get_doi_field(self) -> str:
        # arXiv 可能没有 DOI 字段
        return self.get_field('doi')

    def get_category_field(self) -> str:
        return self.get_field('primary_category') or 'primary_category'

    def format_date_query(self, field: str = None) -> str:
        """arXiv 使用 Date 类型的 published 字段"""
        date_field = field or self.get_date_field()
        return f"formatDateTime({date_field}, '%Y-%m')"

    def get_custom_statistics_queries(self) -> Dict[str, str]:
        """
        获取 arXiv 特有的统计查询

        Returns:
            字典键为统计类型，值为SQL查询
        """
        return {
            'unique_categories': """
                SELECT uniqExact(primary_category)
                FROM academic_db.arxiv
                WHERE primary_category != ''
            """,
            'timespan': """
                SELECT
                    min(published) as earliest,
                    max(published) as latest
                FROM academic_db.arxiv
            """
        }
