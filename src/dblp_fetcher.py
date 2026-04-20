#!/usr/bin/env python3
"""
DBLP Fetcher - 计算机科学论文数据获取系统
双队列流水线架构：XML解析 + 作者API查询
"""

import asyncio
import sys
import signal
from pathlib import Path

# 添加项目路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from src.dblp_config import *
from src.dblp_checkpoint import CheckpointManager
from src.dblp_monitor import PerformanceMonitor, setup_loggers
from src.dblp_clickhouse import create_clickhouse_client


def main():
    """主函数"""
    print("="*80)
    print("DBLP Fetcher - 计算机科学论文数据获取系统")
    print("="*80)
    print()

    # 创建必要的目录
    Path(DATA_DIR).mkdir(parents=True, exist_ok=True)
    Path(LOG_DIR).mkdir(parents=True, exist_ok=True)
    Path(f"{LOG_DIR}/failed_batches").mkdir(parents=True, exist_ok=True)

    # 设置日志
    setup_loggers(LOG_DIR)

    # 初始化监控器
    monitor = PerformanceMonitor()

    # 初始化检查点
    checkpoint = CheckpointManager(PROGRESS_FILE)

    # 连接ClickHouse
    print("📡 连接ClickHouse...")
    ch_client = create_clickhouse_client()
    if not ch_client:
        print("❌ ClickHouse连接失败，程序终止")
        return
    print("✅ ClickHouse连接成功\n")

    # TODO: 实现主流程
    print("主流程待实现...")

    # 测试：完成
    print("\n✅ 基础框架创建成功")


if __name__ == '__main__':
    main()
