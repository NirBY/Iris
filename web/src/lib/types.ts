export interface Kid {
  id: number
  kid_name: string
}

export interface Message {
  id: number
  chat_id: number
  chat_name: string | null
  is_group: boolean
  sender_name: string | null
  from_me: boolean
  type: string
  text: string | null
  transcript: string | null
  snippet: string | null
  sent_at: string
  status: string
  verdict: string | null
  redacted: boolean
  kids: Kid[]
  failure: string | null
}

export interface MessagePage {
  items: Message[]
  total: number
  page: number
  page_size: number
}

export interface Classification {
  id: number
  stage: string
  input_kind: string
  model: string
  scores: Record<string, unknown>
  flagged_categories: string[]
  band: string
  context_message_ids: number[] | null
  latency_ms: number | null
}

export interface MessageDetail extends Message {
  classifications: Classification[]
}

export interface Instance {
  id: number
  kid_name: string
  phone_number: string | null
  openwa_base_url: string
  openwa_instance_id: string
  api_key_set: boolean
  enabled: boolean
  webhook_url: string
  last_webhook_at: string | null
  created_at: string
}

export interface Alert {
  id: number
  message_id: number
  chat_id: number
  categories: string[]
  max_score: number
  kid_names: string[]
  chat_name: string | null
  sender_name: string | null
  quote: string | null
  redacted: boolean
  status: string
  delivery_status: string
  delivery_error: string | null
  notified_at: string | null
  created_at: string
}

export interface AlertPage {
  items: Alert[]
  total: number
  page: number
  page_size: number
}

export interface AlertDetail extends Alert {
  message_type: string
  sent_at: string
  classifications: Classification[]
}

export interface ReviewItem {
  message: Message
  classifications: Classification[]
}

export interface ReviewPage {
  items: ReviewItem[]
  total: number
  page: number
  page_size: number
}
