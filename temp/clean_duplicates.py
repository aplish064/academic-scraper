#!/usr/bin/env python3
"""
清理ClickHouse表中的重复数据
使用OPTIMIZE TABLE ... FINAL DEDUPLICATE命令
"""

import clickhouse_connect
import time
from datetime import datetime

# ClickHouse 配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_USERNAME = 'default'
CH_PASSWORD = ''


def create_client():
    """创建ClickHouse客户端"""
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USERNAME,
            password=CH_PASSWORD,
            database=CH_DATABASE
        )
        print("✓ ClickHouse连接成功")
        return client
    except Exception as e:
        print(f"❌ ClickHouse连接失败: {e}")
        return None


def check_duplicates(client, table_name):
    """检查表的重复情况"""
    print(f"\n{'='*60}")
    print(f"检查 {table_name} 表的重复情况")
    print(f"{'='*60}")

    sql = f"""
    SELECT
        count() as total_rows,
        count(DISTINCT (author_id, doi)) as unique_rows,
        count() - count(DISTINCT (author_id, doi)) as duplicate_count,
        round((count() - count(DISTINCT (author_id, doi))) * 100.0 / count(), 2) as duplicate_rate
    FROM {table_name}
    """

    result = client.query(sql)
    if result and result.result_rows:
        row = result.result_rows[0]
        print(f"总行数: {row[0]:,}")
        print(f"唯一行数: {row[1]:,}")
        print(f"重复行数: {row[2]:,}")
        print(f"重复率: {row[3]}%")
        return row[2]  # 返回重复行数
    return 0


def optimize_table(client, table_name):
    """优化表并去重"""
    print(f"\n{'='*60}")
    print(f"开始优化 {table_name} 表（去重）")
    print(f"{'='*60}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    start_time = time.time()

    try:
        # 执行OPTIMIZE命令
        # DEDUPLICATE会删除重复的行
        # FINAL意味着强制合并所有分片
        client.command(f"OPTIMIZE TABLE {table_name} FINAL DEDUPLICATE")

        elapsed_time = time.time() - start_time

        print(f"✅ {table_name} 优化完成")
        print(f"耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.1f} 分钟)")
        return True

    except Exception as e:
        print(f"❌ {table_name} 优化失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def verify_cleanup(client, table_name):
    """验证清理效果"""
    print(f"\n{'='*60}")
    print(f"验证 {table_name} 清理效果")
    print(f"{'='*60}")

    sql = f"""
    SELECT
        count() as total_rows,
        count(DISTINCT (author_id, doi)) as unique_rows,
        count() - count(DISTINCT (author_id, doi)) as duplicate_count,
        round((count() - count(DISTINCT (author_id, doi))) * 100.0 / count(), 2) as duplicate_rate
    FROM {table_name}
    """

    result = client.query(sql)
    if result and result.result_rows:
        row = result.result_rows[0]
        print(f"总行数: {row[0]:,}")
        print(f"唯一行数: {row[1]:,}")
        print(f"重复行数: {row[2]:,}")
        print(f"重复率: {row[3]}%")

        if row[2] == 0:
            print(f"✅ {table_name} 已无重复记录")
        else:
            print(f"⚠️  {table_name} 仍有 {row[2]:,} 条重复记录")


def main():
    """主函数"""
    print("="*60)
    print("ClickHouse重复数据清理工具")
    print("="*60)
    print(f"数据库: {CH_DATABASE}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)

    # 创建客户端
    client = create_client()
    if not client:
        print("\n🛑 无法连接到ClickHouse，程序终止")
        return

    tables_to_clean = ['OpenAlex', 'semantic']
    results = {}

    # 第一步：检查重复情况
    print("\n" + "="*60)
    print("第一步：检查重复情况")
    print("="*60)

    for table in tables_to_clean:
        dup_count = check_duplicates(client, table)
        results[table] = {'before_dup': dup_count}

    # 第二步：执行清理
    print("\n" + "="*60)
    print("第二步：执行清理")
    print("="*60)
    print("⚠️  注意：这可能需要较长时间，请耐心等待...")

    for table in tables_to_clean:
        success = optimize_table(client, table)
        results[table]['success'] = success

    # 第三步：验证清理效果
    print("\n" + "="*60)
    print("第三步：验证清理效果")
    print("="*60)

    for table in tables_to_clean:
        verify_cleanup(client, table)

    # 总结
    print("\n" + "="*60)
    print("清理总结")
    print("="*60)

    for table, result in results.items():
        status = "✅ 成功" if result.get('success') else "❌ 失败"
        print(f"{table}: {status}")

    print(f"\n完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("="*60)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
