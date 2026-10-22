"""学院视角的聚合（第三十轮）。

## 「学院」在库里**不是一层**

数据模型是 `class → 学生/账号/任务/字段`，**没有 college 表**。
学院 = **全部班级**的聚合视图，**只有院长（DEAN）能进**。

为什么不给班级挂一个上级实体：那要改 `schema.sql`、`seed.py`，还得给
所有按 `class_id` 过滤的查询补一层「学院」维度——而全库只有 2 个班级、
1 个在用，造一层出来背后没有对应的现实需求。院长的身份本身就是「校级」，
**学院视角就是他的权限范围**，这比再引入一个实体更贴合现有的等级模型。

## 三张表

- **学生信息**：跨班级的学生名册。列是**所有班级字段的并集**（按 `field_key`
  去重）——同一套模板在不同班各有一份 `student_field` 定义，列必须合成一份。
- **成员管理**：各班**班主任（导员）名册**。一班一行，不是全院账号列表。
- **任务**：跨班级的任务一览，答题分母**按任务自己的班级**算。

## 全部只读

学院这一层是**看**的：名册、目录、一览。改人改任务仍然在班级层做——
不然同一份数据会有两个可写入口，必然出现「两边不一致」。
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..helpers import like_pattern
from ..models import (
    ClsClass,
    ClsTask,
    ClsTaskAnswer,
    StudentField,
    StudentRecord,
    StudentRecordValue,
    SysUser,
    SysUserClass,
)
from ..security import DEAN_ROLE, LoginUser
from ..serializers import fmt_dt
from . import student_service as svc
from .task_service import is_answer_target, is_open

#: 班主任角色。这个名册只列他们（以及兼班主任的院长）。
TEACHER_ROLE = "TEACHER"

#: 一页最多给多少行。上限不是摆设：不给上限的话，一个「学院」里
#: 几千个学生会把整张表塞进浏览器首屏。
MAX_PAGE_SIZE = 200

DEFAULT_PAGE_SIZE = 50


# ==================== 公共：班级清单 ====================


def _active_classes(db: Session) -> list[ClsClass]:
    """全部**启用**的班级，按 id 排。

    停用的班级不进学院视图——它是历史，不是现状。
    """
    return list(
        db.scalars(
            select(ClsClass)
            .where(ClsClass.status == 1)
            .order_by(ClsClass.id.asc())
        )
    )


def _class_choices(db: Session, classes: list[ClsClass]) -> list[dict]:
    """班级下拉的选项。

    ## 为什么带人数

    一个班**一个人都没有**是很常见的状态（名单还没导进去）。
    这种班出现在筛选下拉里，选下去必然是 0 人——用户会以为「筛选坏了」。

    带上人数（`0 人`）就一目了然了：**能干的活儿摆在那儿，干不了的不藏着**。
    顺带也让「筛出来 0 人」和「这个班本来就是空的」区分得开。
    """
    counts: dict[int, int] = {}
    if classes:
        for cid, n in db.execute(
            select(StudentRecord.class_id, func.count())
            .where(StudentRecord.class_id.in_([c.id for c in classes]))
            .group_by(StudentRecord.class_id)
        ):
            counts[int(cid)] = int(n)
    return [
        {
            "id": c.id,
            "className": c.class_name,
            "grade": c.grade or "",
            "students": counts.get(c.id, 0),
        }
        for c in classes
    ]


def _grade_choices(classes: list[ClsClass]) -> list[str]:
    """年级去重列表，按班级顺序出现（不排序——「2026级、2025级、2022级」
    这种「由近到远」的顺序比字典序更符合看的人的习惯，但库里的年级
    本来就没有保证顺序，所以这里只做**去重**，不假装能排好序。"""
    out: list[str] = []
    for c in classes:
        g = (c.grade or "").strip()
        if g and g not in out:
            out.append(g)
    return out


# ==================== 学生信息（跨班级） ====================


def _unified_columns(db: Session, class_ids: list[int]) -> list[dict]:
    """把各班的字段定义合成**一份**列定义。

    同一个 `field_key` 在每个班各有一行 `student_field`（唯一键是
    `(class_id, field_key)`）。学院视图要跨班展示，列就只能有一份——
    否则「性别」会出现两次，且两列的值来自不同的 `field_id`，对不上。

    ## 合并顺序 = **按班序逐个取首次出现**

    之前是「把所有班的字段行摊平，按 `(sort, id)` 排，取首次出现」。
    那样在**各班字段集不同**时顺序会交错：一个新建的班只有 3 个字段、
    排序从 10 开始，它的某个字段就会插到别的班的两个字段中间——
    表现是「明明把新列插在 A 前面，它却隔了一列」。

    改成「按 class_id 升序，一个班一个班地看，每个班里按 `(sort, id)` 排，
    某个 key 第一次出现就定下位置」：列序以**第一个班**的字段顺序为主，
    后面各班多出来的字段追加在后面。稳定、可预期。
    """
    if not class_ids:
        return []
    out: dict[str, dict] = {}
    for cid in sorted(class_ids):
        rows = db.scalars(
            select(StudentField)
            .where(StudentField.class_id == cid, StudentField.status == 1)
            .order_by(StudentField.sort.asc(), StudentField.id.asc())
        ).all()
        for f in rows:
            if f.field_key in out:
                continue
            out[f.field_key] = {
                "key": f.field_key,
                "label": f.field_label,
                "type": f.field_type,
                "system": bool(f.is_system),
            }
    return list(out.values())


def _field_ids_by_key(
    db: Session, class_ids: list[int]
) -> dict[tuple[int, str], int]:
    """(class_id, field_key) → field_id。

    学院视图的值必须**按 field_key 解析**而不是按 field_id——各班的
    `field_id` 是各自的自增 id，拿全局的 field_id 去查别的班的值，
    会取到完全不相干的字段（值表里存的正是 field_id，不是 key）。
    """
    if not class_ids:
        return {}
    rows = db.execute(
        select(StudentField.class_id, StudentField.field_key, StudentField.id).where(
            StudentField.class_id.in_(class_ids), StudentField.status == 1
        )
    ).all()
    return {(cid, key): fid for cid, key, fid in rows}


def _populated_keys(db: Session, base) -> set[str]:
    """筛选结果里**至少有一行有值**的字段 key 集合。

    按 `field_id` 关联回 `student_field` 取 `field_key`——字段定义是**按班**
    存的，但值的 `field_id` 指向的就是本班那一条，关联出来不会串。

    ⚠ **必须只取启用字段**（`status == 1`）。已停用的字段历史上有值，
    但它已经不在列定义里了；混进来会让 `populatedKeys` 出现
    `columns` 里根本没有的 key，前端按 `columns` 过滤时看着没事，
    但「有值的列是列定义的子集」这条不变式就破了。
    """
    if base is None:
        return set()
    sub = base.with_only_columns(StudentRecord.id).subquery()
    rows = db.execute(
        select(StudentField.field_key)
        .join(StudentRecordValue, StudentRecordValue.field_id == StudentField.id)
        .where(StudentRecordValue.record_id.in_(select(sub.c.id)))
        .where(StudentField.status == 1)
        .where(func.trim(func.coalesce(StudentRecordValue.value_text, "")) != "")
        .distinct()
    ).all()
    return {r[0] for r in rows}


def students(
    db: Session,
    user: LoginUser,
    *,
    keyword: str | None = None,
    class_id: int | None = None,
    grade: str | None = None,
    page: int = 1,
    size: int = DEFAULT_PAGE_SIZE,
) -> dict:
    """学院学生名册：跨班级的学生 + 搜索筛选。

    ## 搜索范围

    关键字命中**学号、姓名，以及任意 TEXT 类型字段的值**（专业、宿舍号…
    这些才是「按关键字找人」时真正会用的）。DATE/NUMBER/BOOL 不参与——
    用户搜「2024」时命中一个日期字段的多半不是本意。

    ## 为什么用 EXISTS 而不是把值全捞出来在 Python 里过滤

    学院可能有几千个学生、每人 30+ 个字段，全捞进内存再过滤是几万个
    Python 对象的开销；而带条件的 EXISTS 让数据库自己筛，命中的是 id。
    """
    classes = _active_classes(db)
    # 先按**班级**收窄。年级不能在这里筛——学生的年级是他自己填的
    # grade 字段值（见 `_row_grade`），跟班级年级可能不一样，
    # 按班级年级筛会把「同班不同年级」的学生整批漏掉。
    # 所以年级筛选放到**行级**做（见下面 `base` 的附加条件）。
    target = [c for c in classes if class_id is None or c.id == class_id]
    class_ids = [c.id for c in target]

    page = max(1, int(page or 1))
    size = max(1, min(int(size or DEFAULT_PAGE_SIZE), MAX_PAGE_SIZE))

    base = select(StudentRecord).where(StudentRecord.class_id.in_(class_ids)) if class_ids else None
    if base is None:
        return {
            "columns": [],
            "populatedKeys": [],
            "rows": [],
            "total": 0,
            "page": page,
            "size": size,
            "classes": _class_choices(db, classes),
            "grades": [],
        }

    kw = (keyword or "").strip()
    if kw:
        pat = like_pattern(kw)
        text_hit = (
            select(StudentRecordValue.record_id)
            .join(StudentField, StudentField.id == StudentRecordValue.field_id)
            .where(
                StudentRecordValue.record_id == StudentRecord.id,
                StudentField.field_type == "TEXT",
                StudentRecordValue.value_text.like(pat),
            )
            .exists()
        )
        base = base.where(
            or_(
                StudentRecord.student_no.like(pat),
                StudentRecord.name.like(pat),
                text_hit,
            )
        )

    # 年级筛选：**行级**判定。
    #
    # 学生的年级 = 他自己填的 grade 字段值；没填才用班级年级。
    # 所以判据是「字段值等于选中值 **或**（没填字段值 且 班级年级等于选中值）」。
    #
    # ⚠ 必须在算 total **之前**加进去，否则 total 算的是没筛过的总数，
    # 分页和「共 N 名学生」都会对不上。
    field_ids_all = _field_ids_by_key(db, class_ids)
    class_by_id_all = {c.id: c for c in classes}
    if grade is not None:
        grade = (grade or "").strip()
        matched_ids = _rows_of_grade(
            db, class_ids, field_ids_all, class_by_id_all, grade
        )
        if not matched_ids:
            base = base.where(StudentRecord.id < 0)  # 选中的年级一个人都没有
        else:
            base = base.where(StudentRecord.id.in_(matched_ids))

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    # 哪些字段在整个筛选结果里**真有值**。
    #
    # 模板有 34 个字段，而一个学院里多数字段在大多数行上是空的。
    # 全列都摆出来 = 一屏 34 列空格子，真正要看的那两列要找半天。
    # 所以只显示有值的列。
    #
    # ⚠ 必须按**整个筛选结果**算，不能按当前页——按当前页算的话，
    # 翻到下一页时列会忽然增减，表格宽度在翻页时跳来跳去。
    populated = _populated_keys(db, base)

    records = list(
        db.scalars(
            base.order_by(StudentRecord.class_id.asc(), StudentRecord.student_no.asc())
            .offset((page - 1) * size)
            .limit(size)
        )
    )

    columns = _unified_columns(db, class_ids)
    field_ids = _field_ids_by_key(db, class_ids)
    class_by_id = {c.id: c for c in classes}

    values: dict[tuple[int, int], str | None] = {}
    if records:
        for rid, fid, val in db.execute(
            select(
                StudentRecordValue.record_id,
                StudentRecordValue.field_id,
                StudentRecordValue.value_text,
            ).where(StudentRecordValue.record_id.in_([r.id for r in records]))
        ):
            values[(rid, fid)] = val

    rows = []
    for r in records:
        cid = r.class_id
        cls = class_by_id.get(cid)
        row_values: dict[str, str | None] = {}
        for col in columns:
            fid = field_ids.get((cid, col["key"]))
            row_values[col["key"]] = values.get((r.id, fid)) if fid else None
        rows.append(
            {
                "id": r.id,
                "classId": cid,
                "className": cls.class_name if cls else "",
                # 学生的年级 = **他自己填的** grade 字段值；没填才回退班级年级。
                #
                # 为什么不用班级年级：导进来的名单里通常带「年级」列，
                # 而同一个班里可能混着不同年级的学生（转专业/降级）。
                # 用班级年级筛就永远只有一个值，筛不出东西来。
                "grade": _row_grade(row_values, cls),
                "studentNo": r.student_no,
                "name": r.name,
                "values": row_values,
            }
        )

    # 年级筛选的**选项域**：跟着数据走。
    #
    # 之前是「所有班级的年级」——那是死数据：导入一份带新年级���名单，
    # 筛选里不会出现那个年级。改成「学生实际的年级」去重，
    # 导入完立刻就能在筛选里看到、并且选它能筛出对应的学生。
    grade_scope = _grade_domain(db, class_ids, field_ids, class_by_id)

    return {
        "columns": columns,
        "populatedKeys": sorted(populated),
        "rows": rows,
        "total": int(total or 0),
        "page": page,
        "size": size,
        "classes": _class_choices(db, classes),
        "grades": grade_scope,
    }


#: 学生「年级」字段的机器名
GRADE_FIELD_KEY = "grade"


def _row_grade(row_values: dict[str, str | None], cls: ClsClass | None) -> str:
    """学生的年级：自己填的 grade 字段值优先，没有才用班级年级。"""
    v = (row_values.get(GRADE_FIELD_KEY) or "").strip()
    if v:
        return v
    return (cls.grade if cls else "") or ""


def _effective_grades(
    db: Session,
    class_ids: list[int],
    field_ids: dict[tuple[int, str], int],
    class_by_id: dict[int, ClsClass],
) -> dict[int, str]:
    """每个学生的**有效年级**：`{记录 id: 年级}`。

    有效年级 = 学生自己填的 `grade` 字段值；**没填**才回退到**班级**的年级。

    ## 为什么要有这个回退

    名单里通常带「年级」列，但**很多班的学生没填**（导入时空格子不写值）。
    回退到班级年级，那些学生才筛得出来——否则「按 2026 级找这班人」
    会一个都找不到。

    ## 筛选和选项域必须用**同一份**判据

    选项域以前是「班级年级 ∪ 学生填过的年级」，那会造出**筛不出人**的死选项：
    一个班的学生都自己填了「2026」，这个班的「2026级」照样出现在下拉里，
    可选下去一个人都筛不出来（学生自己有值，就不再看班级年级了）。
    用户看到的就是「这个筛选不了」——选项在那儿，点了没反应。
    """
    out: dict[int, str] = {}
    for cid in class_ids:
        cls = class_by_id.get(cid)
        class_grade = (cls.grade if cls else "") or ""
        fid = field_ids.get((cid, GRADE_FIELD_KEY))
        # 学生 id → 他自己填的年级
        grade_of: dict[int, str] = {}
        if fid:
            for rid, val in db.execute(
                select(StudentRecordValue.record_id, StudentRecordValue.value_text).where(
                    StudentRecordValue.field_id == fid
                )
            ):
                grade_of[int(rid)] = (val or "").strip()
        for (rid,) in db.execute(
            select(StudentRecord.id).where(StudentRecord.class_id == cid)
        ):
            rid = int(rid)
            v = grade_of.get(rid, "")
            out[rid] = v if v else class_grade
    return out


def _rows_of_grade(
    db: Session,
    class_ids: list[int],
    field_ids: dict[tuple[int, str], int],
    class_by_id: dict[int, ClsClass],
    grade: str,
) -> list[int]:
    """哪些学生属于这个年级。

    判据和选项域**完全一致**（见 `_effective_grades`）：
    学生的有效年级 = 他自己填的 grade 字段值，没填才用班级年级。
    """
    effective = _effective_grades(db, class_ids, field_ids, class_by_id)
    return [rid for rid, g in effective.items() if g == grade]


def _grade_domain(
    db: Session,
    class_ids: list[int],
    field_ids: dict[tuple[int, str], int],
    class_by_id: dict[int, ClsClass],
) -> list[str]:
    """年级筛选的选项域 = 这些班里的**学生的有效年级**去重。

    ⚠ **只收「真能筛出人」的年级**：选项域必须和筛选判据同源
    （见 `_effective_grades`）。收进来的每一个选项，选下去都至少能筛出一个人。
    """
    effective = _effective_grades(db, class_ids, field_ids, class_by_id)
    out = sorted({g for g in effective.values() if g})
    return out


# ==================== 就地编辑（电子表格用） ====================


def _ensure_grade_field(db: Session, class_id: int, user: LoginUser) -> StudentField:
    """在指定班里补一个「年级」字段（key=`grade`）。

    ## 为什么需要它

    学院表里「年级」是**固定的一列**（每一行都有这一格），但它底下是
    **按班定义的 grade 字段**——有的班没建这一列（那份名单里没有年级列）。
    用户在这格填了年级却存不进去（报「未定义的字段」）是最糟的体验，
    所以**缺了就建**：key / 名称 / 类型 / 位置都照抄别的班已有的那一份，
    这样学院视图里这一列的位置和别处一致。

    照抄不到（全校都没这一列）就按「追加到末尾」建。
    """
    ref = db.scalars(
        select(StudentField)
        .where(StudentField.field_key == GRADE_FIELD_KEY, StudentField.status == 1)
        .order_by(StudentField.class_id.asc(), StudentField.sort.asc())
        .limit(1)
    ).first()
    f = StudentField(
        class_id=class_id,
        field_key=GRADE_FIELD_KEY,
        field_label=ref.field_label if ref else "年级",
        field_type=ref.field_type if ref else "TEXT",
        is_system=0,
        sort=ref.sort if ref else 9999,
        status=1,
        created_by=user.id,
    )
    db.add(f)
    db.flush()
    return f


def update_student_cells(
    db: Session,
    user: LoginUser,
    record_id: int,
    values: dict[str, str | None],
    new_name: str | None = None,
    new_no: str | None = None,
    class_name: str | None = None,
) -> dict:
    """改一个学生的若干格（学院视角，**跨班级**）。

    `values` 是 `{字段标识: 值}`，**只接受该学生所在那个班里已定义的字段**。

    ## 学号 / 姓名 / 班级

    这三列不在字段表里（在 `student_record` / `cls_class` 上），所以走
    `new_no` / `new_name` / `class_name`。

    - **学号**：不能空、长度上限、**同班学号不能重复**（学号是 Excel 导入的
      upsert 键，撞号会让下一次导入把这一行覆盖掉）。
    - **姓名**：不能空、长度上限。
    - **班级**：**按名字**改——界面上这一格就是个普通输入框，用户直接打字。
      找到同名班就转过去；**找不到就自动建一个班**（和导入时一个规矩：
      名单里出现的新班级名不该被丢掉）。

    转班不是「改一格」那么简单：值表里存的是 `field_id`，而字段是**按班**
    定义的——把人挪到另一个班，他那些值要**按 key 搬到新班对应的字段上**
    （见 `_move_student_to_class`）。

    ## 为什么按「所在班」取字段

    字段定义是**按班**存的（`student_field.class_id`），值表里存的是 `field_id`。
    学院视图按 `field_key` 把各班的列合并成一份，所以一个 key 在不同班
    对应**不同的 field_id**。按 key 找字段必须先定下是哪个班——就是
    这条记录自己的班。找错了班，写进去的值会落到别的列上。

    ## 整批原子

    任一格非法就整批不落库：表格里用户常一次改多格（或粘贴一批），
    写一半会让界面显示的和库里不一致。

    ## 读操作一律写在 `db.begin()` 里面

    SQLAlchemy 里一旦执行了 SELECT，Session 就已经开了隐式事务，
    此时再 `db.begin()` 会抛 `InvalidRequestError`（表现为 HTTP 500）。
    """
    if not values and new_name is None and new_no is None and class_name is None:
        raise BizException.bad_request("没有需要修改的内容")
    with db.begin():
        rec = db.get(StudentRecord, record_id)
        if rec is None:
            raise BizException.bad_request("学生记录不存在")
        fields = svc._field_map(db, rec.class_id)
        # 「年级」在这个班还没定义时，**就地补建**（见 `_ensure_grade_field`）
        if GRADE_FIELD_KEY in values and GRADE_FIELD_KEY not in fields:
            fields[GRADE_FIELD_KEY] = _ensure_grade_field(db, rec.class_id, user)
        unknown = [k for k in values if k not in fields]
        if unknown:
            raise BizException.bad_request(
                f"存在未定义的字段：{'、'.join(sorted(unknown)[:5])}（可能是已停用的列）"
            )
        # 先全部归一化再写：任一格非法就整批不落库
        norm: dict[int, str | None] = {}
        for key, raw in values.items():
            f = fields[key]
            try:
                norm[f.id] = svc.normalize_value(f.field_type, raw or "", f.field_label)
            except BizException as e:
                raise BizException.bad_request(f"「{f.field_label}」{e.message}") from e
        # 学号 / 姓名：先校验，最后才写
        new_no_clean: str | None = None
        if new_no is not None:
            no = new_no.strip()
            if not no:
                raise BizException.bad_request("学号不能为空")
            if len(no) > 32:
                raise BizException.bad_request("学号不能超过 32 个字符")
            if no != rec.student_no:
                dup = db.scalar(
                    select(StudentRecord.id).where(
                        StudentRecord.class_id == rec.class_id,
                        StudentRecord.student_no == no,
                    )
                )
                if dup is not None:
                    raise BizException.bad_request(f"学号 {no} 已被本班其他学生占用")
            new_no_clean = no
        new_name_clean: str | None = None
        if new_name is not None:
            name = new_name.strip()
            if not name:
                raise BizException.bad_request("姓名不能为空")
            if len(name) > 32:
                raise BizException.bad_request("姓名不能超过 32 个字符")
            new_name_clean = name

        for fid, val in norm.items():
            cur = db.execute(
                select(StudentRecordValue).where(
                    StudentRecordValue.record_id == rec.id,
                    StudentRecordValue.field_id == fid,
                )
            ).scalar_one_or_none()
            if cur is None:
                db.add(StudentRecordValue(record_id=rec.id, field_id=fid, value_text=val))
            else:
                cur.value_text = val
        if new_no_clean is not None:
            rec.student_no = new_no_clean
        if new_name_clean is not None:
            rec.name = new_name_clean

        # 班级：**按名字**改。找到就转过去，找不到就**自动建一个班**
        # （和导入时一个规矩：名单里出现的新班级名不该被丢掉）。
        moved: dict | None = None
        if class_name is not None:
            want = class_name.strip()
            if not want:
                raise BizException.bad_request("班级不能为空")
            if len(want) > 64:
                raise BizException.bad_request("班级名不能超过 64 个字符")
            target = next(
                (c for c in _active_classes(db) if c.class_name == want), None
            )
            if target is None:
                # 库里没有这个班 → 建一个（年级留空：不知道就别编）
                target = ClsClass(
                    class_name=want,
                    grade="",
                    head_teacher=None,
                    balance=Decimal("0.00"),
                    status=1,
                )
                db.add(target)
                db.flush()
            if target.id != rec.class_id:
                moved = _move_student_to_class(db, user, rec, target)
        db.flush()
    return {
        "id": rec.id,
        "updated": len(norm),
        "name": rec.name,
        "studentNo": rec.student_no,
        "className": moved["targetClassName"] if moved else None,
        "moved": moved,
    }


#: 转班时要跟着搬的账号角色。
#:
#: 只有**学生账号**跟着走——他换班了，登录后该看到新班。
#: 老师/班委/院长的账号是「岗位」不是「人」，不该因为一条学生记录被挪走。
TRANSFER_USER_ROLES = frozenset({"MEMBER", "GUEST"})


def transfer_student(
    db: Session, user: LoginUser, record_id: int, target_class_id: int
) -> dict:
    """把一个学生**转到另一个班**（跨班级）。

    ## 为什么不能当成「改一格」

    值表里存的是 `field_id`，而字段是**按班**定义的：同一个 `field_key`
    在不同班是不同的 `field_id`（唯一键是 `(class_id, field_key)`）。
    直接把 `class_id` 一改，他那些值就指向了「在新班根本不存在」的字段——
    界面上会变成一片空白（值还在库里，但读不出来）。

    所以转班必须**按 key 把值搬到新班对应的字段上**。

    ## 目标班缺某一列怎么办

    两个班的字段模板通常一样（key 相同），值能完整搬过去。
    目标班**缺**某一列时：**在目标班补建同 key 的字段**再把值搬过去——
    丢值比多一列糟糕得多（多出来的那列只有这个班有，别的班看不到，
    但那一列里的信息是真的）。

    ## 登录账号

    学生账号（MEMBER/GUEST）**跟着转**：人换班了，登录后该看到新班。
    老师账号不动（那是岗位，不是人）。
    """
    with db.begin():
        rec = db.get(StudentRecord, record_id)
        if rec is None:
            raise BizException.bad_request("学生记录不存在")
        target = db.get(ClsClass, target_class_id)
        if target is None or target.status != 1:
            raise BizException.bad_request("目标班级不存在或已停用")
        if rec.class_id == target.id:
            raise BizException.bad_request("他已经在那个班了")
        return _move_student_to_class(db, user, rec, target)


def _move_student_to_class(
    db: Session, user: LoginUser, rec: StudentRecord, target: ClsClass
) -> dict:
    """在一个**已有事务**里把学生挪到目标班（搬值的核心逻辑）。

    `transfer_student`（按 id 转）和「按班级名改」都走这里——
    两条路只是「目标班从哪来」不一样，搬值的逻辑必须只有一份。
    """
    old_class = db.get(ClsClass, rec.class_id)

    # 目标班**所有**字段（**不管启用还是停用**）。
    #
    # ⚠ 唯一键是 `(class_id, field_key)`，**停用的那一条照样占着这个键**。
    # 只查启用的字段 → 目标班那条被停用的会被当成「没有」→ 再插一条 →
    # IntegrityError（500）。所以这里按全部状态查，碰到停用的就**放回来**。
    target_fields = {
        f.field_key: f
        for f in db.scalars(
            select(StudentField).where(StudentField.class_id == target.id)
        )
    }
    # 这个学生的值，以及它们各属于哪个字段
    values = list(
        db.scalars(
            select(StudentRecordValue).where(StudentRecordValue.record_id == rec.id)
        )
    )
    field_by_id = {
        f.id: f
        for f in db.scalars(
            select(StudentField).where(
                StudentField.id.in_([v.field_id for v in values] or [0])
            )
        )
    }

    moved = 0
    created = 0
    revived = 0
    for v in values:
        f = field_by_id.get(v.field_id)
        if f is None:
            continue
        tf = target_fields.get(f.field_key)
        if tf is None:
            # 目标班**没有**这一列 → 补建同 key 的字段，值照搬
            tf = StudentField(
                class_id=target.id,
                field_key=f.field_key,
                field_label=f.field_label,
                field_type=f.field_type,
                is_system=f.is_system,
                sort=f.sort,
                status=1,
                created_by=user.id,
            )
            db.add(tf)
            db.flush()
            target_fields[f.field_key] = tf
            created += 1
        elif tf.status != 1:
            # 目标班有这一列但**被停用过** → 放回来（值照搬）
            tf.status = 1
            revived += 1
        # 目标班可能已经有这个格子的值（转来转去撞上了）→ 旧的删掉
        dup = db.scalar(
            select(StudentRecordValue).where(
                StudentRecordValue.record_id == rec.id,
                StudentRecordValue.field_id == tf.id,
            )
        )
        if dup is not None and dup.id != v.id:
            db.delete(dup)
        v.field_id = tf.id
        moved += 1

    rec.class_id = target.id

    # 学号在**新班**里不能撞号（学号是导入的 upsert 键，撞号会让
    # 下一次导入把新班那一行覆盖掉）
    dup_no = db.scalar(
        select(StudentRecord.id).where(
            StudentRecord.class_id == target.id,
            StudentRecord.student_no == rec.student_no,
            StudentRecord.id != rec.id,
        )
    )
    if dup_no is not None:
        raise BizException.bad_request(
            f"{target.class_name} 已经有学号 {rec.student_no} 的学生了，"
            "先改一下学号再转"
        )

    # 学生账号跟着转（老师账号不动）
    user_moved = False
    if rec.user_id:
        u = db.get(SysUser, rec.user_id)
        if u is not None and u.role in TRANSFER_USER_ROLES and u.class_id != target.id:
            u.class_id = target.id
            user_moved = True

    db.flush()
    return {
        "id": rec.id,
        "name": rec.name,
        "studentNo": rec.student_no,
        "fromClassId": old_class.id if old_class else rec.class_id,
        "fromClassName": old_class.class_name if old_class else "",
        "targetClassId": target.id,
        "targetClassName": target.class_name,
        "movedValues": moved,
        "createdFields": created,
        "revivedFields": revived,
        "userMoved": user_moved,
    }


# ==================== 列管理（学院只有一份表） ====================


def _next_field_key(db: Session, class_ids: list[int]) -> str:
    """生成一个**在所有班都没被占用**的 `field_key`。

    学院视图按 `field_key` 合并各班的列（见 `_unified_columns`），所以
    这个 key 必须在每个班里**都相同**——否则合并后是两列同名，
    而值各填各的，用户改一列另一列不动。

    用 `f_时间戳`（和界面上新建自定义字段同一套路）：中文没法直接当 key
    （`_KEY_RE` 要求字母开头），音译不现实。
    """
    base = f"f_{int(datetime.now().timestamp() * 1000)}"
    key = base
    n = 0
    while db.scalar(
        select(StudentField.id).where(
            StudentField.class_id.in_(class_ids), StudentField.field_key == key
        )
    ) is not None:
        n += 1
        key = f"{base}_{n}"
    return key


def _sort_for(
    db: Session, class_id: int, anchor_key: str | None, side: str
) -> float:
    """算出这一列该放哪。

    `side='before'` → 插在 `anchor_key` **前面**；`'after'` → 插在**后面**。
    没有锚点（追加到末尾）→ 取当前最大 sort + 10。

    用**浮点中点**而不是整数重排：重排要给所有后续字段发一次 UPDATE，
    而用户「在 B 前面插一列」不应该牵动十几列的排序。
    """
    max_sort = db.scalar(
        select(func.coalesce(func.max(StudentField.sort), 0)).where(
            StudentField.class_id == class_id
        )
    )
    base = int(max_sort or 0)
    if not anchor_key:
        return base + 10
    anchor = db.scalar(
        select(StudentField.sort).where(
            StudentField.class_id == class_id,
            StudentField.field_key == anchor_key,
            StudentField.status == 1,
        )
    )
    if anchor is None:
        return base + 10
    if side == "after":
        nxt = db.scalar(
            select(func.min(StudentField.sort)).where(
                StudentField.class_id == class_id,
                StudentField.status == 1,
                StudentField.sort > anchor,
            )
        )
        if nxt is not None:
            return (anchor + nxt) / 2
        return anchor + 10
    prev = db.scalar(
        select(func.max(StudentField.sort)).where(
            StudentField.class_id == class_id,
            StudentField.status == 1,
            StudentField.sort < anchor,
        )
    )
    # 插到最前面时没有前一列，取 anchor-5（沿用"往后退一格"的步长）
    return (prev + anchor) / 2 if prev is not None else anchor - 5


def create_college_field(
    db: Session,
    user: LoginUser,
    *,
    label: str,
    ftype: str = "TEXT",
    anchor_key: str | None = None,
    side: str = "before",
) -> dict:
    """新增一列（**所有班各建一份，key 相同**）。

    `anchor_key` + `side` 指定插在哪：锚点列的前面 / 后面。
    不给锚点 = 追加到末尾。

    每一班的插入位置**各算各的**——各班的自定义字段可能不一样，
    同一个锚点在不同班的 sort 本来就可能不同。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以新增字段")
    label = (label or "").strip()
    if not label:
        raise BizException.bad_request("请填写字段名称")
    if len(label) > 64:
        raise BizException.bad_request("字段名称不能超过 64 个字符")
    ftype = (ftype or "TEXT").strip() or "TEXT"
    if ftype not in svc.FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(svc.FIELD_TYPES)}")
    if side not in ("before", "after"):
        raise BizException.bad_request("插入位置只能是 before 或 after")

    # ⚠ **所有 SELECT 都要在事务块内**。
    # SQLAlchemy 里只要执行过一次 SELECT，Session 就开了隐式事务，
    # 后面再 `db.begin()` 会抛 InvalidRequestError（表现为 HTTP 500）。
    # 这个坑项目里踩过好几次（create_field / create_request 的注释都写着），
    # 所以这里把查询全塞进 `with db.begin():`。
    with db.begin():
        classes = _active_classes(db)
        if not classes:
            raise BizException.bad_request("还没有班级，无法新增字段")
        class_ids = [c.id for c in classes]
        key = _next_field_key(db, class_ids)
        # 位置只算**一次**（按第一个班），各班用同一个 sort。
        #
        # 为什么不能各班各算：各班的字段集可能不同，同一个锚点在各班的
        # 「前一列」不同 → 各班算出的 sort 不同 → 学院视图按班序合并时
        # 这一列会**插在别处**（实测：明明插在「专业名称」前面，
        # 合并后却隔了一列）。
        #
        # 位置以**第一个班**为准，因为合并后的列序也是以它为主的
        # （见 `_unified_columns`）。
        sort = _sort_for(db, class_ids[0], anchor_key, side)
        for c in classes:
            db.add(
                StudentField(
                    class_id=c.id,
                    field_key=key,
                    field_label=label,
                    field_type=ftype,
                    is_system=0,
                    sort=sort,
                    status=1,
                    created_by=user.id,
                )
            )
        db.flush()

    return {
        "key": key,
        "label": label,
        "type": ftype,
        "classCount": len(classes),
    }


def update_college_field(
    db: Session, user: LoginUser, field_key: str, *, label: str | None = None,
    ftype: str | None = None,
) -> dict:
    """改一列的显示名 / 类型（**所有班**）。

    `field_key` 本身不可改（改了历史数据就对不上）。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    with db.begin():
        rows = list(
            db.scalars(
                select(StudentField).where(
                    StudentField.class_id.in_([c.id for c in _active_classes(db)]),
                    StudentField.field_key == field_key,
                )
            )
        )
        if not rows:
            raise BizException.bad_request("字段不存在")
        if label is not None:
            label = label.strip()
            if not label:
                raise BizException.bad_request("请填写字段名称")
            if len(label) > 64:
                raise BizException.bad_request("字段名称不能超过 64 个字符")
            for f in rows:
                f.field_label = label
        if ftype is not None:
            ftype = ftype.strip() or "TEXT"
            if ftype not in svc.FIELD_TYPES:
                raise BizException.bad_request(f"字段类型只能是 {'/'.join(svc.FIELD_TYPES)}")
            for f in rows:
                f.field_type = ftype
        db.flush()
        return {
            "key": field_key,
            "label": rows[0].field_label,
            "type": rows[0].field_type,
            "classCount": len(rows),
        }


def delete_college_field(db: Session, user: LoginUser, field_key: str) -> dict:
    """停用一列（**所有班**）。软删：已填的值一行不动。

    软删而不是硬删：字段可能只是暂时不用，删了就真的找不回来了。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以删除字段")
    with db.begin():
        rows = list(
            db.scalars(
                select(StudentField).where(
                    StudentField.class_id.in_([c.id for c in _active_classes(db)]),
                    StudentField.field_key == field_key,
                )
            )
        )
        if not rows:
            raise BizException.bad_request("字段不存在")
        for f in rows:
            f.status = 0
        db.flush()
        return {"key": field_key, "classCount": len(rows)}


def disabled_college_fields(db: Session) -> list[dict]:
    """已停用的列（按 `field_key` 合并成一份）。

    和 `_unified_columns` 一样，同一个 key 在各班各有一行定义，
    这里也要合并——否则界面上会出现 34 个同名「已停用字段」。
    """
    out: dict[str, dict] = {}
    for cid in sorted(c.id for c in _active_classes(db)):
        rows = db.scalars(
            select(StudentField)
            .where(StudentField.class_id == cid, StudentField.status == 0)
            .order_by(StudentField.sort.asc(), StudentField.id.asc())
        ).all()
        for f in rows:
            if f.field_key in out:
                out[f.field_key]["classCount"] += 1
                continue
            out[f.field_key] = {
                "key": f.field_key,
                "label": f.field_label,
                "type": f.field_type,
                "system": bool(f.is_system),
                "classCount": 1,
            }
    return list(out.values())


def restore_college_field(db: Session, user: LoginUser, field_key: str) -> dict:
    """恢复一个被停用的列（**所有班**一起放回来）。

    值本来就还在（停用是软删），这里只把 `status` 改回 1。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以恢复字段")
    with db.begin():
        rows = list(
            db.scalars(
                select(StudentField).where(
                    StudentField.class_id.in_([c.id for c in _active_classes(db)]),
                    StudentField.field_key == field_key,
                )
            )
        )
        if not rows:
            raise BizException.bad_request("字段不存在")
        restored = 0
        for f in rows:
            if f.status != 1:
                f.status = 1
                restored += 1
        db.flush()
        return {
            "key": field_key,
            "classCount": len(rows),
            "restored": restored,
            "label": rows[0].field_label,
        }


def _fields_by_key(db: Session, field_key: str) -> list[StudentField]:
    """所有班里**这个 key** 的字段定义。

    学院视图按 `field_key` 把各班的列合并成一份，所以「这一列」在各班
    对应**多个** `student_field` 行（每班一个，key 相同、id 不同）。
    """
    return list(
        db.scalars(
            select(StudentField).where(
                StudentField.field_key == field_key, StudentField.status == 1
            )
        )
    )


def preview_college_field_retype(
    db: Session, user: LoginUser, field_key: str, new_type: str
) -> dict:
    """改类型前先看一眼会发生什么。**不写库。**

    跨**所有班**汇总：这一列在每个班各有一份定义、各有各的存量值，
    改类型要一次改完，预览也得一次摊开——只报一个班的数会骗人。

    返回结构和班级版**一模一样**（`convertibleSamples` / `unconvertibleSamples`
    那一套），两边的「改类型」对话框才能共用同一段界面。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    if new_type not in svc.FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(svc.FIELD_TYPES)}")
    with db.begin():
        fields = _fields_by_key(db, field_key)
        if not fields:
            raise BizException.bad_request("字段不存在")
        total_ok = total_bad = total_empty = 0
        ok_samples: list[dict] = []
        bad_samples: list[dict] = []
        old_type = fields[0].field_type
        for f in fields:
            ok, bad, empty = svc.plan_retype(db, f, new_type)
            total_ok += len(ok)
            total_bad += len(bad)
            total_empty += empty
            for _vid, before, after in ok:
                if len(ok_samples) < svc._RETYPE_SAMPLE:
                    ok_samples.append({"before": before, "after": after})
            for _vid, before, _after in bad:
                if len(bad_samples) < svc._RETYPE_SAMPLE:
                    bad_samples.append({"before": before})
        return {
            "key": field_key,
            "label": fields[0].field_label,
            "fromType": old_type,
            "fromTypeText": svc.FIELD_TYPE_TEXT.get(old_type, old_type),
            "toType": new_type,
            "toTypeText": svc.FIELD_TYPE_TEXT.get(new_type, new_type),
            "classCount": len(fields),
            "total": total_ok + total_bad + total_empty,
            "convertibleCount": total_ok,
            "convertibleSamples": ok_samples,
            "convertibleTruncated": max(0, total_ok - len(ok_samples)),
            "unconvertibleCount": total_bad,
            "unconvertibleSamples": bad_samples,
            "unconvertibleTruncated": max(0, total_bad - len(bad_samples)),
            "emptyCount": total_empty,
        }


def apply_college_field_retype(
    db: Session, user: LoginUser, field_key: str, new_type: str, clear_bad: bool = False
) -> dict:
    """确认改类型：按预览的方案落地（**所有班**一起改）。

    `clear_bad=False`（默认）——转不了的值**保留原文本**。这样改错了还能改回来，
    不丢数据。`clear_bad=True` ——转不了的值置空，用户明确说"这些不要了"。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以修改字段")
    if new_type not in svc.FIELD_TYPES:
        raise BizException.bad_request(f"字段类型只能是 {'/'.join(svc.FIELD_TYPES)}")
    with db.begin():
        fields = _fields_by_key(db, field_key)
        if not fields:
            raise BizException.bad_request("字段不存在")
        converted = kept = cleared = 0
        for f in fields:
            ok, bad, _empty = svc.plan_retype(db, f, new_type)
            for vid, _raw, after in ok:
                v = db.get(StudentRecordValue, vid)
                if v is not None:
                    v.value_text = after
            converted += len(ok)
            if clear_bad:
                for vid, _raw, _a in bad:
                    v = db.get(StudentRecordValue, vid)
                    if v is not None:
                        v.value_text = None
                cleared += len(bad)
            else:
                kept += len(bad)
            f.field_type = new_type
        db.flush()
        return {
            "key": field_key,
            "label": fields[0].field_label,
            "toType": new_type,
            "classCount": len(fields),
            "convertedCount": converted,
            "keptUnconvertibleCount": kept,
            "clearedCount": cleared,
        }


# ==================== 成员管理：班主任（导员）名册 ====================


def advisers(db: Session, user: LoginUser) -> dict:
    """各班班主任（导员）名册。

    ## **一人一行**，不是一班一行

    名册是「按人排」的，所以一行 = 一个班主任账号，班级只是他的一列。

    为什么不能一班一行：有的班有**两个**班主任（班主任本人 + 兼班主任的院长）。
    一班一行就得把两个账号塞进一格，于是「账号状态」那列只能渲染两个「启用」，
    看不出哪个配哪个；而手机号、最近登录这类**属于某个账号**的属性，
    一行放不下两个账号时就只能取第一个——**第二个人的手机号永远不显示**。

    一人一行就没有这个问题：每行一个账号、一个状态、一个手机号。
    一个班有几个人就占几行（班级那列重复），这是名册的正常样子。

    没有班主任账号的班**仍然占一行**（账号各列为空）——「哪个班还没人管」
    是这份名册最该被看见的信息，不能因为没有账号就让那个班从表上消失。

    ## 谁算「班主任」

    **role=TEACHER 的账号**，**加上兼班主任的院长**（role=DEAN 且
    `dean_only=0`）——他就是那个班的班主任，只是职务是院长。
    只按 role=TEACHER 筛的话，院长兼班主任会从名册里消失：
    名册上写着「这个班的班主任是某某」，而某人在系统里明明管着这个班。

    **纯院长**（`dean_only=1`）不算——他不担任任何班的班主任。

    ## 两个来源都要

    - `cls_class.head_teacher`：班级信息里登记的班主任**姓名**
    - 该班的**班主任账号**：能登录、有手机号、有状态

    两者可能不一致（登记了名字但没建号，或建了号没填班级信息），
    所以**都给出**，由看的人自己判断。缺哪个就留空，不编一个「待定」出来。
    """
    classes = _active_classes(db)
    # 第三十二轮：**班主任是「班」的属性**（多对多），不再由账号的默认班决定。
    #
    # 以前是「sys_user.class_id 里有他 = 他是这个班的班主任」——一个账号只能
    # 属于一个班，于是「一个老师带两个班」这件事在系统里**表达不出来**。
    # 现在是 sys_user_class：谁带哪些班。
    by_class: dict[int, list[SysUser]] = {}
    links = db.execute(
        select(SysUserClass.class_id, SysUser)
        .join(SysUser, SysUser.id == SysUserClass.user_id)
        .where(
            SysUserClass.class_id.in_([c.id for c in classes]) if classes else False,
            SysUser.status == 1,
        )
        .order_by(SysUserClass.class_id.asc(), SysUser.id.asc())
    ).all()
    for cid, t in links:
        by_class.setdefault(int(cid), []).append(t)

    rows = []
    for c in classes:
        ts = by_class.get(c.id, [])
        if not ts:
            # 这个班还没有班主任账号：仍然占一行，把「没人管」显出来
            rows.append(
                {
                    "classId": c.id,
                    "className": c.class_name,
                    "grade": c.grade or "",
                    "headTeacher": (c.head_teacher or "").strip(),
                    "teacherId": None,
                    "username": "",
                    "realName": "",
                    "phone": "",
                    "status": None,
                    "lastLoginAt": None,
                }
            )
            continue
        for t in ts:
            rows.append(
                {
                    "classId": c.id,
                    "className": c.class_name,
                    "grade": c.grade or "",
                    "headTeacher": (c.head_teacher or "").strip(),
                    "teacherId": t.id,
                    "username": t.username,
                    "realName": t.real_name or "",
                    "phone": t.phone or "",
                    "status": t.status,
                    "lastLoginAt": fmt_dt(t.last_login_at),
                }
            )
    return {"rows": rows, "total": len(rows)}


def set_class_teachers(
    db: Session, user: LoginUser, class_id: int, teacher_ids: list[int]
) -> dict:
    """设置某个班的**班主任**（可以多个）（第三十二轮）。

    「班主任」是**班**的属性：一个人可以带好几个班，一个班也可以有
    正、副两个班主任。这两件事以前都表达不出来——账号只有一个 class_id。

    只给**运营角色以上**（含院长）能改：这是「谁管这个班」的分配。
    班主任本人也能改「我带的班」（见 update_profile），但那是**加自己**，
    不是改别人的安排。
    """
    with db.begin():
        clazz = db.get(ClsClass, class_id)
        if clazz is None or clazz.status != 1:
            raise BizException.bad_request("班级不存在或已停用")
        # 只能选**启用**的账号（停用的账号当班主任没有意义）
        wanted = [int(t) for t in teacher_ids]
        alive: list[int] = []
        if wanted:
            alive = [
                int(uid)
                for (uid,) in db.execute(
                    select(SysUser.id).where(
                        SysUser.id.in_(wanted), SysUser.status == 1
                    )
                )
            ]
        # 重写这个班的班主任安排
        db.execute(
            delete(SysUserClass).where(SysUserClass.class_id == class_id)
        )
        for uid in alive:
            db.add(SysUserClass(user_id=uid, class_id=class_id))
        db.flush()
        # 账号的**默认班**（sys_user.class_id）也一起对齐：
        # 它是「登录后落在哪个班」，不能和实际安排矛盾。
        for uid in alive:
            u = db.get(SysUser, uid)
            if u is not None and u.class_id != class_id:
                u.class_id = class_id
        db.flush()
        return {
            "classId": class_id,
            "className": clazz.class_name,
            "teacherIds": alive,
        }


def teachers_of_class(db: Session, class_id: int) -> list[dict]:
    """某个班的班主任账号（第三十二轮）。"""
    rows = db.execute(
        select(SysUser)
        .join(SysUserClass, SysUserClass.user_id == SysUser.id)
        .where(SysUserClass.class_id == class_id, SysUser.status == 1)
        .order_by(SysUser.id.asc())
    ).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "realName": u.real_name or "",
            "role": u.role,
            "status": u.status,
        }
        for u in rows
    ]


def teacher_candidates(db: Session) -> list[dict]:
    """能被选为班主任的账号（第三十二轮）。

    = 所有**启用**的账号——不只是 role=TEACHER。
    因为「谁是班主任」是**班**的安排：生活委员/班长被安排带班也是常事，
    而职务（role）决定的是「他有哪些权限」，两者是正交的。
    """
    rows = db.scalars(
        select(SysUser).where(SysUser.status == 1).order_by(SysUser.id.asc())
    ).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "realName": u.real_name or u.username,
            "role": u.role,
        }
        for u in rows
    ]



# ==================== 学院任务 ====================


def tasks(
    db: Session,
    user: LoginUser,
    *,
    keyword: str | None = None,
    class_id: int | None = None,
    only_pinned: bool = False,
) -> dict:
    """跨班级的任务一览。

    ## 答题分母**按任务自己的班级**算

    一个任务只对**它所在那个班**的同学有效。所以「已填 3 / 共 30 人」
    里的 30 是那个班的应答人数，不是全院人数。跨班混算会得出
    「已填 3 / 共 60 人」这种没人看得懂的数。

    分母的算法与班级任务页**完全一致**（`task_service.is_answer_target`），
    两处各算一次必然漂。
    """
    classes = _active_classes(db)
    target = [c for c in classes if class_id is None or c.id == class_id]
    class_ids = [c.id for c in target]

    if not class_ids:
        return {"rows": [], "total": 0, "classes": _class_choices(db, classes)}

    stmt = select(ClsTask).where(ClsTask.class_id.in_(class_ids))
    kw = (keyword or "").strip()
    if kw:
        pat = like_pattern(kw)
        stmt = stmt.where(
            or_(ClsTask.title.like(pat), ClsTask.question.like(pat))
        )
    if only_pinned:
        stmt = stmt.where(ClsTask.pinned == 1)

    task_list = list(
        db.scalars(stmt.order_by(ClsTask.class_id.asc(), ClsTask.id.desc()))
    )

    # 应答对象：各班的启用账号。分母逐条按任务的发布人筛（发布人自己不答）。
    active_by_class: dict[int, list[SysUser]] = {}
    if task_list:
        for u in db.scalars(
            select(SysUser).where(
                SysUser.class_id.in_(class_ids), SysUser.status == 1
            )
        ):
            active_by_class.setdefault(u.class_id, []).append(u)

    answers_by_task: dict[int, int] = {}
    if task_list:
        for tid, cnt in db.execute(
            select(ClsTaskAnswer.task_id, func.count())
            .where(ClsTaskAnswer.task_id.in_([t.id for t in task_list]))
            .group_by(ClsTaskAnswer.task_id)
        ):
            answers_by_task[int(tid)] = int(cnt)

    class_by_id = {c.id: c for c in classes}
    rows = []
    for t in task_list:
        cls = class_by_id.get(t.class_id)
        base = sum(
            1
            for u in active_by_class.get(t.class_id, [])
            if is_answer_target(u, t.created_by)
        )
        answered = answers_by_task.get(t.id, 0)
        rows.append(
            {
                "id": t.id,
                "classId": t.class_id,
                "className": cls.class_name if cls else "",
                "grade": (cls.grade if cls else "") or "",
                "title": t.title,
                "question": t.question,
                "open": is_open(t),
                "pinned": bool(t.pinned),
                "deadline": fmt_dt(t.deadline),
                "createdAt": fmt_dt(t.created_at),
                "answered": answered,
                "total": base,
                "unanswered": max(0, base - answered),
            }
        )

    return {"rows": rows, "total": len(rows), "classes": _class_choices(db, classes)}
