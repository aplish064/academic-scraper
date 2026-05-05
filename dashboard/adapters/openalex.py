"""
OpenAlex 数据源适配器
"""
from .base import DataSourceAdapter
from config import DATA_SOURCES


class OpenAlexAdapter(DataSourceAdapter):
    """OpenAlex 数据源适配器"""

    def __init__(self):
        config = DATA_SOURCES['openalex']
        super().__init__('openalex', config)

    def get_statistics_sql(self) -> str:
        """获取统计查询SQL"""
        return """
            SELECT
                (SELECT uniqHLL12(doi) FROM academic_db.OpenAlex WHERE doi != '') as total_papers,
                (SELECT uniq(cityHash64(author_id)) FROM academic_db.OpenAlex WHERE author_id != '') as unique_authors,
                (SELECT uniqHLL12(journal) FROM academic_db.OpenAlex WHERE journal != '') as unique_journals,
                (SELECT uniq(institution_name) FROM academic_db.OpenAlex WHERE institution_name != '') as unique_institutions,
                (SELECT sum(if(isFinite(fwci) and fwci > 0, fwci, 0)) FROM academic_db.OpenAlex) as fwci_sum,
                (SELECT countIf(fwci > 0) FROM academic_db.OpenAlex) as fwci_count
            SETTINGS max_threads=16, max_execution_time=60
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

    def get_institution_field(self) -> str:
        return self.get_field('institution') or 'institution_name'

    def get_country_field(self) -> str:
        return self.get_field('country') or 'institution_country'

    def get_citation_field(self) -> str:
        return self.get_field('citation_count') or 'citation_count'

    def get_fwci_field(self) -> str:
        return self.get_field('fwci') or 'fwci'

    def get_institution_type_field(self) -> str:
        return self.get_field('institution_type') or 'institution_type'

    def get_tag_field(self) -> str:
        return self.get_field('tag') or 'tag'
