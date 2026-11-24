export function BarList({ rows }: { rows: { name: string; count: number }[] }) {
  const max = Math.max(1, ...rows.map((r) => r.count))
  return (
    <ul className="m-0 flex list-none flex-col gap-2.5 p-0 text-[13px]">
      {rows.map((r) => (
        <li key={r.name} className="grid grid-cols-[72px_minmax(0,1fr)_48px] items-center gap-2.5">
          <span className="truncate" title={r.name}>
            {r.name}
          </span>
          <span aria-hidden="true" className="block h-3.5">
            <span className="block h-full rounded-r bg-s1" style={{ width: `${(r.count / max) * 100}%` }} />
          </span>
          <b className="num text-right font-semibold">{r.count}건</b>
        </li>
      ))}
    </ul>
  )
}
