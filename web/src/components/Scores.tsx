/** Category score bars (0..1) for a classification; `_meta` is bookkeeping, not a score. */
export function Scores({ scores, min = 0.02 }: { scores: Record<string, unknown>; min?: number }) {
  const rows = Object.entries(scores)
    .filter(([k, v]) => k !== '_meta' && typeof v === 'number' && v >= min)
    .sort((a, b) => (b[1] as number) - (a[1] as number))
  if (rows.length === 0) return <p className="text-xs text-slate-500">No category above {min}.</p>
  return (
    <ul className="flex flex-col gap-1">
      {rows.map(([cat, v]) => (
        <li key={cat} className="flex items-center gap-2 text-xs">
          <span className="w-44 shrink-0">{cat}</span>
          <span className="h-2 flex-1 rounded bg-slate-200 dark:bg-slate-800">
            <span
              className="block h-2 rounded bg-indigo-500"
              style={{ width: `${Math.round((v as number) * 100)}%` }}
            />
          </span>
          <span className="w-10 text-right tabular-nums">{(v as number).toFixed(2)}</span>
        </li>
      ))}
    </ul>
  )
}

export function CategoryChips({ categories, score }: { categories: string[]; score?: number }) {
  return (
    <span className="flex flex-wrap gap-1">
      {categories.map((c, i) => (
        <span
          key={c}
          className="rounded bg-red-100 px-2 py-0.5 text-xs text-red-800 dark:bg-red-900 dark:text-red-100"
        >
          {c}
          {i === 0 && score !== undefined ? ` ${score.toFixed(2)}` : ''}
        </span>
      ))}
    </span>
  )
}
