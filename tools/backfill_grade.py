# -*- coding: utf-8 -*-
"""把学生名单里的「年级」回填到班级上（一次性维护脚本，可重复跑）。

## 为什么要单独跑

第五十八轮之前，学院导入只给**新建**的班写年级：班要是早就建好了（上一次
导入没带「年级」列，或者院长手建的），年级永远是空的——「班主任名册」上
那一列就全是「—」。代码已经改成「导入时补空的」，但**已经导进去的那批班
不会自己变**，这个脚本就是给它们补一次。

## 判定规则

1. 只看 `cls_class.grade` **为空**的班（已有年级的不覆盖——那可能是用户在
   「班级信息」里手工写的）；
2. 取这个班学生「年级」字段里**出现次数最多**的非空值；
3. `2024` 这种纯年份补成 `2024级`（和存量班的写法一致）。

用法（在 `server-py` 下）：

    .venv\\Scripts\\python.exe -X utf8 ..\\tools\\backfill_grade.py --dry-run
    .venv\\Scripts\\python.exe -X utf8 ..\\tools\\backfill_grade.py
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1] / "server-py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from app.db import engine  # noqa: E402


def norm_grade(v: str) -> str:
    """`2024` → `2024级`（和后端 `college_excel._norm_grade` 同一口径）。"""
    s = (v or "").strip()
    if len(s) == 4 and s.isdigit():
        s = f"{s}级"
    return s[:32]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="只看会改哪些，不写库")
    args = ap.parse_args()

    with engine.begin() as c:
        rows = c.execute(text(
            """
            SELECT clazz.id, clazz.class_name, v.value_text, COUNT(*) AS n
            FROM cls_class clazz
            JOIN student_record sr ON sr.class_id = clazz.id
            JOIN student_field f
                 ON f.class_id = clazz.id AND f.field_key = 'grade' AND f.status = 1
            JOIN student_record_value v ON v.record_id = sr.id AND v.field_id = f.id
            WHERE clazz.status = 1 AND TRIM(COALESCE(clazz.grade, '')) = ''
              AND TRIM(COALESCE(v.value_text, '')) <> ''
            GROUP BY clazz.id, clazz.class_name, v.value_text
            """
        )).fetchall()

        by_class: dict[int, tuple[str, Counter]] = {}
        for cid, name, value, n in rows:
            cnt = by_class.setdefault(int(cid), (name, Counter()))[1]
            cnt[str(value)] += int(n)

        filled = 0
        for cid, (name, cnt) in sorted(by_class.items()):
            value, votes = cnt.most_common(1)[0]
            grade = norm_grade(value)
            print(f"{name:<16} 年级（空）-> {grade}  （{votes} 人，候选 {dict(cnt)}）")
            if not args.dry_run:
                c.execute(
                    text("UPDATE cls_class SET grade = :g WHERE id = :i"),
                    {"g": grade, "i": cid},
                )
            filled += 1

        print(f"\n{'[dry-run] 会补' if args.dry_run else '已补'} {filled} 个班")
        if not filled:
            print("没有需要补的班（年级都已有值，或班里没有「年级」字段的数据）。")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
