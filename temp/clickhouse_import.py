#!/usr/bin/env python3
"""
将CSV数据导入到ClickHouse（包含publication_date）
"""

import clickhouse_connect
from pathlib import Path
import pandas as pd
from datetime import datetime
import sys
import re

# ClickHouse连接配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_USERNAME = 'default'
CH_PASSWORD = ''
CH_TABLE = 'OpenAlex'

# CSV数据目录
DATA_DIR = Path(__file__).parent.parent / 'output' / 'openalex'

def extract_date_from_filename(csv_file):
    """从CSV文件名提取发表日期"""
    filename = csv_file.name
    # 匹配格式: 2025-04-02.csv, 2024-03-05.csv
    match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', filename)
    if match:
        year, month, day = match.groups()
        return f"{year}-{month.zfill(2)}-{day.zfill(2)}"
    return None

def create_connection():
    """创建ClickHouse连接（先连接到default数据库）"""
    try:
        # 先连接到default数据库
        client = clickhouse_connect.get_client(
            host=CH_HOST,
            port=CH_PORT,
            username=CH_USERNAME,
            password=CH_PASSWORD,
            database='default'  # 先连接到default
        )
        print("✓ ClickHouse连接成功")
        return client
    except Exception as e:
        print(f"❌ 连接ClickHouse失败: {e}")
        return None

def create_database(client):
    """创建数据库"""
    try:
        client.command(f"CREATE DATABASE IF NOT EXISTS {CH_DATABASE}")
        print(f"✓ 数据库 {CH_DATABASE} 已就绪")
    except Exception as e:
        print(f"❌ 创建数据库失败: {e}")
        sys.exit(1)

def create_table(client):
    """创建数据表（包含所有CSV字段，自动去重）"""
    create_table_sql = f"""
    CREATE TABLE IF NOT EXISTS {CH_DATABASE}.{CH_TABLE} (
        author_id String,
        author String,
        uid String,
        doi String,
        title String,
        rank UInt8,
        journal String,
        citation_count UInt32,
        tag String,
        state String,
        institution_id String,
        institution_name String,
        institution_country String,
        institution_type String,
        raw_affiliation String,
        fwci Float32,
        citation_percentile UInt8,
        primary_topic String,
        is_retracted Bool,
        publication_date String
    )
    ENGINE = ReplacingMergeTree()
    ORDER BY (author_id, doi)
    SETTINGS index_granularity = 8192
    """

    try:
        client.command(create_table_sql)
        print(f"✓ 表 {CH_TABLE} 已就绪")

        # 检查表是否有数据
        result = client.query(f"SELECT count() as count FROM {CH_DATABASE}.{CH_TABLE}")
        count = result.result_rows[0][0]
        print(f"  当前记录数: {count:,}")

        # 如果表有数据，询问是否继续
        if count > 0:
            print(f"\n⚠️  表中已有 {count:,} 条记录！")
            print("继续导入会追加数据，不会删除现有记录。")
            response = input("是否继续导入？(y/N): ")
            if response.lower() != 'y':
                print("❌ 导入已取消")
                sys.exit(0)

    except Exception as e:
        print(f"❌ 创建表失败: {e}")
        sys.exit(1)

def import_csv_files(client, limit=None):
    """导入CSV文件"""

    # 获取所有CSV文件
    csv_files = list(DATA_DIR.rglob('*.csv'))
    csv_files = [f for f in csv_files if 'csv_backups' not in str(f)]

    if not csv_files:
        print("❌ 未找到CSV文件")
        return

    print(f"📊 找到 {len(csv_files)} 个CSV文件")
    if limit:
        csv_files = csv_files[:limit]
        print(f"  限制导入前 {limit} 个文件")

    total_imported = 0
    total_skipped = 0
    failed_files = []

    for idx, csv_file in enumerate(csv_files, 1):
        try:
            # 显示进度
            print(f"\n[{idx}/{len(csv_files)}] 处理: {csv_file.name}")

            # 读取CSV（使用多种方式尝试）
            df = None
            try:
                # 方法1：标准读取（增加缓冲区大小）
                df = pd.read_csv(csv_file,
                               encoding='utf-8-sig',
                               low_memory=False,
                               engine='c',  # C引擎更快
                               on_bad_lines='warn',  # 警告但不跳过
                               quoting=1)  # QUOTE_ALL
            except Exception as e:
                print(f"  ⚠️  标准读取失败: {str(e)[:100]}")
                try:
                    # 方法2：Python引擎 + 更宽松的解析
                    df = pd.read_csv(csv_file,
                                   encoding='utf-8-sig',
                                   low_memory=False,
                                   engine='python',  # Python引擎更宽容
                                   on_bad_lines='skip',  # 跳过错误行
                                   quoting=1,
                                   sep=',',
                                   quotechar='"',
                                   escapechar='\\')
                    print(f"  ⚠️  使用容错模式读取（跳过错误行）")
                except Exception as e2:
                    try:
                        # 方法3：逐块读取（处理大文件）
                        chunks = []
                        for chunk in pd.read_csv(csv_file,
                                               encoding='utf-8-sig',
                                               low_memory=False,
                                               engine='python',
                                               on_bad_lines='skip',
                                               chunksize=10000):
                            chunks.append(chunk)
                        df = pd.concat(chunks, ignore_index=True)
                        print(f"  ⚠️  使用分块读取模式")
                    except Exception as e3:
                        try:
                            # 方法4：最后尝试 - 只读取需要的列
                            required_cols = ['author_id', 'author', 'doi', 'title']
                            df = pd.read_csv(csv_file,
                                           encoding='utf-8-sig',
                                           low_memory=False,
                                           engine='python',
                                           on_bad_lines='skip',
                                           usecols=lambda x: x in required_cols or x in ['journal', 'citation_count', 'tag', 'state', 'institution_name', 'institution_country', 'institution_type', 'raw_affiliation', 'fwci', 'citation_percentile', 'primary_topic', 'is_retracted', 'uid', 'rank', 'institution_id'])
                            print(f"  ⚠️  使用列过滤模式读取")
                        except Exception as e4:
                            print(f"  ❌ 所有读取方法都失败")
                            failed_files.append((csv_file.name, f"读取失败: {str(e)[:100]}"))
                            continue

            if df is None or df.empty:
                print(f"  ⚠️  空文件，跳过")
                total_skipped += 1
                continue

            if df.empty:
                print(f"  ⚠️  空文件，跳过")
                total_skipped += 1
                continue

            # 检查必需字段
            required_columns = ['author', 'doi', 'title']
            missing_columns = [col for col in required_columns if col not in df.columns]
            if missing_columns:
                print(f"  ⚠️  缺少字段: {missing_columns}")
                total_skipped += 1
                del df
                continue

            # 从文件名提取发表日期
            publication_date = extract_date_from_filename(csv_file)
            if publication_date:
                print(f"  📅 发表日期: {publication_date}")
            else:
                print(f"  ⚠️  无法从文件名提取日期")

            # 数据类型转换和清理
            print(f"  📥 导入 {len(df)} 条记录...")

            # 准备数据（包含所有CSV字段）
            data_to_insert = []
            for _, row in df.iterrows():
                try:
                    record = {
                        'author_id': str(row.get('author_id', '')),
                        'author': str(row.get('author', '')),
                        'uid': str(row.get('uid', '')),
                        'doi': str(row.get('doi', '')),
                        'title': str(row.get('title', '')),
                        'rank': int(row.get('rank', 0) or 0),
                        'journal': str(row.get('journal', '')),
                        'citation_count': int(row.get('citation_count', 0) or 0),
                        'tag': str(row.get('tag', '')),
                        'state': str(row.get('state', '')),
                        'institution_id': str(row.get('institution_id', '')),
                        'institution_name': str(row.get('institution_name', '')),
                        'institution_country': str(row.get('institution_country', '')),
                        'institution_type': str(row.get('institution_type', '')),
                        'raw_affiliation': str(row.get('raw_affiliation', '')),
                        'fwci': float(row.get('fwci', 0) or 0),
                        'citation_percentile': int(row.get('citation_percentile', 0) or 0),
                        'primary_topic': str(row.get('primary_topic', '')),
                        'is_retracted': str(row.get('is_retracted', 'False')).lower() == 'true',
                        'publication_date': publication_date or ''
                    }
                    data_to_insert.append(record)
                except Exception as e:
                    continue

            # 批量插入
            if data_to_insert:
                try:
                    client.insert_df(f'{CH_DATABASE}.{CH_TABLE}', pd.DataFrame(data_to_insert))
                    total_imported += len(data_to_insert)
                    print(f"  ✓ 成功导入 {len(data_to_insert)} 条记录")
                except Exception as e:
                    print(f"  ❌ 插入失败: {e}")
                    failed_files.append((csv_file.name, str(e)))

            # 清理内存
            del df
            del data_to_insert

            # 每10个文件显示一次总体进度
            if idx % 10 == 0:
                print(f"\n📈 进度: 已导入 {total_imported:,} 条记录")

        except Exception as e:
            print(f"  ❌ 处理文件失败: {e}")
            failed_files.append((csv_file.name, str(e)))
            continue

    # 导入完成统计
    print(f"\n{'='*60}")
    print("📊 导入完成统计")
    print(f"{'='*60}")
    print(f"处理文件数: {len(csv_files)}")
    print(f"成功导入记录: {total_imported:,}")
    print(f"跳过文件数: {total_skipped}")
    print(f"失败文件数: {len(failed_files)}")

    if failed_files:
        print(f"\n❌ 失败文件列表:")
        for filename, error in failed_files[:10]:
            print(f"  {filename}: {error}")
        if len(failed_files) > 10:
            print(f"  ... 还有 {len(failed_files) - 10} 个文件")

    # 验证导入结果
    print(f"\n🔍 验证导入结果...")
    try:
        result = client.query(f"SELECT count() as count FROM {CH_DATABASE}.{CH_TABLE}")
        final_count = result.result_rows[0][0]
        print(f"✓ 表中总记录数: {final_count:,}")

        # 显示一些样本数据
        sample = client.query(f"SELECT author, title, journal, publication_date, citation_count FROM {CH_DATABASE}.{CH_TABLE} LIMIT 5")
        print(f"\n📋 样本数据:")
        for row in sample.result_rows:
            pub_date = row[3] if row[3] else 'N/A'
            print(f"  - {row[0][:30]}: {row[1][:50]}... ({row[2]}) [{pub_date}]")

    except Exception as e:
        print(f"❌ 验证失败: {e}")

def main():
    """主函数"""
    print("🚀 ClickHouse CSV数据导入工具")
    print(f"{'='*60}")

    # 创建连接
    print("📡 连接ClickHouse...")
    client = create_connection()
    if not client:
        return

    # 创建数据库
    print("📦 创建数据库...")
    create_database(client)

    # 创建表
    print("📋 创建数据表...")
    create_table(client)

    # 导入数据
    print("📥 开始导入CSV数据...")
    print()

    # 可以通过命令行参数限制导入的文件数量用于测试
    limit = None
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])
        print(f"⚠️  测试模式：只导入前 {limit} 个文件")

    import_csv_files(client, limit)

    print(f"\n{'='*60}")
    print("✅ 导入完成！")
    print(f"{'='*60}")

if __name__ == '__main__':
    main()