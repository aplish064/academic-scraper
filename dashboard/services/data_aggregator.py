"""
数据聚合器
使用适配器模式重构数据聚合逻辑
"""
import time
from typing import Dict, List, Optional, Any
from concurrent.futures import ThreadPoolExecutor, as_completed
from adapters import get_adapter
from services.cache_manager import CacheManager
from utils.query_builder import QueryBuilder


class DataSourceAggregator:
    """数据源聚合器 - 统一处理所有数据源的查询和聚合"""

    def __init__(
        self,
        ch_client_getter,
        cache_manager: CacheManager = None
    ):
        """
        初始化聚合器

        Args:
            ch_client_getter: ClickHouse客户端获取函数
            cache_manager: 缓存管理器实例
        """
        self.get_ch_client = ch_client_getter
        self.cache_manager = cache_manager or CacheManager()
        self.query_builder = QueryBuilder(ch_client_getter)

    def get_single_source_data(self, source: str) -> Dict:
        """
        获取单个数据源的完整聚合数据

        Args:
            source: 数据源名称

        Returns:
            聚合数据字典
        """
        adapter = get_adapter(source)
        if not adapter:
            return self.get_empty_source_data(source)

        print(f"📊 查询聚合数据... 数据源: {source}, 表: {adapter.get_table()}")
        print(f"{'='*60}")

        # 检查缓存
        cached = self.cache_manager.get_source_data(source)
        if cached:
            return cached

        # 查询数据库
        result = {
            'papers_by_date': {},
            'citations_distribution': {},
            'author_types': {},
            'top_journals': {},
            'top_countries': {},
            'institution_types': {},
            'fwci_distribution': {},
            'ccf_class_distribution': {},
            'publication_type_distribution': {},
            'venue_type_distribution': {},
            'statistics': {},
            'source': source,
            'table': adapter.get_table()
        }

        try:
            # 1. 统计总览
            step_start = time.time()
            print(f"[步骤 1/7] 统计总览查询...")
            result['statistics'] = self.query_statistics(source)
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")

            # 2. 按日期统计
            step_start = time.time()
            print(f"[步骤 2/7] 按日期统计...")
            result['papers_by_date'] = self.query_papers_by_date(source)
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 记录数: {len(result['papers_by_date'])})")

            # 3. 引用数分布（如果支持）
            step_start = time.time()
            print(f"[步骤 3/7] 引用数分布查询...")
            if adapter.supports_metric('citations'):
                result['citations_distribution'] = self.query_citations_distribution(source)
                print(f"  ✓ 完成 (耗时: {time.time() - step_start:.2f}秒)")
            else:
                print(f"  ⊘ 跳过 (数据源不支持)")

            # 4. 作者类型分布（如果支持）
            step_start = time.time()
            print(f"[步骤 4/7] 作者类型分布查询...")
            if adapter.get_field('tag'):
                result['author_types'] = self.query_author_types(source)
                print(f"  ✓ 完成 (耗时: {time.time() - step_start:.2f}秒)")
            else:
                print(f"  ⊘ 跳过 (数据源不支持)")

            # 5. Top期刊
            step_start = time.time()
            print(f"[步骤 5/7] Top期刊查询...")
            result['top_journals'] = self.query_top_journals(source)
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 期刊数: {len(result['top_journals'])})")

            # 6. 数据源特有指标
            self.query_source_specific_metrics(source, adapter, result)

            total_time = time.time() - step_start if 'step_start' in locals() else 0
            print(f"\n{'='*60}")
            print(f"✅ 查询完成！总耗时: {total_time:.2f}秒")
            print(f"{'='*60}\n")

            # 缓存数据
            self.cache_manager.set_source_data(source, result)

            return result

        except Exception as e:
            print(f"❌ 查询失败: {e}")
            return self.get_empty_source_data(source, error=str(e))

    def query_statistics(self, source: str) -> Dict:
        """查询统计数据"""
        adapter = get_adapter(source)
        if not adapter:
            return self.get_empty_statistics()

        sql = adapter.get_statistics_sql()
        result = self.query_builder.execute_query(sql)

        if result and adapter.validate_result(result):
            row = result.result_rows[0]
            # OpenAlex: row[4]=fwci_sum, row[5]=fwci_count
            fwci_sum = float(row[4]) if row[4] and row[4] == row[4] else 0
            fwci_count = int(row[5]) if row[5] and row[5] == row[5] else 0
            avg_fwci = round(fwci_sum / fwci_count, 2) if fwci_count > 0 else 0

            return {
                'total_papers': int(row[0]) if row[0] and row[0] == row[0] else 0,
                'unique_authors': int(row[1]) if row[1] and row[1] == row[1] else 0,
                'unique_journals': int(row[2]) if row[2] and row[2] == row[2] else 0,
                'unique_institutions': int(row[3]) if row[3] and row[3] == row[3] else 0,
                'high_citations': 0,
                'avg_fwci': avg_fwci
            }

        return self.get_empty_statistics()

    def query_papers_by_date(self, source: str) -> Dict[str, int]:
        """查询按日期统计的论文数"""
        adapter = get_adapter(source)
        if not adapter:
            return {}

        sql = self.query_builder.build_date_query(adapter)
        if not sql:
            return {}

        result = self.query_builder.execute_query(sql)
        papers_by_date = {}

        if result and adapter.validate_result(result):
            for row in result.result_rows:
                papers_by_date[str(row[0])] = int(row[1])

        return papers_by_date

    def query_citations_distribution(self, source: str) -> Dict[str, int]:
        """查询引用数分布"""
        adapter = get_adapter(source)
        if not adapter or not adapter.supports_metric('citations'):
            return {}

        sql = self.query_builder.build_citation_distribution_query(adapter)
        if not sql:
            return {}

        result = self.query_builder.execute_query(sql)
        citation_dist = {}

        if result and adapter.validate_result(result):
            for row in result.result_rows:
                citation_dist[row[0]] = int(row[1])

        return citation_dist

    def query_author_types(self, source: str) -> Dict[str, int]:
        """查询作者类型分布"""
        adapter = get_adapter(source)
        if not adapter:
            return {}

        tag_field = adapter.get_field('tag')
        if not tag_field:
            return {}

        sql = f"""
            SELECT
                {tag_field},
                count() as count
            FROM {adapter.get_table()}
            WHERE {tag_field} != ''
            GROUP BY {tag_field}
            ORDER BY count DESC
            LIMIT 10
        """

        result = self.query_builder.execute_query(sql)
        author_types = {}

        if result and adapter.validate_result(result):
            for row in result.result_rows:
                author_types[row[0]] = int(row[1])

        return author_types

    def query_top_journals(self, source: str) -> Dict[str, int]:
        """查询Top期刊"""
        adapter = get_adapter(source)
        if not adapter:
            return {}

        sql = self.query_builder.build_journal_query(adapter)
        if not sql:
            return {}

        result = self.query_builder.execute_query(sql)
        journals = {}

        if result and adapter.validate_result(result):
            for row in result.result_rows:
                journals[row[0]] = int(row[1])

        return journals

    def query_source_specific_metrics(
        self,
        source: str,
        adapter,
        result: Dict
    ):
        """查询数据源特有的指标"""
        # OpenAlex 特有指标
        if source == 'openalex':
            self.query_openalex_metrics(adapter, result)
        # DBLP 特有指标
        elif source == 'dblp':
            self.query_dblp_metrics(adapter, result)

    def query_openalex_metrics(self, adapter, result: Dict):
        """查询OpenAlex特有指标"""
        # Top国家
        country_field = adapter.get_country_field()
        if country_field:
            sql = f"""
                SELECT
                    {country_field},
                    uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {country_field} != ''
                    AND {country_field} != 'nan'
                    AND lower({country_field}) != 'nan'
                GROUP BY {country_field}
                ORDER BY count DESC
                LIMIT 15
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['top_countries'][row[0]] = int(row[1])

        # 机构类型
        inst_type_field = adapter.get_institution_type_field()
        if inst_type_field:
            sql = f"""
                SELECT
                    {inst_type_field},
                    uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {inst_type_field} != ''
                    AND {inst_type_field} != 'nan'
                    AND lower({inst_type_field}) != 'nan'
                GROUP BY {inst_type_field}
                ORDER BY count DESC
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['institution_types'][row[0]] = int(row[1])

        # FWCI分布
        fwci_field = adapter.get_fwci_field()
        if fwci_field:
            sql = f"""
                SELECT
                    multiIf(
                        {fwci_field} < 0.5, '<0.5',
                        {fwci_field} < 1, '0.5-1',
                        {fwci_field} < 2, '1-2',
                        {fwci_field} < 3, '2-3',
                        {fwci_field} < 5, '3-5',
                        {fwci_field} < 10, '5-10',
                        '10+'
                    ) as range,
                    uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {fwci_field} > 0
                GROUP BY range
                ORDER BY range
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['fwci_distribution'][row[0]] = int(row[1])

    def query_dblp_metrics(self, adapter, result: Dict):
        """查询DBLP特有指标"""
        # CCF等级
        ccf_field = adapter.get_ccf_class_field()
        if ccf_field:
            sql = f"""
                SELECT {ccf_field}, uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {ccf_field} != ''
                GROUP BY {ccf_field}
                ORDER BY count DESC
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['ccf_class_distribution'][row[0]] = int(row[1])

        # 发表类型
        pub_type_field = adapter.get_pub_type_field()
        if pub_type_field:
            sql = f"""
                SELECT {pub_type_field}, uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {pub_type_field} != ''
                GROUP BY {pub_type_field}
                ORDER BY count DESC
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['publication_type_distribution'][row[0]] = int(row[1])

        # 场地类型
        venue_type_field = adapter.get_venue_type_field()
        if venue_type_field:
            sql = f"""
                SELECT {venue_type_field}, uniqHLL12(doi) as count
                FROM {adapter.get_table()}
                WHERE {venue_type_field} != '' AND {venue_type_field} != 'unknown'
                GROUP BY {venue_type_field}
                ORDER BY count DESC
            """
            query_result = self.query_builder.execute_query(sql)
            if query_result and adapter.validate_result(query_result):
                for row in query_result.result_rows:
                    result['venue_type_distribution'][row[0]] = int(row[1])

    def aggregate_all_sources(self) -> Dict:
        """
        聚合所有数据源的数据

        Returns:
            合并后的数据
        """
        print("📊 查询所有数据源聚合数据...")
        print("="*60)

        # 先尝试从缓存获取完整的"全部数据"（包含跨源统计）
        cached_all = self.cache_manager.get_source_data('all')
        if cached_all:
            print("🚀 从缓存获取全部数据（包含跨源去重统计，无需重新查询）")
            return cached_all

        # 缓存不存在，重新构建
        print("💾 缓存未命中，重新构建全部数据...")

        # 先尝试从单个源缓存合并（快速路径）
        merged_from_cache = self.cache_manager.get_merged_data()
        if merged_from_cache:
            print("🎯 从单个源缓存合并数据...")
            # 更新跨源去重统计（使用返回值）
            merged_from_cache = self.update_cross_source_statistics(merged_from_cache)
        else:
            print("🔄 单个源缓存不完整，重新查询所有数据源...")
            # 缓存不完整，重新查询所有数据源（使用并行查询）
            sources_data = self._query_all_sources_parallel()

            # 合并数据
            merged_from_cache = self.cache_manager.merge_sources_data(list(sources_data.values()))

            # 更新跨源去重统计（使用返回值）
            merged_from_cache = self.update_cross_source_statistics(merged_from_cache)

        # 保存到缓存（使用更长的TTL：15分钟）
        self.cache_manager.set_source_data('all', merged_from_cache, ttl=900)

        print("="*60)
        print("✅ 全部数据查询完成")
        print("="*60 + "\n")

        return merged_from_cache

    def update_cross_source_statistics(self, merged_data: Dict) -> Dict:
        """
        更新跨数据源的去重统计（纯函数，不修改输入）

        Args:
            merged_data: 合并后的数据

        Returns:
            更新后的统计数据
        """
        # 使用查询构建器进行跨源去重
        total_papers = self.query_builder.query_unique_count_across_sources(
            'doi', ['openalex', 'semantic', 'dblp']
        )

        total_authors = self.query_builder.query_unique_count_across_sources(
            'author_name', ['openalex', 'semantic', 'dblp', 'arxiv']
        )

        total_venues = self.query_builder.query_unique_count_across_sources(
            'venue', ['openalex', 'semantic', 'dblp', 'arxiv']
        )

        # 构建更新的统计数据
        stats = merged_data.get('statistics', {}).copy()
        stats['total_papers'] = total_papers if total_papers > 0 else stats.get('total_papers', 0)
        stats['unique_authors'] = total_authors if total_authors > 0 else stats.get('unique_authors', 0)
        stats['unique_journals'] = total_venues if total_venues > 0 else stats.get('unique_journals', 0)

        # 更新论文按日期统计
        papers_by_date = self.query_builder.query_papers_by_date_union(
            ['openalex', 'semantic', 'dblp']
        )

        # 返回更新的数据副本
        result = merged_data.copy()
        result['statistics'] = stats
        if papers_by_date:
            result['papers_by_date'] = papers_by_date

        return result

    def get_empty_source_data(self, source: str, error: str = None) -> Dict:
        """获取空数据源数据"""
        data = {
            'papers_by_date': {},
            'citations_distribution': {},
            'author_types': {},
            'top_journals': {},
            'top_countries': {},
            'institution_types': {},
            'fwci_distribution': {},
            'ccf_class_distribution': {},
            'publication_type_distribution': {},
            'venue_type_distribution': {},
            'statistics': self.get_empty_statistics(),
            'source': source,
            'table': source
        }

        if error:
            data['error'] = error

        return data

    def get_empty_statistics(self) -> Dict:
        """获取空统计数据"""
        return {
            'total_papers': 0,
            'unique_authors': 0,
            'unique_journals': 0,
            'unique_institutions': 0,
            'high_citations': 0,
            'avg_fwci': 0
        }

    def _query_all_sources_parallel(self) -> Dict[str, Dict]:
        """
        并行查询所有数据源

        Returns:
            数据源名称到数据的映射
        """
        sources_data = {}
        sources_to_query = ['openalex', 'semantic', 'dblp']

        with ThreadPoolExecutor(max_workers=3) as executor:
            # 提交所有查询任务
            future_to_source = {
                executor.submit(self.get_single_source_data, source): source
                for source in sources_to_query
            }

            # 收集结果
            for future in as_completed(future_to_source):
                source = future_to_source[future]
                try:
                    source_data = future.result()
                    sources_data[source] = source_data
                except Exception as e:
                    print(f"❌ {source} 查询失败: {e}")
                    sources_data[source] = self.get_empty_source_data(source, error=str(e))

        return sources_data
