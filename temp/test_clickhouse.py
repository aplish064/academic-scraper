#!/usr/bin/env python3
"""
测试ClickHouse连接和数据
"""

import clickhouse_connect
import sys

def test_connection():
    """测试ClickHouse连接"""
    print("🔍 测试ClickHouse连接...")
    print()

    try:
        # 连接ClickHouse
        client = clickhouse_connect.get_client(
            host='localhost',
            port=8123,
            username='default',
            password=''
        )
        print("✓ 连接成功")

        # 测试查询
        result = client.query('SELECT 1')
        print(f"✓ 查询测试成功: {result.result_rows[0][0]}")

        # 检查数据库
        databases = client.query('SHOW DATABASES')
        db_list = [row[0] for row in databases.result_rows]
        print(f"✓ 数据库列表: {', '.join(db_list)}")

        # 检查academic_db数据库
        if 'academic_db' in db_list:
            print("✓ academic_db 数据库存在")

            # 检查表
            tables = client.query('SHOW TABLES FROM academic_db')
            table_list = [row[0] for row in tables.result_rows]
            print(f"✓ academic_db 表列表: {', '.join(table_list)}")

            # 检查papers表
            if 'papers' in table_list:
                # 获取记录数
                count_result = client.query('SELECT count() as count FROM academic_db.papers')
                count = count_result.result_rows[0][0]
                print(f"✓ papers 表包含 {count:,} 条记录")

                # 获取样本数据
                if count > 0:
                    sample = client.query('SELECT author, title, journal FROM academic_db.papers LIMIT 3')
                    print("📋 样本数据:")
                    for row in sample.result_rows:
                        print(f"  - {row[0][:30]}: {row[1][:50]}... ({row[2]})")
            else:
                print("⚠️  papers 表不存在，请先运行导入脚本")
        else:
            print("⚠️  academic_db 数据库不存在，请先运行导入脚本")

        print()
        print("✅ 所有测试通过！")

    except Exception as e:
        print(f"❌ 测试失败: {e}")
        sys.exit(1)

if __name__ == '__main__':
    test_connection()