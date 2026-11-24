import { screen, within } from '@testing-library/react'
import App from './App'
import { renderWithProviders } from './test/render'

describe('App', () => {
  it('주 메뉴에는 문서에 있는 화면 3개만 있다', () => {
    renderWithProviders(<App />, { route: '/' })
    const nav = screen.getByRole('navigation', { name: '주 메뉴' })
    expect(within(nav).getAllByRole('link').map((l) => l.textContent)).toEqual(['대시보드', '상담 목록', '업로드·처리 상태'])
    expect(nav).not.toHaveTextContent('챗봇')
  })

  it('없는 주소는 404 화면', () => {
    renderWithProviders(<App />, { route: '/nope' })
    expect(screen.getByText('페이지를 찾을 수 없어요')).toBeInTheDocument()
  })
})
