#!/usr/bin/env python3
"""
作者学历状态查找工具 V2
- 严格的论文验证逻辑
- 简化分类：硕士/博士/本科/教师/未知
- 多步验证流程
"""

import requests
import csv
import json
import time
from typing import Dict, Any, Optional, List


# 配置
ANTHROPIC_API_KEY = "6cd56444f8ca470488d9902592695511.pJKcSLeQlEOJ7vqF"
ANTHROPIC_BASE_URL = "https://open.bigmodel.cn/api/anthropic"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = "7Tts2u4jXLaebjvFPICkE7kpTJQvUaYG4byRSpBp"


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
            "evidence": [],
            "reasoning": "无法解析 LLM 返回"
        }

    except Exception as e:
        return {
            "status": "未知",
            "confidence": "低",
            "evidence": [],
            "reasoning": f"API 调用失败: {e}"
        }


def search_and_verify_author(
    author_name: str,
    target_paper: str,
    journal: str = ""
) -> Dict[str, Any]:
    """
    搜索并严格验证作者身份

    Args:
        author_name: 作者姓名
        target_paper: 目标论文标题（用于验证）
        journal: 期刊名称（辅助验证）

    Returns:
        验证结果
    """

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


def find_author_state_strict(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    严格查找单行作者的学历状态
    """

    author_name = row['author']
    paper_title = row['title']
    journal = row['journal']

    print(f"\n🔍 [{author_name}]")
    print(f"   目标论文: {paper_title[:60]}...")

    # 调用严格验证
    result = search_and_verify_author(author_name, paper_title, journal)

    # 提取关键信息
    status = result.get('status', '未知')
    confidence = result.get('confidence', '低')
    verification = result.get('verification', {})
    reasoning = result.get('reasoning', '')
    evidence = result.get('evidence', [])

    # 显示验证结果
    paper_found = verification.get('paper_found', False)
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


def batch_find_states_strict(csv_file: str, output_file: str, limit: int = None):
    """
    批量查找作者状态（严格版）
    """

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

    # 去重作者（保留第一个出现的论文作为验证依据）
    unique_authors = {}
    for row in authors:
        name = row['author']
        if name not in unique_authors:
            unique_authors[name] = row

    print(f"👥 去重后：{len(unique_authors)} 个唯一作者\n")
    print("=" * 70)

    # 查找每个作者的状态
    author_states = {}
    stats = {
        '高置信度': 0,
        '中置信度': 0,
        '低置信度': 0,
        '论文验证失败': 0
    }

    for i, (author_name, row) in enumerate(unique_authors.items(), 1):
        print(f"\n[{i}/{len(unique_authors)}]", end=" ")

        result = find_author_state_strict(row)

        # 格式化状态
        status = result.get('status', '未知')
        confidence = result.get('confidence', '低')
        verification = result.get('verification', {})
        paper_found = verification.get('paper_found', False)

        # 如果论文未找到，标记为未知
        if not paper_found:
            state_str = "未知 [论文验证失败]"
            stats['论文验证失败'] += 1
        else:
            state_str = f"{status} [置信度:{confidence}]"
            if confidence == '高':
                stats['高置信度'] += 1
            elif confidence == '中':
                stats['中置信度'] += 1
            else:
                stats['低置信度'] += 1

        author_states[author_name] = state_str

        # 避免请求过快
        time.sleep(3)

    # 写入输出文件
    print(f"\n{'=' * 70}")
    print(f"\n📝 写入文件: {output_file}")

    with open(csv_file, 'r', encoding='utf-8-sig') as infile, \
         open(output_file, 'w', encoding='utf-8-sig', newline='') as outfile:

        reader = csv.DictReader(infile)
        fieldnames = reader.fieldnames
        writer = csv.DictWriter(outfile, fieldnames=fieldnames, quoting=csv.QUOTE_ALL)
        writer.writeheader()

        for row in reader:
            author_name = row['author']
            row['state'] = author_states.get(author_name, '')
            writer.writerow(row)

    # 显示统计
    print(f"\n{'=' * 70}")
    print(f"📊 统计结果:")
    print(f"   ✅ 高置信度: {stats['高置信度']} 人")
    print(f"   ⚠️  中置信度: {stats['中置信度']} 人")
    print(f"   ❌ 低置信度: {stats['低置信度']} 人")
    print(f"   🔍 论文验证失败: {stats['论文验证失败']} 人")
    print(f"{'=' * 70}")
    print(f"✅ 完成！")


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("用法: python3 author_state_finder_v2.py <input.csv> [output.csv] [limit]")
        print("示例: python3 author_state_finder_v2.py demo_input.csv demo_output_v2.csv 10")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.csv', '_v2.csv')
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    batch_find_states_strict(input_file, output_file, limit)
