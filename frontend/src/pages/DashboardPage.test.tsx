import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import App from '../App'
import { server } from '../mocks/server'
import { renderWithProviders } from '../test/render'

const location = () => screen.getByTestId('location').textContent
const kpi = (name: string) => screen.getByRole('group', { name })
const panel = (name: string) => screen.getByRole('region', { name })

async function open(route = '/') {
  renderWithProviders(<App />, { route })
  await waitFor(() => expect(kpi('총 건수')).toHaveTextContent(/\d+건/))
}

describe('대시보드', () => {
  it('요약 지표 6개', async () => {
    await open('/?from=2026-11-10&to=2026-11-24')
    for (const [name, n] of [['총 건수', 26], ['미조치', 5], ['검토 필요', 2], ['메타데이터 확인 필요', 1], ['실패', 2], ['정체', 2]] as const) {
      expect(kpi(name)).toHaveTextContent(`${n}건`)
    }
  })

  it('유형별·담당자별·고객사별 건수', async () => {
    await open()
    expect(within(panel('유형별 건수')).getAllByRole('listitem').map((l) => l.textContent)).toEqual(['질의7건', '불만5건', '건의3건', '교육 내용3건', '기타 문의2건'])
    await waitFor(() => expect(within(panel('담당자별 현황')).getAllByRole('listitem')[0]).toHaveTextContent('김상담9건'))
    await waitFor(() => expect(within(panel('고객사별 현황')).getAllByRole('listitem').at(-1)).toHaveTextContent('미지정1건'))
  })

  it('일 단위로 그리기에 너무 긴 기간이면 단위를 바꾸라고 안내한다', async () => {
    await open('/?from=2024-01-01&to=2026-11-24')
    expect(await within(panel('기간별 추이')).findByText('기간이 길어서 이 단위로는 볼 수 없어요. 주나 월로 바꾸거나 기간을 줄여 주세요')).toBeInTheDocument()
    expect(within(panel('기간별 추이')).queryByRole('button', { name: '다시 시도' })).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '월' }))
    expect(await within(panel('기간별 추이')).findByRole('img')).toBeInTheDocument()
  })

  describe('통계 요약 API가 아직 없는 서버', () => {
    const noSummary = () =>
      server.use(http.get('*/api/stats/summary', () => HttpResponse.json({ code: 'NOT_FOUND', message: '대상을 찾을 수 없습니다.', detail: null }, { status: 404 })))

    it('목록·분류 API로 셀 수 있는 지표는 같은 값으로 보이고, 나머지는 - 로 보인다', async () => {
      noSummary()
      await open('/?from=2026-11-10&to=2026-11-24')
      for (const [name, n] of [['총 건수', 26], ['검토 필요', 2], ['메타데이터 확인 필요', 1], ['실패', 2]] as const) {
        expect(kpi(name)).toHaveTextContent(`${name}${n}건`)
      }
      for (const name of ['미조치', '정체']) expect(kpi(name)).toHaveTextContent(new RegExp(`^${name}-$`))
      expect(screen.getByText('미조치와 정체는 서버의 통계 요약이 준비되면 보여요')).toBeInTheDocument()
      expect(within(panel('유형별 건수')).getAllByRole('listitem').map((l) => l.textContent)).toEqual(['질의7건', '불만5건', '건의2건', '교육 내용3건', '기타 문의2건'])
      expect(screen.queryByText(/처리가 멈춘 상담/)).not.toBeInTheDocument()
    })

    it('대신 조회하던 것도 실패하면 오류를 보여준다', async () => {
      noSummary()
      server.use(http.get('*/api/calls', () => HttpResponse.json({ code: 'VALIDATION_ERROR', message: '요청 형식이 올바르지 않습니다.', detail: null }, { status: 422 })))
      renderWithProviders(<App />, { route: '/' })
      expect((await screen.findAllByText('요청 형식이 올바르지 않습니다.')).length).toBeGreaterThan(0)
    })

    it('404가 아닌 오류는 대신 조회하지 않고 그대로 보여준다', async () => {
      server.use(http.get('*/api/stats/summary', () => HttpResponse.json({ code: 'VALIDATION_ERROR', message: '요약 오류', detail: null }, { status: 422 })))
      renderWithProviders(<App />, { route: '/' })
      expect((await screen.findAllByText('요약 오류')).length).toBeGreaterThan(0)
    })
  })

  it('요약이 있으면 안내 문구가 없다', async () => {
    await open()
    expect(screen.queryByText(/통계 요약이 준비되면/)).not.toBeInTheDocument()
  })

  it('정체 경고에서 정체 목록으로 간다', async () => {
    await open()
    await userEvent.click(await screen.findByRole('link', { name: '정체 건 보기' }))
    expect(location()).toBe('/calls?stale=true')
  })

  it('정체가 없으면 경고도 없다', async () => {
    await open('/?from=2026-11-10&to=2026-11-13')
    expect(kpi('정체')).toHaveTextContent('0건')
    expect(screen.queryByText(/처리가 멈춘 상담/)).not.toBeInTheDocument()
  })

  it('기간을 바꾸면 주소에 남고 지표가 바뀐다', async () => {
    await open('/?to=2026-11-24')
    await userEvent.type(screen.getByLabelText('시작일'), '2026-11-23')
    await waitFor(() => expect(location()).toContain('from=2026-11-23'))
    await waitFor(() => expect(kpi('총 건수')).toHaveTextContent('7건'))
  })

  it('서버가 받지 않는 기간은 보내지 않고 안내한다', async () => {
    let asked = 0
    server.use(
      http.get('*/api/stats/*', () => {
        asked += 1
        return HttpResponse.json({ items: [] })
      }),
    )
    renderWithProviders(<App />, { route: '/?from=2026-11-20&to=2026-11-10' })
    expect(await screen.findByText('시작일이 종료일보다 늦어요')).toBeInTheDocument()
    expect(screen.queryByRole('group', { name: '총 건수' })).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: '엑셀 다운로드' })).toBeDisabled()
    expect(asked).toBe(0)
  })

  it('추이 단위를 바꾼다', async () => {
    await open()
    expect(await screen.findByRole('img', { name: /11\/10 2건/ })).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: '주' }))
    expect(await screen.findByRole('img', { name: '기간별 상담 건수: 11/9 시작 주 8건, 11/16 시작 주 11건, 11/23 시작 주 7건' })).toBeInTheDocument()
  })

  it('상담이 없는 기간', async () => {
    await open('/?from=2026-12-01')
    expect(within(panel('기간별 추이')).getByText('이 기간에는 상담이 없어요')).toBeInTheDocument()
  })

  it('나중에 추가된 유형은 뒤에 붙인다', async () => {
    server.use(
      http.get('*/api/stats/summary', () =>
        HttpResponse.json({ total: 3, by_category: { COMPLAINT: 2, NEW_TYPE: 1 }, action_open: 0, needs_review: 0, metadata_incomplete: 0, failed: 0, stale: 0 }),
      ),
    )
    await open()
    expect(within(panel('유형별 건수')).getAllByRole('listitem').map((l) => l.textContent)).toEqual(['질의0건', '불만2건', '건의0건', '교육 내용0건', '기타 문의0건', 'NEW_TYPE1건'])
  })

  it('한 부분이 실패해도 나머지는 보인다', async () => {
    server.use(http.get('*/api/stats/trend', () => HttpResponse.json({ code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했습니다.', detail: null }, { status: 500 })))
    await open()
    expect(await within(panel('기간별 추이')).findByText('서버 내부 오류가 발생했습니다.')).toBeInTheDocument()
    expect(kpi('총 건수')).toHaveTextContent('27건')
  })
})

describe('엑셀 다운로드', () => {
  it('기간을 담아 요청하고 파일로 저장한다', async () => {
    let query = ''
    server.use(
      http.get('*/api/reports/excel', ({ request }) => {
        query = new URL(request.url).search
        return new HttpResponse('x')
      }),
    )
    const create = vi.fn(() => 'blob:x')
    const revoke = vi.fn()
    vi.stubGlobal('URL', Object.assign(URL, { createObjectURL: create, revokeObjectURL: revoke }))
    let name = ''
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function (this: HTMLAnchorElement) {
      name = this.download
    })
    await open('/?from=2026-11-10&to=2026-11-24')
    await userEvent.click(screen.getByRole('button', { name: '엑셀 다운로드' }))
    await waitFor(() => expect(name).toBe('report_20261110-20261124.xlsx'))
    expect(query).toBe('?from=2026-11-10&to=2026-11-24')
    expect(create).toHaveBeenCalledOnce()
    click.mockRestore()
    vi.unstubAllGlobals()
  })

  it('실패하면 이유를 알린다', async () => {
    await open()
    await userEvent.click(screen.getByRole('button', { name: '엑셀 다운로드' }))
    expect(await screen.findByText('예시 데이터 모드에서는 엑셀 파일을 만들지 않아요.')).toBeInTheDocument()
  })
})
