"""账号管理服务（第七轮：老师自助建班——列表/新增/编辑/重置密码/停用启用；第十一轮补学号；
第十二轮补删除：仅「无任何历史引用」的账号可物理删除；
第十五轮补 update_profile：本人自助改姓名/学号/手机号）。

约定：
- 全部操作限定操作者所在班级（class_id 隔离）；username 全局唯一（uk_username）
- studentNo=学号可与登录名不同，**同班唯一**（服务层校验，DDL 未建唯一索引）
- 停用=status 0（登录被拒，保留历史）；**删除只给「零引用」的账号**（记账/缴费/公告/批次都没他），
  有引用一律拒绝并提示改用停用——避免流水、缴费名单出现悬空引用
- 重置密码直接指定新密码（运营动作，无需原密码；本人改密走 PUT /auth/password）
- **资料字段（姓名/学号/手机号）两条路径共用 `_apply_profile_fields`**，语义只有一份实现
"""
from __future__ import annotations

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import FeeBatch, FeePayment, FeeRecord, SysNotice, SysUser
from ..schemas import ProfileUpdateRequest, UserCreateRequest, UserUpdateRequest
from ..security import LoginUser, hash_password, require_role_higher, role_level
from ..serializers import fmt_dt

DEFAULT_INITIAL_PASSWORD = "123456"


def account_vo(u: SysUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "studentNo": u.student_no,
        "phone": u.phone,
        "role": u.role,
        "classId": u.class_id,
        "status": u.status,
        "lastLoginAt": fmt_dt(u.last_login_at),
        "createdAt": fmt_dt(u.created_at),
    }


def list_users(db: Session, user: LoginUser, *, keyword: str | None) -> list[dict]:
    conds = [SysUser.class_id == user.class_id]
    kw = keyword.strip() if keyword is not None else ""
    if kw:
        from ..helpers import like_pattern

        pattern = like_pattern(kw)
        conds.append(
            or_(
                SysUser.real_name.like(pattern),
                SysUser.username.like(pattern),
                SysUser.student_no.like(pattern),
                SysUser.phone.like(pattern),
            )
        )
    rows = db.scalars(
        select(SysUser).where(*conds).order_by(SysUser.username.asc())
    ).all()
    return [account_vo(u) for u in rows]


def _ensure_student_no_unique(
    db: Session, class_id: int, student_no: str, exclude_id: int | None
) -> None:
    """同班学号唯一（学号是缴费名单、批次排序的识别键，不能重号）。

    DDL 里 student_no 没有唯一索引（与 Java 存档一致），这里按业务规则在服务层拦。
    """
    conds = [SysUser.class_id == class_id, SysUser.student_no == student_no]
    if exclude_id is not None:
        conds.append(SysUser.id != exclude_id)
    dup = db.scalar(select(func.count()).select_from(SysUser).where(*conds)) or 0
    if dup > 0:
        raise BizException.bad_request("该学号已存在，请检查后再填")


def create_user(db: Session, user: LoginUser, req: UserCreateRequest) -> dict:
    with db.begin():
        exists = (
            db.scalar(
                select(func.count())
                .select_from(SysUser)
                .where(SysUser.username == req.username)
            )
            or 0
        )
        if exists > 0:
            raise BizException.bad_request("账号已存在")

        role = req.role or "MEMBER"
        # 第十五轮：新建账号的**角色等级不得高于操作者**。
        # 这是等级体系的唯一提权入口——不改角色的接口（PUT /users/{id} 不含 role），
        # 但「新建一个班主任账号再登进去」能绕开所有护栏，所以必须在这里拦。
        if role_level(role) > role_level(user.role):
            raise BizException.bad_request(
                "权限不足：不能创建权限高于自己的账号"
            )
        password = req.password or DEFAULT_INITIAL_PASSWORD
        username = req.username or ""
        # 学号：老师显式填的优先；没填时 MEMBER 默认回填登录名（列 VARCHAR(20)，超长则留空）
        if req.studentNo is not None and req.studentNo.strip() != "":
            student_no = req.studentNo.strip()
        elif role == "MEMBER" and len(username) <= 20:
            student_no = username
        else:
            student_no = None
        if student_no is not None:
            _ensure_student_no_unique(db, user.class_id, student_no, None)
        row = SysUser(
            class_id=user.class_id,
            username=username,
            password=hash_password(password),
            real_name=req.realName or "",
            student_no=student_no,
            phone=req.phone or None,
            role=role,
            status=1,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        return account_vo(row)


def _apply_profile_fields(
    db: Session,
    target: SysUser,
    *,
    real_name: str | None,
    student_no: str | None,
    phone: str | None,
) -> dict:
    """把「姓名 / 学号 / 手机号」三类资料字段转成待更新列（运营编辑与本人自助共用）。

    语义：不传=None=不改；学号/手机号 空串=显式清空；学号同班唯一。
    抽出来是为了让两条路径**不可能漂移**——第十五轮加自助改资料时，
    学号唯一校验、空串语义这些坑只应存在一份实现。
    """
    values: dict = {}
    if real_name is not None:
        values["real_name"] = real_name
    if student_no is not None:
        normalized = student_no.strip() or None
        if normalized is not None:
            _ensure_student_no_unique(db, target.class_id, normalized, target.id)
        values["student_no"] = normalized
    if phone is not None:
        values["phone"] = phone.strip() or None
    return values


def update_user(
    db: Session, user: LoginUser, user_id: int, req: UserUpdateRequest
) -> dict:
    with db.begin():
        target = db.get(SysUser, user_id)
        if target is None or target.class_id != user.class_id:
            raise BizException.bad_request("成员不存在")

        if (
            req.realName is None
            and req.studentNo is None
            and req.phone is None
            and req.status is None
            and req.password is None
        ):
            raise BizException.bad_request("没有需要修改的内容")

        # 第十五轮：任何**改动**（含改姓名/学号/手机号）都受等级护栏约束 ——
        # 低等级角色不能改高等级账号的资料，否则能改学号就等于能顶替其缴费身份
        if target.id != user.id:
            require_role_higher(user.role, target.role)

        values = _apply_profile_fields(
            db,
            target,
            real_name=req.realName,
            student_no=req.studentNo,
            phone=req.phone,
        )
        if req.status is not None:
            if target.id == user.id and req.status == 0:
                raise BizException.bad_request("不能停用自己的账号")
            values["status"] = req.status
        if req.password is not None:
            values["password"] = hash_password(req.password)

        db.execute(update(SysUser).where(SysUser.id == target.id).values(**values))
        db.refresh(target)
        return account_vo(target)


def my_profile(db: Session, user: LoginUser) -> dict:
    """第十五轮：读本人完整资料（含学号 / 手机号）。

    不复用 `GET /api/users`：那个接口是运营角色的成员管理列表，普通成员读不到，
    个人信息页就显示不出自己的学号。这里按登录令牌里的 id 取，**只能读自己**。
    """
    with db.begin():
        target = db.get(SysUser, user.id)
        if target is None:
            raise BizException.unauthorized("账号不存在或已被删除")
        return account_vo(target)


def update_profile(db: Session, user: LoginUser, req: ProfileUpdateRequest) -> dict:
    """第十五轮：本人自助修改个人信息（`PUT /api/auth/profile`）。

    与运营编辑的差别只有一处关键：**目标用户取自登录令牌**（`user.id`），
    请求体里没有 id 字段可传，因此**结构上无法改到别人的资料**，不依赖"前端不传"。
    角色、启用状态、登录名、班级都不在本接口的可改范围。
    """
    with db.begin():
        target = db.get(SysUser, user.id)
        if target is None:
            raise BizException.unauthorized("账号不存在或已被删除")

        if req.realName is None and req.studentNo is None and req.phone is None:
            raise BizException.bad_request("没有需要修改的内容")

        values = _apply_profile_fields(
            db,
            target,
            real_name=req.realName,
            student_no=req.studentNo,
            phone=req.phone,
        )
        db.execute(update(SysUser).where(SysUser.id == target.id).values(**values))
        db.refresh(target)
        return account_vo(target)


def _count(db: Session, model, *conds) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conds)) or 0


def delete_user(db: Session, user: LoginUser, user_id: int) -> None:
    """删除账号：仅「零引用」可删；有流水/缴费/公告/批次引用一律拒绝，引导改用停用。

    这样老师能清掉误建、临时用过的账号，同时保证历史账目不出现悬空引用。

    第十五轮补：先过**权限等级**护栏（班主任 > 班长 > 生活委员 > 普通成员），
    低等级/同级角色一律不能删除对方账号 —— 否则班长能删掉班主任。
    """
    with db.begin():
        target = db.get(SysUser, user_id)
        if target is None or target.class_id != user.class_id:
            raise BizException.bad_request("成员不存在")
        if target.id == user.id:
            raise BizException.bad_request("不能删除自己的账号")
        # 权限等级：操作者必须严格高于目标（班主任唯一能删/停用别人的账号）
        require_role_higher(user.role, target.role)

        refs: list[str] = []
        n_record = _count(
            db,
            FeeRecord,
            or_(FeeRecord.created_by == target.id, FeeRecord.payer_user_id == target.id),
        )
        if n_record:
            refs.append(f"{n_record} 笔流水")
        n_payment = _count(db, FeePayment, FeePayment.user_id == target.id)
        if n_payment:
            refs.append(f"{n_payment} 条缴费记录")
        n_notice = _count(db, SysNotice, SysNotice.created_by == target.id)
        if n_notice:
            refs.append(f"{n_notice} 条公告")
        n_batch = _count(db, FeeBatch, FeeBatch.created_by == target.id)
        if n_batch:
            refs.append(f"{n_batch} 个收费批次")
        if refs:
            raise BizException.bad_request(
                f"该成员已关联{'、'.join(refs)}，不能删除；可停用账号以保留历史记录"
            )

        db.delete(target)
