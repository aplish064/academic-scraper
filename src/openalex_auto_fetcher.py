#!/usr/bin/env python3
"""
OpenAlex 论文自动获取工具
- 从 2026年4月10日往前获取到 2010年
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
from typing import List, Dict, Any
from datetime import datetime, timedelta


# OpenAlex API 基础URL
OPENALEX_API_BASE = "https://api.openalex.org"

# CSV字段
CSV_FIELDS = [
    'author', 'uid', 'doi', 'title', 'rank', 'journal',
    'citation_count', 'tag', 'state'
]

# 日志目录和文件
LOG_DIR = "/home/apl064/apl/academic-scraper/log"
LOG_FILE = os.path.join(LOG_DIR, "openalex_fetch.log")
PROGRESS_FILE = os.path.join(LOG_DIR, "openalex_fetch_progress.json")

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
    log_message += f"获取范围: {START_DATE} → {END_YEAR}1231\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_fetch_result(date_str: str, paper_count: int, row_count: int, csv_file: str):
    """记录每次获取结果到日志"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] {date_str} | 论文: {paper_count} | 行: {row_count} | 文件: {csv_file}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_progress_checkpoint(completed_dates: int):
    """记录进度检查点"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"[{timestamp}] 进度检查点 | 已完成: {completed_dates} 天\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def log_completion(total_papers: int, total_rows: int, success_count: int, skip_count: int):
    """记录完成状态"""
    timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    log_message = f"\n{'='*80}\n"
    log_message += f"完成时间: {timestamp}\n"
    log_message += f"成功: {success_count} 天\n"
    log_message += f"跳过: {skip_count} 天\n"
    log_message += f"总论文: {total_papers} 篇\n"
    log_message += f"总行数: {total_rows} 行\n"
    log_message += f"{'='*80}\n"

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_message)


def parse_openalex_work(work: Dict[str, Any]) -> Dict[str, Any]:
    """解析 OpenAlex 作品数据"""
    # 基本信息
    paper_id = work.get('id', '')
    title = work.get('title', '')
    if title:
        title = title.replace('\n', ' ')

    doi = work.get('doi', None)
    if doi is None:
        doi = ''

    # 作者信息
    authors = []
    authorships = work.get('authorships', [])

    for idx, auth in enumerate(authorships):
        author_info = auth.get('author', {})
        if author_info and author_info.get('display_name'):
            authors.append({
                'name': author_info['display_name'],
                'rank': idx + 1
            })

    # 期刊/会议信息
    primary_location = work.get('primary_location') or {}
    source = primary_location.get('source') or {}
    journal = source.get('display_name', 'unknown')

    # 被引次数
    citation_count = work.get('cited_by_count', 0)

    # 概念/分类
    concepts = work.get('concepts', [])
    categories = [c.get('display_name', '') for c in concepts[:3] if c.get('display_name')]

    return {
        'uid': paper_id,
        'doi': doi,
        'title': title,
        'authors': authors,
        'journal': journal,
        'citation_count': citation_count,
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


def fetch_openalex_by_date(date_str: str) -> List[Dict[str, Any]]:
    """
    从 OpenAlex 获取指定日期的论文

    Args:
        date_str: 日期字符串 (YYYY-MM-DD)

    Returns:
        论文列表
    """
    all_papers = []
    cursor = '*'
    per_page = 200  # OpenAlex 默认每页 200
    max_retries = 3  # 最大重试次数

    # 构建查询：从发布日期开始到结束日期
    from_date = date_str
    to_date = date_str

    print(f"    📡 查询日期: {from_date}", flush=True)

    while True:  # 移除限制，获取所有数据
        # 构建API URL
        params = {
            'filter': f'from_publication_date:{from_date},to_publication_date:{to_date}',
            'per-page': per_page,
            'cursor': cursor
        }

        url = f"{OPENALEX_API_BASE}/works"

        retry_count = 0
        while retry_count < max_retries:
            try:
                response = requests.get(
                    url,
                    params=params,
                    headers={
                        'User-Agent': 'AcademicScraper/1.0',
                        'Mailto': 'mailto@example.com',
                        'Accept': 'application/json'
                    },
                    timeout=60
                )
                response.raise_for_status()

                data = response.json()

                results = data.get('results', [])
                if not results:
                    return all_papers

                # 解析论文
                for work in results:
                    paper = parse_openalex_work(work)
                    all_papers.append(paper)

                print(f"      ✅ 获取 {len(results)} 篇 (总计: {len(all_papers)})", flush=True)

                # 检查是否还有更多结果
                meta = data.get('meta', {})
                next_cursor = meta.get('next_cursor')
                if not next_cursor:
                    return all_papers

                cursor = next_cursor

                # 更保守的请求间隔（避免 SSL 错误）
                time.sleep(1)  # 改为 1 秒
                break  # 成功，退出重试循环

            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429:  # Rate limit
                    print(f"      ⚠️  API 限制，等待 10 秒...", flush=True)
                    time.sleep(10)
                    retry_count += 1
                elif e.response.status_code == 500:
                    print(f"      ⚠️  服务器错误 ({retry_count + 1}/{max_retries})", flush=True)
                    time.sleep(5)
                    retry_count += 1
                else:
                    print(f"      ❌ HTTP 错误: {e}", flush=True)
                    return all_papers

            except requests.exceptions.Timeout:
                print(f"      ⚠️  超时 ({retry_count + 1}/{max_retries})，等待 5 秒...", flush=True)
                time.sleep(5)
                retry_count += 1

            except requests.exceptions.SSLError:
                print(f"      ⚠️  SSL 错误 ({retry_count + 1}/{max_retries})，等待 8 秒...", flush=True)
                time.sleep(8)
                retry_count += 1

            except Exception as e:
                print(f"      ❌ 错误: {e}", flush=True)
                return all_papers
        else:
            # 重试次数用完
            print(f"      ❌ 达到最大重试次数，跳过", flush=True)
            break

    return all_papers


def get_all_dates_backward() -> List[str]:
    """获取从START_DATE往前到END_YEAR的所有日期（倒序）"""
    dates = []
    start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')
    end_date_obj = datetime(END_YEAR, 12, 31)

    current = start_date_obj
    while current >= end_date_obj:
        dates.append(current.strftime('%Y-%m-%d'))  # OpenAlex 使用 YYYY-MM-DD 格式
        current -= timedelta(days=1)

    return dates


def get_csv_filename(year: int, month: int) -> str:
    """获取CSV文件名（按月份组织）"""
    output_dir = '/home/apl064/apl/academic-scraper/output'
    os.makedirs(output_dir, exist_ok=True)
    return os.path.join(output_dir, f'{year}_{month}_openalex_papers.csv')


def main():
    """主函数"""
    print("=" * 60)
    print("OpenAlex 论文自动获取工具")
    print("=" * 60)
    print()

    # 创建输出目录
    os.makedirs('output', exist_ok=True)

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

    # 确定起始日期
    start_date_obj = None
    if progress['current_date']:
        # 从上次的位置继续（往前）
        # 进度文件存储的是 YYYYMMDD 格式，需要转换为 YYYY-MM-DD
        old_date = datetime.strptime(progress['current_date'], '%Y%m%d')
        start_date_obj = old_date - timedelta(days=1)
    else:
        # 从开始日期获取
        start_date_obj = datetime.strptime(START_DATE, '%Y%m%d')

    # 生成所有待获取日期（倒序）
    all_dates = []
    current = start_date_obj
    end_date_obj = datetime(END_YEAR, 12, 31)

    while current >= end_date_obj:
        all_dates.append(current.strftime('%Y-%m-%d'))
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
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        year = date_obj.year
        month = date_obj.month
        day = date_obj.day

        # 检查是否已完成（使用 YYYYMMDD 格式存储）
        date_key = date_obj.strftime('%Y%m%d')
        if date_key in progress['completed_dates']:
            skip_count += 1
            continue

        print(f"[{idx}/{len(all_dates)}] {year}年{month}月{day}日 ({date_str})", flush=True)

        # 获取该日数据
        papers = fetch_openalex_by_date(date_str)

        if papers:
            # 展开为作者行
            rows = expand_authors_to_rows(papers)

            # 追加到CSV
            csv_file = get_csv_filename(year, month)
            append_to_csv(rows, csv_file)

            total_papers += len(papers)
            total_rows += len(rows)
            success_count += 1

            print(f"    ✅ {len(papers)} 篇论文, {len(rows)} 行 → {csv_file}", flush=True)

            # 记录到日志
            log_fetch_result(date_str, len(papers), len(rows), csv_file)
        else:
            print(f"    ℹ️  无数据", flush=True)
            log_fetch_result(date_str, 0, 0, "无数据")

        # 更新进度
        progress['current_date'] = date_key
        progress['completed_dates'].append(date_key)

        # 每天都保存进度
        save_progress(progress)

        # 每10天记录进度检查点
        if len(progress['completed_dates']) % 10 == 0:
            log_progress_checkpoint(len(progress['completed_dates']))
            print(f"    💾 进度已保存", flush=True)

        print()

        # 避免过快请求
        time.sleep(2)

    # 最终保存进度
    save_progress(progress)

    # 记录完成状态到日志
    log_completion(total_papers, total_rows, success_count, skip_count)

    # 总结
    print("=" * 60)
    print("🎉 获取完成！")
    print(f"📊 统计:")
    print(f"   - 成功: {success_count} 天")
    print(f"   - 跳过: {skip_count} 天（已完成）")
    print(f"   - 论文: {total_papers} 篇")
    print(f"   - 行数: {total_rows} 行")
    print(f"📁 数据文件: output/")
    print(f"📝 日志文件: {LOG_FILE}")
    print("=" * 60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
        print("💾 进度已保存（每天自动保存），下次运行将从中断处继续")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
