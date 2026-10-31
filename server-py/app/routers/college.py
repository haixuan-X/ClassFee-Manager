"""学院视角的接口（第三十轮）。

**仅院长（DEAN）**。与 `/api/dashboard/students` 同一道闸门
（`require_min_level`），理由也一样：这是校级看板/名册，班主任在
班级层已经能看到本班的全部数据，再给一份跨班的只是重复。

三条腿都要走：这里后端硬拦 403，前端**不渲染**入口（侧栏的「学院」分组
对非院长整个不出现）。
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import get_db
from ..errors import BizException
from ..responses import ok
from ..schemas import UserCreateRequest
from ..security import LoginUser, get_current_user, require_min_level
from ..services import college_excel, college_service, user_service

router = APIRouter(prefix="/api/college", tags=["college"])


class CollegeFieldRequest(BaseModel):
    """新增一列。"""

    label: str = Field(min_length=1, max_length=64)
    type: str = "TEXT"
    #: 插在哪一列旁边。`side` 决定是它前面还是后面。
    anchorKey: str | None = None
    side: str = "before"


class CollegeFieldUpdateRequest(BaseModel):
    """改一列。字段都可选（None=不改）。"""

    label: str | None = Field(default=None, max_length=64)
    type: str | None = None


class CollegeCellUpdateRequest(BaseModel):
    """就地改一格（或几格）。"""

    #: `{字段标识: 值}`。只接受该学生所在那个班里已定义的字段。
    values: dict[str, str | None] = Field(default_factory=dict)
    #: 姓名（不在字段表里，是 `student_record` 上的列）
    name: str | None = None
    #: 学号（同上；upsert 键，改了要同班不撞号）
    studentNo: str | None = None
    #: 班级名。**按名字**改：找到就转过去，找不到就**自动建一个班**。
    #:
    #: 界面上这一格就是个普通输入框（和别的列一样），用户直接打字。
    className: str | None = None


class CollegeRetypeRequest(BaseModel):
    """确认改一列的类型。"""

    toType: str
    #: True = 转不了的值置空（用户明确说「这些不要了」）；默认 False = 保留原文本
    clearBad: bool = False


class CollegeTransferRequest(BaseModel):
    """转班：把一个学生挪到另一个班。"""

    #: 目标班级 id
    classId: int


class CollegeTeachersRequest(BaseModel):
    """设置某个班的班主任（**一个班一个**，换人=顶替）。"""

    #: 班主任账号 id；null = 该班暂无班主任账号
    teacherId: int | None = None


class CollegeClassCreateRequest(BaseModel):
    """新建一个班。"""

    className: str = Field(min_length=1, max_length=64)
    grade: str = Field(default="", max_length=32)


@router.post("/classes", summary="新建一个班（空班，字段模板复制默认班）")
def create_class(
    req: CollegeClassCreateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新建班级。**仅院长**——建班是学院层的事务。

    新班是**空班**：没有学生、没有账目、没有班主任；字段模板复制建班人
    默认班那份（否则「学生信息」里只剩学号和姓名两列）。

    同名班**直接返回已有的那个**（`created=false`），不报错。
    """
    require_min_level(user, "DEAN", "新建班级")
    return ok(college_service.create_class(db, user, req.className, req.grade))


@router.get("/students", summary="学院学生名册")
def students(
    keyword: str | None = Query(None, description="学号/姓名/任意文本字段"),
    class_id: int | None = Query(None, alias="classId"),
    grade: str | None = Query(None),
    page: int = Query(1),
    size: int = Query(50),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """跨班级的学生名册 + 搜索筛选。"""
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(
        college_service.students(
            db,
            user,
            keyword=keyword,
            class_id=class_id,
            grade=grade,
            page=page,
            size=size,
        )
    )


@router.get("/students/export", summary="导出学院学生信息（可选列）")
def export_students(
    columns: str | None = Query(None, description="逗号分隔的字段标识；不给=全部"),
    ids: str | None = Query(None, description="逗号分隔的行 id；不给=全部"),
    keyword: str | None = Query(None, description="关键字（和界面一致）"),
    class_id: int | None = Query(None, alias="classId"),
    grade: str | None = Query(None),
    offset: int = Query(0, ge=0, description="从第几条开始（0 起，配合 limit 做行区间导出）"),
    limit: int | None = Query(None, ge=0, description="最多导多少条；不给=到末尾"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出学院学生信息。

    `columns` 就是界面上那个「选列导出」勾选框传过来的字段标识。
    **学号/姓名无条件保留**（一份没有学号的表没法说明每一行是谁）；
    **班级/年级听勾选**（有人导出只要学号姓名加几个字段）。

    `keyword` / `classId` / `grade` **和界面的筛选一致**——
    界面上筛出来的就该是导出来的。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    only_fields = [c for c in (columns or "").split(",") if c] or None
    only_ids = [int(i) for i in (ids or "").split(",") if i.strip().isdigit()] or None
    body, filename = college_excel.export_xlsx(
        db,
        user,
        only_ids,
        only_fields,
        keyword=keyword,
        class_id=class_id,
        grade=grade,
        offset=offset,
        limit=limit,
    )
    return Response(
        content=body,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            # 中文文件名必须用 RFC 5987 的 filename*，否则浏览器拿到乱码。
            # ⚠ 不 quote 的话这里是 UnicodeEncodeError —— HTTP 头只能放 latin-1。
            "Content-Disposition": (
                f"attachment; filename=\"college-students.xlsx\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.get("/students/template", summary="下载学院导入模板（列 = 各班字段合并）")
def download_students_template(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载学院名册的导入模板：列 = 所有启用班级的字段合并（+「班级」列）。

    每次下载都**现读字段**，所以学院里新增一列之后，重新下载就是新列——
    模板不会和表格脱节。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    body, filename = college_excel.template_xlsx(db)
    return Response(
        content=body,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={
            "Content-Disposition": (
                f"attachment; filename=\"college-students-template.xlsx\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


@router.post("/students/import", summary="导入学院学生信息")
async def import_students(
    file: UploadFile = File(...),
    classId: int | None = Query(None, description="表格没有「班级」列时的默认班"),
    unassigned: bool = Query(
        False,
        description=(
            "true=这批人先不归班（未分班），忽略「班级」列、也不自动建班；"
            "默认 false=按「班级」列分发，没有这一列就进 classId 指定的班"
        ),
    ),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导入学院学生信息。**按文件里的「班级」列分发到各班**。

    文件里没有「班级」列时，全部进 `classId` 指定的班。
    `unassigned=true` 是给「先收名单、后分班」留的口子：这批人进未分班，
    班级列和默认班都不看。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    content = await file.read()
    return ok(college_excel.import_xlsx(db, user, content, classId, unassigned=unassigned))


@router.get("/fields", summary="学院列定义（跨班合并）")
def fields(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """学院表的所有列（按 field_key 把各班的定义合并成一份）。"""
    require_min_level(user, "DEAN", "学院学生信息")
    classes = college_service._active_classes(db)
    return ok({
        "columns": college_service._unified_columns(db, [c.id for c in classes]),
        "classes": college_service._class_choices(db, classes),
    })


@router.post("/fields", summary="新增一列（所有班）")
def create_field(
    req: CollegeFieldRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增一列。

    `anchorKey` + `side` 指定插在哪：锚点列的**前面**（before）或**后面**（after）。
    不给锚点 = 追加到末尾。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(
        college_service.create_college_field(
            db,
            user,
            label=req.label,
            ftype=req.type,
            anchor_key=req.anchorKey,
            side=req.side,
        )
    )


@router.put("/fields/{field_key}", summary="改一列（所有班）")
def update_field(
    field_key: str,
    req: CollegeFieldUpdateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改一列的显示名 / 类型。"""
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(
        college_service.update_college_field(
            db, user, field_key, label=req.label, ftype=req.type
        )
    )


@router.delete("/fields/{field_key}", summary="停用一列（所有班）")
def delete_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """停用一列（软删，已填的值保留）。"""
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.delete_college_field(db, user, field_key))


@router.get("/fields/disabled", summary="已停用的列（可恢复）")
def disabled_fields(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """已停用的列（软删：值还在，只是从表格里收起来了）。

    和班级版的「已停用字段」是同一件事：**停用必须能撤销**，
    否则误停用一列就等于把那一列的历史数据永远藏起来了。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok({"columns": college_service.disabled_college_fields(db)})


@router.post("/fields/{field_key}/restore", summary="恢复一列（所有班）")
def restore_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """恢复一个被停用的列（所有班一起放回来，值原样还在）。"""
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.restore_college_field(db, user, field_key))


@router.delete("/fields/{field_key}/purge", summary="彻底删除一列（所有班，含值）")
def purge_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """彻底删除**已停用**的列：所有班的字段定义和已填的值一起删，不可恢复。"""
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.purge_college_field(db, user, field_key))


@router.get("/fields/{field_key}/retype-preview", summary="改类型前先预览")
def preview_retype(
    field_key: str,
    toType: str = Query(...),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改类型前先看一眼会发生什么。**不写库。**

    跨**所有班**汇总：这一列在每个班各有一份定义、各有各的存量值，
    只报一个班的数会骗人。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.preview_college_field_retype(db, user, field_key, toType))


@router.post("/fields/{field_key}/retype", summary="确认改类型（所有班）")
def apply_retype(
    field_key: str,
    req: CollegeRetypeRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认改类型：按预览的方案落地，所有班一起改。

    `clearBad=False`（默认）——转不了的值**保留原文本**，改错了还能改回来。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(
        college_service.apply_college_field_retype(
            db, user, field_key, req.toType, req.clearBad
        )
    )


@router.put("/students/{record_id}", summary="就地改一格（电子表格）")
def update_student(
    record_id: int,
    req: CollegeCellUpdateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改一个学生的若干格。**跨班级**——院长改哪个班的学生都行。

    `values` 是 `{字段标识: 值}`，只接受该学生所在那个班里已定义的字段。
    `name` / `studentNo` 改的是 `student_record` 上的两列（学号改名要同班不撞号）。
    `className` 改的是**班级**（按名字找班，没有就自动建一个）。

    任一格非法就**整批不落库**（表格里一次改多格很常见，写一半会让
    界面显示的和库里不一致）。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(
        college_service.update_student_cells(
            db, user, record_id, req.values, req.name, req.studentNo, req.className
        )
    )


@router.post("/students/{record_id}/transfer", summary="转班（挪到另一个班）")
def transfer_student(
    record_id: int,
    req: CollegeTransferRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把一个学生转到另一个班。

    **不是「改一格」**：值表里存的是 `field_id`，字段是按班定义的，
    所以转班必须按 `field_key` 把值搬到新班对应的字段上（见
    `college_service.transfer_student` 的说明）。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.transfer_student(db, user, record_id, req.classId))


@router.delete("/students", summary="从学院名册删行（可批量）")
def delete_students(
    ids: str = Query(..., description="要删除的学生记录 id，逗号分隔（如 3,7,9）"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """删除若干个学生（`student_record` + 他们填过的所有字段值）。

    **仅院长**：这是全校名册，班主任在班级页删本班即可，不需要跨班删。
    **登录账号不动**——账号归「成员管理」，删名册不等于销号。
    """
    require_min_level(user, "DEAN", "学院学生信息")
    return ok(college_service.delete_students(db, user, _parse_ids(ids)))


def _parse_ids(raw: str, what: str = "学生") -> list[int]:
    """`"3,7,9"` → `[3, 7, 9]`；非法片段直接 400（不静默丢掉）。"""
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            raise BizException.bad_request(f"{what} id 不合法") from None
    return out


@router.get("/deans", summary="院长账号一览（可多位）")
def deans(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """院长账号一览。

    **允许有多个院长**：系统没有「一个学院只能一位院长」的限制，
    院长之间同级、互不管理（`require_role_higher` 要求严格更高）。

    纯院长也能看：这是「再开一个院长」的入口页，属于学院事务，
    不能挂在「班级 → 成员管理」下面（那一组对纯院长整个不显示）。
    """
    require_min_level(user, "DEAN", "院长账号")
    return ok(user_service.list_deans(db))


@router.post("/deans", summary="新增院长账号（纯院长）")
def create_dean(
    req: UserCreateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """新增一位院长账号。

    与 `/api/users` 的建号走**同一套** `user_service.create_user`（校验、
    密码哈希、唯一登录名都不另写一份），只是把角色钉死成院长、默认纯院长。
    详见 `user_service.create_dean`。
    """
    require_min_level(user, "DEAN", "院长账号")
    return ok(user_service.create_dean(db, user, req))


@router.get("/advisers", summary="班主任（导员）名册")
def advisers(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """各班班主任名册。"""
    require_min_level(user, "DEAN", "学院成员管理")
    return ok(college_service.advisers(db, user))


@router.delete("/advisers", summary="批量删除班主任账号")
def delete_advisers(
    ids: str = Query(..., description="要删除的账号 id，逗号分隔（如 12,19）"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量删除**班主任账号**（不是班级）。

    用户口径：名册上勾几行就能清掉误建/离职的班主任，不用去
    「成员管理」一条条点——纯院长也没有那个入口。

    删的是登录账号本身（`sys_user` + 他的班级关联）；**班级保留**，
    名册上那个班回到「未建账号」。有流水 / 缴费 / 批次引用的账号
    会被跳过并说明原因，规则与单条删除完全一致。
    """
    require_min_level(user, "DEAN", "班主任名册")
    return ok(user_service.delete_adviser_accounts(db, user, _parse_ids(ids, "账号")))


@router.post("/advisers/import", summary="导入班主任账号（Excel）")
async def import_advisers(
    file: UploadFile = File(...),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """批量导入班主任：建号 + 关联「带的班」。仅院长。"""
    require_min_level(user, "DEAN", "导入班主任")
    content = await file.read()
    return ok(college_excel.import_advisers(db, user, content))


@router.get("/advisers/template", summary="下载班主任导入模板")
def adviser_template(
    user: LoginUser = Depends(get_current_user),
):
    """下载班主任导入模板（xlsx）。仅院长。"""
    require_min_level(user, "DEAN", "班主任导入模板")
    from urllib.parse import quote

    return Response(
        content=college_excel.adviser_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                "attachment; filename*=UTF-8''" + quote("班主任导入模板.xlsx")
            )
        },
    )


@router.get("/teacher-candidates", summary="可被选为班主任的账号")
def teacher_candidates(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """能被选为班主任的账号（第三十二轮）。"""
    require_min_level(user, "DEAN", "学院成员管理")
    return ok({"teachers": college_service.teacher_candidates(db)})


@router.put("/classes/{class_id}/teachers", summary="设置某个班的班主任")
def set_class_teachers(
    class_id: int,
    req: CollegeTeachersRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """设置某个班的班主任（**一个班一个**，换人=顶替）（第五十一轮收紧）。

    「班主任」是**班**的属性——一个老师可以带好几个班，
    这在以前「一个账号只能属于一个班」的模型里表达不出来。
    但一个班只有**一位**班主任：这里是唯一允许覆盖的入口（显式点名顶替），
    其余入口撞上已有班主任一律报错指路到这里。
    """
    require_min_level(user, "DEAN", "学院成员管理")
    return ok(college_service.set_class_teachers(db, user, class_id, req.teacherId))


@router.get("/tasks", summary="学院任务一览")
def tasks(
    keyword: str | None = Query(None),
    class_id: int | None = Query(None, alias="classId"),
    only_pinned: bool = Query(False, alias="onlyPinned"),
    scope: str = Query("ALL", description="COLLEGE=学院任务；CLASS=班主任发布的班级任务；ALL=两类都看"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """跨班级的任务一览。

    `scope` 把**学院任务**（院长发的）和**班级任务**（班主任发的）分开——
    侧栏「学院 > 任务」下面挂着这两个入口，看的是同一批任务的两类。

    ## 谁能看：**只有院长**

    「学院」这一栏（第三十二轮）除了院长谁都不展示——它是**校级视角**。
    班主任要了解其他班的任务，走「班级 → 班级任务」里的「其他班」那一档，
    不必、也不该在这里拿到全校一览。
    """
    require_min_level(user, "DEAN", "学院任务")
    return ok(
        college_service.tasks(
            db,
            user,
            keyword=keyword,
            class_id=class_id,
            only_pinned=only_pinned,
            scope=scope,
        )
    )
