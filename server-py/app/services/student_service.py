"""学生信息服务：动态字段 + 学号锚点记录 + 访问申请/授权。

## 权限模型（第二十三轮，用户明确要求的口径）

用户原话：「每个学生班级信息这里只能看见自己那一行，然后增加一个申请编辑按钮。
班长登录之后也只能看见自己那一行详细信息，要是班主任想让班长修改的话，
班长必须申请查看所有信息」「自能看见自己那一行所有信息」。

据此定成**行级**而非字段级权限（第一版我误按字段级设计，被用户纠正）：

| 角色 | 默认能看 | 默认能改 | 需要申请才能获得 |
|------|---------|---------|----------------|
| 班主任 TEACHER | 全部行 | 全部行 | — |
| 班长 MONITOR / 生活委员 ADMIN | **只有自己那一行** | 否 | `EDIT_OWN` / `VIEW_ALL` / `EDIT_ALL` |
| 普通成员 MEMBER | **只有自己那一行** | 否 | 同上 |

三个 scope 的含义与蕴含关系：

- `EDIT_OWN`：能改自己那一行（不含看别人）
- `VIEW_ALL`：能看所有人的行（不含改）
- `EDIT_ALL`：能改所有人的行，**蕴含 VIEW_ALL**

**为什么连「改自己那行」都要申请**：让学生可以自行改写自己的学号、身份证号、贫困建档标记，
等于把数据可信度交给被登记人自己。这条是有意收紧的，不是遗漏。

## 为什么申请与授权分两张表

`student_access_request` 是**流水**（申请过几次、被批被拒都要留痕）；
`student_grant` 是**当前状态**（现在到底有什么权限）。
如果只查「最新一条申请的状态」，撤销场景会算错——批过、撤销、再批过，状态会跳。
"""
from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import (
    StudentAccessRequest,
    StudentField,
    StudentGrant,
    StudentRecord,
    StudentRecordValue,
    SysUser,
)
from ..security import LoginUser

# ---------------- scope 常量（唯一的语义来源） ----------------
SCOPE_EDIT_OWN = "EDIT_OWN"
SCOPE_VIEW_ALL = "VIEW_ALL"
SCOPE_EDIT_ALL = "EDIT_ALL"
SCOPES = (SCOPE_EDIT_OWN, SCOPE_VIEW_ALL, SCOPE_EDIT_ALL)

SCOPE_TEXT = {
    SCOPE_EDIT_OWN: "修改本人信息",
    SCOPE_VIEW_ALL: "查看全部学生信息",
    SCOPE_EDIT_ALL: "编辑全部学生信息",
}
SCOPES_REQUIRING_APPROVAL = frozenset(SCOPES)

# 字段类型
FT_TEXT, FT_NUMBER, FT_DATE, FT_BOOL = "TEXT", "NUMBER", "DATE", "BOOL"
FIELD_TYPES = (FT_TEXT, FT_NUMBER, FT_DATE, FT_BOOL)
FIELD_TYPE_TEXT = {
    FT_TEXT: "文本",
    FT_NUMBER: "数字",
    FT_DATE: "日期",
    FT_BOOL: "是/否",
}

# 可以新增字段的角色：**班主任 + 班长**（用户明确要求）。生活委员不行。
FIELD_ADD_ROLES = frozenset({"TEACHER", "MONITOR"})
# 审批人只有班主任（用户原话「这个得让班主任来授权」）
APPROVER_ROLES = frozenset({"TEACHER"})

# 访客（第二十四轮）：**纯只读**。
#
# 定位是给领导/校方看情况的：能看全班学生信息、能勾选导出，但一行都改不了。
# 与普通成员（MEMBER）的区别在两处，都刻意做得很窄：
#   1. 能看**所有**学生的信息——MEMBER 默认只看得到自己那一行，对领导毫无意义
#   2. 不能改、不能加字段、不能审批、不能进成员管理
#
# 刻意**不放进** APPROVER_ROLES / FIELD_ADD_ROLES：那是「班主任」和「班长」的特权，
# 访客一个都沾不到。
GUEST_ROLE = "GUEST"
#: 访客可见哪些 scope。只给「看全部」，不给任何编辑权。
GUEST_SCOPES = frozenset({SCOPE_VIEW_ALL})

_KEY_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")

#: 锚点列的列标识。这两列不在字段表里，是后端拼在最前面的。
#: 导出时**无条件保留**——一份没有学号的表格没法说明每一行是谁。
ANCHOR_KEYS = ("__no__", "__name__")


# ==================== 权限计算 ====================

def granted_scopes(db: Session, class_id: int, user_id: int) -> set[str]:
    """当前已授予该用户的 scope 集合（**含蕴含展开**）。

    `EDIT_ALL` 蕴含 `VIEW_ALL`：能改所有人的行，当然也能看。不展开的话，
    读路径和写路径要各写一遍蕴含判断，迟早漏一处。
    """
    rows = db.scalars(
        select(StudentGrant.scope).where(
            StudentGrant.class_id == class_id, StudentGrant.user_id == user_id
        )
    )
    out = set(rows)
    if SCOPE_EDIT_ALL in out:
        out.add(SCOPE_VIEW_ALL)
    return out


def _my_record(db: Session, class_id: int, user: LoginUser) -> StudentRecord | None:
    """当前登录用户对应的「自己那一行」。

    匹配口径：`sys_user.student_no == student_record.student_no`。
    没填学号的账号匹配不到（返回 None），此时界面要给出「先在个人信息里补学号」的提示，
    而不是显示一个空表格让人以为没有数据。
    """
    row = db.execute(
        select(StudentRecord).where(
            StudentRecord.class_id == class_id, StudentRecord.user_id == user.id
        )
    ).scalar_one_or_none()
    if row is not None:
        return row
    account = db.get(SysUser, user.id)
    if account is None or not (account.student_no or "").strip():
        return None
    return db.execute(
        select(StudentRecord).where(
            StudentRecord.class_id == class_id,
            StudentRecord.student_no == account.student_no.strip(),
        )
    ).scalar_one_or_none()


def visibility(db: Session, user: LoginUser) -> dict:
    """当前用户的可见/可编辑范围，同时返回自己那一行。

    返回体是给前端用的**权限快照**，前端据此决定锁图标、按钮显隐——
    但真正的闸门在 `_assert_can_*` 里，前端只是体验。
    """
    is_guest = user.role == GUEST_ROLE
    # 访客的可见范围是**角色内建的**，不查 student_grant：
    # 领导账号不该出现在「授权清单」里被审批流程管着，那会让班主任
    # 看到一堆莫名其妙的授权记录。
    scopes = GUEST_SCOPES if is_guest else granted_scopes(db, user.class_id, user.id)
    is_teacher = user.role in APPROVER_ROLES
    mine = _my_record(db, user.class_id, user)
    can_view_all = is_teacher or SCOPE_VIEW_ALL in scopes or SCOPE_EDIT_ALL in scopes
    can_edit_all = is_teacher or SCOPE_EDIT_ALL in scopes
    can_edit_own = is_teacher or SCOPE_EDIT_OWN in scopes or can_edit_all
    # 匹配不到自己那一行时，要区分「没有登记记录」和「账号没填学号」——
    # 后者是可以自己解决的，前者要找班主任导入，提示语不能混。
    account = db.get(SysUser, user.id)
    account_has_no = not ((account.student_no if account else "") or "").strip()
    return {
        "scopes": sorted(scopes),
        "isTeacher": is_teacher,
        "isGuest": is_guest,
        "canViewAll": can_view_all,
        "canEditAll": can_edit_all,
        "canEditOwn": can_edit_own,
        "canAddField": user.role in FIELD_ADD_ROLES,
        "myRecordId": mine.id if mine is not None else None,
        "myStudentNo": mine.student_no if mine is not None else None,
        "accountHasNoStudentNo": bool(mine is None and account_has_no),
        "classHasNoRecords": bool(mine is None and not account_has_no),
    }


def _assert_can_edit(db: Session, user: LoginUser, record: StudentRecord) -> None:
    """闸门：改某一行之前必须持有对应权限。班主任恒可。"""
    if user.role in APPROVER_ROLES:
        return
    scopes = granted_scopes(db, user.class_id, user.id)
    if SCOPE_EDIT_ALL in scopes:
        return
    mine = _my_record(db, user.class_id, user)
    if mine is not None and mine.id == record.id and SCOPE_EDIT_OWN in scopes:
        return
    if mine is not None and mine.id == record.id:
        raise BizException.forbidden(
            "尚未获得「修改本人信息」权限，请点击申请按钮，等班主任审批通过后再改"
        )
    raise BizException.forbidden(
        "尚未获得「编辑全部学生信息」权限，请点击申请按钮，等班主任审批通过后再改"
    )


def _visible_record_ids(db: Session, user: LoginUser) -> list[int]:
    """当前用户能看到的记录 id 列表。班主任/已授权=全部，否则只有自己那行。"""
    vis = visibility(db, user)
    if vis["canViewAll"]:
        return [
            int(i)
            for i in db.scalars(
                select(StudentRecord.id).where(StudentRecord.class_id == user.class_id)
            )
        ]
    return [vis["myRecordId"]] if vis["myRecordId"] is not None else []


# ==================== 值解析 / 格式化 ====================

def _norm_date(raw: str) -> str | None:
    """把各种日期写法归一成 `YYYY-MM-DD`。

    实测来源有三类，导入时都会遇到：
    - Excel 里存的是**数字** `20071209`（number_format=General，不是日期序列号）
    - 已有的 `2026-09-01`
    - `2026/9/1`
    存进库一律是 `YYYY-MM-DD`，展示与导出都只认这一种。
    """
    s = (raw or "").strip()
    if not s:
        return None
    digits = re.sub(r"\D", "", s)
    if len(digits) == 8:
        try:
            return datetime.strptime(digits, "%Y%m%d").date().isoformat()
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    raise BizException.bad_request(f"日期格式无法识别：{s}（应形如 20071209 或 2007-12-09）")


def _norm_bool(raw: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    if s in ("是", "否"):
        return s
    if s in ("1", "true", "True", "Y", "yes", "Y", "Y"):
        return "是"
    if s in ("0", "false", "False", "N", "no", "N", "N"):
        return "否"
    raise BizException.bad_request(f"是/否字段只能填「是」或「否」，收到：{s}")


def _norm_number(raw: str, label: str) -> str | None:
    s = (raw or "").strip()
    if not s:
        return None
    try:
        d = Decimal(s)
    except InvalidOperation as exc:
        raise BizException.bad_request(f"「{label}」应为数字，收到：{s}") from exc
    if not d.is_finite():
        raise BizException.bad_request(f"「{label}」不是有效数字：{s}")
    # 去掉无意义的小数尾零，但保留整数形态（学号类字段不能用科学计数法）
    d = d.normalize()
    if d == d.to_integral_value():
        return str(d.quantize(Decimal(1)))
    return format(d, "f")


def normalize_value(field_type: str, raw: str, label: str) -> str | None:
    """按字段类型归一化；TEXT 原样去首尾空白。空值统一成 None（=未填）。"""
    if field_type == FT_DATE:
        return _norm_date(raw)
    if field_type == FT_BOOL:
        return _norm_bool(raw)
    if field_type == FT_NUMBER:
        return _norm_number(raw, label)
    s = (raw or "").strip()
    return s or None


# ==================== 字段管理 ====================

def list_fields(db: Session, user: LoginUser, include_disabled: bool = False) -> list[dict]:
    """字段列表。`include_disabled=True` 时把已停用的也带上（带 `status` 字段）。

    默认只给启用的——表格、导出、导入匹配都按"用户看得见的列"走，
    停用的列不该出现在这些地方。但"已停用字段"面板要能看到它们，才能恢复。
    """
    q = select(StudentField).where(StudentField.class_id == user.class_id)
    if not include_disabled:
        q = q.where(StudentField.status == 1)
    rows = list(db.scalars(q.order_by(StudentField.sort.asc(), StudentField.id.asc())))
    return [
        {
            "id": f.id,
            "key": f.field_key,
            "label": f.field_label,
            "type": f.field_type,
            "typeText": FIELD_TYPE_TEXT.get(f.field_type, f.field_type),
            "isSystem": bool(f.is_system),
            "sort": f.sort,
            "status": f.status,
            "locked": not (user.role in FIELD_ADD_ROLES),
        }
        for f in rows
    ]


def _next_sort(db: Session, class_id: int) -> float:
    """追加到末尾时该用的 sort 值（比现有最大列大 10）。"""
    mx = db.scalar(
        select(func.coalesce(func.max(StudentField.sort), 0)).where(
            StudentField.class_id == class_id
        )
    )
    return int(mx or 0) + 10


def create_field(db: Session, user: LoginUser, req, before_key: str | None = None) -> dict:
    """新增字段。**班主任 + 班长**可以（用户明确要求）。

    `before_key` 指定插在哪一列**前面**——表头上那个 `＋` 就是这个意思。
    不传（空）= 追加到末尾。

    传一个不存在/已停用的 key 时**回退到末尾**而不是报错：字段可能刚被别人停用，
    用户还按旧表头操作着，静默追加比甩一个红字更好懂。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以新增字段")
    label = (req.label or "").strip()
    if not label:
        raise BizException.bad_request("请填写字段名称")
    if len(label) > 64:
        raise BizException.bad_request("字段名称不能超过 64 个字符")
    ftype = (req.type or FT_TEXT).strip() or FT_TEXT
    if ftype not in FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(FIELD_TYPES)}")
    key = (req.key or "").strip()
    if key:
        if not _KEY_RE.match(key):
            raise BizException.bad_request("字段标识只能由字母开头，含字母/数字/下划线，最长 64 位")
    else:
        key = f"f_{int(datetime.now().timestamp() * 1000)}"

    # 查重必须在事务内（SELECT 会开隐式事务，见 create_request 的注释）
    with db.begin():
        exists = db.execute(
            select(StudentField.id).where(
                StudentField.class_id == user.class_id, StudentField.field_key == key
            )
        ).scalar_one_or_none()
        if exists is not None:
            raise BizException.bad_request(f"字段标识 {key} 已存在")
        max_sort = db.scalar(
            select(func.coalesce(func.max(StudentField.sort), 0)).where(
                StudentField.class_id == user.class_id
            )
        )
        base = int(max_sort or 0)
        # 「插在某列**前面**」→ sort 取它和前一列的中间值；不指定就追加到末尾。
        # 用**浮点中点**而不是整数重排：重排要给所有后续字段发一次 UPDATE，
        # 而用户在界面上「在 B 前面插一列」不应该牵动十几列的排序。
        #
        # 这里必须是"前"而不是"后"：界面上每个表头的 ＋ 都表示"插在我前面"，
        # 而表格**没有**额外的末尾按钮（加了就等于在最后一行后面多一列空白），
        # 所以"插到最前面"这个位置只能靠这个语义表达。
        sort = base + 10
        if before_key:
            anchor = db.scalar(
                select(StudentField.sort).where(
                    StudentField.class_id == user.class_id,
                    StudentField.field_key == before_key,
                    StudentField.status == 1,
                )
            )
            if anchor is not None:
                prev = db.scalar(
                    select(func.max(StudentField.sort)).where(
                        StudentField.class_id == user.class_id,
                        StudentField.status == 1,
                        StudentField.sort < anchor,
                    )
                )
                # 插到最前面时没有前一列，取 anchor-5（沿用"往后退一格"的步长）
                sort = (prev + anchor) / 2 if prev is not None else anchor - 5
        f = StudentField(
            class_id=user.class_id,
            field_key=key,
            field_label=label,
            field_type=ftype,
            is_system=0,
            sort=sort,
            status=1,
            created_by=user.id,
        )
        db.add(f)
        db.flush()
        return {
            "id": f.id,
            "key": f.field_key,
            "label": f.field_label,
            "type": f.field_type,
            "typeText": FIELD_TYPE_TEXT.get(f.field_type, f.field_type),
            "isSystem": False,
            "sort": f.sort,
            "locked": False,
        }


def update_field(db: Session, user: LoginUser, field_key: str, req) -> dict:
    """改字段的显示名 / 类型 / 排序。

    **按 field_key 定位**，和 `delete_field` 保持同一个入口——表格里每列操作
    拿到的都是 key，为了改个名字先拿 id 是没必要的绕路。

    `field_key` 本身一律不可改（改了历史数据就对不上）。
    停用中的字段也允许改，改完保持停用，免得"改个名"就把一列意外复活了。

    ## 改类型会动已存的值
    值是按文本存的（EAV），类型只决定**写入时怎么校验、界面怎么显示**。
    所以 TEXT 改成 DATE 之后，库里那些 `"20250901"` 还是老样子，
    日期选择器会认不出来——必须**同步把存量值重新归一化**。

    这里不直接改类型，而是要求先 `preview_field_retype()` 看一遍：
    有的值转不了（`"待缴"` 没法变日期），直接改就等于静默毁数据。
    确认流程见 `apply_field_retype()`。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    with db.begin():
        f = db.execute(
            select(StudentField).where(
                StudentField.class_id == user.class_id,
                StudentField.field_key == field_key,
            )
        ).scalar_one_or_none()
        if f is None:
            raise BizException.bad_request("字段不存在或已删除")
        if req.label is not None:
            label = req.label.strip()
            if not label:
                raise BizException.bad_request("字段名称不能为空")
            f.field_label = label[:64]
        if req.type is not None and req.type != f.field_type:
            # 类型不能在这里偷偷改：存量值要重新归一化，有的值转不了。
            # 强制走 preview → apply 两步，见 apply_field_retype()。
            raise BizException.bad_request(
                "改字段类型请使用「改类型」接口（会同步转换已填的值）"
            )
        if req.sort is not None:
            f.sort = req.sort
        db.flush()
        return {
            "id": f.id,
            "key": f.field_key,
            "label": f.field_label,
            "type": f.field_type,
            "typeText": FIELD_TYPE_TEXT.get(f.field_type, f.field_type),
            "isSystem": bool(f.is_system),
            "sort": f.sort,
            "locked": False,
        }


# ==================== 改字段类型（两步：先看，再动） ====================

#: 预览时最多回多少条给用户看
_RETYPE_SAMPLE = 8


def _get_field(db: Session, user: LoginUser, field_key: str) -> StudentField:
    """按 key 取字段。**读操作必须留在调用方的事务里**：

    SQLAlchemy 里一旦执行过 SELECT，Session 就开了隐式事务，
    调用方再 `db.begin()` 会抛 `InvalidRequestError`（表现为 HTTP 500）。
    """
    f = db.execute(
        select(StudentField).where(
            StudentField.class_id == user.class_id,
            StudentField.field_key == field_key,
        )
    ).scalar_one_or_none()
    if f is None:
        raise BizException.bad_request("字段不存在或已删除")
    return f


def _plan_retype(
    db: Session, f: StudentField, new_type: str
) -> tuple[list[tuple[int, str, str]], list[tuple[int, str, str]], int]:
    """算出改类型之后每个存量值会变成什么。

    返回 `(可转换, 转不了, 空值数)`，前两项是 `(值id, 原值, 新值)`。
    **原值一起带出来**：预览表要显示 `20250901 → 2025-09-01`，
    只回新值就得再查一次库（N+1）。

    三类分开是因为用户需要区别对待：
    - **可转换**：会被改写成新格式，这是他要的
    - **转不了**：比如把「待缴」转成日期。清空还是保留原样，由用户选
    - **空值**：未填就是未填，不用管
    """
    rows = db.execute(
        select(StudentRecordValue.id, StudentRecordValue.value_text)
        .where(StudentRecordValue.field_id == f.id)
        .order_by(StudentRecordValue.id.asc())
    ).all()
    ok: list[tuple[int, str, str]] = []
    bad: list[tuple[int, str, str]] = []
    empty = 0
    for vid, raw in rows:
        text = raw or ""
        if not text.strip():
            empty += 1
            continue
        try:
            norm = normalize_value(new_type, text, f.field_label)
        except BizException:
            bad.append((vid, text, text))
            continue
        if norm is None:
            bad.append((vid, text, text))
        else:
            ok.append((vid, text, norm))
    return ok, bad, empty


def preview_field_retype(db: Session, user: LoginUser, field_key: str, new_type: str) -> dict:
    """改类型前先看一眼会发生什么。**不写库。**

    用户改类型的场景是"导入时类型猜错了"。猜错的列里往往混着几个
    转不过来的值（某个格子写的是"待缴"），直接改会静默毁掉它们，
    所以必须先把这笔账摊开让用户看。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    if new_type not in FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(FIELD_TYPES)}")
    with db.begin():
        f = _get_field(db, user, field_key)
        if f.field_type == new_type:
            raise BizException.bad_request("新类型和当前一样，不用改")
        ok, bad, empty = _plan_retype(db, f, new_type)
        return {
            "key": f.field_key,
            "label": f.field_label,
            "fromType": f.field_type,
            "fromTypeText": FIELD_TYPE_TEXT.get(f.field_type, f.field_type),
            "toType": new_type,
            "toTypeText": FIELD_TYPE_TEXT.get(new_type, new_type),
            "total": len(ok) + len(bad) + empty,
            "convertibleCount": len(ok),
            "convertibleSamples": [
                {"before": before, "after": after} for _vid, before, after in ok[:_RETYPE_SAMPLE]
            ],
            "convertibleTruncated": max(0, len(ok) - _RETYPE_SAMPLE),
            "unconvertibleCount": len(bad),
            "unconvertibleSamples": [
                {"before": before} for _vid, before, _after in bad[:_RETYPE_SAMPLE]
            ],
            "unconvertibleTruncated": max(0, len(bad) - _RETYPE_SAMPLE),
            "emptyCount": empty,
        }


def apply_field_retype(
    db: Session, user: LoginUser, field_key: str, new_type: str, clear_bad: bool = False
) -> dict:
    """确认改类型：按 `preview_field_retype` 算出的方案落地。

    `clear_bad=False`（默认）——转不了的值**保留原文本**。
    这样把类型改错了还能改回来，不丢数据。
    `clear_bad=True` ——转不了的值置空，用户明确说"这些不要了"。

    保留的那些值现在不符合新类型的约束，但下次编辑这一格时会走
    `normalize_value` 校验，存不进去会被拒——那时用户自然会去把内容改对，
    比现在替他清空要好。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    if new_type not in FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(FIELD_TYPES)}")
    with db.begin():
        f = _get_field(db, user, field_key)
        old_type = f.field_type
        if old_type == new_type:
            raise BizException.bad_request("新类型和当前一样，不用改")
        ok, bad, _empty = _plan_retype(db, f, new_type)

        for vid, _before, after in ok:
            v = db.get(StudentRecordValue, vid)
            if v is not None:
                v.value_text = after
        if clear_bad:
            for vid, _before, _after in bad:
                v = db.get(StudentRecordValue, vid)
                if v is not None:
                    v.value_text = None
        f.field_type = new_type
        db.flush()
        return {
            "key": f.field_key,
            "label": f.field_label,
            "fromType": old_type,
            "toType": new_type,
            "convertedCount": len(ok),
            "keptUnconvertibleCount": 0 if clear_bad else len(bad),
            "clearedCount": len(bad) if clear_bad else 0,
        }


def delete_field(db: Session, user: LoginUser, field_key: str) -> None:
    """停用字段（软删）。**按字段标识 key 定位**，不按 id。

    模板字段（`is_system=1`）**也允许停用**（第二十四轮改）。之前是禁用的，
    理由是「模板字段是对账口径的一部分」——但 34 列里身份证号、院校代码、
    专业代码这些填班费台账根本用不到，却占着屏幕宽度，让表格宽到要横向滚。
    用户点 ✕ 就是不打算看了，替他留着毫无意义。

    **软删**：`status=0`，已填的值一行不动。用户想找回可以再启用（走 `PUT /fields/{key}`），
    误删一列填了几十条数据的字段不至于真丢。硬删会毁掉历史数据，不可逆。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以删除字段")
    with db.begin():
        f = db.execute(
            select(StudentField).where(
                StudentField.class_id == user.class_id,
                StudentField.field_key == field_key,
            )
        ).scalar_one_or_none()
        if f is None:
            raise BizException.bad_request("字段不存在或已删除")
        f.status = 0
        # 值保留不删：字段可能只是暂时不用，删了就真的找不回来了


def restore_field(db: Session, user: LoginUser, field_key: str) -> dict:
    """把停用的字段重新启用。软删保住了值，这里是误删的退路。

    重复启用不报错（幂等）：界面上"恢复"按钮可能被连点两次，
    第二次返回成功比抛个 400 更符合直觉。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    with db.begin():
        f = db.execute(
            select(StudentField).where(
                StudentField.class_id == user.class_id,
                StudentField.field_key == field_key,
            )
        ).scalar_one_or_none()
        if f is None:
            raise BizException.bad_request("字段不存在")
        f.status = 1
        db.flush()
        return {"id": f.id, "key": f.field_key, "label": f.field_label, "status": 1}


# ==================== 记录与字段值 ====================

def match_user_id(db: Session, class_id: int, student_no: str) -> int | None:
    """按学号挂接已有的登录账号（**只挂接，不创建**）。

    手工加行和 Excel 导入都要用。放在 service 而不是 excel 里，
    是因为 `student_excel` 反过来 import 了这个模块——放错地方就是循环依赖。
    """
    u = db.execute(
        select(SysUser.id).where(
            SysUser.class_id == class_id, SysUser.student_no == student_no
        )
    ).scalar_one_or_none()
    return int(u) if u is not None else None


def _field_map(db: Session, class_id: int) -> dict[str, StudentField]:
    rows = db.scalars(
        select(StudentField)
        .where(StudentField.class_id == class_id, StudentField.status == 1)
        .order_by(StudentField.sort.asc(), StudentField.id.asc())
    )
    return {f.field_key: f for f in rows}


def _load_values(db: Session, record_ids: list[int]) -> dict[tuple[int, int], str | None]:
    """一次性取回所有字段值，避免逐行逐字段查询（N+1 × N）。"""
    if not record_ids:
        return {}
    out: dict[tuple[int, int], str | None] = {}
    for rid, fid, val in db.execute(
        select(
            StudentRecordValue.record_id,
            StudentRecordValue.field_id,
            StudentRecordValue.value_text,
        ).where(StudentRecordValue.record_id.in_(record_ids))
    ):
        out[(rid, fid)] = val
    return out


def list_records(db: Session, user: LoginUser, *, keyword: str | None = None) -> dict:
    """学生信息表。**返回的每一行都已经是权限过滤后的结果**——没权限的人根本拿不到别人的学号。"""
    vis = visibility(db, user)
    ids = _visible_record_ids(db, user)
    fields = list(
        db.scalars(
            select(StudentField)
            .where(StudentField.class_id == user.class_id, StudentField.status == 1)
            .order_by(StudentField.sort.asc(), StudentField.id.asc())
        )
    )
    rows: list[StudentRecord] = []
    if ids:
        q = select(StudentRecord).where(StudentRecord.id.in_(ids))
        kw = (keyword or "").strip()
        if kw:
            from ..helpers import like_pattern

            pattern = like_pattern(kw)
            q = q.where(
                StudentRecord.student_no.like(pattern) | StudentRecord.name.like(pattern)
            )
        rows = list(db.scalars(q.order_by(StudentRecord.student_no.asc())))
    values = _load_values(db, [r.id for r in rows])

    # 学号/姓名是锚点，排在最前；其余按字段定义顺序
    cols = [
        {"key": "__no__", "label": "学号", "type": FT_TEXT, "system": True, "writable": vis["canEditAll"]},
        {"key": "__name__", "label": "姓名", "type": FT_TEXT, "system": True, "writable": vis["canEditAll"]},
    ]
    for f in fields:
        cols.append(
            {
                "key": f.field_key,
                "label": f.field_label,
                "type": f.field_type,
                "system": bool(f.is_system),
                "writable": vis["canEditAll"]
                or (vis["canEditOwn"] and vis["myRecordId"] is not None),
            }
        )

    data = []
    for r in rows:
        editable = vis["canEditAll"] or (vis["canEditOwn"] and r.id == vis["myRecordId"])
        data.append(
            {
                "id": r.id,
                "studentNo": r.student_no,
                "name": r.name,
                "isMine": r.id == vis["myRecordId"],
                "editable": bool(editable),
                "linkedUserId": r.user_id,
                "values": {
                    f.field_key: values.get((r.id, f.id)) for f in fields
                },
            }
        )
    return {"columns": cols, "rows": data, "permission": vis}


def create_record(
    db: Session, user: LoginUser, student_no: str, name: str, values: dict[str, str | None] | None = None
) -> dict:
    """手工新增一行（不靠 Excel）。

    只要**学号 + 姓名**就能建行——这两列是锚点，缺了就没法定位"这是谁的行"。
    其余字段留空是常态：老师先把人加进来，细节在表格里逐格填（就像 Excel 里
    新插一行然后往里打字）。所以这里**不要求**其他字段。

    **不创建登录账号**：加一个学生 ≠ 给这个人开登录权限。
    账号仍由班主任在「成员管理」单独建，权限仍走申请/审批。
    """
    _assert_can_manage(db, user)
    no = (student_no or "").strip()
    nm = (name or "").strip()
    if not no:
        raise BizException.bad_request("学号不能为空")
    if not nm:
        raise BizException.bad_request("姓名不能为空")
    if len(no) > 32:
        raise BizException.bad_request("学号不能超过 32 个字符")
    if len(nm) > 32:
        raise BizException.bad_request("姓名不能超过 32 个字符")

    with db.begin():
        fields = _field_map(db, user.class_id)
        unknown = [k for k in (values or {}) if k not in fields]
        if unknown:
            raise BizException.bad_request(
                f"存在未定义的字段：{'、'.join(sorted(unknown)[:5])}（可能是已被删除的字段）"
            )
        dup = db.scalar(
            select(StudentRecord.id).where(
                StudentRecord.class_id == user.class_id, StudentRecord.student_no == no
            )
        )
        if dup is not None:
            # 学号是 upsert 锚点，撞号会让下一次导入把新表里的这一行
            # 覆盖到已经存在的那个人身上。必须在写入前拦住。
            raise BizException.bad_request(f"学号 {no} 已被本班其他学生占用")
        rec = StudentRecord(
            class_id=user.class_id,
            student_no=no,
            name=nm,
            user_id=match_user_id(db, user.class_id, no),
        )
        db.add(rec)
        db.flush()
        # 先全部归一化再写：任一格非法就整批不落库，避免建出一行残缺的记录
        norm: dict[int, str | None] = {}
        for key, raw in (values or {}).items():
            f = fields[key]
            norm[f.id] = normalize_value(f.field_type, raw or "", f.field_label)
        for fid, val in norm.items():
            if val is None:
                continue  # 空格子不建值行，跟"空值不覆盖"一个道理
            db.add(StudentRecordValue(record_id=rec.id, field_id=fid, value_text=val))
        rec.updated_at = datetime.now()
        db.flush()
        return {"id": rec.id, "studentNo": rec.student_no, "name": rec.name}


def _assert_can_manage(db: Session, user: LoginUser) -> None:
    """手工加行的权限：和字段管理一致（班主任 + 班长）。

    生活委员自己给自己开一行登记信息没有意义——他要填的东西，
    要么本来就能改自己那行（走 `update_record`），要么得先申请。
    """
    if user.role not in FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以新增学生")


def update_record(
    db: Session,
    user: LoginUser,
    record_id: int,
    values: dict[str, str | None],
    new_name: str | None = None,
    new_no: str | None = None,
) -> dict:
    """就地编辑一格（第二十三轮 · 表格编辑模式）。

    `values` 是 `{字段标识: 值}`，**只接受已定义的字段**，未知 key 直接报错而不是静默丢弃。
    `new_name` / `new_no` 对应「姓名」「学号」两格——它们是锚点列，不是普通字段。

    **整批原子**：任一格非法就整批不落库。表格模式下用户常一次改多格，
    写一半会让界面显示的和库里不一致。

    注意读操作一律写在 `db.begin()` **里面**：SQLAlchemy 里一旦执行了 SELECT，
    Session 就已经开了一个隐式事务，此时再 `db.begin()` 会抛
    `InvalidRequestError: A transaction is already begun`（表现为 HTTP 500）。
    """
    with db.begin():
        fields = _field_map(db, user.class_id)
        unknown = [k for k in values if k not in fields]
        if unknown:
            raise BizException.bad_request(
                f"存在未定义的字段：{'、'.join(sorted(unknown)[:5])}（可能是已被删除的字段）"
            )
        rec = db.get(StudentRecord, record_id)
        if rec is None or rec.class_id != user.class_id:
            raise BizException.bad_request("学生记录不存在")
        _assert_can_edit(db, user, rec)
        if new_name is not None:
            name = new_name.strip()
            if not name:
                raise BizException.bad_request("姓名不能为空")
            if len(name) > 32:
                raise BizException.bad_request("姓名不能超过 32 个字符")
            rec.name = name
        if new_no is not None:
            no = new_no.strip()
            if not no:
                raise BizException.bad_request("学号不能为空")
            if len(no) > 32:
                raise BizException.bad_request("学号不能超过 32 个字符")
            if no != rec.student_no:
                # 学号是 Excel 导入的 upsert 键，班内撞号会让**下一次导入**把这一行
                # 当成新学生插进去（或者反过来把别人那一行覆盖掉）。必须在写入前拦住。
                dup = db.scalar(
                    select(StudentRecord.id).where(
                        StudentRecord.class_id == user.class_id,
                        StudentRecord.student_no == no,
                    )
                )
                if dup is not None:
                    raise BizException.bad_request(f"学号 {no} 已被本班其他学生占用")
                rec.student_no = no
        # 先全部归一化再写：任一格非法就整批不落库，避免写一半
        norm: dict[int, str | None] = {}
        for key, raw in values.items():
            f = fields[key]
            norm[f.id] = normalize_value(f.field_type, raw or "", f.field_label)
        for fid, val in norm.items():
            existing = db.execute(
                select(StudentRecordValue).where(
                    StudentRecordValue.record_id == record_id,
                    StudentRecordValue.field_id == fid,
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    StudentRecordValue(record_id=record_id, field_id=fid, value_text=val)
                )
            else:
                existing.value_text = val
        rec.updated_at = datetime.now()
        db.flush()
    return {"ok": True}


# ==================== 申请与审批 ====================

def _require_approver(user: LoginUser) -> None:
    if user.role not in APPROVER_ROLES:
        raise BizException.forbidden("只有班主任可以审批学生信息访问申请")


def _user_name(db: Session, user_id: int) -> str:
    u = db.get(SysUser, user_id)
    return u.real_name if u is not None else f"id={user_id}"


def create_request(db: Session, user: LoginUser, scope: str, reason: str | None) -> dict:
    """提交申请。班主任自己不需要申请；已持有该权限的不重复申请。

    **所有读写都在同一个 `db.begin()` 里**：SQLAlchemy 一旦执行 SELECT 就开了隐式事务，
    此后再 `db.begin()` 会抛 `InvalidRequestError` → HTTP 500。
    这个坑本轮踩了三次（update_record / create_request / import），故在此留痕。
    """
    if scope not in SCOPES:
        raise BizException.bad_request("申请类型不合法")
    if user.role in APPROVER_ROLES:
        raise BizException.bad_request("班主任本来就拥有全部权限，无需申请")
    if user.role == GUEST_ROLE:
        # 访客是**角色内建**的只读权限，不走 `student_grant`。
        # 放他进申请流程会出现很怪的状态：他申请到 EDIT_ALL，班主任批了，
        # `granted_scopes` 里有了这条授权——可 `visibility` 对 GUEST 直接返回
        # 内建的 `GUEST_SCOPES`、根本不查这张表，授权批了个寂寞。
        # 所以这里直接拒绝，别让班主任做一次没有效果的审批。
        raise BizException.forbidden("访客是只读账号，不能申请编辑权限")
    with db.begin():
        if scope in granted_scopes(db, user.class_id, user.id):
            raise BizException.bad_request("你已拥有该权限，无需重复申请")
        pending = db.execute(
            select(StudentAccessRequest.id).where(
                StudentAccessRequest.class_id == user.class_id,
                StudentAccessRequest.user_id == user.id,
                StudentAccessRequest.scope == scope,
                StudentAccessRequest.status == "PENDING",
            )
        ).scalar_one_or_none()
        if pending is not None:
            raise BizException.bad_request("该申请已在等待审批，请勿重复提交")
        row = StudentAccessRequest(
            class_id=user.class_id,
            user_id=user.id,
            scope=scope,
            reason=(reason or "").strip() or None,
            status="PENDING",
        )
        db.add(row)
        db.flush()
        return {
            "id": row.id,
            "scope": scope,
            "scopeText": SCOPE_TEXT[scope],
            "status": row.status,
            "createdAt": fmt(row.created_at),
        }


def my_requests(db: Session, user: LoginUser) -> list[dict]:
    rows = list(
        db.scalars(
            select(StudentAccessRequest)
            .where(
                StudentAccessRequest.class_id == user.class_id,
                StudentAccessRequest.user_id == user.id,
            )
            .order_by(StudentAccessRequest.id.desc())
            .limit(50)
        )
    )
    return [
        {
            "id": r.id,
            "scope": r.scope,
            "scopeText": SCOPE_TEXT.get(r.scope, r.scope),
            "status": r.status,
            "reason": r.reason,
            "reply": r.reply,
            "createdAt": fmt(r.created_at),
            "handledAt": fmt(r.handled_at),
        }
        for r in rows
    ]


def pending_requests(db: Session, user: LoginUser) -> list[dict]:
    """班主任的审批收件箱。"""
    _require_approver(user)
    rows = list(
        db.scalars(
            select(StudentAccessRequest)
            .where(
                StudentAccessRequest.class_id == user.class_id,
                StudentAccessRequest.status == "PENDING",
            )
            .order_by(StudentAccessRequest.created_at.asc(), StudentAccessRequest.id.asc())
        )
    )
    out = []
    for r in rows:
        out.append(
            {
                "id": r.id,
                "userId": r.user_id,
                "userName": _user_name(db, r.user_id),
                "role": _role_of(db, r.user_id),
                "scope": r.scope,
                "scopeText": SCOPE_TEXT.get(r.scope, r.scope),
                "reason": r.reason,
                "createdAt": fmt(r.created_at),
            }
        )
    return out


def _role_of(db: Session, user_id: int) -> str:
    u = db.get(SysUser, user_id)
    return u.role if u is not None else ""


def handle_request(
    db: Session, user: LoginUser, request_id: int, approve: bool, reply: str | None
) -> dict:
    """审批。同意 → 写 `student_grant`（当前状态）；不同��� → 只留申请流水。"""
    _require_approver(user)
    with db.begin():
        row = db.get(StudentAccessRequest, request_id)
        if row is None or row.class_id != user.class_id:
            raise BizException.bad_request("申请不存在")
        if row.status != "PENDING":
            raise BizException.bad_request("该申请已处理过，请刷新后重试")
        row.status = "APPROVED" if approve else "REJECTED"
        row.handled_by = user.id
        row.handled_at = datetime.now()
        row.reply = (reply or "").strip() or None
        if approve:
            existing = db.execute(
                select(StudentGrant.id).where(
                    StudentGrant.class_id == row.class_id,
                    StudentGrant.user_id == row.user_id,
                    StudentGrant.scope == row.scope,
                )
            ).scalar_one_or_none()
            if existing is None:
                db.add(
                    StudentGrant(
                        class_id=row.class_id,
                        user_id=row.user_id,
                        scope=row.scope,
                        granted_by=user.id,
                    )
                )
        db.flush()
        return {"ok": True, "status": row.status}


def revoke_grant(db: Session, user: LoginUser, target_user_id: int, scope: str) -> None:
    """撤销授权（班主任主动收回）。"""
    _require_approver(user)
    if scope not in SCOPES:
        raise BizException.bad_request("权限类型不合法")
    with db.begin():
        g = db.execute(
            select(StudentGrant).where(
                StudentGrant.class_id == user.class_id,
                StudentGrant.user_id == target_user_id,
                StudentGrant.scope == scope,
            )
        ).scalar_one_or_none()
        if g is None:
            raise BizException.bad_request("该用户并未持有此权限")
        db.delete(g)


def list_grants(db: Session, user: LoginUser) -> list[dict]:
    _require_approver(user)
    rows = list(
        db.scalars(
            select(StudentGrant)
            .where(StudentGrant.class_id == user.class_id)
            .order_by(StudentGrant.granted_at.desc())
        )
    )
    return [
        {
            "id": g.id,
            "userId": g.user_id,
            "userName": _user_name(db, g.user_id),
            "role": _role_of(db, g.user_id),
            "scope": g.scope,
            "scopeText": SCOPE_TEXT.get(g.scope, g.scope),
            "grantedByName": _user_name(db, g.granted_by),
            "grantedAt": fmt(g.granted_at),
        }
        for g in rows
    ]


def pending_count(db: Session, user: LoginUser) -> int:
    """待审批数量（给顶栏红点用）。"""
    if user.role not in APPROVER_ROLES:
        return 0
    return int(
        db.scalar(
            select(func.count(StudentAccessRequest.id)).where(
                StudentAccessRequest.class_id == user.class_id,
                StudentAccessRequest.status == "PENDING",
            )
        )
        or 0
    )


def fmt(dt: datetime | None) -> str | None:
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt is not None else None