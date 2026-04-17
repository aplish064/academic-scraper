#!/usr/bin/env python3
"""
从CSV文件更新ClickHouse中的publication_date字段
基于文件路径日期，使用批量UPDATE优化性能
"""

import pandas as pd
import clickhouse_connect
from pathlib import Path
import re
from tqdm import tqdm
import time

CSV_DIR = Path("/home/hkustgz/Us/academic-scraper/output/openalex")

def extract_date_from_path(csv_path):
    """从CSV文件路径提取日期"""
    # 支持多种路径格式:
    # 2025/4/2/2025-04-02.csv
    # 2024/03/2024-03-05.csv
    match = re.search(r'(\d{4})[/-](\d{1,2})[/-](\d{1,2})', str(csv_path))
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None

def get_clickhouse_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

def update_publication_dates():
    """批量更新publication_date"""

    print("🚀 开始从CSV更新publication_date...")
    print("=" * 60)

    client = get_clickhouse_client()

    # 获取所有CSV文件
    csv_files = list(CSV_DIR.rglob("*.csv"))
    print(f"📁 找到 {len(csv_files)} 个CSV文件")

    # 按年份分组处理
    from collections import defaultdict
    files_by_year = defaultdict(list)

    for csv_file in csv_files:
        # 提取年份
        match = re.search(r'(\d{4})', str(csv_file))
        if match:
            year = match.group(1)
            files_by_year[year].append(csv_file)

    print(f"📅 按年份分组:")
    for year in sorted(files_by_year.keys())[::-1]:  # 降序
        print(f"  {year}: {len(files_by_year[year])} 个文件")

    # 询问处理策略
    print(f"\n💡 处理策略:")
    print(f"  1. 全部更新 ({len(csv_files)} 个文件)")
    print(f"  2. 仅更新最近年份 (2024, 2025)")
    print(f"  3. 测试模式 (处理10个文件)")

    # 默认选择测试模式
    choice = "1"  # 测试模式

    if choice == "3":
        # 测试模式：处理前10个文件
        csv_files = csv_files[:10]
        print(f"🧪 测试模式: 处理前10个文件")

    # 统计
    total_updated = 0
    total_errors = 0
    start_time = time.time()

    # 批量处理每个文件
    for csv_file in tqdm(csv_files, desc="处理CSV文件"):
        try:
            # 提取日期
            pub_date = extract_date_from_path(csv_file)
            if not pub_date:
                continue

            # 读取CSV（只读取需要的字段）
            df = pd.read_csv(csv_file,
                           usecols=['author', 'title', 'uid', 'doi'])

            # 批量UPDATE (按作者+标题匹配)
            # 为了性能，每次更新一批
            batch_size = 100
            for i in range(0, len(df), batch_size):
                batch = df.iloc[i:i+batch_size]

                # 构建UPDATE条件
                conditions = []
                params = []

                for _, row in batch.iterrows():
                    author = str(row['author']).replace("'", "''") if pd.notna(row['author']) else ''
                    title = str(row['title']).replace("'", "''") if pd.notna(row['title']) else ''
                    uid = str(row['uid']).replace("'", "''") if pd.notna(row['uid']) else ''

                    if author and title:
                        conditions.append(f"(author = '{author}' AND title = '{title}')")

                if conditions:
                    # 批量UPDATE
                    update_sql = f"""
                    ALTER TABLE academic_db.OpenAlex
                    UPDATE publication_date = '{pub_date}'
                    WHERE {' OR '.join(conditions)}
                    SETTINGS mutations_sync = 1
                    """

                    try:
                        client.command(update_sql)
                        total_updated += len(batch)
                    except Exception as e:
                        total_errors += 1
                        # 忽略错误，继续处理

        except Exception as e:
            print(f"❌ 处理文件失败 {csv_file.name}: {e}")
            total_errors += 1
            continue

    elapsed = time.time() - start_time

    print(f"\n✅ 处理完成!")
    print(f"  ⏱️  耗时: {elapsed:.1f}秒 ({elapsed/60:.1f}分钟)")
    print(f"  📊 更新记录: {total_updated:,} 条")
    print(f"  ❌ 错误: {total_errors}")

    # 验证更新结果
    print(f"\n🔍 验证更新结果...")
    result = client.query("""
    SELECT
        publication_date,
        count() as count
    FROM academic_db.OpenAlex
    WHERE publication_date != ''
    GROUP BY publication_date
    ORDER BY publication_date DESC
    LIMIT 10
    """)

    print(f"📅 publication_date分布:")
    for row in result.result_rows:
        print(f"  {row[0]}: {row[1]:,} 篇")

if __name__ == "__main__":
    update_publication_dates()