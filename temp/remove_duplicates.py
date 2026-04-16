#!/usr/bin/env python3
"""
查找并删除所有CSV文件中的重复记录
基于author_id + doi + title组合判断重复
"""

import pandas as pd
from pathlib import Path
import shutil
from datetime import datetime
import hashlib

# 数据目录
DATA_DIR = Path(__file__).parent.parent / 'output' / 'openalex'

# 备份目录
BACKUP_DIR = Path(__file__).parent.parent / 'output' / 'csv_backups'

# 用于判断重复的关键字段
DUPLICATE_KEY_COLUMNS = ['author_id', 'doi', 'title']

def get_file_hash(filepath):
    """获取文件哈希值用于备份命名"""
    with open(filepath, 'rb') as f:
        return hashlib.md5(f.read()).hexdigest()[:8]

def find_and_remove_duplicates():
    """查找并删除所有CSV文件中的重复记录（内存优化版）"""

    import gc

    print("🔍 开始查找重复记录...")
    print(f"📁 数据目录: {DATA_DIR}")
    print(f"📦 备份目录: {BACKUP_DIR}")
    print()

    # 创建备份目录
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    # 获取所有CSV文件
    csv_files = list(DATA_DIR.rglob('*.csv'))

    if not csv_files:
        print("❌ 未找到CSV文件")
        return

    print(f"📊 找到 {len(csv_files)} 个CSV文件")
    print()

    # 统计信息
    total_files = 0
    total_duplicates_found = 0
    total_duplicates_removed = 0
    files_with_duplicates = []

    for idx, csv_file in enumerate(csv_files, 1):
        df = None
        df_cleaned = None

        try:
            # 显示进度
            if idx % 10 == 0:
                print(f"  进度: {idx}/{len(csv_files)}")
                # 强制垃圾回收
                gc.collect()

            # 跳过备份目录中的文件
            if 'csv_backups' in str(csv_file):
                continue

            # 读取CSV（使用更节省内存的方式）
            try:
                # 只读取需要的列
                df = pd.read_csv(csv_file, encoding='utf-8-sig', low_memory=False,
                                usecols=lambda col: col in DUPLICATE_KEY_COLUMNS or col not in [])
            except Exception as e:
                print(f"⚠️  无法读取文件 {csv_file.name}: {e}")
                continue

            if df.empty:
                del df
                df = None
                continue

            original_count = len(df)

            # 检查是否存在关键字段
            missing_columns = [col for col in DUPLICATE_KEY_COLUMNS if col not in df.columns]
            if missing_columns:
                print(f"⚠️  文件 {csv_file.name} 缺少字段: {missing_columns}")
                del df
                df = None
                continue

            # 创建重复键（组合字段）- 使用更高效的方式
            df['_duplicate_key'] = df[DUPLICATE_KEY_COLUMNS[0]].astype(str) + '|' + \
                                   df[DUPLICATE_KEY_COLUMNS[1]].astype(str) + '|' + \
                                   df[DUPLICATE_KEY_COLUMNS[2]].astype(str)

            # 统计重复
            duplicate_mask = df.duplicated(subset=['_duplicate_key'], keep='first')
            duplicate_count = duplicate_mask.sum()

            if duplicate_count > 0:
                # 备份原文件
                backup_filename = f"{csv_file.stem}_{get_file_hash(csv_file)}{csv_file.suffix}"
                backup_path = BACKUP_DIR / backup_filename
                shutil.copy2(csv_file, backup_path)

                # 删除重复记录（保留第一条）
                df_cleaned = df[~duplicate_mask].copy()
                df_cleaned = df_cleaned.drop(columns=['_duplicate_key'])

                # 保存清理后的文件
                df_cleaned.to_csv(csv_file, index=False, encoding='utf-8-sig')

                total_files += 1
                total_duplicates_found += duplicate_count
                total_duplicates_removed += (original_count - len(df_cleaned))

                print(f"✓ {csv_file.name}: {original_count} → {len(df_cleaned)} (删除 {duplicate_count} 条重复)")

                # 只保存文件路径，不保存完整信息以节省内存
                files_with_duplicates.append({
                    'file': str(csv_file.relative_to(DATA_DIR.parent)),
                    'original': original_count,
                    'duplicates': int(duplicate_count),
                    'final': len(df_cleaned),
                    'backup': str(backup_path)
                })

            # 及时清理内存
            del df
            if df_cleaned is not None:
                del df_cleaned
            df = None
            df_cleaned = None

        except Exception as e:
            print(f"❌ 处理文件 {csv_file.name} 时出错: {e}")
            # 清理内存
            if df is not None:
                del df
            if df_cleaned is not None:
                del df_cleaned
            df = None
            df_cleaned = None
            continue

    # 打印总结报告
    print()
    print("=" * 60)
    print("📊 重复记录清理报告")
    print("=" * 60)
    print(f"处理时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"检查文件数: {len(csv_files)}")
    print(f"有重复的文件: {total_files}")
    print(f"发现重复记录: {total_duplicates_found}")
    print(f"删除重复记录: {total_duplicates_removed}")
    print(f"备份文件位置: {BACKUP_DIR}")
    print()

    if files_with_duplicates:
        print("📁 有重复的文件详情:")
        print("-" * 60)
        for file_info in files_with_duplicates:
            print(f"文件: {file_info['file']}")
            print(f"  原始记录: {file_info['original']}")
            print(f"  重复记录: {file_info['duplicates']}")
            print(f"  清理后: {file_info['final']}")
            print(f"  备份: {file_info['backup']}")
            print()
    else:
        print("✅ 未发现重复记录，所有文件都是干净的！")

    print("=" * 60)

def analyze_duplicates():
    """分析重复记录的模式（不删除，只分析，内存优化版）"""

    import gc

    print("🔍 分析重复记录模式...")
    print(f"📁 数据目录: {DATA_DIR}")
    print()

    # 获取所有CSV文件
    csv_files = list(DATA_DIR.rglob('*.csv'))

    print(f"📊 找到 {len(csv_files)} 个CSV文件")
    print()

    files_with_duplicates = []

    for idx, csv_file in enumerate(csv_files, 1):
        df = None

        try:
            # 显示进度
            if idx % 20 == 0:
                print(f"  进度: {idx}/{len(csv_files)}")
                gc.collect()

            if 'csv_backups' in str(csv_file):
                continue

            try:
                df = pd.read_csv(csv_file, encoding='utf-8-sig', low_memory=False)
            except Exception as e:
                continue

            if df.empty:
                del df
                df = None
                continue

            # 检查是否存在关键字段
            if not all(col in df.columns for col in DUPLICATE_KEY_COLUMNS):
                del df
                df = None
                continue

            # 创建重复键 - 使用更高效的方式
            df['_duplicate_key'] = df[DUPLICATE_KEY_COLUMNS[0]].astype(str) + '|' + \
                                   df[DUPLICATE_KEY_COLUMNS[1]].astype(str) + '|' + \
                                   df[DUPLICATE_KEY_COLUMNS[2]].astype(str)

            # 统计重复
            duplicate_mask = df.duplicated(subset=['_duplicate_key'], keep=False)
            duplicate_count = duplicate_mask.sum()

            if duplicate_count > 0:
                files_with_duplicates.append({
                    'file': csv_file.name,
                    'total': len(df),
                    'duplicates': int(duplicate_count),
                    'unique': len(df) - int(duplicate_count)
                })

            # 及时清理内存
            del df
            df = None

        except Exception as e:
            if df is not None:
                del df
            df = None
            continue

    # 打印分析报告
    print("=" * 60)
    print("📊 重复记录分析报告")
    print("=" * 60)
    print(f"分析时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"检查文件数: {len(csv_files)}")
    print(f"有重复的文件: {len(files_with_duplicates)}")
    print()

    if files_with_duplicates:
        total_duplicates = sum(f['duplicates'] for f in files_with_duplicates)
        print(f"总重复记录数: {total_duplicates}")
        print()

        print("📁 有重复的文件 (前20个):")
        print("-" * 60)
        for file_info in sorted(files_with_duplicates, key=lambda x: x['duplicates'], reverse=True)[:20]:
            print(f"{file_info['file']}: {file_info['duplicates']} 条重复 (共 {file_info['total']} 条)")
        print()
    else:
        print("✅ 未发现重复记录，所有文件都是干净的！")

    print("=" * 60)

if __name__ == '__main__':
    import sys

    if len(sys.argv) > 1 and sys.argv[1] == '--analyze':
        # 只分析，不删除
        analyze_duplicates()
    else:
        # 查找并删除重复记录
        print("⚠️  即将删除重复记录，原文件将被备份")
        print("如只分析不删除，请使用: python3 remove_duplicates.py --analyze")
        print()

        response = input("是否继续? (y/N): ")
        if response.lower() == 'y':
            find_and_remove_duplicates()
        else:
            print("❌ 操作已取消")
