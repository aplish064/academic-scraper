#!/usr/bin/env python3
"""
ArXiv 批量论文获取
支持多种策略：按分类、按关键词、按时间范围
"""

import requests
import time
import csv
import sys
from typing import List, Dict, Any
from urllib.parse import quote


def show_progress(current: int, total: int, prefix: str = "进度"):
    """显示简单的进度条"""
    percent = int(100 * current / total) if total > 0 else 100
    bar_length = 40
    filled = int(bar_length * current / total) if total > 0 else bar_length
    bar = '█' * filled + '░' * (bar_length - filled)
    sys.stdout.write(f'\r{prefix}: [{bar}] {percent}% ({current}/{total})')
    sys.stdout.flush()
    if current == total:
        print()


ARXIV_API_URL = "http://export.arxiv.org/api/query?"

CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]


def parse_paper_entry(entry, ns: Dict[str, str]) -> Dict[str, Any]:
    """解析单篇论文的 XML 条目"""
    paper_id = entry.find('atom:id', ns).text
    title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')

    authors = []
    author_elems = entry.findall('atom:author', ns)
    for idx, author_elem in enumerate(author_elems):
        name = author_elem.find('atom:name', ns).text
        authors.append({'name': name, 'rank': idx + 1})

    journal = entry.find('arxiv:journal_ref', ns)
    journal = journal.text if journal is not None else 'arXiv'

    doi_elem = entry.find('arxiv:doi', ns)
    doi = doi_elem.text if doi_elem is not None else ''

    categories = []
    for cat in entry.findall('atom:category', ns):
        term = cat.get('term')
        if term:
            categories.append(term)

    return {
        'uid': paper_id,
        'doi': doi,
        'title': title,
        'authors': authors,
        'journal': journal,
        'citation_count': 0,
        'categories': categories,
        'arxiv_id': paper_id.split('/abs/')[-1] if '/abs/' in paper_id else ''
    }


def expand_authors_to_rows(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """将论文展开为作者行"""
    rows = []
    for paper in papers:
        authors = paper['authors']
        total_authors = len(authors)

        for author_info in authors:
            author_name = author_info['name']
            rank = author_info['rank']

            tag = '其他'
            if rank == 1:
                tag = '第一作者'
            elif rank == total_authors:
                tag = '最后作者'

            row = {
                'author': author_name,
                'uid': paper['uid'],
                'doi': paper['doi'],
                'title': paper['title'],
                'rank': rank,
                'journal': paper['journal'],
                'citation_count': paper['citation_count'],
                'tag': tag,
                'state': ''
            }
            rows.append(row)
    return rows


def save_to_csv(rows: List[Dict[str, Any]], filename: str):
    """保存数据到 CSV 文件"""
    with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n✅ 数据已保存到: {filename}")
    print(f"📊 总计 {len(rows)} 行（按作者展开）")


# ============================================================================
# 策略1: 按分类爬取（推荐用于获取大量数据）
# ============================================================================

def fetch_by_category(category: str, max_results: int = 10000):
    """
    按分类爬取

    常见分类：
    - cs.AI (人工智能)
    - cs.LG (机器学习)
    - cs.CV (计算机视觉)
    - cs.CL (计算语言学)
    - stat.ML (统计机器学习)
    - physics.comp-ph (计算物理)
    - q-bio (生物定量)
    """
    print(f"\n📂 按分类爬取: {category}")
    print(f"   目标数量: {max_results} 篇")
    print("=" * 60)

    all_papers = []
    batch_size = 1000  # 每批获取 1000 篇
    start = 0

    while len(all_papers) < max_results:
        current_batch = min(batch_size, max_results - len(all_papers))

        search_query = f'cat:{category}'
        url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start={start}&max_results={current_batch}"

        print(f"\n📡 获取第 {start // batch_size + 1} 批 (第 {start+1}-{start+current_batch} 篇)...")

        try:
            response = requests.get(url, headers={'User-Agent': 'AcademicScraper/1.0'})
            response.raise_for_status()

            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'arxiv': 'http://arxiv.org/schemas/atom'
            }

            entries = root.findall('atom:entry', ns)

            if not entries:
                print("✅ 该分类已无更多数据")
                break

            for entry in entries:
                paper = parse_paper_entry(entry, ns)
                all_papers.append(paper)

            print(f"   当前总计: {len(all_papers)} 篇")

            start += current_batch

            # 避免过快请求
            time.sleep(3)

        except Exception as e:
            print(f"❌ 出错: {e}")
            break

    return all_papers


# ============================================================================
# 策略2: 按多个关键词爬取
# ============================================================================

def fetch_by_keywords(keywords: List[str], max_per_keyword: int = 1000):
    """
    按多个关键词爬取

    示例:
    keywords = ["machine learning", "deep learning", "neural networks"]
    """
    print(f"\n🔑 按关键词爬取: {', '.join(keywords)}")
    print(f"   每个关键词最多: {max_per_keyword} 篇")
    print("=" * 60)

    all_papers = []

    for idx, keyword in enumerate(keywords, 1):
        print(f"\n[{idx}/{len(keywords)}] 搜索关键词: {keyword}")

        search_query = f'all:{keyword}'
        url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start=0&max_results={max_per_keyword}"

        try:
            response = requests.get(url, headers={'User-Agent': 'AcademicScraper/1.0'})
            response.raise_for_status()

            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'arxiv': 'http://arxiv.org/schemas/atom'
            }

            entries = root.findall('atom:entry', ns)

            for entry in entries:
                paper = parse_paper_entry(entry, ns)
                all_papers.append(paper)

            print(f"   ✅ 获取 {len(entries)} 篇")

            time.sleep(2)

        except Exception as e:
            print(f"   ❌ 出错: {e}")

    return all_papers


# ============================================================================
# 策略3: 按时间范围爬取
# ============================================================================

def fetch_by_date_range(category: str, start_year: int, end_year: int):
    """
    按时间范围爬取

    示例:
    category = "cs.AI"
    start_year = 2020
    end_year = 2024
    """
    print(f"\n📅 按时间范围爬取: {category}")
    print(f"   时间范围: {start_year} - {end_year}")
    print("=" * 60)

    all_papers = []

    for year in range(start_year, end_year + 1):
        print(f"\n📆 爬取 {year} 年的论文...")

        # ArXiv 日期格式
        start_date = f"{year}0101"
        end_date = f"{year}1231"

        search_query = f'cat:{category} AND submittedDate:[{start_date} TO {end_date}]'
        url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start=0&max_results=2000"

        try:
            response = requests.get(url, headers={'User-Agent': 'AcademicScraper/1.0'})
            response.raise_for_status()

            import xml.etree.ElementTree as ET
            root = ET.fromstring(response.content)

            ns = {
                'atom': 'http://www.w3.org/2005/Atom',
                'arxiv': 'http://arxiv.org/schemas/atom'
            }

            entries = root.findall('atom:entry', ns)

            for entry in entries:
                paper = parse_paper_entry(entry, ns)
                all_papers.append(paper)

            print(f"   ✅ {year} 年: {len(entries)} 篇")

            time.sleep(3)

        except Exception as e:
            print(f"   ❌ 出错: {e}")

    return all_papers


# ============================================================================
# 主程序
# ============================================================================

def main():
    print("=" * 60)
    print("ArXiv 批量论文获取工具")
    print("=" * 60)

    print("\n请选择爬取策略:")
    print("1. 按分类爬取（推荐用于获取大量数据）")
    print("2. 按多个关键词爬取")
    print("3. 按时间范围爬取")

    choice = input("\n请输入选项 (1/2/3): ").strip()

    papers = []

    if choice == '1':
        # 按分类爬取
        print("\n常见分类:")
        print("- cs.AI (人工智能)")
        print("- cs.LG (机器学习)")
        print("- cs.CV (计算机视觉)")
        print("- cs.CL (计算语言学)")
        print("- stat.ML (统计机器学习)")

        category = input("\n请输入分类 (例如 cs.AI): ").strip()
        max_results = int(input("请输入最大数量 (建议 1000-10000): ").strip())

        papers = fetch_by_category(category, max_results)

    elif choice == '2':
        # 按关键词爬取
        keywords_input = input("\n请输入关键词 (用逗号分隔): ").strip()
        keywords = [k.strip() for k in keywords_input.split(',')]
        max_per_keyword = int(input("每个关键词最大数量 (建议 500-1000): ").strip())

        papers = fetch_by_keywords(keywords, max_per_keyword)

    elif choice == '3':
        # 按时间范围爬取
        category = input("\n请输入分类 (例如 cs.AI): ").strip()
        start_year = int(input("起始年份 (例如 2020): ").strip())
        end_year = int(input("结束年份 (例如 2024): ").strip())

        papers = fetch_by_date_range(category, start_year, end_year)

    else:
        print("❌ 无效选项")
        return

    if not papers:
        print("\n❌ 没有获取到数据")
        return

    print(f"\n✅ 成功获取 {len(papers)} 篇论文")

    # 展开为作者行
    print("\n👥 正在展开作者...")
    rows = expand_authors_to_rows(papers)
    print(f"📊 展开后总行数: {len(rows)} 行")

    # 保存到CSV
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(script_dir, f'../output/arxiv_papers_{timestamp}.csv')
    save_to_csv(rows, output_file)

    print("\n📋 数据预览（前5行）:")
    print("-" * 100)
    for i, row in enumerate(rows[:5], 1):
        print(f"{i}. {row['author'][:30]:<30} | {row['title'][:40]:<40} | Rank: {row['rank']}")


if __name__ == '__main__':
    main()
