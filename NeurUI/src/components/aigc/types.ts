/** 连播播放器镜头项（video-compose slideshow_manifest / 模板 outputs.images 合并形态）。 */
export interface SlideshowItem {
  shot?: number
  url?: string
  path?: string
  prompt?: string
  description?: string
  narration?: string
  audio?: string
}
