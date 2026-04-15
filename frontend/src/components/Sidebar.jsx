import { useState, useRef, useEffect } from 'react'
import { sendPrompt } from '../api/client'
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
}

export default function Sidebar({ state, events, connected, selectedAgent, onSelectAgent, onResponse }) {
  const [prompt, setPrompt] = useState('')
  const [sending, setSending] = useState(false)
  const [tab, setTab] = useState('console')

  const handleSend = async () => {
    if (!prompt.trim() || sending) return
    setSending(true)
    try {
      const res = await sendPrompt(prompt.trim())
      onResponse(res)
      setPrompt('')
    } catch (e) {
      onResponse({ error: e.response?.data?.detail || e.message })
    }
    setSending(false)
  }

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
        {/* <span style={{ ...s.dot, background: connected ? '#000' : '#ccc' }} /> */}
        {state && <span style={s.stage}>{state.stage}</span>}
      </div>

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
        {['console', 'entities', 'memory', 'config'].map(t => (
          <button key={t} onClick={() => setTab(t)}
            style={{ ...s.tab, ...(tab === t ? s.tabActive : {}) }}>
            {t}
          </button>
        ))}
      </div>

      {/* Content */}
      <div style={s.content}>
        {tab === 'console' && <ConsoleTab events={events} prompt={prompt} setPrompt={setPrompt} sending={sending} onSend={handleSend} />}
        {tab === 'entities' && <EntitiesTab agents={agents} tools={tools} onSelectAgent={onSelectAgent} />}
        {tab === 'memory' && <MemoryTab state={state} />}
        {tab === 'config' && <div style={s.scrollable}><ConfigPanel /></div>}
      </div>
    </aside>
  )
}

// ---------------------------------------------------------------------------
// Console — live event feed only (prompt moved above tabs)
// ---------------------------------------------------------------------------
function ConsoleTab({ events, prompt, setPrompt, sending, onSend }) {
  const liveRef = useRef(null)
  useEffect(() => { if (liveRef.current) liveRef.current.scrollTop = 0 }, [events])

  return (
    <div style={s.consoleLayout}>
      {/* Prompt input */}
      <div style={s.promptArea}>
        <div style={s.promptBox}>
          <textarea
            value={prompt}
            onChange={e => setPrompt(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); onSend() } }}
            placeholder="Ask the society something..."
            rows={2}
            style={s.promptInput}
            disabled={sending}
          />
          <button onClick={onSend} disabled={sending || !prompt.trim()} style={s.promptBtn}>
            {sending ? (
              <span style={s.spinner} />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
      </div>

      {/* Live feed */}
      <div style={s.liveContainer}>
        <div ref={liveRef} style={s.liveFeed}>
          {events.length === 0 && <div style={s.muted}>waiting for activity...</div>}
          {events.map((e, i) => {
            const label = EVENT_LABELS[e.type] || e.type
            const detail = e.data?.agent_name || e.data?.tool_name || e.data?.prompt?.slice(0, 40) || e.data?.vote || ''
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
function EntitiesTab({ agents, tools, onSelectAgent }) {
  return (
    <div style={s.scrollable}>
      {/* Agents */}
      {agents.length > 0 && (
        <>
          <div style={s.entityGroupLabel}>Agents</div>
          {agents.map(a => (
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
          ))}
        </>
      )}

      {/* Tools */}
      {tools.length > 0 && (
        <>
          <div style={{ ...s.entityGroupLabel, marginTop: 16 }}>Tools</div>
          {tools.map(t => (
            <div key={t.id} style={s.entityRow}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={s.entityName}>{t.name}</span>
                <span style={{ ...s.entityBadge, fontSize: 9 }}>tool</span>
              </div>
              <div style={s.entityMeta}>{t.description}</div>
              <div style={{ fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--mono)', marginTop: 2 }}>
                used {t.usage_count} times
              </div>
            </div>
          ))}
        </>
      )}

      {agents.length === 0 && tools.length === 0 && (
        <div style={s.muted}>no entities yet</div>
      )}
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
            <div style={s.policyName}>{p.name}</div>
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
  },
  header: {
    padding: '16px 16px 12px', display: 'flex', alignItems: 'center',
    gap: 8, borderBottom: '1px solid var(--border)', flexShrink: 0,
  },
  logo: { height: 20 },
  dot: { width: 6, height: 6, borderRadius: '50%', flexShrink: 0 },
  stage: { fontFamily: 'var(--mono)', fontSize: 11, color: 'var(--muted)', marginLeft: 'auto', textTransform: 'uppercase', letterSpacing: 1 },
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
