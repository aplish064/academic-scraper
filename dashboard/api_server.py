#!/usr/bin/env python3
"""
学术数据看板后端API服务
使用ClickHouse作为数据存储，提供高性能查询
"""

import os
from config import CLICKHOUSE_CONFIG, FLASK_CONFIG, QUERY_CONFIG
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import clickhouse_connect

app = Flask(__name__, static_folder='.')
CORS(app)

# 全局客户端
ch_client = None

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
    print("📊 查询聚合数据...")

    result = {
        'papers_by_date': {},
        'citations_distribution': {},
        'author_types': {},
        'top_journals': {},
        'top_countries': {},
        'institution_types': {},
        'fwci_distribution': {},
        'top_papers': [],
        'statistics': {}
    }

    try:
        # 1. 统计总览
        stats_sql = f"""
        SELECT
            count() as total_papers,
            count(DISTINCT author_id) as unique_authors,
            count(DISTINCT journal) as unique_journals,
            count(DISTINCT institution_name) as unique_institutions,
            countIf(citation_count >= 50) as high_citations,
            avg(fwci) as avg_fwci
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE fwci > 0
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
                'avg_fwci': round(row[5], 2) if row[5] else 0
            }

        # 2. 按日期统计论文数（最近30天）
        date_sql = f"""
        SELECT
            toString(import_date) as date,
            count() as count
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE import_date >= today() - 30
        GROUP BY import_date
        ORDER BY import_date DESC
        """

        date_result = query_clickhouse(date_sql)
        if date_result:
            for row in date_result.result_rows:
                result['papers_by_date'][row[0]] = row[1]

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
        FROM {CLICKHOUSE_CONFIG['table']}
        GROUP BY range
        ORDER BY range
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
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE tag != ''
        GROUP BY tag
        ORDER BY count DESC
        LIMIT 10
        """

        author_result = query_clickhouse(author_sql)
        if author_result:
            for row in author_result.result_rows:
                result['author_types'][row[0]] = row[1]

        # 5. Top期刊
        journal_sql = f"""
        SELECT
            journal,
            count() as count
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE journal != ''
        GROUP BY journal
        ORDER BY count DESC
        LIMIT 10
        """

        journal_result = query_clickhouse(journal_sql)
        if journal_result:
            for row in journal_result.result_rows:
                result['top_journals'][row[0]] = row[1]

        # 6. Top国家
        country_sql = f"""
        SELECT
            institution_country,
            count() as count
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE institution_country != ''
        GROUP BY institution_country
        ORDER BY count DESC
        LIMIT 10
        """

        country_result = query_clickhouse(country_sql)
        if country_result:
            for row in country_result.result_rows:
                result['top_countries'][row[0]] = row[1]

        # 7. 机构类型分布
        inst_type_sql = f"""
        SELECT
            institution_type,
            count() as count
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE institution_type != ''
        GROUP BY institution_type
        ORDER BY count DESC
        """

        inst_type_result = query_clickhouse(inst_type_sql)
        if inst_type_result:
            for row in inst_type_result.result_rows:
                result['institution_types'][row[0]] = row[1]

        # 8. FWCI分布
        fwci_sql = f"""
        SELECT
            multiIf(
                fwci < 1, '<1',
                fwci < 2, '1-2',
                fwci < 5, '2-5',
                '5+'
            ) as range,
            count() as count
        FROM {CLICKHOUSE_CONFIG['table']}
        WHERE fwci > 0
        GROUP BY range
        ORDER BY range
        """

        fwci_result = query_clickhouse(fwci_sql)
        if fwci_result:
            for row in fwci_result.result_rows:
                result['fwci_distribution'][row[0]] = row[1]

        # 9. Top高引用论文
        top_papers_sql = f"""
        SELECT
            title,
            author,
            journal,
            citation_count,
            fwci
        FROM {CLICKHOUSE_CONFIG['table']}
        ORDER BY citation_count DESC
        LIMIT 10
        """

        top_papers_result = query_clickhouse(top_papers_sql)
        if top_papers_result:
            for row in top_papers_result.result_rows:
                result['top_papers'].append({
                    'title': row[0],
                    'author': row[1],
                    'journal': row[2],
                    'citation_count': row[3],
                    'fwci': round(row[4], 2) if row[4] else 0
                })

        print("✓ 查询完成")
        return jsonify(result)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/refresh')
def refresh_data():
    """刷新数据缓存"""
    # ClickHouse不需要缓存，直接返回成功
    return jsonify({'status': 'success', 'message': 'ClickHouse数据实时查询，无需刷新'})

@app.route('/api/health')
def health_check():
    """健康检查"""
    try:
        client = get_ch_client()
        if not client:
            return jsonify({'status': 'error', 'message': 'Cannot connect to ClickHouse'}), 500

        # 测试查询
        result = client.query('SELECT 1')
        return jsonify({
            'status': 'healthy',
            'clickhouse': 'connected',
            'database': CH_DATABASE,
            'table': CH_TABLE
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)}), 500

if __name__ == '__main__':
    print("🚀 启动学术数据看板服务")
    print(f"📡 ClickHouse: {CLICKHOUSE_CONFIG['host']}:{CLICKHOUSE_CONFIG['port']}/{CLICKHOUSE_CONFIG['database']}")
    print(f"📋 数据表: {CLICKHOUSE_CONFIG['table']}")

    # 测试连接
    client = get_ch_client()
    if client:
        try:
            result = client.query(f"SELECT count() as count FROM {CLICKHOUSE_CONFIG['table']}")
            count = result.result_rows[0][0]
            print(f"✓ 连接成功，数据表包含 {count:,} 条记录")
        except Exception as e:
            print(f"⚠️  查询失败: {e}")
    else:
        print("❌ 连接ClickHouse失败")

    print("🌐 服务启动")
    app.run(**FLASK_CONFIG)