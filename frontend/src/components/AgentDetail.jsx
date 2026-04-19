import { useState, useEffect } from 'react'
import { fetchRecentInteractions, setAgentStatus, reassignRole, renameAgent } from '../api/client'

export default function AgentDetail({ agent: agentProp, state, onBack }) {
  // Always read the live version from state — prop is just the initial selection
  const agent = state?.agents?.find(a => a.id === agentProp.id) || agentProp

  const [interactions, setInteractions] = useState([])
  const [loading, setLoading] = useState(true)
  const [editingName, setEditingName] = useState(false)
  const [nameValue, setNameValue] = useState(agent.name)

  // Sync nameValue when agent updates from WS
  useEffect(() => { if (!editingName) setNameValue(agent.name) }, [agent.name, editingName])

  useEffect(() => {
    setLoading(true)
    fetchRecentInteractions(50).then(data => {
      setInteractions(data.filter(i => i.agents?.includes(agent.id)))
      setLoading(false)
    }).catch(() => setLoading(false))
  }, [agent.id])

  const agents = state?.agents || []
  const roles = state?.roles || []
  const supervisor = agent.supervisor_id ? agents.find(a => a.id === agent.supervisor_id) : null
  const subordinates = agents.filter(a => a.supervisor_id === agent.id)

  const handleRename = async () => {
    if (nameValue.trim() && nameValue.trim() !== agent.name) {
      await renameAgent(agent.id, nameValue.trim())
    }
    setEditingName(false)
  }

  const handleStatusToggle = async () => {
    await setAgentStatus(agent.id, agent.status === 'active' ? 'dormant' : 'active')
  }

  const handleRoleChange = async (roleId) => {
    if (roleId && roleId !== agent.role_id) {
      await reassignRole(agent.id, roleId)
    }
  }

  return (
    <div style={s.container}>
      {/* Sticky header */}
      <div style={s.stickyHeader}>
        <button onClick={onBack} style={s.backBtn}>Back</button>
        <div style={s.headerContent}>
          {editingName ? (
            <div style={s.nameEditRow}>
              <input value={nameValue} onChange={e => setNameValue(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') handleRename(); if (e.key === 'Escape') setEditingName(false) }}
                autoFocus style={s.nameInput} />
              <button onClick={handleRename} style={s.smallBtn}>Save</button>
            </div>
          ) : (
            <div style={s.name} onClick={() => { setEditingName(true); setNameValue(agent.name) }}>
              {agent.name}
              <span style={s.editHint}>click to rename</span>
            </div>
          )}
        </div>
      </div>

      {/* Scrollable body */}
      <div style={s.body}>
        {/* Info section — vertical layout */}
        <div style={s.section}>
          <Field label="Role">
            <div style={s.roleSelector}>
              {roles.map(r => (
                <button key={r.id} onClick={() => handleRoleChange(r.id)}
                  style={{ ...s.roleBtn, ...(agent.role_id === r.id ? s.roleBtnActive : {}) }}>
                  {r.name}
                </button>
              ))}
            </div>
          </Field>
          <Field label="Status">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={s.fieldValue}>{agent.status}</span>
              <button onClick={handleStatusToggle} style={s.smallBtn}>
                {agent.status === 'active' ? 'Set dormant' : 'Activate'}
              </button>
            </div>
          </Field>
          <Field label="Interactions">
            <span style={s.fieldValue}>{agent.interaction_count}</span>
          </Field>
          {agent.expertise?.length > 0 && (
            <Field label="Expertise">
              <span style={s.fieldValue}>{agent.expertise.join(', ')}</span>
            </Field>
          )}
          {agent.thematic_profile && Object.keys(agent.thematic_profile).length > 0 && (
            <Field label="Thematic Affinity">
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                {Object.entries(agent.thematic_profile).map(([theme, score]) => (
                  <span key={theme} style={{
                    fontSize: 10, padding: '2px 6px', borderRadius: 8,
                    background: `rgba(0,100,200,${0.08 + score * 0.2})`,
                    color: 'var(--fg)',
                  }}>{theme} {(score * 100).toFixed(0)}%</span>
                ))}
              </div>
            </Field>
          )}
          {(agent.consecutive_activations >= 3 || agent.inherited_legacy) && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
              {agent.consecutive_activations >= 3 && (
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 8,
                  background: 'rgba(200,100,0,0.12)', color: '#a06000',
                }}>◔ cooldown ({agent.consecutive_activations} in a row)</span>
              )}
              {agent.inherited_legacy && (
                <span style={{
                  fontSize: 10, padding: '2px 8px', borderRadius: 8,
                  background: 'rgba(100,0,200,0.08)', color: '#6000a0',
                }}>◇ carries legacy</span>
              )}
            </div>
          )}
        </div>
        <div style={s.section}>
          <div style={s.sectionTitle}>Reputation</div>
          <div style={s.repBar}>
            <div style={{ ...s.repFill, width: `${(agent.reputation || 0.5) * 100}%` }} />
          </div>
          <div style={s.repScore}>{((agent.reputation || 0.5) * 100).toFixed(0)}%</div>
          <div style={s.repGrid}>
            <RepStat label="approved" value={agent.approved_count || 0} />
            <RepStat label="vetoed" value={agent.vetoed_count || 0} />
            <RepStat label="debates won" value={agent.debates_won || 0} />
            <RepStat label="debates lost" value={agent.debates_lost || 0} />
            <RepStat label="delegations" value={agent.delegations_received || 0} />
          </div>
          {!(agent.approved_count || agent.vetoed_count || agent.debates_won || agent.debates_lost || agent.delegations_received) && (
            <div style={{ fontSize: 10, color: 'var(--muted)', marginTop: 6 }}>
              Counters update as the society evolves and agents participate in supervision, debates, and delegations.
            </div>
          )}
          {/* Reputation log */}
          {agent.reputation_log?.length > 0 && (
            <div style={{ marginTop: 12 }}>
              <div style={s.sectionTitle}>History</div>
              {agent.reputation_log.slice().reverse().map((ev, i) => (
                <div key={i} style={s.repLogRow}>
                  <span style={s.repLogType}>{ev.type}</span>
                  <span style={s.repLogDetail}>{ev.detail}</span>
                  <span style={s.repLogScore}>{(ev.reputation_after * 100).toFixed(0)}%</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Hierarchy */}
        {(supervisor || subordinates.length > 0) && (
          <div style={s.section}>
            <div style={s.sectionTitle}>Hierarchy</div>
            {supervisor && (
              <Field label="Reports to">
                <span style={s.fieldValue}>{supervisor.name} ({supervisor.role})</span>
              </Field>
            )}
            {subordinates.length > 0 && (
              <Field label="Supervises">
                <span style={s.fieldValue}>{subordinates.map(a => a.name).join(', ')}</span>
              </Field>
            )}
          </div>
        )}

        {/* Memory */}
        <div style={s.section}>
          <div style={s.sectionTitle}>Memory</div>
          {agent.memory_summary ? (
            <div style={s.memoryBlock}>{agent.memory_summary}</div>
          ) : (
            <div style={s.muted}>No memories yet</div>
          )}
        </div>

        {/* History */}
        <div style={s.section}>
          <div style={s.sectionTitle}>History ({interactions.length})</div>
          {loading && <div style={s.muted}>Loading...</div>}
          {!loading && interactions.length === 0 && <div style={s.muted}>No interactions yet</div>}
          <div style={s.historyList}>
            {interactions.map(i => (
              <div key={i.id} style={s.historyItem}>
                <div style={s.historyPrompt}>{i.prompt}</div>
                <div style={s.historyResponse}>{i.response?.slice(0, 120)}</div>
                <div style={s.historyMeta}>{i.tokens} tokens / {i.themes?.join(', ')}</div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

function Field({ label, children }) {
  return (
    <div style={s.field}>
      <div style={s.fieldLabel}>{label}</div>
      <div style={s.fieldContent}>{children}</div>
    </div>
  )
}

function RepStat({ label, value }) {
  return (
    <div style={s.repStat}>
      <span style={s.repStatValue}>{value}</span>
      <span style={s.repStatLabel}>{label}</span>
    </div>
  )
}

const s = {
  container: { display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' },

  // Sticky header
  stickyHeader: {
    flexShrink: 0, borderBottom: '1px solid var(--border)', background: 'var(--bg)',
    zIndex: 10, padding: '12px 16px',
  },
  backBtn: { fontSize: 11, fontFamily: 'var(--mono)', padding: '4px 12px', marginBottom: 8 },
  headerContent: {},
  name: {
    fontSize: 18, fontWeight: 600, fontFamily: 'var(--mono)', cursor: 'pointer',
    display: 'flex', alignItems: 'baseline', gap: 8,
  },
  editHint: { fontSize: 10, color: 'var(--muted)', fontWeight: 400 },
  nameEditRow: { display: 'flex', gap: 8, alignItems: 'center' },
  nameInput: { fontSize: 16, fontWeight: 600, fontFamily: 'var(--mono)', flex: 1, padding: '4px 8px' },

  // Scrollable body
  body: { flex: 1, overflow: 'auto' },

  // Sections
  section: { padding: '14px 16px', borderBottom: '1px solid var(--border)' },
  sectionTitle: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 10 },

  // Vertical field layout — label on top, value below
  field: { marginBottom: 12 },
  fieldLabel: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 4 },
  fieldContent: { fontSize: 12 },
  fieldValue: { color: 'var(--fg)' },

  // Role selector
  roleSelector: { display: 'flex', flexWrap: 'wrap', gap: 4 },
  roleBtn: {
    fontSize: 10, fontFamily: 'var(--mono)', padding: '4px 10px',
    border: '1px solid var(--border)', borderRadius: 3, background: 'var(--bg)',
    color: 'var(--muted)', cursor: 'pointer', transition: 'all 0.15s',
  },
  roleBtnActive: { background: 'var(--fg)', color: 'var(--bg)', borderColor: 'var(--fg)' },

  smallBtn: { fontSize: 10, padding: '3px 10px', fontFamily: 'var(--mono)' },

  // Reputation
  repBar: { height: 4, background: 'var(--border)', borderRadius: 2, overflow: 'hidden', marginBottom: 4 },
  repFill: { height: '100%', background: 'var(--fg)', borderRadius: 2, transition: 'width 0.3s' },
  repScore: { fontSize: 11, fontFamily: 'var(--mono)', fontWeight: 600, marginBottom: 8 },
  repGrid: { display: 'flex', flexWrap: 'wrap', gap: 12 },
  repStat: { fontSize: 10, fontFamily: 'var(--mono)' },
  repStatValue: { color: 'var(--fg)', fontWeight: 600 },
  repStatLabel: { color: 'var(--muted)', marginLeft: 6 },
  repLogRow: { display: 'flex', gap: 8, fontSize: 10, fontFamily: 'var(--mono)', padding: '3px 0', borderBottom: '1px solid var(--border)' },
  repLogType: { color: 'var(--fg)', fontWeight: 500, minWidth: 70 },
  repLogDetail: { color: 'var(--muted)', flex: 1 },
  repLogScore: { color: 'var(--fg)', fontWeight: 600, minWidth: 30, textAlign: 'right' },

  // Memory
  memoryBlock: {
    fontSize: 11, fontFamily: 'var(--mono)', lineHeight: 1.6, color: 'var(--fg)',
    whiteSpace: 'pre-wrap', padding: 10, background: 'var(--surface)',
    borderRadius: 'var(--radius)', border: '1px solid var(--border)',
  },

  // History
  historyList: { display: 'flex', flexDirection: 'column', gap: 6 },
  historyItem: { padding: 10, borderRadius: 'var(--radius)', border: '1px solid var(--border)' },
  historyPrompt: { fontWeight: 600, fontSize: 12, marginBottom: 4 },
  historyResponse: { fontSize: 11, color: 'var(--muted)', lineHeight: 1.5 },
  historyMeta: { fontSize: 10, color: 'var(--muted)', fontFamily: 'var(--mono)', marginTop: 4 },

  muted: { color: 'var(--muted)', fontSize: 11 },
}
