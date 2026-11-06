// three 的类型占位：3d-force-graph 的 peer dependency，本仓不直消费其 API 面——
// GraphExplorer3D 的 nodeThreeObject/linkDirectionalParticles 通过动态 import
// 拿到运行时对象后以 any 传参，此处声明模块存在避免 TS7016。
// 若将来需要完整 three 类型面，安装 `@types/three` 后删除本文件。
declare module 'three' {
  export const AmbientLight: any
  export const DirectionalLight: any
  export const PointLight: any
  export const SphereGeometry: any
  export const MeshStandardMaterial: any
  export const MeshBasicMaterial: any
  export const Mesh: any
  export const Group: any
  export const Sprite: any
  export const SpriteMaterial: any
  export const CanvasTexture: any
  export const BackSide: any
  const three: Record<string, any>
  export default three
}
