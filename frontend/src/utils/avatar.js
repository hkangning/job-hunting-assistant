/** 头像工具：默认头像（用户名首字 + 哈希底色）与上传前压缩（SRS §3.14 头像规则）。 */
/** 底色品牌化：主色相（约 215°）7 档明度变体，白字对比度均 ≥4.5:1（最低 4.78）。
    原为「旧主色 + 模块色」七色——与全站更协调，2026-09-29 随主色改版收敛。 */
const PALETTE = ['#2F5B9E', '#3B6DB0', '#2A538C', '#4274B4', '#35618F', '#2E6E96', '#3E5F9E']

/** 字符累加哈希：稳定优先于均匀——同一用户名在任何位置同色即可。 */
export function defaultAvatar(name = '?') {
  const text = String(name || '?')
  let hash = 0
  for (const ch of text) hash = (hash + ch.codePointAt(0)) % 100000
  return { text: text.trim().charAt(0).toUpperCase() || '?', color: PALETTE[hash % PALETTE.length] }
}

/** 头像相对路径 → 可渲染 URL。
 *
 * 后端把 `uploads/` 挂在 `/uploads` 静态路径下，库中存的就是 `uploads/avatars/x.png`，
 * 故直接拼前导斜杠即可访问，不做任何路径改写（接口文档 §3.2）。
 */
export const avatarUrl = (avatar) => (avatar ? '/' + avatar : null)

/** canvas 压缩至 256×256 居中裁切，输出 jpeg Blob（约 20~50KB，满足后端 ≤2MB 校验）。 */
export function compressTo256(file) {
  return new Promise((resolve, reject) => {
    const img = new Image()
    img.onload = () => {
      const canvas = document.createElement('canvas')
      canvas.width = canvas.height = 256
      const ctx = canvas.getContext('2d')
      const side = Math.min(img.width, img.height)
      ctx.drawImage(
        img,
        (img.width - side) / 2, (img.height - side) / 2, side, side, // 居中裁切正方形
        0, 0, 256, 256
      )
      canvas.toBlob((blob) => (blob ? resolve(blob) : reject(new Error('图片压缩失败'))), 'image/jpeg', 0.9)
    }
    img.onerror = () => reject(new Error('图片读取失败'))
    img.src = URL.createObjectURL(file)
  })
}
