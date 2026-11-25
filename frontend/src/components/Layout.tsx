import { NavLink, Outlet } from 'react-router-dom'

const MENU = [
  { to: '/', label: '대시보드' },
  { to: '/calls', label: '상담 목록' },
  { to: '/uploads', label: '업로드·처리 상태' },
]

const linkClass = ({ isActive }: { isActive: boolean }) =>
  `block whitespace-nowrap rounded-md px-2.5 py-2 font-medium no-underline ${
    isActive ? 'bg-accent-soft text-accent font-semibold' : 'text-fg-2 hover:bg-surface-2 hover:text-fg'
  }`

export function Layout() {
  return (
    <div className="grid min-h-screen grid-cols-1 content-start min-[900px]:grid-cols-[208px_minmax(0,1fr)] min-[900px]:content-stretch">
      <nav
        aria-label="주 메뉴"
        className="sticky top-0 z-20 flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-line bg-surface px-4 py-2.5 min-[900px]:h-screen min-[900px]:flex-col min-[900px]:flex-nowrap min-[900px]:items-stretch min-[900px]:gap-5 min-[900px]:border-r min-[900px]:border-b-0 min-[900px]:px-3.5 min-[900px]:py-5"
      >
        <b className="text-[15px] min-[900px]:px-2.5">콜센터 인공지능 비서</b>
        <ul className="m-0 flex max-w-full list-none gap-0.5 overflow-x-auto p-0 min-[900px]:flex-col">
          {MENU.map((m) => (
            <li key={m.to}>
              <NavLink to={m.to} end={m.to === '/'} className={linkClass}>
                {m.label}
              </NavLink>
            </li>
          ))}
        </ul>
      </nav>
      <main className="min-w-0 px-4 pt-6 pb-12 min-[900px]:px-7">
        <Outlet />
      </main>
    </div>
  )
}
