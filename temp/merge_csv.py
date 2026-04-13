#!/usr/bin/env python3
"""
合并CSV文件 - 将 2026_3_openalex_papers.csv 合并到 2026_03_openalex_papers.csv
"""

import csv
import os
import shutil
from datetime import datetime

OUTPUT_DIR = "/home/apl064/apl/academic-scraper/output"
SOURCE_FILE = os.path.join(OUTPUT_DIR, "2026_3_openalex_papers.csv")
TARGET_FILE = os.path.join(OUTPUT_DIR, "2026_03_openalex_papers.csv")


def merge_csv_files(source_path, target_path):
    """
    合并两个CSV文件

    Args:
        source_path: 源文件路径（将被合并）
        target_path: 目标文件路径（合并到这个文件）
    """
    print("=" * 80)
    print("CSV 文件合并工具")
    print("=" * 80)
    print()

    # 检查文件是否存在
    if not os.path.exists(source_path):
        print(f"❌ 源文件不存在: {source_path}")
        return False

    if not os.path.exists(target_path):
        print(f"❌ 目标文件不存在: {target_path}")
        return False

    # 获取文件大小
    source_size = os.path.getsize(source_path)
    target_size_before = os.path.getsize(target_path)

    print(f"📂 源文件: {os.path.basename(source_path)}")
    print(f"   大小: {source_size / (1024**3):.2f} GB")
    print()
    print(f"📂 目标文件: {os.path.basename(target_path)}")
    print(f"   大小: {target_size_before / (1024**3):.2f} GB")
    print()

    # 备份目标文件
    backup_path = target_path + '.backup'
    print(f"💾 备份目标文件到: {os.path.basename(backup_path)}")
    shutil.copy2(target_path, backup_path)
    print("   ✅ 备份完成")
    print()

    # 统计行数
    print("📊 统计行数...")
    with open(source_path, 'r', encoding='utf-8-sig') as f:
        source_lines = sum(1 for _ in f) - 1  # 减去表头

    with open(target_path, 'r', encoding='utf-8-sig') as f:
        target_lines_before = sum(1 for _ in f) - 1  # 减去表头

    print(f"   源文件: {source_lines:,} 行")
    print(f"   目标文件: {target_lines_before:,} 行")
    print()

    # 读取源文件的表头，确保格式一致
    with open(source_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        source_header = next(reader)

    with open(target_path, 'r', encoding='utf-8-sig') as f:
        reader = csv.reader(f)
        target_header = next(reader)

    if source_header != target_header:
        print("⚠️  警告: 两个文件的表头不一致")
        print(f"   源文件表头: {source_header}")
        print(f"   目标文件表头: {target_header}")
        print()
        response = input("是否继续合并? (y/n): ")
        if response.lower() != 'y':
            print("❌ 取消合并")
            return False

    # 合并文件
    print("🔄 开始合并...")
    merged_count = 0
    skipped_header = False

    with open(source_path, 'r', encoding='utf-8-sig') as source_file, \
         open(target_path, 'a', encoding='utf-8-sig', newline='') as target_file:

        reader = csv.reader(source_file)
        writer = csv.writer(target_file)

        for row in reader:
            if not skipped_header:
                # 跳过源文件的表头
                skipped_header = True
                continue

            writer.writerow(row)
            merged_count += 1

            if merged_count % 100000 == 0:
                print(f"   进度: {merged_count:,} 行")

    print(f"   ✅ 合并完成: {merged_count:,} 行")
    print()

    # 验证结果
    print("🔍 验证结果...")
    target_size_after = os.path.getsize(target_path)

    with open(target_path, 'r', encoding='utf-8-sig') as f:
        target_lines_after = sum(1 for _ in f) - 1  # 减去表头

    expected_lines = target_lines_before + source_lines

    print(f"   合并前行数: {target_lines_before:,}")
    print(f"   源文件行数: {source_lines:,}")
    print(f"   合并后行数: {target_lines_after:,}")
    print(f"   期望行数: {expected_lines:,}")

    if target_lines_after == expected_lines:
        print("   ✅ 行数验证通过")
    else:
        print("   ⚠️  行数不匹配！")
        print(f"   差异: {target_lines_after - expected_lines:,} 行")

    print(f"   合并前大小: {target_size_before / (1024**3):.2f} GB")
    print(f"   合并后大小: {target_size_after / (1024**3):.2f} GB")
    print(f"   增加: {(target_size_after - target_size_before) / (1024**3):.2f} GB")
    print()

    # 询问是否删除源文件
    print("=" * 80)
    response = input("是否删除源文件? (y/n): ")
    if response.lower() == 'y':
        os.remove(source_path)
        print(f"✅ 已删除: {os.path.basename(source_path)}")
    else:
        print(f"ℹ️  保留源文件: {os.path.basename(source_path)}")

    print("=" * 80)
    print()
    print("✅ 合并完成！")
    print(f"📝 备份文件: {os.path.basename(backup_path)}")
    print(f"📝 合并文件: {os.path.basename(target_path)}")
    print()

    return True


def main():
    try:
        success = merge_csv_files(SOURCE_FILE, TARGET_FILE)
        if success:
            print("🎉 操作成功完成！")
        else:
            print("❌ 操作失败或被取消")
    except Exception as e:
        print(f"\n❌ 发生错误: {e}")
        import traceback
        traceback.print_exc()


if __name__ == '__main__':
    main()
