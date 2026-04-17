#!/usr/bin/env python3
"""
修复后的API服务器 - 针对不同数据源优化查询
"""

import time
from config import CLICKHOUSE_CONFIG, TABLES, DEFAULT_TABLE, FLASK_CONFIG
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import clickhouse_connect

app = Flask(__name__, static_folder='.')
CORS(app)

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

@app.route('/api/aggregated')
def get_aggregated_data():
    """获取聚合数据"""
    source = request.args.get('source', DEFAULT_TABLE)

    # 如果是全部数据，需要聚合两个表
    if source == 'all':
        return get_all_sources_data()

    table_name = get_table_name()
    print(f"📊 查询聚合数据... 数据源: {source}, 表: {table_name}")

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
        # 1. 统计总览 - 根据数据源使用不同的查询
        if source == 'openalex':
            # OpenAlex有完整字段
            stats_sql = f"""
            SELECT
                count() as total_papers,
                uniqExact(author_id) as unique_authors,
                uniqExact(journal) as unique_journals,
                uniqExact(institution_name) as unique_institutions,
                countIf(citation_count >= 50) as high_citations,
                avg(fwci) as avg_fwci
            FROM {table_name}
            WHERE fwci > 0
            SETTINGS max_threads=1
            """
        else:
            # Semantic字段较少，使用简化统计
            stats_sql = f"""
            SELECT
                count() as total_papers,
                uniqExact(author_id) as unique_authors,
                uniqExact(journal) as unique_journals,
                0 as unique_institutions,
                countIf(citation_count >= 50) as high_citations,
                0 as avg_fwci
            FROM {table_name}
            SETTINGS max_threads=1
            """

        stats_result = query_clickhouse(stats_sql)
        if stats_result and stats_result.result_rows:
            row = stats_result.result_rows[0]
            result['statistics'] = {
                'total_papers': row[0],
                'unique_authors': row[1],
                'unique_journals': row[2],
                'unique_institutions': row[3],
                'high_citations': row[4],
                'avg_fwci': round(row[5], 2) if row[5] and row[5] != 0 else 0
            }

        # 2. 按论文发表日期统计 - 精确到月份
        if source == 'openalex':
            # OpenAlex表有publication_date字段，提取年月
            date_sql = f"""
            SELECT
                formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
                count() as count
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
                count() as count
            FROM {table_name}
            WHERE year > 0
            GROUP BY concat(toString(year), '-01')
            ORDER BY date DESC
            SETTINGS max_threads=1
            """

        date_result = query_clickhouse(date_sql)
        if date_result:
            for row in date_result.result_rows:
                result['papers_by_date'][str(row[0])] = row[1]

        # 3. 引用数分布 - 查询全部数据
        citation_sql = f"""
        SELECT
            multiIf(
                citation_count = 0, '0',
                citation_count < 10, '1-9',
                citation_count < 50, '10-49',
                citation_count < 100, '50-99',
                '100+'
            ) as range,
            count() as count
        FROM {table_name}
        GROUP BY range
        ORDER BY range
        SETTINGS max_threads=4
        """

        citation_result = query_clickhouse(citation_sql)
        if citation_result:
            for row in citation_result.result_rows:
                result['citations_distribution'][row[0]] = row[1]

        # 4. 作者类型分布（基于tag字段）
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
                result['author_types'][row[0]] = row[1]

        # 5. Top期刊 - 查询全部数据
        journal_sql = f"""
        SELECT
            journal,
            count() as count
        FROM {table_name}
        WHERE journal != ''
        GROUP BY journal
        ORDER BY count DESC
        LIMIT 50
        SETTINGS max_threads=4
        """

        journal_result = query_clickhouse(journal_sql)
        if journal_result:
            for row in journal_result.result_rows:
                result['top_journals'][row[0]] = row[1]

        # 6. Top国家（仅OpenAlex支持）
        if source == 'openalex':
            country_sql = f"""
            SELECT
                institution_country,
                count() as count
            FROM {table_name}
            WHERE institution_country != ''
            GROUP BY institution_country
            ORDER BY count DESC
            LIMIT 15
            SETTINGS max_threads=1
            """

            country_result = query_clickhouse(country_sql)
            if country_result:
                for row in country_result.result_rows:
                    result['top_countries'][row[0]] = row[1]

        # 7. 机构类型分布（仅OpenAlex支持）
        if source == 'openalex':
            inst_type_sql = f"""
            SELECT
                institution_type,
                count() as count
            FROM {table_name}
            WHERE institution_type != ''
            GROUP BY institution_type
            ORDER BY count DESC
            """

            inst_type_result = query_clickhouse(inst_type_sql)
            if inst_type_result:
                for row in inst_type_result.result_rows:
                    result['institution_types'][row[0]] = row[1]

        # 8. FWCI分布（仅OpenAlex支持）
        if source == 'openalex':
            fwci_sql = f"""
            SELECT
                multiIf(
                    fwci < 1, '<1',
                    fwci < 2, '1-2',
                    fwci < 5, '2-5',
                    '5+'
                ) as range,
                count() as count
            FROM {table_name}
            WHERE fwci > 0
            GROUP BY range
            ORDER BY range
            """

            fwci_result = query_clickhouse(fwci_sql)
            if fwci_result:
                for row in fwci_result.result_rows:
                    result['fwci_distribution'][row[0]] = row[1]

        print("✓ 查询完成")
        return jsonify(result)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        return jsonify({'error': str(e)}), 500

def get_all_sources_data():
    """获取所有数据源的聚合数据"""
    print("📊 查询所有数据源聚合数据...")

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
        'table': 'all'
    }

    try:
        # 聚合统计
        all_stats = {
            'total_papers': 0,
            'unique_authors': 0,
            'unique_journals': 0,
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
            print(f"  处理数据源: {source} ({table})...")

            # 1. 统计总览 - 区分数据源
            if source == 'openalex':
                stats_sql = f"""
                SELECT
                    count() as total_papers,
                    uniqExact(author_id) as unique_authors,
                    countIf(citation_count >= 50) as high_citations,
                    sum(fwci) as fwci_sum,
                    countIf(fwci > 0) as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """
            else:
                stats_sql = f"""
                SELECT
                    count() as total_papers,
                    uniqExact(author_id) as unique_authors,
                    countIf(citation_count >= 50) as high_citations,
                    0 as fwci_sum,
                    0 as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """

            stats_result = query_clickhouse(stats_sql)
            if stats_result and stats_result.result_rows:
                row = stats_result.result_rows[0]
                all_stats['total_papers'] += row[0]
                all_stats['unique_authors'] += row[1]
                all_stats['high_citations'] += row[2]
                all_stats['fwci_sum'] += (row[3] or 0)
                all_stats['fwci_count'] += (row[4] or 0)

            # 2. 按日期统计 - 精确到月份
            if source == 'openalex':
                date_sql = f"""
                SELECT
                    formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
                    count() as count
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
                    count() as count
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
                    all_papers_by_date[date_key] = all_papers_by_date.get(date_key, 0) + row[1]

            # 3. 引用数分布
            citation_sql = f"""
            SELECT
                multiIf(
                    citation_count = 0, '0',
                    citation_count < 10, '1-9',
                    citation_count < 50, '10-49',
                    citation_count < 100, '50-99',
                    '100+'
                ) as range,
                count() as count
            FROM {table}
            GROUP BY range
            ORDER BY range
            SETTINGS max_threads=1
            """
            citation_result = query_clickhouse(citation_sql)
            if citation_result:
                for row in citation_result.result_rows:
                    all_citations_dist[row[0]] = all_citations_dist.get(row[0], 0) + row[1]

            # 4. Top期刊
            journal_sql = f"""
            SELECT
                journal,
                count() as count
            FROM {table}
            WHERE journal != ''
            GROUP BY journal
            ORDER BY count DESC
            LIMIT 50
            SETTINGS max_threads=1
            """
            journal_result = query_clickhouse(journal_sql)
            if journal_result:
                for row in journal_result.result_rows:
                    all_journals[row[0]] = all_journals.get(row[0], 0) + row[1]

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
            'total_papers': all_stats['total_papers'],
            'unique_authors': all_stats['unique_authors'],
            'unique_journals': total_journals,
            'unique_institutions': all_stats['unique_institutions'],
            'high_citations': all_stats['high_citations'],
            'avg_fwci': round(all_stats['fwci_sum'] / all_stats['fwci_count'], 2) if all_stats['fwci_count'] > 0 and all_stats['fwci_sum'] > 0 else 0
        }

        result['papers_by_date'] = all_papers_by_date
        result['citations_distribution'] = all_citations_dist
        result['top_journals'] = dict(sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50])
        result['top_countries'] = all_countries

        print("✓ 全部数据查询完成")
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
    app.run(**FLASK_CONFIG)