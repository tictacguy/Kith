import Markdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

export default function ResponseSheet({ response, onClose }) {
  if (!response) return null

  return (
    <div style={s.sheet}>
      {/* Header */}
      <div style={s.header}>
        <span style={s.title}>Response</span>
        <button onClick={onClose} style={s.closeBtn}>Close</button>
      </div>

      {/* Content */}
      <div style={s.body}>
        {response.error ? (
          <div style={{ color: '#c00', fontSize: 13 }}>{response.error}</div>
        ) : (
          <>
            <div className="md-response" style={s.mdBody}>
              <Markdown remarkPlugins={[remarkGfm]}>{response.response}</Markdown>
            </div>

            <div style={s.meta}>
              <span style={s.metaItem}>{response.agents_used?.join(', ')}</span>
              <span style={s.metaDot} />
              <span style={s.metaItem}>{response.token_count} tokens</span>
              {response.themes?.length > 0 && (
                <>
                  <span style={s.metaDot} />
                  <span style={s.metaItem}>{response.themes.join(', ')}</span>
                </>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  )
}

const s = {
  sheet: {
    position: 'absolute',
    bottom: 0, left: 0, right: 0,
    maxHeight: 'calc(100% - 80px)',
    zIndex: 90,
    background: '#fff',
    borderTop: '1px solid var(--border)',
    boxShadow: '0 -4px 24px rgba(0,0,0,0.08)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
    padding: '12px 24px',
    borderBottom: '1px solid var(--border)',
    flexShrink: 0,
  },
  title: {
    fontSize: 11, fontWeight: 600, fontFamily: 'var(--mono)',
    textTransform: 'uppercase', letterSpacing: 1, color: 'var(--muted)',
  },
  closeBtn: {
    fontSize: 11, fontFamily: 'var(--mono)', padding: '4px 12px',
    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    background: '#fff', cursor: 'pointer', color: 'var(--fg)',
  },
  body: {
    flex: 1,
    overflow: 'auto',
    padding: '16px 24px 24px',
  },
  mdBody: {
    fontSize: 14,
    lineHeight: 1.7,
  },
  meta: {
    marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--border)',
    display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
    fontSize: 11, fontFamily: 'var(--mono)', color: 'var(--muted)',
  },
  metaItem: {},
  metaDot: {
    width: 3, height: 3, borderRadius: '50%', background: 'var(--border)', flexShrink: 0,
  },
}
