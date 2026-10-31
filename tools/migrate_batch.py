# -*- coding: utf-8 -*-
"""按批次迁移班费系统数据（每批 50–100 条）。

为什么分批
----------
一次性 `SELECT *` 全表再全量写入，两个坑：

1. 内存：学生字段值表有上万行，全拉进来就是几 MB → 几百 MB；
2. 事务：一个长事务把整批锁住，中途失败要从头回滚，而且看不出进度。

按 id 升序、每批 N 条（默认 50），每批一个短事务，跑完打印进度。
中途崩了只要从上次成功的批继续（`--from-id`）。

怎么用
------
    # 1) 先看看要搬多少（不写任何数据）
    python migrate_batch.py --dry-run

    # 2) 正式搬，默认每批 50 条
    python migrate_batch.py --batch 50

    # 3) 只搬指定表 / 换批量大小 / 从某个 id 继续
    python migrate_batch.py --tables cls_class,sys_user --batch 100
    python migrate_batch.py --from-id 1000

连接信息默认读仓库根的 `.env`（和后端同一套）：
    源库 SOURCE_DB_URL，目标库 TARGET_DB_URL，
    形如 mysql+pymysql://user:pass@host:3306/classfee?charset=utf8mb4
不填 TARGET_DB_URL = 搬到同一张库（幂等上覆盖，用来做「重刷」）。
"""
from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time
from decimal import Decimal

REPO = pathlib.Path(__file__).resolve().parents[1]

#: 搬运顺序 = 表之间的逻辑依赖。这个库**没有外键**，顺序只为了「先有班再有人，
#: 先有记录再有字段值」这种语义上的可读性；顺序错了也不会报错，但数据会看不懂。
TABLE_ORDER = [
    "cls_class",
    "sys_user",
    "sys_user_class",
    "student_field",
    "student_record",
    "student_record_value",
    "fee_category",
    "fee_batch",
    "fee_record",
    "fee_payment",
    "cls_task",
    "cls_task_answer",
    "cls_task_student_answer",
]

DEFAULT_BATCH = 50
MAX_BATCH = 100


def load_env() -> dict:
    """读仓库根 `.env`（和后端同一份配置）。"""
    out: dict[str, str] = {}
    p = REPO / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def connect(url: str):
    """按 URL 建连接。用 SQLAlchemy 的 URL 解析 + 原生 pymysql 连接。"""
    from sqlalchemy import make_url
    from sqlalchemy.engine import Connection

    u = make_url(url)
    import pymysql

    conn = pymysql.connect(
        host=u.host or "127.0.0.1",
        port=u.port or 3306,
        user=u.username,
        password=u.password or "",
        database=u.database,
        charset="utf8mb4",
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor,
    )
    return conn


def columns(cur, table: str) -> list[str]:
    cur.execute(f"SHOW COLUMNS FROM `{table}`")
    return [r["Field"] for r in cur.fetchall()]


def iter_batches(cur, table: str, cols: list[str], size: int, from_id: int):
    """按主键 id 升序，每批 `size` 条。主键统一叫 `id`。"""
    last = from_id
    while True:
        cur.execute(
            f"SELECT * FROM `{table}` WHERE id > %s ORDER BY id ASC LIMIT %s",
            (last, size),
        )
        rows = cur.fetchall()
        if not rows:
            return
        last = rows[-1]["id"]
        yield rows


def dump_value(v):
    """把 Decimal/日期这些原生类型转成可序列化值，交给目标端自己处理。"""
    if isinstance(v, Decimal):
        return float(v)
    return v


def migrate_table(src_cur, dst_cur, table: str, cols: list[str], size: int,
                  from_id: int, dry_run: bool) -> int:
    """搬一张表，返回真正处理的行数。"""
    total = 0
    batch_no = 0
    placeholders = ", ".join(["%s"] * len(cols))
    col_list = ", ".join(f"`{c}`" for c in cols)
    # 目标端存在同 id 就覆盖（幂等），不存在才插入——中途失败重跑不会报主键冲突
    upsert = (
        f"INSERT INTO `{table}` ({col_list}) VALUES ({placeholders}) "
        f"ON DUPLICATE KEY UPDATE " + ", ".join(
            f"`{c}` = VALUES(`{c}`)" for c in cols if c != "id"
        )
    )
    for rows in iter_batches(src_cur, table, cols, size, from_id):
        batch_no += 1
        values = [
            tuple(dump_value(row[c]) for c in cols) for row in rows
        ]
        if dry_run:
            print(f"  [{table}] 第 {batch_no} 批：{len(rows)} 条（dry-run，未写）")
        else:
            dst_cur.executemany(upsert, values)
            dst_cur.connection.commit()
            print(f"  [{table}] 第 {batch_no} 批：{len(rows)} 条 ✓")
        total += len(rows)
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description="按批次迁移班费系统数据")
    ap.add_argument("--batch", type=int, default=DEFAULT_BATCH,
                    help=f"每批条数（默认 {DEFAULT_BATCH}，最大 {MAX_BATCH}）")
    ap.add_argument("--tables", default="",
                    help="只搬这些表，逗号分隔；留空 = 全部")
    ap.add_argument("--from-id", type=int, default=0,
                    help="从哪个 id 继续（中断后续跑用）")
    ap.add_argument("--dry-run", action="store_true", help="只统计不写")
    args = ap.parse_args()

    size = max(1, min(MAX_BATCH, args.batch))
    env = load_env()
    src_url = os.environ.get("SOURCE_DB_URL") or env.get(
        "CLASSFEE_DB_URL") or "mysql+pymysql://localhost:3306/classfee?charset=utf8mb4"
    dst_url = os.environ.get("TARGET_DB_URL") or src_url

    tables = [t.strip() for t in args.tables.split(",") if t.strip()] or TABLE_ORDER
    unknown = [t for t in tables if t not in TABLE_ORDER]
    if unknown:
        print(f"未知表：{unknown}（可选：{TABLE_ORDER}）")
        return 2

    print("=" * 72)
    print(f"每批 {size} 条 | 源：{src_url.split('@')[-1]}")
    print(f"目标：{dst_url.split('@')[-1]}" + ("（= 源库，重刷）" if dst_url == src_url else ""))
    print("=" * 72)

    src = connect(src_url)
    dst = connect(dst_url)
    started = time.time()
    grand = 0
    try:
        with src.cursor() as sc, dst.cursor() as dc:
            for table in tables:
                sc.execute(f"SELECT COUNT(*) AS n FROM `{table}`")
                n = int(sc.fetchone()["n"])
                print(f"\n{table}：共 {n} 行")
                if n == 0:
                    continue
                cols = columns(sc, table)
                grand += migrate_table(sc, dc, table, cols, size,
                                       args.from_id, args.dry_run)
    finally:
        src.close()
        dst.close()
    print("\n" + "=" * 72)
    print(f"完成：{grand} 行，用时 {time.time() - started:.1f}s"
          + ("（dry-run，未写任何数据）" if args.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
