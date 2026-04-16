import { useState, useRef } from 'react'
import { useKithSocket } from './hooks/useKithSocket'
import { sendPrompt } from './api/client'
import Sidebar from './components/Sidebar'
import SocietyGraph from './components/SocietyGraph'
import ResponseSheet from './components/ResponseSheet'

export default function App() {
  const { state, events, connected, activeAgents, activeLinks } = useKithSocket()
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [lastResponse, setLastResponse] = useState(null)
  const [prompt, setPrompt] = useState('')
  const [sending, setSending] = useState(false)
  const inputRef = useRef(null)

  const handleSend = async () => {
    if (!prompt.trim() || sending) return
    setSending(true)
    try {
      const res = await sendPrompt(prompt.trim())
      setLastResponse(res)
      setPrompt('')
    } catch (e) {
      setLastResponse({ error: e.response?.data?.detail || e.message })
    }
    setSending(false)
  }

  return (
    <>
      <Sidebar
        state={state}
        events={events}
        connected={connected}
        selectedAgent={selectedAgent}
        onSelectAgent={setSelectedAgent}
      />
      <main style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <SocietyGraph
          state={state}
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
          activeAgents={activeAgents}
          activeLinks={activeLinks}
        />

        {/* Response — bottom sheet, above input */}
        <ResponseSheet
          response={lastResponse}
          onClose={() => setLastResponse(null)}
        />

        {/* Chat input — hidden when response is open */}
        {!lastResponse && (
          <div style={styles.inputBar}>
            <div style={styles.inputBox}>
              <textarea
                ref={inputRef}
                value={prompt}
                onChange={e => {
                  setPrompt(e.target.value)
                  const el = e.target
                  el.style.height = 'auto'
                  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
                }}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSend() } }}
                placeholder="Ask the society..."
                rows={1}
                style={styles.inputField}
                disabled={sending}
              />
              <button onClick={handleSend} disabled={sending || !prompt.trim()} style={styles.inputBtn}>
                {sending ? (
                  <span style={styles.spinner} />
                ) : (
                  <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                    <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
                  </svg>
                )}
              </button>
            </div>
          </div>
        )}
      </main>
    </>
  )
}

const styles = {
  inputBar: {
    position: 'absolute', bottom: 0, left: 0, right: 0,
    zIndex: 100, padding: '12px 24px',
  },
  inputBox: {
    display: 'flex', border: '1px solid var(--border)', borderRadius: 8,
    overflow: 'hidden', background: '#fff',
    boxShadow: '0 2px 16px rgba(0,0,0,0.08)',
    maxWidth: 800, margin: '0 auto',
  },
  inputField: {
    flex: 1, border: 'none', outline: 'none', resize: 'none',
    fontFamily: 'var(--font)', fontSize: 14, lineHeight: 1.5,
    padding: '12px 16px', background: 'transparent',
    minHeight: 44, maxHeight: 200, overflowY: 'auto',
  },
  inputBtn: {
    width: 48, border: 'none', borderLeft: '1px solid var(--border)',
    background: 'var(--fg)', color: 'var(--bg)', cursor: 'pointer',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    borderRadius: 0, transition: 'opacity 0.15s', flexShrink: 0,
  },
  spinner: {
    width: 14, height: 14, border: '2px solid rgba(255,255,255,0.3)',
    borderTopColor: '#fff', borderRadius: '50%',
    animation: 'spin 0.6s linear infinite', display: 'block',
  },
}
