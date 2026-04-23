#!/usr/bin/env python3
"""检查专利数据完整性和重复"""

import clickhouse_connect
import sys


def check_patent_duplicates():
    """检查 Patents 表中的重复记录"""
    client = clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

    print("正在检查重复专利号...")

    # 检查重复的 patent_id
    result = client.query('''
        SELECT patent_id, count(*) as cnt
        FROM Patents
        GROUP BY patent_id
        HAVING cnt > 1
        ORDER BY cnt DESC
        LIMIT 10
    ''')

    duplicates = result.result_rows

    if duplicates:
        print(f"\n发现 {len(duplicates)} 个重复的专利号:")
        for patent_id, count in duplicates:
            print(f"  {patent_id}: {count} 条记录")
    else:
        print("✅ 未发现重复专利号")

    # 检查空发明人
    print("\n正在检查空发明人记录...")

    result = client.query('''
        SELECT count(*) as cnt
        FROM Patents
        WHERE inventor_name = ''
    ''')

    empty_inventors = result.result_rows[0][0]

    if empty_inventors > 0:
        print(f"⚠️  发现 {empty_inventors} 条空发明人记录")
    else:
        print("✅ 未发现空发明人记录")

    # 统计总记录数
    result = client.query('SELECT count(*) FROM Patents')
    total = result.result_rows[0][0]

    print(f"\n总记录数: {total}")

    # 按来源统计
    result = client.query('''
        SELECT source, count(*) as cnt
        FROM Patents
        GROUP BY source
    ''')

    print("\n按来源统计:")
    for source, count in result.result_rows:
        print(f"  {source}: {count}")


if __name__ == '__main__':
    check_patent_duplicates()
