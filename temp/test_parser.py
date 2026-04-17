#!/usr/bin/env python3
"""
测试修改后的parse_openalex_work函数是否能正确提取publication_date
"""

import sys
sys.path.insert(0, '/home/hkustgz/Us/academic-scraper/src')

import asyncio
import httpx
from openalex_fetcher import parse_openalex_work

async def test_publication_date_extraction():
    """测试publication_date字段提取"""

    # 测试URL - 搜索一篇论文
    test_url = "https://api.openalex.org/works?search=deep+learning&filter=publication_year:2024&per-page=3"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(test_url)
            response.raise_for_status()
            data = response.json()

            if data.get('results'):
                print("🧪 测试publication_date字段提取:")
                print("=" * 60)

                for i, work in enumerate(data['results'][:3], 1):
                    print(f"\n论文 {i}:")
                    parsed = parse_openalex_work(work)

                    print(f"  标题: {parsed['title'][:60]}...")
                    print(f"  📅 发表日期: {parsed.get('publication_date', '未找到')}")
                    print(f"  期刊: {parsed['journal']}")
                    print(f"  引用数: {parsed['citation_count']}")

                    # 检查是否有publication_date
                    if 'publication_date' not in parsed:
                        print(f"  ❌ 缺少publication_date字段")
                        return False

                print("\n✅ publication_date字段提取成功")
                return True
            else:
                print("❌ 没有找到论文数据")
                return False

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    result = asyncio.run(test_publication_date_extraction())
    if result:
        print("\n🚀 可以开始获取带有publication_date的论文数据了")
        print("📊 重新运行获取脚本后，dashboard将能显示按发表日期的趋势")
    else:
        print("\n❌ 测试失败，需要检查代码")