#!/usr/bin/env python3
"""
State 填充测试脚本 - 完整流程测试
"""

import asyncio
import sys
import os

# 添加 temp 目录到 Python 路径
sys.path.insert(0, '/home/apl064/apl/academic-scraper/temp')

from author_aggregator import aggregate_author_data, sample_authors, save_sample_to_csv
from state_filler import batch_fill_states, load_sample_authors
from profile_searcher import SearchEngine


async def run_test_pipeline(
    sample_size: int = 50,
    search_engine: SearchEngine = SearchEngine.DUCKDUCKGO,
    serpapi_key: str = None
):
    """
    运行完整测试流程

    Args:
        sample_size: 抽样作者数量
        search_engine: 搜索引擎
        serpapi_key: SerpAPI key
    """
    print("=" * 80)
    print("State 填充测试流程")
    print("=" * 80)
    print()

    # 配置
    SAMPLE_CSV = '/home/apl064/apl/academic-scraper/temp/sample_authors.csv'
    RESULT_CSV = '/home/apl064/apl/academic-scraper/temp/state_fill_results.csv'

    # 步骤 1: 聚合作者数据
    print("📊 步骤 1: 聚合作主数据")
    print("-" * 80)

    authors = aggregate_author_data(limit=sample_size * 2)  # 多聚合一些，以便抽样

    print()

    # 步骤 2: 抽样
    print("🎲 步骤 2: 抽样作者")
    print("-" * 80)

    sampled_ids = sample_authors(authors, n=sample_size)
    save_sample_to_csv(authors, sampled_ids, SAMPLE_CSV)

    print()

    # 步骤 3: 填充状态
    print("🔍 步骤 3: 填充 State")
    print("-" * 80)
    print()

    # 加载抽样数据
    sample_authors_data = []
    for author_id in sampled_ids:
        if author_id in authors:
            sample_authors_data.append(authors[author_id])

    # 批量填充
    await batch_fill_states(
        authors=sample_authors_data,
        search_engine=search_engine,
        serpapi_key=serpapi_key,
        output_path=RESULT_CSV
    )

    print()
    print("=" * 80)
    print("✅ 测试完成！")
    print(f"📁 抽样数据: {SAMPLE_CSV}")
    print(f"📁 填充结果: {RESULT_CSV}")
    print("=" * 80)


async def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description='State 填充测试')
    parser.add_argument('--sample-size', type=int, default=50, help='抽样作者数量')
    parser.add_argument('--engine', type=str, choices=['duckduckgo', 'serpapi'],
                       default='duckduckgo', help='搜索引擎')
    parser.add_argument('--serpapi-key', type=str,
                       default='0b045d21cfcf3a5d546fc16d9206b2a5c322c40454e41885d1066cbec52479bb',
                       help='SerpAPI Key')

    args = parser.parse_args()

    # 解析搜索引擎
    if args.engine == 'serpapi':
        search_engine = SearchEngine.SERPAPI
    else:
        search_engine = SearchEngine.DUCKDUCKGO

    # 运行测试
    await run_test_pipeline(
        sample_size=args.sample_size,
        search_engine=search_engine,
        serpapi_key=args.serpapi_key
    )


if __name__ == '__main__':
    asyncio.run(main())
