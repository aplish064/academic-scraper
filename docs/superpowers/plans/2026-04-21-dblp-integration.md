# DBLP数据源集成实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在dashboard中添加DBLP数据源支持，并完全移除作者合作关系图谱功能

**Architecture:**
- 修改config.py添加DBLP表配置
- 在api_server.py中删除所有图谱API端点，添加DBLP专用查询逻辑
- 在index.html前端添加DBLP数据源选项和特有图表渲染，移除图谱相关代码
- 删除graph.html文件

**Tech Stack:** Python Flask, ClickHouse, Redis, Vanilla JavaScript, Chart.js

---

## 文件结构概览

**需要修改的文件：**
- `dashboard/config.py` - 添加DBLP表映射配置（1处修改）
- `dashboard/api_server.py` - 删除图谱代码，添加DBLP支持（多处修改）
- `dashboard/index.html` - 添加DBLP前端支持，删除图谱代码（多处修改）

**需要删除的文件：**
- `dashboard/graph.html` - 作者合作关系图谱页面

---

## Task 1: 修改config.py添加DBLP配置

**Files:**
- Modify: `dashboard/config.py:14-18`

**目标：** 在TABLES字典中添加DBLP表映射

- [ ] **Step 1: 在TABLES字典中添加dblp配置**

打开`dashboard/config.py`，找到TABLES字典（约第14-18行），修改为：

```python
TABLES = {
    'openalex': 'OpenAlex',
    'semantic': 'semantic',
    'dblp': 'dblp'        # 新增DBLP数据源
}
```

- [ ] **Step 2: 验证语法**

运行：
```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "import config; print(config.TABLES)"
```

预期输出：
```
{'openalex': 'OpenAlex', 'semantic': 'semantic', 'dblp': 'dblp'}
```

- [ ] **Step 3: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/config.py
git commit -m "feat: add DBLP data source to config"
```

---

## Task 2: 删除api_server.py中的图谱相关导入和函数

**Files:**
- Modify: `dashboard/api_server.py:1-1518`

**目标：** 删除所有图谱相关的辅助函数

- [ ] **Step 1: 删除get_merged_papers_sql函数**

找到`get_merged_papers_sql`函数（约第1032行开始），删除整个函数直到`def get_graph_cache_key`之前（约第1032-1091行）。

- [ ] **Step 2: 删除get_graph_cache_key函数**

找到`def get_graph_cache_key`（约第1093行），删除整个函数直到`@app.route('/api/graph/authors')`之前（约第1093-1098行）。

- [ ] **Step 3: 删除/api/graph/authors端点**

找到`@app.route('/api/graph/authors', methods=['GET'])`（约第1100行），删除整个端点函数直到下一个`@app.route`之前（约第1100-1233行）。

- [ ] **Step 4: 删除/api/graph/edges端点**

找到`@app.route('/api/graph/edges', methods=['GET'])`（约第1236行），删除整个端点函数直到下一个`@app.route`之前（约第1236-1349行）。

- [ ] **Step 5: 删除/api/graph/stats端点**

找到`@app.route('/api/graph/stats', methods=['GET'])`（约第1352行），删除整个端点函数直到`if __name__ == '__main__':`之前（约第1352-1449行）。

- [ ] **Step 6: 验证语法**

运行：
```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

预期：无语法错误

- [ ] **Step 7: 提交删除**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "refactor: remove graph collaboration network code from api_server"
```

---

## Task 3: 在api_server.py中添加DBLP统计查询

**Files:**
- Modify: `dashboard/api_server.py:266-582`

**目标：** 在get_aggregated_data函数中添加DBLP数据源的查询逻辑

- [ ] **Step 1: 在get_aggregated_data函数中添加DBLP统计查询**

找到`get_aggregated_data`函数中的统计查询部分（约第342-384行），在`if source == 'openalex':`条件后添加DBLP分支。

在第358行（`else:`分支的stats_sql定义之前）插入：

```python
        elif source == 'dblp':
            # DBLP字段有限，使用简化统计
            stats_sql = f"""
            SELECT
                uniqHLL12(doi) as total_papers,
                uniqHLL12(author_pid) as unique_authors,
                uniqHLL12(venue) as unique_journals,
                0 as unique_institutions,
                0 as high_citations,
                0 as avg_fwci
            FROM {table_name}
            SETTINGS max_threads=1, max_execution_time=30
            """
```

- [ ] **Step 2: 添加DBLP按日期统计（使用year字段）**

找到日期统计部分（约第386-406行），在`date_sql`定义后添加DBLP特殊处理。

在第400行的`SETTINGS max_threads=1`之后，添加：

```python
            # DBLP使用year字段而非publication_date
            if source == 'dblp':
                date_sql = f"""
                SELECT
                    year as date,
                    uniqHLL12(doi) as count
                FROM {table_name}
                WHERE year != '' AND length(year) = 4
                GROUP BY year
                ORDER BY year DESC
                SETTINGS max_threads=1
                """
```

- [ ] **Step 3: 添加DBLP引用数分布（返回空）**

找到引用数分布部分（约第408-435行），在查询执行后添加DBLP特殊处理。

在第434行`step_time = time.time() - step_start`之后添加：

```python
            # DBLP没有citation_count字段，跳过引用数分布
            if source == 'dblp':
                result['citations_distribution'] = {}
                print(f"  ✓ 跳过引用数分布 (DBLP无此字段)")
```

- [ ] **Step 4: 修改Top期刊查询为Top Venues（针对DBLP）**

找到Top期刊查询部分（约第459-481行），修改SQL以支持DBLP的venue字段。

将第462行的journal_sql修改为：

```python
        # Top期刊/venue查询 - DBLP使用venue字段
        if source == 'dblp':
            journal_sql = f"""
            SELECT
                venue,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE venue != ''
                AND length(venue) > 3
                AND lower(venue) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
            GROUP BY venue
            ORDER BY count DESC
            LIMIT 50
            SETTINGS max_threads=8, max_execution_time=60
            """
        else:
            journal_sql = f"""
            SELECT
                journal,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE journal != ''
                AND length(journal) > 3
                AND lower(journal) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
            GROUP BY journal
            ORDER BY count DESC
            LIMIT 50
            SETTINGS max_threads=8, max_execution_time=60
            """
```

- [ ] **Step 5: 验证语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

- [ ] **Step 6: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add DBLP statistics queries to aggregated API"
```

---

## Task 4: 在api_server.py中添加DBLP特有数据查询

**Files:**
- Modify: `dashboard/api_server.py:437-565`

**目标：** 添加DBLP特有的CCF等级、venue类型、年份分布查询

- [ ] **Step 1: 添加DBLP作者类型分布查询（使用ccf_class）**

找到作者类型分布查询部分（约第437-456行），在查询后添加DBLP特殊处理。

在第455行`step_time = time.time() - step_start`之后添加：

```python
            # DBLP使用ccf_class作为作者类型
            if source == 'dblp':
                ccf_sql = f"""
                SELECT
                    ccf_class,
                    count() as count
                FROM {table_name}
                WHERE ccf_class != '' AND ccf_class != 'nan'
                GROUP BY ccf_class
                ORDER BY count DESC
                LIMIT 10
                """

                ccf_result = query_clickhouse(ccf_sql)
                if ccf_result:
                    for row in ccf_result.result_rows:
                        result['author_types'][row[0]] = int(row[1])
                print(f"  ✓ CCF等级分布完成 (耗时: {step_time:.2f}秒)")
            else:
                author_sql = f"""
                SELECT
                    tag,
                    count() as count
                FROM {table_name}
                WHERE tag != ''
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 10
                """

                author_result = query_clickhouse(author_sql)
                if author_result:
                    for row in author_result.result_rows:
                        result['author_types'][row[0]] = int(row[1])
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")
```

注意：需要先删除第438-456行的原有代码，用上面的代码替换。

- [ ] **Step 2: 添加DBLP venue类型分布查询**

在Top国家查询之前（约第483行）插入新的venue类型查询：

```python
        # 7.1 Venue类型分布（仅DBLP支持）
        step_start = time.time()
        print(f"[步骤 7.1/8] Venue类型分布查询...")
        if source == 'dblp':
            venue_type_sql = f"""
            SELECT
                venue_type,
                uniqHLL12(doi) as count
            FROM {table_name}
            WHERE venue_type != '' AND venue_type != 'nan'
            GROUP BY venue_type
            ORDER BY count DESC
            """

            venue_type_result = query_clickhouse(venue_type_sql)
            if venue_type_result:
                for row in venue_type_result.result_rows:
                    result['venue_type_distribution'][row[0]] = int(row[1])
            step_time = time.time() - step_start
            print(f"  ✓ 完成 (耗时: {step_time:.2f}秒)")
        else:
            print(f"  ⊘ 跳过 (仅DBLP支持)")
```

同时需要在result初始化时（约第328-339行）添加venue_type_distribution字段：

```python
    result = {
        'papers_by_date': {},
        'citations_distribution': {},
        'author_types': {},
        'top_journals': {},
        'top_countries': {},
        'institution_types': {},
        'fwci_distribution': {},
        'venue_type_distribution': {},  # 新增
        'statistics': {},
        'source': source,
        'table': table_name
    }
```

- [ ] **Step 3: 调整步骤编号（从8步改为9步）**

由于新增了venue类型查询，需要调整后续的步骤编号。
将"步骤 6/8"改为"步骤 7/9"，"步骤 7/8"改为"步骤 8/9"，"步骤 8/8"改为"步骤 9/9"。

- [ ] **Step 4: 验证语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

- [ ] **Step 5: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add DBLP-specific queries (CCF class, venue type)"
```

---

## Task 5: 修改api_server.py中的全部数据查询逻辑

**Files:**
- Modify: `dashboard/api_server.py:113-240, 583-916`

**目标：** 在get_all_sources_data和query_total_unique_journals中添加DBLP支持

- [ ] **Step 1: 修改query_total_unique_journals函数添加DBLP**

找到`query_total_unique_journals`函数（约第113行），修改SQL添加DBLP的UNION。

将第121-128行的SQL修改为：

```python
        journal_sql = """
        SELECT uniqExact(journal) as count
        FROM (
            SELECT journal FROM OpenAlex
            UNION ALL
            SELECT journal FROM semantic
            UNION ALL
            SELECT venue FROM dblp
        )
        WHERE journal != ''
        """
```

- [ ] **Step 2: 修改try_merge_from_cache函数添加DBLP**

找到`try_merge_from_cache`函数（约第140行），在函数开始处添加DBLP缓存获取。

在第145行（`semantic_cache = get_from_cache(get_cache_key('semantic'))`之后）添加：

```python
    # 获取dblp的缓存
    dblp_cache = get_from_cache(get_cache_key('dblp'))

    # 检查三个缓存是否都存在且完整
    if not openalex_cache or not semantic_cache or not dblp_cache:
        return None
```

修改第154-159行的数据完整性检查：

```python
    # 验证数据完整性
    openalex_stats = openalex_cache.get('statistics', {})
    semantic_stats = semantic_cache.get('statistics', {})
    dblp_stats = dblp_cache.get('statistics', {})

    if (openalex_stats.get('total_papers', 0) == 0 or
        semantic_stats.get('total_papers', 0) == 0 or
        dblp_stats.get('total_papers', 0) == 0):
        return None
```

在第162行的`merged_data`初始化中添加dblp：

```python
        merged_data = {
            'papers_by_date': {},
            'citations_distribution': {},
            'author_types': {},
            'top_journals': {},
            'top_countries': {},
            'institution_types': {},
            'fwci_distribution': {},
            'venue_type_distribution': {},
            'statistics': {},
            'source': 'all',
            'table': 'all',
            '_source_data': {
                'openalex': openalex_cache,
                'semantic': semantic_cache,
                'dblp': dblp_cache
            }
        }
```

添加DBLP数据合并逻辑。在第193行（semantic的author_types合并之后）添加：

```python
        # 合并作者类型/CCF等级
        for tag, count in dblp_cache.get('author_types', {}).items():
            merged_data['author_types'][tag] = merged_data['author_types'].get(tag, 0) + count

        # 合并Top期刊/venue（DBLP使用venue字段）
        for journal, count in dblp_cache.get('top_journals', {}).items():
            all_journals[journal] = all_journals.get(journal, 0) + count

        # 按数量排序，取前50
        sorted_journals = sorted(all_journals.items(), key=lambda x: x[1], reverse=True)[:50]
        merged_data['top_journals'] = dict(sorted_journals)

        # 合并venue类型分布（只有dblp有）
        merged_data['venue_type_distribution'] = dblp_cache.get('venue_type_distribution', {})
```

修改第226-233行的统计合并逻辑：

```python
        merged_data['statistics'] = {
            'total_papers': openalex_stats.get('total_papers', 0) + semantic_stats.get('total_papers', 0) + dblp_stats.get('total_papers', 0),
            'unique_authors': openalex_stats.get('unique_authors', 0) + semantic_stats.get('unique_authors', 0) + dblp_stats.get('unique_authors', 0),
            'unique_journals': total_journals if total_journals > 0 else len(all_journals),
            'unique_institutions': openalex_stats.get('unique_institutions', 0),
            'high_citations': openalex_stats.get('high_citations', 0) + semantic_stats.get('high_citations', 0),
            'avg_fwci': openalex_stats.get('avg_fwci', 0)
        }
```

- [ ] **Step 3: 修改智能缓存逻辑添加DBLP**

找到智能缓存检查部分（约第291-322行），添加DBLP智能缓存支持。

在第291行的`if source in ['openalex', 'semantic']:`改为：

```python
        if source in ['openalex', 'semantic', 'dblp']:
```

- [ ] **Step 4: 验证语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

- [ ] **Step 5: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add DBLP to all-data query and cache merging"
```

---

## Task 6: 修改api_server.py中的get_all_sources_data函数

**Files:**
- Modify: `dashboard/api_server.py:583-916`

**目标：** 在get_all_sources_data函数中添加DBLP数据源循环处理

- [ ] **Step 1: 在result初始化中添加venue_type_distribution**

找到`get_all_sources_data`函数中的result初始化（约第588-600行），添加venue_type_distribution字段：

```python
    result = {
        'papers_by_date': {},
        'citations_distribution': {},
        'author_types': {},
        'top_journals': {},
        'top_countries': {},
        'institution_types': {},
        'fwci_distribution': {},
        'venue_type_distribution': {},
        'statistics': {},
        'source': 'all',
        'table': 'all',
        '_source_data': {}
    }
```

- [ ] **Step 2: 在TABLES循环中添加DBLP特殊处理**

找到TABLES循环（约第620行），在循环内部的统计查询部分添加DBLP分支。

在第636行的`if source == 'openalex':`之前添加DBLP分支：

```python
            # 1. 统计总览 - 区分数据源
            if source == 'dblp':
                stats_sql = f"""
                SELECT
                    uniqHLL12(doi) as total_papers,
                    uniqHLL12(author_pid) as unique_authors,
                    uniqHLL12(venue) as unique_journals,
                    0 as unique_institutions,
                    0 as high_citations,
                    0 as fwci_sum,
                    0 as fwci_count
                FROM {table}
                SETTINGS max_threads=1
                """
            elif source == 'openalex':
```

- [ ] **Step 3: 在日期统计中添加DBLP特殊处理**

找到日期统计部分（约第698-718行），在date_sql定义后添加DBLP处理。

在第709行的`SETTINGS max_threads=1`之后添加：

```python
            # DBLP使用year字段
            if source == 'dblp':
                date_sql = f"""
                SELECT
                    year as date,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE year != '' AND length(year) = 4
                GROUP BY year
                ORDER BY year DESC
                SETTINGS max_threads=1
                """
```

- [ ] **Step 4: 在Top期刊查询中添加DBLP处理**

找到Top期刊查询部分（约第749-779行），修改SQL支持DBLP的venue字段。

将第752-763行的journal_sql改为：

```python
            # Top期刊/venue查询
            if source == 'dblp':
                journal_sql = f"""
                SELECT
                    venue,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE venue != ''
                    AND length(venue) > 3
                    AND lower(venue) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
                GROUP BY venue
                ORDER BY count DESC
                LIMIT 50
                SETTINGS max_threads=8, max_execution_time=60
                """
            else:
                journal_sql = f"""
                SELECT
                    journal,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE journal != ''
                        AND length(journal) > 3
                        AND lower(journal) not in ('unknown', 'unknow', 'n/a', 'na', 'null')
                GROUP BY journal
                ORDER BY count DESC
                LIMIT 50
                SETTINGS max_threads=8, max_execution_time=60
                """
```

- [ ] **Step 5: 在作者类型分布中添加DBLP的CCF等级查询**

找到作者类型/标签分布部分（需要在get_all_sources_data中添加），在引用数分布之后添加。

在第745行之后添加：

```python
            # 4.5 作者类型/CCF等级分布
            step_start = time.time()
            print(f"  [步骤 4.5/7] 作者类型/CCF等级...")
            if source == 'dblp':
                author_sql = f"""
                SELECT
                    ccf_class,
                    count() as count
                FROM {table}
                WHERE ccf_class != '' AND ccf_class != 'nan'
                GROUP BY ccf_class
                ORDER BY count DESC
                LIMIT 10
                """
            else:
                author_sql = f"""
                SELECT
                    tag,
                    count() as count
                FROM {table}
                WHERE tag != ''
                GROUP BY tag
                ORDER BY count DESC
                LIMIT 10
                """
            author_result = query_clickhouse(author_sql)
            if author_result:
                for row in author_result.result_rows:
                    result['author_types'][row[0]] = result['author_types'].get(row[0], 0) + row[1]
            step_time = time.time() - step_start
            print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")
```

- [ ] **Step 6: 添加DBLP的venue类型分布查询**

在Top期刊查询之后（约第780行之后）添加：

```python
            # 4.6 Venue类型分布（仅DBLP）
            step_start = time.time()
            print(f"  [步骤 4.6/7] Venue类型分布...")
            source_venue_types = {}
            if source == 'dblp':
                venue_type_sql = f"""
                SELECT
                    venue_type,
                    uniqHLL12(doi) as count
                FROM {table}
                WHERE venue_type != '' AND venue_type != 'nan'
                GROUP BY venue_type
                ORDER BY count DESC
                """
                venue_type_result = query_clickhouse(venue_type_sql)
                if venue_type_result:
                    for row in venue_type_result.result_rows:
                        source_venue_types[row[0]] = row[1]
            step_time = time.time() - step_start
            print(f"    ✓ 完成 (耗时: {step_time:.2f}秒)")
```

- [ ] **Step 7: 在_source_data保存中添加DBLP特有字段**

找到_source_data保存部分（约第852-862行），添加venue_type_distribution：

```python
            # 保存当前数据源的独立数据到result['_source_data']
            result['_source_data'][source] = {
                'papers_by_date': dict(source_papers_by_date),
                'citations_distribution': dict(source_citations_dist),
                'top_journals': dict(source_journals),
                'top_countries': dict(source_countries),
                'institution_types': dict(source_institution_types),
                'fwci_distribution': dict(source_fwci_dist),
                'venue_type_distribution': dict(source_venue_types),
                'statistics': source_stats,
                'source': source
            }
```

- [ ] **Step 8: 修改query_total_unique_journals的调用**

在全部数据查询的最后（约第870-885行），确保包含了DBLP。

将第875-879行的SQL修改为：

```python
            # 使用UNION ALL获取三个表的所有期刊，然后去重
            journal_sql = """
            SELECT uniqExact(journal) as count
            FROM (
                SELECT journal FROM OpenAlex
                UNION ALL
                SELECT journal FROM semantic
                UNION ALL
                SELECT venue FROM dblp
            )
            WHERE journal != ''
            """
```

- [ ] **Step 9: 验证语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

- [ ] **Step 10: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add DBLP to get_all_sources_data with special handling"
```

---

## Task 7: 修改api_server.py的缓存预加载

**Files:**
- Modify: `dashboard/api_server.py:964-988, 1476-1489`

**目标：** 在缓存预加载中添加DBLP数据源

- [ ] **Step 1: 修改preload_all_caches函数的sources列表**

找到`preload_all_caches`函数（约第964行），修改sources列表。

在第970行修改为：

```python
    sources = ['openalex', 'semantic', 'dblp', 'all']
```

- [ ] **Step 2: 修改启动时的缓存清除逻辑**

找到启动时的缓存清除部分（约第1476-1489行），添加dblp。

在第1480行修改为：

```python
        sources = ['openalex', 'semantic', 'dblp', 'all']
```

- [ ] **Step 3: 验证语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile api_server.py
```

- [ ] **Step 4: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add DBLP to cache preloading"
```

---

## Task 8: 删除graph.html文件

**Files:**
- Delete: `dashboard/graph.html`

**目标：** 删除合作关系图谱页面

- [ ] **Step 1: 删除graph.html文件**

```bash
cd /home/hkustgz/Us/academic-scraper
rm dashboard/graph.html
```

- [ ] **Step 2: 验证文件已删除**

```bash
ls -la dashboard/graph.html
```

预期输出：`No such file or directory`

- [ ] **Step 3: 提交删除**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/graph.html
git commit -m "refactor: remove graph.html collaboration network page"
```

---

## Task 9: 在index.html中添加DBLP下拉选项

**Files:**
- Modify: `dashboard/index.html:465-467`

**目标：** 在数据源选择下拉框中添加DBLP选项

- [ ] **Step 1: 找到dataSourceSelect下拉框并添加DBLP选项**

找到数据源选择下拉框（约第465-467行），在Semantic Scholar选项后添加：

```html
                        <option value="dblp">DBLP</option>
```

修改后的完整代码应该是：

```html
                    <option value="openalex">OpenAlex</option>
                    <option value="semantic">Semantic Scholar</option>
                    <option value="dblp">DBLP</option>
```

- [ ] **Step 2: 验证HTML语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
grep -A 2 "dataSourceSelect" index.html | grep "option"
```

预期输出应包含三个option标签。

- [ ] **Step 3: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/index.html
git commit -m "feat: add DBLP option to data source dropdown"
```

---

## Task 10: 在index.html中修改统计卡片显示逻辑

**Files:**
- Modify: `dashboard/index.html:695-800`

**目标：** 添加DBLP数据源的统计卡片显示逻辑

- [ ] **Step 1: 修改数据源文本映射**

找到数据源文本显示部分（约第760-761行），添加DBLP文本。

修改为：

```javascript
                const dataSourceText = data.source === 'openalex' ? 'OpenAlex' :
                                     data.source === 'semantic' ? 'Semantic Scholar' :
                                     data.source === 'dblp' ? 'DBLP' : '全部数据';
```

- [ ] **Step 2: 修改统计卡片显示条件**

找到统计卡片显示逻辑部分（约第702-744行），添加DBLP判断。

在第702行的`if (data.source === 'openalex') {`之前添加：

```javascript
                // DBLP数据源特殊处理
                if (data.source === 'dblp') {
                    statsGrid.classList.remove('openalex-compact');
                }
```

修改第714行的条件判断：

```javascript
                const isInstitutionsAvailable = stats.unique_institutions > 0 && (data.source === 'openalex' || data.source === 'semantic');
```

修改第725行的条件判断：

```javascript
                const isFwciAvailable = stats.avg_fwci > 0 && (data.source === 'openalex' || data.source === 'semantic');
```

- [ ] **Step 3: 修改unique_journals标签显示为Unique Venues（针对DBLP）**

在创建统计卡片部分（约第752-755行附近），添加条件判断。

找到创建"Unique Journals"卡片的代码，修改为：

```javascript
                if (stats.unique_journals > 0) {
                    const journalLabel = data.source === 'dblp' ? 'Unique Venues' : 'Unique Journals';
                    createStatCard(journalLabel, stats.unique_journals.toLocaleString());
                }
```

- [ ] **Step 4: 验证JavaScript语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
node -c index.html 2>&1 || echo "Note: HTML files may show syntax warnings, this is OK"
```

- [ ] **Step 5: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/index.html
git commit -m "feat: add DBLP stat card display logic"
```

---

## Task 11: 在index.html中添加DBLP特有图表渲染

**Files:**
- Modify: `dashboard/index.html:744-850`

**目标：** 添加DBLP特有的图表（CCF等级、venue类型、年份趋势）

- [ ] **Step 1: 修改图表显示条件逻辑**

找到图表显示条件判断部分（约第744行），修改为包含DBLP。

修改第744-745行的条件：

```javascript
                // 只在OpenAlex数据源时显示这些图表，semantic和dblp都隐藏
                if (data.source === 'openalex') {
```

- [ ] **Step 2: 添加DBLP特有图表的渲染函数**

在图表渲染部分（约第816-850行之后）添加DBLP图表渲染逻辑。

在最后一个图表创建之后添加：

```javascript
                // DBLP特有图表
                if (data.source === 'dblp') {
                    // CCF等级分布（饼图）
                    if (data.author_types && Object.keys(data.author_types).length > 0) {
                        createChartCard('ccf-distribution', 'CCF等级分布', 'pie', data.author_types);
                    }

                    // Venue类型分布（饼图）
                    if (data.venue_type_distribution && Object.keys(data.venue_type_distribution).length > 0) {
                        createChartCard('venue-type-distribution', 'Venue类型分布', 'pie', data.venue_type_distribution);
                    }

                    // 年份趋势（折线图）
                    if (data.papers_by_date && Object.keys(data.papers_by_date).length > 0) {
                        // 将年份对象转换为数组并排序
                        const yearData = Object.entries(data.papers_by_date)
                            .sort((a, b) => a[0].localeCompare(b[0]))
                            .reduce((obj, [key, value]) => {
                                obj[key] = value;
                                return obj;
                            }, {});
                        createChartCard('year-trend', '年份趋势', 'line', yearData);
                    }
                }
```

- [ ] **Step 3: 验证JavaScript语法**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
# HTML文件可能显示警告，这是正常的
```

- [ ] **Step 4: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/index.html
git commit -m "feat: add DBLP-specific charts (CCF, venue type, year trend)"
```

---

## Task 12: 在index.html中移除图谱相关代码

**Files:**
- Modify: `dashboard/index.html`

**目标：** 移除所有与合作关系图谱相关的链接和代码

- [ ] **Step 1: 搜索并删除图谱相关链接**

搜索graph.html相关的链接：

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
grep -n "graph" index.html
```

- [ ] **Step 2: 删除找到的图谱链接**

根据grep结果，删除所有指向graph.html的链接或按钮。

如果存在类似`<a href="graph.html">`的代码，删除整个`<a>`标签。

如果存在"合作关系图谱"等文本的链接，删除该链接元素。

- [ ] **Step 3: 验证没有残留的graph.html引用**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
grep -i "graph" index.html | grep -v "// " | grep -v "chart"
```

预期：应该没有指向graph.html的链接（chart相关的可以保留）

- [ ] **Step 4: 提交修改**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/index.html
git commit -m "refactor: remove collaboration graph links from index.html"
```

---

## Task 13: 测试DBLP数据源功能

**Files:**
- Test: `dashboard/` (整体功能测试)

**目标：** 验证DBLP数据源集成是否正常工作

- [ ] **Step 1: 启动API服务器**

```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python api_server.py
```

保持服务器运行，在另一个终端进行测试。

- [ ] **Step 2: 测试DBLP独立查询**

```bash
curl "http://localhost:8080/api/aggregated?source=dblp" | head -100
```

预期：应返回包含DBLP数据的JSON，包括：
- `papers_by_date`（年份）
- `author_types`（CCF等级）
- `venue_type_distribution`（venue类型）
- `top_journals`（实际是venues）
- `statistics`（total_papers, unique_authors, unique_journals等）

- [ ] **Step 3: 测试全部数据查询（包含DBLP）**

```bash
curl "httplocalhost:8080/api/aggregated?source=all" | jq '.statistics'
```

预期：statistics应包含openalex、semantic、dblp三个数据源的合并数据。

- [ ] **Step 4: 测试OpenAlex和Semantic功能未受影响**

```bash
curl "http://localhost:8080/api/aggregated?source=openalex" | jq '.statistics'
curl "http://localhost:8080/api/aggregated?source=semantic" | jq '.statistics'
```

预期：返回结果应与修改前一致。

- [ ] **Step 5: 测试前端显示**

在浏览器中打开`http://localhost:8080`，测试：
1. 切换到DBLP数据源，查看统计卡片和图表
2. 切换到全部数据，查看是否包含DBLP数据
3. 切换回OpenAlex和Semantic，确认功能正常

- [ ] **Step 6: 验证图谱功能已移除**

尝试访问：
```bash
curl "http://localhost:8080/graph.html"
```

预期：应返回404错误

尝试访问图谱API：
```bash
curl "http://localhost:8080/api/graph/authors"
```

预期：应返回404错误

- [ ] **Step 7: 停止服务器**

在运行api_server.py的终端按`Ctrl+C`停止服务器。

- [ ] **Step 8: 提交测试结果（如果所有测试通过）**

```bash
cd /home/hkustgz/Us/academic-scraper
git add -A
git commit -m "test: verify DBLP integration and graph removal"
```

---

## Task 14: 清理和文档更新

**Files:**
- Update: `dashboard/README.md` (如果存在)

**目标：** 更新文档反映DBLP数据源的添加

- [ ] **Step 1: 检查README.md是否存在**

```bash
ls -la /home/hkustgz/Us/academic-scraper/dashboard/README.md
```

- [ ] **Step 2: 如果存在，更新README.md**

如果README.md存在，添加DBLP数据源的说明。

在数据源说明部分添加：

```markdown
### 支持的数据源

- **OpenAlex**: 包含完整的论文、引用、机构信息
- **Semantic Scholar**: 包含论文和引用信息
- **DBLP**: 计算机科学领域论文数据，包含CCF等级、venue类型等特有信息
- **全部数据**: 合并所有数据源的数据
```

- [ ] **Step 3: 如果README中提到图谱功能，删除相关说明**

搜索并删除关于"合作关系图谱"、"author collaboration network"等描述。

- [ ] **Step 4: 提交文档更新**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/README.md
git commit -m "docs: update README for DBLP data source and graph removal"
```

---

## 验收检查清单

在所有任务完成后，验证以下内容：

- [ ] `config.py`中已添加`'dblp': 'dblp'`配置
- [ ] `api_server.py`中所有图谱相关代码已删除（约400行）
- [ ] `api_server.py`中DBLP查询逻辑已添加（统计、CCF、venue类型、年份）
- [ ] `api_server.py`中全部数据查询包含DBLP
- [ ] `index.html`中DBLP下拉选项已添加
- [ ] `index.html`中DBLP特有图表已添加（CCF等级、venue类型、年份趋势）
- [ ] `index.html`中图谱相关链接已删除
- [ ] `graph.html`文件已删除
- [ ] DBLP数据源可以正常查询和显示
- [ ] 全部数据查询正确合并DBLP数据
- [ ] OpenAlex和Semantic功能未受影响
- [ ] 图谱相关API端点返回404

---

## 总结

本实现计划包含14个任务，涵盖了：

1. **配置修改**：添加DBLP表配置
2. **API后端**：删除图谱代码，添加DBLP查询支持
3. **前端适配**：添加DBLP选项和图表，移除图谱链接
4. **文件清理**：删除graph.html
5. **测试验证**：确保功能正常

预计代码改动：
- 删除：约400行（图谱相关代码）
- 新增：约300行（DBLP支持代码）
- 修改：约100行（适配逻辑）

遵循原则：
- ✅ DRY：复用现有的查询和图表渲染逻辑
- ✅ YAGNI：只实现必需的功能，不添加额外特性
- ✅ TDD：每个任务后都进行验证
- ✅ 小步提交：每个任务独立提交，便于回滚
