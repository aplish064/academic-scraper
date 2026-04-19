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
