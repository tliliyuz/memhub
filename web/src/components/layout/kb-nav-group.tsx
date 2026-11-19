/**
 * 侧边栏「知识库」分组：每个知识库是一个可展开条目，子项是概览 / 节点 / 图谱。
 * 数据来自 /api/v1/kb/projects，新建知识库后随 query 失效自动出现。
 */

import { useQuery } from '@tanstack/react-query'
import {
  BookOpenText,
  Database,
  GitFork,
  Layers,
  LayoutDashboard,
  Network,
} from 'lucide-react'
import { api } from '@/lib/api'
import { NavGroup } from './nav-group'
import type { NavItem } from './types'

export function KbNavGroup() {
  const projects = useQuery({ queryKey: ['projects'], queryFn: api.projects })
  const kbs = projects.data?.items ?? []

  const items: NavItem[] = [
    { title: '全部知识库', url: '/', icon: LayoutDashboard },
    ...kbs.map<NavItem>((kb) => ({
      title: kb.name,
      icon: Database,
      badge: String(kb.nodes),
      items: [
        {
          title: '概览',
          url: `/kb/${kb.id}`,
          icon: LayoutDashboard,
        },
        {
          title: '节点',
          url: `/kb/${kb.id}/nodes`,
          icon: BookOpenText,
        },
        {
          title: '图谱',
          url: `/kb/${kb.id}/graph`,
          icon: GitFork,
        },
      ],
    })),
    { title: '全部节点', url: '/nodes', icon: Layers },
    { title: '全局图谱', url: '/graph', icon: Network },
  ]

  return <NavGroup title='知识库' items={items} />
}
