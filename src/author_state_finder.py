#!/usr/bin/env python3
"""
作者学历状态查找工具 - 优化版
- 多线程并发处理（默认 5 个线程）
- 移除报错的 Semantic Scholar API
- 进度保存，支持断点续传
- 动态延迟控制
"""

import requests
import csv
import json
import time
import os
from typing import Dict, Any, Optional, List
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import sys


# ==================== 配置 ====================
ANTHROPIC_API_KEY = "6cd56444f8ca470488d9902592695511.pJKcSLeQlEOJ7vqF"
ANTHROPIC_BASE_URL = "https://open.bigmodel.cn/api/anthropic"

# 并发配置（默认值）
DEFAULT_MAX_WORKERS = 5  # 并发线程数，可以根据 API 限制调整
REQUEST_DELAY = 0.5  # 每个请求后的延迟（秒）

# 全局变量
MAX_WORKERS = DEFAULT_MAX_WORKERS

# 进度文件
PROGRESS_DIR = "/home/apl064/apl/academic-scraper/log"
PROGRESS_FILE = os.path.join(PROGRESS_DIR, "author_state_progress.json")

# 线程锁
print_lock = Lock()
stats_lock = Lock()


# ==================== 进度管理 ====================
def load_progress() -> Dict[str, Any]:
    """加载进度文件"""
    if os.path.exists(PROGRESS_FILE):
        try:
            with open(PROGRESS_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except:
            pass
    return {
        'completed_authors': {},
        'stats': {
            '高置信度': 0,
            '中置信度': 0,
            '低置信度': 0,
            '论文验证失败': 0
        }
    }


def save_progress(progress: Dict[str, Any]):
    """保存进度文件"""
    os.makedirs(PROGRESS_DIR, exist_ok=True)
    with open(PROGRESS_FILE, 'w', encoding='utf-8') as f:
        json.dump(progress, f, indent=2, ensure_ascii=False)


# ==================== Claude API ====================
def call_claude_api(prompt: str) -> Dict[str, Any]:
    """调用 Claude API"""
    url = f"{ANTHROPIC_BASE_URL}/v1/messages"

    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
    }

    data = {
        "model": "claude-sonnet-4-20250514",
        "max_tokens": 3000,
        "messages": [{
            "role": "user",
            "content": prompt
        }]
    }

    try:
        response = requests.post(url, headers=headers, json=data, timeout=300)
        response.raise_for_status()
        result = response.json()

        content = result.get('content', [])
        if content and len(content) > 0:
            text = content[0].get('text', '')

            # 解析 JSON
            json_start = text.find('{')
            json_end = text.rfind('}') + 1

            if json_start >= 0 and json_end > json_start:
                json_str = text[json_start:json_end]
                return json.loads(json_str)

        return {
            "status": "未知",
            "confidence": "低",
            "verification": {
                "paper_found": False,
                "paper_match_details": "",
                "author_profile_url": "",
                "education_source": ""
            },
            "evidence": [],
            "reasoning": "无法解析 LLM 返回"
        }

    except Exception as e:
        return {
            "status": "未知",
            "confidence": "低",
            "verification": {
                "paper_found": False,
                "paper_match_details": "",
                "author_profile_url": "",
                "education_source": ""
            },
            "evidence": [],
            "reasoning": f"API 调用失败: {e}"
        }


# ==================== 作者信息搜索 ====================
def search_and_verify_author(
    author_name: str,
    target_paper: str,
    journal: str = ""
) -> Dict[str, Any]:
    """搜索并严格验证作者身份"""

    prompt = f"""请帮我查找作者 "{author_name}" 的学历信息，并进行严格验证。

**目标论文（必须验证）**：
- 论文标题：{target_paper}
- 期刊：{journal}

**任务步骤**：

步骤1：搜索作者信息
- 使用联网搜索，查找作者的个人主页（大学官网、GitHub Pages、Google Scholar、ResearchGate等）
- 关键词建议："{author_name}" + "homepage" 或 "profile" 或 "CV"

步骤2：严格验证身份
- **关键**：在找到的主页中，必须找到这篇目标论文："{target_paper}"
- 如果主页中没有这篇论文，说明找错人了，请继续搜索其他同名作者
- 只有确认论文匹配后，才继续下一步

步骤3：查找学历信息
- 在验证过的主页中，查找关于教育背景的明确信息
- 优先查找：About me、Biography、CV、Education 等部分
- 关键词：PhD student（博士生）、Doctoral candidate（博士候选人）、Master student（硕士生）、Undergraduate（本科生）、Professor（教授）、Assistant Professor（助理教授）等

步骤4：交叉验证
- 如果找到多个来源，检查它们是否一致
- 如果有冲突，选择更权威的来源（大学官网 > 个人主页 > 第三方网站）

**返回 JSON 格式**：
{{
    "status": "博士/硕士/本科/教师/未知",
    "confidence": "高/中/低",
    "verification": {{
        "paper_found": true/false,
        "paper_match_details": "在哪里找到了目标论文",
        "author_profile_url": "作者主页链接",
        "education_source": "在哪里找到学历信息"
    }},
    "evidence": [
        "证据1：在XXX页面找到目标论文",
        "证据2：About页面说明'PhD student'",
        "证据3：CV显示教育经历"
    ],
    "reasoning": "完整的推理过程"
}}

**重要提示**：
1. **论文验证是必须的**：如果找不到目标论文，status 必须是"未知"
2. **置信度"高"的条件**：
   - 在官方/权威网站找到明确说明
   - 且论文验证通过
3. **置信度"中"的条件**：
   - 在非官方网站找到信息
   - 或信息不够明确
4. **置信度"低"的条件**：
   - 只找到间接证据
   - 或无法验证论文

请严格执行这些步骤，确保准确性。"""

    return call_claude_api(prompt)


def find_author_state(author_name: str, row: Dict[str, Any]) -> Dict[str, Any]:
    """查找单行作者的学历状态"""
    paper_title = row['title']
    journal = row['journal']

    with print_lock:
        print(f"\n🔍 [{author_name}]")
        print(f"   目标论文: {paper_title[:60]}...")

    # 直接使用 LLM 联网搜索
    with print_lock:
        print(f"   🌐 LLM 联网搜索...")

    result = search_and_verify_author(author_name, paper_title, journal)

    # 提取关键信息
    status = result.get('status', '未知')
    confidence = result.get('confidence', '低')
    verification = result.get('verification', {})
    evidence = result.get('evidence', [])

    # 显示验证结果
    paper_found = verification.get('paper_found', False)

    with print_lock:
        print(f"   📄 论文验证: {'✅ 通过' if paper_found else '❌ 未找到'}")

        if paper_found:
            profile_url = verification.get('author_profile_url', '')
            if profile_url:
                print(f"   🔗 主页: {profile_url}")

            edu_source = verification.get('education_source', '')
            if edu_source:
                print(f"   📚 学历来源: {edu_source}")

            print(f"   🎓 结论: {status} (置信度: {confidence})")
        else:
            print(f"   ⚠️  警告: 未找到目标论文，可能识别错误")
            print(f"   🎓 结论: 未知 (置信度: 低)")

        # 显示证据（第一项）
        if evidence:
            print(f"   📋 证据: {evidence[0][:80]}...")

    return result


def process_author(args: tuple) -> tuple:
    """处理单个作者（用于多线程）"""
    author_name, row, progress_data = args

    # 检查是否已完成
    if author_name in progress_data['completed_authors']:
        with print_lock:
            print(f"\n⏭️  跳过 [{author_name}] - 已处理")
        return author_name, progress_data['completed_authors'][author_name]

    # 查找状态
    result = find_author_state(author_name, row)

    # 格式化状态
    status = result.get('status', '未知')
    confidence = result.get('confidence', '低')
    verification = result.get('verification', {})
    paper_found = verification.get('paper_found', False)

    if not paper_found:
        state_str = "未知"
        with stats_lock:
            progress_data['stats']['论文验证失败'] += 1
    else:
        state_str = status
        with stats_lock:
            if confidence == '高':
                progress_data['stats']['高置信度'] += 1
            elif confidence == '中':
                progress_data['stats']['中置信度'] += 1
            else:
                progress_data['stats']['低置信度'] += 1

    # 延迟
    time.sleep(REQUEST_DELAY)

    return author_name, state_str


# ==================== 批量处理 ====================
def batch_find_states(csv_file: str, output_file: str, limit: int = None, workers: int = DEFAULT_MAX_WORKERS):
    """批量查找作者状态（并发版）"""

    # 读取 CSV
    authors = []
    with open(csv_file, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for row in reader:
            authors.append(row)

    print(f"📂 读取文件: {csv_file}")
    print(f"📊 共 {len(authors)} 行")

    if limit:
        authors = authors[:limit]
        print(f"🧪 测试模式：只处理前 {limit} 行")

    # 去重作者
    unique_authors = {}
    for row in authors:
        name = row['author']
        if name not in unique_authors:
            unique_authors[name] = row

    print(f"👥 去重后：{len(unique_authors)} 个唯一作者")

    # 加载进度
    progress_data = load_progress()
    author_states = progress_data['completed_authors'].copy()

    print(f"\n⏭️  已完成：{len(author_states)} 个作者")
    print(f"🔄 待处理：{len(unique_authors) - len(author_states)} 个作者")
    print(f"🚀 并发数：{workers}")
    print("=" * 70)

    # 准备待处理作者
    pending_authors = [(name, row, progress_data) for name, row in unique_authors.items()
                       if name not in author_states]

    # 并发处理
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(process_author, args): args[0] for args in pending_authors}

        for i, future in enumerate(as_completed(futures), 1):
            try:
                author_name, state_str = future.result()
                author_states[author_name] = state_str

                # 更新进度
                progress_data['completed_authors'][author_name] = state_str

                # 每 10 个作者保存一次进度
                if i % 10 == 0:
                    save_progress(progress_data)
                    completed = len(author_states)
                    total = len(unique_authors)
                    print(f"\n{'=' * 70}")
                    print(f"📊 进度: {completed}/{total} ({completed*100//total}%)")
                    print(f"📝 进度已保存")
                    print(f"{'=' * 70}")

            except Exception as e:
                author_name = futures[future]
                with print_lock:
                    print(f"\n❌ 处理 [{author_name}] 时出错: {e}")
                author_states[author_name] = "未知"

    # 最终保存进度
    save_progress(progress_data)

    # 写入输出文件
    print(f"\n{'=' * 70}")
    print(f"\n📝 写入文件: {output_file}")

    # 读取输入文件获取 fieldnames
    with open(csv_file, 'r', encoding='utf-8-sig') as infile:
        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        if not fieldnames:
            # 如果无法读取 fieldnames，使用默认值
            fieldnames = ['author', 'uid', 'doi', 'title', 'rank', 'journal', 'citation_count', 'tag', 'state']
        rows = list(reader)

    # 写入输出文件
    with open(output_file, 'w', encoding='utf-8-sig', newline='') as outfile:
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for row in rows:
            author_name = row['author']
            row['state'] = author_states.get(author_name, '')
            writer.writerow(row)

    # 显示统计
    stats = progress_data['stats']
    print(f"\n{'=' * 70}")
    print(f"📊 统计结果:")
    print(f"   ✅ 高置信度: {stats['高置信度']} 人")
    print(f"   ⚠️  中置信度: {stats['中置信度']} 人")
    print(f"   ❌ 低置信度: {stats['低置信度']} 人")
    print(f"   🔍 论文验证失败: {stats['论文验证失败']} 人")
    print(f"{'=' * 70}")
    print(f"✅ 完成！")


# ==================== 主程序 ====================
if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("用法: python3 author_state_finder_fast.py <input.csv> [output.csv] [limit] [workers]")
        print("示例: python3 author_state_finder_fast.py demo_input.csv demo_output.csv 100 5")
        print("\n参数说明:")
        print("  input.csv  - 输入 CSV 文件")
        print("  output.csv - 输出 CSV 文件（可选，默认添加 _with_state 后缀）")
        print("  limit      - 限制处理数量（可选，用于测试）")
        print("  workers    - 并发线程数（可选，默认 5）")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.csv', '_with_state.csv')
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    # 获取并发线程数
    workers = int(sys.argv[4]) if len(sys.argv) > 4 else DEFAULT_MAX_WORKERS

    batch_find_states(input_file, output_file, limit, workers)
