/** 头像工具：默认头像（用户名首字 + 哈希底色）与上传前压缩（SRS §3.14 头像规则）。 */
const PALETTE = ['#7A6BC4', '#5B8DD9', '#4FA8A8', '#D9A24E', '#5BAE84', '#D4708D', '#DD7A62']

/** 字符累加哈希：稳定优先于均匀——同一用户名在任何位置同色即可。 */
export function defaultAvatar(name = '?') {
  const text = String(name || '?')
  let hash = 0
  for (const ch of text) hash = (hash + ch.codePointAt(0)) % 100000
  return { text: text.trim().charAt(0).toUpperCase() || '?', color: PALETTE[hash % PALETTE.length] }
}

/** 头像相对路径 → 可渲染 URL（后端存 uploads/avatars/x.png，静态访问为 /static/avatars/x.png）。 */
export const avatarUrl = (avatar) => (avatar ? '/static/avatars/' + avatar.split('/').pop() : null)

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
