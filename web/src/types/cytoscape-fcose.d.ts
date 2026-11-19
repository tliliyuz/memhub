// cytoscape-fcose 不自带类型，只导出 cytoscape 扩展注册函数。
declare module 'cytoscape-fcose' {
  import cytoscape from 'cytoscape'

  const extension: cytoscape.Ext
  export default extension
}
