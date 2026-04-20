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

from src.dblp_config import (
    DATA_DIR, LOG_DIR, XML_SNAPSHOT_PATH, PROGRESS_FILE,
    CH_HOST, CH_PORT, CH_DATABASE, CH_TABLE, CH_USERNAME, CH_PASSWORD,
    XML_PARSER_THREADS, AUTHOR_API_CONCURRENT, CH_BATCH_SIZE
)

try:
    from src.dblp_checkpoint import CheckpointManager
    from src.dblp_monitor import PerformanceMonitor, setup_loggers
    from src.dblp_clickhouse import create_clickhouse_client
except ImportError as e:
    print(f"⚠️  依赖模块未找到: {e}")
    print("请先实现后续任务:")
    print("  - Task 2: 检查点管理器 (dblp_checkpoint)")
    print("  - Task 3: ClickHouse写入器 (dblp_clickhouse)")
    print("  - Task 4: 性能监控器 (dblp_monitor)")
    sys.exit(1)


def main() -> None:
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

    # Task 1 只创建基础框架，主流程将在后续任务实现
    print("✅ 基础框架已就绪，等待实现主流程...")

    # 测试：完成
    print("\n✅ 基础框架创建成功")


if __name__ == '__main__':
    main()
