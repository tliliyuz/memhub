import {
  Activity,
  Brain,
  Database,
  Layers,
  LayoutDashboard,
  Network,
  ShieldCheck,
  Trash2,
} from 'lucide-react'
import { type SidebarData } from '../types'

export const sidebarData: SidebarData = {
  user: {
    name: '本地管理台',
    email: '127.0.0.1:8701',
    avatar: '',
  },
  teams: [
    {
      name: 'memhub',
      logo: LayoutDashboard,
      plan: '知识库 2.0',
    },
  ],
  // 知识库不在侧栏平铺：入口只有「全部知识库」页，库内层级在页面里展开。
  navGroups: [
    {
      title: '知识',
      items: [
        { title: '全部知识库', url: '/', icon: Database },
        { title: '全部节点', url: '/nodes', icon: Layers },
        { title: '全局图谱', url: '/graph', icon: Network },
      ],
    },
    {
      title: '治理',
      items: [
        { title: '审计', url: '/audit', icon: ShieldCheck },
        { title: '调用轨迹', url: '/traces', icon: Activity },
        { title: '长期记忆', url: '/memories', icon: Brain },
        { title: '回收站', url: '/trash', icon: Trash2 },
      ],
    },
  ],
}
