<template>
  <div class="geo-map-panel">
    <div class="geo-toolbar">
      <a-input v-model:value="lat" size="sm" class="geo-input"
               :placeholder="t('knowledge.workbenchLat')" />
      <a-input v-model:value="lon" size="sm" class="geo-input"
               :placeholder="t('knowledge.workbenchLon')" />
      <a-input v-model:value="radiusKm" size="sm" class="geo-input geo-input-narrow"
               :placeholder="t('knowledge.workbenchRadius')" />
      <GlassButton size="sm" :loading="loading" @click="fetchGeo">
        {{ t('knowledge.workbenchApplyFilter') }}
      </GlassButton>
      <GlassButton size="sm" @click="clearFilter">
        {{ t('common.reset') }}
      </GlassButton>
    </div>
    <div ref="mapRef" class="geo-map"></div>
    <div v-if="mapFailed" class="geo-empty">
      <a-empty :description="t('knowledge.workbenchNoGeoItems')" />
    </div>
    <div v-if="!loading && !items.length && !nodeGeo.length" class="geo-empty">
      <a-empty :description="emptyReason" />
    </div>
  </div>
</template>

<script setup lang="ts">
/**
 * 空间视图（升级计划 A6 前端半）：MapLibre 打点可见 geo 条目。
 * 底图用本地空白样式（不依赖外部瓦片服务）；数据来自 /knowledge/geo
 * （服务端已按可见性与 radius/bbox 过滤，前端不重复判权）。
 */
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { message } from 'ant-design-vue'
import { Map as MaplibreMap, Marker, Popup, AttributionControl } from 'maplibre-gl'
import GlassButton from '@/components/GlassButton.vue'
import { request } from '@/api'

const props = defineProps<{
  nodes?: Array<{ id: string; label: string; type: string }>
  agentId?: string
}>()

const { t } = useI18n()
const mapRef = ref<HTMLElement | null>(null)
const loading = ref(false)
const lat = ref('')
const lon = ref('')
const radiusKm = ref('')
const items = ref<Array<{ knowledge_id: string; title: string; geo: { lat: number; lon: number } }>>([])
const nodeGeo = ref<Array<{ node_id: string; label: string; type: string; geo: { lat: number; lon: number } }>>([])
const emptyReason = computed(() => {
  if ((props.nodes?.length ?? 0) > 0 || nodeGeo.value.length || items.value.length) {
    return t('knowledge.workbenchNoGeoNodesHint')
  }
  return t('knowledge.workbenchNoGeoItems')
})
const mapFailed = ref(false)

let map: MaplibreMap | null = null
let markers: Marker[] = []

const fetchGeo = async () => {
  if (mapFailed.value) return
  loading.value = true
  try {
    const params: Record<string, unknown> = {}
    if (lat.value.trim() && lon.value.trim() && radiusKm.value.trim()) {
      params.lat = lat.value
      params.lon = lon.value
      params.radius_km = radiusKm.value
    }
    const res: any = await request.get('/knowledge/geo', { params })
    items.value = res?.data?.items ?? []
    if (props.agentId) {
      try {
        const nr: any = await request.get(
          `/knowledge-graph/${props.agentId}/spatial-nodes`)
        nodeGeo.value = nr?.data ?? []
      } catch {
        nodeGeo.value = []
      }
    }
    renderMarkers()
  } catch (e: any) {
    message.error(e?.response?.data?.detail || e?.message || t('common.error'))
  } finally {
    loading.value = false
  }
}

const clearFilter = () => {
  lat.value = ''
  lon.value = ''
  radiusKm.value = ''
  void fetchGeo()
}

const renderMarkers = () => {
  markers.forEach((m) => m.remove())
  markers = []
  for (const item of items.value) {
    if (!item.geo?.lat || !item.geo?.lon) continue
    const el = document.createElement('div')
    el.className = 'geo-marker'
    el.textContent = '📍'
    el.title = item.title
    markers.push(
      new Marker({ element: el })
        .setLngLat([item.geo.lon, item.geo.lat])
        .setPopup(new Popup({ offset: 12 }).setText(item.title))
        .addTo(map!),
    )
  }
  // 图谱节点标记（社区/类型着色由节点自身语义决定，这里用固定异形标记区分）
  for (const node of nodeGeo.value) {
    if (!node.geo?.lat || !node.geo?.lon) continue
    const el = document.createElement('div')
    el.className = 'geo-marker geo-marker-node'
    el.textContent = '◉'
    el.title = node.label
    markers.push(
      new Marker({ element: el })
        .setLngLat([node.geo.lon, node.geo.lat])
        .setPopup(new Popup({ offset: 12 }).setText(node.label))
        .addTo(map!),
    )
  }
  const allPoints = [
    ...items.value.map((i) => i.geo).filter((g) => g?.lat && g?.lon),
    ...nodeGeo.value.map((n) => n.geo).filter((g) => g?.lat && g?.lon),
  ]
  if (allPoints.length === 1 && map) {
    map.flyTo({ center: [allPoints[0].lon, allPoints[0].lat], zoom: 5 })
  } else if (allPoints.length > 1 && map) {
    const lons = allPoints.map((g) => g.lon)
    const lats = allPoints.map((g) => g.lat)
    map.fitBounds(
      [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      { padding: 60, maxZoom: 8 },
    )
  }
}

onMounted(async () => {
  if (!mapRef.value) return
  // 本地空白底图：不依赖外部瓦片——离线/内网可用，地理渲染不打外网。
  // WebGL 缺席（旧显卡/无 GPU 环境）降级为提示，不 unhandled、不白屏。
  try {
  map = new MaplibreMap({
    container: mapRef.value,
    style: {
      version: 8,
      sources: {},
      layers: [
        { id: 'bg', type: 'background', paint: { 'background-color': 'rgba(0,0,0,0.2)' } },
      ],
    },
    center: [104.0, 35.0],
    zoom: 2,
    attributionControl: false,
  })
  } catch {
    mapFailed.value = true
    return
  }
  await fetchGeo()
})

onBeforeUnmount(() => {
  markers.forEach((m) => m.remove())
  markers = []
  map?.remove()
  map = null
})
</script>

<style scoped>
.geo-map-panel {
  display: flex;
  flex-direction: column;
  gap: var(--nr-space-sm);
}

.geo-toolbar {
  display: flex;
  align-items: center;
  gap: var(--nr-space-sm);
}

.geo-input {
  width: 120px;
}

.geo-input-narrow {
  width: 96px;
}

.geo-map {
  height: 420px;
  border: 1px solid var(--nr-glass-border);
  border-radius: var(--nr-radius-md, 12px);
  overflow: hidden;
}

.geo-marker-node {
  color: var(--nr-primary-light, #818cf8);
  font-size: 14px;
  line-height: 18px;
  text-align: center;
}

.geo-empty {
  position: absolute;
  inset: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  pointer-events: none;
}

.geo-marker {
  font-size: 20px;
  cursor: pointer;
}
</style>
