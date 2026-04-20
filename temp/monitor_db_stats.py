#!/usr/bin/env python3
"""
实时监控数据库记录数
每5秒打印一次 OpenAlex 和 semantic 表的记录数
"""

import clickhouse_connect
import time
from datetime import datetime

def get_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

def print_stats():
    """打印表统计信息"""
    try:
        client = get_client()

        # 查询 OpenAlex 统计
        result = client.query('''
            SELECT
                count(*) as total_rows,
                count(DISTINCT doi) as unique_papers
            FROM OpenAlex
        ''')
        openalex_total, openalex_unique = result.result_rows[0]

        # 查询 semantic 统计
        result = client.query('''
            SELECT
                count(*) as total_rows,
                count(DISTINCT doi) as unique_papers
            FROM semantic
        ''')
        semantic_total, semantic_unique = result.result_rows[0]

        # 打印结果
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}]")
        print(f"  OpenAlex: {openalex_total:,} 行 | {openalex_unique:,} 唯一论文")
        print(f"  semantic: {semantic_total:,} 行 | {semantic_unique:,} 唯一论文")
        print(f"  总计: {openalex_total + semantic_total:,} 行")
        print()

    except Exception as e:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"[{timestamp}] ❌ 查询失败: {e}")
        print()

def main():
    print("="*60)
    print("数据库记录数监控")
    print("每5秒刷新一次")
    print("按 Ctrl+C 停止")
    print("="*60)
    print()

    try:
        while True:
            print_stats()
            time.sleep(5)
    except KeyboardInterrupt:
        print("\n✅ 监控已停止")

if __name__ == "__main__":
    main()
