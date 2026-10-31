<script setup lang="ts">
import { computed, reactive } from "vue";
import { useRouter } from "vue-router";

import { useAuthStore } from "../stores/auth";
import { useFeedbackStore } from "../stores/feedback";

const auth = useAuthStore();
const feedback = useFeedbackStore();
const router = useRouter();

const createdAtText = computed(() => {
  const createdAt = auth.user?.createdAt;
  if (createdAt === undefined) return "未知";
  const date = new Date(createdAt);
  return Number.isNaN(date.getTime()) ? createdAt : date.toLocaleString("zh-CN");
});

const nickname = reactive({ displayName: "", isSaving: false });
const password = reactive({
  currentPassword: "",
  newPassword: "",
  confirmPassword: "",
  isSaving: false
});

function submitNickname(): void {
  const displayName = nickname.displayName.trim();
  if (displayName === "") {
    feedback.show("info", "昵称不能为空。");
    return;
  }
  nickname.isSaving = true;
  void auth
    .updateProfile(displayName)
    .then(() => {
      feedback.show("success", "昵称已更新");
      nickname.displayName = "";
    })
    .catch(() => undefined)
    .finally(() => {
      nickname.isSaving = false;
    });
}

function submitPassword(): void {
  if (password.newPassword.length < 8) {
    feedback.show("info", "新密码至少需要 8 个字符。");
    return;
  }
  if (password.newPassword !== password.confirmPassword) {
    feedback.show("info", "两次输入的新密码不一致。");
    return;
  }
  password.isSaving = true;
  void auth
    .changePassword({
      currentPassword: password.currentPassword,
      newPassword: password.newPassword
    })
    .then(() => {
      feedback.show("success", "密码已修改，请使用新密码重新登录。");
      // 改密码成功后所有会话已被吊销，本地状态已在 store 中清空。
      return router.replace("/login");
    })
    .catch(() => undefined)
    .finally(() => {
      password.isSaving = false;
    });
}
</script>

<template>
  <section class="personal-info" aria-label="个人信息">
    <div class="personal-info__card" aria-label="账号资料">
      <h3>账号资料</h3>
      <div class="personal-info__row"><span>邮箱</span><strong>{{ auth.user?.email }}</strong></div>
      <div class="personal-info__row"><span>昵称</span><strong>{{ auth.user?.displayName }}</strong></div>
      <div class="personal-info__row"><span>注册时间</span><strong>{{ createdAtText }}</strong></div>
    </div>

    <form class="personal-info__card" aria-label="修改昵称" @submit.prevent="submitNickname">
      <h3>修改昵称</h3>
      <label>
        <span>新昵称（最长 160 字）</span>
        <input v-model.trim="nickname.displayName" maxlength="160" :placeholder="auth.user?.displayName" />
      </label>
      <div class="personal-info__commands">
        <button type="submit" :disabled="nickname.isSaving">
          {{ nickname.isSaving ? "保存中" : "保存昵称" }}
        </button>
      </div>
    </form>

    <form class="personal-info__card" aria-label="修改密码" @submit.prevent="submitPassword">
      <h3>修改密码</h3>
      <label>
        <span>当前密码</span>
        <input v-model="password.currentPassword" type="password" autocomplete="current-password" required />
      </label>
      <label>
        <span>新密码（至少 8 位）</span>
        <input v-model="password.newPassword" type="password" autocomplete="new-password" minlength="8" required />
      </label>
      <label>
        <span>确认新密码</span>
        <input v-model="password.confirmPassword" type="password" autocomplete="new-password" minlength="8" required />
      </label>
      <p class="personal-info__hint">修改成功后会退出全部登录会话，需要用新密码重新登录。</p>
      <div class="personal-info__commands">
        <button type="submit" :disabled="password.isSaving">
          {{ password.isSaving ? "提交中" : "修改密码" }}
        </button>
      </div>
    </form>
  </section>
</template>

<style scoped>
.personal-info { display: grid; gap: 1rem; grid-template-columns: repeat(2, minmax(0, 1fr)); }
.personal-info__card { background: var(--canvas); border: 1px solid var(--line); border-radius: var(--radius-md); display: grid; gap: 0.65rem; padding: 1rem 1.1rem; }
.personal-info__card h3 { font-size: 0.9rem; font-weight: 600; margin: 0; }
.personal-info__row { display: flex; justify-content: space-between; gap: 0.8rem; }
.personal-info__row span { color: var(--text-tertiary); font-size: 0.78rem; }
.personal-info__row strong { font-size: 0.82rem; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.personal-info__card label { display: grid; gap: 0.3rem; }
.personal-info__card label span { color: var(--text-secondary); font-size: 0.78rem; font-weight: 600; }
.personal-info__card input { background: var(--surface-raised); border: 1px solid var(--line); border-radius: var(--radius-sm); color: var(--text-primary); font-size: 0.85rem; min-height: 2rem; padding: 0 0.65rem; }
.personal-info__card input:focus { border-color: var(--accent); outline: none; }
.personal-info__commands { display: flex; justify-content: flex-end; }
.personal-info__commands button { background: var(--accent-solid); border: 0; border-radius: var(--radius-sm); color: #fff; cursor: pointer; font-size: 0.82rem; font-weight: 600; min-height: 2rem; padding: 0 0.9rem; }
.personal-info__commands button:disabled { cursor: not-allowed; opacity: 0.55; }
.personal-info__hint { color: var(--text-tertiary); font-size: 0.74rem; margin: 0; }
@media (max-width: 760px) { .personal-info { grid-template-columns: minmax(0, 1fr); } }
</style>
