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
from ..models import FeeBatch, FeePayment, FeeRecord, StudentRecord, SysUser
from ..schemas import ProfileUpdateRequest, UserCreateRequest, UserUpdateRequest
from ..security import (
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


def account_vo(u: SysUser) -> dict:
    return {
        "id": u.id,
        "username": u.username,
        "realName": u.real_name,
        "studentNo": u.student_no,
        "phone": u.phone,
        "role": u.role,
        # 只有访客用得上；非访客一律给 null，别让前端对每个角色都判一遍
        "guestScopes": parse_guest_scopes(u.guest_scopes) if u.role == GUEST_ROLE else None,
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
        # 第二十六轮：访客的「可见范围」。只对访客有意义，其他角色一律 NULL，
        # 免得库里躺着一堆永远不会被读的 JSON。
        guest_scopes = dump_guest_scopes(req.guestScopes) if role == GUEST_ROLE else None
        # 第十五轮：新建账号的**角色等级不得高于操作者**。
        # 这是等级体系的唯一提权入口——不改角色的接口（PUT /users/{id} 不含 role），
        # 但「新建一个班主任账号再登进去」能绕开所有护栏，所以必须在这里拦。
        if role_level(role) > role_level(user.role):
            raise BizException.bad_request(
                "权限不足：不能创建权限高于自己的账号"
            )
        # 第二十四轮：访客**只由班主任创建**（用户原话「访客权限由班主任创建」）。
        # 等级校验拦不住这条——GUEST 和 MEMBER 同为 0 级，班长等级高、反而"能建"。
        # 但访客是给领导/校方开的只读账号，属于"对外"的口子，
        # 不该由班长随手开一个。
        if role == "GUEST" and user.role != "TEACHER":
            raise BizException.forbidden("访客账号只能由班主任创建")
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
            and req.guestScopes is None
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
        n_batch = _count(db, FeeBatch, FeeBatch.created_by == target.id)
        if n_batch:
            refs.append(f"{n_batch} 个收费批次")
        if refs:
            raise BizException.bad_request(
                f"该成员已关联{'、'.join(refs)}，不能删除；可停用账号以保留历史记录"
            )

        db.delete(target)


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


def preview_accounts_from_students(db: Session, user: LoginUser) -> dict:
    """预演：看一眼会建什么、挂什么、跳过什么。**一个字节都不写。**"""
    if user.role != "TEACHER":
        raise BizException.forbidden("只有班主任可以按学生信息创建账号")
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
    if user.role != "TEACHER":
        raise BizException.forbidden("只有班主任可以按学生信息创建账号")

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
