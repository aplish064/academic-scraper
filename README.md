# Academic Scraper

高性能学术论文数据获取工具，支持从 OpenAlex 和 ArXiv 批量获取论文数据。

## 快速开始

### 安装依赖

```bash
pip install httpx tqdm
```

### 运行主程序

```bash
# OpenAlex 获取器（异步高性能）
python3 src/openalex_fetcher.py

# ArXiv 获取器
python3 src/arxiv_fetcher.py
```

### 数据维护工具

```bash
# 检查 CSV 文件重复记录
python3 temp/check_duplicates.py

# 合并 CSV 文件
python3 temp/merge_csv.py
```

## 主要特性

- ⚡ **异步高性能**：使用 async I/O + HTTP/2，速度提升 20-50 倍
- 🔄 **断点续传**：自动保存进度，支持中断后继续
- 🛡️ **智能重试**：自动处理 API 限制和网络错误
- 📊 **按月组织**：CSV 文件按月份自动组织
- 🧠 **内存优化**：及时释放数据，避免 OOM

## 输出文件

```
output/
├── openalex/              # OpenAlex 数据
│   ├── 2026_03.csv
│   ├── 2026_02.csv
│   └── ...
└── arxiv/                # ArXiv 数据
    ├── 2026_04.csv
    └── ...

log/
├── openalex_fetch_progress.json  # 进度文件
└── openalex_fetch_fast.log        # 日志文件
```

## 配置

编辑 `src/openalex_fetcher.py`：

```python
START_DATE = "20260410"              # 开始日期
END_YEAR = 2010                      # 结束年份
MAX_CONCURRENT_REQUESTS = 20        # 并发数
```

## 文档

- `CLAUDE.md` - 开发指南和架构说明
- `src/` - 主程序源代码
- `temp/` - 数据维护工具

## 常见问题

**Q: 脚本被 Killed？**
A: 内存不足，已优化。如仍有问题，降低 `MAX_CONCURRENT_REQUESTS`。

**Q: API 配额耗尽？**
A: 等待 UTC 午夜重置（约22小时），或注册付费账户。

**Q: 如何断点续传？**
A: 直接重新运行，会自动从上次位置继续。

## 流式架构（DBLP）

流式获取器（`src/dblp_fetcher_streaming.py`）使用生产者-消费者模式实现恒定内存占用。

### 运行

```bash
bash src/run_streaming.sh
```

### 架构

- **XML 解析器**：将论文流式传输到队列（最大 10,000 条）
- **作者缓存**：按作者聚合论文
- **作者匹配器**：并发查询（100 并行）
- **队列监控**：检测背压

### 断点恢复

获取器会在中断后自动从 `log/checkpoint_streaming.json` 恢复。

### 性能

- 内存：< 3GB（批量模式需 15-20GB）
- 时间：4-12 小时（批量模式需 532 天）
