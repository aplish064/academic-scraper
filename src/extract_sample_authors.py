#!/usr/bin/env python3
"""
从 CSV 文件中抽取 10 个不同的作者用于测试
"""

import csv
import random
from collections import defaultdict


def extract_sample_authors(input_file: str, output_file: str, num_authors: int = 10):
    """
    抽取指定数量的不同作者

    Args:
        input_file: 输入 CSV 文件
        output_file: 输出 CSV 文件
        num_authors: 需要抽取的作者数量
    """
    # 读取所有行，按作者分组
    authors_papers = defaultdict(list)

    print(f"📂 读取文件: {input_file}")

    with open(input_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            author = row['author']
            authors_papers[author].append(row)

    print(f"📊 总共找到 {len(authors_papers)} 个唯一作者")

    # 随机选择作者
    selected_authors = random.sample(list(authors_papers.keys()), min(num_authors, len(authors_papers)))

    print(f"🎲 随机选择了 {len(selected_authors)} 个作者:")
    for i, author in enumerate(selected_authors, 1):
        papers_count = len(authors_papers[author])
        print(f"  {i}. {author} ({papers_count} 篇论文)")

    # 写入输出文件
    print(f"\n📝 写入文件: {output_file}")

    with open(output_file, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'author', 'uid', 'doi', 'title', 'rank',
            'journal', 'citation_count', 'tag', 'state'
        ], quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for author in selected_authors:
            # 每个作者只选第一篇论文（保持简洁）
            row = authors_papers[author][0]
            writer.writerow(row)

    print(f"✅ 完成！共 {len(selected_authors)} 行")
    print(f"\n📋 选中的作者:")
    for i, author in enumerate(selected_authors, 1):
        row = authors_papers[author][0]
        print(f"  {i}. {author} - {row['title'][:50]}...")


if __name__ == '__main__':
    input_file = '/home/apl064/apl/academic-scraper/output/2026_4_openalex_papers.csv'
    output_file = '/home/apl064/apl/academic-scraper/demo_input.csv'

    extract_sample_authors(input_file, output_file, num_authors=10)
