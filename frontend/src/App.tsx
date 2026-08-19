import type { ReactElement } from 'react'

import { Sidebar } from './components/Sidebar'
import { SourcePanel } from './components/SourcePanel'
import { Toasts } from './components/Toasts'
import { ClusterScreen } from './screens/ClusterScreen'
import { EditsScreen } from './screens/EditsScreen'
import { FollowupScreen } from './screens/FollowupScreen'
import { HistoryScreen } from './screens/HistoryScreen'
import { PapersScreen } from './screens/PapersScreen'
import { PrintScreen } from './screens/PrintScreen'
import { QueryScreen } from './screens/QueryScreen'
import { ReportScreen } from './screens/ReportScreen'
import { RunScreen } from './screens/RunScreen'
import { StatesScreen } from './screens/StatesScreen'
import { useStore } from './state/store'

export function App(): ReactElement {
  const store = useStore()

  return (
    <div className="shell">
      <Sidebar />
      <main className="main">
        {store.screen === 'query' ? <QueryScreen /> : null}
        {store.screen === 'run' ? <RunScreen /> : null}
        {store.screen === 'report' ? <ReportScreen /> : null}
        {store.screen === 'cluster' ? <ClusterScreen /> : null}
        {store.screen === 'papers' ? <PapersScreen /> : null}
        {store.screen === 'edits' ? <EditsScreen /> : null}
        {store.screen === 'followup' ? <FollowupScreen /> : null}
        {store.screen === 'history' ? <HistoryScreen /> : null}
        {store.screen === 'states' ? <StatesScreen /> : null}
        {store.screen === 'print' ? <PrintScreen /> : null}
      </main>

      {store.sourceClaimId ? (
        <SourcePanel source={store.source} claimRef={store.sourceRef} onClose={store.closeSource} />
      ) : null}

      {/* App-level: a gap is a fact about the socket, not about the run screen,
          and it can be detected while the report or a cluster is open. */}
      <Toasts />
    </div>
  )
}
