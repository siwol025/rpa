import { cleanup, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import App from '../App'
import { MOCK_CALLS } from '../mocks/data'
import { server } from '../mocks/server'
import { renderWithProviders } from '../test/render'

const bodyRows = () => screen.getAllByRole('row').slice(1)
const location = () => decodeURIComponent(screen.getByTestId('location').textContent ?? '').replaceAll('+', ' ')
const count = () => screen.getByLabelText('검색 결과 수')

async function openList(route = '/calls') {
  renderWithProviders(<App />, { route })
  await waitFor(() => expect(count()).toHaveTextContent(/^\d+건$/))
}

describe('상담 목록', () => {
  it('열과 전체 건수를 보여주고 최신 상담이 맨 위', async () => {
    await openList()
    expect(screen.getAllByRole('columnheader').map((h) => h.textContent)).toEqual([
      '통화 일시', '담당자', '고객사', '유형', '질문 요약', '통화 시간', '조치 상태', '처리 상태',
    ])
    expect(count()).toHaveTextContent(`${MOCK_CALLS.length}건`)
    expect(within(bodyRows()[0]).getByText('11/24 09:50')).toBeInTheDocument()
  })

  it('유형을 고르면 그 유형만 보이고 주소에 남는다', async () => {
    await openList()
    await userEvent.selectOptions(screen.getByLabelText('유형'), '교육 내용')
    await waitFor(() => expect(location()).toBe('/calls?category=EDUCATION'))
    await waitFor(() => expect(bodyRows()).toHaveLength(3))
    for (const r of bodyRows()) expect(within(r).getByText('교육 내용')).toBeInTheDocument()
  })

  it('담당자·고객사 선택지를 통계 API에서 가져온다', async () => {
    await openList()
    await within(screen.getByLabelText('담당자')).findByRole('option', { name: '이상담' })
    await within(screen.getByLabelText('고객사')).findByRole('option', { name: 'E건설' })
  })

  it('메타데이터 확인 필요와 정체로 거른다', async () => {
    await openList()
    await userEvent.click(screen.getByLabelText('메타데이터 확인 필요'))
    await waitFor(() => expect(location()).toBe('/calls?metadata_incomplete=true'))
    await waitFor(() => expect(count()).toHaveTextContent('2건'))
    await userEvent.click(screen.getByLabelText('메타데이터 확인 필요'))
    await userEvent.click(screen.getByLabelText('정체'))
    await waitFor(() => expect(location()).toBe('/calls?stale=true'))
    await waitFor(() => expect(bodyRows()).toHaveLength(2))
  })

  it('키워드를 입력하면 잠시 뒤 결과가 바뀐다', async () => {
    await openList()
    await userEvent.type(screen.getByLabelText('키워드'), '분실')
    await waitFor(() => expect(location()).toBe('/calls?q=분실'))
    await waitFor(() => expect(bodyRows()).toHaveLength(1))
  })

  it('키워드 입력 직후 고른 필터가 지워지지 않는다', async () => {
    await openList()
    await userEvent.type(screen.getByLabelText('키워드'), '이체')
    await userEvent.selectOptions(screen.getByLabelText('유형'), '불만')
    await waitFor(() => expect(location()).toContain('q=이체'))
    expect(location()).toContain('category=COMPLAINT')
  })

  it('띄어쓰기 뒤에 잠깐 멈춰도 입력이 바뀌지 않는다', async () => {
    await openList()
    await userEvent.type(screen.getByLabelText('키워드'), '분실 ')
    await waitFor(() => expect(bodyRows()).toHaveLength(1))
    expect(location()).toBe('/calls?q=분실')
    expect(screen.getByLabelText('키워드')).toHaveValue('분실 ')
  })

  it('주소에서 키워드가 빠지면 입력칸도 비워진다', async () => {
    await openList('/calls?q=분실')
    expect(screen.getByLabelText('키워드')).toHaveValue('분실')
    await userEvent.click(screen.getByRole('link', { name: '상담 목록' }))
    await waitFor(() => expect(location()).toBe('/calls'))
    expect(screen.getByLabelText('키워드')).toHaveValue('')
  })

  it('기간과 정렬', async () => {
    await openList('/calls?from=2026-11-16&to=2026-11-17')
    expect(screen.getByLabelText('시작일')).toHaveValue('2026-11-16')
    for (const r of bodyRows()) expect(r).toHaveTextContent(/11\/1[67] /)
    await userEvent.selectOptions(screen.getByLabelText('정렬'), '오래된순')
    await waitFor(() => expect(location()).toContain('sort=call_datetime'))
    await waitFor(() => expect(bodyRows()[0]).toHaveTextContent('11/16 10:55'))
  })

  it('질문 요약은 상세로 가는 링크라서 새 탭으로도 열 수 있다', async () => {
    await openList('/calls?q=분실')
    const link = within(bodyRows()[0]).getByRole('link')
    expect(link).toHaveAttribute('href', '/calls/8')
    await userEvent.click(link)
    await waitFor(() => expect(location()).toBe('/calls/8'))
  })

  it('정보가 빠진 건은 - 와 확인 필요 표시', async () => {
    await openList('/calls?metadata_incomplete=true')
    await waitFor(() => expect(bodyRows()).toHaveLength(2))
    const last = bodyRows()[1]
    expect(within(last).getByText('메타데이터 확인 필요')).toBeInTheDocument()
    expect(within(last).getAllByText('-')).toHaveLength(3)
  })

  it('이름이 없는 통계 행(null)은 담당자·고객사 선택지에 넣지 않는다', async () => {
    server.use(
      http.get('*/api/stats/breakdown', () =>
        HttpResponse.json({ by: 'agent', items: [{ name: '이상담', count: 2, by_category: {} }, { name: null, count: 1, by_category: {} }] }),
      ),
    )
    await openList()
    const agent = screen.getByLabelText('담당자')
    await within(agent).findByRole('option', { name: '이상담' })
    expect(within(agent).getAllByRole('option').map((o) => o.textContent)).toEqual(['담당자 전체', '이상담'])
  })

  it('분석 전이거나 통화 시간이 없어도 깨지지 않는다', async () => {
    const base = { ...MOCK_CALLS[0], category: null, question_summary: null, action_status: null, duration_sec: null }
    server.use(http.get('*/api/calls', () => HttpResponse.json({ items: [base], page: 1, size: 20, total: 1 })))
    await openList()
    expect(within(bodyRows()[0]).getByText('분석 결과 없음')).toBeInTheDocument()
  })

  it('범위를 넘는 페이지면 빈 상태와 첫 페이지 버튼만 보여준다', async () => {
    renderWithProviders(<App />, { route: '/calls?page=99' })
    expect(await screen.findByText('조건에 맞는 상담이 없어요')).toBeInTheDocument()
    expect(screen.queryByRole('navigation', { name: '페이지' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '첫 페이지로' }))
    await waitFor(() => expect(bodyRows()).toHaveLength(20))
  })

  it('다음 페이지로 간다', async () => {
    await openList()
    expect(screen.getByText('1 / 2')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '다음' }))
    await waitFor(() => expect(bodyRows()).toHaveLength(7))
    expect(location()).toBe('/calls?page=2')
  })

  it('주소의 잘못된 값은 무시한다', async () => {
    let sent = ''
    server.use(
      http.get('*/api/calls', ({ request }) => {
        sent = new URL(request.url).search
        return HttpResponse.json({ items: [], page: 1, size: 20, total: 0 })
      }),
    )
    await openList('/calls?category=foo&status=BAD&sort=x&page=1.5')
    expect(sent).toBe('?page=1&size=20&sort=-call_datetime')
  })

  it('새 결과를 불러오는 동안 표시한다', async () => {
    await openList()
    server.use(
      http.get('*/api/calls', async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    await userEvent.selectOptions(screen.getByLabelText('유형'), '불만')
    await waitFor(() => expect(screen.getByRole('table')).toHaveAttribute('aria-busy', 'true'))
  })

  it('페이지가 허용 범위를 넘으면 최댓값으로 보낸다', async () => {
    let sent = ''
    server.use(
      http.get('*/api/calls', ({ request }) => {
        sent = new URL(request.url).searchParams.get('page') ?? ''
        return HttpResponse.json({ items: [], page: 10000, size: 20, total: 27 })
      }),
    )
    renderWithProviders(<App />, { route: '/calls?page=99999999' })
    expect(await screen.findByText('조건에 맞는 상담이 없어요')).toBeInTheDocument()
    expect(sent).toBe('10000')
  })

  describe('서버가 아직 정체 여부(is_stale)를 주지 않을 때', () => {
    const { is_stale: _, ...noStale } = { ...MOCK_CALLS[0], category: null, question_summary: null, action_status: null }
    beforeEach(() => server.use(http.get('*/api/calls', () => HttpResponse.json({ items: [noStale], page: 1, size: 20, total: 1 }))))

    it('정체 조건을 고를 수 없다', async () => {
      await openList()
      expect(screen.getByLabelText('정체')).toBeDisabled()
      expect(bodyRows()).toHaveLength(1)
    })

    it('정체 목록 주소로 들어오면 전체 상담을 정체인 것처럼 보여주지 않고, 조건을 지울 수 있다', async () => {
      renderWithProviders(<App />, { route: '/calls?stale=true' })
      expect(await screen.findByText('아직 정체 건만 골라 볼 수 없어요')).toBeInTheDocument()
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
      expect(count()).toBeEmptyDOMElement()
      await userEvent.click(screen.getByRole('button', { name: '정체 조건 지우기' }))
      await waitFor(() => expect(location()).toBe('/calls'))
      expect(bodyRows()).toHaveLength(1)
    })
  })

  describe('서버가 받지 않는 조회 조건', () => {
    let sent: string[] = []
    beforeEach(() => {
      sent = []
      server.use(
        http.get('*/api/calls', ({ request }) => {
          sent.push(new URL(request.url).searchParams.get('q') ?? '')
          return HttpResponse.json({ items: [], page: 1, size: 20, total: 0 })
        }),
      )
    })

    it.each([
      ['from=2026-11-20&to=2026-11-10', '시작일이 종료일보다 늦어요'],
      ['from=0202-11-10', '날짜는 2000년부터 2100년까지 고를 수 있어요'],
      ['to=2101-01-01', '날짜는 2000년부터 2100년까지 고를 수 있어요'],
    ])('기간 %s는 보내지 않고 안내한다', async (query, message) => {
      renderWithProviders(<App />, { route: `/calls?${query}` })
      expect(await screen.findByText(message)).toBeInTheDocument()
      expect(screen.queryByRole('table')).not.toBeInTheDocument()
      expect(sent).toEqual([])
    })

    it('같은 날과 범위의 양 끝은 허용한다', async () => {
      await openList('/calls?from=2000-01-01&to=2100-12-31')
      cleanup()
      await openList('/calls?from=2026-11-10&to=2026-11-10')
      expect(sent).toHaveLength(2)
    })

    it('키워드는 100자까지만 보낸다', async () => {
      await openList(`/calls?q=${'가'.repeat(101)}`)
      expect(sent).toEqual(['가'.repeat(100)])
      expect(screen.getByLabelText('키워드')).toHaveAttribute('maxlength', '100')
    })
  })

  it('서버 오류면 서버 문구와 다시 시도 버튼', async () => {
    server.use(http.get('*/api/calls', () => HttpResponse.json({ code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했습니다.', detail: null }, { status: 500 })))
    renderWithProviders(<App />, { route: '/calls' })
    expect(await screen.findByText('서버 내부 오류가 발생했습니다.')).toBeInTheDocument()
    server.resetHandlers()
    await userEvent.click(screen.getByRole('button', { name: '다시 시도' }))
    await waitFor(() => expect(bodyRows()).toHaveLength(20))
  })
})
