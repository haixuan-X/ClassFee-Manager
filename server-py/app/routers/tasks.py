"""班级任务 HTTP 层（第二十五轮）。

权限分工（细则在 `task_service` 的模块 docstring）：

| 端点 | 权限 |
|------|------|
| GET  /api/tasks | 全员（含访客）。**只到汇总为止**，不含别人的答案 |
| GET  /api/tasks/pinned | 全员。仪表盘面板用，形状与列表一致 |
| POST /api/tasks | 班主任 / 班长 |
| PUT  /api/tasks/{id} · .../close · .../reopen · .../pin · .../unpin · DELETE | **仅发布人自己** |
| PUT  /api/tasks/{id}/answer | 全员；**班主任与访客除外**（都不是被统计的同学） |
| GET  /api/tasks/{id}/detail | **仅发布人和班主任**（唯一出现别人答案的出口） |
| GET  /api/tasks/{id}/export | 同 detail |

中间件 `_STAFF_ROUTES` **故意不放**这里任何一条：填答案是**全员**动作，
拦在中间件会造成「同学连任务都答不了」。真正的闸门逐条在 service 层判。
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from ..db import get_db
from ..responses import ok
from ..schemas import TaskAnswerRequest, TaskCreateRequest, TaskUpdateRequest
from ..security import LoginUser, get_current_user, require_min_level
from ..services import task_excel, task_service as svc

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# ---------------- 读 ----------------


@router.get("")
def list_tasks(
    view: str = Query("mine", description="mine=本班+学院；college=只看学院；other=其他班"),
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(
        {
            "rows": svc.list_tasks(db, user, view),
            # 发布权限随列表一起下发：前端据此决定要不要显示「发布任务」按钮。
            # 这只是决定按钮显不显示，真正的闸门在 create_task。
            "canPublish": svc.can_publish(user),
            # 第三十二轮：能不能发**学院任务**（只有院长）
            "canPublishCollege": user.role == "DEAN",
            "view": view,
        }
    )


@router.get("/overview")
def task_overview(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """任务总览（第三十二轮）：统计「现在什么状况」。

    声明在 `/{task_id}/...` 那几条**之前**（段数不同本来不会真撞，
    但把字面量路径排在参数路径前面是这个仓库的一贯写法）。

    ⚠ **只有院长能看**（用户口径）：它是「学院」这一组里的一页，
    而「学院」除了院长谁都不展示。侧栏不给入口、路由也弹回仪表盘，
    后端这里再硬拦一道——手输 URL / 直接调接口都绕不过去。
    """
    require_min_level(user, "DEAN", "任务总览")
    return ok(svc.overview(db, user))


@router.get("/overview/export", summary="导出任务总览（所有任务一览）")
def export_overview(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """把任务总览导出成 Excel。仅院长。"""
    require_min_level(user, "DEAN", "任务总览导出")
    return task_excel.xlsx_response(task_excel.export_overview(db, user))


@router.get("/pinned")
def pinned_tasks(
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """仪表盘「置顶任务」面板的数据源。

    声明在 `/{task_id}/...` 那几条**之前**：段数不同本来不会真撞，但把字面量路径
    排在参数路径前面是这个仓库的一贯写法（见 /users、/records），免得以后有人
    加一条 `GET /tasks/{task_id}` 就把它吃掉了。
    """
    return ok({"rows": svc.pinned_tasks(db, user)})


@router.get("/{task_id}/detail")
def task_detail(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """谁填了什么、谁还没填。**仅发布人和班主任**——非发布人拿 403。"""
    return ok(svc.get_detail(db, user, task_id))


@router.get("/{task_id}/export")
def export_detail(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return task_excel.xlsx_response(task_excel.export_detail(db, user, task_id))


# ---------------- 写 ----------------


@router.post("")
def create_task(
    req: TaskCreateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(
        svc.create_task(
            db, user,
            title=req.title or "",
            question=req.question or "",
            qtype=req.qtype or "BOOLEAN",
            options=req.options,
            allow_text=bool(req.allowText),
            deadline=req.deadline,
            # 第三十二轮：scope=COLLEGE 就是**学院任务**（只有院长能发）
            scope=req.scope or "CLASS",
        )
    )


@router.put("/{task_id}")
def update_task(
    task_id: int,
    req: TaskUpdateRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(
        svc.update_task(
            db, user, task_id,
            title=req.title or "",
            question=req.question or "",
            deadline=req.deadline,
            status=req.status,
            allow_text=bool(req.allowText),
        )
    )


@router.post("/{task_id}/close")
def close_task(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.set_status(db, user, task_id, False))


@router.post("/{task_id}/reopen")
def reopen_task(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.set_status(db, user, task_id, True))


@router.post("/{task_id}/pin")
def pin_task(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """置顶：出现在所有人仪表盘的「置顶任务」里。**仅发布人自己**。"""
    return ok(svc.set_pinned(db, user, task_id, True))


@router.post("/{task_id}/unpin")
def unpin_task(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return ok(svc.set_pinned(db, user, task_id, False))


@router.put("/{task_id}/answer")
def submit_answer(
    task_id: int,
    req: TaskAnswerRequest,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """提交或修改**自己**的答案（一人一任务一条）。访客 403。"""
    return ok(svc.submit_answer(db, user, task_id, req.value, req.note))


@router.delete("/{task_id}")
def delete_task(
    task_id: int,
    user: LoginUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    svc.delete_task(db, user, task_id)
    return ok()