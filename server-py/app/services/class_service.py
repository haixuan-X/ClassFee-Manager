"""班级信息服务：查看（全员）/ 编辑班级名·年级·班主任（仅运营角色）。

`balance` 是记账事务同步的冗余列（可用流水对账），**不开放手改**；
`status`（班级停用）当前无业务语义（系统按单班运营），同样不在此编辑。
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..errors import BizException
from ..models import ClsClass
from ..schemas import ClassInfoRequest
from ..security import ROLE_LEVEL, LoginUser, role_level
from ..serializers import class_vo


def _require_class(db: Session, class_id: int) -> ClsClass:
    clazz = db.get(ClsClass, class_id)
    if clazz is None:
        raise BizException.bad_request("班级不存在")
    return clazz


def get_class_info(db: Session, user: LoginUser) -> dict:
    return class_vo(_require_class(db, user.class_id))


def update_class_info(db: Session, user: LoginUser, req: ClassInfoRequest) -> dict:
    """字段语义：非 None 即写入；空串=清空（年级/班主任）；空 body 400。

    第十六轮补**字段级**授权：`headTeacher`（班主任）是**角色字段**，不是普通资料——
    旧实现只按「运营角色」放行，于是生活委员/班长也能把班主任姓名改成自己
    （实测 `PUT /class {"headTeacher": "Life Probe"}` 返回 200）。
    与第十五轮的账号等级一致：班主任（等级 3）及以上能写这个字段。
    班级名/年级属于班务公共信息，三个运营角色都可维护。

    ⚠ 这里判的是**等级**而不是 `role != "TEACHER"`。原实现的注释写的就是
    「等级 3」，代码却按角色名写死——两者当时恰好等价所以没人发现，
    直到第二十八轮加了院长（等级 4）才暴露：如果一个既是院长又是班主任的人
    登录进来，判角色名的话他改不了自己的班主任姓名，比他的班主任身份还低。
    「既是院长又是班主任」正是这种按角色名写死判据的照妖镜。
    """
    values: dict = {}
    if req.className is not None:
        values["class_name"] = req.className.strip()
    if req.grade is not None:
        values["grade"] = req.grade.strip() or None
    if req.headTeacher is not None:
        if role_level(user.role) < ROLE_LEVEL["TEACHER"]:
            raise BizException.forbidden("班主任姓名只能由班主任及以上修改")
        values["head_teacher"] = req.headTeacher.strip() or None
    if not values:
        raise BizException.bad_request("没有需要修改的内容")

    with db.begin():
        clazz = _require_class(db, user.class_id)
        if "class_name" in values:
            # 班级名是空库建班与人工识别的键，保持全局唯一（跨班）
            dup = (
                db.scalar(
                    select(func.count())
                    .select_from(ClsClass)
                    .where(
                        ClsClass.class_name == values["class_name"],
                        ClsClass.id != clazz.id,
                    )
                )
                or 0
            )
            if dup > 0:
                raise BizException.bad_request("班级名称已存在")
        for key, value in values.items():
            setattr(clazz, key, value)
        return class_vo(clazz)
