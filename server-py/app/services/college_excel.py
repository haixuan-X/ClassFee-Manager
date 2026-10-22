"""学院级的 Excel 导入 / 导出（第三十轮）。

和班级版（`student_excel.py`）的区别只有一处，但那一处是本质的：**跨班级**。

- **导出**：所有班级的学生，表格里多一列「班级」和「年级」。
- **导入**：按文件里的「班级」列把**每一行**分发到对应的班；文件里没有
  「班级」列时，走调用方指定的默认班。
- **列（字段）管理**：一次操作**所有班级**——学院只有一份表，
  新增一列就该每个班都有一列，否则那张表在跨班视图里是残的。

## 为什么列要在所有班级各建一份、且 **field_key 必须相同**

`student_field` 的唯一键是 `(class_id, field_key)`，所以同一个 key 在不同班
可以各有一份定义。学院视图按 `field_key` 把各班的列**合并成一份**
（见 `college_service._unified_columns`）——

- 各班 key **相同** → 合并后是一列，值按各班自己的 `field_id` 解析，对得上；
- 各班 key **不同** → 合并后是两列，标题还长得一模一样，值各填各的——
  用户会看到两个「寝室号」列，而且改一个另一个不动。

所以建列时**先生成一个 key，再在每个班用它建一份**。
"""
from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from io import BytesIO
from typing import Callable

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import (
    ClsClass,
    StudentField,
    StudentRecord,
    StudentRecordValue,
    SysUser,
    SysUserClass,
)
from ..security import LoginUser
from . import student_excel as se
from . import student_service as svc
from .college_service import _active_classes, _grade_choices, _unified_columns

#: 学院表里的锚点列。**学号/姓名是行的身份**，不能没有。
ANCHOR_HEADERS = ("学号", "姓名", "班级", "年级")

#: 锚点列的**列标识**（界面上传的是 key，不是中文名）。
#:
#: 学号/姓名**无条件保留**；班级/年级**听勾选**——有人导出只要
#: 学号姓名加几个字段，不需要「这人在哪个班」。
ANCHOR_KEYS = ("__no__", "__name__", "__class__", "__grade__")

#: 锚点列的中文名（写表头用）
ANCHOR_LABELS = {
    "__no__": "学号",
    "__name__": "姓名",
    "__class__": "班级",
    "__grade__": "年级",
}

#: 导入时用来定位班级的列名（可以叫「班级」或「班」）
_CLASS_HEADERS = ("班级", "班", "班级名称", "所在班级")

#: 导入时用来**指定班主任**的列名（第三十二轮）。
#:
#: 和「班级」一样是**元信息列**：不进字段表，而是用来建立
#: 「这个班由谁带」的关系（sys_user_class）。
#: 一个老师带好几个班时，表格里同一个名字出现多行即可。
_TEACHER_HEADERS = ("班主任", "班主任姓名", "导员", "辅导员")

#: 单次导入最多多少行
MAX_ROWS = se.MAX_ROWS

_HEAD_FILL = se._HEAD_FILL
_HEAD_FONT = se._HEAD_FONT
_TITLE_FONT = se._TITLE_FONT


# ==================== 导出 ====================


def export_xlsx(
    db: Session,
    user: LoginUser,
    only_ids: list[int] | None = None,
    only_fields: list[str] | None = None,
    *,
    keyword: str | None = None,
    class_id: int | None = None,
    grade: str | None = None,
) -> tuple[bytes, str]:
    """导出学院学生信息（跨班级）。行和列都可以只导其中一部分。

    - `only_ids`：只导这些行（按 id）
    - `only_fields`：只导这些列（字段标识）。**学号/姓名无条件保留**——
      一份没有学号的表格无法说明每一行是谁，导出去也没法用；
      **班级/年级听勾选**。
    - `keyword` / `class_id` / `grade`：**和界面上看到的筛选一致**。
      界面上筛了「2026 级」，导出来就该是这批人——否则用户会拿到
      一份「屏幕上不是这些行、文件里却是」的表，那还不如不筛。

    「班级」这一列是学院视图的**命脉**：没有它，导出的表在 Excel 里是
    一堆分不清归属的行，再导回来也认不出该进哪个班——
    所以它虽然可取消，但**默认是勾上的**。
    """
    from . import college_service as cs

    payload = cs.students(
        db,
        user,
        keyword=keyword,
        class_id=class_id,
        grade=grade,
        page=1,
        size=cs.MAX_PAGE_SIZE,
    )
    all_columns = payload["columns"]
    rows = payload["rows"]

    if only_ids:
        want = {int(i) for i in only_ids}
        rows = [r for r in rows if r["id"] in want]

    columns = all_columns
    dropped = 0
    if only_fields:
        wanted = {k for k in only_fields}
        columns = [c for c in all_columns if c["key"] in wanted]
        dropped = len(all_columns) - len(columns)

    # 「年级」字段列**不单独出列**。
    #
    # 学院表里学生的年级= 他自己填的 grade 字段值（没填才回退班级年级），
    # 固定的「年级」锚点列写的正是这个值。再让 grade 字段列跟着出一遍，
    # 表里就有**两列都叫「年级」**——值一样还行，值不一样就不知道该信哪个。
    # 表格里（前端）也是同样处理：固定列代表 grade 字段，字段列不再重复。
    #
    # ⚠ 这**不算「未选」**（用户根本没在界面上看到这一列），
    # 所以不并进 `dropped`，只在说明里讲一句。
    grade_dup = [c for c in columns if c["key"] == cs.GRADE_FIELD_KEY]
    if grade_dup:
        columns = [c for c in columns if c["key"] != cs.GRADE_FIELD_KEY]

    # 哪些锚点列进文件。
    #
    # **学号/姓名无条件保留**——一份没有学号的表没法说明每一行是谁（和班级版一致）。
    # **班级/年级听勾选**：它们是「这人在哪个班、哪一届」，
    # 有的人导出只要学号姓名和几个字段，不需要它们。
    anchor_wanted = {k for k in only_fields} if only_fields is not None else set(ANCHOR_KEYS)
    keep_class = "__class__" in anchor_wanted
    keep_grade = "__grade__" in anchor_wanted

    wb = Workbook()
    ws = wb.active
    ws.title = "学院学生信息"

    ws.cell(
        row=1, column=1, value=f"学院学生信息 · 导出 {datetime.now():%Y-%m-%d %H:%M}"
    ).font = _TITLE_FONT
    scope_text = f"全部班级共 {len(rows)} 人，共 {2 + int(keep_class) + int(keep_grade) + len(columns)} 列"
    if dropped > 0:
        scope_text += f"（另有 {dropped} 列未选）"
    if grade_dup:
        scope_text += "（年级与「年级」字段合并为一列）"
    ws.cell(row=2, column=1, value=f"导出范围：{scope_text}").font = Font(size=10, color="666666")
    header_row = 3

    # 锚点列在前，字段列在后
    anchor_cols: list[tuple[str, str]] = [("__no__", "学号"), ("__name__", "姓名")]
    if keep_class:
        anchor_cols.append(("__class__", "班级"))
    if keep_grade:
        anchor_cols.append(("__grade__", "年级"))
    labels = [label for _key, label in anchor_cols] + [c["label"] for c in columns]
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=header_row, column=i, value=label)
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(28, len(label) * 2 + 6))

    for r_i, row in enumerate(rows, start=header_row + 1):
        values = row["values"]
        anchor_vals = {
            "__no__": row["studentNo"],
            "__name__": row["name"],
            "__class__": row["className"],
            "__grade__": row["grade"],
        }
        for i, (key, _label) in enumerate(anchor_cols, start=1):
            ws.cell(row=r_i, column=i, value=anchor_vals[key])
        for i, col in enumerate(columns, start=len(anchor_cols) + 1):
            raw = values.get(col["key"])
            text = "" if raw is None else str(raw)
            if col["type"] == svc.FT_NUMBER:
                try:
                    text = str(int(float(text))) if text.strip() else ""
                except ValueError:
                    pass
            ws.cell(row=r_i, column=i, value=text)

    from io import BytesIO as _B

    buf = _B()
    wb.save(buf)
    return buf.getvalue(), f"学院学生信息_{datetime.now():%Y%m%d_%H%M}.xlsx"


# ==================== 导入 ====================


def _match_class(
    classes: list[ClsClass], raw: str
) -> ClsClass | None:
    """按班级名找班。允许「云计算2502」或「云计算2502（2026级）」这种写法。"""
    name = (raw or "").strip()
    if not name:
        return None
    for c in classes:
        if c.class_name == name:
            return c
    # 带括号的写法：去掉括号部分再比一次
    cleaned = re.sub(r"[（(].*?[)）]\s*$", "", name).strip()
    for c in classes:
        if c.class_name == cleaned:
            return c
    # 反过来：库里带括号、文件里不带
    for c in classes:
        if re.sub(r"[（(].*?[)）]\s*$", "", c.class_name).strip() == cleaned:
            return c
    return None


def _shared_key_maker(db: Session, class_ids: list[int]) -> "Callable[[str], str]":
    """做一个「按列名记忆」的 key 生成器：**所有班共用同一个 key**。

    学院视图按 `field_key` 把各班的列合并成一份，所以同一个列名在所有班
    必须拿到**同一个 key**——否则合并后是两列同名，而值各填各的
    （改一列另一列不动，用户会以为坏了）。

    ## 已有列怎么办

    先用**现存的定义**定下每个列名的规范 key（取第一个撞上这个列名的字段），
    这样「A 班早就有『学院标签』这一列、B 班还没有」的情况，导入到 B 班时
    用的是 A 班那个 key —— 两班合并后仍是**一列**，值也各归各的班但列是同一列。

    ## 新列怎么办

    生成一个**在所有班都没被占用**的 key（`college_service._next_field_key`），
    然后所有班都用它。
    """
    from . import college_service as cs

    cache: dict[str, str] = {}
    for f in db.scalars(
        select(StudentField).where(
            StudentField.class_id.in_(class_ids), StudentField.status == 1
        )
    ):
        cache.setdefault(f.field_label, f.field_key)

    def make(label: str) -> str:
        key = cache.get(label)
        if key is None:
            key = cs._next_field_key(db, class_ids)
            cache[label] = key
        return key

    return make


#: 文件里可能出现的「年级」列名（用来给自动新建的班级定年级）
GRADE_HEADERS = ("年级", "年级/届别", "入学年级")


def _row_grade_of(cells: list[str], headers: list[str]) -> str:
    """这一行的年级（文件里有「年级」列的话）。

    给**自动新建**的班级定年级用的：名单里写「2026级」，这个班就该是 2026级。
    """
    for h in GRADE_HEADERS:
        if h in headers:
            v = cells[headers.index(h)].strip()
            if v:
                return v
    return ""


def _create_class(db: Session, name: str, grade: str) -> ClsClass:
    """按名字新建一个班级。

    年级取文件里那一行的年级（没有就留空——**不编**一个出来）。
    余额留 0：它由记账流水实时算，这里写死会和流水对不上。
    """
    c = ClsClass(
        class_name=name,
        grade=grade or "",
        head_teacher=None,
        balance=Decimal("0.00"),
        status=1,
    )
    db.add(c)
    db.flush()
    return c


def import_xlsx(
    db: Session,
    user: LoginUser,
    content: bytes,
    default_class_id: int | None = None,
) -> dict:
    """导入学院学生信息。**按文件里的「班级」列分发到各班**。

    ## 分发规则

    1. 文件里有「班级」列 → 每一行按自己的班级走（学号相同但班级不同的两行，
       是**两个班里的两个人**，不是重复——这和班级版「同表重复学号」不是一回事）
    2. 文件里没有「班级」列 → 全部进 `default_class_id` 指定的班
    3. 某一行的班级名在库里找不到 → **这一行跳过并报错**，
       不静默塞进别的班（塞错班比不导更糟：人找不到了）

    ## 与班级版共用判据

    学号是 upsert 键、空格子不覆盖旧值、没见过的列自动建字段、重复学号
    后一行覆盖前一行——全部走 `student_excel._import_rows_into_class`，
    那一份实现是唯一口径。
    """
    if not content:
        raise BizException.bad_request("没有读到文件内容")
    try:
        wb = load_workbook(BytesIO(content), data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        raise BizException.bad_request(f"无法解析 Excel 文件：{exc}") from exc
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration as exc:
        raise BizException.bad_request("表格是空的，至少要有表头和一行数据") from exc

    headers = [se._cell_text(c) for c in header_row]
    if "学号" not in headers:
        raise BizException.bad_request("表格里必须有「学号」列——它是用来说明这行数据是谁的")
    if "姓名" not in headers:
        raise BizException.bad_request("表格里必须有「姓名」列")

    # 「班级」列是可选的：有就按行分发，没有就全进默认班
    col_class = -1
    for name in _CLASS_HEADERS:
        if name in headers:
            col_class = headers.index(name)
            break

    # 「班主任」列（第三十二轮）：可选。有就按行指定「这个班由谁带」。
    col_teacher = -1
    for name in _TEACHER_HEADERS:
        if name in headers:
            col_teacher = headers.index(name)
            break

    created = updated = skipped = 0
    errors: list[str] = []
    new_fields: list[dict] = []
    unmatched: list[str] = []
    # 同一个列名在每个班各建了一份字段（key 相同），但**只该报一次**——
    # 报两遍会让用户以为建了两个列。
    seen_new_labels: set[str] = set()

    # ⚠ **班级查询必须在事务块内**：SQLAlchemy 里执行过一次 SELECT 就开了
    # 隐式事务，后面再 `db.begin()` 会抛 InvalidRequestError（HTTP 500）。
    with db.begin():
        classes = _active_classes(db)
        if not classes:
            raise BizException.bad_request("还没有班级，无法导入")
        by_id = {c.id: c for c in classes}

        default_class: ClsClass | None = None
        if col_class < 0:
            if default_class_id is None:
                raise BizException.bad_request(
                    "表格里没有「班级」列，请先选择这些学生要导入到哪个班"
                )
            default_class = by_id.get(default_class_id)
            if default_class is None:
                raise BizException.bad_request("选择的班级不存在")

        # 先整表读进来：新建字段要按整列的取值形态猜类型
        body, _samples_all = se._read_body(rows, headers)
        processed = len(body)

        # 所有班共用同一个 key 生成器（学院视图靠 field_key 合并列）
        key_maker = _shared_key_maker(db, [c.id for c in classes])

        # 按班级分组。同一张表里「同班同号」才算重复（跨班同号是两个人）
        groups: dict[int, tuple[list, dict]] = {}
        # 这次导入**新建**的班级（名字在库里没有 → 自动建班）。
        # 建完它就会出现在「班级」筛选里——筛选是跟着数据走的，不是死数据。
        created_classes: list[str] = []
        # 班 → 这一行里出现的班主任名字（第三十二轮）
        teacher_by_class: dict[int, set[str]] = {}
        for excel_row_no, cells in body:
            target = default_class
            if col_class >= 0:
                raw_class = cells[col_class].strip()
                if not raw_class:
                    # ⚠ **空班级名不能建班**——会建出一个名字为空的班
                    # （名册上多一行空班级、学生进了那个「班」）。
                    # 这一行直接跳过并报出来。
                    errors.append(
                        f"第 {excel_row_no} 行：班级是空的，这行没导入"
                    )
                    continue
                matched = _match_class(classes, raw_class)
                if matched is None:
                    # ⚠ 库里没有这个班 → **自动建班**，而不是把行丢掉。
                    #
                    # 丢掉的话：用户导一份全校名单进来，发现少了一半人，
                    # 还得先手工建班再导一遍。而「没见过的列自动建字段」
                    # 那条设计（第二十四轮）就是这个思路的延伸——**用户导进来的
                    # 东西不该被静默丢弃**。
                    matched = _create_class(db, raw_class, _row_grade_of(cells, headers))
                    classes.append(matched)
                    by_id[matched.id] = matched
                    created_classes.append(matched.class_name)
                target = matched
            cid = target.id
            # 第三十二轮：这一行指定的班主任（**元信息**，不进字段表）
            if col_teacher >= 0:
                t_name = cells[col_teacher].strip()
                if t_name:
                    teacher_by_class.setdefault(cid, set()).add(t_name)
            samples = groups.setdefault(cid, ([], {}))[1]
            g_body = groups[cid][0]
            g_body.append((excel_row_no, cells))
            for i, h in enumerate(headers):
                if col_class >= 0 and i == col_class:
                    continue
                v = cells[i].strip()
                if v:
                    col = samples.setdefault(h, [])
                    if len(col) < 200:
                        col.append(v)

        for cid, (g_body, g_samples) in groups.items():
            # 班级列本身不是字段（它是分发依据），不参与建字段
            g_headers = headers
            drop = {i for i in (col_class, col_teacher) if i >= 0}
            if drop:
                g_headers = [h for i, h in enumerate(headers) if i not in drop]
                # cells 也要同步去掉那一列，否则列位会错位
                g_body = [
                    (n, [c for i, c in enumerate(cs) if i not in drop])
                    for n, cs in g_body
                ]
            r = se._import_rows_into_class(
                db, user, cid, g_headers, g_body, g_samples, key_maker
            )
            created += r["created"]
            updated += r["updated"]
            skipped += r["skippedEmptyCells"]
            errors.extend(r["errors"])
            new_fields.extend(
                f
                for f in r["newFields"]
                if not (f["label"] in seen_new_labels or seen_new_labels.add(f["label"]))
            )
            for h in r["unmatchedColumns"]:
                if h not in unmatched:
                    unmatched.append(h)

        # ---------- 第三十二轮：按「班主任」列建立师生关系 ----------
        #
        # 「班主任」是**班**的属性：这一行说「云计算2502 的班主任是王老师」，
        # 就把王老师记成这个班的班主任（sys_user_class）。
        #
        # 一个老师带好几个班时，表格里同一个名字出现在多个班的行里即可 ——
        # 这正是「通过导入的 Excel 识别多个班级信息」的意思。
        #
        # 匹配按**姓名或登录名**精确匹配（real_name / username），
        # 因为表格里填的是**名字**（和班级信息里登记的班主任姓名一个口径）。
        # 匹配不到就**报出来**（别静默丢掉：用户以为配好了，其实没有）。
        teacher_links = 0
        for cid, names in teacher_by_class.items():
            for t_name in sorted(names):
                uid = db.scalar(
                    select(SysUser.id).where(
                        or_(
                            SysUser.real_name == t_name,
                            SysUser.username == t_name,
                        ),
                        SysUser.status == 1,
                    ).limit(1)
                )
                if uid is None:
                    errors.append(
                        f"班级「{by_id[cid].class_name if cid in by_id else cid}」的班主任"
                        f"「{t_name}」找不到对应账号（按姓名或登录名匹配），没配上"
                    )
                    continue
                exists = db.scalar(
                    select(SysUserClass.user_id).where(
                        SysUserClass.user_id == uid, SysUserClass.class_id == cid
                    )
                )
                if exists is None:
                    db.add(SysUserClass(user_id=int(uid), class_id=cid))
                    teacher_links += 1
                # 班级信息里登记的班主任姓名也同步一下（那一栏是自由文本）
                clazz = by_id.get(cid)
                if clazz is not None and not (clazz.head_teacher or "").strip():
                    clazz.head_teacher = t_name
        db.flush()

    return {
        "created": created,
        "updated": updated,
        "teacherLinks": teacher_links,
        "rows": processed,
        "skippedEmptyCells": skipped,
        "newFields": new_fields,
        "duplicateRows": len([e for e in errors if "重复" in e]),
        "unmatchedColumns": unmatched,
        "errors": errors[:50],
        "errorCount": len(errors),
    }
