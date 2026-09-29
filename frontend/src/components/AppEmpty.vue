<script setup>
/**
 * 定制空态（去 Element 默认插图，全站统一画风）。
 *
 * 线稿风格：细线（1.6）+ 圆角线帽 + 每图 2~4 个形状 + 一处实色点缀；
 * 描边取 `currentColor`——调用处经 `--empty-color` 传模块色（未传则回落到品牌色），
 * 点缀色为同色 35% 混浅，保证与模块色的整体协调。
 */
defineProps({
  /** 图形名：applications / jd / interview / practice / wrong / experience / campus / chart / note / build */
  type: { type: String, default: 'note' },
  title: { type: String, default: '' },
  description: { type: String, default: '' },
  /** 'md' 140px（页面级）| 'sm' 96px（侧栏卡内） */
  size: { type: String, default: 'md' }
})
</script>

<template>
  <div class="empty" :class="`empty--${size}`">
    <svg class="empty__art" viewBox="0 0 140 96" fill="none" xmlns="http://www.w3.org/2000/svg">
      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-if="type === 'wrong'"
      >
        <rect x="36" y="16" width="68" height="64" rx="5" />
        <path d="M48 16v64" />
        <path d="M58 34h34M58 46h34M58 58h22" />
        <path d="M86 16v20l-6-4-6 4V16" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'applications'"
      >
        <path d="M30 26h24l7 9h49a4 4 0 0 1 4 4v35a4 4 0 0 1-4 4H34a4 4 0 0 1-4-4V30a4 4 0 0 1 4-4z" />
        <path d="M58 58l9 9 17-20" stroke-width="2" />
        <circle cx="98" cy="33" r="4" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'jd'"
      >
        <path d="M46 16h34l16 16v46a4 4 0 0 1-4 4H46a4 4 0 0 1-4-4V20a4 4 0 0 1 4-4z" />
        <path d="M80 16v16h16" />
        <path d="M56 44h26M56 56h18" />
        <circle cx="78" cy="64" r="10" stroke-width="2" />
        <path d="M85 71l9 9" stroke-width="2" />
        <circle cx="58" cy="30" r="2.5" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'interview'"
      >
        <path d="M28 24h50a6 6 0 0 1 6 6v20a6 6 0 0 1-6 6H52l-12 12V56H28a6 6 0 0 1-6-6V30a6 6 0 0 1 6-6z" />
        <circle cx="42" cy="40" r="2.5" fill="var(--empty-accent)" stroke="none" />
        <circle cx="54" cy="40" r="2.5" fill="var(--empty-accent)" stroke="none" />
        <circle cx="66" cy="40" r="2.5" fill="var(--empty-accent)" stroke="none" />
        <path d="M64 44h42a6 6 0 0 1 6 6v14a6 6 0 0 1-6 6h-4v10l-10-10H64" opacity="0.55" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'practice'"
      >
        <rect x="42" y="12" width="56" height="72" rx="6" />
        <path d="M54 26h18" stroke-width="2" />
        <path d="M62 44a9 9 0 1 1 13 8c-3.5 2-5 3.5-5 7" />
        <circle cx="70" cy="70" r="3" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'experience'"
      >
        <path d="M34 18h58v46l-14 14H34z" />
        <path d="M78 78l14-14H78z" />
        <path d="M46 34h34M46 46h34M46 58h20" />
        <path d="M94 26l10-9 5 5-9 10-7 2z" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'campus'"
      >
        <rect x="32" y="24" width="76" height="58" rx="5" />
        <path d="M32 40h76" />
        <path d="M50 14v14M90 14v14" />
        <rect x="46" y="52" width="12" height="12" rx="2.5" fill="var(--empty-accent)" stroke="none" />
        <path d="M68 52h26M68 66h18" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'chart'"
      >
        <path d="M32 20v60h76" />
        <rect x="46" y="50" width="13" height="30" rx="2.5" />
        <rect x="66" y="36" width="13" height="44" rx="2.5" />
        <rect x="86" y="58" width="13" height="22" rx="2.5" />
        <circle cx="104" cy="26" r="4.5" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else-if="type === 'build'"
      >
        <rect x="40" y="32" width="60" height="44" rx="5" />
        <path d="M56 20v12M84 20v12" />
        <path d="M52 46h36M52 58h24" />
        <circle cx="60" cy="65" r="2.5" fill="var(--empty-accent)" stroke="none" />
      </g>

      <g
        stroke="currentColor"
        stroke-width="1.6"
        stroke-linecap="round"
        stroke-linejoin="round"
        v-else
      >
        <rect x="40" y="14" width="60" height="68" rx="6" />
        <path d="M50 32l4 4 7-8" />
        <path d="M68 32h22" />
        <path d="M50 50l4 4 7-8" />
        <path d="M68 50h22" />
        <rect x="48" y="62" width="11" height="11" rx="2.5" />
        <path d="M68 68h18" />
        <circle cx="92" cy="26" r="3" fill="var(--empty-accent)" stroke="none" />
      </g>
    </svg>

    <p v-if="title" class="empty__title">{{ title }}</p>
    <p v-if="description" class="empty__desc">{{ description }}</p>
    <div v-if="$slots.default" class="empty__actions"><slot /></div>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 28px 16px;
  /* 描边取模块色（调用处经 --empty-color 传入）；点缀为同色 35% 混浅 */
  color: var(--empty-color, var(--brand));
  --empty-accent: color-mix(in srgb, var(--empty-color, var(--brand)) 35%, #fff);
}
.empty--sm {
  padding: 18px 12px;
}
.empty__art {
  width: 140px;
  height: auto;
  opacity: 0.9;
}
.empty--sm .empty__art {
  width: 96px;
}
.empty__title {
  margin: 14px 0 0;
  font-size: var(--fs-body);
  font-weight: 600;
  color: var(--c-text);
}
.empty__desc {
  margin: 6px 0 0;
  font-size: var(--fs-sm);
  color: var(--c-text-3);
  text-align: center;
  line-height: 1.7;
}
.empty__actions {
  margin-top: 14px;
}
</style>
