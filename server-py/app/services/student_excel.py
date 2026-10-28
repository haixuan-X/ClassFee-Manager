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
from typing import Callable

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


def _strip_wrapping_quotes(s: str) -> str:
    """剥掉整串被一对配对引号裹住的情况。

    某些导出工具（如从带引号的 CSV 转 xlsx）会把每个单元格都裹上引号，
    于是表头变成 `'学号'`、数据变成 `'2026001'`，系统自然认不出「学号」。
    仅当首尾是同一种引号且配对才剥，避免误伤「他说'你好'」这种正常文本。
    """
    _q = ("'", '"', "“", "”", "‘", "’")
    if len(s) >= 2 and s[0] in _q and s[-1] == s[0]:
        return s[1:-1]
    return s


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
    return _strip_wrapping_quotes(str(v).strip())


#: 表头里需要清掉的「脏字符」：控制字符、零宽、不间断空格、全角空格等。
#: 半角空格 `str.strip()` 能去，但**全角空格（中文输入法的空格）和零宽字符去不掉**，
#: 于是「学号（全角空格）」看着一样却匹配不到精确的「学号」，导入就报「没有学号」。
_HEADER_DIRTY_RE = re.compile(
    r"[\u0000-\u001f\u007f\u00a0\u1680\u2000-\u200a\u200b-\u200f\u2028\u2029\u202f\u205f\u3000\ufeff\s]+"
)


def _norm_header(v) -> str:
    """表头归一化：清掉全角空格/零宽/控制字符再 trim。"""
    if v is None:
        return ""
    return _HEADER_DIRTY_RE.sub(" ", str(v)).strip()


#: 学号/姓名的常见别名 → 规范名。**只动这两个锚点列**，
#: 不动「班级/年级/班主任」，否则会干扰学院侧按原列名做分发与字段建列的判断。
_HEADER_ALIASES = {
    "学号": {"学号", "学生学号", "学 号", "学号/", "编号", "序号", "准考证号", "学籍号", "学生编号"},
    "姓名": {"姓名", "学生姓名", "名字"},
}


def _canon_anchor(v) -> str:
    """表头清洗 + 学号/姓名别名归一。

    命中别名则换成规范名「学号」「姓名」；否则返回清洗后的原值。
    清洗同样作用于普通字段名，能顺带避免「宿舍号（全角空格）」被建成重复字段。
    """
    n = _strip_wrapping_quotes(_norm_header(v))
    for canon, aliases in _HEADER_ALIASES.items():
        if n == canon or n in aliases:
            return canon
    return n


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
    key_maker: "Callable[[str], str] | None" = None,
) -> tuple[dict[str, StudentField], list[str], list[dict]]:
    """把表头对齐到字段定义，**没见过的列顺手建出来**。

    返回 `(label→field, 未能处理的表头, 新建字段清单)`。

    匹配顺序：先按 `field_label` 精确匹配（用户能在界面上看到的名字），
    再按 `field_key` 匹配（机器名，方便脚本化导入）。

    `samples` 是 `{表头: 该列的非空取值样本}`，用来给**新建**的字段猜类型。
    没有样本（列全是空的）就按文本建——空列猜不出任何东西，
    用户填了值之后可以在表格里改成别的类型。

    ## `key_maker`：新建字段时**用哪个 field_key**

    默认按班生成（`_make_field_key`）——班级版就该各班各的。

    学院版要**所有班共用同一个 key**：学院视图按 `field_key` 把各班的列合并成
    一份，key 不同就合并成两列同名、而值各填各的（改一列另一列不动）。
    所以学院版传一个「按列名记忆」的生成器：同一个列名在所有班拿到同一个 key。
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
            h = _canon_anchor(h)
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
        h = _canon_anchor(h)
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
            field_key=(key_maker(h) if key_maker else _make_field_key(db, class_id, h)),
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


def _read_body(
    rows, headers: list[str]
) -> tuple[list[tuple[int, list[str]]], dict[str, list[str]]]:
    """把数据行读进内存，同时收集每列的非空样本。

    为什么一次性读进内存：新建字段时要按**整列**的取值形态猜类型，
    没法边读行边建字段（第一行还不知道后面有没有混进一个"301"）。
    MAX_ROWS 已经限死了体量（5000 行 × 几十列），一次性读进内存没问题。

    `samples` 每列最多留 200 个非空样本，够判出整列性质了。
    """
    body: list[tuple[int, list[str]]] = []
    samples: dict[str, list[str]] = {}
    processed = 0
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
        for i, h in enumerate(headers):
            v = cells[i].strip()
            if v:
                col = samples.setdefault(h, [])
                if len(col) < 200:
                    col.append(v)
    return body, samples


def _import_rows_into_class(
    db: Session,
    actor: LoginUser,
    class_id: int,
    headers: list[str],
    body: list[tuple[int, list[str]]],
    samples: dict[str, list[str]],
    key_maker: "Callable[[str], str] | None" = None,
) -> dict:
    """把一批行写进**某一个班**。

    返回 `{created, updated, skippedEmptyCells, unmatchedColumns, newFields, errors}`。

    ## 为什么要抽出来

    班级版（`import_xlsx`）和学院版（`college_excel.import_xlsx`）都要用这套
    判据：学号是 upsert 键、空格子不覆盖旧值、没见过的列自动建字段、
    重复学号后一行覆盖前一行。**两份实现必然漂**——而且漂了极难查：
    「班级能导进去的列，学院导不进去」这种差异，用户只会觉得学院功能有 bug。
    所以这里只有一份实现，两个入口都调它。
    """
    col_no = headers.index("学号")
    col_name = headers.index("姓名")

    created = updated = skipped = 0
    errors: list[str] = []

    mapping, unmatched, new_fields = _find_or_create_fields(
        db, class_id, headers, actor, samples, key_maker
    )
    existing: dict[str, StudentRecord] = {}
    for r in db.scalars(select(StudentRecord).where(StudentRecord.class_id == class_id)):
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
                class_id=class_id,
                student_no=student_no,
                name=name,
                user_id=svc.match_user_id(db, class_id, student_no),
            )
            db.add(rec)
            db.flush()
            existing[student_no] = rec
            created += 1
        else:
            # 姓名以本次表格为准，但允许表格里留空时保留旧值
            if name:
                rec.name = name
            rec.user_id = rec.user_id or svc.match_user_id(db, class_id, student_no)
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
        "skippedEmptyCells": skipped,
        "unmatchedColumns": unmatched,
        "newFields": new_fields,
        "errors": errors,
    }


def import_xlsx(db: Session, user: LoginUser, content: bytes) -> dict:
    """导入 xlsx。返回 `{created, updated, skippedEmpty, unmatchedColumns, errors}`。"""
    if not content:
        raise BizException.bad_request("没有读到文件内容")
    try:
        wb = load_workbook(BytesIO(content), data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise BizException.bad_request(f"无法解析 Excel 文件：{exc}") from exc
    ws = wb[wb.sheetnames[0]]
    rows = ws.iter_rows(values_only=True)
    try:
        header_row = next(rows)
    except StopIteration as exc:
        raise BizException.bad_request("表格是空的，至少要有表头和一行数据") from exc

    headers = [_canon_anchor(c) for c in header_row]
    # 学号与姓名是锚点，不走字段值表；模板里必须有，否则无法定位「是哪一行」
    if "学号" not in headers:
        raise BizException.bad_request("表格里必须有「学号」列——它是用来说明这行数据是谁的")
    if "姓名" not in headers:
        raise BizException.bad_request("表格里必须有「姓名」列")

    # 表头匹配也是 SELECT，必须与写入同处一个事务：否则后续 db.begin() 会抛
    # InvalidRequestError（HTTP 500）。本轮在这里踩过一次。
    with db.begin():
        body, samples = _read_body(rows, headers)
        processed = len(body)
        r = _import_rows_into_class(db, user, user.class_id, headers, body, samples)

    errors = r["errors"]
    return {
        "created": r["created"],
        "updated": r["updated"],
        "rows": processed,
        "skippedEmptyCells": r["skippedEmptyCells"],
        "newFields": r["newFields"],
        "duplicateRows": len([e for e in errors if "重复" in e]),
        "unmatchedColumns": r["unmatchedColumns"],
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


# ==================== 导入模板 ====================

#: 「填写说明」页里每种字段类型的说法：类型名 / 示例 / 通用填写规则。
_TYPE_HELP: dict[str, tuple[str, str, str]] = {
    svc.FT_TEXT: ("文本", "张三", "任意文字，最多 255 字"),
    svc.FT_NUMBER: ("数字", "512", "只填数字，不带单位、不带空格"),
    svc.FT_DATE: ("日期", "2026-09-01", "2026-09-01 或 20260901 两种都认"),
    svc.FT_BOOL: ("是/否", "是", "填「是」或「否」"),
}

#: 个别列的补充要求。键是 `field_key`（各班一致），表里没这列就不显示。
FIELD_HINTS: dict[str, str] = {
    "reg_status": "在籍 / 毕业 / 入伍 / 休学 / 退学；其他写法仪表盘会按关键词归类",
    "grade": "如 2026级",
    "enroll_date": "YYYY-MM-DD，也可以直接填 20260901",
}

#: 模板里预先设好单元格格式（文本/日期）的行数。填不满就往下拖，超过也能导——
#: 这些格式只是「别让 Excel 把学号变成 1.2344E+7」的提示，导入仍按值判断。
TEMPLATE_STYLE_ROWS = 200

TEMPLATE_SHEET = "学生信息"
TEMPLATE_HELP_SHEET = "填写说明"


def build_template_xlsx(
    headers: list[dict],
    *,
    title: str,
    intro: list[str],
    filename: str,
) -> tuple[bytes, str]:
    """生成「填完能直接导」的模板。

    ## 列必须**从当前字段现生成**，不能放一张固定的空表

    字段是**按班**定义的，而且用户随时会新增/停用列。模板要是写死的，
    照着它填完导进来就会多出几列（或漏掉几列）——用户就再也不敢用模板了。
    每次下载都读一遍 `student_field`，新增字段后重新下载即可。

    ## 表头就在**第 1 行**

    导出文件有标题行、表头在第 3 行；模板**不能**这样：导入读的是第一行表头，
    隔两行就得先手工删。模板唯一的用途是填完直接传回来。

    ## 第 2 页是填写说明

    导入只读第一张表，说明放第二张——填错位置也不会被当成数据导进去。
    """
    wb = Workbook()
    ws = wb.active
    ws.title = TEMPLATE_SHEET

    for i, h in enumerate(headers, start=1):
        c = ws.cell(row=1, column=i, value=h["label"])
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        ws.column_dimensions[get_column_letter(i)].width = max(
            12, min(28, len(h["label"]) * 2 + 6)
        )
        fmt = h.get("format")
        if fmt:
            for r in range(2, TEMPLATE_STYLE_ROWS + 2):
                ws.cell(row=r, column=i).number_format = fmt
    ws.row_dimensions[1].height = 22
    # 冻结表头 + 前两列（学号/姓名），往下填的时候始终知道是谁
    ws.freeze_panes = "C2"

    hs = wb.create_sheet(TEMPLATE_HELP_SHEET)
    hs["A1"] = title
    hs["A1"].font = _TITLE_FONT
    row = 3
    for line in intro:
        hs.cell(row=row, column=1, value=line).font = Font(size=10, color="555555")
        row += 1

    row += 1
    head_row = row
    for i, name in enumerate(("列名", "类型", "填写要求", "示例"), start=1):
        c = hs.cell(row=head_row, column=i, value=name)
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.alignment = Alignment(horizontal="center")
    for h in headers:
        row += 1
        type_text, type_example, type_rule = _TYPE_HELP.get(
            h.get("type") or "", ("文本", "", "任意文字")
        )
        hs.cell(row=row, column=1, value=h["label"])
        hs.cell(row=row, column=2, value=type_text)
        # 列的专门要求优先；没有就写这个类型的通用规则
        hs.cell(row=row, column=3, value=h.get("hint") or type_rule)
        hs.cell(row=row, column=4, value=h.get("example") or type_example)
    for col, width in zip("ABCD", (18, 10, 56, 18), strict=False):
        hs.column_dimensions[col].width = width

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), filename


def template_xlsx(db: Session, user: LoginUser) -> tuple[bytes, str]:
    """班级「学生信息」的导入模板：列 = **本班当前启用的字段**。

    权限在路由层判（能导入的人才能拿模板）：模板里只有列名，
    没有学生数据，但给普通同学一个「导入模板」也没有意义。
    """
    fields = svc.list_fields(db, user)
    headers: list[dict] = [
        {
            "label": "学号",
            "type": svc.FT_TEXT,
            "format": "@",  # 文本格式：否则 Excel 会把 0012345 吃成 12345
            "required": True,
            "example": "12344312",
            "hint": "必填，同一张表里不要重复。库里已有这个学号就更新那一行",
        },
        {
            "label": "姓名",
            "type": svc.FT_TEXT,
            "format": "@",
            "required": True,
            "example": "张三",
            "hint": "必填",
        },
    ]
    headers += [
        {
            "label": f["label"],
            "type": f["type"],
            # 日期列给日期格式，填「2026-09-01」不会被当成文本左对齐
            "format": "yyyy-mm-dd" if f["type"] == svc.FT_DATE else None,
            "hint": FIELD_HINTS.get(f["key"], ""),
        }
        for f in fields
    ]
    return build_template_xlsx(
        headers,
        title="学生信息 · 导入模板",
        intro=[
            "填完直接把这个文件传回「学生信息 → 导入 Excel」，表头不用改。",
            "表头可以调顺序，但不要改列名：导入是按列名找列的。",
            "空着的格子不会覆盖库里已有的值（只更新填了的格子）。",
            "列跟本班当前的字段一致；新增或停用字段后，重新下载一次就是新的列。",
        ],
        filename=f"学生信息导入模板_{datetime.now():%Y%m%d}.xlsx",
    )