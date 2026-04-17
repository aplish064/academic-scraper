#!/usr/bin/env python3
"""
评估从OpenAlex API获取publication_date需要的时间
"""

import asyncio
import httpx
from pathlib import Path
import pandas as pd
from tqdm import tqdm
import time

CSV_DIR = Path("/home/hkustgz/Us/academic-scraper/output/openalex")

async def estimate_time():
    """评估获取publication_date的时间"""

    print("📊 评估OpenAlex publication_date获取时间...")
    print("=" * 60)

    # 统计CSV文件
    csv_files = list(CSV_DIR.rglob("*.csv"))
    print(f"📁 CSV文件数量: {len(csv_files)}")

    # 统计总记录数（抽样）
    sample_files = csv_files[:10]  # 取前10个文件作为样本
    total_sample_rows = 0

    for csv_file in sample_files:
        try:
            df = pd.read_csv(csv_file, usecols=['uid'])
            total_sample_rows += len(df)
        except Exception as e:
            print(f"  ❌ 读取文件失败 {csv_file.name}: {e}")

    avg_rows_per_file = total_sample_rows / len(sample_files)
    estimated_total_rows = avg_rows_per_file * len(csv_files)

    print(f"📈 估计总记录数: {estimated_total_rows:,.0f}")
    print(f"📊 平均每文件: {avg_rows_per_file:,.0f} 条记录")

    # 测试API调用速度
    print(f"\n🔍 测试OpenAlex API速度...")

    # 从样本文件获取一些UID
    sample_uids = []
    for csv_file in sample_files[:3]:
        try:
            df = pd.read_csv(csv_file, usecols=['uid'])
            uids = df['uid'].dropna().unique()[:10]  # 每个文件取10个
            sample_uids.extend(uids)
        except:
            pass

    sample_uids = list(set(sample_uids))[:20]  # 取20个唯一的UID

    print(f"  测试 {len(sample_uids)} 个UID的API调用速度...")

    start_time = time.time()

    async with httpx.AsyncClient(timeout=30.0) as client:
        for uid in sample_uids:
            try:
                # 提取OpenAlex ID
                if '/W' in uid:
                    openalex_id = uid.split('/W')[-1]
                    url = f"https://api.openalex.org/works/{openalex_id}"

                    response = await client.get(url)
                    if response.status_code == 200:
                        data = response.json()
                        pub_date = data.get('publication_date', '')

            except Exception as e:
                pass

    elapsed = time.time() - start_time
    avg_time_per_request = elapsed / len(sample_uids)

    print(f"  ✅ {len(sample_uids)} 个请求耗时: {elapsed:.2f}秒")
    print(f"  📊 平均每请求: {avg_time_per_request:.2f}秒")
    print(f"  📈 每秒请求数: {1/avg_time_per_request:.1f}")

    # 估算总时间
    # 假设每个UID需要一次API调用，并且可以并发
    concurrent_requests = 20  # 并发请求数
    requests_per_second = concurrent_requests / avg_time_per_request
    total_uids = int(estimated_total_rows)  # 每条记录一个UID

    # 但是要去重，因为同一篇论文可能有多个作者
    unique_papers_ratio = 0.3  # 假设30%是唯一论文
    unique_papers = int(total_uids * unique_papers_ratio)

    total_requests = unique_papers
    estimated_seconds = total_requests / requests_per_second
    estimated_minutes = estimated_seconds / 60
    estimated_hours = estimated_minutes / 60

    print(f"\n⏱️  时间估算:")
    print(f"  📊 唯一论文数: {unique_papers:,}")
    print(f"  🔗 需要API调用: {total_requests:,}")
    print(f"  ⚡ 并发请求: {concurrent_requests}")
    print(f"  ⏱️  预计耗时:")
    print(f"     - {estimated_minutes:,.0f} 分钟")
    print(f"     - {estimated_hours:,.1f} 小时")

    # 不同并发方案
    print(f"\n🚀 不同并发方案:")
    for concurrent in [10, 20, 50, 100]:
        requests_per_sec = concurrent / avg_time_per_request
        est_minutes = total_requests / requests_per_sec / 60
        print(f"  并发{concurrent:3d}: {est_minutes:,.0f} 分钟 ({est_minutes/60:,.1f} 小时)")

    # 更现实的方案：批量处理
    print(f"\n💡 推荐方案:")
    print(f"  1. 先更新最近获取的数据（2024年）")
    print(f"  2. 使用高并发（50-100）")
    print(f"  3. 分批处理，避免API限制")

    # 检查2024年的数据量
    csv_2024 = list(CSV_DIR.glob("2024/**/*.csv"))
    print(f"\n📅 2024年数据:")
    print(f"  📁 文件数: {len(csv_2024)}")

    if len(csv_2024) > 0:
        # 统计2024年数据
        sample_2024 = csv_2024[:20]
        rows_2024 = 0
        for csv_file in sample_2024:
            try:
                df = pd.read_csv(csv_file, usecols=['uid'])
                rows_2024 += len(df)
            except:
                pass

        avg_rows_2024 = rows_2024 / len(sample_2024)
        est_rows_2024 = avg_rows_2024 * len(csv_2024)
        unique_2024 = int(est_rows_2024 * unique_papers_ratio)

        time_2024 = unique_2024 / (50 / avg_time_per_request) / 60

        print(f"  📊 估计记录数: {est_rows_2024:,.0f}")
        print(f"  📄 唯一论文数: {unique_2024:,}")
        print(f"  ⏱️  预计耗时(并发50): {time_2024:,.0f} 分钟")

if __name__ == "__main__":
    asyncio.run(estimate_time())