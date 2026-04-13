#!/usr/bin/env python3
"""
检查CSV文件中的重复记录 - 内存优化版
"""

import csv
import os
from collections import defaultdict
from datetime import datetime

OUTPUT_DIR = "/home/apl064/apl/academic-scraper/output"


def check_file_duplicates(filepath):
    """
    检查单个CSV文件的重复记录（内存优化版）

    Returns:
        dict: 包含重复记录信息的字典
    """
    if not os.path.exists(filepath):
        return None

    filename = os.path.basename(filepath)
    file_size = os.path.getsize(filepath)

    if file_size == 0:
        return {
            'filename': filename,
            'size': file_size,
            'total_rows': 0,
            'data_rows': 0,
            'duplicates': 0,
            'duplicate_groups': 0,
            'has_duplicates': False
        }

    # 只存储出现次数，不存储完整记录
    key_count = defaultdict(int)
    total_rows = 0

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            for row in reader:
                total_rows += 1

                # 创建唯一标识
                uid = row.get('uid', '')
                author = row.get('author', '')
                rank = row.get('rank', '')

                # 使用 uid + author + rank 作为唯一键
                unique_key = f"{uid}_{author}_{rank}"
                key_count[unique_key] += 1

    except Exception as e:
        return {
            'filename': filename,
            'error': str(e)
        }

    # 统计重复
    duplicates = sum(count - 1 for count in key_count.values() if count > 1)
    duplicate_groups = sum(1 for count in key_count.values() if count > 1)

    return {
        'filename': filename,
        'size': file_size,
        'total_rows': total_rows + 1,  # +1 for header
        'data_rows': total_rows,
        'duplicates': duplicates,
        'duplicate_groups': duplicate_groups,
        'has_duplicates': duplicates > 0,
        'unique_keys': len(key_count)
    }


def main():
    print("=" * 80)
    print("OpenAlex CSV 文件重复记录检查工具")
    print("=" * 80)
    print()

    # 获取所有CSV文件
    csv_files = []
    for filename in sorted(os.listdir(OUTPUT_DIR)):
        if filename.endswith('_openalex_papers.csv') and not filename.startswith('2026_3_'):
            csv_files.append(os.path.join(OUTPUT_DIR, filename))

    if not csv_files:
        print("❌ 未找到CSV文件")
        return

    print(f"📂 找到 {len(csv_files)} 个CSV文件")
    print()

    total_files = 0
    total_rows = 0
    total_duplicates = 0
    files_with_duplicates = []

    # 检查每个文件
    for filepath in csv_files:
        result = check_file_duplicates(filepath)

        if result.get('error'):
            print(f"❌ {result['filename']}: {result['error']}")
            continue

        total_files += 1
        total_rows += result.get('data_rows', 0)

        if result['has_duplicates']:
            files_with_duplicates.append(result)
            total_duplicates += result['duplicates']

            size_mb = result['size'] / (1024 * 1024)
            print(f"❌ {result['filename']}")
            print(f"   大小: {size_mb:.1f}MB")
            print(f"   总行数: {result['total_rows']:,}")
            print(f"   唯一记录: {result['unique_keys']:,}")
            print(f"   重复行数: {result['duplicates']:,} ({result['duplicate_groups']:,} 组)")
            print(f"   重复率: {result['duplicates']/result['data_rows']*100:.2f}%")
            print()
        else:
            size_mb = result['size'] / (1024 * 1024)
            print(f"✅ {result['filename']}: {result['data_rows']:,} 行 ({size_mb:.1f}MB) - 无重复")

    # 总结
    print()
    print("=" * 80)
    print("📊 总结")
    print("=" * 80)
    print(f"检查文件数: {total_files}")
    print(f"总记录数: {total_rows:,}")
    print(f"有重复的文件: {len(files_with_duplicates)}")
    print(f"总重复记录数: {total_duplicates:,}")

    if files_with_duplicates:
        print()
        print("⚠️  发现重复记录的文件:")
        for result in files_with_duplicates:
            print(f"   - {result['filename']} ({result['duplicates']:,} 条重复)")
    else:
        print()
        print("✅ 所有文件都没有重复记录！")

    print("=" * 80)


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
