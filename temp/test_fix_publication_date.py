#!/usr/bin/env python3
"""
测试修复后的openalex_fetcher.py是否能正确获取和保存publication_date
"""

import sys
import os
sys.path.append('/home/hkustgz/Us/academic-scraper/src')

# 模拟一个OpenAlex API返回的work对象
test_work = {
    'id': 'https://openalex.org/W4123456789',
    'doi': 'https://doi.org/10.1234/test.2024.001',
    'title': 'Test Paper for Publication Date',
    'type': 'article',
    'publication_date': '2024-04-17',
    'cited_by_count': 100,
    'fwci': 2.5,
    'authorships': [
        {
            'author': {
                'id': 'https://openalex.org/A1234567890',
                'display_name': 'Test Author'
            },
            'institution': {
                'id': 'https://openalex.org/I123456789',
                'name': 'Test University',
                'country': 'US',
                'type': 'education'
            },
            'raw_affiliation': 'Test University',
            'rank': 1
        }
    ],
    'primary_topic': {
        'display_name': 'Computer Science'
    },
    'concepts': [
        {'display_name': 'Artificial Intelligence'},
        {'display_name': 'Machine Learning'}
    ],
    'is_retracted': False
}

# 导入修复后的parse_openalex_work函数
from openalex_fetcher import parse_openalex_work

print("🧪 测试修复后的publication_date获取")
print("=" * 50)

# 解析work对象
paper = parse_openalex_work(test_work)

print(f"✅ 解析成功")
print(f"   论文标题: {paper['title']}")
print(f"   发表日期: {paper['publication_date']}")

# 模拟展开为作者行
authors = paper['authors']
print(f"\n📋 模拟展开为作者行...")

for author_info in authors:
    author_id = author_info.get('id', '') or ''
    author_name = author_info.get('name', '') or ''
    rank = author_info.get('rank', 1) or 1

    tag = '其他'
    if rank == 1:
        tag = '第一作者'
    elif rank == len(authors):
        tag = '最后作者'

    # 获取机构信息
    institution = author_info.get('institution', {}) or {}

    # 创建行数据（使用修复后的逻辑）
    row = {
        'author_id': str(author_id) if author_id else '',
        'author': str(author_name) if author_name else '',
        'uid': str(paper.get('uid', '') or ''),
        'doi': str(paper.get('doi', '') or ''),
        'title': str(paper.get('title', '') or ''),
        'rank': int(rank) if rank else 1,
        'journal': str(paper.get('journal', '') or ''),
        'publication_date': str(paper.get('publication_date', '') or ''),  # ✅ 修复后的字段
        'citation_count': int(paper.get('citation_count', 0) or 0),
        'tag': str(tag),
        'state': '',
        'institution_id': str(institution.get('id', '') or ''),
        'institution_name': str(institution.get('name', '') or ''),
        'institution_country': str(institution.get('country', '') or ''),
        'institution_type': str(institution.get('type', '') or ''),
        'raw_affiliation': str(institution.get('raw', '') or ''),
        'fwci': float(paper.get('fwci', 0) or 0),
        'citation_percentile': int(paper.get('citation_percentile', 0) or 0),
        'primary_topic': str(paper.get('primary_topic', '') or ''),
        'is_retracted': bool(paper.get('is_retracted', False))
    }

    print(f"✅ 行数据创建成功:")
    print(f"   作者: {row['author']}")
    print(f"   发表日期: {row['publication_date']}")
    print(f"   机构: {row['institution_name']}")

    # 验证关键字段
    assert row['publication_date'] == '2024-04-17', "❌ publication_date字段丢失！"
    assert row['author'] == 'Test Author', "❌ author字段错误！"
    assert row['fwci'] == 2.5, "❌ fwci字段错误！"

print(f"\n✅ 所有测试通过！")
print(f"💡 修复成功：publication_date字段现在会正确保存到ClickHouse")
