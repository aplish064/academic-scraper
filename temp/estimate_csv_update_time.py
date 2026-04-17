#!/usr/bin/env python3
"""
从CSV文件更新ClickHouse中的publication_date字段
基于文件路径日期和记录匹配
"""

import pandas as pd
import clickhouse_connect
from pathlib import Path
import re
from datetime import datetime
from tqdm import tqdm
import time

CSV_DIR = Path("/home/hkustgz/Us/academic-scraper/output/openalex")

def extract_date_from_path(csv_path):
    """从CSV文件路径提取日期"""
    # 路径格式: 2025/4/2/2025-04-02.csv 或 2024/03/2024-03-05.csv
    match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})[/-]', str(csv_path))
    if match:
        year, month, day = match.groups()
        try:
            return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
        except:
            return None
    return None

def get_clickhouse_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

def estimate_time():
    """评估处理时间"""

    print("📊 评估从CSV更新publication_date的时间...")
    print("=" * 60)

    # 统计CSV文件
    csv_files = list(CSV_DIR.rglob("*.csv"))
    print(f"📁 CSV文件数量: {len(csv_files)}")

    # 测试读取和处理速度
    print(f"\n🔍 测试处理速度...")

    client = get_clickhouse_client()

    # 取样测试
    sample_files = csv_files[:5]

    total_rows_processed = 0
    total_time = 0

    for csv_file in sample_files:
        start_time = time.time()

        # 提取日期
        pub_date = extract_date_from_path(csv_file)
        if not pub_date:
            continue

        # 读取CSV（只读取需要的字段）
        try:
            df = pd.read_csv(csv_file,
                           usecols=['author', 'title', 'uid', 'doi'],
                           nrows=100)  # 只读100行测试

            # 模拟匹配和更新（这里只是计时，不实际更新）
            process_time = time.time() - start_time
            total_time += process_time
            total_rows_processed += len(df)

        except Exception as e:
            print(f"  ❌ 处理文件失败 {csv_file.name}: {e}")

    if total_rows_processed > 0:
        avg_time_per_100rows = total_time / len(sample_files)
        avg_time_per_row = avg_time_per_100rows / 100

        print(f"  ✅ 处理速度测试:")
        print(f"     - 处理了 {total_rows_processed} 行")
        print(f"     - 耗时: {total_time:.2f}秒")
        print(f"     - 平均每100行: {avg_time_per_100rows:.2f}秒")
        print(f"     - 平均每行: {avg_time_per_row:.4f}秒")

    # 估算总时间
    print(f"\n⏱️  时间估算:")

    # 方案1: 基于文件数
    total_files = len(csv_files)
    est_time_by_files = total_files * avg_time_per_100rows * 10  # 假设每个文件1000行
    est_minutes_by_files = est_time_by_files / 60

    print(f"  📊 基于文件数: {est_minutes_by_files:,.0f} 分钟 ({est_minutes_by_files/60:,.1f} 小时)")

    # 方案2: 基于总行数
    # 从之前的统计，总行数约1.26亿
    total_rows = 125888282
    est_time_by_rows = total_rows * avg_time_per_row
    est_minutes_by_rows = est_time_by_rows / 60

    print(f"  📈 基于总行数: {est_minutes_by_rows:,.0f} 分钟 ({est_minutes_by_rows/60:,.1f} 小时)")

    # 方案3: 批量更新优化
    # 如果批量更新，可以减少网络往返
    batch_size = 10000
    num_batches = total_rows / batch_size
    batch_update_time = num_batches * 0.1  # 假设每个批次0.1秒
    batch_minutes = batch_update_time / 60

    print(f"  🚀 批量更新优化: {batch_minutes:,.0f} 分钟 ({batch_minutes/60:,.1f} 小时)")

    # 分年份处理
    print(f"\n📅 分年份处理:")

    years = ['2024', '2023', '2022', '2021', '2020']
    for year in years:
        year_files = list(CSV_DIR.glob(f"{year}/**/*.csv"))
        if year_files:
            year_rows = len(year_files) * 1000  # 估计
            year_time = year_rows * avg_time_per_row / 60
            print(f"  {year}: {len(year_files)} 文件, 预计 {year_time:,.0f} 分钟")

    print(f"\n💡 推荐策略:")
    print(f"  1. 分批处理，先处理最近年份")
    print(f"  2. 使用批量UPDATE减少网络往返")
    print(f"  3. 并行处理多个文件")
    print(f"  4. 基于关键字段匹配（author + title + doi）")

    return {
        'total_files': total_files,
        'total_rows': total_rows,
        'estimated_minutes': est_minutes_by_rows,
        'estimated_hours': est_minutes_by_rows / 60
    }

if __name__ == "__main__":
    result = estimate_time()

    print(f"\n🎯 总结:")
    print(f"  📁 需要处理: {result['total_files']:,} 个CSV文件")
    print(f"  📊 包含记录: {result['total_rows']:,} 条")
    print(f"  ⏱️  预计耗时: {result['estimated_minutes']:,.0f} 分钟 ({result['estimated_hours']:,.1f} 小时)")
    print(f"  ✅ 比API方案快: {445 / result['estimated_hours']:.1f} 倍")