# 作者合作关系图谱优化设计

**项目：** Academic Scraper Dashboard 关系图谱性能优化与界面重构
**日期：** 2026-04-20
**状态：** 设计阶段 - 待用户review

---

## 📋 项目概述

### 当前问题
1. **性能问题**：关系图谱查询速度慢（15-40秒），影响用户体验
2. **界面风格**：现有深色主题不符合用户需求（要求黑白简洁风格）
3. **数据过滤**：缺少LLM等特定领域的快速筛选功能

### 优化目标
1. **性能提升**：查询时间从30秒降至2秒以内（15-100倍提升）
2. **界面重构**：改为黑白简洁风格（白底+灰色节点+黑色文字）
3. **Demo优先**：优先实现可用demo，使用最近1年LLM方向数据
4. **全数据支持**：长期支持全数据量查询（通过预计算表）

### 技术方案
采用**方案B修订版**：创建新表预计算合作关系 + 快速Demo
- **阶段1（1天）**：黑白风格界面 + LLM关键词过滤
- **阶段2（1-2天）**：创建预计算表 + API性能优化
- **阶段3（未来）**：定时更新 + 全数据量支持

---

## 🎨 阶段1：黑白风格Demo设计

### 1.1 配色方案

```css
:root {
  /* 背景色 */
  --bg-primary: #ffffff;           /* 纯白背景 */
  --bg-secondary: #f8f8f8;         /* 淡灰次要背景 */

  /* 文字色 */
  --text-primary: #1a1a1a;         /* 近黑文字 */
  --text-secondary: #666666;       /* 灰色次要文字 */

  /* 边框和阴影 */
  --border-color: #e8e8e8;         /* 淡灰边框 */
  --panel-border: #e0e0e0;         /* 面板边框 */
  --shadow: rgba(0, 0, 0, 0.08);   /* 淡阴影 */

  /* 节点配色 */
  --node-normal: #d0d0d0;          /* 淡灰节点 */
  --node-highlight: #888888;       /* 中灰高亮 */
  --node-important: #4a4a4a;       /* 深灰重要节点（degree>=5） */
  --node-stroke: #2a2a2a;          /* 近黑边框 */

  /* 链接配色 */
  --link-normal: #d8d8d8;          /* 淡灰链接 */
  --link-highlight: #666666;       /* 深灰高亮 */
}
```

### 1.2 UI组件调整

**保留的特性（从graph目录借鉴）：**
- ✅ D3.js力导向图核心逻辑
- ✅ 节点三层结构（光晕→主圆→标签）
- ✅ 弧形链接（非直线）
- ✅ 悬停高亮交互
- ✅ 拖拽+缩放功能
- ✅ 物理模拟参数
- ✅ 入场动画

**去掉的效果：**
- ❌ 粒子背景canvas（保持简洁）
- ❌ 毛玻璃效果（`backdrop-filter`）
- ❌ 极光渐变背景（改为纯白）
- ❌ 彩色光晕（改为淡灰色晕）

**新增组件：**

1. **LLM关键词输入框**
```html
<div class="filter-group">
  <label>LLM关键词:</label>
  <input type="text" id="llm-keywords"
         placeholder="LLM|Large Language Model|ChatGPT|GPT"
         value="LLM|Large Language Model|ChatGPT|GPT">
  <small class="help-text">用 | 分隔多个关键词，匹配期刊名或论文标题</small>
</div>
```

2. **加载进度面板**
```html
<div id="loading-progress" class="loading-panel">
  <div class="progress-content">
    <div class="progress-icon">📊</div>
    <div class="progress-text" id="progress-text">正在加载作者数据...</div>
    <div class="progress-bar">
      <div class="progress-fill" id="progress-fill" style="width: 0%"></div>
    </div>
    <div class="progress-detail" id="progress-detail"></div>
  </div>
</div>
```

3. **数据统计信息**
```html
<div class="data-info">
  <span class="info-item">
    <strong>数据范围:</strong> <span id="data-range">最近1年</span>
  </span>
  <span class="info-item">
    <strong>相关论文:</strong> <span id="paper-count">--</span> 篇
  </span>
  <span class="info-item">
    <strong>作者数量:</strong> <span id="author-count">--</span> 人
  </span>
</div>
```

### 1.3 前端优化

**并行加载策略：**
```javascript
// 原方案：串行加载（慢）
const authorsData = await fetchAuthors();
const edgesData = await fetchEdges(); // 等authors完成才开始

// 新方案：并行加载（快）
const [authorsData, edgesData] = await Promise.all([
  fetchAuthors(),
  fetchEdges()
]);
```

**进度提示更新：**
```javascript
async function loadGraphWithProgress() {
  updateProgress('正在加载作者数据...', 10);

  const [authorsPromise, edgesPromise] = [
    fetch('/api/graph/authors?...').then(r => r.json()),
    fetch('/api/graph/edges?...').then(r => r.json())
  ];

  updateProgress('作者数据加载完成，正在加载合作关系...', 50);
  const [authorsData, edgesData] = await Promise.all([
    authorsPromise,
    edgesPromise
  ]);

  updateProgress('数据加载完成，正在渲染图谱...', 90);
  renderGraph(authorsData, edgesData);

  updateProgress('完成！', 100);
  setTimeout(hideProgress, 500);
}
```

### 1.4 临时API修改（阶段1使用）

**修改 `get_merged_papers_sql()` 函数，添加关键词过滤：**
```python
def get_merged_papers_sql(time_range="all", journal_keyword=None):
    """生成合并OpenAlex和Semantic数据的SQL - 支持关键词过滤"""

    # 原有的时间过滤
    time_filter = ""
    if time_range != "all":
        years = int(time_range)
        time_filter = f"AND toYear(toDateOrNull(publication_date)) >= year(toDate(today())) - {years}"

    # 新增：关键词过滤（匹配期刊名或论文标题）
    keyword_filter = ""
    if journal_keyword and journal_keyword.strip():
        keywords = journal_keyword.split('|')
        keyword_conditions = []

        for kw in keywords:
            kw = kw.strip()
            if kw:
                # 匹配期刊名或论文标题（不区分大小写）
                keyword_conditions.append(f"lower(journal) LIKE lower('%{kw}%')")
                keyword_conditions.append(f"lower(title) LIKE lower('%{kw}%')")

        if keyword_conditions:
            keyword_filter = "AND (" + " OR ".join(keyword_conditions) + ")"

    # 共同字段
    common_fields = [
        'doi', 'rank', 'author_id', 'author', 'uid', 'title', 'journal',
        'citation_count', 'tag', 'state', 'institution_id', 'institution_name',
        'institution_country', 'institution_type', 'publication_date'
    ]
    fields_str = ', '.join(common_fields)

    # 基础日期过滤
    base_date_filter = "AND length(publication_date) >= 4"

    # 限制查询数据量（阶段1临时措施）
    limit_clause = "LIMIT 100000"  # 限制10万篇论文

    return f"""
    WITH combined AS (
        SELECT
            doi,
            rank,
            argMax(author_id, source_order) as author_id,
            argMax(author, source_order) as author,
            argMax(uid, source_order) as uid,
            argMax(title, source_order) as title,
            argMax(journal, source_order) as journal,
            argMax(citation_count, source_order) as citation_count,
            argMax(tag, source_order) as tag,
            argMax(state, source_order) as state,
            argMax(institution_id, source_order) as institution_id,
            argMax(institution_name, source_order) as institution_name,
            argMax(institution_country, source_order) as institution_country,
            argMax(institution_type, source_order) as institution_type,
            argMax(publication_date, source_order) as publication_date
        FROM (
            SELECT {fields_str}, 1 as source_order
            FROM OpenAlex
            PREWHERE doi != ''
            {base_date_filter} {time_filter} {keyword_filter}

            UNION ALL

            SELECT {fields_str}, 2 as source_order
            FROM semantic
            PREWHERE doi != ''
            {base_date_filter} {time_filter} {keyword_filter}
        )
        GROUP BY doi, rank
        {limit_clause}
    )
    SELECT * FROM combined
    """
```

### 1.5 阶段1交付物

**文件清单：**
1. `/dashboard/css/graph.css` - 更新为黑白配色
2. `/dashboard/graph.html` - 添加关键词输入框和进度面板
3. `/dashboard/js/graph.js` - 更新为并行加载
4. `/dashboard/api_server.py` - 临时修改SQL添加关键词过滤

**验收标准：**
- ✅ 界面为黑白风格（白底+灰色节点）
- ✅ 支持LLM关键词过滤（默认值：LLM|Large Language Model|ChatGPT|GPT）
- ✅ 显示加载进度（作者数据→合作关系→渲染）
- ✅ 数据范围：最近1年+LLM关键词
- ✅ 查询时间：可能较慢（10-30秒），但能正常工作

---

## 🚀 阶段2：预计算表+性能优化

### 2.1 新表结构设计

```sql
-- 作者合作关系预计算表
CREATE TABLE IF NOT EXISTS author_collaborations (
    -- 作者基本信息
    author_id String,
    author_name String,
    collaborator_id String,
    collaborator_name String,

    -- 合作关系统计
    collaboration_count UInt32,           -- 合作论文数
    first_collaboration_date Date,        -- 首次合作时间
    latest_collaboration_date Date,       -- 最近合作时间

    -- 论文详情（最多存储100篇共同论文的DOI）
    common_papers Array(String),

    -- 筛选维度
    time_range String,                    -- '1year', '2years', '3years', 'all'
    keyword_filter String DEFAULT '',     -- 'LLM', 'AI', ''表示全部

    -- 统计信息（用于节点大小计算）
    author_degree UInt32,                 -- 该作者的合作者总数
    collaborator_degree UInt32,           -- 合作者的合作者总数

    -- 元数据
    last_updated DateTime DEFAULT now()
)
ENGINE = MergeTree()
PARTITION BY toYYYYMM(latest_collaboration_date)
ORDER BY (time_range, keyword_filter, collaboration_count DESC, author_id, collaborator_id)
SETTINGS index_granularity = 8192;

-- 创建布隆过滤器索引（加速精确查找）
CREATE INDEX idx_author_collab_authors ON author_collaborations (author_id, collaborator_id)
TYPE bloom_filter GRANULARITY 1;

-- 创建minmax索引（加速范围查询）
CREATE INDEX idx_collab_count ON author_collaborations (collaboration_count)
TYPE minmax GRANULARITY 1;
```

### 2.2 数据迁移脚本

**文件：`/scripts/migrate_collaborations.py`**

```python
#!/usr/bin/env python3
"""
合作关系数据迁移脚本
从现有论文表计算合作关系，存入预计算表
执行时间：约10-30分钟（取决于数据量）
"""

import sys
sys.path.append('/home/hkustgz/Us/academic-scraper')

import clickhouse_connect
from config import CLICKHOUSE_CONFIG
from tqdm import tqdm
import time

def get_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)

def get_time_filter(time_range):
    """生成时间过滤SQL"""
    if time_range == "all":
        return ""
    years = int(time_range)
    return f"AND toYear(toDateOrNull(publication_date)) >= year(toDate(today())) - {years} AND toDateOrNull(publication_date) IS NOT NULL"

def get_keyword_filter(keywords):
    """生成关键词过滤SQL"""
    if not keywords or not keywords.strip():
        return ""

    keyword_list = [k.strip() for k in keywords.split('|') if k.strip()]
    if not keyword_list:
        return ""

    conditions = []
    for kw in keyword_list:
        conditions.append(f"lower(journal) LIKE lower('%{kw}%')")
        conditions.append(f"lower(title) LIKE lower('%{kw}%')")

    return "AND (" + " OR ".join(conditions) + ")"

def calculate_collaborations_sql(time_range='1year', keyword_filter=''):
    """生成计算合作关系的SQL"""
    time_filter = get_time_filter(time_range)
    keyword_filter_sql = get_keyword_filter(keyword_filter)

    # 限制关键词长度（避免超出ClickHouse限制）
    keyword_short = keyword_filter[:50] if keyword_filter else ''

    return f"""
    INSERT INTO author_collaborations
    WITH
    -- 1. 获取符合时间范围和关键词的论文
    filtered_papers AS (
        SELECT
            doi,
            author_id,
            author,
            publication_date
        FROM (
            SELECT doi, author_id, author, publication_date, 1 as src
            FROM OpenAlex
            WHERE publication_date != ''
              AND length(publication_date) >= 4
              {time_filter}
              {keyword_filter_sql}

            UNION ALL

            SELECT doi, author_id, author, publication_date, 2 as src
            FROM semantic
            WHERE publication_date != ''
              AND length(publication_date) >= 4
              {time_filter}
              {keyword_filter_sql}
        )
        GROUP BY doi, author_id, author, publication_date
    ),

    -- 2. 找出合作关系（同一篇论文的不同作者）
    collaborations AS (
        SELECT
            p1.author_id as author_id,
            p1.author as author_name,
            p2.author_id as collaborator_id,
            p2.author as collaborator_name,
            count(DISTINCT p1.doi) as collaboration_count,
            min(p1.publication_date) as first_collaboration_date,
            max(p1.publication_date) as latest_collaboration_date,
            groupArray(DISTINCT p1.doi) as common_papers
        FROM filtered_papers p1
        INNER JOIN filtered_papers p2
            ON p1.doi = p2.doi
            AND p1.author_id < p2.author_id
        GROUP BY
            p1.author_id, p1.author,
            p2.author_id, p2.author
        HAVING collaboration_count >= 1
    ),

    -- 3. 计算每个作者的总合作者数
    author_degrees AS (
        SELECT
            author_id,
            count(DISTINCT collaborator_id) as degree
        FROM collaborations
        GROUP BY author_id
    )

    SELECT
        c.*,
        ad1.degree as author_degree,
        ad2.degree as collaborator_degree,
        '{time_range}' as time_range,
        '{keyword_short}' as keyword_filter,
        now() as last_updated
    FROM collaborations c
    LEFT JOIN author_degrees ad1 ON c.author_id = ad1.author_id
    LEFT JOIN author_degrees ad2 ON c.collaborator_id = ad2.author_id
    """

def migrate_all_combinations():
    """迁移所有时间范围和关键词组合"""
    client = get_client()

    # 定义需要迁移的组合
    combinations = [
        ('1year', 'LLM|Large Language Model|ChatGPT|GPT'),
        ('2years', 'LLM|Large Language Model|ChatGPT|GPT'),
        ('3years', 'LLM|Large Language Model|ChatGPT|GPT'),
        ('all', 'LLM|Large Language Model|ChatGPT|GPT'),
        ('1year', ''),
        ('2years', ''),
        ('3years', ''),
        ('all', ''),
    ]

    print("=" * 60)
    print("开始迁移合作关系数据")
    print("=" * 60)

    for time_range, keywords in tqdm(combinations, desc="总体进度"):
        keyword_display = keywords[:30] + "..." if len(keywords) > 30 else keywords
        print(f"\n{'='*60}")
        print(f"处理: time_range={time_range}, keywords={keyword_display}")
        print(f"{'='*60}")

        sql = calculate_collaborations_sql(time_range, keywords)
        start = time.time()

        try:
            client.command(sql)
            elapsed = time.time() - start
            print(f"✅ 完成，耗时: {elapsed:.1f}秒")
        except Exception as e:
            print(f"❌ 失败: {e}")
            import traceback
            traceback.print_exc()

    print(f"\n{'='*60}")
    print("所有数据迁移完成！")
    print(f"{'='*60}")

    # 显示统计信息
    stats_sql = """
    SELECT
        time_range,
        keyword_filter,
        count(DISTINCT author_id) as unique_authors,
        sum(collaboration_count) as total_collaborations
    FROM author_collaborations
    GROUP BY time_range, keyword_filter
    ORDER BY time_range, keyword_filter
    """

    result = client.query(stats_sql)
    print("\n数据统计:")
    print(f"{'时间范围':<10} {'关键词':<20} {'作者数':<10} {'合作数':<10}")
    print("-" * 60)
    for row in result.result_rows:
        tr = row[0]
        kf = row[1][:20] if row[1] else "(全部)"
        ua = row[2]
        tc = row[3]
        print(f"{tr:<10} {kf:<20} {ua:<10} {tc:<10}")

if __name__ == '__main__':
    migrate_all_combinations()
```

### 2.3 API优化（查询预计算表）

**修改 `/dashboard/api_server.py` 中的图谱API端点：**

```python
# ===== 新增：从预计算表查询（极速版） =====

@app.route('/api/graph/authors_v2', methods=['GET'])
def get_graph_authors_v2():
    """从预计算表获取作者节点（极速版，查询时间<2秒）"""
    start_time = time.time()
    print("📊 [V2] 查询作者节点（预计算表）...")

    try:
        # 获取参数
        min_collab = int(request.args.get('min_collaborations', 1))
        max_nodes = min(int(request.args.get('max_nodes', 200)), 500)
        time_range = request.args.get('time_range', '1')
        keywords = request.args.get('keywords', 'LLM|Large Language Model|ChatGPT|GPT')

        # 参数验证
        if time_range not in ['1', '2', '3', 'all']:
            return jsonify({'error': 'Invalid time_range'}), 400

        # 将time_range转换为表中的格式
        time_range_map = {'1': '1year', '2': '2years', '3': '3years', 'all': 'all'}
        tr = time_range_map[time_range]

        # 限制关键词长度
        keyword_short = keywords[:50] if keywords else ''

        # 检查缓存
        cache_key = get_graph_cache_key('authors_v2', min_collab=min_collab,
                                        max_nodes=max_nodes, time_range=tr,
                                        keywords=keyword_short)
        cached = get_from_cache(cache_key)
        if cached:
            print(f"🎯 命中缓存！")
            return jsonify(cached)

        # 从预计算表查询（速度提升100倍）
        sql = f"""
        SELECT DISTINCT
            author_id as id,
            author_name as label,
            max(author_degree) as degree,
            arraySlice(groupArray(common_papers), 1, 10) as sample_papers,
            min(first_collaboration_date) as first_date,
            max(latest_collaboration_date) as latest_date,
            sum(collaboration_count) as total_collaborations
        FROM author_collaborations
        WHERE time_range = '{tr}'
          AND keyword_filter = '{keyword_short}'
          AND author_degree >= {min_collab}
        GROUP BY author_id, author_name
        ORDER BY degree DESC
        LIMIT {max_nodes}
        """

        result = query_clickhouse(sql)
        if not result or not result.result_rows:
            return jsonify({
                'error': True,
                'message': '未找到符合条件的数据',
                'code': 'NO_DATA'
            }), 404

        nodes = []
        for row in result.result_rows:
            # 计算论文数（从sample_papers中统计非空数量）
            papers = [p for p in row[3] if p]
            paper_count = len(papers)

            nodes.append({
                'id': row[0],
                'label': row[1],
                'degree': row[2],
                'paper_count': paper_count,
                'citation_count': row[6],  # 用合作数作为代理指标
                'institution': '未知',  # 预计算表中没有，后续可补充
                'country': '未知'
            })

        elapsed = time.time() - start_time
        print(f"✅ 查询完成！耗时: {elapsed:.2f}秒，节点数: {len(nodes)}")

        response = {
            'nodes': nodes,
            'total_authors': len(nodes),
            'filtered_authors': len(nodes),
            'query_time': elapsed
        }

        # 缓存结果（10分钟）
        set_to_cache(cache_key, response, ttl=600)

        return jsonify(response)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': True,
            'message': f'查询失败: {str(e)}',
            'code': 'QUERY_ERROR'
        }), 500


@app.route('/api/graph/edges_v2', methods=['GET'])
def get_graph_edges_v2():
    """从预计算表获取合作关系（极速版，查询时间<1秒）"""
    start_time = time.time()
    print("📊 [V2] 查询合作关系（预计算表）...")

    try:
        # 获取参数
        author_ids = request.args.getlist('author_ids')
        min_weight = int(request.args.get('min_weight', 1))
        time_range = request.args.get('time_range', '1')
        keywords = request.args.get('keywords', 'LLM|Large Language Model|ChatGPT|GPT')

        # 参数验证
        if not author_ids:
            return jsonify({'error': 'Missing author_ids'}), 400

        # 防止SQL注入
        for aid in author_ids:
            if "'" in aid or ";" in aid or "\\" in aid:
                return jsonify({'error': 'Invalid author_id'}), 400

        # 时间范围映射
        time_range_map = {'1': '1year', '2': '2years', '3': '3years', 'all': 'all'}
        tr = time_range_map[time_range]
        keyword_short = keywords[:50] if keywords else ''

        # 检查缓存
        cache_key = get_graph_cache_key('edges_v2', ids=",".join(sorted(author_ids)),
                                        min_weight=min_weight, time_range=tr,
                                        keywords=keyword_short)
        cached = get_from_cache(cache_key)
        if cached:
            print(f"🎯 命中缓存！")
            return jsonify(cached)

        # 从预计算表查询（不需要JOIN，速度快）
        ids_str = "','".join(author_ids[:500])  # 限制最多500个作者
        sql = f"""
        SELECT
            author_id as source,
            collaborator_id as target,
            collaboration_count as weight,
            length(common_papers) as paper_count
        FROM author_collaborations
        WHERE time_range = '{tr}'
          AND keyword_filter = '{keyword_short}'
          AND ((author_id IN ('{ids_str}') AND collaborator_id IN ('{ids_str}'))
               OR (author_id IN ('{ids_str}') AND collaborator_id IN ('{ids_str}')))
          AND collaboration_count >= {min_weight}
        """

        result = query_clickhouse(sql)
        edges = []
        if result:
            for row in result.result_rows:
                edges.append({
                    'source': row[0],
                    'target': row[1],
                    'weight': row[2]
                })

        elapsed = time.time() - start_time
        print(f"✅ 查询完成！耗时: {elapsed:.2f}秒，关系数: {len(edges)}")

        response = {
            'edges': edges,
            'total_collaborations': len(edges),
            'query_time': elapsed
        }

        # 缓存结果（10分钟）
        set_to_cache(cache_key, response, ttl=600)

        return jsonify(response)

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': True,
            'message': f'查询失败: {str(e)}',
            'code': 'QUERY_ERROR'
        }), 500
```

### 2.4 定时更新任务

**文件：`/scripts/update_collaborations.py`**

```python
#!/usr/bin/env python3
"""
定时任务：更新合作关系预计算表
建议使用crontab每小时执行一次
"""

import sys
sys.path.append('/home/hkustgz/Us/academic-scraper')

import clickhouse_connect
from config import CLICKHOUSE_CONFIG
import time
from datetime import datetime

def get_client():
    """获取ClickHouse客户端"""
    return clickhouse_connect.get_client(**CLICKHOUSE_CONFIG)

def update_collaborations():
    """增量更新最近1年的LLM合作关系数据"""
    client = get_client()

    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 开始更新合作关系数据...")

    try:
        # 1. 删除旧的最近1年LLM数据
        print("  → 删除旧数据...")
        client.command("""
            ALTER TABLE author_collaborations
            DELETE WHERE time_range = '1year' AND keyword_filter LIKE '%LLM%'
        """)
        print("  ✓ 旧数据已删除")

        # 2. 重新计算最近1年LLM数据
        print("  → 重新计算数据...")
        from migrate_collaborations import calculate_collaborations_sql

        sql = calculate_collaborations_sql('1year', 'LLM|Large Language Model|ChatGPT|GPT')
        client.command(sql)
        print("  ✓ 新数据已计算")

        # 3. 优化表（合并分区）
        print("  → 优化表结构...")
        client.command("OPTIMIZE TABLE author_collaborations FINAL")
        print("  ✓ 表已优化")

        # 4. 显示统计信息
        stats = client.query("""
            SELECT
                count(DISTINCT author_id) as authors,
                count() as total_collabs
            FROM author_collaborations
            WHERE time_range = '1year' AND keyword_filter LIKE '%LLM%'
        """)

        if stats.result_rows:
            row = stats.result_rows[0]
            print(f"\n  📊 统计信息:")
            print(f"     - 作者数: {row[0]:,}")
            print(f"     - 合作关系数: {row[1]:,}")

        print(f"\n✅ 更新完成！耗时: {elapsed:.1f}秒")

    except Exception as e:
        print(f"\n❌ 更新失败: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True

if __name__ == '__main__':
    start = time.time()
    success = update_collaborations()
    elapsed = time.time() - start

    if success:
        print(f"\n总耗时: {elapsed:.1f}秒")
    else:
        print(f"\n更新失败，耗时: {elapsed:.1f}秒")
        sys.exit(1)
```

**Crontab配置：**
```bash
# 编辑crontab
crontab -e

# 添加以下行（每小时更新一次）
0 * * * * /home/hkustgz/Us/academic-scraper/venv/bin/python /home/hkustgz/Us/academic-scraper/scripts/update_collaborations.py >> /var/log/collab_update.log 2>&1
```

### 2.5 性能对比

| 指标 | 原方案（实时JOIN） | 新方案（预计算表） | 提升倍数 |
|------|------------------|------------------|---------|
| 查询作者节点 | 15-30秒 | 0.5-2秒 | **15-60倍** |
| 查询合作关系 | 20-40秒 | 0.3-1秒 | **20-130倍** |
| 内存占用 | 高（大表JOIN） | 低（索引查询） | **10倍** |
| 并发支持 | 差（锁竞争） | 好（无锁） | **显著提升** |
| CPU使用 | 高（复杂计算） | 低（简单查询） | **5倍** |

### 2.6 阶段2实施步骤

**Day 1上午（3-4小时）：**
1. 创建 `author_collaborations` 表（15分钟）
2. 编写数据迁移脚本（1小时）
3. 小规模测试迁移（1000条数据，30分钟）
4. 运行完整数据迁移（1-2小时）

**Day 1下午（3-4小时）：**
5. 修改API端点添加 `_v2` 版本（1.5小时）
6. 测试新API性能（1小时）
7. 前端切换到新API（30分钟）
8. 性能对比测试（30分钟）

**Day 2（2-3小时）：**
9. 编写定时更新脚本（1小时）
10. 配置crontab定时任务（30分钟）
11. 添加监控和日志（30分钟）
12. 完整功能测试（1小时）

### 2.7 阶段2交付物

**文件清单：**
1. `/scripts/migrate_collaborations.py` - 数据迁移脚本
2. `/scripts/update_collaborations.py` - 定时更新脚本
3. `/dashboard/api_server.py` - 添加 `_v2` 版本的API端点
4. `/dashboard/js/graph.js` - 修改为调用 `_v2` API
5. `/var/log/collab_update.log` - 更新日志文件

**验收标准：**
- ✅ `author_collaborations` 表已创建并填充数据
- ✅ 查询时间<2秒（作者节点）和<1秒（合作关系）
- ✅ 前端正常显示黑白风格关系图谱
- ✅ 定时任务正常运行（每小时更新）
- ✅ Redis缓存正常工作

---

## 📊 数据流和架构

### 原架构（阶段1之前）
```
用户请求 → API → 实时JOIN OpenAlex+semantic表 → 返回数据
           ↓
       15-40秒查询时间
```

### 新架构（阶段2之后）
```
用户请求 → API → 查询预计算表 → 返回数据
           ↓              ↓
       <2秒查询      Redis缓存（可选）
                          ↓
                   定时任务更新预计算表
```

### 数据更新流程
```
新论文数据 → OpenAlex/semantic表
                    ↓
            定时任务（每小时）
                    ↓
        重新计算合作关系
                    ↓
        更新author_collaborations表
                    ↓
                清除Redis缓存
```

---

## 🎯 成功指标

### 阶段1（Demo）
- [ ] 界面改为黑白风格（白底+灰色节点）
- [ ] 支持LLM关键词过滤
- [ ] 显示加载进度
- [ ] 能正常显示最近1年LLM合作关系图谱

### 阶段2（性能优化）
- [ ] 查询时间<2秒（原15-30秒）
- [ ] 支持200-500个节点流畅渲染
- [ ] 预计算表包含至少1000个作者的合作关系
- [ ] 定时任务正常运行
- [ ] 内存占用降低50%以上

### 阶段3（未来扩展）
- [ ] 支持全数据量查询（不限时间范围）
- [ ] 支持更多领域关键词（AI、ML等）
- [ ] 提供数据导出功能
- [ ] 添加更多统计信息（合作趋势分析）

---

## 🚨 风险和注意事项

### 技术风险

1. **数据迁移失败**
   - **风险**：SQL复杂，可能内存溢出
   - **缓解**：分批迁移，限制单次查询数据量

2. **定时任务冲突**
   - **风险**：定时任务可能占用大量资源
   - **缓解**：设置资源限制，选择低峰时段执行

3. **API兼容性**
   - **风险**：新API可能破坏现有功能
   - **缓解**：保留旧API，新增 `_v2` 版本

### 数据质量

1. **合作关系计算错误**
   - **验证**：对比预计算表和实时查询结果
   - **监控**：添加数据质量检查脚本

2. **数据过期**
   - **问题**：预计算表数据可能不是最新的
   - **解决**：显示"数据更新时间"，让用户知情

### 性能监控

1. **查询性能退化**
   - **监控**：记录每次查询时间
   - **告警**：超过5秒发送告警

2. **缓存命中率**
   - **监控**：统计Redis缓存命中率
   - **优化**：根据命中率调整缓存策略

---

## 📝 实施检查清单

### 阶段1检查清单
- [ ] 备份现有CSS文件
- [ ] 修改CSS配色为黑白风格
- [ ] 添加LLM关键词输入框
- [ ] 添加加载进度面板
- [ ] 修改SQL添加关键词过滤
- [ ] 前端实现并行加载
- [ ] 测试demo功能
- [ ] 验证黑白风格效果

### 阶段2检查清单
- [ ] 创建 `author_collaborations` 表
- [ ] 编写数据迁移脚本
- [ ] 小规模测试迁移
- [ ] 运行完整数据迁移
- [ ] 验证数据正确性
- [ ] 添加 `_v2` 版本API端点
- [ ] 前端切换到新API
- [ ] 性能测试和对比
- [ ] 编写定时更新脚本
- [ ] 配置crontab
- [ ] 添加监控日志
- [ ] 完整功能测试

### 部署检查清单
- [ ] 备份生产数据库
- [ ] 在测试环境验证
- [ ] 准备回滚方案
- [ ] 通知用户维护窗口
- [ ] 执行数据迁移
- [ ] 验证功能正常
- [ ] 监控系统性能
- [ ] 更新文档

---

## 📚 参考资源

### 技术文档
- [ClickHouse MergeTree引擎](https://clickhouse.com/docs/en/engines/table-engines/mergetree-family/mergetree/)
- [D3.js Force Simulation](https://github.com/d3/d3-force)
- [Redis缓存最佳实践](https://redis.io/docs/manual/patterns/)

### 项目文件
- `/home/hkustgz/Us/academic-scraper/graph/关系图谱风格分析.md` - D3.js图谱设计参考
- `/home/hkustgz/Us/academic-scraper/dashboard/api_server.py` - 现有API实现
- `/home/hkustgz/Us/academic-scraper/dashboard/js/graph.js` - D3.js图谱渲染

---

## ✅ 下一步行动

1. **用户review本设计文档**
2. **创建实施计划**（调用writing-plans技能）
3. **开始阶段1实施**（黑白风格demo）
4. **完成阶段2实施**（性能优化）
5. **部署和监控**

---

**文档版本：** v1.0
**最后更新：** 2026-04-20
**状态：** 待用户review
