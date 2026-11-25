import { fireEvent, screen, waitFor, within } from '@testing-library/react'
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
    expect(screen.getByLabelText('유형')).toHaveValue('INQUIRY')
    expect(screen.getByLabelText('질문 요약')).toHaveValue(c.analysis!.question_summary)
    expect(screen.getByLabelText('조치 내역')).toHaveValue(c.analysis!.action_summary)
    expect(screen.getByLabelText('조치 상태')).toHaveValue('DONE')
    expect(screen.getByText('0.93')).toBeInTheDocument()
    expect(screen.getByText('제품·서비스').nextSibling).toBeInTheDocument()
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

  it('정해지지 않은 후속 조치·조치 상태를 정해진 것처럼 보여주지 않는다', async () => {
    const c = call(1)
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({ ...c, analysis: { ...c.analysis!, follow_up_required: null, action_status: null, needs_review: null } }),
      ),
    )
    await openDetail(1)
    expect(screen.queryByText('필요 없음')).not.toBeInTheDocument()
    expect(screen.getByText('후속 조치').nextSibling).toHaveTextContent('-')
    expect(screen.getByLabelText('조치 상태')).toHaveDisplayValue('-')
    expect(button('저장')).toBeDisabled()
  })

  it('조치 상태가 정해져 있으면 빈 선택지는 없다', async () => {
    await openDetail(1)
    expect(within(screen.getByLabelText('조치 상태')).getAllByRole('option').map((o) => o.textContent)).toEqual(['미조치', '조치 완료'])
  })

  it('전사 구간의 시작 시각과 화자 미상', async () => {
    const c = call(1)
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({
          ...c,
          transcript: { segments: [{ speaker: 'AGENT', start_sec: 61.4, end_sec: 63, text: '여보세요' }, { speaker: 'UNKNOWN', start_sec: 64.2, end_sec: 65, text: '네' }] },
        }),
      ),
    )
    await openDetail(1)
    const conv = screen.getByRole('region', { name: '전사 원문' })
    expect(within(conv).getAllByRole('listitem').map((l) => l.textContent)).toEqual(['상담원 · 1:01여보세요', '화자 미상 · 1:04네'])
  })

  it('개체명은 종류별로 묶고, 나중에 추가된 종류는 코드를 그대로 보여준다', async () => {
    const c = call(1)
    const entities = [
      { type: 'OTHER', value: '한도' }, { type: 'PRODUCT', value: '법인카드' }, { type: 'NEW_TYPE', value: '새 값' }, { type: 'PRODUCT', value: '이체' },
      { type: 'ORG', value: 'B회사' }, { type: 'DATE', value: '내일' }, { type: 'AMOUNT', value: '300만원' }, { type: 'REF_NO', value: '[REF]' },
    ]
    server.use(http.get('*/api/calls/1', () => HttpResponse.json({ ...c, analysis: { ...c.analysis!, entities } })))
    await openDetail(1)
    const shown = screen.getAllByRole('term').map((t) => [t.textContent, t.nextSibling?.textContent])
    expect(shown.slice(shown.findIndex(([k]) => k === '후속 조치') + 1)).toEqual([
      ['제품·서비스', '법인카드, 이체'], ['기관·회사', 'B회사'], ['일정', '내일'], ['금액', '300만원'], ['접수 번호', '[REF]'], ['기타', '한도'], ['NEW_TYPE', '새 값'],
    ])
  })

  it('[PHONE] 같은 개인정보 표시도 강조한다', async () => {
    const c = call(1)
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({ ...c, transcript: { segments: [{ speaker: 'CUSTOMER', start_sec: 0, end_sec: 1, text: '번호는 [PHONE]이고 [공지] 확인' }] } }),
      ),
    )
    await openDetail(1)
    expect(screen.getByText('[PHONE]').tagName).toBe('MARK')
    expect(document.querySelectorAll('mark')).toHaveLength(1)
  })

  it('로봇이 남긴 이력을 한글로 보여준다', async () => {
    server.use(
      http.get('*/api/calls/1', () =>
        HttpResponse.json({ ...call(1), processing_log: [{ step: 'STT', status: 'SUCCESS', message: '[robot] QUEUED -> STT_DONE', created_at: '2026-11-10T09:20:00+09:00' }] }),
      ),
    )
    await openDetail(1)
    expect(within(screen.getByRole('region', { name: '처리 이력' })).getByText('로봇: 처리 대기 → 전사 완료')).toBeInTheDocument()
  })

  it('음성을 불러오지 못하면 안내하고, 다시 재생할 수 있게 되면 지운다', async () => {
    await openDetail(1)
    const audio = screen.getByLabelText('원본 음성 재생')
    expect(screen.queryByText(/음성을 불러오지 못했어요/)).not.toBeInTheDocument()
    fireEvent.error(audio)
    expect(screen.getByText('음성을 불러오지 못했어요. 음성 파일이 없거나 서버에 문제가 있을 수 있어요.')).toBeInTheDocument()
    fireEvent.loadedMetadata(audio)
    expect(screen.queryByText(/음성을 불러오지 못했어요/)).not.toBeInTheDocument()
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

  it.each(['/calls/99999', '/calls/abc', '/calls/0', '/calls/99999999999999999999'])('없는 상담 %s', async (route) => {
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

  it('NOT_FOUND가 아닌 404는 삭제된 상담으로 안내하지 않는다', async () => {
    server.use(http.get('*/api/calls/1', () => new HttpResponse('not found', { status: 404 })))
    renderWithProviders(<App />, { route: '/calls/1' })
    expect(await screen.findByText('요청을 처리하지 못했어요.')).toBeInTheDocument()
  })

  it('나중에 추가된 유형도 그대로 보여준다', async () => {
    const c = call(1)
    server.use(http.get('*/api/calls/1', () => HttpResponse.json({ ...c, analysis: { ...c.analysis!, category: 'NEW_TYPE' } })))
    await openDetail(1)
    expect(screen.getByLabelText('유형')).toHaveValue('NEW_TYPE')
    expect(within(header()).getByText('NEW_TYPE')).toBeInTheDocument()
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
    renderWithProviders(<App />, { route: '/calls?category=COMPLAINT' })
    await userEvent.click((await screen.findAllByRole('link', { name: /항의함/ }))[0])
    await userEvent.click(await screen.findByRole('link', { name: '← 상담 목록' }))
    await waitFor(() => expect(location()).toBe('/calls?category=COMPLAINT'))
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
    expect(sent).toEqual([{ category: 'INQUIRY', review_completed: true }])
    expect(screen.queryByRole('button', { name: '검토 완료' })).not.toBeInTheDocument()
  })

  it.each([
    ['datetime_range', ['body', 'call_datetime'], '통화 일시는 2000년부터 2100년까지 입력할 수 있어요'],
  ])('서버가 받지 않는 값이면 무엇이 문제인지 알려준다: %s', async (type, loc, message) => {
    server.use(
      http.patch('*/api/calls/2', () =>
        HttpResponse.json({ code: 'VALIDATION_ERROR', message: '요청 형식이 올바르지 않습니다.', detail: { errors: [{ loc, msg: 'x', type }] } }, { status: 422 }),
      ),
    )
    await openDetail(2)
    await userEvent.type(screen.getByLabelText('담당자'), 'A')
    await userEvent.click(button('저장'))
    expect(await screen.findByRole('alert')).toHaveTextContent(message)
    expect(button('저장')).toBeEnabled()
  })

  it('저장한 뒤에는 앞뒤 공백 때문에 다시 저장할 것이 남지 않는다', async () => {
    const sent = await capturePatch(2)
    await openDetail(2)
    await userEvent.type(screen.getByLabelText('담당자'), 'A ')
    await userEvent.click(button('저장'))
    expect(await screen.findByText('저장했어요')).toBeInTheDocument()
    expect(sent).toEqual([{ agent_name: `${call(2).agent_name}A` }])
    expect(button('저장')).toBeDisabled()
  })

  it('요약과 조치 내역은 앞뒤 공백을 지우고, 비우면 null로 보낸다', async () => {
    const sent = await capturePatch(2)
    await openDetail(2)
    await userEvent.clear(screen.getByLabelText('질문 요약'))
    await userEvent.clear(screen.getByLabelText('조치 내역'))
    await userEvent.type(screen.getByLabelText('조치 내역'), ' 회신함 ')
    await userEvent.click(button('저장'))
    expect(await screen.findByText('저장했어요')).toBeInTheDocument()
    expect(sent).toEqual([{ question_summary: null, action_summary: '회신함' }])
    expect(button('저장')).toBeDisabled()
  })

  it('저장된 값에 공백이 있어도 바꾸지 않았으면 저장할 것이 없다', async () => {
    const c = call(2)
    server.use(
      http.get('*/api/calls/2', () =>
        HttpResponse.json({ ...c, agent_name: ' 김상담 ', analysis: { ...c.analysis!, question_summary: '문의함 ', action_summary: ' ' } }),
      ),
    )
    await openDetail(2)
    expect(button('저장')).toBeDisabled()
  })

  it('요약과 조치 내역은 2000자까지 입력할 수 있다', async () => {
    await openDetail(2)
    expect(screen.getByLabelText('질문 요약')).toHaveAttribute('maxlength', '2000')
    expect(screen.getByLabelText('조치 내역')).toHaveAttribute('maxlength', '2000')
  })

  it('그사이 상태가 바뀌어 검토 완료가 거절되면 이유를 보여주고 지금 상태를 다시 불러온다', async () => {
    await openDetail(7)
    server.use(
      http.patch('*/api/calls/7', () => HttpResponse.json({ code: 'INVALID_STATE_TRANSITION', message: '현재 상태에서 허용되지 않는 요청입니다.', detail: null }, { status: 409 })),
      http.get('*/api/calls/7', () => HttpResponse.json({ ...call(7), status: 'RETRY_REQUESTED' })),
    )
    await userEvent.type(screen.getByLabelText('수정자 이름'), '홍길동')
    await userEvent.click(button('검토 완료'))
    expect(await screen.findByRole('alert')).toHaveTextContent('현재 상태에서 허용되지 않는 요청입니다.')
    await waitFor(() => expect(within(header()).getByText('재처리 요청됨')).toBeInTheDocument())
    expect(screen.getByLabelText('수정자 이름')).toHaveValue('홍길동')
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

  it('분석 결과가 있으면 재처리로 수정한 내용이 사라진다고 알린다', async () => {
    await openDetail(1)
    expect(screen.getByText('재처리하면 분석 결과가 새로 만들어져요. 직접 수정한 내용은 사라져요.')).toBeInTheDocument()
  })

  it('분석 결과가 없거나 재처리할 수 없으면 그 안내는 없다', async () => {
    await openDetail(21)
    expect(screen.queryByText(/직접 수정한 내용은 사라져요/)).not.toBeInTheDocument()
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

  it.each([
    [' 홍길동 ', '?editor=%ED%99%8D%EA%B8%B8%EB%8F%99'],
    ['   ', ''],
  ])('삭제한 사람 이름을 적으면 함께 보낸다 (%j)', async (typed, query) => {
    let sent = 'none'
    server.use(
      http.delete('*/api/calls/1', ({ request }) => {
        sent = new URL(request.url).search
        return new HttpResponse(null, { status: 204 })
      }),
    )
    await openDetail(1)
    await userEvent.click(button('삭제'))
    await userEvent.type(screen.getByLabelText('삭제하는 사람 (선택)'), typed)
    await userEvent.click(within(screen.getByRole('group', { name: '삭제 확인' })).getByRole('button', { name: '삭제' }))
    await waitFor(() => expect(location()).toBe('/calls'))
    expect(sent).toBe(query)
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
