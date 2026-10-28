"""学生信息 HTTP 层（第二十三轮）。

权限分工（细则在 `student_service` 的模块 docstring）：

| 端点 | 权限 |
|------|------|
| GET  /api/students | 全员；**返回体已按可见范围裁剪**，没权限的人拿不到别人的学号 |
| PUT  /api/students/{id} | 需 `EDIT_OWN` / `EDIT_ALL`，班主任恒可 |
| POST /api/students/import | 班主任 / 班长 |
| GET  /api/students/template | 班主任 / 班长（模板 = 本班当前字段，填完直接导回来） |
| DELETE /api/students?ids=… | **班主任及以上**（班长能加不能删）；删行含字段值，账号不动 |
| GET  /api/students/export | 全员；导出内容 = 自己的可见范围 |
| GET/POST/PUT/DELETE /api/students/fields | 新增/改字段：班主任 / 班长 |
| GET  /api/students/accounts/preview | **仅班主任**。预演一键建账号，不写库 |
| POST /api/students/accounts | **仅班主任**。按学生信息批量建登录账号 |
| POST /api/students/requests | 全员（含申请） |
| GET  /api/students/requests | 两种含义：`mine=true` 看自己的申请；否则看收件箱（仅班主任） |
| POST /api/students/requests/{id}/handle | 仅班主任 |
| GET  /api/students/grants · DELETE ... | 仅班主任 |

中间件 `_STAFF_ROUTES` **故意不放**这些写路径：申请与查看自己那一行是**全员**动作，
拦在中间件会造成「班长连申请都提交不了」。真正的闸门在 service 层逐条判。
"""
from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.datastructures import UploadFile as StarletteUploadFile

from ..db import get_db
from ..errors import BizException
from ..responses import ok
from ..schemas import (
    FieldRetypeRequest,
    StudentAccessRequest as AccessReqModel,
    StudentExportRequest,
    StudentFieldRequest,
    StudentRecordCreate,
    StudentRecordUpdate,
)
from ..security import LoginUser, get_current_user
from ..services import student_excel, student_service as svc
from ..services import user_service

router = APIRouter(prefix="/api/students", tags=["students"])

MAX_IMPORT_BYTES = 8 * 1024 * 1024  # 名单文件 8MB 足够


# ---------------- 记录 ----------------

@router.get("")
def list_students(
    keyword: str | None = Query(None),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.list_records(db, user, keyword=keyword))


@router.get("/accounts/preview")
def preview_accounts(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """预演「按学生信息一键建账号」：将新建 / 将挂接 / 将跳过各多少、各为什么。

    声明在 `/{record_id}` 之前：路径段数不同本来不会真撞，但把字面量路径排在
    参数路径前面是这个仓库的一贯写法（见 /tasks/pinned），免得以后有人加一条
    `GET /students/{record_id}` 就把它吃掉了。

    **纯读**：一个字节都不写。建号是不可逆动作（建错了得一个个删），
    所以先让人看清楚再点。
    """
    return ok(user_service.preview_accounts_from_students(db, user))


@router.post("/accounts")
def create_accounts(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """按学生信息一键建账号（第二十五轮）。**仅班主任**。

    学号即登录名，姓名即昵称，密码统一 123456，角色一律普通成员。
    已经存在的账号不重建，而是把对应的学生行**挂接**上去——这一步能救回
    「上学期建过账号、这次导入名单没认出来」的情况。
    """
    return ok(user_service.create_accounts_from_students(db, user))


@router.post("")
def create_student(
    req: StudentRecordCreate,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """手工新增一行（不靠 Excel）。只要学号 + 姓名，其余留空后在表格里逐格填。"""
    return ok(svc.create_record(db, user, req.studentNo, req.name, req.values))


@router.put("/{record_id}")
def update_student(
    record_id: int,
    req: StudentRecordUpdate,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(
        svc.update_record(db, user, record_id, req.values or {}, req.name, req.studentNo)
    )


@router.delete("")
def delete_students(
    ids: str = Query(..., description="要删除的学生记录 id，逗号分隔（如 3,7,9）"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """从本班名册删行（可批量）。**只有班主任及以上**，班长不能删。

    删的是 `student_record` + 他填过的所有 `student_record_value`；
    **登录账号不动**（那是「成员管理」的事）。不可撤销，界面负责确认。

    用逗号串而不是请求体：`DELETE` 带 body 在中间代理上不保证透传，
    而这条路径只是若干整数，查询串足够。
    """
    return ok(svc.delete_records(db, user, _parse_ids(ids)))


def _parse_ids(raw: str) -> list[int]:
    out: list[int] = []
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            out.append(int(part))
        except ValueError:
            raise BizException.bad_request("学生 id 不合法") from None
    return out


# ---------------- Excel ----------------

@router.post("/import")
async def import_students(
    request: Request,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导入名单。**班主任 / 班长**——与「能加字段」同一档权限。"""
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以导入学生信息")
    length = request.headers.get("content-length")
    if length is not None and length.isdigit() and int(length) > MAX_IMPORT_BYTES:
        raise BizException.bad_request("文件不能超过 8MB")
    form = await request.form()
    item = form.get("file")
    if not isinstance(item, StarletteUploadFile):
        raise BizException.bad_request("请选择要导入的 Excel 文件")
    name = (item.filename or "").lower()
    if not name.endswith((".xlsx", ".xlsm")):
        raise BizException.bad_request("只支持 .xlsx 格式（旧版 .xls 请先另存为 .xlsx）")
    data = item.file.read(MAX_IMPORT_BYTES + 1)
    if len(data) > MAX_IMPORT_BYTES:
        raise BizException.bad_request("文件不能超过 8MB")
    return ok(student_excel.import_xlsx(db, user, data))


@router.get("/export")
def export_students(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """导出当前可见范围内的全部学生。"""
    return _xlsx_response(student_excel.export_xlsx(db, user))


@router.post("/export")
def export_selected(
    req: StudentExportRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """**勾选导出**：行（`recordIds`）和列（`fieldKeys`）都可以只导一部分。

    为什么不走 GET + query：id 列表可能几十个，URL 放不下也不好看，
    而且 id 放 URL 里会被浏览历史和代理日志记下来。

    服务层会把不在可见范围内的 id 过滤掉——否则"按 id 导出"就成了
    绕过可见性去偷看别人行的口子。
    """
    ids = [int(i) for i in (req.recordIds or [])][:500]
    keys = [str(k) for k in (req.fieldKeys or [])][:200]
    if not ids and not keys:
        raise BizException.bad_request("请先勾选要导出的学生或字段")
    return _xlsx_response(
        student_excel.export_xlsx(db, user, only_ids=ids or None, only_fields=keys or None)
    )


@router.get("/template", summary="下载导入模板（列 = 本班当前字段）")
def download_template(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """下载**今天这张表的列**，填完直接传回 `/students/import`。

    权限和导入同一档（班主任 / 班长 / 院长）：模板里只有列名、没有学生数据，
    但给一个导不进来的人发模板没有意义。
    """
    if user.role not in svc.FIELD_ADD_ROLES:
        raise BizException.forbidden("只有班主任或班长可以下载导入模板")
    return _xlsx_response(student_excel.template_xlsx(db, user))


def _xlsx_response(pair: tuple[bytes, str]) -> Response:
    content, filename = pair
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            # 中文文件名必须用 RFC 5987 的 filename*，否则浏览器拿到乱码
            "Content-Disposition": (
                f"attachment; filename=\"students.xlsx\"; "
                f"filename*=UTF-8''{quote(filename)}"
            )
        },
    )


# ---------------- 字段 ----------------

@router.get("/fields")
def list_fields(
    includeDisabled: bool = Query(
        False, description="带上已停用的字段（「已停用字段」面板要用）"
    ),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.list_fields(db, user, include_disabled=includeDisabled))


@router.post("/fields")
def create_field(
    req: StudentFieldRequest,
    beforeKey: str | None = Query(
        None, description="插在哪一列之前；空 = 追加到末尾"
    ),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.create_field(db, user, req, before_key=beforeKey))


@router.put("/fields/{field_key}")
def update_field(
    field_key: str,
    req: StudentFieldRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改字段显示名 / 类型 / 排序。**按字段标识 key 定位**，和删除同一个入口。

    模板字段现在也能改（以前只有自定义字段能），理由同 `delete_field`。
    """
    return ok(svc.update_field(db, user, field_key, req))


@router.get("/fields/{field_key}/retype-preview")
def preview_retype(
    field_key: str,
    toType: str = Query(..., description="要改成的新类型"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """改类型前先预览会发生什么。**不写库。**

    改类型要同步转换已填的值，有的值转不了（"待缴"没法变日期）。
    先把这笔账摊开给用户看，确认了再调 apply 那个接口。
    """
    return ok(svc.preview_field_retype(db, user, field_key, toType))


@router.post("/fields/{field_key}/retype")
def apply_retype(
    field_key: str,
    payload: FieldRetypeRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """确认改类型，并把存量值一并转换。"""
    return ok(
        svc.apply_field_retype(
            db, user, field_key, payload.toType, clear_bad=payload.clearUnconvertible
        )
    )


@router.post("/fields/{field_key}/restore")
def restore_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把停用的字段重新启用。软删保住了值，这条路是误删的退路。"""
    return ok(svc.restore_field(db, user, field_key))


@router.delete("/fields/{field_key}")
def delete_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """停用字段（软删）。**按字段标识 key 定位**，不按 id——表格里每列的按钮拿到的就是 key。

    模板字段也允许停用；值一律保留，可用 `POST /fields/{key}/restore` 找回。
    """
    return ok(svc.delete_field(db, user, field_key))


@router.delete("/fields/{field_key}/purge", summary="彻底删除已停用的字段（含值）")
def purge_field(
    field_key: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """彻底删除**已停用**的字段：字段行连同它名下的所有值一起删，不可恢复。

    只对已停用（status=0）的字段放行——先停用、再彻底删除，两步保护。
    误删想找回走 `POST /fields/{key}/restore`（在彻底删除之前都有效）。
    """
    return ok(svc.purge_field(db, user, field_key))


# ---------------- 申请与审批 ----------------

@router.post("/requests")
def create_request(
    req: AccessReqModel,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.create_request(db, user, req.scope, req.reason))


@router.get("/requests")
def list_requests(
    mine: bool = Query(False, description="true=看自己的申请；否则看待审批收件箱（仅班主任）"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if mine:
        return ok(svc.my_requests(db, user))
    return ok(svc.pending_requests(db, user))


@router.post("/requests/{request_id}/handle")
def handle_request(
    request_id: int,
    req: AccessReqModel,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.handle_request(db, user, request_id, req.approve, req.reply))


@router.get("/grants")
def list_grants(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.list_grants(db, user))


@router.delete("/grants/{target_user_id}/{scope}")
def revoke_grant(
    target_user_id: int,
    scope: str,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc.revoke_grant(db, user, target_user_id, scope)
    return ok()


@router.get("/pending-count")
def pending_count(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """顶栏红点用。班主任返回待审批条数，其它角色恒为 0。"""
    return ok({"count": svc.pending_count(db, user)})