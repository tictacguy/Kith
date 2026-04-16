import { useRef, useEffect, useCallback } from 'react'
import * as d3 from 'd3'

const ROLE_SHAPES = {
  Elder: '◆', Scout: '▲', Builder: '■', Critic: '✖',
  'Tool Smith': '⚙', Governor: '★', Analyst: '◎',
  Historian: '◑',
}
const STATUS_OPACITY = { active: 1, dormant: 0.3, retired: 0.15 }

export default function SocietyGraph({ state, selectedAgent, onSelectAgent, activeAgents, activeLinks }) {
  const svgRef = useRef(null)
  const gRef = useRef(null)
  const simRef = useRef(null)
  const nodesRef = useRef([])
  const linksRef = useRef([])
  const initRef = useRef(false)
  const zoomRef = useRef(null)

  // -----------------------------------------------------------------------
  // Arrange — cluster agents by role, tools separate
  // -----------------------------------------------------------------------
  const arrange = useCallback(() => {
    const nodes = nodesRef.current
    if (!nodes.length || !svgRef.current) return

    const { width, height } = svgRef.current.getBoundingClientRect()
    const cx = width / 2, cy = height / 2

    // Pull all nodes toward center as a compact group
    nodes.forEach(n => {
      n.fx = cx + (Math.random() - 0.5) * 40
      n.fy = cy + (Math.random() - 0.5) * 40
    })

    if (simRef.current) {
      simRef.current.alpha(0.8).restart()
    }

    // Release after they converge — forces will spread them naturally
    setTimeout(() => {
      nodes.forEach(n => { n.fx = null; n.fy = null })
      if (simRef.current) simRef.current.alpha(0.3).restart()
    }, 600)
  }, [])

  // -----------------------------------------------------------------------
  // Build / update graph
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
    const agents = state.agents || []
    const tools = state.tools || []

    const existingMap = Object.fromEntries(nodesRef.current.map(n => [n.id, n]))
    const newNodes = agents.map(a => {
      const existing = existingMap[a.id]
      const nt = a.node_type === 'system' ? 'system' : 'agent'
      return {
        id: a.id, name: a.name, role: a.role || '—', status: a.status,
        interactions: a.interaction_count, supervisorId: a.supervisor_id, nodeType: nt,
        x: existing?.x ?? undefined, y: existing?.y ?? undefined,
        fx: existing?.fx, fy: existing?.fy,
      }
    })
    tools.forEach(t => {
      const existing = existingMap[`tool:${t.id}`]
      newNodes.push({
        id: `tool:${t.id}`, name: t.name, role: 'tool', status: 'active',
        interactions: t.usage_count || 0, nodeType: 'tool',
        x: existing?.x ?? undefined, y: existing?.y ?? undefined,
        fx: existing?.fx, fy: existing?.fy,
      })
    })
    nodesRef.current = newNodes

    const nodeIds = new Set(newNodes.map(n => n.id))
    const newLinks = []
    newNodes.forEach(n => {
      if (n.supervisorId && nodeIds.has(n.supervisorId))
        newLinks.push({ source: n.supervisorId, target: n.id, linkType: 'supervision' })
    })
    // Add relationship links (trust/distrust)
    const relationships = state.relationships || []
    relationships.forEach(r => {
      if (r.agents?.length === 2 && nodeIds.has(r.agents[0]) && nodeIds.has(r.agents[1])) {
        newLinks.push({
          source: r.agents[0], target: r.agents[1],
          linkType: r.affinity > 0 ? 'trust' : 'distrust',
          affinity: r.affinity,
        })
      }
    })
    linksRef.current = newLinks

    if (simRef.current) {
      simRef.current.nodes(newNodes)
      simRef.current.force('link').links(newLinks)
      simRef.current.alpha(0.15).restart()
    } else {
      const sim = d3.forceSimulation(newNodes)
        .force('link', d3.forceLink(newLinks).id(d => d.id).distance(110))
        .force('charge', d3.forceManyBody().strength(-250))
        .force('center', d3.forceCenter(width / 2, height / 2))
        .force('collide', d3.forceCollide(45))
        .velocityDecay(0.6)
      simRef.current = sim
      sim.on('tick', () => renderTick(g, newNodes, newLinks))
    }

    renderGraph(g, newNodes, newLinks, selectedAgent, onSelectAgent, agents)
  }, [state])

  useEffect(() => {
    if (!gRef.current || !nodesRef.current.length) return
    updateActivity(gRef.current, nodesRef.current, activeAgents, activeLinks, selectedAgent)
  }, [activeAgents, activeLinks, selectedAgent])

  return (
    <div style={styles.container}>
      <svg ref={svgRef} style={styles.svg} />

      {/* Arrange button — top right */}
      <button onClick={arrange} style={styles.arrangeBtn}>Arrange</button>

      {/* Legend — top left */}
      <div style={styles.legend}>
        {Object.entries(ROLE_SHAPES).map(([role, shape]) => (
          <span key={role} style={styles.legendItem}>
            <span style={{ fontSize: 14 }}>{shape}</span> {role}
          </span>
        ))}
        <span style={styles.legendItem}><span style={{ fontSize: 14 }}>⬡</span> Tool</span>
      </div>

      {(!state?.agents?.length) && (
        <div style={styles.empty}>waiting for society...</div>
      )}
    </div>
  )
}

function renderGraph(g, nodes, links, selectedAgent, onSelectAgent, rawAgents) {
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

  const nodeSel = g.selectAll('.node-group').data(nodes, d => d.id)
  nodeSel.exit().remove()

  const enter = nodeSel.enter().append('g').attr('class', 'node-group').style('cursor', 'pointer')

  enter.append('circle').attr('class', 'node-circle')
    .attr('fill', d => d.nodeType === 'tool' ? 'rgba(0,102,204,0.08)' : d.nodeType === 'system' ? '#f0f0f0' : '#fff')
    .attr('stroke', d => d.nodeType === 'tool' ? '#0066cc' : '#999').attr('stroke-width', 1.5)

  enter.append('text').attr('class', 'node-symbol')
    .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
    .attr('fill', '#000').style('pointer-events', 'none')

  enter.append('text').attr('class', 'node-name')
    .attr('text-anchor', 'middle').attr('font-size', 10)
    .attr('font-family', 'var(--mono)').attr('fill', '#000')
    .style('pointer-events', 'none')

  enter.append('text').attr('class', 'node-role')
    .attr('text-anchor', 'middle').attr('font-size', 9).attr('fill', '#999')
    .style('pointer-events', 'none')

  enter.append('circle').attr('class', 'glow-ring')
    .attr('fill', 'none').attr('stroke', '#000').attr('stroke-width', 2)
    .attr('opacity', 0)

  enter.call(d3.drag()
    .on('start', (e, d) => { d.fx = d.x; d.fy = d.y })
    .on('drag', (e, d) => { d.fx = e.x; d.fy = e.y; renderTick(g, nodes, links) })
    .on('end', (e, d) => { d.fx = null; d.fy = null })
  )

  enter.on('click', (e, d) => {
    e.stopPropagation()
    if (d.nodeType === 'tool' || d.nodeType === 'system') return
    const agent = rawAgents?.find(a => a.id === d.id)
    onSelectAgent(selectedAgent?.id === d.id ? null : agent)
  })

  const allNodes = g.selectAll('.node-group')
  const r = d => d.nodeType === 'tool' ? 12 : d.nodeType === 'system' ? 14 : 8 + Math.min(d.interactions * 2, 16)

  allNodes.select('.node-circle')
    .attr('r', r)
    .attr('opacity', d => STATUS_OPACITY[d.status] || 1)

  allNodes.select('.node-symbol')
    .text(d => d.nodeType === 'tool' ? '⬡' : (ROLE_SHAPES[d.role] || '○'))
    .attr('font-size', d => d.nodeType === 'tool' ? 12 : d.nodeType === 'system' ? 14 : 10 + Math.min(d.interactions, 8))
    .attr('fill', d => d.nodeType === 'tool' ? '#0066cc' : '#000')
    .attr('opacity', d => STATUS_OPACITY[d.status] || 1)

  allNodes.select('.node-name').text(d => d.name).attr('dy', d => r(d) + 12)
    .attr('fill', d => d.nodeType === 'tool' ? '#0066cc' : '#000')
  allNodes.select('.node-role').text(d => d.nodeType === 'tool' ? 'tool' : d.nodeType === 'system' ? 'system' : d.role).attr('dy', d => r(d) + 24)
    .attr('fill', d => d.nodeType === 'tool' ? '#0066cc' : '#999')
  allNodes.select('.glow-ring').attr('r', d => r(d) + 4)
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

  g.selectAll('.glow-ring')
    .attr('opacity', d => activeAgents.has(d.id) ? 1 : 0)
    .attr('stroke', d => activeAgents.has(d.id) ? '#000' : 'transparent')

  g.selectAll('.node-circle')
    .attr('stroke', d => {
      if (selId === d.id) return '#000'
      if (activeAgents.has(d.id)) return '#000'
      return '#999'
    })
    .attr('stroke-width', d => {
      if (selId === d.id) return 2.5
      if (activeAgents.has(d.id)) return 2
      return 1.5
    })

  // Highlight relationship links connected to selected agent
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
