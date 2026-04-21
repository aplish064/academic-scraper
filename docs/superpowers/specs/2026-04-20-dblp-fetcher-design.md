# DBLP Fetcher 设计文档

**日期**: 2026-04-20
**状态**: 设计阶段
**作者**: Claude (协助用户)

---

## 1. 项目概述

### 1.1 目标
构建一个完整的计算机科学论文数据库，通过DBLP数据源获取所有论文信息，并存储到ClickHouse中。

### 1.2 核心需求
- 从DBLP获取所有计算机科学领域的论文
- 按作者展开为宽表存储（每行一个作者-论文对）
- 获取详细的作者信息（ORCID、论文总数等）
- 智能处理同名作者问题
- 支持增量更新（月度快照）
- 断点续传功能

### 1.3 技术栈
- **数据源**: DBLP XML快照 + DBLP API
- **存储**: ClickHouse
- **语言**: Python 3.8+
- **并发**: asyncio + ThreadPoolExecutor
- **参考**: `/home/hkustgz/Us/dblp-api` (DBLP API客户端)

---

## 2. 系统架构

### 2.1 架构选择：双队列流水线（方案A）

采用双队列流水线架构，实现XML解析和API调用的并行处理：

```
下载/检测DBLP XML
        ↓
多线程分片解析XML (50线程)
        ↓
论文去重 & 作者提取
        ↓
    ┌─────┴─────┐
    ↓           ↓
论文记录队列   作者API请求队列
    ↓           ↓
100并发API    智能同名匹配
    ↓           ↓
    └─────┬─────┘
          ↓
    数据合并 & 宽表展开
          ↓
    批量写入ClickHouse
          ↓
    保存进度检查点
```

### 2.2 核心组件

#### 2.2.1 XML下载器
- **功能**: 自动检测DROPS上的最新快照
- **增量**: 对比新旧快照的key列表，只处理新增/修改记录
- **实现**: 使用`requests`库下载，支持断点续传

#### 2.2.2 多线程XML解析器
- **并发**: 50个线程并行解析
- **策略**: 按文件字节偏移量分片
- **方法**: 使用`xml.etree.ElementTree.iterparse()`流式解析
- **内存**: 边解析边发送到下游队列，避免OOM

#### 2.2.3 作者详情获取器
- **并发**: 100个异步HTTP请求
- **智能匹配**: 基于机构信息匹配同名作者
- **重试**: 失败重试+指数退避
- **缓存**: 已查询作者结果缓存

#### 2.2.4 数据合并器
- **功能**: 将论文记录与作者详情合并
- **展开**: 按作者展开为宽表（每行一个作者-论文对）
- **增强**: 添加CCF分级、rank标签等

#### 2.2.5 ClickHouse写入器
- **批量**: 9000条/批
- **去重**: 使用临时表去重
- **容错**: 错误处理+重试

---

## 3. 数据结构

### 3.1 中间数据结构

#### 3.1.1 论文记录（从XML解析）
```python
{
    'dblp_key': 'conf/kdd/SifferFTL17',
    'mdate': '2017-08-16',
    'type': 'inproceedings',
    'title': 'Anomaly Detection in Streams...',
    'year': '2017',
    'venue': 'KDD',
    'pages': '1067-1075',
    'volume': None,
    'number': None,
    'publisher': 'ACM',
    'authors': ['Alban Siffer', 'Pierre-Alain Fouque', ...],
    'doi': '10.1145/3097983.3098144',
    'ee': ['https://doi.org/...'],
    'url': 'https://dblp.org/rec/conf/kdd/...',
    'ccf_class': 'A'
}
```

#### 3.1.2 作者详情（从API获取）
```python
{
    'pid': 's/AlbanSiffer',
    'name': 'Alban Siffer',
    'orcid': ['0000-0002-1234-5678'],
    'record_count': 15,
    'profile_url': 'https://dblp.org/pid/s/...',
    'person_key': 'person/s/AlbanSiffer',
    'affiliation': 'Telecom ParisTech',
    'confidence': 0.95,
    'publications': [...]
}
```

#### 3.1.3 最终宽表记录
```python
{
    # 论文标识
    'dbl p_key': 'conf/kdd/SifferFTL17',
    'mdate': '2017-08-16',
    'type': 'inproceedings',

    # 论文基本信息
    'title': 'Anomaly Detection in Streams...',
    'year': '2017',
    'venue': 'KDD',
    'venue_type': 'conference',
    'ccf_class': 'A',

    # 作者信息
    'author_pid': 's/AlbanSiffer',
    'author_name': 'Alban Siffer',
    'author_orcid': '0000-0002-1234-5678',
    'author_rank': 1,
    'author_role': '第一作者',
    'author_total_papers': 15,
    'author_profile_url': 'https://dblp.org/pid/s/...',

    # 详细元数据
    'volume': None,
    'number': None,
    'pages': '1067-1075',
    'publisher': 'ACM',

    # 标识符
    'doi': '10.1145/3097983.3098144',
    'ee': 'https://doi.org/...',
    'dblp_url': 'https://dblp.org/rec/conf/kdd/...',

    # 机构信息
    'institution': 'Telecom ParisTech',
    'institution_confidence': 0.95
}
```

### 3.2 ClickHouse表结构

```sql
CREATE TABLE IF NOT EXISTS academic_db.dblp (
    -- 论文标识
    dblp_key String,
    mdate String,
    type String,

    -- 论文基本信息
    title String,
    year String,
    venue String,
    venue_type String,
    ccf_class String,

    -- 作者信息
    author_pid String,
    author_name String,
    author_orcid String,
    author_rank UInt8,
    author_role String,
    author_total_papers UInt32,
    author_profile_url String,

    -- 详细元数据
    volume String,
    number String,
    pages String,
    publisher String,

    -- 标识符
    doi String,
    ee String,
    dblp_url String,

    -- 机构信息
    institution String,
    institution_confidence Float32,

    -- 元数据
    created_at DateTime DEFAULT now()
) ENGINE = MergeTree()
ORDER BY (author_pid, year, dblp_key)
SETTINGS index_granularity = 8192;
```

---

## 4. 关键算法

### 4.1 同名作者智能匹配

**策略**: 基于论文元数据的机构匹配

```python
def match_author_by_institution(
    author_name: str,
    paper_context: dict,
    dblp_api
) -> dict | None:
    """
    智能匹配同名作者

    匹配优先级：
    1. 唯一匹配：直接返回
    2. 场所匹配：在相同venue发表过文章
    3. 合作者网络：有共同合作者
    4. 论文数量：选择多产者
    """
    # Step 1: 搜索同名作者
    candidates = dblp_api.search_authors(author_name, limit=10)

    # Step 2: 场所匹配
    venue_matches = check_venue_publications(candidates, paper_context['venue'])

    # Step 3: 合作者网络匹配
    coauthor_matches = check_coauthor_overlap(candidates, paper_context['coauthors'])

    # Step 4: 论文数量匹配
    if not (venue_matches or coauthor_matches):
        return select_most_prolific(candidates)

    return best_match
```

### 4.2 多线程XML分片解析

**策略**: 按字节偏移量分片

```python
def calculate_xml_chunks(xml_file_path: str, num_chunks: int = 50) -> list[dict]:
    """
    计算XML文件的分片位置

    策略：
    1. 获取文件总大小
    2. 平均分成N份
    3. 每个分片找到最近的<xxx>开始标签
    """
    file_size = os.path.getsize(xml_file_path)
    chunk_size = file_size // num_chunks

    chunks = []
    for i in range(num_chunks):
        start = i * chunk_size
        end = find_next_tag_start(start) if i < num_chunks - 1 else file_size

        chunks.append({
            'thread_id': i,
            'start': start,
            'end': end,
            'size': end - start
        })

    return chunks
```

### 4.3 并发控制

**三层并发控制**：

```python
# 第一层：XML解析（50线程）
xml_parser_pool = ThreadPoolExecutor(max_workers=50)

# 第二层：作者API查询（100并发）
author_api_semaphore = asyncio.Semaphore(100)

# 第三层：ClickHouse写入（批处理）
ch_writer_batch_size = 9000
```

---

## 5. 断点续传机制

### 5.1 多层级检查点系统

```python
class CheckpointManager:
    """检查点管理器"""

    def __init__(self, checkpoint_path: str):
        self.checkpoint = {
            # XML解析进度
            'xml': {
                'current_snapshot': None,
                'parsed_chunks': [],
                'processed_keys': set(),
            },

            # 作者API查询进度
            'authors': {
                'queried_authors': {},
                'failed_authors': [],
            },

            # ClickHouse写入进度
            'clickhouse': {
                'last_written_batch': 0,
                'total_rows_written': 0,
            },

            # 统计信息
            'stats': {
                'total_papers': 0,
                'total_authors': 0,
                'total_rows': 0,
            }
        }
```

### 5.2 恢复逻辑

```python
def resume_from_checkpoint(checkpoint: CheckpointManager) -> dict:
    """
    从检查点恢复

    1. 检查XML快照是否更新
    2. 恢复XML解析进度
    3. 恢复作者查询
    4. 恢复ClickHouse写入
    """
    current_snapshot = get_latest_dblp_snapshot()

    if current_snapshot != checkpoint.checkpoint['xml']['current_snapshot']:
        # 新快照，重新扫描
        return {'mode': 'full_rescan'}

    # 恢复进度
    remaining_chunks = get_uncompleted_chunks(checkpoint)
    return {'mode': 'resume', 'remaining_chunks': remaining_chunks}
```

### 5.3 优雅中断处理

```python
try:
    asyncio.run(main_async())
except KeyboardInterrupt:
    print("\n⚠️  用户中断")
    checkpoint.save()
    print("✅ 进度已保存，下次运行将自动恢复")
```

---

## 6. 错误处理和监控

### 6.1 错误分类

| 错误类型 | 处理策略 | 重试次数 | 退避策略 |
|---------|---------|---------|---------|
| XML下载失败 | 终止任务 | 3次 | 指数退避 |
| XML解析错误 | 跳过记录 | 不重试 | - |
| API限流(429) | 等待重试 | 无限 | 固定60s |
| API超时 | 重试 | 3次 | 指数退避 |
| API 5xx错误 | 重试 | 5次 | 指数退避 |
| CH连接断开 | 重试 | 3次 | 固定5s |

### 6.2 日志系统

**多级日志**：
- 主日志：`dblp_fetcher.log`
- 错误日志：`dblp_errors.log`
- API日志：`dblp_api.log`
- 性能日志：`dblp_performance.log`

**日志轮转**：每个日志文件最大10MB，保留5个备份文件

### 6.3 实时监控

```python
class PerformanceMonitor:
    """性能监控器"""

    def record_xml_parse(self, chunk_id: int, record_count: int, duration: float):
        """记录XML解析性能"""
        pass

    def record_author_api(self, success: bool, duration: float):
        """记录作者API调用"""
        pass

    def get_summary(self) -> dict:
        """获取性能摘要"""
        return {
            'xml_parse_speed': ...,
            'author_api_success_rate': ...,
            'overall_speed': ...
        }
```

### 6.4 失败批次管理

```python
def save_failed_batch(batch_data: list, error: Exception):
    """保存失败的批次到文件"""
    failed_file = f"log/failed_batches/batch_{timestamp}.json"
    with open(failed_file, 'w') as f:
        json.dump({
            'timestamp': timestamp,
            'error': str(error),
            'data': batch_data
        }, f)

def retry_failed_batches():
    """重试所有失败的批次"""
    # 读取失败批次文件
    # 重新插入ClickHouse
    # 成功后删除失败文件
```

---

## 7. 实现计划

### 7.1 文件结构

```
/home/hkustgz/Us/academic-scraper/
├── src/
│   ├── dblp_fetcher.py          # 主程序
│   ├── dblp_xml_parser.py       # XML解析器
│   ├── dblp_author_matcher.py   # 作者匹配器
│   └── dblp_api_client.py       # DBLP API客户端
├── log/
│   ├── dblp_fetch_progress.json # 进度检查点
│   ├── dblp_fetcher.log         # 主日志
│   ├── dblp_errors.log          # 错误日志
│   └── failed_batches/          # 失败批次
└── docs/
    └── superpowers/specs/
        └── 2026-04-20-dblp-fetcher-design.md
```

### 7.2 依赖项

```python
# 新增依赖
import gzip                           # XML解压
import xml.etree.ElementTree as ET   # XML解析
from concurrent.futures import ThreadPoolExecutor  # 多线程
import asyncio                        # 异步IO
import aiohttp                        # 异步HTTP
from pathlib import Path              # 路径处理

# 复用现有依赖
import clickhouse_connect             # ClickHouse客户端
from tqdm import tqdm                 # 进度条
```

### 7.3 配置参数

```python
# DBLP配置
DBLP_XML_BASE_URL = "https://drops.dagstuhl.de/entities/artifact/10.4230"
DBLP_AUTHOR_API_URL = "https://dblp.org/search/author/api"
DBLP_PERSON_API_URL = "https://dblp.org/pid"

# 并发配置
XML_PARSER_THREADS = 50               # XML解析线程数
AUTHOR_API_CONCURRENT = 100           # 作者API并发数
CH_BATCH_SIZE = 9000                  # ClickHouse批量大小

# 超时配置
REQUEST_TIMEOUT = 20                  # API请求超时
MAX_RETRIES = 3                       # 最大重试次数

# 文件路径
XML_SNAPSHOT_PATH = "data/dblp.xml.gz"
PROGRESS_FILE = "log/dblp_fetch_progress.json"
LOG_DIR = "log"
```

---

## 8. 性能预估

### 8.1 数据规模

- **DBLP XML大小**: ~1GB (压缩)，~5-10GB (解压)
- **论文记录数**: ~500万篇
- **作者记录数**: ~300万位
- **展开后行数**: ~2000万行（假设平均每篇论文4个作者）

### 8.2 性能指标

| 指标 | 预估值 |
|------|--------|
| XML解析速度 | 10,000 记录/秒 |
| 作者API调用 | 100 并发，~2秒/次 |
| ClickHouse写入 | 9,000 行/批，~1秒/批 |
| 总体速度 | ~5,000 行/秒 |
| 预计总耗时 | ~4-6 小时（首次） |

### 8.3 增量更新性能

- **月度增量**: ~50,000 新记录
- **增量耗时**: ~10-20 分钟

---

## 9. 风险和挑战

### 9.1 技术风险

| 风险 | 影响 | 缓解措施 |
|------|------|---------|
| API限流 | 作者详情获取失败 | 智能限流+重试机制 |
| 同名作者误匹配 | 数据准确性 | 多策略匹配+置信度评分 |
| 内存溢出 | 程序崩溃 | 流式解析+分批处理 |
| ClickHouse写入失败 | 数据丢失 | 临时表+失败批次管理 |

### 9.2 数据质量

- **同名作者**: 即使智能匹配，仍有10-20%可能误匹配
- **机构信息**: DBLP XML不包含机构字段，需推断
- **ORCID缺失**: 不是所有作者都有ORCID

### 9.3 缓解策略

1. **置信度评分**: 每个作者匹配给出置信度
2. **人工审核**: 低置信度记录标记，后续人工确认
3. **数据验证**: 与OpenAlex数据交叉验证

---

## 10. 未来扩展

### 10.1 可能的改进

1. **引用关系**: 从其他数据源（OpenAlex）补充引用数
2. **主题分类**: 使用论文标题/摘要进行主题分类
3. **作者消歧**: 使用机器学习模型进行同名作者消歧
4. **实时更新**: 接入DBLP实时API（如果可用）

### 10.2 数据应用

- 学术影响力分析
- 作者合作网络构建
- 研究趋势挖掘
- 机构排名评估

---

## 11. 总结

本设计文档描述了DBLP Fetcher的完整架构，采用双队列流水线实现高效的并行处理。关键特性包括：

✅ **高效并行**: 50线程解析 + 100并发API
✅ **智能匹配**: 多策略同名作者匹配
✅ **断点续传**: 多层级检查点系统
✅ **容错机制**: 完善的错误处理和重试
✅ **实时监控**: 性能指标和进度展示

该设计平衡了性能、可靠性和数据质量，能够满足构建完整计算机科学论文数据库的需求。

---

**下一步**: 编写详细实现计划
