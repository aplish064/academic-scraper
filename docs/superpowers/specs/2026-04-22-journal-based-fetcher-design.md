# Semantic Scholar 期刊表论文获取器设计文档

**日期**: 2026-04-22
**状态**: 设计阶段
**作者**: Claude Code

## 1. 概述

### 1.1 目标
修改 `src/semantic_fetcher.py`，从现有的三层漏斗策略改为基于期刊表的批量获取策略。从用户提供的期刊表 CSV 文件中读取期刊列表，为每个期刊获取所有可用论文并存储到 ClickHouse 数据库。

### 1.2 关键需求
- **数据源**: `/home/hkustgz/Us/academic-scraper/data/XR2026-UTF8.csv`（期刊表）
- **期刊字段**: CSV 的 "Journal" 列
- **时间范围**: 无限制，获取所有年份的论文
- **API 策略**: 先用 `venue` 参数查询，失败后用 `query` 搜索期刊名
- **并发设置**: 使用现有的 1.1 秒请求间隔
- **进度追踪**: 按期刊+页数追踪，支持中断恢复
- **数据库**: 使用现有的 ClickHouse 插入逻辑
- **实现方式**: 完全重写 `semantic_fetcher.py`

## 2. 架构设计

### 2.1 整体架构

系统分为四个主要阶段：

**阶段 1: 数据准备**
- 加载 CSV 文件
- 提取 Journal 列的所有非空值
- 数据清理：去重、移除空值、标准化名称
- 生成待处理期刊列表

**阶段 2: 批量验证**
- 对每个期刊尝试 venue 查询（仅获取1篇，验证有效性）
- 记录有效的期刊及其查询方式（venue 或 query）
- 跳过无效的期刊（API 无返回值）
- 生成可用的期刊列表

**阶段 3: 论文获取**
- 按顺序处理每个可用期刊
- 使用验证通过的查询方式（venue 或 query）
- 翻页获取所有论文（每页 100 篇，直到无更多结果）
- 实时插入 ClickHouse 数据库
- 每完成一页更新进度

**阶段 4: 进度管理**
- 保存详细的进度文件（journal_progress.json）
- 支持中断后从未完成的页数继续
- 记录统计信息（每个期刊的论文总数、获取时间、状态）

### 2.2 执行流程

```
1. 初始化
   ├─ 加载配置参数
   ├─ 创建 ClickHouse 客户端
   ├─ 加载/创建进度文件
   └─ 显示欢迎信息

2. 数据准备阶段
   ├─ 读取 CSV 文件
   ├─ 提取和清理期刊列表
   ├─ 显示统计信息（总数、去重后数量）
   └─ 保存到进度文件

3. 批量验证阶段
   ├─ 跳过已验证的期刊
   ├─ 对每个期刊验证 API 可用性
   ├─ 显示进度条和实时统计
   └─ 保存验证结果

4. 论文获取阶段
   ├─ 跳过已完成/失败的期刊
   ├─ 对每个有效期刊：
   │   ├─ 从中断页数开始（或第0页）
   │   ├─ 翻页获取所有论文
   │   ├─ 实时插入数据库
   │   ├─ 每页更新进度
   │   └─ 完成后标记状态
   └─ 显示最终统计

5. 总结报告
   ├─ 总期刊数、有效数、失败数
   ├─ 总论文数、总行数
   ├─ 总耗时、平均速度
   └─ 保存日志
```

## 3. 数据结构设计

### 3.1 进度文件结构

**文件位置**: `log/journal_progress.json`

```json
{
  "csv_file": "XR2026-UTF8.csv",
  "csv_loaded_at": "2026-04-22 10:00:00",
  "total_journals": 1500,
  "journals": {
    "Nature": {
      "query_type": "venue",
      "status": "completed",
      "total_pages": 50,
      "current_page": 50,
      "papers_fetched": 5000,
      "last_updated": "2026-04-22 10:30:00"
    },
    "Journal Asiatique": {
      "query_type": "query",
      "status": "in_progress",
      "total_pages": null,
      "current_page": 3,
      "papers_fetched": 300,
      "last_updated": "2026-04-22 10:35:00"
    },
    "Unknown Journal": {
      "query_type": null,
      "status": "failed",
      "error": "No results found",
      "last_updated": "2026-04-22 10:15:00"
    }
  },
  "last_update": "2026-04-22 10:35:00"
}
```

### 3.2 内存数据结构

**期刊列表**:
```python
journal_list = [
    {"name": "Nature", "original_name": "Nature", "row_number": 1},
    {"name": "Journal Asiatique", "original_name": "Journal Asiatique", "row_number": 2},
]
```

**验证结果**:
```python
validated_journals = {
    "Nature": {"query_type": "venue", "status": "valid"},
    "Journal Asiatique": {"query_type": "query", "status": "valid"},
}
```

### 3.3 状态枚举

- `pending`: 待处理
- `validating`: 验证中
- `valid`: 验证通过
- `in_progress`: 获取中
- `completed`: 已完成
- `failed`: 失败
- `skipped`: 已跳过

## 4. 核心函数设计

### 4.1 主要函数模块

#### `load_journals_from_csv(csv_path)`
- **功能**: 读取 CSV 文件并提取期刊列表
- **输入**: CSV 文件路径
- **输出**: 期刊字典列表
- **处理**:
  - 使用 pandas 读取 CSV
  - 提取 "Journal" 列
  - 过滤空值
  - 去重并保留原始行号

#### `validate_journal(journal_name, api_client)`
- **功能**: 验证单个期刊是否可用
- **输入**: 期刊名称、API 客户端
- **输出**: 验证结果字典
- **处理**:
  - 先尝试 venue 查询（limit=1）
  - 如果有结果，返回 `{"query_type": "venue", "valid": true}`
  - 如果无结果，尝试 query 查询（limit=1）
  - 如果有结果，返回 `{"query_type": "query", "valid": true}`
  - 都无效则返回 `{"query_type": null, "valid": false}`
  - 重试 3 次，记录错误

#### `fetch_papers_by_journal(journal_name, query_type, start_page, progress_data, api_client, ch_client)`
- **功能**: 获取指定期刊的所有论文
- **输入**: 期刊名、查询类型、起始页、进度数据、API 客户端、ClickHouse 客户端
- **输出**: (论文数, 行数) 元组
- **处理**:
  - 从指定页数开始获取
  - 使用 venue 或 query 参数
  - 不设置年份过滤
  - 每页 100 篇，持续翻页直到无结果
  - 每页完成后更新进度并插入数据库

#### `batch_validate_journals(journal_list, progress_data, api_client)`
- **功能**: 批量验证所有期刊
- **输入**: 期刊列表、进度数据、API 客户端
- **输出**: 验证通过的期刊字典
- **处理**:
  - 跳过已验证的期刊
  - 显示进度条
  - 调用 validate_journal 对每个期刊验证
  - 保存验证结果

#### `execute_journal_fetching(validated_journals, progress_data, api_client, ch_client)`
- **功能**: 执行论文获取主流程
- **输入**: 验证通过的期刊、进度数据、API 客户端、ClickHouse 客户端
- **输出**: 总论文数、总行数
- **处理**:
  - 跳过已完成或失败的期刊
  - 对未完成的期刊继续获取
  - 每个期刊完成后保存进度
  - 显示统计信息

### 4.2 保留的现有函数

从原 `semantic_fetcher.py` 保留以下函数（无需修改）:
- `setup_directories()`: 创建必要的目录
- `load_progress()`: 加载进度文件
- `save_progress(progress_data)`: 保存进度文件
- `log_message(message)`: 记录日志消息
- `make_request(url, params, retry_count)`: 发送 HTTP 请求
- `create_clickhouse_client()`: 创建 ClickHouse 客户端
- `batch_insert_clickhouse(client, rows)`: 批量插入数据
- `paper_to_rows(paper)`: 将论文数据转换为数据库行

## 5. 错误处理和边界情况

### 5.1 CSV 读取错误
- **文件不存在**: 明确提示路径，退出程序
- **Journal 列不存在**: 提示列名，显示可用列名
- **编码错误**: 尝试不同编码（UTF-8, GBK, Latin-1）

### 5.2 API 错误
- **429 速率限制**: 暂停 60 秒，重试 3 次
- **5xx 服务器错误**: 指数退避重试（2秒, 4秒, 8秒）
- **超时**: 重试 3 次，延长超时时间
- **空结果**: 记录为无效期刊，不重试

### 5.3 数据库错误
- **连接失败**: 尝试重连 3 次
- **插入失败**: 记录失败的论文数据到错误日志文件
- **批量插入失败**: 分小批重试

### 5.4 边界情况处理
- **期刊名称为空**: 跳过该行，记录警告
- **期刊名称重复**: CSV 去重，保留第一次出现
- **特殊字符**: 保留原始名称，API 查询时自动转义
- **无结果期刊**: 标记为 failed，记录原因，不阻塞其他期刊
- **进度文件损坏**: 检测并备份，重新开始

### 5.5 日志文件

- **log/journal_fetch.log**: 主日志（所有操作记录）
- **log/journal_errors.log**: 错误日志（仅错误和警告）
- **log/journal_progress.json**: 进度文件（JSON 格式）

## 6. 配置参数

### 6.1 CSV 配置
```python
CSV_PATH = SCRIPT_DIR / "data/XR2026-UTF8.csv"
CSV_ENCODING = "utf-8-sig"  # 支持 BOM
```

### 6.2 API 配置
```python
API_KEY = "7Tts2u4jXLaebjvFPICkE7kpTJQvUaYG4byRSpBp"
BASE_URL = "https://api.semanticscholar.org/graph/v1"
REQUEST_INTERVAL = 1.1
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
```

### 6.3 查询配置
```python
PAPERS_PER_REQUEST = 100
MAX_PAGES_PER_JOURNAL = None  # 无限制，获取所有
FIELDS = "paperId,title,authors,year,venue,journal,publicationDate,citationCount,externalIds,url,abstract"
```

### 6.4 ClickHouse 配置
```python
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'semantic'
CH_USERNAME = 'default'
CH_PASSWORD = ''
```

## 7. 文件结构

```
src/
└── semantic_fetcher.py          # 完全重写

log/
├── journal_progress.json        # 进度文件
├── journal_fetch.log           # 主日志
└── journal_errors.log          # 错误日志

data/
└── XR2026-UTF8.csv             # 期刊表（用户提供）
```

## 8. 使用方式

```bash
# 使用虚拟环境运行
/home/hkustgz/Us/academic-scraper/venv/bin/python src/semantic_fetcher.py
```

## 9. 测试策略

1. **小规模测试**: 先用 CSV 的前 10 个期刊测试
2. **恢复测试**: 中途中断，验证能否从正确位置继续
3. **错误测试**: 模拟 API 错误，验证重试机制
4. **数据验证**: 检查插入数据库的数据完整性

## 10. 预期输出

### 10.1 控制台输出示例

```
============================================================
Semantic Scholar 期刊表论文获取器
============================================================
CSV 文件: /home/hkustgz/Us/academic-scraper/data/XR2026-UTF8.csv
查询策略: venue → query
时间范围: 所有年份
============================================================

✓ ClickHouse 连接成功
📊 加载期刊列表...
   总计: 1500 个期刊
   去重后: 1450 个期刊

🔍 验证期刊有效性...
   进度: ████████████████████ 100% (1450/1450)
   有效: 1200 个 | 无效: 250 个

📥 获取论文...
   进度: ████████████-------- 80% (960/1200)
   已完成: Nature (5000篇), Science (4500篇)...
   进行中: Journal Asiatique (第3页)

✅ 全部完成
📊 统计:
   总期刊: 1450 个
   有效: 1200 个
   失败: 250 个
   总论文: 600,000 篇
   总行数: 1,800,000 行
⏱️  总耗时: 1500.0 秒 (25.0 分钟)
============================================================
```

### 10.2 日志文件示例

**journal_fetch.log**:
```
[2026-04-22 10:00:00] 程序启动
[2026-04-22 10:00:01] 加载 CSV 文件: XR2026-UTF8.csv
[2026-04-22 10:00:02] 发现 1500 个期刊，去重后 1450 个
[2026-04-22 10:00:03] 开始验证期刊
[2026-04-22 10:05:00] 验证完成：1200 有效，250 失败
[2026-04-22 10:05:01] 开始获取论文
[2026-04-22 10:30:00] Nature: 完成 5000 篇论文
[2026-04-22 10:35:00] 程序完成
```

**journal_errors.log**:
```
[2026-04-22 10:02:15] WARNING: 期刊 "Unknown Journal" 无结果，跳过
[2026-04-22 10:15:30] ERROR: API 请求超时，重试 1/3
```

## 11. 成功标准

1. 能够成功读取 CSV 文件中的所有期刊
2. 能够验证每个期刊的 API 可用性
3. 能够为每个有效期刊获取所有论文（无年份限制）
4. 能够正确处理中断和恢复
5. 能够将数据正确插入 ClickHouse 数据库
6. 能够生成详细的进度报告和日志
