"""班级任务的 Excel 导出（第二十五轮）。

只导**明细**（谁填了什么、谁还没填），因为任务列表页给所有人看的都只是汇总，
明细是发布人/班主任才有权看的那一份——导出的口径必须和 `/detail` 一致，
否则就成了绕过 403 的越权口子。

导出前先过一次 `task_service.get_detail`：权限判定只有那一处，
这里不再重复实现「谁能看」的规则。
"""
from __future__ import annotations

from datetime import datetime
from io import BytesIO
from urllib.parse import quote

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from ..security import LoginUser
from . import task_service as svc

_TITLE_FONT = Font(bold=True, size=14)
_HEAD_FONT = Font(bold=True, color="FFFFFF")
_HEAD_FILL = PatternFill("solid", fgColor="4A7EBB")
_MUTED_FONT = Font(size=10, color="666666")

ROLE_TEXT = {
    "TEACHER": "班主任",
    "MONITOR": "班长",
    "ADMIN": "生活委员",
    "MEMBER": "普通成员",
    "GUEST": "访客",
}


def export_detail(db: Session, user: LoginUser, task_id: int) -> tuple[bytes, str]:
    """导出某个任务的全班回答。权限由 get_detail 把关（无权会抛 403）。"""
    detail = svc.get_detail(db, user, task_id)
    rows = detail["rows"]

    wb = Workbook()
    ws = wb.active
    ws.title = "任务回答"

    ws.cell(row=1, column=1, value=f"{detail['title']} · 导出 {datetime.now():%Y-%m-%d %H:%M}").font = _TITLE_FONT
    ws.cell(
        row=2,
        column=1,
        value=(
            f"题目：{detail['question']}（{detail['qtypeText']}）　"
            f"已填 {detail['answered']} / 共 {detail['unanswered'] + detail['answered']} 人"
            + (f"　带说明 {detail['noteCount']} 条" if detail["allowText"] else "")
        ),
    ).font = _MUTED_FONT

    headers = ["姓名", "登录名", "角色", "是否已填", "答案", "补充说明", "提交时间"]
    for i, label in enumerate(headers, start=1):
        c = ws.cell(row=3, column=i, value=label)
        c.font = _HEAD_FONT
        c.fill = _HEAD_FILL
        c.alignment = Alignment(horizontal="center")
        ws.column_dimensions[get_column_letter(i)].width = 16 if i != 5 else 28

    for r_i, r in enumerate(rows, start=4):
        # 未填的人排在前面（service 已排好序），导出保持同一顺序，便于对照催交
        ws.cell(row=r_i, column=1, value=r["name"])
        ws.cell(row=r_i, column=2, value=r["username"])
        ws.cell(row=r_i, column=3, value=ROLE_TEXT.get(r["role"], r["role"]))
        ws.cell(row=r_i, column=4, value="是" if r["answered"] else "未填")
        ws.cell(row=r_i, column=5, value=r["value"] or "")
        ws.cell(row=r_i, column=6, value=r["note"] or "")
        ws.cell(row=r_i, column=7, value=r["submittedAt"] or "")

    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue(), f"{detail['title']}-回答.xlsx"


def xlsx_response(pair: tuple[bytes, str]):
    """包成带附件头的 HTTP 响应。

    中文文件名必须走 RFC 5987 的 `filename*`，否则浏览器拿到乱码——
    与 students 的导出同一套处理。
    """
    from fastapi.responses import Response

    content, filename = pair
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": (
                f'attachment; filename="tasks.xlsx"; filename*=UTF-8\'\'{quote(filename)}'
            )
        },
    )