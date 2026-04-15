import { useEffect, useRef, useCallback, useState } from 'react'

export function useKithSocket() {
  const [state, setState] = useState(null)       // full society snapshot
  const [events, setEvents] = useState([])        // live event log (last 50)
  const [connected, setConnected] = useState(false)
  const [activeAgents, setActiveAgents] = useState(new Set())  // agents currently thinking
  const [activeLinks, setActiveLinks] = useState([])           // {from, to, type} during processing
  const wsRef = useRef(null)
  const reconnectRef = useRef(null)

  const connect = useCallback(() => {
    const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
    const host = window.location.host
    const ws = new WebSocket(`${proto}://${host}/ws`)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => {
      setConnected(false)
      reconnectRef.current = setTimeout(connect, 2000)
    }
    ws.onerror = () => ws.close()

    ws.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      const { type, data } = msg

      // Append to event log (skip state snapshots — not user-visible activity)
      if (type !== 'society_state') {
        setEvents(prev => [msg, ...prev].slice(0, 50))
      }

      switch (type) {
        case 'society_state':
          setState(data)
          break

        case 'processing_start':
          setActiveAgents(new Set())
          setActiveLinks([])
          break

        case 'processing_end':
          // Clear after short delay so user sees final state
          setTimeout(() => {
            setActiveAgents(new Set())
            setActiveLinks([])
          }, 1500)
          break

        case 'agent_bidding':
          setActiveAgents(prev => new Set([...prev, data.agent_id]))
          break

        case 'mobilization_end':
          setActiveAgents(new Set())
          break

        case 'agent_thinking':
          setActiveAgents(prev => new Set([...prev, data.agent_id]))
          break

        case 'agent_responded':
          setActiveAgents(prev => {
            const next = new Set(prev)
            next.delete(data.agent_id)
            return next
          })
          break

        // Deliberation
        case 'deliberation_start':
          setActiveLinks([])
          break

        case 'agent_deliberating':
          setActiveAgents(prev => new Set([...prev, data.agent_id]))
          // Show links from this agent to all agents it's reading
          if (data.reading_from) {
            setActiveLinks(prev => [
              ...prev,
              ...data.reading_from.map(to => ({ from: data.agent_id, to, type: 'deliberating' }))
            ])
          }
          break

        case 'agent_deliberated':
          setActiveAgents(prev => {
            const next = new Set(prev)
            next.delete(data.agent_id)
            return next
          })
          setActiveLinks(prev => prev.filter(l => l.from !== data.agent_id || l.type !== 'deliberating'))
          break

        // Delegation
        case 'agent_delegating':
          setActiveLinks(prev => [...prev, { from: data.from_id, to: data.to_id, type: 'delegating' }])
          setActiveAgents(prev => new Set([...prev, data.to_id]))
          break

        case 'agent_delegated':
          setActiveAgents(prev => {
            const next = new Set(prev)
            next.delete(data.to_id)
            return next
          })
          setActiveLinks(prev => prev.filter(l => !(l.from === data.from_id && l.to === data.to_id && l.type === 'delegating')))
          break

        // Debate
        case 'debate_start':
          break

        case 'agent_debating':
          setActiveAgents(prev => new Set([...prev, data.agent_id]))
          break

        case 'debate_mediated':
          break

        case 'debate_end':
          break

        // Consensus
        case 'agent_voting':
          setActiveAgents(prev => new Set([...prev, data.agent_id]))
          break

        case 'agent_voted':
          setActiveAgents(prev => {
            const next = new Set(prev)
            next.delete(data.agent_id)
            return next
          })
          break

        case 'consensus_end':
          setActiveLinks([])
          break

        case 'agent_supervising':
          setActiveLinks(prev => [...prev, {
            from: data.supervisor_id,
            to: data.subordinate_id,
            type: 'supervising',
          }])
          setActiveAgents(prev => new Set([...prev, data.supervisor_id]))
          break

        case 'agent_verdict':
          setActiveAgents(prev => {
            const next = new Set(prev)
            next.delete(data.supervisor_id)
            return next
          })
          break

        case 'synthesis_start':
          if (data.agent_ids?.length) {
            // Show links between all participating agents
            const ids = data.agent_ids
            for (let i = 0; i < ids.length; i++) {
              for (let j = i + 1; j < ids.length; j++) {
                setActiveLinks(prev => [...prev, { from: ids[i], to: ids[j], type: 'synthesis' }])
              }
            }
          }
          break

        case 'synthesis_end':
          setActiveLinks(prev => prev.filter(l => l.type !== 'synthesis'))
          break
      }
    }
  }, [])

  useEffect(() => {
    connect()
    return () => {
      clearTimeout(reconnectRef.current)
      wsRef.current?.close()
    }
  }, [connect])

  return { state, events, connected, activeAgents, activeLinks }
}
