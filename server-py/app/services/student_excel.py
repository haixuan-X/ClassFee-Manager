"""学生信息的 Excel 导入 / 导出。

## 导入

- **upsert 键 = 学号**（`student_record` 上的锚点），库里没有就新增记录，已存在就更新。
- **空值不覆盖**：表格里空着的格子不动库里旧值。整行覆盖会把「这次只填了姓名」
  变成「把别人的身份证号也清空了」，这是最容易被投诉的行为。
- **首行是表头**，按 `field_label` 匹配已有字段。
- **没见过的列自动建字段**（第二十四轮）：分批收集信息时老师手上常常有好几张表，
  第二张只多几列（如"寝室信息"）。早先的做法是报 `unmatchedColumns` 然后丢掉，
  等于逼着每次都先去界面上手工加一遍列——这恰恰是导入最核心的用法。
  现在按**实际取值形态**猜类型（整列 YYYYMMDD → 日期、整列整数 → 数字、其余 → 文本），
  建完立刻把这一列的值写进去，并在结果里报出 `newFields` 让人知道多了什么。
- **不创建登录账号**：导入名单 ≠ 授权登录。账号仍由班主任在「成员管理」单独建。

## 实测到的格式坑（来自真实表格）

- 「出生日期」「入校日期」在 Excel 里存的是**数字** `20071209`，`number_format=General`，
  **不是**日期序列号。按序列号去读会得到 1900 年附近的日期，所以按 `YYYYMMDD` 文本解析。
- 学号、身份证号、家长电话这些**在 Excel 里是数字**，但**在库里必须是文本**：
  学号前导 0 会丢、身份证超过 15 位会被 Excel 截断成科学计数法。
- `0x8000` 以上的码值（考生号、院校代码、专业代码）在 openpyxl 里正常读出，不用特殊处理。
"""
from __future__ import annotations

import re
from datetime import datetime
from io import BytesIO

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import StudentField, StudentRecord, StudentRecordValue
from ..security import LoginUser
from . import student_service as svc

MAX_ROWS = 5000  # 单次导入上限；班级量级远小于此，够用且防止误传超大表

#: 锚点列名：这两列写在 `student_record` 上，不走字段值表，因此**不参与表头匹配**
ANCHOR_HEADERS = ("学号", "姓名")


def _cell_text(v) -> str:
    """统一成字符串。

    openpyxl 对 `20071209` 给 int、对 `1.0` 给 float；float 要去掉 `.0`
    否则「学号 12344312.0」会在库里留下一条带小数点的脏数据。
    """
    if v is None:
        return ""
    if isinstance(v, bool):
        return "是" if v else "否"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d")
    return str(v).strip()


#: 能当数字的：正负号、小数点、科学计数法。够用就行，不追求完整校验。
_NUM_RE = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")

#: 8 位纯数字且落在 1900~2100 之间 → 当日期（YYYYMMDD）
_YMD_LEN = 8
_DATE_MIN, _DATE_MAX = 19000101, 21001231


def _looks_date(vals: list[str]) -> bool:
    """整列都像 YYYYMMDD 才算日期。

    必须**整列**都成立：只要有一格不是，「寝室号 301」这种就会把整列拖成文本。
    宁可判成文本（用户能在界面上改字段类型），也不要判错——
    猜成日期之后，用户往里填 "3-01" 会直接被后端拒掉，格子存不进去。
    """
    seen = False
    for v in vals:
        if not v:
            continue  # 空格子不算"不是日期"，否则整列只要有一格空就全变文本
        seen = True
        if len(v) != _YMD_LEN or not v.isdigit():
            return False
        if not (_DATE_MIN <= int(v) <= _DATE_MAX):
            return False
    return seen


def _looks_number(vals: list[str]) -> bool:
    seen = False
    for v in vals:
        if not v:
            continue
        seen = True
        if not _NUM_RE.match(v):
            return False
    return seen


def _guess_field_type(vals: list[str]) -> str:
    """按**实际取值形态**猜字段类型。判不准一律文本。"""
    if _looks_date(vals):
        return svc.FT_DATE
    if _looks_number(vals):
        return svc.FT_NUMBER
    return svc.FT_TEXT


def _make_field_key(db: Session, class_id: int, label: str) -> str:
    """从字段名生成一个班内唯一的 `field_key`。

    中文没法直接当 key（`_KEY_RE` 要求字母开头），用音译是不现实的，
    所以退化成 `f_时间戳`，和界面上新建自定义字段时的做法一致。
    """
    base = f"f_{int(datetime.now().timestamp() * 1000)}"
    key = base
    n = 0
    while db.scalar(
        select(StudentField.id).where(
            StudentField.class_id == class_id, StudentField.field_key == key
        )
    ) is not None:
        n += 1
        key = f"{base}_{n}"
    return key


def _find_or_create_fields(
    db: Session,
    class_id: int,
    headers: list[str],
    actor: LoginUser,
    samples: dict[str, list[str]] | None = None,
) -> tuple[dict[str, StudentField], list[str], list[dict]]:
    """把表头对齐到字段定义，**没见过的列顺手建出来**。

    返回 `(label→field, 未能处理的表头, 新建字段清单)`。

    匹配顺序：先按 `field_label` 精确匹配（用户能在界面上看到的名字），
    再按 `field_key` 匹配（机器名，方便脚本化导入）。

    `samples` 是 `{表头: 该列的非空取值样本}`，用来给**新建**的字段猜类型。
    没有样本（列全是空的）就按文本建——空列猜不出任何东西，
    用户填了值之后可以在表格里改成别的类型。
    """
    if actor.role not in svc.FIELD_ADD_ROLES:
        # 没有加字段权限的人不能顺带建字段：他导进来的表如果带了陌生列，
        # 直接跳过并报出来，而不是越权改表结构。
        by_label: dict[str, StudentField] = {}
        by_key: dict[str, StudentField] = {}
        for f in db.scalars(
            select(StudentField).where(
                StudentField.class_id == class_id, StudentField.status == 1
            )
        ):
            by_label.setdefault(f.field_label, f)
            by_key.setdefault(f.field_key, f)
        mapping0: dict[str, StudentField] = {}
        unmatched: list[str] = []
        for h in headers:
            h = (h or "").strip()
            if not h or h in ANCHOR_HEADERS:
                continue
            f = by_label.get(h) or by_key.get(h)
            if f is not None:
                mapping0[h] = f
            else:
                unmatched.append(h)
        return mapping0, unmatched, []

    by_label = {}
    by_key = {}
    for f in db.scalars(
        select(StudentField).where(
            StudentField.class_id == class_id, StudentField.status == 1
        )
    ):
        by_label.setdefault(f.field_label, f)
        by_key.setdefault(f.field_key, f)

    mapping: dict[str, StudentField] = {}
    unmatched: list[str] = []
    new_fields: list[dict] = []
    for h in headers:
        h = (h or "").strip()
        if not h or h in ANCHOR_HEADERS:
            # 学号/姓名是锚点列，**本来就不在字段表里**，不是「没匹配上」。
            # 把它们报进 unmatched 会让用户以为表格有问题。
            continue
        f = by_label.get(h) or by_key.get(h)
        if f is not None:
            mapping[h] = f
            continue
        ftype = _guess_field_type((samples or {}).get(h, []))
        f = StudentField(
            class_id=class_id,
            field_key=_make_field_key(db, class_id, h),
            field_label=h,
            field_type=ftype,
            is_system=0,
            # 追加到末尾：不改动已有列的相对顺序，导入不该偷偷重排用户的表格
            sort=float(svc._next_sort(db, class_id)),
            status=1,
            created_by=actor.id,
        )
        db.add(f)
        db.flush()
        mapping[h] = f
        new_fields.append({"label": h, "type": ftype, "typeText": svc.FIELD_TYPE_TEXT.get(ftype, ftype)})
    return mapping, unmatched, new_fields


def import_xlsx(db: Session, user: LoginUser, content: bytes) -> dict:
    """导入 xlsx。返回 `{created, updated, skippedEmpty, unmatchedColumns, errors}`。"""
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

    headers = [_cell_text(c) for c in header_row]
    # 学号与姓名是锚点，不走字段值表；模板里必须有，否则无法定位「是哪一行」
    if "学号" not in headers:
        raise BizException.bad_request("表格里必须有「学号」列——它是用来说明这行数据是谁的")
    if "姓名" not in headers:
        raise BizException.bad_request("表格里必须有「姓名」列")
    col_no = headers.index("学号")
    col_name = headers.index("姓名")

    created = updated = skipped = 0
    errors: list[str] = []
    processed = 0

    # 表头匹配也是 SELECT，必须与写入同处一个事务：否则后续 db.begin() 会抛
    # InvalidRequestError（HTTP 500）。本轮在这里踩过一次。
    with db.begin():
        # 先把所有数据行读成内存表：新建字段时要按**整列**的取值形态猜类型，
        # 没法边读行边建字段（第一行还不知道后面有没有混进一个"301"）。
        # MAX_ROWS 已经限死了体量（5000 行 × 几十列），一次性读进内存没问题。
        body: list[tuple[int, list[str]]] = []
        samples: dict[str, list[str]] = {}
        for excel_row_no, raw in enumerate(rows, start=2):
            cells = [_cell_text(c) for c in raw]
            if not any(cells):
                continue
            processed += 1
            if processed > MAX_ROWS:
                raise BizException.bad_request(
                    f"单次导入超过 {MAX_ROWS} 行，请拆分后再导（当前已读 {processed} 行）"
                )
            if len(cells) < len(headers):
                cells += [""] * (len(headers) - len(cells))
            body.append((excel_row_no, cells))
            # 每列最多留 200 个非空样本用于猜类型，够判出整列性质了
            for i, h in enumerate(headers):
                v = cells[i].strip()
                if v:
                    col = samples.setdefault(h, [])
                    if len(col) < 200:
                        col.append(v)

        mapping, unmatched, new_fields = _find_or_create_fields(
            db, user.class_id, headers, user, samples
        )
        existing: dict[str, StudentRecord] = {}
        for r in db.scalars(
            select(StudentRecord).where(StudentRecord.class_id == user.class_id)
        ):
            existing[r.student_no] = r

        # {学号: 首次出现的行号}，用来报"第 N 行与第 M 行重复"
        seen_in_file: dict[str, int] = {}

        for excel_row_no, cells in body:
            student_no = cells[col_no].strip()
            name = cells[col_name].strip()
            if not student_no:
                errors.append(f"第 {excel_row_no} 行：学号为空，已跳过")
                continue
            if not name:
                errors.append(f"第 {excel_row_no} 行：姓名为空，已跳过")
                continue

            # 同一张表里学号重复：**后一行覆盖前一行**，不报错也不中止。
            #
            # 这里曾经是个 500：两行会各自往同一个 (record_id, field_id) 插一条值，
            # 撞上 uk_cell 唯一索引 → IntegrityError → 整个事务回滚，
            # 连前面已经导对的数据一起没了。用户看到的是「系统繁忙」，重试还是 500。
            # 重复学号在真实表格里很常见（复制粘贴漏删、空行没清干净）。
            if student_no in seen_in_file:
                dup_row = seen_in_file[student_no]
                errors.append(
                    f"第 {excel_row_no} 行：学号 {student_no} 与第 {dup_row} 行重复，"
                    f"已按本行覆盖"
                )
            seen_in_file[student_no] = excel_row_no

            rec = existing.get(student_no)
            if rec is None:
                rec = StudentRecord(
                    class_id=user.class_id,
                    student_no=student_no,
                    name=name,
                    user_id=svc.match_user_id(db, user.class_id, student_no),
                )
                db.add(rec)
                db.flush()
                existing[student_no] = rec
                created += 1
            else:
                # 姓名以本次表格为准，但允许表格里留空时保留旧值
                if name:
                    rec.name = name
                rec.user_id = rec.user_id or svc.match_user_id(db, user.class_id, student_no)
                updated += 1

            # 逐格写入；空格子不动旧值。
            # 用 enumerate 而不是 headers.index(h)：后者是 O(n) 线性查找，
            # 40 列 × 5000 行会白烧掉 20 万次比较。
            cells_to_write: list[tuple[int, int, str]] = []
            for ci, h in enumerate(headers):
                f = mapping.get(h)
                if f is None or h in ANCHOR_HEADERS:
                    continue
                raw_val = cells[ci].strip()
                # 学号/姓名这两列已经写进 student_record，不重复写进字段值表
                if not raw_val:
                    skipped += 1
                    continue
                try:
                    norm = svc.normalize_value(f.field_type, raw_val, f.field_label)
                except BizException as e:
                    errors.append(f"第 {excel_row_no} 行「{f.field_label}」：{e.message}")
                    continue
                if norm is not None:
                    cells_to_write.append((rec.id, f.id, norm))
            for rid, fid, val in cells_to_write:
                cur = db.execute(
                    select(StudentRecordValue).where(
                        StudentRecordValue.record_id == rid,
                        StudentRecordValue.field_id == fid,
                    )
                ).scalar_one_or_none()
                if cur is None:
                    db.add(StudentRecordValue(record_id=rid, field_id=fid, value_text=val))
                    # 立刻 flush：同一张表里重复学号时，下一行会再插一条**同样的**
                    # (record_id, field_id)，不 flush 就得等到事务提交才撞唯一索引，
                    # 那时整笔已经回滚、没法再回头修了。
                    db.flush()
                else:
                    cur.value_text = val

    return {
        "created": created,
        "updated": updated,
        "rows": processed,
        "skippedEmptyCells": skipped,
        "newFields": new_fields,
        "duplicateRows": len([e for e in errors if "重复" in e]),
        "unmatchedColumns": unmatched,
        "errors": errors[:50],
        "errorCount": len(errors),
    }


# ==================== 导出 ====================

_HEAD_FILL = PatternFill("solid", fgColor="E8EEF7")
_HEAD_FONT = Font(bold=True)
_TITLE_FONT = Font(bold=True, size=13)


def export_xlsx(
    db: Session,
    user: LoginUser,
    only_ids: list[int] | None = None,
    only_fields: list[str] | None = None,
) -> tuple[bytes, str]:
    """导出学生信息。行和列都可以只导其中一部分。

    - `only_ids`：**只导这些行**。传了 id 也必须落在用户的可见范围内——
      否则「只导勾选的」就变成了「按 id 就能偷看看不见的行」的越权口子。
    - `only_fields`：**只导这些列**（字段标识）。学号/姓名是锚点列，
      始终保留：一份没有学号的表格无法说明每一行是谁，导出去也没法用。

    行和列可以同时给：领导真正要的多半是「这 3 个人的学号、姓名、寝室、电话」，
    36 列全倒出来没人看得下去。
    """
    payload = svc.list_records(db, user)
    vis = payload["permission"]
    all_columns = payload["columns"]
    rows = payload["rows"]

    if only_ids:
        want = {int(i) for i in only_ids}
        rows = [r for r in rows if r["id"] in want]

    columns = all_columns
    dropped = 0
    if only_fields:
        wanted = {k for k in only_fields}
        # 学号/姓名是锚点，**无条件保留**——没有学号的表没法用
        columns = [c for c in all_columns if c["key"] in wanted or c["key"] in svc.ANCHOR_KEYS]
        dropped = len(all_columns) - len(columns)

    wb = Workbook()
    ws = wb.active
    ws.title = "学生信息"

    ws.cell(row=1, column=1, value=f"学生信息 · 导出 {datetime.now():%Y-%m-%d %H:%M}").font = _TITLE_FONT
    if only_ids:
        scope_text = f"勾选的 {len(rows)} 名学生"
    elif vis["canViewAll"]:
        scope_text = f"全部学生（共 {len(rows)} 人）"
    else:
        scope_text = f"仅本人（当前可见 {len(rows)} 行）"
    if dropped > 0:
        scope_text += f"，共 {len(columns)} 列（另有 {dropped} 列未选）"
    ws.cell(row=2, column=1, value=f"导出范围：{scope_text}").font = Font(size=10, color="666666")
    header_row = 3

    labels = [c["label"] for c in columns]
    for i, label in enumerate(labels, start=1):
        c = ws.cell(row=header_row, column=i, value=label)
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = max(12, min(28, len(label) * 2 + 6))

    for r_i, row in enumerate(rows, start=header_row + 1):
        values = row["values"]
        for i, col in enumerate(columns, start=1):
            key = col["key"]
            if key == "__no__":
                v = row["studentNo"]
            elif key == "__name__":
                v = row["name"]
            else:
                v = values.get(key)
            ws.cell(row=r_i, column=i, value=("" if v is None else v))
    ws.freeze_panes = ws.cell(row=header_row + 1, column=3)

    buf = BytesIO()
    wb.save(buf)
    fname = f"学生信息_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    return buf.getvalue(), fname