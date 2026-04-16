#!/usr/bin/env python3
"""
学术数据看板后端API服务（优化版）
支持增量加载和更好的性能
"""

import os
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path
from flask import Flask, jsonify, send_from_directory, request
from flask_cors import CORS
import pandas as pd

app = Flask(__name__, static_folder='.')
CORS(app)

# 数据目录
DATA_DIR = Path(__file__).parent.parent / 'output' / 'openalex'

# 配置
SAMPLE_MODE = True  # 示例模式：只加载最近的部分数据
MAX_FILES = 50      # 加载50个最新文件（约50万条记录，内存友好）
CACHE_DURATION = 300  # 5分钟缓存

# 缓存数据
papers_cache = []
last_cache_time = None


def get_recent_csv_files(limit=50):
    """获取最近的CSV文件"""
    csv_files = list(DATA_DIR.rglob('*.csv'))

    # 按修改时间排序，获取最新的文件
    csv_files.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    if SAMPLE_MODE:
        csv_files = csv_files[:limit]

    return csv_files


def load_papers_data():
    """加载CSV数据"""
    global papers_cache, last_cache_time

    # 检查缓存
    if papers_cache and last_cache_time:
        cache_age = (datetime.now() - last_cache_time).total_seconds()
        if cache_age < CACHE_DURATION:
            print(f"✓ 使用缓存数据 (缓存时间: {cache_age:.1f}秒)")
            return papers_cache

    print("📊 加载CSV数据...")
    papers = []

    # 获取CSV文件
    csv_files = get_recent_csv_files(MAX_FILES)
    total_files = len(csv_files)

    print(f"📁 找到 {total_files} 个文件")

    for idx, csv_file in enumerate(csv_files, 1):
        if idx % 10 == 0:
            print(f"  进度: {idx}/{total_files}")

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

            # 读取CSV（只读取需要的列以提高性能）
            usecols = ['author_id', 'author', 'uid', 'doi', 'title', 'rank',
                      'journal', 'citation_count', 'tag', 'state', 'institution_name',
                      'institution_country', 'institution_type', 'fwci',
                      'citation_percentile', 'primary_topic', 'is_retracted']

            df = pd.read_csv(csv_file, encoding='utf-8-sig', usecols=usecols, low_memory=False)

            for _, row in df.iterrows():
                paper = {
                    'author_id': str(row.get('author_id', '')),
                    'author': str(row.get('author', '')),
                    'uid': str(row.get('uid', '')),
                    'doi': str(row.get('doi', '')),
                    'title': str(row.get('title', '')),
                    'rank': str(row.get('rank', '')),
                    'journal': str(row.get('journal', '')),
                    'citation_count': int(row.get('citation_count', 0) or 0),
                    'tag': str(row.get('tag', '')),
                    'state': str(row.get('state', '')),
                    'institution_name': str(row.get('institution_name', '')),
                    'institution_country': str(row.get('institution_country', '')),
                    'institution_type': str(row.get('institution_type', '')),
                    'fwci': str(row.get('fwci', '')),
                    'citation_percentile': str(row.get('citation_percentile', '')),
                    'primary_topic': str(row.get('primary_topic', '')),
                    'is_retracted': str(row.get('is_retracted', '')),
                    'date': date_str or ''
                }
                papers.append(paper)

        except Exception as e:
            print(f"  ⚠️  跳过文件 {csv_file.name}: {e}")
            continue

    papers_cache = papers
    last_cache_time = datetime.now()

    print(f"✅ 数据加载完成: 共 {len(papers):,} 条记录")
    print(f"🕒 缓存时间: {last_cache_time.strftime('%Y-%m-%d %H:%M:%S')}")

    return papers


@app.route('/')
def index():
    """提供主页"""
    return send_from_directory('.', 'index.html')


@app.route('/api/papers')
def get_papers():
    """获取所有论文数据"""
    try:
        papers = load_papers_data()

        # 前端获取全部数据用于分析
        return_all = request.args.get('all', 'false').lower() == 'true'

        if return_all:
            return jsonify({
                'success': True,
                'papers': papers,
                'total': len(papers),
                'sample_mode': SAMPLE_MODE
            })

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
            'total_pages': (len(papers) + per_page - 1) // per_page,
            'sample_mode': SAMPLE_MODE
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
        unique_authors = len(set(p['author_id'] for p in papers if p['author_id']))
        unique_journals = len(set(p['journal'] for p in papers if p['journal']))
        high_citations = len([p for p in papers if p['citation_count'] >= 50])
        unique_institutions = len(set(
            p['institution_name'] for p in papers
            if p['institution_name'] and p['institution_name'] != 'nan'
        ))

        # 计算平均FWCI
        fwcis = []
        for p in papers:
            try:
                if p['fwci'] and p['fwci'] != '' and p['fwci'] != 'nan':
                    fwcis.append(float(p['fwci']))
            except (ValueError, TypeError):
                continue

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
            },
            'sample_mode': SAMPLE_MODE
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
            if date and date != 'nan':
                if date not in papers_by_date:
                    papers_by_date[date] = 0
                papers_by_date[date] += 1

        # 排序（最新的在前）
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


@app.route('/api/config')
def get_config():
    """获取配置信息"""
    return jsonify({
        'sample_mode': SAMPLE_MODE,
        'max_files': MAX_FILES,
        'cache_duration': CACHE_DURATION
    })


if __name__ == '__main__':
    print("=" * 70)
    print("📊 学术数据看板后端服务 (优化版)")
    print("=" * 70)
    print(f"📁 数据目录: {DATA_DIR}")
    print(f"🔧 模式: {'示例模式 (仅加载最近' + str(MAX_FILES) + '个文件)' if SAMPLE_MODE else '完整模式'}")
    print(f"🌐 服务地址: http://localhost:5000")
    print("")
    print("📚 API接口:")
    print(f"  - GET /                    主页")
    print(f"  - GET /api/papers          获取论文列表")
    print(f"  - GET /api/statistics      获取统计信息")
    print(f"  - GET /api/top-papers      获取高被引论文")
    print(f"  - GET /api/papers/by-date  按日期统计")
    print(f"  - GET /api/config          获取配置信息")
    print("=" * 70)

    # 预加载数据
    print("\n🔄 预加载数据中...")
    try:
        load_papers_data()
        print("✅ 数据预加载完成\n")
    except Exception as e:
        print(f"⚠️  数据预加载失败: {e}\n")
        print("📊 服务将在首次请求时加载数据\n")

    print("🚀 启动服务...")
    print("💡 提示: 按 Ctrl+C 停止服务\n")

    app.run(host='0.0.0.0', port=5000, debug=True)
