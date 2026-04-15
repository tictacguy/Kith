import axios from 'axios'

const api = axios.create({ baseURL: '/api/v1' })

export const fetchSociety = () => api.get('/society').then(r => r.data)
export const fetchAgents = () => api.get('/agents').then(r => r.data)
export const fetchRoles = () => api.get('/roles').then(r => r.data)
export const fetchTools = () => api.get('/tools').then(r => r.data)
export const fetchPolicies = () => api.get('/policies').then(r => r.data)
export const fetchRecentInteractions = (n = 10) => api.get(`/interactions/recent?n=${n}`).then(r => r.data)
export const fetchSupervision = () => api.get('/supervision/last').then(r => r.data)
export const fetchLLMConfig = () => api.get('/config/llm').then(r => r.data)

export const sendPrompt = (prompt) => api.post('/prompt', { prompt }).then(r => r.data)
export const setLLMConfig = (cfg) => api.put('/config/llm', cfg).then(r => r.data)
export const setAgentStatus = (id, status) => api.patch(`/agents/${id}/status`, { status }).then(r => r.data)
export const reassignRole = (id, role_id) => api.patch(`/agents/${id}/role`, { role_id }).then(r => r.data)
export const renameAgent = (id, name) => api.patch(`/agents/${id}/name`, { name }).then(r => r.data)
export const updatePolicy = (id, data) => api.patch(`/policies/${id}`, data).then(r => r.data)
export const addPolicy = (data) => api.post('/policies', data).then(r => r.data)
export const proposeTools = () => api.post('/tools/propose').then(r => r.data)
export const registerTool = (data) => api.post('/tools/register', data).then(r => r.data)
export const forceEvolve = () => api.post('/society/evolve').then(r => r.data)
export const resetSociety = () => api.post('/society/reset').then(r => r.data)
