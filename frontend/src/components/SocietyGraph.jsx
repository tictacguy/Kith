import { useRef, useEffect, useCallback, useState } from 'react'
import * as d3 from 'd3'

const ROLE_SHAPES = {
  Elder: '◆', Scout: '▲', Builder: '■', Critic: '✖',
  'Tool Smith': '⚙', Governor: '★', Analyst: '◎',
  Historian: '◑',
}
const STATUS_OPACITY = { active: 1, dormant: 0.3, retired: 0.15 }
const CLUSTER_THRESHOLD = 12 // collapse into clusters above this agent count

export default function SocietyGraph({ state, selectedAgent, onSelectAgent, activeAgents, activeLinks }) {
  const svgRef = useRef(null)
  const gRef = useRef(null)
  const simRef = useRef(null)
  const nodesRef = useRef([])
  const linksRef = useRef([])
  const initRef = useRef(false)
  const zoomRef = useRef(null)
  const [expandedClusters, setExpandedClusters] = useState(new Set())

  const toggleCluster = useCallback((role) => {
    setExpandedClusters(prev => {
      const next = new Set(prev)
      if (next.has(role)) next.delete(role)
      else next.add(role)
      return next
    })
  }, [])

  // -----------------------------------------------------------------------
  // Arrange
  // -----------------------------------------------------------------------
  const arrange = useCallback(() => {
    const nodes = nodesRef.current
    if (!nodes.length || !svgRef.current) return
    const { width, height } = svgRef.current.getBoundingClientRect()
    const cx = width / 2, cy = height / 2
    nodes.forEach(n => {
      n.fx = cx + (Math.random() - 0.5) * 40
      n.fy = cy + (Math.random() - 0.5) * 40
    })
    if (simRef.current) simRef.current.alpha(0.8).restart()
    setTimeout(() => {
      nodes.forEach(n => { n.fx = null; n.fy = null })
      if (simRef.current) simRef.current.alpha(0.3).restart()
    }, 600)
  }, [])

  // -----------------------------------------------------------------------
  // Build nodes — clustered or flat depending on agent count
  // -----------------------------------------------------------------------
  const buildGraphData = useCallback((state, expandedClusters) => {
    const agents = state.agents || []
    const tools = state.tools || [] // used by parent, not rendered in graph
    const realAgents = agents.filter(a => a.node_type !== 'system')
    const systemAgents = agents.filter(a => a.node_type === 'system')
    const useClusters = realAgents.length > CLUSTER_THRESHOLD

    const existingMap = Object.fromEntries(nodesRef.current.map(n => [n.id, n]))
    const newNodes = []

    if (useClusters) {
      // Group agents by role
      const byRole = {}
      realAgents.forEach(a => {
        const role = a.role || 'unknown'
        if (!byRole[role]) byRole[role] = []
        byRole[role].push(a)
      })

      Object.entries(byRole).forEach(([role, members]) => {
        if (expandedClusters.has(role)) {
          // Expanded — show individual agents
          members.forEach(a => {
            const existing = existingMap[a.id]
            newNodes.push({
              id: a.id, name: a.name, role: a.role || '—', status: a.status,
              interactions: a.interaction_count, supervisorId: a.supervisor_id,
              nodeType: 'agent', clustered: false,
              x: existing?.x, y: existing?.y, fx: existing?.fx, fy: existing?.fy,
            })
          })
        } else {
          // Collapsed — single cluster node
          const clusterId = `cluster:${role}`
          const existing = existingMap[clusterId]
          const avgRep = members.reduce((s, a) => s + (a.reputation || 0.5), 0) / members.length
          newNodes.push({
            id: clusterId, name: `${role} (${members.length})`, role,
            status: 'active', interactions: members.reduce((s, a) => s + a.interaction_count, 0),
            nodeType: 'cluster', memberCount: members.length, avgReputation: avgRep,
            memberIds: members.map(a => a.id),
            x: existing?.x, y: existing?.y, fx: existing?.fx, fy: existing?.fy,
          })
        }
      })
    } else {
      // Flat — all agents visible
      realAgents.forEach(a => {
        const existing = existingMap[a.id]
        newNodes.push({
          id: a.id, name: a.name, role: a.role || '—', status: a.status,
          interactions: a.interaction_count, supervisorId: a.supervisor_id,
          nodeType: 'agent', clustered: false,
          x: existing?.x, y: existing?.y, fx: existing?.fx, fy: existing?.fy,
        })
      })
    }

    // System entities (Historian)
    systemAgents.forEach(a => {
      const existing = existingMap[a.id]
      newNodes.push({
        id: a.id, name: a.name, role: a.role || '—', status: a.status,
        interactions: a.interaction_count, nodeType: 'system',
        x: existing?.x, y: existing?.y, fx: existing?.fx, fy: existing?.fy,
      })
    })

    // (Tools are shown in the Tools tab, not in the graph)

    // Links
    const nodeIds = new Set(newNodes.map(n => n.id))
    const newLinks = []

    // Supervision links (only between visible nodes)
    newNodes.forEach(n => {
      if (n.supervisorId && nodeIds.has(n.supervisorId))
        newLinks.push({ source: n.supervisorId, target: n.id, linkType: 'supervision' })
    })

    // Relationship links
    const relationships = state.relationships || []
    relationships.forEach(r => {
      if (r.agents?.length !== 2) return
      let src = r.agents[0], tgt = r.agents[1]

      // If either agent is inside a collapsed cluster, link to the cluster node
      if (!nodeIds.has(src)) {
        const cluster = newNodes.find(n => n.nodeType === 'cluster' && n.memberIds?.includes(src))
        if (cluster) src = cluster.id; else return
      }
      if (!nodeIds.has(tgt)) {
        const cluster = newNodes.find(n => n.nodeType === 'cluster' && n.memberIds?.includes(tgt))
        if (cluster) tgt = cluster.id; else return
      }
      if (src === tgt) return // same cluster
      if (!nodeIds.has(src) || !nodeIds.has(tgt)) return

      newLinks.push({
        source: src, target: tgt,
        linkType: r.affinity > 0 ? 'trust' : 'distrust',
        affinity: r.affinity,
      })
    })

    return { nodes: newNodes, links: newLinks }
  }, [])

  // -----------------------------------------------------------------------
  // Main effect — build/update graph
  // -----------------------------------------------------------------------
  useEffect(() => {
    if (!svgRef.current || !state?.agents?.length) return

    const svg = d3.select(svgRef.current)
    const { width, height } = svgRef.current.getBoundingClientRect()
    if (!width || !height) return

    if (!initRef.current) {
      svg.attr('viewBox', `0 0 ${width} ${height}`)
      const g = svg.append('g')
      gRef.current = g
      const zoom = d3.zoom().scaleExtent([0.2, 5]).on('zoom', e => g.attr('transform', e.transform))
      svg.call(zoom)
      svg.on('dblclick.zoom', null)
      zoomRef.current = zoom
      svg.on('click', () => onSelectAgent(null))
      svg.append('defs').append('marker')
        .attr('id', 'arrow').attr('viewBox', '0 0 10 10')
        .attr('refX', 28).attr('refY', 5)
        .attr('markerWidth', 6).attr('markerHeight', 6).attr('orient', 'auto')
        .append('path').attr('d', 'M0,0 L10,5 L0,10 Z').attr('fill', '#ccc')
      initRef.current = true
    }

    const g = gRef.current
    const { nodes: newNodes, links: newLinks } = buildGraphData(state, expandedClusters)
    nodesRef.current = newNodes
    linksRef.current = newLinks

    if (simRef.current) {
      simRef.current.stop()
      simRef.current = null
    }

    const sim = d3.forceSimulation(newNodes)
      .force('link', d3.forceLink(newLinks).id(d => d.id).distance(d =>
        d.source?.nodeType === 'cluster' || d.target?.nodeType === 'cluster' ? 140 : 110
      ))
      .force('charge', d3.forceManyBody().strength(d =>
        d.nodeType === 'cluster' ? -400 : -250
      ))
      .force('center', d3.forceCenter(width / 2, height / 2))
      .force('collide', d3.forceCollide(d =>
        d.nodeType === 'cluster' ? 60 : 45
      ))
      .velocityDecay(0.6)
    simRef.current = sim
    sim.on('tick', () => renderTick(g, newNodes, newLinks))

    renderGraph(g, newNodes, newLinks, selectedAgent, onSelectAgent, state.agents, toggleCluster)
  }, [state, expandedClusters])

  useEffect(() => {
    if (!gRef.current || !nodesRef.current.length) return
    updateActivity(gRef.current, nodesRef.current, activeAgents, activeLinks, selectedAgent)
  }, [activeAgents, activeLinks, selectedAgent])

  return (
    <div style={styles.container}>
      <svg ref={svgRef} style={styles.svg} />

      {/* Arrange button */}
      <button onClick={arrange} style={styles.arrangeBtn}>Arrange</button>

      {/* Legend */}
      <div style={styles.legend}>
        {Object.entries(ROLE_SHAPES).map(([role, shape]) => (
        <span style={styles.legendItem}><span style={{ fontSize: 14 }}>{shape}</span> {role}</span>
        ))}
      </div>

      {(!state?.agents?.length) && (
        <div style={styles.empty}>waiting for society...</div>
      )}
    </div>
  )
}

function nodeRadius(d) {
  if (d.nodeType === 'cluster') return 20 + Math.min(d.memberCount * 3, 20)
  if (d.nodeType === 'tool') return 12
  if (d.nodeType === 'system') return 14
  return 8 + Math.min(d.interactions * 2, 16)
}

function renderGraph(g, nodes, links, selectedAgent, onSelectAgent, rawAgents, toggleCluster) {
  // Links
  const linkSel = g.selectAll('.link').data(links, d => `${d.source.id || d.source}-${d.target.id || d.target}`)
  linkSel.exit().remove()
  linkSel.enter().append('line')
    .attr('class', 'link')
    .attr('stroke', d => {
      if (d.linkType === 'trust') return 'rgba(0,150,0,0.3)'
      if (d.linkType === 'distrust') return 'rgba(200,0,0,0.3)'
      return '#ddd'
    })
    .attr('stroke-width', d => d.linkType === 'supervision' ? 1 : Math.max(0.5, Math.abs(d.affinity || 0) * 2))
    .attr('stroke-dasharray', d => {
      if (d.linkType === 'distrust') return '2,2'
      if (d.linkType === 'supervision') return '4,3'
      return 'none'
    })
    .attr('marker-end', d => d.linkType === 'supervision' ? 'url(#arrow)' : null)

  g.selectAll('.active-link').remove()

  // Nodes
  const nodeSel = g.selectAll('.node-group').data(nodes, d => d.id)
  nodeSel.exit().remove()

  const enter = nodeSel.enter().append('g').attr('class', 'node-group').style('cursor', 'pointer')

  enter.append('circle').attr('class', 'node-circle')
  enter.append('text').attr('class', 'node-symbol')
    .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
    .style('pointer-events', 'none')
  enter.append('text').attr('class', 'node-name')
    .attr('text-anchor', 'middle').attr('font-size', 10)
    .attr('font-family', 'var(--mono)').style('pointer-events', 'none')
  enter.append('text').attr('class', 'node-role')
    .attr('text-anchor', 'middle').attr('font-size', 9)
    .style('pointer-events', 'none')
  enter.append('circle').attr('class', 'glow-ring')
    .attr('fill', 'none').attr('stroke', '#000').attr('stroke-width', 2)
    .attr('opacity', 0)

  // Cluster count badge
  enter.filter(d => d.nodeType === 'cluster').append('text').attr('class', 'cluster-count')
    .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
    .attr('font-size', 11).attr('font-family', 'var(--mono)')
    .attr('fill', '#666').attr('dy', 16).style('pointer-events', 'none')

  enter.call(d3.drag()
    .on('start', (e, d) => { d.fx = d.x; d.fy = d.y })
    .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; renderTick(g, nodes, links) })
    .on('end', (e, d) => { d.fx = null; d.fy = null })
  )

  enter.on('click', (e, d) => {
    e.stopPropagation()
    if (d.nodeType === 'cluster') {
      toggleCluster(d.role)
      return
    }
    if (d.nodeType === 'tool' || d.nodeType === 'system') return
    const agent = rawAgents?.find(a => a.id === d.id)
    onSelectAgent(selectedAgent?.id === d.id ? null : agent)
  })

  // Update all
  const allNodes = g.selectAll('.node-group')

  allNodes.select('.node-circle')
    .attr('r', nodeRadius)
    .attr('fill', d => {
      if (d.nodeType === 'cluster') return 'rgba(0,102,204,0.06)'
      if (d.nodeType === 'tool') return 'rgba(0,102,204,0.08)'
      if (d.nodeType === 'system') return '#f0f0f0'
      return '#fff'
    })
    .attr('stroke', d => {
      if (d.nodeType === 'cluster') return '#0066cc'
      if (d.nodeType === 'tool') return '#0066cc'
      return '#999'
    })
    .attr('stroke-width', d => d.nodeType === 'cluster' ? 2 : 1.5)
    .attr('stroke-dasharray', d => d.nodeType === 'cluster' ? '4,2' : 'none')
    .attr('opacity', d => STATUS_OPACITY[d.status] || 1)

  allNodes.select('.node-symbol')
    .text(d => {
      if (d.nodeType === 'cluster') return ROLE_SHAPES[d.role] || '○'
      if (d.nodeType === 'tool') return '⬡'
      return ROLE_SHAPES[d.role] || '○'
    })
    .attr('font-size', d => {
      if (d.nodeType === 'cluster') return 18
      if (d.nodeType === 'tool') return 12
      if (d.nodeType === 'system') return 14
      return 10 + Math.min(d.interactions, 8)
    })
    .attr('fill', d => (d.nodeType === 'tool' || d.nodeType === 'cluster') ? '#0066cc' : '#000')
    .attr('opacity', d => STATUS_OPACITY[d.status] || 1)

  allNodes.select('.node-name')
    .text(d => d.name)
    .attr('dy', d => nodeRadius(d) + 12)
    .attr('fill', d => (d.nodeType === 'tool' || d.nodeType === 'cluster') ? '#0066cc' : '#000')

  allNodes.select('.node-role')
    .text(d => {
      if (d.nodeType === 'cluster') return 'click to expand'
      if (d.nodeType === 'tool') return 'tool'
      if (d.nodeType === 'system') return 'system'
      return d.role
    })
    .attr('dy', d => nodeRadius(d) + 24)
    .attr('fill', d => d.nodeType === 'cluster' ? '#0066cc' : '#999')

  allNodes.select('.glow-ring').attr('r', d => nodeRadius(d) + 4)
}

function renderTick(g, nodes, links) {
  g.selectAll('.link')
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
  g.selectAll('.node-group')
    .attr('transform', d => `translate(${d.x || 0},${d.y || 0})`)
  g.selectAll('.active-link')
    .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
    .attr('x2', d => d.target.x).attr('y2', d => d.target.y)
}

function updateActivity(g, nodes, activeAgents, activeLinks, selectedAgent) {
  const nodeMap = Object.fromEntries(nodes.map(n => [n.id, n]))
  const selId = selectedAgent?.id

  // For clusters, check if any member is active
  const isActive = (d) => {
    if (activeAgents.has(d.id)) return true
    if (d.nodeType === 'cluster' && d.memberIds)
      return d.memberIds.some(id => activeAgents.has(id))
    return false
  }

  g.selectAll('.glow-ring')
    .attr('opacity', d => isActive(d) ? 1 : 0)
    .attr('stroke', d => isActive(d) ? '#000' : 'transparent')

  g.selectAll('.node-circle')
    .attr('stroke', d => {
      if (selId === d.id) return '#000'
      if (isActive(d)) return '#000'
      if (d.nodeType === 'cluster') return '#0066cc'
      return '#999'
    })
    .attr('stroke-width', d => {
      if (selId === d.id) return 2.5
      if (isActive(d)) return 2
      if (d.nodeType === 'cluster') return 2
      return 1.5
    })

  // Highlight links connected to selected
  g.selectAll('.link')
    .attr('opacity', d => {
      if (!selId) return 1
      const srcId = d.source.id || d.source
      const tgtId = d.target.id || d.target
      if (srcId === selId || tgtId === selId) return 1
      return 0.1
    })
    .attr('stroke-width', d => {
      if (!selId) {
        if (d.linkType === 'supervision') return 1
        return Math.max(0.5, Math.abs(d.affinity || 0) * 2)
      }
      const srcId = d.source.id || d.source
      const tgtId = d.target.id || d.target
      if (srcId === selId || tgtId === selId) {
        if (d.linkType === 'supervision') return 2
        return Math.max(1.5, Math.abs(d.affinity || 0) * 4)
      }
      return d.linkType === 'supervision' ? 1 : Math.max(0.5, Math.abs(d.affinity || 0) * 2)
    })

  // Dim unconnected nodes when agent is selected
  if (selId) {
    const connectedIds = new Set([selId])
    g.selectAll('.link').each(d => {
      const srcId = d.source.id || d.source
      const tgtId = d.target.id || d.target
      if (srcId === selId) connectedIds.add(tgtId)
      if (tgtId === selId) connectedIds.add(srcId)
    })
    g.selectAll('.node-group')
      .attr('opacity', d => connectedIds.has(d.id) ? 1 : 0.2)
  } else {
    g.selectAll('.node-group').attr('opacity', d => d.status === 'active' ? 1 : 0.3)
  }

  g.selectAll('.active-link').remove()
  activeLinks.forEach(l => {
    const from = nodeMap[l.from]
    const to = nodeMap[l.to]
    if (!from || !to) return
    g.append('line').attr('class', 'active-link')
      .attr('x1', from.x).attr('y1', from.y)
      .attr('x2', to.x).attr('y2', to.y)
      .attr('stroke', l.type === 'supervising' ? '#000' : '#666')
      .attr('stroke-width', 2)
      .attr('stroke-dasharray', l.type === 'supervising' ? '6,3' : '2,2')
      .attr('opacity', 0.7)
  })
}

const styles = {
  container: {
    width: '100%', height: '100%', position: 'relative', background: '#fff',
    backgroundImage: 'radial-gradient(#e8e8e8 1px, transparent 1px)', backgroundSize: '20px 20px',
  },
  svg: { width: '100%', height: '100%', display: 'block' },
  arrangeBtn: {
    position: 'absolute', top: 16, right: 16, zIndex: 200,
    fontFamily: 'var(--mono)', fontSize: 11, letterSpacing: 1,
    padding: '6px 16px', background: '#fff',
    border: '1px solid #e0e0e0', borderRadius: 4,
    cursor: 'pointer', color: '#000',
  },
  legend: {
    position: 'absolute', top: 16, left: 16, display: 'flex', gap: 16, flexWrap: 'wrap',
    background: 'rgba(255,255,255,0.9)', padding: '8px 14px', borderRadius: 6, border: '1px solid #e0e0e0',
  },
  legendItem: {
    fontSize: 10, color: '#666', display: 'flex', alignItems: 'center', gap: 4, fontFamily: 'var(--mono)',
  },
  empty: {
    position: 'absolute', top: '50%', left: '50%', transform: 'translate(-50%, -50%)',
    color: '#ccc', fontFamily: 'var(--mono)', fontSize: 14, letterSpacing: 1,
  },
}
