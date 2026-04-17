#!/usr/bin/env python3
"""
测试OpenAlex数据获取脚本是否能正确获取publication_date
"""

import asyncio
import httpx
import clickhouse_connect
from datetime import datetime
import sys
import os

# 添加src目录到路径
sys.path.append('/home/hkustgz/Us/academic-scraper/src')

# OpenAlex API 配置
OPENALEX_API_KEY = "toZBE5tNglH7oDydLefrKc"
OPENALEX_EMAIL = "13360197039@163.com"

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'OpenAlex'

async def test_fetch_and_store():
    """测试获取今天的数据并写入ClickHouse"""

    print("🧪 测试OpenAlex数据获取脚本")
    print("=" * 50)

    # 测试日期：2026-04-17
    test_date = "2026-04-17"

    # 1. 测试API调用
    print(f"\n📡 步骤1: 从OpenAlex API获取 {test_date} 的数据...")

    params = {
        'filter': f'from_publication_date:{test_date},to_publication_date:{test_date},type:article',
        'per-page': 10,  # 只获取10条测试
        'api_key': OPENALEX_API_KEY,
        'mailto': OPENALEX_EMAIL
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get('https://api.openalex.org/works', params=params)
        data = response.json()

        if 'results' not in data:
            print(f"❌ API调用失败: {data}")
            return

        results = data['results']
        print(f"✅ 获取到 {len(results)} 条记录")

        # 2. 检查publication_date字段
        print(f"\n📅 步骤2: 检查publication_date字段...")
        has_pub_date = 0
        no_pub_date = 0

        for work in results:
            pub_date = work.get('publication_date', '')
            if pub_date:
                has_pub_date += 1
            else:
                no_pub_date += 1

        print(f"   有publication_date: {has_pub_date} 条")
        print(f"   无publication_date: {no_pub_date} 条")

        # 3. 显示样本数据
        print(f"\n📋 步骤3: 样本数据...")
        for i, work in enumerate(results[:3], 1):
            title = work.get('title', '无标题')[:40]
            pub_date = work.get('publication_date', '无')
            author = work.get('authorships', [{}])[0].get('author', {}).get('display_name', '未知') if work.get('authorships') else '未知'
            print(f"   {i}. {title}...")
            print(f"      作者: {author}")
            print(f"      发表日期: {pub_date}")

        # 4. 测试ClickHouse写入
        print(f"\n💾 步骤4: 测试ClickHouse连接...")
        try:
            client = clickhouse_connect.get_client(
                host=CH_HOST,
                port=CH_PORT,
                database=CH_DATABASE
            )
            print("✅ ClickHouse连接成功")

            # 检查表结构
            print(f"\n🔍 步骤5: 检查表结构...")
            result = client.query(f"DESCRIBE TABLE {CH_TABLE}")
            pub_date_type = None
            for row in result.result_rows:
                if row[0] == 'publication_date':
                    pub_date_type = row[1]
                    break

            if pub_date_type:
                print(f"✅ publication_date字段存在，类型: {pub_date_type}")
            else:
                print(f"❌ publication_date字段不存在")
                return

            # 5. 查询今天是否有数据
            print(f"\n📊 步骤6: 查询今天导入的数据...")
            result = client.query(f"""
                SELECT count()
                FROM {CH_TABLE}
                WHERE import_date = today()
            """)
            today_count = result.result_rows[0][0]
            print(f"   今天导入的数据: {today_count:,} 条")

            # 查询今天导入数据中publication_date情况
            result = client.query(f"""
                SELECT
                    count() as total,
                    countIf(publication_date != '') as has_pub_date,
                    countIf(publication_date == '') as no_pub_date
                FROM {CH_TABLE}
                WHERE import_date = today()
            """)
            total, has_date, no_date = result.result_rows[0]
            print(f"   有publication_date: {has_date:,} 条")
            print(f"   无publication_date: {no_date:,} 条")

            if total > 0:
                percentage = (has_date / total) * 100
                print(f"   覆盖率: {percentage:.2f}%")

            print(f"\n✅ 测试完成！")
            print(f"\n💡 结论:")
            if has_date == 0:
                print(f"   ❌ 今天导入的数据都没有publication_date")
                print(f"   建议运行update_publication_date_from_csv.py补充数据")
            else:
                print(f"   ✅ 数据获取脚本正在正常获取publication_date")

        except Exception as e:
            print(f"❌ ClickHouse错误: {e}")

if __name__ == '__main__':
    asyncio.run(test_fetch_and_store())
