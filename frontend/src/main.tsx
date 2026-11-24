import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter } from 'react-router-dom'
import './index.css'
import App from './App'
import { createQueryClient } from './api/queryClient'

const queryClient = createQueryClient()

async function start() {
  // npm run dev → 예시 데이터, npm run dev:api → 실제 백엔드. 배포 빌드에는 예시 데이터가 들어가지 않는다.
  if (import.meta.env.DEV && import.meta.env.MODE !== 'api') {
    const { worker } = await import('./mocks/browser')
    await worker.start({ onUnhandledFrame: 'bypass' })
  }
  createRoot(document.getElementById('root')!).render(
    <StrictMode>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </StrictMode>,
  )
}

start()
