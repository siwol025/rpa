import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { delay, http, HttpResponse } from 'msw'
import App from '../App'
import { MOCK_CALLS } from '../mocks/data'
import { server } from '../mocks/server'
import { renderWithProviders } from '../test/render'

const call = (id: number) => MOCK_CALLS.find((c) => c.id === id)!
const location = () => decodeURIComponent(screen.getByTestId('location').textContent ?? '')
const header = () => screen.getByRole('region', { name: '상담 정보' })
const button = (name: string) => screen.getByRole('button', { name })

async function openDetail(id: number) {
  renderWithProviders(<App />, { route: `/calls/${id}` })
  await screen.findByRole('heading', { level: 1, name: `상담 ${id}` })
}

describe('상담 상세: 보기', () => {
  it('기본 정보, 전사 원문, 분석 결과, 처리 이력', async () => {
    const c = call(1)
    await openDetail(1)
    for (const t of ['11/10 09:12', '김상담', 'A산업', '3:34', c.original_name, '클라우드 폴더']) {
      expect(within(header()).getByText(t)).toBeInTheDocument()
    }
    const conv = screen.getByRole('region', { name: '전사 원문' })
    expect(within(conv).getAllByRole('listitem')).toHaveLength(c.transcript!.segments.length)
    expect(within(conv).getByText('상담원 · 0:00')).toBeInTheDocument()
    expect(screen.getByLabelText('유형')).toHaveValue('질의')
    expect(screen.getByLabelText('질문 요약')).toHaveValue(c.analysis!.question_summary)
    expect(screen.getByLabelText('조치 내역')).toHaveValue(c.analysis!.action_summary)
    expect(screen.getByLabelText('조치 상태')).toHaveValue('DONE')
    expect(screen.getByText('0.93')).toBeInTheDocument()
    expect(screen.getByText('해외 결제, 차단 해제')).toBeInTheDocument()
    const log = screen.getByRole('region', { name: '처리 이력' })
    expect(within(log).getByText('AI 분석')).toBeInTheDocument()
  })

  it('가려진 개인정보를 강조한다', async () => {
    await openDetail(1)
    expect(screen.getByText('010-****-5821').tagName).toBe('MARK')
  })

  it('음성 주소를 연결한다', async () => {
    await openDetail(1)
    expect(screen.getByLabelText('원본 음성 재생')).toHaveAttribute('src', '/api/calls/1/audio')
  })

  it('전사 실패: 이력에 사유', async () => {
    await openDetail(21)
    expect(screen.getByText('전사에 실패했어요.')).toBeInTheDocument()
    expect(screen.getByText('음질이 낮아 전사하지 못했습니다.')).toBeInTheDocument()
  })

  it('분석만 실패: 전사는 보이고 AI 분석 실패로 안내', async () => {
    await openDetail(22)
    expect(within(screen.getByRole('region', { name: '전사 원문' })).getAllByRole('listitem')).toHaveLength(2)
    expect(screen.getByText(/AI 분석에 실패했어요/)).toBeInTheDocument()
  })

  it('처리 중: 아직 없다고 안내', async () => {
    await openDetail(25)
    expect(screen.getByText('아직 전사되지 않았어요.')).toBeInTheDocument()
    expect(screen.getByText('아직 분석 결과가 없어요.')).toBeInTheDocument()
  })

  it('비어 있을 수 있는 값이 모두 비어도 깨지지 않는다', async () => {
    const c = call(1)
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({ ...c, duration_sec: null, analysis: { ...c.analysis!, confidence: null, question_summary: null, action_summary: null, entities: null } }),
      ),
    )
    await openDetail(1)
    expect(screen.getByLabelText('질문 요약')).toHaveValue('')
  })

  it('모르는 처리 단계와 결과도 그대로 보여준다', async () => {
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({ ...call(1), processing_log: [{ step: 'NEW_STEP', status: 'NEW', message: null, created_at: '2026-11-10T09:20:00+09:00' }] }),
      ),
    )
    await openDetail(1)
    expect(screen.getByText('NEW_STEP')).toBeInTheDocument()
    expect(screen.getByText('NEW')).toBeInTheDocument()
  })

  it.each(['/calls/99999', '/calls/abc', '/calls/0'])('없는 상담 %s', async (route) => {
    let asked = 0
    server.use(
      http.get('*/api/calls/:id', ({ params }) => {
        asked += params.id === '99999' ? 0 : 1
        return HttpResponse.json({ code: 'NOT_FOUND', message: '대상을 찾을 수 없습니다.', detail: null }, { status: 404 })
      }),
    )
    renderWithProviders(<App />, { route })
    expect(await screen.findByText('없거나 삭제된 상담이에요.')).toBeInTheDocument()
    expect(asked).toBe(0)
  })

  it('불러오는 동안 표시한다', async () => {
    server.use(
      http.get('*/api/calls/1', async () => {
        await delay('infinite')
        return HttpResponse.json({})
      }),
    )
    renderWithProviders(<App />, { route: '/calls/1' })
    expect(await screen.findByLabelText('불러오는 중')).toBeInTheDocument()
  })

  it('목록으로 돌아가면 필터가 그대로', async () => {
    renderWithProviders(<App />, { route: '/calls?category=불만' })
    await userEvent.click((await screen.findAllByRole('link', { name: /항의함/ }))[0])
    await userEvent.click(await screen.findByRole('link', { name: '← 상담 목록' }))
    await waitFor(() => expect(location()).toBe('/calls?category=불만'))
  })
})

describe('상담 상세: 수정', () => {
  async function capturePatch(id: number) {
    const sent: unknown[] = []
    server.use(
      http.patch(`*/api/calls/${id}`, async ({ request }) => {
        sent.push(await request.clone().json())
        return undefined // 기본 mock으로 이어서 처리
      }),
    )
    return sent
  }

  it('바뀐 값과 수정자 이름만 보낸다', async () => {
    const sent = await capturePatch(2)
    await openDetail(2)
    expect(button('저장')).toBeDisabled()
    await userEvent.selectOptions(screen.getByLabelText('조치 상태'), '조치 완료')
    await userEvent.type(screen.getByLabelText('수정자 이름'), ' 홍길동 ')
    await userEvent.click(button('저장'))
    expect(await screen.findByText('저장했어요')).toBeInTheDocument()
    expect(sent).toEqual([{ action_status: 'DONE', editor: '홍길동' }])
    expect(button('저장')).toBeDisabled()
  })

  it('수정자 이름만 적으면 저장할 것이 없다', async () => {
    await openDetail(2)
    await userEvent.type(screen.getByLabelText('수정자 이름'), '홍길동')
    expect(button('저장')).toBeDisabled()
  })

  it('담당자와 통화 일시를 채우면 확인 필요가 사라진다', async () => {
    await openDetail(20)
    expect(within(header()).getByText('메타데이터 확인 필요')).toBeInTheDocument()
    await userEvent.type(screen.getByLabelText('담당자'), '김상담')
    await userEvent.type(screen.getByLabelText('통화 일시'), '2026-11-23T11:12')
    await userEvent.click(button('저장'))
    await waitFor(() => expect(within(header()).queryByText('메타데이터 확인 필요')).not.toBeInTheDocument())
    expect(within(header()).getByText('11/23 11:12')).toBeInTheDocument()
  })

  it('담당자를 지우면 null로 보낸다', async () => {
    const sent = await capturePatch(1)
    await openDetail(1)
    await userEvent.clear(screen.getByLabelText('담당자'))
    await userEvent.click(button('저장'))
    await waitFor(() => expect(sent).toEqual([{ agent_name: null }]))
  })

  it('검토 완료', async () => {
    const sent = await capturePatch(7)
    await openDetail(7)
    expect(screen.getByText('분류 신뢰도가 낮아 검토가 필요해요.')).toBeInTheDocument()
    await userEvent.selectOptions(screen.getByLabelText('유형'), '질의')
    await userEvent.click(button('검토 완료'))
    await waitFor(() => expect(within(header()).getByText('저장 완료')).toBeInTheDocument())
    expect(sent).toEqual([{ category: '질의', review_completed: true }])
    expect(screen.queryByRole('button', { name: '검토 완료' })).not.toBeInTheDocument()
  })

  it('저장에 실패하면 이유를 보여주고 입력을 지우지 않는다', async () => {
    server.use(http.patch('*/api/calls/2', () => HttpResponse.json({ code: 'VALIDATION_ERROR', message: '요청 형식이 올바르지 않습니다.', detail: null }, { status: 422 })))
    await openDetail(2)
    await userEvent.type(screen.getByLabelText('질문 요약'), ' 추가')
    await userEvent.click(button('저장'))
    expect(await screen.findByRole('alert')).toHaveTextContent('요청 형식이 올바르지 않습니다.')
    expect(screen.getByLabelText('질문 요약')).toHaveValue(`${call(2).analysis!.question_summary} 추가`)
    expect(button('저장')).toBeEnabled()
  })

  it('다시 불러와도 저장하지 않은 입력이 남는다', async () => {
    await openDetail(21)
    await userEvent.type(screen.getByLabelText('수정자 이름'), '홍')
    await userEvent.type(screen.getByLabelText('담당자'), 'X')
    await userEvent.click(button('재처리 요청'))
    await waitFor(() => expect(within(header()).getByText('재처리 요청됨')).toBeInTheDocument())
    expect(screen.getByLabelText('담당자')).toHaveValue('김상담X')
  })
})

describe('상담 상세: 재처리와 삭제', () => {
  it('실패한 건을 재처리 요청한다', async () => {
    await openDetail(21)
    await userEvent.click(button('재처리 요청'))
    expect(await screen.findByText('재처리를 요청했어요. 다음 처리 주기에 반영돼요')).toBeInTheDocument()
    await waitFor(() => expect(button('재처리 요청')).toBeDisabled())
  })

  it('처리 중인 건은 요청할 수 없다', async () => {
    await openDetail(24)
    expect(button('재처리 요청')).toBeDisabled()
    expect(screen.getByText('처리 중인 상담은 재처리를 요청할 수 없어요.')).toBeInTheDocument()
  })

  it('정체된 건은 요청할 수 있다', async () => {
    await openDetail(23)
    expect(within(header()).getByText('정체')).toBeInTheDocument()
    expect(button('재처리 요청')).toBeEnabled()
  })

  it('재처리 요청이 멈춰 있으면 로봇 점검을 안내한다', async () => {
    await openDetail(27)
    expect(button('재처리 요청')).toBeDisabled()
    expect(screen.getByText(/로봇 점검을 요청해 주세요/)).toBeInTheDocument()
  })

  it('그사이 상태가 바뀌어 거절되면 이유를 보여준다', async () => {
    server.use(http.post('*/api/calls/21/retry', () => HttpResponse.json({ code: 'INVALID_STATE_TRANSITION', message: '현재 상태에서 허용되지 않는 요청입니다.', detail: null }, { status: 409 })))
    await openDetail(21)
    await userEvent.click(button('재처리 요청'))
    expect(await screen.findByRole('alert')).toHaveTextContent('현재 상태에서 허용되지 않는 요청입니다.')
  })

  it('확인을 거쳐 삭제하고 목록으로 간다', async () => {
    await openDetail(1)
    await userEvent.click(button('삭제'))
    await userEvent.click(button('취소'))
    expect(screen.queryByText('이 상담을 삭제할까요?')).not.toBeInTheDocument()
    await userEvent.click(button('삭제'))
    await userEvent.click(within(screen.getByRole('group', { name: '삭제 확인' })).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(location()).toBe('/calls'))
    expect(await screen.findByText('삭제했어요')).toBeInTheDocument()
    await waitFor(() => expect(screen.getByLabelText('검색 결과 수')).toHaveTextContent('26건'))
  })
})
