#!/usr/bin/env python3
"""
学术数据看板API服务器 - 支持Redis缓存和去重统计
"""

import time
import json
import threading
import pandas as pd
from config import CLICKHOUSE_CONFIG, TABLES, DEFAULT_TABLE, FLASK_CONFIG
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import clickhouse_connect
import redis

app = Flask(__name__, static_folder='.')
CORS(app)

# Redis缓存配置
REDIS_CONFIG = {
    'host': 'localhost',
    'port': 6379,
    'db': 0,
    'decode_responses': True
}

# 全局客户端
ch_client = None
redis_client = None
USE_CACHE = True

# 全局客户端
ch_client = None

def get_table_name():
    """根据请求参数获取表名"""
    source = request.args.get('source', DEFAULT_TABLE)
    return TABLES.get(source, TABLES[DEFAULT_TABLE])

def get_ch_client():
    """获取ClickHouse客户端"""
    global ch_client
    if ch_client is None:
        try:
            ch_client = clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)
        except Exception as e:
            print(f"❌ 连接ClickHouse失败: {e}")
            return None
    return ch_client

def init_redis():
    """初始化Redis客户端"""
    global redis_client
    try:
        redis_client = redis.Redis(**REDIS_CONFIG)
        redis_client.ping()
        print("✓ Redis缓存已启用")
        return True
    except Exception as e:
        print(f"⚠️  Redis连接失败，缓存功能已禁用: {e}")
        USE_CACHE = False
        return False

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
    """获取聚合数据"""
    start_time = time.time()
    source = request.args.get('source', DEFAULT_TABLE)

    # 检查缓存
    cache_key = get_cache_key(source)
    cached_data = get_from_cache(cache_key)
    if cached_data:
        return jsonify(cached_data)

    # 如果是全部数据，需要聚合两个表
    if source == 'all':
        return get_all_sources_data()

    # 智能缓存：检查"全部数据"缓存中是否有该数据源的独立数据
    if source in ['openalex', 'semantic']:
        all_cache_key = get_cache_key('all')
        all_cached_data = get_from_cache(all_cache_key)
        if all_cached_data and all_cached_data.get('_source_data', {}).get(source):
            print(f"🚀 智能缓存：从全部数据中提取 {source} 独立数据（无需重新查询）")
            source_data = all_cached_data['_source_data'][source]

            # 验证数据完整性
            source_stats = source_data.get('statistics', {})
            if (source_stats.get('unique_journals', 0) == 0 or
                source_stats.get('total_papers', 0) == 0):
                print(f"⚠️  智能缓存数据不完整 (期刊数:{source_stats.get('unique_journals', 0)}, 论文数:{source_stats.get('total_papers', 0)})，重新查询 {source}...")
                redis_client.delete(all_cache_key)
            else:
                # 确保包含所有必需字段
                result = {
                    'papers_by_date': source_data.get('papers_by_date', {}),
                    'citations_distribution': source_data.get('citations_distribution', {}),
                    'top_journals': source_data.get('top_journals', {}),
                    'top_countries': source_data.get('top_countries', {}),
                    'institution_types': source_data.get('institution_types', {}),
                    'fwci_distribution': source_data.get('fwci_distribution', {}),
                    'statistics': source_stats,
                    'source': source,
                    'table': TABLES.get(source, source)
                }
                set_to_cache(cache_key, result, ttl=300)

                # 清理NaN值，避免JSON序列化错误
                result = clean_nan_values(result)

                return jsonify(result)

    table_name = get_table_name()
    print(f"📊 查询聚合数据... 数据源: {source}, 表: {table_name}")
    print(f"{'='*60}")

    result = {
        'papers_by_date': {},
        'citations_distribution': {},
        'author_types': {},
        'top_journals': {},
        'top_countries': {},
        'institution_types': {},
        'fwci_distribution': {},
        'statistics': {},
        'source': source,
        'table': table_name
    }

    try:
        # 1. 统计总览 - 使用DOI去重，根据数据源使用不同的查询
        step_start = time.time()
        print(f"[步骤 1/8] 统计总览查询...")
        if source == 'openalex':
            # OpenAlex有完整字段，使用近似计数大幅提升性能
            stats_sql = f"""
            SELECT
                uniqHLL12(doi) as total_papers,
                uniqHLL12(author_id) as unique_authors,
                uniqHLL12(journal) as unique_journals,
                uniqHLL12(institution_name) as unique_institutions,
                uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
                round(avgIf(fwci, fwci > 0), 2) as avg_fwci
            FROM {table_name}
            SETTINGS max_threads=4, max_execution_time=30
            """
        else:
            # Semantic字段较少，使用简化统计
            stats_sql = f"""
            SELECT
                uniqHLL12(doi) as total_papers,
                uniqHLL12(author_id) as unique_authors,
                uniqHLL12(journal) as unique_journals,
                0 as unique_institutions,
                uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
                0 as avg_fwci
            FROM {table_name}
            SETTINGS max_threads=1, max_execution_time=30
            """

        stats_result = query_clickhouse(stats_sql)
        if stats_result and stats_result.result_rows:
            row = stats_result.result_rows[0]
            result['statistics'] = {
                'total_papers': int(row[0]) if row[0] else 0,
                'unique_authors': int(row[1]) if row[1] else 0,
                'unique_journals': int(row[2]) if row[2] else 0,
                'unique_institutions': int(row[3]) if row[3] else 0,
                'high_citations': int(row[4]) if row[4] else 0,
                'avg_fwci': float(row[5]) if row[5] and row[5] == row[5] else 0  # 验证不是NaN
            }
        step_time = time.time() - step_start
        print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")

        # 2. 按论文发表日期统计 - 精确到月份，使用DOI去重
        step_start = time.time()
        print(f"[步骤 2/8] 按日期统计...")
        if source == 'openalex':
            # OpenAlex表有publication_date字段，提取年月
            date_sql = f"""
            SELECT
                formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE publication_date != '' AND length(publication_date) > 0
            GROUP BY formatDateTime(toDateOrNull(publication_date), '%Y-%m')
            ORDER BY date DESC
            SETTINGS max_threads=1
            """
        else:
            # Semantic表使用year字段，转换为YYYY-01格式
            date_sql = f"""
            SELECT
                concat(toString(year), '-01') as date,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE year > 0
            GROUP BY concat(toString(year), '-01')
            ORDER BY date DESC
            SETTINGS max_threads=1
            """

        date_result = query_clickhouse(date_sql)
        if date_result:
            for row in date_result.result_rows:
                result['papers_by_date'][str(row[0])] = int(row[1])
        step_time = time.time() - step_start
        print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 记录数: {len(result['papers_by_date'])})")

        # 3. 引用数分布 - 使用DOI去重
        step_start = time.time()
        print(f"[步骤 3/8] 引用数分布查询...")
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
        FROM {table_name}
        GROUP BY range
        ORDER BY range
        SETTINGS max_threads=4, max_execution_time=60
        """

        citation_result = query_clickhouse(citation_sql)
        if citation_result:
            for row in citation_result.result_rows:
                result['citations_distribution'][row[0]] = int(row[1])
        step_time = time.time() - step_start
        print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")

        # 4. 作者类型分布（基于tag字段）
        step_start = time.time()
        print(f"[步骤 4/8] 作者类型分布查询...")
        author_sql = f"""
        SELECT
            tag,
            count() as count
        FROM {table_name}
        WHERE tag != ''
        GROUP BY tag
        ORDER BY count DESC
        LIMIT 10
        """

        author_result = query_clickhouse(author_sql)
        if author_result:
            for row in author_result.result_rows:
                result['author_types'][row[0]] = int(row[1])
        step_time = time.time() - step_start
        print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")


        # 5. Top期刊 - 使用DOI去重
        step_start = time.time()
        print(f"[步骤 5/8] Top期刊查询...")
        journal_sql = f"""
        SELECT
            journal,
            uniqHLL12(doi) as count
        FROM {table_name}
        WHERE journal != ''
            AND length(journal) > 3
            AND lower(journal) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
        GROUP BY journal
        ORDER BY count DESC
        LIMIT 50
        SETTINGS max_threads=8, max_execution_time=60
        """

        journal_result = query_clickhouse(journal_sql)
        if journal_result:
            for row in journal_result.result_rows:
                result['top_journals'][row[0]] = int(row[1])
        step_time = time.time() - step_start
        print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 期刊数: {len(result['top_journals'])})")

        # 6. Top国家（仅OpenAlex支持）- 使用DOI去重
        step_start = time.time()
        print(f"[步骤 6/8] Top国家查询...")
        if source == 'openalex':
            country_sql = f"""
            SELECT
                institution_country,
                uniqHLL12(doi) as count
            FROM {table_name}
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
                    result['top_countries'][row[0]] = int(row[1])
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 国家数: {len(result['top_countries'])})")
        else:
            print(f"  ⊘ 跳过 (仅OpenAlex支持)")

        # 7. 机构类型分布（仅OpenAlex支持）- 使用DOI去重
        step_start = time.time()
        print(f"[步骤 7/8] 机构类型分布查询...")
        if source == 'openalex':
            inst_type_sql = f"""
            SELECT
                institution_type,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE institution_type != ''
                AND institution_type != 'nan'
                AND lower(institution_type) != 'nan'
            GROUP BY institution_type
            ORDER BY count DESC
            """

            inst_type_result = query_clickhouse(inst_type_sql)
            if inst_type_result:
                for row in inst_type_result.result_rows:
                    result['institution_types'][row[0]] = int(row[1])
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")
        else:
            print(f"  ⊘ 跳过 (仅OpenAlex支持)")

        # 8. FWCI分布（仅OpenAlex支持）- 使用DOI去重
        step_start = time.time()
        print(f"[步骤 8/8] FWCI分布查询...")
        if source == 'openalex':
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
            FROM {table_name}
            WHERE fwci > 0
            GROUP BY range
            ORDER BY range
            """

            fwci_result = query_clickhouse(fwci_sql)
            if fwci_result:
                for row in fwci_result.result_rows:
                    result['fwci_distribution'][row[0]] = int(row[1])
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")
        else:
            print(f"  ⊘ 跳过 (仅OpenAlex支持)")

        total_time = time.time() - start_time if 'start_time' in locals() else 0
        print(f"\n{'='*60}")
        print(f"✅ 查询完成！总耗时: {total_time:.2f}秒")
        print(f"{'='*60}\n")

        # 保存到缓存
        set_to_cache(cache_key, result, ttl=300)

        # 清理NaN值，避免JSON序列化错误
        result = clean_nan_values(result)

        return jsonify(result)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        return jsonify({'error': str(e)}), 500

def get_all_sources_data():
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
            'unique_journals': 0,  # 累加各数据源的期刊数（注意：这会有重复，后面会用union去重）
            'unique_institutions': 0,
            'high_citations': 0,
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
                    uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
                    sum(fwci) as fwci_sum,
                    countIf(fwci > 0) as fwci_count
                FROM {table}
                SETTINGS max_threads=4
                """
            else:
                stats_sql = f"""
                SELECT
                    uniqHLL12(doi) as total_papers,
                    uniqHLL12(author_id) as unique_authors,
                    uniqHLL12(journal) as unique_journals,
                    0 as unique_institutions,
                    uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
                    0 as fwci_sum,
                    0 as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """

            stats_result = query_clickhouse(stats_sql)
            source_stats = {}
            if stats_result and stats_result.result_rows:
                row = stats_result.result_rows[0]
                total_papers = int(row[0]) if row[0] else 0
                unique_authors = int(row[1]) if row[1] else 0
                unique_journals = int(row[2]) if row[2] else 0
                unique_institutions = int(row[3]) if row[3] else 0
                high_citations = int(row[4]) if row[4] else 0
                fwci_sum = float(row[5]) if row[5] else 0
                fwci_count = int(row[6]) if row[6] else 0

                all_stats['total_papers'] += total_papers
                all_stats['unique_authors'] += unique_authors
                all_stats['unique_journals'] += unique_journals
                all_stats['unique_institutions'] += unique_institutions
                all_stats['high_citations'] += high_citations
                all_stats['fwci_sum'] += fwci_sum
                all_stats['fwci_count'] += fwci_count

                # 保存当前数据源的统计信息，用于独立数据缓存
                source_stats = {
                    'total_papers': total_papers,
                    'unique_authors': unique_authors,
                    'unique_journals': unique_journals,  # 直接使用SQL查询的唯一期刊数
                    'unique_institutions': unique_institutions,
                    'high_citations': high_citations,
                    'avg_fwci': round(fwci_sum / fwci_count, 2) if fwci_count > 0 and source == 'openalex' else 0
                }

                if source == 'openalex':
                    source_fwci_sum = fwci_sum
                    source_fwci_count = fwci_count
                    source_unique_institutions = unique_institutions

            # 2. 按日期统计 - 精确到月份
            if source == 'openalex':
                date_sql = f"""
                SELECT
                    formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE publication_date != '' AND length(publication_date) > 0
                GROUP BY formatDateTime(toDateOrNull(publication_date), '%Y-%m')
                ORDER BY date DESC
                SETTINGS max_threads=1
                """
            else:
                # Semantic表只有年份，转换为YYYY-01格式
                date_sql = f"""
                SELECT
                    concat(toString(year), '-01') as date,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE year > 0
                GROUP BY concat(toString(year), '-01')
                ORDER BY date DESC
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

            # 3. 引用数分布
            step_start = time.time()
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

            # 4. Top期刊
            step_start = time.time()
            print(f"  [步骤 4/7] Top期刊...")
            journal_sql = f"""
            SELECT
                journal,
                uniqHLL12(doi) as count
            FROM {table}
            WHERE journal != ''
                AND length(journal) > 3
                AND lower(journal) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
            GROUP BY journal
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
        # 查询总的唯一期刊数
        total_journals = 0
        try:
            # 使用UNION ALL获取两个表的所有期刊，然后去重
            journal_sql = """
            SELECT uniqExact(journal) as count
            FROM (
                SELECT journal FROM OpenAlex
                UNION ALL
                SELECT journal FROM semantic
            )
            WHERE journal != ''
            """
            journal_result = query_clickhouse(journal_sql)
            if journal_result and journal_result.result_rows:
                total_journals = journal_result.result_rows[0][0]
        except Exception as e:
            print(f"  ⚠️ 查询总期刊数失败: {e}")

        result['statistics'] = {
            'total_papers': int(all_stats['total_papers']) if all_stats['total_papers'] else 0,
            'unique_authors': int(all_stats['unique_authors']) if all_stats['unique_authors'] else 0,
            'unique_journals': int(total_journals) if total_journals else 0,
            'unique_institutions': int(all_stats['unique_institutions']) if all_stats['unique_institutions'] else 0,
            'high_citations': int(all_stats['high_citations']) if all_stats['high_citations'] else 0,
            'avg_fwci': round(all_stats['fwci_sum'] / all_stats['fwci_count'], 2) if all_stats['fwci_count'] > 0 and all_stats['fwci_sum'] > 0 else 0
        }

        result['papers_by_date'] = all_papers_by_date
        result['citations_distribution'] = all_citations_dist
        result['top_journals'] = dict(sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50])
        result['top_countries'] = all_countries

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

if __name__ == '__main__':
    print("🚀 启动学术数据看板服务")
    print(f"📡 ClickHouse: {CLICKHOUSE_CONFIG['host']}:{CLICKHOUSE_CONFIG['port']}/{CLICKHOUSE_CONFIG['database']}")
    print(f"📋 数据表: {TABLES}")

    # 初始化Redis
    init_redis()

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
        sources = ['openalex', 'semantic', 'all']
        for source in sources:
            cache_key = get_cache_key(source)
            try:
                if redis_client:
                    redis_client.delete(cache_key)
                    print(f"  ✅ {source} 缓存已清除")
            except Exception as e:
                print(f"  ❌ {source} 缓存清除失败: {e}")
        print("="*60 + "\n")

    app.run(**FLASK_CONFIG)