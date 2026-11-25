import { Link } from 'react-router-dom'

export function NotFoundPage() {
  return (
    <section className="flex flex-col gap-2">
      <h1 className="m-0 text-[22px] font-bold">페이지를 찾을 수 없어요</h1>
      <Link to="/" className="underline">
        대시보드로 가기
      </Link>
    </section>
  )
}
