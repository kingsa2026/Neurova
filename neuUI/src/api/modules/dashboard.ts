import { request } from '@/api'

export const dashboardAPI = {
  getHomeData: () => request.get('/home/data'),
  getTrends: (days = 7) => request.get(`/home/trends?days=${days}`),
  getSystemStats: () => request.get('/stats/system'),
}
