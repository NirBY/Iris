import { useEffect, useRef, useState } from 'react'
import { t } from '../lib/i18n'

/** WhatsApp animated (Lottie) sticker. The light player has no expression engine, so a
 * sticker cannot run code, and Iris removes external image references before sending it. */
export function AnimatedSticker({ id }: { id: number }) {
  const box = useRef<HTMLDivElement>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    const controller = new AbortController()
    let destroy: (() => void) | undefined
    void (async () => {
      try {
        const response = await fetch(`/api/media/message/${id}/animation`, {
          signal: controller.signal,
          credentials: 'same-origin',
        })
        if (!response.ok) {
          const data = await response.json().catch(() => ({}))
          throw new Error(typeof data.detail === 'string' ? data.detail : '')
        }
        const animationData = await response.json()
        const { default: lottie } = await import('lottie-web/build/player/lottie_light')
        if (controller.signal.aborted || !box.current) return
        const animation = lottie.loadAnimation({
          container: box.current,
          renderer: 'svg',
          loop: true,
          autoplay: true,
          animationData,
        })
        destroy = () => animation.destroy()
      } catch (exc) {
        if (!controller.signal.aborted)
          setError(
            exc instanceof Error && exc.message
              ? exc.message
              : 'Could not play this animated sticker. Try again.',
          )
      }
    })()
    return () => {
      controller.abort()
      destroy?.()
    }
  }, [id])
  if (error)
    return (
      <p role="alert" className="text-sm">
        {t(error)}
      </p>
    )
  return (
    <div
      ref={box}
      role="img"
      aria-label={t('Animated sticker')}
      className="size-48 max-w-full"
      data-testid="animated-sticker"
    />
  )
}
