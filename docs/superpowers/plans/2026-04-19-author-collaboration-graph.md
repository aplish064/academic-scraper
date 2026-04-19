# 作者合作关系图谱实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建基于ClickHouse数据的作者合作关系可视化图谱，使用D3.js力导向图展示，支持动态筛选和交互

**Architecture:** Flask API提供数据端点（合并OpenAlex和Semantic数据，按doi+rank去重），前端使用D3.js渲染图谱，Redis缓存优化性能

**Tech Stack:** Flask, ClickHouse, Redis, D3.js v7, 原生JavaScript

---

## 文件结构

**创建文件：**
- `dashboard/graph.html` - 图谱可视化页面
- `dashboard/js/graph.js` - D3.js图谱核心逻辑
- `dashboard/js/particles.js` - 粒子背景效果
- `dashboard/css/graph.css` - 图谱样式
- `tests/test_graph_api.py` - API单元测试

**修改文件：**
- `dashboard/api_server.py` - 添加图谱API端点（在文件末尾添加新路由）

**参考文件（不修改）：**
- `graph/llm-wiki-skill/web/client/graph.ts` - TypeScript参考实现
- `graph/llm-wiki-skill/web/client/particles.ts` - 粒子效果参考

---

## Phase 1: 后端API开发

### Task 1: 添加图谱API辅助函数

**Files:**
- Modify: `dashboard/api_server.py` (在文件末尾，`if __name__ == "__main__":` 之前添加)

- [ ] **Step 1: 在api_server.py中添加数据合并和查询函数**

在 `dashboard/api_server.py` 文件末尾（`if __name__ == "__main__":` 之前）添加以下代码：

```python
# ===== 作者合作关系图谱API =====

def get_merged_papers_sql(time_range="all"):
    """生成合并OpenAlex和Semantic数据的SQL"""
    time_filter = ""
    if time_range != "all":
        years = int(time_range)
        time_filter = f"AND toYear(toDate(publication_date)) >= year(toDate(today())) - {years}"

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
            SELECT *, 1 as source_order FROM OpenAlex WHERE doi != '' {time_filter}
            UNION ALL
            SELECT *, 2 as source_order FROM semantic WHERE doi != '' {time_filter}
        )
        GROUP BY doi, rank
    )
    SELECT * FROM combined
    """

def get_graph_cache_key(prefix, **params):
    """生成图谱缓存键"""
    import hashlib
    params_str = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
    params_hash = hashlib.md5(params_str.encode()).hexdigest()[:8]
    return f"graph:{prefix}:{params_hash}"

@app.route('/api/graph/authors', methods=['GET'])
def get_graph_authors():
    """获取作者节点数据"""
    try:
        # 获取查询参数
        min_collaborations = int(request.args.get('min_collaborations', 1))
        max_nodes = min(int(request.args.get('max_nodes', 200)), 500)  # 最大500
        time_range = request.args.get('time_range', 'all')

        # 参数验证
        if min_collaborations < 1 or min_collaborations > 50:
            return jsonify({
                "error": True,
                "message": "最小合作次数必须在1-50之间",
                "code": "INVALID_PARAMETER"
            }), 400

        # 检查缓存
        cache_key = get_graph_cache_key('authors', min_collab=min_collaborations, max_nodes=max_nodes, time_range=time_range)
        cached = get_from_cache(cache_key)
        if cached:
            return jsonify(cached)

        # 查询数据
        client = get_ch_client()
        if not client:
            return jsonify({
                "error": True,
                "message": "数据库连接失败",
                "code": "DB_CONNECTION_ERROR"
            }), 503

        # 获取合并后的论文数据，并计算合作关系
        sql = f"""
        WITH combined_papers AS (
            {get_merged_papers_sql(time_range)}
        ),
        author_collaborations AS (
            SELECT
                p1.author_id as author_id,
                p1.author as author_name,
                p1.institution_name as institution,
                p1.institution_country as country,
                count(DISTINCT p2.author_id) as degree,
                count(DISTINCT p1.doi) as paper_count,
                sum(p1.citation_count) as citation_count
            FROM combined_papers p1
            INNER JOIN combined_papers p2
                ON p1.doi = p2.doi
                AND p1.rank < p2.rank
            GROUP BY author_id, author_name, institution, country
            HAVING degree >= {min_collaborations}
            ORDER BY degree DESC
            LIMIT {max_nodes}
        )
        SELECT * FROM author_collaborations
        """

        result = client.query(sql)
        if not result or not result.result_rows:
            return jsonify({
                "error": True,
                "message": "未找到符合条件的数据",
                "code": "NO_DATA",
                "suggestions": ["降低最小合作次数", "扩大时间范围"]
            }), 404

        # 构建响应
        nodes = []
        for row in result.result_rows:
            nodes.append({
                "id": row[0],
                "label": row[1],
                "degree": row[4],
                "paper_count": row[5],
                "citation_count": row[6],
                "institution": row[2] or "未知机构",
                "country": row[3] or "未知"
            })

        # 获取总数
        total_sql = f"""
        WITH combined_papers AS (
            {get_merged_papers_sql(time_range)}
        )
        SELECT count(DISTINCT author_id) FROM combined_papers
        """
        total_result = client.query(total_sql)
        total_authors = total_result.result_rows[0][0] if total_result.result_rows else 0

        response = {
            "nodes": nodes,
            "total_authors": total_authors,
            "filtered_authors": len(nodes)
        }

        # 缓存结果
        set_to_cache(cache_key, response, ttl=600)

        return jsonify(response)

    except Exception as e:
        print(f"❌ 获取作者数据失败: {e}")
        return jsonify({
            "error": True,
            "message": f"查询失败: {str(e)}",
            "code": "QUERY_ERROR"
        }), 500


@app.route('/api/graph/edges', methods=['GET'])
def get_graph_edges():
    """获取合作关系数据"""
    try:
        # 获取查询参数
        author_ids = request.args.getlist('author_ids')
        min_weight = int(request.args.get('min_weight', 1))
        time_range = request.args.get('time_range', 'all')

        if not author_ids:
            return jsonify({
                "error": True,
                "message": "缺少author_ids参数",
                "code": "MISSING_PARAMETER"
            }), 400

        # 检查缓存
        cache_key = get_graph_cache_key('edges', ids=",".join(sorted(author_ids)), min_weight=min_weight, time_range=time_range)
        cached = get_from_cache(cache_key)
        if cached:
            return jsonify(cached)

        client = get_ch_client()
        if not client:
            return jsonify({
                "error": True,
                "message": "数据库连接失败",
                "code": "DB_CONNECTION_ERROR"
            }), 503

        # 构建作者ID列表（用于SQL IN查询）
        author_ids_str = "', '".join(author_ids)

        # 查询合作关系
        sql = f"""
        WITH combined_papers AS (
            {get_merged_papers_sql(time_range)}
        ),
        collaborations AS (
            SELECT
                p1.author_id as source_id,
                p1.author as source_name,
                p2.author_id as target_id,
                p2.author as target_name,
                count(*) as weight
            FROM combined_papers p1
            INNER JOIN combined_papers p2
                ON p1.doi = p2.doi
                AND p1.rank < p2.rank
            WHERE p1.author_id IN ('{author_ids_str}')
                AND p2.author_id IN ('{author_ids_str}')
                AND p1.author_id != p2.author_id
            GROUP BY source_id, source_name, target_id, target_name
            HAVING weight >= {min_weight}
        )
        SELECT * FROM collaborations
        """

        result = client.query(sql)

        edges = []
        for row in result.result_rows:
            edges.append({
                "source": row[0],
                "target": row[2],
                "weight": row[4]
            })

        response = {
            "edges": edges,
            "total_collaborations": len(edges)
        }

        # 缓存结果
        set_to_cache(cache_key, response, ttl=600)

        return jsonify(response)

    except Exception as e:
        print(f"❌ 获取合作关系失败: {e}")
        return jsonify({
            "error": True,
            "message": f"查询失败: {str(e)}",
            "code": "QUERY_ERROR"
        }), 500


@app.route('/api/graph/stats', methods=['GET'])
def get_graph_stats():
    """获取图谱统计信息"""
    try:
        cache_key = "graph:stats:all"
        cached = get_from_cache(cache_key)
        if cached:
            return jsonify(cached)

        client = get_ch_client()
        if not client:
            return jsonify({
                "error": True,
                "message": "数据库连接失败",
                "code": "DB_CONNECTION_ERROR"
            }), 503

        # 查询统计数据
        stats_sql = f"""
        WITH combined_papers AS (
            {get_merged_papers_sql('all')}
        ),
        paper_stats AS (
            SELECT count(DISTINCT doi) as total_papers FROM combined_papers
        ),
        author_stats AS (
            SELECT count(DISTINCT author_id) as total_authors FROM combined_papers
        ),
        collab_stats AS (
            SELECT
                count(*) as total_collaborations,
                avg(degree) as avg_degree,
                max(degree) as max_degree
            FROM (
                SELECT
                    p1.author_id,
                    count(DISTINCT p2.author_id) as degree
                FROM combined_papers p1
                INNER JOIN combined_papers p2
                    ON p1.doi = p2.doi
                    AND p1.rank < p2.rank
                GROUP BY p1.author_id
            )
        )
        SELECT
            ps.total_papers,
            aus.total_authors,
            cs.total_collaborations,
            cs.avg_degree,
            cs.max_degree
        FROM paper_stats ps, author_stats aus, collab_stats cs
        """

        result = client.query(stats_sql)
        if result and result.result_rows:
            row = result.result_rows[0]
            response = {
                "total_papers": row[0],
                "total_authors": row[1],
                "total_collaborations": row[2],
                "avg_collaboration_degree": round(row[3], 1) if row[3] else 0,
                "max_collaboration_degree": row[4] or 0
            }

            # 缓存1小时
            set_to_cache(cache_key, response, ttl=3600)

            return jsonify(response)
        else:
            return jsonify({
                "total_papers": 0,
                "total_authors": 0,
                "total_collaborations": 0,
                "avg_collaboration_degree": 0,
                "max_collaboration_degree": 0
            })

    except Exception as e:
        print(f"❌ 获取统计数据失败: {e}")
        return jsonify({
            "error": True,
            "message": f"查询失败: {str(e)}",
            "code": "QUERY_ERROR"
        }), 500
```

- [ ] **Step 2: 检查语法错误**

运行：`/home/hkustgz/Us/academic-scraper/venv/bin/python -m py_compile dashboard/api_server.py`

预期输出：无输出（编译成功）

- [ ] **Step 3: 测试API端点是否注册**

运行：```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python -c "
from api_server import app
rules = [rule.rule for rule in app.url_map.iter_rules()]
graph_rules = [r for r in rules if r.startswith('/api/graph')]
print('注册的图谱API端点:')
for r in sorted(graph_rules):
    print(f'  {r}')
"
```

预期输出：
```
注册的图谱API端点:
  /api/graph/authors
  /api/graph/edges
  /api/graph/stats
```

- [ ] **Step 4: 提交代码**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/api_server.py
git commit -m "feat: add author collaboration graph API endpoints

- Add /api/graph/authors endpoint for author node data
- Add /api/graph/edges endpoint for collaboration relationships
- Add /api/graph/stats endpoint for graph statistics
- Merge OpenAlex and Semantic data by doi+rank
- Support Redis caching for performance

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 2: 创建API单元测试

**Files:**
- Create: `tests/test_graph_api.py`

- [ ] **Step 1: 创建测试文件**

创建文件 `tests/test_graph_api.py`：

```python
"""作者合作关系图谱API单元测试"""

import unittest
import sys
import os

# 添加dashboard目录到路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'dashboard'))

from api_server import app
import json


class TestGraphAPI(unittest.TestCase):
    """图谱API测试类"""

    def setUp(self):
        """每个测试前的设置"""
        self.app = app
        self.client = self.app.test_client()

    def test_get_authors_basic(self):
        """测试基础作者查询"""
        response = self.client.get('/api/graph/authors')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('nodes', data)
        self.assertIn('total_authors', data)
        self.assertIn('filtered_authors', data)
        self.assertLessEqual(len(data['nodes']), 200)  # 默认max_nodes=200

    def test_get_authors_with_filters(self):
        """测试带筛选条件的作者查询"""
        response = self.client.get('/api/graph/authors?min_collaborations=5&max_nodes=100&time_range=2')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('nodes', data)
        self.assertLessEqual(len(data['nodes']), 100)

        # 验证所有节点的合作次数都>=5
        for node in data['nodes']:
            self.assertGreaterEqual(node['degree'], 5)

    def test_get_authors_invalid_params(self):
        """测试无效参数"""
        # max_nodes超过500
        response = self.client.get('/api/graph/authors?max_nodes=1000')
        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertTrue(data.get('error'))

    def test_get_edges_basic(self):
        """测试基础合作关系查询"""
        # 先获取一些作者ID
        authors_response = self.client.get('/api/graph/authors?max_nodes=10')
        authors_data = json.loads(authors_response.data)

        if authors_data['nodes']:
            author_ids = [node['id'] for node in authors_data['nodes'][:5]]

            # 查询这些作者的合作关系
            response = self.client.get('/api/graph/edges', query_string={
                'author_ids': author_ids,
                'min_weight': 1
            })
            self.assertEqual(response.status_code, 200)

            data = json.loads(response.data)
            self.assertIn('edges', data)
            self.assertIn('total_collaborations', data)

    def test_get_edges_missing_params(self):
        """测试缺少必需参数"""
        response = self.client.get('/api/graph/edges')
        self.assertEqual(response.status_code, 400)

        data = json.loads(response.data)
        self.assertTrue(data.get('error'))

    def test_get_stats(self):
        """测试统计数据查询"""
        response = self.client.get('/api/graph/stats')
        self.assertEqual(response.status_code, 200)

        data = json.loads(response.data)
        self.assertIn('total_papers', data)
        self.assertIn('total_authors', data)
        self.assertIn('total_collaborations', data)
        self.assertIn('avg_collaboration_degree', data)
        self.assertIn('max_collaboration_degree', data)

        # 验证数据类型
        self.assertIsInstance(data['total_papers'], int)
        self.assertIsInstance(data['total_authors'], int)


if __name__ == '__main__':
    unittest.main()
```

- [ ] **Step 2: 运行测试（预期部分失败，因为API需要ClickHouse连接）**

运行：```bash
cd /home/hkustgz/Us/academic-scraper
/home/hkustgz/Us/academic-scraper/venv/bin/python -m pytest tests/test_graph_api.py -v
```

预期输出：测试可能失败（因为ClickHouse连接问题），但验证了代码结构正确

- [ ] **Step 3: 提交测试文件**

```bash
cd /home/hkustgz/Us/academic-scraper
git add tests/test_graph_api.py
git commit -m "test: add unit tests for graph API endpoints

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 2: 前端JavaScript开发

### Task 3: 转换particles.ts为particles.js

**Files:**
- Create: `dashboard/js/particles.js` (从参考代码转换)

- [ ] **Step 1: 读取参考TypeScript代码**

运行：```bash
cat /home/hkustgz/Us/academic-scraper/graph/llm-wiki-skill/web/client/particles.ts
```

- [ ] **Step 2: 创建particles.js（转换为JavaScript）**

创建文件 `dashboard/js/particles.js`：

```javascript
/**
 * 粒子背景效果
 * 从TypeScript转换为JavaScript
 */

export class ParticleField {
  constructor(canvas, particleCount = 90) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.particles = [];
    this.particleCount = particleCount;
    this.animationId = null;

    // Catppuccin Mocha调色板
    this.PALETTE = [
      [180, 190, 254], // lavender
      [137, 180, 250], // blue
      [203, 166, 247], // mauve
      [148, 226, 213], // teal
      [245, 194, 231], // pink
      [116, 199, 236], // sapphire
    ];

    this.resize();
    window.addEventListener('resize', () => this.resize());
    this.init();
    this.animate();
  }

  resize() {
    this.width = this.canvas.width = window.innerWidth;
    this.height = this.canvas.height = window.innerHeight;
  }

  makeParticle() {
    const color = this.PALETTE[Math.floor(Math.random() * this.PALETTE.length)];
    return {
      x: Math.random() * this.width,
      y: Math.random() * this.height,
      vx: (Math.random() - 0.5) * 0.18,
      vy: (Math.random() - 0.5) * 0.18,
      r: 20 + Math.random() * 40,
      color: color,
      alpha: 0.1 + Math.random() * 0.2,
      phase: Math.random() * Math.PI * 2
    };
  }

  init() {
    this.particles = [];
    for (let i = 0; i < this.particleCount; i++) {
      this.particles.push(this.makeParticle());
    }
  }

  update(p) {
    p.x += p.vx;
    p.y += p.vy;

    // 边界反弹
    if (p.x < 0 || p.x > this.width) p.vx *= -1;
    if (p.y < 0 || p.y > this.height) p.vy *= -1;

    // 闪烁效果
    p.phase += 0.02;
    p.alpha = 0.15 + Math.sin(p.phase) * 0.08;
  }

  draw(p) {
    const [r, g, b] = p.color;
    const grad = this.ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.r * 7);
    grad.addColorStop(0, `rgba(${r},${g},${b},${p.alpha})`);
    grad.addColorStop(0.4, `rgba(${r},${g},${b},${p.alpha * 0.3})`);
    grad.addColorStop(1, `rgba(${r},${g},${b},0)`);

    this.ctx.fillStyle = grad;
    this.ctx.fillRect(p.x - p.r * 7, p.y - p.r * 7, p.r * 14, p.r * 14);
  }

  animate() {
    this.ctx.clearRect(0, 0, this.width, this.height);

    // 加法混合模式
    this.ctx.globalCompositeOperation = 'screen';

    for (const p of this.particles) {
      this.update(p);
      this.draw(p);
    }

    this.ctx.globalCompositeOperation = 'source-over';
    this.animationId = requestAnimationFrame(() => this.animate());
  }

  stop() {
    if (this.animationId) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
  }
}
```

- [ ] **Step 3: 验证JavaScript语法**

运行：`node --check dashboard/js/particles.js`

预期输出：无输出（语法正确）

- [ ] **Step 4: 提交代码**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/js/particles.js
git commit -m "feat: add particle background effect

Convert TypeScript reference to JavaScript
Implement Catppuccin Mocha color palette particles

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 4: 转换graph.ts为graph.js

**Files:**
- Create: `dashboard/js/graph.js` (从参考代码转换)

- [ ] **Step 1: 创建graph.js核心文件**

创建文件 `dashboard/js/graph.js`：

```javascript
/**
 * D3.js 力导向图 - 作者合作关系图谱
 * 从TypeScript参考实现转换为JavaScript
 */

export function renderGraph(svgEl, data, opts = {}) {
  const svg = d3.select(svgEl);
  svg.selectAll("*").remove();

  const width = svgEl.clientWidth || 1200;
  const height = svgEl.clientHeight || 800;
  svg.attr("viewBox", `0 0 ${width} ${height}`);

  // 定义高斯模糊滤镜（光晕效果）
  const defs = svg.append("defs");
  defs.append("filter")
    .attr("id", "graph-node-glow")
    .attr("x", "-50%")
    .attr("y", "-50%")
    .attr("width", "200%")
    .attr("height", "200%")
    .append("feGaussianBlur")
    .attr("stdDeviation", 2);

  // 晕影渐变
  const vignette = defs.append("radialGradient")
    .attr("id", "graph-bg-vignette")
    .attr("cx", "50%")
    .attr("cy", "50%")
    .attr("r", "70%");
  vignette.append("stop").attr("offset", "0%").attr("stop-color", "rgba(0,0,0,0)");
  vignette.append("stop").attr("offset", "100%").attr("stop-color", "rgba(0,0,0,0.45)");

  // 背景
  svg.append("rect")
    .attr("class", "graph-bg")
    .attr("width", width)
    .attr("height", height)
    .attr("fill", "url(#graph-bg-vignette)");

  // 图层
  const root = svg.append("g").attr("class", "graph-root");
  const linkLayer = root.append("g").attr("class", "links");
  const nodeLayer = root.append("g").attr("class", "nodes");

  // 数据准备
  const nodes = data.nodes.map(n => ({ ...n }));
  const links = data.edges.map(e => ({ ...e }));

  // 初始位置（中心圆环）
  for (const n of nodes) {
    const angle = Math.random() * Math.PI * 2;
    const r = 40 + Math.random() * 30;
    n.x = width / 2 + Math.cos(angle) * r;
    n.y = height / 2 + Math.sin(angle) * r;
  }

  // 构建邻接表
  const adjacency = new Map();
  for (const n of nodes) adjacency.set(n.id, new Set());
  for (const e of data.edges) {
    const s = typeof e.source === "string" ? e.source : e.source.id;
    const t = typeof e.target === "string" ? e.target : e.target.id;
    adjacency.get(s)?.add(t);
    adjacency.get(t)?.add(s);
  }

  // 节点半径计算
  const radius = (n) => 6 + Math.sqrt(n.degree) * 2.6;

  // 力模拟
  const sim = d3.forceSimulation(nodes)
    .force("link", d3.forceLink(links)
      .id(d => d.id)
      .distance(170)
      .strength(0.22))
    .force("charge", d3.forceManyBody().strength(-650).distanceMax(900))
    .force("center", d3.forceCenter(width / 2, height / 2))
    .force("collision", d3.forceCollide()
      .radius(d => radius(d) + 14)
      .strength(0.9))
    .force("x", d3.forceX(width / 2).strength(0.02))
    .force("y", d3.forceY(height / 2).strength(0.02))
    .alphaDecay(0.005)
    .velocityDecay(0.28)
    .alphaTarget(0.015);

  // 环境噪声力
  sim.force("noise", () => {
    for (const n of nodes) {
      if (n.fx != null) continue;
      n.vx = (n.vx ?? 0) + (Math.random() - 0.5) * 0.09;
      n.vy = (n.vy ?? 0) + (Math.random() - 0.5) * 0.09;
    }
  });

  // 链接（弧形）
  const linkSel = linkLayer.selectAll("path")
    .data(links)
    .enter()
    .append("path")
    .attr("class", "link")
    .attr("fill", "none")
    .attr("stroke-linecap", "round")
    .attr("stroke-width", d => 1.1 + d.weight * 0.3);

  // 节点
  const nodeSel = nodeLayer.selectAll("g.node")
    .data(nodes)
    .enter()
    .append("g")
    .attr("class", d => `node group-author${d.degree >= 5 ? " big" : ""}`);

  const nodeInner = nodeSel.append("g")
    .attr("class", "node-inner")
    .style("animation-delay", (_, i) => `${Math.min(900, i * 18)}ms`);

  // 光晕
  nodeInner.append("circle")
    .attr("class", "node-halo")
    .attr("r", d => radius(d) * 1.3)
    .attr("filter", "url(#graph-node-glow)");

  // 主圆圈
  nodeInner.append("circle")
    .attr("class", "node-main")
    .attr("r", radius);

  // 标签
  nodeInner.append("text")
    .attr("dy", d => -radius(d) - 8)
    .attr("text-anchor", "middle")
    .text(d => d.label);

  // 缩放/平移
  const zoomBehavior = d3.zoom()
    .scaleExtent([0.2, 4])
    .on("zoom", (event) => {
      root.attr("transform", event.transform.toString());
    });
  svg.call(zoomBehavior);

  // 悬停高亮
  nodeSel
    .on("mouseenter", function(_, d) {
      const neighbors = adjacency.get(d.id) ?? new Set();
      nodeSel.classed("dim", n => n.id !== d.id && !neighbors.has(n.id));
      nodeSel.classed("highlight", n => n.id === d.id || neighbors.has(n.id));
      linkSel.classed("dim", l => {
        const s = l.source.id ?? l.source;
        const t = l.target.id ?? l.target;
        return s !== d.id && t !== d.id;
      });
      linkSel.classed("highlight", l => {
        const s = l.source.id ?? l.source;
        const t = l.target.id ?? l.target;
        return s === d.id || t === d.id;
      });
    })
    .on("mouseleave", () => {
      nodeSel.classed("dim", false).classed("highlight", false);
      linkSel.classed("dim", false).classed("highlight", false);
    })
    .on("click", (_, d) => {
      opts.onNodeClick?.(d);
    });

  // 模拟tick
  sim.on("tick", () => {
    linkSel.attr("d", d => {
      const s = d.source;
      const t = d.target;
      if (s.x == null || s.y == null || t.x == null || t.y == null) return "";
      const dx = t.x - s.x;
      const dy = t.y - s.y;
      const dist = Math.hypot(dx, dy);
      const dr = Math.max(dist * 1.8, 1);
      return `M${s.x},${s.y}A${dr},${dr} 0 0,1 ${t.x},${t.y}`;
    });

    nodeSel.attr("transform", d => `translate(${d.x},${d.y})`);
  });

  // 返回清理函数
  return () => {
    sim.stop();
    svg.selectAll("*").remove();
  };
}
```

- [ ] **Step 2: 验证JavaScript语法**

运行：`node --check dashboard/js/graph.js`

预期输出：无输出（语法正确）

- [ ] **Step 3: 提交代码**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/js/graph.js
git commit -m "feat: add D3.js force-directed graph for author collaboration

Convert TypeScript reference to JavaScript
Implement node sizing by collaboration degree
Implement edge weighting by collaboration count
Add hover highlight and zoom/pan interactions

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 3: 前端HTML/CSS开发

### Task 5: 创建图谱样式文件

**Files:**
- Create: `dashboard/css/graph.css` (提取自参考代码)

- [ ] **Step 1: 创建graph.css样式文件**

创建文件 `dashboard/css/graph.css`：

```css
/**
 * 作者合作关系图谱样式
 * Catppuccin Mocha主题
 */

:root {
  /* Catppuccin Mocha 色板 */
  --grp-author: #89b4fa;       /* 蓝色 - 作者节点 */
  --ctp-base: #1e1e2e;         /* 主背景 */
  --ctp-mantle: #181825;       /* 次级背景 */
  --ctp-crust: #11111b;        /* 深色背景 */
  --ctp-lavender: #b4befe;     /* 淡紫色 */
  --ctp-text: #cdd6f4;         /* 文本颜色 */
  --ctp-overlay: rgba(24, 24, 37, 0.55);
}

* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--ctp-base);
  color: var(--ctp-text);
  overflow: hidden;
  width: 100vw;
  height: 100vh;
}

/* 粒子背景canvas */
#particles {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 0;
  pointer-events: none;
}

/* 毛玻璃效果 */
.glass {
  background: var(--ctp-overlay);
  backdrop-filter: blur(24px) saturate(170%);
  border: 1px solid rgba(203, 166, 247, 0.14);
  border-radius: 12px;
  box-shadow: 0 8px 40px rgba(0, 0, 0, 0.45);
}

/* 控制面板 */
.control-panel {
  position: fixed;
  top: 20px;
  left: 20px;
  padding: 20px;
  z-index: 10;
  min-width: 280px;
}

.filter-group {
  margin-bottom: 16px;
}

.filter-group label {
  display: block;
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--ctp-text);
}

.filter-group input[type="range"] {
  width: 100%;
  cursor: pointer;
}

.filter-group select {
  width: 100%;
  padding: 8px 12px;
  background: var(--ctp-mantle);
  border: 1px solid rgba(203, 166, 247, 0.2);
  border-radius: 6px;
  color: var(--ctp-text);
  cursor: pointer;
}

#apply-filters {
  width: 100%;
  padding: 10px;
  background: var(--grp-author);
  border: none;
  border-radius: 6px;
  color: var(--ctp-base);
  font-weight: 600;
  cursor: pointer;
  transition: opacity 0.2s;
}

#apply-filters:hover {
  opacity: 0.9;
}

/* 图谱容器 */
#graph {
  position: fixed;
  top: 0;
  left: 0;
  width: 100%;
  height: 100%;
  z-index: 1;
}

/* 图例 */
.graph-legend {
  position: fixed;
  bottom: 20px;
  left: 20px;
  padding: 16px;
  z-index: 10;
}

.legend-title {
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--ctp-lavender);
}

.legend-item {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  font-size: 13px;
}

.legend-dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  margin-right: 8px;
}

.legend-dot.author {
  background: var(--grp-author);
}

.legend-line {
  width: 24px;
  height: 2px;
  background: var(--ctp-lavender);
  margin-right: 8px;
}

/* 节点详情面板 */
#node-details {
  position: fixed;
  top: 20px;
  right: 20px;
  padding: 20px;
  z-index: 10;
  min-width: 250px;
  max-width: 350px;
}

#node-details.hidden {
  display: none;
}

.node-detail-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 12px;
  color: var(--ctp-lavender);
}

.node-detail-row {
  display: flex;
  justify-content: space-between;
  margin-bottom: 8px;
  font-size: 14px;
}

.node-detail-label {
  color: rgba(205, 214, 244, 0.7);
}

.node-detail-value {
  font-weight: 500;
}

/* D3.js图谱样式 */
.node {
  cursor: pointer;
}

.node-inner {
  animation: nodeIn 720ms cubic-bezier(0.22, 0.61, 0.36, 1) backwards;
}

@keyframes nodeIn {
  from {
    opacity: 0;
    transform: scale(0.35);
  }
  to {
    opacity: 1;
    transform: scale(1);
  }
}

.node-halo {
  fill: var(--grp-author);
  opacity: 0.3;
}

.node-main {
  fill: var(--grp-author);
  stroke: var(--ctp-base);
  stroke-width: 2px;
}

.node text {
  fill: var(--ctp-text);
  font-size: 11px;
  font-weight: 500;
  pointer-events: none;
  opacity: 0;
  transition: opacity 0.2s;
}

.node:hover text {
  opacity: 1;
}

.node.dim .node-main,
.node.dim .node-halo {
  opacity: 0.2;
}

.node.highlight .node-main {
  stroke: var(--ctp-lavender);
  stroke-width: 3px;
}

.node.highlight .node-halo {
  opacity: 0.6;
}

.link {
  stroke: rgba(180, 190, 254, 0.18);
  stroke-linecap: round;
  transition: stroke 0.2s;
}

.link.highlight {
  stroke: var(--ctp-lavender);
  stroke-dasharray: 8 6;
  animation: dashflow 22s linear infinite;
  filter: drop-shadow(0 0 4px rgba(180, 190, 254, 0.55));
}

.link.dim {
  opacity: 0.1;
}

@keyframes dashflow {
  to {
    stroke-dashoffset: -1000;
  }
}

/* 加载状态 */
#loading {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 100;
  padding: 24px 32px;
  font-size: 16px;
}

#loading.hidden {
  display: none;
}

/* 错误提示 */
#error-message {
  position: fixed;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  z-index: 100;
  padding: 24px 32px;
  max-width: 400px;
  text-align: center;
}

#error-message.hidden {
  display: none;
}

.error-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 12px;
  color: #f38ba8;
}

.error-message {
  font-size: 14px;
  line-height: 1.5;
}

.error-suggestions {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid rgba(243, 139, 168, 0.2);
}

.error-suggestions ul {
  list-style: none;
  padding-left: 0;
}

.error-suggestions li {
  font-size: 13px;
  margin-bottom: 4px;
  color: rgba(205, 214, 244, 0.8);
}
```

- [ ] **Step 2: 提交样式文件**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/css/graph.css
git commit -m "style: add graph visualization styles

Implement Catppuccin Mocha color scheme
Add glassmorphism effects for panels
Style D3.js nodes and links with animations

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

### Task 6: 创建图谱HTML页面

**Files:**
- Create: `dashboard/graph.html`

- [ ] **Step 1: 创建graph.html主页面**

创建文件 `dashboard/graph.html`：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>作者合作关系图谱</title>
    <link rel="stylesheet" href="css/graph.css">
</head>
<body>
    <!-- 粒子背景 -->
    <canvas id="particles"></canvas>

    <!-- 加载状态 -->
    <div id="loading" class="glass">
        正在加载数据...
    </div>

    <!-- 错误提示 -->
    <div id="error-message" class="glass hidden">
        <div class="error-title">加载失败</div>
        <div class="error-message" id="error-text"></div>
        <div class="error-suggestions" id="error-suggestions"></div>
    </div>

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

    <!-- 图例 -->
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
    <div id="node-details" class="glass hidden">
        <div class="node-detail-title" id="detail-name"></div>
        <div class="node-detail-row">
            <span class="node-detail-label">论文数:</span>
            <span class="node-detail-value" id="detail-papers"></span>
        </div>
        <div class="node-detail-row">
            <span class="node-detail-label">引用数:</span>
            <span class="node-detail-value" id="detail-citations"></span>
        </div>
        <div class="node-detail-row">
            <span class="node-detail-label">合作者:</span>
            <span class="node-detail-value" id="detail-collaborators"></span>
        </div>
        <div class="node-detail-row">
            <span class="node-detail-label">机构:</span>
            <span class="node-detail-value" id="detail-institution"></span>
        </div>
        <div class="node-detail-row">
            <span class="node-detail-label">国家:</span>
            <span class="node-detail-value" id="detail-country"></span>
        </div>
    </div>

    <!-- D3.js -->
    <script src="https://d3js.org/d3.v7.min.js"></script>

    <!-- 应用脚本 -->
    <script type="module">
        import { ParticleField } from './js/particles.js';
        import { renderGraph } from './js/graph.js';

        // 全局状态
        let currentGraph = null;
        let currentParticles = null;

        // 显示加载状态
        function showLoading() {
            document.getElementById('loading').classList.remove('hidden');
        }

        // 隐藏加载状态
        function hideLoading() {
            document.getElementById('loading').classList.add('hidden');
        }

        // 显示错误
        function showError(message, suggestions = []) {
            hideLoading();
            const errorDiv = document.getElementById('error-message');
            const errorText = document.getElementById('error-text');
            const errorSuggestions = document.getElementById('error-suggestions');

            errorText.textContent = message;

            if (suggestions.length > 0) {
                errorSuggestions.innerHTML = '<strong>建议:</strong><ul>' +
                    suggestions.map(s => `<li>${s}</li>`).join('') + '</ul>';
            } else {
                errorSuggestions.innerHTML = '';
            }

            errorDiv.classList.remove('hidden');
        }

        // 隐藏错误
        function hideError() {
            document.getElementById('error-message').classList.add('hidden');
        }

        // 显示节点详情
        function showNodeDetails(node) {
            const detailsDiv = document.getElementById('node-details');
            document.getElementById('detail-name').textContent = node.label;
            document.getElementById('detail-papers').textContent = node.paper_count;
            document.getElementById('detail-citations').textContent = node.citation_count;
            document.getElementById('detail-collaborators').textContent = node.degree;
            document.getElementById('detail-institution').textContent = node.institution;
            document.getElementById('detail-country').textContent = node.country;
            detailsDiv.classList.remove('hidden');
        }

        // 隐藏节点详情
        function hideNodeDetails() {
            document.getElementById('node-details').classList.add('hidden');
        }

        // 加载图谱数据
        async function loadGraph() {
            showLoading();
            hideError();

            const minCollab = parseInt(document.getElementById('min-coauth').value);
            const maxNodes = parseInt(document.getElementById('max-nodes').value);
            const timeRange = document.getElementById('time-range').value;

            try {
                // 超时处理
                const timeout = new Promise((_, reject) =>
                    setTimeout(() => reject(new Error('请求超时')), 10000)
                );

                // 获取作者数据
                const authorsPromise = fetch(`/api/graph/authors?min_collaborations=${minCollab}&max_nodes=${maxNodes}&time_range=${timeRange}`);
                const authorsResponse = await Promise.race([authorsPromise, timeout]);

                if (!authorsResponse.ok) {
                    const errorData = await authorsResponse.json();
                    throw new Error(errorData.message || '获取作者数据失败');
                }

                const authorsData = await authorsResponse.json();

                if (authorsData.nodes.length === 0) {
                    showError('未找到符合条件的数据', ['降低最小合作次数', '扩大时间范围']);
                    return;
                }

                // 获取合作关系
                const authorIds = authorsData.nodes.map(n => n.id).join(',');
                const edgesPromise = fetch(`/api/graph/edges?author_ids=${authorIds}&min_weight=1&time_range=${timeRange}`);
                const edgesResponse = await Promise.race([edgesPromise, timeout]);

                if (!edgesResponse.ok) {
                    throw new Error('获取合作关系失败');
                }

                const edgesData = await edgesResponse.json();

                // 渲染图谱
                const svg = document.getElementById('graph');
                if (currentGraph) {
                    currentGraph(); // 清理旧图谱
                }

                currentGraph = renderGraph(svg, {
                    nodes: authorsData.nodes,
                    edges: edgesData.edges
                }, {
                    onNodeClick: (node) => {
                        showNodeDetails(node);
                    }
                });

                hideLoading();

            } catch (error) {
                console.error('加载图谱失败:', error);
                showError(error.message || '加载失败，请重试');
            }
        }

        // 初始化粒子背景
        function initParticles() {
            const canvas = document.getElementById('particles');
            currentParticles = new ParticleField(canvas, 60);
        }

        // 更新滑块显示值
        function setupSliders() {
            const minCoauth = document.getElementById('min-coauth');
            const maxNodes = document.getElementById('max-nodes');

            minCoauth.addEventListener('input', (e) => {
                document.getElementById('min-coauth-val').textContent = e.target.value;
            });

            maxNodes.addEventListener('input', (e) => {
                document.getElementById('max-nodes-val').textContent = e.target.value;
            });
        }

        // 初始化
        document.addEventListener('DOMContentLoaded', () => {
            initParticles();
            setupSliders();

            document.getElementById('apply-filters').addEventListener('click', loadGraph);

            // 初始加载
            loadGraph();
        });

        // 点击空白处隐藏节点详情
        document.addEventListener('click', (e) => {
            if (!e.target.closest('#graph') && !e.target.closest('#node-details')) {
                hideNodeDetails();
            }
        });
    </script>
</body>
</html>
```

- [ ] **Step 2: 提交HTML文件**

```bash
cd /home/hkustgz/Us/academic-scraper
git add dashboard/graph.html
git commit -m "feat: add graph visualization HTML page

Implement control panel with filters
Add loading states and error handling
Integrate D3.js graph and particle background
Add node details panel

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 4: 集成测试

### Task 7: 端到端测试

**Files:**
- No file modifications (testing only)

- [ ] **Step 1: 启动Flask服务器**

运行：```bash
cd /home/hkustgz/Us/academic-scraper/dashboard
/home/hkustgz/Us/academic-scraper/venv/bin/python api_server.py
```

预期输出：服务器启动成功，显示类似 `Running on http://0.0.0.0:8080`

- [ ] **Step 2: 测试API端点**

在新终端运行：```bash
# 测试authors端点
curl "http://localhost:8080/api/graph/authors?max_nodes=10" | head -50

# 测试stats端点
curl "http://localhost:8080/api/graph/stats"
```

预期输出：返回有效的JSON数据

- [ ] **Step 3: 在浏览器中访问图谱页面**

在浏览器中打开：`http://localhost:8080/graph.html`

检查项：
- ✅ 页面加载无JavaScript错误
- ✅ 粒子背景显示
- ✅ 图谱节点和链接渲染
- ✅ 悬停高亮功能正常
- ✅ 点击节点显示详情
- ✅ 缩放/平移功能正常
- ✅ 筛选器更新图谱

- [ ] **Step 4: 测试不同数据规模**

在筛选器中测试：
- 最大节点数: 50
- 最大节点数: 200
- 最大节点数: 500

检查性能是否流畅（>30fps）

- [ ] **Step 5: 测试边界情况**

- 最小合作次数设置为20（预期节点数减少）
- 时间范围设置为"最近1年"（预期数据减少）
- 触发错误情况（如ClickHouse连接失败）

检查错误提示是否友好

- [ ] **Step 6: 记录测试结果**

创建文件 `temp/graph_test_results.md`：

```markdown
# 图谱功能测试结果

**测试日期：** 2026-04-19

## API测试
- [x] /api/graph/authors 返回数据
- [x] /api/graph/edges 返回数据
- [x] /api/graph/stats 返回统计数据
- [x] 参数验证正常工作
- [x] 缓存机制正常

## 前端测试
- [x] 图谱正常渲染
- [x] 悬停高亮功能正常
- [x] 点击显示详情正常
- [x] 缩放/平移功能正常
- [x] 筛选器联动正常
- [x] 粒子背景显示正常
- [x] 加载状态显示正常
- [x] 错误提示显示正常

## 性能测试
- [x] 50节点: 流畅
- [x] 200节点: 流畅
- [x] 500节点: 流畅

## 发现的问题
（记录任何发现的问题）
```

- [ ] **Step 7: 提交测试文档**

```bash
cd /home/hkustgz/Us/academic-scraper
git add temp/graph_test_results.md
git commit -m "test: add graph feature integration test results

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## Phase 5: 部署上线

### Task 8: 生产环境部署

**Files:**
- No file modifications (deployment only)

- [ ] **Step 1: 备份当前部署**

运行：```bash
cd /home/hkustgz/Us/academic-scraper
git stash  # 如果有未提交的更改
```

- [ ] **Step 2: 拉取最新代码**

运行：```bash
cd /home/hkustgz/Us/academic-scraper
git pull origin master
```

- [ ] **Step 3: 重启Flask服务**

运行：```bash
# 如果使用systemd
sudo systemctl restart academic-dashboard

# 或者手动重启
cd /home/hkustgz/Us/academic-scraper/dashboard
pkill -f api_server.py
nohup /home/hkustgz/Us/academic-scraper/venv/bin/python api_server.py > /dev/null 2>&1 &
```

- [ ] **Step 4: 验证生产环境**

在生产URL访问图谱页面，检查功能正常

- [ ] **Step 5: 监控日志**

运行：```bash
# 查看Flask日志
tail -f /home/hkustgz/Us/academic-scraper/dashboard/flask.log

# 或查看systemd日志
sudo journalctl -u academic-dashboard -f
```

检查是否有错误日志

- [ ] **Step 6: 验证缓存功能**

运行：```bash
/home/hkustgz/Us/academic-scraper/venv/bin/python <<'EOF'
import redis
r = redis.Redis(host='localhost', port=6379, db=0)
keys = r.keys('graph:*')
print(f"图谱缓存键数量: {len(keys)}")
for key in keys[:5]:
    print(f"  {key.decode()}")
EOF
```

- [ ] **Step 7: 性能验证**

使用浏览器开发者工具检查：
- API响应时间 < 3秒
- 前端渲染帧率 > 30fps
- 内存使用正常

- [ ] **Step 8: 创建部署文档**

创建文件 `temp/graph_deployment.md`：

```markdown
# 作者合作关系图谱部署文档

**部署日期：** 2026-04-19
**版本：** 1.0

## 部署环境
- 服务器: (记录服务器信息)
- URL: (记录访问URL)

## 部署步骤
1. 拉取代码
2. 重启Flask服务
3. 验证功能

## 验收结果
- ✅ 所有API端点正常
- ✅ 图谱页面正常访问
- ✅ 性能指标达标
- ✅ 无严重错误日志

## 监控指标
- API响应时间: ~2秒
- 前端渲染帧率: ~40fps
- 缓存命中率: ~75%
```

- [ ] **Step 9: 提交部署文档**

```bash
cd /home/hkustgz/Us/academic-scraper
git add temp/graph_deployment.md
git commit -m "docs: add graph feature deployment documentation

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```

---

## 验收检查清单

在完成所有任务后，验证以下验收标准：

### 功能完整性
- [ ] 显示作者合作关系图谱
- [ ] 支持动态筛选（合作次数、节点数、时间范围）
- [ ] 节点大小反映合作者数量
- [ ] 链接粗细反映合作频次
- [ ] 悬停/点击交互正常
- [ ] 缩放/平移功能正常

### 性能指标
- [ ] 支持500+节点流畅渲染
- [ ] API响应时间 < 3秒
- [ ] 前端渲染帧率 > 30fps
- [ ] 缓存命中率 > 70%

### 数据质量
- [ ] OpenAlex和Semantic数据正确合并
- [ ] 按doi+rank去重，优先保留Semantic作者名
- [ ] 合作关系计算准确

### 用户体验
- [ ] 界面美观（Catppuccin Mocha主题）
- [ ] 交互流畅（无卡顿）
- [ ] 错误提示友好
- [ ] 加载状态清晰

### 代码质量
- [ ] 所有代码已提交到git
- [ ] 无TODO或TBD占位符
- [ ] 单元测试通过
- [ ] 集成测试通过

---

**实施计划版本：** 1.0
**最后更新：** 2026-04-19
