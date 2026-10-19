<script setup lang="ts">
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import dayjs from 'dayjs'
import type { Task } from '@/types'

/**
 * 置顶任务面板（第二十五轮）。仪表盘两个总览共用。
 *
 * 抽成组件而不是复制两遍：这块面板有「待填数 / 不需填写标签 / 去填写入口」
 * 三处分支逻辑，复制一份将来改一处忘另一处，症状是「账目总览里有、
 * 学生总览里没有」，极难归因。
 */
const props = defineProps<{ tasks: Task[]; loading: boolean }>()

const router = useRouter()

function fmtTime(value: string | null | undefined) {
  return value ? dayjs(value).format('MM-DD HH:mm') : '—'
}

/**
 * 我还没填的置顶任务 —— 这个面板存在的**全部理由**。
 *
 * 置顶不是为了「让所有人看见」，而是为了**催人交**；所以判断口径是
 * 「我还欠着哪几道」，而不是「有几道题」。已填的在下面单独标出来，
 * 免得填完的人以为漏看了。
 *
 * 班主任和访客拿不到 `canAnswer`（后端口径：他们不是被统计的同学），
 * 这里自然就不会出现「待填」——不另写角色判断。
 */
const myPending = computed(() => props.tasks.filter((t) => t.canAnswer && !t.myAnswer))
</script>

<template>
  <article class="glass-card panel">
    <div class="panel-head">
      <h3>置顶任务</h3>
      <!-- 待填数是这个面板存在的理由，摆进标题行而不是藏进每一条里：
           一眼就知道「我欠了几道」，比逐条数省事 -->
      <span v-if="myPending.length > 0" class="hint pending">
        {{ myPending.length }} 道待填
      </span>
      <router-link to="/tasks" class="panel-link">查看全部</router-link>
    </div>

    <ul v-if="props.tasks.length > 0" class="task-list">
      <li v-for="t in props.tasks" :key="t.id" class="task-item">
        <div class="task-title">
          {{ t.title }}
          <!-- 只在「这条我不用答」时出现，解释右上角为什么没有「去填写」。
               标签刻意不叫「只读」——那个词会被读成「这题已关闭」，
               这里说的其实是「你不用填」（班主任和访客都不是被统计的同学）。 -->
          <el-tag v-if="!t.canAnswer" size="small" type="info" effect="plain">
            不需填写
          </el-tag>
        </div>
        <div class="task-q">{{ t.question }}</div>
        <div class="task-meta">
          <span>已填 {{ t.summary.answered }} / 共 {{ t.summary.total }} 人</span>
          <span v-if="t.deadline"> · 截止 {{ fmtTime(t.deadline) }}</span>
        </div>
        <!-- 只在「我还欠着」时给入口：已经填过的再摆一个「去填写」是噪音 -->
        <div v-if="t.canAnswer && !t.myAnswer" class="task-act">
          <button type="button" class="task-jump" @click="router.push('/tasks')">
            去填写 →
          </button>
        </div>
        <div v-else-if="t.myAnswer" class="task-mine">
          我的答案：{{ t.myAnswer.value }}
        </div>
      </li>
    </ul>

    <el-empty
      v-else-if="!props.loading"
      description="暂时没有置顶任务。班主任或班长可在「班级任务」里置顶一道题，全班都会在这里看到"
      :image-size="72"
    />
  </article>
</template>

<style scoped>
.panel {
  padding: var(--space-md);
}

.panel-head {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 14px;
}

.panel-head h3 {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
}

.hint {
  font-size: 12px;
  color: var(--color-muted-fg);
}

/* 「N 道待填」：唯一需要强调的一行，所以给它颜色 */
.hint.pending {
  color: var(--color-expense);
  font-weight: 600;
}

.panel-link {
  margin-left: auto;
  margin-top: -7px;
  margin-bottom: -7px;
  padding: 7px 6px;
  font-size: 12px;
  color: var(--color-accent-text);
  text-decoration: none;
  border-radius: var(--el-border-radius-small);
}

.panel-link:hover {
  text-decoration: underline;
  background: var(--color-muted);
}

.task-list {
  list-style: none;
  margin: 0;
  padding: 0;
}

.task-item {
  padding: 10px 0;
  border-bottom: 1px dashed var(--color-border);
}

.task-item:last-child {
  border-bottom: 0;
}

.task-title {
  font-size: 14px;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
}

.task-q {
  margin: 4px 0 0;
  font-size: 13px;
}

.task-meta {
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.task-act {
  margin-top: 8px;
}

.task-jump {
  border: 0;
  background: none;
  padding: 0;
  cursor: pointer;
  font-size: 13px;
  font-weight: 600;
  color: var(--color-accent-text);
}

.task-jump:hover {
  text-decoration: underline;
}

.task-mine {
  margin-top: 6px;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>