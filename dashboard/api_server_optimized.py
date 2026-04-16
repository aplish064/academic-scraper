#!/usr/bin/env python3
"""
学术数据看板后端API服务（内存优化版）
后端聚合数据，只发送统计结果到前端
"""

import os
import csv
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import pandas as pd

app = Flask(__name__, static_folder='.')
CORS(app)

# 数据目录
DATA_DIR = Path(__file__).parent.parent / 'output' / 'openalex'

# 配置
MAX_FILES = 10  # 加载10个文件

# 全局缓存
aggregated_data = None
last_cache_time = None
CACHE_DURATION = 600  # 10分钟缓存
data_loading = False  # 数据加载状态标志


def aggregate_data():
    """聚合数据，只保留统计信息"""
    global aggregated_data, last_cache_time

    # 检查缓存
    if aggregated_data and last_cache_time:
        cache_age = (datetime.now() - last_cache_time).total_seconds()
        if cache_age < CACHE_DURATION:
            print(f"✓ 使用缓存数据 (缓存时间: {cache_age:.1f}秒)")
            return aggregated_data

    print("📊 开始聚合数据...")
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

    # 用于按作者ID去重的统计
    unique_authors_by_country = {}  # {country: set(author_ids)}

    # 获取CSV文件
    csv_files = list(DATA_DIR.rglob('*.csv'))
    csv_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)
    csv_files = csv_files[:MAX_FILES]

    print(f"📁 处理 {len(csv_files)} 个文件")

    all_papers_for_stats = []

    for idx, csv_file in enumerate(csv_files, 1):
        if idx % 5 == 0:
            print(f"  进度: {idx}/{len(csv_files)}")

        try:
            # 提取日期
            path_parts = csv_file.parts
            date_str = None
            for i, part in enumerate(path_parts):
                if part == 'openalex' and i + 3 < len(path_parts):
                    # 直接使用文件名中的日期，避免重复
                    date_str = path_parts[i + 3].replace('.csv', '')
                    break

            # 读取CSV
            try:
                df = pd.read_csv(csv_file, encoding='utf-8-sig', low_memory=False)
            except:
                continue

            # 统计每日论文数
            if date_str:
                result['papers_by_date'][date_str] = len(df)

            # 处理每篇论文
            for _, row in df.iterrows():
                citation_count = int(row.get('citation_count', 0) or 0)
                author_id = str(row.get('author_id', ''))
                tag = str(row.get('tag', ''))
                journal = str(row.get('journal', ''))
                country = str(row.get('institution_country', ''))
                inst_type = str(row.get('institution_type', ''))
                fwci_str = str(row.get('fwci', ''))

                # 引用分布
                if citation_count == 0:
                    result['citations_distribution']['0'] = result['citations_distribution'].get('0', 0) + 1
                elif citation_count <= 10:
                    result['citations_distribution']['1-10'] = result['citations_distribution'].get('1-10', 0) + 1
                elif citation_count <= 50:
                    result['citations_distribution']['11-50'] = result['citations_distribution'].get('11-50', 0) + 1
                elif citation_count <= 100:
                    result['citations_distribution']['51-100'] = result['citations_distribution'].get('51-100', 0) + 1
                else:
                    result['citations_distribution']['100+'] = result['citations_distribution'].get('100+', 0) + 1

                # 作者类型
                if tag:
                    result['author_types'][tag] = result['author_types'].get(tag, 0) + 1

                # 期刊分布
                if journal and journal != 'nan':
                    result['top_journals'][journal] = result['top_journals'].get(journal, 0) + 1

                # 国家分布（按作者去重）
                if country and country != 'nan' and author_id and author_id != 'nan':
                    if country not in unique_authors_by_country:
                        unique_authors_by_country[country] = set()
                    unique_authors_by_country[country].add(author_id)

                # 机构类型
                if inst_type and inst_type != 'nan':
                    result['institution_types'][inst_type] = result['institution_types'].get(inst_type, 0) + 1

                # FWCI分布
                try:
                    if fwci_str and fwci_str != 'nan':
                        fwci = float(fwci_str)
                        if fwci < 1:
                            result['fwci_distribution']['0-1'] = result['fwci_distribution'].get('0-1', 0) + 1
                        elif fwci < 2:
                            result['fwci_distribution']['1-2'] = result['fwci_distribution'].get('1-2', 0) + 1
                        elif fwci < 5:
                            result['fwci_distribution']['2-5'] = result['fwci_distribution'].get('2-5', 0) + 1
                        elif fwci < 10:
                            result['fwci_distribution']['5-10'] = result['fwci_distribution'].get('5-10', 0) + 1
                        elif fwci < 20:
                            result['fwci_distribution']['10-20'] = result['fwci_distribution'].get('10-20', 0) + 1
                        else:
                            result['fwci_distribution']['20+'] = result['fwci_distribution'].get('20+', 0) + 1
                except (ValueError, TypeError):
                    pass

                # 收集top论文（按标题去重，只保留第一作者）
                if len(result['top_papers']) < 100:
                    paper_title = str(row.get('title', ''))
                    # 检查是否已有相同标题的论文
                    existing_paper = next((p for p in result['top_papers'] if p['title'] == paper_title), None)
                    if not existing_paper:
                        result['top_papers'].append({
                            'title': paper_title,
                            'author': str(row.get('author', '')),
                            'journal': journal,
                            'citation_count': citation_count,
                            'fwci': fwci_str,
                            'doi': str(row.get('doi', ''))
                        })

                # 统计数据
                all_papers_for_stats.append({
                    'author_id': str(row.get('author_id', '')),
                    'journal': journal,
                    'institution_name': str(row.get('institution_name', '')),
                    'citation_count': citation_count,
                    'fwci': fwci_str,
                    'tag': tag
                })

        except Exception as e:
            print(f"  ⚠️  跳过文件: {e}")
            continue

    # 计算国家分布（按作者去重）
    result['top_countries'] = {country: len(authors) for country, authors in unique_authors_by_country.items()}

    # 计算最终统计
    total_papers = len(all_papers_for_stats)
    unique_authors = len(set(p['author_id'] for p in all_papers_for_stats if p['author_id']))
    unique_journals = len(set(p['journal'] for p in all_papers_for_stats if p['journal'] and p['journal'] != 'nan'))
    unique_institutions = len(set(p['institution_name'] for p in all_papers_for_stats if p['institution_name'] and p['institution_name'] != 'nan'))
    high_citations = len([p for p in all_papers_for_stats if p['citation_count'] >= 50])

    fwcis = []
    for p in all_papers_for_stats:
        try:
            if p['fwci'] and p['fwci'] != 'nan':
                fwcis.append(float(p['fwci']))
        except:
            pass
    avg_fwci = sum(fwcis) / len(fwcis) if fwcis else 0

    result['statistics'] = {
        'total_papers': total_papers,
        'unique_authors': unique_authors,
        'unique_journals': unique_journals,
        'unique_institutions': unique_institutions,
        'high_citations': high_citations,
        'avg_fwci': round(avg_fwci, 2)
    }

    # 期刊和国家按数量排序并限制数量
    result['top_journals'] = dict(sorted(result['top_journals'].items(), key=lambda x: x[1], reverse=True)[:50])
    result['top_countries'] = dict(sorted(result['top_countries'].items(), key=lambda x: x[1], reverse=True)[:15])

    # Top论文按引用排序
    result['top_papers'] = sorted(result['top_papers'], key=lambda x: x['citation_count'], reverse=True)[:20]

    aggregated_data = result
    last_cache_time = datetime.now()

    print(f"✅ 数据聚合完成: {total_papers:,} 条记录")
    print(f"🕒 缓存时间: {last_cache_time.strftime('%Y-%m-%d %H:%M:%S')}")

    return aggregated_data


@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:filename>')
def serve_static(filename):
    """提供静态文件"""
    return send_from_directory('.', filename)


@app.route('/api/aggregated')
def get_aggregated_data():
    """获取聚合数据"""
    try:
        data = aggregate_data()
        return jsonify({
            'success': True,
            'data': data,
            'max_files': MAX_FILES
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/refresh')
def refresh_data():
    """刷新数据"""
    global aggregated_data, last_cache_time
    aggregated_data = None
    last_cache_time = None
    return get_aggregated_data()


if __name__ == '__main__':
    print("=" * 70)
    print("📊 学术数据看板后端服务（内存优化版）")
    print("=" * 70)
    print(f"📁 数据目录: {DATA_DIR}")
    print(f"🔧 加载文件数: {MAX_FILES}")
    print(f"🌐 服务地址: http://localhost:5000")
    print("")
    print("💡 特点:")
    print("  - 后端聚合数据，内存占用低")
    print("  - 只发送统计结果到前端")
    print("  - 10分钟数据缓存")
    print("=" * 70)

    # 不预加载数据，改为懒加载模式
    print("\n📊 使用懒加载模式（首次请求时加载数据）")
    print("🚀 启动服务...")
    app.run(host='0.0.0.0', port=5000, debug=False)
