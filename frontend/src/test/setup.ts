import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { resetDb } from '../mocks/handlers'
import { server } from '../mocks/server'

beforeAll(() => server.listen({ onUnhandledFrame: 'error' }))
afterEach(() => {
  cleanup()
  server.resetHandlers()
  resetDb()
})
afterAll(() => server.close())
