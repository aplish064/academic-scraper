#!/usr/bin/env python3
"""
测试OpenAlex API是否返回publication_date字段
"""

import httpx
import asyncio
from typing import Dict, Any

async def test_openalex_publication_date():
    """测试OpenAlex API的publication_date字段"""

    # 测试URL - 搜索机器学习论文
    test_url = "https://api.openalex.org/works?search=machine+learning&filter=publication_year:2023&per-page=1"

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            response = await client.get(test_url)
            response.raise_for_status()
            data = response.json()

            if data.get('results') and len(data['results']) > 0:
                work = data['results'][0]

                print("📚 OpenAlex论文数据测试:")
                print(f"论文ID: {work.get('id', 'N/A')}")
                print(f"标题: {work.get('title', 'N/A')[:80]}...")

                # 检查日期相关字段
                print(f"\n📅 日期字段:")

                # publication_date
                pub_date = work.get('publication_date', 'N/A')
                print(f"  publication_date: {pub_date}")

                # publication_year
                pub_year = work.get('publication_year', 'N/A')
                print(f"  publication_year: {pub_year}")

                # 检查primary_location中的日期信息
                primary_location = work.get('primary_location', {})
                if primary_location:
                    print(f"\n  primary_location信息:")
                    source = primary_location.get('source', {})
                    if source:
                        print(f"    source: {source.get('display_name', 'N/A')}")
                        print(f"    type: {source.get('type', 'N/A')}")

                # 检查type
                work_type = work.get('type', 'N/A')
                print(f"\n  类型: {work_type}")

                # 检查created_date
                created_date = work.get('created_date', 'N/A')
                print(f"  created_date: {created_date}")

                return pub_date is not None and pub_date != ''
            else:
                print("❌ 没有找到论文数据")
                return False

        except Exception as e:
            print(f"❌ 错误: {e}")
            return False

if __name__ == "__main__":
    result = asyncio.run(test_openalex_publication_date())
    if result:
        print("\n✅ OpenAlex API确实包含publication_date字段")
        print("✅ 可以使用该字段进行时间序列分析")
    else:
        print("\n❌ OpenAlex API不包含publication_date字段或字段为空")