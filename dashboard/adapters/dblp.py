"""
DBLP 数据源适配器
"""
from .base import DataSourceAdapter
from config import DATA_SOURCES


class DBLPAdapter(DataSourceAdapter):
    """DBLP 数据源适配器"""

    def __init__(self):
        config = DATA_SOURCES['dblp']
        super().__init__('dblp', config)

    def get_statistics_sql(self) -> str:
        """获取统计查询SQL"""
        return """
            SELECT
                uniqHLL12(doi) as total_papers,
                uniqHLL12(author_name) as unique_authors,
                uniqHLL12(venue) as unique_journals,
                0 as unique_institutions,
                0 as high_citations,
                0 as avg_fwci
            FROM academic_db.dblp
            SETTINGS max_threads=1, max_execution_time=30
        """

    def get_date_field(self) -> str:
        return self.get_field('date') or 'year'

    def get_journal_field(self) -> str:
        return self.get_field('journal') or 'venue'

    def get_author_field(self) -> str:
        return self.get_field('author') or 'author_name'

    def get_venue_field(self) -> str:
        return self.get_field('venue') or 'venue'

    def get_doi_field(self) -> str:
        return self.get_field('doi') or 'doi'

    def get_ccf_class_field(self) -> str:
        return self.get_field('ccf_class') or 'ccf_class'

    def get_pub_type_field(self) -> str:
        return self.get_field('pub_type') or 'type'

    def get_venue_type_field(self) -> str:
        return self.get_field('venue_type') or 'venue_type'

    def format_date_query(self, field: str = None) -> str:
        """DBLP 使用年份，需要特殊格式化"""
        date_field = field or self.get_date_field()
        return f"concat({date_field}, '-01')"
