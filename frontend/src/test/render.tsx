import type { ReactElement } from 'react'
import { render, type RenderResult } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { MemoryRouter } from 'react-router-dom'
import { LocationProbe } from './LocationProbe'

export function renderWithProviders(ui: ReactElement, opts: { route?: string } = {}): RenderResult {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[opts.route ?? '/']}>
        {ui}
        <LocationProbe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}
