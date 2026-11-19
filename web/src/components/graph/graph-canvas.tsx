/**
 * 知识图谱画布（Cytoscape + fCoSE）。
 *
 * 取代之前内联的 semantica explorer：布局、配色、标签密度都由管理台控制，
 * 数据来自 `/api/v1/kb/graph?project=` —— 一个知识库一份子图，不混库。
 *
 * 可读性约定：
 * - 颜色按 kind（或按知识库）区分，大小按度数；
 * - 节点多的时候标签随缩放出现，命中搜索/悬停邻域/选中节点始终显示；
 * - 悬停只高亮邻域，其余元素淡出，避免一团线。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import cytoscape, {
  type Core,
  type ElementDefinition,
  type NodeSingular,
  type StylesheetJson,
} from 'cytoscape'
import fcose from 'cytoscape-fcose'
import { Crosshair, Maximize2, RotateCcw, Search as SearchIcon } from 'lucide-react'
import { KINDS, type GraphEdge, type GraphNode, type Kind } from '@/lib/api'
import { cn } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { useTheme } from '@/context/theme-provider'

export type GraphCanvasNode = GraphNode & { project?: string }

type GraphCanvasProps = {
  nodes: GraphCanvasNode[]
  edges: GraphEdge[]
  colorBy?: 'kind' | 'project'
  projects?: { id: string; name: string }[]
  selectedId?: string | null
  onSelect?: (node: GraphCanvasNode | null) => void
  className?: string
}

let fcoseRegistered = false

const KIND_COLORS: Record<Kind, { light: string; dark: string }> = {
  entity: { light: '#2563eb', dark: '#60a5fa' },
  fact: { light: '#0d9488', dark: '#2dd4bf' },
  decision: { light: '#7c3aed', dark: '#a78bfa' },
  procedure: { light: '#c2410c', dark: '#fb923c' },
  pitfall: { light: '#dc2626', dark: '#f87171' },
  preference: { light: '#a16207', dark: '#facc15' },
  event: { light: '#0891b2', dark: '#22d3ee' },
  question: { light: '#db2777', dark: '#f472b6' },
}

const PROJECT_COLORS = ['#2563eb', '#0d9488', '#7c3aed', '#c2410c', '#db2777', '#0891b2', '#a16207', '#4d7c0f']

function kindLabel(kind: Kind): string {
  return KINDS.find((item) => item.value === kind)?.label ?? kind
}

function projectColor(index: number): string {
  return PROJECT_COLORS[index % PROJECT_COLORS.length]
}

type ElementColors = (node: GraphCanvasNode) => string

function buildElements(
  nodes: GraphCanvasNode[],
  edges: GraphEdge[],
  colorOf: ElementColors,
): ElementDefinition[] {
  const ids = new Set(nodes.map((node) => node.id))
  const elements: ElementDefinition[] = nodes.map((node) => ({
    group: 'nodes',
    data: {
      id: node.id,
      title: node.title,
      kind: node.kind,
      tier: node.tier,
      degree: node.degree,
      project: node.project ?? '',
      color: colorOf(node),
      size: 22 + Math.min(26, Math.sqrt(node.degree) * 12),
      display: '',
      node,
    },
    classes: `k-${node.kind}${node.tier === 'deprecated' ? ' deprecated' : ''}${node.degree === 0 ? ' orphan' : ''}`,
  }))

  edges.forEach((edge, index) => {
    if (!ids.has(edge.source) || !ids.has(edge.target)) return
    const element: ElementDefinition = {
      group: 'edges',
      data: {
        id: `e:${index}:${edge.source}->${edge.target}:${edge.predicate}`,
        source: edge.source,
        target: edge.target,
        predicate: edge.predicate,
        displayEdge: '',
        edge,
      },
      classes: 'rel',
    }
    elements.push(element)
  })
  return elements
}

function buildStyles(theme: 'light' | 'dark'): StylesheetJson {
  const dark = theme === 'dark'
  const bg = dark ? '#0b1220' : '#ffffff'
  const fg = dark ? '#e2e8f0' : '#1e293b'
  const muted = dark ? '#64748b' : '#94a3b8'
  const accent = dark ? '#fbbf24' : '#d97706'

  return [
    {
      selector: 'node',
      style: {
        'background-color': 'data(color)',
        'border-width': 2,
        'border-color': bg,
        width: 'data(size)',
        height: 'data(size)',
        label: 'data(display)',
        'font-size': 9,
        'font-weight': 500,
        color: fg,
        'text-valign': 'bottom',
        'text-halign': 'center',
        'text-margin-y': 4,
        'text-max-width': '120px',
        'text-wrap': 'ellipsis',
        'text-outline-width': 2,
        'text-outline-color': bg,
        'overlay-opacity': 0,
      },
    },
    { selector: 'node.hub', style: { 'border-width': 3 } },
    { selector: 'node.deprecated', style: { opacity: 0.35 } },
    { selector: 'node.faded', style: { opacity: 0.12 } },
    {
      selector: 'node.match',
      style: { 'border-color': accent, 'border-width': 4 },
    },
    {
      selector: 'node:selected',
      style: { 'border-color': fg, 'border-width': 4 },
    },
    {
      selector: 'edge',
      style: {
        width: 1,
        'line-color': muted,
        'target-arrow-color': muted,
        'target-arrow-shape': 'triangle',
        'curve-style': 'bezier',
        'arrow-scale': 0.7,
        opacity: 0.28,
        label: 'data(displayEdge)',
        'font-size': 7,
        color: muted,
        'text-rotation': 'autorotate',
        'text-background-color': bg,
        'text-background-opacity': 0.9,
        'text-background-padding': '1px',
        'text-outline-width': 0,
      },
    },
    { selector: 'edge.faded', style: { opacity: 0.04 } },
    {
      selector: 'edge.highlighted',
      style: { 'line-color': accent, 'target-arrow-color': accent, opacity: 1 },
    },
    { selector: '.hidden', style: { display: 'none' } },
  ]
}

function layoutOptions(randomize: boolean) {
  return {
    name: 'fcose',
    quality: 'default',
    animate: false,
    randomize,
    fit: true,
    padding: 36,
    nodeSeparation: 90,
    idealEdgeLength: 90,
    nodeRepulsion: (node: NodeSingular) =>
      Number(node.data('degree')) >= 4 ? 24000 : 9000,
    gravity: 0.25,
    numIter: 2500,
    packComponents: true,
    tile: false,
  } as unknown as cytoscape.LayoutOptions
}

export function GraphCanvas({
  nodes,
  edges,
  colorBy = 'kind',
  projects = [],
  selectedId = null,
  onSelect,
  className,
}: GraphCanvasProps) {
  const { resolvedTheme } = useTheme()
  const containerRef = useRef<HTMLDivElement>(null)
  const cyRef = useRef<Core | null>(null)
  const onSelectRef = useRef(onSelect)
  const [query, setQuery] = useState('')
  const [activeKinds, setActiveKinds] = useState<Set<Kind>>(
    () => new Set(KINDS.map((item) => item.value)),
  )
  const [hideDeprecated, setHideDeprecated] = useState(false)
  const [hideOrphans, setHideOrphans] = useState(false)
  const [matchCount, setMatchCount] = useState(0)

  onSelectRef.current = onSelect

  const projectIndex = useMemo(
    () => new Map(projects.map((item, index) => [item.id, index])),
    [projects],
  )

  const colorOf = (node: GraphCanvasNode): string => {
    if (colorBy === 'project') {
      return projectColor(projectIndex.get(node.project ?? '') ?? 0)
    }
    return KIND_COLORS[node.kind][resolvedTheme]
  }

  // 建画布只做一次；数据和主题各自同步。
  useEffect(() => {
    if (!containerRef.current) return
    if (!fcoseRegistered) {
      cytoscape.use(fcose)
      fcoseRegistered = true
    }
    const cy = cytoscape({
      container: containerRef.current,
      style: buildStyles(resolvedTheme),
      elements: [],
      wheelSensitivity: 0.2,
      minZoom: 0.08,
      maxZoom: 4,
    })
    cyRef.current = cy
    // 调试/自动化定位用：容器元素上挂一份实例，不参与渲染。
    ;(containerRef.current as HTMLElement & { __cy?: Core }).__cy = cy

    const applyLabels = () => {
      const showAll = cy.nodes().length <= 60 || cy.zoom() >= 0.75
      const showEdges = cy.zoom() >= 1.35
      cy.batch(() => {
        cy.nodes().forEach((node) => {
          const show =
            showAll ||
            node.hasClass('hub') ||
            node.hasClass('match') ||
            node.selected()
          node.data('display', show ? String(node.data('title')) : '')
        })
        cy.edges().forEach((edge) => {
          edge.data(
            'displayEdge',
            showEdges || edge.selected() || edge.hasClass('highlighted')
              ? String(edge.data('predicate'))
              : '',
          )
        })
      })
    }

    const clearHighlight = () => {
      cy.elements().removeClass('faded highlighted')
      applyLabels()
    }

    cy.on('zoom', () => applyLabels())
    // 布局结束时画布尺寸可能刚稳定，重新 fit 一次，避免图缩在角落。
    cy.on('layoutstop', () => {
      cy.resize()
      cy.fit(cy.elements().filter(':visible'), 40)
      applyLabels()
    })
    const observer = new ResizeObserver(() => cy.resize())
    observer.observe(containerRef.current)
    cy.on('mouseover', 'node', (event) => {
      const node = event.target as NodeSingular
      const hood = node.closedNeighborhood()
      cy.elements().addClass('faded')
      hood.removeClass('faded')
      hood.edges().addClass('highlighted')
      cy.batch(() => {
        hood.nodes().forEach((item) => {
          item.data('display', String(item.data('title')))
        })
      })
    })
    cy.on('mouseout', 'node', clearHighlight)
    cy.on('tap', 'node', (event) => {
      const node = event.target as NodeSingular
      onSelectRef.current?.(node.data('node') as GraphCanvasNode)
    })
    cy.on('tap', (event) => {
      if (event.target === cy) onSelectRef.current?.(null)
    })

    ;(cy as Core & { applyLabels?: () => void }).applyLabels = applyLabels

    return () => {
      observer.disconnect()
      cy.destroy()
      cyRef.current = null
    }
    // 只初始化一次；主题/数据在下面的 effect 里同步。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const applyLabels = () => {
    const cy = cyRef.current as (Core & { applyLabels?: () => void }) | null
    cy?.applyLabels?.()
  }

  // 数据变化：重建元素并重新布局。
  const elementsKey = useMemo(
    () =>
      JSON.stringify({
        nodes: nodes.map((node) => [node.id, node.degree, node.kind, node.tier]),
        edges: edges.map((edge) => [edge.source, edge.target, edge.predicate]),
        colorBy,
        theme: resolvedTheme,
        order: projects.map((item) => item.id),
      }),
    [nodes, edges, colorBy, resolvedTheme, projects],
  )

  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const elements = buildElements(nodes, edges, colorOf)
    cy.batch(() => {
      cy.elements().remove()
      cy.add(elements)
      cy.nodes().forEach((node) => {
        if (Number(node.data('degree')) >= 8) node.addClass('hub')
      })
    })
    cy.style(buildStyles(resolvedTheme))
    cy.layout(layoutOptions(true)).run()
    applyLabels()
    // colorOf 依赖同一次渲染的数据，elementsKey 已覆盖其输入。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [elementsKey])

  // 选中节点：同步 selection 并居中。
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.nodes().unselect()
    if (!selectedId) return
    const node = cy.getElementById(selectedId)
    if (node.length === 0) return
    node.select()
    node.data('display', String(node.data('title')))
    cy.animate({ center: { eles: node } }, { duration: 250 })
  }, [selectedId])

  // 过滤：按 kind / 废弃状态加 hidden。
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    cy.batch(() => {
      cy.nodes().forEach((node) => {
        const kind = node.data('kind') as Kind
        const hidden =
          !activeKinds.has(kind) ||
          (hideDeprecated && node.data('tier') === 'deprecated') ||
          (hideOrphans && node.hasClass('orphan'))
        node.toggleClass('hidden', hidden)
      })
    })
    applyLabels()
  }, [activeKinds, hideDeprecated, hideOrphans, elementsKey])

  // 搜索：高亮命中并显示它们的标签。
  useEffect(() => {
    const cy = cyRef.current
    if (!cy) return
    const needle = query.trim().toLowerCase()
    cy.batch(() => {
      cy.nodes().removeClass('match')
      if (!needle) return
      cy.nodes().forEach((node) => {
        const hay = [node.data('title'), node.data('id'), node.data('project')]
          .join(' ')
          .toLowerCase()
        if (hay.includes(needle)) {
          node.addClass('match')
          node.data('display', String(node.data('title')))
        }
      })
    })
    const matches = cy.nodes('.match')
    setMatchCount(matches.length)
    if (matches.length === 1 && needle.length >= 2) {
      cy.animate({ fit: { eles: matches, padding: 120 } }, { duration: 250 })
    }
    applyLabels()
  }, [query, elementsKey])

  const fitAll = () => {
    cyRef.current?.animate({ fit: { eles: cyRef.current.elements(), padding: 36 } }, { duration: 300 })
  }

  const relayout = () => {
    const cy = cyRef.current
    if (!cy) return
    cy.layout(
      layoutOptions(false) as unknown as cytoscape.LayoutOptions,
    ).run()
    const showAll = cy.nodes().length <= 60 || cy.zoom() >= 0.75
    cy.nodes().forEach((node) => {
      const show =
        showAll || node.hasClass('hub') || node.hasClass('match') || node.selected()
      node.data('display', show ? String(node.data('title')) : '')
    })
  }

  const toggleKind = (kind: Kind) => {
    setActiveKinds((current) => {
      const next = new Set(current)
      if (next.has(kind)) next.delete(kind)
      else next.add(kind)
      return next
    })
  }

  const kindCounts = useMemo(() => {
    const counts = new Map<Kind, number>()
    for (const node of nodes) {
      counts.set(node.kind, (counts.get(node.kind) ?? 0) + 1)
    }
    return counts
  }, [nodes])

  return (
    <div className={cn('relative min-h-0 overflow-hidden', className)}>
      {/* cytoscape 会注入 `.__________cytoscape_container { position: relative }`（未分层样式，
          优先级高于 Tailwind utilities），所以这里不能用 absolute 定位，交给 size-full 撑满。 */}
      <div ref={containerRef} className='size-full' />

      <div className='pointer-events-none absolute inset-x-0 top-0 flex flex-wrap items-start justify-between gap-2 p-3'>
        <div className='pointer-events-auto flex max-w-[min(100%,42rem)] flex-wrap items-center gap-1.5 rounded-md border bg-background/85 p-1.5 shadow-sm backdrop-blur'>
          <div className='relative'>
            <SearchIcon className='pointer-events-none absolute top-1.5 left-2 size-3.5 text-muted-foreground' />
            <Input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder='搜索标题…'
              className='h-7 w-44 pl-7 text-xs'
            />
          </div>
          {KINDS.filter((item) => (kindCounts.get(item.value) ?? 0) > 0).map(
            (item) => {
              const active = activeKinds.has(item.value)
              return (
                <button
                  key={item.value}
                  type='button'
                  onClick={() => toggleKind(item.value)}
                  className={cn(
                    'flex items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] transition',
                    active
                      ? 'border-border bg-background text-foreground'
                      : 'border-transparent bg-muted text-muted-foreground opacity-60',
                  )}
                >
                  {colorBy === 'kind' && (
                    <span
                      className='size-2 rounded-full'
                      style={{ backgroundColor: KIND_COLORS[item.value][resolvedTheme] }}
                    />
                  )}
                  {item.label}
                  <span className='text-muted-foreground'>
                    {kindCounts.get(item.value)}
                  </span>
                </button>
              )
            },
          )}
          <label className='flex items-center gap-1 rounded px-1 text-[11px] text-muted-foreground'>
            <input
              type='checkbox'
              checked={hideDeprecated}
              onChange={(event) => setHideDeprecated(event.target.checked)}
              className='size-3'
            />
            隐藏废弃
          </label>
          <label className='flex items-center gap-1 rounded px-1 text-[11px] text-muted-foreground'>
            <input
              type='checkbox'
              checked={hideOrphans}
              onChange={(event) => setHideOrphans(event.target.checked)}
              className='size-3'
            />
            隐藏孤立
          </label>
        </div>

        <div className='pointer-events-auto flex items-center gap-1 rounded-md border bg-background/85 p-1 shadow-sm backdrop-blur'>
          {query.trim() && (
            <Badge variant='secondary' className='mx-1 text-[11px]'>
              匹配 {matchCount}
            </Badge>
          )}
          <Button variant='ghost' size='icon' className='size-7' title='适应画布' onClick={fitAll}>
            <Maximize2 className='size-3.5' />
          </Button>
          <Button variant='ghost' size='icon' className='size-7' title='重新布局' onClick={relayout}>
            <RotateCcw className='size-3.5' />
          </Button>
          <span className='px-1 text-[10px] text-muted-foreground'>
            {nodes.length} 节点 · {edges.length} 边
          </span>
        </div>
      </div>

      {colorBy === 'project' && projects.length > 0 && (
        <div className='pointer-events-none absolute bottom-2 left-3 flex flex-wrap gap-2 rounded-md border bg-background/85 px-2 py-1 text-[11px] shadow-sm backdrop-blur'>
          {projects.map((item, index) => (
            <span key={item.id} className='flex items-center gap-1'>
              <span
                className='size-2 rounded-full'
                style={{ backgroundColor: projectColor(index) }}
              />
              {item.name}
            </span>
          ))}
        </div>
      )}

      {nodes.length === 0 && (
        <div className='pointer-events-none absolute inset-0 flex flex-col items-center justify-center gap-2 text-sm text-muted-foreground'>
          <Crosshair className='size-8 opacity-40' />
          <span>这个知识库还没有节点</span>
        </div>
      )}

    </div>
  )
}

export { KIND_COLORS, kindLabel, projectColor }
