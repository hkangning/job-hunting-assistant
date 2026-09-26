<script setup>
/** 顶栏用户菜单（设计文档 §4.4）：头像 + 用户名 → 个人中心 / 设置 / AI 配置 / 退出登录。 */
import { useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { ArrowDown } from '@element-plus/icons-vue'
import { useUserStore } from '../stores/user'

const router = useRouter()
const userStore = useUserStore()

async function onCommand(command) {
  if (command === 'logout') {
    try {
      await ElMessageBox.confirm('退出后需重新登录，确定退出当前账号？', '退出登录', {
        type: 'warning',
        confirmButtonText: '退出',
        cancelButtonText: '取消'
      })
    } catch {
      return // 取消
    }
    userStore.logout() // 清 Token + 重置其余 store（TC-66）
    router.replace('/login')
    return
  }
  router.push(command)
}
</script>

<template>
  <el-dropdown trigger="click" @command="onCommand">
    <div class="user-menu">
      <img v-if="userStore.avatarImg" class="user-menu__avatar" :src="userStore.avatarImg" alt="" />
      <span
        v-else
        class="user-menu__avatar user-menu__avatar--text"
        :style="{ background: userStore.fallbackAvatar.color }"
        >{{ userStore.fallbackAvatar.text }}</span
      >
      <span class="user-menu__name">{{ userStore.displayName }}</span>
      <el-icon class="user-menu__arrow"><ArrowDown /></el-icon>
    </div>

    <template #dropdown>
      <el-dropdown-menu>
        <el-dropdown-item command="/profile">个人中心</el-dropdown-item>
        <el-dropdown-item command="/settings">设置</el-dropdown-item>
        <el-dropdown-item command="/ai-config">AI 配置</el-dropdown-item>
        <!-- 退出登录置于末位并以分隔线区隔，防误点（设计文档 §4.4） -->
        <el-dropdown-item divided command="logout">退出登录</el-dropdown-item>
      </el-dropdown-menu>
    </template>
  </el-dropdown>
</template>

<style scoped>
.user-menu {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 4px 6px;
  border-radius: var(--r-menu);
  cursor: pointer;
  outline: none;
  transition: background 0.15s ease;
}
.user-menu:hover {
  background: var(--c-bg);
}
.user-menu__avatar {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  object-fit: cover;
  flex-shrink: 0;
}
.user-menu__avatar--text {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #fff;
  font-size: var(--fs-body);
  font-weight: 700;
}
.user-menu__name {
  max-width: 96px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: var(--fs-body);
  color: var(--c-text);
}
.user-menu__arrow {
  font-size: var(--fs-sm);
  color: var(--c-text-3);
}
</style>
