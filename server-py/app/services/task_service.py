"""班级任务（第二十五轮）。

## 它和被删掉的班级公告差在哪

公告是**发出去就看**，任务是**发出去还要回收答案**。所以多一张
`cls_task_answer` 表，并且整个模块的复杂度都集中在「谁能看到谁填了什么」。

用户口径（本轮问过，四条）：

| 问题 | 用户的答案 |
|------|-----------|
| 一个任务几个问题 | 单问题 |
| 题型 | 是/否(+文字说明) / 单选 / 多选 / 日期 |
| 学生能看到别人的答案吗 | **只能看汇总，不含具体是谁** |
| 谁能发布 | 班主任 + 班长 |
| 访客能看吗 | 能，只读 |
| 班主任要不要自己填 | **不要**——「统计班主任干什么」 |

## 可见性（本模块的核心）

| 角色 | 看任务 | 提交答案 | 看**明细**（谁填了什么） | 看汇总 |
|------|--------|---------|------------------------|--------|
| 发布人（班主任/班长） | ✅ | 视角色，见下 | ✅ | ✅ |
| 班主任（非发布人） | ✅ | **❌** | ✅ | ✅ |
| 生活委员 | ✅ | ✅ | ❌ | ✅ |
| 班长 | ✅ | ✅（除非他是这条的发布人） | ❌ | ✅ |
| 普通成员 | ✅ | ✅ | ❌ | ✅ |
| 访客 | ✅ | **❌** | ❌ | ✅ |

「明细」这个口子必须**只**开给发布人和班主任，理由很直接：题目可以是
「你家里有没有人在做兼职」「你最近身体好吗」——汇总（多少人是/多少否）用来
催人交，「张伟没返校」这类具体到人的答案不该出现在非发布人的页面上。

访客能看的是**汇总**，不是明细：领导要看的是「返校率怎么样」，
不是「谁没返校」。这条口径也决定了访客**不能**答题（他是校方，不是被统计的人）。

## 应答对象

**全部启用账号，减去班主任和访客（`NON_ANSWER_ROLES`），再减去发布人自己。**

- 排除班主任：他是老师，发题、催交、看明细都行，但**自己不填、也不算进分母**。
- 排除访客：校方人员，是看情况的人，不是被统计的同学。
- 排除发布人：你出的题你自己不算（班长是同学，出的题照样不算自己的分）。

后两条必须和 `can_answer` 同步，否则会出现「进了分母却永远交不上」的人，
发布人的「未填名单」里会永远挂着一个人，看起来像是催不动。

⚠ 排除班主任**不能**用「他是发布人」顶替：班主任自己发的题靠 creator_id
已经排掉了，但**班长发的题**里班主任不是发布人、却同样不该被统计——
只判 creator_id 的话他会混进分母和未填名单。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import delete, or_, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import ClsTask, ClsTaskAnswer, SysUser
from ..security import ROLE_LEVEL, LoginUser, role_level


def _roles_at_least(role_name: str) -> frozenset[str]:
    """等级 >= 指定角色的全部角色名（第二十八轮起权限集一律这样推导）。"""
    floor = role_level(role_name)
    return frozenset(r for r, lv in ROLE_LEVEL.items() if lv >= floor)

# 发布权限：**班长及以上**（用户口径「班主任 + 班长」）。
# 从 ROLE_LEVEL 推导而非手写角色名——加了更高的角色忘了补这里，表现为
# 静默降权（院长发不了题），这类问题没有报错、只能靠人撞见。
PUBLISH_ROLES = _roles_at_least("MONITOR")   # 班长 + 班主任 + 院长

# 访客角色名。刻意用常量而不是到处写字面量：它是「应答对象」这条规则的
# 排除条件之一，写错了两边就不配套（见 is_answer_target）。
GUEST_ROLE = "GUEST"

# 班主任角色名。同上——它也是「应答对象」的排除条件。
TEACHER_ROLE = "TEACHER"

# 院长角色名（第三十二轮）：**学院任务**只有院长能发。
DEAN_ROLE = "DEAN"

# **不被统计的角色**。
#
# - 班主任及以上（含院长）：老师，不是被点名的同学。他们发题、催交、看明细，
#   但自己不填。（用户原话「统计班主任干什么」。）注意这条和「排除发布人」
#   是**两回事**：班长发题时班主任不在应答名单里，靠的就是这里，不是靠 creator_id。
# - 访客：校方/领导，是看的人不是被统计的人。
#
# 生活委员和班长**是**同学（他们就是班委），所以要答、能被统计。
# 院长与班主任同理——他是校方的人，不是被点名的同学。
NON_ANSWER_ROLES = _roles_at_least("TEACHER") | {GUEST_ROLE}

# 四种题型。刻意不设 TEXT：单问题 + 有结构的选项，够覆盖点名/统计，
# 开放式文字题反而会让「回收率」这种统计失去意义（用户没选它）。
QTYPES = ("BOOLEAN", "SINGLE", "MULTI", "DATE")

QTYPE_TEXT = {
    "BOOLEAN": "是 / 否",
    "SINGLE": "单选",
    "MULTI": "多选",
    "DATE": "日期",
}

BOOLEAN_LABELS = {"true": "是", "false": "否"}

MAX_OPTIONS = 12
MAX_OPTION_LEN = 30
MAX_VALUE_LEN = 255

# ---------------- 第三十二轮：班级任务 / 学院任务 ----------------
#
# 两种任务，差别在「谁能看到、谁来答」：
#
# | 任务 | 谁能看到 | 谁应答 | 谁看明细 |
# |------|-----------|--------|----------|
# | 班级任务（CLASS） | 本班所有人 | 本班**同学** | 发布人 + 班主任及以上 |
# | 学院任务（COLLEGE） | **全学院**所有人 | **各班班主任** | 院长 + 发布人（班主任只看自己班那份） |
#
# 学院任务的存在意义：「各班统计一下本班返校情况，交上来」——
# 一个人（班主任）交**一份**代表他那个班的答案。
SCOPE_CLASS = "CLASS"
SCOPE_COLLEGE = "COLLEGE"
SCOPES = (SCOPE_CLASS, SCOPE_COLLEGE)

SCOPE_TEXT = {
    SCOPE_CLASS: "班级任务",
    SCOPE_COLLEGE: "学院任务",
}


# ==================== 可见性判定 ====================


def is_college_task(task: ClsTask) -> bool:
    """这是不是一条**学院任务**（第三十二轮）。"""
    return (task.scope or SCOPE_CLASS) == SCOPE_COLLEGE


def is_college_answer_target(u: SysUser) -> bool:
    """这个人是不是**学院任务**的应答对象（各班班主任）。

    - **班主任及以上**：每个班有一份答案，这就是「各班交上来」的意思。
      纯院长（dean_only=1）不参与班级事务 → 不算应答对象。
    - **访客**：校方的人，是看情况的不是交情况的。
    - **普通成员 / 生活委员 / 班长**：学院任务问的是**班**的情况，答的人
      是班主任；让每个同学都答一遍，等于让班主任收全班同学的答案再交上来，
      那正是「班级任务」干的事。
    """
    if u.role == GUEST_ROLE:
        return False
    if u.role == DEAN_ROLE and u.dean_only:
        return False
    return u.role in _roles_at_least(TEACHER_ROLE)


def is_answer_target(u: SysUser, creator_id: int, scope: str = SCOPE_CLASS) -> bool:
    """这个人要不要答这条任务。

    **按任务类型分流**（第三十二轮）：

    - 班级任务：应答对象是**本班同学**（排除班主任及以上、访客、发布人）。
    - 学院任务：应答对象是**各班班主任**（一个人代表一个班）。

    班级任务的两个排除条件，缺一不可：

    1. u.role in NON_ANSWER_ROLES（班主任 / 访客）——他们不是被点名的同学。
       这条**不能**用 creator_id 顶替：班主任自己发的题靠 creator_id 已经排除了，
       但**班长发的题**班主任既不是发布人、也不该被统计，只靠 creator_id
       他就会混进分母和未填名单。
    2. u.id == creator_id——你出的题你自己不算，哪怕你是班长（班长是同学）。

    和 can_answer 必须同口径：不配套的话会出现「进了分母却永远交不上」的人，
    发布人的未填名单里会永远挂着一个人，看着像催不动。
    """
    if (scope or SCOPE_CLASS) == SCOPE_COLLEGE:
        return is_college_answer_target(u)
    return u.role not in NON_ANSWER_ROLES and u.id != creator_id


def is_pure_dean(user: LoginUser) -> bool:
    """纯院长：只管学院，班级事务一概不参与（第三十三轮）。"""
    return user.role == DEAN_ROLE and bool(user.dean_only)


def can_publish(user: LoginUser) -> bool:
    return user.role in PUBLISH_ROLES


def can_see_detail(task: ClsTask, user: LoginUser) -> bool:
    """能不能看到「谁填了什么」。规则见模块 docstring 的可见性表。

    班主任**及以上**（含院长）都能看，不只是发布人自己。用等级判定而非
    `== TEACHER`：写成角色相等的话，院长就看不到明细了，而院长的等级比班主任高。

    **学院任务**（第三十二轮）：只有**院长 / 发布人**能看到全院的明细；
    班主任能看到，但**只限自己班那一份**（按班分组，见 `get_detail`）。
    """
    if is_college_task(task):
        if task.created_by == user.id:
            return True
        # 纯院长看全院（他管学院）；兼班主任的院长也看全院
        return user.role == DEAN_ROLE
    # 纯院长不参与班级事务：班级任务的明细他不该看
    if is_pure_dean(user):
        return False
    return task.created_by == user.id or user.role in _roles_at_least("TEACHER")


def can_answer(task: ClsTask, user: LoginUser) -> bool:
    """能不能提交/修改自己的答案。前端据此决定渲不渲染「填写答案」按钮。

    三个条件必须和 `is_answer_target` **严格同口径**，否则会出现两种很难查的毛病：

    - 放得太松：能提交，但提交的那条既不进分母、也不进明细（`is_answer_target`
      把它排掉了）。用户填了、提示"已提交"，回头发现谁也看不到他的答案。
    - 放得太紧：前端没渲染按钮，其实后端收——或者反过来，渲染了却 403。

    所以这里不自己另立规则，直接复用同一套判据。

    **学院任务**（第三十二轮）走另一套：应答对象是**各班班主任**，
    同学答不了（那是班级任务干的事）。
    """
    if is_college_task(task):
        # 学院任务：只有「各班班主任」交得上
        if not is_college_answer_target(user):
            return False
        if task.created_by == user.id:
            return False  # 你出的题你自己不算（和班级任务一个口径）
        if task.status != 1:
            return False
        if task.deadline is not None and datetime.now() > task.deadline:
            return False
        return True
    if user.role in NON_ANSWER_ROLES:
        return False  # 班主任发题催交，访客看情况——都不是被统计的同学
    if task.created_by == user.id:
        return False  # 你出的题你自己不算（班长是同学，但出的题也不答自己的）
    if task.status != 1:
        return False
    if task.deadline is not None and datetime.now() > task.deadline:
        return False
    return True


def is_open(task: ClsTask) -> bool:
    """是否还在收答案。status 是发布人的开关，deadline 是时间闸门，两个都会关。"""
    if task.status != 1:
        return False
    return task.deadline is None or datetime.now() <= task.deadline


def _require_task(db: Session, class_id: int, task_id: int) -> ClsTask:
    """按 id 取任务，并校验**这个班能不能碰它**。

    第三十二轮：任务分两种了——
    - **班级任务**：属于某个班，只有那个班的人能碰 ✓
    - **学院任务**（`scope=COLLEGE`）：**不属于任何班**，全学院可见。
      它的修改权在**发布人**（院长）自己手上，不按班算。
    """
    task = db.get(ClsTask, task_id)
    if task is None:
        raise BizException.bad_request("任务不存在")
    if is_college_task(task):
        # 学院任务不按班限制：谁能改由 `_require_publisher` 说了算
        return task
    if task.class_id != class_id:
        raise BizException.bad_request("任务不存在")
    return task


def _require_publisher(task: ClsTask, user: LoginUser) -> None:
    """改/关/删任务：发布人自己；**院长**可以管理全院任何任务（学院视角）。

    班主任不能删别人（班长）发的任务——「谁发的任务谁负责」这条线要保住；
    但院长是学院层管理员，学院视角的班级任务一览需要能统一编辑/关闭/删除。
    """
    if task.created_by != user.id and user.role != DEAN_ROLE:
        raise BizException.forbidden("只有发布这个任务的人才能修改它")


# ==================== 值的解析与归一 ====================


def _load_options(task: ClsTask) -> list[str]:
    if not task.options_json:
        return []
    try:
        raw = json.loads(task.options_json)
    except (TypeError, ValueError):
        return []
    return [str(x) for x in raw] if isinstance(raw, list) else []


def _dump_value(task: ClsTask, value) -> str | None:
    """按题型归一化答案；转不了就抛 400（绝不静默丢数据）。"""
    if value is None or (isinstance(value, str) and not value.strip()):
        raise BizException.bad_request(f"请填写「{task.question}」的答案")

    if task.qtype == "BOOLEAN":
        if isinstance(value, bool):
            return "true" if value else "false"
        s = str(value).strip().lower()
        if s in ("true", "false"):
            return s
        raise BizException.bad_request("这一题只能回答「是」或「否」")

    if task.qtype == "SINGLE":
        s = str(value).strip()
        options = _load_options(task)
        if s not in options:
            raise BizException.bad_request(f"「{s}」不在候选项里，请重新选择")
        return s

    if task.qtype == "MULTI":
        items = value if isinstance(value, list) else str(value).split(",")
        options = _load_options(task)
        picked: list[str] = []
        for raw in items:
            s = str(raw).strip()
            if not s:
                continue
            if s not in options:
                raise BizException.bad_request(f"「{s}」不在候选项里，请重新选择")
            if s not in picked:  # 去重但保序：重复勾同一项不该算两票
                picked.append(s)
        if not picked:
            raise BizException.bad_request("请至少选择一项")
        return json.dumps(picked, ensure_ascii=False)

    # DATE：存 YYYY-MM-DD。带时分秒也能收（datetime 的日期部分）
    s = str(value).strip()
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass
    try:
        return datetime.strptime(s, "%Y-%m-%d").date().isoformat()
    except ValueError:
        raise BizException.bad_request("日期格式应为 YYYY-MM-DD")


def _display_value(task: ClsTask, raw: str | None) -> str:
    """把存储值翻成人看的文字。汇总和明细、导出都用它，保证三处口径一致。"""
    if raw is None:
        return ""
    if task.qtype == "BOOLEAN":
        return BOOLEAN_LABELS.get(raw, raw)
    if task.qtype == "MULTI":
        try:
            items = json.loads(raw)
        except (TypeError, ValueError):
            return raw
        return "、".join(str(x) for x in items) if isinstance(items, list) else raw
    return raw


# ==================== 统计 ====================


def _summarize(task: ClsTask, answers: list[ClsTaskAnswer], total: int) -> dict:
    """汇总：**只给分布，不含具体是谁**——这是用户明确要的口径。

    未填单列一项，因为「还差谁没交」恰恰是发布人要的东西；而未填的人
    在明细页里能看到名字，汇总页只给个数。
    """
    answered = len(answers)
    out: dict = {
        "total": total,
        "answered": answered,
        "unanswered": max(0, total - answered),
        "options": [],
    }
    if task.qtype in ("BOOLEAN", "SINGLE", "MULTI"):
        if task.qtype == "BOOLEAN":
            buckets = ["true", "false"]  # 两个选项都要出现，哪怕没人选「否」
        elif task.qtype == "SINGLE":
            buckets = _load_options(task)
        else:
            buckets = _load_options(task)
        counts = {b: 0 for b in buckets}
        for a in answers:
            if task.qtype == "MULTI":
                try:
                    for item in json.loads(a.value_json or "[]"):
                        if item in counts:
                            counts[item] += 1
                except (TypeError, ValueError):
                    pass
            elif (a.value_json or "") in counts:
                counts[a.value_json] += 1
        out["options"] = [
            {"label": _display_value(task, b), "count": counts[b]} for b in buckets
        ]
    return out


# ==================== 读 ====================


def _build_rows(db: Session, user: LoginUser, tasks: list[ClsTask]) -> list[dict]:
    """把任务行拼成对外的 VO：每条自带「我填了吗」和汇总。

    **不给明细**：列表页对所有人一律只到汇总这一层，明细是单独一个端点
    （`/tasks/{id}/detail`），那里的闸门才是 `can_see_detail`。

    列表页和仪表盘的「置顶任务」共用这一段——两处**必须**拼出同一个形状，
    否则仪表盘上会出现只有列表页才有的字段（或反过来），改一处忘另一处
    就是"某个页面突然缺一块"的经典 bug。
    """
    if not tasks:
        return []

    # 应答对象池：CLASS 任务看**本班**，COLLEGE 任务看**全校的班主任**。
    # 一律把全校启用账号取出来（第三十二轮起任务不再只属于自己班）。
    active = (
        db.execute(select(SysUser).where(SysUser.status == 1)).scalars().all()
    )
    # 班级名（任务可能属于别的班，界面上要显示是哪个班发的）
    from ..models import ClsClass

    class_name_of = {
        int(cid): name
        for cid, name in db.execute(
            select(ClsClass.id, ClsClass.class_name)
        )
    }

    ids = [t.id for t in tasks]
    answers = (
        db.execute(select(ClsTaskAnswer).where(ClsTaskAnswer.task_id.in_(ids)))
        .scalars()
        .all()
    )
    by_task: dict[int, list[ClsTaskAnswer]] = {}
    mine: dict[int, ClsTaskAnswer] = {}
    for a in answers:
        by_task.setdefault(a.task_id, []).append(a)
        if a.user_id == user.id:
            mine[a.task_id] = a

    out = []
    for t in tasks:
        # 分母按任务各自算：发布人自己不答，所以这里要按 t.created_by 逐条筛。
        # ⚠ 分母按**任务自己的班**算（第三十二轮起任务可能属于别的班）：
        #   拿「我」的班去算别的班的分母，那个数字是错的。
        if is_college_task(t):
            base = sum(1 for u in active if is_college_answer_target(u))
        else:
            base = sum(
                1
                for u in active
                if u.class_id == t.class_id
                and is_answer_target(u, t.created_by, t.scope)
            )
        rows = by_task.get(t.id, [])
        my = mine.get(t.id)
        out.append(
            {
                "id": t.id,
                "title": t.title,
                "question": t.question,
                "qtype": t.qtype,
                "qtypeText": QTYPE_TEXT.get(t.qtype, t.qtype),
                # 第三十二轮：这条是班级任务还是学院任务（前端据此打标签）
                "scope": t.scope or SCOPE_CLASS,
                "scopeText": SCOPE_TEXT.get(t.scope or SCOPE_CLASS, "班级任务"),
                "classId": t.class_id,
                "className": class_name_of.get(t.class_id, ""),
                "options": _load_options(t),
                "allowText": bool(t.allow_text),
                "deadline": t.deadline.strftime("%Y-%m-%d %H:%M") if t.deadline else None,
                "open": is_open(t),
                "canAnswer": can_answer(t, user),
                "createdBy": t.created_by,
                "isMine": t.created_by == user.id,
                "canSeeDetail": can_see_detail(t, user),
                "canEdit": t.created_by == user.id,
                "pinned": bool(t.pinned),
                "createdAt": t.created_at.strftime("%Y-%m-%d %H:%M") if t.created_at else None,
                "myAnswer": (
                    {
                        "value": _display_value(t, my.value_json),
                        "raw": my.value_json,
                        "note": my.note,
                        "submittedAt": my.submitted_at.strftime("%Y-%m-%d %H:%M")
                        if my.submitted_at
                        else None,
                    }
                    if my
                    else None
                ),
                "summary": _summarize(t, rows, base),
            }
        )
    return out


#: 任务列表的**范围**（第三十二轮）。
#:
#: - `mine`（默认）：**本班**的任务 + **学院**的任务。班级任务页看这个。
#: - `college`：只有**学院任务**。
#: - `other`：**其他班**班主任发出来的任务（只对运营角色有意义——同学看别的班
#:   的任务与自己无关）。**只读**：不能答、看不到明细。
VIEW_MINE = "mine"
VIEW_COLLEGE = "college"
VIEW_OTHER = "other"
VIEWS = (VIEW_MINE, VIEW_COLLEGE, VIEW_OTHER)


def _visible_task_query(user: LoginUser, view: str):
    """按范围拼「我能看到的任务」。

    - `mine`：本班的（scope=CLASS）+ 学院任务（scope=COLLEGE）
    - `college`：只要学院任务
    - `other`：其他班的任务（不含本班、不含学院任务）
    """
    if is_pure_dean(user):
        # 纯院长只碰学院任务，看不到任何班级任务
        return select(ClsTask).where(ClsTask.scope == SCOPE_COLLEGE)
    if view == VIEW_COLLEGE:
        return select(ClsTask).where(ClsTask.scope == SCOPE_COLLEGE)
    if view == VIEW_OTHER:
        # 第三十三轮：**班级数据不互通**——任何角色都不能在这里看其他班。
        # 前端已去掉这一档；这里返回空集，防止旧前端 / 手输参数绕过。
        return select(ClsTask).where(ClsTask.id < 0)
    # 默认：本班 + 学院
    return select(ClsTask).where(
        or_(ClsTask.class_id == user.class_id, ClsTask.scope == SCOPE_COLLEGE)
    )


def list_tasks(db: Session, user: LoginUser, view: str = VIEW_MINE) -> list[dict]:
    """任务列表（按发布时间倒序）。

    `view` 决定看哪一块（见 `VIEWS`）。
    """
    if view not in VIEWS:
        view = VIEW_MINE
    tasks = (
        db.execute(
            _visible_task_query(user, view)
            .order_by(ClsTask.created_at.desc(), ClsTask.id.desc())
        )
        .scalars()
        .all()
    )
    return _build_rows(db, user, list(tasks))


#: 仪表盘「置顶任务」最多显示几条。和删掉的置顶公告面板一个量级：
#: 面板是给人「路过瞄一眼」的，超过 3 条就没人看了，反而稀释了置顶的意义。
PINNED_LIMIT = 3


def pinned_tasks(db: Session, user: LoginUser, limit: int = PINNED_LIMIT) -> list[dict]:
    """仪表盘的「置顶任务」：置顶 + **还在收答案**的，按快到期的排前面。

    两条设计取舍：

    1. **只显示还开放着的**。置顶的目的是催人填；任务一关闭，它就从仪表盘消失。
       发布人不用记得手动取消置顶——放着不管也不会一直占着所有人的仪表盘。
    2. **快到期的排前面**。置顶位是有限的（`limit`），同一个截止时间的东西
       先到先处理才对；不限时的排最后。

    可见性口径与任务列表**完全一致**（走同一个 `_build_rows`）：访客看得到但
    拿不到「我的答案」、`canAnswer` 为 false；明细在这里根本不存在。
    """
    if is_pure_dean(user):
        cond = (ClsTask.scope == SCOPE_COLLEGE) & (ClsTask.pinned == 1)
    else:
        cond = (ClsTask.class_id == user.class_id) & (ClsTask.pinned == 1)
    tasks = (
        db.execute(
            select(ClsTask)
            .where(cond)
            .order_by(ClsTask.created_at.desc(), ClsTask.id.desc())
        )
        .scalars()
        .all()
    )
    now = datetime.now()
    open_ones = [t for t in tasks if is_open(t)]
    # 有截止时间的在前（按 deadline 升序），不限时的排后面；同为 None 时保持
    # 原有的「新发布在前」，别让 Python 的稳定排序把顺序打乱成发布顺序倒序。
    open_ones.sort(key=lambda t: (t.deadline is None, t.deadline or now))
    return _build_rows(db, user, open_ones[:limit])


def get_detail(db: Session, user: LoginUser, task_id: int) -> dict:
    """明细：谁填了什么、谁还没填。**仅发布人和班主任**。

    这一页是整个模块里唯一出现别人答案的地方，也是催交和导出的依据。
    """
    task = _require_task(db, user.class_id, task_id)
    if not can_see_detail(task, user):
        raise BizException.forbidden("只有任务发布人和班主任能查看每个人的回答")

    # 学院任务：应答对象是**各班班主任**，明细**按班分组**。
    # 班主任只能看**自己班**那一份（别的班的返校情况不该让他看见）；
    # 院长 / 发布人看全部分组。
    college_scope = is_college_task(task)
    if college_scope:
        everyone = (
            db.execute(
                select(SysUser).where(
                    SysUser.status == 1, SysUser.role.in_(list(_roles_at_least(TEACHER_ROLE)))
                )
            )
            .scalars()
            .all()
        )
        # 纯院长不参与班级事务 → 不是应答对象
        everyone = [u for u in everyone if is_college_answer_target(u)]
        if user.role != DEAN_ROLE:
            # 班主任：只看自己班
            everyone = [u for u in everyone if u.class_id == user.class_id]
    else:
        everyone = (
            db.execute(
                select(SysUser).where(SysUser.class_id == task.class_id, SysUser.status == 1)
            )
            .scalars()
            .all()
        )
    answers = {
        a.user_id: a
        for a in db.execute(
            select(ClsTaskAnswer).where(ClsTaskAnswer.task_id == task_id)
        ).scalars()
    }

    rows, answered, with_note = [], 0, 0
    for u in everyone:
        # 发布人自己不答；访客永远交不上，列出来只会让「未填」永远挂着一个人
        if not is_answer_target(u, task.created_by, task.scope):
            continue
        a = answers.get(u.id)
        if a is not None:
            answered += 1
            if a.note:
                with_note += 1
        rows.append(
            {
                "userId": u.id,
                "name": u.real_name,
                "username": u.username,
                "role": u.role,
                "answered": a is not None,
                "value": _display_value(task, a.value_json) if a else None,
                "raw": a.value_json if a else None,
                "note": a.note if a else None,
                "submittedAt": a.submitted_at.strftime("%Y-%m-%d %H:%M")
                if a and a.submitted_at
                else None,
            }
        )
    # 未交的排前面：发布人打开这一页就是为了催人
    rows.sort(key=lambda r: (r["answered"], r["name"]))

    return {
        "taskId": task.id,
        "title": task.title,
        "question": task.question,
        "qtype": task.qtype,
        "qtypeText": QTYPE_TEXT.get(task.qtype, task.qtype),
        "allowText": bool(task.allow_text),
        "deadline": task.deadline.strftime("%Y-%m-%d %H:%M") if task.deadline else None,
        "open": is_open(task),
        "rows": rows,
        "answered": answered,
        "unanswered": max(0, len(rows) - answered),
        "noteCount": with_note,
        "summary": _summarize(task, list(answers.values()), len(rows)),
    }


# ==================== 任务总览（第三十二轮） ====================


def overview(db: Session, user: LoginUser) -> dict:
    """任务总览：**我能看到的**任务都统计一遍。

    放在「班级任务」上面那一页，给的是「现在什么状况」而不是「有哪些任务」：
    多少条、还开着几条、回收率多少、哪个班交得最齐。

    统计范围 = 任务列表的可见范围（本班 + 学院任务），
    加上**其他班**的任务（只对运营角色）——不然总览就少了大半。
    """
    is_staff = user.role in _roles_at_least(TEACHER_ROLE)
    if is_staff:
        tasks = db.execute(
            select(ClsTask).order_by(ClsTask.created_at.desc(), ClsTask.id.desc())
        ).scalars().all()
    else:
        tasks = db.execute(
            _visible_task_query(user, VIEW_MINE)
            .order_by(ClsTask.created_at.desc(), ClsTask.id.desc())
        ).scalars().all()

    rows = _build_rows(db, user, list(tasks))
    total = len(rows)
    open_count = sum(1 for r in rows if r["open"])
    college_count = sum(1 for r in rows if r["scope"] == SCOPE_COLLEGE)
    class_count = total - college_count

    # 回收率：已答 / 应答对象。分母为 0 的任务不算进去（没人数就没法算比例）
    answered = 0
    base = 0
    for r in rows:
        s = r.get("summary") or {}
        b = int(s.get("total") or 0)
        if b <= 0:
            continue
        base += b
        answered += int(s.get("answered") or 0)
    rate = round(answered * 100.0 / base, 1) if base else None

    # 按班分布：每个班多少条任务、答了多少
    # 学院任务**不属于任何班**（class_id 只是发布人的默认班）——
    # 归到「全学院」一栏，否则会显得是某个班发出来的。
    by_class: dict[int, dict] = {}
    for r in rows:
        is_college = r.get("scope") == SCOPE_COLLEGE
        cid = 0 if is_college else int(r.get("classId") or 0)
        slot = by_class.setdefault(
            cid,
            {
                "classId": cid,
                "className": "全学院" if is_college else (r.get("className") or ""),
                "total": 0,
                "open": 0,
                "answered": 0,
                "base": 0,
            },
        )
        slot["total"] += 1
        if r["open"]:
            slot["open"] += 1
        s = r.get("summary") or {}
        b = int(s.get("total") or 0)
        if b > 0:
            slot["base"] += b
            slot["answered"] += int(s.get("answered") or 0)
    class_rows = []
    for slot in by_class.values():
        b = slot["base"]
        slot["rate"] = round(slot["answered"] * 100.0 / b, 1) if b else None
        class_rows.append(slot)
    class_rows.sort(key=lambda x: (-x["total"], x["className"]))

    # 按发布人分布：谁发的、发了几条
    by_publisher: dict[int, dict] = {}
    names = {
        int(uid): (name or uname)
        for uid, name, uname in db.execute(
            select(SysUser.id, SysUser.real_name, SysUser.username)
        )
    }
    for r in rows:
        pid = int(r.get("createdBy") or 0)
        slot = by_publisher.setdefault(
            pid, {"userId": pid, "name": names.get(pid, "未知"), "total": 0, "open": 0}
        )
        slot["total"] += 1
        if r["open"]:
            slot["open"] += 1
    publisher_rows = sorted(by_publisher.values(), key=lambda x: (-x["total"], x["name"]))

    return {
        "canSeeAll": is_staff,
        "total": total,
        "open": open_count,
        "closed": total - open_count,
        "classTasks": class_count,
        "collegeTasks": college_count,
        "answered": answered,
        "base": base,
        "rate": rate,
        "byClass": class_rows,
        "byPublisher": publisher_rows,
        "recent": rows[:10],
    }



# ==================== 写 ====================


def create_task(
    db: Session,
    user: LoginUser,
    title: str,
    question: str,
    qtype: str,
    options: list[str] | None,
    allow_text: bool,
    deadline: datetime | None,
    scope: str = SCOPE_CLASS,
) -> dict:
    """发布任务。

    **学院任务**（第三十二轮，`scope='COLLEGE'`）只有**院长**能发：
    它面向全学院，班主任发的话就成了「这个班的老师给全学院布置任务」——
    层级不对。

    学院任务的**应答对象是各班班主任**（见 `is_college_answer_target`），
    也就是「各班统计一下本班情况，交上来」。
    """
    if scope not in SCOPES:
        scope = SCOPE_CLASS
    if scope == SCOPE_COLLEGE:
        if user.role != DEAN_ROLE:
            raise BizException.forbidden("只有院长能发布学院任务")
    elif is_pure_dean(user):
        # 纯院长只发学院任务；班级任务归班主任（或班委）
        raise BizException.forbidden(
            "纯院长只能发布学院任务；班级任务请由班主任（或班委）处理"
        )
    elif not can_publish(user):
        raise BizException.forbidden("只有班主任或班长可以发布任务")
    if qtype not in QTYPES:
        raise BizException.bad_request("题目类型不对")

    opts: list[str] = []
    if qtype in ("SINGLE", "MULTI"):
        opts = [str(o).strip() for o in (options or []) if str(o).strip()]
        if len(opts) < 2:
            raise BizException.bad_request("单选题和多选题至少要有 2 个候选项")
        if len(opts) > MAX_OPTIONS:
            raise BizException.bad_request(f"候选项最多 {MAX_OPTIONS} 个")
        if any(len(o) > MAX_OPTION_LEN for o in opts):
            raise BizException.bad_request(f"每个候选项最多 {MAX_OPTION_LEN} 字")
        dup = {o for o in opts if opts.count(o) > 1}
        if dup:
            raise BizException.bad_request("候选项不能重复：" + "、".join(sorted(dup)))

    task = ClsTask(
        class_id=user.class_id,
        title=title.strip(),
        question=question.strip(),
        qtype=qtype,
        options_json=json.dumps(opts, ensure_ascii=False) if opts else None,
        allow_text=1 if allow_text else 0,
        deadline=deadline,
        status=1,
        scope=scope,
        created_by=user.id,
    )
    with db.begin():
        db.add(task)
    db.refresh(task)
    return {"id": task.id, "title": task.title, "scope": task.scope}


def update_task(
    db: Session,
    user: LoginUser,
    task_id: int,
    *,
    title: str,
    question: str,
    deadline: datetime | None,
    status: int | None,
    allow_text: bool,
) -> dict:
    """改任务。

    **刻意不能改题型、不能改候选项**：已有回答是按原文存的，
    换题型会让老答案对不上题（"true" 去回答一个日期题）。
    要换题就删了重发。
    """
    with db.begin():
        task = _require_task(db, user.class_id, task_id)
        _require_publisher(task, user)
        task.title = title.strip()
        task.question = question.strip()
        task.deadline = deadline
        task.allow_text = 1 if allow_text else 0
        if status is not None:
            task.status = 1 if status else 0
    db.refresh(task)
    return {"id": task.id, "open": is_open(task)}


def set_status(db: Session, user: LoginUser, task_id: int, open_: bool) -> dict:
    """关闭 / 重新开放。已收回的回答保留，重新开放后还在。"""
    with db.begin():
        task = _require_task(db, user.class_id, task_id)
        _require_publisher(task, user)
        task.status = 1 if open_ else 0
    db.refresh(task)
    return {"id": task.id, "open": is_open(task)}


def set_pinned(db: Session, user: LoginUser, task_id: int, pinned: bool) -> dict:
    """置顶 / 取消置顶。**只有发布人自己**——和改标题、关闭同一个闸门。

    置顶占用的是**每个人**的仪表盘，比关掉自己一道题影响面大得多，
    所以不能只按「能不能发布任务」放行——生活委员和班长都能发任务，
    但只能置顶自己发的那些。
    """
    with db.begin():
        task = _require_task(db, user.class_id, task_id)
        _require_publisher(task, user)
        task.pinned = 1 if pinned else 0
    db.refresh(task)
    return {"id": task.id, "pinned": bool(task.pinned)}


def submit_answer(
    db: Session, user: LoginUser, task_id: int, value, note: str | None
) -> dict:
    """提交/修改**自己**的答案。一人一任务一条（uk_task_user），重复提交是"改"。"""
    with db.begin():
        task = _require_task(db, user.class_id, task_id)
        if is_college_task(task):
            # 学院任务（第三十二轮）：应答对象是**各班班主任**，同学答不了。
            # 这条分支不能省——班主任在 NON_ANSWER_ROLES 里（班级任务里他不填），
            # 拿老口径一刀切下去，全校班主任就一个都交不上。
            if not is_college_answer_target(user):
                raise BizException.forbidden(
                    "学院任务由各班班主任应答，同学不用填"
                )
        elif user.role in NON_ANSWER_ROLES:
            raise BizException.forbidden(
                "班主任和访客不在被统计的同学名单里，只能发题和查看，不能填写"
            )
        if task.created_by == user.id:
            raise BizException.forbidden("发布人可以查看答题情况，不用填自己的题")
        if task.status != 1:
            raise BizException.bad_request("这个任务已经关闭，不能再填")
        if task.deadline is not None and datetime.now() > task.deadline:
            raise BizException.bad_request("这个任务已经过截止时间了")

        stored = _dump_value(task, value)
        text = (note or "").strip() or None
        if text and not task.allow_text:
            text = None  # 没开补充说明就忽略，不报错——多写的字没必要拦
        if text and len(text) > MAX_VALUE_LEN:
            raise BizException.bad_request(f"补充说明最多 {MAX_VALUE_LEN} 字")

        existing = db.execute(
            select(ClsTaskAnswer).where(
                ClsTaskAnswer.task_id == task_id, ClsTaskAnswer.user_id == user.id
            )
        ).scalar_one_or_none()
        if existing is None:
            db.add(
                ClsTaskAnswer(task_id=task_id, user_id=user.id, value_json=stored, note=text)
            )
        else:
            existing.value_json = stored
            existing.note = text
            existing.submitted_at = datetime.now()

    return {"taskId": task_id, "value": _display_value(task, stored), "raw": stored, "note": text}


def delete_task(db: Session, user: LoginUser, task_id: int) -> None:
    """删除任务，**连带回答**（发布人删题 = 这题的答案没有保留意义）。

    先删回答不是冗余：整个库**一张外键都没有**（`information_schema` 里
    FOREIGN KEY 约束数为 0，只建索引不建外键），
    所以 DDL 里的 `ON DELETE CASCADE` 并不存在，删任务不会自动带走答案。
    少这一句就是一批永久孤儿数据，而且没人会来报。
    """
    with db.begin():
        task = _require_task(db, user.class_id, task_id)
        _require_publisher(task, user)
        db.execute(delete(ClsTaskAnswer).where(ClsTaskAnswer.task_id == task_id))
        db.execute(delete(ClsTask).where(ClsTask.id == task_id))