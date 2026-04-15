import { useState } from 'react'
import { useKithSocket } from './hooks/useKithSocket'
import Sidebar from './components/Sidebar'
import SocietyGraph from './components/SocietyGraph'
import ResponsePanel from './components/ResponsePanel'

export default function App() {
  const { state, events, connected, activeAgents, activeLinks } = useKithSocket()
  const [selectedAgent, setSelectedAgent] = useState(null)
  const [lastResponse, setLastResponse] = useState(null)

  return (
    <>
      <Sidebar
        state={state}
        events={events}
        connected={connected}
        selectedAgent={selectedAgent}
        onSelectAgent={setSelectedAgent}
        onResponse={setLastResponse}
      />
      <main style={{ flex: 1, position: 'relative', overflow: 'hidden' }}>
        <SocietyGraph
          state={state}
          selectedAgent={selectedAgent}
          onSelectAgent={setSelectedAgent}
          activeAgents={activeAgents}
          activeLinks={activeLinks}
        />
        <ResponsePanel
          response={lastResponse}
          onClose={() => setLastResponse(null)}
        />
      </main>
    </>
  )
}
