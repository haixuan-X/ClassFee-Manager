"""请求入参模型：字段名/校验文案与 Java DTO 注解逐一相同。

- 校验失败经 errors.py 转成 400「参数校验失败」+ [{field,message}]（= Spring @Valid 字段列表）
- 字段类型/日期格式错误 → 400「请求体格式不正确」（= Jackson HttpMessageNotReadable）
- 所有字段默认 None + validate_default=True：缺失时也走同一套中文文案（= @NotNull/@NotBlank）
"""
from __future__ import annotations

import math
import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator
from pydantic_core import PydanticCustomError

from .errors import BizException, FIELD_CONSTRAINT

_ENUM_KIND = re.compile(r"INCOME|EXPENSE")
_ENUM_CHANNEL = re.compile(r"CASH|WECHAT|ALIPAY|BANK|OTHER")
_ENUM_PAY_STATUS = re.compile(r"UNPAID|PAID|REFUNDED")
_ENUM_ROLE = re.compile(r"ADMIN|MEMBER|MONITOR|TEACHER")
# 小票相对路径（file_service.save_receipt 生成 receipts/<uuid>.<ext>，只认这一形态）
_ENUM_RECEIPT = re.compile(r"receipts/[A-Za-z0-9][A-Za-z0-9._-]*")


def _raise_constraint(message: str) -> None:
    raise PydanticCustomError(FIELD_CONSTRAINT, message)


def _raise_format() -> None:
    """非字段约束类错误 → errors.py 归入「请求体格式不正确」。"""
    raise PydanticCustomError("body_parse", "parse error")


def _not_blank(v: Any, message: str) -> None:
    # @NotBlank：null 或 trim 后为空
    if v is None or (isinstance(v, str) and not v.strip()):
        _raise_constraint(message)


def _check_size(v: Any, max_len: int | None, message: str, min_len: int | None = None) -> None:
    # @Size：null 跳过；按原始字符串长度（Java String.length）
    if v is None or not isinstance(v, str):
        return
    if min_len is not None and len(v) < min_len:
        _raise_constraint(message)
    if max_len is not None and len(v) > max_len:
        _raise_constraint(message)


def _decimal_parts(v: Decimal) -> tuple[int, int]:
    _sign, digits, exp = v.as_tuple()
    if not isinstance(exp, int):  # NaN / Infinity
        _raise_format()
    frac = max(0, -exp)
    int_digits = len(digits) - frac + max(0, exp)
    return max(0, int_digits), frac


def _check_amount(v: Decimal | None, *, required_message: str | None) -> Decimal | None:
    """@NotNull(可选) → @DecimalMin(0.01) → @Digits(8,2)，顺序与声明一致。"""
    if v is None:
        if required_message is not None:
            _raise_constraint(required_message)
        return None
    if not v.is_finite():
        _raise_format()
    if v < Decimal("0.01"):
        _raise_constraint("金额必须大于 0")
    int_digits, frac = _decimal_parts(v)
    if int_digits > 8 or frac > 2:
        _raise_constraint("金额最多两位小数")
    return v


def _parse_datetime_str(v: Any, fmt: str) -> datetime | date | None:
    """严格按 Java @JsonFormat 的 pattern 解析；空串→null（同 Jackson）。"""
    if v is None:
        return None
    if isinstance(v, str):
        if v == "":
            return None
        try:
            return datetime.strptime(v, fmt)
        except ValueError:
            _raise_format()
    if isinstance(v, (datetime, date)):
        return v
    _raise_format()
    return None


class _BodyModel(BaseModel):
    model_config = ConfigDict(validate_default=True)


class LoginRequest(_BodyModel):
    username: str | None = None
    password: str | None = None

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入账号")
        return v

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入密码")
        _check_size(v, 32, "密码长度需为 6-32 位", min_len=6)
        return v


class PasswordRequest(_BodyModel):
    oldPassword: str | None = None
    newPassword: str | None = None

    @field_validator("oldPassword")
    @classmethod
    def _v_old(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入原密码")
        return v

    @field_validator("newPassword")
    @classmethod
    def _v_new(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入新密码")
        _check_size(v, 32, "新密码长度需为 6-32 位", min_len=6)
        return v


class RecordRequest(_BodyModel):
    type: str | None = None
    categoryId: int | None = None
    amount: Decimal | None = None
    title: str | None = None
    occurredAt: datetime | None = None
    channel: str | None = None
    remark: str | None = None
    receiptUrl: str | None = None

    @field_validator("type")
    @classmethod
    def _v_type(cls, v: str | None) -> str | None:
        _not_blank(v, "请选择收支类型")
        if v is not None and not _ENUM_KIND.fullmatch(v):
            _raise_constraint("收支类型不合法")
        return v

    @field_validator("categoryId")
    @classmethod
    def _v_category(cls, v: int | None) -> int | None:
        if v is None:
            _raise_constraint("请选择收支类别")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount_pre(cls, v: Any) -> Any:
        if isinstance(v, float):
            if not math.isfinite(v):
                _raise_format()
            return str(v)  # Decimal(str(0.1)) == Jackson 用 JSON 文本构造的 0.1
        return v

    @field_validator("amount")
    @classmethod
    def _v_amount(cls, v: Decimal | None) -> Decimal | None:
        return _check_amount(v, required_message="请输入金额")

    @field_validator("title")
    @classmethod
    def _v_title(cls, v: str | None) -> str | None:
        _not_blank(v, "请填写摘要")
        _check_size(v, 60, "摘要最多 60 字")
        return v

    @field_validator("occurredAt", mode="before")
    @classmethod
    def _v_occurred_pre(cls, v: Any) -> Any:
        return _parse_datetime_str(v, "%Y-%m-%d %H:%M:%S")

    @field_validator("occurredAt")
    @classmethod
    def _v_occurred(cls, v: datetime | None) -> datetime | None:
        if v is None:
            _raise_constraint("请选择发生时间")
        return v

    @field_validator("channel")
    @classmethod
    def _v_channel(cls, v: str | None) -> str | None:
        if v is not None and not _ENUM_CHANNEL.fullmatch(v):
            _raise_constraint("支付方式不合法")
        return v

    @field_validator("remark")
    @classmethod
    def _v_remark(cls, v: str | None) -> str | None:
        _check_size(v, 255, "备注最多 255 字")
        return v

    @field_validator("receiptUrl")
    @classmethod
    def _v_receipt(cls, v: str | None) -> str | None:
        # 空白串=未上传，归一为 None；只接受 file_service 生成的 receipts/<name> 形态
        if v is None or (isinstance(v, str) and not v.strip()):
            return None
        v = v.strip()
        _check_size(v, 255, "小票路径不合法")
        if not _ENUM_RECEIPT.fullmatch(v):
            _raise_constraint("小票路径不合法")
        return v


class CategoryRequest(_BodyModel):
    """收支类别。**新建**要求 name+kind 都在；**编辑**（`PUT /categories/{id}`）全部可选，
    语义统一为「不传=不修改」——与 `UserUpdateRequest` / `NoticeRequest` 一致。

    `id`：历史契约里客户端会在 body 里重复带一遍 id；路径里已经有 id，所以它**只做一致性校验**
    （传了且与路径不符直接 400），不再作为「必填」——否则这个接口按 REST 方式根本调不通。
    """

    id: int | None = None
    name: str | None = None
    kind: str | None = None
    icon: str | None = None
    sort: int | None = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入类别名称")
        _check_size(v, 30, "类别名称最多 30 字")
        return v

    @field_validator("kind")
    @classmethod
    def _v_kind(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请选择类别方向")
        if not _ENUM_KIND.fullmatch(v):
            _raise_constraint("类别方向不合法")
        return v

    @field_validator("icon")
    @classmethod
    def _v_icon(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _check_size(v, 50, "图标名最多 50 字")
        return v


class BatchRequest(_BodyModel):
    name: str | None = None
    amount: Decimal | None = None
    deadline: date | None = None
    remark: str | None = None

    @field_validator("name")
    @classmethod
    def _v_name(cls, v: str | None) -> str | None:
        _not_blank(v, "请填写批次名称")
        _check_size(v, 60, "批次名称最多 60 字")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount_pre(cls, v: Any) -> Any:
        if isinstance(v, float):
            if not math.isfinite(v):
                _raise_format()
            return str(v)
        return v

    @field_validator("amount")
    @classmethod
    def _v_amount(cls, v: Decimal | None) -> Decimal | None:
        return _check_amount(v, required_message="请填写每人应收金额")

    @field_validator("deadline", mode="before")
    @classmethod
    def _v_deadline(cls, v: Any) -> Any:
        parsed = _parse_datetime_str(v, "%Y-%m-%d")
        if isinstance(parsed, datetime):
            return parsed.date()
        return parsed

    @field_validator("remark")
    @classmethod
    def _v_remark(cls, v: str | None) -> str | None:
        _check_size(v, 255, "备注最多 255 字")
        return v


class BatchPayRequest(_BodyModel):
    userId: int | None = None
    amount: Decimal | None = None
    channel: str | None = None
    occurredAt: datetime | None = None
    remark: str | None = None

    @field_validator("userId")
    @classmethod
    def _v_user(cls, v: int | None) -> int | None:
        if v is None:
            _raise_constraint("请选择缴费成员")
        return v

    @field_validator("amount", mode="before")
    @classmethod
    def _v_amount_pre(cls, v: Any) -> Any:
        if isinstance(v, float):
            if not math.isfinite(v):
                _raise_format()
            return str(v)
        return v

    @field_validator("amount")
    @classmethod
    def _v_amount(cls, v: Decimal | None) -> Decimal | None:
        return _check_amount(v, required_message=None)

    @field_validator("channel")
    @classmethod
    def _v_channel(cls, v: str | None) -> str | None:
        if v is not None and not _ENUM_CHANNEL.fullmatch(v):
            _raise_constraint("支付方式不合法")
        return v

    @field_validator("occurredAt", mode="before")
    @classmethod
    def _v_occurred(cls, v: Any) -> Any:
        return _parse_datetime_str(v, "%Y-%m-%d %H:%M:%S")

    @field_validator("remark")
    @classmethod
    def _v_remark(cls, v: str | None) -> str | None:
        _check_size(v, 255, "备注最多 255 字")
        return v


class UserCreateRequest(_BodyModel):
    """新建账号（运营建班）：username=登录名；password 缺省 123456；role 缺省 MEMBER。

    role 四选一：MEMBER(普通成员，只读) / ADMIN(生活委员) / MONITOR(班长) / TEACHER(班主任)，
    后三者同为运营角色（STAFF_ROLES）。
    studentNo=学号（可与登录名不同）：留空时 MEMBER 默认回填登录名（超 20 字则留空）。
    """

    username: str | None = None
    realName: str | None = None
    studentNo: str | None = None
    password: str | None = None
    phone: str | None = None
    role: str | None = None

    @field_validator("username")
    @classmethod
    def _v_username(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入登录名")
        _check_size(v, 32, "登录名最多 32 字")
        return v

    @field_validator("realName")
    @classmethod
    def _v_real_name(cls, v: str | None) -> str | None:
        _not_blank(v, "请输入姓名")
        _check_size(v, 32, "姓名最多 32 字")
        return v

    @field_validator("studentNo")
    @classmethod
    def _v_student_no(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None  # 空串=未提供
        _check_size(v, 20, "学号最多 20 字")
        return v

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None  # 空串=未提供，使用默认初始密码
        _check_size(v, 32, "密码长度需为 6-32 位", min_len=6)
        return v

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None
        _check_size(v, 20, "手机号最多 20 位")
        return v

    @field_validator("role")
    @classmethod
    def _v_role(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None  # 空串=未提供，使用默认 MEMBER
        if v is not None and not _ENUM_ROLE.fullmatch(v):
            _raise_constraint("角色不合法")
        return v


class UserUpdateRequest(_BodyModel):
    """编辑账号：字段均可选（None=不修改）；password=重置密码；status=0/1 停用启用。

    studentNo 语义同 phone：**空串=清空、不传=None=不改**。
    """

    realName: str | None = None
    studentNo: str | None = None
    phone: str | None = None
    status: int | None = None
    password: str | None = None

    @field_validator("realName")
    @classmethod
    def _v_real_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入姓名")
        _check_size(v, 32, "姓名最多 32 字")
        return v

    @field_validator("phone")
    @classmethod
    def _v_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None  # None=不修改
        if v == "":
            return ""  # 空串=显式清空手机号
        _check_size(v, 20, "手机号最多 20 位")
        return v

    @field_validator("studentNo")
    @classmethod
    def _v_student_no_update(cls, v: str | None) -> str | None:
        if v is None:
            return None  # None=不修改
        if v == "":
            return ""  # 空串=显式清空学号
        _check_size(v, 20, "学号最多 20 字")
        return v

    @field_validator("status")
    @classmethod
    def _v_status(cls, v: int | None) -> int | None:
        if v is None:
            return None
        if v not in (0, 1):
            _raise_constraint("状态不合法")
        return v

    @field_validator("password")
    @classmethod
    def _v_password(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            return None  # 空串=不修改
        _check_size(v, 32, "密码长度需为 6-32 位", min_len=6)
        return v


class ProfileUpdateRequest(_BodyModel):
    """第十五轮：本人自助修改个人信息。

    与 UserUpdateRequest 的区别是**只有「自己的资料」三类字段**：
    - 不含 role/status（权限与启用状态只能由运营改）
    - 不含 password（改密走 `PUT /auth/password`，要校验原密码）
    - 不含 username/classId（登录名创建后不可改，班级由归属决定）
    - 目标用户**取自登录令牌**，不接受请求体传 id，从根上杜绝改别人

    语义沿用既有约定：字段不传=None=不改；realName 传了就不能为空；
    studentNo/phone 空串=清空；学号同班唯一。
    """

    realName: str | None = None
    studentNo: str | None = None
    phone: str | None = None

    @field_validator("realName")
    @classmethod
    def _v_profile_real_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入姓名")
        _check_size(v, 32, "姓名最多 32 字")
        return v

    @field_validator("studentNo")
    @classmethod
    def _v_profile_student_no(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v == "":
            return ""
        _check_size(v, 20, "学号最多 20 字")
        return v

    @field_validator("phone")
    @classmethod
    def _v_profile_phone(cls, v: str | None) -> str | None:
        if v is None:
            return None
        if v == "":
            return ""
        _check_size(v, 20, "手机号最多 20 位")
        return v


# ---------------- 班级公告 / 班级信息（M4） ----------------


class NoticeRequest(_BodyModel):
    """班级公告：发布时 title/content 必填；编辑时全部可选（None=不修改）。

    - `pinned`：1=置顶（仪表盘只展示置顶公告）
    - `status`：1=发布 0=下架（软删除，可恢复）；发布接口恒为「已发布」，
      下架/恢复走编辑接口的 status 字段
    """

    title: str | None = None
    content: str | None = None
    pinned: int | None = None
    status: int | None = None

    @field_validator("title")
    @classmethod
    def _v_notice_title(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入公告标题")
        _check_size(v, 80, "公告标题最多 80 字")
        return v

    @field_validator("content")
    @classmethod
    def _v_notice_content(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入公告内容")
        _check_size(v, 2000, "公告内容最多 2000 字")
        return v

    @field_validator("pinned")
    @classmethod
    def _v_pinned(cls, v: int | None) -> int | None:
        if v is not None and v not in (0, 1):
            _raise_constraint("置顶状态不合法")
        return v

    @field_validator("status")
    @classmethod
    def _v_notice_status(cls, v: int | None) -> int | None:
        if v is not None and v not in (0, 1):
            _raise_constraint("公告状态不合法")
        return v


class ClassInfoRequest(_BodyModel):
    """编辑班级信息：className 必填（≤50）；grade/headTeacher 可选，
    **空串=清空、None=不修改**（同 /users 的 phone 语义）。balance 不接受手改。"""

    className: str | None = None
    grade: str | None = None
    headTeacher: str | None = None

    @field_validator("className")
    @classmethod
    def _v_class_name(cls, v: str | None) -> str | None:
        if v is None:
            return None
        _not_blank(v, "请输入班级名称")
        _check_size(v, 50, "班级名称最多 50 字")
        return v

    @field_validator("grade")
    @classmethod
    def _v_grade(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            _check_size(v, 20, "年级最多 20 字")
        return v

    @field_validator("headTeacher")
    @classmethod
    def _v_head_teacher(cls, v: str | None) -> str | None:
        if v is not None and v != "":
            _check_size(v, 50, "班主任姓名最多 50 字")
        return v


# ---------------- query 参数（= Spring @Min/@Max/@Pattern 的 ConstraintViolation） ----------------

def check_paging(page: int, size: int) -> None:
    """RecordQuery：@Min/@Max 违例 → 400 + 首条违规消息（data=null）。"""
    if page < 1:
        raise BizException.bad_request("页码从 1 开始")
    if size < 1:
        raise BizException.bad_request("每页至少 1 条")
    if size > 100:
        raise BizException.bad_request("每页最多 100 条")


def check_pay_status(pay_status: str | None) -> None:
    """MemberQuery：@Pattern 违例 → 400 + 首条违规消息（data=null）。"""
    if pay_status is not None and not _ENUM_PAY_STATUS.fullmatch(pay_status):
        raise BizException.bad_request("缴费状态不合法")
