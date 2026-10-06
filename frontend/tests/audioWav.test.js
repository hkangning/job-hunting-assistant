import { test } from 'node:test'
import assert from 'node:assert/strict'
import { encodeWav, resampleTo16k } from '../src/utils/audioWav.js'

test('encodeWav：头部字段与长度', () => {
  const buf = encodeWav(new Float32Array([0, 1, -1]), 16000)
  const view = new DataView(buf)
  const str = (o) => String.fromCharCode(...new Uint8Array(buf, o, 4))
  assert.equal(str(0), 'RIFF')
  assert.equal(str(8), 'WAVE')
  assert.equal(str(12), 'fmt ')
  assert.equal(str(36), 'data')
  assert.equal(view.getUint32(16, true), 16) // fmt chunk 大小
  assert.equal(view.getUint32(4, true), 36 + 3 * 2) // RIFF size = 36 + data
  assert.equal(view.getUint16(20, true), 1) // PCM
  assert.equal(view.getUint16(22, true), 1) // mono
  assert.equal(view.getUint32(24, true), 16000)
  assert.equal(view.getUint32(28, true), 16000 * 2) // byteRate
  assert.equal(view.getUint16(32, true), 2) // blockAlign
  assert.equal(view.getUint16(34, true), 16) // bits
  assert.equal(view.getUint32(40, true), 3 * 2) // data size
  assert.equal(buf.byteLength, 44 + 6)
})

test('encodeWav：采样换算与超限钳制', () => {
  const buf = encodeWav(new Float32Array([0, 1, -1, 1.5, -1.5]), 16000)
  const view = new DataView(buf)
  const s = (i) => view.getInt16(44 + i * 2, true)
  assert.equal(s(0), 0)
  assert.equal(s(1), 32767)
  assert.equal(s(2), -32768)
  assert.equal(s(3), 32767) // 超 1 钳到上限
  assert.equal(s(4), -32768)
})

test('resampleTo16k：同采样率原样返回', () => {
  const src = new Float32Array([0, 0.5, 1, -1])
  assert.equal(resampleTo16k(src, 16000), src)
})

test('resampleTo16k：下采样长度与取值', () => {
  const down = resampleTo16k(new Float32Array(48000).fill(0.5), 48000)
  assert.equal(down.length, 16000)
  assert.equal(down[0], 0.5)
  assert.equal(down[15999], 0.5)
})
