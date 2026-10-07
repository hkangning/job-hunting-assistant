/**
 * 播报队列（纯逻辑：合成 / 播放 / 释放三个副作用由调用方注入，不碰 Audio 与 URL）。
 *
 * 承担流式播报的时序与竞态（设计见
 * `docs/superpowers/specs/2026-10-07-面试流式同步播报-design.md`）：
 * - **顺序**：单泵循环按入队顺序合成、播放；播到哪句 `onKey(key)` 回调（UI 段级点亮）；
 * - **抢跑**：播放游标前最多 `lead` 句已发起合成——整段预合成会堆内存，串行合成又会
 *   「播一句等一句」；
 * - **流式追加**：`push` 随时可加，泵在跑就不重启；`finish()` 后播空即收尾；
 * - **作废**：`start` / `stop` 自增 token，旧链路每个 await 点校验；作废的合成产物走
 *   `release` 释放；
 * - **失败静默停**：合成失败或 `play` 返回 false → 整轮放弃（`onFail` 通知，不弹错），
 *   与「60002 / 网络 → 静默停、用户可手动再点播报」的既有口径一致。
 *
 * 契约：`play(handle)` 返回的 promise 必须在适配层被 stop 时以 `false` 结束
 * （否则旧泵会一直挂在 await 上）。
 *
 * @returns {{ start: (ctx?: any) => void, push: (text: string, key?: any) => void,
 *             finish: () => void, stop: () => void }}
 */
export function createSpeechQueue({
  synthesize,
  play,
  release = () => {},
  onKey,
  onActive,
  onFail,
  lead = 2
} = {}) {
  let token = 0
  let items = [] // [{ text, key, task, handle, released }]
  let cursor = 0
  let ctx = null
  let running = false
  let finished = true
  let active = false
  let wake = null

  /** 开新一轮（流式：先 start 再逐句 push 最后 finish；整段播放：push 完即 finish）。 */
  function start(context) {
    discard()
    ctx = context ?? null
    finished = false
  }

  /** 追加一句（流式期间随时可调）。 */
  function push(text, key) {
    items.push({ text, key, task: null, handle: null, released: false })
    ensureRunning()
    schedule(token) // 新句一到就补足抢跑窗口（否则要等上一句播完才开始合成它）
    wakeUp()
  }

  /** 不会再有新句子：队列播空后收尾。 */
  function finish() {
    finished = true
    wakeUp()
  }

  /** 立即停 + 作废整轮（在播的音频由适配层掐，见模块头契约）。 */
  function stop() {
    discard()
  }

  function ensureRunning() {
    if (running || cursor >= items.length) return
    running = true
    setActive(true)
    void pump(token)
  }

  async function pump(my) {
    while (my === token) {
      schedule(my)
      if (cursor >= items.length) {
        if (finished) break
        await waitForWork()
        continue
      }
      const item = items[cursor]
      const handle = await item.task
      if (my !== token) return
      if (!handle) return fail(my) // 合成失败：整轮静默停
      onKey?.(item.key)
      const ok = await play(handle)
      releaseItem(item)
      if (my !== token) return
      if (!ok) return fail(my) // 播放失败：同上
      cursor += 1
    }
    end(my)
  }

  /** 抢跑：从播放游标起，最多 lead 句已发起合成。 */
  function schedule(my) {
    for (let i = cursor; i < items.length && i <= cursor + lead; i++) {
      if (!items[i].task) items[i].task = synthesizeItem(items[i], my)
    }
  }

  async function synthesizeItem(item, my) {
    let handle = null
    try {
      handle = await synthesize(item.text, ctx)
    } catch {
      handle = null
    }
    if (my !== token) {
      if (handle) release(handle) // 开新一轮 / 停：在途产物就地释放
      return null
    }
    item.handle = handle
    return handle
  }

  function releaseItem(item) {
    if (!item.handle || item.released) return
    item.released = true
    release(item.handle)
  }

  /** 清场：作废在途链路、释放尚未播出的产物。 */
  function discard() {
    token += 1
    for (const item of items) releaseItem(item)
    items = []
    cursor = 0
    running = false
    wakeUp()
    setActive(false)
  }

  function end(my) {
    if (my !== token) return
    discard()
  }

  function fail(my) {
    if (my !== token) return
    discard()
    onFail?.()
  }

  function setActive(value) {
    if (active === value) return
    active = value
    onActive?.(value)
  }

  function waitForWork() {
    return new Promise((resolve) => {
      wake = resolve
    })
  }

  function wakeUp() {
    const resolve = wake
    wake = null
    resolve?.()
  }

  return { start, push, finish, stop }
}
