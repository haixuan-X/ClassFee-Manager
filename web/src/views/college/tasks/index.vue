<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { fetchCollegeTasks } from '@/api/college'
import type { CollegeTaskList } from '@/types'

/**
 * 学院任务（第三十轮）：跨班级的任务一览。
 *
 * ## 和「班级 → 班级任务」的区别
 *
 * 班级任务页是**本班**的任务，且能发布/关闭/改置顶/答题。
 * 这个页面是**所有班级**的任务的**只读**一览：谁发了什么题、回收了多少。
 *
 * ## 「已填 X / 共 Y 人」的分母是**任务自己那个班**的人数
 *
 * 一个任务只对**它所在那个班**的同学有效。跨班混算会得出
 * 「已填 3 / 共 60 人」这种没人看得懂的数（3 个是 A 班的，60 是全校的）。
 *
 * ## 只读
 *
 * 改任务在班级页做。学院视角一旦能改，就会有两个可写入口。
 */
const list = ref<CollegeTaskList | null>(null)
const loading = ref(true)
const loadError = ref(false)

const keyword = ref('')
const classId = ref<number | null>(null)
const onlyPinned = ref(false)

const applied = ref<{ keyword: string; classId: number | null; onlyPinned: boolean }>({
  keyword: '',
  classId: null,
  onlyPinned: false,
})

async function load() {
  loading.value = true
  try {
    list.value = await fetchCollegeTasks({
      keyword: applied.value.keyword,
      classId: applied.value.classId,
      onlyPinned: applied.value.onlyPinned,
    })
    loadError.value = false
  } catch {
    list.value = null
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function search() {
  applied.value = {
    keyword: keyword.value.trim(),
    classId: classId.value,
    onlyPinned: onlyPinned.value,
  }
  void load()
}

function reset() {
  keyword.value = ''
  classId.value = null
  onlyPinned.value = false
  applied.value = { keyword: '', classId: null, onlyPinned: false }
  void load()
}

const rows = computed(() => list.value?.rows ?? [])

/** 汇总：开放中的、置顶的 */
const openCount = computed(() => rows.value.filter((r) => r.open).length)
const pinnedCount = computed(() => rows.value.filter((r) => r.pinned).length)

function fmtTime(value: string | null | undefined): string {
  return value ? value.slice(0, 16) : '—'
}

/** 回收进度（0-100）。分母为 0 时给 0——没有应答对象时「100%」是假的 */
function rate(row: { answered: number; total: number }): number {
  if (!row.total) return 0
  return Math.round((row.answered / row.total) * 100)
}

onMounted(load)
</script>

<template>
  <div class="page">
    <div class="page-head">
      <div>
        <h2>学院任务</h2>
        <p>所有班级的任务一览（只读）。发布或关闭任务请到「班级 → 班级任务」。</p>
      </div>
    </div>

    <section class="glass-card filters" aria-label="搜索筛选">
      <div class="filter-row">
        <el-input
          v-model="keyword"
          class="f-keyword"
          placeholder="搜索任务标题或题目"
          aria-label="搜索任务"
          clearable
          @keyup.enter="search"
          @clear="search"
        />
        <el-select
          v-model="classId"
          class="f-select"
          placeholder="全部班级"
          aria-label="按班级筛选"
          clearable
          @change="search"
        >
          <el-option
            v-for="c in list?.classes ?? []"
            :key="c.id"
            :label="c.grade ? `${c.className}（${c.grade}）` : c.className"
            :value="c.id"
          />
        </el-select>
        <el-checkbox v-model="onlyPinned" @change="search">只看置顶</el-checkbox>
        <el-button type="primary" @click="search">查询</el-button>
        <el-button @click="reset">重置</el-button>
      </div>
      <p class="filter-hint">
        共 {{ rows.length }} 条任务，其中 {{ openCount }} 条开放中、{{ pinnedCount }} 条置顶。
      </p>
    </section>

    <section class="glass-card" aria-label="任务一览" :aria-busy="loading">
      <div v-if="rows.length > 0" class="table-wrap">
        <table class="roster">
          <thead>
            <tr>
              <th scope="col">班级</th>
              <th scope="col">标题</th>
              <th scope="col">题目</th>
              <th scope="col">状态</th>
              <th scope="col">回收进度</th>
              <th scope="col">截止</th>
              <th scope="col">发布时间</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="row in rows" :key="row.id">
              <td>{{ row.className }}</td>
              <td>
                {{ row.title }}
                <el-tag v-if="row.pinned" size="small" type="warning" effect="plain">置顶</el-tag>
              </td>
              <td class="q">{{ row.question }}</td>
              <td>
                <el-tag size="small" effect="plain" :type="row.open ? 'success' : 'info'">
                  {{ row.open ? '开放中' : '已关闭' }}
                </el-tag>
              </td>
              <td class="progress-cell">
                <el-progress
                  :percentage="rate(row)"
                  :stroke-width="8"
                  :show-text="false"
                  color="var(--color-accent-text)"
                  aria-hidden="true"
                />
                <span class="progress-text num">已填 {{ row.answered }} / 共 {{ row.total }} 人</span>
              </td>
              <td class="num">{{ fmtTime(row.deadline) }}</td>
              <td class="num">{{ fmtTime(row.createdAt) }}</td>
            </tr>
          </tbody>
        </table>
      </div>

      <el-empty
        v-else-if="!loading"
        :description="
          loadError
            ? '学院任务加载失败，请检查网络后重试'
            : applied.keyword || applied.classId || applied.onlyPinned
              ? '没有符合条件的任务'
              : '还没有发布过任务'
        "
        :image-size="80"
      >
        <el-button v-if="loadError" type="primary" @click="load">重新加载</el-button>
      </el-empty>
    </section>
  </div>
</template>

<style scoped>
.page {
  display: flex;
  flex-direction: column;
  gap: var(--space-md);
}

.filters {
  padding: var(--space-md);
}

.filter-row {
  display: flex;
  gap: 10px;
  flex-wrap: wrap;
  align-items: center;
}

.f-keyword {
  flex: 1 1 260px;
  min-width: 200px;
}

.f-select {
  width: 200px;
}

.filter-hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: var(--color-muted-fg);
}

.table-wrap {
  overflow-x: auto;
}

.roster {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.roster th,
.roster td {
  padding: 9px 12px;
  border-bottom: 1px solid var(--color-border);
  text-align: left;
  vertical-align: top;
}

.roster thead th {
  background: var(--color-surface, #fff);
  font-weight: 600;
  color: var(--color-foreground);
  white-space: nowrap;
}

.q {
  max-width: 320px;
  white-space: normal;
}

.progress-cell {
  min-width: 160px;
}

.progress-text {
  display: block;
  margin-top: 4px;
  font-size: 12px;
  color: var(--color-muted-fg);
}
</style>
