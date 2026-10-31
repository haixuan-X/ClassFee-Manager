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

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import (
    ClsClass,
    FeeBatch,
    FeePayment,
    FeeRecord,
    StudentRecord,
    SysUser,
    SysUserClass,
)
from ..schemas import ProfileUpdateRequest, UserCreateRequest, UserUpdateRequest
from ..security import (
    DEAN_ROLE,
    STAFF_ROLES,
    GUEST_MANAGER_MIN_LEVEL,
    GUEST_ROLE,
    LoginUser,
    dump_guest_scopes,
    hash_password,
    parse_guest_scopes,
    require_role_higher,
    role_level,
)
from ..serializers import fmt_dt

DEFAULT_INITIAL_PASSWORD = "123456"

#: `sys_user.student_no` 是 VARCHAR(20)，而 `student_record.student_no` 是 VARCHAR(32)。
#: 学号更长的行建不出账号（塞不进登录账号那一列），只能跳过并说明原因。
#: **不静默截断**——截断出来的学号是个错号，回头会和另一行撞上。
MAX_STUDENT_NO_LEN = 20




def managed_class_ids(
    db: Session, user_id: int, role: str, default_class_id: int
) -> list[int]:
    """这个账号**能管哪些班**（第三十二轮）。

    - **其他人 = 默认班 ∪ `sys_user_class` 里关联的班**。
    - **院长 = 他自己勾的「我带的班」**；一条都没勾过才退回「所有启用班」。

    ## 院长为什么也要看关联表（第三十三轮）

    原来的口径是「院长恒等于全部启用班」。可「个人信息」里明明有「我带的班」
    多选，院长勾完保存，回执还是全班——**那个多选对院长就是个摆设**。
    用户是这么撞上的：「感觉有点串数据，没有根据我带的班来分类」。

    现在分两层，互不干扰：

    - **学院层**（`/api/college/*`、学生总览、任务总览）= 全校，不看关联表
    - **班级层**（账目/任务/学生信息/成员缴费/班级信息）= 只在他勾的班里切

    **没勾过**（老账号、回归探针）仍然全管——否则存量院长一升级就
    「一个班都切不过去」。

    ⚠ **必须用同一个 Session 查**：engine 版的 `security.managed_class_ids`
    走的是**另一条连接**，看不到当前事务里刚写的关联表（还没提交）——
    表现为「明明加了班，回执里还是只有一个」。

    ⚠ **默认班永远在里面**：关联表是后加的，老账号一条关联记录都没有——
    要是只看关联表，所有存量账号都会变成「一个班都管不了」。
    """
    picked: list[int] = []
    for (cid,) in db.execute(
        select(SysUserClass.class_id).where(SysUserClass.user_id == user_id)
    ):
        c = int(cid)
        if c not in picked:
            picked.append(c)

    if role == DEAN_ROLE:
        if not picked:
            return [
                int(cid)
                for (cid,) in db.execute(
                    select(ClsClass.id).where(ClsClass.status == 1).order_by(ClsClass.id.asc())
                )
            ]
        alive = {
            int(cid)
            for (cid,) in db.execute(select(ClsClass.id).where(ClsClass.status == 1))
        }
        out = [default_class_id]
        for c in picked:
            if c in alive and c not in out:
                out.append(c)
        return out

    ids: list[int] = [default_class_id]
    for c in picked:
        if c not in ids:
            ids.append(c)
    return ids


def _adviser_role_condition():
    """谁**能**在名册上占「班主任」这一位（第五十一轮）。

    - 班主任（`TEACHER`）
    - 兼班主任的院长（`DEAN` 且 `dean_only=0`）——**和班主任同权同额**，
      一个班也只能有一位
    - 纯院长不算：他只管学院、不参与班级事务

    名册（`college_service.advisers`）与冲突判定（`_class_teacher_conflict`）
    必须共用这一份条件。各写一份的话，迟早会出现「名册上看不见他，
    但安排时又说他占了位」这种查不动的矛盾。
    """
    return or_(
        SysUser.role == "TEACHER",
        (SysUser.role == DEAN_ROLE) & (SysUser.dean_only == 0),
    )


def _class_teacher_conflict(
    db: Session, class_id: int, *, exclude_user_id: int | None = None
) -> SysUser | None:
    """这个班**已有的班主任账号**（`is_adviser=1`，院长也算）。

    「一班一个班主任」（第五十一轮）的唯一判定口径——所有入口
    （改班主任安排 / 导入班主任 / 建号 / 改能管的班 / 本人改「我带的班」）
    共用这一个函数，各写一份必然漂。

    判定看 `sys_user_class.is_adviser`，**不再看「谁在这个班的关联表里」**：
    一行关联只代表「能管这个班」（院长的「我带的班」、被顶替后留下的
    管理行都在里面），不占班主任名额。

    也只认**能在名册上出现的人**（`_adviser_role_condition`：班主任 +
    兼班主任院长）。纯院长即使有一行旧标志，名册上也不显示，不能让他
    变成「看不见的占位人」。

    `exclude_user_id` = 正在被安排的那个人自己（重挂自己不算冲突——
    导入同一份表、本人重存「我带的班」都会走到）。
    """
    conds = [
        SysUserClass.class_id == class_id,
        SysUserClass.is_adviser == 1,
        SysUser.status == 1,
        _adviser_role_condition(),
    ]
    if exclude_user_id is not None:
        conds.append(SysUser.id != exclude_user_id)
    return db.scalar(
        select(SysUser)
        .join(SysUserClass, SysUserClass.user_id == SysUser.id)
        .where(*conds)
        .limit(1)
    )


def _teacher_conflict_msg(
    db: Session, class_id: int, *, exclude_user_id: int | None, action: str
) -> str | None:
    """撞车时的统一文案（带班名 + 占位人名 + 指路）；没撞返回 None。

    和 `_class_teacher_conflict` 分开是为了**行级跳过**（导入）与
    **整单拒绝**（建号/改班）共用同一句话——报错文案写两份必然漂，
    用户在两个入口看到两种说法就不知道该信哪个。
    """
    other = _class_teacher_conflict(db, class_id, exclude_user_id=exclude_user_id)
    if other is None:
        return None
    clazz = db.get(ClsClass, class_id)
    cname = clazz.class_name if clazz else f"#{class_id}"
    return (
        f"{action}：「{cname}」已有班主任「{other.real_name or other.username}」；"
        "一个班只有一位班主任，如需更换请到「班主任名册 → 改班主任安排」"
    )


def _raise_if_class_taken(
    db: Session, class_id: int, *, exclude_user_id: int | None, action: str
) -> None:
    """想把某人挂到 `class_id` 当班主任前先问这一句；已有别人就 400 指路。

    用于**整单拒绝**的入口（建号、运营改班、本人改「我带的班」）。
    导入是行级跳过，走 `_teacher_conflict_msg` 自己 append errors——
    在 `db.begin()` 里抛异常会把整批导入回滚，而用户只想跳过那一行。
    """
    msg = _teacher_conflict_msg(
        db, class_id, exclude_user_id=exclude_user_id, action=action
    )
    if msg is not None:
        raise BizException.bad_request(msg)


def _set_managed_classes(
    db: Session, user_id: int, default_class_id: int, class_ids: list[int],
    *, force_default: bool = True, adviser_class_ids: set[int] | None = None,
) -> None:
    """把「可管理的班级」写成给定的那几个（**默认班永远包含在内**）。

    `sys_user.class_id` 是**默认班**（登录后落在哪个班），不能被摘掉——
    摘掉的话这个人就「一个班都管不了」了，成员列表、账目、学生信息全空。

    `force_default=False`：默认班**不强制写关联行**（第五十一轮）。
    管理权不靠这一行——`managed_class_ids` 恒含默认班；这一行只影响
    「班主任名册」上算不算这个班的班主任。默认班已被**别的班主任**占着时
    （本人被顶替、默认班还指着原班），照写就会把自己塞回名册——
    「一个班一个班主任」当场破功。只给 role=TEACHER 的目标传 False，
    且只在调用方确认「默认班有冲突」时传。

    ## `is_adviser` 怎么定（第五十一轮）

    重写关联表**不能顺手把班主任降成「只是能管」**：运营改「能管的班」时
    勾选列表往往原样带回，标志必须跟人走。所以：

    - 原来就是 `is_adviser=1` 的班且还在 `wanted` 里 → 保持 1
    - 调用方明确新增为班主任的班（`adviser_class_ids`）→ 1
    - 其余（含被自动带上的默认班、院长勾的「我带的班」）→ 0

    否则「改一次能管的班」就把名册上的班主任抹掉，用户会看到名册突然空了。
    """
    adviser_ids = {int(c) for c in (adviser_class_ids or set())}
    was_adviser = {
        int(cid)
        for (cid,) in db.execute(
            select(SysUserClass.class_id).where(
                SysUserClass.user_id == user_id,
                SysUserClass.is_adviser == 1,
            )
        )
    }
    wanted = [default_class_id] if force_default else []
    for cid in class_ids:
        c = int(cid)
        if c not in wanted:
            wanted.append(c)
    # 只留**存在的班**（班级被停用/删了，关联记录要跟着清掉）
    alive = {
        int(cid)
        for (cid,) in db.execute(
            select(ClsClass.id).where(ClsClass.id.in_(wanted))
        )
    }
    # 只留**存在的班**（班级被停用/删了，关联记录要跟着清掉）。
    # 全部失效时的兜底也要看 force_default：False 的语义就是
    # 「默认班不占班主任位」，兜回去等于把刚拒绝的事又做了。
    kept = [c for c in wanted if c in alive]
    if not kept:
        kept = [default_class_id] if force_default else []
    wanted = kept
    db.execute(delete(SysUserClass).where(SysUserClass.user_id == user_id))
    for cid in wanted:
        db.add(
            SysUserClass(
                user_id=user_id,
                class_id=cid,
                is_adviser=1 if (cid in was_adviser or cid in adviser_ids) else 0,
            )
        )
    db.flush()


def account_vo(u: SysUser, managed_ids: list[int] | None = None) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "studentNo": u.student_no,
        "phone": u.phone,
        "role": u.role,
        # 只有访客用得上；非访客一律给 null，别让前端对每个角色都判一遍
        "guestScopes": parse_guest_scopes(u.guest_scopes) if u.role == GUEST_ROLE else None,
        # 第三十轮：只有院长用得上。1 = 纯院长（只管学院，不参与班级事务）。
        # 非院长一律给 false —— 前端据此决定侧栏里给不给「账目」「班级」两组。
        "deanOnly": u.role == DEAN_ROLE and bool(u.dean_only),
        "classId": u.class_id,
        # 第三十二轮：这个账号能管哪些班（默认班排第一）。
        "managedClassIds": managed_ids or [u.class_id],
        "status": u.status,
        "lastLoginAt": fmt_dt(u.last_login_at),
        "createdAt": fmt_dt(u.created_at),
    }


def list_users(db: Session, user: LoginUser, *, keyword: str | None) -> list[dict]:
    # 第三十二轮：列出**我能管的班**的成员（不止当前班）——
    # 一个老师带两个班，两个班的成员他都要能看见。
    managed = managed_class_ids(db, user.id, user.role, user.class_id)
    conds = [SysUser.class_id.in_(managed)]
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
    return [
        account_vo(u, managed_class_ids(db, u.id, u.role, u.class_id)) for u in rows
    ]


def _ensure_student_no_unique(
    db: Session, class_id: int, student_no: str, exclude_id: int | None
) -> None:
    """同班学号唯一（学号是缴费名单、批次排序的识别键，不能重号）。

    DDL 里 student_no 没有唯一索引，这里按业务规则在服务层拦。
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
        # 第二十六轮：访客的「可见范围」。只对访客有意义，其他角色一律 NULL，
        # 免得库里躺着一堆永远不会被读的 JSON。
        guest_scopes = dump_guest_scopes(req.guestScopes) if role == GUEST_ROLE else None
        # 第三十轮：纯院长。只对院长有意义，其他角色一律 0（库里不留死数据）。
        # 第三十三轮：新建院长**默认纯院长**（只管学院，不参与班级事务）。
        # 想「院长 + 班主任」的，自己去「个人信息 → 职务范围」里切，
        # 或在创建时显式传 deanOnly=false。
        if role == DEAN_ROLE:
            dean_only = 0 if req.deanOnly is False else 1
        else:
            dean_only = 0
        # 第十五轮：新建账号的**角色等级不得高于操作者**。
        # 这是等级体系的唯一提权入口——不改角色的接口（PUT /users/{id} 不含 role），
        # 但「新建一个班主任账号再登进去」能绕开所有护栏，所以必须在这里拦。
        if role_level(role) > role_level(user.role):
            raise BizException.bad_request(
                "权限不足：不能创建权限高于自己的账号"
            )
        # 第二十四轮：访客**只由班主任及以上创建**（用户原话「访客权限由班主任创建」）。
        # 等级校验拦不住这条——GUEST 和 MEMBER 同为 0 级，班长等级高、反而"能建"。
        # 但访客是给领导/校方开的只读账号，属于"对外"的口子，
        # 不该由班长随手开一个。
        # 第二十八轮改成等级判定：院长(4) 也够格，否则会出现「院长管不了访客、
        # 班主任却管得了」的倒挂。
        if role == GUEST_ROLE and role_level(user.role) < GUEST_MANAGER_MIN_LEVEL:
            raise BizException.forbidden("访客账号只能由班主任及以上创建")
        # 第五十一轮：**一个班一个班主任**。新建 role=TEACHER 会自动把他挂成
        # 「操作者当前班」的班主任（下面的 SysUserClass 行），所以当前班已有
        # 班主任就先在这里拦下——否则名册上一个班挂出两个账号，
        # 正是用户报的那个问题。想换人：先到「改班主任安排」顶替，再回来建号。
        # 院长（含兼班主任院长）的自动挂班不拦：院长行只是「我带的班」
        # （管理权，is_adviser=0），不占班主任位；要当班主任走「改班主任安排」。
        if role == "TEACHER":
            _raise_if_class_taken(
                db, user.class_id, exclude_user_id=None, action="新建班主任账号"
            )
            for cid in req.classIds or []:
                if int(cid) != user.class_id:
                    _raise_if_class_taken(
                        db, int(cid), exclude_user_id=None, action="新建班主任账号"
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
            guest_scopes=guest_scopes,
            dean_only=dean_only,
            status=1,
        )
        db.add(row)
        db.flush()
        db.refresh(row)
        # 第三十二轮：新建**班主任**时，自动把「他是这个班的班主任」记上。
        #
        # 名册是按关联表（`sys_user_class`）列的——不记的话，新建的班主任
        # 在名册上**不出现**（看着像这个班没人管）。
        # 第五十一轮：`is_adviser=1` 才是班主任。院长（兼班主任）默认只写
        # 管理行（0）：他的「我带的班」不等于「他是班主任」，要当班主任
        # 得走「改班主任安排」显式指定——否则新建院长就白占一个名额。
        if role == "TEACHER" or (role == DEAN_ROLE and not dean_only):
            db.add(
                SysUserClass(
                    user_id=row.id,
                    class_id=row.class_id,
                    is_adviser=1 if role == "TEACHER" else 0,
                )
            )
            db.flush()
        # 第三十二轮：新建时也可以直接指定「能管哪些班」（默认只有当前班）。
        if req.classIds:
            mine = set(managed_class_ids(db, user.id, user.role, user.class_id))
            wanted = [cid for cid in req.classIds if int(cid) in mine]
            # 新建班主任时，指定的班在冲突校验里已经确认没人占——它们就是
            # 他当班主任的班，标志必须是 1（否则名册上只有默认班那一行）。
            _set_managed_classes(
                db,
                row.id,
                row.class_id,
                wanted,
                adviser_class_ids={int(c) for c in wanted} if role == "TEACHER" else set(),
            )
        return account_vo(row, managed_class_ids(db, row.id, row.role, row.class_id))


def list_deans(db: Session) -> dict:
    """院长账号一览（第五十二轮）。

    **只列 `role=DEAN`，不按班级过滤**：院长是学院级账号，不属于某一个班。
    这也正是它不能复用「成员管理」列表的原因——那份列表按「我能管的班」
    过滤，是班级视角；纯院长不参与班级事务，看到一屏学生账号没有意义。
    """
    rows = db.scalars(
        select(SysUser)
        .where(SysUser.role == DEAN_ROLE)
        .order_by(SysUser.id.asc())
    ).all()
    items = [
        {
            "id": u.id,
            "username": u.username,
            "realName": u.real_name or "",
            "phone": u.phone or "",
            "status": u.status,
            "deanOnly": bool(u.dean_only),
            "lastLoginAt": fmt_dt(u.last_login_at),
        }
        for u in rows
    ]
    return {"rows": items, "total": len(items)}


def create_dean(db: Session, user: LoginUser, req: UserCreateRequest) -> dict:
    """新增一位院长账号（第五十二轮）。

    ## 为什么单独一个入口

    纯院长的接口白名单里没有 `/api/users`，侧栏也不给「班级 → 成员管理」——
    他不能参与班级账号的增删改。但「再开一个院长」是**学院级**的事，
    不能因为这两道闸门就没有入口，否则院长账号只能靠改库或部署声明新增。

    ## 为什么一律建成纯院长

    新院长默认只管学院。若建出来就自动挂到某个班（`create_user` 对
    兼班主任院长会写一条管理行），「他为什么能进这个班」会变成一个
    没人记得的副作用，还可能和班主任安排纠缠。
    需要兼班主任的，本人登录后在「个人信息 → 职务范围」切换即可
    （第三十二轮起院长自己能改，立刻生效）。

    ## 角色/班级字段不是调用方说了算

    `role` 覆盖成 DEAN、`deanOnly` 覆盖成 True、`classIds`/`guestScopes`/
    `studentNo` 清空：这个入口只建院长。即使请求体里塞了 `role=TEACHER`，
    也只会建出院长——避免把「院长账号」页当成绕过等级校验的建号后门。
    """
    payload = req.model_copy(
        update={
            "role": DEAN_ROLE,
            "deanOnly": True,
            "classIds": None,
            "guestScopes": None,
            "studentNo": None,
        }
    )
    return create_user(db, user, payload)


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
        # 第三十二轮：成员在**我能管的班**里就行（不一定在当前班）。
        if target is None or target.class_id not in managed_class_ids(
            db, user.id, user.role, user.class_id
        ):
            raise BizException.bad_request("成员不存在")

        if (
            req.realName is None
            and req.studentNo is None
            and req.phone is None
            and req.status is None
            and req.password is None
            and req.guestScopes is None
            and req.deanOnly is None
            and req.classIds is None
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
        # 第二十六轮：改访客的可见范围。要求是「创建时选、编辑时也能改」，
        # 所以改完**立刻生效**——访客不用重新登录，中间件每个请求都会重读这一列
        # （见 `security._account_active`）。
        #
        # 只对访客生效：给普通成员写一串 guest_scopes 不会起作用，
        # 却会在库里躺一份永远读不到的死数据，所以非访客一律存 NULL。
        if req.guestScopes is not None and target.role == GUEST_ROLE:
            values["guest_scopes"] = dump_guest_scopes(req.guestScopes)
        # 第三十轮：改「是否纯院长」。要求是「创建时选、编辑时也能改」，
        # 改完**立刻生效**（中间件每个请求都重读这一列）。
        #
        # 只对院长生效：给别的角色写这一位不会起作用，
        # 却会在库里躺一份永远读不到的死数据，所以非院长一律存 0。
        if req.deanOnly is not None and target.role == DEAN_ROLE:
            values["dean_only"] = 1 if req.deanOnly else 0

        # ⚠ `values` 可能**是空的**（只传了 classIds 之类不进这张表的字段）——
        # `UPDATE ... SET WHERE ...` 是语法错误，整个请求 500。
        # 所以空了就别执行这条 UPDATE（下面的关联表处理照样做）。
        if values:
            db.execute(update(SysUser).where(SysUser.id == target.id).values(**values))
            db.refresh(target)
        # 第三十二轮：改「这个账号能管哪些班」。
        if req.classIds is not None:
            # 只能给**我能管的班**——不能把权限发给我自己都管不了的班。
            mine = set(managed_class_ids(db, user.id, user.role, user.class_id))
            wanted = [cid for cid in req.classIds if int(cid) in mine]
            if not wanted:
                raise BizException.bad_request("至少要保留一个你能管的班")
            # 第五十一轮：**一个班一个班主任**。只在目标是班主任、且是
            # **新增**的班时查冲突（重存同一批不能把自己挡在外面）；
            # 班长/生活委员被安排带班不算「班主任」（名册只列能占位的人），
            # 所以非班主任目标不受此限。
            force_default = True
            adviser_new: set[int] = set()
            if target.role == "TEACHER":
                current = {
                    int(cid)
                    for (cid,) in db.execute(
                        select(SysUserClass.class_id).where(
                            SysUserClass.user_id == target.id
                        )
                    )
                }
                for cid in wanted:
                    if int(cid) not in current:
                        _raise_if_class_taken(
                            db, int(cid), exclude_user_id=target.id, action="调整能管的班"
                        )
                        # 校验通过的**新班**是「安排他当这个班的班主任」，
                        # 标志要跟着写；否则只是能管、名册上不出现。
                        adviser_new.add(int(cid))
                # 默认班被**别人**占着时（此人曾是该班班主任、后被顶替），
                # `_set_managed_classes` 的默认班强制写入会把名册行加回来，
                # 「一个班一个班主任」当场破功——只保留管理权，不占名册位。
                if int(target.class_id) not in current:
                    force_default = (
                        _class_teacher_conflict(
                            db, int(target.class_id), exclude_user_id=target.id
                        )
                        is None
                    )
            _set_managed_classes(
                db, target.id, target.class_id, wanted,
                force_default=force_default,
                adviser_class_ids=adviser_new,
            )
        # 第五十一轮：切成**纯院长** = 不再担任任何班的班主任。
        # 管理行留着（他仍能进那些班），但名册位必须让出来——否则他占着
        # 一个「名册上看不见的名额」，别人安排时又被判冲突。
        if req.deanOnly is not None and target.role == DEAN_ROLE and req.deanOnly:
            db.execute(
                update(SysUserClass)
                .where(
                    SysUserClass.user_id == target.id,
                    SysUserClass.is_adviser == 1,
                )
                .values(is_adviser=0)
            )
        return account_vo(target, managed_class_ids(db, target.id, target.role, target.class_id))


def my_profile(db: Session, user: LoginUser) -> dict:
    """第十五轮：读本人完整资料（含学号 / 手机号）。

    不复用 `GET /api/users`：那个接口是运营角色的成员管理列表，普通成员读不到，
    个人信息页就显示不出自己的学号。这里按登录令牌里的 id 取，**只能读自己**。
    """
    with db.begin():
        target = db.get(SysUser, user.id)
        if target is None:
            raise BizException.unauthorized("账号不存在或已被删除")
        return account_vo(
            target, managed_class_ids(db, target.id, target.role, target.class_id)
        )


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

        if (
            req.realName is None
            and req.studentNo is None
            and req.phone is None
            and req.deanOnly is None
            and req.classIds is None
        ):
            raise BizException.bad_request("没有需要修改的内容")

        values = _apply_profile_fields(
            db,
            target,
            real_name=req.realName,
            student_no=req.studentNo,
            phone=req.phone,
        )
        # 第三十二轮：本人改「职务范围」（纯院长 ↔ 兼班主任）。
        #
        # 只有**院长本人**能改：别的角色这一位没有意义（`dean_only` 对他们
        # 永远是 0），给他们一个开关只会让人以为自己多了什么。
        #
        # ⚠ 这是**本人给自己**开班级事务的权限，所以只对「纯院长」开放
        # （解除第三十轮加的那个限制），不给普通角色。
        if req.deanOnly is not None and target.role == DEAN_ROLE:
            values["dean_only"] = 1 if req.deanOnly else 0
        if values:
            db.execute(update(SysUser).where(SysUser.id == target.id).values(**values))
            db.refresh(target)

        # 第三十二轮：本人改「**我带的班**」。
        #
        # 「班主任」是**班**的属性（多对多）：`sys_user_class` 里
        # (我, 班) 的行 = 我能管这个班（`is_adviser=1` 才是名册上的班主任）。
        #
        # 这里是**本人说了算**（用户口径）——所以他能给自己加一个班，
        # 也就等于有了那个班的收钱/成员/任务权限。这是用户明确要的。
        #
        # ⚠ 只动**我自己**的那些行：同一个班里别的老师不受影响。
        # ⚠ 默认班自动包含在内：那是「登录落在哪个班」，
        # 要是它不在我带的班里，登录后落在一个「我不是班主任」的班上，很别扭。
        #
        # ⚠ **纯院长没有这一项**（第三十轮）：他是「只管学院、不参与班级事务」
        # 的那一种，一个班都不带。界面上这个选项对他不显示，接口这里也拦一道——
        # 「界面上没有、接口里能改」是最容易漏的那种洞。
        #
        # 第五十一轮：**一个班一个班主任，院长兼班主任也一样**。
        # 所以名额判定对「班主任 + 兼班主任院长」都生效：
        # - **显式勾选**的班已被别的班主任占着 → 400 指路「改班主任安排」；
        # - **默认班**是系统自动带上的、不是本人勾的，撞车时**静默不写名册行**
        #   （管理权不受影响——`managed_class_ids` 恒含默认班；这一行只决定
        #   名册上算不算班主任）。若这里也 400，被顶替的班主任会**永远存不了
        #   个人信息**——默认班永远在提交列表里，等于把人锁死。
        # - **已经挂着的行**保持原样：院长的「我带的班」原本就是管理行
        #   （`is_adviser=0`），重存不能顺手把他升成班主任、也不能把他挡在外面。
        if req.classIds is not None and target.role in STAFF_ROLES:
            if target.role == DEAN_ROLE and target.dean_only:
                raise BizException.forbidden(
                    "纯院长不参与班级事务，没有「我带的班」；"
                    "在「职务范围」里切回「院长 + 班主任」之后才能带班"
                )
            wanted = [int(c) for c in req.classIds]
            alive: list[int] = []
            if wanted:
                alive = [
                    int(cid)
                    for (cid,) in db.execute(
                        select(ClsClass.id).where(
                            ClsClass.id.in_(wanted), ClsClass.status == 1
                        )
                    )
                ]
            if target.class_id not in alive:
                alive.append(target.class_id)
            # 院长兼班主任与班主任同权同额，所以「占不占名额」对两者都算。
            occupies_slot = target.role == "TEACHER" or (
                target.role == DEAN_ROLE and not target.dean_only
            )
            kept: list[tuple[int, int]] = []
            if occupies_slot:
                current = {
                    int(cid): int(flag)
                    for cid, flag in db.execute(
                        select(SysUserClass.class_id, SysUserClass.is_adviser).where(
                            SysUserClass.user_id == target.id
                        )
                    )
                }
                for cid in alive:
                    if cid in current:
                        # 已经挂着的：保持原样（重存不能把自己挡在外面，也不算新增）
                        kept.append((cid, current[cid]))
                        continue
                    msg = _teacher_conflict_msg(
                        db, cid, exclude_user_id=target.id, action="修改「我带的班」"
                    )
                    if msg is None:
                        kept.append((cid, 1))
                    elif cid == target.class_id:
                        continue  # 默认班撞车：静默不占名册位（见上）
                    else:
                        raise BizException.bad_request(msg)
            else:
                # 班长/生活委员/管理员：能管班，但不是「班主任」，不占名额
                kept = [(cid, 0) for cid in alive]
            db.execute(delete(SysUserClass).where(SysUserClass.user_id == target.id))
            for cid, flag in kept:
                db.add(
                    SysUserClass(user_id=target.id, class_id=cid, is_adviser=flag)
                )
            db.flush()
        # 第五十一轮：切成**纯院长** = 不再担任任何班的班主任（管理行保留）。
        if req.deanOnly is not None and target.role == DEAN_ROLE and req.deanOnly:
            db.execute(
                update(SysUserClass)
                .where(
                    SysUserClass.user_id == target.id,
                    SysUserClass.is_adviser == 1,
                )
                .values(is_adviser=0)
            )
        return account_vo(target, managed_class_ids(db, target.id, target.role, target.class_id))


def _count(db: Session, model, *conds) -> int:
    return db.scalar(select(func.count()).select_from(model).where(*conds)) or 0


def _reference_reasons(db: Session, target: SysUser) -> list[str]:
    """这个账号被哪些历史数据引用着（删除前的闸门）。空列表 = 零引用，可删。

    抽出来给**单条删除**和**批量删除**共用——两处各写一份必然漂移，
    而漂移的后果是「单条删不掉、批量却删掉了」这种查不动的账。
    """
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
    n_batch = _count(db, FeeBatch, FeeBatch.created_by == target.id)
    if n_batch:
        refs.append(f"{n_batch} 个收费批次")
    return refs


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

        refs = _reference_reasons(db, target)
        if refs:
            raise BizException.bad_request(
                f"该成员已关联{'、'.join(refs)}，不能删除；可停用账号以保留历史记录"
            )

        db.delete(target)


# =====================================================================
# 批量管理账号（第四十四轮）
# =====================================================================
# 用户口径：一个班几十上百个账号，毕业后要整批停用、清误建账号要整批删，
# 一条条点「编辑 → 停用 → 保存」点到手抽筋。批量只放**同一个值套到 N 个人**
# 身上的动作；改姓名/学号那种逐人不同的字段不进批量（容易把 N 个人改成同名）。

#: 批量动作 -> 中文名（回执、日志、提示共用一份措辞）
BATCH_ACTIONS: dict[str, str] = {
    "disable": "停用",
    "enable": "启用",
    "delete": "删除",
    "resetPassword": "重置密码",
}

#: 一次最多处理多少人。不是安全边界（真正的边界是权限），
#: 只是防止一次误点几千行把请求拖死——真有那么多也该分批做。
BATCH_MAX = 500


def batch_users(
    db: Session,
    user: LoginUser,
    *,
    action: str,
    user_ids: list[int],
    password: str | None = None,
) -> dict:
    """批量停用 / 启用 / 删除 / 重置密码。

    ## 规则与单条操作**完全同口径**（`update_user` / `delete_user`）

    - 目标必须在**我能管的班**里
    - 不能操作**自己**（停用自己 = 把自己锁在门外）
    - 权限等级护栏：操作者必须**严格高于**目标（否则班长能停掉班主任）
    - 删除只对**零引用**账号生效

    ## 「能做就做，做不了的跳过并说明」

    批量删除如果「有一条删不了就整批不执行」，用户会看到
    「点了没反应」——而他真正想要的是把能清的清掉。
    所以逐条判定：能做的做，做不了的记下原因，最后一起汇报。
    """
    if action not in BATCH_ACTIONS:
        raise BizException.bad_request("不支持的批量操作")
    ids = list(dict.fromkeys(int(i) for i in user_ids))
    if not ids:
        raise BizException.bad_request("请先勾选要操作的成员")
    if len(ids) > BATCH_MAX:
        raise BizException.bad_request(f"一次最多处理 {BATCH_MAX} 人，请分批操作")

    with db.begin():
        targets = {
            u.id: u
            for u in db.scalars(select(SysUser).where(SysUser.id.in_(ids))).all()
        }
        managed = managed_class_ids(db, user.id, user.role, user.class_id)

        # 逐条判定：能做的做，做不了的记原因（不因为一条卡住整批）
        skipped: list[dict] = []
        to_update: list[int] = []
        to_delete: list[SysUser] = []
        values: dict | None = None
        if action == "disable":
            values = {"status": 0}
        elif action == "enable":
            values = {"status": 1}
        elif action == "resetPassword":
            # 运营动作：统一重置成初始密码，无需原密码（和个人「改密码」不是一条路）
            values = {"password": hash_password(password or DEFAULT_INITIAL_PASSWORD)}

        for uid in ids:
            target = targets.get(uid)
            if target is None or target.class_id not in managed:
                skipped.append({"userId": uid, "reason": "成员不存在"})
                continue
            if target.id == user.id:
                skipped.append({"userId": uid, "reason": "不能操作自己的账号"})
                continue
            # 护栏和单条一致：等级相同/更低一律不许动（否则班长能停掉班主任）
            if role_level(user.role) <= role_level(target.role):
                skipped.append({"userId": uid, "reason": "权限不足，不能操作该账号"})
                continue
            if action == "delete":
                refs = _reference_reasons(db, target)
                if refs:
                    skipped.append(
                        {
                            "userId": uid,
                            "reason": f"已关联{'、'.join(refs)}，不能删除；可停用保留历史",
                        }
                    )
                    continue
                to_delete.append(target)
            else:
                to_update.append(uid)

        if values and to_update:
            db.execute(update(SysUser).where(SysUser.id.in_(to_update)).values(**values))
        for target in to_delete:
            db.delete(target)

        changed = len(to_update) + len(to_delete)

    return {
        "action": action,
        "actionText": BATCH_ACTIONS[action],
        "requested": len(ids),
        "changed": changed,
        "skipped": skipped,
        # 只有重置密码才回这个，别的动作给 null（前端不会拿它去显示）
        "password": (password or DEFAULT_INITIAL_PASSWORD)
        if action == "resetPassword"
        else None,
    }


# =====================================================================
# 第二十五轮追加：按学生信息一键创建登录账号
# =====================================================================
# 老师导入 Excel 名单之后，本来还要去「成员管理」一条条敲几十个账号。
# 这里把「学生信息里的一行」直接变成「一个能登录的账号」，学号即登录名。
#
# 用户口径（本轮问过，四条）：
#   建哪些      = 一次建全部可建的（不需要逐个勾选）
#   初始密码    = 全部用默认 123456
#   已有账号    = 顺便自动挂接，不重复建
#   谁能点      = 仅班主任


def _plan_from_students(db: Session, user: LoginUser) -> dict:
    """把每一行学生记录分类成「建 / 挂接 / 跳过」。**不写任何库**。

    预演（preview）和真建（create）**共用这一份分类逻辑**——这是刻意的：
    分成两份的话，弹窗里说「将新建 35 个」、点下去却建了 34 个，
    用户没法判断是预览错了还是中间又变了。预览和执行之间唯一的差别
    是本函数有没有被调用去写库。

    判定顺序有讲究：先排除「数据本身就建不出账号」的（学号超长、缺姓名），
    再看「已经有账号了」，最后才轮到「这个学号和别人撞了」。
    前两类不管顺序都会跳过，但放前面能让给用户的提示更贴近真正的原因。
    """
    records = (
        db.execute(
            select(StudentRecord)
            .where(StudentRecord.class_id == user.class_id)
            .order_by(StudentRecord.student_no)
        )
        .scalars()
        .all()
    )
    if not records:
        return {"create": [], "link": [], "skip": []}

    # 登录名是**全局**唯一（uk_username），所以占用检查必须跨班级查；
    # 只查本班会和别的班撞车，撞了就是「账号已存在」500。
    all_users = db.execute(select(SysUser)).scalars().all()
    by_sno: dict[str, list[SysUser]] = {}
    by_username: dict[str, SysUser] = {}
    for u in all_users:
        if u.student_no:
            by_sno.setdefault(u.student_no, []).append(u)
        by_username[u.username] = u
    live_ids = {u.id for u in all_users}

    create: list[dict] = []
    link: list[dict] = []
    skip: list[dict] = []

    def why(sno: str, name: str, reason: str) -> None:
        skip.append({"studentNo": sno, "name": name, "reason": reason})

    for r in records:
        sno = (r.student_no or "").strip()
        name = (r.name or "").strip()

        # 学号/姓名都是**保证非空**的，这里不判空：手工新增走 `StudentRecordCreate`
        # 的 `_not_blank`，Excel 导入在 `student_excel` 里逐行跳过空学号/空姓名，
        # 两者都到不了这一层。写一个永远走不到的分支，只会让人误以为空值是被这里挡住的。
        #
        # 但**长度**必须判：`student_record.student_no` 是 VARCHAR(32)，
        # `sys_user.student_no` 只有 20 —— 长的那些真能进库、真建不出账号。
        if len(sno) > MAX_STUDENT_NO_LEN:
            # 不截断：截出来的学号是个错号，回头会和另一行撞
            why(sno, name, f"学号超过 {MAX_STUDENT_NO_LEN} 位，登录账号存不下")
            continue

        # 已经挂着有效账号：不动它。这一行最常见——老师可能早就手工建过
        if r.user_id and r.user_id in live_ids:
            why(sno, name, "已经挂接账号了")
            continue

        # 学号已经对应某个账号 -> 挂接。这是「上学期建过」的典型情形
        hit = by_sno.get(sno, [])
        if len(hit) == 1:
            link.append(
                {
                    "recordId": r.id,
                    "userId": hit[0].id,
                    "studentNo": sno,
                    "name": name,
                    "username": hit[0].username,
                    "backfill": False,
                }
            )
            continue
        if len(hit) > 1:
            # 服务层一直拦着同班同学号，这种脏数据只可能是历史遗留或手改过库
            why(sno, name, f"本班有 {len(hit)} 个账号的学号都是这个，没法判断该挂哪个")
            continue

        # 登录名撞上了：优先当成「手工建过、只是没填学号」，挂上并把学号补齐
        occupied = by_username.get(sno)
        if occupied is not None:
            if occupied.class_id == user.class_id and not occupied.student_no:
                link.append(
                    {
                        "recordId": r.id,
                        "userId": occupied.id,
                        "studentNo": sno,
                        "name": name,
                        "username": occupied.username,
                        "backfill": True,  # 顺手把学号回填给这个账号
                    }
                )
            elif occupied.class_id == user.class_id:
                why(sno, name, f"登录名「{sno}」已被账号「{occupied.real_name}」占用")
            else:
                why(sno, name, f"登录名「{sno}」被别的班级占用了")
            continue

        create.append({"recordId": r.id, "studentNo": sno, "name": name})

    return {"create": create, "link": link, "skip": skip}


def _plan_view(plan: dict, *, executed: bool) -> dict:
    """把内部计划转成前端要的形状（预演和执行结果共用）。"""
    create, link, skip = plan["create"], plan["link"], plan["skip"]
    return {
        "executed": executed,
        "total": len(create) + len(link) + len(skip),
        "toCreate": len(create),
        "toLink": len(link),
        "toSkip": len(skip),
        # 将要建的那些（预演时也要给）：老师得能在点之前**逐个核对**，
        # 只给一个数字的话没法确认「要建的到底是哪几个」。
        # 顺带让「预演说建哪些、执行就建哪些」这条可被断言——否则两边各算各的，
        # 界面上显示的数字和实际建出来的人对不上，谁也发现不了。
        "toCreateList": [{"studentNo": x["studentNo"], "name": x["name"]} for x in create],
        "created": [
            {"id": u["id"], "username": u["username"], "realName": u["real_name"]}
            for u in (plan.get("createdUsers") or [])
        ],
        "linked": [
            {
                "userId": x["userId"],
                "studentNo": x["studentNo"],
                "name": x["name"],
                "username": x["username"],
                "backfilled": bool(x.get("backfill")),
            }
            for x in link
        ],
        "skipped": skip,
        "initialPassword": DEFAULT_INITIAL_PASSWORD,
    }


#: 「按学生信息一键建号」的最低等级 = 班主任（第三十一轮起含院长）。
#: 两个入口（预演 / 执行）共用这一道闸——分开写过一次，结果两边文案漂了。
ACCOUNT_PLANNER_MIN_LEVEL = role_level("TEACHER")


def _require_account_planner(user: LoginUser) -> None:
    """只有班主任及以上能按学生信息建号。用等级判定，院长(4) 自然包含。"""
    if role_level(user.role) < ACCOUNT_PLANNER_MIN_LEVEL:
        raise BizException.forbidden("只有班主任及以上可以按学生信息创建账号")


def preview_accounts_from_students(db: Session, user: LoginUser) -> dict:
    """预演：看一眼会建什么、挂什么、跳过什么。**一个字节都不写。**"""
    _require_account_planner(user)
    return _plan_view(_plan_from_students(db, user), executed=False)


def create_accounts_from_students(db: Session, user: LoginUser) -> dict:
    """真建。角色一律 `MEMBER`——班长/生活委员这种角色由老师在成员管理里单独指定。

    批量建出来一律给 MEMBER 是有意的：这里的输入是**一份名单**，不是一次
    职务任免。万一这批人里有班长，让他自己去成员管理里改角色，也不会出错。

    两条容易踩的实现细节，都在这儿被显式处理了：

    1. **计划必须在事务里算**。在 `with db.begin():` 之前先查一次库，SQLAlchemy
       会隐式开一个事务，随后 `db.begin()` 直接抛
       `InvalidRequestError: A transaction is already begun`。这正是本仓库
       所有写接口把读也包进 `db.begin()` 的原因。
    2. **结果要在事务里转成普通 dict**。`db.begin()` 退出时对象上的属性被标记为过期，
       之后再读 `u.id` 会触发一次懒加载查询——在已经收掉的 session 上会炸。
    """
    _require_account_planner(user)

    created: list[dict] = []
    with db.begin():
        plan = _plan_from_students(db, user)
        for item in plan["create"]:
            u = SysUser(
                class_id=user.class_id,
                username=item["studentNo"],  # 学号即登录名，和成员管理里新建 MEMBER 一致
                password=hash_password(DEFAULT_INITIAL_PASSWORD),
                real_name=item["name"],
                student_no=item["studentNo"],
                role="MEMBER",
                status=1,
            )
            db.add(u)
            db.flush()  # 拿到自增 id
            created.append({"id": u.id, "username": u.username, "real_name": u.real_name})
            db.execute(
                update(StudentRecord)
                .where(StudentRecord.id == item["recordId"])
                .values(user_id=u.id)
            )
        for item in plan["link"]:
            db.execute(
                update(StudentRecord)
                .where(StudentRecord.id == item["recordId"])
                .values(user_id=item["userId"])
            )
            if item.get("backfill"):
                # 登录名撞上但学号空着的那种：顺手补齐，否则它下次还会撞一次
                db.execute(
                    update(SysUser)
                    .where(SysUser.id == item["userId"])
                    .values(student_no=item["studentNo"])
                )

    plan["createdUsers"] = created
    return _plan_view(plan, executed=True)
