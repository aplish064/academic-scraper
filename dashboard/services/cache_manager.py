"""
缓存管理器
统一处理缓存读写、验证和合并逻辑
"""
import json
import redis
from typing import Dict, List, Optional, Any
from config import REDIS_CONFIG, get_enabled_sources


class CacheManager:
    """缓存管理器 - 统一处理所有缓存操作"""

    def __init__(self, redis_client=None):
        """
        初始化缓存管理器

        Args:
            redis_client: Redis客户端实例，如果为None则创建新客户端
        """
        self.redis_client = redis_client
        self.cache_enabled = redis_client is not None
        self.default_ttl = 300  # 默认5分钟缓存

    def get_cache_key(self, source: str) -> str:
        """生成缓存键"""
        return f"aggregated:{source}"

    def get_from_cache(self, cache_key: str) -> Optional[Dict]:
        """
        从缓存获取数据

        Args:
            cache_key: 缓存键

        Returns:
            缓存的数据，如果不存在或无效返回None
        """
        if not self.cache_enabled or not self.redis_client:
            return None

        try:
            cached_data = self.redis_client.get(cache_key)
            if cached_data:
                print(f"🎯 命中缓存！数据源: {cache_key.split(':')[1]}")
                return json.loads(cached_data)
            return None
        except Exception as e:
            print(f"⚠️  缓存读取失败: {e}")
            return None

    def set_to_cache(
        self,
        cache_key: str,
        data: Dict,
        ttl: int = None
    ) -> bool:
        """
        保存数据到缓存

        Args:
            cache_key: 缓存键
            data: 要缓存的数据
            ttl: 缓存时间（秒），如果为None使用默认值

        Returns:
            是否成功
        """
        if not self.cache_enabled or not self.redis_client:
            return False

        try:
            ttl = ttl or self.default_ttl
            self.redis_client.setex(cache_key, ttl, json.dumps(data))
            print(f"💾 数据已缓存 ({ttl}秒)")
            return True
        except Exception as e:
            print(f"⚠️ 缓存写入失败: {e}")
            return False

    def validate_data_integrity(
        self,
        data: Dict,
        source: str
    ) -> bool:
        """
        验证缓存数据完整性

        Args:
            data: 缓存数据
            source: 数据源名称

        Returns:
            数据是否完整有效
        """
        if not data or not isinstance(data, dict):
            return False

        stats = data.get('statistics', {})

        # 检查基本统计数据
        if stats.get('total_papers', 0) == 0:
            return False

        # 对于有期刊数据的数据源，检查期刊数
        if source not in ['arxiv']:  # arXiv 可能没有期刊数据
            if stats.get('unique_journals', 0) == 0:
                return False

        return True

    def get_source_data(self, source: str) -> Optional[Dict]:
        """
        获取单个数据源的缓存数据

        Args:
            source: 数据源名称

        Returns:
            缓存的数据，如果不存在或无效返回None
        """
        cache_key = self.get_cache_key(source)
        cached_data = self.get_from_cache(cache_key)

        if cached_data and self.validate_data_integrity(cached_data, source):
            return cached_data

        return None

    def set_source_data(
        self,
        source: str,
        data: Dict,
        ttl: int = None
    ) -> bool:
        """
        缓存单个数据源的数据

        Args:
            source: 数据源名称
            data: 要缓存的数据
            ttl: 缓存时间

        Returns:
            是否成功
        """
        cache_key = self.get_cache_key(source)
        return self.set_to_cache(cache_key, data, ttl)

    def get_merged_data(
        self,
        sources: List[str] = None
    ) -> Optional[Dict]:
        """
        合并多个数据源的缓存数据（支持部分缓存命中）

        Args:
            sources: 数据源列表，如果为None则使用所有启用的数据源

        Returns:
            合并后的数据，如果缓存不完整（超过50%缺失）返回None
        """
        if not sources:
            sources = get_enabled_sources()

        cached_sources = {}
        missing_sources = []

        # 获取所有数据源的缓存
        for source in sources:
            data = self.get_source_data(source)
            if data:
                cached_sources[source] = data
            else:
                missing_sources.append(source)

        # 如果超过50%的数据源缓存缺失，返回None触发全量查询
        if len(missing_sources) > len(sources) / 2:
            print(f"⚠️  缓存不完整：缺失 {len(missing_sources)}/{len(sources)} 个数据源")
            return None

        if missing_sources:
            print(f"📊 部分缓存命中：{len(cached_sources)}/{len(sources)} 个数据源")

        # 合并可用的缓存数据
        return self.merge_sources_data(list(cached_sources.values()))

    def merge_sources_data(
        self,
        sources_data: List[Dict]
    ) -> Dict:
        """
        合并多个数据源的数据 - 标准化的合并逻辑

        Args:
            sources_data: 数据源数据列表

        Returns:
            合并后的数据
        """
        merged = {
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
            'source': 'all',
            'table': 'all',
            '_source_data': {}
        }

        # 收集所有期刊用于合并
        all_journals = {}

        # 合并各数据源的数据
        for source_data in sources_data:
            source_name = source_data.get('source', 'unknown')
            merged['_source_data'][source_name] = source_data

            # 合并论文按日期统计
            for date, count in source_data.get('papers_by_date', {}).items():
                merged['papers_by_date'][date] = merged['papers_by_date'].get(date, 0) + count

            # 合并引用分布
            for range_key, count in source_data.get('citations_distribution', {}).items():
                merged['citations_distribution'][range_key] = merged['citations_distribution'].get(range_key, 0) + count

            # 合并作者类型
            for tag, count in source_data.get('author_types', {}).items():
                merged['author_types'][tag] = merged['author_types'].get(tag, 0) + count

            # 收集期刊数据（稍后排序）
            for journal, count in source_data.get('top_journals', {}).items():
                all_journals[journal] = all_journals.get(journal, 0) + count

            # 合并国家分布（只有OpenAlex有）
            for country, count in source_data.get('top_countries', {}).items():
                merged['top_countries'][country] = merged['top_countries'].get(country, 0) + count

            # 合并机构类型（只有OpenAlex有）
            for inst_type, count in source_data.get('institution_types', {}).items():
                merged['institution_types'][inst_type] = merged['institution_types'].get(inst_type, 0) + count

            # 合并FWCI分布（只有OpenAlex有）
            for fwci_range, count in source_data.get('fwci_distribution', {}).items():
                merged['fwci_distribution'][fwci_range] = merged['fwci_distribution'].get(fwci_range, 0) + count

            # 合并DBLP特有字段
            for ccf_class, count in source_data.get('ccf_class_distribution', {}).items():
                merged['ccf_class_distribution'][ccf_class] = merged['ccf_class_distribution'].get(ccf_class, 0) + count

            for pub_type, count in source_data.get('publication_type_distribution', {}).items():
                merged['publication_type_distribution'][pub_type] = merged['publication_type_distribution'].get(pub_type, 0) + count

            for venue_type, count in source_data.get('venue_type_distribution', {}).items():
                merged['venue_type_distribution'][venue_type] = merged['venue_type_distribution'].get(venue_type, 0) + count

        # 按数量排序期刊，取前50
        sorted_journals = sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50]
        merged['top_journals'] = dict(sorted_journals)

        return merged

    def delete_cache(self, source: str) -> bool:
        """
        删除指定数据源的缓存

        Args:
            source: 数据源名称

        Returns:
            是否成功
        """
        if not self.cache_enabled or not self.redis_client:
            return False

        cache_key = self.get_cache_key(source)
        try:
            self.redis_client.delete(cache_key)
            print(f"  ✅ {source} 缓存已删除")
            return True
        except Exception as e:
            print(f"  ❌ {source} 缓存删除失败: {e}")
            return False

    def clear_all_caches(self, sources: List[str] = None) -> int:
        """
        清除所有缓存

        Args:
            sources: 要清除的数据源列表，如果为None则清除所有

        Returns:
            成功清除的数量
        """
        if not sources:
            sources = get_enabled_sources()

        success_count = 0
        for source in sources:
            if self.delete_cache(source):
                success_count += 1

        return success_count
