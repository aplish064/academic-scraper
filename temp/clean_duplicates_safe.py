#!/usr/bin/env python3
"""
安全的ClickHouse重复数据清理工具
- 增加超时时间到3600秒（1小时）
- 分步执行，一次只处理一个表
- 使用异步执行方式
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
    """创建ClickHouse客户端（增加超时时间）"""
    try:
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USERNAME,
            password=CH_PASSWORD,
            database=CH_DATABASE,
            connect_timeout=30,
            send_receive_timeout=3600  # 1小时超时
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
        return row[2]
    return 0


def optimize_table_async(client, table_name):
    """异步优化表并去重"""
    print(f"\n{'='*60}")
    print(f"开始优化 {table_name} 表（去重）")
    print(f"{'='*60}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("⚠️  这可能需要很长时间，请耐心等待...")

    start_time = time.time()

    try:
        # 分步执行：先不使用FINAL，只合并分区
        print("步骤1: 合并分区...")
        client.command(f"OPTIMIZE TABLE {table_name}")

        elapsed_step1 = time.time() - start_time
        print(f"✅ 步骤1完成，耗时: {elapsed_step1:.1f} 秒")

        # 然后使用DEDUPLICATE去重
        print("步骤2: 去除重复...")
        client.command(f"OPTIMIZE TABLE {table_name} DEDUPLICATE")

        elapsed_time = time.time() - start_time

        print(f"✅ {table_name} 优化完成")
        print(f"总耗时: {elapsed_time:.2f} 秒 ({elapsed_time/60:.1f} 分钟)")
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
            return True
        else:
            print(f"⚠️  {table_name} 仍有 {row[2]:,} 条重复记录")
            return False
    return False


def main():
    """主函数"""
    print("="*60)
    print("ClickHouse重复数据清理工具（安全版）")
    print("="*60)
    print(f"数据库: {CH_DATABASE}")
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("⚠️  请确保没有其他程序在访问这些表")
    print("="*60)

    # 创建客户端
    client = create_client()
    if not client:
        print("\n🛑 无法连接到ClickHouse，程序终止")
        return

    # 先处理较小的semantic表
    tables_to_clean = ['semantic', 'OpenAlex']  # 按大小排序

    for i, table in enumerate(tables_to_clean, 1):
        print(f"\n{'='*60}")
        print(f"处理第 {i}/{len(tables_to_clean)} 个表: {table}")
        print(f"{'='*60}")

        # 检查重复情况
        dup_count = check_duplicates(client, table)

        if dup_count == 0:
            print(f"✅ {table} 表没有重复记录，跳过")
            continue

        # 执行清理
        success = optimize_table_async(client, table)

        if success:
            # 验证效果
            verify_cleanup(client, table)
        else:
            print(f"❌ {table} 清理失败，跳过")

        # 如果不是最后一个表，等待一下再处理下一个
        if i < len(tables_to_clean):
            print(f"\n⏱️  等待10秒后处理下一个表...")
            time.sleep(10)

    # 总结
    print("\n" + "="*60)
    print("清理完成")
    print(f"完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
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
