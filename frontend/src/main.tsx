import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { App } from './App'
import { StoreProvider } from './state/store'
import './styles/tokens.css'
import './styles/base.css'
import './styles/landing.css'

const container = document.getElementById('root')
if (!container) throw new Error('#root is missing from index.html')

createRoot(container).render(
  <StrictMode>
    <StoreProvider>
      <App />
    </StoreProvider>
  </StrictMode>,
)
