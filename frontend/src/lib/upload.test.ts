import { checkFile } from './upload'

const MB = 1024 * 1024

describe('checkFile', () => {
  it('wav, mp3는 통과 (대소문자 무관)', () => {
    expect(checkFile({ name: 'a.wav', size: 1 })).toBeNull()
    expect(checkFile({ name: 'b.MP3', size: 1 })).toBeNull()
  })
  it('다른 형식과 확장자 없는 파일은 거절', () => {
    expect(checkFile({ name: 'c.m4a', size: 1 })).toBe('지원하지 않는 형식이에요. wav, mp3 파일만 올릴 수 있어요')
    expect(checkFile({ name: 'mp3', size: 1 })).toBe('지원하지 않는 형식이에요. wav, mp3 파일만 올릴 수 있어요')
  })
  it('빈 파일은 거절', () => {
    expect(checkFile({ name: 'e.wav', size: 0 })).toBe('빈 파일이에요')
  })
  it('100MB를 넘으면 거절', () => {
    expect(checkFile({ name: 'd.wav', size: 100 * MB })).toBeNull()
    expect(checkFile({ name: 'd.wav', size: 100 * MB + 1 })).toBe('파일이 너무 커요. 100MB까지 올릴 수 있어요')
  })
})
