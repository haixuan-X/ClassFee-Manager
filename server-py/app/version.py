"""应用版本：**整个项目唯一的版本号真相源**。

为什么放在后端而不是只写在前端 `package.json` 里：

- 后端才是对外契约的一方。接口加了字段、语义变了，该 bump 的是**后端**版本，
  前端跟着对齐。版本号写在 `package.json` 里，前端改了接口就没人记得同步。
- 「当前跑的是哪一版」这个问题，只有后端能权威回答——部署了三个副本、
  前端缓存着旧 bundle 时，浏览器里的版本号是骗人的。

所以规则是：**改版本号只改这一个常量**，前端通过 `GET /api/version` 读它。
`web/package.json` 的 `version` 字段同步改，但**只作为漂移检测的锚**——
回归里有一条断言专门盯着它不一致（见 `tests/api_regression.py` 的
`test_a19_version`），因为两处手写迟早会忘。

## 语义化版本（SemVer 2.0.0）：MAJOR.MINOR.PATCH

| 位 | 什么时候加 |
|---|---|
| MAJOR | 不向后兼容的改动：删接口、改字段名/含义、收紧权限导致旧客户端直接崩 |
| MINOR | 向后兼容的新增：新接口、新可选字段、新页面 |
| PATCH | 向后兼容的修bug：不改契约的行为修正 |

**不要因为「加了很多功能」就动 MAJOR**——SemVer 量的是兼容性影响，不是功能数量。
本项目从初版到 1.1.0 全是增量（学生信息、班级任务、访客范围、一键建号都是新加的，
既有端点的字段和语义一个没动），所以只走 MINOR。
"""
from __future__ import annotations

import re

#: 对外展示的应用名。界面页脚用它和版本号一起显示（`版本号 + 应用名` 缺一不可，
#: 光一个 "1.1.0" 看不出是什么东西的版本）。
APP_NAME = "学生信息管理系统"

#: 语义化版本号。**改版本只改这一行。**
VERSION = "1.1.0"

#: 语义化版本 + 可选的预发布/构建后缀，如 `1.2.0-rc.1`、`1.2.0+20261019`。
#: 拆开是为了让前端能显示 `1.2.0-rc.1` 而不是把它当数字。
_SEMVER = re.compile(
    r"^(?P<major>0|[1-9]\d*)\.(?P<minor>0|[1-9]\d*)\.(?P<patch>0|[1-9]\d*)"
    r"(?:-(?P<pre>[0-9a-z.-]+))?"
    r"(?:\+(?P<build>[0-9a-z.-]+))?$",
    re.IGNORECASE,
)


def parse_version(raw: str = VERSION) -> tuple[int, int, int, str | None, str | None]:
    """拆版本号。格式不合法直接抛——版本号写错必须**响亮地失败**。

    静默兜底成 0.0.0 的后果是：线上跑着坏版本号，日志和界面都显示 "0.0.0"，
    排查时根本想不起来版本常量被改坏了。
    """
    m = _SEMVER.match(raw.strip())
    if not m:
        raise ValueError(
            f"版本号 {raw!r} 不符合语义化版本（MAJOR.MINOR.PATCH[-预发布][+构建]）"
        )
    return (
        int(m["major"]),
        int(m["minor"]),
        int(m["patch"]),
        m["pre"],
        m["build"],
    )


def version_info() -> dict:
    """给 `GET /api/version` 用的结构。"""
    major, minor, patch, pre, build = parse_version()
    return {
        "appName": APP_NAME,
        "version": VERSION,
        "major": major,
        "minor": minor,
        "patch": patch,
        "preRelease": pre,
        "build": build,
    }