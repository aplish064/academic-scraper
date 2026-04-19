// D3.js Force-Directed Graph for Author Collaboration Network
// Renders interactive node-link diagram with physics simulation

/**
 * Main function to render the D3.js force-directed graph
 * @param {Object} data - Graph data with nodes and links
 * @param {Array} data.nodes - Array of node objects (authors)
 * @param {Array} data.links - Array of link objects (collaborations)
 */
export function renderGraph(data) {
  if (!data || !data.nodes || !data.links) {
    console.error('Invalid graph data:', data);
    return;
  }

  // Clear previous graph if exists
  d3.select('#collaboration-graph').selectAll('*').remove();

  const width = document.getElementById('collaboration-graph').clientWidth || 800;
  const height = document.getElementById('collaboration-graph').clientHeight || 600;

  // Create SVG
  const svg = d3.select('#collaboration-graph')
    .append('svg')
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', [0, 0, width, height])
    .style('font', '300 14px system-ui');

  // Create main group for zoom/pan
  const g = svg.append('g');

  // Define arrow marker for directed edges
  svg.append('defs').append('marker')
    .attr('id', 'arrow')
    .attr('viewBox', '0 -5 10 10')
    .attr('refX', 20)
    .attr('refY', 0)
    .attr('markerWidth', 6)
    .attr('markerHeight', 6)
    .attr('orient', 'auto')
    .append('path')
    .attr('d', 'M0,-5L10,0L0,5')
    .attr('fill', '#999')
    .attr('opacity', 0.6);

  // Create zoom behavior
  const zoom = d3.zoom()
    .scaleExtent([0.1, 4])
    .on('zoom', (event) => {
      g.attr('transform', event.transform);
    });

  svg.call(zoom);

  // Calculate node degrees for sizing
  const nodeDegrees = new Map();
  data.links.forEach(link => {
    nodeDegrees.set(link.source, (nodeDegrees.get(link.source) || 0) + 1);
    nodeDegrees.set(link.target, (nodeDegrees.get(link.target) || 0) + 1);
  });

  // Add degree to nodes
  data.nodes.forEach(node => {
    node.degree = nodeDegrees.get(node.id) || 0;
  });

  // Create force simulation
  const simulation = d3.forceSimulation(data.nodes)
    .force('link', d3.forceLink(data.links)
      .id(d => d.id)
      .distance(170))
    .force('charge', d3.forceManyBody()
      .strength(-650))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide()
      .radius(d => 6 + Math.sqrt(d.degree) * 2.6 + 5)
      .iterations(2));

  // Create curved links (arcs)
  const link = g.append('g')
    .attr('stroke', '#999')
    .attr('stroke-opacity', 0.6)
    .selectAll('path')
    .data(data.links)
    .join('path')
    .attr('stroke-width', d => Math.sqrt(d.value || 1))
    .attr('fill', 'none')
    .attr('marker-end', 'url(#arrow)');

  // Create nodes
  const node = g.append('g')
    .attr('stroke', '#fff')
    .attr('stroke-width', 1.5)
    .selectAll('circle')
    .data(data.nodes)
    .join('circle')
    .attr('r', d => 6 + Math.sqrt(d.degree) * 2.6)
    .attr('fill', d => {
      // Color based on degree (collaboration count)
      const hue = 200 + (d.degree % 60); // Blue to purple range
      return `hsl(${hue}, 70%, 50%)`;
    })
    .attr('cursor', 'pointer')
    .call(drag(simulation));

  // Add labels for nodes
  const label = g.append('g')
    .attr('class', 'labels')
    .selectAll('text')
    .data(data.nodes)
    .join('text')
    .text(d => d.name || d.id)
    .attr('font-size', 12)
    .attr('fill', '#333')
    .attr('text-anchor', 'middle')
    .attr('dy', d => -(6 + Math.sqrt(d.degree) * 2.6) - 5)
    .style('pointer-events', 'none')
    .style('text-shadow', '0 1px 0 #fff, 1px 0 0 #fff, 0 -1px 0 #fff, -1px 0 0 #fff');

  // Add hover interactions
  node.on('mouseover', function(event, d) {
    // Highlight connected nodes and links
    node.transition()
      .duration(200)
      .attr('opacity', n => {
        const connectedLinks = data.links.filter(l =>
          l.source.id === d.id || l.target.id === d.id
        );
        const connectedIds = new Set(connectedLinks.flatMap(l => [l.source.id, l.target.id]));
        return connectedIds.has(n.id) ? 1 : 0.1;
      });

    link.transition()
      .duration(200)
      .attr('opacity', l => l.source.id === d.id || l.target.id === d.id ? 1 : 0.1);

    label.transition()
      .duration(200)
      .attr('opacity', l => {
        const connectedLinks = data.links.filter(link =>
          link.source.id === d.id || link.target.id === d.id
        );
        const connectedIds = new Set(connectedLinks.flatMap(l => [l.source.id, l.target.id]));
        return connectedIds.has(l.id) ? 1 : 0.1;
      });

    // Show tooltip
    const tooltip = d3.select('body')
      .append('div')
      .attr('class', 'tooltip')
      .style('position', 'absolute')
      .style('padding', '10px')
      .style('background', 'rgba(0, 0, 0, 0.8)')
      .style('color', '#fff')
      .style('border-radius', '5px')
      .style('pointer-events', 'none')
      .style('font-size', '12px')
      .html(`<strong>${d.name || d.id}</strong><br/>Collaborations: ${d.degree}`);

    tooltip
      .style('left', (event.pageX + 10) + 'px')
      .style('top', (event.pageY - 10) + 'px');
  })
  .on('mouseout', function() {
    // Reset all highlights
    node.transition()
      .duration(200)
      .attr('opacity', 1);

    link.transition()
      .duration(200)
      .attr('opacity', 0.6);

    label.transition()
      .duration(200)
      .attr('opacity', 1);

    // Remove tooltip
    d3.selectAll('.tooltip').remove();
  })
  .on('click', function(event, d) {
    // Handle node click - could open author details
    console.log('Clicked node:', d);
    // You can trigger a modal or navigate to author page here
  });

  // Add title attribute for browser tooltip
  node.append('title')
    .text(d => `${d.name || d.id}\nCollaborations: ${d.degree}`);

  // Tick function to update positions
  simulation.on('tick', () => {
    // Update link paths with curves
    link.attr('d', d => {
      const dx = d.target.x - d.source.x;
      const dy = d.target.y - d.source.y;
      const dr = Math.sqrt(dx * dx + dy * dy) * 0.5; // Curve radius

      // Create curved path
      const midX = (d.source.x + d.target.x) / 2;
      const midY = (d.source.y + d.target.y) / 2;

      return `M ${d.source.x} ${d.source.y}
              Q ${midX} ${midY} ${d.target.x} ${d.target.y}`;
    });

    // Update node positions
    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y);

    // Update label positions
    label
      .attr('x', d => d.x)
      .attr('y', d => d.y);
  });

  // Add environmental noise for breathing effect
  setInterval(() => {
    data.nodes.forEach(node => {
      if (node.x && node.y) {
        node.x += (Math.random() - 0.5) * 0.3;
        node.y += (Math.random() - 0.5) * 0.3;
      }
    });
    simulation.alpha(0.1).restart();
  }, 2000);

  // Drag behavior
  function drag(simulation) {
    function dragstarted(event) {
      if (!event.active) simulation.alphaTarget(0.3).restart();
      event.subject.fx = event.subject.x;
      event.subject.fy = event.subject.y;
    }

    function dragged(event) {
      event.subject.fx = event.x;
      event.subject.fy = event.y;
    }

    function dragended(event) {
      if (!event.active) simulation.alphaTarget(0);
      event.subject.fx = null;
      event.subject.fy = null;
    }

    return d3.drag()
      .on('start', dragstarted)
      .on('drag', dragged)
      .on('end', dragended);
  }
}
