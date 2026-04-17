# Semantic Scholar 表结构文档

## 表概述

Semantic 表存储从 Semantic Scholar API 获取的学术论文数据，采用"漏斗式分层获取法"策略。数据按作者级别存储，每篇论文的多个作者会展开为多行记录。

**数据库名**: `academic_db`  
**表名**: `semantic`  
**存储引擎**: `MergeTree()`  
**排序键**: `(author_id, doi)`

## 字段说明

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `author_id` | String | 作者在 Semantic Scholar 中的唯一ID | "123456789" |
| `author` | String | 作者姓名 | "Wei Zhang" |
| `uid` | String | 论文在 Semantic Scholar 中的唯一ID | "5c8a7b9f123456789012345" |
| `doi` | String | 论文 DOI 标识符 | "10.1234/example.2025" |
| `title` | String | 论文标题 | "Attention Is All You Need" |
| `rank` | UInt8 | 作者排序（1=第一作者） | 1, 2, 3... |
| `journal` | String | 期刊/会议名称（venue字段） | "NeurIPS", "Nature" |
| `citation_count` | UInt32 | 引用次数 | 50000 |
| `tag` | String | 作者标签 | "第一作者", "最后作者", "其他" |
| `state` | String | 数据状态 | "fetched" |
| `institution_id` | String | 所属机构ID | "" |
| `institution_name` | String | 所属机构名称 | "" |
| `institution_country` | String | 所属机构国家 | "" |
| `institution_type` | String | 机构类型 | "" |
| `raw_affiliation` | String | 原始所属机构信息 | "" |
| `year` | UInt16 | 论文发表年份 | 2025 |
| `publication_date` | String | 论文发表日期 | "2025-03-15" |
| `venue` | String | 发表场所 | "Conference on Neural Information Processing Systems" |
| `journal_name` | String | 期刊名称 | "Nature" |
| `arxiv_id` | String | arXiv ID | "2303.12345" |
| `pubmed_id` | String | PubMed ID | "12345678" |
| `url` | String | 论文URL | "https://www.semanticscholar.org/paper/..." |
| `abstract` | String | 论文摘要 | "This paper proposes a new architecture..." |

## 数据特点

1. **漏斗式分层获取**: 使用三层策略获取数据
   - 第一层：按月 + 学科领域（10个领域）
   - 第二层：按月 + 顶级期刊会议（15个）
   - 第三层：按年 + 常见学术词（20个）

2. **排除 arXiv 论文**: 避免与 OpenAlex 数据重复
3. **多标识符支持**: 同时记录 DOI、arXiv ID、PubMed ID
4. **作者级别存储**: 支持作者排序和标签

## 获取策略详解

### 第一层：按月 + 学科领域
- 时间范围：2025年 → 2010年（倒序）
- 学科领域：计算机科学、机器学习、人工智能、生物、医学、化学、物理、数学、经济学、心理学
- 每个领域每月最多获取1000条
- 预计获取时间：约15分钟

### 第二层：按月 + 顶级期刊
- 顶级期刊：Nature, Science, Cell, NEJM, Lancet
- 顶级会议：CVPR, ICCV, NeurIPS, ICML, ACL, AAAI, IJCAI, KDD, WWW, SIGIR
- 每个期刊每月最多获取1000条
- 预计获取时间：约5分钟

### 第三层：按年 + 常见学术词
- 常见词：method, algorithm, system, analysis, design, framework, model等
- 每个词每年最多获取500条
- 预计获取时间：约3分钟

## 常用查询命令

### 基础统计

```sql
-- 查看总记录数
SELECT count() FROM academic_db.semantic;

-- 查看论文数量（按uid去重）
SELECT count(DISTINCT uid) AS unique_papers FROM academic_db.semantic;

-- 查看作者数量
SELECT count(DISTINCT author_id) AS unique_authors FROM academic_db.semantic;

-- 查看年份分布
SELECT 
    year,
    count(DISTINCT uid) AS paper_count
FROM academic_db.semantic
GROUP BY year
ORDER BY year DESC;

-- 查看引用统计
SELECT 
    sum(citation_count) AS total_citations,
    avg(citation_count) AS avg_citations,
    max(citation_count) AS max_citations,
    median(citation_count) AS median_citations
FROM academic_db.semantic;
```

### 按字段统计

```sql
-- 按发表场所统计
SELECT 
    venue,
    count(DISTINCT uid) AS paper_count,
    sum(citation_count) AS total_citations,
    avg(citation_count) AS avg_citations
FROM academic_db.semantic
GROUP BY venue
ORDER BY paper_count DESC
LIMIT 20;

-- 按期刊统计
SELECT 
    journal_name,
    count(DISTINCT uid) AS paper_count,
    sum(citation_count) AS total_citations
FROM academic_db.semantic
WHERE journal_name != ''
GROUP BY journal_name
ORDER BY paper_count DESC
LIMIT 20;

-- 按年份统计高引用论文
SELECT 
    year,
    count(DISTINCT uid) AS paper_count,
    countIf(citation_count > 1000) AS highly_cited,
    avg(citation_count) AS avg_citations
FROM academic_db.semantic
GROUP BY year
ORDER BY year DESC;
```

### 作者分析

```sql
-- 查看第一作者统计
SELECT 
    author,
    count(DISTINCT uid) AS first_author_papers,
    sum(citation_count) AS total_citations,
    avg(citation_count) AS avg_citations
FROM academic_db.semantic
WHERE tag = '第一作者'
GROUP BY author
ORDER BY first_author_papers DESC
LIMIT 20;

-- 查看多产作者（所有论文）
SELECT 
    author,
    count(DISTINCT uid) AS total_papers,
    sum(citation_count) AS total_citations,
    max(citation_count) AS max_citations
FROM academic_db.semantic
WHERE author_id != ''
GROUP BY author_id, author
HAVING total_papers >= 5
ORDER BY total_papers DESC
LIMIT 20;
```

### 时间序列分析

```sql
-- 按月统计论文趋势
SELECT 
    toYearMonth(toDate(publication_date)) AS year_month,
    count(DISTINCT uid) AS paper_count,
    count(DISTINCT author_id) AS author_count
FROM academic_db.semantic
WHERE publication_date != ''
GROUP BY year_month
ORDER BY year_month DESC
LIMIT 24;

-- 按年份和季度统计
SELECT 
    year,
    toQuarter(toDate(publication_date)) AS quarter,
    count(DISTINCT uid) AS paper_count
FROM academic_db.semantic
WHERE publication_date != ''
GROUP BY year, quarter
ORDER BY year DESC, quarter DESC;
```

### 高级查询

```sql
-- 查找有多个ID标识的论文
SELECT 
    title,
    doi,
    arxiv_id,
    pubmed_id,
    citation_count
FROM academic_db.semantic
WHERE (doi != '' AND arxiv_id != '')
   OR (doi != '' AND pubmed_id != '')
   OR (arxiv_id != '' AND pubmed_id != '')
LIMIT 20;

-- 查找有完整摘要的高引用论文
SELECT 
    title,
    venue,
    year,
    citation_count,
    length(abstract) AS abstract_length
FROM academic_db.semantic
WHERE abstract != '' 
  AND length(abstract) > 500
  AND citation_count > 100
ORDER BY citation_count DESC
LIMIT 20;

-- 查找特定年份的热门论文
SELECT 
    title,
    venue,
    citation_count,
    year
FROM academic_db.semantic
WHERE year = 2024
ORDER BY citation_count DESC
LIMIT 50;
```

## 示例记录查询

### 查询单个论文的完整信息

```sql
SELECT 
    title,
    author,
    rank,
    tag,
    venue,
    journal_name,
    year,
    publication_date,
    citation_count,
    doi,
    arxiv_id,
    pubmed_id,
    substring(abstract, 1, 200) AS abstract_preview
FROM academic_db.semantic
WHERE uid = '5c8a7b9f123456789012345'
ORDER BY rank;
```

### 查询某个特定作者

```sql
SELECT 
    title,
    venue,
    year,
    citation_count,
    tag,
    rank
FROM academic_db.semantic
WHERE author_id = '123456789'
ORDER BY year DESC, citation_count DESC;
```

### 查找顶级会议论文

```sql
SELECT 
    title,
    venue,
    year,
    citation_count,
    author
FROM academic_db.semantic
WHERE venue IN ('NeurIPS', 'ICML', 'CVPR', 'ACL', 'KDD')
  AND year >= 2020
ORDER BY citation_count DESC
LIMIT 50;
```

### 按摘要关键词搜索

```sql
SELECT 
    title,
    venue,
    year,
    citation_count,
    abstract
FROM academic_db.semantic
WHERE abstract LIKE '%transformer%'
   OR abstract LIKE '%attention mechanism%'
   OR abstract LIKE '%neural network%'
ORDER BY citation_count DESC
LIMIT 20;
```

## 数据质量检查

### 检查数据完整性

```sql
-- 检查缺失值统计
SELECT 
    count() AS total_records,
    countIf(title = '') AS missing_title,
    countIf(author = '') AS missing_author,
    countIf(venue = '') AS missing_venue,
    countIf(year = 0) AS missing_year,
    countIf(abstract = '') AS missing_abstract,
    countIf(doi = '' AND arxiv_id = '' AND pubmed_id = '') AS missing_all_ids
FROM academic_db.semantic;

-- 检查数据分布
SELECT 
    count(DISTINCT uid) AS unique_papers,
    count(DISTINCT author_id) AS unique_authors,
    count(DISTINCT venue) AS unique_venues,
    count(DISTINCT year) AS years_covered
FROM academic_db.semantic;

-- 检查异常数据
SELECT 
    countIf(year > 2025) AS future_papers,
    countIf(year < 1900) AS very_old_papers,
    countIf(citation_count > 100000) AS extremely_cited,
    countIf(rank = 0) AS zero_rank
FROM academic_db.semantic;
```

### 重复数据检查

```sql
-- 检查论文级别的重复
SELECT 
    uid,
    count() AS duplicate_count
FROM academic_db.semantic
GROUP BY uid
HAVING duplicate_count > 1
LIMIT 10;

-- 检查DOI重复
SELECT 
    doi,
    count() AS duplicate_count
FROM academic_db.semantic
WHERE doi != ''
GROUP BY doi
HAVING duplicate_count > 1
LIMIT 10;
```

## 数据维护建议

### 定期维护任务

```sql
-- 分析表统计信息
OPTIMIZE TABLE academic_db.semantic FINAL;

-- 查看表存储大小
SELECT 
    formatReadableSize(sum(bytes)) AS table_size,
    sum(rows) AS total_rows
FROM system.parts
WHERE table = 'semantic' AND active;

-- 查看分区信息
SELECT 
    partition,
    rows,
    bytes_on_disk,
    formatReadableSize(bytes_on_disk) AS size
FROM system.parts
WHERE table = 'semantic' AND active
ORDER BY partition DESC;
```

## 性能优化建议

1. **按年份分区**: 为大表创建分区策略
2. **创建物化视图**: 预计算常用统计
3. **使用采样**: 对于探索性分析使用 SAMPLE
4. **定期优化**: 执行 OPTIMIZE TABLE 命令

## 与 OpenAlex 表的差异

| 特性 | Semantic 表 | OpenAlex 表 |
|------|-------------|-------------|
| API来源 | Semantic Scholar | OpenAlex |
| 获取策略 | 漏斗式三层获取 | 按日期并发获取 |
| 时间范围 | 2010-2025 | 灵活配置 |
| 机构信息 | 暂未填充 | 完整机构信息 |
| 论文ID | uid (Semantic Scholar) | uid (OpenAlex URL) |
| 特殊字段 | abstract, arxiv_id, pubmed_id | fwci, citation_percentile, is_retracted |
| arXiv论文 | 已排除 | 包含 |

## 注意事项

1. **机构信息**: 当前版本机构信息字段为空，需要后续补充
2. **去重策略**: 按 uid 去重，同一篇论文可能有多个作者记录
3. **引用时效性**: 引用数据相对稳定，但建议定期更新
4. **摘要字段**: 摘要可能很长，查询时注意截断
5. **ID标识**: 优先使用 uid 作为主键，doi、arxiv_id、pubmed_id 为辅
