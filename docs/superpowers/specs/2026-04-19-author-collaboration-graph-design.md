# 作者合作关系图谱设计文档

**日期：** 2026-04-19
**状态：** 设计阶段
**预计工期：** 2-3天

## 概述

基于现有学术数据（OpenAlex和Semantic Scholar）构建作者合作关系可视化图谱，帮助研究者理解学术合作网络。

### 核心功能
- 展示作者间的合作关系（共同发表论文）
- 动态筛选合作强度、时间范围
- 可视化节点（作者）和链接（合作关系）
- 性能优化：支持500+节点流畅渲染

### 参考设计
基于 `/home/hkustgz/Us/academic-scraper/graph/llm-wiki-skill` 的D3.js力导向图实现，采用Catppuccin Mocha配色、毛玻璃效果、粒子背景。

---

## 系统架构

### 整体架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        Browser                              │
│  ┌──────────────┐         ┌──────────────┐                 │
│  │ index.html   │         │ graph.html   │                 │
│  │ (现有仪表板)  │◄───────►│ (新图谱页面)  │                 │
│  └──────────────┘         └──────┬───────┘                 │
│                                  │                          │
│                                  ▼                          │
│                          ┌──────────────┐                  │
│                          │   D3.js      │                  │
│                          │   力导向图    │                  │
│                          └──────────────┘                  │
└─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    Flask API Server                         │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ /api/graph/authors     - 获取作者节点数据              │  │
│  │ /api/graph/edges       - 获取合作关系数据              │  │
│  │ /api/graph/stats       - 获取图谱统计信息              │  │
│  └──────────────────────────────────────────────────────┘  │
│                                  │                          │
│                                  ▼                          │
│  ┌──────────────────────────────────────────────────────┐  │
│  │         Redis缓存 (合作关系预计算)                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────┐
│                    ClickHouse 数据库                        │
│  ┌──────────────┐    ┌──────────────┐                     │
│  │   OpenAlex   │    │   semantic   │                     │
│  │   原始表      │    │   原始表      │                     │
│  └──────────────┘    └──────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

### 目录结构

```
dashboard/
├── api_server.py           # 现有API服务器（添加图谱端点）
├── index.html              # 现有仪表板
├── graph.html              # 新增：图谱可视化页面
├── js/
│   ├── graph.js            # 新增：D3.js图谱逻辑（从graph.ts转换）
│   └── particles.js        # 新增：粒子背景（从particles.ts转换）
└── css/
    └── graph.css           # 新增：图谱样式（提取自参考代码）

docs/superpowers/specs/
└── 2026-04-19-author-collaboration-graph-design.md  # 本文档
```

### 技术栈

- **后端：** Flask + ClickHouse + Redis（现有技术栈）
- **前端：** D3.js v7 + 原生JavaScript
- **样式：** Catppuccin Mocha主题 + 毛玻璃效果 + 极光背景

---

## 数据处理

### 数据源合并

**关键需求：**
- OpenAlex和Semantic两个表可能包含同一篇论文（doi相同）
- 同一位作者在不同表中的名字可能不一致（如"J.Y. Zhang" vs "Junyou Zhang"）
- 需要按 `doi + rank` 去重，优先保留Semantic的作者名

**合并SQL逻辑：**

```sql
WITH combined AS (
    SELECT
        doi,
        rank,
        -- 优先使用semantic的author_id
        argMax(author_id, source_order) as author_id,
        -- 优先使用semantic的author
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
        -- OpenAlex数据（source_order=1，优先级低）
        SELECT *, 1 as source_order FROM OpenAlex
        UNION ALL
        -- Semantic数据（source_order=2，优先级高）
        SELECT *, 2 as source_order FROM semantic
    )
    GROUP BY doi, rank
)
SELECT * FROM combined
```

### 合作关系计算

**SQL逻辑：**

```sql
WITH author_papers AS (
    -- 上面的合并查询
),
co_authorship AS (
    SELECT
        p1.author_id as author1_id,
        p1.author as author1_name,
        p2.author_id as author2_id,
        p2.author as author2_name,
        count(*) as collaboration_count
    FROM author_papers p1
    JOIN author_papers p2
        ON p1.doi = p2.doi
        AND p1.rank < p2.rank  -- 避免重复和自连接
    GROUP BY author1_id, author1_name, author2_id, author2_name
)
SELECT * FROM co_authorship
```

---

## API设计

### 1. `/api/graph/authors` - 获取作者节点数据

**查询参数：**
- `min_collaborations`: int (default=1) - 最小合作次数
- `max_nodes`: int (default=200) - 最大节点数
- `time_range`: str (default="all") - 时间范围：all/1/2/3（年）

**响应格式：**
```json
{
  "nodes": [
    {
      "id": "https://openalex.org/A123456789",
      "label": "张三",
      "degree": 15,              # 合作者数量
      "paper_count": 42,         # 论文总数
      "citation_count": 156,     # 总引用数
      "institution": "香港科技大学",
      "country": "China"
    }
  ],
  "total_authors": 1234,        # 数据库总作者数
  "filtered_authors": 234       # 筛选后的作者数
}
```

### 2. `/api/graph/edges` - 获取合作关系数据

**查询参数：**
- `author_ids`: string[] - 作者ID列表（从nodes获取）
- `min_weight`: int (default=1) - 最小合作次数

**响应格式：**
```json
{
  "edges": [
    {
      "source": "https://openalex.org/A123456789",
      "target": "https://openalex.org/A987654321",
      "weight": 5               # 合作论文数
    }
  ],
  "total_collaborations": 456   # 总合作关系数
}
```

### 3. `/api/graph/stats` - 获取图谱统计信息

**响应格式：**
```json
{
  "total_papers": 12345,
  "total_authors": 2345,
  "total_collaborations": 5678,
  "avg_collaboration_degree": 4.8,
  "max_collaboration_degree": 42
}
```

---

## 前端设计

### 页面结构（graph.html）

```html
<!DOCTYPE html>
<html>
<head>
    <title>作者合作关系图谱</title>
    <link rel="stylesheet" href="css/graph.css">
</head>
<body>
    <!-- 粒子背景canvas -->
    <canvas id="particles"></canvas>

    <!-- 控制面板 -->
    <div class="control-panel glass">
        <div class="filter-group">
            <label>最小合作次数: <span id="min-coauth-val">1</span></label>
            <input type="range" id="min-coauth" min="1" max="20" value="1">
        </div>
        <div class="filter-group">
            <label>最大节点数: <span id="max-nodes-val">200</span></label>
            <input type="range" id="max-nodes" min="50" max="500" value="200">
        </div>
        <div class="filter-group">
            <label>时间范围:</label>
            <select id="time-range">
                <option value="all">全部</option>
                <option value="1">最近1年</option>
                <option value="2">最近2年</option>
                <option value="3">最近3年</option>
            </select>
        </div>
        <button id="apply-filters">应用筛选</button>
    </div>

    <!-- 图谱容器 -->
    <svg id="graph"></svg>

    <!-- 图例和提示 -->
    <div class="graph-legend glass">
        <div class="legend-title">作者合作关系</div>
        <div class="legend-item">
            <span class="legend-dot author"></span>
            <span>节点大小 = 合作者数量</span>
        </div>
        <div class="legend-item">
            <span class="legend-line"></span>
            <span>链接粗细 = 合作频次</span>
        </div>
    </div>

    <!-- 节点详情面板 -->
    <div id="node-details" class="glass hidden"></div>

    <script src="https://d3js.org/d3.v7.min.js"></script>
    <script src="js/particles.js"></script>
    <script src="js/graph.js"></script>
</body>
</html>
```

### 交互功能

**支持的操作：**
- ✅ 悬停高亮（鼠标移到节点上，高亮显示相关节点和链接）
- ✅ 点击节点（显示作者详情：论文数、引用数、机构等）
- ✅ 缩放/平移（鼠标滚轮缩放，拖拽画布平移）
- ❌ 拖拽节点（不实现此功能）
- ✅ 筛选器动态更新图谱

### 可视化特性

**节点设计：**
- 节点大小 = 6 + √(degree) × 2.6（degree为合作者数量）
- 节点颜色：统一使用作者节点颜色（可扩展）
- 悬停时显示作者姓名

**链接设计：**
- 弧形链接（非直线）
- 链接粗细 = 1.1 + weight × 0.3（weight为合作论文数）
- 高亮时显示流动动画

**物理模拟：**
- 斥力强度：-650
- 链接长度：170
- 碰撞检测：启用
- 环境噪声：微小随机速度，产生呼吸效果

---

## 缓存策略

### Redis缓存层级

**1. 预计算缓存（后台更新）**
- Key: `graph:top_authors:{time_range}`
- Value: Top 500 作者节点数据
- TTL: 3600秒（1小时）
- 更新频率: 每30分钟后台重算

**2. 查询缓存（按需更新）**
- Key: `graph:authors:{min_collab}:{max_nodes}:{time_range}`
- Value: 筛选后的作者节点
- TTL: 600秒（10分钟）

**3. 关系缓存**
- Key: `graph:edges:{author_ids_hash}`
- Value: 作者合作关系数据
- TTL: 600秒（10分钟）

### 性能优化策略

**ClickHouse查询优化：**
- 使用物化视图预计算合作关系
- 查询超时保护（5秒）
- 分页加载大数据集

**前端性能优化：**
- 分层加载：先显示Top 100节点，再逐步加载更多
- 防抖处理：筛选器变更300ms后才触发查询
- 虚拟化渲染：超出视口的节点不渲染DOM

**内存管理：**
- 节点数量上限：500个
- 链接数量上限：2000条（按权重排序）

---

## 错误处理

### API错误处理

**错误响应格式：**
```json
{
  "error": true,
  "message": "描述性错误信息",
  "code": "ERROR_CODE",
  "details": {}
}
```

**错误类型：**
1. **数据库连接错误** (503) - "数据库连接失败，请稍后重试"
2. **查询超时** (408) - "查询超时，请缩小查询范围"
3. **数据为空** (404) - "未找到符合条件的数据，请调整筛选条件"
4. **参数验证错误** (400) - "最大节点数不能超过500"

### 前端错误处理

**加载状态管理：**
- 显示加载中动画
- 10秒超时提示
- 友好的错误信息展示

### 边界情况处理

**1. 数据量过小**
- 节点数 < 10：显示提示"数据较少，建议扩大筛选范围"

**2. 数据量过大**
- 节点数 > 500：自动截断，显示提示"已显示前500个节点"

**3. 孤立节点**
- 没有合作关系的作者：仍然显示，但用灰色标记

**4. 作者ID为空**
- 使用 `author_name + institution` 作为临时ID

**5. 同名不同作者**
- 在节点详情中显示 `institution` 帮助区分

---

## 测试计划

### 单元测试

```python
# tests/test_graph_api.py
def test_get_authors_basic():
    """测试基础作者查询"""
    response = client.get('/api/graph/authors')
    assert response.status_code == 200
    assert 'nodes' in response.json
    assert len(response.json['nodes']) <= 200

def test_author_merge_logic():
    """测试OpenAlex和Semantic数据合并"""
    # 验证按doi+rank去重
    # 验证优先保留semantic作者名
    pass

def test_cache_invalidation():
    """测试缓存失效机制"""
    pass
```

### 集成测试

- 测试完整的数据流：ClickHouse → API → 前端渲染
- 测试筛选器联动
- 测试缓存机制

### 性能测试

```python
def test_query_performance():
    """确保API响应时间 < 3秒"""
    start = time.time()
    response = client.get('/api/graph/authors?max_nodes=500')
    duration = time.time() - start
    assert duration < 3.0
```

### 前端测试

- 测试不同数据量下的渲染性能（100/200/500节点）
- 测试浏览器兼容性（Chrome/Firefox/Safari）

---

## 部署计划

### Phase 1: 后端准备（1天）

**任务：**
1. 在 `api_server.py` 中添加图谱API端点
2. 实现数据合并和查询逻辑
3. 添加Redis缓存
4. 单元测试

**验收标准：**
- API端点返回正确数据
- 缓存机制正常工作
- 单元测试通过

### Phase 2: 前端开发（1天）

**任务：**
1. 创建 `graph.html`
2. 转换TypeScript代码为JavaScript（`graph.ts` → `graph.js`）
3. 转换 `particles.ts` → `particles.js`
4. 提取CSS样式到 `graph.css`
5. 集成测试

**验收标准：**
- 图谱正常渲染
- 交互功能正常（悬停、点击、缩放）
- 筛选器联动正常

### Phase 3: 集成测试（0.5天）

**任务：**
- 端到端测试
- 性能优化
- Bug修复

**验收标准：**
- 完整功能流程正常
- 500节点渲染流畅（>30fps）
- API响应时间 < 3秒

### Phase 4: 部署上线（0.5天）

**任务：**
1. 重启Flask服务
2. 验证生产环境功能
3. 监控日志和性能

**验收标准：**
- 生产环境访问正常
- 无严重错误日志
- 性能指标达标

---

## 验收标准

### 功能完整性
- ✅ 显示作者合作关系图谱
- ✅ 支持动态筛选（合作次数、节点数、时间范围）
- ✅ 节点大小反映合作者数量
- ✅ 链接粗细反映合作频次
- ✅ 悬停/点击交互正常
- ✅ 缩放/平移功能正常

### 性能指标
- ✅ 支持500+节点流畅渲染
- ✅ API响应时间 < 3秒
- ✅ 前端渲染帧率 > 30fps
- ✅ 缓存命中率 > 70%

### 数据质量
- ✅ OpenAlex和Semantic数据正确合并
- ✅ 按doi+rank去重，优先保留Semantic作者名
- ✅ 合作关系计算准确

### 用户体验
- ✅ 界面美观（Catppuccin Mocha主题）
- ✅ 交互流畅（无卡顿）
- ✅ 错误提示友好
- ✅ 加载状态清晰

---

## 风险和缓解措施

### 风险1：数据量过大导致性能问题

**缓解措施：**
- 设置节点数量上限（500个）
- 使用物化视图预计算
- Redis缓存热门查询

### 风险2：同名不同作者被误判为同一人

**缓解措施：**
- 在节点详情中显示机构信息帮助区分
- 后续可引入更复杂的作者消歧算法

### 风险3：前端性能不足

**缓解措施：**
- 使用虚拟化渲染
- 分层加载节点
- 参考代码已验证支持500+节点

### 风险4：ClickHouse查询慢

**缓解措施：**
- 设置5秒查询超时
- 使用物化视图
- Redis缓存结果

---

## 后续优化方向

1. **更复杂的作者消歧** - 使用机器学习算法识别同名不同作者
2. **时间轴动画** - 展示合作网络的演化过程
3. **社区发现算法** - 自动识别研究团队/学术圈
4. **导出功能** - 导出图谱数据为NetworkX/Gephi格式
5. **移动端适配** - 响应式设计，支持移动设备访问
6. **实时更新** - WebSocket推送新论文导致的合作关系变化

---

## 参考资料

- 参考实现：`/home/hkustgz/Us/academic-scraper/graph/llm-wiki-skill`
- D3.js官方文档：https://d3js.org/
- Catppuccin色板：https://catppuccin.com/
- ClickHouse文档：https://clickhouse.com/docs

---

**文档版本：** 1.0
**最后更新：** 2026-04-19
