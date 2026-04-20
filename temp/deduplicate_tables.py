#!/usr/bin/env python3
"""
去除 ClickHouse 表中的重复记录
- OpenAlex: 按 (doi, author_id, rank) 去重
- Semantic: 按 (doi, author_id, rank) 去重
"""

import clickhouse_connect
import time

def get_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

def deduplicate_table(table_name):
    """去重单个表"""
    print(f"\n{'='*60}")
    print(f"开始去重: {table_name}")
    print(f"{'='*60}")

    client = get_client()

    # 1. 检查当前行数
    print("\n📊 检查当前数据...")
    result = client.query(f'SELECT count(*) as cnt FROM {table_name}')
    total_before = result.result_rows[0][0]
    print(f"   去重前总行数: {total_before:,}")

    # 2. 创建去重后的临时表
    print("\n🔨 创建去重临时表...")
    temp_table = f"{table_name}_dedup_temp"

    # 删除旧临时表
    client.command(f'DROP TABLE IF EXISTS {temp_table}')

    # 创建新表（结构与原表相同）
    client.command(f'''
        CREATE TABLE {temp_table} AS {table_name}
        ENGINE = MergeTree()
        ORDER BY (doi, rank, author_id)
        SETTINGS index_granularity = 8192
    ''')
    print(f"   ✅ 临时表创建完成: {temp_table}")

    # 3. 插入去重后的数据
    print("\n💾 插入去重数据（这可能需要几分钟）...")
    start_time = time.time()

    client.command(f'''
        INSERT INTO {temp_table}
        SELECT DISTINCT *
        FROM {table_name}
    ''')

    elapsed = time.time() - start_time
    print(f"   ✅ 数据插入完成 (耗时: {elapsed:.1f}秒)")

    # 4. 验证去重后的行数
    print("\n📊 验证去重结果...")
    result = client.query(f'SELECT count(*) as cnt FROM {temp_table}')
    total_after = result.result_rows[0][0]
    print(f"   去重后行数: {total_after:,}")
    print(f"   删除的重复行: {total_before - total_after:,}")

    # 5. 删除原表
    print(f"\n🗑️  删除原表: {table_name}")
    client.command(f'DROP TABLE {table_name}')
    print(f"   ✅ 原表已删除")

    # 6. 重命名临时表为原表名
    print(f"\n✨ 重命名临时表: {temp_table} -> {table_name}")
    client.command(f'RENAME TABLE {temp_table} TO {table_name}')
    print(f"   ✅ 重命名完成")

    print(f"\n✅ {table_name} 去重完成！")
    print(f"   保留行数: {total_after:,}")
    print(f"   删除行数: {total_before - total_after:,}")

    return total_after

def main():
    print("="*60)
    print("ClickHouse 表去重工具")
    print("="*60)

    try:
        # 去重 OpenAlex
        openalex_final = deduplicate_table("OpenAlex")

        # 去重 semantic
        semantic_final = deduplicate_table("semantic")

        print("\n" + "="*60)
        print("✅ 全部去重完成！")
        print("="*60)
        print(f"OpenAlex 最终行数: {openalex_final:,}")
        print(f"semantic 最终行数: {semantic_final:,}")
        print(f"总计保留行数: {openalex_final + semantic_final:,}")

    except Exception as e:
        print(f"\n❌ 去重失败: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
