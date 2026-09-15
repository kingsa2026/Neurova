<script setup lang="ts">
/**
 * 创作专区 · 项目列表。
 * 卡片：封面/标题/题材/风格/画幅/集数进度/更新时间；新建向导弹窗；删除确认。
 */
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { message } from 'ant-design-vue'
import {
  createProject, deleteProject, listProjects,
  type StudioProject,
} from '@/api/modules/studio'
import GlassPanel from '@/components/GlassPanel.vue'
import GlassButton from '@/components/GlassButton.vue'

const { t } = useI18n()
const router = useRouter()

const projects = ref<StudioProject[]>([])
const loading = ref(false)
const showCreate = ref(false)
const creating = ref(false)
const form = ref({
  title: '',
  genre: '都市逆袭',
  style: 'cinematic',
  aspect_ratio: '9:16 竖屏',
  total_episodes: 1,
  description: '',
})

const genreOptions = ['都市逆袭', '甜宠恋爱', '悬疑惊悚', '古装权谋', '战神归来']
  .map((g) => ({ label: g, value: g }))
const aspectOptions = ['9:16 竖屏', '16:9 横屏', '1:1 方形']
  .map((a) => ({ label: a, value: a }))

async function load() {
  loading.value = true
  try {
    const res: any = await listProjects()
    projects.value = res?.data?.projects ?? []
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    loading.value = false
  }
}

async function create() {
  if (!form.value.title.trim()) return
  creating.value = true
  try {
    const res: any = await createProject({
      title: form.value.title.trim(),
      genre: form.value.genre,
      style: form.value.style.trim() || 'cinematic',
      aspect_ratio: form.value.aspect_ratio,
      total_episodes: form.value.total_episodes,
      description: form.value.description,
    })
    const pid = res?.data?.project?.id
    showCreate.value = false
    form.value = { title: '', genre: '都市逆袭', style: 'cinematic', aspect_ratio: '9:16 竖屏', total_episodes: 1, description: '' }
    if (pid) router.push(`/aigc/studio/${pid}`)
  } catch {
    message.error(t('aigc.generateError'))
  } finally {
    creating.value = false
  }
}

async function remove(p: StudioProject) {
  try {
    await deleteProject(p.id)
    await load()
  } catch {
    message.error(t('aigc.generateError'))
  }
}

function fmt(ts: number): string {
  return ts ? new Date(ts * 1000).toLocaleString() : ''
}

onMounted(load)
</script>

<template>
  <div class="studio-list-page">
    <div class="studio-list-head">
      <div>
        <h3 class="studio-h3">{{ t('studio.title') }}</h3>
        <div class="studio-sub">{{ t('studio.subtitle') }}</div>
      </div>
      <GlassButton variant="primary" @click="showCreate = true">{{ t('studio.newProject') }}</GlassButton>
    </div>

    <a-spin :spinning="loading">
      <div v-if="projects.length" class="studio-grid">
        <GlassPanel
          v-for="p in projects"
          :key="p.id"
          class="studio-card"
          variant="subtle"
        >
          <div class="studio-card-title" @click="router.push(`/aigc/studio/${p.id}`)">{{ p.title }}</div>
          <div class="studio-card-meta">
            <a-tag color="purple">{{ p.genre }}</a-tag>
            <a-tag>{{ p.aspect_ratio }}</a-tag>
            <a-tag color="cyan">{{ p.style }}</a-tag>
          </div>
          <div class="studio-card-desc">{{ p.description || '—' }}</div>
          <div class="studio-card-foot">
            <span class="studio-card-time">{{ t('studio.updatedAt') }} {{ fmt(p.updated_at) }}</span>
            <span class="studio-card-actions">
              <GlassButton size="sm" variant="primary" @click="router.push(`/aigc/studio/${p.id}`)">
                {{ t('common.open') }}
              </GlassButton>
              <a-popconfirm :title="t('common.confirm') + '?'" @confirm="remove(p)">
                <GlassButton size="sm" variant="danger">{{ t('common.delete') }}</GlassButton>
              </a-popconfirm>
            </span>
          </div>
        </GlassPanel>
      </div>
      <a-empty v-else-if="!loading" :description="t('studio.noProjects')" />
    </a-spin>

    <a-modal
      v-model:open="showCreate"
      :title="t('studio.newProject')"
      :confirm-loading="creating"
      @ok="create"
    >
      <a-form layout="vertical">
        <a-form-item :label="t('common.name')">
          <a-input v-model:value="form.title" :placeholder="t('studio.projectTitleHint')" />
        </a-form-item>
        <a-form-item :label="t('studio.genre')">
          <a-select v-model:value="form.genre" :options="genreOptions" />
        </a-form-item>
        <a-form-item :label="t('studio.style')">
          <a-input v-model:value="form.style" :placeholder="t('studio.styleHint')" />
        </a-form-item>
        <a-form-item :label="t('studio.aspect')">
          <a-select v-model:value="form.aspect_ratio" :options="aspectOptions" />
        </a-form-item>
        <a-form-item :label="t('studio.episodes')">
          <a-input-number v-model:value="form.total_episodes" :min="1" :max="100" style="width: 100%" />
        </a-form-item>
      </a-form>
    </a-modal>
  </div>
</template>

<style scoped>
.studio-list-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: 16px;
  gap: 12px;
}
.studio-h3 { margin: 0; font-size: 16px; color: var(--nr-text-primary); }
.studio-sub { margin-top: 4px; font-size: 12px; color: var(--nr-text-secondary); }
.studio-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 14px;
}
.studio-card { padding: 16px; display: flex; flex-direction: column; gap: 8px; }
.studio-card-title { font-size: 15px; font-weight: 600; color: var(--nr-text-primary); cursor: pointer; }
.studio-card-title:hover { color: var(--nr-accent, #4096ff); }
.studio-card-meta { display: flex; gap: 6px; flex-wrap: wrap; }
.studio-card-desc {
  font-size: 12px;
  color: var(--nr-text-secondary);
  min-height: 18px;
  overflow: hidden;
  text-overflow: ellipsis;
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
}
.studio-card-foot { display: flex; align-items: center; justify-content: space-between; gap: 8px; }
.studio-card-time { font-size: 11px; color: var(--nr-text-secondary); }
.studio-card-actions { display: flex; gap: 6px; }
</style>
