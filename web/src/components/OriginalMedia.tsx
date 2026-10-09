import { useState } from 'react'

/** Only Iris serves the bytes; OpenWA credentials never reach the browser. */
export function OriginalMedia({
  id,
  type,
  revealed,
}: {
  id: number
  type: string
  revealed: boolean
}) {
  const [failed, setFailed] = useState(false)
  if (!revealed)
    return (
      <span className="text-sm text-muted-foreground">
        Media hidden — use Show content to view.
      </span>
    )
  if (failed)
    return (
      <span role="alert">
        Original media unavailable from OpenWA, unsupported by this browser, or exceeds the 250 MB
        limit.
      </span>
    )
  const props = { src: `/api/media/message/${id}`, onError: () => setFailed(true) }
  if (type === 'video')
    return <video {...props} controls preload="metadata" className="max-h-80 max-w-full" />
  if (type === 'voice' || type === 'audio') return <audio {...props} controls preload="metadata" />
  return (
    <img
      {...props}
      alt={type === 'sticker' ? 'Sticker' : 'Message image'}
      className="max-h-64 max-w-full object-contain"
    />
  )
}
