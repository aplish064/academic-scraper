# arXiv Fetcher 使用说明

## 功能

从 arXiv API 获取所有论文并存储到 ClickHouse 数据库。

## 使用方法

### 基本使用

```bash
cd /home/hkustgz/Us/academic-scraper
source venv/bin/activate
python src/arxiv_fetcher.py
```

这将从 2026-04-22 开始获取所有论文，直到 1990 年。

### 自定义参数

```bash
python src/arxiv_fetcher.py --start-date 2026-01-01 --end-year 2020
```

可用参数：
- `--start-date`: 开始日期 (格式: YYYY-MM-DD，默认: 2026-04-22)
- `--end-year`: 结束年份 (默认: 1990)
- `--interval`: 请求间隔秒数 (默认: 1.0)
- `--per-page`: 每页论文数 (默认: 3000)
- `--test-days`: 测试模式，只获取指定天数 (用于测试)

### 测试模式

```bash
# 只获取 3 天的数据用于测试
python src/arxiv_fetcher.py --start-date 2020-12-11 --end-year 2020 --test-days 3
```

## 进度管理

- 进度文件: `log/arxiv_fetch_progress.json`
- 自动保存已完成日期
- 支持中断后恢复运行
- 重新运行会自动跳过已完成日期

## 日志文件

- 主日志: `log/arxiv_fetch.log`
- 错误日志: `log/arxiv_errors.log`

## 数据存储

- 数据库: ClickHouse
- 表名: `academic_db.arxiv`
- 每个作者一行数据

### 表结构

```sql
CREATE TABLE academic_db.arxiv (
    arxiv_id String,              -- arXiv ID (例如: 2101.12345v1)
    uid String,                   -- 唯一标识符
    title String,                 -- 论文标题
    published Date,               -- 发表日期
    updated DateTime,             -- 更新时间
    categories Array(String),     -- 分类标签
    primary_category String,      -- 主分类
    journal_ref String,           -- 期刊引用
    comment String,               -- 评论
    url String,                   -- 论文 URL
    pdf_url String,               -- PDF URL
    author String,                -- 作者姓名
    rank UInt16,                  -- 作者序号 (1, 2, 3, ...)
    tag String,                   -- 作者标签 (第一作者/其他/最后作者)
    affiliation String,           -- 作者机构
    import_date Date              -- 导入日期
) ENGINE = MergeTree()
ORDER BY (arxiv_id, rank)
```

## 数据示例

```
arxiv_id: 2012.04795v2
title: Deformed algebra and the effective dynamics of the interior of black holes
author: Pasquale Bosso, rank: 1, tag: 第一作者
author: Octavio Obregón, rank: 2, tag: 其他
author: Saeed Rastgoo, rank: 3, tag: 其他
author: Wilfredo Yupanqui, rank: 4, tag: 最后作者
```

每个论文会展开为多行，每行代表一个作者。

## 性能

- 处理速度: 约 2-5 秒/天
- 预计总时间: 4-11 小时（完整 13,500 天范围）

## 注意事项

- 遵守 arXiv API 速率限制（1 请求/秒）
- 遇到 HTTP 429 错误会自动暂停 60 秒
- 单个日期失败不影响其他日期
- 只有完全成功才会标记日期为完成
- 作者序号使用 UInt16 类型，支持最多 65,535 个作者

## 常见问题

### 如何查看进度？

```bash
cat log/arxiv_fetch_progress.json
```

### 如何清空数据重新开始？

```bash
# 清空表数据
clickhouse-client --query "TRUNCATE TABLE academic_db.arxiv"

# 删除进度文件
rm log/arxiv_fetch_progress.json
```

### 如何查询已导入的数据？

```bash
# 查看总论文数
clickhouse-client --query "SELECT count(DISTINCT arxiv_id) FROM academic_db.arxiv"

# 查看总行数（含作者展开）
clickhouse-client --query "SELECT count(*) FROM academic_db.arxiv"

# 查看日期范围
clickhouse-client --query "SELECT min(published), max(published) FROM academic_db.arxiv"
```
