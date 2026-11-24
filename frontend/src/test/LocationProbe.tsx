import { useLocation } from 'react-router-dom'

/** 테스트에서 현재 주소(pathname + search)를 읽기 위한 숨은 요소 */
export function LocationProbe() {
  const loc = useLocation()
  return (
    <output data-testid="location" hidden>
      {loc.pathname + loc.search}
    </output>
  )
}
