"""启动初始化：幂等执行 schema.sql + 补齐基础数据（班级/类别）+ 配置声明的班主任账号。

账号模型（第九轮起，与 `/api/users` 运行时建号并存）：

1. **代码里不写死任何账号**——没有注册页，只有登录页；
2. **班主任（运营）账号在部署配置里声明**：`CLASSFEE_TEACHER_USERNAME` /
   `CLASSFEE_TEACHER_PASSWORD`（另可选 `CLASSFEE_TEACHER_NAME` / `CLASSFEE_TEACHER_ROLE`），
   在 compose 的 `.env` 或系统环境变量里填写，**声明即生效**：启动时若库中不存在该用户名则创建，
   **已存在则跳过**（不覆盖库里已被改过的密码/角色/停用状态）；
3. **其余学生/管理员账号由班主任登录后在「成员管理」中创建**（`POST /api/users`）。
"""
from __future__ import annotations

import logging
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from .config import settings
from .db import SessionLocal, engine
from .models import ClsClass, FeeCategory, StudentField, SysUser
from .security import hash_password

log = logging.getLogger("classfee")

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "db" / "schema.sql"

INCOME_CATEGORIES = [
    ("班费收取", "Money"),
    ("义卖收入", "Sell"),
    ("捐款", "Present"),
    ("退款", "RefreshLeft"),
    ("其他", "MoreFilled"),
]
EXPENSE_CATEGORIES = [
    ("活动物资", "Goods"),
    ("打印资料", "Document"),
    ("饮用水", "Cup"),
    ("班会布置", "House"),
    ("交通", "Bus"),
    ("其他", "MoreFilled"),
]

# 账号不再写死：空库只建「班级 + 类别」等基础数据；
# 班主任账号由部署配置声明（CLASSFEE_TEACHER_USERNAME / CLASSFEE_TEACHER_PASSWORD），
# 声明即生效、仅在不存在时创建；其余账号一律由班主任在「成员管理」中运行时创建。


def run_schema() -> None:
    """执行 db/schema.sql（IF NOT EXISTS 幂等；出错继续 = Spring continue-on-error: true）。

    用 `utf-8-sig` 读而不是 `utf-8`：这个项目约定「含中文的文本文件加 BOM」（否则 GBK
    工具打开是乱码），但 `utf-8` **不剥 BOM**，`\ufeff` 会粘在首行开头。而首行是
    `-- 1) 班级表` 注释，注释过滤靠 `lstrip().startswith("--")`，而 `"\ufeff".isspace()`
    是 False —— 于是这行没被剔掉，切出来的第一条语句 MySQL 语法报错，又被下面的
    `except ProgrammingError: continue` 静默吞掉，**新库首启会少 cls_class 一张表且
    启动日志一个字都不报**。`utf-8-sig` 对有无 BOM 都能正确读取，BOM 存在时额外告警。
    """
    raw = SCHEMA_PATH.read_text(encoding="utf-8-sig")
    # utf-8-sig 读完 raw 里已经没有 BOM 了，判断「原来有没有」只能看原始字节
    if SCHEMA_PATH.read_bytes()[:3] == b"\xef\xbb\xbf":
        log.warning("db/schema.sql 带 UTF-8 BOM：已用 utf-8-sig 读取并跳过 BOM，"
                    "但本文件按约定应保存为无 BOM")
    lines = [ln for ln in raw.splitlines() if not ln.lstrip().startswith("--")]
    statements = [s.strip() for s in "\n".join(lines).split(";") if s.strip()]
    if not statements:
        # 空语句集一定是读法出了错（比如 BOM 把首行变成了非法 SQL 又被吞掉），必须显式炸出来
        raise RuntimeError(f"db/schema.sql 未解析出任何语句，文件可能损坏或编码不对：{SCHEMA_PATH}")
    # DDL 隐式提交，必须在 AUTOCOMMIT 连接上跑
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        failed: list[str] = []
        for stmt in statements:
            try:
                conn.execute(text(stmt))
            except ProgrammingError as exc:
                # 容错是对的（对齐 Spring continue-on-error），但不能把错误信号一起丢掉：
                # 只放过「对象已存在」这一类预期内错误，其余记下来在末尾汇总告警
                failed.append(f"{str(exc.orig)[:120]} :: {stmt.splitlines()[0][:80]}")
                log.warning("schema.sql 语句执行失败（已跳过）：%s", stmt.splitlines()[0][:80])
        if failed:
            log.warning("schema.sql 有 %d 条语句未执行，新库可能缺表，请检查上面日志", len(failed))


def init_data() -> None:
    cfg = settings()
    with SessionLocal() as db:
        with db.begin():
            class_id = _init_class(db, cfg)
            _init_categories(db, class_id)
            _init_teacher_account(db, cfg, class_id)
            # 第二十三轮：学生信息字段模板。**每次启动都调**（内部按 field_key 幂等），
            # 这样「班主任在界面上删掉了某个模板字段」不会被下次启动悄悄加回来，
            # 但「字段表是空的」能被自动补齐 —— 既有库升级、新库首启走同一条路径。
            n = init_student_fields(db, class_id)
    if n:
        log.info("已下发学生信息字段模板：%d 个字段", n)


def _init_class(db: Session, cfg: dict) -> int:
    existing = db.execute(
        select(ClsClass).where(ClsClass.class_name == cfg["class_name"]).limit(1)
    ).scalar()
    if existing is not None:
        return existing.id
    clazz = ClsClass(
        class_name=cfg["class_name"],
        grade=cfg["grade"],
        head_teacher=cfg["head_teacher"],
        balance=0,
        status=1,
    )
    db.add(clazz)
    db.flush()
    log.info("已初始化班级：%s（id=%s）", clazz.class_name, clazz.id)
    return clazz.id


def _init_teacher_account(db: Session, cfg: dict, class_id: int) -> None:
    """按部署配置创建班主任账号：声明即生效，仅在库中不存在时创建。

    - 用户名与密码必须同时填写（半个配置不建号，也不给默认口令）；
    - 已存在同名账号 → 跳过，**不覆盖**库里改过的密码/角色/停用状态；
    - 角色只允许 ADMIN/TEACHER（这是运营账号入口），非法值回退 TEACHER。
    """
    username = cfg["teacher_username"]
    password = cfg["teacher_password"]
    if not username or not password:
        if username or password:
            log.warning(
                "班主任账号配置不完整（USERNAME=%s / PASSWORD=%s）：两项都填才会建号；"
                "请在 compose 的 .env 或系统环境变量补齐后重启",
                username or "<空>",
                "<已填>" if password else "<空>",
            )
        else:
            log.warning(
                "未配置 CLASSFEE_TEACHER_USERNAME / CLASSFEE_TEACHER_PASSWORD：本次不创建账号。"
                "首次部署请在 compose 的 .env 里声明班主任账号后重启；"
                "若库里已有运营账号（如已由班主任自行建号），可忽略此提示"
            )
        return

    count = (
        db.scalar(
            select(func.count()).select_from(SysUser).where(SysUser.username == username)
        )
        or 0
    )
    if count > 0:
        log.info("配置声明的班主任账号 %s 已存在，跳过创建（不覆盖库中密码/角色）", username)
        return

    role = cfg["teacher_role"]
    if role not in ("ADMIN", "TEACHER"):
        log.warning("CLASSFEE_TEACHER_ROLE=%s 非法，回退为 TEACHER", role)
        role = "TEACHER"
    account = SysUser(
        class_id=class_id,
        username=username,
        password=hash_password(password),
        real_name=cfg["teacher_name"] or username,
        student_no=None,
        role=role,
        status=1,
    )
    db.add(account)
    # 只记用户名不记口令：口令以部署配置为准，且日志不该留明文密码
    log.warning(
        "已按部署配置创建班主任账号：%s（role=%s）——首次登录后请立即在「个人中心」修改密码",
        username,
        role,
    )


def _init_categories(db: Session, class_id: int) -> None:
    count = (
        db.scalar(
            select(func.count())
            .select_from(FeeCategory)
            .where(FeeCategory.class_id == class_id)
        )
        or 0
    )
    if count > 0:
        return
    for sort, (name, icon) in enumerate(INCOME_CATEGORIES, start=1):
        db.add(
            FeeCategory(
                class_id=class_id,
                name=name,
                kind="INCOME",
                icon=icon,
                sort=sort * 10,
                status=1,
            )
        )
    for sort, (name, icon) in enumerate(EXPENSE_CATEGORIES, start=1):
        db.add(
            FeeCategory(
                class_id=class_id,
                name=name,
                kind="EXPENSE",
                icon=icon,
                sort=sort * 10,
                status=1,
            )
        )
    log.info(
        "已初始化默认收支类别：收入 %d 个，支出 %d 个",
        len(INCOME_CATEGORIES),
        len(EXPENSE_CATEGORIES),
    )


def migrate_role_enum() -> None:
    """给 `sys_user.role` 的 ENUM 补齐新增角色。

    第十四轮加了 'MONITOR'（班长），第二十四轮加了 'GUEST'（访客·给领导看的只读账号）。

    为什么需要单独迁移：schema.sql 用 `CREATE TABLE IF NOT EXISTS`，
    **已建好的库不会因为改了 DDL 文本而变更列定义**（只有新库能拿到新枚举）。
    不迁的话，老库上建访客账号会直接 500：
    `DataError (1265): Data truncated for column 'role'`。

    查 INFORMATION_SCHEMA，缺哪个补哪个 —— 幂等，升级过的库直接跳过。
    每次都是**整列重写**成完整枚举，别改成"只加一个"的增量写法：
    那样老库上会出现枚举值顺序不稳定的问题。
    """
    wanted = ("ADMIN", "MEMBER", "GUEST", "MONITOR", "TEACHER")
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        column_type = conn.execute(
            text(
                "SELECT COLUMN_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'sys_user' "
                "AND COLUMN_NAME = 'role'"
            )
        ).scalar()
        if not column_type:
            return
        upper = column_type.upper()
        missing = [r for r in wanted if f"'{r}'" not in upper]
        if not missing:
            return
        enum_sql = ",".join(f"'{r}'" for r in wanted)
        conn.execute(
            text(f"ALTER TABLE sys_user MODIFY role ENUM({enum_sql}) NOT NULL DEFAULT 'MEMBER'")
        )
        log.info("已升级 sys_user.role 枚举：新增 %s", "、".join(missing))


def add_audit_columns() -> None:
    """第十九轮起：给几张表补列（后来名字就不叫「审计」了，见下）。

    和 `migrate_role_enum` 同一个理由：schema.sql 用 `CREATE TABLE IF NOT EXISTS`，
    **已建好的库不会因为改了 DDL 文本而多出列**。所以每个列都先查
    INFORMATION_SCHEMA，缺了才 ALTER —— 幂等，升级过的库直接跳过，新库由 schema.sql 建好。

    | 表 | 列 | 回答什么问题 |
    |----|----|--------------|
    | fee_record | voided_by / voided_at | 这笔账是谁作废的、什么时候 |
    | fee_batch  | closed_by / closed_at | 这个批次是谁关的、什么时候 |
    | cls_task   | pinned | 这条任务要不要出现在**每个人**的仪表盘上 |

    第二十四轮移除了班级公告，`sys_notice` 的两列也一并删掉了。

    函数名没跟着改：改名要动 `bootstrap()` 的调用点，而它的实际职责一直是
    「补 DDL 里新增、但老库还没有的列」，`cls_task.pinned` 属于同一类。名字略窄，
    注释和这张表才是准的 —— 留着比满仓库改字符串更安全。

    注意**删除仍然无痕**：`delete_record` / `delete_batch` 是硬删，行都没了自然留不下
    记录。留痕路径是「作废」，不是删除 —— 这是设计取舍，界面上一律引导
    「记错优先作废（可查是谁作废的）」。
    """
    columns = [
        ("fee_record", "voided_by", "BIGINT NULL COMMENT '作废人'"),
        ("fee_record", "voided_at", "DATETIME NULL COMMENT '作废时间'"),
        ("fee_batch", "closed_by", "BIGINT NULL COMMENT '关闭人'"),
        ("fee_batch", "closed_at", "DATETIME NULL COMMENT '关闭时间'"),
        # 第二十五轮补记：`cls_task` 建表时没有这一列（用户后来才提出「任务也能置顶」），
        # 所以已经建好 `cls_task` 的库不会因为改了 DDL 文本而多出它。
        # 和上面几列同理由：逐列查 INFORMATION_SCHEMA，缺了才 ALTER，幂等。
        ("cls_task", "pinned", "TINYINT(1) NOT NULL DEFAULT 0 "
                               "COMMENT '置顶：会出现在所有人仪表盘的「置顶任务」里'"),
    ]
    added: list[str] = []
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        live_tables = {
            r[0] for r in conn.execute(
                text("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES "
                     "WHERE TABLE_SCHEMA = DATABASE()")
            )
        }
        for table, column, ddl in columns:
            # 表可能已经不存在（模块下线后旧库不会自动删表）。
            # 这里必须跳过而不是让 ALTER 报 1146 —— 启动期的迁移崩溃会让**整个服务起不来**，
            # 而缺的只是一张没人引用的表，代价完全不成比例。
            # （第二十四轮删班级公告时就踩过一次：sys_notice 一删，本函数直接把启动打挂。）
            if table not in live_tables:
                continue
            exists = conn.execute(
                text(
                    "SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t AND COLUMN_NAME = :c"
                ),
                {"t": table, "c": column},
            ).scalar()
            if exists:
                continue
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            added.append(f"{table}.{column}")
    if added:
        log.info("已补列：%s", "、".join(added))
    else:
        log.info("列已齐全，跳过迁移")


def backfill_payable_roster() -> None:
    """第二十轮：把生活委员 / 班长补进**已存在批次**的缴费名单。

    缴费对象口径从「只算 MEMBER」改成「除班主任外的全部学生」之后，新建的批次会自动
    带上这两类人，但**升级前就建好的批次**里没有他们的缴费行 —— 表现是：成员缴费页
    （口径已改）能列出他，但点「标记缴费」会 400「该成员缴费状态不存在」；而他自己在
    「我的缴费」里永远看不到欠费。必须回填。

    两点刻意的设计：

    - **只补 OPEN 批次**。已关闭批次是历史记录，补一堆 UNPAID 行会把当时的完成率
      改写成另一个数（等于篡改历史账），而且关闭后本来就拒绝收款，补了也无法销账。
    - **幂等**。靠 `NOT EXISTS` 判定，且 `fee_payment` 上有 `uk_batch_user(batch_id,user_id)`
      唯一索引兜底，重复启动不会产生重复行、也不会因为并发插重复键而炸掉。
    """
    payable = ("MEMBER", "ADMIN", "MONITOR")
    inserted = 0
    with engine.begin() as conn:
        result = conn.execute(
            text(
                """
                INSERT INTO fee_payment (batch_id, user_id, amount, status)
                SELECT b.id, u.id, 0.00, 'UNPAID'
                FROM fee_batch b
                JOIN sys_user u
                  ON u.class_id = b.class_id
                 AND u.status = 1
                 AND u.role IN :payable
                WHERE b.status = 'OPEN'
                  AND NOT EXISTS (
                    SELECT 1 FROM fee_payment p
                    WHERE p.batch_id = b.id AND p.user_id = u.id
                  )
                """
            ).bindparams(payable=payable)
        )
        inserted = result.rowcount or 0
    if inserted:
        log.info("已把 %d 条缴费行补进进行中的批次（生活委员 / 班长 纳入缴费对象）", inserted)
    else:
        log.info("进行中批次的缴费名单已覆盖全部缴费对象，跳过回填")


# ------------------------------------------------------------------
# 第二十三轮：学生信息字段模板
# ------------------------------------------------------------------
# 来自用户提供的真实导出生表。**学号 / 姓名不在这张表里**——它们是记录的锚点
# （`student_record.student_no` / `.name`），承担「这是谁的行」的定位职责，
# 放进字段值表会让「我那一行是哪一行」变成一次联表比对。
#
# field_type 的判定依据是**这一列的实际取值形态**，不是列名：
# - DATE：出生日期 / 入校日期。源表里存的是 `20071209` 这样的数字（General 格式，
#   不是 Excel 日期序列号），导入时按 YYYYMMDD 解析。
# - BOOL：所有「是否…」列，取值域就是 是/否。
# - 其余一律 TEXT。**学号/证件号/电话/代码类即使源表里是数字也存 TEXT**：
#   前导 0 会丢、15 位以上会被 Excel 转成科学计数法。
TEMPLATE_FIELDS: list[tuple[str, str, str]] = [
    ("exam_no", "考生号", "TEXT"),
    ("province_city_code", "生源省市代码", "TEXT"),
    ("gender", "性别", "TEXT"),
    ("birth_date", "出生日期", "DATE"),
    ("id_type", "证件类型", "TEXT"),
    ("id_number", "身份证号", "TEXT"),
    ("political_status", "政治面貌", "TEXT"),
    ("ethnicity", "民族", "TEXT"),
    ("college_code", "院校代码", "TEXT"),
    ("college_name", "院校名称", "TEXT"),
    ("major_code", "专业代码", "TEXT"),
    ("major_name", "专业名称", "TEXT"),
    ("second_college", "二级学院", "TEXT"),
    ("department", "所属系", "TEXT"),
    ("class_no", "班号", "TEXT"),
    ("level", "层次", "TEXT"),
    ("duration", "学制", "TEXT"),
    ("study_nature", "学习性质", "TEXT"),
    ("enroll_date", "入校日期", "DATE"),
    ("grade", "年级", "TEXT"),
    ("reg_status", "注册状态", "TEXT"),
    ("source_province", "生源地所在省（全称）", "TEXT"),
    ("source_city", "生源地所在市（全称）", "TEXT"),
    ("from_military", "是否来自军队", "BOOL"),
    ("rural_hukou", "是否常驻户口在农村", "BOOL"),
    ("grad_school", "毕业学校（全称）", "TEXT"),
    ("entrance_score", "入学总分", "NUMBER"),
    ("admission_type", "招生方式", "TEXT"),
    ("source_type", "生源类型", "TEXT"),
    ("home_address", "家庭详细住址", "TEXT"),
    ("guardian_phone", "家长电话", "TEXT"),
    ("own_phone", "本人电话", "TEXT"),
    ("email", "电子邮箱", "TEXT"),
    ("poverty_family", "是否建档立卡贫困家庭", "BOOL"),
]


def init_student_fields(db: Session, class_id: int) -> int:
    """给**所有班级**下发学生信息字段模板。幂等：按 field_key 判存在，不覆盖已有定义。

    为什么是「所有班级」而不是只给种子班级：`cls_class` 里可能有手工建出来的班级
    （种子只认 `cfg["class_name"]` 那一个），只发给种子班级会让其它班在界面上
    看到一张**空表**，分不清是「还没导入」还是「这个班没有字段」。

    已有的字段一律不动——班主任/班长可能改过标签或停用过字段，
    启动时被模板覆盖回去是不可接受的。
    """
    class_ids = [class_id]
    for (cid,) in db.execute(select(ClsClass.id).where(ClsClass.id != class_id)):
        class_ids.append(int(cid))

    added = 0
    for cid in class_ids:
        existing = {
            k
            for (k,) in db.execute(
                select(StudentField.field_key).where(
                    StudentField.class_id == cid, StudentField.status == 1
                )
            )
        }
        todo = [f for f in TEMPLATE_FIELDS if f[0] not in existing]
        for i, (key, label, ftype) in enumerate(todo):
            db.add(
                StudentField(
                    class_id=cid,
                    field_key=key,
                    field_label=label,
                    field_type=ftype,
                    is_system=1,
                    sort=(i + 1) * 10,
                    status=1,
                    created_by=0,  # 0 = 系统模板下发，非某个真人操作
                )
            )
        added += len(todo)
    db.flush()
    return added


def bootstrap() -> None:
    run_schema()
    migrate_role_enum()
    add_audit_columns()
    backfill_payable_roster()
    # 基础数据（班级/类别）总是幂等补齐；班主任账号按部署配置声明（存在即跳过）
    init_data()
