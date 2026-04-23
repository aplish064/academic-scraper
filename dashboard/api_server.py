#!/usr/bin/env python3
"""
学术数据看板API服务器 - 支持Redis缓存和去重统计
- 使用适配器模式支持动态添加数据源
- 启动时预加载所有数据源缓存
- 后台线程每2分钟自动刷新缓存
"""

import time
import json
import threading
import pandas as pd
from config import (
    CLICKHOUSE_CONFIG, TABLES, DEFAULT_TABLE, FLASK_CONFIG,
    REDIS_CONFIG, get_enabled_sources
)
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import clickhouse_connect
import redis

# 导入新的架构组件
from adapters import get_adapter
from services import CacheManager, DataSourceAggregator
from utils import QueryBuilder

app = Flask(__name__, static_folder='.')
CORS(app)

# 全局客户端和服务
ch_client = None
redis_client = None
USE_CACHE = True

# 新架构组件
cache_manager = None
data_aggregator = None
query_builder = None

# 缓存刷新间隔（秒）
CACHE_REFRESH_INTERVAL = 120  # 2分钟

# 后台刷新线程
cache_refresh_thread = None
cache_refresh_running = False

def get_table_name():
    """根据请求参数获取表名（向后兼容）"""
    source = request.args.get('source', DEFAULT_TABLE)
    adapter = get_adapter(source)
    if adapter:
        return adapter.get_table()
    return TABLES.get(source, TABLES[DEFAULT_TABLE])

def get_ch_client():
    """获取ClickHouse客户端 - 每次调用创建新实例避免并发冲突"""
    try:
        # 每次创建新客户端，避免并发查询冲突
        client = clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)
        return client
    except Exception as e:
        print(f"❌ 连接ClickHouse失败: {e}")
        return None

def init_redis():
    """初始化Redis客户端"""
    global redis_client, cache_manager
    try:
        redis_client = redis.Redis(**REDIS_CONFIG)
        redis_client.ping()
        print("✓ Redis缓存已启用")

        # 初始化缓存管理器
        cache_manager = CacheManager(redis_client)

        return True
    except Exception as e:
        print(f"⚠️  Redis连接失败，缓存功能已禁用: {e}")
        USE_CACHE = False
        cache_manager = CacheManager(None)
        return False

def init_services():
    """初始化新架构的服务"""
    global data_aggregator, query_builder

    # 初始化查询构建器
    query_builder = QueryBuilder(get_ch_client)

    # 初始化数据聚合器
    data_aggregator = DataSourceAggregator(get_ch_client, cache_manager)

    print("✓ 数据源适配器服务已初始化")

def get_cache_key(source):
    """生成缓存键"""
    return f"aggregated:{source}"

def get_from_cache(cache_key):
    """从缓存获取数据"""
    if not USE_CACHE or not redis_client:
        return None
    try:
        cached_data = redis_client.get(cache_key)
        if cached_data:
            print(f"🎯 命中缓存！数据源: {cache_key.split(':')[1]}")
            return json.loads(cached_data)
        return None
    except Exception as e:
        print(f"⚠️  缓存读取失败: {e}")
        return None

def set_to_cache(cache_key, data, ttl=600):
    """保存数据到缓存（10分钟缓存，优化性能）"""
    if not USE_CACHE:
        return
    try:
        redis_client.setex(cache_key, ttl, json.dumps(data))
        print(f"💾 数据已缓存 ({ttl}秒)")
    except Exception as e:
        print(f"⚠️ 缓存写入失败: {e}")

def query_clickhouse(sql, params=None):
    """执行ClickHouse查询"""
    client = get_ch_client()
    if not client:
        return None

    try:
        result = client.query(sql, parameters=params)
        # 短暂延迟，避免并发查询
        time.sleep(0.01)
        return result
    except Exception as e:
        print(f"❌ 查询失败: {e}")
        return None


def query_total_unique_journals():
    """查询所有表的总唯一期刊数（去重）- 使用新架构"""
    return query_builder.query_unique_count_across_sources('venue', ['openalex', 'semantic', 'dblp', 'arxiv'])

def query_total_unique_papers():
    """查询三个表的总唯一论文数（DOI去重）- 使用新架构"""
    return query_builder.query_unique_count_across_sources('doi', ['openalex', 'semantic', 'dblp'])

def query_total_unique_authors():
    """查询四个表的总唯一作者数（按author_name去重）- 使用新架构"""
    return query_builder.query_unique_count_across_sources('author_name', ['openalex', 'semantic', 'dblp', 'arxiv'])

def query_total_unique_venues():
    """查询四个表的总唯一期刊数（按venue/journal去重）- 使用新架构"""
    return query_builder.query_unique_count_across_sources('venue', ['openalex', 'semantic', 'dblp', 'arxiv'])

def query_papers_by_date_union():
    """跨数据源按日期统计论文数（DOI去重）- 使用新架构"""
    return query_builder.query_papers_by_date_union(['openalex', 'semantic', 'dblp'])


def query_arxiv_statistics():
    """查询arxiv基础统计数据"""
    client = get_ch_client()
    if not client:
        return {
            'total_papers': 0,
            'unique_authors': 0,
            'unique_categories': 0,
            'earliest_date': 'N/A',
            'latest_date': 'N/A',
            'error': '数据库连接失败'
        }

    try:
        # 论文总数
        total_papers_sql = "SELECT count() FROM academic_db.arxiv"
        total_papers_result = client.query(total_papers_sql)
        total_papers = total_papers_result.result_rows[0][0] if total_papers_result.result_rows else 0

        # 唯一作者数
        authors_sql = """
            SELECT uniqExact(author)
            FROM academic_db.arxiv
            WHERE author != ''
        """
        authors_result = client.query(authors_sql)
        unique_authors = authors_result.result_rows[0][0] if authors_result.result_rows else 0

        # 唯一主分类数
        categories_sql = """
            SELECT uniqExact(primary_category)
            FROM academic_db.arxiv
            WHERE primary_category != ''
        """
        categories_result = client.query(categories_sql)
        unique_categories = categories_result.result_rows[0][0] if categories_result.result_rows else 0

        # 时间跨度 (published是Date类型，不能与空字符串比较)
        timespan_sql = """
            SELECT
                min(published) as earliest,
                max(published) as latest
            FROM academic_db.arxiv
        """
        timespan_result = client.query(timespan_sql)
        if timespan_result.result_rows:
            earliest_date = str(timespan_result.result_rows[0][0])
            latest_date = str(timespan_result.result_rows[0][1])
        else:
            earliest_date = 'N/A'
            latest_date = 'N/A'

        return {
            'total_papers': total_papers,
            'unique_authors': unique_authors,
            'unique_categories': unique_categories,
            'earliest_date': earliest_date,
            'latest_date': latest_date
        }
    except Exception as e:
        print(f"❌ 查询arxiv统计失败: {e}")
        return {
            'total_papers': 0,
            'unique_authors': 0,
            'unique_categories': 0,
            'earliest_date': 'N/A',
            'latest_date': 'N/A',
            'error': str(e)
        }


def query_arxiv_category_distribution():
    """查询arxiv主分类分布"""
    client = get_ch_client()
    if not client:
        return {}

    try:
        sql = """
            SELECT
                primary_category,
                count() as paper_count
            FROM academic_db.arxiv
            WHERE primary_category != ''
            GROUP BY primary_category
            ORDER BY paper_count DESC
            LIMIT 50
        """

        result = client.query(sql)
        category_dist = {}
        if result.result_rows:
            for row in result.result_rows:
                category = str(row[0]) if row[0] else 'Unknown'
                count = int(row[1]) if row[1] else 0
                category_dist[category] = count

        return category_dist
    except Exception as e:
        print(f"❌ 查询arxiv分类分布失败: {e}")
        return {}


def query_arxiv_papers_by_month():
    """查询arxiv按月统计论文数"""
    client = get_ch_client()
    if not client:
        return {}

    try:
        sql = """
            SELECT
                formatDateTime(published, '%Y-%m') as month,
                count() as paper_count
            FROM academic_db.arxiv
            GROUP BY month
            ORDER BY month ASC
        """

        result = client.query(sql)
        papers_by_month = {}
        if result.result_rows:
            for row in result.result_rows:
                month = str(row[0]) if row[0] else 'Unknown'
                count = int(row[1]) if row[1] else 0
                papers_by_month[month] = count

        return papers_by_month
    except Exception as e:
        print(f"❌ 查询arxiv时间趋势失败: {e}")
        return {}


def get_aggregated_data_arxiv():
    """获取arxiv聚合数据"""
    # 尝试从缓存获取
    cache_key = get_cache_key('arxiv')
    cached_data = get_from_cache(cache_key)
    if cached_data:
        print(f"🎯 命中arxiv缓存!")
        return cached_data

    print(f"🔄 查询arxiv数据库...")

    # 查询数据库
    try:
        aggregated_data = {
            'category_distribution': query_arxiv_category_distribution(),
            'papers_by_date': query_arxiv_papers_by_month(),
            'statistics': query_arxiv_statistics(),
            'source': 'arxiv',
            'table': 'arxiv'
        }

        # 写入缓存
        set_to_cache(cache_key, aggregated_data, ttl=120)

        return aggregated_data
    except Exception as e:
        print(f"❌ 聚合arxiv数据失败: {e}")
        return {
            'category_distribution': {},
            'papers_by_date': {},
            'statistics': {
                'total_papers': 0,
                'unique_authors': 0,
                'unique_categories': 0,
                'earliest_date': 'N/A',
                'latest_date': 'N/A',
                'error': str(e)
            },
            'source': 'arxiv',
            'table': 'arxiv'
        }


# 旧函数已删除 - 功能已由 CacheManager 替代

@app.route('/')
def index():
    """主页"""
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def static_files(filename):
    """静态文件"""
    return send_from_directory('.', filename)

def clean_nan_values(obj):
    """清理对象中的NaN和Infinity值，避免JSON序列化错误"""
    if isinstance(obj, dict):
        return {k: clean_nan_values(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_nan_values(item) for item in obj]
    elif isinstance(obj, float):
        if obj != obj:  # NaN check
            return 0
        elif obj == float('inf') or obj == float('-inf'):
            return 0
        return obj
    else:
        return obj

@app.route('/api/aggregated')
def get_aggregated_data():
    """获取聚合数据 - 使用新架构重构"""
    source = request.args.get('source', DEFAULT_TABLE)

    # 特殊处理arXiv
    if source == 'arxiv':
        return jsonify(get_aggregated_data_arxiv())

    # 如果是全部数据，使用聚合器
    if source == 'all':
        result = data_aggregator.aggregate_all_sources()
        return jsonify(clean_nan_values(result))

    # 单个数据源，使用聚合器
    result = data_aggregator.get_single_source_data(source)
    return jsonify(clean_nan_values(result))

# 旧的get_aggregated_data函数代码已删除 - 功能已由DataSourceAggregator替代
    """获取所有数据源的聚合数据"""
    print("📊 查询所有数据源聚合数据...")
    print("="*60)

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
        'source': 'all',
        'table': 'all',
        '_source_data': {}  # 新增：保存各数据源的独立数据，供切换时使用
    }

    try:
        # 聚合统计
        all_stats = {
            'total_papers': 0,
            'unique_authors': 0,
            'unique_journals': 0,
            'unique_institutions': 0,
            'fwci_sum': 0,
            'fwci_count': 0
        }

        # 聚合各表数据
        all_papers_by_date = {}
        all_citations_dist = {}
        all_journals = {}
        all_countries = {}

        for source, table in TABLES.items():
            source_start = time.time()
            print(f"\n[处理数据源: {source} ({table})]")

            # 数据源独立数据
            source_papers_by_date = {}
            source_citations_dist = {}
            source_journals = {}
            source_countries = {}
            source_institution_types = {}
            source_fwci_dist = {}
            source_unique_institutions = 0
            source_fwci_sum = 0
            source_fwci_count = 0

            # 1. 统计总览 - 区分数据源，使用去重机制
            if source == 'openalex':
                stats_sql = f"""
                SELECT
                    uniqHLL12(doi) as total_papers,
                    uniqHLL12(author_id) as unique_authors,
                    uniqHLL12(journal) as unique_journals,
                    uniqHLL12(institution_name) as unique_institutions,
                    coalesce(sum(fwci), 0) as fwci_sum,
                    countIf(fwci > 0) as fwci_count
                FROM {table}
                SETTINGS max_threads=4
                """
            elif source == 'dblp':
                stats_sql = f"""
                SELECT
                    uniqHLL12(doi) as total_papers,
                    uniqHLL12(author_name) as unique_authors,
                    uniqHLL12(venue) as unique_journals,
                    0 as unique_institutions,
                    0 as fwci_sum,
                    0 as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """
            else:
                stats_sql = f"""
                SELECT
                    uniqHLL12(doi) as total_papers,
                    uniqHLL12(author_id) as unique_authors,
                    uniqHLL12(journal) as unique_journals,
                    0 as unique_institutions,
                    0 as fwci_sum,
                    0 as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """

            stats_result = query_clickhouse(stats_sql)
            source_stats = {}
            if stats_result and stats_result.result_rows:
                row = stats_result.result_rows[0]
                total_papers = int(row[0]) if row[0] and row[0] == row[0] else 0
                unique_authors = int(row[1]) if row[1] and row[1] == row[1] else 0
                unique_journals = int(row[2]) if row[2] and row[2] == row[2] else 0
                unique_institutions = int(row[3]) if row[3] and row[3] == row[3] else 0
                fwci_sum = float(row[4]) if row[4] and row[4] == row[4] else 0
                fwci_count = int(row[5]) if row[5] and row[5] == row[5] else 0

                all_stats['total_papers'] += total_papers
                all_stats['unique_authors'] += unique_authors
                all_stats['unique_journals'] += unique_journals
                all_stats['unique_institutions'] += unique_institutions
                all_stats['fwci_sum'] += fwci_sum
                all_stats['fwci_count'] += fwci_count

                # 保存当前数据源的统计信息，用于独立数据缓存
                source_stats = {
                    'total_papers': total_papers,
                    'unique_authors': unique_authors,
                    'unique_journals': unique_journals,
                    'unique_institutions': unique_institutions,
                    'avg_fwci': round(fwci_sum / fwci_count, 2) if fwci_count > 0 and source == 'openalex' else 0
                }

                if source == 'openalex':
                    source_fwci_sum = fwci_sum
                    source_fwci_count = fwci_count
                    source_unique_institutions = unique_institutions

            # 2. 按日期统计 - 精确到月份
            # DBLP使用year字段，其他使用publication_date字段
            if source == 'dblp':
                # DBLP的publication_date是年份（如'2024'），需要特殊处理
                date_sql = f"""
                SELECT
                    concat(year, '-01') as date,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE year != '' AND length(year) == 4
                GROUP BY year
                ORDER BY year DESC
                SETTINGS max_threads=1
                """
            else:
                date_sql = f"""
                SELECT
                    toDate(toDateOrNull(publication_date)) as date_month,
                    formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE publication_date != '' AND length(publication_date) > 0
                GROUP BY date_month, date
                ORDER BY date_month DESC
                SETTINGS max_threads=1
                """

            date_result = query_clickhouse(date_sql)
            if date_result:
                for row in date_result.result_rows:
                    # 统一转换为字符串格式，避免类型混合
                    date_key = str(row[0])
                    count_value = row[1]
                    all_papers_by_date[date_key] = all_papers_by_date.get(date_key, 0) + count_value
                    source_papers_by_date[date_key] = count_value  # 同时保存独立数据

            # 3. 引用数分布（仅OpenAlex和Semantic支持）
            step_start = time.time()
            if source in ['openalex', 'semantic']:
                print(f"  [步骤 3/7] 引用数分布...")
                citation_sql = f"""
                SELECT
                    multiIf(
                        citation_count = 0, '0',
                        citation_count < 6, '1-5',
                        citation_count < 11, '6-10',
                        citation_count < 21, '11-20',
                        citation_count < 51, '21-50',
                        citation_count < 101, '51-100',
                        citation_count < 501, '101-500',
                        '500+'
                    ) as range,
                    uniqHLL12(doi) as count
                FROM {table}
                GROUP BY range
                ORDER BY range
                SETTINGS max_threads=1, max_execution_time=60
                """
                citation_result = query_clickhouse(citation_sql)
                if citation_result:
                    for row in citation_result.result_rows:
                        all_citations_dist[row[0]] = all_citations_dist.get(row[0], 0) + row[1]
                        source_citations_dist[row[0]] = row[1]  # 同时保存独立数据
                step_time = time.time() - step_start
                print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")
            else:
                print(f"  [步骤 3/7] 引用数分布... ⊘ 跳过 (数据源不支持)")

            # 4. Top期刊
            step_start = time.time()
            print(f"  [步骤 4/7] Top期刊...")
            # 根据数据源选择字段名
            journal_field = 'venue' if source == 'dblp' else 'journal'
            journal_sql = f"""
            SELECT
                {journal_field},
                uniqHLL12(doi) as count
            FROM {table}
            WHERE {journal_field} != ''
                AND length({journal_field}) > 3
                AND lower({journal_field}) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
            GROUP BY {journal_field}
            ORDER BY count DESC
            LIMIT 50
            SETTINGS max_threads=8, max_execution_time=60
            """
            journal_result = query_clickhouse(journal_sql)
            print(f"    📊 查询对象: {journal_result}")
            if journal_result:
                print(f"    📊 result_rows类型: {type(journal_result.result_rows)}")
                if journal_result.result_rows:
                    print(f"    📊 result_rows长度: {len(journal_result.result_rows)}")
                    for row in journal_result.result_rows:
                        all_journals[row[0]] = all_journals.get(row[0], 0) + row[1]
                        source_journals[row[0]] = row[1]  # 同时保存独立数据
                    print(f"    ✓ 完成 (耗时: {step_time:.2f}秒, 期刊数: {len(source_journals)})")
                else:
                    print(f"    ⚠️ 查询返回空结果")
            else:
                print(f"    ⚠️ 查询失败或无结果")
            step_time = time.time() - step_start

            # 5. OpenAlex特有数据（仅OpenAlex查询）
            if source == 'openalex':
                step_start = time.time()
                print(f"  [步骤 5/7] Top国家查询...")
                country_sql = f"""
                SELECT
                    institution_country,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE institution_country != ''
                    AND institution_country != 'nan'
                    AND lower(institution_country) != 'nan'
                GROUP BY institution_country
                ORDER BY count DESC
                LIMIT 15
                SETTINGS max_threads=1
                """
                country_result = query_clickhouse(country_sql)
                if country_result:
                    for row in country_result.result_rows:
                        all_countries[row[0]] = all_countries.get(row[0], 0) + row[1]
                        source_countries[row[0]] = row[1]  # 保存独立数据
                step_time = time.time() - step_start
                print(f"    ✓ 完成 (耗时: {step_time:.2f}秒, 国家数: {len(source_countries)})")

                step_start = time.time()
                print(f"  [步骤 6/7] 机构类型查询...")
                inst_type_sql = f"""
                SELECT
                    institution_type,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE institution_type != ''
                        AND institution_type != 'nan'
                        AND lower(institution_type) != 'nan'
                GROUP BY institution_type
                ORDER BY count DESC
                """
                inst_type_result = query_clickhouse(inst_type_sql)
                if inst_type_result:
                    for row in inst_type_result.result_rows:
                        source_institution_types[row[0]] = row[1]
                step_time = time.time() - step_start
                print(f"    ✓ 完成 (耗时: {step_time:.2f}秒, 类型数: {len(source_institution_types)})")

                step_start = time.time()
                print(f"  [步骤 7/7] FWCI分布查询...")
                fwci_sql = f"""
                SELECT
                    multiIf(
                        fwci < 0.5, '<0.5',
                        fwci < 1, '0.5-1',
                        fwci < 2, '1-2',
                        fwci < 3, '2-3',
                        fwci < 5, '3-5',
                        fwci < 10, '5-10',
                        '10+'
                    ) as range,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE fwci > 0
                GROUP BY range
                ORDER BY range
                """
                fwci_result = query_clickhouse(fwci_sql)
                if fwci_result:
                    for row in fwci_result.result_rows:
                        source_fwci_dist[row[0]] = row[1]
                step_time = time.time() - step_start
                print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")

            # 保存当前数据源的独立数据到result['_source_data']
            result['_source_data'][source] = {
                'papers_by_date': dict(source_papers_by_date),
                'citations_distribution': dict(source_citations_dist),
                'top_journals': dict(source_journals),
                'top_countries': dict(source_countries),
                'institution_types': dict(source_institution_types),
                'fwci_distribution': dict(source_fwci_dist),
                'statistics': source_stats,
                'source': source
            }

            source_time = time.time() - source_start
            print(f"  ✅ {source} 数据源处理完成 (耗时: {source_time:.2f}秒)")

        # 构建最终结果
        # 使用跨数据源去重函数获取准确的统计数字
        total_papers = query_total_unique_papers()
        total_authors = query_total_unique_authors()
        total_venues = query_total_unique_venues()
        papers_by_date = query_papers_by_date_union()

        result['statistics'] = {
            'total_papers': int(total_papers) if total_papers and total_papers == total_papers else 0,
            'unique_authors': int(total_authors) if total_authors and total_authors == total_authors else 0,
            'unique_journals': int(total_venues) if total_venues and total_venues == total_venues else 0,
            'unique_institutions': int(all_stats['unique_institutions']) if all_stats['unique_institutions'] and all_stats['unique_institutions'] == all_stats['unique_institutions'] else 0,
            'high_citations': 0,
            'avg_fwci': round(all_stats['fwci_sum'] / all_stats['fwci_count'], 2) if all_stats['fwci_count'] > 0 and all_stats['fwci_sum'] > 0 else 0
        }

        result['papers_by_date'] = papers_by_date if papers_by_date else all_papers_by_date
        result['citations_distribution'] = all_citations_dist
        result['top_journals'] = dict(sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50])
        result['top_countries'] = all_countries

        # DBLP特有字段（不再计算，返回空字典保持API兼容性）
        result['ccf_class_distribution'] = {}
        result['publication_type_distribution'] = {}
        result['venue_type_distribution'] = {}

        print("="*60)
        print("✅ 全部数据查询完成")
        print("="*60 + "\n")

        # 清理NaN值，避免JSON序列化错误
        result = clean_nan_values(result)

        # 保存到缓存
        all_cache_key = get_cache_key('all')
        set_to_cache(all_cache_key, result, ttl=120)

        return jsonify(result)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500

@app.route('/api/sources')
def get_sources():
    """获取所有数据源的基本统计"""
    print("📊 查询所有数据源统计...")

    result = {}
    for source, table in TABLES.items():
        try:
            # 查询每个表的基本统计
            stats_sql = f"SELECT count() as count FROM {table}"
            stats_result = query_clickhouse(stats_sql)

            if stats_result and stats_result.result_rows:
                row = stats_result.result_rows[0]
                result[source] = {
                    'table': table,
                    'total_records': row[0]
                }
        except Exception as e:
            result[source] = {
                'table': table,
                'error': str(e)
            }

    return jsonify(result)

@app.route('/api/health')
def health_check():
    """健康检查"""
    try:
        client = get_ch_client()
        if not client:
            return jsonify({'status': 'error', 'message': 'Cannot connect to ClickHouse'}), 500

        # 测试查询
        client.query('SELECT 1')
        return jsonify({
            'status': 'healthy',
            'clickhouse': 'connected',
            'database': CLICKHOUSE_CONFIG['database'],
            'tables': TABLES
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500


def preload_all_caches():
    """预加载所有数据源的缓存（通过HTTP请求）"""
    if not USE_CACHE or not redis_client:
        print("⚠️  缓存未启用，跳过预加载")
        return

    sources = ['openalex', 'semantic', 'dblp', 'arxiv', 'all']

    for source in sources:
        print(f"  📦 预加载 {source} 数据源...")
        try:
            import requests
            # 使用较短的超时时间，避免长时间等待
            response = requests.get(f'http://localhost:8080/api/aggregated?source={source}', timeout=300)
            if response.status_code == 200:
                print(f"    ✅ {source} 缓存加载成功")
            else:
                print(f"    ❌ {source} 缓存加载失败: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"    ⚠️  {source} 连接失败（服务器可能还未完全启动）")
        except Exception as e:
            print(f"    ❌ {source} 缓存加载异常: {e}")

    print("  ✅ 所有数据源缓存预加载完成")


def start_cache_refresh_thread():
    """启动后台缓存刷新线程"""
    global cache_refresh_thread, cache_refresh_running

    if not USE_CACHE or not redis_client:
        print("⚠️  缓存未启用，跳过后台刷新")
        return

    cache_refresh_running = True
    cache_refresh_thread = threading.Thread(target=cache_refresh_worker, daemon=True)
    cache_refresh_thread.start()
    print(f"✅ 后台缓存刷新线程已启动（间隔: {CACHE_REFRESH_INTERVAL}秒）")


def cache_refresh_worker():
    """后台缓存刷新工作线程"""
    global cache_refresh_running

    while cache_refresh_running:
        try:
            time.sleep(CACHE_REFRESH_INTERVAL)

            if not cache_refresh_running:
                break

            print(f"\n{'='*60}")
            print(f"🔄 开始自动刷新缓存...")
            print(f"时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"{'='*60}")

            preload_all_caches()

            print(f"✅ 缓存刷新完成")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"❌ 缓存刷新失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    print("🚀 启动学术数据看板服务")
    print(f"📡 ClickHouse: {CLICKHOUSE_CONFIG['host']}:{CLICKHOUSE_CONFIG['port']}/{CLICKHOUSE_CONFIG['database']}")
    print(f"📋 数据表: {TABLES}")

    # 初始化Redis
    init_redis()

    # 初始化新架构服务
    init_services()

    # 测试连接
    client = get_ch_client()
    if client:
        try:
            for source, table in TABLES.items():
                result = client.query(f"SELECT count() FROM {table}")
                count = result.result_rows[0][0]
                print(f"✓ {source} ({table}): {count:,} 条记录")
        except Exception as e:
            print(f"⚠️  查询失败: {e}")
    else:
        print("❌ 连接ClickHouse失败")

    print("🌐 服务启动在 http://0.0.0.0:8080")

    # 启动时清除所有缓存
    if USE_CACHE:
        print("\n" + "="*60)
        print("🔄 清除启动时的旧缓存...")
        print("="*60)
        sources = get_enabled_sources()
        for source in sources:
            cache_manager.delete_cache(source)
        cache_manager.delete_cache('all')
        print("="*60 + "\n")

    # 设置缓存预加载和后台刷新（在Flask启动后自动执行）
    if USE_CACHE:
        from threading import Timer

        def delayed_cache_init():
            """延迟执行缓存初始化"""
            # 等待Flask完全启动
            time.sleep(5)

            print("\n" + "="*60)
            print("🚀 启动缓存预加载...")
            print("="*60)
            preload_all_caches()

            # 启动后台缓存刷新线程
            print("\n" + "="*60)
            print("🔄 启动后台缓存刷新线程...")
            print("="*60)
            start_cache_refresh_thread()
            print("✅ 缓存将每2分钟自动刷新")
            print("="*60 + "\n")

        # 立即启动Timer，在app.run()执行时开始计时
        cache_timer = Timer(0, delayed_cache_init)
        cache_timer.daemon = True
        cache_timer.start()

    # 启动Flask服务器
    app.run(**FLASK_CONFIG)