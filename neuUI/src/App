&lt;template&gt;
  &lt;div id="app"&gt;
    &lt;router-view /&gt;
  &lt;/div&gt;
&lt;/template&gt;
&lt;script setup lang="ts"&gt;
import { onMounted } from 'vue'
import { useRouter } from 'vue-router'
const router = useRouter()
onMounted(() =&gt; {
  // 检查是否需要登录
  const token = localStorage.getItem('token')
  const currentPath = window.location.pathname
  if (!token &amp;&amp; currentPath !== '/login') {
    router.push({ name: 'Login', query: { redirect: currentPath } })
  }
})
&lt;/script&gt;
&lt;style&gt;
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}
body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial,
    'Noto Sans', sans-serif, 'Apple Color Emoji', 'Segoe UI Emoji', 'Segoe UI Symbol',
    'Noto Color Emoji';
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
#app {
  width: 100%;
  min-height: 100vh;
}
&lt;/style&gt;
&nbsp;