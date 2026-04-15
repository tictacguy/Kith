import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function ResponsePanel({ response, onClose }) {
  if (!response) return null

  return (
    <div style={s.overlay}>
      <div style={s.panel}>
        {/* Header */}
        <div style={s.header}>
          <span style={s.title}>Response</span>
          <button onClick={onClose} style={s.closeBtn}>Close</button>
        </div>

        {/* Body — no scroll, full content visible */}
        <div style={s.body}>
          {response.error ? (
            <div style={{ color: '#c00', fontSize: 13 }}>{response.error}</div>
          ) : (
            <>
              <div className="md-response" style={s.mdBody}>
                <Markdown remarkPlugins={[remarkGfm]}>{response.response}</Markdown>
              </div>

              {/* Meta */}
              <div style={s.meta}>
                <div style={s.metaRow}>
                  <span style={s.metaLabel}>Agents</span>
                  <span style={s.metaValue}>{response.agents_used?.join(', ')}</span>
                </div>
                <div style={s.metaRow}>
                  <span style={s.metaLabel}>Tokens</span>
                  <span style={s.metaValue}>{response.token_count}</span>
                </div>
                {response.themes?.length > 0 && (
                  <div style={s.metaRow}>
                    <span style={s.metaLabel}>Themes</span>
                    <span style={s.metaValue}>{response.themes.join(', ')}</span>
                  </div>
                )}
                <div style={s.metaRow}>
                  <span style={s.metaLabel}>Stage</span>
                  <span style={s.metaValue}>{response.society_stage}</span>
                </div>
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

const s = {
  overlay: {
    position: 'absolute',
    top: 0, right: 0, bottom: 0,
    zIndex: 50,
    display: 'flex',
    justifyContent: 'flex-end',
    pointerEvents: 'none',
  },
  panel: {
    width: 'fit-content',
    minWidth: 360,
    maxWidth: '60vw',
    height: '100%',
    background: '#fff',
    borderLeft: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    boxShadow: '-4px 0 24px rgba(0,0,0,0.06)',
    pointerEvents: 'auto',
  },
  header: {
    padding: '14px 20px',
    borderBottom: '1px solid var(--border)',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    flexShrink: 0,
  },
  title: {
    fontSize: 12, fontWeight: 600, fontFamily: 'var(--mono)',
    textTransform: 'uppercase', letterSpacing: 1,
  },
  closeBtn: { fontSize: 11, fontFamily: 'var(--mono)', padding: '4px 12px' },
  body: {
    flex: 1,
    overflow: 'auto',
    padding: 20,
  },
  mdBody: { fontSize: 14, lineHeight: 1.7 },
  meta: {
    marginTop: 24, paddingTop: 16, borderTop: '1px solid var(--border)',
    display: 'flex', flexDirection: 'column', gap: 6,
  },
  metaRow: { display: 'flex', gap: 12, fontSize: 11 },
  metaLabel: {
    color: 'var(--muted)', minWidth: 60, fontFamily: 'var(--mono)',
    textTransform: 'uppercase', letterSpacing: 0.5, fontSize: 9,
  },
  metaValue: { color: 'var(--fg)', fontFamily: 'var(--mono)', fontSize: 11 },
}
