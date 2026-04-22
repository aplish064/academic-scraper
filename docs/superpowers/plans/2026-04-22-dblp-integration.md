# DBLP数据源集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-step. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在学术数据看板API服务器中添加DBLP作为第三个数据源，支持单独查询和跨数据源去重统计

**Architecture:** 增量扩展方案 - 在现有OpenAlex和Semantic数据源基础上添加DBLP支持，通过跨数据源UNION查询实现去重统计

**Tech Stack:** Python, Flask, ClickHouse, Redis

---

## File Structure

```
dashboard/
├── config.py (修改 - 添加DBLP表配置)
└── api_server.py (修改 - 添加DBLP查询和合并逻辑)
```

**修改的文件：**
- `dashboard/config.py` - 添加DBLP表名配置
- `dashboard/api_server.py` - 添加跨源去重函数、DBLP查询分支、合并逻辑

---

## Task 1: 添加DBLP表配置

**Files:**
- Modify: `dashboard/config.py`

- [ ] **Step 1: 在TABLES字典中添加DBLP配置**

在`config.py`文件的TABLES字典中添加DBLP表配置：

```python
# 数据表配置
TABLES = {
    'openalex': 'OpenAlex',       # OpenAlex数据表
    'semantic': 'semantic',        # Semantic Scholar数据表
    'dblp': 'dblp'                 # DBLP数据表 (新增)
}
```

- [ ] **Step 2: 验证配置文件语法**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python -c "from config import TABLES; print(TABLES)"`

预期输出:
```
{'openalex': 'OpenAlex', 'semantic': 'semantic', 'dblp': 'dblp'}
```

- [ ] **Step 3: 提交配置修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/config.py
git commit -m "feat: add dblp table configuration"
```

---

## Task 2: 添加跨数据源论文去重函数

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在query_total_unique_journals()函数后添加query_total_unique_papers()函数**

在`api_server.py`中，找到`query_total_unique_journals()`函数（约第137行），在其后添加新函数：

```python
def query_total_unique_papers():
    """查询三个表的总唯一论文数（DOI去重）"""
    try:
        client = get_ch_client()
        if not client:
            return 0

        # 使用UNION ALL获取三个表的所有DOI，然后去重
        paper_sql = """
        SELECT uniqExact(doi) as count
        FROM (
            SELECT doi FROM OpenAlex WHERE doi != ''
            UNION ALL
            SELECT doi FROM semantic WHERE doi != ''
            UNION ALL
            SELECT doi FROM dblp WHERE doi != ''
        )
        WHERE doi != ''
        SETTINGS max_execution_time=120
        """

        result = client.query(paper_sql)
        if result and result.result_rows:
            return result.result_rows[0][0]
        return 0
    except Exception as e:
        print(f"⚠️  查询总论文数失败: {e}")
        return 0
```

- [ ] **Step 2: 测试函数是否可以正常导入**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python -c "from api_server import query_total_unique_papers; print('Function imported successfully')"`

预期输出:
```
Function imported successfully
```

- [ ] **Step 3: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add query_total_unique_papers function for cross-source deduplication"
```

---

## Task 3: 添加跨数据源作者去重函数

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在query_total_unique_papers()后添加query_total_unique_authors()函数**

```python
def query_total_unique_authors():
    """查询三个表的总唯一作者数（按author_name去重）"""
    try:
        client = get_ch_client()
        if not client:
            return 0

        # 使用UNION ALL获取三个表的所有作者，然后去重
        author_sql = """
        SELECT uniqExact(author_name) as count
        FROM (
            SELECT author_id as author_name FROM OpenAlex WHERE author_id != ''
            UNION ALL
            SELECT author_id as author_name FROM semantic WHERE author_id != ''
            UNION ALL
            SELECT author_name FROM dblp WHERE author_name != ''
        )
        WHERE author_name != ''
        SETTINGS max_execution_time=120
        """

        result = client.query(author_sql)
        if result and result.result_rows:
            return result.result_rows[0][0]
        return 0
    except Exception as e:
        print(f"⚠️  查询总作者数失败: {e}")
        return 0
```

- [ ] **Step 2: 测试函数导入**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python -c "from api_server import query_total_unique_authors; print('OK')"`

预期输出: `OK`

- [ ] **Step 3: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add query_total_unique_authors function for cross-source deduplication"
```

---

## Task 4: 添加跨数据源期刊去重函数

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在query_total_unique_authors()后添加query_total_unique_venues()函数**

```python
def query_total_unique_venues():
    """查询三个表的总唯一期刊数（按venue/journal去重）"""
    try:
        client = get_ch_client()
        if not client:
            return 0

        # 使用UNION ALL获取三个表的所有期刊，然后去重
        venue_sql = """
        SELECT uniqExact(venue) as count
        FROM (
            SELECT journal as venue FROM OpenAlex WHERE journal != ''
            UNION ALL
            SELECT journal as venue FROM semantic WHERE journal != ''
            UNION ALL
            SELECT venue FROM dblp WHERE venue != ''
        )
        WHERE venue != ''
        SETTINGS max_execution_time=120
        """

        result = client.query(venue_sql)
        if result and result.result_rows:
            return result.result_rows[0][0]
        return 0
    except Exception as e:
        print(f"⚠️  查询总期刊数失败: {e}")
        return 0
```

- [ ] **Step 2: 测试函数导入**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python -c "from api_server import query_total_unique_venues; print('OK')"`

预期输出: `OK`

- [ ] **Step 3: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add query_total_unique_venues function for cross-source deduplication"
```

---

## Task 5: 添加跨数据源按日期统计去重函数

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在query_total_unique_venues()后添加query_papers_by_date_union()函数**

```python
def query_papers_by_date_union():
    """跨数据源按日期统计论文数（DOI去重）"""
    try:
        client = get_ch_client()
        if not client:
            return {}

        date_sql = """
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
        SETTINGS max_execution_time=120
        """

        result = client.query(date_sql)
        papers_by_date = {}
        if result:
            for row in result.result_rows:
                papers_by_date[str(row[0])] = int(row[1])
        return papers_by_date
    except Exception as e:
        print(f"⚠️  查询跨源按日期统计失败: {e}")
        return {}
```

- [ ] **Step 2: 测试函数导入**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python -c "from api_server import query_papers_by_date_union; print('OK')"`

预期输出: `OK`

- [ ] **Step 3: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add query_papers_by_date_union function for cross-source deduplication"
```

---

## Task 6: 在get_aggregated_data()中添加DBLP基础统计

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在步骤1统计总览中添加DBLP分支**

找到`get_aggregated_data()`函数中的步骤1统计总览部分（约第343-383行），在`if source == 'openalex':`和`else:`之间添加DBLP分支：

```python
if source == 'openalex':
    # OpenAlex有完整字段，使用近似计数大幅提升性能
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_id) as unique_authors,
        uniqHLL12(journal) as unique_journals,
        uniqHLL12(institution_name) as unique_institutions,
        uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
        round(avgIf(fwci, fwci > 0), 2) as avg_fwci
    FROM {table_name}
    SETTINGS max_threads=4, max_execution_time=30
    """
elif source == 'dblp':  # 新增DBLP分支
    # DBLP字段较少，使用简化统计
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
else:
    # Semantic字段较少，使用简化统计
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_id) as unique_authors,
        uniqHLL12(journal) as unique_journals,
        0 as unique_institutions,
        uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
        0 as avg_fwci
    FROM {table_name}
    SETTINGS max_threads=1, max_execution_time=30
    """
```

- [ ] **Step 2: 修改Top期刊查询以支持DBLP的venue字段**

找到步骤5 Top期刊查询部分（约第459-481行），修改SQL以支持DBLP的venue字段：

```python
# 5. Top期刊 - 使用DOI去重
step_start = time.time()
print(f"[步骤 5/8] Top期刊查询...")

# 根据数据源选择字段名
journal_field = 'venue' if source == 'dblp' else 'journal'

journal_sql = f"""
SELECT
    {journal_field},
    uniqHLL12(doi) as count
FROM {table_name}
WHERE {journal_field} != ''
    AND length({journal_field}) > 3
    AND lower({journal_field}) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
GROUP BY {journal_field}
ORDER BY count DESC
LIMIT 50
SETTINGS max_threads=8, max_execution_time=60
"""

journal_result = query_clickhouse(journal_sql)
if journal_result:
    for row in journal_result.result_rows:
        result['top_journals'][row[0]] = int(row[1])
step_time = time.time() - step_start
print(f"  ✓ 完成 (耗时: {step_time:.2f}秒, 期刊数: {len(result['top_journals'])})")
```

- [ ] **Step 3: 在result初始化中添加DBLP特有字段**

找到`result`字典初始化部分（约第328-339行），添加DBLP特有字段：

```python
result = {
    'papers_by_date': {},
    'citations_distribution': {},
    'author_types': {},
    'top_journals': {},
    'top_countries': {},
    'institution_types': {},
    'fwci_distribution': {},
    'ccf_class_distribution': {},       # 新增
    'publication_type_distribution': {}, # 新增
    'venue_type_distribution': {},      # 新增
    'statistics': {},
    'source': source,
    'table': table_name
}
```

- [ ] **Step 4: 测试API服务器启动**

运行: `cd /home/hkustgz/Us/academic-scraper/dashboard && timeout 5 ../venv/bin/python api_server.py 2>&1 | head -20`

预期输出包含: `✓ dblp (dblp): XXXXX 条记录`

- [ ] **Step 5: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add dblp basic statistics support in get_aggregated_data"
```

---

## Task 7: 添加DBLP特有字段查询

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在get_aggregated_data()中添加DBLP特有字段查询**

在步骤8 FWCI分布查询后（约第564行），添加DBLP特有字段查询：

```python
# 9. DBLP特有字段查询（仅DBLP）
if source == 'dblp':
    step_start = time.time()
    print(f"[步骤 9/9] CCF等级分布查询...")
    ccf_sql = f"""
    SELECT
        ccf_class,
        uniqHLL12(doi) as count
    FROM {table_name}
    WHERE ccf_class != ''
    GROUP BY ccf_class
    ORDER BY count DESC
    """
    ccf_result = query_clickhouse(ccf_sql)
    if ccf_result:
        for row in ccf_result.result_rows:
            result['ccf_class_distribution'][row[0]] = int(row[1])
    step_time = time.time() - step_start
    print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")

    step_start = time.time()
    print(f"[步骤 10/10] 出版物类型分布查询...")
    pubtype_sql = f"""
    SELECT
        type,
        uniqHLL12(doi) as count
    FROM {table_name}
    WHERE type != ''
    GROUP BY type
    ORDER BY count DESC
    """
    pubtype_result = query_clickhouse(pubtype_sql)
    if pubtype_result:
        for row in pubtype_result.result_rows:
            result['publication_type_distribution'][row[0]] = int(row[1])
    step_time = time.time() - step_start
    print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")

    step_start = time.time()
    print(f"[步骤 11/11] 发表场所类型分布查询...")
    venuetype_sql = f"""
    SELECT
        venue_type,
        uniqHLL12(doi) as count
    FROM {table_name}
    WHERE venue_type != '' AND venue_type != 'unknown'
    GROUP BY venue_type
    ORDER BY count DESC
    """
    venuetype_result = query_clickhouse(venuetype_sql)
    if venuetype_result:
        for row in venuetype_result.result_rows:
            result['venue_type_distribution'][row[0]] = int(row[1])
    step_time = time.time() - step_start
    print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")
```

- [ ] **Step 2: 修改print语句中的步骤计数**

将之前的步骤8/8改为步骤8/11，步骤总数需要更新。将所有`print(f"[步骤 X/8]`改为`print(f"[步骤 X/11]`（X为1-8）

- [ ] **Step 3: 测试DBLP查询**

运行: `curl "http://localhost:8080/api/aggregated?source=dblp" 2>/dev/null | python -m json.tool | grep -E "(ccf_class_distribution|publication_type_distribution|venue_type_distribution)" -A 5`

预期输出包含DBLP特有字段的统计结果

- [ ] **Step 4: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add dblp specific fields query (CCF, publication type, venue type)"
```

---

## Task 8: 在get_all_sources_data()中添加DBLP处理

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在get_all_sources_data()中添加DBLP特有字段初始化**

找到`get_all_sources_data()`函数中的数据源独立数据初始化部分（约第624-633行），添加DBLP特有字段：

```python
# 数据源独立数据
source_papers_by_date = {}
source_citations_dist = {}
source_journals = {}
source_countries = {}
source_institution_types = {}
source_fwci_dist = {}
source_ccf_dist = {}              # 新增
source_pubtype_dist = {}         # 新增
source_venuetype_dist = {}       # 新增
source_unique_institutions = 0
source_fwci_sum = 0
source_fwci_count = 0
```

- [ ] **Step 2: 在统计总览部分添加DBLP分支**

找到`get_all_sources_data()`中的统计总览部分（约第635-661行），在OpenAlex分支后添加DBLP分支：

```python
# 1. 统计总览 - 区分数据源，使用去重机制
if source == 'openalex':
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_id) as unique_authors,
        uniqHLL12(journal) as unique_journals,
        uniqHLL12(institution_name) as unique_institutions,
        uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
        sum(fwci) as fwci_sum,
        countIf(fwci > 0) as fwci_count
    FROM {table}
    SETTINGS max_threads=4
    """
elif source == 'dblp':  # 新增DBLP分支
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_name) as unique_authors,
        uniqHLL12(venue) as unique_journals,
        0 as unique_institutions,
        0 as high_citations,
        0 as fwci_sum,
        0 as fwci_count
    FROM {table}
    SETTINGS max_threads=1
    """
else:  # semantic
    stats_sql = f"""
    SELECT
        uniqHLL12(doi) as total_papers,
        uniqHLL12(author_id) as unique_authors,
        uniqHLL12(journal) as unique_journals,
        0 as unique_institutions,
        uniqHLL12(doi) FILTER (WHERE citation_count >= 50) as high_citations,
        0 as fwci_sum,
        0 as fwci_count
    FROM {table}
    SETTINGS max_threads=1
    """
```

- [ ] **Step 3: 在Top期刊查询中添加DBLP字段处理**

找到Top期刊查询部分（约第751-779行），修改以支持DBLP的venue字段：

```python
# 4. Top期刊
step_start = time.time()
print(f"  [步骤 4/7] Top期刊...")

# 根据数据源选择字段名
journal_field = 'venue' if source == 'dblp' else 'journal'

journal_sql = f"""
SELECT
    {journal_field},
    uniqHLL12(doi) as count
FROM {table}
WHERE {journal_field} != ''
    AND length({journal_field}) > 3
    AND lower({journal_field}) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
GROUP BY {journal_field}
ORDER BY count DESC
LIMIT 50
SETTINGS max_threads=8, max_execution_time=60
"""
```

- [ ] **Step 4: 添加DBLP特有字段查询**

在OpenAlex特有数据查询部分后（约第850行），添加DBLP特有字段查询：

```python
# 6. DBLP特有数据（仅DBLP查询）
if source == 'dblp':
    step_start = time.time()
    print(f"  [步骤 6/7] CCF等级查询...")
    ccf_sql = f"""
    SELECT
        ccf_class,
        uniqHLL12(doi) as count
    FROM {table}
    WHERE ccf_class != ''
    GROUP BY ccf_class
    ORDER BY count DESC
    """
    ccf_result = query_clickhouse(ccf_sql)
    if ccf_result:
        for row in ccf_result.result_rows:
            source_ccf_dist[row[0]] = row[1]
    step_time = time.time() - step_start
    print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")

    step_start = time.time()
    print(f"  [步骤 7/7] 出版物类型查询...")
    pubtype_sql = f"""
    SELECT
        type,
        uniqHLL12(doi) as count
    FROM {table}
    WHERE type != ''
    GROUP BY type
    ORDER BY count DESC
    """
    pubtype_result = query_clickhouse(pubtype_sql)
    if pubtype_result:
        for row in pubtype_result.result_rows:
            source_pubtype_dist[row[0]] = row[1]
    step_time = time.time() - step_start
    print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")

    step_start = time.time()
    print(f"  [步骤 8/7] 发表场所类型查询...")
    venuetype_sql = f"""
    SELECT
        venue_type,
        uniqHLL12(doi) as count
    FROM {table}
    WHERE venue_type != '' AND venue_type != 'unknown'
    GROUP BY venue_type
    ORDER BY count DESC
    """
    venuetype_result = query_clickhouse(venuetype_sql)
    if venuetype_result:
        for row in venuetype_result.result_rows:
            source_venuetype_dist[row[0]] = row[1]
    step_time = time.time() - step_start
    print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")
```

- [ ] **Step 5: 在保存source_data时添加DBLP特有字段**

找到`result['_source_data'][source]`赋值部分（约第853-862行），添加DBLP特有字段：

```python
# 保存当前数据源的独立数据到result['_source_data']
result['_source_data'][source] = {
    'papers_by_date': dict(source_papers_by_date),
    'citations_distribution': dict(source_citations_dist),
    'top_journals': dict(source_journals),
    'top_countries': dict(source_countries),
    'institution_types': dict(source_institution_types),
    'fwci_distribution': dict(source_fwci_dist),
    'ccf_class_distribution': dict(source_ccf_dist),              # 新增
    'publication_type_distribution': dict(source_pubtype_dist),  # 新增
    'venue_type_distribution': dict(source_venuetype_dist),      # 新增
    'statistics': source_stats,
    'source': source
}
```

- [ ] **Step 6: 修改"全部数据"统计查询使用跨源去重函数**

找到`get_all_sources_data()`中构建最终结果的部分（约第867-894行），修改为使用跨源去重函数：

```python
# 构建最终结果
# 使用跨数据源去重函数获取准确的统计数字
total_papers = query_total_unique_papers()
total_authors = query_total_unique_authors()
total_venues = query_total_unique_venues()
papers_by_date = query_papers_by_date_union()

result['statistics'] = {
    'total_papers': int(total_papers) if total_papers else 0,
    'unique_authors': int(total_authors) if total_authors else 0,
    'unique_journals': int(total_venues) if total_venues else 0,
    'unique_institutions': int(all_stats['unique_institutions']) if all_stats['unique_institutions'] else 0,
    'high_citations': int(all_stats['high_citations']) if all_stats['high_citations'] else 0,
    'avg_fwci': round(all_stats['fwci_sum'] / all_stats['fwci_count'], 2) if all_stats['fwci_count'] > 0 and all_stats['fwci_sum'] > 0 else 0
}

result['papers_by_date'] = papers_by_date if papers_by_date else all_papers_by_date
result['citations_distribution'] = all_citations_dist
result['top_journals'] = dict(sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50])
result['top_countries'] = all_countries
```

- [ ] **Step 7: 在result初始化中添加DBLP特有字段**

找到`get_all_sources_data()`中的`result`初始化部分（约第588-600行），添加DBLP特有字段：

```python
result = {
    'papers_by_date': {},
    'citations_distribution': {},
    'author_types': {},
    'top_journals': {},
    'top_countries': {},
    'institution_types': {},
    'fwci_distribution': {},
    'ccf_class_distribution': {},       # 新增
    'publication_type_distribution': {}, # 新增
    'venue_type_distribution': {},      # 新增
    'statistics': {},
    'source': 'all',
    'table': 'all',
    '_source_data': {}  # 新增：保存各数据源的独立数据，供切换时使用
}
```

- [ ] **Step 8: 合并DBLP特有字段到全部数据**

在构建最终结果部分（约第898行后），添加DBLP特有字段的合并：

```python
result['top_countries'] = all_countries
result['institution_types'] = all_institution_types if 'openalex' in TABLES else {}
result['fwci_distribution'] = all_fwci_dist if 'openalex' in TABLES else {}

# 合并DBLP特有字段
all_ccf_dist = {}
all_pubtype_dist = {}
all_venuetype_dist = {}

for source, table in TABLES.items():
    if source == 'dblp' and source in result['_source_data']:
        source_data = result['_source_data'][source]
        all_ccf_dist.update(source_data.get('ccf_class_distribution', {}))
        all_pubtype_dist.update(source_data.get('publication_type_distribution', {}))
        all_venuetype_dist.update(source_data.get('venue_type_distribution', {}))

result['ccf_class_distribution'] = all_ccf_dist
result['publication_type_distribution'] = all_pubtype_dist
result['venue_type_distribution'] = all_venuetype_dist
```

- [ ] **Step 9: 测试全部数据查询**

运行: `curl "http://localhost:8080/api/aggregated?source=all" 2>/dev/null | python -m json.tool | grep -E "dblp" -A 2`

预期输出包含DBLP相关数据

- [ ] **Step 10: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add dblp support in get_all_sources_data with cross-source deduplication"
```

---

## Task 9: 修改缓存逻辑

**Files:**
- Modify: `dashboard/api_server.py`

- [ ] **Step 1: 在preload_all_caches()中添加DBLP**

找到`preload_all_caches()`函数（约第964-987行），修改sources列表：

```python
def preload_all_caches():
    """预加载所有数据源的缓存（通过HTTP请求）"""
    if not USE_CACHE or not redis_client:
        print("⚠️  缓存未启用，跳过预加载")
        return

    sources = ['openalex', 'semantic', 'dblp', 'all']  # 添加dblp

    for source in sources:
        print(f"  📦 预加载 {source} 数据源...")
        try:
            import requests
            # 使用较短的超时时间，避免长时间等待
            response = requests.get(f'http://localhost:8080/api/aggregated?source={source}', timeout=300)
            if response.status_code == 200:
                print(f"    ✅ {source} 缓存加载成功")
            else:
                print(f"    ❌ {source} 缓存加载失败: {response.status_code}")
        except requests.exceptions.ConnectionError:
            print(f"    ⚠️  {source} 连接失败（服务器可能还未完全启动）")
        except Exception as e:
            print(f"    ❌ {source} 缓存加载异常: {e}")

    print("  ✅ 所有数据源缓存预加载完成")
```

- [ ] **Step 2: 在启动清除缓存中添加DBLP**

找到启动时清除缓存的部分（约第1054-1068行），修改sources列表：

```python
# 启动时清除所有缓存
if USE_CACHE:
    print("\n" + "="*60)
    print("🔄 清除启动时的旧缓存...")
    print("="*60)
    sources = ['openalex', 'semantic', 'dblp', 'all']  # 添加dblp
    for source in sources:
        cache_key = get_cache_key(source)
        try:
            if redis_client:
                redis_client.delete(cache_key)
                print(f"  ✅ {source} 缓存已清除")
        except Exception as e:
            print(f"  ❌ {source} 缓存清除失败: {e}")
    print("="*60 + "\n")
```

- [ ] **Step 3: 在智能缓存逻辑中添加DBLP支持**

找到智能缓存检查部分（约第291-322行），修改条件判断：

```python
# 智能缓存：检查"全部数据"缓存中是否有该数据源的独立数据
if source in ['openalex', 'semantic', 'dblp']:  # 添加dblp
    all_cache_key = get_cache_key('all')
    all_cached_data = get_from_cache(all_cache_key)
    if all_cached_data and all_cached_data.get('_source_data', {}).get(source):
        print(f"🚀 智能缓存：从全部数据中提取 {source} 独立数据（无需重新查询）")
        source_data = all_cached_data['_source_data'][source]

        # 验证数据完整性
        source_stats = source_data.get('statistics', {})
        if (source_stats.get('unique_journals', 0) == 0 or
            source_stats.get('total_papers', 0) == 0):
            print(f"⚠️  智能缓存数据不完整 (期刊数:{source_stats.get('unique_journals', 0)}, 论文数:{source_stats.get('total_papers', 0)})，重新查询 {source}...")
            redis_client.delete(all_cache_key)
        else:
            # 确保包含所有必需字段
            result = {
                'papers_by_date': source_data.get('papers_by_date', {}),
                'citations_distribution': source_data.get('citations_distribution', {}),
                'top_journals': source_data.get('top_journals', {}),
                'top_countries': source_data.get('top_countries', {}),
                'institution_types': source_data.get('institution_types', {}),
                'fwci_distribution': source_data.get('fwci_distribution', {}),
                'ccf_class_distribution': source_data.get('ccf_class_distribution', {}),        # 新增
                'publication_type_distribution': source_data.get('publication_type_distribution', {}),  # 新增
                'venue_type_distribution': source_data.get('venue_type_distribution', {}),     # 新增
                'statistics': source_stats,
                'source': source,
                'table': TABLES.get(source, source)
            }
            set_to_cache(cache_key, result, ttl=300)

            # 清理NaN值，避免JSON序列化错误
            result = clean_nan_values(result)

            return jsonify(result)
```

- [ ] **Step 4: 在try_merge_from_cache()中添加DBLP**

找到`try_merge_from_cache()`函数（约第140-239行），修改以支持DBLP：

```python
def try_merge_from_cache():
    """尝试从openalex、semantic和dblp缓存合并数据"""
    if not USE_CACHE or not redis_client:
        return None

    # 获取openalex、semantic和dblp的缓存
    openalex_cache = get_from_cache(get_cache_key('openalex'))
    semantic_cache = get_from_cache(get_cache_key('semantic'))
    dblp_cache = get_from_cache(get_cache_key('dblp'))  # 新增

    # 检查三个缓存是否都存在且完整
    if not openalex_cache or not semantic_cache or not dblp_cache:  # 添加dblp检查
        return None

    # 验证数据完整性
    openalex_stats = openalex_cache.get('statistics', {})
    semantic_stats = semantic_cache.get('statistics', {})
    dblp_stats = dblp_cache.get('statistics', {})  # 新增

    if (openalex_stats.get('total_papers', 0) == 0 or
        semantic_stats.get('total_papers', 0) == 0 or
        dblp_stats.get('total_papers', 0) == 0):  # 添加dblp检查
        return None

    try:
        # 合并数据
        merged_data = {
            'papers_by_date': {},
            'citations_distribution': {},
            'author_types': {},
            'top_journals': {},
            'top_countries': {},
            'institution_types': {},
            'fwci_distribution': {},
            'ccf_class_distribution': {},       # 新增
            'publication_type_distribution': {}, # 新增
            'venue_type_distribution': {},      # 新增
            'statistics': {},
            'source': 'all',
            'table': 'all',
            '_source_data': {
                'openalex': openalex_cache,
                'semantic': semantic_cache,
                'dblp': dblp_cache  # 新增
            }
        }

        # 合并论文按日期统计
        for date, count in openalex_cache.get('papers_by_date', {}).items():
            merged_data['papers_by_date'][date] = merged_data['papers_by_date'].get(date, 0) + count

        for date, count in semantic_cache.get('papers_by_date', {}).items():
            merged_data['papers_by_date'][date] = merged_data['papers_by_date'].get(date, 0) + count

        for date, count in dblp_cache.get('papers_by_date', {}).items():  # 新增
            merged_data['papers_by_date'][date] = merged_data['papers_by_date'].get(date, 0) + count

        # ... 其他合并逻辑保持不变 ...

        # 合并DBLP特有字段
        merged_data['ccf_class_distribution'] = dblp_cache.get('ccf_class_distribution', {})
        merged_data['publication_type_distribution'] = dblp_cache.get('publication_type_distribution', {})
        merged_data['venue_type_distribution'] = dblp_cache.get('venue_type_distribution', {})

        # 合并统计数据 - 使用跨源去重函数
        total_papers = query_total_unique_papers()
        total_authors = query_total_unique_authors()
        total_journals = query_total_unique_venues()

        merged_data['statistics'] = {
            'total_papers': total_papers if total_papers > 0 else (
                openalex_stats.get('total_papers', 0) +
                semantic_stats.get('total_papers', 0) +
                dblp_stats.get('total_papers', 0)
            ),
            'unique_authors': total_authors if total_authors > 0 else (
                openalex_stats.get('unique_authors', 0) +
                semantic_stats.get('unique_authors', 0) +
                dblp_stats.get('unique_authors', 0)
            ),
            'unique_journals': total_journals if total_journals > 0 else len(all_journals),
            'unique_institutions': openalex_stats.get('unique_institutions', 0),
            'high_citations': openalex_stats.get('high_citations', 0) + semantic_stats.get('high_citations', 0),
            'avg_fwci': openalex_stats.get('avg_fwci', 0)
        }

        return merged_data

    except Exception as e:
        print(f"⚠️  合并缓存数据失败: {e}")
        return None
```

- [ ] **Step 5: 测试缓存功能**

运行以下命令测试缓存：
```bash
# 清除缓存
redis-cli FLUSHDB

# 启动服务器
cd /home/hkustgz/Us/academic-scraper/dashboard && ../venv/bin/python api_server.py

# 在另一个终端测试查询
curl "http://localhost:8080/api/aggregated?source=dblp" -s | python -m json.tool | head -20
curl "http://localhost:8080/api/aggregated?source=all" -s | python -m json.tool | grep -E "total_papers|unique_authors|unique_journals"
```

预期输出显示正确的统计数字

- [ ] **Step 6: 提交代码**

```bash
git add dashboard/api_server.py
git commit -m "feat: add dblp support to cache preloading and smart caching"
```

---

## Task 10: 测试验证

**Files:**
- Test: Manual API testing

- [ ] **Step 1: 测试DBLP单独查询**

运行: `curl "http://localhost:8080/api/aggregated?source=dblp" -s | python -m json.tool`

验证点:
- [ ] `source` 字段为 `"dblp"`
- [ ] `statistics.total_papers` > 0
- [ ] `statistics.unique_authors` > 0
- [ ] `statistics.unique_journals` > 0
- [ ] `statistics.high_citations` == 0
- [ ] `statistics.avg_fwci` == 0
- [ ] `ccf_class_distribution` 包含数据（A/B/C等级）
- [ ] `publication_type_distribution` 包含数据
- [ ] `venue_type_distribution` 包含数据
- [ ] `citations_distribution` 为空对象 `{}`
- [ ] `top_countries` 为空对象 `{}`

- [ ] **Step 2: 测试全部数据包含DBLP**

运行: `curl "http://localhost:8080/api/aggregated?source=all" -s | python -m json.tool`

验证点:
- [ ] `source` 字段为 `"all"`
- [ ] `_source_data` 包含 `openalex`, `semantic`, `dblp` 三个键
- [ ] `statistics.total_papers` >= 任一单数据源的total_papers
- [ ] `statistics.unique_authors` >= 任一单数据源的unique_authors
- [ ] `statistics.unique_journals` >= 任一单数据源的unique_journals
- [ ] 包含 `ccf_class_distribution`（来自DBLP）
- [ ] 包含 `publication_type_distribution`（来自DBLP）
- [ ] 包含 `venue_type_distribution`（来自DBLP）
- [ ] 包含 `citations_distribution`（来自OpenAlex+Semantic）
- [ ] 包含 `fwci_distribution`（来自OpenAlex）

- [ ] **Step 3: 验证跨数据源去重**

运行以下命令比较去重前后的数字：

```bash
# 获取各数据源单独的数字
echo "OpenAlex papers:"
curl "http://localhost:8080/api/aggregated?source=openalex" -s | python -c "import sys, json; data=json.load(sys.stdin); print(data['statistics']['total_papers'])"

echo "Semantic papers:"
curl "http://localhost:8080/api/aggregated?source=semantic" -s | python -c "import sys, json; data=json.load(sys.stdin); print(data['statistics']['total_papers'])"

echo "DBLP papers:"
curl "http://localhost:8080/api/aggregated?source=dblp" -s | python -c "import sys, json; data=json.load(sys.stdin); print(data['statistics']['total_papers'])"

echo "All papers (deduplicated):"
curl "http://localhost:8080/api/aggregated?source=all" -s | python -c "import sys, json; data=json.load(sys.stdin); print(data['statistics']['total_papers'])"
```

验证点:
- [ ] 全部数据的total_papers < 三个数据源简单相加（说明去重生效）
- [ ] 全部数据的total_papers >= 任一单数据源

- [ ] **Step 4: 性能测试**

```bash
# 测试DBLP单独查询响应时间
time curl "http://localhost:8080/api/aggregated?source=dblp" -s > /dev/null

# 测试全部数据查询响应时间
time curl "http://localhost:8080/api/aggregated?source=all" -s > /dev/null

# 测试缓存命中响应时间
curl "http://localhost:8080/api/aggregated?source=dblp" -s > /dev/null
time curl "http://localhost:8080/api/aggregated?source=dblp" -s > /dev/null
```

验证点:
- [ ] DBLP单独查询 < 10秒
- [ ] 全部数据查询 < 60秒
- [ ] 缓存命中 < 1秒

- [ ] **Step 5: 数据完整性验证**

运行以下脚本验证数据逻辑：

```python
import requests
import json

# 获取DBLP数据
dblp_resp = requests.get('http://localhost:8080/api/aggregated?source=dblp')
dblp_data = dblp_resp.json()

# 验证数据完整性
assert dblp_data['statistics']['total_papers'] >= dblp_data['statistics']['unique_journals'], \
    f"total_papers ({dblp_data['statistics']['total_papers']}) 应该 >= unique_journals ({dblp_data['statistics']['unique_journals']})"

assert dblp_data['statistics']['total_papers'] >= dblp_data['statistics']['unique_authors'], \
    f"total_papers ({dblp_data['statistics']['total_papers']}) 应该 >= unique_authors ({dblp_data['statistics']['unique_authors']})"

# 验证DBLP特有字段存在
assert 'ccf_class_distribution' in dblp_data, "应该包含ccf_class_distribution"
assert 'publication_type_distribution' in dblp_data, "应该包含publication_type_distribution"
assert 'venue_type_distribution' in dblp_data, "应该包含venue_type_distribution"

# 验证DBLP无字段为空
assert dblp_data['statistics']['high_citations'] == 0, "DBLP的high_citations应该为0"
assert dblp_data['statistics']['avg_fwci'] == 0, "DBLP的avg_fwci应该为0"
assert dblp_data['citations_distribution'] == {}, "DBLP的citations_distribution应该为空"

print("✅ 所有数据完整性验证通过")
```

- [ ] **Step 6: 提交测试文档**

```bash
cd /home/hkustgz/Us/academic-scraper
cat > temp/test_dblp_integration.sh << 'EOF'
#!/bin/bash
# DBLP集成测试脚本

echo "=== DBLP集成测试 ==="

# 测试1: DBLP单独查询
echo "测试1: DBLP单独查询"
curl -s "http://localhost:8080/api/aggregated?source=dblp" | python -m json.tool | head -30

# 测试2: 全部数据包含DBLP
echo -e "\n测试2: 全部数据包含DBLP"
curl -s "http://localhost:8080/api/aggregated?source=all" | python -c "import sys, json; data=json.load(sys.stdin); print(json.dumps({'source': data['source'], 'total_papers': data['statistics']['total_papers'], 'has_dblp': 'dblp' in data.get('_source_data', {})}, indent=2))"

# 测试3: 验证跨源去重
echo -e "\n测试3: 跨源去重验证"
for source in openalex semantic dblp all; do
    papers=$(curl -s "http://localhost:8080/api/aggregated?source=$source" | python -c "import sys, json; print(json.load(sys.stdin)['statistics']['total_papers'])")
    echo "$source: $papers papers"
done

echo -e "\n=== 测试完成 ==="
EOF

chmod +x temp/test_dblp_integration.sh
git add temp/test_dblp_integration.sh
git commit -m "test: add DBLP integration test script"
```

---

## Summary Checklist

完成所有任务后，验证以下清单：

- [ ] `config.py` 中已添加DBLP表配置
- [ ] `api_server.py` 中已添加4个跨数据源去重函数
- [ ] `get_aggregated_data()` 支持DBLP单独查询
- [ ] `get_aggregated_data()` 返回DBLP特有字段（CCF、出版物类型、场所类型）
- [ ] `get_all_sources_data()` 包含DBLP数据处理
- [ ] `get_all_sources_data()` 使用跨源去重函数
- [ ] 缓存预加载包含DBLP
- [ ] 智能缓存支持DBLP
- [ ] DBLP单独查询测试通过
- [ ] 全部数据包含DBLP测试通过
- [ ] 跨数据源去重验证通过
- [ ] 性能测试通过
- [ ] 数据完整性验证通过

---

## Completion

完成所有任务后，运行最终测试：

```bash
cd /home/hkustgz/Us/academic-scraper
./temp/test_dblp_integration.sh
```

如果所有测试通过，DBLP数据源集成完成！
