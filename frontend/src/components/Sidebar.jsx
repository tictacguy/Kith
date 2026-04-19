import { useState, useRef, useEffect } from 'react'
import ConfigPanel from './ConfigPanel'
import AgentDetail from './AgentDetail'

const EVENT_LABELS = {
  processing_start: 'processing',
  processing_end: 'done',
  mobilization_start: 'mobilizing',
  mobilization_end: 'mobilized',
  agent_bidding: 'bidding',
  agent_thinking: 'thinking',
  agent_responded: 'responded',
  agent_deliberating: 'reading peers',
  agent_deliberated: 'reacted',
  deliberation_start: 'deliberation',
  deliberation_end: 'deliberated',
  agent_delegating: 'delegating',
  agent_delegated: 'delegation done',
  debate_start: 'debate',
  agent_debating: 'defending',
  debate_mediated: 'mediated',
  debate_end: 'debate resolved',
  agent_voting: 'voting',
  agent_voted: 'voted',
  consensus_start: 'consensus',
  consensus_end: 'consensus reached',
  agent_supervising: 'supervising',
  agent_verdict: 'verdict',
  synthesis_start: 'synthesizing',
  synthesis_end: 'synthesized',
  tool_called: 'tool called',
  memory_compressed: 'memory compressed',
  society_evolved: 'society evolved',
  retrospective_start: 'retrospective',
  retrospective_end: 'retrospective done',
}

export default function Sidebar({ state, events, connected, selectedAgent, onSelectAgent }) {
  const [tab, setTab] = useState('console')
  const [showConfig, setShowConfig] = useState(false)

  const agents = (state?.agents || []).filter(a => a.node_type !== 'system' && a.id !== '__historian__')
  const tools = state?.tools || []
  const policies = state?.policies || []

  if (selectedAgent) {
    return (
      <aside style={s.sidebar}>
        <AgentDetail agent={selectedAgent} state={state} onBack={() => onSelectAgent(null)} />
      </aside>
    )
  }

  return (
    <aside style={s.sidebar}>
      {/* Header */}
      <div style={s.header}>
        <img src="/logo_black.svg" alt="Kith" style={s.logo} />
        <button onClick={() => setShowConfig(c => !c)} style={s.settingsBtn} title="Settings">
          Settings
        </button>
      </div>
      {showConfig && (
        <div style={s.configOverlay}>
          <div style={s.configPanel}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
              <span style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>Settings</span>
              <button onClick={() => setShowConfig(false)} style={s.closeBtn}>×</button>
            </div>
            <ConfigPanel />
          </div>
        </div>
      )}

      {/* Stats */}
      {state && (
        <div style={s.stats}>
          <Stat label="agents" value={agents.filter(a => a.status === 'active').length} />
          <Stat label="interactions" value={state.total_interactions} />
          <Stat label="tools" value={tools.length} />
          <Stat label="policies" value={policies.filter(p => p.active).length} />
        </div>
      )}

      {/* Tabs */}
      <div style={s.tabs}>
        {['console', 'entities', 'memory', 'tools'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}>
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={s.content}>
        {tab === 'console' && <ConsoleTab events={events} />}
        {tab === 'entities' && <EntitiesTab agents={agents} onSelectAgent={onSelectAgent} />}
        {tab === 'memory' && <MemoryTab state={state} />}
        {tab === 'tools' && <ToolsTab tools={tools} />}
      </div>
    </aside>
  )
}

// ---------------------------------------------------------------------------
// Console — live event feed only (prompt moved above tabs)
// ---------------------------------------------------------------------------
function ConsoleTab({ events }) {
  const liveRef = useRef(null)
  useEffect(() => { if (liveRef.current) liveRef.current.scrollTop = 0 }, [events])

  return (
    <div style={s.consoleLayout}>
      {/* Live feed */}
      <div style={s.liveContainer}>
        <div ref={liveRef} style={s.liveFeed}>
          {events.length === 0 && <div style={s.muted}>waiting for activity...</div>}
          {events.map((e, i) => {
            const label = EVENT_LABELS[e.type] || e.type
            const isEvolution = e.type === 'society_evolved'
            const isRetro = e.type === 'retrospective_end'
            const detail = e.data?.agent_name || e.data?.tool_name || e.data?.prompt?.slice(0, 40) || e.data?.vote || ''

            // Retrospective events: show actions taken
            if (isRetro && e.data?.actions_taken?.length) {
              return e.data.actions_taken.map((line, j) => (
                <div key={`${i}-r-${j}`} style={s.eventRowEvolution}>
                  <span style={s.eventTime}>
                    {new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <span style={s.eventLabelEvolution}>retro: {line}</span>
                </div>
              ))
            }

            // Evolution events: render each changelog line separately
            if (isEvolution && e.data?.changelog?.length) {
              return e.data.changelog.map((line, j) => (
                <div key={`${i}-${j}`} style={s.eventRowEvolution}>
                  <span style={s.eventTime}>
                    {new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                  </span>
                  <span style={s.eventLabelEvolution}>{line}</span>
                </div>
              ))
            }

            return (
              <div key={i} style={s.eventRow}>
                <span style={s.eventTime}>
                  {new Date(e.ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })}
                </span>
                <span style={s.eventLabel}>{label}</span>
                {detail && <span style={s.eventDetail}>{detail}</span>}
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Entities — agents + tools merged
// ---------------------------------------------------------------------------
function EntitiesTab({ agents, onSelectAgent }) {
  return (
    <div style={s.scrollable}>
      {agents.length > 0 ? agents.map(a => (
        <div key={a.id} onClick={() => onSelectAgent(a)}
          onMouseEnter={e => e.currentTarget.style.background = 'var(--surface)'}
          onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
          style={{ ...s.entityRow, opacity: a.status === 'active' ? 1 : 0.35 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={s.entityName}>{a.name}</span>
            <span style={s.entityBadge}>{a.role || '--'}</span>
          </div>
          <div style={s.entityMeta}>
            {a.interaction_count} interactions
            {a.reputation != null && ` / ${(a.reputation * 100).toFixed(0)}% rep`}
            {a.supervisor_id ? ' / supervised' : ''}
          </div>
        </div>
      )) : (
        <div style={s.muted}>no agents yet</div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tools — dedicated tab with full detail
// ---------------------------------------------------------------------------
function ToolsTab({ tools }) {
  return (
    <div style={s.scrollable}>
      {tools.length === 0 && (
        <div style={s.muted}>No tools yet. The Tool Smith proposes tools as the society identifies needs.</div>
      )}
      {tools.map(t => (
        <div key={t.id} style={s.toolCard}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={s.entityName}>{t.name}</span>
            <span style={s.toolUsage}>{t.usage_count}x</span>
          </div>
          <div style={s.entityMeta}>{t.description}</div>
          {t.parameters && Object.keys(t.parameters).length > 0 && (
            <div style={s.toolParams}>
              {Object.entries(t.parameters).map(([k, v]) => (
                <span key={k} style={s.toolParam}>{k}: {typeof v === 'string' ? v : JSON.stringify(v)}</span>
              ))}
            </div>
          )}
          {t.created_at && (
            <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--mono)', marginTop: 4 }}>
              proposed {new Date(t.created_at).toLocaleDateString()}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Memory — society summary, dominant themes, policies
// ---------------------------------------------------------------------------
function MemoryTab({ state }) {
  if (!state) return <div style={s.muted}>loading...</div>

  const policies = state.policies?.filter(p => p.active) || []

  return (
    <div style={s.scrollable}>
      {/* Society summary */}
      <div style={s.memSection}>
        <div style={s.memLabel}>Society Summary</div>
        {state.society_summary ? (
          <div style={s.memText}>{state.society_summary}</div>
        ) : (
          <div style={s.muted}>No summary yet. The society builds memory as it processes prompts.</div>
        )}
      </div>

      {/* Dominant themes */}
      <div style={s.memSection}>
        <div style={s.memLabel}>Dominant Themes</div>
        {state.dominant_themes?.length > 0 ? (
          <div style={s.themeList}>
            {state.dominant_themes.map((t, i) => (
              <span key={i} style={s.themeTag}>{t}</span>
            ))}
          </div>
        ) : (
          <div style={s.muted}>No themes yet.</div>
        )}
      </div>

      {/* Active policies */}
      <div style={s.memSection}>
        <div style={s.memLabel}>Active Policies ({policies.length})</div>
        {policies.length === 0 && <div style={s.muted}>No policies yet. Policies emerge as the society encounters problems.</div>}
        {policies.map(p => (
          <div key={p.id} style={s.policyRow}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div style={s.policyName}>{p.name}</div>
              <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                <span style={{
                  fontSize: 9, fontFamily: 'var(--mono)', padding: '1px 5px',
                  border: '1px solid var(--border)', borderRadius: 3, color: 'var(--muted)',
                }}>{p.source || 'organic'}</span>
                {p.effectiveness != null && (
                  <span style={{
                    fontSize: 9, fontFamily: 'var(--mono)', color: p.effectiveness > 0.5 ? '#0a7' : '#c44',
                  }}>{(p.effectiveness * 100).toFixed(0)}%</span>
                )}
              </div>
            </div>
            <div style={s.policyRule}>{p.rule}</div>
          </div>
        ))}
      </div>

      {/* Stage info */}
      <div style={s.memSection}>
        <div style={s.memLabel}>Stage</div>
        <div style={{ fontSize: 13, fontFamily: 'var(--mono)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: 1 }}>
          {state.stage}
        </div>
        <div style={{ fontSize: 11, color: 'var(--muted)', marginTop: 4 }}>
          {state.total_interactions} total interactions
        </div>
      </div>

      {/* Last retrospective */}
      {state.last_retrospective && (
        <div style={s.memSection}>
          <div style={s.memLabel}>Last Retrospective</div>
          <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--mono)', marginBottom: 8 }}>
            {state.last_retrospective.range}
          </div>

          {state.last_retrospective.quality && (
            <div style={{ fontSize: 12, lineHeight: 1.6, marginBottom: 12 }}>
              {state.last_retrospective.quality}
            </div>
          )}

          {state.last_retrospective.strengths?.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, marginBottom: 4 }}>STRENGTHS</div>
              {state.last_retrospective.strengths.map((s, i) => (
                <div key={i} style={{ fontSize: 11, color: '#0a7', lineHeight: 1.5 }}>+ {s}</div>
              ))}
            </div>
          )}

          {state.last_retrospective.weaknesses?.length > 0 && (
            <div style={{ marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, marginBottom: 4 }}>WEAKNESSES</div>
              {state.last_retrospective.weaknesses.map((s, i) => (
                <div key={i} style={{ fontSize: 11, color: '#c44', lineHeight: 1.5 }}>- {s}</div>
              ))}
            </div>
          )}

          {state.last_retrospective.actions_taken?.length > 0 && (
            <div>
              <div style={{ fontSize: 10, color: 'var(--muted)', fontWeight: 600, marginBottom: 4 }}>ACTIONS TAKEN</div>
              {state.last_retrospective.actions_taken.map((s, i) => (
                <div key={i} style={{ fontSize: 11, color: '#0066cc', lineHeight: 1.5 }}>{s}</div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div style={s.stat}>
      <span style={s.statValue}>{value}</span>
      <span style={s.statLabel}>{label}</span>
    </div>
  )
}

const s = {
  sidebar: {
    width: 'var(--sidebar-w)', minWidth: 'var(--sidebar-w)',
    borderRight: '1px solid var(--border)', display: 'flex',
    flexDirection: 'column', height: '100vh', overflow: 'hidden',
    position: 'relative',
  },
  header: {
    padding: '16px 16px 12px', display: 'flex', alignItems: 'center',
    gap: 8, borderBottom: '1px solid var(--border)', flexShrink: 0,
  },
  logo: { height: 20 },
  dot: { width: 6, height: 6, borderRadius: '50%', flexShrink: 0 },
  stage: { fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)', marginLeft: 'auto', textTransform: 'uppercase', letterSpacing: 1 },
  settingsBtn: {
    marginLeft: 'auto', background: 'none', border: 'none',
    padding: 0, cursor: 'pointer', color: 'var(--muted)',
    fontFamily: 'var(--mono)', fontSize: 10, letterSpacing: 0.5,
    textTransform: 'uppercase',
  },
  configOverlay: {
    position: 'absolute', top: 0, left: 0, right: 0, bottom: 0,
    background: 'var(--bg)', zIndex: 300,
    display: 'flex', flexDirection: 'column', overflow: 'auto',
  },
  configPanel: { padding: 16, flex: 1 },
  closeBtn: {
    background: 'none', border: 'none', fontSize: 18, cursor: 'pointer',
    color: 'var(--muted)', padding: '0 4px', lineHeight: 1,
  },
  stats: { display: 'flex', padding: '10px 16px', gap: 16, borderBottom: '1px solid var(--border)', flexShrink: 0 },
  stat: { display: 'flex', flexDirection: 'column', alignItems: 'center', flex: 1 },
  statValue: { fontFamily: 'var(--mono)', fontWeight: 600, fontSize: 16 },
  statLabel: { fontSize: 9, color: 'var(--muted)', textTransform: 'uppercase', letterSpacing: 0.5 },

  // Prompt area — inside console tab
  promptArea: { flexShrink: 0, paddingBottom: 12 },
  promptBox: {
    display: 'flex', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    overflow: 'hidden', background: 'var(--bg)', transition: 'border-color 0.15s',
  },
  promptInput: {
    flex: 1, border: 'none', outline: 'none', resize: 'none',
    fontFamily: 'var(--font)', fontSize: 13, lineHeight: 1.5,
    padding: '10px 12px', background: 'transparent', minHeight: 44,
  },
  promptBtn: {
    width: 44, border: 'none', borderLeft: '1px solid var(--border)',
    background: 'var(--fg)', color: 'var(--bg)', cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 0, transition: 'opacity 0.15s', flexShrink: 0,
  },
  spinner: {
    width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff', borderRadius: '50%',
    animation: 'spin 0.6s linear infinite', display: 'block',
  },

  // Tabs
  tabs: { display: 'flex', borderBottom: '1px solid var(--border)', flexShrink: 0 },
  tab: {
    flex: 1, border: 'none', borderRadius: 0, padding: '8px 0', fontSize: 10,
    textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', background: 'transparent',
  },
  tabActive: { color: 'var(--fg)', borderBottom: '2px solid var(--fg)', fontWeight: 600 },

  // Content
  content: { flex: 1, overflow: 'hidden', display: 'flex', flexDirection: 'column', minHeight: 0 },
  scrollable: { flex: 1, overflow: 'auto', padding: 16, display: 'flex', flexDirection: 'column', gap: 0 },

  // Console layout
  consoleLayout: { display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0, padding: 16, gap: 0 },

  // Live feed (console tab)
  liveContainer: {
    flex: 1, minHeight: 0, display: 'flex', flexDirection: 'column',
    padding: 12, overflow: 'hidden',
  },
  liveFeed: { flex: 1, overflow: 'auto', minHeight: 0, display: 'flex', flexDirection: 'column', gap: 1 },
  eventRow: { display: 'flex', gap: 8, fontSize: 11, fontFamily: 'var(--mono)', padding: '3px 0', borderBottom: '1px solid var(--border)' },
  eventTime: { color: 'var(--muted)', fontSize: 10, flexShrink: 0, width: 60 },
  eventLabel: { color: 'var(--fg)', fontWeight: 500, flexShrink: 0 },
  eventDetail: { color: 'var(--muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
  eventRowEvolution: {
    display: 'flex', gap: 8, fontSize: 11, fontFamily: 'var(--mono)', padding: '4px 0',
    borderBottom: '1px solid var(--border)', background: 'rgba(0,100,200,0.04)',
  },
  eventLabelEvolution: { color: '#0066cc', fontWeight: 500, flex: 1 },

  // Entities tab
  entityGroupLabel: {
    fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5,
    color: 'var(--muted)', padding: '8px 12px 4px', fontWeight: 600,
  },
  entityRow: {
    padding: '10px 12px', cursor: 'pointer',
    borderBottom: '1px solid var(--border)', transition: 'background 0.15s',
  },
  entityName: { fontWeight: 600, fontSize: 13 },
  entityBadge: {
    fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--muted)',
    padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 3,
  },
  entityMeta: { fontSize: 11, color: 'var(--muted)', marginTop: 2 },

  // Tools tab
  toolCard: {
    padding: '12px 12px', borderBottom: '1px solid var(--border)',
  },
  toolUsage: {
    fontSize: 10, fontFamily: 'var(--mono)', color: 'var(--muted)',
    padding: '2px 6px', border: '1px solid var(--border)', borderRadius: 3,
  },
  toolParams: {
    display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 6,
  },
  toolParam: {
    fontSize: 10, fontFamily: 'var(--mono)', padding: '2px 6px',
    background: 'var(--surface)', borderRadius: 3, color: 'var(--fg)',
  },

  // Memory tab
  memSection: { padding: '14px 0', borderBottom: '1px solid var(--border)' },
  memLabel: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 8, fontWeight: 600 },
  memText: { fontSize: 12, lineHeight: 1.6, color: 'var(--fg)' },
  themeList: { display: 'flex', flexWrap: 'wrap', gap: 6 },
  themeTag: {
    fontSize: 11, fontFamily: 'var(--mono)', padding: '3px 10px',
    border: '1px solid var(--border)', borderRadius: 12, color: 'var(--fg)',
  },
  policyRow: { padding: '8px 0', borderBottom: '1px solid var(--surface)' },
  policyName: { fontSize: 12, fontWeight: 600, marginBottom: 2 },
  policyRule: { fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 },

  muted: { color: 'var(--muted)', fontSize: 12, textAlign: 'center', padding: 20 },
}
