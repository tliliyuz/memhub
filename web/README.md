# memhub-web — 本地知识库管理台

kb-api（`memhub kb`，默认 `127.0.0.1:8701`）托管的前端：**按知识库隔离**的导航（每个库有自己的概览/节点/图谱）、节点列表与检索、节点详情编辑（标题/正文/标签/层级/置信度）、出边编辑、废弃与归档删除、回收站恢复、治理审计，以及基于 Cytoscape + fCoSE 自绘的知识图谱（数据直接读真源，不再内联 semantica explorer）。

## 来源与许可

- 脚手架与 UI 组件复用自 **DynamicFocusGroup/apps/web**，其底层是 [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin)（commit `e16c87f`），MIT License，版权归 Sat Naing。完整许可见 [LICENSE](./LICENSE)。
- 复用范围：`src/components/ui/*`、`src/components/data-table/*`、布局（sidebar/header/main/nav-*）、context、hooks、`src/lib/{utils,cookies,search-params}`、`src/styles/*`、TanStack Router + Query 配置。
- 改动：导航与主题换成 memhub 的（知识库列表 → 每库概览/节点/图谱，外加全部节点/全局图谱/审计/回收站），去掉认证与权限守卫、去掉了未使用的 `input-otp`，业务页面全部重写（对接 kb-api），表格默认中文文案。

### 本仓库相对 DFG 的额外改动（同步上游时先看这段）

- `components/ui/*`：零改动。
- `components/data-table/*`：沿用 DFG 的服务端分页 + `rowCount` + 中文文案，**本仓库未再改**；若将来要改，先在这里记一条，避免两边 diff 漂移。
- `components/layout/nav-user.tsx`：菜单换成「后端健康状态 + 重建投影」，不涉及用户体系。
- 删除未引用组件：`ui/input-otp.tsx`（DFG 也只在 auth 演示路由用）。
- 依赖：比 DFG 多 `react-top-loading-bar@^3.0.2`（`NavigationProgress` 需要）与 `cytoscape@3.35` + `cytoscape-fcose@2.2`（自绘图谱），少认证相关包。`cytoscape-fcose` 不带类型，`src/types/cytoscape-fcose.d.ts` 里补了一条 `Ext` 声明。

新增 shadcn 组件仍可用：

```bash
pnpm dlx shadcn@latest add <component>   # components.json 已按上游配置（new-york / slate / cssVariables）
```

## 开发

```bash
pnpm install
pnpm dev        # http://127.0.0.1:5173 ，/api 代理到 127.0.0.1:8701
pnpm build      # tsc -b && vite build → dist/
pnpm typecheck
```

构建产物 `dist/` 由 kb-api 托管：

```bash
memhub kb --knowledge-dir ./knowledge --graph-out kb/kg.json --web-dist web/dist
```

图谱数据来自 `GET /api/v1/kb/graph?project=<库>`：节点数 ≤60 时直接显示标签，更大的图只在枢纽/命中搜索/悬停邻域时显示标签；节点按 kind 上色、按度数定大小，支持类型过滤、隐藏废弃/孤立、搜索与重新布局。全局图谱（`/graph`）把各库子图合并显示，按知识库配色。

## 与后端的分工

- 前端不持有任何真源状态：列表/详情来自 kb-api，写操作带 `expected_revision`（冲突 409 / `1010` 时提示刷新）。
- 删除是归档到 `_trash/`；「废弃」不删文件，只改 tier 与 `superseded_by`。
- 投影（`kg.json`，供 MCP / semantica explorer 使用）由后端重建，前端只触发 `POST /api/v1/kb/rebuild`；管理台的图谱不依赖它，直接读 `/api/v1/kb/graph`。
- 接口细节见 [../docs/contracts/kb-admin-api.md](../docs/contracts/kb-admin-api.md)。

## 目录速览

```
src/routes/           文件路由（_app.index=知识库列表 / _app.kb.$project.{index,nodes,graph} /
                      _app.nodes.index / _app.nodes.$ / _app.graph=全局图谱 / _app.audit / _app.trash）
src/components/graph/graph-canvas.tsx   Cytoscape 图谱画布（布局、配色、过滤、搜索）
src/components/nodes/nodes-browser.tsx  节点表格（全局与单库复用）
src/components/layout/kb-nav-group.tsx  侧栏动态知识库分组
src/lib/api.ts        带类型的 kb-api 客户端
src/components/ui     shadcn 组件（上游原样）
src/components/data-table  表格工具（上游，服务端分页 + 中文）
src/components/layout      应用外壳（侧栏、页头、NavUser=健康状态+重建按钮）
```
