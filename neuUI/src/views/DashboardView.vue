<template>
  <div >
    <StarBackground />
    <div >
      <div >
        <h1 >欢迎回来</h1>
        <p >开始您的智能之旅</p>
      </div>
      <div >
        <p >
          您好，{{ authStore.currentUser?.username || '用户' }}！
        </p>
        <div >
          <div >
            <div >🤖</div>
            <h3 >创建 Agent</h3>
            <p >创建您的专属智能伙伴</p>
          </div>
          <div >
            <div >💬</div>
            <h3 >开始对话</h3>
            <p >与您的 Agent 交流</p>
          </div>
          <div >
            <div >📚</div>
            <h3 >知识库</h3>
            <p >管理您的知识资源</p>
          </div>
        </div>
        <a-button
          type="primary"
          @click="handleLogout"
        >
          退出登录
        </a-button>
      </div>
    </div>
  </div>
</template>
<script setup lang="ts">
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import StarBackground from '@/components/StarBackground.vue'
const router = useRouter()
const authStore = useAuthStore()
onMounted(() => {
  authStore.restoreUser()
})
async function handleLogout() {
  await authStore.logout()
  router.push('/login')
}
</script>
<style scoped>
.dashboard-container {
  position: relative;
  width: 100vw;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
}
.dashboard-content {
  position: relative;
  z-index: 10;
  width: 800px;
  padding: 3rem;
  animation: fadeInUp 0.6s ease-out;
}
@keyframes fadeInUp {
  from {
    opacity: 0;
    transform: translateY(30px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
.dashboard-header {
  text-align: center;
  margin-bottom: 3rem;
}
.dashboard-header h1 {
  font-size: 2.5rem;
  font-weight: 700;
  margin-bottom: 0.5rem;
}
.subtitle {
  color: rgba(255, 255, 255, 0.6);
  font-size: 1.1rem;
}
.dashboard-body {
  text-align: center;
}
.welcome-text {
  font-size: 1.25rem;
  color: rgba(255, 255, 255, 0.8);
  margin-bottom: 2rem;
}
.action-cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 1.5rem;
  margin-bottom: 3rem;
}
.action-card {
  padding: 2rem;
  text-align: center;
  cursor: pointer;
}
.card-icon {
  font-size: 2.5rem;
  margin-bottom: 1rem;
}
.card-title {
  font-size: 1.25rem;
  font-weight: 600;
  color: #ffffff;
  margin-bottom: 0.5rem;
}
.card-desc {
  color: rgba(255, 255, 255, 0.6);
  font-size: 0.95rem;
}
.logout-button {
  margin-top: 2rem;
}
@media (max-width: 768px) {
  .dashboard-content {
    width: 90%;
    padding: 2rem 1.5rem;
  }
  .dashboard-header h1 {
    font-size: 2rem;
  }
  .action-cards {
    grid-template-columns: 1fr;
  }
}
</style>
 