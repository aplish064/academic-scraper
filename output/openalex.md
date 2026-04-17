# OpenAlex 表结构文档

## 表概述

OpenAlex 表存储从 OpenAlex API 获取的学术论文数据，采用作者级别的存储方式。每篇论文如果有多个作者，会展开为多行记录。

**数据库名**: `academic_db`  
**表名**: `papers`  
**存储引擎**: `MergeTree()`  
**排序键**: `(author_id, doi)`

## 字段说明

| 字段名 | 类型 | 说明 | 示例值 |
|--------|------|------|--------|
| `author_id` | String | 作者在 OpenAlex 中的唯一ID | "A1234567890" |
| `author` | String | 作者姓名 | "Zhang, Wei" |
| `uid` | String | 论文在 OpenAlex 中的唯一ID | "https://openalex.org/W123456789" |
| `doi` | String | 论文 DOI 标识符 | "10.1234/example.2025" |
| `title` | String | 论文标题 | "Deep Learning for Computer Vision" |
| `rank` | UInt8 | 作者排序（1=第一作者） | 1, 2, 3... |
| `journal` | String | 期刊/会议名称 | "Nature", "CVPR" |
| `citation_count` | UInt32 | 引用次数 | 1250 |
| `tag` | String | 作者标签 | "第一作者", "最后作者", "其他" |
| `state` | String | 数据状态 | "fetched" |
| `institution_id` | String | 所属机构ID | "I123456789" |
| `institution_name` | String | 所属机构名称 | "Stanford University" |
| `institution_country` | String | 所属机构国家 | "United States" |
| `institution_type` | String | 机构类型 | "education" |
| `raw_affiliation` | String | 原始所属机构信息 | "Department of CS, Stanford" |
| `fwci` | Float32 | 归一化引用影响力 | 2.5 |
| `citation_percentile` | UInt8 | 引用百分位 | 95 |
| `primary_topic` | String | 主要研究主题 | "Artificial Intelligence" |
| `is_retracted` | Bool | 是否撤稿 | false |
| `import_date` | Date | 导入日期 | 2025-04-17 |
| `import_time` | DateTime | 导入时间戳 | 2025-04-17 10:30:00 |

## 数据特点

1. **作者级别存储**: 一篇论文有 N 个作者会产生 N 条记录
2. **按日期倒序获取**: 从最新日期开始往回获取
3. **异步并发获取**: 使用 HTTP/2 实现高并发性能
4. **增量更新**: 支持断点续传和增量导入

## 常用查询命令

### 基础统计

```sql
-- 查看总记录数
SELECT count() FROM academic_db.papers;

-- 查看论文数量（按DOI去重）
SELECT count(DISTINCT doi) AS unique_papers FROM academic_db.papers;

-- 查看作者数量（按author_id去重）
SELECT count(DISTINCT author_id) AS unique_authors FROM academic_db.papers;

-- 查看时间范围
SELECT 
    min(publication_date) AS earliest,
    max(publication_date) AS latest
FROM academic_db.papers;

-- 查看引用统计
SELECT 
    sum(citation_count) AS total_citations,
    avg(citation_count) AS avg_citations,
    max(citation_count) AS max_citations,
    quantile(0.5)(citation_count) AS median_citations
FROM academic_db.papers;
```

### 按字段统计

```sql
-- 按期刊/会议统计论文数
SELECT 
    journal,
    count(DISTINCT doi) AS paper_count,
    sum(citation_count) AS total_citations
FROM academic_db.papers
GROUP BY journal
ORDER BY paper_count DESC
LIMIT 20;

-- 按国家统计作者数
SELECT 
    institution_country,
    count(DISTINCT author_id) AS author_count,
    count(DISTINCT doi) AS paper_count
FROM academic_db.papers
WHERE institution_country != ''
GROUP BY institution_country
ORDER BY author_count DESC
LIMIT 20;

-- 按机构统计
SELECT 
    institution_name,
    count(DISTINCT author_id) AS author_count,
    count(DISTINCT doi) AS paper_count,
    avg(fwci) AS avg_fwci
FROM academic_db.papers
WHERE institution_name != ''
GROUP BY institution_name
ORDER BY paper_count DESC
LIMIT 20;

-- 按研究主题统计
SELECT 
    primary_topic,
    count(DISTINCT doi) AS paper_count,
    avg(citation_count) AS avg_citations
FROM academic_db.papers
WHERE primary_topic != ''
GROUP BY primary_topic
ORDER BY paper_count DESC
LIMIT 20;
```

### 作者分析

```sql
-- 查看第一作者论文数排名
SELECT 
    author,
    count(DISTINCT doi) AS first_author_papers,
    sum(citation_count) AS total_citations
FROM academic_db.papers
WHERE tag = '第一作者'
GROUP BY author
ORDER BY first_author_papers DESC
LIMIT 20;

-- 查看高影响力作者（H指数近似）
SELECT 
    author,
    count(DISTINCT doi) AS paper_count,
    sum(citation_count) AS total_citations,
    avg(fwci) AS avg_fwci
FROM academic_db.papers
WHERE author_id != ''
GROUP BY author_id, author
HAVING paper_count >= 5
ORDER BY avg_fwci DESC
LIMIT 20;
```

### 时间序列分析

```sql
-- 按年统计论文发表趋势
SELECT 
    toYear(toDate(parseDateTimeBestEffort(publication_date))) AS year,
    count(DISTINCT doi) AS paper_count,
    count(DISTINCT author_id) AS author_count
FROM academic_db.papers
WHERE publication_date != ''
GROUP BY year
ORDER BY year DESC;

-- 按月统计最近论文
SELECT 
    toYearMonth(toDate(parseDateTimeBestEffort(publication_date))) AS year_month,
    count(DISTINCT doi) AS paper_count
FROM academic_db.papers
WHERE publication_date != ''
GROUP BY year_month
ORDER BY year_month DESC
LIMIT 12;
```

## 示例记录查询

### 查询单个论文的所有作者

```sql
SELECT 
    author,
    rank,
    tag,
    institution_name,
    citation_count
FROM academic_db.papers
WHERE doi = '10.1234/example.2025'
ORDER BY rank;
```

### 查询某个作者的所有论文

```sql
SELECT 
    title,
    journal,
    publication_date,
    citation_count,
    tag
FROM academic_db.papers
WHERE author_id = 'A1234567890'
ORDER BY publication_date DESC;
```

### 查找高引用论文

```sql
SELECT 
    title,
    journal,
    publication_date,
    citation_count,
    arrayJoin(splitByString(' ', author)) AS author_name
FROM academic_db.papers
WHERE citation_count > 1000
ORDER BY citation_count DESC
LIMIT 20;
```

### 查找特定领域的论文

```sql
SELECT 
    title,
    journal,
    citation_count,
    publication_date
FROM academic_db.papers
WHERE primary_topic LIKE '%Artificial Intelligence%'
   OR journal LIKE '%NeurIPS%'
   OR journal LIKE '%ICML%'
ORDER BY citation_count DESC
LIMIT 50;
```

## 数据维护

### 检查数据质量

```sql
-- 检查重复记录
SELECT 
    doi,
    author_id,
    count() AS duplicate_count
FROM academic_db.papers
GROUP BY doi, author_id
HAVING duplicate_count > 1
LIMIT 10;

-- 检查缺失关键字段
SELECT 
    count() AS missing_title,
    countIf(doi = '') AS missing_doi,
    countIf(author = '') AS missing_author,
    countIf(journal = '') AS missing_journal
FROM academic_db.papers;

-- 检查异常引用数
SELECT 
    count() AS extremely_high_citations
FROM academic_db.papers
WHERE citation_count > 100000;
```

### 数据更新

```sql
-- 查看最近导入的数据
SELECT 
    import_date,
    import_time,
    count() AS imported_count
FROM academic_db.papers
GROUP BY import_date, import_time
ORDER BY import_time DESC
LIMIT 10;

-- 清理测试数据（谨慎使用）
-- ALTER TABLE academic_db.papers DELETE WHERE import_date < '2025-01-01';
```

## 性能优化建议

1. **创建物化视图**: 用于常用统计查询
2. **分区策略**: 按年份或月份分区
3. **索引优化**: 在常用查询字段上创建索引
4. **数据采样**: 对于探索性分析使用 SAMPLE 子句

## 注意事项

1. **数据去重**: 该表允许同一作者-论文组合存在多条记录（因为可能有多个机构）
2. **引用时效性**: 引用数据随时间变化，需要定期更新
3. **作者消歧**: author_id 可能存在同名人问题
4. **机构名称**: 机构名称可能存在多种拼写变体
