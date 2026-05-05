"""
数据聚合器
使用适配器模式重构数据聚合逻辑
"""
import time
import threading
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
        self._refresh_lock = threading.Lock()
        self._refreshing_sources = set()
        self._source_locks_lock = threading.Lock()
        self._source_locks = {}

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

        get_stale_source_data = getattr(self.cache_manager, 'get_stale_source_data', None)
        stale = get_stale_source_data(source) if get_stale_source_data else None
        if stale:
            self._refresh_source_cache_async(source)
            return stale

        get_source_data_from_all = getattr(self.cache_manager, 'get_source_data_from_all', None)
        all_snapshot = get_source_data_from_all(source) if get_source_data_from_all else None
        if all_snapshot:
            return all_snapshot

        source_lock = self._get_source_lock(source)
        with source_lock:
            cached = self.cache_manager.get_source_data(source)
            if cached:
                return cached

            stale = get_stale_source_data(source) if get_stale_source_data else None
            if stale:
                self._refresh_source_cache_async(source)
                return stale

            all_snapshot = get_source_data_from_all(source) if get_source_data_from_all else None
            if all_snapshot:
                return all_snapshot

            return self._query_single_source_data(source, adapter)

    def _get_source_lock(self, source: str) -> threading.Lock:
        """获取单数据源冷查询锁，避免并发重复重聚合"""
        with self._source_locks_lock:
            if source not in self._source_locks:
                self._source_locks[source] = threading.Lock()
            return self._source_locks[source]

    def _query_single_source_data(self, source: str, adapter) -> Dict:
        """同步查询单个数据源并写入缓存"""
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

    def _refresh_source_cache_async(self, source: str) -> None:
        """后台刷新stale数据源缓存，避免请求线程等待慢查询"""
        with self._refresh_lock:
            if source in self._refreshing_sources:
                return
            self._refreshing_sources.add(source)

        thread = threading.Thread(
            target=self._refresh_source_cache,
            args=(source,),
            daemon=True
        )
        thread.start()

    def _refresh_source_cache(self, source: str) -> None:
        try:
            adapter = get_adapter(source)
            if not adapter:
                return

            print(f"🔄 后台刷新缓存：{source}")
            self._query_single_source_data(source, adapter)
        finally:
            with self._refresh_lock:
                self._refreshing_sources.discard(source)

    def query_statistics(self, source: str) -> Dict:
        """查询统计数据"""
        adapter = get_adapter(source)
        if not adapter:
            return self.get_empty_statistics()

        if source == 'openalex':
            return self.query_openalex_statistics(adapter)

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

    def _query_scalar(self, sql: str, default=0):
        """执行单值查询，失败时返回默认值"""
        result = self.query_builder.execute_query(sql)
        if not result or not getattr(result, 'result_rows', None):
            return default

        value = result.result_rows[0][0]
        if value is None or value != value:
            return default
        return value

    def query_openalex_statistics(self, adapter) -> Dict:
        """查询OpenAlex统计数据。

        OpenAlex 表很大，单条多子查询SQL在API进程内容易触发30秒超时；
        拆成独立标量查询后，每个指标可以按ClickHouse自己的计划执行，
        避免统计总览整体失败导致source缓存无法写入。
        """
        table = f"academic_db.{adapter.get_table()}"
        settings = "SETTINGS max_threads=16, max_execution_time=30"
        heavy_settings = "SETTINGS max_threads=16, max_execution_time=60"

        total_papers = self._query_scalar(
            f"SELECT uniqHLL12(doi) FROM {table} WHERE doi != '' {settings}",
            0
        )
        unique_authors = self._query_scalar(
            f"SELECT uniq(cityHash64(author_id)) FROM {table} WHERE author_id != '' {heavy_settings}",
            0
        )
        unique_journals = self._query_scalar(
            f"SELECT uniqHLL12(journal) FROM {table} WHERE journal != '' {settings}",
            0
        )
        unique_institutions = self._query_scalar(
            f"SELECT uniq(institution_name) FROM {table} WHERE institution_name != '' {heavy_settings}",
            0
        )
        fwci_sum = self._query_scalar(
            f"SELECT sum(if(isFinite(fwci) and fwci > 0, fwci, 0)) FROM {table} {settings}",
            0
        )
        fwci_count = self._query_scalar(
            f"SELECT countIf(fwci > 0) FROM {table} {settings}",
            0
        )

        fwci_sum = float(fwci_sum) if fwci_sum else 0
        fwci_count = int(fwci_count) if fwci_count else 0
        avg_fwci = round(fwci_sum / fwci_count, 2) if fwci_count > 0 else 0

        return {
            'total_papers': int(total_papers) if total_papers else 0,
            'unique_authors': int(unique_authors) if unique_authors else 0,
            'unique_journals': int(unique_journals) if unique_journals else 0,
            'unique_institutions': int(unique_institutions) if unique_institutions else 0,
            'high_citations': 0,
            'avg_fwci': avg_fwci
        }

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

        if source == 'patents':
            return self.query_top_patent_assignees()

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
        elif source == 'patents':
            self.query_patent_metrics(result)

    def query_top_patent_assignees(self) -> Dict[str, int]:
        """查询Top专利权利人"""
        sql = """
            SELECT assignee_name, count(DISTINCT patent_id) AS count
            FROM patent_db.patent_assignees
            WHERE assignee_name != ''
            GROUP BY assignee_name
            ORDER BY count DESC
            LIMIT 50
            SETTINGS max_threads=4, max_execution_time=60
        """
        query_result = self.query_builder.execute_query(sql)
        assignees = {}
        if query_result and query_result.result_rows:
            for row in query_result.result_rows:
                assignees[row[0]] = int(row[1])
        return assignees

    def query_patent_metrics(self, result: Dict):
        """查询专利特有指标"""
        cpc_sql = """
            SELECT cpc_group, count() AS count
            FROM patent_db.patent_cpc
            WHERE cpc_group != ''
            GROUP BY cpc_group
            ORDER BY count DESC
            LIMIT 20
            SETTINGS max_threads=4, max_execution_time=60
        """
        query_result = self.query_builder.execute_query(cpc_sql)
        if query_result and query_result.result_rows:
            for row in query_result.result_rows:
                result['ccf_class_distribution'][row[0]] = int(row[1])

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
            return self._hydrate_all_statistics_from_sources(cached_all)

        get_stale_source_data = getattr(self.cache_manager, 'get_stale_source_data', None)
        stale_all = get_stale_source_data('all') if get_stale_source_data else None
        if stale_all:
            print("♻️  从stale缓存获取全部数据")
            return self._hydrate_all_statistics_from_sources(stale_all)

        print("💾 all缓存未命中，使用已有单源缓存快速合并...")

        get_available_merged_data = getattr(self.cache_manager, 'get_available_merged_data', None)
        merged_from_cache = get_available_merged_data() if get_available_merged_data else self.cache_manager.get_merged_data()
        if merged_from_cache:
            print("🎯 从已有单源缓存合并全部数据，跳过请求线程内的大表重聚合")
            merged_from_cache['source'] = 'all'
            merged_from_cache['table'] = 'all'
        else:
            print("⚠️  单源缓存为空，返回空的all数据，避免代理超时")
            merged_from_cache = self.get_empty_source_data('all')

        # 保存到缓存；后续请求直接命中，不在请求线程里跑重查询。
        self.cache_manager.set_source_data('all', merged_from_cache, ttl=900)

        print("="*60)
        print("✅ 全部数据查询完成")
        print("="*60 + "\n")

        return merged_from_cache

    def _hydrate_all_statistics_from_sources(self, all_data: Dict) -> Dict:
        """用已缓存的单源指标补齐all缓存中的OpenAlex专属统计。"""
        if not all_data or all_data.get('source') != 'all':
            return all_data

        result = all_data.copy()
        stats = result.get('statistics', {}).copy()
        result['statistics'] = stats

        openalex_data = self.cache_manager.get_source_data('openalex')
        if not openalex_data:
            get_stale_source_data = getattr(self.cache_manager, 'get_stale_source_data', None)
            openalex_data = get_stale_source_data('openalex') if get_stale_source_data else None

        openalex_stats = (openalex_data or {}).get('statistics', {})
        if openalex_stats:
            if not stats.get('unique_institutions'):
                stats['unique_institutions'] = openalex_stats.get('unique_institutions', 0)
            if not stats.get('avg_fwci'):
                stats['avg_fwci'] = openalex_stats.get('avg_fwci', 0)

            source_data = result.get('_source_data')
            if isinstance(source_data, dict):
                result['_source_data'] = source_data.copy()
                result['_source_data']['openalex'] = openalex_data

        return result

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
