#!/usr/bin/env python3
"""
ArXiv 论文数据获取
按月份获取论文信息并按作者展开，每行一个作者
自动处理 API 限制，获取完整数据
"""

import requests
import time
import csv
import sys
from typing import List, Dict, Any, Tuple
from urllib.parse import quote
import os


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


# ArXiv API 基础URL
ARXIV_API_URL = "http://export.arxiv.org/api/query?"

# CSV字段顺序（author在第一列）
CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]


def parse_paper_entry(entry, ns: Dict[str, str]) -> Dict[str, Any]:
    """解析单篇论文的 XML 条目"""
    # 基本信息
    paper_id = entry.find('atom:id', ns).text
    title = entry.find('atom:title', ns).text.strip().replace('\n', ' ')

    # 提取 ArXiv ID
    arxiv_id = paper_id.split('/abs/')[-1] if '/abs/' in paper_id else paper_id

    # 作者信息
    authors = []
    author_elems = entry.findall('atom:author', ns)
    for idx, author_elem in enumerate(author_elems):
        name = author_elem.find('atom:name', ns).text
        authors.append({
            'name': name,
            'rank': idx + 1
        })

    # 期刊/会议信息
    journal = entry.find('arxiv:journal_ref', ns)
    journal = journal.text if journal is not None else 'arXiv'

    # DOI
    doi_elem = entry.find('arxiv:doi', ns)
    doi = doi_elem.text if doi_elem is not None else ''

    # 发布日期
    published = entry.find('atom:published', ns).text

    # 分类
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
        'published': published,
        'arxiv_id': arxiv_id
    }


def expand_authors_to_rows(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    将论文展开为作者行，每行一个作者

    Args:
        papers: 论文列表

    Returns:
        作者行列表
    """
    rows = []
    total_papers = len(papers)

    for idx, paper in enumerate(papers, 1):
        show_progress(idx, total_papers, "  进度")

        authors = paper['authors']
        total_authors = len(authors)

        for author_info in authors:
            author_name = author_info['name']
            rank = author_info['rank']

            # 判断 tag：通讯作者/最后作者/第一作者/其他
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
                'state': ''  # 暂时留空
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

    # 显示文件大小
    file_size = os.path.getsize(filename)
    if file_size < 1024:
        size_str = f"{file_size} B"
    elif file_size < 1024 * 1024:
        size_str = f"{file_size / 1024:.2f} KB"
    else:
        size_str = f"{file_size / (1024 * 1024):.2f} MB"

    print(f"📊 总计 {len(rows)} 行（按作者展开）")
    print(f"📁 文件大小: {size_str}")


def fetch_by_date_range(
    start_date: str, end_date: str,
    category: str = None
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    按日期范围获取论文

    Args:
        start_date: 开始日期 (YYYYMMDD)
        end_date: 结束日期 (YYYYMMDD)
        category: 分类（可选）

    Returns:
        (论文列表, 是否达到限制)
    """
    # 构建搜索查询
    if category:
        search_query = f'cat:{category} AND submittedDate:[{start_date} TO {end_date}]'
    else:
        search_query = f'submittedDate:[{start_date} TO {end_date}]'

    all_papers = []
    batch_size = 1000  # 每批1000篇
    start = 0
    max_retries = 3
    hit_limit = False

    while start < 10000:  # ArXiv API 限制
        url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start={start}&max_results={batch_size}"

        batch_num = start // batch_size + 1

        for retry in range(max_retries):
            try:
                response = requests.get(url, headers={'User-Agent': 'AcademicScraper/1.0'}, timeout=60)
                response.raise_for_status()

                # 解析XML响应
                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)

                # 命名空间
                ns = {
                    'atom': 'http://www.w3.org/2005/Atom',
                    'arxiv': 'http://arxiv.org/schemas/atom'
                }

                entries = root.findall('atom:entry', ns)

                if not entries:
                    return all_papers, False

                # 解析论文
                for entry in entries:
                    paper = parse_paper_entry(entry, ns)
                    all_papers.append(paper)

                print(f"    ✅ 第 {batch_num} 批: {len(entries)} 篇", flush=True)
                start += batch_size

                # 如果获取到的数量少于请求数量，说明已经没有更多数据了
                if len(entries) < batch_size:
                    return all_papers, False

                # 成功获取，跳出重试循环
                break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 500:
                    if retry < max_retries - 1:
                        print(f"    ⚠️  服务器错误，重试 {retry + 1}/{max_retries}...", flush=True)
                        time.sleep(5 * (retry + 1))
                        continue
                    else:
                        print(f"    ⚠️  达到 API 限制，已获取 {len(all_papers)} 篇", flush=True)
                        hit_limit = True
                        return all_papers, hit_limit
                else:
                    print(f"    ❌ HTTP 错误: {e}")
                    return all_papers, False

            except Exception as e:
                print(f"    ❌ 错误: {e}")
                return all_papers, False

        time.sleep(3)

    return all_papers, True  # 达到 10000 限制


def fetch_monthly_complete(year: int, month: int, category: str = None) -> List[Dict[str, Any]]:
    """
    获取指定月份的所有论文（自动处理 API 限制）

    如果单月超过 10000 篇，自动拆分为更小的时间段
    """
    # 先尝试获取整月数据
    start_date = f"{year}{month:02d}01"
    if month == 12:
        end_date = f"{year}1231"
    else:
        end_date = f"{year}{month+1:02d}01"

    print(f"📆 {year}年 {month}月")
    print(f"📅 尝试获取完整月份数据...")

    papers, hit_limit = fetch_by_date_range(start_date, end_date, category)

    # 如果没有达到限制，直接返回
    if not hit_limit:
        print(f"✅ 成功获取 {len(papers)} 篇论文（完整）")
        return papers

    # 如果达到限制，拆分时间段
    print(f"⚠️  该月数据超过 API 限制，正在拆分获取...")

    # 按旬拆分（每月分3段：1-10日，11-20日，21-月底）
    all_papers = []
    splits = get_month_splits(year, month)

    for idx, (split_start, split_end) in enumerate(splits, 1):
        print(f"\n  [{idx}/{len(splits)}] 获取 {split_start} - {split_end}")

        split_papers, _ = fetch_by_date_range(split_start, split_end, category)
        all_papers.extend(split_papers)

        # 如果这一段达到限制，继续拆分
        if len(split_papers) >= 10000:
            print(f"  ⚠️  该段仍有大量数据，建议添加分类过滤")
            break

    print(f"\n✅ 累计获取 {len(all_papers)} 篇论文")
    return all_papers


def get_month_splits(year: int, month: int) -> List[Tuple[str, str]]:
    """
    将月份拆分为更小的时间段（按旬）

    Returns:
        [(start_date, end_date), ...]
    """
    splits = []

    # 上旬：1-10日
    splits.append((f"{year}{month:02d}01", f"{year}{month:02d}10"))

    # 中旬：11-20日
    splits.append((f"{year}{month:02d}11", f"{year}{month:02d}20"))

    # 下旬：21日-月底
    if month in [1, 3, 5, 7, 8, 10, 12]:
        splits.append((f"{year}{month:02d}21", f"{year}{month:02d}31"))
    elif month in [4, 6, 9, 11]:
        splits.append((f"{year}{month:02d}21", f"{year}{month:02d}30"))
    else:  # 2月
        # 判断闰年
        if (year % 400 == 0) or (year % 100 != 0 and year % 4 == 0):
            splits.append((f"{year}{month:02d}21", f"{year}{month:02d}29"))
        else:
            splits.append((f"{year}{month:02d}21", f"{year}{month:02d}28"))

    return splits


def main():
    """主函数"""
    print("=" * 60)
    print("ArXiv 论文获取（按月份）")
    print("=" * 60)
    print()
    print("💡 提示: 程序会自动获取每月所有论文")
    print("   如果某月超过 10000 篇，会自动拆分为上/中/下旬")
    print()

    # 获取用户输入
    try:
        year_input = input("请输入年份 (例如 2024): ").strip()
        year = int(year_input)

        if year < 1991:
            print("⚠️  ArXiv 成立于 1991 年，最早的论文从那时开始")
            year = 1991
        elif year > 2025:
            print("⚠️  年份不能超过当前年份")
            year = 2024

        print()
        category_input = input("请输入分类 (留空则获取所有分类，强烈建议添加分类如 cs.AI): ").strip()
        category = category_input if category_input else None

        print()
        months_input = input("请输入月份 (1-12，用逗号分隔，留空则获取全年): ").strip()
        if months_input:
            months = [int(m.strip()) for m in months_input.split(',')]
        else:
            months = list(range(1, 13))

    except ValueError:
        print("❌ 输入无效，请输入有效的数字")
        return
    except KeyboardInterrupt:
        print("\n\n👋 用户取消")
        return

    print()
    print("=" * 60)
    print(f"开始获取 {year} 年数据")
    print(f"月份: {', '.join(map(str, months))}")
    if category:
        print(f"分类: {category}")
        print("✅ 添加分类可以避免 API 限制，获取完整数据")
    else:
        print("⚠️  未添加分类，热门月份可能无法获取完整数据")
    print("=" * 60)
    print()

    # 准备输出目录
    script_dir = os.path.dirname(os.path.abspath(__file__))
    output_dir = os.path.join(script_dir, '../output')
    os.makedirs(output_dir, exist_ok=True)

    # 按月份获取
    all_papers = []

    for idx, month in enumerate(months, 1):
        print(f"\n{'='*60}")
        print(f"[{idx}/{len(months)}] ", end="")

        # 获取该月数据
        papers = fetch_monthly_complete(year, month, category)
        all_papers.extend(papers)

        # 展开为作者行并保存
        if papers:
            print(f"👥 展开作者...")
            rows = expand_authors_to_rows(papers)

            # 保存该月数据
            output_file = os.path.join(output_dir, f'{year}_{month:02d}_arxiv_papers.csv')
            save_to_csv(rows, output_file)

        # 月份之间稍作延迟
        if month != months[-1]:
            print(f"⏳ 等待 3 秒...")
            time.sleep(3)

    # 总结
    print()
    print("=" * 60)
    print(f"🎉 全部完成！")
    print(f"📊 总计获取 {len(all_papers)} 篇论文")
    print(f"📁 文件保存在: {output_dir}")
    print(f"📂 文件列表:")
    for month in months:
        filename = f'{year}_{month:02d}_arxiv_papers.csv'
        filepath = os.path.join(output_dir, filename)
        if os.path.exists(filepath):
            size = os.path.getsize(filepath)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            print(f"   - {filename} ({size_str})")
    print("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 用户取消")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
