#!/usr/bin/env python3
"""
State 填充主流程 - 整合所有模块，填充作者状态信息
"""

import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Any, Optional
from tqdm import tqdm

# 导入自定义模块
from profile_searcher import ProfileSearcher, SearchEngine
from llm_inference import LLMInference


class StateFiller:
    def __init__(self, search_engine: SearchEngine = SearchEngine.DUCKDUCKGO, serpapi_key: str = None):
        """
        初始化 State 填充器

        Args:
            search_engine: 搜索引擎类型
            serpapi_key: SerpAPI key（如果使用 SerpAPI）
        """
        self.searcher = ProfileSearcher(engine=search_engine, serpapi_key=serpapi_key)
        self.llm = LLMInference()

    async def fill_author_state(self, author_info: Dict[str, Any], max_candidates: int = 5) -> Dict[str, Any]:
        """
        为单个作者填充状态信息

        Args:
            author_info: 作者信息
            max_candidates: 最多验证的候选主页数量

        Returns:
            填充结果 {state, confidence, evidence, source_url}
        """
        author_id = author_info['author_id']
        author_name = author_info['author_name']

        result = {
            'author_id': author_id,
            'author_name': author_name,
            'state': '',
            'confidence': 0,
            'evidence': '',
            'source_url': '',
            'searched': False,
            'verified': False
        }

        try:
            # 步骤 1: 生成搜索查询
            print(f"   🔍 为 {author_name} 生成搜索查询...")
            queries = self.llm.generate_search_queries(author_info)

            if not queries:
                # 使用默认查询
                queries = self.searcher._generate_search_queries(author_info)

            print(f"      生成了 {len(queries)} 个查询")

            # 步骤 2: 执行搜索
            print(f"   🔎 执行搜索...")
            all_results = []

            for query in queries[:5]:  # 限制查询数量
                try:
                    if self.searcher.engine == SearchEngine.DUCKDUCKGO:
                        results = await self.searcher._search_duckduckgo(query)
                    else:
                        results = await self.searcher._search_serpapi(query)

                    all_results.extend(results)
                except Exception as e:
                    print(f"      ⚠️  查询失败: {e}")
                    continue

            print(f"      找到 {len(all_results)} 个结果")

            if not all_results:
                result['searched'] = True
                return result

            # 步骤 3: LLM 过滤结果
            print(f"   🤖 LLM 过滤结果...")
            filtered_results = self.llm.filter_search_results(all_results, author_info)

            # 只保留置信度 > 30 的结果
            high_conf_results = [r for r in filtered_results if r.get('confidence', 0) > 30]

            print(f"      过滤后: {len(high_conf_results)} 个高置信度结果")

            if not high_conf_results:
                result['searched'] = True
                return result

            # 步骤 4: 验证候选主页
            print(f"   🔐 验证候选主页...")
            for i, candidate in enumerate(high_conf_results[:max_candidates], 1):
                url = candidate['url']
                print(f"      [{i}/{min(len(high_conf_results), max_candidates)}] {url[:60]}...")

                # 获取页面内容
                page_content = await self.searcher.fetch_page_content(url, timeout=10)

                if not page_content:
                    print(f"         ❌ 无法获取页面内容")
                    continue

                # 验证身份
                verification = self.llm.verify_author_identity(page_content, author_info)

                print(f"         匹配度: {verification['confidence']}% - {verification['reason']}")

                if verification['confidence'] >= 60:
                    # 提取状态信息
                    state_info = self.llm.extract_author_state(page_content, author_info, url)

                    if state_info:
                        # 格式化状态
                        state_str = self.llm.format_state_string(state_info)

                        result['state'] = state_str
                        result['confidence'] = verification['confidence']
                        result['evidence'] = state_info.get('evidence', verification['reason'])
                        result['source_url'] = url
                        result['searched'] = True
                        result['verified'] = True

                        print(f"         ✅ 成功提取状态: {state_str}")
                        return result
                    else:
                        print(f"         ⚠️  身份匹配但无法提取状态信息")
                else:
                    print(f"         ❌ 身份不匹配")

            result['searched'] = True
            return result

        except Exception as e:
            print(f"      ❌ 处理出错: {e}")
            result['searched'] = True
            return result


async def batch_fill_states(authors: List[Dict], search_engine: SearchEngine = SearchEngine.DUCKDUCKGO,
                           serpapi_key: str = None, output_path: str = None):
    """
    批量填充作者状态

    Args:
        authors: 作者列表
        search_engine: 搜索引擎
        serpapi_key: SerpAPI key
        output_path: 输出文件路径
    """
    print("=" * 80)
    print("State 批量填充")
    print("=" * 80)
    print()

    filler = StateFiller(search_engine=search_engine, serpapi_key=serpapi_key)

    results = []
    success_count = 0
    failed_count = 0

    for i, author in enumerate(authors, 1):
        author_id = author.get('author_id', '')
        author_name = author.get('author_name', 'Unknown')

        print(f"\n[{i}/{len(authors)}] 处理: {author_name} (ID: {author_id})")
        print("-" * 80)

        result = await filler.fill_author_state(author)
        results.append(result)

        if result['verified']:
            success_count += 1
        else:
            failed_count += 1

        # 显示进度
        print(f"   当前进度: 成功 {success_count}, 失败 {failed_count}, 总计 {i}")

        # 避免请求过快
        await asyncio.sleep(1)

    # 保存结果
    if output_path:
        print(f"\n💾 保存结果到 {output_path}...")
        save_results_to_csv(results, output_path)

    # 统计
    print()
    print("=" * 80)
    print("📊 处理完成统计")
    print("=" * 80)
    print(f"总作者数: {len(authors)}")
    print(f"成功填充: {success_count} ({success_count/len(authors)*100:.1f}%)")
    print(f"失败/未找到: {failed_count} ({failed_count/len(authors)*100:.1f}%)")
    print("=" * 80)


def save_results_to_csv(results: List[Dict], output_path: str):
    """保存结果到 CSV"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    with open(output_path, 'w', encoding='utf-8-sig', newline='') as f:
        writer = csv.writer(f)
        writer.writerow([
            'author_id', 'author_name', 'state', 'confidence',
            'evidence', 'source_url', 'searched', 'verified'
        ])

        for result in results:
            writer.writerow([
                result['author_id'],
                result['author_name'],
                result['state'],
                result['confidence'],
                result['evidence'],
                result['source_url'],
                result['searched'],
                result['verified']
            ])

    print(f"   ✅ 结果已保存")


def load_sample_authors(csv_path: str) -> List[Dict]:
    """从 CSV 加载抽样作者数据"""
    authors = []

    with open(csv_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)

        for row in reader:
            author = {
                'author_id': row['author_id'],
                'author_name': row['author_name'],
                'total_papers': int(row['total_papers']),
                'latest_institution': row['latest_institution'],
                'institutions': json.loads(row['institutions']),
                'research_fields': json.loads(row['research_fields']),
                'papers': json.loads(row['paper_sample'])
            }
            authors.append(author)

    return authors


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='State 填充工具')
    parser.add_argument('--sample', type=str, help='抽样作者 CSV 文件路径')
    parser.add_argument('--output', type=str, help='输出文件路径')
    parser.add_argument('--engine', type=str, choices=['duckduckgo', 'serpapi'],
                       default='duckduckgo', help='搜索引擎')
    parser.add_argument('--serpapi-key', type=str, help='SerpAPI Key')

    args = parser.parse_args()

    # 默认路径
    sample_path = args.sample or '/home/apl064/apl/academic-scraper/temp/sample_authors.csv'
    output_path = args.output or '/home/apl064/apl/academic-scraper/temp/state_fill_results.csv'

    # 解析搜索引擎
    if args.engine == 'serpapi':
        if not args.serpapi_key:
            print("❌ 使用 SerpAPI 必须提供 --serpapi-key")
            return
        search_engine = SearchEngine.SERPAPI
    else:
        search_engine = SearchEngine.DUCKDUCKGO

    # 加载抽样数据
    print(f"📂 加载抽样数据: {sample_path}")
    authors = load_sample_authors(sample_path)
    print(f"   加载了 {len(authors)} 位作者")
    print()

    # 批量填充
    await batch_fill_states(
        authors=authors,
        search_engine=search_engine,
        serpapi_key=args.serpapi_key,
        output_path=output_path
    )


if __name__ == '__main__':
    asyncio.run(main())
