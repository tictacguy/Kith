import { useState, useEffect } from 'react'
import { fetchLLMConfig, setLLMConfig, resetSociety } from '../api/client'

const PROVIDERS = [
  { id: 'openai', label: 'OpenAI', icon: '/openai.svg' },
  { id: 'anthropic', label: 'Anthropic', icon: '/anthropic.svg' },
  { id: 'bedrock', label: 'Bedrock', icon: '/aws.svg' },
  { id: 'ollama', label: 'Ollama', icon: '/ollama.png' },
]

export default function ConfigPanel() {
  const [cfg, setCfg] = useState(null)
  const [form, setForm] = useState({ backend: '', model: '', api_key: '', aws_token: '', aws_region: '', ollama_url: '', max_tokens: '' })
  const [saving, setSaving] = useState(false)
  const [msg, setMsg] = useState('')
  const [resetting, setResetting] = useState(false)
  const [confirmReset, setConfirmReset] = useState(false)

  useEffect(() => {
    fetchLLMConfig().then(data => {
      setCfg(data)
      setForm({
        backend: data.backend,
        model: data.model,
        api_key: '',
        aws_token: '',
        aws_region: data.aws_region || '',
        ollama_url: data.ollama_base_url || '',
        max_tokens: String(data.max_tokens || 1024),
      })
    }).catch(() => {})
  }, [])

  const handleSave = async () => {
    setSaving(true)
    setMsg('')
    try {
      const payload = { backend: form.backend }
      if (form.model) payload.model = form.model
      if (form.max_tokens) payload.max_tokens = parseInt(form.max_tokens)
      if (form.api_key) payload.api_key = form.api_key
      if (form.aws_token) payload.aws_token = form.aws_token
      if (form.aws_region) payload.aws_region = form.aws_region
      if (form.ollama_url) payload.ollama_url = form.ollama_url
      const res = await setLLMConfig(payload)
      setMsg(`Saved: ${res.backend} / ${res.model}`)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Error saving')
    }
    setSaving(false)
  }

  const handleReset = async () => {
    if (!confirmReset) {
      setConfirmReset(true)
      return
    }
    setResetting(true)
    try {
      await resetSociety()
      setMsg('Society reset to primitive')
      setConfirmReset(false)
    } catch (e) {
      setMsg(e.response?.data?.detail || 'Reset failed')
    }
    setResetting(false)
  }

  const update = (k, v) => setForm(f => ({ ...f, [k]: v }))

  if (!cfg) return <div style={s.muted}>Loading configuration...</div>

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* LLM Provider */}
      <div>
        <div style={s.sectionTitle}>LLM Provider</div>
        <div style={s.providerGrid}>
          {PROVIDERS.map(p => (
            <button key={p.id} onClick={() => update('backend', p.id)}
              style={{ ...s.providerBtn, ...(form.backend === p.id ? s.providerBtnActive : {}) }}>
              <img src={p.icon} alt={p.label} style={s.providerIcon} />
              <span>{p.label}</span>
            </button>
          ))}
        </div>
      </div>

      <Field label="Model" value={form.model} onChange={v => update('model', v)} placeholder="e.g. gpt-4o, claude-3-5-haiku" />
      <Field label="Max tokens" value={form.max_tokens} onChange={v => update('max_tokens', v)} type="number" />

      {(form.backend === 'openai' || form.backend === 'anthropic') && (
        <Field label="API Key" value={form.api_key} onChange={v => update('api_key', v)} type="password"
          placeholder={cfg[`${form.backend}_key_set`] ? '(set)' : 'Enter key'} />
      )}
      {form.backend === 'bedrock' && (
        <>
          <Field label="Bearer token" value={form.aws_token} onChange={v => update('aws_token', v)} type="password"
            placeholder={cfg.bedrock_token_set ? '(set)' : 'Enter token'} />
          <Field label="Region" value={form.aws_region} onChange={v => update('aws_region', v)} />
        </>
      )}
      {form.backend === 'ollama' && (
        <Field label="Base URL" value={form.ollama_url} onChange={v => update('ollama_url', v)} placeholder="http://localhost:11434/v1" />
      )}

      <button onClick={handleSave} disabled={saving} style={s.saveBtn}>
        {saving ? 'Saving...' : 'Save LLM configuration'}
      </button>

      {/* Society settings */}
      <div style={{ borderTop: '1px solid var(--border)', paddingTop: 16 }}>
        <div style={s.sectionTitle}>Society</div>

        <div style={{ marginTop: 12 }}>
          <div style={s.dangerLabel}>Reset society</div>
          <div style={{ fontSize: 11, color: 'var(--muted)', marginBottom: 8 }}>
            Deletes all interactions, agent memories, tools, and policies. Starts fresh with a primitive society.
          </div>
          <button onClick={handleReset} disabled={resetting}
            style={{ ...s.dangerBtn, ...(confirmReset ? s.dangerBtnConfirm : {}) }}>
            {resetting ? 'Resetting...' : confirmReset ? 'Confirm reset' : 'Reset society'}
          </button>
          {confirmReset && !resetting && (
            <button onClick={() => setConfirmReset(false)} style={{ ...s.cancelBtn, marginLeft: 8 }}>Cancel</button>
          )}
        </div>
      </div>

      {msg && (
        <div style={{ fontSize: 11, fontFamily: 'var(--mono)', color: msg.startsWith('Error') || msg.startsWith('Reset failed') ? '#c00' : 'var(--fg)' }}>
          {msg}
        </div>
      )}
    </div>
  )
}

function Field({ label, value, onChange, type = 'text', placeholder = '' }) {
  return (
    <div>
      <div style={s.fieldLabel}>{label}</div>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder} />
    </div>
  )
}

const s = {
  sectionTitle: { fontSize: 9, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 8 },
  fieldLabel: { fontSize: 10, textTransform: 'uppercase', letterSpacing: 0.5, color: 'var(--muted)', marginBottom: 4 },
  providerGrid: { display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 },
  providerBtn: {
    padding: '10px 0', fontSize: 11, fontFamily: 'var(--mono)',
    display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 6,
  },
  providerBtnActive: { background: 'var(--fg)', color: 'var(--bg)', borderColor: 'var(--fg)' },
  providerIcon: { height: 16, width: 16, objectFit: 'contain' },
  saveBtn: { padding: '10px 0', fontWeight: 600, fontSize: 12 },
  dangerLabel: { fontSize: 12, fontWeight: 600, marginBottom: 4 },
  dangerBtn: { padding: '8px 16px', fontSize: 11, fontFamily: 'var(--mono)', borderColor: '#c00', color: '#c00' },
  dangerBtnConfirm: { background: '#c00', color: '#fff', borderColor: '#c00' },
  cancelBtn: { padding: '8px 16px', fontSize: 11, fontFamily: 'var(--mono)' },
  muted: { color: 'var(--muted)', fontSize: 12 },
}
