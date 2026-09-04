import type { SocialPost } from '../../../lib/api'
import { toLocalInput } from './constants'

export interface EditorState {
  id?: number; platform: string; content: string; topic: string; hashtags: string; link_url: string; creative_id: number | null; creative_url: string; scheduled_for: string
}

export const emptyEditor = (platform = 'instagram', siteUrl = ''): EditorState => ({ platform, content: '', topic: '', hashtags: '', link_url: siteUrl, creative_id: null, creative_url: '', scheduled_for: '' })

export function fromPost(p: SocialPost): EditorState {
  return { id: p.id, platform: p.platform, content: p.content, topic: p.topic, hashtags: p.hashtags.join(' '), link_url: p.link_url, creative_id: p.creative_id, creative_url: p.creative_url, scheduled_for: toLocalInput(p.scheduled_for) }
}
