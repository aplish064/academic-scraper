#!/usr/bin/env python3
"""
去除CSV文件中的重复记录
"""

import csv
import os
import shutil
from collections import defaultdict

OUTPUT_DIR = "/home/apl064/apl/academic-scraper/output/openalex"

# 有重复记录的文件列表
DUPLICATE_FILES = [
    "2026/01/2026-01-01.csv",
    "2025/01/2025-01-14.csv",
    "2025/01/2025-01-20.csv",
    "2025/01/2025-01-21.csv",
    "2025/01/2025-01-17.csv",
    "2025/01/2025-01-23.csv",
    "2025/01/2025-01-31.csv",
    "2025/01/2025-01-16.csv",
    "2025/01/2025-01-22.csv",
    "2025/01/2025-01-15.csv",
    "2025/05/2025-05-08.csv",
    "2025/05/2025-05-05.csv",
    "2025/05/2025-05-09.csv",
    "2025/05/2025-05-06.csv",
    "2025/05/2025-05-07.csv",
]


def remove_duplicates_from_file(filepath):
    """
    去除单个CSV文件中的重复记录

    Args:
        filepath: CSV文件路径

    Returns:
        dict: 处理结果
    """
    if not os.path.exists(filepath):
        return {
            'success': False,
            'error': f'文件不存在: {filepath}'
        }

    filename = os.path.basename(filepath)
    file_size_before = os.path.getsize(filepath)

    print(f"\n{'='*80}")
    print(f"处理文件: {filename}")
    print(f"{'='*80}")

    # 备份原文件
    backup_path = filepath + '.backup'
    print(f"📦 备份原文件...")
    shutil.copy2(filepath, backup_path)
    print(f"   ✅ 备份完成: {os.path.basename(backup_path)}")

    # 读取并去重
    print(f"🔍 读取并去重...")
    seen = set()
    unique_rows = []
    total_rows = 0
    duplicates_count = 0
    header = None

    try:
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)

            if reader.fieldnames:
                header = reader.fieldnames

            for row in reader:
                total_rows += 1

                # 创建唯一键
                uid = row.get('uid', '')
                author = row.get('author', '')
                rank = row.get('rank', '')
                unique_key = f"{uid}_{author}_{rank}"

                if unique_key not in seen:
                    seen.add(unique_key)
                    unique_rows.append(row)
                else:
                    duplicates_count += 1

                if total_rows % 100000 == 0:
                    print(f"   已处理: {total_rows:,} 行，发现重复: {duplicates_count:,} 行")

        print(f"   ✅ 读取完成: {total_rows:,} 行")
        print(f"   📊 统计:")
        print(f"      总行数: {total_rows:,}")
        print(f"      唯一记录: {len(unique_rows):,}")
        print(f"      重复记录: {duplicates_count:,} ({duplicates_count/total_rows*100:.2f}%)")

        # 写入去重后的数据
        print(f"\n💾 写入去重后的数据...")
        with open(filepath, 'w', encoding='utf-8-sig', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=header)
            writer.writeheader()
            writer.writerows(unique_rows)

        file_size_after = os.path.getsize(filepath)
        saved_space = file_size_before - file_size_after

        print(f"   ✅ 写入完成: {len(unique_rows):,} 行")
        print(f"   📊 文件大小:")
        print(f"      处理前: {file_size_before / (1024**2):.1f} MB")
        print(f"      处理后: {file_size_after / (1024**2):.1f} MB")
        print(f"      节省空间: {saved_space / (1024**2):.1f} MB ({saved_space/file_size_before*100:.1f}%)")

        # 验证结果
        print(f"\n🔍 验证结果...")
        with open(filepath, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            final_count = sum(1 for _ in reader)

        if final_count == len(unique_rows):
            print(f"   ✅ 验证通过: {final_count:,} 行")
        else:
            print(f"   ⚠️  警告: 行数不匹配！期望 {len(unique_rows):,}，实际 {final_count:,}")

        return {
            'success': True,
            'filename': filename,
            'total_rows': total_rows,
            'unique_rows': len(unique_rows),
            'duplicates_removed': duplicates_count,
            'size_before': file_size_before,
            'size_after': file_size_after,
            'saved_space': saved_space
        }

    except Exception as e:
        # 恢复备份
        print(f"\n❌ 发生错误: {e}")
        print(f"🔄 恢复备份...")
        shutil.copy2(backup_path, filepath)
        print(f"   ✅ 已恢复原文件")

        return {
            'success': False,
            'error': str(e)
        }


def main():
    print("=" * 80)
    print("CSV 文件去重工具")
    print("=" * 80)
    print()
    print(f"📂 输出目录: {OUTPUT_DIR}")
    print(f"📊 待处理文件: {len(DUPLICATE_FILES)} 个")
    print()

    # 统计信息
    total_files = 0
    total_rows_before = 0
    total_unique_rows = 0
    total_duplicates = 0
    total_saved_space = 0
    failed_files = []

    # 处理每个文件
    for relative_path in DUPLICATE_FILES:
        filepath = os.path.join(OUTPUT_DIR, relative_path)

        if not os.path.exists(filepath):
            print(f"⚠️  文件不存在，跳过: {relative_path}")
            failed_files.append(relative_path)
            continue

        result = remove_duplicates_from_file(filepath)

        if result['success']:
            total_files += 1
            total_rows_before += result['total_rows']
            total_unique_rows += result['unique_rows']
            total_duplicates += result['duplicates_removed']
            total_saved_space += result['saved_space']
        else:
            failed_files.append(relative_path)

    # 总结
    print()
    print("=" * 80)
    print("📊 处理总结")
    print("=" * 80)
    print(f"成功处理: {total_files} 个文件")
    print(f"处理失败: {len(failed_files)} 个文件")

    if total_files > 0:
        print()
        print(f"📈 数据统计:")
        print(f"   处理前行数: {total_rows_before:,}")
        print(f"   处理后行数: {total_unique_rows:,}")
        print(f"   删除重复: {total_duplicates:,} ({total_duplicates/total_rows_before*100:.2f}%)")
        print()
        print(f"💾 空间节省:")
        print(f"   节省空间: {total_saved_space / (1024**2):.1f} MB")
        print(f"   平均每文件: {total_saved_space / total_files / (1024**2):.1f} MB")

    if failed_files:
        print()
        print("⚠️  处理失败的文件:")
        for f in failed_files:
            print(f"   - {f}")

    print()
    print("=" * 80)
    print("✅ 去重完成！")
    print(f"📝 备份文件保存在原文件所在目录，后缀为 .backup")
    print("=" * 80)
    print()

    # 询问是否删除备份文件
    if total_files > 0:
        response = input("是否删除所有备份文件? (yes/no): ").strip().lower()
        if response in ['yes', 'y']:
            print("\n🗑️  删除备份文件...")
            deleted_count = 0
            for relative_path in DUPLICATE_FILES:
                filepath = os.path.join(OUTPUT_DIR, relative_path)
                backup_path = filepath + '.backup'
                if os.path.exists(backup_path):
                    os.remove(backup_path)
                    deleted_count += 1
                    print(f"   ✅ 已删除: {os.path.basename(backup_path)}")
            print(f"\n✅ 已删除 {deleted_count} 个备份文件")
        else:
            print("\nℹ️  保留所有备份文件")


if __name__ == '__main__':
    try:
        main()
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()
