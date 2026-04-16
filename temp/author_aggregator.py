#!/usr/bin/env python3
"""
作者数据聚合器 - 从 CSV 文件中按 author_id 聚合作者信息
"""

import csv
import os
import json
from collections import defaultdict
from datetime import datetime
from typing import Dict, List, Any

OUTPUT_DIR = "/home/apl064/apl/academic-scraper/output/openalex"


def aggregate_author_data(limit: int = None, max_files: int = None) -> Dict[str, Dict[str, Any]]:
    """
    聚合所有作者的数据

    Args:
        limit: 限制处理的作者数量（用于测试）

    Returns:
        Dict: {author_id: author_info}
    """
    print("📊 开始聚合作主数据...")

    authors = defaultdict(lambda: {
        'author_id': '',
        'author_name': '',
        'papers': [],
        'institutions': [],
        'research_fields': [],
        'collaborators': set(),
        'earliest_paper': None,
        'latest_paper': None,
        'total_papers': 0,
        'unique_dois': set()
    })

    # 查找所有 CSV 文件
    csv_files = []
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for filename in files:
            if filename.endswith('.csv'):
                csv_files.append(os.path.join(root, filename))

    # 按修改时间排序，只取最新的几个文件（用于测试）
    csv_files.sort(key=lambda x: os.path.getmtime(x), reverse=True)
    if max_files:
        csv_files = csv_files[:max_files]

    print(f"   找到 {len(csv_files)} 个 CSV 文件（限制：{max_files if max_files else '全部'}）")

    # 读取数据
    processed_files = 0
    for filepath in csv_files:
        try:
            with open(filepath, 'r', encoding='utf-8-sig') as f:
                reader = csv.DictReader(f)

                for row in reader:
                    author_id = row.get('author_id', '').strip()
                    if not author_id:
                        continue

                    # 基本信息
                    if not authors[author_id]['author_id']:
                        authors[author_id]['author_id'] = author_id
                        authors[author_id]['author_name'] = row.get('author', '')

                    # 论文信息
                    paper_info = {
                        'title': row.get('title', ''),
                        'doi': row.get('doi', ''),
                        'journal': row.get('journal', ''),
                        'year': extract_year_from_filepath(filepath),
                        'citation_count': row.get('citation_count', '0'),
                        'rank': row.get('rank', ''),
                        'tag': row.get('tag', ''),
                        'institution': row.get('institution_name', ''),
                        'raw_affiliation': row.get('raw_affiliation', ''),
                        'primary_topic': row.get('primary_topic', '')
                    }

                    doi = paper_info['doi']
                    if doi and doi not in authors[author_id]['unique_dois']:
                        authors[author_id]['papers'].append(paper_info)
                        authors[author_id]['unique_dois'].add(doi)

                        # 更新最早和最新论文
                        paper_year = paper_info['year']
                        if authors[author_id]['earliest_paper'] is None or paper_year < authors[author_id]['earliest_paper']:
                            authors[author_id]['earliest_paper'] = paper_year
                        if authors[author_id]['latest_paper'] is None or paper_year > authors[author_id]['latest_paper']:
                            authors[author_id]['latest_paper'] = paper_year

                    # 机构信息
                    institution = row.get('institution_name', '').strip()
                    if institution and institution not in authors[author_id]['institutions']:
                        authors[author_id]['institutions'].append(institution)

                    # 研究领域
                    primary_topic = row.get('primary_topic', '').strip()
                    if primary_topic and primary_topic not in authors[author_id]['research_fields']:
                        authors[author_id]['research_fields'].append(primary_topic)

                    # 合作者（从论文标题推断，简化处理）
                    # 实际应该从同一篇论文的其他作者获取

            processed_files += 1
            if processed_files % 100 == 0:
                print(f"   已处理 {processed_files} 个文件...")

        except Exception as e:
            print(f"   ⚠️  处理文件出错 {filepath}: {e}")
            continue

    # 转换为最终格式
    print("   整理数据...")
    result = {}

    for author_id, data in authors.items():
        if not data['papers']:
            continue

        # 排序论文（按时间倒序）
        data['papers'].sort(key=lambda x: x['year'], reverse=True)

        # 获取最新机构
        latest_institution = ''
        for paper in data['papers']:
            if paper['institution']:
                latest_institution = paper['institution']
                break

        # 转换集合为列表
        data['collaborators'] = list(data['collaborators'])
        data['total_papers'] = len(data['papers'])
        del data['unique_dois']  # 删除临时数据

        # 添加最新机构
        data['latest_institution'] = latest_institution

        result[author_id] = data

        if limit and len(result) >= limit:
            break

    print(f"   ✅ 聚合完成：{len(result)} 位作者")
    return result


def extract_year_from_filepath(filepath: str) -> int:
    """从文件路径中提取年份"""
    parts = filepath.split('/')
    for part in parts:
        if part.isdigit() and len(part) == 4:
            return int(part)
    return 2024  # 默认值


def sample_authors(authors: Dict[str, Dict[str, Any]], n: int = 50) -> List[str]:
    """
    抽样 n 个作者用于测试

    优先选择：
    1. 有完整机构信息的
    2. 论文数量适中的（5-50篇）
    3. 有明确研究领域的
    """
    print(f"🎲 抽样 {n} 位作者...")

    # 计算每个作者的得分
    scored_authors = []
    for author_id, data in authors.items():
        score = 0

        # 有机构信息
        if data['latest_institution']:
            score += 10

        # 论文数量适中
        paper_count = data['total_papers']
        if 5 <= paper_count <= 50:
            score += 5
        elif 50 < paper_count <= 100:
            score += 3

        # 有研究领域
        if data['research_fields']:
            score += len(data['research_fields'])

        # 有多个机构（说明有职业变迁）
        if len(data['institutions']) > 1:
            score += 3

        scored_authors.append((author_id, score))

    # 按得分排序，取前 n 个
    scored_authors.sort(key=lambda x: x[1], reverse=True)
    sampled = [author_id for author_id, _ in scored_authors[:n]]

    print(f"   ✅ 抽样完成")
    return sampled


def save_sample_to_csv(authors: Dict[str, Dict[str, Any]], author_ids: List[str], output_path: str):
    """保存抽样数据到 CSV"""
    print(f"💾 保存抽样数据到 {output_path}...")

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'author_id', 'author_name', 'total_papers',
            'earliest_paper', 'latest_paper', 'latest_institution',
            'institutions', 'research_fields', 'paper_sample'
        ])

        for author_id in author_ids:
            if author_id not in authors:
                continue

            data = authors[author_id]

            # 取前 5 篇论文作为样本
            paper_sample = json.dumps(data['papers'][:5], ensure_ascii=False)

            writer.writerow([
                author_id,
                data['author_name'],
                data['total_papers'],
                data['earliest_paper'],
                data['latest_paper'],
                data['latest_institution'],
                json.dumps(data['institutions'], ensure_ascii=False),
                json.dumps(data['research_fields'], ensure_ascii=False),
                paper_sample
            ])

    print(f"   ✅ 保存完成：{len(author_ids)} 位作者")


def main():
    """测试函数"""
    print("=" * 80)
    print("作者数据聚合器")
    print("=" * 80)
    print()

    # 聚合数据（限制处理文件数和作者数用于测试）
    authors = aggregate_author_data(limit=100, max_files=5)

    # 抽样 50 位
    sampled_ids = sample_authors(authors, n=50)

    # 保存到 CSV
    output_path = "/home/apl064/apl/academic-scraper/temp/sample_authors.csv"
    save_sample_to_csv(authors, sampled_ids, output_path)

    print()
    print("=" * 80)
    print("✅ 完成！")
    print(f"📁 抽样数据已保存到: {output_path}")
    print("=" * 80)


if __name__ == '__main__':
    main()
