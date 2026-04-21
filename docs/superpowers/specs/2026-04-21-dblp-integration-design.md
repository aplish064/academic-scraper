# DBLP数据源集成设计文档

**日期**: 2026-04-21
**状态**: 已批准
**作者**: Claude
**类型**: 功能增强

## 概述

将DBLP数据源集成到学术数据看板dashboard中，支持DBLP作为独立数据源查询，并支持在"全部数据"中合并DBLP数据。同时完全移除作者合作关系图谱功能。

## 需求背景

- DBLP表已存在于ClickHouse数据库中，包含计算机科学领域的论文数据
- DBLP具有不同于OpenAlex和Semantic Scholar的字段结构和特色数据（CCF等级、venue类型等）
- 需要在dashboard中支持DBLP数据查询和展示
- 不再需要作者合作关系图谱功能，需要彻底移除

## 设计方案

### 1. 整体架构

#### 1.1 配置层修改（config.py）

在`TABLES`字典中添加DBLP配置：

```python
TABLES = {
    'openalex': 'OpenAlex',
    'semantic': 'semantic',
    'dblp': 'dblp'  # 新增
}
```

保持其他配置不变。

#### 1.2 API层修改（api_server.py）

**新增功能**：
- 添加DBLP专用查询分支
- 实现DBLP特有的统计查询：
  - CCF等级分布（`ccf_class`字段）
  - Venue类型分布（`venue_type`字段）
  - 年份趋势（`year`字段）
- 修改"全部数据"查询逻辑，合并DBLP数据（仅核心字段）

**删除功能**：
- 删除所有图谱相关API端点：
  - `/api/graph/authors`
  - `/api/graph/edges`
  - `/api/graph/stats`
- 删除辅助函数：
  - `get_merged_papers_sql()`
  - `get_graph_cache_key()`

#### 1.3 前端层修改（index.html）

**新增功能**：
- 在数据源下拉框中添加"DBLP"选项
- 添加DBLP特有的图表渲染：
  - CCF等级分布（饼图或柱状图）
  - Venue类型分布（饼图）
  - 年份趋势（折线图）
- 实现DBLP数据源的条件显示逻辑

**调整逻辑**：
- DBLP数据源时隐藏不适用的统计和图表：
  - 隐藏：citation_count、fwci、institution_country、institution_type相关内容
  - 显示：total_papers、unique_authors、unique_venues
- 将`unique_journals`显示为"Unique Venues"（适配DBLP的venue字段）

**删除功能**：
- 移除所有图谱相关的JavaScript代码
- 移除图谱导航链接（如果有）

#### 1.4 文件清理

- **删除**: `dashboard/graph.html`（合作关系图谱页面）
- **清理**: `api_server.py`中的所有图谱相关代码（约400行）

### 2. 数据字段映射策略

#### 2.1 全部数据查询

在"全部数据"查询时，仅映射核心字段：

| DBLP字段 | 通用字段 | 说明 |
|---------|---------|------|
| `doi` | `doi` | 直接映射 |
| `title` | `title` | 直接映射 |
| `author_name` | `author` | 作者姓名 |
| `author_pid` | `author_id` | 作者ID |
| `venue` | `journal` | 会议/期刊名称 |
| `year` | `publication_date` | 发表年份 |

**缺失字段处理规则**：
- `citation_count`: 不参与合并，在统计查询中返回0
- `tag`: 使用空字符串代替
- `institution_name`: 使用DBLP的`institution`字段
- `institution_country`、`institution_type`: 不合并，查询时返回0
- `fwci`: 不合并，查询时返回0

#### 2.2 DBLP独立查询

DBLP作为独立数据源时，使用原生字段并展示特有数据：

**CCF等级分布**：
```sql
SELECT
    ccf_class,
    uniqHLL12(doi) as count
FROM dblp
WHERE ccf_class != '' AND ccf_class != 'nan'
GROUP BY ccf_class
ORDER BY count DESC
```

**Venue类型分布**：
```sql
SELECT
    venue_type,
    uniqHLL12(doi) as count
FROM dblp
WHERE venue_type != '' AND venue_type != 'nan'
GROUP BY venue_type
ORDER BY count DESC
```

**年份趋势**：
```sql
SELECT
    year,
    uniqHLL12(doi) as count
FROM dblp
WHERE year != '' AND length(year) = 4
GROUP BY year
ORDER BY year DESC
```

### 3. API修改详情

#### 3.1 `/api/aggregated` 端点修改

**新增DBLP统计查询分支**：

```python
if source == 'dblp':
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

**新增DBLP特有数据查询**：
- CCF等级分布（替代引用数分布和FWCI分布）
- Venue类型分布（替代机构类型分布）
- 年份趋势（替代按月统计的publication_date）
- Top venues（使用`venue`字段，替代top journals）

**修改全部数据查询**：
- 在`get_all_sources_data()`函数的`TABLES`循环中添加DBLP处理
- 在`query_total_unique_journals()`中添加DBLP的UNION
- 在`try_merge_from_cache()`中添加DBLP缓存合并逻辑
- 智能缓存逻辑中添加DBLP支持

#### 3.2 删除的API端点

完全移除以下端点及相关代码：
- `@app.route('/api/graph/authors', methods=['GET'])`
- `@app.route('/api/graph/edges', methods=['GET'])`
- `@app.route('/api/graph/stats', methods=['GET'])`
- 所有相关的辅助函数（约300-400行代码）

#### 3.3 缓存策略调整

- DBLP数据源使用相同的Redis缓存机制
- 缓存键格式：`aggregated:dblp`
- 全部数据缓存中包含DBLP的独立数据：`_source_data.dblp`

### 4. 前端修改详情

#### 4.1 数据源选择下拉框

```html
<select id="dataSourceSelect">
    <option value="all">全部数据</option>
    <option value="openalex">OpenAlex</option>
    <option value="semantic">Semantic Scholar</option>
    <option value="dblp">DBLP</option>  <!-- 新增 -->
</select>
```

#### 4.2 统计卡片显示逻辑

**DBLP数据源显示的统计卡片**（共3个）：
- ✓ Total Papers (`total_papers`)
- ✓ Unique Authors (`unique_authors`)
- ✓ Unique Venues (`unique_journals`，标签改为"Unique Venues")

**DBLP数据源隐藏的统计卡片**：
- ✗ Unique Institutions
- ✗ Highly Cited Papers
- ✗ Average FWCI

#### 4.3 新增DBLP图表

当`data.source === 'dblp'`时：

**新增图表**：
1. **CCF等级分布**（饼图或柱状图）
   - 数据来源：`data.ccf_distribution`
   - 显示CCF A/B/C等级分布

2. **Venue类型分布**（饼图）
   - 数据来源：`data.venue_type_distribution`
   - 显示Conference/Journal等类型分布

3. **年份趋势**（折线图）
   - 数据来源：`data.papers_by_year`
   - 显示论文发表年份趋势

**调整的图表**：
- Top Journals → 改名为"Top Venues"，使用`data.top_venues`数据

**隐藏的图表**（OpenAlex/Semantic有，DBLP没有）：
- ✗ 引用数分布
- ✗ FWCI分布
- ✗ Top国家
- ✗ 机构类型分布

#### 4.4 移除图谱相关代码

- 删除所有与graph.html相关的链接
- 删除图谱相关的JavaScript变量和函数

### 5. 实现步骤

#### 阶段1: 配置与API后端（预计修改api_server.py约200行）

1. 修改`config.py`：
   - 在`TABLES`字典中添加`'dblp': 'dblp'`

2. 修改`api_server.py`：
   - 删除所有图谱相关代码（约400行）
   - 在`get_aggregated_data()`中添加DBLP分支
   - 实现DBLP统计查询SQL
   - 实现DBLP特有数据查询（CCF、venue_type、year）
   - 修改`get_all_sources_data()`添加DBLP循环
   - 修改`query_total_unique_journals()`添加DBLP UNION
   - 修改`try_merge_from_cache()`添加DBLP缓存合并
   - 调整智能缓存逻辑支持DBLP

#### 阶段2: 前端适配（预计修改index.html约300行）

1. 添加DBLP下拉选项

2. 修改统计卡片逻辑：
   - 添加DBLP数据源判断
   - 隐藏不适用的统计卡片
   - 调整unique_journals标签为"Unique Venues"

3. 实现DBLP图表：
   - CCF等级分布图表（饼图）
   - Venue类型分布图表（饼图）
   - 年份趋势图表（折线图）
   - Top Venues图表（复用Top Journals逻辑）

4. 隐藏不适用的图表：
   - 引用数分布
   - FWCI分布
   - Top国家
   - 机构类型分布

5. 移除图谱相关代码

#### 阶段3: 清理与测试

1. 删除`graph.html`文件

2. 功能测试：
   - 测试DBLP数据源切换
   - 测试DBLP独立查询
   - 测试全部数据查询（包含DBLP）
   - 验证DBLP特有图表显示
   - 验证OpenAlex/Semantic功能不受影响

3. 性能测试：
   - 验证DBLP查询性能
   - 验证缓存机制正常

### 6. 关键注意事项

#### 6.1 严格遵循CLAUDE.md规范

- **最小化改动**：只修改必要的代码，不添加额外功能
- **不改善无关代码**：不重构未涉及的代码段
- **保持代码风格**：遵循现有代码的命名和格式规范
- **不添加注释**：除非逻辑不显而易见

#### 6.2 数据一致性

- 全部数据查询时只合并有值的字段
- 避免因字段缺失导致的统计错误
- DBLP的`year`字段格式化为`YYYY`，与`publication_date`区分

#### 6.3 性能考虑

- DBLP表可能很大，使用`uniqHLL12`近似计数
- 合理设置查询超时时间（30秒）
- 使用`PREWHERE`子句优化查询性能
- 保持Redis缓存机制，TTL设置为300秒

#### 6.4 向后兼容

- 不影响现有OpenAlex和Semantic数据源功能
- 保持API响应格式一致
- 确保前端切换数据源时无错误

#### 6.5 错误处理

- DBLP查询失败时返回友好的错误信息
- 缓存失败时降级到直接查询
- 处理DBLP特有字段为空或NULL的情况

### 7. 成功标准

- [ ] DBLP作为独立数据源可正常查询和展示
- [ ] 全部数据查询正确合并DBLP数据
- [ ] DBLP特有图表（CCF、venue_type、year）正确显示
- [ ] 不适用的统计和图表正确隐藏
- [ ] 所有图谱相关代码和文件完全移除
- [ ] OpenAlex和Semantic功能不受影响
- [ ] 缓存机制正常工作
- [ ] 查询性能符合预期（<30秒）

### 8. 风险与限制

#### 8.1 已知风险

- DBLP表数据量大可能导致查询较慢
- 字段映射可能存在语义差异（venue vs journal）
- 年份格式可能与publication_date格式不一致

#### 8.2 限制

- DBLP数据源不显示引用相关统计（无citation_count字段）
- DBLP数据源不显示机构国家/类型信息
- DBLP数据源不显示FWCI相关数据

#### 8.3 未来改进

- 如果需要引用统计，可考虑从其他数据源关联
- 可以添加DBLP特有的作者排名功能
- 可以添加DBLP的CCF等级趋势分析

---

## 附录

### A. DBLP表结构参考

```
dblp_key                String
mdate                   String
type                    String
title                   String
year                    String
venue                   String
venue_type              String
ccf_class               String
author_pid              String
author_name             String
author_orcid            String
author_rank             UInt8
author_role             String
author_total_papers     UInt32
author_profile_url      String
volume                  String
number                  String
pages                   String
publisher               String
doi                     String
ee                      String
dblp_url                String
institution             String
institution_confidence  Float32
created_at              DateTime
```

### B. 相关文件清单

**需要修改的文件**：
- `dashboard/config.py`（添加DBLP配置，约5行）
- `dashboard/api_server.py`（添加DBLP支持，删除图谱代码，约200行净改动）
- `dashboard/index.html`（添加DBLP前端支持，删除图谱代码，约300行净改动）

**需要删除的文件**：
- `dashboard/graph.html`（图谱页面）

**不需要修改的文件**：
- `dashboard/chart.umd.js`（图表库）
- `dashboard/requirements.txt`（依赖）
- `dashboard/start.sh`（启动脚本）

### C. API响应格式示例

**DBLP独立查询响应**：

```json
{
  "papers_by_year": {
    "2023": 15000,
    "2022": 14500,
    "2021": 13800
  },
  "ccf_distribution": {
    "A": 5000,
    "B": 8000,
    "C": 12000,
    "N/A": 500
  },
  "venue_type_distribution": {
    "conference": 15000,
    "journal": 10000,
    "book": 500,
    "unknown": 3000
  },
  "top_venues": {
    "CVPR": 800,
    "ICCV": 650,
    "ECCV": 520
  },
  "statistics": {
    "total_papers": 28500,
    "unique_authors": 45000,
    "unique_journals": 3500,
    "unique_institutions": 0,
    "high_citations": 0,
    "avg_fwci": 0
  },
  "source": "dblp",
  "table": "dblp"
}
```
