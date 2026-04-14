#!/usr/bin/env python3
"""
ArXiv 论文自动获取工具 - 极速版（按天）
- 异步IO + HTTP/2
- 按天获取，按月写入CSV
- 并发请求
- 预计速度提升 20-50 倍
"""

import asyncio
import httpx
import time
import csv
import sys
import json
import os
from typing import List, Dict, Any
from datetime import datetime, timedelta
from tqdm.asyncio import tqdm
from urllib.parse import quote
import xml.etree.ElementTree as ET


# ArXiv API 基础URL
ARXIV_API_URL = "https://export.arxiv.org/api/query?"

# CSV字段
CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]

# 日志目录和文件
LOG_DIR = "/home/apl064/apl/academic-scraper/log"
LOG_FILE = os.path.join(LOG_DIR, "arxiv_fetch_fast.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "arxiv_fetch_progress.json")

# 配置
START_DATE = "20240413"  # 从这个日期开始往前获取（使用过去的日期）
END_YEAR = 2024          # 往前获取到这一年
CATEGORY = None          # 分类过滤，如 "cs.AI", "cs.CV" 等，None 表示所有分类

# 并发配置
MAX_CONCURRENT_REQUESTS = 1  # ArXiv API 限制非常严格，使用串行请求
REQUEST_TIMEOUT = 60.0
MAX_RETRIES = 3


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
    os.makedirs(os.path.dirname(PROGRESS_FILE), exist_ok=True)
    progress['last_update'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


def setup_logging():
    """设置日志"""
    os.makedirs(LOG_DIR, exist_ok=True)

    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"开始时间: {timestamp}\n"
    log_message += f"获取范围: {START_DATE} → {END_YEAR}（按天获取）\n"
    if CATEGORY:
        log_message += f"分类过滤: {CATEGORY}\n"
    log_message += f"并发数: {MAX_CONCURRENT_REQUESTS}\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_fetch_result(date_str: str, paper_count: int, row_count: int, csv_file: str):
    """记录每次获取结果到日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] {date_str} | 论文: {paper_count} | 行: {row_count} | 文件: {csv_file}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_completion(total_papers: int, total_rows: int, success_count: int, skip_count: int, elapsed_time: float):
    """记录完成状态"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"完成时间: {timestamp}\n"
    log_message += f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_time/3600:.2f} 小时)\n"
    log_message += f"成功: {success_count} 天\n"
    log_message += f"跳过: {skip_count} 天\n"
    log_message += f"总论文: {total_papers} 篇\n"
    log_message += f"总行数: {total_rows} 行\n"
    log_message += f"平均速度: {total_papers/elapsed_time:.1f} 篇/秒\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


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
    """追加数据到CSV文件（线程安全）"""
    file_exists = os.path.exists(filepath)

    with open(filepath, 'a', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, quoting=csv.QUOTE_ALL)
        if not file_exists:
            writer.writeheader()
        writer.writerows(rows)


def get_csv_filename(year: int, month: int) -> str:
    """获取CSV文件名（按月份组织）"""
    output_dir = '/home/apl064/apl/academic-scraper/output/arxiv'
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f'{year}_{month:02d}.csv')


async def fetch_arxiv_day(
    client: httpx.AsyncClient,
    date_str: str,
    semaphore: asyncio.Semaphore,
    day_pbar: tqdm,
    paper_pbar: tqdm,
    progress: Dict[str, Any],
    progress_lock: asyncio.Lock
) -> Dict[str, Any]:
    """
    异步获取指定日期的所有论文

    Args:
        client: httpx 异步客户端
        date_str: 日期字符串 (YYYY-MM-DD)
        semaphore: 信号量（控制并发）
        day_pbar: 天数进度条
        paper_pbar: 论文数进度条
        progress: 进度字典
        progress_lock: 进度文件锁

    Returns:
        包含结果的字典
    """
    async with semaphore:
        # 打印当前正在获取的日期
        print(f"📅 正在获取: {date_str}", flush=True)

        # 初始延迟避免速率限制
        await asyncio.sleep(2.0)

        all_papers = []
        retry_count = 0

        # ArXiv API 使用 YYYYMMDD 格式
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        date_yyyymmdd = date_obj.strftime('%Y%m%d')

        # 构建搜索查询 - 使用日期范围格式
        # ArXiv API 格式: submittedDate:[YYYYMMDDHHMM+TO+YYYYMMDDHHMM]
        date_start = f"{date_yyyymmdd}0000"
        date_end = f"{date_yyyymmdd}2359"

        if CATEGORY:
            search_query = f'cat:{CATEGORY} AND submittedDate:[{date_start}+TO+{date_end}]'
        else:
            search_query = f'submittedDate:[{date_start}+TO+{date_end}]'

        # ArXiv API 单次请求最多返回 2000 条，需要分批获取
        batch_size = 1000
        start = 0
        max_results_per_day = 10000  # ArXiv API 单日限制

        while start < max_results_per_day and retry_count < MAX_RETRIES:
            try:
                url = f"{ARXIV_API_URL}search_query={quote(search_query)}&start={start}&max_results={batch_size}"

                response = await client.get(
                    url,
                    timeout=REQUEST_TIMEOUT
                )
                response.raise_for_status()

                # 解析XML响应
                root = ET.fromstring(response.content)

                # 命名空间
                ns = {
                    'atom': 'http://www.w3.org/2005/Atom',
                    'arxiv': 'http://arxiv.org/schemas/atom'
                }

                entries = root.findall('atom:entry', ns)

                if not entries:
                    # 没有更多数据
                    break

                # 解析论文
                for entry in entries:
                    paper = parse_paper_entry(entry, ns)
                    all_papers.append(paper)

                # 更新论文进度条
                paper_pbar.update(len(entries))

                # 如果获取到的数量少于请求数量，说明已经没有更多数据了
                if len(entries) < batch_size:
                    break

                start += batch_size

                # 延迟避免触发速率限制
                await asyncio.sleep(3.0)

            except httpx.HTTPStatusError as e:
                if e.response.status_code == 429:
                    # Rate limit
                    await asyncio.sleep(5)
                    retry_count += 1
                elif e.response.status_code >= 500:
                    await asyncio.sleep(3)
                    retry_count += 1
                else:
                    return {
                        'date_str': date_str,
                        'year': year,
                        'month': month,
                        'papers': [],
                        'error': str(e)
                    }

            except (httpx.TimeoutException, httpx.NetworkError) as e:
                await asyncio.sleep(3)
                retry_count += 1

            except Exception as e:
                return {
                    'date_str': date_str,
                    'year': year,
                    'month': month,
                    'papers': [],
                    'error': str(e)
                }

        # 更新天数进度条
        day_pbar.update(1)

        # 写入CSV（按月组织）
        if all_papers:
            rows = expand_authors_to_rows(all_papers)
            csv_file = get_csv_filename(year, month)
            append_to_csv(rows, csv_file)

            # 打印完成信息
            print(f"  ✅ {date_str}: {len(all_papers)} 篇论文 → {len(rows)} 行", flush=True)

            # 保存统计信息
            paper_count = len(all_papers)
            row_count = len(rows)

            # 更新进度文件（线程安全）- 只保存有数据的日期
            async with progress_lock:
                date_key = date_obj.strftime('%Y%m%d')
                progress['current_date'] = date_key
                progress['completed_dates'].append(date_key)
                save_progress(progress)

            # 只返回统计信息，不返回实际数据
            return {
                'date_str': date_str,
                'year': year,
                'month': month,
                'paper_count': paper_count,
                'row_count': row_count,
                'csv_file': csv_file,
                'error': None
            }
        else:
            # 无数据 - 不保存到进度文件，下次会重试
            print(f"  ⚠️  {date_str}: 无数据", flush=True)

            # 不更新进度文件，让这个日期下次重新获取
            return {
                'date_str': date_str,
                'year': year,
                'month': month,
                'paper_count': 0,
                'row_count': 0,
                'error': 'NO_DATA'
            }


def get_all_dates_backward() -> List[str]:
    """获取从START_DATE往前到END_YEAR的所有日期（倒序）"""
    dates = []
    start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')
    end_date_obj = datetime(END_YEAR, 1, 1)  # 改为年初，不是年末

    current = start_date_obj
    while current >= end_date_obj:
        dates.append(current.strftime('%Y-%m-%d'))
        current -= timedelta(days=1)

    return dates


async def main_async():
    """异步主函数"""
    print("=" * 60)
    print("ArXiv 论文自动获取工具 - 极速版 ⚡")
    print("=" * 60)
    print()

    # 创建输出目录
    os.makedirs('output/arxiv', exist_ok=True)

    # 设置日志
    setup_logging()
    print("📝 日志已启用")

    # 加载进度
    progress = load_progress()

    if progress['current_date']:
        print(f"📂 检测到进度文件，从 {progress['current_date']} 继续")
        print(f"   已完成: {len(progress['completed_dates'])} 天")
        print()
    else:
        print("📂 开始新的获取任务")
        print()

    # 生成所有待获取日期（倒序）
    all_dates = get_all_dates_backward()

    # 过滤已完成的日期
    pending_dates = []
    for date_str in all_dates:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        date_key = date_obj.strftime('%Y%m%d')
        if date_key not in progress['completed_dates']:
            pending_dates.append(date_str)

    print(f"📅 待获取日期范围: {START_DATE} → {END_YEAR}（往前）")
    print(f"📊 共 {len(all_dates)} 天，待获取 {len(pending_dates)} 天")
    if CATEGORY:
        print(f"🏷️  分类过滤: {CATEGORY}")
    print(f"⚡ 并发数: {MAX_CONCURRENT_REQUESTS}")
    print()
    print("=" * 60)
    print()

    if not pending_dates:
        print("✅ 所有日期已获取完成！")
        return

    # 创建异步客户端（HTTP/1.1 + 连接池）
    # ArXiv 不支持 HTTP/2，使用 HTTP/1.1
    # 注意：ArXiv API 不需要代理，直接访问即可
    async with httpx.AsyncClient(
        timeout=REQUEST_TIMEOUT,
        limits=httpx.Limits(
            max_connections=MAX_CONCURRENT_REQUESTS * 2,
            max_keepalive_connections=MAX_CONCURRENT_REQUESTS
        ),
        headers={
            'User-Agent': 'AcademicScraper/2.0-Arxiv-Fast',
            'Accept': 'application/xml'
        }
    ) as client:
        # 创建信号量（控制并发）
        semaphore = asyncio.Semaphore(MAX_CONCURRENT_REQUESTS)

        # 创建进度锁
        progress_lock = asyncio.Lock()

        # 统计
        total_papers = 0
        total_rows = 0
        success_count = 0
        skip_count = len(all_dates) - len(pending_dates)

        start_time = time.time()

        # 创建两个进度条：天数和论文数
        with tqdm(total=len(pending_dates), desc="日期进度", unit="天", ncols=80) as day_pbar, \
             tqdm(total=0, desc="论文进度", unit="篇", ncols=80) as paper_pbar:

            # 创建所有任务
            tasks = [
                fetch_arxiv_day(client, date_str, semaphore, day_pbar, paper_pbar, progress, progress_lock)
                for date_str in pending_dates
            ]

            # 并发执行所有任务
            results = await asyncio.gather(*tasks, return_exceptions=True)

            # 处理结果
            for result in results:
                if isinstance(result, Exception):
                    print(f"❌ 任务异常: {result}")
                    continue

                if result.get('error') and result.get('error') != 'NO_DATA':
                    print(f"❌ {result['date_str']}: {result['error']}")
                    continue

                # 使用新的字段名（不包含实际数据）
                paper_count = result.get('paper_count', 0)
                if paper_count > 0:
                    total_papers += paper_count
                    total_rows += result.get('row_count', 0)
                    success_count += 1

                    # 记录到日志
                    log_fetch_result(
                        result['date_str'],
                        paper_count,
                        result.get('row_count', 0),
                        result.get('csv_file', '')
                    )

        elapsed_time = time.time() - start_time

    # 最终保存进度
    save_progress(progress)

    # 记录完成状态到日志
    log_completion(total_papers, total_rows, success_count, skip_count, elapsed_time)

    # 总结
    print()
    print("=" * 60)
    print("🎉 获取完成！")
    print(f"📊 统计:")
    print(f"   - 成功: {success_count} 天")
    print(f"   - 跳过: {skip_count} 天（已完成）")
    print(f"   - 论文: {total_papers} 篇")
    print(f"   - 行数: {total_rows} 行")
    print(f"   - 耗时: {elapsed_time:.2f} 秒 ({elapsed_time/3600:.2f} 小时)")
    print(f"   - 速度: {total_papers/elapsed_time:.1f} 篇/秒")
    print(f"📁 数据文件: output/arxiv/")
    print(f"📝 日志文件: {LOG_FILE}")
    print("=" * 60)


def main():
    """主函数"""
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("💾 进度已保存，下次运行将从中断处继续")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()


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
    output_dir = os.path.join(script_dir, '../output/arxiv')
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
            output_file = os.path.join(output_dir, f'{year}_{month:02d}.csv')
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
        filename = f'{year}_{month:02d}.csv'
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
