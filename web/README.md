# memhub-web — 本地知识库管理台

kb-api（`memhub kb`，默认 `127.0.0.1:8701`）托管的前端：知识库概览、节点列表与检索、节点详情编辑（标题/正文/标签/层级/置信度）、出边编辑、废弃与归档删除、回收站恢复、治理审计、知识图谱（semantica explorer iframe）。

## 来源与许可

- 脚手架与 UI 组件复用自 **DynamicFocusGroup/apps/web**，其底层是 [satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin)（commit `e16c87f`），MIT License，版权归 Sat Naing。完整许可见 [LICENSE](./LICENSE)。
- 复用范围：`src/components/ui/*`、`src/components/data-table/*`、布局（sidebar/header/main/nav-*）、context、hooks、`src/lib/{utils,cookies,search-params}`、`src/styles/*`、TanStack Router + Query 配置。
- 改动：导航与主题换成 memhub 的（概览/节点/图谱/审计/回收站），去掉认证与权限守卫、去掉了未使用的 `input-otp`，业务页面全部重写（对接 kb-api），表格默认中文文案。

### 本仓库相对 DFG 的额外改动（同步上游时先看这段）

- `components/ui/*`：零改动。
- `components/data-table/*`：沿用 DFG 的服务端分页 + `rowCount` + 中文文案，**本仓库未再改**；若将来要改，先在这里记一条，避免两边 diff 漂移。
- `components/layout/nav-user.tsx`：菜单换成「后端健康状态 + 重建投影」，不涉及用户体系。
- 删除未引用组件：`ui/input-otp.tsx`（DFG 也只在 auth 演示路由用）。
- 依赖：比 DFG 多 `react-top-loading-bar@^3.0.2`（`NavigationProgress` 需要），少认证相关包。

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

图谱页 iframe 默认指向 `http://127.0.0.1:8703/`，可用 `VITE_GRAPH_URL` 覆盖。

## 与后端的分工

- 前端不持有任何真源状态：列表/详情来自 kb-api，写操作带 `expected_revision`（冲突 409 / `1010` 时提示刷新）。
- 删除是归档到 `_trash/`；「废弃」不删文件，只改 tier 与 `superseded_by`。
- 投影（`kg.json`）由后端重建，前端只触发 `POST /api/v1/kb/rebuild` 并刷新 iframe。
- 接口细节见 [../docs/contracts/kb-admin-api.md](../docs/contracts/kb-admin-api.md)。

## 目录速览

```
src/routes/           文件路由（_app.index / _app.nodes.index / _app.nodes.$ / _app.graph / _app.audit / _app.trash）
src/lib/api.ts        带类型的 kb-api 客户端
src/components/ui     shadcn 组件（上游原样）
src/components/data-table  表格工具（上游，服务端分页 + 中文）
src/components/layout      应用外壳（侧栏、页头、NavUser=健康状态+重建按钮）
```
