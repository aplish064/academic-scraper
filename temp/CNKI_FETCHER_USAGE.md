# CNKI文献抓取器使用指南

## 项目概述

CNKI文献抓取器是一个高性能的学术文献数据采集系统，支持从中国知网（CNKI）抓取以下类型的文献：

- 期刊论文
- 学位论文（硕士/博士）
- 会议论文
- 专利

**技术栈：**
- Python 3.8+
- 异步I/O（asyncio）
- Scrapling（隐身模式爬虫）
- BeautifulSoup（HTML解析）
- ClickHouse（数据存储）

## 环境配置

### 1. 系统要求

- Linux系统（推荐Ubuntu 20.04+）
- Python 3.8或更高版本
- 至少4GB可用内存
- 稳定的网络连接

### 2. 安装依赖

**使用虚拟环境（推荐）：**

```bash
cd /home/hkustgz/Us/academic-scraper

# 激活虚拟环境
source venv/bin/activate

# 安装Python依赖
pip install scrapling beautifulsoup4 clickhouse-connect pandas lxml tqdm
```

**关键依赖说明：**

- `scrapling`: 隐身模式爬虫框架，避免反爬检测
- `beautifulsoup4`: HTML解析库
- `clickhouse-connect`: ClickHouse数据库驱动
- `pandas`: 数据处理和清洗
- `lxml`: XML/HTML解析器
- `tqdm`: 进度条显示

### 3. ClickHouse数据库配置

**安装ClickHouse：**

```bash
# Ubuntu/Debian
sudo apt-get install clickhouse-server clickhouse-client

# 启动ClickHouse服务
sudo service clickhouse-server start
```

**创建数据库和表：**

```bash
# 连接ClickHouse
clickhouse-client

# 创建数据库
CREATE DATABASE IF NOT EXISTS academic_db;

# 使用数据库
USE academic_db;

# 创建CNKI表（执行项目中的SQL脚本）
# 见: src/cnki_table.sql
```

**验证连接：**

```bash
clickhouse-client --query "SELECT 1"
```

### 4. 配置文件

配置参数位于 `src/cnki_fetcher.py` 文件开头：

```python
# 时间范围
START_YEAR = 2000          # 起始年份
END_DATE = datetime.now()   # 结束日期（默认为当前日期）

# ClickHouse配置
CH_HOST = 'localhost'
CH_PORT = 8123
CH_DATABASE = 'academic_db'
CH_TABLE = 'CNKI'
CH_USERNAME = 'default'
CH_PASSWORD = ''

# 并发控制
MAX_CONCURRENT_REQUESTS = 15   # 最大并发数
BATCH_SIZE = 1000               # 批量写入大小
REQUEST_DELAY = (0.5, 2.0)      # 请求延迟范围（秒）

# 重试配置
MAX_RETRIES = 3
TIMEOUT = 30.0
```

**根据实际情况调整：**
- 网络带宽较小 → 降低 `MAX_CONCURRENT_REQUESTS`
- 服务器性能较强 → 提高 `MAX_CONCURRENT_REQUESTS`
- 反爬严格 → 增大 `REQUEST_DELAY`

## 使用指南

### 1. 启动抓取器

```bash
cd /home/hkustgz/Us/academic-scraper

# 使用虚拟环境Python
venv/bin/python src/cnki_fetcher.py

# 或者先激活虚拟环境
source venv/bin/activate
python src/cnki_fetcher.py
```

### 2. 首次运行

首次运行时，程序会：

1. 创建必要的日志目录
2. 连接ClickHouse数据库
3. 生成日期列表（从START_YEAR到当前日期）
4. 开始抓取任务

**首次运行示例输出：**

```
================================================================================
CNKI文献抓取器启动
================================================================================

总日期数: 9610
已完成: 0
待处理: 9610
✓ ClickHouse连接成功

[进度] 2024-01-15 | 抓取中...
[进度] 2024-01-15 | 论文: 1523 | 行: 1523 | 已写入ClickHouse
```

### 3. 断点续传

程序支持自动断点续传：

- 进度保存在 `log/cnki_fetch_progress.json`
- 每完成一个日期的抓取，自动保存进度
- 中断后重新运行，自动跳过已完成的日期

**进度文件格式：**

```json
{
  "current_date": "2024-01-15",
  "completed_dates": ["2024-01-15", "2024-01-14", ...],
  "last_update": "2024-01-15 14:30:00",
  "total_papers": 1523,
  "total_rows": 1523
}
```

### 4. 监控进度

**查看日志文件：**

```bash
# 实时查看日志
tail -f log/cnki_fetch.log

# 查看最近100行
tail -n 100 log/cnki_fetch.log
```

**查看进度文件：**

```bash
cat log/cnki_fetch_progress.json | python -m json.tool
```

**ClickHouse查询进度：**

```sql
-- 查询总记录数
SELECT COUNT(*) FROM academic_db.CNKI;

-- 按日期统计
SELECT pub_date, COUNT(*) as count
FROM academic_db.CNKI
GROUP BY pub_date
ORDER BY pub_date DESC
LIMIT 10;

-- 按资源类型统计
SELECT resource_type, COUNT(*) as count
FROM academic_db.CNKI
GROUP BY resource_type;
```

### 5. 性能优化

**并发调优：**

```python
# 根据网络和服务器性能调整
MAX_CONCURRENT_REQUESTS = 20   # 默认15，可尝试10-30
```

**内存优化：**

- 程序已实现内存优化，及时释放抓取的数据
- 如遇内存不足，降低 `MAX_CONCURRENT_REQUESTS`

**速度优化：**

- 提高并发数（但要注意反爬）
- 减少请求延迟（但可能被封禁）
- 使用更快的网络连接

## 数据结构

### ClickHouse表结构

```sql
CREATE TABLE IF NOT EXISTS academic_db.CNKI (
    uid String COMMENT '唯一标识符',
    title String COMMENT '文献标题',
    author String COMMENT '作者',
    abstract String COMMENT '摘要',
    keywords String COMMENT '关键词',
    resource_type String COMMENT '资源类型: journal/thesis/conference/patent',
    pub_date String COMMENT '发表日期',
    journal String COMMENT '期刊名称（期刊论文）',
    volume String COMMENT '卷',
    issue String COMMENT '期',
    pages String COMMENT '页码',
    publisher String COMMENT '出版社/学校',
    degree String COMMENT '学位（学位论文）',
    conference_name String COMMENT '会议名称（会议论文）',
    patent_number String COMMENT '专利号（专利）',
    patent_type String COMMENT '专利类型',
    cited_count Int32 DEFAULT 0 COMMENT '被引次数',
    download_count Int32 DEFAULT 0 COMMENT '下载次数',
    source_url String COMMENT '来源URL',
    import_time DateTime COMMENT '导入时间',
    rank Int32 DEFAULT 0 COMMENT '排名'
) ENGINE = MergeTree()
ORDER BY (pub_date, resource_type)
SETTINGS index_granularity = 8192;
```

### 数据字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| uid | String | 文献唯一标识符 |
| title | String | 文献标题 |
| author | String | 作者（多个作者用分号分隔）|
| abstract | String | 摘要内容 |
| keywords | String | 关键词（用分号分隔）|
| resource_type | String | 资源类型：journal/thesis/conference/patent |
| pub_date | String | 发表日期（YYYY-MM-DD格式）|
| journal | String | 期刊名称（仅期刊论文）|
| volume | String | 卷号 |
| issue | String | 期号 |
| pages | String | 页码范围 |
| publisher | String | 出版社或授予学位的学校 |
| degree | String | 学位类型（硕士/博士）|
| conference_name | String | 会议名称 |
| patent_number | String | 专利号 |
| patent_type | String | 专利类型（发明/实用新型/外观设计）|
| cited_count | Int32 | 被引次数 |
| download_count | Int32 | 下载次数 |
| source_url | String | 来源URL |
| import_time | DateTime | 导入时间戳 |
| rank | Int32 | 排名（搜索结果中的排名）|

## 故障排查

### 1. ClickHouse连接失败

**错误信息：**
```
❌ ClickHouse连接失败: ...
```

**解决方案：**

```bash
# 检查ClickHouse服务状态
sudo service clickhouse-server status

# 启动ClickHouse服务
sudo service clickhouse-server start

# 测试连接
clickhouse-client --query "SELECT 1"
```

### 2. 网络连接超时

**错误信息：**
```
❌ 抓取失败: Timeout
```

**解决方案：**

1. 检查网络连接
2. 增加超时时间：
   ```python
   TIMEOUT = 60.0  # 默认30秒
   ```
3. 降低并发数：
   ```python
   MAX_CONCURRENT_REQUESTS = 5  # 降低并发
   ```

### 3. 反爬虫检测

**错误信息：**
```
❌ 抓取失败: HTTP 403
```

**解决方案：**

1. 增加请求延迟：
   ```python
   REQUEST_DELAY = (2.0, 5.0)  # 增大延迟
   ```
2. 降低并发数：
   ```python
   MAX_CONCURRENT_REQUESTS = 5
   ```
3. 使用代理（需要自行实现）

### 4. 内存不足

**错误信息：**
```
MemoryError: ...
```

**解决方案：**

1. 降低并发数：
   ```python
   MAX_CONCURRENT_REQUESTS = 5
   ```
2. 减小批量大小：
   ```python
   BATCH_SIZE = 500
   ```
3. 增加系统交换空间

### 5. 数据重复

**问题：** ClickHouse中出现重复记录

**解决方案：**

```sql
-- 查找重复记录
SELECT uid, COUNT(*) as count
FROM academic_db.CNKI
GROUP BY uid
HAVING count > 1;

-- 删除重复记录（保留最新的）
ALTER TABLE academic_db.CNKI
DELETE WHERE (uid, import_time) NOT IN (
    SELECT uid, max(import_time)
    FROM academic_db.CNKI
    GROUP BY uid
);
```

**注意：** 程序已内置去重机制，使用临时表+DISTINCT确保数据唯一性。

## 页面结构研究

使用研究工具分析CNKI页面结构：

```bash
cd /home/hkustgz/Us/academic-scraper

# 运行页面结构研究工具
venv/bin/python temp/research_cnki_pages.py
```

**输出文件：**

- HTML文件：`temp/cnki_samples/*.html`
- 分析结果：`temp/cnki_samples/*_analysis.json`

**用途：**

- 了解CNKI页面结构
- 提取CSS选择器和XPath
- 优化解析逻辑

## 开发和调试

### 1. 测试单个页面

修改 `cnki_fetcher.py`，添加测试代码：

```python
# 测试单个URL
test_url = "https://cnki.net/..."
fetcher = create_fetcher()
html = fetch_page(test_url, fetcher)
print(html[:500])  # 打印前500字符
```

### 2. 调试解析逻辑

```python
# 测试解析函数
from bs4 import BeautifulSoup
soup = BeautifulSoup(html, 'html.parser')
# 在这里添加调试代码
```

### 3. 查看详细错误

在程序中添加调试输出：

```python
import traceback
try:
    # 你的代码
except Exception as e:
    traceback.print_exc()
```

## 常见问题

**Q: 抓取速度很慢怎么办？**

A: 适当提高 `MAX_CONCURRENT_REQUESTS`，但要注意反爬。建议从15逐步增加。

**Q: 如何只抓取特定类型的文献？**

A: 修改 `get_all_dates()` 函数，添加类型过滤逻辑。

**Q: 数据能否导出为CSV？**

A: 可以使用ClickHouse客户端导出：
```bash
clickhouse-client --query "SELECT * FROM academic_db.CNKI FORMAT CSVWithNames" > output.csv
```

**Q: 如何更新已有数据？**

A: 程序会自动跳过已完成的日期。如需重新抓取，删除进度文件：
```bash
rm log/cnki_fetch_progress.json
```

**Q: 支持增量更新吗？**

A: 支持。程序会记录已完成的日期，下次运行时自动续传。

## 技术支持

如遇问题：

1. 查看日志文件：`log/cnki_fetch.log`
2. 查看进度文件：`log/cnki_fetch_progress.json`
3. 检查ClickHouse连接
4. 检查网络连接

## 版本历史

- v0.1.0 (2024-01-15): 初始版本，支持基础框架
- 后续版本将添加完整的解析逻辑

## 许可证

本项目遵循学术规范，仅用于学术研究目的。使用时请遵守CNKI的服务条款和robots.txt规定。
