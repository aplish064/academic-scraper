#!/usr/bin/env python3
"""
作者学历状态查找工具
结合 Semantic Scholar API 和大模型联网搜索
"""

import os
import requests
import anthropic
import csv
import json
import time
from typing import Dict, Any, Optional, List
from datetime import datetime


# 配置
ANTHROPIC_API_KEY = "6cd56444f8ca470488d9902592695511.pJKcSLeQlEOJ7vqF"
ANTHROPIC_BASE_URL = "https://open.bigmodel.cn/api/anthropic"
SEMANTIC_SCHOLAR_API = "https://api.semanticscholar.org/graph/v1"
SEMANTIC_SCHOLAR_API_KEY = "7Tts2u4jXLaebjvFPICkE7kpTJQvUaYG4byRSpBp"

# 初始化 Claude 客户端
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    base_url=ANTHROPIC_BASE_URL,
    timeout=3000  # 50 分钟
)


def search_semantic_scholar(author_name: str) -> Optional[Dict[str, Any]]:
    """
    使用 Semantic Scholar API 搜索作者

    Args:
        author_name: 作者姓名

    Returns:
        作者信息或 None
    """
    url = f"{SEMANTIC_SCHOLAR_API}/author/search"

    params = {
        'query': author_name,
        'fields': 'authorId,name,papers,affiliations,homepage,externalOrganizations,papers.title,papers.year,papers.citationCount',
        'limit': 5
    }

    try:
        headers = {}
        if SEMANTIC_SCHOLAR_API_KEY:
            headers['x-api-key'] = SEMANTIC_SCHOLAR_API_KEY

        response = requests.get(
            url,
            params=params,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        data = response.json()
        results = data.get('data', [])

        if not results:
            return None

        # 返回最匹配的作者
        return results[0]

    except Exception as e:
        print(f"      ❌ Semantic Scholar 错误: {e}")
        return None


def search_author_with_llm(
    author_name: str,
    papers: List[Dict[str, Any]],
    affiliations: List[str] = None
) -> Dict[str, Any]:
    """
    使用大模型联网搜索作者信息

    Args:
        author_name: 作者姓名
        papers: 论文列表
        affiliations: 单位列表

    Returns:
        查找结果
    """

    # 构建论文上下文
    papers_context = ""
    if papers:
        papers_context = "\n该作者的论文（用于验证身份）：\n"
        for i, paper in enumerate(papers[:5], 1):
            papers_context += f"{i}. {paper.get('title', 'N/A')} ({paper.get('year', 'N/A')})\n"

    # 构建单位上下文
    affiliation_context = ""
    if affiliations:
        affiliation_context = f"\n已知单位：{', '.join(affiliations[:3])}"

    prompt = f"""请帮我查找作者 "{author_name}" 的学历信息。{papers_context}{affiliation_context}

请使用联网搜索功能，查找以下信息：
1. 作者的个人主页（大学官网、Google Scholar、ResearchGate等）
2. 作者的教育背景（博士/硕士/本科）
3. 如果是在读学生，请尝试确定年级（如博三、硕二等）

请返回 JSON 格式：
{{
    "status": "博士生/硕士生/本科生/博士后/教师/未知",
    "year": "年级（如适用）：3（表示博三/硕三）",
    "institution": "所在机构",
    "confidence": "高/中/低",
    "sources": ["信息来源列表"],
    "reasoning": "推断理由"
}}

注意：
- 请务必通过论文标题验证作者身份
- 如果找到多个同名作者，请选择论文匹配度最高的
- 如果找不到明确信息，请基于可用信息合理推断
- 置信度"高"表示在官方网站找到明确说明
- 置信度"中"表示在个人主页或CV中找到信息
- 置信度"低"表示基于间接信息推断"""

    try:
        response = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=2000,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )

        result_text = response.content[0].text

        # 解析 JSON
        json_start = result_text.find('{')
        json_end = result_text.rfind('}') + 1

        if json_start >= 0 and json_end > json_start:
            json_str = result_text[json_start:json_end]
            result = json.loads(json_str)
            return result
        else:
            return {
                "status": "未知",
                "confidence": "低",
                "sources": [],
                "reasoning": "LLM 返回格式无法解析"
            }

    except Exception as e:
        return {
            "status": "未知",
            "confidence": "低",
            "sources": [],
            "reasoning": f"LLM 调用失败: {e}"
        }


def find_author_state(row: Dict[str, Any]) -> Dict[str, Any]:
    """
    查找单行作者的学历状态

    Args:
        row: CSV 行数据

    Returns:
        查找结果
    """
    author_name = row['author']
    print(f"\n🔍 查找作者: {author_name}")

    # 步骤1：Semantic Scholar 搜索
    print("  1️⃣  Semantic Scholar 搜索...")
    ss_info = search_semantic_scholar(author_name)

    affiliations = []
    papers_for_llm = []

    if ss_info:
        print(f"     ✅ 找到作者 ID: {ss_info.get('authorId')}")

        # 提取单位信息
        external_orgs = ss_info.get('externalOrganizations', [])
        if external_orgs:
            affiliations = [org.get('name', '') for org in external_orgs]

        # 提取论文信息（用于 LLM 验证）
        ss_papers = ss_info.get('papers', [])
        papers_for_llm = [
            {
                'title': p.get('title', ''),
                'year': p.get('year', '')
            }
            for p in ss_papers[:5]
        ]

        # 检查是否有教育背景
        if 'education' in ss_info and ss_info['education']:
            education = ss_info['education'][0]
            degree = education.get('degree', '')

            if 'PhD' in degree or '博士' in degree:
                return {
                    "status": "博士生",
                    "institution": education.get('institution', ''),
                    "confidence": "高",
                    "sources": ["Semantic Scholar"],
                    "reasoning": f"API 返回教育背景: {degree}"
                }
    else:
        print("     ⚠️  未找到")
        # 使用 CSV 中的论文信息
        papers_for_llm = [{
            'title': row['title'],
            'year': '2024'  # 从文件路径推断
        }]

    # 步骤2：LLM 联网搜索
    print("  2️⃣  LLM 联网搜索...")
    llm_result = search_author_with_llm(
        author_name,
        papers_for_llm,
        affiliations
    )

    print(f"     结果: {llm_result.get('status', '未知')} (置信度: {llm_result.get('confidence', 'N/A')})")

    return llm_result


def batch_find_states(csv_file: str, output_file: str, limit: int = None):
    """
    批量查找作者状态

    Args:
        csv_file: 输入 CSV 文件
        output_file: 输出 CSV 文件
        limit: 限制处理数量（测试用）
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

    # 去重作者（基于姓名）
    unique_authors = {}
    for row in authors:
        name = row['author']
        if name not in unique_authors:
            unique_authors[name] = []

        unique_authors[name].append(row)

    print(f"👥 去重后：{len(unique_authors)} 个唯一作者\n")

    # 查找每个作者的状态
    author_states = {}

    for i, author_name in enumerate(unique_authors.keys(), 1):
        print(f"[{i}/{len(unique_authors)}] {author_name}")

        # 使用第一个出现的行作为参考
        sample_row = unique_authors[author_name][0]
        result = find_author_state(sample_row)

        # 格式化状态
        status = result.get('status', '未知')
        year = result.get('year', '')
        confidence = result.get('confidence', '低')

        if year:
            state_str = f"{status}（{year}）"
        else:
            state_str = status

        state_str += f" [置信度:{confidence}]"

        author_states[author_name] = state_str

        print(f"  ✅ 最终状态: {state_str}")

        # 避免请求过快
        time.sleep(3)

    # 写入输出文件
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

    print(f"✅ 完成！")


# 主程序
if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("用法: python author_state_finder.py <input.csv> [output.csv] [limit]")
        print("示例: python author_state_finder.py data.csv output.csv 10")
        sys.exit(1)

    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else input_file.replace('.csv', '_with_state.csv')
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None

    batch_find_states(input_file, output_file, limit)
