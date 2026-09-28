<script setup>
/**
 * 准备台：横向铺开的单张面板，三区——选范围 / 选模式 / 定规则。
 *
 * 全部选项**数据驱动**自 `GET /practice/meta`，不在前端硬编码枚举与轮次上限。
 * 模式是本页的核心决策，故用分段选择器占住视觉重心，其余元素保持安静。
 */
import { computed, ref, watch } from 'vue'

const props = defineProps({
  meta: { type: Object, default: null },
  busy: { type: Boolean, default: false }
})
const emit = defineEmits(['start'])

const stacks = ref([])
const directions = ref([])
const qtypes = ref([])
const mode = ref('')
const timeLimit = ref(0) // 0 = 不限时
const strategy = ref('SMART')

const stackOptions = computed(() => props.meta?.stacks || [])
const modeOptions = computed(() => props.meta?.modes || [])
const qtypeOptions = computed(() => props.meta?.qtypes || [])
const positionOptions = computed(() => props.meta?.positions || [])
const timeLimits = computed(() => props.meta?.time_limits || [])

/** 领域候选 = 已选技术栈下辖领域的并集；未选栈时给出全部领域。 */
const directionOptions = computed(() => {
  const all = stackOptions.value
  const picked = stacks.value.length
    ? all.filter((s) => stacks.value.includes(s.value))
    : all
  const seen = new Map()
  for (const stack of picked) {
    for (const domain of stack.domains || []) {
      if (!seen.has(domain.value)) seen.set(domain.value, domain)
    }
  }
  return [...seen.values()]
})

/** 所选栈变化后，剔除已不在候选里的领域，避免提交出无意义的筛选组合。 */
watch(directionOptions, (options) => {
  const valid = new Set(options.map((o) => o.value))
  directions.value = directions.value.filter((d) => valid.has(d))
})

/** 模式默认选第一个（快练）。 */
watch(modeOptions, (options) => {
  if (!mode.value && options.length) mode.value = options[0].value
}, { immediate: true })

/**
 * 多选切换。注意传进来的是**数组本身**而非 ref——模板对 `stacks` / `directions` /
 * `qtypes` 这类顶层 ref 会自动解包（写 `list.value` 会二次取值成 undefined）。
 */
function toggle(list, value) {
  const index = list.indexOf(value)
  if (index >= 0) list.splice(index, 1)
  else list.push(value)
}

/** 岗位是一组技术栈的并集——后端不感知「岗位」，展开后仍走 stacks 参数。 */
function pickPosition(position) {
  stacks.value = [...position.stacks]
}

const selectedMode = computed(() => modeOptions.value.find((m) => m.value === mode.value) || null)
const canStart = computed(() => !!mode.value && !props.busy)

function start() {
  if (!canStart.value) return
  emit('start', {
    stacks: [...stacks.value],
    directions: [...directions.value],
    qtypes: [...qtypes.value],
    mode: mode.value,
    timeLimit: timeLimit.value,
    strategy: strategy.value
  })
}
</script>

<template>
  <section class="setup">
    <!-- 一、练哪一块 -->
    <div class="setup__field">
      <span class="setup__label">按岗位</span>
      <div class="setup__chips">
        <button
          v-for="position in positionOptions"
          :key="position.value"
          type="button"
          class="chip chip--preset"
          :disabled="busy"
          @click="pickPosition(position)"
        >
          {{ position.label }}
        </button>
      </div>
    </div>

    <div class="setup__field">
      <span class="setup__label">技术栈</span>
      <div class="setup__chips">
        <button
          v-for="stack in stackOptions"
          :key="stack.value"
          type="button"
          class="chip"
          :class="{ 'chip--on': stacks.includes(stack.value) }"
          :disabled="busy"
          @click="toggle(stacks, stack.value)"
        >
          {{ stack.label }}
        </button>
      </div>
    </div>

    <div class="setup__field">
      <span class="setup__label">领域</span>
      <div v-if="stacks.length && directionOptions.length" class="setup__chips">
        <button
          v-for="domain in directionOptions"
          :key="domain.value"
          type="button"
          class="chip"
          :class="{ 'chip--on': directions.includes(domain.value) }"
          :disabled="busy"
          @click="toggle(directions, domain.value)"
        >
          {{ domain.label }}
        </button>
      </div>
      <!-- 严格两步：领域候选只在选了技术栈之后出现。
           原先把全部 18 个领域平铺出来，一屏全是灰胶囊，既像标签云也违背「先选栈再选领域」的设计 -->
      <span v-else class="setup__empty">先选技术栈</span>
    </div>

    <div class="setup__field">
      <span class="setup__label">题型</span>
      <div class="setup__chips">
        <button
          v-for="type in qtypeOptions"
          :key="type.value"
          type="button"
          class="chip"
          :class="{ 'chip--on': qtypes.includes(type.value) }"
          :disabled="busy"
          @click="toggle(qtypes, type.value)"
        >
          {{ type.label }}
        </button>
      </div>
    </div>

    <!-- 二、怎么练：本页的核心决策 -->
    <div class="setup__block">
      <h3 class="setup__heading">怎么练</h3>
      <div class="seg seg--fill">
        <button
          v-for="item in modeOptions"
          :key="item.value"
          type="button"
          class="seg__item"
          :class="{ 'seg__item--on': item.value === mode }"
          :disabled="busy"
          @click="mode = item.value"
        >
          {{ item.label }}
        </button>
      </div>
      <p v-if="selectedMode" class="setup__note">
        <span class="setup__note-text">{{ selectedMode.description }}</span>
        <span class="setup__note-rounds">最多 {{ selectedMode.max_rounds }} 轮</span>
      </p>
    </div>

    <!-- 三、定规则 + 开练 -->
    <div class="setup__block setup__block--rules">
      <div class="setup__rule">
        <span class="setup__label">限时</span>
        <div class="seg">
          <button
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': timeLimit === 0 }"
            :disabled="busy"
            @click="timeLimit = 0"
          >
            不限时
          </button>
          <button
            v-for="limit in timeLimits"
            :key="limit"
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': timeLimit === limit }"
            :disabled="busy"
            @click="timeLimit = limit"
          >
            {{ limit }} 秒
          </button>
        </div>
      </div>
      <div class="setup__rule">
        <span class="setup__label">选题</span>
        <div class="seg">
          <button
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': strategy === 'SMART' }"
            :disabled="busy"
            @click="strategy = 'SMART'"
          >
            薄弱优先
          </button>
          <button
            type="button"
            class="seg__item"
            :class="{ 'seg__item--on': strategy === 'RANDOM' }"
            :disabled="busy"
            @click="strategy = 'RANDOM'"
          >
            随机
          </button>
        </div>
        <el-button
          class="setup__go"
          type="primary"
          size="large"
          :loading="busy"
          :disabled="!canStart"
          @click="start"
        >
          开始训练
        </el-button>
      </div>
    </div>
  </section>
</template>

<style scoped>
.setup {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: var(--r-card);
  box-shadow: 0 1px 2px rgba(42, 39, 64, 0.05);
  padding: 18px 22px 22px;
}

/* ---------- 筛选字段 ---------- */
.setup__field {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  padding: 7px 0;
}
.setup__field + .setup__field {
  border-top: 1px solid var(--c-divider);
}
.setup__label {
  flex: 0 0 48px;
  padding-top: 6px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
}
.setup__chips {
  display: flex;
  flex: 1;
  flex-wrap: wrap;
  gap: 8px;
}
.setup__empty {
  padding-top: 6px;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}

/* 胶囊：白底细边，比灰底更轻也更像「可点的按钮」而非「贴上去的标签」 */
.chip {
  padding: 4px 13px;
  font-family: inherit;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 999px;
  cursor: pointer;
  transition: color 0.15s, background 0.15s, border-color 0.15s;
}
.chip:hover:not(:disabled) {
  color: var(--brand);
  border-color: color-mix(in srgb, var(--brand) 45%, var(--c-card));
}
/* 选中态用品牌紫——全站一致（Element 的选中也是这个色），
   且避免用绿色：绿在界面里读作「成功/通过」，而这里只是「选中」 */
.chip--on {
  color: var(--brand);
  background: color-mix(in srgb, var(--brand) 12%, var(--c-card));
  border-color: color-mix(in srgb, var(--brand) 45%, var(--c-card));
  font-weight: 600;
}
/* 岗位是「一键预设」而非一种选中状态，用虚线边框与实心选中态区分开 */
.chip--preset {
  color: var(--c-text-2);
  background: transparent;
  border-style: dashed;
}
.chip--preset:hover:not(:disabled) {
  color: var(--brand);
  border-color: var(--brand);
}
.chip:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

/* ---------- 模式：本页的视觉重心 ---------- */
.setup__block {
  margin-top: 18px;
  padding-top: 18px;
  border-top: 1px solid var(--c-divider);
}
.setup__heading {
  margin: 0 0 12px;
  font-size: var(--fs-title);
  font-weight: 700;
  color: var(--c-text);
}
/* 分段选择器：模式 / 限时 / 选题三处共用，保证同类选择长得一样 */
.seg {
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  background: var(--c-bg);
  border-radius: var(--r-control);
}
.seg--fill {
  display: flex;
}
.seg__item {
  padding: 8px 14px;
  font-family: inherit;
  font-size: var(--fs-sm);
  color: var(--c-text-2);
  background: transparent;
  border: none;
  border-radius: calc(var(--r-control) - 2px);
  cursor: pointer;
  white-space: nowrap;
  transition: color 0.15s, background 0.15s, box-shadow 0.15s;
}
.seg--fill .seg__item {
  flex: 1 1 0;
}
.seg__item:hover:not(:disabled) {
  color: var(--c-text);
}
.seg__item--on {
  color: var(--brand);
  background: var(--c-card);
  font-weight: 600;
  box-shadow: 0 1px 3px rgba(42, 39, 64, 0.1);
}
.seg__item:disabled {
  cursor: not-allowed;
}

.setup__note {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin: 10px 0 0;
}
.setup__note-text {
  font-size: var(--fs-sm);
  color: var(--c-text-2);
}
.setup__note-rounds {
  flex: 0 0 auto;
  padding: 2px 9px;
  font-size: var(--fs-xs);
  color: var(--c-text-3);
  background: var(--c-bg);
  border-radius: var(--r-mark);
}

/* ---------- 规则与开练 ---------- */
.setup__block--rules {
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.setup__rule {
  display: flex;
  align-items: center;
  gap: 14px;
}
.setup__rule .setup__label {
  padding-top: 0;
}
.setup__go {
  margin-left: auto;
}
</style>
