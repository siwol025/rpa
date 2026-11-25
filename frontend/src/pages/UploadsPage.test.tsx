import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import App from '../App'
import { uploadFile } from '../api/uploads'
import { server } from '../mocks/server'
import { renderWithProviders } from '../test/render'

// 실제 동작은 그대로 두고, 필요한 테스트에서만 바꿀 수 있게 한다
vi.mock('../api/uploads', { spy: true })

const user = userEvent.setup({ applyAccept: false })
const file = (name: string) => new File(['x'], name)
const results = () => within(screen.getByRole('list', { name: '업로드 결과' })).getAllByRole('listitem').map((l) => l.textContent)

async function open() {
  renderWithProviders(<App />, { route: '/uploads' })
  await screen.findByRole('link', { name: '20261124_084000_이상담_B물류.mp3' })
}

describe('업로드', () => {
  it('파일마다 따로 보내고, 형식이 다른 파일은 보내지 않는다', async () => {
    let requests = 0
    server.use(
      http.post('*/api/uploads', () => {
        requests++
        return new HttpResponse(null, { status: 202 })
      }),
    )
    await open()
    await user.upload(screen.getByLabelText('음성 파일'), [file('a.wav'), file('b.txt'), file('c.mp3')])
    await waitFor(() =>
      expect(results()).toEqual(['a.wav접수됨, 처리 대기', 'b.txt지원하지 않는 형식이에요. wav, mp3 파일만 올릴 수 있어요', 'c.mp3접수됨, 처리 대기']),
    )
    expect(requests).toBe(2)
  })

  it('서버가 저장한 이름으로 보여준다 (목록의 파일 이름과 같음)', async () => {
    server.use(http.post('*/api/uploads', () => HttpResponse.json({ items: [{ name: 'a.wav' }] }, { status: 202 })))
    await open()
    await user.upload(screen.getByLabelText('음성 파일'), [file('a.WAV')])
    await waitFor(() => expect(results()).toEqual(['a.wav접수됨, 처리 대기']))
  })

  it.each([
    [422, 'VALIDATION_ERROR', { errors: [{ loc: ['body', 'files', 0], msg: '사용할 수 없는 파일명입니다', type: 'filename_invalid' }] }, '사용할 수 없는 파일 이름이에요. 이름을 바꿔서 다시 올려 주세요'],
    [415, 'UNSUPPORTED_MEDIA', { index: 0 }, '파일 내용이 wav, mp3가 아니거나 확장자와 달라요'],
    [422, 'VALIDATION_ERROR', { errors: [{ loc: ['body', 'files'], msg: 'x', type: 'missing' }] }, '서버 문구'],
    [503, 'INBOX_UNAVAILABLE', null, '서버 문구'],
  ])('%i %s이면 이유를 알려준다', async (status, code, detail, message) => {
    server.use(http.post('*/api/uploads', () => HttpResponse.json({ code, message: '서버 문구', detail }, { status })))
    await open()
    await user.upload(screen.getByLabelText('음성 파일'), [file('a.wav')])
    await waitFor(() => expect(results()).toEqual([`a.wav${message}`]))
  })

  it('한 파일이 실패해도 나머지는 계속 올린다', async () => {
    let n = 0
    server.use(
      http.post('*/api/uploads', () =>
        ++n === 1
          ? HttpResponse.json({ code: 'INBOX_UNAVAILABLE', message: '업로드 저장소를 사용할 수 없습니다.', detail: null }, { status: 503 })
          : new HttpResponse(null, { status: 202 }),
      ),
    )
    await open()
    await user.upload(screen.getByLabelText('음성 파일'), [file('a.wav'), file('c.mp3')])
    await waitFor(() => expect(results()).toEqual(['a.wav업로드 저장소를 사용할 수 없습니다.', 'c.mp3접수됨, 처리 대기']))
  })

  it('올리는 동안 표시한다', async () => {
    // jsdom의 파일은 Node fetch로 끝까지 보낼 수 없어서 전송만 대신한다
    vi.mocked(uploadFile).mockImplementationOnce(() => new Promise(() => {}))
    await open()
    await user.upload(screen.getByLabelText('음성 파일'), [file('a.wav')])
    await waitFor(() => expect(results()).toEqual(['a.wav올리는 중']))
  })
})

describe('처리 상태', () => {
  it('처리 중이거나 실패한 건만 최근 변경 순으로 보여준다', async () => {
    await open()
    await waitFor(() => expect(screen.getAllByRole('row')).toHaveLength(1 + 7))
    expect(screen.getAllByRole('row')[1]).toHaveTextContent('11/24 09:55')
    expect(screen.getByText(/처리가 멈춘 상담이 2건 있어요/)).toBeInTheDocument()
  })

  it('정체된 건만 재처리할 수 있고, 멈춘 재처리 요청은 로봇 점검을 안내한다', async () => {
    await open()
    const row = (name: string) => screen.getByRole('link', { name }).closest('tr')!
    expect(within(row('20261124_092000_이상담_E건설.mp3')).queryByRole('button')).not.toBeInTheDocument()
    expect(row('20261119_171000_김상담_B물류.mp3')).toHaveTextContent('로봇 점검 필요')
    await user.click(within(row('20261124_084000_이상담_B물류.mp3')).getByRole('button', { name: '재처리 요청' }))
    expect(await screen.findByText('재처리를 요청했어요. 다음 처리 주기에 반영돼요')).toBeInTheDocument()
    await waitFor(() => expect(row('20261124_084000_이상담_B물류.mp3')).toHaveTextContent('재처리 요청됨'))
  })

  it('불러오지 못하면 이유와 다시 시도', async () => {
    server.use(http.get('*/api/calls', () => HttpResponse.json({ code: 'INTERNAL_ERROR', message: '서버 내부 오류가 발생했습니다.', detail: null }, { status: 500 })))
    renderWithProviders(<App />, { route: '/uploads' })
    expect(await screen.findByText('서버 내부 오류가 발생했습니다.')).toBeInTheDocument()
    server.resetHandlers()
    await user.click(screen.getByRole('button', { name: '다시 시도' }))
    expect(await screen.findByRole('link', { name: '20261124_084000_이상담_B물류.mp3' })).toBeInTheDocument()
  })

  it('상태 여러 개를 한 번에 조회하고, 다 못 보여주면 남은 건수를 알린다', async () => {
    let sent = ''
    server.use(
      http.get('*/api/calls', ({ request }) => {
        sent = new URL(request.url).search
        return HttpResponse.json({ items: [], page: 1, size: 100, total: 130 })
      }),
    )
    renderWithProviders(<App />, { route: '/uploads' })
    expect(await screen.findByText(/130건이 더 있어요/)).toBeInTheDocument()
    expect(sent).toBe('?status=REGISTERED&status=QUEUED&status=STT_DONE&status=RETRY_REQUESTED&status=FAILED&page=1&size=100&sort=-status_changed_at')
  })
})
