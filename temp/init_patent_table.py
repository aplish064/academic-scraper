#!/usr/bin/env python3
"""初始化 ClickHouse Patents 表"""

import clickhouse_connect

def create_patents_table():
    """创建 Patents 表"""
    client = clickhouse_connect.get_client(
        host='localhost',
        port=8123,
        database='academic_db'
    )

    # 删除已存在的表
    client.command('DROP TABLE IF EXISTS Patents')

    # 创建表
    create_table_sql = '''
    CREATE TABLE Patents (
        inventor_name String,
        inventor_rank UInt8,
        patent_id String,
        title String,
        applicants Array(String),
        assignees Array(String),
        application_date String,
        publication_date String,
        grant_date Nullable(String),
        patent_type String,
        classifications Array(String),
        citations UInt32,
        family_size UInt32,
        source String,
        fetched_at DateTime
    ) ENGINE = MergeTree()
    ORDER BY (inventor_name, publication_date)
    '''

    client.command(create_table_sql)
    print("✅ Patents 表创建成功")

if __name__ == '__main__':
    create_patents_table()
