# DBLP数据源集成设计文档

**日期:** 2026-04-22
**状态:** 设计中
**实现方案:** 增量扩展

## 1. 概述

### 1.1 目标
在学术数据看板中添加DBLP作为第三个数据源，支持单独查询和合并到"全部数据"统计中。

### 1.2 核心需求
- DBLP可以单独查询：`/api/aggregated?source=dblp`
- DBLP包含在"全部数据"中：`/api/aggregated?source=all`
- 跨数据源去重：论文数、作者数、期刊数需跨源UNION去重
- 引用字段只统计有数据的数据源（OpenAlex和Semantic）
- 支持DBLP特有字段：CCF等级、出版物类型、发表场所类型

## 2. 数据源字段支持矩阵

| 统计指标 | OpenAlex | Semantic | DBLP | 全部数据 | 去重方式 |
|---------|----------|----------|------|---------|---------|
| 总论文数 | ✅ | ✅ | ✅ | 跨源去重 | DOI (优先) + title |
| 唯一作者 | ✅ | ✅ | ✅ | 跨源去重 | author_name |
| 唯一期刊 | ✅ | ✅ | ✅ | 跨源去重 | venue/journal |
| 按日期统计 | ✅ | ✅ | ✅ | 跨源去重 | DOI + title + publication_date |
| 引用分布 | ✅ | ✅ | ❌ | 仅OA+Sem | DOI |
| 高引用数 | ✅ | ✅ | ❌ | 仅OA+Sem | DOI |
| FWCI分布 | ✅ | ❌ | ❌ | 仅OA | DOI |
| 作者类型 | ✅ | ✅ | ❌ | 仅OA+Sem | - |
| Top国家 | ✅ | ❌ | ❌ | 仅OA | DOI |
| 机构类型 | ✅ | ❌ | ❌ | 仅OA | DOI |
| **CCF等级** | ❌ | ❌ | ✅ | 仅DBLP | - |
| **出版物类型** | ❌ | ❌ | ✅ | 仅DBLP | - |
| **发表场所类型** | ❌ | ❌ | ✅ | 仅DBLP | - |

## 3. DBLP表结构

### 3.1 关键字段
```sql
dblp_key: String              -- DBLP唯一标识
title: String                 -- 论文标题
year: String                  -- 年份
publication_date: String      -- 发表日期
venue: String                 -- 发表场所（相当于journal）
venue_type: String            -- 发表场所类型
ccf_class: String             -- CCF分类
author_name: String           -- 作者姓名
author_rank: UInt8            -- 作者排名
doi: String                   -- DOI
type: String                  -- 出版物类型
institution: String           -- 机构名称
```

### 3.2 DBLP特有的统计字段

#### 3.2.1 CCF等级分布
```sql
SELECT ccf_class, uniqHLL12(doi) as count
FROM dblp
WHERE ccf_class != ''
GROUP BY ccf_class
ORDER BY count DESC
```

#### 3.2.2 出版物类型分布
```sql
SELECT type, uniqHLL12(doi) as count
FROM dblp
WHERE type != ''
GROUP BY type
ORDER BY count DESC
```

#### 3.2.3 发表场所类型分布
```sql
SELECT venue_type, uniqHLL12(doi) as count
FROM dblp
WHERE venue_type != '' AND venue_type != 'unknown'
GROUP BY venue_type
ORDER BY count DESC
```

## 4. 修改文件清单

### 4.1 config.py
**修改内容：**
- 添加DBLP表配置：`'dblp': 'dblp'`
- 可选：添加数据源字段支持配置

### 4.2 api_server.py
**修改内容：**
- 添加跨数据源去重函数
- 修改`get_aggregated_data()`：添加DBLP查询分支
- 修改`get_all_sources_data()`：添加DBLP合并逻辑
- 修改缓存预加载和清理逻辑
- 添加DBLP特有字段查询

## 5. 核心函数设计

### 5.1 跨数据源去重函数

#### 5.1.1 总论文数去重（DOI + title）
```python
def query_total_unique_papers():
    """查询三个表的总唯一论文数（DOI优先）"""
    sql = """
    SELECT uniqExact(doi) as count
    FROM (
        SELECT doi FROM OpenAlex WHERE doi != ''
        UNION ALL
        SELECT doi FROM semantic WHERE doi != ''
        UNION ALL
        SELECT doi FROM dblp WHERE doi != ''
    )
    WHERE doi != ''
    """
    return query_clickhouse(sql)
```

#### 5.1.2 唯一作者去重（author_name）
```python
def query_total_unique_authors():
    """查询三个表的总唯一作者数"""
    sql = """
    SELECT uniqExact(author_name) as count
    FROM (
        SELECT author_id as author_name FROM OpenAlex WHERE author_id != ''
        UNION ALL
        SELECT author_id as author_name FROM semantic WHERE author_id != ''
        UNION ALL
        SELECT author_name FROM dblp WHERE author_name != ''
    )
    WHERE author_name != ''
    """
    return query_clickhouse(sql)
```

#### 5.1.3 唯一期刊去重（venue/journal）
```python
def query_total_unique_venues():
    """查询三个表的总唯一期刊数"""
    sql = """
    SELECT uniqExact(venue) as count
    FROM (
        SELECT journal as venue FROM OpenAlex WHERE journal != ''
        UNION ALL
        SELECT journal as venue FROM semantic WHERE journal != ''
        UNION ALL
        SELECT venue FROM dblp WHERE venue != ''
    )
    WHERE venue != ''
    """
    return query_clickhouse(sql)
```

#### 5.1.4 按日期统计去重
```python
def query_papers_by_date_union():
    """跨数据源按日期统计论文数（DOI去重）"""
    sql = """
    SELECT date, uniqExact(doi) as count
    FROM (
        SELECT
            formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
            doi
        FROM OpenAlex
        WHERE publication_date != '' AND length(publication_date) > 0
        UNION ALL
        SELECT
            formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
            doi
        FROM semantic
        WHERE publication_date != '' AND length(publication_date) > 0
        UNION ALL
        SELECT
            formatDateTime(toDateOrNull(publication_date), '%Y-%m') as date,
            doi
        FROM dblp
        WHERE publication_date != '' AND length(publication_date) > 0
    )
    WHERE date != ''
    GROUP BY date
    ORDER BY date DESC
    """
    return query_clickhouse(sql)
```

### 5.2 DBLP统计查询

#### 5.2.1 DBLP基础统计
```python
def get_dblp_statistics(table_name):
    """获取DBLP基础统计"""
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_name) as unique_authors,
        uniqHLL12(venue) as unique_journals,
        0 as unique_institutions,
        0 as high_citations,
        0 as avg_fwci
    FROM {table_name}
    SETTINGS max_threads=1, max_execution_time=30
    """
    return query_clickhouse(stats_sql)
```

#### 5.2.2 DBLP特有字段查询
```python
def get_dblp_specific_fields(table_name):
    """获取DBLP特有字段统计"""
    result = {}

    # CCF等级分布
    ccf_sql = f"""
    SELECT ccf_class, uniqHLL12(doi) as count
    FROM {table_name}
    WHERE ccf_class != ''
    GROUP BY ccf_class
    ORDER BY count DESC
    """
    ccf_result = query_clickhouse(ccf_sql)
    if ccf_result:
        result['ccf_class_distribution'] = {row[0]: int(row[1]) for row in ccf_result.result_rows}

    # 出版物类型分布
    type_sql = f"""
    SELECT type, uniqHLL12(doi) as count
    FROM {table_name}
    WHERE type != ''
    GROUP BY type
    ORDER BY count DESC
    """
    type_result = query_clickhouse(type_sql)
    if type_result:
        result['publication_type_distribution'] = {row[0]: int(row[1]) for row in type_result.result_rows}

    # 发表场所类型分布
    venue_sql = f"""
    SELECT venue_type, uniqHLL12(doi) as count
    FROM {table_name}
    WHERE venue_type != '' AND venue_type != 'unknown'
    GROUP BY venue_type
    ORDER BY count DESC
    """
    venue_result = query_clickhouse(venue_sql)
    if venue_result:
        result['venue_type_distribution'] = {row[0]: int(row[1]) for row in venue_result.result_rows}

    return result
```

## 6. API响应格式

### 6.1 DBLP单独查询响应
```json
{
  "papers_by_date": {
    "2026-03": 150,
    "2026-02": 200
  },
  "citations_distribution": {},
  "author_types": {},
  "top_journals": {
    "Nature": 50,
    "Science": 40
  },
  "top_countries": {},
  "institution_types": {},
  "fwci_distribution": {},
  "ccf_class_distribution": {
    "A": 500,
    "B": 800,
    "C": 1200
  },
  "publication_type_distribution": {
    "article": 1000,
    "inproceedings": 1500
  },
  "venue_type_distribution": {
    "journal": 1000,
    "conference": 1500
  },
  "statistics": {
    "total_papers": 2500,
    "unique_authors": 1800,
    "unique_journals": 150,
    "unique_institutions": 0,
    "high_citations": 0,
    "avg_fwci": 0
  },
  "source": "dblp",
  "table": "dblp"
}
```

### 6.2 全部数据查询响应（包含DBLP）
```json
{
  "papers_by_date": {
    "2026-03": 1500,
    "2026-02": 2000
  },
  "citations_distribution": {
    "0": 5000,
    "1-5": 3000
  },
  "author_types": {
    "faculty": 8000,
    "student": 5000
  },
  "top_journals": {
    "Nature": 500,
    "Science": 400
  },
  "top_countries": {
    "USA": 10000,
    "China": 8000
  },
  "institution_types": {
    "education": 15000,
    "government": 3000
  },
  "fwci_distribution": {
    "0.5-1": 5000,
    "1-2": 8000
  },
  "ccf_class_distribution": {
    "A": 500,
    "B": 800,
    "C": 1200
  },
  "publication_type_distribution": {
    "article": 1000,
    "inproceedings": 1500
  },
  "venue_type_distribution": {
    "journal": 1000,
    "conference": 1500
  },
  "statistics": {
    "total_papers": 50000,
    "unique_authors": 30000,
    "unique_journals": 5000,
    "unique_institutions": 8000,
    "high_citations": 5000,
    "avg_fwci": 1.5
  },
  "source": "all",
  "table": "all",
  "_source_data": {
    "openalex": {...},
    "semantic": {...},
    "dblp": {...}
  }
}
```

## 7. 实现步骤

### 步骤1: 修改config.py
- [ ] 在`TABLES`字典中添加`'dblp': 'dblp'`

### 步骤2: 添加跨数据源去重函数
- [ ] 实现`query_total_unique_papers()`
- [ ] 实现`query_total_unique_authors()`
- [ ] 实现`query_total_unique_venues()`
- [ ] 实现`query_papers_by_date_union()`

### 步骤3: 修改get_aggregated_data()
- [ ] 添加DBLP分支的基础统计查询
- [ ] 添加DBLP特有字段查询（CCF、出版物类型、场所类型）
- [ ] 处理DBLP无字段的返回空值

### 步骤4: 修改get_all_sources_data()
- [ ] 在循环中添加DBLP数据处理
- [ ] 合并DBLP的按日期统计
- [ ] 合并DBLP的Top期刊
- [ ] 添加DBLP特有字段的合并

### 步骤5: 修改缓存逻辑
- [ ] 在`preload_all_caches()`中添加DBLP
- [ ] 在启动清除缓存中添加DBLP
- [ ] 在智能缓存逻辑中添加DBLP支持

### 步骤6: 测试验证
- [ ] 测试DBLP单独查询
- [ ] 测试全部数据包含DBLP
- [ ] 验证跨数据源去重正确性
- [ ] 性能测试

## 8. 错误处理

### 8.1 字段缺失处理
- DBLP无引用字段：返回0或空对象
- DBLP无FWCI字段：返回0
- DBLP无国家/机构字段：返回空对象

### 8.2 查询失败降级
```python
try:
    ccf_result = query_clickhouse(ccf_sql)
    if ccf_result:
        result['ccf_class_distribution'] = {...}
    else:
        result['ccf_class_distribution'] = {}
except Exception as e:
    print(f"⚠️ CCF等级查询失败: {e}")
    result['ccf_class_distribution'] = {}
```

### 8.3 性能优化
- 跨数据源UNION查询使用较长超时时间（120秒）
- 使用`uniqHLL12`近似计数提升性能
- 缓存跨数据源去重结果

## 9. 测试要点

### 9.1 功能测试
- [ ] DBLP单独查询：`/api/aggregated?source=dblp`
- [ ] 全部数据包含DBLP：`/api/aggregated?source=all`
- [ ] DBLP特有字段正确显示
- [ ] DBLP无字段返回空值
- [ ] 跨数据源去重验证

### 9.2 性能测试
- [ ] DBLP单独查询 < 10秒
- [ ] 全部数据查询 < 60秒
- [ ] 缓存命中 < 1秒
- [ ] 跨源UNION查询不超时

### 9.3 数据完整性
- [ ] total_papers >= unique_journals
- [ ] 全部数据 >= 任一单数据源
- [ ] 去重后数字合理

## 10. 注意事项

1. **DBLP字段映射**：DBLP使用`venue`和`author_name`，与OpenAlex/Semantic的`journal`和`author_id`不同
2. **跨源去重性能**：UNION查询可能较慢，需要优化超时设置
3. **空值处理**：DBLP特有字段可能为空，需要返回空对象而非错误
4. **缓存一致性**：添加DBLP后需要清除所有旧缓存
5. **向后兼容**：保持现有API接口不变，只是添加DBLP支持
