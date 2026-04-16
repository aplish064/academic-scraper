#!/usr/bin/env python3
"""
LLM 推断器 - 使用 Anthropic API 进行智能推断
"""

import os
import json
from typing import Dict, List, Any, Optional
from anthropic import Anthropic


# API 配置（智谱AI）
ANTHROPIC_BASE_URL = "https://open.bigmodel.cn/api/anthropic"
ANTHROPIC_AUTH_TOKEN = "6cd56444f8ca470488d9902592695511.pJKcSLeQlEOJ7vqF"


class LLMInference:
    def __init__(self):
        """初始化 LLM 客户端"""
        self.client = Anthropic(
            base_url=ANTHROPIC_BASE_URL,
            api_key=ANTHROPIC_AUTH_TOKEN
        )

    def generate_search_queries(self, author_info: Dict[str, Any]) -> List[str]:
        """
        生成搜索查询

        Args:
            author_info: 作者信息

        Returns:
            搜索查询列表
        """
        name = author_info['author_name']
        institution = author_info.get('latest_institution', '')
        research_fields = author_info.get('research_fields', [])
        paper_titles = [p['title'] for p in author_info.get('papers', [])[:3]]

        prompt = f"""你是一个学术信息检索专家。我需要你帮我找到某位作者的个人主页。

作者信息：
- 姓名：{name}
- 论文样本：{', '.join(paper_titles[:3])}
- 研究领域：{', '.join(research_fields[:3]) if research_fields else '未知'}
- 最新机构：{institution}

请分析这个作者的背景，生成 5-8 个最可能找到其个人主页的搜索查询。
这些查询应该涵盖多种来源：
1. 学术平台（ORCID、Google Scholar 等）
2. 个人网站/博客
3. 代码仓库（GitHub、GitLab）
4. 机构主页
5. 学术社交网络（ResearchGate、LinkedIn 等）

请只输出搜索查询，每行一个，不要有编号或其他文字。"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                temperature=0.7,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            content = response.content[0].text
            queries = [q.strip() for q in content.strip().split('\n') if q.strip()]

            return queries[:10]

        except Exception as e:
            print(f"   ⚠️  LLM 生成查询失败: {e}")
            return []

    def filter_search_results(self, search_results: List[Dict], author_info: Dict) -> List[Dict]:
        """
        过滤和排序搜索结果

        Args:
            search_results: 搜索结果列表
            author_info: 作者信息

        Returns:
            过滤后的结果列表（带评分）
        """
        if not search_results:
            return []

        name = author_info['author_name']
        paper_titles = [p['title'] for p in author_info.get('papers', [])[:5]]
        research_fields = author_info.get('research_fields', [])

        # 构建搜索结果摘要
        results_summary = []
        for i, result in enumerate(search_results[:20], 1):
            results_summary.append(
                f"{i}. 标题: {result['title']}\n"
                f"   URL: {result['url']}\n"
                f"   摘要: {result.get('snippet', '')[:200]}"
            )

        prompt = f"""我需要判断以下搜索结果是否是目标作者的个人主页。

目标作者信息：
- 姓名：{name}
- 论文样本：{', '.join(paper_titles[:3])}
- 研究领域：{', '.join(research_fields[:3]) if research_fields else '未知'}

搜索结果：
{chr(10).join(results_summary)}

请分析每个结果，判断：
1. 是否是作者主页（是/否/不确定）
2. 主页类型（ORCID/GS/个人网站/GitHub/机构页面/LinkedIn/其他）
3. 置信度（0-100）
4. 理由（一句话）

请以 JSON 格式输出，是一个数组，每个元素包含：index, is_valid, type, confidence, reason
只输出 JSON，不要有其他文字。"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=2000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            content = response.content[0].text.strip()

            # 尝试解析 JSON
            # 移除可能的 markdown 代码块标记
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            evaluations = json.loads(content)

            # 为搜索结果添加评分
            scored_results = []
            for eval_item in evaluations:
                index = eval_item.get('index', 1) - 1  # 转换为 0-based
                if 0 <= index < len(search_results):
                    result = search_results[index].copy()
                    result['is_valid'] = eval_item.get('is_valid', '否') == '是'
                    result['type'] = eval_item.get('type', '未知')
                    result['confidence'] = eval_item.get('confidence', 0)
                    result['reason'] = eval_item.get('reason', '')
                    scored_results.append(result)

            # 按 confidence 排序
            scored_results.sort(key=lambda x: x['confidence'], reverse=True)

            return scored_results

        except Exception as e:
            print(f"   ⚠️  LLM 过滤失败: {e}")
            # 返回原始结果
            return search_results[:10]

    def extract_author_state(self, page_content: str, author_info: Dict, url: str) -> Optional[Dict]:
        """
        从页面内容中提取作者状态

        Args:
            page_content: 页面内容
            author_info: 作者信息
            url: 页面 URL

        Returns:
            作者状态信息或 None
        """
        name = author_info['author_name']
        paper_titles = [p['title'] for p in author_info.get('papers', [])[:3]]

        prompt = f"""从以下网页中提取作者的状态信息。

作者姓名：{name}
作者论文样本：{', '.join(paper_titles)}

网页 URL：{url}
网页内容：
{page_content[:8000]}

请提取以下信息（如果网页中没有明确提及，请返回 null）：

1. current_status: 当前状态（学生/博士后/助理教授/副教授/教授/研究员/工程师/其他）
2. institution: 机构名称
3. department: 部门/院系
4. position: 具体职位（如"博士三年级"、"高级算法工程师"等）
5. degree: 学位（如"博士"、"硕士"、"本科"，如果是学生）
6. year: 年级或入职年份（如果能推断）
7. evidence: 支持上述判断的证据（网页中的原句）

请以 JSON 格式输出，只包含上述字段。如果信息不足，相应字段填 null。
只输出 JSON，不要有其他文字。"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            content = response.content[0].text.strip()

            # 解析 JSON
            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            state_info = json.loads(content)

            # 验证是否有有效信息
            if not state_info.get('current_status') and not state_info.get('position'):
                return None

            return state_info

        except Exception as e:
            print(f"   ⚠️  LLM 提取失败: {e}")
            return None

    def verify_author_identity(self, page_content: str, author_info: Dict) -> Dict[str, Any]:
        """
        验证页面是否属于目标作者

        Args:
            page_content: 页面内容
            author_info: 作者信息

        Returns:
            验证结果 {is_match: bool, confidence: float, reason: str}
        """
        name = author_info['author_name']
        paper_titles = [p['title'] for p in author_info.get('papers', [])[:5]]

        prompt = f"""验证这个网页是否属于目标作者。

作者姓名：{name}
作者论文（至少有3篇匹配才算确认）：
{chr(10).join([f'- {p}' for p in paper_titles])}

网页内容：
{page_content[:8000]}

请检查：
1. 网页中是否明确提及作者姓名（或变体）
2. 网页中是否列出了作者的论文
3. 论文匹配度如何

请以 JSON 格式输出：
{{
    "is_match": true/false,
    "confidence": 0-100,
    "reason": "验证理由",
    "matched_papers": ["匹配的论文标题列表"]
}}

只输出 JSON，不要有其他文字。"""

        try:
            response = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=1000,
                temperature=0.3,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            content = response.content[0].text.strip()

            if content.startswith('```'):
                content = content.split('```')[1]
                if content.startswith('json'):
                    content = content[4:]

            verification = json.loads(content)

            return {
                'is_match': verification.get('is_match', False),
                'confidence': verification.get('confidence', 0),
                'reason': verification.get('reason', ''),
                'matched_papers': verification.get('matched_papers', [])
            }

        except Exception as e:
            print(f"   ⚠️  LLM 验证失败: {e}")
            return {
                'is_match': False,
                'confidence': 0,
                'reason': f'验证出错: {e}',
                'matched_papers': []
            }

    def format_state_string(self, state_info: Dict) -> str:
        """
        格式化状态信息为字符串

        Args:
            state_info: LLM 提取的状态信息

        Returns:
            格式化的状态字符串
        """
        if not state_info:
            return ''

        parts = []

        # 机构
        if state_info.get('institution'):
            parts.append(state_info['institution'])

        # 部门
        if state_info.get('department'):
            parts.append(state_info['department'])

        # 职位/学位
        if state_info.get('position'):
            parts.append(state_info['position'])
        elif state_info.get('degree'):
            parts.append(state_info['degree'])

        # 组合
        state_str = ' '.join(parts)

        return state_str.strip()


def main():
    """测试函数"""
    print("=" * 80)
    print("LLM 推断器测试")
    print("=" * 80)
    print()

    llm = LLMInference()

    # 测试生成搜索查询
    test_author = {
        'author_name': 'Geoffrey Hinton',
        'latest_institution': 'University of Toronto',
        'research_fields': ['Deep Learning', 'Neural Networks'],
        'papers': [
            {'title': 'Deep learning'},
            {'title': 'ImageNet Classification with Deep Convolutional Neural Networks'}
        ]
    }

    print("🔍 测试生成搜索查询...")
    queries = llm.generate_search_queries(test_author)
    print(f"   生成了 {len(queries)} 个查询:")
    for i, q in enumerate(queries, 1):
        print(f"   {i}. {q}")

    print()
    print("=" * 80)


if __name__ == '__main__':
    main()
