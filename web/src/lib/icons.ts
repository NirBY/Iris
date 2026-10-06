const ICON: Record<string, string> = {
  text: '💬',
  image: '🖼️',
  audio: '🎧',
  voice: '🎤',
  video: '🎬',
  sticker: '🏷️',
  document: '📄',
  other: '❔',
}

export function typeIcon(t: string) {
  return ICON[t] ?? ICON.other
}
