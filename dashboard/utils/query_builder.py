"""
通用查询构建器
消除跨数据源查询的代码重复
"""
from typing import List, Dict, Any, Optional
from adapters import get_adapter


class QueryBuilder:
    """通用SQL查询构建器"""

    def __init__(self, ch_client_getter):
        """
        初始化查询构建器

        Args:
            ch_client_getter: ClickHouse客户端获取函数
        """
        self.get_ch_client = ch_client_getter

    def query_unique_count_across_sources(
        self,
        field: str,
        sources: List[str],
        where_clause: str = ""
    ) -> int:
        """
        跨数据源的唯一计数通用查询

        Args:
            field: 要统计的字段名（逻辑字段名）
            sources: 数据源列表
            where_clause: 额外的WHERE条件

        Returns:
            唯一计数
        """
        try:
            client = self.get_ch_client()
            if not client:
                return 0

            # 为每个数据源构建别名字段，确保UNION ALL正常工作
            select_parts = []
            field_mapping = []

            for i, source in enumerate(sources):
                adapter = get_adapter(source)
                if not adapter:
                    continue

                table = adapter.get_table()
                source_field = adapter.get_field(field)

                # 如果该数据源没有这个字段，跳过
                if not source_field:
                    continue

                # 使用别名字段名，避免不同数据源字段名冲突
                alias = f"{source}_{field}"
                select_parts.append(f"SELECT {source_field} as {alias} FROM {table}")
                field_mapping.append(alias)

            if not select_parts:
                return 0

            # 构建UNION ALL查询并使用别名字段
            select_queries = []
            for i, part in enumerate(select_parts):
                select_queries.append(f"SELECT {field_mapping[i]} as combined_field FROM ({part})")

            unified_sql = f"""
                SELECT uniqExact(combined_field) as count
                FROM ({' UNION ALL '.join(select_queries)})
                WHERE combined_field != '' {where_clause}
                SETTINGS max_execution_time=120
            """

            result = client.query(unified_sql)
            if result and result.result_rows:
                return result.result_rows[0][0]
            return 0
        except Exception as e:
            print(f"⚠️  查询唯一{field}数失败: {e}")
            return 0

    def query_papers_by_date_union(
        self,
        sources: List[str],
        date_field: str = 'date',
        count_field: str = 'doi'
    ) -> Dict[str, int]:
        """
        跨数据源按日期统计论文数

        Args:
            sources: 数据源列表
            date_field: 日期字段名
            count_field: 计数字段（通常是doi）

        Returns:
            日期到论文数的映射
        """
        try:
            client = self.get_ch_client()
            if not client:
                return {}

            # 为每个数据源构建查询并分别执行
            all_papers_by_date = {}

            for source in sources:
                adapter = get_adapter(source)
                if not adapter:
                    continue

                table = adapter.get_table()
                source_date_field = adapter.get_date_field()
                source_count_field = adapter.get_doi_field()

                # 如果没有DOI字段，跳过该数据源
                if not source_count_field:
                    continue

                # 格式化日期查询
                formatted_date = adapter.format_date_query(source_date_field)

                # 构建该数据源的查询
                date_sql = f"""
                    SELECT
                        {formatted_date} as date,
                        uniqHLL12({source_count_field}) as count
                    FROM academic_db.{table}
                    WHERE {source_date_field} != '' AND length({source_date_field}) > 0
                    GROUP BY {formatted_date}
                    ORDER BY {formatted_date} DESC
                    SETTINGS max_execution_time=60
                """

                result = client.query(date_sql)
                if result and result.result_rows:
                    for row in result.result_rows:
                        date_str = str(row[0])
                        count = int(row[1])
                        # 合并数据：相同日期的计数相加
                        if date_str in all_papers_by_date:
                            all_papers_by_date[date_str] += count
                        else:
                            all_papers_by_date[date_str] = count

            return all_papers_by_date
        except Exception as e:
            print(f"⚠️  查询跨源按日期统计失败: {e}")
            return {}

    def build_date_query(
        self,
        adapter,
        group_by_date: bool = True
    ) -> str:
        """
        构建日期查询SQL

        Args:
            adapter: 数据源适配器
            group_by_date: 是否按日期分组

        Returns:
            SQL查询字符串
        """
        date_field = adapter.get_date_field()
        doi_field = adapter.get_doi_field()

        if not doi_field:
            return None

        formatted_date = adapter.format_date_query(date_field)

        if group_by_date:
            return f"""
                SELECT
                    {formatted_date} as date,
                    uniqHLL12({doi_field}) as count
                FROM academic_db.{adapter.get_table()}
                WHERE {date_field} != '' AND length({date_field}) > 0
                GROUP BY {formatted_date}
                ORDER BY date DESC
                SETTINGS max_threads=1
            """
        else:
            return f"""
                SELECT
                    {formatted_date} as date,
                    {doi_field}
                FROM academic_db.{adapter.get_table()}
                WHERE {date_field} != '' AND length({date_field}) > 0
            """

    def build_journal_query(
        self,
        adapter,
        limit: int = 50
    ) -> str:
        """
        构建期刊查询SQL

        Args:
            adapter: 数据源适配器
            limit: 返回记录数限制

        Returns:
            SQL查询字符串
        """
        journal_field = adapter.get_journal_field()
        doi_field = adapter.get_doi_field()

        if not doi_field:
            return None

        return f"""
            SELECT
                {journal_field},
                uniqHLL12({doi_field}) as count
            FROM academic_db.{adapter.get_table()}
            WHERE {journal_field} != ''
                AND length({journal_field}) > 3
                AND lower({journal_field}) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
            GROUP BY {journal_field}
            ORDER BY count DESC
            LIMIT {limit}
            SETTINGS max_threads=8, max_execution_time=60
        """

    def build_citation_distribution_query(self, adapter) -> Optional[str]:
        """
        构建引用分布查询SQL

        Args:
            adapter: 数据源适配器

        Returns:
            SQL查询字符串，如果不支持引用则返回None
        """
        if not adapter.supports_metric('citations'):
            return None

        citation_field = adapter.get_citation_field()
        doi_field = adapter.get_doi_field()

        if not citation_field or not doi_field:
            return None

        return f"""
            SELECT
                multiIf(
                    {citation_field} = 0, '0',
                    {citation_field} < 6, '1-5',
                    {citation_field} < 11, '6-10',
                    {citation_field} < 21, '11-20',
                    {citation_field} < 51, '21-50',
                    {citation_field} < 101, '51-100',
                    {citation_field} < 501, '101-500',
                    '500+'
                ) as range,
                uniqHLL12({doi_field}) as count
            FROM academic_db.{adapter.get_table()}
            GROUP BY range
            ORDER BY range
            SETTINGS max_threads=4, max_execution_time=60
        """

    def execute_query(self, sql: str) -> Optional[Any]:
        """
        执行SQL查询

        Args:
            sql: SQL查询字符串

        Returns:
            查询结果，失败返回None
        """
        client = self.get_ch_client()
        if not client:
            return None

        try:
            return client.query(sql)
        except Exception as e:
            print(f"❌ 查询失败: {e}")
            return None
