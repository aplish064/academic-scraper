#!/usr/bin/env python3
"""
学术数据看板后端API服务
提供CSV数据的读取和查询接口
"""

import os
import csv
import json
from datetime import datetime
from pathlib import Path
from flask import Flask, jsonify, send_from_directory
from flask_cors import CORS
import pandas as pd

app = Flask(__name__, static_folder='.')
CORS(app)

# 数据目录
DATA_DIR = Path(__file__).parent.parent / 'output' / 'openalex'

# 缓存数据
papers_cache = []
last_cache_time = None
CACHE_DURATION = 300  # 5分钟缓存


def load_papers_data():
    """加载所有CSV数据"""
    global papers_cache, last_cache_time

    # 检查缓存
    if papers_cache and last_cache_time:
        cache_age = (datetime.now() - last_cache_time).total_seconds()
        if cache_age < CACHE_DURATION:
            print(f"使用缓存数据 (缓存时间: {cache_age:.1f}秒)")
            return papers_cache

    print("加载CSV数据...")
    papers = []

    # 遍历所有CSV文件
    csv_files = list(DATA_DIR.rglob('*.csv'))
    total_files = len(csv_files)

    for idx, csv_file in enumerate(csv_files, 1):
        if idx % 100 == 0:
            print(f"进度: {idx}/{total_files} 文件")

        try:
            # 从文件路径提取日期
            path_parts = csv_file.parts
            date_str = None
            for i, part in enumerate(path_parts):
                if part == 'openalex' and i + 3 < len(path_parts):
                    year = path_parts[i + 1]
                    month = path_parts[i + 2]
                    day = path_parts[i + 3].replace('.csv', '')
                    date_str = f"{year}-{month}-{day}"
                    break

            # 读取CSV
            df = pd.read_csv(csv_file, encoding='utf-8-sig')

            for _, row in df.iterrows():
                paper = {
                    'author_id': row.get('author_id', ''),
                    'author': row.get('author', ''),
                    'uid': row.get('uid', ''),
                    'doi': row.get('doi', ''),
                    'title': row.get('title', ''),
                    'rank': row.get('rank', ''),
                    'journal': row.get('journal', ''),
                    'citation_count': int(row.get('citation_count', 0) or 0),
                    'tag': row.get('tag', ''),
                    'state': row.get('state', ''),
                    'institution_name': row.get('institution_name', ''),
                    'institution_country': row.get('institution_country', ''),
                    'institution_type': row.get('institution_type', ''),
                    'fwci': row.get('fwci', ''),
                    'citation_percentile': row.get('citation_percentile', ''),
                    'primary_topic': row.get('primary_topic', ''),
                    'is_retracted': row.get('is_retracted', ''),
                    'date': date_str
                }
                papers.append(paper)

        except Exception as e:
            print(f"读取文件错误 {csv_file}: {e}")
            continue

    papers_cache = papers
    last_cache_time = datetime.now()

    print(f"数据加载完成: 共 {len(papers)} 条记录")
    print(f"缓存时间: {last_cache_time.strftime('%Y-%m-%d %H:%M:%S')}")

    return papers


@app.route('/')
def index():
    """提供主页"""
    return send_from_directory('.', 'index.html')


@app.route('/api/papers')
def get_papers():
    """获取所有论文数据（带分页）"""
    try:
        papers = load_papers_data()

        # 支持分页
        page = int(request.args.get('page', 1))
        per_page = int(request.args.get('per_page', 100))

        start = (page - 1) * per_page
        end = start + per_page

        return jsonify({
            'success': True,
            'papers': papers[start:end],
            'total': len(papers),
            'page': page,
            'per_page': per_page,
            'total_pages': (len(papers) + per_page - 1) // per_page
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/statistics')
def get_statistics():
    """获取统计信息"""
    try:
        papers = load_papers_data()

        total_papers = len(papers)
        unique_authors = len(set(p['author_id'] for p in papers))
        unique_journals = len(set(p['journal'] for p in papers))
        high_citations = len([p for p in papers if p['citation_count'] >= 50])
        unique_institutions = len(set(
            p['institution_name'] for p in papers
            if p['institution_name']
        ))

        # 计算平均FWCI
        fwcis = [float(p['fwci']) for p in papers if p['fwci'] and p['fwci'] != '']
        avg_fwci = sum(fwcis) / len(fwcis) if fwcis else 0

        return jsonify({
            'success': True,
            'statistics': {
                'total_papers': total_papers,
                'unique_authors': unique_authors,
                'unique_journals': unique_journals,
                'high_citations': high_citations,
                'unique_institutions': unique_institutions,
                'avg_fwci': round(avg_fwci, 2)
            }
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/top-papers')
def get_top_papers():
    """获取高被引论文"""
    try:
        papers = load_papers_data()
        limit = int(request.args.get('limit', 10))

        top_papers = sorted(papers, key=lambda x: x['citation_count'], reverse=True)[:limit]

        return jsonify({
            'success': True,
            'papers': top_papers
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@app.route('/api/papers/by-date')
def get_papers_by_date():
    """按日期分组获取论文数量"""
    try:
        papers = load_papers_data()

        # 按日期分组
        papers_by_date = {}
        for paper in papers:
            date = paper.get('date', 'Unknown')
            if date not in papers_by_date:
                papers_by_date[date] = 0
            papers_by_date[date] += 1

        # 排序
        sorted_dates = sorted(papers_by_date.items(), key=lambda x: x[0], reverse=True)

        return jsonify({
            'success': True,
            'data': dict(sorted_dates)
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# 修复导入问题
from flask import request

if __name__ == '__main__':
    print("=" * 60)
    print("📊 学术数据看板后端服务")
    print("=" * 60)
    print(f"数据目录: {DATA_DIR}")
    print(f"服务地址: http://localhost:5000")
    print(f"API文档:")
    print(f"  - GET /api/papers          获取论文列表")
    print(f"  - GET /api/statistics      获取统计信息")
    print(f"  - GET /api/top-papers      获取高被引论文")
    print(f"  - GET /api/papers/by-date  按日期统计")
    print("=" * 60)

    # 预加载数据
    print("\n预加载数据中...")
    load_papers_data()

    print("\n🚀 启动服务...")
    app.run(host='0.0.0.0', port=5000, debug=True)
