#!/usr/bin/env python3
"""
ArXiv 论文自动获取工具
- 自动获取 2010-2026 年论文
- 按天获取，支持断点续传
- 智能重试，自动处理 API 限制
- 进度记录，随时可中断继续
"""

import requests
import time
import csv
import sys
import json
import os
from typing import List, Dict, Any, Optional
from urllib.parse import quote
from datetime import datetime, timedelta


# ArXiv API 基础URL
ARXIV_API_URL = "http://export.arxiv.org/api/query?"

# CSV字段
CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]

# 进度文件
PROGRESS_FILE = "fetch_progress.json"

# 配置
START_DATE = "20260410"  # 从这个日期开始往前获取
END_YEAR = 2010          # 往前获取到这一年


def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        'current_date': None,
        'completed_dates': [],
        'last_update': None
    }


def save_progress(progress: Dict[str, Any]):
    """保存进度文件"""
    progress['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def parse_paper_entry(entry, ns: Dict[str, str]) -> Dict[str, Any]:
    """解析单篇论文"""
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
        'categories': categories
    }


def expand_authors_to_rows(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """展开为作者行"""
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

            rows.append({
                'author': author_name,
                'uid': paper['uid'],
                'doi': paper['doi'],
                'title': paper['title'],
                'rank': rank,
                'journal': paper['journal'],
                'citation_count': paper['citation_count'],
                'tag': tag,
                'state': ''
            })
    return rows


def append_to_csv(rows: List[Dict[str, Any]], filepath: str):
    """追加数据到CSV文件"""
    file_exists = os.path.exists(filepath)

    with open(filepath, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def fetch_date_papers(date_str: str, category: str = None) -> List[Dict[str, Any]]:
    """
    获取指定日期的论文

    Args:
        date_str: 日期字符串 (YYYYMMDD)
        category: 分类（可选）

    Returns:
        论文列表
    """
    if category:
        search_query = f'cat:{category} AND submittedDate:{date_str}'
    else:
        search_query = f'submittedDate:{date_str}'

    all_papers = []
    batch_size = 1000
    start = 0
    max_retries = 5  # 增加重试次数
    base_delay = 5   # 基础延迟时间（秒）

    while start < 10000:
        url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start={start}&max_results={batch_size}"

        for retry in range(max_retries):
            try:
                response = requests.get(
                    url,
                    headers={'User-Agent': 'AcademicScraper/1.0'},
                    timeout=60
                )
                response.raise_for_status()

                import xml.etree.ElementTree as ET
                root = ET.fromstring(response.content)

                ns = {
                    'atom': 'http://www.w3.org/2005/Atom',
                    'arxiv': 'http://arxiv.org/schemas/atom'
                }

                entries = root.findall('atom:entry', ns)

                if not entries:
                    return all_papers

                for entry in entries:
                    paper = parse_paper_entry(entry, ns)
                    all_papers.append(paper)

                start += batch_size

                if len(entries) < batch_size:
                    return all_papers

                # 成功获取，跳出重试循环
                break

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 500:
                    if retry < max_retries - 1:
                        # 指数退避策略
                        delay = base_delay * (2 ** retry)
                        print(f"    ⚠️  API限制，等待 {delay} 秒后重试 ({retry+1}/{max_retries})...", flush=True)
                        time.sleep(delay)
                        continue
                    else:
                        print(f"    ❌ 达到最大重试次数，已获取 {len(all_papers)} 篇", flush=True)
                        return all_papers
                else:
                    print(f"    ❌ HTTP错误: {e}", flush=True)
                    return all_papers

            except requests.exceptions.Timeout:
                if retry < max_retries - 1:
                    delay = base_delay * (2 ** retry)
                    print(f"    ⚠️  超时，等待 {delay} 秒后重试...", flush=True)
                    time.sleep(delay)
                    continue
                else:
                    print(f"    ❌ 超时，已重试 {max_retries} 次", flush=True)
                    return all_papers

            except Exception as e:
                print(f"    ❌ 错误: {e}", flush=True)
                return all_papers

        time.sleep(3)  # 正常请求间隔

    return all_papers


def get_all_dates_backward() -> List[str]:
    """获取从START_DATE往前到END_YEAR的所有日期（倒序）"""
    dates = []
    start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')
    end_date_obj = datetime(END_YEAR, 12, 31)

    current = start_date_obj
    while current >= end_date_obj:
        dates.append(current.strftime('%Y%m%d'))
        current -= timedelta(days=1)

    return dates


def get_csv_filename(year: int) -> str:
    """获取CSV文件名（按年份组织）"""
    output_dir = '/home/apl064/apl/academic-scraper/output'
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f'{year}_arxiv_papers.csv')


def main():
    """主函数"""
    print("=" * 60)
    print("ArXiv 论文自动获取工具")
    print("=" * 60)
    print()

    # 创建输出目录
    output_dir = '/home/apl064/apl/academic-scraper/output'
    os.makedirs(output_dir, exist_ok=True)

    # 加载进度
    progress = load_progress()

    if progress['current_date']:
        print(f"📂 检测到进度文件，从 {progress['current_date']} 继续")
        print(f"   已完成: {len(progress['completed_dates'])} 天")
        print()
    else:
        print("📂 开始新的获取任务")
        print()

    # 确定起始日期
    start_date_obj = None
    if progress['current_date']:
        # 从上次的位置继续（往前）
        start_date_obj = datetime.strptime(progress['current_date'], '%Y%m%d')
        # 移动到前一天（往前）
        start_date_obj -= timedelta(days=1)
    else:
        # 从开始日期获取
        start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')

    # 生成所有待获取日期（倒序）
    all_dates = []
    current = start_date_obj
    end_date_obj = datetime(END_YEAR, 12, 31)

    while current >= end_date_obj:
        all_dates.append(current.strftime('%Y%m%d'))
        current -= timedelta(days=1)

    print(f"📅 待获取日期范围: {START_DATE} → {END_YEAR}1231（往前）")
    print(f"📊 共 {len(all_dates)} 天")
    print()
    print("=" * 60)
    print()

    # 统计
    total_papers = 0
    total_rows = 0
    success_count = 0
    skip_count = 0

    # 遍历每个日期
    for idx, date_str in enumerate(all_dates, 1):
        date_obj = datetime.strptime(date_str, '%Y%m%d')
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        # 检查是否已完成
        if date_str in progress['completed_dates']:
            skip_count += 1
            continue

        print(f"[{idx}/{len(all_dates)}] {year}年{month}月{day}日 ({date_str})", flush=True)

        # 获取该日数据
        papers = fetch_date_papers(date_str)

        if papers:
            # 展开为作者行
            rows = expand_authors_to_rows(papers)

            # 追加到CSV
            csv_file = get_csv_filename(year)
            append_to_csv(rows, csv_file)

            total_papers += len(papers)
            total_rows += len(rows)
            success_count += 1

            print(f"    ✅ {len(papers)} 篇论文, {len(rows)} 行 → {csv_file}", flush=True)
        else:
            print(f"    ℹ️  无数据", flush=True)

        # 更新进度
        progress['current_date'] = date_str
        progress['completed_dates'].append(date_str)

        # 每10天保存一次进度
        if len(progress['completed_dates']) % 10 == 0:
            save_progress(progress)
            print(f"    💾 进度已保存", flush=True)

        print()

        # 避免过快请求
        time.sleep(2)

    # 最终保存进度
    save_progress(progress)

    # 总结
    print("=" * 60)
    print("🎉 获取完成！")
    print(f"📊 统计:")
    print(f"   - 成功: {success_count} 天")
    print(f"   - 跳过: {skip_count} 天（已完成）")
    print(f"   - 论文: {total_papers} 篇")
    print(f"   - 行数: {total_rows} 行")
    print(f"📁 数据文件: output/")
    print("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("💾 进度已保存，下次运行将从中断处继续")
        save_progress(load_progress())
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
