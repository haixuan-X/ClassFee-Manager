"""SQLAlchemy 模型：与 server/src/main/resources/db/schema.sql 一一对应（只用于 DML，DDL 由 schema.sql 负责）。"""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, Float, Integer, Numeric, String, Text, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class ClsClass(Base):
    __tablename__ = "cls_class"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_name: Mapped[str] = mapped_column(String(50))
    grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    head_teacher: Mapped[str | None] = mapped_column(String(50), nullable=True)
    balance: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0.00"))
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )


class SysUser(Base):
    __tablename__ = "sys_user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    username: Mapped[str] = mapped_column(String(32))
    password: Mapped[str] = mapped_column(String(100))
    real_name: Mapped[str] = mapped_column(String(32))
    student_no: Mapped[str | None] = mapped_column(String(20), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="MEMBER")
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[int] = mapped_column(Integer, default=1)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )


class FeeCategory(Base):
    __tablename__ = "fee_category"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(30))
    kind: Mapped[str] = mapped_column(String(16))
    icon: Mapped[str | None] = mapped_column(String(50), nullable=True)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[int] = mapped_column(Integer, default=1)


class FeeRecord(Base):
    __tablename__ = "fee_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    type: Mapped[str] = mapped_column(String(8))
    category_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    title: Mapped[str] = mapped_column(String(60))
    occurred_at: Mapped[datetime] = mapped_column(DateTime)
    channel: Mapped[str] = mapped_column(String(16), default="CASH")
    payer_user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    batch_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    receipt_url: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="NORMAL")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    # 第十九轮审计：作废留痕（谁、何时）。删除是硬删、无痕 —— 要留痕请用「作废」
    voided_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    voided_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FeeBatch(Base):
    __tablename__ = "fee_batch"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(60))
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2))
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(8), default="OPEN")
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    # 第十九轮审计：关闭是实质动作（关完不能收款），记谁关的、什么时候
    closed_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class FeePayment(Base):
    __tablename__ = "fee_payment"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    amount: Mapped[Decimal] = mapped_column(Numeric(10, 2), default=Decimal("0.00"))
    status: Mapped[str] = mapped_column(String(8), default="UNPAID")
    channel: Mapped[str | None] = mapped_column(String(16), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    record_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )


# 第二十四轮：班级公告已整体移除，SysNotice 模型与 sys_notice 表一并删除。
# 存量库里那张表会留下但**没有任何代码引用**，确认不需要历史公告后可手工 DROP。


# ==================== 第二十三轮：学生信息登记 ====================
# 字段定义与字段值全部落库：加字段是**数据操作**，不是改代码/改表。


class StudentField(Base):
    """字段定义：一列 = 一行。`field_key` 机器名稳定，改 `field_label` 不影响历史数据。"""

    __tablename__ = "student_field"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    field_key: Mapped[str] = mapped_column(String(64))
    field_label: Mapped[str] = mapped_column(String(64))
    field_type: Mapped[str] = mapped_column(String(8), default="TEXT")
    is_system: Mapped[int] = mapped_column(Integer, default=0)
    # 列序。用浮点是为了「插在两列中间」能取中点而不必重排后续所有列
    # （DDL 里是 INT，能装下；SQLAlchemy 侧要用 Float 匹配，否则回读会被截断成整数）
    sort: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )


class StudentRecord(Base):
    """学生记录：一行一人，**学号是锚点**（Excel 导入的 upsert 键）。

    学号/姓名刻意不放进字段值表：它们要承担「这是谁的行」的定位职责。
    `user_id` 是**可选**关联——导入名单不等于创建可登录账号。
    """

    __tablename__ = "student_record"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    student_no: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(32))
    user_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )


class StudentRecordValue(Base):
    """字段值（EAV）。值统一按文本存，读写时按 `field_type` 解析/格式化。

    选 EAV 而不是 JSON 列的两个理由：
    1. 字段集合会变（加字段是常态），JSON 改一次结构就要迁移全表；
    2. EAV 能对单字段建索引，将来「按学号/身份证号去重」不必全表扫。
    """

    __tablename__ = "student_record_value"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    record_id: Mapped[int] = mapped_column(Integer)
    field_id: Mapped[int] = mapped_column(Integer)
    value_text: Mapped[str | None] = mapped_column(String(255), nullable=True)


class StudentAccessRequest(Base):
    """访问申请（流水）：班长/同学默认只看得到自己那一行，要看全部/要改必须申请。"""

    __tablename__ = "student_access_request"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    status: Mapped[str] = mapped_column(String(12), default="PENDING")
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
    handled_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    handled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reply: Mapped[str | None] = mapped_column(String(255), nullable=True)


class StudentGrant(Base):
    """已授权（当前状态）：审批通过的结果。与「申请」分表——申请是流水，授权是状态。

    分表而不是在申请行上查 status：同一 scope 可能被批过又撤销过多次，
    只看「最新的那条申请状态」在撤销场景下会算错。
    """

    __tablename__ = "student_grant"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    class_id: Mapped[int] = mapped_column(Integer)
    user_id: Mapped[int] = mapped_column(Integer)
    scope: Mapped[str] = mapped_column(String(16))
    granted_by: Mapped[int] = mapped_column(Integer)
    granted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP")
    )
