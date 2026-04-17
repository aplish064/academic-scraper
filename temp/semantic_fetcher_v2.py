#!/usr/bin/env python3
"""
Semantic Scholar Paper Fetcher - 改进版
使用多种策略突破API限制，获取更完整的数据
"""

import requests
import json
import time
import os
from datetime import datetime, timedelta
from pathlib import Path
import itertools

# ============ 配置参数 ============
API_KEY = "7Tts2u4jXLaebjvFPICkE7kpTJQvUaYG4byRSpBp"
EMAIL = "20228132063@m.scnu.edu.cn"
BASE_URL = "https://api.semanticscholar.org/graph/v1"

# 时间配置
START_DATE = "20260401"  # 开始日期 (YYYYMMDD)
END_YEAR = 2010          # 结束年份

# 请求配置
REQUEST_INTERVAL = 1.1   # 请求间隔（秒）
REQUEST_TIMEOUT = 30     # 请求超时（秒）
MAX_RETRIES = 3          # 最大重试次数

# 分页配置
PAPERS_PER_REQUEST = 100 # 每次请求获取的论文数

# 输出配置
OUTPUT_DIR = Path("output/semanticscholar")
PROGRESS_FILE = Path("log/semantic_scholar_progress.json")
LOG_FILE = Path("log/semantic_scholar_fetch.log")

# ============ 改进的搜索策略 ============

# 策略1: A-Z单字母
SEARCH_SINGLE_LETTERS = [chr(i) for i in range(ord('A'), ord('Z') + 1))]

# 策略2: 常见双字母组合（提升覆盖率）
SEARCH_DOUBLE_LETTERS = [
    'AB', 'AC', 'AD', 'AE', 'AF', 'AG', 'AH', 'AI', 'AJ', 'AK', 'AL', 'AM', 'AN', 'AP', 'AR', 'AS', 'AT',
    'BA', 'BE', 'BO', 'BR', 'BU',
    'CA', 'CE', 'CH', 'CL', 'CO', 'CR',
    'DA', 'DE', 'DI', 'DI',
    'EA', 'EC', 'ED', 'EE', 'EF', 'EG', 'EL', 'EN', 'EP', 'ER', 'ES', 'ET',
    'FA', 'FE', 'FI', 'FO', 'FR',
    'GA', 'GE', 'GO', 'GR', 'GU',
    'HA', 'HE', 'HI', 'HO', 'HU',
    'IA', 'IB', 'IC', 'ID', 'IE', 'IF', 'IG', 'IH', 'IM', 'IN', 'IO', 'IR', 'IS', 'IT',
    'JA', 'JE', 'JI', 'JO', 'JU',
    'KA', 'KE', 'KI', 'KO',
    'LA', 'LE', 'LI', 'LO', 'LU',
    'MA', 'ME', 'MI', 'MO', 'MU', 'MY',
    'NA', 'NE', 'NI', 'NO', 'NU',
    'OA', 'OB', 'OC', 'OD', 'OF', 'OG', 'OH', 'OI', 'OM', 'ON', 'OP', 'OR', 'OS', 'OT', 'OU', 'OV', 'OW',
    'PA', 'PE', 'PI', 'PO', 'PR', 'PU',
    'RA', 'RE', 'RI', 'RO', 'RU',
    'SA', 'SE', 'SI', 'SO', 'SU',
    'TA', 'TE', 'TI', 'TO', 'TU',
    'UA', 'UB', 'UC', 'UD', 'UE', 'UF', 'UG', 'UH', 'UI', 'UM', 'UN', 'UP', 'UR', 'US', 'UT',
    'VA', 'VE', 'VI', 'VO', 'VU',
    'WA', 'WE', 'WI', 'WO', 'WU',
    'YA', 'YE', 'YI', 'YO', 'YU',
    'ZA', 'ZE', 'ZI', 'ZO', 'ZU'
]

# 策略3: 学术领域关键词
ACADEMIC_KEYWORDS = [
    'machine learning', 'deep learning', 'neural network', 'artificial intelligence',
    'data analysis', 'statistics', 'algorithm', 'optimization',
    'biology', 'chemistry', 'physics', 'mathematics', 'computer science',
    'medicine', 'health', 'disease', 'treatment', 'therapy',
    'social', 'economic', 'political', 'history', 'philosophy',
    'engineering', 'technology', 'materials', 'energy', 'environment'
]

# 策略4: 通用词汇（覆盖论文标题常见词）
COMMON_WORDS = [
    'study', 'research', 'analysis', 'method', 'approach', 'system', 'model', 'framework',
    'application', 'implementation', 'evaluation', 'performance', 'optimization', 'design',
    'development', 'management', 'processing', 'network', 'based', 'using', 'new', 'novel',
    'efficient', 'effective', 'robust', 'scalable', 'adaptive', 'automatic', 'distributed',
    'dynamic', 'intelligent', 'advanced', 'modern', 'smart', 'virtual', 'digital', 'online'
]

# 选择使用哪个策略
SEARCH_STRATEGY = 'COMPREHENSIVE'  # 'SINGLE', 'DOUBLE', 'ACADEMIC', 'COMMON', 'COMPREHENSIVE'

def get_search_keywords():
    """根据策略返回搜索关键词列表"""
    if SEARCH_STRATEGY == 'SINGLE':
        return SEARCH_SINGLE_LETTERS
    elif SEARCH_STRATEGY == 'DOUBLE':
        return SEARCH_DOUBLE_LETTERS
    elif SEARCH_STRATEGY == 'ACADEMIC':
        return ACADEMIC_KEYWORDS
    elif SEARCH_STRATEGY == 'COMMON':
        return COMMON_WORDS
    else:  # COMPREHENSIVE
        # 组合多种策略，提高覆盖率
        return SEARCH_SINGLE_LETTERS + SEARCH_DOUBLE_LETTERS[:50] + ACADEMIC_KEYWORDS[:10]


# ============ 全局变量 ============
headers = {
    "x-api-key": API_KEY,
    "Content-Type": "application/json"
}


def setup_directories():
    """创建必要的目录"""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)


def load_progress():
    """加载进度文件"""
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "completed_dates": [],
        "last_update": None
    }


def save_progress(progress_data, date=None):
    """保存进度文件"""
    if date and date not in progress_data["completed_dates"]:
        progress_data["completed_dates"].append(date)

    progress_data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress_data, f, indent=2, ensure_ascii=False)


def log_message(message):
    """记录日志消息"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_line = f"[{timestamp}] {message}\n"

    print(log_line.strip())

    with open(LOG_FILE, 'a', encoding='utf-8') as f:
        f.write(log_line)


def make_request(url, params, retry_count=0):
    """发送 HTTP 请求，带有重试机制"""
    try:
        response = requests.get(url, headers=headers, params=params,
                               timeout=REQUEST_TIMEOUT)

        # 检查速率限制
        if response.status_code == 429:
            log_message(f"⚠️  速率限制: {response.text}")
            return None

        # 检查其他错误
        if response.status_code != 200:
            if retry_count < MAX_RETRIES:
                wait_time = (2 ** retry_count) * 2  # 指数退避
                log_message(f"⚠️  请求失败 (状态码 {response.status_code}), {wait_time}秒后重试...")
                time.sleep(wait_time)
                return make_request(url, params, retry_count + 1)
            else:
                log_message(f"❌ 请求失败: {response.text}")
                return None

        return response.json()

    except requests.exceptions.Timeout:
        if retry_count < MAX_RETRIES:
            log_message(f"⚠️  请求超时, 重试 {retry_count + 1}/{MAX_RETRIES}")
            time.sleep(5)
            return make_request(url, params, retry_count + 1)
        else:
            log_message(f"❌ 请求超时，已达最大重试次数")
            return None

    except Exception as e:
        log_message(f"❌ 请求异常: {e}")
        return None


def fetch_papers_for_date(date_str):
    """
    获取指定日期的论文（使用改进的搜索策略）

    Args:
        date_str: 日期字符串 (YYYYMMDD)

    Returns:
        list: 论文列表，如果失败返回 None
    """
    date_obj = datetime.strptime(date_str, "%Y%m%d")
    date_start = date_obj.strftime("%Y-%m-%d")
    date_end = (date_obj + timedelta(days=1)).strftime("%Y-%m-%d")

    # 获取搜索关键词
    keywords = get_search_keywords()

    log_message(f"📅 开始获取 {date_start} 的论文")
    log_message(f"🔍 搜索策略: {SEARCH_STRATEGY}, 关键词数量: {len(keywords)}")

    # 用于去重的论文ID集合
    seen_paper_ids = set()
    all_papers = []

    # 使用多种关键词搜索
    for idx, keyword in enumerate(keywords, 1):
        log_message(f"   [{idx}/{len(keywords)}] 搜索关键词: '{keyword}'")

        offset = 0
        keyword_papers = []
        max_pages = 10  # 每个关键词最多获取10页（1000条）

        while offset < max_pages * PAPERS_PER_REQUEST:
            params = {
                "query": keyword,
                "fields": "paperId,title,authors,year,venue,journal,publicationDate,citationCount,openAccessPdf,externalIds,url,abstract",
                "year": date_obj.year,
                "fromDate": date_start,
                "toDate": date_end,
                "limit": PAPERS_PER_REQUEST,
                "offset": offset
            }

            data = make_request(f"{BASE_URL}/paper/search", params)

            if not data:
                log_message(f"   ❌ 搜索 '{keyword}' 失败")
                break

            papers = data.get("data", [])
            total = data.get("total", 0)

            if not papers:
                break

            # 去重：只添加未见过的新论文
            new_papers = []
            for paper in papers:
                paper_id = paper.get("paperId", "")
                if paper_id and paper_id not in seen_paper_ids:
                    seen_paper_ids.add(paper_id)
                    new_papers.append(paper)

            keyword_papers.extend(new_papers)
            log_message(f"      获取了 {len(new_papers)} 篇新论文 (总计: {len(keyword_papers)}/{total})")

            # 检查是否还有更多数据
            if offset + len(papers) >= total or len(papers) < PAPERS_PER_REQUEST:
                break

            offset += len(papers)

            # 遵守速率限制
            time.sleep(REQUEST_INTERVAL)

        log_message(f"   ✅ '{keyword}' 搜索完成: {len(keyword_papers)} 篇论文")
        all_papers.extend(keyword_papers)

        # 遵守速率限制
        time.sleep(REQUEST_INTERVAL)

    log_message(f"✅ {date_start} 获取完成: {len(all_papers)} 篇论文（去重后）")
    return all_papers


def generate_date_range():
    """生成日期范围（从 START_DATE 往前到 END_YEAR）"""
    start = datetime.strptime(START_DATE, "%Y%m%d")

    current = start
    while current.year >= END_YEAR:
        yield current.strftime("%Y%m%d")
        current -= timedelta(days=1)


def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("Semantic Scholar Paper Fetcher - 改进版")
    print("=" * 60)
    print(f"开始日期: {START_DATE}")
    print(f"结束年份: {END_YEAR}")
    print(f"搜索策略: {SEARCH_STRATEGY}")
    print(f"请求间隔: {REQUEST_INTERVAL}秒")
    print(f"输出目录: {OUTPUT_DIR}")
    print("=" * 60 + "\n")

    # 创建必要的目录
    setup_directories()

    # 加载进度
    progress = load_progress()
    completed_dates = set(progress["completed_dates"])

    log_message("🚀 开始获取任务")

    total_papers = 0
    skipped_dates = 0

    # 生成日期范围并过滤已完成的日期
    dates_to_process = [
        date for date in generate_date_range()
        if date not in completed_dates
    ]

    log_message(f"📊 总共需要处理 {len(dates_to_process)} 个日期")

    for i, date_str in enumerate(dates_to_process, 1):
        log_message(f"\n[{i}/{len(dates_to_process)}] 处理日期: {date_str}")

        # 获取论文
        papers = fetch_papers_for_date(date_str)

        if papers is None:
            # 获取失败，跳过这个日期
            log_message(f"⏭️  跳过日期: {date_str}")
            continue

        if len(papers) == 0:
            # 没有论文，标记为完成但不保存
            log_message(f"📭 没有论文: {date_str}")
            save_progress(progress, date_str)
            skipped_dates += 1
            continue

        # TODO: 这里改为保存到ClickHouse
        # row_count = save_to_csv(papers, date_str)

        # 更新统计
        total_papers += len(papers)

        # 保存进度
        save_progress(progress, date_str)

        # 遵守速率限制
        time.sleep(REQUEST_INTERVAL)

    # 最终统计
    log_message("\n" + "=" * 60)
    log_message("✅ 任务完成")
    log_message(f"📊 总计获取: {total_papers} 篇论文")
    log_message(f"⏭️  跳过日期: {skipped_dates}")
    log_message(f"📝 进度文件: {PROGRESS_FILE}")
    log_message("=" * 60)


if __name__ == "__main__":
    main()