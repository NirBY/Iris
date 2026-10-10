import type { ReactNode } from 'react'
import { t } from '../lib/i18n'

/** A titled group of related settings. */
export function Section({
  title,
  description,
  children,
}: {
  title: string
  description?: string
  children: ReactNode
}) {
  return (
    <section className="flex flex-col gap-4 rounded-lg border bg-surface p-4 sm:p-5">
      <div className="flex flex-col gap-1">
        <h2 className="text-lg font-semibold">{t(title)}</h2>
        {description && (
          <p className="max-w-prose text-sm text-muted-foreground">{t(description)}</p>
        )}
      </div>
      {children}
    </section>
  )
}
