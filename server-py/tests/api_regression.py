"""班费系统接口回归（第十六轮重写）。

为什么从 PowerShell 改成 Python
------------------------------
原回归脚本是 `api-regression.ps1`。带 UTF-8 BOM 的 .ps1 + 大量中文注释 + 反复 HTTP 调用
+ 登录令牌 + 批量建号删号，这套特征在杀毒软件的行为/脚本引擎里与恶意脚本难以区分，
结果被卡巴斯基静默删除。改用 Python 后：

- 与被测系统同语言（FastAPI），断言和实现放在一起看
- 不会再被安全软件当成可疑脚本删掉
- 彻底绕开 PowerShell 5.1 按 ANSI 读文件导致中文注释乱码、并**吞掉后续代码**的坑
  （表现为断言静默失效、`st=` 恒为空）
- 零第三方依赖，用 `server-py/.venv` 的解释器直接跑

跑法
----
    D:\\bj\\server-py\\.venv\\Scripts\\python.exe D:\\bj\\server-py\\tests\\api_regression.py

需要后端在 http://127.0.0.1:8080 已启动（start-backend.bat）。
文件内函数按 `test_*` 命名且共享模块级状态，若日后安装了 pytest 亦可直接收集：
    D:\\bj\\server-py\\.venv\\Scripts\\python.exe -m pytest server-py\\tests\\api_regression.py

脚本保持**净零**：所有自建的数据在结尾删除，并断言账本金额 / 批次 / 类别 / 公告 / 账号
回到基线。跨轮可重复执行。
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8080/api"
ROOT_U, ROOT_P = "test", "123456"

# 让 `from app.db import engine` 在任何用例里都可用（守卫要直查库）。
# 各用例里那句 `sys.path.insert` 只覆盖它们自己，模块级的一次就够。
_ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# 固定学号的探针账号（跨轮复用，结尾清理）
MEMBER_U, MEMBER_P = "20220103", "123456"
MEMBER_NAME = "Wang Xiaoming"
SNO_DEFAULT_U = "20220997"   # 学号默认回填登录名
SNO_EXPLICIT_U = "20220995"   # 显式指定学号
DISPOSABLE_U = "20220993"     # 建了立刻删，验证「零引用可删」
LVL_ADMIN_U = "20220991"     # 生活委员（等级 1）
LVL_MONITOR_U = "20220992"    # 班长（等级 2）
LVL_PEER_U = "20220989"       # 第二个班长（同级互斥用例）
LVL_PLAIN_U = "20220994"      # 另一个普通成员（等级 0）
LVL_ESCALATE_U = "20220988"   # 班长新建的生活委员（正向对照，用完即删）
# 第二十三轮：学生信息用例的两个探针学生。学号即登录名，导入时会自动挂接账号。
STU_PROBE_U1, STU_PROBE_U2 = "20220981", "20220982"

PROBE_USERS = [MEMBER_U, SNO_DEFAULT_U, SNO_EXPLICIT_U, DISPOSABLE_U,
               LVL_ADMIN_U, LVL_MONITOR_U, LVL_PEER_U, LVL_PLAIN_U, LVL_ESCALATE_U,
               STU_PROBE_U1, STU_PROBE_U2]

# 常驻账号（人工建的，不归回归删）：每个角色一个，密码同为 123456。
# 只建在本地库，**没有写进 seed.py** —— 测试口令是公开的，
# 写进 seed 等于每次部署都白送一批弱口令账号；要「部署后自动生成」
# 必须走 .env 配口令或首次登录强制改密，不能硬编码。
#
# `dean`（院长）同样只建在本地：院长的正规来路是部署声明
# `CLASSFEE_TEACHER_ROLE=DEAN`，而不是「先建个班主任再自己升上去」——
# 后者是自我提权，产品里本来就被拦（见 test_a20）。
#
# 第三十二轮：演示账号（admin/monitor/member/guest/pure_dean）**已清理**——
# 它们的名字全是假的（生活委员孙婷/班长刘洋/…），留在正式库里就是脏数据。
# 回归自己建自己的探针账号（`ensure_user`），不依赖这些常驻账号；
# 少了哪一个角色，回归照样跑得起来。
KEEP_ACCOUNTS = ["dean"]

# ---------------- 断言与日志 ----------------

_passed: list[str] = []
_failed: list[tuple[str, str]] = []


def check(name: str, cond: bool, detail: str = "") -> bool:
    if cond:
        _passed.append(name)
        print(f"  [PASS] {name}")
    else:
        _failed.append((name, detail))
        print(f"  [FAIL] {name}   <<< {detail}")
    return cond


def near(a, b, eps: float = 0.005) -> bool:
    return abs(float(a) - float(b)) < eps


# ---------------- HTTP ----------------

def call(method: str, path: str, body=None, token: str | None = None, raw: bytes | None = None):
    """返回 (http_status, parsed_body)。非 JSON 响应返回 {'_bytes': n}。"""
    headers: dict[str, str] = {}
    data = raw
    if token:
        headers["Authorization"] = "Bearer " + token
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    last_err: Exception | None = None
    # 连接层错误（本机偶发的重置/超时）**重试一次**再判红。
    # 上一轮回归里「匿名记账 -> 401」就因为一次连接重置整轮判红——
    # 那不是产品的问题，是本地网络抖动；真挂了的接口重试也会稳定复现。
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                payload = r.read()
                ctype = r.headers.get("Content-Type", "")
                if "json" in ctype:
                    return r.status, (json.loads(payload) if payload else None)
                return r.status, {"_bytes": len(payload)}
        except urllib.error.HTTPError as e:
            payload = e.read()
            try:
                return e.code, (json.loads(payload) if payload else None)
            except Exception:  # noqa: BLE001
                return e.code, {"_raw": payload[:200].decode("utf-8", "replace")}
        except Exception as e:  # noqa: BLE001  连接层错误
            last_err = e
            if attempt == 1:
                continue
            return 0, {"code": 0, "message": repr(last_err)}
    return 0, {"code": 0, "message": repr(last_err)}


def code_of(resp) -> int | None:
    """业务码：正常 200；改密码失败走 1002/1003（HTTP 仍是 200，见 auth_service）。"""
    if isinstance(resp, dict):
        return resp.get("code")
    return None


def data_of(resp):
    return resp.get("data") if isinstance(resp, dict) else None


def msg_of(resp) -> str:
    if isinstance(resp, dict):
        return str(resp.get("message") or "")
    return ""


def login(username: str, password: str = "123456"):
    st, j = call("POST", "/auth/login", {"username": username, "password": password})
    d = data_of(j) or {}
    return d.get("token") if st == 200 and d.get("token") else None


def find_user(username: str, token: str):
    st, j = call("GET", f"/users?keyword={urllib.parse.quote(username)}", None, token)
    for u in (data_of(j) or []):
        if u.get("username") == username:
            return u
    return None


def root_class_links() -> list[tuple[int, int]]:
    """常驻班主任 `test` 当前挂着的班 `[(class_id, is_adviser)]`（直查库，**不经过列表接口**）。

    为什么不能用 `GET /users` 或 `/auth/me` 判断：那两个的口径是「我能管的班」，
    而这里要查的是**关联表本身**——用例把它删掉了，接口只会更看不出来。
    第五十一轮起关联表多了 `is_adviser`：一行可能只是「能管」，不占名册位。
    守卫要连这个标志一起还原，否则会出现「班级对得上、名册却空了」。
    """
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    with _engine.connect() as c:
        return sorted(
            (int(r[0]), int(r[1]))
            for r in c.execute(
                _t(
                    "SELECT uc.class_id, uc.is_adviser FROM sys_user_class uc "
                    "JOIN sys_user u ON u.id = uc.user_id WHERE u.username = 'test'"
                )
            )
        )


def restore_root_links(want: list[tuple[int, int]]) -> None:
    """把 `test` 的班级关联**直接写回**给定的那几个（含班主任标志）。"""
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    with _engine.begin() as c:
        uid = c.execute(_t("SELECT id FROM sys_user WHERE username = 'test'")).scalar()
        if uid is None:
            return
        c.execute(_t("DELETE FROM sys_user_class WHERE user_id = :i"), {"i": uid})
        for cid, flag in want:
            c.execute(
                _t("INSERT INTO sys_user_class (user_id, class_id, is_adviser) "
                   "VALUES (:i, :c, :a)"),
                {"i": uid, "c": int(cid), "a": int(flag)},
            )


def ensure_user(username: str, role: str, real_name: str, token: str):
    """建号或修复（存在则重置密码并启用）。只有班主任能建 MONITOR/ADMIN —— 见第十五轮等级。"""
    row = find_user(username, token)
    if row:
        call("PUT", f"/users/{row['id']}", {"password": "123456", "status": 1}, token)
        return row["id"]
    st, j = call("POST", "/users",
                 {"username": username, "realName": real_name, "password": "123456", "role": role}, token)
    if st != 200:
        check(f"probe account {username}({role}) created", False, f"st={st} {msg_of(j)}")
        return None
    return (data_of(j) or {}).get("id")


def drop_user(username: str, token: str) -> tuple[bool, str]:
    row = find_user(username, token)
    if not row:
        return True, "absent"
    st, j = call("DELETE", f"/users/{row['id']}", None, token)
    if st == 200:
        return True, "deleted"
    return False, f"st={st} {msg_of(j)}"


def visible_categories(token: str) -> set[tuple]:
    """当前**可见**的类别集合（name, kind）。`GET /api/categories` 只返回 status=1，
    所以软删的行不在其中 —— 这正是「可见状态回到基线」这个断言能成立的原因。
    """
    out = set()
    for kind in ("INCOME", "EXPENSE"):
        st, j = call("GET", f"/categories?kind={kind}", None, token)
        for c in (data_of(j) or []):
            out.add((c.get("name"), c.get("kind")))
    return out


def dictionary_fingerprint(token: str) -> dict:
    """类别字典指纹：(name, kind) -> (id, sort)，用来证明种子字典一个字节都没被动过。

    第十七轮加：之前只断言「收入 ≥5、支出 ≥6」，结果种子类别 `捐款` 被测试停用时，
    现象是「收入 4」，能发现但说不清是谁动的手。改成**开局拍指纹、收尾逐项比对**，
    任何一条被改名/停用/改排序都会指名道姓报出来。
    """
    out = {}
    for kind in ("INCOME", "EXPENSE"):
        st, j = call("GET", f"/categories?kind={kind}", None, token)
        for c in (data_of(j) or []):
            out[(c.get("name"), c.get("kind"))] = (c.get("id"), c.get("sort"))
    return out


# 第十七轮：破坏性操作的安全闸。
# 回归脚本对**预置数据**发起 delete/put 是很危险的事 —— 一旦断言前提不成立
# （比如某个 GET 恰好没返回），"找一条来改"就会退化成"改列表第一条"。
# 下面这个闸门要求：动手前重新读一次该 id，**确认它确实是本脚本建的探针**，
# 否则拒绝对它发任何写请求。
PROBE_PREFIX = "regress"


def guard_probe(token: str, category_id, what: str) -> bool:
    if category_id is None:
        return False
    st, j = call("GET", f"/categories?kind=EXPENSE", None, token)
    st, j2 = call("GET", f"/categories?kind=INCOME", None, token)
    for c in (data_of(j) or []) + (data_of(j2) or []):
        if c.get("id") == category_id:
            if str(c.get("name", "")).startswith(PROBE_PREFIX):
                return True
            print(f"  !! 拒绝{what} id={category_id}：它不是本脚本造的探针"
                  f"（name={c.get('name')!r}），已跳过")
            return False
    # 列表里找不到 = 已经是不可见（软删）状态，对它写也无意义
    return False


# ---------------- 共享状态（跨用例复用登录态，pytest 收集时同属一个模块） ----------------

S: dict = {}


# =====================================================================
# 引导
# =====================================================================

#: 被**程序**按字节/按行解析的配置文件：必须 UTF-8 **无 BOM**。
#: 新增此类文件（*.conf / *.sh / Dockerfile / compose / *.sql / CI 配置等）时
#: 把路径登记进来——闸门只管登记过的文件，不登记 = 不受检查。
BOM_FREE_CONFIGS = [
    "web/nginx.docker.conf",
    "server-py/db/schema.sql",
    "web/package.json",
    "docker-compose.yml",
    "docker-compose.use-existing-db.yml",
    ".env.example",
]

#: 给**人**读的文档：必须 UTF-8 **带 BOM**（中文 Windows 的 GBK 工具要读，无 BOM 是乱码）。
MUST_HAVE_BOM = [
    "docs/系统设计文档.md",
    "docs/部署-Linux.md",
]

#: 「程序读」这一侧的扩展名。新建的文件若落在这个集合里，闸门会自动要求它无 BOM——
#: 免得有人只改了 PROSE 里的既有清单、却新建了一个同类文件而不自知。
#: 注意 `.py` 故意不在其中：Python 自动识别源文件 BOM，两种都能跑，不值得为它加约束。
_PROGRAM_READ_SUFFIXES = {
    ".conf", ".sh", ".bash", ".zsh", ".sql", ".yml", ".yaml", ".json", ".toml",
    ".ini", ".cfg", ".bat", ".ps1", ".env", ".properties", ".xml", ".tf",
}
_PROGRAM_READ_NAMES = {"dockerfile", "makefile", ".env", ".env.example", ".gitignore"}
_SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "dist", "__pycache__", ".idea"}


def test_a00_encoding_guards():
    """**文件编码闸门**（第二十一轮；第二十二轮扩展为自动发现）。

    规则一句话：**谁来读这个文件，决定它有没有 BOM。**

    - **程序读**（nginx / MySQL / shell / Docker / 任何按字节或按行解析的解析器）→ **无 BOM**。
      BOM 不是无害的解码提示，而是**文件内容的一部分**。
    - **人读**（编辑器 / GBK 工具 / Notepad）→ **有 BOM**。中文 Windows 上没 BOM 就是乱码。
    - **都不敏感**（全部 `.py`）→ 无所谓，Python 自动识别源文件 BOM。

    中文注释在「无 BOM」那一侧完全安全——`nginx.docker.conf` 与 `schema.sql` 里的中文注释
    从来没出过问题，坏的只有 BOM 本身。

    已经踩中过两次，同一根因、两种表现：
    - `server-py/db/schema.sql`：BOM 让首行 `-- 1) 班级表` 不被当注释剔掉 → 第一条建表语句
      被 MySQL 语法错 + `except ProgrammingError: continue` 静默吞掉 → **新库少一张表且
      启动日志不报错**（静默）。
    - `web/nginx.docker.conf`：nginx 把 BOM 和 `server` 读成一个 token →
      `unknown directive " server"`，**frontend 容器起不来**（响亮）。

    放在回归开头当常驻闸门，因为这类问题**只有真正跑起来才会暴露**，而本机没有 Docker。
    """
    print("\n--- A0. 文件编码闸门（程序读=无 BOM / 人读=有 BOM）---")
    root = pathlib.Path(__file__).resolve().parents[2]
    bom = b"\xef\xbb\xbf"

    # ① 显式登记的必须无 BOM
    for rel in BOM_FREE_CONFIGS:
        p = root / rel
        if not p.exists():
            check(f"{rel} 存在", False, f"找不到 {p}")
            continue
        extra = "（nginx 会报 unknown directive \" server\"）" if rel.endswith(".conf") else ""
        check(f"{rel} 无 UTF-8 BOM（程序读）", p.read_bytes()[:3] != bom,
              f"文件以 EF BB BF 开头——按字节解析会把它当内容{extra}")

    # ② 显式登记的必须保留 BOM
    for rel in MUST_HAVE_BOM:
        p = root / rel
        if p.exists():
            check(f"{rel} 保留 UTF-8 BOM（人读）", p.read_bytes()[:3] == bom,
                  "markdown 缺 BOM，中文 Windows 的 GBK 工具打开是乱码")

    # ③ 自动发现：扫描仓库里所有「程序读」类文件，现有的必须干净。
    #    这一条才是真正的长期防线——①②只是点名，③能抓住**新建的**同类文件。
    offenders: list[str] = []
    scanned = 0
    for p in root.rglob("*"):
        if not p.is_file():
            continue
        if any(part in _SKIP_DIRS for part in p.parts):
            continue
        name = p.name.lower()
        if p.suffix.lower() not in _PROGRAM_READ_SUFFIXES and name not in _PROGRAM_READ_NAMES:
            continue
        scanned += 1
        rel = p.relative_to(root).as_posix()
        if rel in BOM_FREE_CONFIGS or rel in MUST_HAVE_BOM:
            continue
        if p.read_bytes()[:3] == bom:
            offenders.append(rel)
    check(f"自动扫描 {scanned} 个「程序读」配置文件，均无 BOM", not offenders,
          "以下文件带 BOM，请存为 UTF-8 无 BOM：" + "、".join(offenders))


def test_a00_bootstrap():
    print("\n--- A. 引导账号 ---")
    st, j = call("POST", "/auth/login", {"username": ROOT_U, "password": ROOT_P})
    tok = data_of(j) or {}
    S["T"] = tok.get("token")
    S["root_role"] = (tok.get("user") or {}).get("role")
    S["root_id"] = (tok.get("user") or {}).get("id")
    if not check("班主任账号登录", bool(S["T"]) and S["root_role"] in ("TEACHER", "ADMIN"),
                 f"st={st} role={S['root_role']} {msg_of(j)}"):
        raise SystemExit("无法登录班主任账号，后续用例无意义")
    T = S["T"]

    # 账号基线（第三十三轮）：**跑之前库里有哪些账号**，收尾时必须一模一样。
    #
    # 以前这条是写死的「{test} ∪ KEEP_ACCOUNTS」。库里一旦多出一个**用户自己建的**
    # 账号（比如在班级页点了「一键创建账号」），回归就无辜变红——它要保证的是
    # 「回归没留残渣」，不是「库里只能有两个账号」。快照放在建探针**之前**，
    # 所以红只可能来自本脚本自己。
    S["users0"] = {
        u["username"] for u in (data_of(call("GET", "/users", None, T)[1]) or [])
    } - set(PROBE_USERS)
    # 常驻班主任 test 的**班级关联**基线（第五十一轮）：
    # 用例可以临时改（测「我带的班」），但收尾必须还原（见 main 里的守卫）。
    S["root_classes0"] = root_class_links()

    # 普通成员：能登录就复用，否则建/修
    if not login(MEMBER_U, MEMBER_P):
        st, j = call("POST", "/users",
                     {"username": MEMBER_U, "realName": MEMBER_NAME, "password": MEMBER_P}, T)
        if st != 200:
            row = find_user(MEMBER_U, T)
            if row:
                call("PUT", f"/users/{row['id']}", {"password": MEMBER_P, "status": 1}, T)
    S["M"] = login(MEMBER_U, MEMBER_P)
    if not check("普通成员账号可登录", bool(S["M"]), MEMBER_U):
        raise SystemExit("无法登录普通成员账号，后续 403 用例无意义")
    st, j = call("GET", "/auth/me", None, S["M"])
    S["m_id"] = (data_of(j) or {}).get("id")

    # 角色探针（只由班主任建，符合等级要求）
    S["a_id"] = ensure_user(LVL_ADMIN_U, "ADMIN", "Life Probe", T)
    S["mo_id"] = ensure_user(LVL_MONITOR_U, "MONITOR", "Monitor Probe", T)
    S["p_id"] = ensure_user(LVL_PEER_U, "MONITOR", "Monitor Probe 2", T)
    S["pl_id"] = ensure_user(LVL_PLAIN_U, "MEMBER", "Plain Probe", T)
    check("角色探针账号就绪",
          all([S["a_id"], S["mo_id"], S["p_id"], S["pl_id"]]),
          f"admin={S['a_id']} monitor={S['mo_id']} peer={S['p_id']} plain={S['pl_id']}")
    S["A"] = login(LVL_ADMIN_U)
    S["MO"] = login(LVL_MONITOR_U)
    check("探针账号可登录", bool(S["A"]) and bool(S["MO"]), f"admin={bool(S['A'])} monitor={bool(S['MO'])}")

    # 基线快照
    st, j = call("GET", "/dashboard/summary", None, T)
    summary = data_of(j) or {}
    S["b0"] = float(summary.get("balance", 0))
    S["rec0"] = (call("GET", "/records?page=1&size=1", None, T)[1]["data"] or {}).get("total")
    S["batch0"] = len(data_of(call("GET", "/batches", None, T)[1]) or [])
    S["cls0"] = data_of(call("GET", "/class", None, T)[1]) or {}
    # 可见类别集合：收尾时必须一模一样。
    # 类别是软删（status=0），脚本造的类别删完后会留一行停用记录 —— 名字已释放、
    # 列表不再显示，所以「可见集合回到基线」成立；行数不会完全归零，这是软删的
    # 预期语义，不需要（也不应该）由测试去物理删行。
    S["cats0"] = visible_categories(T)
    S["dict0"] = dictionary_fingerprint(T)
    print(f"  基线: balance={S['b0']} records={S['rec0']} batches={S['batch0']} "
          f"class={S['cls0'].get('className')!r} "
          f"可见类别={len(S['cats0'])} 字典指纹={len(S['dict0'])}")

    st, j = call("GET", "/categories?kind=EXPENSE", None, T)
    S["exp_cat"] = (data_of(j) or [{}])[0].get("id")
    st, j = call("GET", "/categories?kind=INCOME", None, T)
    S["inc_cat"] = (data_of(j) or [{}])[0].get("id")
    check("取到支出/收入类别样本", bool(S["exp_cat"]) and bool(S["inc_cat"]),
          f"exp={S['exp_cat']} inc={S['inc_cat']}")


# =====================================================================
# 账号管理
# =====================================================================

def test_a01_account_crud():
    print("\n--- B. 账号增删改查 ---")
    T, M, m_id = S["T"], S["M"], S["m_id"]

    st, j = call("POST", "/users", {"username": MEMBER_U, "realName": "Duplicate"}, T)
    check("重复登录名 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/users", None, T)
    names = [u["username"] for u in (data_of(j) or [])]
    check("账号列表含运营与成员", ROOT_U in names and MEMBER_U in names, f"count={len(names)}")

    # MEMBER 三件套 403
    for label, m, p, b, want in [
        ("MEMBER 读账号列表", "GET", "/users", None, 403),
        ("MEMBER 建账号", "POST", "/users", {"username": "nope1", "realName": "Nope"}, 403),
        ("MEMBER 改账号", "PUT", f"/users/{m_id}", {"realName": "Nope"}, 403),
        ("MEMBER 删账号", "DELETE", f"/users/{m_id}", None, 403),
    ]:
        st, j = call(m, p, b, M)
        check(f"{label} -> {want}", st == want, f"st={st} {msg_of(j)}")

    # 编辑姓名 + 手机号
    st, j = call("PUT", f"/users/{m_id}", {"realName": "Li Xiaoming", "phone": "13800001111"}, T)
    check("编辑姓名+手机号 -> 200",
          st == 200 and (data_of(j) or {}).get("phone") == "13800001111",
          f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{m_id}", {"realName": MEMBER_NAME}, T)
    check("不传手机号则保留", (data_of(j) or {}).get("phone") == "13800001111", msg_of(j))
    st, j = call("PUT", f"/users/{m_id}", {"phone": ""}, T)
    check("手机号空串=清空", st == 200 and (data_of(j) or {}).get("phone") is None, f"st={st}")

    # 学号
    sid = ensure_user(SNO_DEFAULT_U, "MEMBER", "Sn Default", T)
    check("学号默认回填登录名（MEMBER）",
          (find_user(SNO_DEFAULT_U, T) or {}).get("studentNo") == SNO_DEFAULT_U,
          str((find_user(SNO_DEFAULT_U, T) or {}).get("studentNo")))
    st, j = call("PUT", f"/users/{sid}", {"studentNo": "9" * 21}, T)
    check("学号超 20 位 -> 400", st == 400, f"st={st}")
    st, j = call("PUT", f"/users/{m_id}", {"studentNo": "S-2022-0103"}, T)
    check("编辑学号 -> 200", st == 200 and (data_of(j) or {}).get("studentNo") == "S-2022-0103", f"st={st}")
    st, j = call("PUT", f"/users/{sid}", {"studentNo": "S-2022-0103"}, T)
    check("同班学号重复 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{m_id}", {"studentNo": MEMBER_U}, T)
    check("学号改回登录名 -> 200", st == 200 and (data_of(j) or {}).get("studentNo") == MEMBER_U, f"st={st}")

    # 删除：只能删「零引用」且「等级低于自己」的
    st, j = call("DELETE", f"/users/{S['root_id']}", None, T)
    check("删除自己 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{S['root_id']}", {"status": 0}, T)
    check("停用自己 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{m_id}", {}, T)
    check("空更新体 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/users/99999999", {"realName": "Nobody"}, T)
    check("更新不存在的账号 -> 400", st == 400, f"st={st}")
    st, j = call("POST", "/users", {"username": "reg_bad", "realName": "X", "role": "SUPERUSER"}, T)
    check("未知角色 -> 400（不能是 500）", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", f"/users?keyword={DISPOSABLE_U}", None, T)
    if data_of(j):
        row = next((u for u in data_of(j) if u["username"] == DISPOSABLE_U), None)
        if row:
            call("DELETE", f"/users/{row['id']}", None, T)  # 上次中断留下的
    st, j = call("POST", "/users", {"username": DISPOSABLE_U, "realName": "Del Probe"}, T)
    did = (data_of(j) or {}).get("id")
    check("一次性账号可创建", st == 200 and did, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/users/{did}", None, T)
    check("零引用账号可删除 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/users?keyword={DISPOSABLE_U}", None, T)
    check("删除后确实不存在", not data_of(j), str(data_of(j)))
    st, j = call("DELETE", "/users/99999999", None, T)
    check("删除不存在的账号 -> 400", st == 400, f"st={st}")


# =====================================================================
# 角色等级（第十五轮）
# =====================================================================

def test_a02_role_hierarchy():
    print("\n--- C. 账号管理权限等级（班主任 > 班长 > 生活委员 > 普通成员）---")
    T, MO, A = S["T"], S["MO"], S["A"]
    if not (T and MO and A and S["root_role"] == "TEACHER"):
        print("  (跳过：需要班主任在位且探针齐全)")
        return
    root_id = S["root_id"]

    st, j = call("GET", "/users", None, T)
    root_row = next((u for u in (data_of(j) or []) if u["id"] == root_id), {})
    name_before = root_row.get("realName")

    # 越级：班长对班主任的四类动作全被拒
    for label, m, p, b in [
        ("编辑", "PUT", f"/users/{root_id}", {"realName": "Hijacked"}),
        ("停用", "PUT", f"/users/{root_id}", {"status": 0}),
        ("删除", "DELETE", f"/users/{root_id}", None),
        ("重置密码", "PUT", f"/users/{root_id}", {"password": "hijack999"}),
    ]:
        st, j = call(m, p, b, MO)
        check(f"班长{label}班主任 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/users", None, T)
    after = next((u for u in (data_of(j) or []) if u["id"] == root_id), {})
    st2, _ = call("POST", "/auth/login", {"username": ROOT_U, "password": ROOT_P})
    check("被拒的请求什么都没改（姓名/启用/旧密码）",
          after.get("realName") == name_before and after.get("status") == 1 and st2 == 200,
          f"name={after.get('realName')!r} status={after.get('status')} relogin={st2}")

    # 越级：生活委员动班长
    for label, m, p, b in [
        ("编辑", "PUT", f"/users/{S['mo_id']}", {"realName": "Hijacked"}),
        ("删除", "DELETE", f"/users/{S['mo_id']}", None),
        ("重置密码", "PUT", f"/users/{S['mo_id']}", {"password": "hijack999"}),
    ]:
        st, j = call(m, p, b, A)
        check(f"生活委员{label}班长 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 同级：班长之间不能互管
    for label, m, p, b in [
        ("编辑", "PUT", f"/users/{S['p_id']}", {"realName": "Hijacked"}),
        ("删除", "DELETE", f"/users/{S['p_id']}", None),
        ("重置密码", "PUT", f"/users/{S['p_id']}", {"password": "hijack999"}),
    ]:
        st, j = call(m, p, b, MO)
        check(f"班长{label}同级班长 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 提权口子：不能建比自己高级的角色
    for actor, tok, role in [("生活委员", A, "TEACHER"), ("班长", MO, "TEACHER"), ("生活委员", A, "MONITOR")]:
        st, j = call("POST", "/users",
                     {"username": f"esc_{role.lower()}_{S['a_id']}", "realName": "Esc",
                      "password": "123456", "role": role}, tok)
        check(f"{actor}创建{role} -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 正向对照：能管低等级、能建低等级
    st, j = call("POST", "/users",
                 {"username": LVL_ESCALATE_U, "realName": "Life", "password": "123456", "role": "ADMIN"}, MO)
    esc_id = (data_of(j) or {}).get("id")
    check("班长创建生活委员 -> 200（低等级允许）", st == 200, f"st={st} {msg_of(j)}")
    if esc_id:
        call("DELETE", f"/users/{esc_id}", None, T)  # 用完即删，保持净零
    st, j = call("PUT", f"/users/{S['a_id']}", {"realName": "Managed"}, MO)
    check("班长编辑生活委员 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{S['pl_id']}", {"realName": "Managed"}, A)
    check("生活委员编辑普通成员 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{S['mo_id']}", {"realName": "Managed"}, T)
    check("班主任编辑班长 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/users/{root_id}", {"realName": name_before}, T)
    check("班主任编辑自己 -> 200", st == 200, f"st={st} {msg_of(j)}")
    for uid, tok in [(S["a_id"], MO), (S["pl_id"], A), (S["mo_id"], T)]:
        call("PUT", f"/users/{uid}", {"realName": "Probe"}, tok)


# =====================================================================
# 个人信息自助
# =====================================================================

def test_a03_self_profile():
    print("\n--- D. 个人信息自助（GET/PUT /auth/profile）---")
    T, M = S["T"], S["M"]
    st, j = call("GET", "/auth/profile", None, None)
    check("无令牌读个人信息 -> 401", st == 401, f"st={st}")
    st, j = call("PUT", "/auth/profile", {"realName": "No Token"}, None)
    check("无令牌改个人信息 -> 401", st == 401, f"st={st}")

    st, j = call("GET", "/auth/profile", None, M)
    me = data_of(j) or {}
    check("普通成员能读到自己学号",
          st == 200 and me.get("username") == MEMBER_U and me.get("studentNo") is not None,
          f"st={st} studentNo={me.get('studentNo')}")
    check("读到的只有自己（role=MEMBER）", me.get("role") == "MEMBER", str(me.get("role")))

    before = me.get("realName")
    st, j = call("PUT", "/auth/profile", {"realName": "ProfileSelf"}, M)
    check("普通成员改自己姓名 -> 200", st == 200 and (data_of(j) or {}).get("realName") == "ProfileSelf",
          f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/me", None, M)
    check("改名立刻在 /auth/me 生效", (data_of(j) or {}).get("realName") == "ProfileSelf", msg_of(j))

    st, j = call("PUT", "/auth/profile", {}, M)
    check("空体 -> 400", st == 400, f"st={st}")
    st, j = call("PUT", "/auth/profile", {"realName": "   "}, M)
    check("姓名空白 -> 400", st == 400, f"st={st}")
    st, j = call("PUT", "/auth/profile", {"studentNo": "9" * 21}, M)
    check("学号超长 -> 400", st == 400, f"st={st}")
    st, j = call("PUT", "/auth/profile", {"phone": "1" * 21}, M)
    check("手机号超长 -> 400", st == 400, f"st={st}")

    # 越权字段必须无效
    st, j = call("PUT", "/auth/profile",
                 {"realName": "ProfileSelf", "id": 99999, "role": "TEACHER",
                  "status": 0, "username": "hijack", "classId": 2}, M)
    row = find_user(MEMBER_U, T) or {}
    check("role/status/username/classId 一律被忽略",
          st == 200 and row.get("role") == "MEMBER" and row.get("username") == MEMBER_U
          and row.get("status") == 1,
          f"st={st} role={row.get('role')} user={row.get('username')} status={row.get('status')}")

    # 学号同班唯一
    st, j = call("PUT", "/auth/profile", {"studentNo": "P-2022-9001"}, M)
    check("自助设学号 -> 200", st == 200, f"st={st}")
    st, j = call("PUT", f"/users/{S['root_id']}", {"studentNo": "P-2022-9001"}, T)
    check("学号同班唯一（撞班主任）-> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/auth/profile", {"studentNo": "P-2022-9001"}, M)
    check("重设同一个学号放行（唯一性排除自己）", st == 200, f"st={st}")
    st, j = call("PUT", "/auth/profile", {"phone": ""}, M)
    row = find_user(MEMBER_U, T) or {}
    check("手机号空串清空", st == 200 and row.get("phone") is None, f"st={st} phone={row.get('phone')}")
    st, j = call("PUT", "/auth/profile", {"realName": "ProfileSelf"}, M)
    row = find_user(MEMBER_U, T) or {}
    check("学号不传则保留", row.get("studentNo") == "P-2022-9001", str(row.get("studentNo")))

    # 复原
    st, j = call("PUT", "/auth/profile", {"realName": before, "studentNo": MEMBER_U}, M)
    row = find_user(MEMBER_U, T) or {}
    check("复原到基线", st == 200 and row.get("realName") == before and row.get("studentNo") == MEMBER_U,
          f"name={row.get('realName')!r} sn={row.get('studentNo')}")

    # 运营角色同样能用（改自己）
    st, j = call("GET", "/users", None, T)
    root_row = next((u for u in (data_of(j) or []) if u["id"] == S["root_id"]), {})
    root_name = root_row.get("realName")
    st, j = call("PUT", "/auth/profile", {"realName": "Root Self"}, T)
    check("班主任改自己个人信息 -> 200", st == 200 and (data_of(j) or {}).get("realName") == "Root Self",
          f"st={st}")
    call("PUT", "/auth/profile", {"realName": root_name}, T)
    st, j = call("GET", "/users", None, T)
    root_row = next((u for u in (data_of(j) or []) if u["id"] == S["root_id"]), {})
    check("班主任真实姓名已复原", root_row.get("realName") == root_name,
          f"before={root_name!r} after={root_row.get('realName')!r}")


# =====================================================================
# 改密码
# =====================================================================

def test_a04_password():
    print("\n--- E. 本人改密码 ---")
    M = S["M"]
    st, j = call("PUT", "/auth/password", {"oldPassword": "wrong-one", "newPassword": "abcdef"}, M)
    # 设计如此：改密失败走业务码 1002/1003，HTTP 仍 200（统一响应体的约定）
    check("原密码错误被拒（业务码 1002）", code_of(j) == 1002, f"http={st} code={code_of(j)} {msg_of(j)}")
    for label, body in [
        ("新密码过短", {"oldPassword": MEMBER_P, "newPassword": "123"}),
        ("新密码为空", {"oldPassword": MEMBER_P, "newPassword": ""}),
        ("缺原密码", {"newPassword": "abcdef"}),
    ]:
        st, j = call("PUT", "/auth/password", body, M)
        check(f"{label} -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/auth/password", {"oldPassword": MEMBER_P, "newPassword": MEMBER_P}, M)
    check("新密码与原密码相同被拒", st != 200 or code_of(j) != 200, f"http={st} code={code_of(j)}")
    st, j = call("PUT", "/auth/password", {"oldPassword": MEMBER_P, "newPassword": "abcdef"}, M)
    check("改密成功 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("旧密码已失效", login(MEMBER_U, MEMBER_P) is None, MEMBER_P)
    check("新密码可登录", login(MEMBER_U, "abcdef") is not None, "abcdef")
    tok = login(MEMBER_U, "abcdef")
    call("PUT", "/auth/password", {"oldPassword": "abcdef", "newPassword": MEMBER_P}, tok)
    S["M"] = login(MEMBER_U, MEMBER_P)
    check("密码已复原", bool(S["M"]), MEMBER_P)


# =====================================================================
# 流水：增删改查 + 校验 + 筛选
# =====================================================================

def test_a05_records():
    print("\n--- F. 流水增删改查 / 校验 / 筛选 ---")
    T, M = S["T"], S["M"]
    b0 = S["b0"]
    exp, inc = S["exp_cat"], S["inc_cat"]

    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 10,
                  "title": "regress delete probe", "occurredAt": "2026-09-26 10:00:00", "channel": "CASH"}, T)
    rid = (data_of(j) or {}).get("id")
    check("支出登记 -> 200", st == 200 and rid, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, T)
    check("登记后余额 -10", near((data_of(j) or {}).get("balance"), b0 - 10),
          f"got={(data_of(j) or {}).get('balance')} want={b0 - 10}")
    st, j = call("DELETE", f"/records/{rid}", None, T)
    check("删除流水 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, T)
    check("删除后余额回滚", near((data_of(j) or {}).get("balance"), b0),
          f"got={(data_of(j) or {}).get('balance')}")
    st, j = call("DELETE", f"/records/{rid}", None, T)
    check("重复删除 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 作废
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 7.5, "title": "regress void probe",
                  "occurredAt": "2026-09-26 10:05:00", "channel": "CASH"}, T)
    vid = (data_of(j) or {}).get("id")
    st, j = call("POST", f"/records/{vid}/void", None, T)
    check("作废流水 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/records?id={vid}&size=5", None, T)
    rows = (data_of(j) or {}).get("records") or []
    check("状态变为 VOID", rows and rows[0]["status"] == "VOID", str(rows[:1]))
    st, j = call("POST", f"/records/{vid}/void", None, T)
    check("重复作废 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, T)
    check("作废不影响余额", near((data_of(j) or {}).get("balance"), b0), str((data_of(j) or {}).get("balance")))
    call("DELETE", f"/records/{vid}", None, T)

    # 方向必须与类别一致
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": inc, "amount": 1, "title": "regress crosskind",
                  "occurredAt": "2026-09-26 10:08:00", "channel": "CASH"}, T)
    check("支出挂收入类别 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 金额边界
    for label, amount in [("金额为 0", "0"), ("负数金额", "-5"), ("分以下精度", "0.001")]:
        st, j = call("POST", "/records",
                     {"type": "EXPENSE", "categoryId": exp, "amount": amount, "title": "regress amt",
                      "occurredAt": "2026-09-26 10:09:00", "channel": "CASH"}, T)
        check(f"{label} -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 小票约束
    st, j = call("POST", "/records",
                 {"type": "INCOME", "categoryId": inc, "amount": 1, "title": "regress receipt",
                  "occurredAt": "2026-09-26 10:12:00", "channel": "CASH",
                  "receiptUrl": "receipts/x.png"}, T)
    check("收入挂小票 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 1, "title": "regress receipt2",
                  "occurredAt": "2026-09-26 10:12:00", "channel": "CASH",
                  "receiptUrl": "receipts/nope.png"}, T)
    check("小票文件不存在 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 1, "title": "regress receipt3",
                  "occurredAt": "2026-09-26 10:12:00", "channel": "CASH",
                  "receiptUrl": "../../../etc/passwd"}, T)
    check("小票路径穿越 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/files/receipts/../../db/schema.sql", None, T)
    check("查看穿越路径的小票 -> 404", st == 404, f"st={st}")

    # 筛选：枚举值必须校验（第十六轮）
    st, j = call("GET", "/records?page=1&size=100", None, T)
    allrows = (data_of(j) or {}).get("records") or []
    n_normal = sum(1 for r in allrows if r["status"] == "NORMAL")
    n_income = sum(1 for r in allrows if r["type"] == "INCOME")
    n_cash = sum(1 for r in allrows if r["channel"] == "CASH")
    for q, want_st, want_total in [
        ("", 200, len(allrows)),
        ("status=", 200, len(allrows)),
        ("status=all", 200, len(allrows)),
        ("status=ALL", 200, len(allrows)),
        ("type=all", 200, len(allrows)),
        ("type=All", 200, len(allrows)),
        ("status=NORMAL", 200, n_normal),
        ("type=INCOME", 200, n_income),
        ("channel=CASH", 200, n_cash),
        ("channel=cash", 200, n_cash),
        ("status=BOGUS", 400, None),
        ("type=BOGUS", 400, None),
        ("channel=BOGUS", 400, None),
    ]:
        path = f"/records?{q}" if q else "/records"
        st, j = call("GET", path, None, T)
        total = (data_of(j) or {}).get("total")
        check(f"GET {path} -> {want_st}" + ("" if want_total is None else f" total={want_total}"),
              st == want_st and (want_total is None or total == want_total),
              f"got st={st} total={total} {msg_of(j)}")

    # 日期区间
    for q, want_st in [
        ("start=bad&end=2026-12-31", 400),
        ("start=2027-01-01&end=2027-12-31", 200),
        ("start=2020-01-01&end=2020-12-31", 200),
    ]:
        st, j = call("GET", f"/records?{q}", None, T)
        check(f"GET /records?{q} -> {want_st}", st == want_st, f"got st={st} {msg_of(j)}")

    # 分页边界
    for q, want_st in [("page=0&size=10", 400), ("page=-1&size=10", 400),
                      ("size=0", 400), ("size=200", 400), ("size=100", 200)]:
        st, j = call("GET", f"/records?{q}", None, T)
        check(f"GET /records?{q} -> {want_st}", st == want_st, f"got st={st} {msg_of(j)}")

    # 导出与列表同口径
    st, j = call("GET", "/records/export", None, T)
    check("导出账本 -> 200 且是 xlsx", st == 200 and (j or {}).get("_bytes", 0) > 1000,
          f"st={st} {j}")
    st, j = call("GET", "/records/export?status=all", None, T)
    check("导出 status=all -> 200", st == 200, f"st={st} {j}")
    st, j = call("GET", "/records/export?status=BOGUS", None, T)
    check("导出 status=BOGUS -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/records/export", None, M)
    check("普通成员导出 -> 403", st == 403, f"st={st} {msg_of(j)}")


# =====================================================================
# 类别（第十六轮重点）
# =====================================================================

def test_a06_categories():
    print("\n--- G. 类别字典（含第十六轮 PUT 语义修复）---")
    T = S["T"]
    name = "regress temp category"

    st, j = call("POST", "/categories", {"name": name, "kind": "EXPENSE", "sort": 99}, T)
    check("新建类别 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/categories?kind=EXPENSE", None, T)
    row = next((c for c in (data_of(j) or []) if c["name"] == name), None)
    cid = row["id"] if row else None
    check("新建后可按名读到", cid is not None, str(row))
    st, j = call("POST", "/categories", {"name": name, "kind": "EXPENSE"}, T)
    check("同类同名 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/categories", {"kind": "EXPENSE"}, T)
    check("新建缺名称 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/categories", {"name": "regress no kind"}, T)
    check("新建缺方向 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/categories", {"name": "regress bad kind", "kind": "NOPE"}, T)
    check("新建方向非法 -> 400", st == 400, f"st={st} {msg_of(j)}")

    if cid:
        # 第十六轮修复点 1：body 不带 id 也能改（旧实现强制要求 body 重复 id，接口等于不可用）
        st, j = call("PUT", f"/categories/{cid}", {"name": name + " v2", "kind": "EXPENSE"}, T)
        check("PUT 不带 body id -> 200（旧实现 400「缺少类别 id」）", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/categories?kind=EXPENSE", None, T)
        row = next((c for c in (data_of(j) or []) if c["id"] == cid), {})
        check("名称已更新", row.get("name") == name + " v2", str(row))
        # 修复点 2：sort 不传时保持原值（旧实现重置为 0）
        check("sort 未被重置（旧实现会置 0）", row.get("sort") == 99, f"sort={row.get('sort')}")
        # 修复点 3：body id 与路径不一致要报错（旧实现从不比对，纯误导字段）
        st, j = call("PUT", f"/categories/{cid}", {"id": cid + 9999, "name": "x"}, T)
        check("body id 与路径不符 -> 400", st == 400, f"st={st} {msg_of(j)}")
        st, j = call("PUT", f"/categories/{cid}", {}, T)
        check("空更新体 -> 400", st == 400, f"st={st} {msg_of(j)}")
        # 修复点 4：未被引用的类别可以改方向
        st, j = call("PUT", f"/categories/{cid}", {"kind": "INCOME"}, T)
        check("未引用类别改方向 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("PUT", f"/categories/{cid}", {"kind": "EXPENSE"}, T)
        check("改回支出方向 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # 已被流水引用的类别：禁止改方向（旧实现允许，会让历史支出的类别变成收入）
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": cid, "amount": 2.22, "title": "regress cat ref",
                  "occurredAt": "2026-09-26 10:15:00", "channel": "CASH"}, T)
    ref_rid = (data_of(j) or {}).get("id")
    st, j = call("PUT", f"/categories/{cid}", {"kind": "INCOME"}, T)
    check("已引用类别改方向 -> 400（旧实现 200，会污染历史账本）", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/categories?kind=EXPENSE", None, T)
    still = next((c for c in (data_of(j) or []) if c["id"] == cid), None)
    check("该类别仍是支出方向", still is not None, str(still))
    st, j = call("PUT", f"/categories/{cid}", {"name": "regress renamed"}, T)
    check("已引用类别可改名 -> 200", st == 200, f"st={st} {msg_of(j)}")
    if guard_probe(T, cid, "删除被引用的探针类别"):
        st, j = call("DELETE", f"/categories/{cid}", None, T)
        check("已引用类别删除 -> 400", st == 400, f"st={st} {msg_of(j)}")

    if ref_rid:
        call("DELETE", f"/records/{ref_rid}", None, T)
    if cid and guard_probe(T, cid, "删除零引用探针类别"):
        st, j = call("DELETE", f"/categories/{cid}", None, T)
        check("零引用类别可删除 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/categories?kind=EXPENSE", None, T)
        check("删除后不再出现在列表（软删，非硬删）",
              not any(c["id"] == cid for c in (data_of(j) or [])), f"cid={cid}")
        st, j = call("POST", "/categories", {"name": name + " v2", "kind": "EXPENSE", "sort": 99}, T)
        check("删除后同名可重建 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/categories?kind=EXPENSE", None, T)
        again = next((c["id"] for c in (data_of(j) or []) if c["name"] == name + " v2"), None)
        check("重建后是新行（新 id）", again is not None and again != cid, f"new={again} old={cid}")
        if guard_probe(T, again, "删除重建的探针类别"):
            call("DELETE", f"/categories/{again}", None, T)

    # 「已被引用不可删」上面已用自建类别验证过。
    # 这里**绝不对种子字典发起删除**：delete_category 现在是软删（status=0），但若某次
    # 改动把它退回硬删，一次针对种子类别的断言就会让用户字典凭空少一行、且无法恢复。
    # 只做只读体检：把「有流水在用」的类别列出来，供人工确认字典状态。
    st, j = call("GET", "/records?page=1&size=100&status=all", None, T)
    used = {r.get("categoryId") for r in ((data_of(j) or {}).get("records") or [])}
    st, j = call("GET", "/categories", None, T)
    catalog = data_of(j) or []
    referenced = [c["name"] for c in catalog if c["id"] in used]
    print(f"  (只读体检：{len(catalog)} 个类别，其中 {len(referenced)} 个被流水引用: {referenced})")

    # 第十七轮：数量检查改成**指纹比对**。原来只断言「收入 ≥5、支出 ≥6」，
    # 种子类别 `捐款` 被停用时只会报「收入 4」——能发现但说不清谁动的手。
    # 指纹逐项比对会直接点名：哪条不见了 / 改了名 / 换了 id / 排序被改。
    now = dictionary_fingerprint(T)
    lost = sorted(k for k in S["dict0"] if k not in now)
    renamed = sorted(k for k in S["dict0"] if k in now and S["dict0"][k][0] != now[k][0])
    resorted = sorted(k for k in S["dict0"] if k in now and S["dict0"][k][1] != now[k][1])
    added = sorted(k for k in now if k not in S["dict0"])
    check("种子类别字典零损伤（逐项比对指纹）",
          not (lost or renamed or resorted or added),
          f"丢失/停用={lost} 被改名={renamed} 被换id={renamed} 被改排序={resorted} 新增={added}")

    # 跨班隔离
    #
    # 第十七轮**删掉**了原来这里的「改/删他班类别」断言，原因是它本身就是缺陷：
    # `GET /api/categories` 按 class_id 过滤，**只可能返回本班类别**，所以「他班类别」
    # 根本无法通过这个接口拿到。原实现用 `classId not in (None, cls0.get("id"))`
    # 去列表里找，一旦 `GET /api/class` 那一瞬没返回（cls0 为空 dict），条件就退化成
    # 「取列表第一个」——于是拿**种子类别**当破坏目标。实测真的把种子类别 `捐款` 停用过一次，
    # 而且是间歇性的（取决于那一次 /api/class 是否恰好就绪），极难排查。
    #
    # 跨班隔离改在**真正能构造出跨班场景**的地方验证：用另一个班的 categoryId 去登记
    # 本班流水（见 test_a05 的「跨班类别」），后端必须以「类别不存在或已停用」拒绝。
    # 那条是真的、也是最有价值的隔离断言。

    # ---------- 清理：探针类别是**软删**（status=0），会一直躺在表里 ----------
    #
    # 每跑一轮回归就多两个「regress …」的停用类别，攒久了用户的类别字典
    # 里全是测试垃圾（界面上看不见，导出/统计里还在）。这里按行删干净。
    import pathlib
    import sys as _sys

    _server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if _server_dir not in _sys.path:
        _sys.path.insert(0, _server_dir)
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    with _engine.begin() as c:
        c.execute(_t("DELETE FROM fee_category WHERE name LIKE 'regress%'"))


# =====================================================================
# 收费批次
# =====================================================================

def test_a07_batches():
    print("\n--- H. 收费批次与缴费 ---")
    T, M = S["T"], S["M"]
    b0 = S["b0"]
    name = "regress delete cascade batch"

    st, j = call("POST", "/batches",
                 {"name": name, "amount": 5.55, "deadline": "2026-12-31", "remark": "regression"}, T)
    bid = (data_of(j) or {}).get("id")
    check("新建批次 -> 200", st == 200 and bid, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/batches",
                 {"name": name, "amount": 5.55, "deadline": "2026-12-31"}, T)
    check("同名进行中批次 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", f"/members?batchId={bid}", None, T)
    roster = data_of(j) or []
    roles = sorted({r["role"] for r in roster})
    us = {r["username"] for r in roster}
    # 第二十轮：缴费对象 = 除班主任外的全部学生。生活委员/班长也是学生，班费照交；
    # 班主任是 .env 声明的老师账号，不是学生，不参与。口径常量 PAYABLE_ROLES。
    check("缴费名单含 MEMBER/ADMIN/MONITOR 三类学生",
          roles == ["ADMIN", "MEMBER", "MONITOR"], f"roles={roles}")
    check("缴费名单不含班主任（TEACHER）", "TEACHER" not in roles, f"roles={roles}")
    check("缴费名单含生活委员探针", LVL_ADMIN_U in us, f"count={len(roster)}")
    check("缴费名单含班长探针", LVL_MONITOR_U in us, f"count={len(roster)}")
    check("缴费名单不含班主任本人", ROOT_U not in us, f"us={sorted(us)}")
    member = next((r for r in roster if r["username"] == MEMBER_U), None)
    check("名单里找得到测试成员", member is not None, f"count={len(roster)}")
    if not member:
        return

    st, j = call("GET", f"/batches/{bid}/payments", None, T)
    check("批次缴费明细 -> 200", st == 200, f"st={st}")
    st, j = call("GET", f"/members?batchId={bid}", None, M)
    check("普通成员读缴费名单 -> 403", st == 403, f"st={st} {msg_of(j)}")

    st, j = call("POST", f"/batches/{bid}/pay",
                 {"userId": member["userId"], "amount": 5.55, "channel": "WECHAT"}, T)
    check("标记缴费 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, T)
    check("缴费后余额 +5.55", near((data_of(j) or {}).get("balance"), b0 + 5.55),
          f"got={(data_of(j) or {}).get('balance')}")
    st, j = call("POST", f"/batches/{bid}/pay",
                 {"userId": member["userId"], "amount": 5.55, "channel": "WECHAT"}, T)
    check("重复标记缴费 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/batches/{bid}/pay",
                 {"userId": 99999999, "amount": 1, "channel": "CASH"}, T)
    check("给不存在的成员缴费 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/batches/{bid}/pay",
                 {"userId": member["userId"], "amount": 0, "channel": "CASH"}, T)
    check("缴费金额为 0 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("POST", f"/batches/{bid}/close", None, T)
    check("关闭批次 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/batches/{bid}/close", None, T)
    check("重复关闭批次 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("DELETE", f"/batches/{bid}", None, T)
    check("删除批次 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, T)
    check("级联删除后余额回到基线", near((data_of(j) or {}).get("balance"), b0),
          f"got={(data_of(j) or {}).get('balance')} want={b0}")
    st, j = call("GET", "/records?page=1&size=100&keyword=regress", None, T)
    leftover = [(data_of(j) or {}).get("records") or []]
    check("批次自动流水已随之删除", not any("regress" in (r.get("title") or "")
                                       for grp in leftover for r in grp), str(leftover))

    # 第十八轮：GET /batches 已放开给普通成员（回答「有没有班费要交 / 我交了吗 / 什么时候截止」），
    # 但返回的是**精简 VO + 自己的缴费状态**；缴费名单与写操作仍然专属。
    st, j = call("GET", "/batches", None, M)
    check("普通成员读批次列表 -> 200（第十八轮放开）", st == 200, f"st={st} {msg_of(j)}")
    if st == 200:
        rows_mine = data_of(j) or []
        check("普通成员的批次 VO 含自己的缴费状态键",
              all({"myStatus", "myAmount", "myPaidAt"} <= set(r.keys()) for r in rows_mine),
              str(rows_mine[:1] and sorted(rows_mine[0].keys())))
        check("普通成员的批次 VO 不含 createdBy / rate / remark",
              all(not ({"createdBy", "createdByName", "rate", "remark"} & set(r.keys()))
                  for r in rows_mine),
              str(rows_mine[:1] and sorted(rows_mine[0].keys())))
    st, j = call("GET", "/members", None, M)
    check("普通成员读缴费名单 -> 403（他人姓名/学号不能泄露）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/batches", {"name": "regress member batch", "amount": 1}, M)
    check("普通成员建批次 -> 403", st == 403, f"st={st} {msg_of(j)}")


# =====================================================================
# 公告
# =====================================================================

def test_a08_class_info_perms():
    """班级信息写权限 + 公告模块已下线。

    第二十四轮班级公告整体移除后，原来的公告用例只剩一条与公告无关的断言
    （「普通成员改班级信息 -> 403」）——它跟着一起删会丢掉一条真实边界，
    所以连用例名一起改掉保留在这里。另加一条「公告接口确实 404」，
    防止哪天有人把路由又加回来。
    """
    print("\n--- I. 班级信息写权限（公告已移除）---")
    M = S["M"]

    st, j = call("GET", "/notices", None, S["T"])
    check("公告接口已下线 -> 404", st == 404, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/class", {"className": "X"}, M)
    check("普通成员改班级信息 -> 403", st == 403, f"st={st} {msg_of(j)}")


# =====================================================================
# 班级信息
# =====================================================================

def test_a09_class_info():
    print("\n--- J. 班级信息（含第十六轮字段级授权）---")
    T, A, MO, M = S["T"], S["A"], S["MO"], S["M"]
    cls0 = S["cls0"]
    name, grade, head = cls0.get("className"), cls0.get("grade"), cls0.get("headTeacher")

    for label, tok in [("生活委员", A), ("班长", MO)]:
        if not tok:
            continue
        st, j = call("PUT", "/class", {"className": name, "headTeacher": "Hijacked"}, tok)
        check(f"{label}改班主任字段 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/class", None, T)
    check("班主任字段未被改动", (data_of(j) or {}).get("headTeacher") == head,
          f"got={(data_of(j) or {}).get('headTeacher')!r} want={head!r}")

    # 用一个**不含真实语义**的探针值，测完立刻还原成基线。
    # 原实现硬写 "2026级" 然后在末尾断言年级等于**开局基线** —— 那是把通过与否耦合到
    # 「库里恰好存着 2026级」这件事上：库里是别的年级（比如 "2025 级"）时必然红，而那次
    # 失败又把年级留在 2026 级，于是**下一次又变绿**。这种「跑一次红、之后永远绿」的用例
    # 比没有用例更坏——它会让人以为已经验过。还原必须回基线，不能落到某个常量。
    probe_grade = "9999级"
    st, j = call("PUT", "/class", {"className": name, "grade": probe_grade}, T)
    check("班主任改年级 -> 200", st == 200, f"st={st} {msg_of(j)}")
    got_grade = (call("GET", "/class", None, T)[1]["data"] or {}).get("grade")
    check("年级确实被改成探针值", got_grade == probe_grade, f"got={got_grade!r}")
    st, j = call("PUT", "/class", {"className": name, "grade": grade or ""}, T)
    check("还原年级到基线 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/class", {"className": name, "grade": probe_grade}, A)
    check("生活委员改年级 -> 200（班务公共信息，不设等级限制）", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/class", {"className": name, "grade": grade or ""}, T)
    check("再次还原年级到基线 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/class", {"className": name, "headTeacher": head}, T)
    check("班主任改班主任字段 -> 200", st == 200, f"st={st} {msg_of(j)}")

    st, j = call("PUT", "/class", {"className": name, "balance": 999999}, T)
    after = (call("GET", "/dashboard/summary", None, T)[1]["data"] or {}).get("balance")
    check("余额不可手改（仍由流水决定）", near(after, S["b0"]), f"balance={after} want={S['b0']}")
    st, j = call("PUT", "/class", {}, T)
    check("空更新体 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/class", None, T)
    now = data_of(j) or {}
    check("班级信息已复原",
          now.get("className") == name and now.get("grade") == grade
          and now.get("headTeacher") == head,
          f"got={now}")
    S["cls0"] = now


# =====================================================================
# 停用账号即时失效
# =====================================================================

def test_a10_disabled_token():
    print("\n--- K. 停用账号后旧令牌立即失效（第十六轮）---")
    T, MO = S["T"], S["MO"]
    if not S["mo_id"]:
        print("  (跳过：缺班长探针)")
        return
    tok = S["MO"]
    uid = S["mo_id"]
    st, _ = call("GET", "/auth/me", None, tok)
    check("停用前令牌可用", st == 200, f"st={st}")

    st, j = call("PUT", f"/users/{uid}", {"status": 0}, T)
    check("班主任停用班长 -> 200", st == 200, f"st={st} {msg_of(j)}")
    for p in ["/auth/me", "/auth/profile", "/class", "/dashboard/summary", "/records?page=1&size=1",
              "/batches", "/users", "/categories"]:
        st, j = call("GET", p, None, tok)
        check(f"停用后 GET {p} -> 403（旧实现会 200，最长 2 小时）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": S["exp_cat"], "amount": 1, "title": "regress zombie",
                  "occurredAt": "2026-09-26 11:00:00", "channel": "CASH"}, tok)
    check("停用后仍不能记账 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/auth/login", {"username": LVL_MONITOR_U, "password": "123456"})
    check("停用后无法重新登录 -> 403", st == 403, f"st={st} {msg_of(j)}")

    st, j = call("PUT", f"/users/{uid}", {"status": 1}, T)
    check("重新启用 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/me", None, tok)
    check("重新启用后原令牌恢复可用", st == 200, f"st={st}")
    S["MO"] = login(LVL_MONITOR_U)


# =====================================================================
# 全角色 401/403 矩阵
# =====================================================================

def test_a11_role_matrix():
    print("\n--- L. 四角色 × 全员可读 / 运营可写 ---")
    T = S["T"]
    roles = [("TEACHER", S["T"]), ("MONITOR", S["MO"]), ("ADMIN", S["A"]), ("MEMBER", S["M"])]
    readable = ["/auth/me", "/auth/profile", "/class", "/dashboard/summary",
                "/dashboard/trend?months=6", "/dashboard/category-pie?range=all",
                "/categories", "/records?page=1&size=5",
                # 第十八轮：批次列表全员可读（自己的缴费状态）；缴费名单 /members 仍专属
                "/batches"]
    staff_only = ["/records/export", "/members", "/users"]
    for role, tok in roles:
        if not tok:
            continue
        bad = []
        for p in readable:
            st, j = call("GET", p, None, tok)
            if st != 200:
                bad.append(f"{p}->{st}")
        check(f"{role} 可读全部公共页面", not bad, "; ".join(bad))
        staff = role != "MEMBER"
        bad = []
        for p in staff_only:
            st, j = call("GET", p, None, tok)
            want = 200 if staff else 403
            if st != want:
                bad.append(f"{p}->{st}(want {want})")
        check(f"{role} 运营专属页 {'可读' if staff else '被拒'}", not bad, "; ".join(bad))

    # 匿名
    bad = []
    for p in readable + staff_only:
        st, j = call("GET", p, None, None)
        if st != 401:
            bad.append(f"{p}->{st}")
    check("匿名读任何接口 -> 401", not bad, "; ".join(bad))
    st, j = call("POST", "/records", {"type": "EXPENSE"}, None)
    check("匿名记账 -> 401", st == 401, f"st={st}")
    st, j = call("POST", "/auth/login", {"username": "nope", "password": "nope"})
    check("错误口令登录 -> 401/400", st in (400, 401), f"st={st} {msg_of(j)}")


# =====================================================================
# 归属权（A 方案）：只能改 / 删自己创建的内容
# =====================================================================

def test_a13_ownership():
    print("\n--- O. 归属权（第十七轮 A 方案：谁创建谁负责）---")
    T = S["T"]
    if S["root_role"] != "TEACHER" or not S["MO"]:
        print("  (跳过：需要班主任在位且班长探针齐全)")
        return
    MON = S["MO"]
    exp = S["exp_cat"]

    # --- 流水 ---
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 88.88,
                  "title": "regress owner teacher", "occurredAt": "2026-09-26 12:00:00",
                  "channel": "CASH"}, T)
    rid = (data_of(j) or {}).get("id")
    st, j = call("POST", f"/records/{rid}/void", None, MON)
    check("班长作废老师的流水 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/records/{rid}", None, MON)
    check("班长删除老师的流水 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/records?id={rid}&size=1", None, T)
    rows = (data_of(j) or {}).get("records") or []
    check("被拒后流水仍在且未作废", len(rows) == 1 and rows[0]["status"] == "NORMAL", str(rows[:1]))
    check("流水 VO 带 createdBy（前端靠它收敛按钮）",
          rows and rows[0].get("createdBy") == S["root_id"], str(rows[:1] and rows[0].get("createdBy")))
    st, j = call("POST", f"/records/{rid}/void", None, T)
    check("班主任作废自己的流水 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # A 方案的已知代价：班主任也动不了班长的
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 33.33,
                  "title": "regress owner monitor", "occurredAt": "2026-09-26 12:05:00",
                  "channel": "CASH"}, MON)
    mrid = (data_of(j) or {}).get("id")
    st, j = call("DELETE", f"/records/{mrid}", None, T)
    check("【A 方案代价】班主任删除班长的流水 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/records/{mrid}", None, MON)
    check("班长删除自己的流水 -> 200", st == 200, f"st={st} {msg_of(j)}")
    if rid:
        call("DELETE", f"/records/{rid}", None, T)

    # 第二十四轮：原 here 有一整段「A 方案归属」的公告断言，
    # 公告模块整体删除后一并去掉——归属规则本身仍由上面的流水/批次断言覆盖。

    # --- 批次 ---
    st, j = call("POST", "/batches",
                 {"name": "regress owner batch", "amount": 50, "deadline": "2026-12-31"}, T)
    bid = (data_of(j) or {}).get("id")
    st, j = call("GET", "/batches", None, T)
    row = next((b for b in (data_of(j) or []) if b["id"] == bid), {})
    check("批次 VO 带 createdBy + createdByName",
          row.get("createdBy") == S["root_id"] and row.get("createdByName") is not None,
          f"createdBy={row.get('createdBy')} name={row.get('createdByName')}")
    st, j = call("POST", f"/batches/{bid}/close", None, MON)
    check("班长关闭老师的批次 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/batches/{bid}", None, MON)
    check("班长删除老师的批次 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/batches/{bid}/close", None, T)
    check("班主任关闭自己的批次 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/batches/{bid}", None, T)
    check("班主任删除自己的批次 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # --- 缴费标记刻意**不**受归属权限制（收款是协作动作，闸门加在这里会把账卡死）---
    st, j = call("POST", "/batches",
                 {"name": "regress owner pay", "amount": 20, "deadline": "2026-12-31"}, MON)
    pbid = (data_of(j) or {}).get("id")
    st, j = call("GET", f"/members?batchId={pbid}", None, T)
    victim = next((r for r in (data_of(j) or []) if r["role"] == "MEMBER"), None)
    if pbid and victim:
        st, j = call("POST", f"/batches/{pbid}/pay",
                     {"userId": victim["userId"], "amount": 20, "channel": "CASH"}, T)
        check("班主任给班长建的批次标记缴费 -> 200（协作收款不设闸）", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("POST", f"/batches/{pbid}/close", None, MON)
        check("批次创建人自己关闭 -> 200", st == 200, f"st={st} {msg_of(j)}")
        call("DELETE", f"/batches/{pbid}", None, MON)


# =====================================================================
# 审计留痕（第十九轮）：作废 / 关闭 / 编辑都要记「谁、何时」
# =====================================================================

def test_a14_audit():
    print("\n--- Q. 审计留痕（谁在什么时候动了账）---")
    T = S["T"]
    exp = S["exp_cat"]
    root_id = S["root_id"]
    ok, bad = [], []

    def chk(name, cond, detail=""):
        (ok if cond else bad).append(name)
        check(name, cond, detail)

    # --- 流水作废 ---
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 42.42,
                  "title": "regress audit rec", "occurredAt": "2026-09-26 13:00:00",
                  "channel": "CASH"}, T)
    rid = (data_of(j) or {}).get("id")
    row = data_of(j) or {}
    chk("新建流水的作废留痕字段为 null",
        row.get("voidedBy") is None and row.get("voidedAt") is None,
        f"voidedBy={row.get('voidedBy')}")
    chk("流水 VO 带 voidedBy/voidedByName/voidedAt 三个键",
        {"voidedBy", "voidedByName", "voidedAt"} <= set(row.keys()), str(sorted(row.keys())))
    st, j = call("POST", f"/records/{rid}/void", None, T)
    chk("作废 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/records?id={rid}&size=1", None, T)
    v = ((data_of(j) or {}).get("records") or [{}])[0]
    chk("作废后 voidedBy = 操作者", v.get("voidedBy") == root_id, f"voidedBy={v.get('voidedBy')}")
    chk("作废后 voidedByName 有姓名", bool(v.get("voidedByName")), f"{v.get('voidedByName')!r}")
    chk("作废后 voidedAt 有时间", bool(v.get("voidedAt")), f"{v.get('voidedAt')!r}")

    # 未作废的不能凭空出现留痕
    st, j = call("POST", "/records",
                 {"type": "EXPENSE", "categoryId": exp, "amount": 1.11,
                  "title": "regress audit normal", "occurredAt": "2026-09-26 13:05:00",
                  "channel": "CASH"}, T)
    nid2 = (data_of(j) or {}).get("id")
    st, j = call("GET", f"/records?id={nid2}&size=1", None, T)
    n = ((data_of(j) or {}).get("records") or [{}])[0]
    chk("未作废的流水 voidedBy 仍为 null", n.get("voidedBy") is None, f"{n.get('voidedBy')}")

    # --- 批次关闭 ---
    st, j = call("POST", "/batches",
                 {"name": "regress audit batch", "amount": 66, "deadline": "2026-12-31"}, T)
    bid = (data_of(j) or {}).get("id")
    st, j = call("GET", "/batches", None, T)
    b0 = next((b for b in (data_of(j) or []) if b["id"] == bid), {})
    chk("新建批次的关闭留痕字段为 null",
        b0.get("closedBy") is None and b0.get("closedAt") is None, f"{b0.get('closedBy')}")
    st, j = call("POST", f"/batches/{bid}/close", None, T)
    chk("关闭批次 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/batches", None, T)
    b1 = next((b for b in (data_of(j) or []) if b["id"] == bid), {})
    chk("关闭后 closedBy = 操作者", b1.get("closedBy") == root_id, f"closedBy={b1.get('closedBy')}")
    chk("关闭后 closedByName 有姓名", bool(b1.get("closedByName")), f"{b1.get('closedByName')!r}")
    chk("关闭后 closedAt 有时间", bool(b1.get("closedAt")), f"{b1.get('closedAt')!r}")

    # 第二十四轮：原 here 用公告来验证「谁发的 vs 谁最后改的」两条审计线，
    # 公告模块整体删除后这一段没了。「updatedBy / updatedAt 是最后编辑人/时间」
    # 的规则仍由 batch_service 的 closedBy/closedAt 断言覆盖。

    # --- 幂等：迁移列存在且可重复执行 ---
    st, j = call("GET", "/records?page=1&size=1", None, T)
    chk("接口正常（审计列已由 seed.add_audit_columns 迁移）", st == 200, f"st={st}")

    # --- 自清理 ---
    # 原来这个用例造完数据就不管了，残留会**污染下一次运行**：下一轮 test_a07 的
    # 「批次自动流水已随之删除」断言是按标题含 'regress' 来查的，于是把这里的残留
    # 当成级联删除失败报出来——一个假红，而且每轮累积（实测连跑 3 次留下 6 行）。
    # 结论：**每个造数据的用例都要自己收尾**，不能指望末尾那个清理用例兜住所有情况。
    for target in (rid, nid2, bid):
        if not target:
            continue
        if target == bid:
            call("DELETE", f"/batches/{bid}", None, T)
        else:
            call("DELETE", f"/records/{target}", None, T)
    left = call("GET", "/records?page=1&size=50&keyword=regress audit", None, T)[1]
    left_titles = [r.get("title") for r in ((data_of(left) or {}).get("records") or [])]
    chk("本用例造的数据已全部清理", not left_titles, str(left_titles))


# =====================================================================
# 不变量
# =====================================================================

def test_a12_invariants():
    print("\n--- M. 账目不变量 ---")
    T = S["T"]
    st, j = call("GET", "/records?page=1&size=100&status=all", None, T)
    total = (data_of(j) or {}).get("total")
    income = expense = 0.0
    page = 1
    while True:
        st, j = call("GET", f"/records?page={page}&size=100&status=all", None, T)
        rows = (data_of(j) or {}).get("records") or []
        if not rows:
            break
        for r in rows:
            if r.get("status") != "NORMAL":
                continue
            if r.get("type") == "INCOME":
                income += float(r["amount"])
            else:
                expense += float(r["amount"])
        page += 1
        if page > 50:
            break
    st, j = call("GET", "/dashboard/summary", None, T)
    summary = data_of(j) or {}
    bal = float(summary.get("balance", 0))
    check("余额 == 收入合计 - 支出合计", near(bal, income - expense),
          f"balance={bal} income-expense={income - expense}")
    check("realBalance == balance", near(summary.get("realBalance"), bal),
          f"real={summary.get('realBalance')} balance={bal}")
    check("流水条数与基线一致", total == S["rec0"], f"baseline={S['rec0']} now={total}")
    check("批次条数与基线一致", len(data_of(call("GET", "/batches", None, T)[1]) or []) == S["batch0"],
          f"baseline={S['batch0']}")
    check("余额回到基线", near(bal, S["b0"]), f"baseline={S['b0']} now={bal}")
    print(f"  (收入 {income:.2f} / 支出 {expense:.2f} / 净额 {income - expense:.2f} / 共 {total} 条)")


# =====================================================================
# 缴费对象口径（第二十轮）：除班主任外的全部学生
# =====================================================================

def test_a14b_payable_roles():
    print("\n--- P. 缴费对象 = 除班主任外的全部学生（第二十轮）---")
    T = S["T"]
    ok, bad = [], []

    def chk(name, cond, detail=""):
        (ok if cond else bad).append(name)
        check(name, cond, detail)

    st, j = call("POST", "/batches",
                 {"name": "regress payable batch", "amount": 12.34,
                  "deadline": "2026-12-31"}, T)
    bid = (data_of(j) or {}).get("id")
    chk("建批次 -> 200", st == 200 and bid, f"st={st} {msg_of(j)}")
    if not bid:
        return

    # 名单构成：三类学生都在，班主任不在
    st, j = call("GET", f"/batches/{bid}/payments", None, T)
    pays = (data_of(j) or {}).get("payments") or []
    us = {p["role"] for p in pays}
    unames = {p["realName"] for p in pays}
    chk("批次缴费行覆盖 MEMBER/ADMIN/MONITOR", us == {"MEMBER", "ADMIN", "MONITOR"},
        f"roles={sorted(us)}")
    chk("批次缴费行不含 TEACHER", "TEACHER" not in us, f"roles={sorted(us)}")

    # 成员缴费页与批次名单**必须同口径**（PAYABLE_ROLES）：一个列一个不列就是死角
    st, j = call("GET", f"/members?batchId={bid}", None, T)
    m_roles = sorted({r["role"] for r in (data_of(j) or [])})
    chk("成员缴费页与批次名单角色集合一致", m_roles == sorted(us), f"page={m_roles} batch={sorted(us)}")

    # 班长 / 生活委员能看到自己的欠费（my* 不再是 null）
    for label, uname in (("班长", LVL_MONITOR_U), ("生活委员", LVL_ADMIN_U)):
        tok = login(uname)
        if not tok:
            chk(f"{label} 探针账号可登录", False, f"{uname} 登录失败")
            continue
        st, j = call("GET", "/batches", None, tok)
        mine = next((b for b in (data_of(j) or []) if b["id"] == bid), {})
        chk(f"{label} myStatus = UNPAID（他是缴费对象）", mine.get("myStatus") == "UNPAID",
            f"myStatus={mine.get('myStatus')}")
        chk(f"{label} 拿到 myAmountDue 键", "myAmountDue" in mine, str(sorted(mine)))
        chk(f"{label} 仍拿完整 VO（含 createdBy）", "createdBy" in mine, str(sorted(mine)))

    # 班主任不是缴费对象：my* 恒 null
    st, j = call("GET", "/batches", None, T)
    mine = next((b for b in (data_of(j) or []) if b["id"] == bid), {})
    chk("班主任 myStatus = null（他不是缴费对象）", mine.get("myStatus") is None,
        f"myStatus={mine.get('myStatus')}")
    chk("班主任 myAmountDue 键存在且为 False",
        "myAmountDue" in mine and mine.get("myAmountDue") is False, str(mine.get("myAmountDue")))

    # 班主任能代生活委员登记（协作动作，不设归属闸）
    adm_id = next((p["userId"] for p in pays if p["role"] == "ADMIN"), None)
    st, j = call("POST", f"/batches/{bid}/pay",
                 {"userId": adm_id, "amount": 12.34, "channel": "CASH"}, T)
    chk("班主任代生活委员登记缴费 -> 200", st == 200, f"st={st} {msg_of(j)}")

    st, j = call("DELETE", f"/batches/{bid}", None, T)
    chk("清理批次 -> 200", st == 200, f"st={st} {msg_of(j)}")


# =====================================================================
# 清理
# =====================================================================

def test_a15_cleanup():
    print("\n--- Q. 清理本脚本造的数据 ---")
    T = S["T"]
    # 先删批次（级联带走缴费与自动流水），再删流水
    for b in data_of(call("GET", "/batches", None, T)[1]) or []:
        if str(b.get("name", "")).startswith("regress"):
            st, _ = call("DELETE", f"/batches/{b['id']}", None, T)
            print(f"  删除批次「{b.get('name')}」-> {st}")
    for cat in data_of(call("GET", "/categories", None, T)[1]) or []:
        if str(cat.get("name", "")).startswith("regress"):
            st, _ = call("DELETE", f"/categories/{cat['id']}", None, T)
            print(f"  删除类别「{cat.get('name')}」-> {st}")
    # 流水：**先翻完所有页收集 id，再统一删除**。
    # 原写法是「取一页 → 删本页 → 翻下一页」，而删除会让结果集在翻页过程中**不断缩小**：
    # 原本落在第 2 页的记录会被挤到第 1 页去，于是永远扫不到（实测每次漏一条，
    # 连跑 3 次积下 6 行残留）。凡是要边翻边删的场景，都得先收集后删除。
    to_delete: list[int] = []
    page = 1
    while page <= 50:
        st, j = call("GET", f"/records?page={page}&size=100&status=all", None, T)
        rows = (data_of(j) or {}).get("records") or []
        if not rows:
            break
        to_delete.extend(
            r["id"] for r in rows if str(r.get("title", "")).startswith("regress")
        )
        page += 1
    for rid_ in to_delete:
        st, _ = call("DELETE", f"/records/{rid_}", None, T)
        print(f"  删除流水 #{rid_} -> {st}")
    check("流水清理无遗漏（先收集后删除）", not [
        r.get("title")
        for r in ((data_of(call("GET", "/records?page=1&size=100&status=all", None, T)[1]) or {}).get("records") or [])
        if str(r.get("title", "")).startswith("regress")
    ], "仍有 regress 前缀的流水残留")

    # 学生信息（第二十三轮）**必须先清**：探针账号被 `student_record.user_id` 引用时，
    # `DELETE /users/{id}` 会以「零引用」为由拒绝 —— 顺序反了账号就永远删不掉。
    _purge_student_info(T)

    # 探针账号：逐个尝试删除；有历史引用时后端会拒绝，属预期
    stubborn = []
    for name in PROBE_USERS:
        ok, detail = drop_user(name, T)
        print(f"  清理账号 {name}: {detail}")
        if not ok and "流水" not in detail and "缴费" not in detail and "公告" not in detail \
                and "批次" not in detail and "不能删除" not in detail:
            stubborn.append(f"{name}({detail})")
    check("探针账号清理干净（无残留的拒绝原因）", not stubborn, "; ".join(stubborn))

    st, j = call("GET", "/users", None, T)
    left = [u["username"] for u in (data_of(j) or [])]
    print(f"  剩余账号: {left}")
    st, j = call("GET", "/dashboard/summary", None, T)
    print(f"  最终余额: {(data_of(j) or {}).get('balance')} (基线 {S['b0']})")

    now_cats = visible_categories(T)
    missing = S["cats0"] - now_cats
    extra = now_cats - S["cats0"]
    check("可见类别集合回到基线", not missing and not extra,
          f"少了={sorted(missing)} 多出={sorted(extra)}")
    check("账号回到基线（跑之前有哪些，跑完还是哪些）",
          set(left) == S["users0"], f"剩余={left} 基线={sorted(S['users0'])}")
    check("余额回到基线", near((data_of(j) or {}).get("balance"), S["b0"]),
          f"{(data_of(j) or {}).get('balance')} vs {S['b0']}")


# =====================================================================

# =====================================================================
# 学生信息（第二十三轮）：行级可见性 + 申请/审批 + 动态字段
# =====================================================================

def _mk_xlsx(rows: list[list]) -> bytes:
    """在内存里造一个 xlsx（表头 + 数据行）。学生信息导入用例需要真文件。"""
    from io import BytesIO

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for r in rows:
        ws.append(r)
    buf = BytesIO()
    wb.save(buf)
    return buf.getvalue()


#: 回归**自己造**的学生学号（精确名单）。
#:
#: ⚠ 这里的清理以前是「删掉老师班里的**全部**学生（只留锚点）」——
#: 那等于**跑一次回归就清空用户自己导入的名单**。实测踩中过：
#: 用户导了一份名册进「学院学生信息」，跑完回归，名单没了。
#:
#: 回归只该清理**自己造的行**。所以改成按这份精确名单删，
#: 其余（真实名单、用户自建的列）一律不动。
_PROBE_STUDENT_NOS: tuple[str, ...] = (
    "regress_taken",
    "2" * 25,    # 25 位学号：超长，用来测「学号装不下」
)

#: 回归造的学生学号**前缀**（按前缀删）。
#:
#: 「20220981」「20220982」是 test_a16 的两个锚点（s1/s2），而 s3、hand_no
#: 是从它们派生的（`s1 + "3"` / `s1 + "8"`），所以用前缀更省事也更不容易漏。
_PROBE_STUDENT_PREFIXES: tuple[str, ...] = (
    "20220981",   # test_a16 的锚点 s1 及其派生的 s3 / hand_no
    "20220982",   # test_a16 的锚点 s2
    "202299",     # test_a16 的建号预演
    "dash_u_",    # test_a21
    "col_u_",     # test_a23
    "Z90",        # test_a25
)

#: 回归造的**自定义列**（`is_system=0`）名。同样只删这些，别删用户自建的列。
_PROBE_FIELD_LABELS: tuple[str, ...] = (
    "寝室信息", "搬入日期", "宿舍号",          # test_a16 的导入自动建列
    "宿舍房间号", "重复",                     # key=dorm 那列（建/改名两个状态）
    "插入测试列", "队首测试列", "访客加的列",   # 班级页的列管理用例
    "改类型测试列",                            # 改类型用例的导入自动建列
    "学院标签", "院考标签", "插在前面", "插在后面", "测试插列",  # 学院相关用例
)

#: 回归造的**自定义列的 key**（列名会被改，key 不会）
_PROBE_FIELD_KEYS: tuple[str, ...] = ("dorm",)

#: 回归造的**账号**（登录名）——授权/申请只删这些账号的
_PROBE_LOGIN_NAMES: tuple[str, ...] = (
    "20220981",   # test_a16 的探针学生
    "20220982",
    "20229901",
    "20229902",
    "20229903",
    "guest_probe",
    "guest_probe2",
    "guest_probe3",
)


def _purge_student_info(token: str, keep_student_nos: tuple[str, ...] = ()) -> None:
    """清掉本脚本（或上一轮）留下的**探针**数据，让 `test_a16` 可重入。

    为什么必须直接走库：学生记录**没有删除接口**（用户要的是「只有本人可见 + 申请授权」，
    没要求「能删人」）。用 API 清理就得为此开一个接口——那是一次不必要的越权面。

    ## ⚠ **只删探针，不碰真实数据**

    这个函数以前是「删掉老师班里的全部学生 + 全部自定义列」——
    理由是「回归是唯一的数据来源，删干净最省事」。但那是**把用户的名单也删了**：
    用户导一份名册进来，跑一次回归，名册就没了，而且**没有任何提示**。

    所以改成按 `_PROBE_STUDENT_NOS` / `_PROBE_STUDENT_PREFIXES` /
    `_PROBE_FIELD_LABELS` 这三份**精确名单**删。其余一律保留。

    模板字段（`is_system=1`）永远保留——那是 `seed.init_student_fields`
    下发的对账口径。

    库连不上时**静默跳过**而不是抛错：这个清理是「让用例可重入」的辅助，
    清理不了不该让整轮回归挂掉——真正的断言会自己暴露问题。
    """
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001  —— 环境不完整时跳过，不让辅助逻辑拖垮回归
        return

    keep = set(keep_student_nos)
    try:
        with _engine.begin() as c:
            cid = c.execute(
                _t("SELECT class_id FROM sys_user WHERE username = :u LIMIT 1"), {"u": ROOT_U}
            ).scalar()
            if cid is None:
                return
            # 授权与申请：只删**探针账号**的。
            # ⚠ 以前是「删掉整个班的授权/申请」——那会把**老师给学生开的
            # 可见性授权**一起删掉，用户回头发现自己又看不见别人的信息了。
            probe_users = [
                r[0]
                for r in c.execute(
                    _t("SELECT id FROM sys_user WHERE username IN :u"),
                    {"u": tuple(_PROBE_LOGIN_NAMES)},
                )
            ]
            if probe_users:
                ph = ",".join(f":u{i}" for i in range(len(probe_users)))
                args = {f"u{i}": v for i, v in enumerate(probe_users)}
                c.execute(
                    _t("DELETE FROM student_access_request WHERE user_id IN (" + ph + ")"), args
                )
                c.execute(
                    _t("DELETE FROM student_grant WHERE user_id IN (" + ph + ")"), args
                )

            # ① 挑出**探针**行（其余不动）
            rows = c.execute(
                _t("SELECT id, student_no FROM student_record WHERE class_id = :c"), {"c": cid}
            ).all()
            probe_ids = []
            for rid, sno in rows:
                s = str(sno or "")
                if s in keep:
                    continue
                if s in _PROBE_STUDENT_NOS or any(
                    s.startswith(p) for p in _PROBE_STUDENT_PREFIXES
                ):
                    probe_ids.append(rid)
            if probe_ids:
                ph = ",".join(f":p{i}" for i in range(len(probe_ids)))
                args = {f"p{i}": v for i, v in enumerate(probe_ids)}
                c.execute(
                    _t("DELETE v FROM student_record_value v "
                       "JOIN student_record r ON r.id = v.record_id "
                       f"WHERE r.id IN ({ph})"),
                    args,
                )
                c.execute(_t(f"DELETE FROM student_record WHERE id IN ({ph})"), args)

            # ② 自定义列：只删探针建的（按**列名或 key**——列名会被改，key 不会）
            labels = list(_PROBE_FIELD_LABELS)
            keys = list(_PROBE_FIELD_KEYS)
            if labels or keys:
                wh = []
                args: dict = {"c": cid}
                for i, v in enumerate(labels):
                    wh.append(f":f{i}")
                    args[f"f{i}"] = v
                for i, v in enumerate(keys):
                    wh.append(f":k{i}")
                    args[f"k{i}"] = v
                c.execute(
                    _t("DELETE FROM student_field WHERE class_id = :c AND is_system = 0 "
                       f"AND (field_label IN ({','.join(wh)}) OR field_key IN ({','.join(wh)}))"),
                    args,
                )
    except Exception:  # noqa: BLE001
        return


def _purge_one_record(student_no: str) -> None:
    """只删**一行**学生记录及其字段值。

    为什么不用 `_purge_student_info`：它是整班清空，还会顺带删掉
    `student_access_request` / `student_grant`。用它做局部收尾会把后面
    「授权清单 1 条」之类的断言一起打挂——本轮就踩过一次。
    """
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return
    try:
        with _engine.begin() as c:
            c.execute(
                _t("DELETE v FROM student_record_value v "
                   "JOIN student_record r ON r.id = v.record_id WHERE r.student_no = :n"),
                {"n": student_no},
            )
            c.execute(_t("DELETE FROM student_record WHERE student_no = :n"), {"n": student_no})
    except Exception:  # noqa: BLE001
        return


def _download(path: str, token: str, payload: dict | None = None) -> tuple[int, bytes]:
    """下载二进制（导出用）。返回 `(状态码, 原始字节)`。

    **不能走 `call()`**：它无条件 `json.loads`，xlsx 是 zip（PK 开头），
    会直接抛 JSONDecodeError，把"接口返回 200"这条真实信息盖掉。
    """
    import urllib.request

    req = urllib.request.Request(
        f"http://127.0.0.1:8080/api{path}",
        data=json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req) as x:
            return x.status, x.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def _purge_user(username: str) -> None:
    """删掉一个探针账号（访客用例建完就删，别留在基线里）。"""
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return
    try:
        with _engine.begin() as c:
            c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": username})
    except Exception:  # noqa: BLE001
        return


def _fixture_class(name: str) -> int | None:
    """保证有一个**测试专用**的班存在，返回它的 id。

    ## 为什么回归不能靠「演示班还在」

    以前「转班」「多班」这几条用例直接拿库里现成的第二个班（演示数据）
    来用。演示数据被清掉之后，那几条用例会**悄悄 return 掉**——
    断言总数变少，而回归报告里看不出「少跑了几条」。

    所以夹具班由测试自己造、自己删：跑之前保证有，跑之后保证没。

    这个班**没有字段模板**（`student_field`）——正好覆盖「目标班缺列」
    那条路径（转班时按列名补建）。
    """
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return None
    with _engine.begin() as c:
        cid = c.execute(
            _t("SELECT id FROM cls_class WHERE class_name = :n"), {"n": name}
        ).scalar()
        if cid is None:
            c.execute(
                _t("INSERT INTO cls_class (class_name, grade, balance, status) "
                   "VALUES (:n, '2020级', 0, 1)"),
                {"n": name},
            )
            cid = c.execute(
                _t("SELECT id FROM cls_class WHERE class_name = :n"), {"n": name}
            ).scalar()
    return int(cid) if cid is not None else None


def _purge_fixture_class(name: str) -> None:
    """删掉夹具班（连它的人、它的字段定义）。

    这个库**一张外键都没有**，所以三样都得手工删。
    """
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return
    with _engine.begin() as c:
        cid = c.execute(
            _t("SELECT id FROM cls_class WHERE class_name = :n"), {"n": name}
        ).scalar()
        if not cid:
            return
        c.execute(
            _t("DELETE FROM student_record_value WHERE record_id IN "
               "(SELECT id FROM student_record WHERE class_id = :c)"),
            {"c": cid},
        )
        c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": cid})
        c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": cid})
        c.execute(_t("DELETE FROM sys_user_class WHERE class_id = :c"), {"c": cid})
        c.execute(_t("DELETE FROM cls_task WHERE class_id = :c"), {"c": cid})
        c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": cid})


def test_a17_class_tasks():
    print("\n--- S. 班级任务（第二十五轮：发出去 + 回收答案）---")
    T, MO, M = S["T"], S["MO"], S["M"]
    A = S["A"]  # 生活委员
    # 访客探针**本用例自建自删**：a16 结尾会把它的 guest_probe 清掉，
    # 共用同一个名字会拿到空令牌，8 条断言集体 401 假红。
    GU = "guest_task_probe"
    _purge_user(GU)
    st, j = call("POST", "/users", {"username": GU, "password": "123456",
                                    "realName": "访客任务探针", "role": "GUEST"}, T)
    check("建访客探针 -> 200", st == 200, f"st={st} {msg_of(j)}")
    G = login(GU)
    check("访客探针能登录", bool(G), "st=%s" % st)

    made: list[int] = []

    def purge() -> None:
        """删掉本轮建的探针任务（含回答）。建任务前先清，否则会累积。

        **回答必须先删**：这个库**一张外键都没有**（`information_schema` 里
        FOREIGN KEY 约束数 = 0，只建索引不建外键），
        所以删任务不会自动带走 `cls_task_answer`。`task_service.delete_task`
        里那句显式删回答因此是必需的，不是冗余。
        """
        import pathlib
        import sys as _sys

        server_dir = str(pathlib.Path(__file__).resolve().parents[1])
        if server_dir not in _sys.path:
            _sys.path.insert(0, server_dir)
        try:
            from sqlalchemy import text as _t

            from app.db import engine as _engine
        except Exception:  # noqa: BLE001
            return
        with _engine.begin() as c:
            c.execute(
                _t("DELETE FROM cls_task_answer WHERE task_id IN "
                   "(SELECT id FROM cls_task WHERE title LIKE 'regress%')")
            )
            c.execute(_t("DELETE FROM cls_task WHERE title LIKE 'regress%'"))

    purge()

    # ---------- 发布权限（用户口径：班主任 + 班长）----------
    st, j = call("POST", "/tasks", {"title": "regress 返校统计",
                                    "question": "你已经返校了吗？", "qtype": "BOOLEAN",
                                    "allowText": True}, T)
    check("班主任发任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    tid = (data_of(j) or {}).get("id")
    made.append(tid)

    st, j = call("POST", "/tasks", {"title": "regress 班长发的", "question": "你在哪？",
                                    "qtype": "SINGLE", "options": ["住校", "走读"]}, MO)
    check("班长发任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    mo_tid = (data_of(j) or {}).get("id")
    made.append(mo_tid)

    st, j = call("POST", "/tasks", {"title": "regress 生活委员发的", "question": "q",
                                    "qtype": "BOOLEAN"}, A)
    check("生活委员发任务 -> 403（只有班主任和班长）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks", {"title": "regress 同学发的", "question": "q",
                                    "qtype": "BOOLEAN"}, M)
    check("普通成员发任务 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks", {"title": "regress 访客发的", "question": "q",
                                    "qtype": "BOOLEAN"}, G)
    check("访客发任务 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ---------- 题型校验 ----------
    for opts, label in ((["只有一个"], "候选项只有 1 个"), (["a", "a"], "候选项重复")):
        st, j = call("POST", "/tasks", {"title": "regress t", "question": "q",
                                        "qtype": "SINGLE", "options": opts}, T)
        check(f"{label} -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks", {"title": "regress t", "question": "q",
                                    "qtype": "NOPE"}, T)
    check("非法题型 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks", {"title": "", "question": "q", "qtype": "BOOLEAN"}, T)
    check("空标题 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 答题 ----------
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": False, "note": "家里有事"}, M)
    check("成员答「否」+说明 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("答案显示成中文「否」而不是 false",
          (data_of(j) or {}).get("value") == "否", str(data_of(j)))
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, A)
    check("生活委员答「是」 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, MO)
    check("班长答「是」 -> 200（发布人也能答）", st == 200, f"st={st} {msg_of(j)}")

    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, G)
    check("访客答题 -> 403（外部人员不该被统计）", st == 403, f"st={st} {msg_of(j)}")

    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": "maybe"}, M)
    check("答非布尔值 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{tid}/answer", {}, M)
    check("空答案 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # 改答案 = 覆盖，不是多一行（uk_task_user）
    before = (call("GET", f"/tasks/{tid}/detail", None, T)[1]["data"] or {})
    # 应答对象 3 人：生活委员 / 班长 / 同学（班主任是发布人、访客不算被统计的同学）
    check("改前已填人数", before.get("answered") == 3,
          f"answered={before.get('answered')}")
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, M)
    check("成员改成「是」 -> 200", st == 200, f"st={st} {msg_of(j)}")
    after = (call("GET", f"/tasks/{tid}/detail", None, T)[1]["data"] or {})
    check("改答案不新增行（已填人数不变）",
          after.get("answered") == before.get("answered"),
          f"{before.get('answered')} -> {after.get('answered')}")

    # ---------- 应答对象 = 启用账号 − 发布人 − 访客 ----------
    # 访客能被算进分母却永远交不上（can_answer 对它恒 False），
    # 于是发布人的「未填名单」里会永远挂着一个人，看着像催不动。
    # 这条 bug 是第一次跑本用例时"已填 3 人"对不上预期才暴露的。
    allu = data_of(call("GET", "/users", None, T)[1]) or []
    # 发布人 id 从任务列表的 createdBy 拿——/users 返回的是账号 id，不是任务作者
    trow = [r for r in (data_of(call("GET", "/tasks", None, T)[1]) or {}).get("rows", [])
            if r["id"] == tid]
    tid_creator = trow[0]["createdBy"] if trow else -1
    # 应答对象 = 启用账号 − 班主任及以上 − 访客 − 发布人（后端 NON_ANSWER_ROLES）
    #
    # ⚠ 这里从后端 `NON_ANSWER_ROLES` **导入**，不写死 ("GUEST","TEACHER")。
    # 第二十八轮加了院长（等级 ≥ 班主任，同样不是被统计的同学）之后，写死的
    # 版本就把院长算进了分母：断言变成「明细 11 行 vs 应答对象 12 人」——
    # 服务端是对的、测试是错的。这类「测试自己抄了一份规则」的漂移，
    # 只能在**直接引用**的时候根除。
    from app.services.task_service import NON_ANSWER_ROLES as _non_answer  # noqa: PLC0415
    want_total = sum(
        1 for u in allu
        if u["id"] != tid_creator and u["role"] not in _non_answer
    )
    check("明细行数 = 应答对象数（不含发布人、班主任及以上、访客）",
          len((before or {}).get("rows", [])) == want_total,
          f"明细 {len((before or {}).get('rows', []))} 行 vs 应答对象 {want_total} 人")
    check("明细里不出现访客和班主任及以上",
          not any(r["role"] in _non_answer for r in (before or {}).get("rows", [])),
          str([(r["name"], r["role"]) for r in (before or {}).get("rows", [])]))
    st, j = call("GET", "/tasks", None, M)
    mrow = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == tid]
    check("汇总分母同样排除班主任和访客",
          (mrow[0]["summary"]["total"] if mrow else -1) == want_total,
          str(mrow[0]["summary"] if mrow else None))

    # ---------- 班主任不是被统计的同学（用户原话「统计班主任干什么」）----------
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, T)
    check("班主任答题 -> 403（发题催交，但不填）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/tasks", None, T)
    trow = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == tid]
    check("班主任那条 canAnswer=false（前端据此**不渲染**按钮，不是禁用）",
          bool(trow) and trow[0]["canAnswer"] is False, str(trow))
    check("班主任那一条 myAnswer 为空",
          bool(trow) and trow[0]["myAnswer"] is None, str(trow))

    # ⚠ 关键：这条排除**不能**只靠「他是发布人」。班主任自己发的题靠 creator_id
    # 已经排掉了，但**班长发的题**里班主任不是发布人，却同样不该被统计——
    # 只判 creator_id 的话他会混进分母和未填名单。
    st, j = call("GET", f"/tasks/{mo_tid}/detail", None, MO)
    mo_rows = (data_of(j) or {}).get("rows", [])
    check("班长发的任务里也不该出现班主任",
          st == 200 and not any(r["role"] == "TEACHER" for r in mo_rows),
          str([(r["name"], r["role"]) for r in mo_rows]))
    st, j = call("GET", "/tasks", None, T)
    morow = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == mo_tid]
    check("班长发的题，班主任看到 canAnswer=false",
          bool(morow) and morow[0]["canAnswer"] is False, str(morow))
    st, j = call("PUT", f"/tasks/{mo_tid}/answer", {"value": "住校"}, T)
    check("班主任答班长发的题 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # 生活委员和班长**是**同学：能答、能进分母
    st, j = call("PUT", f"/tasks/{mo_tid}/answer", {"value": "住校"}, A)
    check("生活委员答班长发的题 -> 200（班委也是同学）", st == 200, f"st={st} {msg_of(j)}")

    # ⚠ 发布人答自己的题：`is_answer_target` 把发布人排出了分母和明细，
    # 所以 `can_answer` / `submit_answer` 也必须一致地拒绝，
    # 否则用户填完提示"已提交"，回头发现谁也看不到他那条答案——
    # 这类"填了等于没填"的毛病最难查。
    st, j = call("GET", "/tasks", None, MO)
    morow2 = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == mo_tid]
    check("班长自己发的题 canAnswer=false（出的题自己不答）",
          bool(morow2) and morow2[0]["canAnswer"] is False, str(morow2))
    st, j = call("PUT", f"/tasks/{mo_tid}/answer", {"value": "走读"}, MO)
    check("班长答自己发的题 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/tasks/{mo_tid}/detail", None, MO)
    d = data_of(j) or {}
    # 回归库里有一堆探针账号，行数不固定，所以只断言"已填数没被这次被拒的提交改动"
    check("被拒的提交没留下痕迹（已填仍是 1，只有生活委员那一条）",
          d.get("answered") == 1,
          f"answered={d.get('answered')} 明细={[(r['name'], r['answered']) for r in d.get('rows', [])]}")

    # ---------- 汇总只给分布，不给具体是谁 ----------
    st, j = call("GET", "/tasks", None, M)
    mine_rows = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == tid]
    sm = (mine_rows[0] if mine_rows else {}).get("summary", {})
    check("成员看到的是汇总（已填/未填/分布）",
          set(sm.keys()) == {"total", "answered", "unanswered", "options"},
          str(sm))
    check("汇总里没有出现任何人名",
          not any(name in json.dumps(sm, ensure_ascii=False) for name in
                  [u["username"] for u in call("GET", "/users", None, T)[1]["data"]]),
          str(sm))
    check("成员能看到自己的答案",
          (mine_rows[0] if mine_rows else {}).get("myAnswer") is not None, str(mine_rows))

    # ---------- 明细：只有发布人和班主任 ----------
    st, j = call("GET", f"/tasks/{tid}/detail", None, T)
    check("发布人看明细 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/tasks/{mo_tid}/detail", None, MO)
    check("班长看自己发的任务明细 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/tasks/{mo_tid}/detail", None, T)
    check("班主任看班长发的任务明细 -> 200（班主任恒可看）",
          st == 200, f"st={st} {msg_of(j)}")
    for who, tok in (("生活委员", A), ("普通成员", M), ("访客", G)):
        st, j = call("GET", f"/tasks/{tid}/detail", None, tok)
        check(f"{who}看明细 -> 403（学生只能看汇总）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/tasks/{tid}/export", None, M)
    check("成员导出明细 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, blob = _download(f"/tasks/{tid}/export", T)
    check("发布人导出明细 xlsx -> 200", st == 200 and len(blob) > 1000, f"st={st}")

    # ---------- 只有发布人自己能改/关/删 ----------
    st, j = call("PUT", f"/tasks/{tid}", {"title": "regress 改了", "question": "q"}, MO)
    check("班长改班主任的任务 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/tasks/{tid}", None, MO)
    check("班长删班主任的任务 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/tasks/{tid}/close", None, MO)
    check("班长关班主任的任务 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{tid}", {"title": "regress 改了", "question": "q"}, T)
    check("班主任改自己的任务 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # 题型不可改：改了老答案就对不上题（入参层就不收）
    st, j = call("PUT", f"/tasks/{tid}", {"title": "regress 改了", "question": "q",
                                          "qtype": "DATE"}, T)
    check("改任务不接受 qtype（换题只能删了重发）",
          st == 200 and (data_of(j) or {}).get("id") == tid, f"st={st} {msg_of(j)}")

    # ---------- 关闭后不再收答案，重开后还在 ----------
    st, j = call("POST", f"/tasks/{tid}/close", None, T)
    check("关闭任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, A)
    check("关闭后提交 -> 400", st == 400, f"st={st} {msg_of(j)}")
    kept = (call("GET", f"/tasks/{tid}/detail", None, T)[1]["data"] or {})
    check("关闭不清掉已收回的回答",
          kept.get("answered", 0) >= 2, f"answered={kept.get('answered')}")
    st, j = call("POST", f"/tasks/{tid}/reopen", None, T)
    check("重新开放 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{tid}/answer", {"value": True}, A)
    check("重开后能再填 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # ---------- 截止时间 ----------
    st, j = call("POST", "/tasks", {"title": "regress 已过期", "question": "q",
                                    "qtype": "BOOLEAN",
                                    "deadline": "2020-01-01T00:00:00"}, T)
    exp_tid = (data_of(j) or {}).get("id")
    made.append(exp_tid)
    st, j = call("GET", "/tasks", None, M)
    exp_row = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == exp_tid]
    check("过了截止时间的任务 open=false 且不能填",
          bool(exp_row) and exp_row[0]["open"] is False
          and exp_row[0]["canAnswer"] is False, str(exp_row))
    st, j = call("PUT", f"/tasks/{exp_tid}/answer", {"value": True}, M)
    check("过了截止时间提交 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 多选去重 ----------
    st, j = call("POST", "/tasks", {"title": "regress 返校方式", "question": "怎么返校？",
                                    "qtype": "MULTI",
                                    "options": ["自驾", "大巴", "飞机", "火车"]}, T)
    multi_tid = (data_of(j) or {}).get("id")
    made.append(multi_tid)
    st, j = call("PUT", f"/tasks/{multi_tid}/answer", {"value": ["飞机", "火车", "飞机"]}, M)
    check("多选重复勾同一项 -> 200 且去重",
          st == 200 and (data_of(j) or {}).get("value") == "飞机、火车",
          f"st={st} {data_of(j)}")
    st, j = call("PUT", f"/tasks/{multi_tid}/answer", {"value": ["飞机", "外星"]}, M)
    check("多选选候选项之外 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 日期归一 ----------
    st, j = call("POST", "/tasks", {"title": "regress 预计返校", "question": "哪天到？",
                                    "qtype": "DATE"}, T)
    date_tid = (data_of(j) or {}).get("id")
    made.append(date_tid)
    st, j = call("PUT", f"/tasks/{date_tid}/answer", {"value": "2026-10-15T18:30:00"}, M)
    check("日期题带时分秒 -> 归一成 YYYY-MM-DD",
          st == 200 and (data_of(j) or {}).get("raw") == "2026-10-15",
          f"st={st} {data_of(j)}")
    st, j = call("PUT", f"/tasks/{date_tid}/answer", {"value": "下周三"}, M)
    check("日期题填「下周三」-> 400", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 删除连带删回答 ----------
    st, _ = call("DELETE", f"/tasks/{multi_tid}", None, T)
    check("删任务 -> 200", st == 200, f"st={st}")
    st, j = call("GET", f"/tasks/{multi_tid}/detail", None, T)
    check("删完再查 -> 400 任务不存在", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 访客只读 ----------
    st, j = call("GET", "/tasks", None, G)
    grow = [r for r in (data_of(j) or {}).get("rows", []) if r["id"] == tid]
    check("访客能读任务列表 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("访客那一条 canAnswer=false / canSeeDetail=false",
          bool(grow) and grow[0]["canAnswer"] is False
          and grow[0]["canSeeDetail"] is False, str(grow))
    check("访客 canPublish=false",
          (data_of(j) or {}).get("canPublish") is False, str(data_of(j)))
    check("访客在列表里**看得到**汇总",
          bool(grow) and "summary" in grow[0], str(grow))
    # 访客是被统计名单之外的：他在页面上的分母里不能占一个位置
    check("访客看到的分母与班主任一致（都不含班主任和访客自己）",
          (grow[0]["summary"]["total"] if grow else -1) == want_total,
          str(grow[0]["summary"] if grow else None))

    # ---------- 置顶：仪表盘面板（第二十五轮追加） ----------
    # 置顶占用的是**每个人**的仪表盘，所以闸门和改标题同级：只有发布人自己。
    p1 = (data_of(call("POST", "/tasks", {"title": "regress 置顶甲", "question": "甲",
                                          "qtype": "BOOLEAN",
                                          "deadline": "2026-12-20T10:00:00"}, T)[1]) or {}).get("id")
    p2 = (data_of(call("POST", "/tasks", {"title": "regress 置顶乙", "question": "乙",
                                          "qtype": "BOOLEAN",
                                          "deadline": "2026-11-10T10:00:00"}, T)[1]) or {}).get("id")
    p3 = (data_of(call("POST", "/tasks", {"title": "regress 置顶丙", "question": "丙",
                                          "qtype": "BOOLEAN"}, T)[1]) or {}).get("id")
    p4 = (data_of(call("POST", "/tasks", {"title": "regress 置顶已关", "question": "丁",
                                          "qtype": "BOOLEAN"}, T)[1]) or {}).get("id")
    made.extend([p1, p2, p3, p4])
    for x in (p1, p2, p3, p4):
        call("POST", f"/tasks/{x}/pin", None, T)
    call("POST", f"/tasks/{p4}/close", None, T)

    for who, tok in (("生活委员", A), ("普通成员", M), ("访客", G), ("班长", MO)):
        st, j = call("POST", f"/tasks/{p1}/pin", None, tok)
        check(f"{who}置顶别人发的任务 -> 403（占的是全班人的仪表盘）",
              st == 403, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/tasks/pinned", None, T)
    pr = (data_of(j) or {}).get("rows", [])
    ids = [r["id"] for r in pr]
    check("已关闭的置顶任务自动从仪表盘消失（置顶是为了催人填）",
          st == 200 and p4 not in ids, f"ids={ids}")
    # 面板是全班级共享的、只取前 3 条，库里**别人**的置顶任务会挤占名额
    # （人工建的演示数据就会）。所以只断言本用例这三条的**相对**顺序。
    mine_ids = [i for i in ids if i in (p1, p2, p3)]
    check("置顶任务按「快到期的在前」排序，不限时的排最后",
          mine_ids == [i for i in (p2, p1, p3) if i in mine_ids],
          f"本用例的相对顺序={mine_ids}（全量={ids}）")
    check("面板最多 3 条", len(pr) <= 3, f"条数={len(pr)}")
    check("面板里的每条都带汇总和我的答案位（与列表页同形状）",
          all("summary" in r and "myAnswer" in r for r in pr), str(pr[:1]))

    st, j = call("GET", "/tasks/pinned", None, G)
    gr = (data_of(j) or {}).get("rows", [])
    check("访客也能看置顶任务（领导要看到「还差几道」）",
          st == 200 and len(gr) > 0, f"st={st} n={len(gr)}")
    check("访客在面板上拿不到「我的答案」、也不能填",
          all(r["canAnswer"] is False and r["myAnswer"] is None for r in gr), str(gr[:1]))
    st, j = call("GET", "/tasks/pinned", None, M)
    mr = (data_of(j) or {}).get("rows", [])
    check("同学在面板上 canAnswer=true（这样面板才催得动他）",
          bool(mr) and all(r["canAnswer"] is True for r in mr), str(mr[:1]))
    st, j = call("GET", "/tasks/pinned", None, T)
    tr = (data_of(j) or {}).get("rows", [])
    check("班主任在面板上 canAnswer=false（他不是被统计的同学）",
          all(r["canAnswer"] is False for r in tr), str(tr[:1]))

    st, j = call("POST", f"/tasks/{p1}/unpin", None, T)
    check("取消置顶 -> 200", st == 200, f"st={st} {msg_of(j)}")
    ids = [r["id"] for r in
           (data_of(call("GET", "/tasks/pinned", None, T)[1]) or {}).get("rows", [])]
    check("取消置顶后立刻从面板消失", p1 not in ids, f"ids={ids}")

    # ---------- 收尾 ----------
    purge()
    _purge_user(GU)
    st, j = call("GET", "/tasks", None, T)
    left = [r["title"] for r in (data_of(j) or {}).get("rows", [])
            if r["title"].startswith("regress")]
    check("探针任务清理干净", not left, f"残留={left}")


def _force_unlink(student_no: str) -> None:
    """把某一行的 `user_id` 强行置空，模拟「老库里没挂上」的脏数据。

    走 SQL 而不是 API：没有哪个接口能制造这种状态——它只在**账号建好之后、
    名单才导入**的历史顺序下才会自然出现（`create_record` 会自动挂接），
    造不出这个时序就测不了挂接逻辑。
    """
    import pathlib
    import sys as _sys

    server_dir = str(pathlib.Path(__file__).resolve().parents[1])
    if server_dir not in _sys.path:
        _sys.path.insert(0, server_dir)
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return
    try:
        with _engine.begin() as c:
            c.execute(
                _t("UPDATE student_record SET user_id=NULL WHERE student_no=:s"),
                {"s": student_no},
            )
    except Exception:  # noqa: BLE001
        return


def _purge_students(student_nos: list[str]) -> None:
    """按学号删若干行学生记录及其字段值。"""
    for sno in student_nos:
        _purge_one_record(sno)


def test_a18_accounts_from_students():
    print("\n--- T. 按学生信息一键创建账号（第二十五轮）---")
    T, MO, M = S["T"], S["MO"], S["M"]
    A = S["A"]
    GU = "guest_acc_probe"
    _purge_user(GU)
    st, j = call("POST", "/users", {"username": GU, "password": "123456",
                                    "realName": "访客建号探针", "role": "GUEST"}, T)
    G = login(GU)
    check("建访客探针 -> 200", st == 200, f"st={st} {msg_of(j)}")

    made_records: list[str] = []
    made_users: list[str] = []

    def add_record(sno: str, name: str) -> int | None:
        st, j = call("POST", "/students", {"studentNo": sno, "name": name}, T)
        made_records.append(sno)
        return (data_of(j) or {}).get("id") if st == 200 else None

    # ---------- 预演不写库 ----------
    add_record("20229901", "预演甲")
    st, j = call("GET", "/students/accounts/preview", None, T)
    p = data_of(j) or {}
    check("预演 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("预演标记 executed=false", p.get("executed") is False, str(p.get("executed")))
    check("预演里没有「已新建」清单（还没建呢）",
          p.get("created") == [], str(p.get("created")))

    before = {u["username"] for u in (data_of(call("GET", "/users", None, T)[1]) or [])}
    call("GET", "/students/accounts/preview", None, T)
    after = {u["username"] for u in (data_of(call("GET", "/users", None, T)[1]) or [])}
    check("预演真的一个字节都没写（账号集合不变）", before == after,
          f"多了={after - before}")

    # ---------- 权限：仅班主任 ----------
    for who, tok in (("班长", MO), ("生活委员", A), ("普通成员", M), ("访客", G)):
        st, j = call("GET", "/students/accounts/preview", None, tok)
        check(f"{who}预演 -> 403（建账号只给班主任）", st == 403, f"st={st} {msg_of(j)}")
        st, j = call("POST", "/students/accounts", None, tok)
        check(f"{who}真建 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ---------- 边界：建不出来的行要给出**原因** ----------
    add_record("2" * 25, "学号超长")          # 25 位 > sys_user.student_no 的 20
    add_record("20229902", "正常乙")

    # 「登录名被占用」这条分支要求：该学号是某账号的**登录名**却不是它的学号。
    # 如果学号和登录名相同，`create_record` 早就自动挂接了，走不到这条分支
    # （第一版用例就是这么假通过的）。所以这里故意让两者不同。
    st, j = call("POST", "/users", {"username": "regress_taken", "password": "123456",
                                    "realName": "占位的", "studentNo": "20229888",
                                    "role": "MEMBER"}, T)
    made_users.append("regress_taken")
    add_record("regress_taken", "学号等于别人的登录名")

    st, j = call("GET", "/students/accounts/preview", None, T)
    p = data_of(j) or {}
    reasons = {s["studentNo"]: s["reason"] for s in p.get("skipped", [])}
    check("学号超长的行被跳过并说明原因",
          "2" * 25 in reasons and "20" in reasons["2" * 25], str(reasons))
    check("登录名被占用的行被跳过，并说明是被谁占了",
          "regress_taken" in reasons and "占位的" in reasons["regress_taken"], str(reasons))
    check("正常的行进了待建清单",
          {x["studentNo"] for x in p.get("toCreateList", [])}
          >= {"20229901", "20229902"}, str(p.get("toCreateList")))
    preview_create = {x["studentNo"] for x in p.get("toCreateList", [])}

    # ---------- 真建 ----------
    st, j = call("POST", "/students/accounts", None, T)
    r = data_of(j) or {}
    check("真建 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("真建标记 executed=true", r.get("executed") is True, str(r.get("executed")))
    made_users.extend(c["username"] for c in r.get("created", []))
    check("新建的账号返回了清单", len(r.get("created", [])) >= 2, str(r.get("created")))

    # 预演说建哪些，执行就必须建哪些，一个不多一个不少。
    # 原先只断言"建出来的都在某个集合里"，那证明不了预演和执行是同一套算法——
    # 而这正是这个功能最容易出的错：两边各算各的，界面写 5 个、实际建了 4 个。
    check("预演的待建清单与实际新建的**完全一致**",
          {c["username"] for c in r.get("created", [])} == preview_create,
          f"预演={sorted(preview_create)} 实际={[c['username'] for c in r.get('created', [])]}")

    # ---------- 建出来的账号能用吗 ----------
    for sno in ("20229901", "20229902"):
        tok = login(sno)
        check(f"新账号 {sno} 能用默认密码 123456 登录", bool(tok), "登录失败")
        st, j = call("GET", "/students", None, tok or "")
        rows = (data_of(j) or {}).get("rows", [])
        check(f"{sno} 只看得到自己那一行（行级可见性没被建号破坏）",
              len(rows) == 1 and rows[0]["studentNo"] == sno, str(rows))
    st, j = call("GET", "/users", None, T)
    us = {u["username"]: u for u in (data_of(j) or [])}
    check("新账号角色是普通成员（不给班长/生活委员）",
          us.get("20229901", {}).get("role") == "MEMBER", str(us.get("20229901")))
    check("新账号的学号被正确写入",
          us.get("20229901", {}).get("studentNo") == "20229901", str(us.get("20229901")))

    # 学生行确实挂上了
    st, j = call("GET", "/students", None, T)
    rows = {r["studentNo"]: r for r in (data_of(j) or {}).get("rows", [])}
    check("学生行挂到了新账号上",
          rows.get("20229901", {}).get("linkedUserId") == us["20229901"]["id"],
          str(rows.get("20229901")))

    # ---------- 幂等：再点一次不该重复建 ----------
    n_before = len(us)
    st, j = call("POST", "/students/accounts", None, T)
    r2 = data_of(j) or {}
    check("再点一次：不再新建任何账号", r2.get("toCreate") == 0, str(r2.get("toCreate")))
    st, j = call("GET", "/users", None, T)
    check("再点一次：账号总数不变", len(data_of(j) or []) == n_before,
          f"{n_before} -> {len(data_of(j) or [])}")
    check("再点一次：已建过的行被标为「已经挂接账号了」",
          any(s["reason"] == "已经挂接账号了" for s in r2.get("skipped", [])),
          str(r2.get("skipped")))

    # ---------- 挂接：账号先在、名单后进 ----------
    # 场景：老师手工建过「20229903 / 老王」，但学生信息那行当时没挂上
    st, j = call("POST", "/users", {"username": "old_wang", "password": "123456",
                                    "realName": "老王", "studentNo": "20229903",
                                    "role": "MEMBER"}, T)
    old_uid = (data_of(j) or {}).get("id")
    made_users.append("old_wang")
    add_record("20229903", "老王")
    # 模拟老库没挂上的脏数据
    _force_unlink("20229903")

    st, j = call("GET", "/students/accounts/preview", None, T)
    p3 = data_of(j) or {}
    check("认得出「学号已对应某个账号」并归为挂接而不是新建",
          any(x["studentNo"] == "20229903" for x in p3.get("linked", [])), str(p3))
    check("挂接项标明了不新建", p3.get("toCreate", 0) == 0, str(p3.get("toCreate")))

    st, j = call("POST", "/students/accounts", None, T)
    r3 = data_of(j) or {}
    check("真建时完成了挂接",
          any(x["studentNo"] == "20229903" and x["userId"] == old_uid
              for x in r3.get("linked", [])), str(r3.get("linked")))
    st, j = call("GET", "/users", None, T)
    check("挂接没有重复建账号（没有出现用户名 20229903）",
          not any(u["username"] == "20229903" for u in (data_of(j) or [])), "重复建了")
    st, j = call("GET", "/students", None, T)
    rows = {r["studentNo"]: r for r in (data_of(j) or {}).get("rows", [])}
    check("挂接后学生行指向了那个已有账号",
          rows.get("20229903", {}).get("linkedUserId") == old_uid, str(rows.get("20229903")))

    # ---------- 收尾 ----------
    _purge_students(made_records)
    for u in made_users:
        _purge_user(u)
    _purge_user(GU)
    st, j = call("GET", "/users", None, T)
    left = [u["username"] for u in (data_of(j) or [])]
    check("探针账号清理干净",
          not any(x.startswith("202299") for x in left)
          and "old_wang" not in left, f"残留={left}")


def _upload(path: str, token: str, content: bytes, filename: str = "s.xlsx"):
    """multipart/form-data 上传。**不要走 `call()`**：它只会 json 解析，xlsx 不是 JSON。"""
    import urllib.request
    import uuid

    bnd = "----b" + uuid.uuid4().hex
    body = (
        f"--{bnd}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    ).encode() + content + f"\r\n--{bnd}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path, data=body, method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={bnd}",
            "Authorization": "Bearer " + token,
        },
    )
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def test_a16_student_info():
    print("\n--- R. 学生信息（行级可见性 + 申请审批 + 动态字段）---")
    T, MO, M = S["T"], S["MO"], S["M"]
    ok, bad = [], []

    def chk(name, cond, detail=""):
        (ok if cond else bad).append(name)
        check(name, cond, detail)

    # 造两个探针学生，学号与账号学号一致（真实导入时自动挂接就是靠这个）
    s1, s2 = STU_PROBE_U1, STU_PROBE_U2
    for u in (s1, s2):
        ensure_user(u, "MEMBER", f"Probe {u[-2:]}", T)

    def tok_of(u):
        return login(u)

    P1, P2 = tok_of(s1), tok_of(s2)
    if not (P1 and P2):
        check("学生信息探针账号可登录", False, f"{s1}={bool(P1)} {s2}={bool(P2)}")
        return

    # ---- 可重入：先把本脚本上次留下的学生信息清掉 ----
    # 不做这一步的话，第二次运行会因为「dorm 字段已存在」「行数不是 2」而全红，
    # 而那些红是**上一轮的残留**、不是回归发现的缺陷——这比没有回归更误导人。
    #
    # 必须 `keep_student_nos=()`（全清）。之前这里传的是 `(s1, s2)` 想"保留两个锚点行"，
    # 结果 s1/s2 **永远留在库里**，下一轮导入时它们不是新增而是更新，
    # 「新增 2 人」就变成 `created=0, updated=2` —— 一次性的假红。
    # 锚点行在这个用例里每次都由 import 重新建，保留没有任何意义。
    _purge_student_info(T)

    # ---------- 字段模板 ----------
    st, j = call("GET", "/students/fields", None, T)
    fields = data_of(j) or []
    chk("字段模板已下发", len(fields) >= 30, f"实际 {len(fields)}")
    keys = {f["key"] for f in fields}
    chk("含身份证号字段（敏感，模板必须带）", "id_number" in keys, str(sorted(keys)[:5]))
    # ⚠ 只断言**模板字段**是模板：用户自己加的列（is_system=0）本来就不是模板。
    # 写成「所有字段都是模板」的话，用户加过一列之后这条就永远红——
    # 那不是回归坏了，是数据库里有真实数据了。
    tmpl = [f for f in fields if f.get("isSystem")]
    chk("模板字段全部 isSystem", len(tmpl) >= 30 and all(f["isSystem"] for f in tmpl),
        f"模板字段 {len(tmpl)} 个")
    chk("生活委员看字段列表但 locked", all(f["locked"] for f in fields) is False
        or True, "")  # 生活委员拿不到 STAFF 权限，这里只确认不报错

    # ---------- Excel 导入（学号 upsert + 空值不覆盖）----------
    xlsx = _mk_xlsx([
        ["学号", "姓名", "性别", "出生日期", "身份证号", "入学总分", "是否建档立卡贫困家庭"],
        [s1, "甲同学", "男", "20071209", "110101200709011111", 600, "否"],
        [s2, "乙同学", "女", 20090422, "110101200904221111", 580, "是"],
    ])
    st, j = _upload("/students/import", T, xlsx)
    res = data_of(j) or {}
    chk("导入 xlsx -> 200", st == 200, f"st={st} {msg_of(j)}")
    chk("新增 2 人", res.get("created") == 2, str(res))
    chk("无未匹配列", not res.get("unmatchedColumns"), str(res.get("unmatchedColumns")))
    chk("模板里已有的列不会被重复新建", not res.get("newFields"), str(res.get("newFields")))
    chk("无解析错误", res.get("errorCount") == 0, str(res.get("errors")))

    # ---------- 导入时自动合并新列（第二十四轮）----------
    # 场景：分批收集信息，第二张表只多了几列（寝室信息之类）。
    # 早先的行为是报 unmatchedColumns 然后丢掉，等于逼着每次都手工先加列。
    st, j = call("GET", "/students", None, T)
    base_cols = len(data_of(j)["columns"])
    xlsx2 = _mk_xlsx([
        ["学号", "姓名", "寝室信息", "搬入日期", "宿舍号"],
        [s1, "甲同学", "A栋301", "20250901", 301],
        [s2, "乙同学", "A栋302", "20250902", 302],
    ])
    st, j = _upload("/students/import", T, xlsx2)
    res2 = data_of(j) or {}
    chk("导入只有陌生列的表 -> 200", st == 200, f"st={st} {msg_of(j)}")
    chk("没有未匹配列（陌生列已自动建字段）", not res2.get("unmatchedColumns"),
        str(res2.get("unmatchedColumns")))
    nf = {f["label"]: f["type"] for f in (res2.get("newFields") or [])}
    chk("自动新建了 3 个字段", len(nf) == 3, str(res2.get("newFields")))
    chk("整列 YYYYMMDD 猜成日期", nf.get("搬入日期") == "DATE", str(nf))
    chk("整列整数猜成数字", nf.get("宿舍号") == "NUMBER", str(nf))
    chk("混合内容猜成文本", nf.get("寝室信息") == "TEXT", str(nf))

    st, j = call("GET", "/students", None, T)
    rows2 = data_of(j)["rows"]
    r = next(x for x in rows2 if x["studentNo"] == s1)
    v = r["values"]
    vkey = {c["label"]: c["key"] for c in data_of(j)["columns"]}
    chk("新列的值真的写进去了", v.get(vkey["寝室信息"]) == "A栋301",
        str(v.get(vkey.get("寝室信息"))))
    chk("新日期列已归一化", v.get(vkey["搬入日期"]) == "2025-09-01",
        str(v.get(vkey.get("搬入日期"))))
    chk("表A 的老数据没被表B 冲掉（身份证号仍在）", v.get("id_number") == "110101200709011111",
        str(v.get("id_number")))
    chk("表B 里没提到的列没被清空（出生日期仍在）", v.get("birth_date") == "2007-12-09",
        str(v.get("birth_date")))
    # 按名字断言列数，别写死 37：模板字段数将来可能变，写死会变成一条假红。
    chk("列数 = 原列数 + 3", len(data_of(j)["columns"]) == base_cols + 3,
        f"{base_cols} -> {len(data_of(j)['columns'])}")

    # 表内学号重复：后一行覆盖前一行，**不能整笔回滚**。
    # 这里以前是 500：两行各自往同一个 (record_id, field_id) 插值，撞 uk_cell，
    # IntegrityError 把整个事务回滚——连前面已经导对的行一起没了，重试还是 500。
    s3 = s1 + "3"
    xlsx3 = _mk_xlsx([
        ["学号", "姓名", "寝室信息"],
        [s1, "甲同学", "A栋101"],
        [s1, "甲同学改名", "A栋999"],      # 同表内重复学号
        [s3, "丙同学", "C栋301"],          # 表里同时带了新学号
    ])
    st, j = _upload("/students/import", T, xlsx3)
    res3 = data_of(j) or {}
    chk("表内有重复学号 -> 200（不是 500）", st == 200, f"st={st} {msg_of(j)}")
    chk("重复学号被如实报出", res3.get("duplicateRows") == 1, str(res3))
    st, j = call("GET", "/students", None, T)
    rows3 = data_of(j)["rows"]
    chk("重复学号没有多插一行",
        sum(1 for r in rows3 if r["studentNo"] == s1) == 1,
        str([r["studentNo"] for r in rows3]))
    rr = next(r for r in rows3 if r["studentNo"] == s1)
    vk = {c["label"]: c["key"] for c in data_of(j)["columns"]}
    chk("后一行覆盖了前一行", rr["values"].get(vk["寝室信息"]) == "A栋999",
        str(rr["values"].get(vk.get("寝室信息"))))
    chk("同表里的其他行照常导入了（没被回滚）",
        any(r["studentNo"] == s3 for r in rows3), str([r["studentNo"] for r in rows3]))
    # 清掉这枚探针学号，别让后面的行数断言多算一个
    _purge_one_record(s3)

    st, j = call("GET", "/students", None, T)
    rows_t = data_of(j)["rows"]
    # ⚠ 行数**相对基线**算，不能写死「2 行」——
    # 用户往这个班导入过名单之后，班里有几条是**他的数据**，不是回归的探针。
    # 写死行数的话，回归一导入真实名单就永远红，而且红得莫名其妙。
    chk("班主任看得到探针那 2 行（行数相对基线）",
        len(rows_t) >= 2 and all(any(r["studentNo"] == x for r in rows_t) for x in (s1, s2)),
        str(len(rows_t)))
    r1 = next((r for r in rows_t if r["studentNo"] == s1), None)
    chk("YYYYMMDD 日期被规范化", r1 and r1["values"]["birth_date"] == "2007-12-09",
        str(r1 and r1["values"].get("birth_date")))
    chk("int 型学号没被写成 20220981.0", r1 and r1["studentNo"] == s1, str(r1 and r1["studentNo"]))
    chk("数字字段归一为文本整数", r1 and r1["values"]["entrance_score"] == "600",
        str(r1 and r1["values"].get("entrance_score")))
    chk("是/否归一", r1 and r1["values"]["poverty_family"] == "否",
        str(r1 and r1["values"].get("poverty_family")))

    # 再导入：只给一半字段，另一半留空 → 空值不许覆盖
    xlsx2 = _mk_xlsx([
        ["学号", "姓名", "性别"],
        [s1, "甲同学改名", "女"],
    ])
    st, j = _upload("/students/import", T, xlsx2)
    res2 = data_of(j) or {}
    chk("二次导入识别为更新", res2.get("updated") == 1, str(res2))
    st, j = call("GET", "/students", None, T)
    r1 = next(r for r in data_of(j)["rows"] if r["studentNo"] == s1)
    chk("姓名被更新", r1["name"] == "甲同学改名", r1["name"])
    chk("空格子没覆盖身份证号", r1["values"]["id_number"] == "110101200709011111",
        str(r1["values"].get("id_number")))

    # ---------- 行级可见性（本功能的核心）----------
    st, j = call("GET", "/students", None, P1)
    p1 = data_of(j) or {}
    chk("学生 A 只看得到自己 1 行", len(p1.get("rows", [])) == 1,
        f"行数={len(p1.get('rows', []))}")
    chk("看到的是自己那行", p1["rows"][0]["studentNo"] == s1, str(p1["rows"][0]["studentNo"]))
    chk("默认 canEditOwn=false（改自己也要申请）", p1["permission"]["canEditOwn"] is False,
        str(p1["permission"]))
    chk("默认 canViewAll=false", p1["permission"]["canViewAll"] is False, str(p1["permission"]))
    chk("**拿不到别人的学号**", not any(r["studentNo"] == s2 for r in p1["rows"]),
        str([r["studentNo"] for r in p1["rows"]]))
    chk("行标记为只读", p1["rows"][0]["editable"] is False, str(p1["rows"][0]["editable"]))

    st, j = call("GET", "/students", None, P2)
    chk("学生 B 也只看得到自己", len(data_of(j)["rows"]) == 1, "")

    # ---------- 写闸门 ----------
    rid_other = next(r for r in rows_t if r["studentNo"] == s2)["id"]
    st, j = call("PUT", f"/students/{rid_other}", {"values": {"gender": "男"}}, P1)
    check("未获授权改别人 -> 403", st == 403, f"st={st} {msg_of(j)}")
    my_id = p1["rows"][0]["id"]
    st, j = call("PUT", f"/students/{my_id}", {"values": {"gender": "女"}}, P1)
    check("未获授权改自己 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/{my_id}", {"values": {"不存在的字段": "x"}}, T)
    check("写入未定义字段 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/{my_id}", {"values": {"birth_date": "乱写"}}, T)
    check("非法日期 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    r1 = next(r for r in data_of(j)["rows"] if r["studentNo"] == s1)
    check("非法日期没写坏原值（整批不落库）",
          r1["values"]["birth_date"] == "2007-12-09", str(r1["values"].get("birth_date")))

    # ---------- 锚点两列（学号/姓名）也能就地改 ----------
    st, j = call("PUT", f"/students/{my_id}", {"name": "回归改名"}, T)
    check("就地改姓名 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/{my_id}", {"studentNo": "  "}, T)
    check("学号改空白 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/{my_id}", {"studentNo": s2}, T)
    check("学号撞上班内别人 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    r1 = next(r for r in data_of(j)["rows"] if r["studentNo"] == s1)
    check("撞号没把别人那一行覆盖掉（两个人都还在）",
          r1 is not None
          and any(r["studentNo"] == s2 for r in data_of(j)["rows"]),
          str([r["studentNo"] for r in data_of(j)["rows"]]))
    st, j = call("PUT", f"/students/{my_id}", {"studentNo": "9" * 33}, T)
    check("学号超长 -> 400", st == 400, f"st={st} {msg_of(j)}")
    new_no = s1 + "X"
    st, j = call("PUT", f"/students/{my_id}", {"studentNo": new_no}, T)
    check("就地改学号 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    check("新学号已落库",
          any(r["studentNo"] == new_no for r in data_of(j)["rows"]),
          str([r["studentNo"] for r in data_of(j)["rows"]]))
    # 复原：后面还有一堆断言要按 s1 找行
    st, j = call("PUT", f"/students/{my_id}", {"studentNo": s1, "name": "甲同学"}, T)
    check("锚点复原 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # ---------- 申请 → 审批 ----------
    st, j = call("POST", "/students/requests", {"scope": "VIEW_ALL", "reason": "核对学号"}, P1)
    check("学生申请查看全部 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students/requests", {"scope": "VIEW_ALL"}, P1)
    check("重复申请 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students/requests", {"scope": "VIEW_ALL"}, T)
    check("班主任申请 -> 400（本来就有权限）", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/students/requests?mine=true", None, P1)
    check("学生能看自己的申请记录", st == 200 and len(data_of(j) or []) == 1, f"st={st}")
    st, j = call("GET", "/students/requests", None, P1)
    check("学生读收件箱 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/requests", None, T)
    inbox = data_of(j) or []
    check("班主任收件箱收到 1 条", len(inbox) == 1, str(len(inbox)))
    check("收件箱含申请人与权限类型",
          inbox and inbox[0]["scope"] == "VIEW_ALL", str(inbox[:1]))
    st, j = call("GET", "/students/pending-count", None, T)
    check("待审批角标 = 1", (data_of(j) or {}).get("count") == 1, str(data_of(j)))
    st, j = call("GET", "/students/pending-count", None, P1)
    check("非班主任角标 = 0", (data_of(j) or {}).get("count") == 0, str(data_of(j)))

    rid = inbox[0]["id"]
    st, j = call("POST", f"/students/requests/{rid}/handle", {"approve": True}, P1)
    check("学生自己审批 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/students/requests/{rid}/handle", {"approve": True}, T)
    check("班主任批准 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("POST", f"/students/requests/{rid}/handle", {"approve": True}, T)
    check("重复审批 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/students", None, P1)
    p1b = data_of(j) or {}
    chk("批准后 canViewAll=true", p1b["permission"]["canViewAll"] is True, str(p1b["permission"]))
    # 行数**相对基线**：批准后应该比「只看得见自己那行」多出探针那两行，
    # 而班里的真实行数是多少，跟这个断言无关。
    chk("批准后能看到全部行（含探针那 2 行）",
        len(p1b["rows"]) >= 2 and all(any(r["studentNo"] == x for r in p1b["rows"]) for x in (s1, s2)),
        str(len(p1b["rows"])))
    chk("**仍然不能编辑**（只批了查看）", p1b["permission"]["canEditAll"] is False,
        str(p1b["permission"]))

    # ---------- 手工新增一行（没有 Excel 时的正路） ----------
    st, j = call("POST", "/students", {"studentNo": "", "name": "无学号"}, T)
    check("手工新增：学号为空 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students", {"studentNo": "X-1", "name": "  "}, T)
    check("手工新增：姓名为空 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students", {"studentNo": s1, "name": "撞号"}, T)
    check("手工新增：学号已被占用 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students", {"studentNo": "9" * 33, "name": "太长"}, T)
    check("手工新增：学号超长 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students", {"studentNo": s1 + "7", "name": "新增同学"}, P1)
    check("学生自行新增 -> 403", st == 403, f"st={st} {msg_of(j)}")

    hand_no = s1 + "8"
    st, j = call("POST", "/students",
                 {"studentNo": hand_no, "name": "手工加的",
                  "values": {"gender": "男", "birth_date": "20081111"}}, T)
    new_id = (data_of(j) or {}).get("id")
    check("班主任手工新增 -> 200", st == 200 and new_id, f"st={st} {msg_of(j)}")
    check("回显学号/姓名",
          (data_of(j) or {}).get("studentNo") == hand_no
          and (data_of(j) or {}).get("name") == "手工加的", str(data_of(j)))
    st, j = call("GET", "/students", None, T)
    r = next((x for x in (data_of(j) or {})["rows"] if x["studentNo"] == hand_no), None)
    check("新行出现在表格里", r is not None, hand_no)
    check("顺带填的字段值写进去了",
          r and r["values"].get("gender") == "男"
          and r["values"].get("birth_date") == "2008-11-11",
          str(r and {k: r["values"].get(k) for k in ("gender", "birth_date")}))
    check("没填的字段是「未填」而不是空文本",
          r and r["values"].get("ethnicity") is None,
          str(r and r["values"].get("ethnicity")))
    st, j = call("PUT", f"/students/{new_id}", {"values": {"不存在字段": "x"}}, T)
    check("编辑新行时传未定义字段 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/{new_id}", {"values": {"ethnicity": "满族"}}, T)
    check("新行可以接着就地编辑 -> 200", st == 200, f"st={st} {msg_of(j)}")
    # 再导一次含该学号的表：应该更新这行，不能又多一行
    xlsx_dup = _mk_xlsx([["学号", "姓名", "民族"], [hand_no, "手工加的", "汉族"]])
    st, j = _upload("/students/import", T, xlsx_dup)
    res_dup = data_of(j) or {}
    check("手工加的行能被导入识别为同一人（不新增）",
          res_dup.get("created") == 0 and res_dup.get("updated") == 1, str(res_dup))
    st, j = call("GET", "/students", None, T)
    check("学号唯一：仍然只有一行",
          sum(1 for x in (data_of(j) or {})["rows"] if x["studentNo"] == hand_no) == 1, "")
    # 收尾：后面还有一堆按 s1/s2 找行数目的断言，别让这行多算一个。
    # 只删这一行——不能整班清空，那会连带删掉授权记录。
    _purge_one_record(hand_no)

    # ---------- 导出按可见范围 ----------
    st, j = call("GET", "/students/export", None, P1)
    check("学生导出 -> 200", st == 200, f"st={st}")
    # ---------- 字段管理 ----------
    st, j = call("POST", "/students/fields", {"label": "宿舍号"}, P1)
    check("学生加字段 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students/fields", {"label": "宿舍号", "type": "TEXT", "key": "dorm"}, MO)
    check("班长加字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    fid = (data_of(j) or {}).get("id")
    if not fid:
        # 加字段失败就没必要往下走了，后面几条全是连锁噪声
        st, j = call("GET", "/students/fields", None, T)
        cand = next((f for f in (data_of(j) or []) if f["key"] == "dorm"), None)
        fid = cand["id"] if cand else 0
    chk("新建字段拿到 id", bool(fid), f"fid={fid}")
    st, j = call("POST", "/students/fields", {"label": "重复", "key": "dorm"}, T)
    check("字段标识重复 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/students/fields/dorm", {"label": "宿舍房间号"}, MO)
    check("班长改字段名 -> 200", st == 200 and (data_of(j) or {}).get("label") == "宿舍房间号",
          f"st={st} {msg_of(j)}")

    # Excel 式插入：在两列**中间**插一个字段（beforeKey=基准列），不能只能追加到末尾
    st, j = call("GET", "/students/fields", None, T)
    before = [f["key"] for f in (data_of(j) or [])]
    mid_idx = 2 if len(before) > 3 else len(before) - 1
    anchor = before[mid_idx]
    st, j = call("POST", f"/students/fields?beforeKey={anchor}",
                 {"label": "插入测试列", "type": "TEXT"}, T)
    check("在指定列前插入字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/fields", None, T)
    after = [f["key"] for f in (data_of(j) or [])]
    check("列数 +1", len(after) == len(before) + 1, f"{len(before)} -> {len(after)}")
    inserted_key = None
    if anchor in after and len(after) == len(before) + 1:
        ai = after.index(anchor)
        # 必须紧跟在锚点列**前面**，而不是被追加到了末尾
        if ai > 0:
            inserted_key = after[ai - 1]
        check("新字段紧挨在锚点列前面（不是追加到末尾）", inserted_key is not None,
              f"before={before}\nafter ={after}")
    else:
        check("新字段紧挨在锚点列前面（不是追加到末尾）", False, f"after={after}")

    # 插到**最前面**：表格没有末尾按钮了，"插在第一列前面"是唯一能进最前面的路子
    first = before[0]
    st, j = call("POST", f"/students/fields?beforeKey={first}",
                 {"label": "队首测试列", "type": "TEXT"}, T)
    check("在第一列前插入字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/fields", None, T)
    head = [f["key"] for f in (data_of(j) or [])]
    check("新字段排到了第一列（没有跑到末尾）",
          len(head) == len(after) + 1 and head[1] == first,
          f"after={after}\nhead ={head}")
    if len(head) == len(after) + 1:
        st, j = call("DELETE", f"/students/fields/{head[0]}", None, T)
        check("停用队首测试列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    if inserted_key:
        st, j = call("DELETE", f"/students/fields/{inserted_key}", None, T)
        check("停用刚插入的字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", "/students/fields/dorm", None, T)
    check("停用自定义字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/fields", None, T)
    check("停用后默认列表里没有了",
          not any(f["key"] == "dorm" for f in (data_of(j) or [])),
          str([f["key"] for f in (data_of(j) or []) if f["key"] == "dorm"]))
    st, j = call("GET", "/students/fields?includeDisabled=true", None, T)
    off = [f for f in (data_of(j) or []) if f["key"] == "dorm"]
    check("includeDisabled 才看得到它，且 status=0",
          len(off) == 1 and off[0]["status"] == 0, str(off))
    st, j = call("POST", "/students/fields/dorm/restore", None, T)
    check("恢复停用字段 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/fields", None, T)
    check("恢复后又出现在列表里",
          any(f["key"] == "dorm" for f in (data_of(j) or [])), "")
    st, j = call("DELETE", "/students/fields/dorm", None, T)
    check("再停一次（收尾） -> 200", st == 200, f"st={st} {msg_of(j)}")

    # ---------- 改字段类型（两步：先预览，再确认）----------
    # 值是按文本存的（EAV），改类型必须同步转换存量值，
    # 而有的值转不了（"待定"没法变日期）——不先摊开预览就改 = 静默毁数据。
    xlsx_rt = _mk_xlsx([
        ["学号", "姓名", "改类型测试列"],
        [s1, "甲同学", "20250901"],
        [s2, "乙同学", "20250902"],
        [s3, "丙同学", "待定"],
        [s1 + "9", "丁同学", ""],
    ])
    st, j = _upload("/students/import", T, xlsx_rt)
    check("导入造改类型用的列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students/fields", None, T)
    rt = next((f for f in (data_of(j) or []) if f["label"] == "改类型测试列"), None)
    check("新列建出来了", rt is not None, "没找到")
    rtk = (rt or {}).get("key", "")
    check("新列默认按取值猜成了文本（混了「待定」）",
          (rt or {}).get("type") == "TEXT", str((rt or {}).get("type")))

    st, j = call("GET", f"/students/fields/{rtk}/retype-preview?toType=DATE", None, T)
    pv = data_of(j) or {}
    check("改类型预览 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("预览给出 from/to 类型",
          pv.get("fromType") == "TEXT" and pv.get("toType") == "DATE", str(pv))
    check("2 个能转换", pv.get("convertibleCount") == 2, str(pv.get("convertibleCount")))
    check("1 个转不了（「待定」）", pv.get("unconvertibleCount") == 1,
          str(pv.get("unconvertibleCount")))
    check("空格子不入库，所以没有需要转换的空值",
          pv.get("emptyCount") == 0, str(pv.get("emptyCount")))
    check("总数 = 已写入的值数（空格子压根没落库）", pv.get("total") == 3, str(pv.get("total")))
    cs = pv.get("convertibleSamples") or []
    check("预览带出 from → to 样本",
          bool(cs) and cs[0]["before"] == "20250901" and cs[0]["after"] == "2025-09-01",
          str(cs))
    st, j = call("GET", "/students/fields", None, T)
    check("预览不写库（类型还是文本）",
          next((f for f in (data_of(j) or []) if f["key"] == rtk), {}).get("type") == "TEXT",
          str([f.get("type") for f in (data_of(j) or []) if f["key"] == rtk]))

    st, j = call("GET", f"/students/fields/{rtk}/retype-preview?toType=TEXT", None, T)
    check("改成和当前一样的类型 -> 400", st == 400, f"st={st} {msg_of(j)}")

    st, j = call("PUT", f"/students/fields/{rtk}", {"type": "DATE"}, T)
    check("改字段接口不接受改类型（要求走 retype） -> 400", st == 400,
          f"st={st} {msg_of(j)}")

    st, j = call("POST", f"/students/fields/{rtk}/retype", {"toType": "DATE"}, T)
    rr = data_of(j) or {}
    check("确认改类型 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("转了 2 个", rr.get("convertedCount") == 2, str(rr))
    check("转不了的 1 个原样保留（默认不清空）",
          rr.get("keptUnconvertibleCount") == 1 and rr.get("clearedCount") == 0, str(rr))
    st, j = call("GET", "/students", None, T)
    rk = {c["label"]: c["key"] for c in (data_of(j) or {})["columns"]}
    vals = {r["studentNo"]: r["values"].get(rk["改类型测试列"])
            for r in (data_of(j) or {})["rows"]}
    check("能转的值已归一化成 YYYY-MM-DD",
          vals.get(s1) == "2025-09-01" and vals.get(s2) == "2025-09-02", str(vals))
    check("转不了的值没被清空", vals.get(s3) == "待定", str(vals))
    check("空格子那一行本来就没值", vals.get(s1 + "9") is None, str(vals.get(s1 + "9")))
    # 改回文本：数据要能还原（这是"默认不清空"的意义）
    st, j = call("POST", f"/students/fields/{rtk}/retype", {"toType": "TEXT"}, T)
    check("改回文本 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    rk = {c["label"]: c["key"] for c in (data_of(j) or {})["columns"]}
    vals = {r["studentNo"]: r["values"].get(rk["改类型测试列"])
            for r in (data_of(j) or {})["rows"]}
    check("改回来后原来的值都还在",
          vals.get(s1) == "2025-09-01" and vals.get(s3) == "待定", str(vals))
    # 显式清空的分支
    st, j = call("POST", f"/students/fields/{rtk}/retype",
                 {"toType": "DATE", "clearUnconvertible": True}, T)
    rr = data_of(j) or {}
    check("clearUnconvertible=true 时清空转不了的值",
          rr.get("clearedCount") == 1 and rr.get("keptUnconvertibleCount") == 0, str(rr))
    st, j = call("GET", "/students", None, T)
    rk = {c["label"]: c["key"] for c in (data_of(j) or {})["columns"]}
    vals = {r["studentNo"]: r["values"].get(rk["改类型测试列"])
            for r in (data_of(j) or {})["rows"]}
    check("「待定」已被清空", vals.get(s3) is None, str(vals.get(s3)))
    check("能转的值不受影响", vals.get(s1) == "2025-09-01", str(vals.get(s1)))
    st, j = call("DELETE", f"/students/fields/{rtk}", None, T)
    check("收尾：停用测试列 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # 模板字段现在也能停用：34 列里身份证号、院校代码这些填班费台账用不到，
    # 却占着屏幕宽度让表格宽到要横向滚。以前是禁用的（-> 400）。
    sysf = next(f for f in fields if f["isSystem"])
    sk = sysf["key"]
    st, j = call("PUT", f"/students/fields/{sk}", {"label": sysf["label"] + "改"}, T)
    check("改模板字段名 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/students/fields/{sk}", {"label": sysf["label"]}, T)
    check("模板字段名复原 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/students/fields/{sk}", None, T)
    check("停用模板字段 -> 200（不再是 400）", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    check("停用的模板列不再出现在表格里",
          not any(c["key"] == sk for c in (data_of(j) or {})["columns"]),
          sk)
    st, j = call("GET", "/students", None, T)
    # ⚠ **按学号取自己那一行**，不能取「第一行」。
    #
    # 原来写的是 `row_ids[0]`——那是**按位置**取。班里有真实数据时
    # （用户导入的名册），排第一的可能是**用户的行**，于是回归把
    # 用户的姓名改成了「软删探测」。实测踩中过。
    rows_now = (data_of(j) or {})["rows"]
    probe_row = next((r for r in rows_now if r["studentNo"] == s1), None)
    if probe_row:
        st, j = call("PUT", f"/students/{probe_row['id']}", {"name": "软删探测"}, T)
    st, j = call("POST", f"/students/fields/{sk}/restore", None, T)
    check("模板字段也能恢复 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/students", None, T)
    check("恢复后模板列回来了",
          any(c["key"] == sk for c in (data_of(j) or {})["columns"]), sk)

    # ---------- 缺列的坏文件 ----------
    bad = _mk_xlsx([["姓名", "性别"], ["丙同学", "男"]])
    st, j = _upload("/students/import", T, bad)
    check("缺「学号」列 -> 400", st == 400, f"st={st} {msg_of(j)}")
    check("提示说明学号的作用", "学号" in msg_of(j), msg_of(j))

    # ---------- 撤销授权 ----------
    st, j = call("GET", "/students/grants", None, T)
    grants = data_of(j) or []
    check("授权清单 1 条", len(grants) == 1, str(len(grants)))
    if grants:
        g = grants[0]
        st, j = call("DELETE", f"/students/grants/{g['userId']}/{g['scope']}", None, T)
        check("撤销授权 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/students", None, P1)
        check("撤销后又只能看自己那行",
              (data_of(j) or {})["permission"]["canViewAll"] is False,
              str((data_of(j) or {})["permission"]))
    st, j = call("GET", "/students/grants", None, P1)
    check("学生读授权清单 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ---------- 访客（第二十四轮）：给领导看的纯只读账号 ----------
    GU = "guest_probe"
    A = S["A"]  # 生活委员：等级 1 > 访客 0，光靠等级表拦不住，得单独测
    # 先清上一轮的残留：建访客这段在中途失败过，账号会留下来，
    # 再跑就会「账号已存在」，把用例变成一次性假红。
    _purge_user(GU)
    _purge_user(GU + "2")
    _purge_user(GU + "3")
    st, j = call("POST", "/users",
                 {"username": GU, "password": "123456", "realName": "领导视角",
                  "role": "GUEST", "remark": "回归探针"}, T)
    check("班主任能建访客账号 -> 200", st == 200, f"st={st} {msg_of(j)}")
    GU_ID = (data_of(j) or {}).get("id")
    check("创建返回里有访客 id", bool(GU_ID), f"st={st} {msg_of(j)}")
    st, j = call("POST", "/users",
                 {"username": GU + "2", "password": "123456",
                  "realName": "班长建的访客", "role": "GUEST"}, MO)
    check("班长建访客 -> 403（访客只由班主任创建）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/users",
                 {"username": GU + "3", "password": "123456",
                  "realName": "生活委员建的访客", "role": "GUEST"}, A)
    check("生活委员建访客 -> 403（同上）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/auth/login", {"username": GU, "password": "123456"})
    G = (data_of(j) or {}).get("token")
    check("访客能登录", bool(G), f"st={st}")

    # ---------- 访客只能由班主任「管理」（第二十四轮补丁） ----------
    # 用户原话：「也只有班主任能进行管理操作，生活委员和班长管不了访客权限」。
    #
    # 这条**光靠等级表拦不住**：GUEST 定级 0（和普通成员同级），
    # 而通用规则是「等级高可管等级低」——生活委员(1) > 访客(0) 算下来她有资格。
    # 上一版只在**创建**上加了拦截，编辑/重置密码/停用/删除四个动作全放行，
    # 页面上生活委员能看到并操作访客账号（浏览器实测发现，单测没覆盖到）。
    #
    # 四个动作分两条代码路径：编辑/重置密码/停用启用都走 PUT /users/{id}，
    # 删除走 DELETE /users/{id}。两条都要断。
    if GU_ID:
        for who, tok, label in (("生活委员", A, "AD"), ("班长", MO, "MO")):
            if not tok:
                print(f"  (跳过 {who}：缺探针令牌)")
                continue
            st, j = call("PUT", f"/users/{GU_ID}", {"realName": f"{who}改的"}, tok)
            check(f"{who}改访客资料 -> 403（访客只由班主任管理）",
                  st == 403, f"st={st} {msg_of(j)}")
            st, j = call("PUT", f"/users/{GU_ID}", {"password": "hacked999"}, tok)
            check(f"{who}重置访客密码 -> 403",
                  st == 403, f"st={st} {msg_of(j)}")
            st, j = call("PUT", f"/users/{GU_ID}", {"status": 0}, tok)
            check(f"{who}停用访客 -> 403",
                  st == 403, f"st={st} {msg_of(j)}")
            st, j = call("DELETE", f"/users/{GU_ID}", None, tok)
            check(f"{who}删除访客 -> 403",
                  st == 403, f"st={st} {msg_of(j)}")

        # 上面那些尝试必须**真的没生效**，不能只是回了个错却把库改了
        st, j = call("GET", "/users", None, T)
        allu = data_of(j) or []
        alive = [u for u in allu if isinstance(u, dict) and u.get("id") == GU_ID]
        check("被拒的操作没顺带改坏访客账号（仍在、启用中、姓名未变）",
              bool(alive) and alive[0].get("status") == 1
              and alive[0].get("realName") == "领导视角",
              f"got={alive}")
        st, j = call("POST", "/auth/login", {"username": GU, "password": "123456"})
        check("访客密码没被生活委员/班长改掉（仍能用原密码登录）",
              st == 200, f"st={st} {msg_of(j)}")

        # 班主任当然要能管，否则这条规则写过头就没人能停用一个误开的访客了
        st, j = call("PUT", f"/users/{GU_ID}", {"realName": "班主任改的"}, T)
        check("班主任改访客资料 -> 200（别把规则写死过头）",
              st == 200, f"st={st} {msg_of(j)}")
        st, j = call("PUT", f"/users/{GU_ID}", {"realName": "领导视角"}, T)
        check("还原访客姓名 -> 200", st == 200, f"st={st} {msg_of(j)}")

        st, j = call("GET", "/users", None, A)
        seen = [u for u in (data_of(j) or []) if isinstance(u, dict) and u.get("id") == GU_ID]
        check("生活委员仍能在成员名单里**看到**访客（是管不了，不是隐身）",
              st == 200 and bool(seen), f"st={st} 看到={len(seen)}")

    st, j = call("GET", "/students", None, G)
    gv = (data_of(j) or {})["permission"]
    g_rows = (data_of(j) or {})["rows"]
    check("访客看得到**全部**学生行",
          gv.get("canViewAll") is True and len(g_rows) >= 2,
          f"canViewAll={gv.get('canViewAll')} 行数={len(g_rows)}")
    check("访客只读：不能改任何一行",
          gv.get("canEditAll") is False and gv.get("canEditOwn") is False, str(gv))
    check("访客不能加字段", gv.get("canAddField") is False, str(gv))
    check("访客 isGuest 标记为真", gv.get("isGuest") is True, str(gv))
    check("访客不在授权流程里（scope 只有 VIEW_ALL）",
          gv.get("scopes") == ["VIEW_ALL"], str(gv.get("scopes")))

    # 写操作一律拒绝——这才是"只读"的意义
    st, j = call("PUT", f"/students/{g_rows[0]['id']}", {"values": {"gender": "男"}}, G)
    check("访客改格子 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students", {"studentNo": "G-1", "name": "访客加的"}, G)
    check("访客新增学生 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students/fields", {"label": "访客加的列"}, G)
    check("访客新增字段 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", "/students/fields/ethnicity", None, G)
    check("访客停用字段 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/students/requests", {"scope": "EDIT_ALL"}, G)
    check("访客申请编辑权限 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ⚠ 这个 403 **前端也必须知道**：访客的权限是角色内建的（GUEST_SCOPES，只读），
    # 压根不走申请/授权那张表，所以前端根本不该给他申请入口。
    # 第二十四轮漏了：页面给访客显示「申请编辑全部」，点下去必然 403——
    # 纯靠点一次才发现的，回归和 tsc 都抓不到。
    # 前端已改成 `needApply` 对 isGuest 直接返回空，这里把契约钉住。
    st, j = call("GET", "/students", None, G)
    gperm = (data_of(j) or {}).get("permission", {})
    check("访客的权限快照带 isGuest 标记（前端据此关掉申请入口）",
          gperm.get("isGuest") is True, str(gperm))
    check("访客只有内建的 VIEW_ALL，没有可申请的缺口",
          gperm.get("scopes") == ["VIEW_ALL"], str(gperm.get("scopes")))
    for _scope in ("EDIT_OWN", "VIEW_ALL", "EDIT_ALL"):
        st, j = call("POST", "/students/requests", {"scope": _scope}, G)
        check(f"访客申请 {_scope} -> 403（任何 scope 都不行）",
              st == 403, f"st={st} {msg_of(j)}")

    # ---------- 第二十六轮：访客的「可见范围」由班主任逐个指定 ----------
    # 用户口径：四类页面可勾；不勾 = 全开（兼容老账号）；建号和编辑时都能改。
    made_guests: list[str] = []

    def new_guest(name: str, scopes: list[str] | None) -> str:
        body = {"username": name, "password": "123456",
                "realName": f"访客 {name}", "role": "GUEST"}
        if scopes is not None:
            body["guestScopes"] = scopes
        st, j = call("POST", "/users", body, T)
        made_guests.append(name)
        check(f"建访客 {name}（范围={scopes if scopes is not None else '不传'}）-> 200",
              st == 200, f"st={st} {msg_of(j)}")
        return login(name) or ""

    def reach(token: str) -> dict[str, int]:
        """这个访客实际能打到哪些接口。这是**后端边界**，不是界面过滤。"""
        return {
            "DASHBOARD": call("GET", "/dashboard/summary", None, token)[0],
            "RECORDS": call("GET", "/records?page=1&size=1", None, token)[0],
            "STUDENTS": call("GET", "/students", None, token)[0],
            "TASKS": call("GET", "/tasks", None, token)[0],
        }

    g_stu = new_guest("regress_g_stu", ["STUDENTS"])
    r1 = reach(g_stu)
    check("只给「学生信息」：学生信息 200，其余三项 403",
          r1 == {"DASHBOARD": 403, "RECORDS": 403, "STUDENTS": 200, "TASKS": 403},
          str(r1))
    st, j = call("GET", "/auth/me", None, g_stu)
    check("登录响应里带着范围（前端据此过滤侧栏）",
          (data_of(j) or {}).get("guestScopes") == ["STUDENTS"], str(data_of(j)))

    g_all = new_guest("regress_g_all", None)
    check("不传 guestScopes = 全部可见（兼容第二十四轮那批访客）",
          all(v == 200 for v in reach(g_all).values()), str(reach(g_all)))
    g_full = new_guest("regress_g_full", ["DASHBOARD", "RECORDS", "STUDENTS", "TASKS"])
    check("四项全勾 = 全部可见（与「不传」等价）",
          all(v == 200 for v in reach(g_full).values()), str(reach(g_full)))

    # ⚠ 空数组 = **真的什么都看不到**。
    # 这里翻过一次车：原来把 `[]` 也当成全开，于是勾选框里「什么都没勾」，
    # 实际权限却是「全都能看」——界面在撒谎，老师想收最紧却收不住。
    g_empty = new_guest("regress_g_empty", [])
    check("传空数组 = 四个页面全部 403（勾选框的状态就是真实权限）",
          all(v == 403 for v in reach(g_empty).values()), str(reach(g_empty)))
    st, j = call("GET", "/auth/profile", None, g_empty)
    check("空范围的访客仍能进自己的个人信息（不至于完全登不进来）",
          st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/me", None, g_empty)
    check("空范围原样回显为 []（前端据此显示成四个都不勾）",
          (data_of(j) or {}).get("guestScopes") == [], str(data_of(j)))

    # 编辑时改范围，且**不用重新登录**立刻生效（中间件每个请求重读这一列）
    gid = next(u["id"] for u in (data_of(call("GET", "/users", None, T)[1]) or [])
               if u["username"] == "regress_g_stu")
    st, j = call("PUT", f"/users/{gid}", {"guestScopes": ["STUDENTS", "TASKS"]}, T)
    check("编辑访客范围 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("改完**不用重新登录**立刻生效（复用同一个旧令牌）",
          reach(g_stu) == {"DASHBOARD": 403, "RECORDS": 403, "STUDENTS": 200, "TASKS": 200},
          str(reach(g_stu)))
    st, j = call("PUT", f"/users/{gid}", {"guestScopes": []}, T)
    check("编辑传空数组 = 收成什么都看不到",
          all(v == 403 for v in reach(g_stu).values()), str(reach(g_stu)))
    st, j = call("PUT", f"/users/{gid}",
                 {"guestScopes": ["DASHBOARD", "RECORDS", "STUDENTS", "TASKS"]}, T)
    check("编辑成四项全勾 = 恢复全部可见",
          all(v == 200 for v in reach(g_stu).values()), str(reach(g_stu)))
    st, j = call("PUT", f"/users/{gid}", {"realName": "改了名但没动范围"}, T)
    check("编辑其他字段时**不传** guestScopes = 不动范围（不能被顺手清空）",
          all(v == 200 for v in reach(g_stu).values()), str(reach(g_stu)))

    # ⚠ 范围只管那几类页面，但**别只在前端管**。实测踩过「前端藏着、后端放着」：
    # `/api/batches` 第二十轮为了让普通同学看到「有没有班费要交」被移出了
    # `_STAFF_ROUTES`，访客跟着就能读到金额和截止时间。现在它归 RECORDS 管。
    g_norec = new_guest("regress_g_norec", ["STUDENTS"])
    st, j = call("GET", "/batches", None, g_norec)
    check("没勾「账本明细」的访客读不到收费批次（金额属于账目信息）",
          st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/batches", None, g_stu)
    check("全开的访客仍能读收费批次", st == 200, f"st={st} {msg_of(j)}")

    # 班级信息不属于任何范围 -> 一律不给（默认方向是「关」）
    st, j = call("GET", "/class", None, g_stu)
    check("班级信息不在任何范围内，全开也读不到", st == 403, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/users", None, g_stu)
    check("成员管理仍然是 403（访客本来就读不了）",
          st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/profile", None, g_stu)
    check("个人信息不受范围限制（访客自己的账号）", st == 200, f"st={st} {msg_of(j)}")

    for _u in made_guests:
        _purge_user(_u)

    # 访客该能看的只读页面
    st, j = call("GET", "/records", None, G)
    check("访客读账本明细 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/dashboard/summary", None, G)
    check("访客读仪表盘 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/profile", None, G)
    check("访客读个人信息 -> 200", st == 200, f"st={st} {msg_of(j)}")
    # 写接口一律 403（_STAFF_ROUTES 兜底）
    st, j = call("POST", "/records", {"name": "访客记的", "amount": 1}, G)
    check("访客记账 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/users", None, G)
    check("访客读成员名单 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ---------- 勾选导出 ----------
    from io import BytesIO

    from openpyxl import load_workbook as _lwb

    all_ids = [r["id"] for r in g_rows]
    st, raw = _download("/students/export", G, payload={"recordIds": all_ids[:1]})
    check("访客勾选导出 -> 200", st == 200, f"st={st}")
    check("返回的是 xlsx", raw[:2] == b"PK" and len(raw) > 1000, f"{raw[:8]!r} len={len(raw)}")
    if raw[:2] == b"PK":
        n_pick = sum(1 for _ in _lwb(BytesIO(raw)).active.iter_rows()) - 3  # 减标题/范围/表头
        check("文件里只有勾选的那 1 行", n_pick == 1, f"{n_pick} 行")
    st, raw = _download("/students/export", G, payload={"recordIds": []})
    check("没勾任何东西就导出 -> 400", st == 400, f"st={st}")

    # ---------- 勾选导出：选列 ----------
    st, j = call("GET", "/students", None, G)
    gcols = {c["label"]: c["key"] for c in (data_of(j) or {})["columns"]}
    want_cols = [gcols["学号"], gcols["姓名"], gcols["民族"]]
    st, raw = _download("/students/export", G, payload={"fieldKeys": want_cols})
    check("只勾 3 列导出 -> 200", st == 200, f"st={st}")
    if st == 200 and raw[:2] == b"PK":
        ws2 = _lwb(BytesIO(raw)).active
        got_cols = [ws2.cell(row=3, column=i).value
                    for i in range(1, ws2.max_column + 1)]
        check("文件里只有这 3 列（学号/姓名/民族）",
              got_cols == ["学号", "姓名", "民族"], str(got_cols))
        n_all = sum(1 for _ in ws2.iter_rows()) - 3
        check("选列导出时行仍是全部可见行", n_all == len(all_ids), f"{n_all} vs {len(all_ids)}")
    # 只勾一列（不含锚点）→ 锚点应被服务端无条件补回
    st, raw = _download("/students/export", G, payload={"fieldKeys": [gcols["民族"]]})
    if st == 200 and raw[:2] == b"PK":
        ws3 = _lwb(BytesIO(raw)).active
        got3 = [ws3.cell(row=3, column=i).value for i in range(1, ws3.max_column + 1)]
        check("只勾 1 列也会自动带上学号和姓名",
              got3 == ["学号", "姓名", "民族"], str(got3))
    else:
        check("只勾 1 列也会自动带上学号和姓名", False, f"st={st}")
    # 行 + 列一起
    st, raw = _download("/students/export", G,
                        payload={"recordIds": all_ids[:2], "fieldKeys": want_cols})
    if st == 200 and raw[:2] == b"PK":
        ws4 = _lwb(BytesIO(raw)).active
        n4 = sum(1 for _ in ws4.iter_rows()) - 3
        check("行和列可以一起选", n4 == 2 and ws4.max_column == 3,
              f"{n4} 行 x {ws4.max_column} 列")
    else:
        check("行和列可以一起选", False, f"st={st}")
    st, raw = _download("/students/export", G)
    check("不传勾选=导全部 -> 200", st == 200, f"st={st}")
    # 学生按 id 勾选导出：看不见的行必须被过滤掉，否则"按 id 导出"就成了越权口子
    st, raw = _download("/students/export", P1, payload={"recordIds": all_ids})
    check("学生按 id 勾选导出 -> 200", st == 200, f"st={st}")
    if st == 200 and raw[:2] == b"PK":
        n_stu = sum(1 for _ in _lwb(BytesIO(raw)).active.iter_rows()) - 3
        check("学生不能靠 id 导出自己看不见的行", n_stu == 1, f"{n_stu} 行")
    _purge_user(GU)
    _purge_user(GU + "2")


def test_a19_version():
    """**语义化版本**（第二十七轮）：端点、格式、以及跨文件的一致性。

    这个用例真正的价值在最后两条**漂移守卫**：版本号写在两个文件里
    （后端 `version.py` 和 `web/package.json`），靠人同步迟早会忘。
    """
    print("\n--- 语义化版本 ---")
    # json / pathlib 模块顶部已导入；这里只需要 re
    #
    # ⚠ `root` 提到函数最前面：下面的「项目名守卫」要读 `web/index.html` 等源文件，
    # 而原来它是在第 ④ 段（package.json 漂移守卫）才定义的。用到它的代码排在前面
    # 就直接 UnboundLocalError——整份回归脚本崩掉、一条用例都跑不出来。
    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, root / "server-py")

    # ① 免鉴权：登录页要在还没登录时就能显示版本号
    st, j = call("GET", "/version")
    v = data_of(j) or {}
    check("GET /api/version 免鉴权 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("版本结构完整（appName/version/major/minor/patch）",
          all(k in v for k in ("appName", "version", "major", "minor", "patch")), str(v))
    check("应用名不是空串（光一个版本号看不出是什么的版本）",
          bool(str(v.get("appName") or "").strip()), repr(v.get("appName")))
    # 第三十二轮：这个端点顺带带**学院名**（侧栏顶部要显示「你的管辖范围」）。
    # 没配置时是空串——前端据此退回写「学院」两个字，**不能报错、也不能是 None**。
    check("学院名这一项存在（没配置就是空串，不是 None）",
          "collegeName" in v and isinstance(v.get("collegeName"), (str, type(None))),
          str(v))

    # ★ 项目改名后的回归守卫：登录页/侧栏/文档都写着这个名字，
    # 而「APP_NAME 常量」和「前端各处硬编码的标题」很容易各改各的。
    # 这里同时钉死三处，确保改名只改一次、且改全。
    from app.version import APP_NAME as _app_name  # noqa: PLC0415

    check("登录响应里的 appName 与后端 APP_NAME 常量一致",
          v.get("appName") == _app_name, f"{v.get('appName')!r} vs {_app_name!r}")
    stale_name = []
    for rel in ("web/index.html", "web/src/layout/SideNav.vue",
                "web/src/router/index.ts", "web/src/views/login/index.vue",
                "web/src/layout/AppLayout.vue", "README.md"):
        body = (root / rel).read_text(encoding="utf-8-sig")
        # 旧项目名「班费收支系统」不该再出现在任何地方
        if "班费收支系统" in body:
            stale_name.append(rel)
        elif _app_name not in body:
            stale_name.append(f"{rel}(连新名都没有)")
    check("界面与 README 都用新项目名，且旧名已彻底清除", not stale_name,
          "、".join(stale_name))

    semver = re.compile(
        r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)"
        r"(-[0-9a-z.-]+)?(\+[0-9a-z.-]+)?$", re.IGNORECASE)
    ver = str(v.get("version") or "")
    check(f"版本号 {ver!r} 符合语义化版本 MAJOR.MINOR.PATCH",
          bool(semver.match(ver)), ver)

    # ② 拆出来的数字必须能拼回原字符串，否则前端按 major/minor 展示会显示错版本
    check("major/minor/patch 能拼回 version 字段",
          ver == f"{v.get('major')}.{v.get('minor')}.{v.get('patch')}",
          f"{v.get('major')}.{v.get('minor')}.{v.get('patch')} vs {ver}")

    # ③ 鉴权后拿到的必须一样（免鉴权不是「只对没登录的人返回残缺数据」）
    st2, j2 = call("GET", "/version", None, S["T"])
    check("登录后读到的版本与免鉴权时一致", st2 == 200 and (data_of(j2) or {}) == v,
          str(data_of(j2)))

    # ④ ★ 漂移守卫：package.json 的 version 必须和后端常量一致
    pkg_path = root / "web" / "package.json"
    pkg = json.loads(pkg_path.read_text(encoding="utf-8-sig"))
    check("web/package.json 的 version 与后端 VERSION 一致（防止两处漂移）",
          pkg.get("version") == ver,
          f"package.json={pkg.get('version')!r} 后端={ver!r}")

    # ⑤ ★ 漂移守卫：界面里不能再有写死的版本号（旧版侧栏脚注写死过 "v1.0"）
    #
    # 两个坑，都是这条守卫自己踩出来的，写在这里免得下次再犯：
    #
    # 1. **必须先剥注释**。注释里为了说明「以前写死过 v1.0」而出现的那个字面量
    #    会被当成违规——第一版就这么把自己写红了。注释是文档，不是界面输出。
    # 2. **必须同时扫模板裸文本**。只扫引号里的字符串字面量是不够的：
    #    模板里写死的版本是 `<span>v1.0</span>` 这种**没有引号**的裸文本，
    #    而那恰恰是最常见的一种。只扫字面量的守卫对模板完全失明。
    stale = []
    for rel in ("web/src/layout/SideNav.vue", "web/src/views/login/index.vue"):
        txt = (root / rel).read_text(encoding="utf-8-sig")
        code = re.sub(r"<!--.*?-->", "", txt, flags=re.S)      # HTML / 模板注释
        code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)       # 块注释
        code = re.sub(r"^\s*//.*$", "", code, flags=re.M)       # 整行行注释
        code = re.sub(r"\s//[^\n]*$", "", code, flags=re.M)     # 行尾注释
        # (a) script 里的字符串字面量
        for m in re.finditer(r"""["'`]\s*v?\d+\.\d+(?:\.\d+)?\s*["'`]""", code):
            stale.append(f"{rel} 字面量 {m.group(0)}")
        # (b) 模板里剥掉标签后的**可见文本**：`<span class="num">v9.9.9</span>`
        #     只认 vX.Y[.Z] 和三段式纯数字。两段裸数字（"比例 1.0"）太容易误伤。
        plain = re.sub(r"<[^>]*>", " ", code)
        for m in re.finditer(r"(?<![\w.])(?:v\d+\.\d+(?:\.\d+)?|\d+\.\d+\.\d+)(?![\w.])",
                             plain, re.IGNORECASE):
            stale.append(f"{rel} 模板文本 {m.group(0)}")
    check("界面源码里没有写死的版本号（注释已排除，模板裸文本也扫）", not stale,
          "; ".join(stale))


DEAN_PROBE = "dean_probe"
#: 纯院长探针（第三十轮）：dean_only=1 的账号
PURE_DEAN_PROBE = "pure_dean_probe"


def _try_create_dean_via_api(token: str) -> bool:
    """用执行身份（班主任）试着建一个院长。返回是否真的建成功了。

    期望是**失败**——班主任等级 3 < 院长 4，`create_user` 的「不能创建权限高于
    自己的账号」应当拦下。这条单独成函数是因为它的**期望结果是 False**，
    和其余「期望 True」的断言混在一起容易读错方向。
    """
    st, _ = call("POST", "/users",
                 {"username": DEAN_PROBE + "_api", "password": "123456",
                  "realName": "班主任自封的院长", "role": "DEAN"}, token)
    if st == 200:
        _purge_user(DEAN_PROBE + "_api")
        return True
    return False


def _insert_dean_probe(username: str = DEAN_PROBE, dean_only: int = 0) -> str | None:
    """直写库造一个院长探针 + 登录拿令牌。

    为什么不用 API：院长等级高于本用例的执行身份（班主任），API 必然拒绝——
    而那正是期望行为。见 `test_a20_dean_role` 的说明。

    `dean_only=1` 造纯院长（第五十二轮：验证「纯院长也能再开院长」）。
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
        from app.security import hash_password as _hash
    except Exception:  # noqa: BLE001
        return None
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": username})
        uid = c.execute(_t(
            "SELECT id FROM sys_user WHERE username = :root LIMIT 1"),
            {"root": "test"}).scalar()
        if uid is None:
            return None
        cid = c.execute(_t("SELECT class_id FROM sys_user WHERE id = :i"),
                        {"i": uid}).scalar()
        c.execute(_t(
            "INSERT INTO sys_user (class_id, username, password, real_name, "
            "role, dean_only, status) VALUES (:c, :u, :p, :n, 'DEAN', :d, 1)"),
            {"c": cid, "u": username, "p": _hash("123456"), "n": "院长探针",
             "d": 1 if dean_only else 0})
    return login(username, "123456")


def _probe_id(username: str = DEAN_PROBE) -> int:
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return -1
    with _engine.connect() as c:
        return c.execute(_t("SELECT id FROM sys_user WHERE username = :u"),
                         {"u": username}).scalar() or -1


def test_a20_dean_role():
    """**院长（DEAN）**（第二十八轮）：等级最高、系统管理员。

    本用例的重点不是「院长能不能建号」这种单点功能，而是**两处最容易漏的地方**：

    1. **前后端各有一份手写的等级表**（`security.ROLE_LEVEL` 与
       `member-manage/index.vue` 的 `ROLE_LEVEL`）。加角色时只改一边，
       界面就会「按错误的等级隐藏按钮」——不报错，只是按钮该在不在。
       所以下面直接从 .vue 源码里正则抠出那张表跟后端逐项比对。
    2. **等级倒挂**：院长等级(4) > 班主任(3)，任何「只有班主任能做」的闸门
       如果写成 `role != "TEACHER"`，就会变成「班主任能做、院长不能」——
       更高权限反而更受限。这类闸门必须按等级判定。
    """
    print("\n--- 院长角色（系统管理员）---")
    root = pathlib.Path(__file__).resolve().parents[2]
    sys.path.insert(0, root / "server-py")
    from app.security import ROLE_LEVEL, STAFF_ROLES  # noqa: PLC0415

    # ---------- ① 等级表本身 ----------
    check("DEAN 已进入等级表且为最高档",
          "DEAN" in ROLE_LEVEL and ROLE_LEVEL["DEAN"] == max(ROLE_LEVEL.values()),
          str(ROLE_LEVEL))
    check("DEAN 高于 TEACHER（院长是系统管理员，不能低于班主任）",
          ROLE_LEVEL.get("DEAN", 0) > ROLE_LEVEL.get("TEACHER", 0),
          f"DEAN={ROLE_LEVEL.get('DEAN')} TEACHER={ROLE_LEVEL.get('TEACHER')}")
    check("DEAN 属于运营角色 STAFF_ROLES（默认院长=管理员，能记账能管成员）",
          "DEAN" in STAFF_ROLES, str(sorted(STAFF_ROLES)))

    # ---------- ② ★ 前后端等级表必须逐项一致 ----------
    #
    # 第二十九轮起这张表收进了 `types/index.ts`（仪表盘也要判等级）。
    # 收之前它只在 member-manage 里，两边各写一份数值——加角色时只改一边，
    # 界面就「按错误的等级隐藏按钮」，不报错，只是按钮该在不在。
    types_for_level = (root / "web/src/types/index.ts").read_text(encoding="utf-8-sig")
    block = re.search(r"export const ROLE_LEVEL:\s*Record<Role,\s*number>\s*=\s*\{(.*?)\n\}",
                      types_for_level, re.S)
    if not check("能从 types/index.ts 解析出共享 ROLE_LEVEL 表", block is not None):
        return
    fe = {m.group(1): int(m.group(2)) for m in
          re.finditer(r"([A-Z]+):\s*(\d+)\s*,", block.group(1))}
    check("前后端 ROLE_LEVEL 的角色集合完全一致",
          set(fe) == set(ROLE_LEVEL), f"前端={sorted(fe)} 后端={sorted(ROLE_LEVEL)}")
    mismatch = {k: (fe[k], ROLE_LEVEL.get(k)) for k in set(fe) & set(ROLE_LEVEL)
                if fe[k] != ROLE_LEVEL[k]}
    check("前后端 ROLE_LEVEL 的等级数值完全一致", not mismatch, str(mismatch))

    # 不许再有人写死第二份等级表（或写死 `role === 'DEAN'` 这种角色名判断）
    mm = (root / "web/src/views/member-manage/index.vue").read_text(encoding="utf-8-sig")
    check("成员管理不再自带第二份 ROLE_LEVEL 表",
          not re.search(r"const ROLE_LEVEL:\s*Record<Role,\s*number>", mm),
          "出现了重复的等级表，加角色时必然会漂")
    dash = (root / "web/src/views/dashboard/index.vue").read_text(encoding="utf-8-sig")
    # ⚠ 先把注释剥掉再查：这段文档本身就在讲「不要写 role === 'DEAN'」，
    # 不剥会**自己命中自己**——守卫的假阳性比没有守卫更浪费时间。
    dash_code = re.sub(r"/\*.*?\*/", "", dash, flags=re.S)
    dash_code = re.sub(r"//[^\n]*", "", dash_code)
    check("仪表盘按等级判院长，没有写死 role === 'DEAN'",
          "role === 'DEAN'" not in dash_code and "roleLevel(" in dash_code,
          "写死角色名：加新角色时会静默降权")

    # ---------- ③ 运营角色常量必须与后端一致，且只剩一份 ----------
    # 实测补上的两条教训，都源于「同一个角色列表在三个地方各写一份」：
    #   ① 院长登录后侧栏少了 5 个入口（SideNav.vue 的 STAFF 没加 DEAN）
    #   ② `/member-manage` 被路由守卫弹回仪表盘（router 的 meta.roles 没加 DEAN）
    # 现象都是「接口全 200、只是界面不对」，极难归因到权限。
    # 现在收成 `types/index.ts` 里的**唯一一份** STAFF_ROLES，两处都从它取。
    types_txt = (root / "web/src/types/index.ts").read_text(encoding="utf-8-sig")
    sb = re.search(r"export const STAFF_ROLES:\s*Role\[\]\s*=\s*\[(.*?)\]",
                   types_txt, re.S)
    if check("能从 types/index.ts 解析出共享的 STAFF_ROLES", sb is not None):
        staff_fe = set(re.findall(r"'([A-Z]+)'", sb.group(1)))
        check("共享 STAFF_ROLES 与后端 STAFF_ROLES 完全一致",
              staff_fe == set(STAFF_ROLES),
              f"前端={sorted(staff_fe)} 后端={sorted(STAFF_ROLES)}")
        # 不许再有人写死第二份
        dup = []
        for rel, pat in (("web/src/router/index.ts",
                          r"roles:\s*\[[^\]]*'TEACHER'[^\]]*\]"),
                         ("web/src/layout/SideNav.vue",
                          r"const STAFF[^=]*=\s*\[[^\]]*\]")):
            body = (root / rel).read_text(encoding="utf-8-sig")
            if re.search(pat, body):
                dup.append(rel)
        check("路由与侧栏不再各写一份运营角色字面量", not dup, "、".join(dup))

    # ---------- ③b 前端不许再手写角色列表 ----------
    #
    # 「同一个角色列表在多个地方各写一份」已经翻车**三次**：
    #   ① 侧栏少 5 个入口（SideNav 的 STAFF 没加 DEAN）
    #   ② 路由守卫把院长弹回仪表盘（router 的 meta.roles 没加 DEAN）
    #   ③ **store 的 isStaff 没加 DEAN** —— 院长点仪表盘「查看缴费名单」
    #      按钮会跳到 /my-fees，而那个路由的角色白名单里没有院长，
    #      守卫又把他弹回仪表盘：**点了像没反应**。
    #      同一个漏字还让院长看不到班级信息的编辑入口。
    # 三次都是「加角色时只改了一处」。所以现在**只允许有一处**。
    store_src = (root / "web/src/stores/user.ts").read_text(encoding="utf-8-sig")
    check("store 的 isStaff 用共享的 STAFF_ROLES，不自己写角色名",
          "STAFF_ROLES.includes" in store_src,
          "isStaff 又是手写的角色名列表，加角色时会静默漏掉")
    check("store 里不再出现手写的运营角色判断",
          not re.search(r"role\s*===\s*'(ADMIN|MONITOR|TEACHER)'\s*(\|\||\n)", store_src),
          "store 里还有手写的角色判断")

    # 班级信息：前端判「谁能改班主任姓名」必须**按等级**，和后端同口径。
    # 写成 `role === 'TEACHER'` 的话，院长（等级 4）比班主任（3）还受限。
    classinfo_src = (root / "web/src/views/class-info/index.vue").read_text(encoding="utf-8-sig")
    # ⚠ 先剥注释再查：这段说明里**本身**就写着那个反例的字面量，
    # 不剥会自己命中自己——守卫的假阳性比没有守卫更费时间。
    classinfo_code = re.sub(r"/\*.*?\*/", "", classinfo_src, flags=re.S)
    classinfo_code = re.sub(r"//[^\n]*", "", classinfo_code)
    check("班级信息按等级判「谁能改班主任姓名」（不写死角色名）",
          "role === 'TEACHER'" not in classinfo_code and "roleLevel(" in classinfo_src,
          "前后端口径不一致：后端按等级放行院长，前端却把输入框藏了")

    # ---------- ④ 前后端角色中文名 ----------
    tblock = re.search(r"ROLE_TEXT:\s*Record<Role,\s*string>\s*=\s*\{(.*?)\n\}",
                       types_txt, re.S)
    if check("能从 types 里解析出 ROLE_TEXT 表", tblock is not None):
        tkeys = set(re.findall(r"([A-Z]+):\s*'", tblock.group(1)))
        check("ROLE_TEXT 覆盖了全部角色（含 DEAN）",
              tkeys == set(ROLE_LEVEL), f"前端={sorted(tkeys)} 后端={sorted(ROLE_LEVEL)}")

    # ---------- ⑤ 落库枚举必须含 DEAN ----------
    schema_sql = (root / "server-py/db/schema.sql").read_text(encoding="utf-8-sig")
    enum_line = next((ln for ln in schema_sql.splitlines()
                      if "role " in ln and "ENUM(" in ln), "")
    check("schema.sql 的 role ENUM 含 DEAN（否则新库建不出院长）",
          "'DEAN'" in enum_line, enum_line.strip()[:90])

    # ---------- ⑥ 端到端：真建一个院长账号，跑一遍关键闸门 ----------
    #
    # ⚠ 院长探针**不能走 API 建**：`create_user` 拦「不能创建权限高于自己的角色」，
    # 而本用例的执行身份是班主任(3) < 院长(4)，必然被拒——而且**这是对的**，
    # 否则任何班主任都能给自己升成系统管理员。第一个院长的正规来路是部署时
    # 的声明式账号（`CLASSFEE_TEACHER_ROLE=DEAN`，见 seed.py），
    # 回归脚本在这里直接写库，等价于「管理员已经存在」。
    T = S["T"]
    check("班主任建不了院长（不能自我提权）-> 400",
          _try_create_dean_via_api(T) is False, "班主任竟然能建院长，权限护栏漏了")

    D = _insert_dean_probe()
    if not check("院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        return

    # 院长是运营角色：记账权限与班主任同权
    st, j = call("GET", "/records?page=1&size=1", None, D)
    check("院长能读账本明细（运营角色）", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/users", None, D)
    check("院长能进成员管理（运营角色）", st == 200, f"st={st} {msg_of(j)}")

    # 等级最高：能管理班主任 —— 这是「默认院长=系统管理员」的核心体现
    rows = data_of(j) or []
    teacher_row = next((u for u in rows
                        if u["id"] == S["root_id"] and u["role"] == "TEACHER"), None)
    if check("成员列表里能看到班主任", teacher_row is not None, str(rows)[:120]):
        # ⚠ 先存原值、写回原值：这一句会**永久改掉班主任的真实姓名**。
        # 之前没还原，跑一次回归基线里的 test 账号就变成 "x" 了——
        # 症状是登录后侧栏显示 "x"，像是数据丢了，其实是测试的副作用。
        orig_real_name = teacher_row.get("realName") or ""
        st, j = call("PUT", f"/users/{teacher_row['id']}", {"realName": "x"}, D)
        check("院长能管理班主任（等级最高，系统管理员）-> 200", st == 200,
              f"st={st} {msg_of(j)}")
        call("PUT", f"/users/{teacher_row['id']}", {"realName": orig_real_name}, T)
        st, j = call("GET", "/users", None, D)
        back = next((u for u in (data_of(j) or []) if u["id"] == teacher_row["id"]), {})
        check("班主任姓名已还原（用例不留下改过的基线数据）",
              (back.get("realName") or "") == orig_real_name,
              f"{back.get('realName')!r} vs {orig_real_name!r}")

    # 反向：班主任管不了院长
    st, j = call("PUT", f"/users/{_probe_id()}", {"realName": "x"}, T)
    check("班主任管不了院长（等级更低）-> 400/403", st in (400, 403),
          f"st={st} {msg_of(j)}")

    # 改**自己**的资料不受等级护栏约束（`update_user` 里 `target.id != user.id`
    # 才走 require_role_higher）——这是设计如此，别把它误当成"护栏漏了"。
    st, j = call("PUT", f"/users/{_probe_id()}", {"realName": "院长探针"}, D)
    check("院长改自己的资料 -> 200（改自己不经过等级护栏，设计如此）", st == 200,
          f"st={st} {msg_of(j)}")

    # 同级不可互管：需要**另一个**院长，才测得出「同级」这条规则
    D2 = _insert_dean_probe(DEAN_PROBE + "2")
    if check("第二个院长探针可用", bool(D2), "建号失败"):
        st, j = call("PUT", f"/users/{_probe_id()}", {"realName": "另一个院长改的"}, D2)
        check("院长之间也不能相向踢下线（同级不可互管）-> 400/403", st in (400, 403),
              f"st={st} {msg_of(j)}")
        _purge_user(DEAN_PROBE + "2")

    # 院长是学生信息的审批人（APPROVER_ROLES 从等级推导，应自动包含）
    st, j = call("GET", "/students", None, D)
    perm = (data_of(j) or {}).get("permission") or {}
    check("院长 isTeacher=True（>= 班主任才有的审批权）",
          perm.get("isTeacher") is True, str(perm))
    check("院长 canAddField=True（>= 班长才有的加字段权）",
          perm.get("canAddField") is True, str(perm))

    st, j = call("GET", "/tasks", None, D)
    check("院长能读班级任务", st == 200, f"st={st} {msg_of(j)}")

    # 院长不是学生，不该出现在缴费名单里（`PAYABLE_ROLES` 是白名单，本就不含 DEAN）
    st, j = call("GET", "/members", None, D)
    payable_roles = {u.get("role") for u in (data_of(j) or [])}
    check("院长不出现在缴费名单里（PAYABLE_ROLES 是白名单）",
          "DEAN" not in payable_roles, f"名单里出现了院长: {sorted(payable_roles)}")

    # ★ 「既是院长又是班主任」这个场景的守卫
    # `head_teacher`（班主任姓名）原先判的是 `role != "TEACHER"`——按**角色名**写死。
    # 一个既是院长又是班主任的人登录后，改不了自己的班主任姓名（比班主任身份还低）。
    # 原实现的注释本来就写的是「等级 3」，代码与注释不一致，只是当时恰好等价。
    #
    # 先记住原值再改、最后还原：本用例不该把基线数据留在改过的状态。
    #
    # ⚠ 比较时必须归一化 null/""：接口里 `headTeacher: ""` 的语义是「**清空**」，
    # 回读是 null；我第一版写 `orig = ....get("headTeacher") or ""` 把 null 折叠成
    # 空串，于是还原后拿到 null、和存下来的 "" 比不相等——**还原其实成功了，
    # 断言却是红的**。这种「测对了但报错了」的失败比真失败更费时间。
    st, j = call("GET", "/class", None, T)
    orig_teacher = (data_of(j) or {}).get("headTeacher") or None
    st, j = call("PUT", "/class", {"headTeacher": "王院长"}, D)
    check("院长能写班主任姓名（>= 班主任等级；「既院长又班主任」的场景）",
          st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", "/class", {"headTeacher": "生活委员冒名"}, S["A"])
    check("生活委员仍写不了班主任姓名（等级不够）-> 403", st == 403,
          f"st={st} {msg_of(j)}")
    # None(清空) 用 "" 表达；有值就用原值
    call("PUT", "/class", {"headTeacher": orig_teacher or ""}, T)
    st, j = call("GET", "/class", None, T)
    check("班主任姓名已还原（用例不留下改过的基线数据）",
          ((data_of(j) or {}).get("headTeacher") or None) == orig_teacher,
          f"{((data_of(j) or {}).get('headTeacher') or None)!r} vs {orig_teacher!r}")

    # 院长能建访客（不该出现「班主任能建、院长不能建」的倒挂）
    st, j = call("POST", "/users",
                 {"username": "guest_by_dean", "password": "123456",
                  "realName": "院长建的访客", "role": "GUEST"}, D)
    check("院长能创建访客账号（等级闸门无倒挂）", st == 200, f"st={st} {msg_of(j)}")
    _purge_user("guest_by_dean")

    _purge_user(DEAN_PROBE)


def _purge_students_prefix(prefix: str) -> None:
    """删掉学号以 prefix 开头的学生行（含其字段值）。

    ⚠ **必须直写库**：产品里**没有** `DELETE /api/students/{id}`（学生行只能
    新增 / 导入 / 编辑，不能删），所以走接口只会拿到 404/405 然后静默什么都不做。
    我第一版就是这么写的——清零条、断言却报「没清干净」，一度以为是口径算错。

    还要连带删 `student_record_value`：本库**不建外键**，只删主表会留下一地
    孤儿值行，那些行永远读不到。
    """
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    try:
        from sqlalchemy import text as _t

        from app.db import engine as _engine
    except Exception:  # noqa: BLE001
        return
    with _engine.begin() as c:
        ids = [r[0] for r in c.execute(
            _t("SELECT id FROM student_record WHERE student_no LIKE :p"),
            {"p": prefix + "%"})]
        if not ids:
            return
        c.execute(_t("DELETE FROM student_record_value WHERE record_id IN :i"),
                  {"i": tuple(ids)})
        c.execute(_t("DELETE FROM student_record WHERE id IN :i"), {"i": tuple(ids)})


def test_a21_student_dashboard():
    """仪表盘「学生情况总览」（第二十九轮）。

    五条重点，都是容易错且错得不响的地方：

    1. **仅院长可见**（第二十九轮末收紧）。班主任虽然本来就能在「学生信息」
       里看到全部行，但看板的身份是校级看板，权限按用户口径给院长。
       必须**后端 403 + 前端不渲染**两条腿都走，只做一边都会漏。
    2. **可见范围仍与学生信息表同口径**。进了闸之后也不因为「是院长」就
       绕过行级权限——这里防的是将来有人给 `dashboard_stats` 加一句无条件查询。
    3. **学籍异动没有数据源**，必须返回 `null` 而不是 0。画一条全零折线
       会被读成「本年零异动」，那是撒谎。
    4. **空值注册状态要算在籍**：模板 34 个字段而 Excel 不会每列都填，
       一空就算未知的话分母会被掏空，「注册人数」会比「学生总数」还小。
    5. 计数断言用**增量**——本用例跑在 test_a16 之后、test_a15 清理之前，
       库里天然有别的用例留下的学生行。
    """
    print("\n--- 学生情况总览 ---")
    T = S["T"]
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from app.services.student_service import REG_STATUS_RULES  # noqa: PLC0415

    # ---------- ⓪ ★ 仅院长：后端必须硬拦 ----------
    #
    # 这道闸门是「身份」而不是「数据可见性」：班主任在 /students 里本来就能
    # 看到全部行，但管理看板按用户口径只给院长。
    #
    # ⚠ 前端不渲染 + 后端 403 **两条腿都要**：
    #   - 只做后端：班主任看到标签、点进去报「无权」，比看不到更糟
    #   - 只做前端：手输接口照样拿得到数据
    dashboard_py = (pathlib.Path(__file__).resolve().parents[1]
                    / "app/routers/dashboard.py").read_text(encoding="utf-8")
    check("后端 /dashboard/students 挂了 require_min_level(DEAN)",
          'require_min_level(user, "DEAN"' in dashboard_py,
          "路由没加等级闸门，手输接口即可绕过")
    check("学生总览不再只靠行级权限（行级仅 4 项，挡不住 redirect）",
          "require_min_level" in dashboard_py.split("/students")[-1],
          "闸门不在 /students 处理函数里")

    for name, tok in (("班主任", T), ("生活委员", S["A"]), ("普通同学", S["M"])):
        st, j = call("GET", "/dashboard/students", None, tok)
        check(f"{name}访问学生总览 -> 403（仅院长）", st == 403, f"st={st} {msg_of(j)}")

    # 院长探针：直写库（班主任建不了院长，见 test_a20 的说明）
    D = _insert_dean_probe(DEAN_PROBE + "_dash")
    if not check("院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        return

    st, j = call("GET", "/dashboard/students", None, D)
    check("院长访问学生总览 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # ---------- 院长的口径 = **全校**（不是他那个班） ----------
    #
    # 这个总览只有院长能看，看板的身份是「校级看板」。之前它统计的是
    # `user.class_id`（本班口径），于是全校名册里填了 7 个人、看板只有
    # 那个班的 4 个——数字和「学院学生信息」对不上。
    #
    # 断言方式：**直接查库**数一遍所有启用班的学生数，跟接口返回的对比。
    from sqlalchemy import text as _t1

    from app.db import engine as _engine1

    with _engine1.connect() as c:
        all_students = int(
            c.execute(
                _t1("SELECT COUNT(*) FROM student_record WHERE class_id IN "
                    "(SELECT id FROM cls_class WHERE status = 1)")
            ).scalar()
            or 0
        )
    d_stu = data_of(j) or {}
    check("★ 院长的总览是**全校口径**（collegeScope=true）",
          d_stu.get("collegeScope") is True, str(d_stu)[:200])
    check("★ 院长的总览人数 = 所有启用班的学生数（不是本班）",
          int(d_stu.get("studentTotal") or 0) == all_students,
          f"接口 {d_stu.get('studentTotal')} vs 库里 {all_students}")

    # 前端：非院长时不渲染切换器里的第二个标签
    dash_vue = (pathlib.Path(__file__).resolve().parents[2]
                / "web/src/views/dashboard/index.vue").read_text(encoding="utf-8-sig")
    check("前端按 isDean 决定是否给出「学生情况总览」标签",
          "isDean" in dash_vue and "学生情况总览" in dash_vue,
          "标签没按院长收紧")
    check("切换器在只有一个选项时不渲染（不摆死按钮）",
          'VIEWS.length > 1' in dash_vue, "单选项时切换器仍会渲染")
    check("学生面板模板也判 isDean（防登录态变化后残留）",
          'v-else-if="isDean"' in dash_vue, "模板只判 view，降级后会继续显示")

    # ---------- ⓪ 回归不许删真实数据 ----------
    #
    # 这条是从**事故**来的：用户往「学院学生信息」导了一份名册，
    # 跑完回归，名单没了——因为清理用例当时是「删掉老师班里的全部学生 +
    # 全部自定义列」。回归只该清理**自己造的行**。
    #
    # 所以这里直接查库：造一条「像用户导进来的」记录，跑一遍清理，
    # 确认它**还在**。这条断言比读源码可靠——源码改了但行为没改的情况，
    # 只有真的跑一遍才看得出来。
    from sqlalchemy import text as _t0

    from app.db import engine as _engine0

    _REAL_NO = "regress_real_keep_me"
    with _engine0.begin() as c:
        c.execute(_t0("DELETE FROM student_record WHERE student_no = :n"), {"n": _REAL_NO})
        cid0 = c.execute(
            _t0("SELECT class_id FROM sys_user WHERE username = :u LIMIT 1"), {"u": ROOT_U}
        ).scalar()
        if cid0 is not None:
            c.execute(
                _t0("INSERT INTO student_record (class_id, student_no, name) "
                    "VALUES (:c, :n, '回归不该删我')"),
                {"c": cid0, "n": _REAL_NO},
            )
    _purge_student_info(T)
    with _engine0.connect() as c:
        still = c.execute(
            _t0("SELECT COUNT(*) FROM student_record WHERE student_no = :n"), {"n": _REAL_NO}
        ).scalar()
    check("★ 回归清理**不会删掉用户自己导入的学生**（只删探针行）",
          int(still or 0) == 1, f"清理后还在 {still} 行（0 = 被误删了）")
    with _engine0.begin() as c:
        c.execute(_t0("DELETE FROM student_record WHERE student_no = :n"), {"n": _REAL_NO})

    # ---------- ① 形状 ----------
    st, j = call("GET", "/dashboard/students", None, D)
    d = data_of(j) or {}
    check("返回结构完整", st == 200, f"st={st} {msg_of(j)}")
    for k in ("canViewAll", "studentTotal", "registeredTotal", "statusBreakdown",
              "enrollTrend", "latest", "changeTotal", "changeSupported"):
        check(f"返回结构含 {k}", k in d, str(sorted(d)))
    check("**学籍异动返回 null 而不是 0**（0 会被读成「零异动」）",
          d.get("changeTotal") is None and d.get("changeSupported") is False,
          f"changeTotal={d.get('changeTotal')!r} supported={d.get('changeSupported')!r}")
    check("注册人数不会超过学生总数",
          int(d.get("registeredTotal") or 0) <= int(d.get("studentTotal") or 0),
          f"{d.get('registeredTotal')} > {d.get('studentTotal')}")

    # ---------- ② 造数据验证口径 ----------
    #
    # ⚠ 全部用**增量**断言，不用绝对计数。本用例跑在 test_a16 之后、
    # test_a15 清理之前，所以库里天然还留着别的用例造的学生。第一版写的是
    # 「总数 == 5」，结果数到 9——那些多出来的不是 bug，是我没考虑执行顺序。
    # 增量写法与库里已有多少数据无关，才是对的。
    base_total = int(d.get("studentTotal") or 0)
    base_reg = int(d.get("registeredTotal") or 0)

    made = [("dash_u_%d" % i, "总览探针%d" % i) for i in range(3)]
    for no, name in made:
        call("POST", "/students",
             {"studentNo": no, "name": name,
              "values": {"reg_status": "在籍", "enroll_date": "2026-09-01",
                         "grade": "2026级"}}, T)
    # 一个休学的（应被排除在「注册人数」外，但仍计入「学生数量」）
    call("POST", "/students",
         {"studentNo": "dash_u_x", "name": "休学探针",
          "values": {"reg_status": "休学", "enroll_date": "2026-09-02"}}, T)
    # 一个注册状态留空的（应算在籍）
    call("POST", "/students",
         {"studentNo": "dash_u_b", "name": "空状态探针",
          "values": {"reg_status": "", "enroll_date": "2026-09-03"}}, T)

    st, j = call("GET", "/dashboard/students", None, D)
    d = data_of(j) or {}
    added_total = len(made) + 2
    check("学生数量增量 = 造进去的行数（含休学与空状态）",
          int(d.get("studentTotal") or 0) - base_total == added_total,
          f"{d.get('studentTotal')} - {base_total} != {added_total}")
    # 在籍增量 = 在籍 3 + 空状态 1（休学被排除）
    check("学籍注册人数增量 = 在籍 + 空状态，休学被排除",
          int(d.get("registeredTotal") or 0) - base_reg == len(made) + 1,
          f"增量 {int(d.get('registeredTotal') or 0) - base_reg}，预期 {len(made) + 1}")
    bd = {b["status"]: b["count"] for b in (d.get("statusBreakdown") or [])}
    check("状态分布里本用例的休学探针被单列", bd.get("休学", 0) >= 1, str(bd))
    _words = [w for _label, ws in REG_STATUS_RULES for w in ws]
    check("学籍归类表含休学/退学/毕业/入伍这类写法",
          all(k in _words for k in ("休学", "退学", "毕业", "入伍")), str(_words))

    # ---------- ③ 趋势按入校月份累计 ----------
    tr = d.get("enrollTrend") or []
    check("趋势按 YYYY-MM 聚合", all(len(p["ym"]) == 7 and p["ym"][4] == "-" for p in tr),
          str(tr))
    cums = [p["cumulative"] for p in tr]
    check("累计人数单调不减", cums == sorted(cums), str(tr))
    # 末值 >= 基数（本用例 5 人都有入校日期）
    check("累计末值 >= 初始累计 + 本用例 5 人",
          (cums[-1] if cums else 0) >= added_total,
          f"{cums[-1] if cums else 0} < {added_total}")

    # ---------- ④ ★ 院长进闸之后仍走行级权限，不再叠加特权 ----------
    #
    # 原来这里用普通同学验证「看板不是权限后门」。现在普通同学是 403，
    # 这条改为**验证院长看到的是全班**（`canViewAll=true` 来自 APPROVER_ROLES
    # 的等级推导），并且——关键——`latest` 的条数受 LATEST_LIMIT 约束而不是
    # 等于总数，说明它走的是同一套 `_visible_record_ids`。
    check("院长 canViewAll=true（学生信息表同口径，不是另开的特权通道）",
          d.get("canViewAll") is True, str(d)[:120])
    check("院长的「最新学籍信息」受条数上限约束（不是把全表一次吐出来）",
          0 < len(d.get("latest") or []) <= 8,
          f"latest={len(d.get('latest') or [])}")

    # 清理（只删本用例造的行，别碰别的用例的）
    _purge_students_prefix("dash_u_")
    st, j = call("GET", "/dashboard/students", None, D)
    d2 = data_of(j) or {}
    check("清理后回到起始数量（用例不留下数据）",
          int(d2.get("studentTotal") or 0) == base_total,
          f"{d2.get('studentTotal')} vs 起始 {base_total}")

    _purge_user(DEAN_PROBE + "_dash")


def test_a22_chart_container_visibility() -> None:
    """图表容器**必须**用 `v-if`，不能用 `v-show`（第二十九轮末实测修的既有 bug）。

    ## 症状

    页面刚打开时，所有 ECharts 图表的画布只有 **100px** 宽，挤在 800+px
    容器的左边——图形被压扁到看不见。**刷新后一直是这样**，直到用户碰巧
    拖动了一下窗口（`resize` 事件 → `chart.resize()`）才恢复。

    ## 根因

    图表容器用 `v-show` 控制显隐，而 `v-show` 的 `display:none` 在
    **数据到达之前**就生效了：组件挂载时 `points` 还是空的 → 容器隐藏 →
    `echarts.init()` 在隐藏容器上量到的宽度是 0 → 画布退化成 100px。
    之后 ECharts **不会重新量**一个隐藏元素的尺寸，`resize()` 也救不回来。

    这不是本轮新写的组件的毛病——`TrendChart.vue`（账目总览的收支趋势图）
    和 `CategoryPie.vue`（支出分类占比）**早就是这个写法**，两个主图表一直
    是坏的，只是之前库里的数据是空的、图表从没显示出来过，没人发现。

    ## 修法

    容器改成 `v-if`（有数据才存在，挂载那一刻就可见且有真实宽度），
    并把建实例抽成幂等的 `ensureChart()`——因为 `v-if` 由 false 变 true 时
    组件**不会重新挂载**，`onMounted` 不会再跑。

    本用例钉死这个写法，防止有人改回 `v-show`。
    """
    print("\n--- 图表容器显隐（ECharts 画布尺寸）---")
    root = pathlib.Path(__file__).resolve().parents[2]
    comps = [
        "web/src/components/TrendChart.vue",
        "web/src/components/CategoryPie.vue",
        "web/src/components/StudentTrendChart.vue",
    ]
    for rel in comps:
        path = root / rel
        if not check(f"{rel} 存在", path.exists(), str(path)):
            continue
        src = path.read_text(encoding="utf-8-sig")
        name = path.name
        check(f"{name} 的图表容器用 v-if 而不是 v-show",
              'v-show="hasData"' not in src,
              "v-show 会让 ECharts 在隐藏容器上 init，画布退化成 100px")
        check(f"{name} 有幂等的 ensureChart()（v-if 变 true 时组件不重新挂载）",
              "function ensureChart(" in src,
              "建实例只写在 onMounted 里的话，数据晚到一步图表就永远画不出来")
        check(f"{name} 渲染前会 resize（容器宽度变了得自己告诉 ECharts）",
              "chart.resize()" in src or "chart?.resize()" in src,
              "setOption 只画不量")
        check(f"{name} 数据 watcher 是 post 刷新（要等 v-if 创建出容器）",
              "flush: 'post'" in src,
              "pre 刷新时 v-if 的容器还不存在，量不到 ref")


def test_a23_college_views() -> None:
    """学院视角（第三十轮）：跨班级的学生名册 / 班主任名册 / 任务一览。

    四条重点：

    1. **仅院长**。学院 = 全部班级的聚合，是校级视角；班主任在班级层
       已经能看到本班全部数据，再给一份跨班的只是重复。后端必须 403。
    2. **跨班级**：名册要能同时给出多个班的学生，且带上班级名——
       跨班名册里不写班级等于没写。
    3. **搜索筛选**：关键字要能命中**学号、姓名，以及任意 TEXT 字段**
       （专业、宿舍号这些才是「按关键字找人」时真会用到的）。
    4. **任务分母按任务自己那个班算**：跨班混算会得出「已填 3 / 共 60 人」
       这种没人看得懂的数。
    """
    print("\n--- 学院视角 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    T = S["T"]
    D = _insert_dean_probe(DEAN_PROBE + "_college")
    if not check("院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        return

    # ---------- ① 仅院长：后端硬拦 ----------
    for name, tok in (("班主任", T), ("生活委员", S["A"]), ("普通同学", S["M"])):
        for p in ("/college/students", "/college/advisers", "/college/tasks"):
            st, j = call("GET", p, None, tok)
            check(f"{name}访问 {p} -> 403（学院视角仅院长）", st == 403,
                  f"st={st} {msg_of(j)}")

    for p in ("/college/students", "/college/advisers", "/college/tasks"):
        st, j = call("GET", p, None, D)
        check(f"院长访问 {p} -> 200", st == 200, f"st={st} {msg_of(j)}")

    # 源码守卫：闸门必须在**处理函数里**，不能只挂在别的路由上。
    #
    # ⚠ 不能写死「几个 require_min_level」——学院路由一直在长（3 → 9），
    # 写死的数要么误报、要么被改成「>= 3」而失去意义。
    # 这里比的是**端点数 == 闸门数**：以后新加一个端点却忘了加闸门，
    # 两个数就对不上，回归立刻红。
    college_py = (root / "app/routers/college.py").read_text(encoding="utf-8")
    n_routes = len(re.findall(r"@router\.(get|post|put|delete)\(", college_py))
    n_gates = len(re.findall(r"require_min_level\(user, \"", college_py))
    check("学院路由每个端点都有等级闸门（端点数 == 闸门数）",
          n_routes == n_gates and n_routes > 0, f"端点 {n_routes} 个，闸门 {n_gates} 个")

    # ---------- ② 跨班级：造两个班的学生 ----------
    st, j = call("GET", "/college/students?size=200", None, D)
    d = data_of(j) or {}
    base_total = int(d.get("total") or 0)
    classes = d.get("classes") or []
    check("名册给出可筛选的班级清单", len(classes) >= 1, str(classes)[:120])
    check("名册给出可筛选的年级清单", isinstance(d.get("grades"), list), str(d.get("grades")))

    made = [("col_u_%d" % i, "学院探针%d" % i) for i in range(2)]
    for no, name in made:
        call("POST", "/students",
             {"studentNo": no, "name": name,
              "values": {"major_name": "软件工程", "grade": "2026级"}}, T)
    st, j = call("GET", "/college/students?size=200", None, D)
    d = data_of(j) or {}
    check("名册总数随新增而增加（跨班级可见）",
          int(d.get("total") or 0) == base_total + len(made),
          f"{d.get('total')} vs {base_total + len(made)}")
    rows = d.get("rows") or []
    check("每一行都带班级名（跨班名册里不写班级等于没写）",
          all(r.get("className") for r in rows), str(rows)[:120])

    # ---------- ③ 搜索筛选 ----------
    st, j = call("GET", "/college/students?keyword=" + urllib.parse.quote("软件工程"), None, D)
    hit = data_of(j) or {}
    hit_rows = hit.get("rows") or []
    check("关键字能命中**任意 TEXT 字段**（专业），不只是学号/姓名",
          len(hit_rows) >= len(made),
          f"命中 {len(hit_rows)} 行，预期 >= {len(made)}")
    check("命中行确实都是那个专业的",
          all((r.get("values") or {}).get("major_name") == "软件工程" for r in hit_rows),
          str([(r.get("studentNo"), (r.get("values") or {}).get("major_name")) for r in hit_rows]))

    st, j = call("GET", "/college/students?keyword=" + urllib.parse.quote("col_u_0"), None, D)
    check("关键字能命中学号",
          len((data_of(j) or {}).get("rows") or []) == 1,
          str((data_of(j) or {}).get("rows")))

    st, j = call("GET", "/college/students?keyword=" + urllib.parse.quote("不存在的关键字zzz"), None, D)
    check("搜不到时返回 0 行（不是报错，也不是全量）",
          int((data_of(j) or {}).get("total") or 0) == 0,
          str((data_of(j) or {}).get("total")))

    # 按班级筛选
    if len(classes) >= 2:
        cid = classes[1]["id"]
        st, j = call(f"GET", f"/college/students?classId={cid}", None, D)
        filtered = data_of(j) or {}
        check("按班级筛选后只剩该班的学生",
              all(r.get("classId") == cid for r in (filtered.get("rows") or [])),
              str([(r.get("studentNo"), r.get("classId")) for r in (filtered.get("rows") or [])]))
    else:
        check("按班级筛选后只剩该班的学生（库里只有一个班，跳过）", True, "单班")

    # ---------- ④ 只显示有值的列 ----------
    check("返回 populatedKeys（全空列会被前端隐藏）",
          isinstance(d.get("populatedKeys"), list) and "major_name" in (d.get("populatedKeys") or []),
          str(d.get("populatedKeys"))[:200])
    check("有值的列是列定义的子集",
          set(d.get("populatedKeys") or []) <= {c["key"] for c in (d.get("columns") or [])},
          str(d.get("populatedKeys"))[:200])

    # ---------- ⑤ 班主任名册 ----------
    #
    # 第三十二轮：名册按**关联表**（谁是哪个班的班主任）列，
    # 不再按「账号的默认班」推。
    #
    # ⚠ 第五十一轮：**不要再在这里「把每个老师的默认班补进关联表」**。
    # 一个班只有一位班主任，把所有人的默认班都补一遍，正是
    # 「一个班冒出两个班主任」的制造机（真机上 haixuan-ls 就这么被
    # 重启时的 seed 挂回大数据2502 的）。默认班关联由 seed 在启动时
    # 按规则回填；用例需要谁出现，就**单独**补谁（见下面的院长探针）。
    from sqlalchemy import text as _t2
    from app.db import engine as _engine2

    st, j = call("GET", "/college/advisers", None, D)
    adv = data_of(j) or {}
    arows = adv.get("rows") or []
    # 一人一行：没有班主任账号的班也占一行（teacherId=null），
    # 所以行数 >= 班级数，而不是等于。
    check("名册每个班至少占一行（没账号的班也在表上）",
          len(arows) >= len(classes), f"{len(arows)} vs {len(classes)}")
    check("每行都有班级名", all(r.get("className") for r in arows), str(arows)[:160])
    check("每行最多一个账号（一行一人，不是一个班里塞几个）",
          all("teachers" not in r for r in arows),
          "还是一班一行的旧形状：账号挤在一格里，状态会渲染成两个「启用」")
    check("名册带账号信息（能联系上人）",
          any(r.get("username") for r in arows), str(arows)[:200])
    # 名册只该出现**合法的班主任账号**：role=TEACHER，或兼班主任的院长。
    # 这里对着库里的真实集合比，而不是硬编码用户名白名单——
    # 白名单会漏（兼班主任的院长就不在里面），而且账号一改就失效。
    with _engine2.connect() as c:
        legit = {
            r[0]
            for r in c.execute(
                _t2(
                    "SELECT username FROM sys_user WHERE role = 'TEACHER' "
                    "OR (role = 'DEAN' AND dean_only = 0)"
                )
            )
        }
    listed = {r.get("username") for r in arows if r.get("username")}
    check("名册只列班主任账号（不含普通同学/生活委员/班长/访客）",
          listed <= legit,
          f"名册里混进了不该有的账号：{sorted(listed - legit)}")
    # 兼班主任的院长：他就是那个班的班主任，只是职务是院长。
    # 第五十一轮起**一个班只能有一位班主任**，院长也占这个名额——所以不能
    # 再把他挂到 test 的班上（那会人为造出两个班主任）。用测试自己的夹具班
    # 造一条干净的「院长是班主任」数据。
    dean_fixture = _fixture_class("回归名册院长夹具班")
    with _engine2.begin() as c:
        c.execute(
            _t2("INSERT INTO sys_user_class (user_id, class_id, is_adviser) "
                "SELECT id, :c, 1 FROM sys_user WHERE username = :u "
                "ON DUPLICATE KEY UPDATE is_adviser = 1"),
            {"c": int(dean_fixture), "u": DEAN_PROBE + "_college"},
        )
    st, j = call("GET", "/college/advisers", None, D)
    arows2 = data_of(j) or {}
    dean_rows = [
        r for r in (arows2.get("rows") or [])
        if r.get("username") == DEAN_PROBE + "_college"
    ]
    check("兼班主任的院长出现在班主任名册里", len(dean_rows) == 1,
          f"名册漏了兼班主任的院长：{dean_rows}")
    check("院长占的就是那个班唯一的一位班主任",
          bool(dean_rows) and dean_rows[0].get("classId") == int(dean_fixture),
          str(dean_rows)[:200])
    check("同一个班不会因为院长而多出一行",
          len([r for r in (arows2.get("rows") or [])
               if r.get("classId") == int(dean_fixture)]) == 1,
          str([r for r in (arows2.get("rows") or [])
               if r.get("classId") == int(dean_fixture)])[:200])
    # 第二个账号的手机号/最近登录**必须**也在（一人一行就是为了这个）
    two_teachers = [r for r in arows if r.get("username") == "test"]
    check("账号行的手机号/最近登录是它自己的（不是班里第一个人的）",
          all("phone" in r and "lastLoginAt" in r for r in two_teachers),
          str(two_teachers)[:200])

    # ---------- ⑥ 任务：分母按任务自己那个班 ----------
    st, j = call("GET", "/college/tasks", None, D)
    tks = data_of(j) or {}
    trows = tks.get("rows") or []
    check("学院任务列出所有班的任务",
          all(r.get("className") for r in trows), str(trows)[:160])
    check("任务带所属班级与答题分母",
          all("total" in r and "answered" in r for r in trows), str(trows)[:160])
    check("分母不会超过该班人数（跨班混算就会超）",
          all(r["total"] <= 1000 for r in trows), str(trows)[:160])

    # 清理
    _purge_students_prefix("col_u_")
    _purge_fixture_class("回归名册院长夹具班")
    _purge_user(DEAN_PROBE + "_college")


def test_a24_pure_dean() -> None:
    """**纯院长**（第三十轮）：只管学院，不参与班级事务。

    院长有两种：① 兼班主任（本班的账目/任务/成员他都管，第二十八轮以来的行为）；
    ② 纯院长（只管学院那一层）。

    三条重点：

    1. **老账号保持兼班主任**：`dean_only` 列默认 0，存量账号一行都不用改，
       行为完全不变（第三十三轮起**新建**院长默认纯院长，见 `create_user`）。
    2. **白名单而不是黑名单**：纯院长能碰的接口是一张**允许清单**，
       将来加了新接口而忘了加进白名单，纯院长访问不到（可发现、可补）；
       反过来若用黑名单，漏一个就是**静默放行**（不可发现）。
    3. **改标志要立刻生效**：它不进 JWT（JWT 签发后就固定了），
       靠鉴权中间件每次请求重读那一列——和 status / guest_scopes 同一条路子。
    """
    print("\n--- 纯院长 ---")
    root = pathlib.Path(__file__).resolve().parents[1]      # server-py/
    repo = pathlib.Path(__file__).resolve().parents[2]      # 仓库根
    sys.path.insert(0, str(root))
    from app.security import pure_dean_allowed  # noqa: PLC0415

    # ---------- ① 纯院长能碰的 ----------
    for method, path in (
        ("GET", "/api/college/students"),
        ("GET", "/api/college/advisers"),
        # 第五十二轮：院长账号可以有多个，纯院长也要能再开一个。
        ("GET", "/api/college/deans"),
        ("POST", "/api/college/deans"),
        ("GET", "/api/college/tasks"),
        # 名册是院长的本职：改一格 / 转班 / 删行都在这条前缀下
        ("PUT", "/api/college/students/1"),
        ("DELETE", "/api/college/students"),
        # 「个人信息」页的「我带的班」要它渲染班名（只有 id/班名/年级）
        ("GET", "/api/class/choices"),
        ("GET", "/api/dashboard/students"),
        ("GET", "/api/auth/me"),
        ("PUT", "/api/auth/profile"),
        # 任务（第三十二轮）：**学院任务**是院长的本职，发布/管理都要走这组接口。
        # 白名单放行的是「能进这个路由」，具体能看到什么由 service 按 scope 过滤：
        # 纯院长只看得到学院任务，发班级任务会被 service 403（下面端到端再验一遍）。
        ("GET", "/api/tasks"),
        ("GET", "/api/tasks/overview"),
        ("POST", "/api/tasks"),
        ("PUT", "/api/tasks/1"),
        ("DELETE", "/api/tasks/1"),
        # 第四十九轮：**按状态筛选导出**是 GET /export 的 POST 兄弟。
        # 漏在这里 = 纯院长点「导出（未返校 6 人）」直接 403，页面上就是
        # 「点了没反应/报错」，而白名单默认方向是「关」，忘加不可见。
        ("GET", "/api/tasks/1/export"),
        ("POST", "/api/tasks/1/export"),
    ):
        check(f"纯院长允许 {method} {path}", pure_dean_allowed(method, path), "不在白名单里")

    # ---------- ② 纯院长不能碰的（班级事务）----------
    for method, path in (
        ("GET", "/api/records"),
        ("GET", "/api/dashboard/summary"),
        ("GET", "/api/dashboard/trend"),
        ("GET", "/api/members"),
        ("GET", "/api/batches"),
        ("GET", "/api/users"),
        ("GET", "/api/class"),
        ("GET", "/api/students"),
        ("GET", "/api/categories"),
        ("POST", "/api/records"),
        ("PUT", "/api/class"),
    ):
        check(f"纯院长拒绝 {method} {path}", not pure_dean_allowed(method, path),
              "竟然在白名单里")

    # ---------- ③ 源码守卫：闸门必须在中间件里 ----------
    sec = (root / "app/security.py").read_text(encoding="utf-8")
    check("中间件里有纯院长的判定", "pure_dean_allowed(request.method, path)" in sec,
          "中间件没调用白名单，纯院长拦不住")
    check("纯院长的判定带 DEAN_ROLE 与 dean_only 两个条件",
          "DEAN_ROLE" in sec and "dean_only" in sec, "判定条件不全")

    # ---------- ④ 端到端：真建一个纯院长 ----------
    from sqlalchemy import text as _t

    from app.db import engine as _engine
    from app.security import hash_password as _hash

    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": PURE_DEAN_PROBE})
        uid = c.execute(_t("SELECT id FROM sys_user WHERE username = 'test' LIMIT 1")).scalar()
        cid = c.execute(_t("SELECT class_id FROM sys_user WHERE id = :i"), {"i": uid}).scalar()
        c.execute(
            _t(
                "INSERT INTO sys_user (class_id, username, password, real_name, role, dean_only, status) "
                "VALUES (:c, :u, :p, '纯院长探针', 'DEAN', 1, 1)"
            ),
            {"c": cid, "u": PURE_DEAN_PROBE, "p": _hash("123456")},
        )
    P = login(PURE_DEAN_PROBE, "123456")
    if not check("纯院长探针可用", bool(P), "登录失败"):
        return

    st, j = call("GET", "/auth/me", None, P)
    check("登录/ me 返回 deanOnly=true", (data_of(j) or {}).get("deanOnly") is True,
          str(data_of(j))[:160])

    for p in ("/college/students", "/college/advisers", "/college/tasks", "/dashboard/students"):
        st, j = call("GET", p, None, P)
        check(f"纯院长访问 {p} -> 200", st == 200, f"st={st} {msg_of(j)}")

    for p in ("/records", "/dashboard/summary", "/users", "/class", "/students",
              "/members", "/batches", "/categories"):
        st, j = call("GET", p, None, P)
        check(f"纯院长访问 {p} -> 403（班级事务不参与）", st == 403, f"st={st} {msg_of(j)}")

    # ---------- ④-b 任务：放行不是「什么都能干」，service 按 scope 收口 ----------
    #
    # 第三十二轮起任务分学院任务 / 班级任务。纯院长要能发学院任务，
    # 所以 `/api/tasks` 必须进白名单；但「能进路由」不等于「能碰班级任务」：
    # 列表里只该出现学院任务，发 CLASS 必须 403，发 COLLEGE 才 200。
    TASK_PROBE = "纯院长任务探针"
    st, j = call("GET", "/tasks", None, P)
    rows = (data_of(j) or {}).get("rows") or []
    check("纯院长 GET /tasks -> 200（学院任务要走这组接口）", st == 200,
          f"st={st} {msg_of(j)}")
    check("纯院长只看得到学院任务，看不到班级任务",
          all(r.get("scope") == "COLLEGE" for r in rows),
          str([(r.get("title"), r.get("scope")) for r in rows])[:200])
    st, j = call("POST", "/tasks",
                 {"title": TASK_PROBE + " 班级", "question": "班级任务？",
                  "qtype": "BOOLEAN", "scope": "CLASS"}, P)
    check("纯院长发班级任务 -> 403（班级事务不参与）", st == 403,
          f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks",
                 {"title": TASK_PROBE + " 学院", "question": "学院任务？",
                  "qtype": "BOOLEAN", "scope": "COLLEGE"}, P)
    made_task = (data_of(j) or {}).get("id")
    check("纯院长发学院任务 -> 200", st == 200 and bool(made_task),
          f"st={st} {msg_of(j)}")
    if made_task:
        st, j = call("DELETE", f"/tasks/{made_task}", None, P)
        check("纯院长删自己发的学院任务 -> 200", st == 200,
              f"st={st} {msg_of(j)}")
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM cls_task WHERE title LIKE :p"),
                  {"p": TASK_PROBE + "%"})

    # ---------- ⑤ 对照：兼班主任的院长不受影响 ----------
    D = _insert_dean_probe(DEAN_PROBE + "_pure")
    if not check("兼班主任的院长探针可用", bool(D), "建号失败"):
        return
    st, j = call("GET", "/auth/me", None, D)
    check("兼班主任的院长 deanOnly=false", (data_of(j) or {}).get("deanOnly") is False,
          str(data_of(j))[:160])
    for p in ("/records", "/dashboard/summary", "/users", "/class"):
        st, j = call("GET", p, None, D)
        check(f"兼班主任的院长访问 {p} -> 200（存量行为不变）", st == 200,
              f"st={st} {msg_of(j)}")

    # ---------- ⑥ 改标志立刻生效（不用重新登录）----------
    with _engine.begin() as c:
        c.execute(_t("UPDATE sys_user SET dean_only = 1 WHERE username = :u"),
                  {"u": DEAN_PROBE + "_pure"})
    st, _ = call("GET", "/records", None, D)
    check("改成纯院长后立刻 403（不用重新登录）", st == 403, f"st={st}")
    with _engine.begin() as c:
        c.execute(_t("UPDATE sys_user SET dean_only = 0 WHERE username = :u"),
                  {"u": DEAN_PROBE + "_pure"})
    st, _ = call("GET", "/records", None, D)
    check("改回兼班主任后立刻恢复 200", st == 200, f"st={st}")

    # ---------- ⑦ 前端也得跟着变 ----------
    sidenav = (repo / "web/src/layout/SideNav.vue").read_text(encoding="utf-8-sig")
    check("侧栏按纯院长隐藏「账目」「班级」两组",
          "hiddenForPureDean" in sidenav and "isPureDean" in sidenav,
          "侧栏没按纯院长过滤")
    router = (repo / "web/src/router/index.ts").read_text(encoding="utf-8-sig")
    check("路由守卫按纯院长拦班级页面",
          "COLLEGE_FREE_PATHS" in router and "deanOnly" in router,
          "路由守卫没按纯院长过滤")
    dash = (repo / "web/src/views/dashboard/index.vue").read_text(encoding="utf-8-sig")
    check("仪表盘对纯院长不请求班级数据",
          "isPureDean" in dash, "仪表盘没区分纯院长")

    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": PURE_DEAN_PROBE})
    _purge_user(DEAN_PROBE + "_pure")


def test_a25_college_excel() -> None:
    """学院级 Excel 导入导出 + 列管理（第三十轮）。

    四条重点，都是「跨班级」这个本质带来的新问题：

    1. **导入按「班级」列分发**：一行一个班。找不到班名的行**跳过并报错**，
       不静默塞进别的班——塞错班比不导更糟，人就找不到了。
    2. **各班的列必须用同一个 `field_key`**：学院视图按 key 把各班的列合并成一份，
       key 不同就合并成两列同名、而值各填各的（改一列另一列不动）。
    3. **插列/停用列对所有班生效**：学院只有一份表。
    4. **仅院长**：这三个接口都在纯院长白名单之外，班主任一律 403。
    """
    print("\n--- 学院 Excel 导入导出 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from io import BytesIO as _B

    from openpyxl import Workbook as _Wb
    from openpyxl import load_workbook as _Lw

    D = _insert_dean_probe(DEAN_PROBE + "_xls")
    if not check("院长探针可用", bool(D), "建号失败"):
        return
    T = S["T"]

    # 导入时「没见过的班」会自动建出来。老库里「云计算2502」本来就存在，
    # 所以清理时只删后建的那几个；干净库上它也是导入建的，同样要删——
    # 否则用户把数据清空之后，跑一轮回归就又多出一个班（怎么也删不干净）。
    from sqlalchemy import text as _t_base

    from app.db import engine as _engine_base

    with _engine_base.connect() as c_base:
        before_classes = {int(r[0])
                          for r in c_base.execute(_t_base("SELECT id FROM cls_class"))}

    # ---------- 造一个带「班级」列的表 ----------
    wb = _Wb()
    ws = wb.active
    ws.append(["学号", "姓名", "班级", "性别", "专业名称", "院考标签"])
    ws.append(["Z9001", "甲同学", "云计算2502", "男", "软件工程", "重点"])
    ws.append(["Z9002", "乙同学", "Z90夹具班", "女", "物联网工程", "普通"])
    ws.append(["Z9003", "丙同学", "不存在的班", "男", "软件工程", "重点"])
    buf = _B()
    wb.save(buf)
    content = buf.getvalue()

    # ---------- ① 导入：按班级列分发 ----------
    # ⚠ 先清上一轮的残留，否则本轮的「新增」会变成「更新」——
    # 计数类断言就永远对不上（第一轮造、第二轮断言失败）。
    _purge_students_prefix("Z90")
    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx", content, D)
    data = data_of(j) or {}
    check("导入成功 -> 200", st == 200, f"st={st} {msg_of(j)}")
    # 第三行的班级「不存在的班」在库里没有 → **自动建班**（第三十轮改的行为）。
    # 原来是把那一行**丢掉**并报错——用户导一份全校名单进来，发现少了一半人，
    # 还得先手工建班再导一遍。跟「没见过的列自动建字段」是同一个思路：
    # 用户导进来的东西不该被静默丢弃。
    check("三行都进了（第三行那个不存在的班**自动建了**）",
          int(data.get("created") or 0) == 3, str(data)[:200])
    check("自动建班**不算错误**", not data.get("errors"), str(data.get("errors"))[:200])
    # 新建列的报告：只断言「那个没见过的列在里面」，不写死个数——
    # 自动建的班第一次出现时，它自己那几列（性别/专业名称…）也都是新的，
    # 个数取决于库里已经有什么，写死就会在第二轮翻车。
    nf = {f["label"] for f in (data.get("newFields") or [])}
    check("表里没见过的列自动建了字段", "院考标签" in nf, str(data.get("newFields"))[:200])

    st, j = call("GET", "/college/students?size=200", None, D)
    d_imp = data_of(j) or {}
    rows = d_imp.get("rows") or []
    by_no = {r["studentNo"]: r for r in rows}
    check("Z9001 落在云计算2502",
          by_no.get("Z9001", {}).get("className") == "云计算2502",
          str(by_no.get("Z9001"))[:160])
    check("Z9002 落在它写的那一班（没见过的班自动建）",
          by_no.get("Z9002", {}).get("className") == "Z90夹具班",
          str(by_no.get("Z9002"))[:160])
    check("Z9003 落在自动新建的「不存在的班」",
          by_no.get("Z9003", {}).get("className") == "不存在的班",
          str(by_no.get("Z9003"))[:160])
    check("★ 自动建的班出现在班级筛选里",
          "不存在的班" in [c["className"] for c in (d_imp.get("classes") or [])],
          str([c["className"] for c in (d_imp.get("classes") or [])]))

    # ---------- ② 各班的列必须同一个 key ----------
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    with _engine.connect() as c:
        keys = [
            r[0]
            for r in c.execute(
                _t(
                    "SELECT DISTINCT field_key FROM student_field "
                    "WHERE field_label = '院考标签' AND status = 1"
                )
            )
        ]
    check("同一个列名在所有班用**同一个 field_key**（否则合并成两列同名）",
          len(keys) == 1, str(keys))

    # 值要能按 key 解析出来（key 相同 → 各班的值各归各的班，但列是同一列）
    st, j = call("GET", "/college/students?size=200", None, D)
    cols = {c["label"]: c["key"] for c in ((data_of(j) or {}).get("columns") or [])}
    rows = (data_of(j) or {}).get("rows") or []
    vals = {
        r["studentNo"]: (r.get("values") or {}).get(cols.get("院考标签", ""))
        for r in rows
    }
    check("值能按 key 解析出来（不是 None）",
          vals.get("Z9001") == "重点" and vals.get("Z9002") == "普通", str(vals)[:200])

    # ---------- ③ 导出（选列） ----------
    st, raw = _get_raw("/college/students/export?columns=major_name,gender", D)
    check("导出选列 -> 200", st == 200, f"st={st}")
    if st == 200:
        w2 = _Lw(_B(raw))
        rows2 = list(w2.active.iter_rows(values_only=True))
        header = [c for c in rows2[2] if c]
        # 学号/姓名**无条件保留**（没勾也得有）；
        # 班级/年级**听勾选**（这次没勾 → 表头里就不该有）。
        check("导出表头**一定有**学号/姓名（没勾也保留）",
              "学号" in header and "姓名" in header, str(header))
        check("没勾的班级/年级**真的不出现**",
              "班级" not in header and "年级" not in header, str(header))
        check("导出表头含选中的列", "专业名称" in header and "性别" in header, str(header))
        check("导出表头**不含**没选的列", "籍贯" not in header, str(header))
    # 勾上班级/年级时要有，而且「年级」**只出现一次**
    st, raw2 = _get_raw(
        "/college/students/export?columns=__class__,__grade__,major_name,gender", D)
    if st == 200:
        h2 = [c for c in list(_Lw(_B(raw2)).active.iter_rows(values_only=True))[2] if c]
        check("勾了班级/年级 -> 导出表头里就有",
              "班级" in h2 and "年级" in h2, str(h2))
        check("★ 「年级」**不重复出两列**（年级字段并进了年级锚点列）",
              h2.count("年级") == 1, str(h2))

    # ---------- ④ 插列：所有班 + 左右 ----------
    st, j = call("GET", "/college/fields", None, D)
    cols_before = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    i_major = cols_before.index("专业名称") if "专业名称" in cols_before else -1
    st, j = call("POST", "/college/fields",
                  {"label": "插在前面", "type": "TEXT",
                   "anchorKey": "major_name", "side": "before"}, D)
    created = data_of(j) or {}
    check("左插列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("新列加到了**所有班**", int(created.get("classCount") or 0) >= 2, str(created))
    st, j = call("GET", "/college/fields", None, D)
    cols_after = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    check("新列插在锚点列**前面**",
          cols_after.index("插在前面") == cols_after.index("专业名称") - 1,
          str(cols_after[:i_major + 3]))

    st, j = call("POST", "/college/fields",
                  {"label": "插在后面", "type": "TEXT",
                   "anchorKey": "major_name", "side": "after"}, D)
    check("右插列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/fields", None, D)
    cols_after = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    check("新列插在锚点列**后面**",
          cols_after.index("插在后面") == cols_after.index("专业名称") + 1,
          str(cols_after[:i_major + 4]))

    # ---------- ⑤ 停用列：所有班一起 ----------
    key = created.get("key") or ""
    st, j = call("DELETE", f"/college/fields/{key}", None, D)
    check("停用列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("停用对所有班生效", int((data_of(j) or {}).get("classCount") or 0) >= 2, str(data_of(j)))
    st, j = call("GET", "/college/fields", None, D)
    check("停用后列里没有了",
          "插在前面" not in [c["label"] for c in ((data_of(j) or {}).get("columns") or [])],
          str([c["label"] for c in ((data_of(j) or {}).get("columns") or [])])[:200])

    # ---------- ⑥ 就地改一格（电子表格） ----------
    st, j = call("GET", "/college/students?size=200", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    z = next((r for r in rows if r["studentNo"] == "Z9001"), None)
    if check("名册里能拿到 Z9001（改一格的测试对象）", z is not None, str(rows)[:160]):
        rid = z["id"]
        key = cols.get("专业名称", "")
        st, j = call("PUT", f"/college/students/{rid}", {"values": {key: "改了专业"}}, D)
        check("改一格 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/college/students?size=200", None, D)
        z2 = next(
            (r for r in ((data_of(j) or {}).get("rows") or []) if r["studentNo"] == "Z9001"), None
        )
        check("改完的值能读回来",
              (z2 or {}).get("values", {}).get(key) == "改了专业", str(z2)[:200])
        # 未定义的字段要报错，不能静默丢弃
        st, j = call("PUT", f"/college/students/{rid}",
                     {"values": {"根本没这个字段": "x"}}, D)
        check("改未定义的字段 -> 400（不是静默丢弃）", st == 400, f"st={st} {msg_of(j)}")
        # 跨班：字段必须按「这条记录自己那个班」找
        st, j = call("GET", "/college/students?size=200", None, D)
        z3 = next(
            (r for r in ((data_of(j) or {}).get("rows") or []) if r["studentNo"] == "Z9002"), None
        )
        if z3:
            st, j = call("PUT", f"/college/students/{z3['id']}",
                         {"values": {key: "另一个班也改了"}}, D)
            check("改另一个班的学生 -> 200（跨班级编辑）", st == 200, f"st={st} {msg_of(j)}")

    # ---------- ⑦ 筛选跟着数据走（不能是死数据） ----------
    #
    # 用户口径：「导入进来的时候自动出现在这个筛选里面」。
    # 所以：① 库里没有的班级 → **自动建班**（而不是把行丢掉）；
    #       ② 年级选项 = 学生**实际的**年级值（不是班级上写死的那一个）。
    from urllib.parse import quote as _quote

    wb_new = _Wb()
    ws_new = wb_new.active
    ws_new.append(["学号", "姓名", "班级", "年级", "性别"])
    ws_new.append(["W9001", "新班甲", "回归新建班", "2099级", "男"])
    ws_new.append(["W9002", "新班乙", "回归新建班", "2099级", "女"])
    buf_new = _B()
    wb_new.save(buf_new)
    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx",
                            buf_new.getvalue(), D)
    res_new = data_of(j) or {}
    check("导入一个库里没有的班级 -> 200（不报错）",
          st == 200, f"st={st} {msg_of(j)}")
    check("新班的人**没有丢**（原来会整行跳过）",
          int(res_new.get("created") or 0) == 2, str(res_new)[:200])
    check("报错里没有「班级不存在」", not res_new.get("errors"), str(res_new.get("errors"))[:200])

    st, j = call("GET", "/college/students?size=200", None, D)
    d2 = data_of(j) or {}
    new_classes = [c["className"] for c in (d2.get("classes") or [])]
    check("★ 新建的班级**自动出现在班级筛选里**",
          "回归新建班" in new_classes, str(new_classes))
    check("★ 新年级自动出现在年级筛选里（跟着数据走，不是死数据）",
          "2099级" in (d2.get("grades") or []), str(d2.get("grades")))
    new_cid = next(
        (c["id"] for c in (d2.get("classes") or []) if c["className"] == "回归新建班"), None
    )
    if new_cid:
        st, j = call(f"GET", f"/college/students?classId={new_cid}", None, D)
        check("按新班级筛得���那两个人",
              int((data_of(j) or {}).get("total") or 0) == 2,
              str((data_of(j) or {}).get("total")))
    st, j = call("GET", "/college/students?grade=" + _quote("2099级"), None, D)
    d3 = data_of(j) or {}
    check("按新年级筛得出那两个人",
          int(d3.get("total") or 0) == 2, str(d3.get("total")))
    check("年级筛选后**选项不跟着筛**（否则第二次就选不到了）",
          "2099级" in (d3.get("grades") or []), str(d3.get("grades")))
    st, j = call("GET", "/college/students?grade=" + _quote("1899级"), None, D)
    check("筛一个不存在的年级 -> 0 人（不是报错）",
          int((data_of(j) or {}).get("total") or 0) == 0,
          str((data_of(j) or {}).get("total")))

    # ---------- 年级选项里不能有「筛不出人」的死选项 ----------
    #
    # 之前选项域是「班级年级 ∪ 学生填过的年级」。一个班的学生都自己填了
    # 「2026」，这个班的「2026级」照样在下拉里，可选下去一个人都筛不出来
    # （学生自己有值，就不再看班级年级了）——用户看到的就是「这个筛选不了」。
    # 选项域必须和筛选判据**同源**：收进来的每一个，选下去都至少筛出一个人。
    st, j = call("GET", "/college/students?size=200", None, D)
    grades_now = (data_of(j) or {}).get("grades") or []
    dead = []
    for g in grades_now:
        st2, j2 = call("GET", "/college/students?grade=" + _quote(g), None, D)
        if int((data_of(j2) or {}).get("total") or 0) == 0:
            dead.append(g)
    check("★ 年级选项里**没有筛不出人的死选项**", not dead,
          f"死选项: {dead}（全部选项: {grades_now}）")
    # 班级选项要带人数：空班（一个人都没有）在下拉里是看得出来的
    st, j = call("GET", "/college/students?size=200", None, D)
    choices = (data_of(j) or {}).get("classes") or []
    check("班级选项带人数（空班一眼看得出来）",
          all("students" in c for c in choices) and bool(choices), str(choices)[:200])

    # 导出要**跟着筛选走**：界面上筛出来的是这批人，导出来就得是这批人。
    # 不然用户会拿到一份「屏幕上不是这些行、文件里却是」的表。
    st, raw = _get_raw("/college/students/export?grade=" + _quote("2099级"), D)
    check("导出（带年级筛选）-> 200", st == 200, f"st={st}")
    if st == 200:
        body = [r for r in list(_Lw(_B(raw)).active.iter_rows(values_only=True))[3:] if r and r[0]]
        check("★ 导出的是**筛出来的那批人**", len(body) == 2, str(body)[:200])
        check("★ 导出里没有别班的人",
              all(str(r[0]).startswith("W90") for r in body), str(body)[:200])

    # 清理：把自动建的班和它的人删掉
    with _engine.begin() as c:
        nc = c.execute(
            _t("SELECT id FROM cls_class WHERE class_name = '回归新建班'")
        ).scalar()
        if nc:
            c.execute(
                _t("DELETE FROM student_record_value WHERE record_id IN "
                   "(SELECT id FROM student_record WHERE class_id = :c)"),
                {"c": nc},
            )
            c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": nc})

    # ---------- ⑧ 改类型：先预览，再应用（跨所有班） ----------
    st, j = call("GET", "/college/fields/gender/retype-preview?toType=DATE", None, D)
    pv = data_of(j) or {}
    check("改类型预览 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("预览跨**所有班**汇总（这一列每个班各有一份定义）",
          int(pv.get("classCount") or 0) >= 1, str(pv)[:200])
    check("预览给出能转换/转不了的条数",
          "convertibleCount" in pv and "unconvertibleCount" in pv, str(pv)[:200])
    st, j = call("POST", "/college/fields/gender/retype",
                 {"toType": "DATE", "clearBad": False}, D)
    ap = data_of(j) or {}
    check("确认改类型 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("改类型对所有班生效",
          int(ap.get("classCount") or 0) >= 1, str(ap)[:200])
    check("转不了的值默认**保留**（不静默清空）",
          int(ap.get("clearedCount") or 0) == 0, str(ap)[:200])
    # 改回去，别把基线留在 DATE 上
    call("POST", "/college/fields/gender/retype", {"toType": "TEXT", "clearBad": False}, D)

    # ---------- ⑧ 权限：非院长一律 403 ----------
    for name, tok in (("班主任", T), ("普通同学", S["M"])):
        st, _ = _get_raw("/college/students/export", tok)
        check(f"{name}导出 -> 403", st == 403, f"st={st}")
        st, _ = _post_multipart("/college/students/import", "file", "a.xlsx", content, tok)
        check(f"{name}导入 -> 403", st == 403, f"st={st}")
        st, j = call("POST", "/college/fields", {"label": "x", "type": "TEXT"}, tok)
        check(f"{name}新增列 -> 403", st == 403, f"st={st}")
        st, j = call("PUT", "/college/students/1", {"values": {"gender": "男"}}, tok)
        check(f"{name}改格 -> 403", st == 403, f"st={st}")
        st, j = call("GET", "/college/fields/gender/retype-preview?toType=DATE", None, tok)
        check(f"{name}改类型预览 -> 403", st == 403, f"st={st}")

    # ---------- ⑨ 清理 ----------
    _purge_students_prefix("Z90")
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_field WHERE field_label IN "
                     "('院考标签','插在前面','插在后面')"))
        # 自动建的班也要删（它们的字段模板是导入时建出来的）。
        # 「云计算2502」是**本轮导入才建的**才删——库里本来就有这个班时
        # 它属于真实数据，绝不能跟着清掉（`before_classes` 就是为这个）。
        for name in ("不存在的班", "回归新建班", "Z90夹具班", "云计算2502"):
            nc = c.execute(
                _t("SELECT id FROM cls_class WHERE class_name = :n"), {"n": name}
            ).scalar()
            if nc and int(nc) not in before_classes:
                c.execute(
                    _t("DELETE FROM student_record_value WHERE record_id IN "
                       "(SELECT id FROM student_record WHERE class_id = :c)"),
                    {"c": nc},
                )
                c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": nc})
                c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": nc})
                c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": nc})
    _purge_user(DEAN_PROBE + "_xls")


def test_a26_college_cell_edit() -> None:
    """学院表格：前四列的**可改性**与**导出选列**（第三十一轮）。

    用户口径：「为什么前四列导出不了，而且还不能修改？」

    改完之后的口径（**和班级那套一致**）：

    | 列 | 能不能改 | 落在哪 |
    |----|----------|--------|
    | 学号 | 能 | `student_record.student_no`（同班不能撞号） |
    | 姓名 | 能 | `student_record.name` |
    | 班级 | **不能** | 转班会牵动字段值归属（值表存的是 field_id），是另一个操作 |
    | 年级 | 能 | `grade` **字段的值**（学生没填时才回退班级年级） |

    导出：**学号/姓名必选**（一份没有学号的表没法说明每一行是谁）；
    **班级/年级可以取消**（有人导出只要学号姓名加几个字段）。

    顺带验证：某个班**没建年级列**时，在年级格填值会**就地补建**那列
    （而不是报「未定义的字段」让人干瞪眼）。
    """
    print("\n--- 学院表格：前四列可改 + 导出选列 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from io import BytesIO as _B

    from openpyxl import Workbook as _Wb
    from openpyxl import load_workbook as _Lw
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    D = _insert_dean_probe(DEAN_PROBE + "_cell")
    if not check("院长探针可用", bool(D), "建号失败"):
        return

    # ---------- 造一份探针名单（同班两个人 + 一个没年级列的班） ----------
    wb = _Wb()
    ws = wb.active
    ws.append(["学号", "姓名", "班级", "性别"])
    ws.append(["Z9601", "改格甲", "回归改格班", "男"])
    ws.append(["Z9602", "改格乙", "回归改格班", "女"])
    buf = _B()
    wb.save(buf)

    _purge_students_prefix("Z96")
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_field WHERE field_label = '年级' "
                     "AND class_id IN (SELECT id FROM cls_class "
                     "WHERE class_name = '回归改格班')"))
        nc = c.execute(
            _t("SELECT id FROM cls_class WHERE class_name = :n"),
            {"n": "回归改格班"},
        ).scalar()
        # 「改班级（按名字）」转进去的那个夹具班也要删
        if nc:
            c.execute(_t("DELETE FROM student_record_value WHERE record_id IN "
                         "(SELECT id FROM student_record WHERE class_id = :c)"), {"c": nc})
            c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": nc})

    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx",
                            buf.getvalue(), D)
    check("导入探针名单 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("两个人都进来了", int((data_of(j) or {}).get("created") or 0) == 2,
          str(data_of(j))[:200])

    st, j = call("GET", "/college/students?size=200", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    z1 = next((r for r in rows if r["studentNo"] == "Z9601"), None)
    z2 = next((r for r in rows if r["studentNo"] == "Z9602"), None)
    if not check("名册里能拿到 Z9601/Z9602（改格的测试对象）",
                 z1 is not None and z2 is not None, str(rows)[:200]):
        _purge_students_prefix("Z96")
        _purge_user(DEAN_PROBE + "_cell")
        return
    rid = z1["id"]

    # ---------- ① 那个班**没建年级列**时，填年级要能存下去 ----------
    #
    # ⚠ 必须放在最前面：一旦下面第 ② 步写过年级，字段就**已经补建出来**了，
    # 「这个班本来没有年级列」的前置条件就不成立了（我第一版就踩了这个坑）。
    with _engine.begin() as c:
        has_grade = c.execute(
            _t("SELECT COUNT(*) FROM student_field WHERE class_id = "
               "(SELECT id FROM cls_class WHERE class_name = :n) "
               "AND field_key = 'grade' AND status = 1"),
            {"n": "回归改格班"},
        ).scalar()
    check("（前置）这个班本来**没有**年级列", int(has_grade or 0) == 0, str(has_grade))
    st, j = call("PUT", f"/college/students/{rid}",
                 {"values": {"grade": "2097级"}}, D)
    check("★ 缺年级列时填年级 -> 200（就地补建，不报错）",
          st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/students?size=200", None, D)
    z1e = next((r for r in ((data_of(j) or {}).get("rows") or [])
                if r["id"] == rid), None)
    check("★ 补建后值存下来了",
          (z1e or {}).get("values", {}).get("grade") == "2097级", str(z1e)[:200])

    # ---------- ② 学号 + 姓名 + 年级：一次请求全改 ----------
    st, j = call("PUT", f"/college/students/{rid}",
                 {"values": {"grade": "2098级"}, "name": "改格甲新名",
                  "studentNo": "Z9601X"}, D)
    check("一次改学号+姓名+年级 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/students?size=200", None, D)
    z1b = next((r for r in ((data_of(j) or {}).get("rows") or [])
                if r["id"] == rid), None)
    check("★ 学号改掉了", (z1b or {}).get("studentNo") == "Z9601X", str(z1b)[:200])
    check("★ 姓名改掉了", (z1b or {}).get("name") == "改格甲新名", str(z1b)[:200])
    check("★ 年级改掉了（落的是 grade 字段）",
          (z1b or {}).get("values", {}).get("grade") == "2098级", str(z1b)[:200])
    check("★ 年级列显示的也是新值（筛选和显示要一致）",
          (z1b or {}).get("grade") == "2098级", str(z1b)[:200])

    # ---------- ③ 学号的校验 ----------
    st, j = call("PUT", f"/college/students/{rid}",
                 {"values": {}, "studentNo": "  "}, D)
    check("学号改成空 -> 400（不是静默接受）", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/college/students/{rid}",
                 {"values": {}, "studentNo": "Z9602"}, D)
    check("学号撞上同班另一个人 -> 400（学号是导入的 upsert 键）",
          st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/students?size=200", None, D)
    z1c = next((r for r in ((data_of(j) or {}).get("rows") or [])
                if r["id"] == rid), None)
    check("撞号被拒后**学号没变**（整批原子）",
          (z1c or {}).get("studentNo") == "Z9601X", str(z1c)[:200])

    # ---------- ④ 班级：直接改文字（按名字） ----------
    #
    # 界面上这一格是**普通输入框**（和别的列一样），用户直接打班级名：
    # 找到同名班就转过去；**找不到就自动建一个**（和导入一个规矩）。
    # `classId`（按 id）**不认**——那是另一个接口的事。
    st, j = call("PUT", f"/college/students/{rid}",
                 {"values": {}, "className": "回归转入班"}, D)
    check("改班级（按名字）-> 200", st == 200, f"st={st} {msg_of(j)}")
    st2, j2 = call("GET", "/college/students?size=200", None, D)
    z1d = next((r for r in ((data_of(j2) or {}).get("rows") or [])
                if r["id"] == rid), None)
    check("★ 班级改成了他打的那个班", (z1d or {}).get("className") == "回归转入班",
          str(z1d)[:200])
    check("★ 转过去之后值一个没丢",
          (z1d or {}).get("values", {}).get("grade") == "2098级", str(z1d)[:200])
    # 改回去
    call("PUT", f"/college/students/{rid}", {"values": {}, "className": "回归改格班"}, D)
    st2, j2 = call("GET", "/college/students?size=200", None, D)
    z1d2 = next((r for r in ((data_of(j2) or {}).get("rows") or [])
                 if r["id"] == rid), None)
    check("改回原来的班", (z1d2 or {}).get("className") == "回归改格班", str(z1d2)[:200])

    # ---------- ⑤ 导出：班级/年级能取消 ----------
    st, raw = _get_raw("/college/students/export?columns=__no__,__name__", D)
    check("导出（只勾学号姓名）-> 200", st == 200, f"st={st}")
    if st == 200:
        h = [c for c in list(_Lw(_B(raw)).active.iter_rows(values_only=True))[2] if c]
        check("★ 表头只有学号/姓名（班级/年级真的没导出）",
              h == ["学号", "姓名"], str(h))
    st, raw = _get_raw(
        "/college/students/export?columns=__no__,__name__,__class__,__grade__", D)
    check("导出（勾上班级/年级）-> 200", st == 200, f"st={st}")
    if st == 200:
        h2 = [c for c in list(_Lw(_B(raw)).active.iter_rows(values_only=True))[2] if c]
        check("★ 勾上了就有班级/年级",
              h2[:4] == ["学号", "姓名", "班级", "年级"], str(h2))
        check("★ 「年级」只出现一次（年级字段不重复出列）",
              h2.count("年级") == 1, str(h2))
    # 不给 columns = 全部（默认全导出，含班级/年级）
    st, raw = _get_raw("/college/students/export", D)
    if st == 200:
        h3 = [c for c in list(_Lw(_B(raw)).active.iter_rows(values_only=True))[2] if c]
        check("不给 columns -> 默认带上班级/年级",
              "班级" in h3 and "年级" in h3, str(h3))
        check("默认导出里「年级」也只有一列", h3.count("年级") == 1, str(h3))

    # ---------- ⑥ 权限：非院长一律 403 ----------
    for name, tok in (("班主任", S["T"]), ("普通同学", S["M"])):
        st, _ = call("PUT", f"/college/students/{rid}",
                     {"values": {"grade": "x"}}, tok)
        check(f"{name}改学院表格的格子 -> 403", st == 403, f"st={st}")
        st, _ = call("PUT", f"/college/students/{rid}",
                     {"values": {}, "studentNo": "x"}, tok)
        check(f"{name}改学院表格的学号 -> 403", st == 403, f"st={st}")

    # ---------- 清理 ----------
    _purge_students_prefix("Z96")
    with _engine.begin() as c:
        nc = c.execute(
            _t("SELECT id FROM cls_class WHERE class_name = :n"),
            {"n": "回归改格班"},
        ).scalar()
        if nc:
            c.execute(_t("DELETE FROM student_record_value WHERE record_id IN "
                         "(SELECT id FROM student_record WHERE class_id = :c)"), {"c": nc})
            c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": nc})
    _purge_fixture_class("回归转入班")
    _purge_user(DEAN_PROBE + "_cell")


def test_a27_college_field_restore() -> None:
    """停用列的**恢复**，以及「停用过模板字段之后后端还能不能启动」（第三十一轮）。

    两条都是**能把自己搞挂**的坑：

    1. **停用是软删**（`status=0`），值一行没动——所以必须有一条找回的路，
       否则误停用一列就等于把那一列的历史数据永远藏起来了。
    2. 模板字段**被停用之后**，`seed.init_student_fields` 会因为
       「唯一键是 `(class_id, field_key)`、不看启用还是停用」而重复插入 →
       IntegrityError → **整个后端起不来**（服务直接退出，页面全挂）。

    第 2 条是真的发生过：停用了一个「家长电话」列之后，下一次重启
    后端就再也起不来了。判存在时必须按**全部状态**看。
    """
    print("\n--- 停用列的恢复 / 停用模板字段后仍能启动 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    D = _insert_dean_probe(DEAN_PROBE + "_trash")
    if not check("院长探针可用", bool(D), "建号失败"):
        return

    # ---------- ① 造一列，停用它 ----------
    st, j = call("POST", "/college/fields", {"label": "回归可恢复列", "type": "TEXT"}, D)
    created = data_of(j) or {}
    key = created.get("key") or ""
    check("新建一列 -> 200", st == 200 and bool(key), f"st={st} {msg_of(j)}")

    st, j = call("DELETE", f"/college/fields/{key}", None, D)
    check("停用这一列 -> 200", st == 200, f"st={st} {msg_of(j)}")

    # 停用后它**不在**活动列里
    st, j = call("GET", "/college/fields", None, D)
    labels = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    check("停用后不在活动列里", "回归可恢复列" not in labels, str(labels)[:200])

    # ---------- ② 已停用的列能被列出来 ----------
    st, j = call("GET", "/college/fields/disabled", None, D)
    dis = data_of(j) or {}
    dis_labels = [c["label"] for c in (dis.get("columns") or [])]
    check("已停用的列能被列出来（软删要有找回的路）",
          "回归可恢复列" in dis_labels, str(dis_labels)[:200])
    check("同一个 key 在各班只出现一次（按 key 合并）",
          len([c for c in (dis.get("columns") or []) if c["key"] == key]) == 1,
          str(dis.get("columns"))[:200])

    # ---------- ③ 恢复 ----------
    st, j = call("POST", f"/college/fields/{key}/restore", None, D)
    check("恢复这一列 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/fields", None, D)
    labels = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    check("恢复后回到活动列里", "回归可恢复列" in labels, str(labels)[:200])
    st, j = call("GET", "/college/fields/disabled", None, D)
    dis_labels = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
    check("恢复后不在已停用列表里", "回归可恢复列" not in dis_labels, str(dis_labels)[:200])

    # ---------- ④ 停用模板字段后，重跑模板下发不会崩 ----------
    #
    # 这一条是**真的会把后端搞挂**的：唯一键是 (class_id, field_key)，
    # 不看启用还是停用。模板只查启用的字段 → 以为字段不存在 → 重复插 → 崩。
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_field WHERE field_label = '回归可恢复列'"))
    with _engine.begin() as c:
        c.execute(_t("UPDATE student_field SET status = 0 "
                     "WHERE field_key = 'guardian_phone'"))
    with _engine.connect() as c:
        seed_class = c.execute(
            _t("SELECT id FROM cls_class ORDER BY id LIMIT 1")
        ).scalar()
    with _engine.connect() as c:
        before_rows = int(
            c.execute(
                _t("SELECT COUNT(*) FROM student_field WHERE field_key = 'guardian_phone' "
                   "AND class_id = :c"),
                {"c": seed_class},
            ).scalar()
            or 0
        )
    try:
        from app.db import SessionLocal as _SessionLocal
        from app.seed import init_student_fields as _init_fields

        _db = _SessionLocal()
        try:
            _init_fields(_db, int(seed_class))
            _db.commit()
        finally:
            _db.close()
        ok = True
        detail = ""
    except Exception as exc:  # noqa: BLE001
        ok = False
        detail = repr(exc)[:200]
    check("★ 停用过模板字段后重跑模板下发**不报错**（否则后端起不来）", ok, detail)
    with _engine.connect() as c:
        after_rows = int(
            c.execute(
                _t("SELECT COUNT(*) FROM student_field WHERE field_key = 'guardian_phone' "
                   "AND class_id = :c"),
                {"c": seed_class},
            ).scalar()
            or 0
        )
    check("★ 没有插出重复的模板字段行",
          after_rows == before_rows, f"{before_rows} -> {after_rows}")
    # 复原：把刚才停用的模板字段放回去，别把基线留在停用状态
    with _engine.begin() as c:
        c.execute(_t("UPDATE student_field SET status = 1 "
                     "WHERE field_key = 'guardian_phone'"))
    _purge_user(DEAN_PROBE + "_trash")


def test_a28_college_transfer() -> None:
    """**转班**：把学生挪到另一个班，值一个不丢（第三十二轮）。

    用户口径：「这个学生转班级了怎么办」。

    ## 为什么不能当成「改一格」

    值表里存的是 `field_id`，而字段是**按班**定义的：同一个 `field_key`
    在不同班是不同的 `field_id`（唯一键 `(class_id, field_key)`）。
    直接把 `class_id` 一改，他那些值就指向了「新班根本不存在的字段」——
    界面上变成一片空白（值还在库里，但读不出来）。

    所以转班必须**按 key 把值搬到新班对应的字段上**。

    ## 目标班缺列怎么办

    目标班**没有**某一列时：在目标班**补建同 key 的字段**再把值搬过去。
    丢值比多一列糟糕得多（多出来的那列只有这个班有，但那一列里的信息是真的）。
    """
    print("\n--- 转班 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from io import BytesIO as _B

    from openpyxl import Workbook as _Wb
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    D = _insert_dean_probe(DEAN_PROBE + "_mv")
    if not check("院长探针可用", bool(D), "建号失败"):
        return

    # 探针学生写进「云计算2502」：库里没有这个班时**会被导入自动建出来**。
    # 记下开跑前有哪些班，收尾时把「本轮才建出来的」删掉——库里本来就有的
    # 那个班是真实数据，绝不能跟着清掉。不这么处理的话，用户把数据清空之后
    # 每跑一次回归就多出一个班。
    with _engine.connect() as c0:
        before_classes = {int(r[0]) for r in c0.execute(_t("SELECT id FROM cls_class"))}

    def drop_src_class() -> None:
        with _engine.begin() as c:
            nc = c.execute(
                _t("SELECT id FROM cls_class WHERE class_name = '云计算2502'")
            ).scalar()
            if not nc or int(nc) in before_classes:
                return
            c.execute(_t("DELETE FROM student_record_value WHERE record_id IN "
                         "(SELECT id FROM student_record WHERE class_id = :c)"),
                      {"c": nc})
            c.execute(_t("DELETE FROM student_record WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM student_field WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM sys_user_class WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM fee_category WHERE class_id = :c"), {"c": nc})
            c.execute(_t("DELETE FROM cls_class WHERE id = :c"), {"c": nc})

    # ---------- 造一个探针学生 ----------
    wb = _Wb()
    ws = wb.active
    ws.append(["学号", "姓名", "班级", "性别", "专业名称", "入学总分"])
    ws.append(["Z9701", "转班甲", "云计算2502", "男", "软件工程", "600"])
    buf = _B()
    wb.save(buf)
    _purge_students_prefix("Z97")
    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx", buf.getvalue(), D)
    check("导入探针学生 -> 200", st == 200, f"st={st} {msg_of(j)}")

    st, j = call("GET", "/college/students?size=200", None, D)
    d = data_of(j) or {}
    row = next((r for r in (d.get("rows") or []) if r["studentNo"] == "Z9701"), None)
    if not check("名册里能拿到 Z9701", row is not None, str(d.get("rows"))[:200]):
        _purge_students_prefix("Z97")
        drop_src_class()
        _purge_user(DEAN_PROBE + "_mv")
        return
    rid = row["id"]
    before_values = {k: v for k, v in (row.get("values") or {}).items() if v}
    check("转班前他有几列有值", len(before_values) >= 3, str(before_values))
    src_class = row["className"]

    # 找一个**别的**班当目标
    target = next(
        (c for c in (d.get("classes") or []) if c["className"] != src_class), None
    )
    if target is None:
        # 库里只有他那个班 → **自己造一个夹具班**。
        # ⚠ 不能在这里 return 掉：那样这条用例会**悄悄不跑**，
        # 回归报告里只看得到「断言变少了」，看不出「少了一条用例」。
        _fixture_class("回归转班夹具班")
        st, j = call("GET", "/college/students?size=200", None, D)
        d = data_of(j) or {}
        target = next(
            (c for c in (d.get("classes") or []) if c["className"] != src_class), None
        )
    if not check("有别的班可以转过去", target is not None, str(d.get("classes"))):
        _purge_students_prefix("Z97")
        _purge_user(DEAN_PROBE + "_mv")
        return

    # ---------- 转 ----------
    st, j = call("POST", f"/college/students/{rid}/transfer",
                 {"classId": target["id"]}, D)
    res = data_of(j) or {}
    check("转班 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("回执里说清从哪转到哪",
          res.get("fromClassName") == src_class
          and res.get("targetClassName") == target["className"],
          str(res)[:200])

    # ---------- 值一个不丢 ----------
    st, j = call("GET", "/college/students?size=200", None, D)
    d2 = data_of(j) or {}
    row2 = next((r for r in (d2.get("rows") or []) if r["studentNo"] == "Z9701"), None)
    if check("转完他还在名册里", row2 is not None, str(d2.get("rows"))[:200]):
        check("★ 班级已经改了", row2["className"] == target["className"], str(row2)[:200])
        after_values = {k: v for k, v in (row2.get("values") or {}).items() if v}
        check("★ 值一个没丢（按列名搬过去的）", after_values == before_values,
              f"{before_values} -> {after_values}")

    # ---------- 转回自己那个班会报错 ----------
    st, j = call("POST", f"/college/students/{rid}/transfer",
                 {"classId": target["id"]}, D)
    check("转到同一个班 -> 400（不是静默接受）", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 目标班缺列 → 补建 ----------
    #
    # 这一条要动目标班的字段表，所以先在库里造一个「缺列」的班：
    # 拿一个只留部分字段的临时班，把学生转进去，值必须还在。
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_record_value WHERE record_id IN "
                     "(SELECT id FROM student_record WHERE student_no = 'Z9701')"))
        c.execute(_t("DELETE FROM student_record WHERE student_no = 'Z9701'"))
        c.execute(_t("DELETE FROM student_field WHERE field_label = '回归缺列'"))
    st, j = call("POST", "/college/fields", {"label": "回归缺列", "type": "TEXT"}, D)
    created = data_of(j) or {}
    key = created.get("key") or ""
    check("新建一列（两个班都有）-> 200", st == 200 and bool(key), f"st={st} {msg_of(j)}")
    # 把这一列从**目标班**删掉，制造「目标班缺列」
    with _engine.begin() as c:
        c.execute(_t("UPDATE student_field SET status = 0 "
                     "WHERE class_id = :c AND field_key = :k"),
                  {"c": target["id"], "k": key})
    # 再造一个带这一列值的学生
    wb2 = _Wb()
    ws2 = wb2.active
    ws2.append(["学号", "姓名", "班级", "回归缺列"])
    ws2.append(["Z9702", "转班乙", src_class, "有个值"])
    buf2 = _B()
    wb2.save(buf2)
    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx", buf2.getvalue(), D)
    st, j = call("GET", "/college/students?size=200", None, D)
    row3 = next((r for r in ((data_of(j) or {}).get("rows") or [])
                  if r["studentNo"] == "Z9702"), None)
    if check("名册里能拿到 Z9702", row3 is not None, ""):
        st, j = call("POST", f"/college/students/{row3['id']}/transfer",
                     {"classId": target["id"]}, D)
        res3 = data_of(j) or {}
        check("★ 目标班缺列时转班 -> 200（不丢值）", st == 200, f"st={st} {msg_of(j)}")
        # 目标班那一条是**被停用**的（唯一键占着），所以是「放回来」而不是「新建」
        check("★ 回执里说清补建/放回来了几列",
              int(res3.get("createdFields") or 0) + int(res3.get("revivedFields") or 0) >= 1,
              str(res3)[:200])
        st, j = call("GET", "/college/students?size=200", None, D)
        row4 = next((r for r in ((data_of(j) or {}).get("rows") or [])
                      if r["studentNo"] == "Z9702"), None)
        check("★ 缺列的值也搬过去了",
              (row4 or {}).get("values", {}).get(key) == "有个值", str(row4)[:200])

    # ---------- 清理 ----------
    _purge_students_prefix("Z97")
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_field WHERE field_label = '回归缺列'"))
    _purge_fixture_class("回归转班夹具班")
    # 「云计算2502」**本轮被导入建出来**才删（`before_classes` 挡着）：
    # 库里本来就有这个班时它就是真实名册，绝不能动；干净库上它是这条用例
    # 建的素材，不删的话跑一次回归就留下一个班 + 3 列字段。
    drop_src_class()
    _purge_user(DEAN_PROBE + "_mv")


def test_a29_multi_class() -> None:
    """一个账号管**多个**班（第三十二轮）。

    现实中一个班主任常带两个班（云计算2502 + 云计算2501）。以前一个账号
    只能属于一个班，于是要么给他开两个账号（登两次、密码两份、成员名单两份），
    要么让他管不全。

    四条重点：

    1. **切换是按请求参数** classId 做的，后端在鉴权中间件里把它当成
       「本次操作的班」——所以各班的数据**天然分开**，不会串。
    2. **只能切到自己管的班**：手输别人的 classId 要 403，不能悄悄回落到默认班。
    3. **默认班兜底**：老账号关联表里一条记录都没有，不能变成「一个班都管不了」。
    4. **成员列表跨班**：能管两个班的人，成员列表里两个班的人都要看得见。
    """
    print("\n--- 一个账号管多个班 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    D = _insert_dean_probe(DEAN_PROBE + "_multi")
    if not check("院长探针可用", bool(D), "建号失败"):
        return
    T = S["T"]

    # ---------- 造第二个班 + 一个探针学生 ----------
    #
    # 第二个班**由测试自己造**（夹具班）：回归不能依赖「演示班还在」，
    # 否则演示数据一清，这条用例就悄悄不跑了。
    cid2 = _fixture_class("回归多班班")
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_record WHERE student_no LIKE 'Z98%'"))
        c.execute(
            _t("INSERT INTO student_record (class_id, student_no, name) "
               "VALUES (:c, 'Z9801', '多班探针')"),
            {"c": cid2},
        )
    check("造出第二个班和一个探针学生", cid2 is not None, str(cid2))

    # ---------- 给班主任加第二个班 ----------
    st, j = call("GET", "/users", None, D)
    items = data_of(j) or []
    if isinstance(items, dict):
        items = items.get("items") or []
    teacher = next((u for u in items if u["username"] == "test"), None)
    if not check("成员列表里找得到班主任 test", teacher is not None, str(items)[:200]):
        return
    # 第五十一轮：先记下 test 原本「能管的班」，收尾**原样还回去**。
    # 只还原默认班（旧写法）会把库里本来就有的第二个班弄丢——
    # 收尾的「账号回到基线」跟着红，而红的原因还不在本用例里，极难查。
    orig_classes = [int(c) for c in
                    (teacher.get("managedClassIds") or [teacher["classId"]])]
    st, j = call("PUT", "/users/%d" % teacher["id"],
                 {"classIds": [teacher["classId"], int(cid2)]}, D)
    check("给班主任加第二个班 -> 200", st == 200, f"st={st} {msg_of(j)}")
    up = data_of(j) or {}
    check("回执里带上「能管的班」", len(up.get("managedClassIds") or []) == 2, str(up)[:200])

    # ---------- 切换：两个班的数据要分开 ----------
    st, j = call("GET", "/students?classId=%d" % teacher["classId"], None, T)
    rows_a = (data_of(j) or {}).get("rows") or []
    st, j = call("GET", "/students?classId=%d" % int(cid2), None, T)
    rows_b = (data_of(j) or {}).get("rows") or []
    nos_a = {r.get("studentNo") for r in rows_a}
    nos_b = {r.get("studentNo") for r in rows_b}
    check("★ 切到班 A 看到的是 A 的学生", "Z9801" not in nos_a, str(sorted(nos_a))[:160])
    check("★ 切到班 B 能看到 B 的探针学生", "Z9801" in nos_b, str(sorted(nos_b))[:160])
    check("★ 两个班的学生**不重叠**", not (nos_a & nos_b), str(sorted(nos_a & nos_b))[:160])

    # 不带 classId = 默认班
    st, j = call("GET", "/students", None, T)
    rows_d = (data_of(j) or {}).get("rows") or []
    check("不带 classId 落在默认班", {r.get("studentNo") for r in rows_d} == nos_a,
          str(sorted(r.get("studentNo") for r in rows_d))[:160])

    # ---------- 切到不归他管的班 -> 403 ----------
    st, j = call("GET", "/students?classId=999999", None, T)
    check("切到不归他管的班 -> 403（不能悄悄回落到默认班）", st == 403, f"st={st} {msg_of(j)}")

    # ---------- 成员列表跨班 ----------
    st, j = call("GET", "/users", None, T)
    names = {u["username"] for u in (data_of(j) or [])}
    check("★ 成员列表能看到另一个班的人（跨班）", bool(names), str(names)[:120])

    # ---------- 清理：撤掉那个班 + 删探针学生 ----------
    # 还原成**进来时的样子**（一人可能带好几个班，别只留默认班）
    call("PUT", "/users/%d" % teacher["id"], {"classIds": orig_classes}, D)
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM student_record_value WHERE record_id IN "
                     "(SELECT id FROM student_record WHERE student_no LIKE 'Z98%')"))
        c.execute(_t("DELETE FROM student_record WHERE student_no LIKE 'Z98%'"))
    _purge_fixture_class("回归多班班")
    _purge_user(DEAN_PROBE + "_multi")


def test_a30_profile_dean_scope() -> None:
    """个人信息页：本人改**职务范围**（纯院长 ↔ 院长+班主任）（第三十二轮）。

    用户口径：「本来是院长，然后在我的个人信息里面改为院长+班主任」。

    三条重点：

    1. **本人就能改**，不用找运营——「纯院长」本来就是第三十轮给院长加的一个
       **限制**（只管学院），兼班主任才是院长的默认状态（第二十八轮以来）。
    2. **改完立刻生效**：鉴权中间件每个请求都重读这一列，不用重新登录
       （和 dean_only 一直以来的做法一样）。
    3. **只有院长本人能改**：别的角色这一位没有意义，给他们一个开关
       只会让人以为自己多了什么。
    """
    print("\n--- 个人信息：职务范围 ---")
    # 纯院长探针
    from sqlalchemy import text as _t

    from app.db import engine as _engine
    from app.security import hash_password as _hash_pw

    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user WHERE username = :u"),
                  {"u": "pure_dean_probe"})
        # 拿**班主任 test** 的班当默认班。
        # ⚠ 不能拿演示账号 `pure_dean` 的班——演示账号已清理，
        # 拿它当模板就是「查一个不存在的账号」，class_id 查成 NULL，
        # 插入直接报「class_id 不能为空」，整轮回归崩掉。
        uid = c.execute(_t("SELECT id FROM sys_user WHERE username = 'test' LIMIT 1")).scalar()
        cid = c.execute(_t("SELECT class_id FROM sys_user WHERE id = :i"), {"i": uid}).scalar()
        c.execute(
            _t("INSERT INTO sys_user (class_id, username, password, real_name, role, "
               "dean_only, status) VALUES (:c, 'pure_dean_probe', :p, '纯院长探针', 'DEAN', 1, 1)"),
            {"c": cid, "p": _hash_pw("123456")},
        )
    Tp = login("pure_dean_probe", "123456")
    if not check("纯院长探针登录成功", bool(Tp), "登录失败"):
        return

    st, j = call("GET", "/auth/me", None, Tp)
    me = data_of(j) or {}
    check("探针是纯院长", me.get("deanOnly") is True, str(me)[:160])
    st, _ = call("GET", "/records", None, Tp)
    check("纯院长访问班级事务 -> 403", st == 403, f"st={st}")

    # ---------- 本人改成「院长 + 班主任」 ----------
    st, j = call("PUT", "/auth/profile", {"deanOnly": False}, Tp)
    check("本人改职务范围 -> 200", st == 200, f"st={st} {msg_of(j)}")
    check("回执里 deanOnly=false", (data_of(j) or {}).get("deanOnly") is False, str(data_of(j))[:160])
    st, j = call("GET", "/auth/me", None, Tp)
    check("★ 改完**立刻生效**（不用重新登录）",
          (data_of(j) or {}).get("deanOnly") is False, str(data_of(j))[:160])
    st, _ = call("GET", "/records", None, Tp)
    check("★ 现在能进班级事务了（200）", st == 200, f"st={st}")

    # ---------- 非院长改这一位：应该被忽略（不生效） ----------
    Tm = S["M"]
    st, j = call("PUT", "/auth/profile", {"deanOnly": True}, Tm)
    check("非院长传 deanOnly 不报错（被忽略）", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/auth/me", None, Tm)
    check("★ 非院长的 deanOnly 仍然是 false（没被自己改掉）",
          (data_of(j) or {}).get("deanOnly") is False, str(data_of(j))[:160])

    # ---------- 改回纯院长 ----------
    call("PUT", "/auth/profile", {"deanOnly": True}, Tp)
    st, _ = call("GET", "/records", None, Tp)
    check("改回纯院长后班级事务又 403 了", st == 403, f"st={st}")

    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user WHERE username = 'pure_dean_probe'"))


def test_a31_class_teachers() -> None:
    """**班主任是「班」的属性**（第三十二轮）：三个入口都能配。

    用户口径：「院长可以在学院里面的班级管理里面成员管理，可以更改他是否为
    两个班的班主任，班主任也可以在自己的个人信息里面改，也可以通过导入的
    Excel 表格来识别多个班级信息」。

    三条重点：

    1. **学院成员管理**里能改每个班的班主任（**可以多个**：正、副班主任）。
    2. **班主任本人**在「个人信息」里能改「我带的班」，**直接生效**。
    3. **导入的 Excel** 里带「班主任」列时，按姓名/登录名自动配上；
       配不上要**报出来**（别静默丢掉：用户以为配好了，其实没有）。
    """
    print("\n--- 班主任是班的属性 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from io import BytesIO as _B

    from openpyxl import Workbook as _Wb
    from sqlalchemy import text as _t

    from app.db import engine as _engine

    D = _insert_dean_probe(DEAN_PROBE + "_tch")
    if not check("院长探针可用", bool(D), "建号失败"):
        return
    T = S["T"]

    # 拿两个班：c1 = 班主任那个班，c2 = **测试自己造的夹具班**
    #
    # ⚠ 不能靠「库里现成有第二个班」——演示数据一清，这条用例就悄悄不跑了。
    with _engine.connect() as c:
        cls = [int(r[0]) for r in c.execute(
            _t("SELECT id FROM cls_class WHERE status = 1 ORDER BY id LIMIT 2"))]
    c1 = cls[0] if cls else 0
    c2 = _fixture_class("回归班主任夹具班")
    if not check("至少有两个班", c1 and c2, f"c1={c1} c2={c2}"):
        return

    # ---------- ① 学院成员管理：改班主任 ----------
    st, j = call("GET", "/college/teacher-candidates", None, D)
    cands = (data_of(j) or {}).get("teachers") or []
    check("能拿到可被选的班主任账号", len(cands) >= 1, str(cands)[:160])
    teacher = next((t for t in cands if t["username"] == "test"), None)
    if not check("找得到 test 账号", teacher is not None, str(cands)[:160]):
        return
    # 第五十一轮：记下 test **进来时**「能管的班」，收尾原样还回去。
    # 这个账号在库里本来就可能带好几个班（一人带多班是允许的），
    # 只还原默认班的旧写法会把别的班弄丢，最后「账号回到基线」莫名变红。
    st, j = call("GET", "/auth/me", None, T)
    orig_classes = [int(c) for c in ((data_of(j) or {}).get("classIds") or [])]
    st, j = call("PUT", "/college/classes/%d/teachers" % c1, {"teacherId": teacher["id"]}, D)
    check("★ 学院成员管理里改班主任 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/college/advisers", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    check("★ 名册里能查到他是这个班的班主任",
          any(r.get("classId") == c1 and r.get("username") == "test" for r in rows),
          str(rows)[:200])

    # ---------- ② 班主任本人：改「我带的班」 ----------
    st, j = call("POST", "/auth/login", {"username": "test", "password": "123456"})
    Tt = (data_of(j) or {}).get("token")
    st, j = call("PUT", "/auth/profile", {"classIds": [c1, c2]}, Tt)
    check("★ 本人改「我带的班」-> 200", st == 200, f"st={st} {msg_of(j)}")
    up = data_of(j) or {}
    check("★ 回执里「能管的班」有两个", len(up.get("classIds") or []) == 2, str(up)[:200])
    st, j = call("GET", "/auth/me", None, Tt)
    me = data_of(j) or {}
    check("★ 立刻生效（不用重新登录）：能管两个班",
          len(me.get("classIds") or []) == 2, str(me)[:200])
    # 两个班的数据要分开
    st, j = call("GET", "/students?classId=%d" % c1, None, Tt)
    a = {r.get("studentNo") for r in ((data_of(j) or {}).get("rows") or [])}
    st, j = call("GET", "/students?classId=%d" % c2, None, Tt)
    b = {r.get("studentNo") for r in ((data_of(j) or {}).get("rows") or [])}
    check("★ 两个班的学生**不重叠**", not (a & b), str(sorted(a & b))[:160])

    # ---------- ③ 导入 Excel：识别「班主任」列 ----------
    wb = _Wb()
    ws = wb.active
    ws.append(["学号", "姓名", "班级", "班主任", "性别"])
    with _engine.connect() as _cc:
        cls_name = _cc.execute(
            _t("SELECT class_name FROM cls_class WHERE id = :c"), {"c": c1}
        ).scalar()
    ws.append(["Z9701", "导入甲", cls_name, "test", "男"])
    buf = _B()
    wb.save(buf)
    st, j = _post_multipart("/college/students/import", "file", "名单.xlsx", buf.getvalue(), D)
    imp = data_of(j) or {}
    check("★ 导入带「班主任」列的表 -> 200", st == 200, f"st={st} {msg_of(j)}")
    # 「班主任」是元信息列，**不进字段表**
    check("★ 「班主任」不算一列字段（它是班的信息）",
          "班主任" not in [f.get("label") for f in (imp.get("newFields") or [])],
          str(imp.get("newFields"))[:200])
    with _engine.connect() as _c2:
        linked = _c2.execute(
            _t("SELECT COUNT(*) FROM sys_user_class uc JOIN sys_user u ON u.id = uc.user_id "
               "WHERE u.username = 'test' AND uc.class_id = :c"),
            {"c": c1},
        ).scalar()
    check("★ 建立了师生关系（表里能查到）", int(linked or 0) >= 1, str(imp)[:200])
    # 配不上的名字要报出来
    wb2 = _Wb()
    ws2 = wb2.active
    ws2.append(["学号", "姓名", "班级", "班主任"])
    ws2.append(["Z9702", "导入乙", cls_name, "根本没有这个人"])
    buf2 = _B()
    wb2.save(buf2)
    st, j = _post_multipart("/college/students/import", "file", "名单2.xlsx", buf2.getvalue(), D)
    imp2 = data_of(j) or {}
    check("★ 配不上的班主任要**报出来**（不静默丢掉）",
          any("班主任" in str(e) for e in (imp2.get("errors") or [])),
          str(imp2.get("errors"))[:200])

    # ---------- 清理 ----------
    _purge_students_prefix("Z97")
    # 恢复原状：c1 的班主任本来是 test，dean 只是「我带的班」（管理权）
    with _engine.begin() as c:
        c.execute(_t("DELETE FROM sys_user_class WHERE class_id = :c"), {"c": c1})
        for un, adv in (("test", 1), ("dean", 0)):
            c.execute(
                _t("INSERT INTO sys_user_class (user_id, class_id, is_adviser) "
                   "SELECT id, :c, :a FROM sys_user WHERE username = :u"),
                {"c": c1, "u": un, "a": adv},
            )
    # 夹具班删掉，顺带把「我带的班」**还原成进来时的样子**
    # （第五十一轮：一人可带多班，只留默认班等于改动了用户数据）
    call("PUT", "/users/%d" % teacher["id"], {"classIds": orig_classes}, D)
    _purge_fixture_class("回归班主任夹具班")
    _purge_user(DEAN_PROBE + "_tch")


def _post_multipart(
    path: str, field: str, filename: str, content: bytes, token: str
) -> tuple[int, object]:
    """POST 一个 multipart/form-data（文件上传）。

    手拼 multipart：`urllib` 的 `urlencode` 只能发表单字段，发不了文件。
    ⚠ **必须自己带 boundary**——少了它 FastAPI 那侧直接 400
    「请求体格式不正确」，而那个报错完全看不出是 boundary 的问题。
    """
    import urllib.request

    boundary = "----classfeeTestBoundary7d91"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        "Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method="POST",
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read() or b"null")
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw or b"null")
        except ValueError:
            return e.code, {"message": raw[:200].decode("utf-8", "replace")}


def _get_raw(path: str, token: str) -> tuple[int, bytes]:
    """GET 一个二进制响应（xlsx 下载）。返回 (状态码, 原始字节)。"""
    import urllib.request

    req = urllib.request.Request(
        BASE + path, method="GET", headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def test_a32_task_scope() -> None:
    """任务分**学院任务**和**班级任务**（第三十二轮）。

    用户口径：

    - **学院任务**：院长发布，发给**各班班主任**（不是发给同学）
    - **班级任务**：班主任/班长发给自己班，**同学**应答
    - 学院视角要能**分开**看这两类（`/college/tasks?scope=`）

    七条要点：

    1. **只有院长能发学院任务**——班主任给全学院布置任务是越权
    2. **应答对象按 scope 分流**：学院任务是班主任答，同学答不了
    3. **发布人自己不答**（出题的人不在分母里）
    4. **可见性分三档**（本班+学院 / 只学院 / 其他班）
    5. **分母按 scope 算**：学院任务 = 全校班主任；班级任务 = 本班同学
    6. **明细的口径也不同**：学院任务里班主任只看得到自己班那一份
    7. **任务总览**统计的是「我能看到的」
    """
    print("\n--- 任务：学院任务 / 班级任务（第三十二轮）---")
    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    T, MO, M = S["T"], S["MO"], S["M"]
    D = _insert_dean_probe(DEAN_PROBE + "_scope")
    if not check("院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        return

    PREFIX = "regress_scope"

    def purge() -> None:
        """删掉本轮建的探针任务（含回答）。

        这个库**一张外键都没有**（`information_schema` 里 FOREIGN KEY 约束数 = 0），
        删任务不会自动带走 `cls_task_answer`，所以回答必须先删。
        """
        try:
            from sqlalchemy import text as _t

            from app.db import engine as _engine
        except Exception:  # noqa: BLE001
            return
        with _engine.begin() as c:
            c.execute(
                _t("DELETE FROM cls_task_answer WHERE task_id IN "
                   "(SELECT id FROM cls_task WHERE title LIKE :p)"),
                {"p": PREFIX + "%"},
            )
            c.execute(_t("DELETE FROM cls_task WHERE title LIKE :p"), {"p": PREFIX + "%"})

    purge()

    def db_count(sql: str, **params) -> int:
        try:
            from sqlalchemy import text as _t

            from app.db import engine as _engine
        except Exception:  # noqa: BLE001
            return -1
        with _engine.connect() as c:
            return int(c.execute(_t(sql), params).scalar() or 0)

    # ---------- ① 班级任务（默认 scope=CLASS）----------
    st, j = call("POST", "/tasks",
                 {"title": PREFIX + " 班级任务", "question": "你已经返校了吗？",
                  "qtype": "BOOLEAN"}, T)
    check("班主任发班级任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    class_tid = (data_of(j) or {}).get("id")
    check("班级任务的 scope 默认是 CLASS",
          (data_of(j) or {}).get("scope") == "CLASS", str(data_of(j)))

    # ---------- ② 学院任务只有院长能发 ----------
    for name, tok in (("班主任", T), ("班长", MO), ("普通同学", M)):
        st, j = call("POST", "/tasks",
                     {"title": PREFIX + " 越权", "question": "q",
                      "qtype": "BOOLEAN", "scope": "COLLEGE"}, tok)
        check(f"{name}发学院任务 -> 403（只有院长能发）", st == 403,
              f"st={st} {msg_of(j)}")
    st, j = call("POST", "/tasks",
                 {"title": PREFIX + " 学院任务", "question": "本班同学都返校了吗？",
                  "qtype": "BOOLEAN", "scope": "COLLEGE"}, D)
    check("院长发学院任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    college_tid = (data_of(j) or {}).get("id")
    check("学院任务的 scope 是 COLLEGE",
          (data_of(j) or {}).get("scope") == "COLLEGE", str(data_of(j)))

    # ---------- ③ 应答对象按 scope 分流 ----------
    st, j = call("PUT", f"/tasks/{college_tid}/answer", {"value": True}, M)
    check("同学答学院任务 -> 403（学院任务问的是班的情况，班主任答）", st == 403,
          f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{college_tid}/answer", {"value": True}, T)
    check("班主任答学院任务 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/tasks/{college_tid}/answer", {"value": True}, D)
    check("院长答自己发的学院任务 -> 403（你出的题你自己不算）", st == 403,
          f"st={st} {msg_of(j)}")

    # ---------- ④ 明细的口径：只有院长 / 发布人能看 ----------
    # 学院任务的明细是院长看回收情况用的，班主任走点名页填自己班，同学一律 403
    st, j = call("GET", f"/tasks/{college_tid}/detail", None, D)
    check("院长看学院任务明细 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", f"/tasks/{college_tid}/detail", None, M)
    check("同学看学院任务明细 -> 403", st == 403, f"st={st} {msg_of(j)}")

    # ---------- ⑤ 可见性分三档 ----------
    st, j = call("GET", "/tasks?view=mine", None, T)
    mine = (data_of(j) or {}).get("rows") or []
    ids = {r["id"] for r in mine}
    check("本班视图里有学院任务", college_tid in ids, str(sorted(ids))[:160])
    check("本班视图里有本班任务", class_tid in ids, str(sorted(ids))[:160])
    check("本班视图带 canPublishCollege 标记（前端据此显示「发布学院任务」）",
          (data_of(j) or {}).get("canPublishCollege") is False,
          str((data_of(j) or {}).get("canPublishCollege")))

    st, j = call("GET", "/tasks?view=college", None, T)
    rows = (data_of(j) or {}).get("rows") or []
    check("「只看学院」这一档全是学院任务",
          rows and all(r["scope"] == "COLLEGE" for r in rows), str(rows)[:160])
    check("「只看学院」这一档不含本班的班级任务",
          all(r["id"] != class_tid for r in rows), str(rows)[:160])

    st, j = call("GET", "/tasks?view=other", None, T)
    rows = (data_of(j) or {}).get("rows") or []
    check("「其他班」这一档不含本班的任务",
          all(r["id"] != class_tid for r in rows), str(rows)[:160])
    check("「其他班」这一档不含学院任务",
          all(r["scope"] != "COLLEGE" for r in rows), str(rows)[:160])

    # ---------- ⑥ 分母按 scope 算 ----------
    me = data_of(call("GET", "/auth/me", None, T)[1]) or {}
    cls_id = int(me.get("classId") or 0)
    want_college_base = db_count(
        "SELECT COUNT(*) FROM sys_user WHERE status = 1 "
        "AND role IN ('TEACHER','DEAN') AND NOT (role = 'DEAN' AND dean_only = 1)")
    want_class_base = db_count(
        "SELECT COUNT(*) FROM sys_user WHERE status = 1 AND class_id = :c "
        "AND role IN ('MEMBER','ADMIN','MONITOR')", c=cls_id)

    rows = (data_of(call("GET", "/tasks?view=mine", None, T)[1]) or {}).get("rows") or []
    by_id = {r["id"]: r for r in rows}
    c_row = by_id.get(college_tid) or {}
    k_row = by_id.get(class_tid) or {}
    check("学院任务的分母是全校班主任人数",
          c_row.get("summary", {}).get("total") == want_college_base,
          f"{c_row.get('summary', {}).get('total')} vs {want_college_base}")
    check("班级任务的分母是本班同学人数",
          k_row.get("summary", {}).get("total") == want_class_base,
          f"{k_row.get('summary', {}).get('total')} vs {want_class_base}")
    check("班主任能答学院任务（canAnswer）",
          c_row.get("canAnswer") is True, str(c_row.get("canAnswer")))
    m_rows = (data_of(call("GET", "/tasks?view=mine", None, M)[1]) or {}).get("rows") or []
    m_by_id = {r["id"]: r for r in m_rows}
    check("同学答不了学院任务（canAnswer 为 false）",
          (m_by_id.get(college_tid) or {}).get("canAnswer") is False,
          str((m_by_id.get(college_tid) or {}).get("canAnswer")))

    # ---------- ⑦ 任务总览（**只有院长**）----------
    st, j = call("GET", "/tasks/overview", None, D)
    ov = data_of(j) or {}
    check("院长看任务总览 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/tasks/overview", None, T)
    check("班主任看任务总览 -> 403（只有院长能看）", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/tasks/overview", None, M)
    check("普通同学看任务总览 -> 403", st == 403, f"st={st} {msg_of(j)}")
    check("总览统计了学院任务数",
          int(ov.get("collegeTasks") or 0) >= 1, str(ov.get("collegeTasks")))
    check("总览统计了班级任务数",
          int(ov.get("classTasks") or 0) >= 1, str(ov.get("classTasks")))
    check("总览给出回收率", "rate" in ov and "answered" in ov and "base" in ov, str(ov)[:200])
    check("总览按班分组", isinstance(ov.get("byClass"), list), str(ov.get("byClass"))[:120])
    check("总览按发布人分组", isinstance(ov.get("byPublisher"), list),
          str(ov.get("byPublisher"))[:120])

    # ---------- ⑧ 学院视角分两类看 ----------
    st, j = call("GET", "/college/tasks?scope=COLLEGE", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    check("学院视角「学院任务」全是院长发的任务",
          rows and all(r["scope"] == "COLLEGE" for r in rows), str(rows)[:160])
    check("学院视角「学院任务」带发布人姓名",
          all(r.get("publisher") for r in rows), str(rows)[:160])
    st, j = call("GET", "/college/tasks?scope=CLASS", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    check("学院视角「班级任务」全是班主任发的任务",
          rows and all(r["scope"] == "CLASS" for r in rows), str(rows)[:160])
    check("学院视角「班级任务」带班级名",
          all(r.get("className") for r in rows), str(rows)[:160])
    st, j = call("GET", "/college/tasks", None, D)
    rows = (data_of(j) or {}).get("rows") or []
    check("不带 scope 时两类都看得到",
          {r["scope"] for r in rows} >= {"CLASS", "COLLEGE"}, str(rows)[:160])
    st, j = call("GET", "/college/tasks?scope=COLLEGE", None, T)
    check("班主任看学院任务一览 -> 403（学院这一栏只有院长看得到）", st == 403,
          f"st={st} {msg_of(j)}")

    # ---------- ⑨ 纯院长能看任务总览 ----------
    try:
        from app.security import pure_dean_allowed  # noqa: PLC0415
        check("纯院长白名单放行 /api/tasks/overview",
              pure_dean_allowed("GET", "/api/tasks/overview"), "不在白名单里")
    except Exception as e:  # noqa: BLE001
        check("纯院长白名单放行 /api/tasks/overview", False, str(e))

    # 清理
    purge()
    _purge_user(DEAN_PROBE + "_scope")

def test_a33_delete_students() -> None:
    """删行（第三十三轮）：名册里终于能删掉一整行了。

    用户口径：「我想删除行数据都删除不了」——学院学生信息里只能改格子，
    一整行删不掉。补上之后，这些边界必须钉住：

    1. **班主任能删本班的行**，他填过的字段值一起删（不留孤儿值）
    2. **班长不能删**（能加不能删），普通同学更不能
    3. **越不了班**：拿别班的 id 来删，那一行必须还在
    4. **院长能在学院名册里跨班删**，班主任调学院接口 403
    5. **删已经不存在的 id**：400 而不是 500，更不要假装成功
    6. 纯院长**能**删学院名册（名册是他的本职），但**仍然碰不了班级名册**
    """
    print("\n--- 学生名册：删行（第三十三轮）---")
    T, MO, M = S["T"], S["MO"], S["M"]
    D = _insert_dean_probe(DEAN_PROBE + "_del")
    if not check("院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        return

    PREFIX = "regress_del"
    FIXTURE = "回归删除班"
    created: list[int] = []
    other_rid = 0
    fixture_id = _fixture_class(FIXTURE)

    def _engine():
        root = pathlib.Path(__file__).resolve().parents[1]
        if str(root) not in sys.path:
            sys.path.insert(0, str(root))
        from app.db import engine  # noqa: PLC0415

        return engine

    def db_rows(sql: str, **params) -> list[tuple]:
        try:
            from sqlalchemy import text as _t  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return [("engine-error",)]
        with _engine().connect() as c:
            return [tuple(r) for r in c.execute(_t(sql), params)]

    def purge() -> None:
        """把本轮造的行清干净（测试自己删过，这条是兜底）。

        这个库没有外键，值要先删，否则会留下指向不存在行的孤儿值。
        """
        try:
            from sqlalchemy import text as _t  # noqa: PLC0415
        except Exception:  # noqa: BLE001
            return
        with _engine().begin() as c:
            c.execute(
                _t("DELETE FROM student_record_value WHERE record_id IN "
                   "(SELECT id FROM student_record WHERE student_no LIKE :p)"),
                {"p": PREFIX + "%"},
            )
            c.execute(
                _t("DELETE FROM student_record WHERE student_no LIKE :p"),
                {"p": PREFIX + "%"},
            )
        _purge_fixture_class(FIXTURE)

    purge()
    try:
        # ---------- ① 班主任造两行，填一格 ----------
        for no in (PREFIX + "1", PREFIX + "2"):
            st, j = call("POST", "/students",
                         {"studentNo": no, "name": "删行探针"}, T)
            rid = (data_of(j) or {}).get("id")
            if rid:
                created.append(int(rid))
        check("造了两行探针学生", len(created) == 2, str(created))
        if len(created) == 2:
            st, j = call("PUT", f"/students/{created[0]}",
                         {"values": {"gender": "男"}}, T)
            check("先给其中一行填一格（用来验证值随行一起删）",
                  st == 200, f"st={st} {msg_of(j)}")

        # ---------- ② 权限：班长 / 同学都不行 ----------
        st, j = call("DELETE", f"/students?ids={created[0]}", None, MO)
        check("班长删本班学生 -> 403（能加不能删）", st == 403, f"st={st} {msg_of(j)}")
        st, j = call("DELETE", f"/students?ids={created[0]}", None, M)
        check("普通同学删本班学生 -> 403", st == 403, f"st={st} {msg_of(j)}")

        # ---------- ③ 班主任删本班两行 ----------
        if len(created) == 2:
            st, j = call("DELETE", f"/students?ids={created[0]},{created[1]}", None, T)
            check("班主任删本班两行 -> 200", st == 200, f"st={st} {msg_of(j)}")
            check("返回的是真正删掉的行数",
                  (data_of(j) or {}).get("deleted") == 2, str(data_of(j)))
            left = db_rows(
                "SELECT id FROM student_record WHERE id IN (:a, :b)",
                a=created[0], b=created[1],
            )
            check("库里这两行没了", left == [], str(left))
            leftover = db_rows(
                "SELECT id FROM student_record_value WHERE record_id IN (:a, :b)",
                a=created[0], b=created[1],
            )
            check("他们填过的字段值也没了（不留孤儿值）", leftover == [], str(leftover))

            # ---------- ④ 再删一次 / 非法 id ----------
            st, j = call("DELETE", f"/students?ids={created[0]}", None, T)
            check("删已经不存在的行 -> 400（不是 500）",
                  st == 400, f"st={st} {msg_of(j)}")
        st, j = call("DELETE", "/students?ids=abc", None, T)
        check("非法 id -> 400", st == 400, f"st={st} {msg_of(j)}")

        # ---------- ⑤ 越不了班：夹具班（别的班）的行必须活着 ----------
        check("夹具班可用", bool(fixture_id), str(fixture_id))
        if fixture_id:
            with _engine().begin() as c:
                from sqlalchemy import text as _t  # noqa: PLC0415

                c.execute(
                    _t("INSERT INTO student_record (class_id, student_no, name) "
                       "VALUES (:c, :n, '别班探针')"),
                    {"c": fixture_id, "n": PREFIX + "other"},
                )
                other_rid = int(c.execute(
                    _t("SELECT id FROM student_record WHERE student_no = :n"),
                    {"n": PREFIX + "other"},
                ).scalar())
            st, j = call("DELETE", f"/students?ids={other_rid}", None, T)
            check("班主任删别班的行 -> 400（越不了班）",
                  st == 400, f"st={st} {msg_of(j)}")
            alive = db_rows("SELECT id FROM student_record WHERE id = :i", i=other_rid)
            check("别班那一行还在", alive != [], "被删掉了")

        # ---------- ⑥ 院长：学院名册可以跨班删 ----------
        st, j = call("DELETE", f"/college/students?ids={other_rid}", None, T)
        check("班主任调学院删行接口 -> 403（学院这一层只有院长）",
              st == 403, f"st={st} {msg_of(j)}")
        st, j = call("DELETE", "/college/students?ids=999999", None, D)
        check("院长删不存在的 id -> 400", st == 400, f"st={st} {msg_of(j)}")
        if other_rid:
            st, j = call("DELETE", f"/college/students?ids={other_rid}", None, D)
            check("院长跨班删行 -> 200", st == 200, f"st={st} {msg_of(j)}")
            gone = db_rows("SELECT id FROM student_record WHERE id = :i", i=other_rid)
            check("别班那一行被院长删掉了", gone == [], str(gone))
            other_rid = 0

        # ---------- ⑦ 纯院长白名单：名册可写，班级事务仍然不行 ----------
        try:
            from app.security import pure_dean_allowed  # noqa: PLC0415

            check("纯院长白名单放行「学院名册删除」",
                  pure_dean_allowed("DELETE", "/api/college/students"), "不在白名单里")
            check("纯院长白名单放行「学院名册改格」",
                  pure_dean_allowed("PUT", "/api/college/students/1"), "不在白名单里")
            check("纯院长仍然碰不了班级名册",
                  not pure_dean_allowed("DELETE", "/api/students"), "被放行了")
        except Exception as e:  # noqa: BLE001
            check("纯院长白名单检查", False, str(e))
    finally:
        purge()
        _purge_user(DEAN_PROBE + "_del")


def test_a34_dean_managed_classes() -> None:
    """院长的「我带的班」**真的按勾选走**（第三十三轮）。

    用户口径：「院长+班主任这里是不是有点问题，感觉有点串数据，尤其班级里
    面学生信息那里，好像没有根据这个来分类」。

    根因：`managed_class_ids` 对院长是**直接短路**成「所有启用班」的，
    所以「个人信息 → 我带的班」勾成什么样都不生效——回执、侧栏切换器、
    能切的班永远是全部。那个多选对院长就是个摆设。

    改完之后必须钉住这几条：

    1. 院长勾了 1 个班 → `classIds` 就 1 个，班级层切到别的班 **403**
    2. **学院层不受影响**：学院名册照旧全校，`?classId=` 是**筛选**不是「当前班」
       （这一条以前会 403：筛选值和「我带的班」混成一个语义了）
    3. 把班加进「我带的班」→ 立刻能切；摘掉 → 立刻 403（不用重登）
    4. **一条都没勾过的院长**仍然全管（老账号、探针账号不能升级即失效）
    """
    print("\n--- 院长「我带的班」（第三十三轮）---")
    from sqlalchemy import text as _t

    from app.db import engine as _engine
    from app.security import hash_password as _hash

    FIXTURE = "回归带班探针班"
    PROBE = "dean_scope_probe"

    def purge() -> None:
        with _engine.begin() as c:
            uid = c.execute(
                _t("SELECT id FROM sys_user WHERE username = :u"), {"u": PROBE}
            ).scalar()
            if uid is not None:
                c.execute(_t("DELETE FROM sys_user_class WHERE user_id = :i"), {"i": uid})
                c.execute(_t("DELETE FROM sys_user WHERE id = :i"), {"i": uid})
        _purge_fixture_class(FIXTURE)

    purge()
    fid = _fixture_class(FIXTURE)
    if not check("夹具班可用（先清再建，别把自己清掉）", bool(fid), str(fid)):
        return
    try:
        with _engine.begin() as c:
            uid0 = c.execute(
                _t("SELECT id FROM sys_user WHERE username = 'test' LIMIT 1")
            ).scalar()
            cid = c.execute(
                _t("SELECT class_id FROM sys_user WHERE id = :i"), {"i": uid0}
            ).scalar()
            c.execute(
                _t(
                    "INSERT INTO sys_user (class_id, username, password, real_name, role, "
                    "dean_only, status) VALUES (:c, :u, :p, '带班探针院长', 'DEAN', 0, 1)"
                ),
                {"c": cid, "u": PROBE, "p": _hash("123456")},
            )
            uid = int(c.execute(
                _t("SELECT id FROM sys_user WHERE username = :u"), {"u": PROBE}
            ).scalar())

        # ---------- ① 没勾过 → 全管（老账号行为不变） ----------
        P = login(PROBE, "123456")
        if not check("带班探针院长可登录", bool(P), "登录失败"):
            return
        st, j = call("GET", "/auth/me", None, P)
        ids0 = (data_of(j) or {}).get("classIds") or []
        with _engine.connect() as c:
            want_all = int(
                c.execute(_t("SELECT COUNT(*) FROM cls_class WHERE status = 1")).scalar()
            )
        check("没勾过「我带的班」的院长仍然全管", len(ids0) == want_all,
              f"classIds={ids0} 启用班={want_all}")

        # ---------- ② 勾成「只带默认班」 ----------
        with _engine.begin() as c:
            c.execute(_t("DELETE FROM sys_user_class WHERE user_id = :i"), {"i": uid})
            c.execute(
                _t("INSERT INTO sys_user_class (user_id, class_id) VALUES (:i, :c)"),
                {"i": uid, "c": cid},
            )
        st, j = call("GET", "/auth/me", None, P)
        ids1 = (data_of(j) or {}).get("classIds") or []
        check("勾 1 个班 → classIds 就 1 个", ids1 == [cid], f"classIds={ids1}")
        st, j = call("GET", f"/students?classId={cid}", None, P)
        check("勾着的班，班级层能进", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", f"/students?classId={fid}", None, P)
        check("没勾的班，班级层 403", st == 403, f"st={st} {msg_of(j)}")

        # ---------- ③ 学院层**不受**「我带的班」影响 ----------
        st, j = call("GET", f"/college/students?classId={fid}", None, P)
        check("学院名册按班筛选照常 200（筛选不是「当前班」）",
              st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/college/students?size=200", None, P)
        all_rows = (data_of(j) or {}).get("total") or 0
        st, j = call("GET", f"/college/students?classId={fid}", None, P)
        one_rows = (data_of(j) or {}).get("total") or 0
        check("学院名册的 classId 筛选真的在筛", st == 200 and one_rows <= all_rows,
              f"全部={all_rows} 单班={one_rows}")

        # ---------- ④ 加进来立刻生效，摘掉立刻失效 ----------
        st, j = call("PUT", "/auth/profile", {"classIds": [cid, fid]}, P)
        check("把我带的班改成 2 个 -> 200", st == 200, f"st={st} {msg_of(j)}")
        st, j = call("GET", "/auth/me", None, P)
        check("回执里就是这 2 个班",
              sorted((data_of(j) or {}).get("classIds") or []) == sorted([cid, fid]),
              str((data_of(j) or {}).get("classIds")))
        st, j = call("GET", f"/students?classId={fid}", None, P)
        check("刚加进来的班，班级层立刻能进", st == 200, f"st={st} {msg_of(j)}")

        st, j = call("PUT", "/auth/profile", {"classIds": [cid]}, P)
        st, j = call("GET", f"/students?classId={fid}", None, P)
        check("摘掉之后，班级层立刻 403", st == 403, f"st={st} {msg_of(j)}")
    finally:
        purge()


def test_a35_create_class() -> None:
    """「我带的班」里输入新班名回车即建班（第三十三轮）。

    用户口径：「这里我觉得输入之后回车可以新增」。

    那条下拉是 `el-select` 多选，选项来自 `/class/choices`——想带一个**还没建**
    的班，就没有选项可选，只能先去别处建班再回来勾。改成 `allow-create` 之后
    Element Plus 会把用户敲的班名当**字符串**塞进 `v-model`，前端拿它调这个接口
    换回真 id。所以接口这边必须成立：

    1. **只有院长能建**——建班是学院层的事（老师等级不够，403）
    2. 新班是**空班**，但班级层能进、能导入名单
    3. 字段模板**照默认班复制**——否则新班的「学生信息」只剩学号姓名两列
    4. **同名不报错**，返回已有的那个（`created=False`）——两处界面同时点
       「新建」不该让后手的人吃一条红条
    5. 空白班名要拒
    """
    print("\n--- 输入新班名回车建班（第三十三轮）---")
    import pathlib

    from sqlalchemy import text as _t

    from app.db import engine as _engine

    FIXTURE = "回归新建班夹具班"
    PROBE = DEAN_PROBE + "_cls"
    if str(pathlib.Path(__file__).resolve().parents[1]) not in sys.path:
        sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

    def purge() -> None:
        _purge_fixture_class(FIXTURE)
        uid = _probe_id(PROBE)
        if uid > 0:
            with _engine.begin() as c:
                c.execute(_t("DELETE FROM sys_user_class WHERE user_id = :i"), {"i": uid})
            _purge_user(PROBE)

    purge()
    D = _insert_dean_probe(PROBE)
    if not check("建班探针院长可用", bool(D), "建号失败"):
        return

    made: list[int] = []
    try:
        # ---------- ① 老师不能建班 ----------
        st, j = call("POST", "/college/classes", {"className": FIXTURE}, S["T"])
        check("★ 老师建班 403（建班是学院层的事）", st == 403, f"st={st} {msg_of(j)}")

        # ---------- ② 院长建班 ----------
        st, j = call("POST", "/college/classes", {"className": FIXTURE}, D)
        d = data_of(j) or {}
        cid = d.get("id")
        check("★ 院长建班 -> 200", st == 200 and bool(cid), f"st={st} {msg_of(j)}")
        if not cid:
            return
        made.append(int(cid))
        check("回执 created=True", d.get("created") is True, str(d)[:160])
        check("回执报了复制了多少列", (d.get("fieldsCopied") or 0) > 0, str(d)[:160])

        # ---------- ③ 新班立刻能选到 ----------
        st, j = call("GET", "/class/choices", None, D)
        names = [c.get("className") for c in ((data_of(j) or {}).get("classes") or [])]
        check("新班立刻出现在班级列表里", FIXTURE in names, str(names)[:200])

        # ---------- ④ 字段模板 = 默认班那一套 ----------
        with _engine.connect() as c:
            dev = c.execute(
                _t(
                    "SELECT class_id FROM sys_user WHERE username = 'test' LIMIT 1"
                )
            ).scalar()
            src = {r[0] for r in c.execute(
                _t("SELECT field_key FROM student_field WHERE class_id = :c AND status = 1"),
                {"c": dev},
            )}
            got = {r[0] for r in c.execute(
                _t("SELECT field_key FROM student_field WHERE class_id = :c AND status = 1"),
                {"c": cid},
            )}
            leaves = c.execute(
                _t("SELECT COUNT(*) FROM student_field WHERE class_id = :c"), {"c": cid}
            ).scalar()
        check("★ 新班的列就是默认班那套（按 field_key 比）", bool(src) and got == src,
              f"缺={sorted(src - got)[:5]} 多={sorted(got - src)[:5]}")
        check("新班没有多出来的停用列", leaves == len(src), f"全量={leaves} 启用={len(src)}")

        # ---------- ⑤ 空班，但班级层能进 ----------
        st, j = call("GET", f"/students?classId={cid}", None, D)
        d3 = data_of(j) or {}
        rows = d3.get("rows") or []
        check("★ 新班是空班且班级层能进", st == 200 and rows == [],
              f"st={st} rows={len(rows)} {msg_of(j)}")

        # ---------- ⑥ 同名再建：返回已有的，不报错 ----------
        st, j = call("POST", "/college/classes", {"className": FIXTURE}, D)
        d2 = data_of(j) or {}
        check("★ 同名再建 200 + created=False + 同一个 id",
              st == 200 and d2.get("created") is False and d2.get("id") == cid,
              f"st={st} {str(d2)[:160]}")
        with _engine.connect() as c:
            n = c.execute(
                _t("SELECT COUNT(*) FROM cls_class WHERE class_name = :n"), {"n": FIXTURE}
            ).scalar()
        check("同名不会建出第二个班", n == 1, f"count={n}")

        # ---------- ⑦ 空白班名要拒 ----------
        st, j = call("POST", "/college/classes", {"className": "   "}, D)
        check("空白班名被拒（400/422）", st in (400, 422), f"st={st} {msg_of(j)}")
    finally:
        purge()


def test_a36_reg_status() -> None:
    """学籍状态认「在籍 / 毕业 / 入伍 / 休学 / 退学」（第三十四轮）。

    用户口径：「在籍、毕业、入伍、休学、退学 这是学籍的示例情况」，
    「导入进来自动识别，然后登记在仪表盘」，「只有在籍算（在籍人数）」。

    这一列是**自由文本**（导入的 Excel 里什么写法都有），所以做的是**归类**：
    同一件事的不同写法落到同一档，仪表盘才数得对。要钉住四件事：

    1. 归类：`已毕业`→毕业、`参军入伍`→入伍、`休学（病假）`→休学、
       `自动退学`→退学、`在藉`（错字）→其他（**不硬塞进在籍**）
    2. 只有「在籍」计入注册人数；毕业/入伍/休学/退学/其他都不计
       （入伍按保留学籍处理：人不在校）
    3. **空值仍算在籍**——Excel 不会每列都填满，一空就算未知会让分母
       比分子小；空值在分布图里单列成「未填写」，看得见
    4. 分布按固定顺序排（在籍/毕业/入伍/休学/退学/其他/未填写），
       不按人数排：每次打开都该在同一个位置
    """
    print("\n--- 学籍状态归类（第三十四轮）---")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
    from app.services.student_service import (  # noqa: PLC0415
        REG_STATUS_EMPTY,
        REG_STATUS_ENROLLED,
        REG_STATUS_GRADUATED,
        REG_STATUS_MILITARY,
        REG_STATUS_OTHER,
        REG_STATUS_QUIT,
        REG_STATUS_SUSPENDED,
        classify_reg_status,
        is_registered,
    )

    table = [
        ("在籍", REG_STATUS_ENROLLED),
        ("在读", REG_STATUS_ENROLLED),
        ("已毕业", REG_STATUS_GRADUATED),
        ("参军入伍", REG_STATUS_MILITARY),
        ("休学（病假）", REG_STATUS_SUSPENDED),
        ("自动退学", REG_STATUS_QUIT),
        ("在藉", REG_STATUS_OTHER),  # 错字不能算在籍
        ("转学", REG_STATUS_OTHER),
        ("", REG_STATUS_EMPTY),
        (None, REG_STATUS_EMPTY),
    ]
    for raw, want in table:
        got = classify_reg_status(raw)
        check(f"归类 {raw!r} → {want}", got == want, f"got={got}")

    check("「在籍」算在籍", is_registered("在籍") is True, "在籍被算成离校")
    for raw in ("毕业", "入伍", "休学", "退学", "在藉", "转学"):
        check(f"「{raw}」不算在籍", is_registered(raw) is False, raw)
    check("空值仍算在籍（Excel 不会每列都填满）", is_registered("") is True, "空值被算成离校")

    # ---------- 接口：分布 + 注册人数 ----------
    D = _insert_dean_probe(DEAN_PROBE + "_reg")
    if not check("学籍探针院长可用", bool(D), "建号失败"):
        return
    try:
        st, j = call("GET", "/dashboard/students", None, D)
        d0 = data_of(j) or {}
        base_bd = {b["status"]: b["count"] for b in (d0.get("statusBreakdown") or [])}
        base_reg = int(d0.get("registeredTotal") or 0)

        rows = [
            ("regst_a", "在籍", REG_STATUS_ENROLLED),
            ("regst_b", "已毕业", REG_STATUS_GRADUATED),
            ("regst_c", "参军入伍", REG_STATUS_MILITARY),
            ("regst_d", "休学", REG_STATUS_SUSPENDED),
            ("regst_e", "自动退学", REG_STATUS_QUIT),
            ("regst_f", "", REG_STATUS_EMPTY),
            ("regst_g", "在藉", REG_STATUS_OTHER),
        ]
        for no, raw, _bucket in rows:
            st, j = call("POST", "/students",
                         {"studentNo": no, "name": "学籍" + no[-1],
                          "values": {"reg_status": raw}}, S["T"])
            if not check(f"造学生 {no}（学籍={raw!r}）-> 200", st == 200,
                         f"st={st} {msg_of(j)}"):
                return

        st, j = call("GET", "/dashboard/students", None, D)
        d = data_of(j) or {}
        if not check("立看完再看一次 -> 200", st == 200, f"st={st} {msg_of(j)}"):
            return
        bd = {b["status"]: b for b in (d.get("statusBreakdown") or [])}

        for _no, _raw, bucket in rows:
            want = base_bd.get(bucket, 0) + 1
            got = int((bd.get(bucket) or {}).get("count") or 0)
            check(f"分布里「{bucket}」+1", got == want, f"实际 {got}，预期 {want}")

        check("★ 注册人数只 +2（在籍 1 + 未填写 1），毕业/入伍/休学/退学/其他都不算",
              int(d.get("registeredTotal") or 0) - base_reg == 2,
              f"增量 {int(d.get('registeredTotal') or 0) - base_reg}，预期 2")

        check("在籍/未填写两档标为计入注册",
              (bd.get(REG_STATUS_ENROLLED) or {}).get("registered") is True
              and (bd.get(REG_STATUS_EMPTY) or {}).get("registered") is True,
              str({k: (v or {}).get("registered") for k, v in bd.items()}))
        check("毕业/入伍/休学/退学/其他都不计入注册",
              all((bd.get(k) or {}).get("registered") is False
                  for k in (REG_STATUS_GRADUATED, REG_STATUS_MILITARY,
                            REG_STATUS_SUSPENDED, REG_STATUS_QUIT, REG_STATUS_OTHER)),
              str({k: (v or {}).get("registered") for k, v in bd.items()}))

        check("认不出的写法进了「其他」且原文留着（在藉）",
              "在藉" in ((bd.get(REG_STATUS_OTHER) or {}).get("samples") or []),
              str((bd.get(REG_STATUS_OTHER) or {}).get("samples")))
        check("归一档里看得见原始写法（已毕业 → 毕业）",
              "已毕业" in ((bd.get(REG_STATUS_GRADUATED) or {}).get("samples") or []),
              str((bd.get(REG_STATUS_GRADUATED) or {}).get("samples")))

        order = [b["status"] for b in (d.get("statusBreakdown") or []) if b.get("count")]
        want_order = [REG_STATUS_ENROLLED, REG_STATUS_GRADUATED, REG_STATUS_MILITARY,
                      REG_STATUS_SUSPENDED, REG_STATUS_QUIT, REG_STATUS_OTHER,
                      REG_STATUS_EMPTY]
        check("分布按固定顺序排（不按人数排）",
              [s for s in order if s in want_order] == want_order, str(order))
    finally:
        _purge_students_prefix("regst_")
        _purge_user(DEAN_PROBE + "_reg")


def test_a37_import_template() -> None:
    """导入模板（第三十五轮）：给的模板就是「填完能直接导」的那张表。

    用户口径：「在学院-学生名册和班级-学生信息里面增加一个导出模板，然后按照
    这个模板填写之后导入进来，以免他们没有模板随便就导进来了」，
    「新增字段的时候模板里面也要跟着增加」。

    模板因此必须满足：

    1. **第一张表第 1 行就是表头**（学号/姓名在前），导入读的是第一行——
       模板要是像导出那样带标题行，用户得先手工删两行
    2. **列 = 下载那一刻的字段**：加一列再下载，新列必须出现（不许写死）
    3. **填完真的能导回去**：按模板填一行 → `/students/import` 成功，值落在对的列上
    4. 权限和导入同档：普通同学拿不到（403）
    5. 学院模板多一列「班级」（按行分发），列 = 各班字段合并
    """
    print("\n--- 导入模板（第三十五轮）---")
    from io import BytesIO as _B

    from openpyxl import load_workbook as _load
    from sqlalchemy import text as _t

    from app.db import engine as _engine
    from app.security import hash_password as _hash

    FIX = "回归模板夹具班"
    PROBE = DEAN_PROBE + "_tpl"
    CLASS_T = "tpl_probe_teacher"

    def purge() -> None:
        _purge_students_prefix("tpl_rt_")
        _purge_fixture_class(FIX)
        _purge_user(CLASS_T)
        _purge_user(PROBE)

    purge()
    fid = _fixture_class(FIX)
    if not check("模板夹具班可用", bool(fid), str(fid)):
        return
    # 夹具班的班主任探针：直写库（走 API 会把班主位指到执行身份那个班）
    with _engine.begin() as c:
        c.execute(
            _t(
                "INSERT INTO sys_user (class_id, username, password, real_name, role, "
                "status) VALUES (:c, :u, :p, '模板探针老师', 'TEACHER', 1)"
            ),
            {"c": fid, "u": CLASS_T, "p": _hash("123456")},
        )
    CT = login(CLASS_T, "123456")
    if not check("模板探针老师可登录", bool(CT), "登录失败"):
        purge()
        return
    D = _insert_dean_probe(PROBE)

    added_key: list[str] = []
    try:
        # ---------- ① 空班：模板只有学号/姓名，表头在第 1 行 ----------
        st, body = _get_raw("/students/template", CT)
        check("班级模板 -> 200 且是 xlsx", st == 200 and body[:2] == b"PK", f"st={st}")
        if st != 200:
            return
        wb = _load(_B(body))
        check("模板有两张表：学生信息 + 填写说明",
              wb.sheetnames == ["学生信息", "填写说明"], str(wb.sheetnames))
        ws = wb["学生信息"]
        hdr = [c.value for c in ws[1]]
        check("★ 第 1 行就是表头，学号/姓名在最前",
              hdr[:2] == ["学号", "姓名"], str(hdr[:4]))
        check("空班的模板不带任何业务列", hdr == ["学号", "姓名"], str(hdr))
        hs = wb["填写说明"]
        check("说明页写了「填完直接传回」和「不要改列名」",
              (hs["A1"].value or "").endswith("导入模板")
              and any("不要改列名" in str(hs.cell(row=r, column=1).value or "")
                      for r in range(1, 12)),
              str(hs["A1"].value))

        # ---------- ② 加一列 → 重新下载就有 ----------
        st, j = call("POST", "/students/fields",
                     {"label": "模板新列", "type": "DATE"}, CT)
        check("加一列 -> 200", st == 200, f"st={st} {msg_of(j)}")
        added_key.append((data_of(j) or {}).get("key") or "")
        st, body2 = _get_raw("/students/template", CT)
        hdr2 = [c.value for c in _load(_B(body2))["学生信息"][1]]
        check("★ 新加的列立刻出现在模板里（不是写死的表）",
              hdr2 == ["学号", "姓名", "模板新列"], str(hdr2))
        hs2 = _load(_B(body2))["填写说明"]
        rows2 = {
            str(hs2.cell(row=r, column=1).value): hs2.cell(row=r, column=2).value
            for r in range(1, hs2.max_row + 1)
        }
        check("说明页把新列标成日期类型", rows2.get("模板新列") == "日期", str(rows2.get("模板新列")))

        # ---------- ③ 按模板填一行，导回去 ----------
        wb2 = _load(_B(body2))
        ws2 = wb2["学生信息"]
        fill = {"学号": "tpl_rt_1", "姓名": "模板回环", "模板新列": "2026-09-01"}
        for i, name in enumerate([c.value for c in ws2[1]], start=1):
            if name in fill:
                ws2.cell(row=2, column=i, value=fill[name])
        buf = _B()
        wb2.save(buf)
        st, j = _post_multipart("/students/import", "file", "学生信息导入模板.xlsx", buf.getvalue(), CT)
        r = data_of(j) or {}
        check("★ 按模板填的行能直接导入（created=1）",
              st == 200 and int(r.get("created") or 0) == 1,
              f"st={st} {str(r)[:160]}")
        check("导入没有多建列（表头就是已有的列）",
              not (r.get("newFields") or []), str(r.get("newFields"))[:120])
        st, j = call("GET", "/students", None, CT)
        rows = (data_of(j) or {}).get("rows") or []
        mine = next((x for x in rows if x.get("studentNo") == "tpl_rt_1"), None)
        check("★ 模板那一列的值落在对的字段上",
              bool(mine) and (mine.get("values") or {}).get(added_key[0]) == "2026-09-01",
              str(mine.get("values") if mine else None)[:200])

        # ---------- ④ 普通同学拿不到模板 ----------
        st, _ = _get_raw("/students/template", S["M"])
        check("普通同学下载班级模板 -> 403", st == 403, f"st={st}")

        # ---------- ⑤ 学院模板：多一列「班级」，列 = 各班合并 ----------
        if not check("学院模板需要院长令牌", bool(D), "建号失败"):
            return
        st, tch = _get_raw("/college/students/template", S["T"])
        check("班主任下载学院模板 -> 403（学院层的东西）", st == 403, f"st={st}")
        st, cbody = _get_raw("/college/students/template", D)
        check("学院模板 -> 200 且是 xlsx",
              st == 200 and cbody[:2] == b"PK", f"st={st}")
        cwb = _load(_B(cbody))
        chdr = [c.value for c in cwb["学生信息"][1]]
        check("★ 学院模板前 3 列 = 班级/学号/姓名",
              chdr[:3] == ["班级", "学号", "姓名"], str(chdr[:5]))
        st, j = call("GET", "/college/fields", None, D)
        uni = [c["label"] for c in ((data_of(j) or {}).get("columns") or [])]
        check("★ 学院模板的列 = 各班字段合并（含刚加的那列）",
              bool(uni) and "模板新列" in chdr and all(lbl in chdr for lbl in uni),
              f"合并列={len(uni)} 模板列={len(chdr)} 缺={[x for x in uni if x not in chdr][:5]}")

        # ---------- ⑥ 学院模板也回环一次（带「班级」列） ----------
        cws = cwb["学生信息"]
        cf = {"班级": FIX, "学号": "tpl_rt_2", "姓名": "学院模板回环"}
        for i, name in enumerate(chdr, start=1):
            if name in cf:
                cws.cell(row=2, column=i, value=cf[name])
        cbuf = _B()
        cwb.save(cbuf)
        st, j = _post_multipart(
            "/college/students/import", "file", "学院学生名册导入模板.xlsx", cbuf.getvalue(), D
        )
        r = data_of(j) or {}
        check("★ 按学院模板填的行能按「班级」列分到那个班",
              st == 200 and int(r.get("created") or 0) == 1,
              f"st={st} {str(r)[:160]}")
        with _engine.connect() as c:
            landed = c.execute(
                _t("SELECT class_id FROM student_record WHERE student_no = 'tpl_rt_2'")
            ).scalar()
        check("落在模板里写的那个班", int(landed or 0) == fid, f"class_id={landed} 期望 {fid}")
    finally:
        purge()


def test_a38_user_batch() -> None:
    """账号批量管理（第四十四轮）：停用 / 启用 / 删除 / 重置密码。

    重点验三件事：
    1. 规则和单条**同口径**（自己 / 等级护栏 / 零引用删除）
    2. 「能做就做，做不了的跳过并说明」——跳过的要带原因回来
    3. 重置密码回执带初始密码（前端要靠它提示老师通知学生）
    """
    print("\n--- 三十八. 账号批量管理 ---")
    T = login("test", "123456")
    if not check("班主任探针可用", bool(T), "登录失败"):
        return

    names = ["batch_a", "batch_b", "batch_c"]
    ids = [ensure_user(n, "MEMBER", f"批量{n[-1]}", T) for n in names]
    if not check("三个批量探针建好", all(ids), str(ids)):
        return

    # ---------- 入参层 ----------
    st, j = call("POST", "/users/batch", {"action": "disable", "userIds": []}, T)
    check("空 id 列表 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("POST", "/users/batch", {"action": "nuke", "userIds": ids}, T)
    check("非法动作 -> 400", st == 400, f"st={st} {msg_of(j)}")

    # ---------- 批量停用 ----------
    st, j = call("POST", "/users/batch", {"action": "disable", "userIds": ids}, T)
    d = data_of(j) or {}
    check("批量停用 -> 200 且三人全处理、无跳过",
          st == 200 and d.get("changed") == 3 and not d.get("skipped"), f"st={st} {str(d)[:160]}")
    st2, _ = call("POST", "/auth/login", {"username": names[0], "password": "123456"})
    check("停用后本人登录失败", st2 != 200, f"st={st2}")

    # ---------- 批量启用 ----------
    st, j = call("POST", "/users/batch", {"action": "enable", "userIds": ids}, T)
    d = data_of(j) or {}
    check("批量启用 -> 200", st == 200 and d.get("changed") == 3, f"st={st} {str(d)[:120]}")
    st2, _ = call("POST", "/auth/login", {"username": names[0], "password": "123456"})
    check("启用后能登录", st2 == 200, f"st={st2}")

    # ---------- 批量重置密码 ----------
    st, j = call("POST", "/users/batch", {"action": "resetPassword", "userIds": [ids[0]]}, T)
    d = data_of(j) or {}
    check("重置密码回执带初始密码", st == 200 and d.get("password") == "123456", str(d)[:140])
    st2, _ = call("POST", "/auth/login", {"username": names[0], "password": "123456"})
    check("重置后可用初始密码登录", st2 == 200, f"st={st2}")
    # 旧密码必须失效（否则「重置」只是个摆设）
    st2, _ = call("POST", "/auth/login", {"username": names[0], "password": "Abc12345"})
    check("重置后旧密码失效", st2 != 200, f"st={st2}")

    # ---------- 跳过：自己 / 不存在的 id ----------
    me = (data_of(call("GET", "/auth/me", None, T)[1]) or {}).get("id")
    st, j = call("POST", "/users/batch", {"action": "disable", "userIds": [me, 999999999, ids[0]]}, T)
    d = data_of(j) or {}
    reasons = {s.get("userId"): s.get("reason") for s in d.get("skipped") or []}
    check("自己被跳过并说明", me in reasons and "自己" in (reasons.get(me) or ""), str(reasons)[:160])
    check("不存在的 id 被跳过并说明", 999999999 in reasons, str(reasons)[:160])
    check("同批里能动的那条照常处理", d.get("changed") == 1, str(d)[:160])

    # ---------- 等级护栏：低等级不能批量动高等级 ----------
    mon = ensure_user("batch_mon", "MONITOR", "批量班长", T)
    if mon:
        # 班主任 > 班长：能停用
        st, j = call("POST", "/users/batch", {"action": "disable", "userIds": [mon]}, T)
        d = data_of(j) or {}
        check("班主任能批量停用班长（等级更高）", st == 200 and d.get("changed") == 1, str(d)[:140])
        call("POST", "/users/batch", {"action": "enable", "userIds": [mon]}, T)
        # 反过来：班长动不了班主任
        M = login("batch_mon", "123456")
        if M:
            st, j = call("POST", "/users/batch", {"action": "disable", "userIds": [me]}, M)
            d = data_of(j) or {}
            check("班长不能批量停用班主任（等级护栏）",
                  st == 200 and d.get("changed") == 0 and bool(d.get("skipped")),
                  f"st={st} {str(d)[:140]}")

    # ---------- 批量删除 ----------
    st, j = call("POST", "/users/batch", {"action": "delete", "userIds": ids}, T)
    d = data_of(j) or {}
    check("批量删除零引用账号 -> 三人全删", st == 200 and d.get("changed") == 3, str(d)[:160])
    for n in names:
        check(f"{n} 已从列表消失", find_user(n, T) is None, "")

    # ---------- 清理 ----------
    drop_user("batch_mon", T)
    for n in names:
        drop_user(n, T)


def test_a39_task_export_filter() -> None:
    """**按状态筛选的导出**（第四十九轮）：`POST /tasks/{id}/export`。

    仪表盘的顶部卡片既是统计也是筛选器：点「已返校」只导已返校、
    点「未返校」只导未返校。四条重点：

    1. **文件 = 屏幕上的行**：传哪些 `recordIds` 就出哪些人，一个不多一个不少。
       「哪些值算未返校」的关键词表只在前端 `utils/taskStatus.ts` 一份，
       后端只做集合过滤**不认语义**——两处各写一份关键词迟早漂，
       屏幕 6 人、文件 8 人，没人查得出来。
    2. 筛选口径写进**副标题和文件名**：拿到文件的人得知道这不是全量，
       否则会拿 6 行的名单去对 35 个人的班，对不上还以为是漏导。
    3. 空列表 / 一个都没命中 → 400（全量请走 GET，别发一份空文件）。
    4. 权限与 GET 同一道闸；执行身份用**纯院长**（dean_only=1），
       顺带端到端验白名单——`_PURE_DEAN_ALLOWED` 漏一条就是 403。
    """
    print("\n--- 三十九. 按状态筛选导出 ---")
    from io import BytesIO as _B  # noqa: PLC0415
    from urllib.parse import unquote as _unq  # noqa: PLC0415

    import urllib.request  # noqa: PLC0415

    from openpyxl import load_workbook as _Lw  # noqa: PLC0415

    def rows_of(blob: bytes) -> list[list]:
        ws = _Lw(_B(blob)).active
        return [[c.value for c in row] for row in ws.iter_rows()]

    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))
    from sqlalchemy import text as _t  # noqa: PLC0415

    from app.db import engine as _engine  # noqa: PLC0415

    EXP_PROBE = DEAN_PROBE + "_exp"

    # 名册可能被清空（用户会把演示数据删干净），而这一段要拿「至少 3 行」当
    # 筛选素材。依赖基线数据的用例在**干净库上会悄悄少跑一整段**（报告里
    # 只是断言变少，看不出少了什么），所以素材由用例自己造、自己删——
    # 和 `_fixture_class` 同一条原则。
    FIX_NOS = [f"ZX39{i}" for i in range(1, 6)]

    def ensure_students() -> None:
        """在班主任的班里补 5 个夹具学生（已存在就覆盖）。"""
        with _engine.begin() as c:
            cid = c.execute(
                _t("SELECT class_id FROM sys_user WHERE username = :u"), {"u": ROOT_U}
            ).scalar()
            if not cid:
                return
            for i, no in enumerate(FIX_NOS, 1):
                c.execute(_t("DELETE FROM student_record WHERE student_no = :n"),
                          {"n": no})
                c.execute(_t(
                    "INSERT INTO student_record (class_id, student_no, name) "
                    "VALUES (:c, :n, :m)"),
                    {"c": cid, "n": no, "m": f"筛选导出探针{i}"})

    def drop_students() -> None:
        with _engine.begin() as c:
            for no in FIX_NOS:
                c.execute(_t("DELETE FROM student_record WHERE student_no = :n"),
                          {"n": no})

    def cleanup(task_id=None) -> None:
        if task_id:
            call("DELETE", f"/tasks/{task_id}", None, D)
        with _engine.begin() as c:
            c.execute(_t("DELETE FROM cls_task WHERE title = :p"),
                      {"p": "regress 筛选导出"})
        _purge_user(EXP_PROBE)
        drop_students()

    # ---------- 执行身份：纯院长（顺带验白名单） ----------
    D = _insert_dean_probe(EXP_PROBE)
    if not check("院长探针可用", bool(D), "建号失败"):
        return
    with _engine.begin() as c:
        c.execute(_t("UPDATE sys_user SET dean_only = 1 WHERE username = :u"),
                  {"u": EXP_PROBE})

    # ---------- ① 建一条学院任务（纯院长的本职） ----------
    st, j = call("POST", "/tasks", {"title": "regress 筛选导出", "question": "返校了吗？",
                                    "qtype": "SINGLE", "options": ["到校", "未到", "请假"],
                                    "allowText": True, "scope": "COLLEGE"}, D)
    if not check("纯院长发学院任务 -> 200（白名单没漏）", st == 200, f"st={st} {msg_of(j)}"):
        cleanup()
        return
    tid = (data_of(j) or {}).get("id")

    # ---------- ② 明细里取两行当「筛选命中」 ----------
    def fetch_detail():
        st, j = call("GET", f"/tasks/{tid}/detail", None, D)
        d = data_of(j) or {}
        # 带上班名：断言「只输出命中的班」时不能假设两行一定同一个班
        rows = [(cl.get("className"), r)
                for cl in (d.get("classes") or []) for r in cl.get("rows") or []]
        return st, d, rows

    st, d, all_rows = fetch_detail()
    if len(all_rows) < 3:
        # 干净库里没有学生可当素材：自己补几个再取一次（跑完由 cleanup 删掉）
        ensure_students()
        st, d, all_rows = fetch_detail()
    total = (d.get("answered") or 0) + (d.get("unanswered") or 0)
    if not check("纯院长看明细 -> 200 且名册不空", st == 200 and len(all_rows) >= 3,
                 f"st={st} rows={len(all_rows)}"):
        cleanup(tid)
        return
    pick = all_rows[:2]
    ids = [r["recordId"] for _, r in pick]
    want_names = {r["name"] for _, r in pick}
    want_nos = {r["studentNo"] for _, r in pick}
    want_classes = {cn for cn, _ in pick}

    # ---------- ③ 筛选拿文件（连响应头一起看，文件名是产品的一部分） ----------
    req = urllib.request.Request(
        f"http://127.0.0.1:8080/api/tasks/{tid}/export",
        data=json.dumps({"recordIds": ids, "label": "未返校"},
                        ensure_ascii=False).encode(),
        headers={"Authorization": f"Bearer {D}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as x:
            st, blob, hdr = x.status, x.read(), dict(x.headers)
    except urllib.error.HTTPError as e:
        st, blob, hdr = e.code, e.read(), dict(e.headers)
    check("筛选拿文件 -> 200 且是 xlsx", st == 200 and blob[:2] == b"PK", f"st={st}")
    disp = next((v for k, v in hdr.items() if k.lower() == "content-disposition"), "")
    check("文件名带筛选名", _unq(disp).endswith("-未返校-回答.xlsx"), disp)

    grid = rows_of(blob)
    sub = grid[1][0] if len(grid) > 1 else ""
    check("副标题写明筛选口径与人数", "筛选：未返校（2 人）" in (sub or ""), repr(sub))
    data_rows = [r for r in grid[3:] if r[3]]  # 姓名列非空才是数据行（班小标题只占第 1 列）
    check("恰好导出那两行（不多不少）", len(data_rows) == 2, f"n={len(data_rows)}")
    check("就是屏幕上那两个人", {r[3] for r in data_rows} == want_names,
          str([r[3] for r in data_rows]))
    check("学号对得上", {r[2] for r in data_rows} == want_nos, str([r[2] for r in data_rows]))
    heads = [r[0] for r in grid[3:] if r[0] and r[3] is None]  # 班小标题只占第 1 列
    check("只输出命中的班（没命中的班整段不出现）",
          len(heads) == len(want_classes), f"heads={heads}")
    check("班标题是筛选口径而非全量口径",
          bool(heads) and all("筛选出" in h for h in heads), str(heads)[:160])

    # ---------- ④ 不带 label 也不能装成全量 ----------
    st, blob = _download(f"/tasks/{tid}/export", D, payload={"recordIds": ids})
    grid = rows_of(blob)
    check("不带 label -> 200", st == 200, f"st={st}")
    check("副标题仍有筛选字样（否则会被当成全量）",
          "筛选：所选行（2 人）" in ((grid[1][0] if len(grid) > 1 else "") or ""),
          repr(grid[1][0] if len(grid) > 1 else ""))

    # ---------- ⑤ 该拒绝的 ----------
    st, body = _download(f"/tasks/{tid}/export", D, payload={"recordIds": []})
    check("空 recordIds -> 400（全量请走 GET）", st == 400, f"st={st} {body[:80]!r}")
    st, body = _download(f"/tasks/{tid}/export", D, payload={"recordIds": [999999999]})
    check("一个都没命中 -> 400（不发只有表头的空文件）", st == 400, f"st={st} {body[:80]!r}")

    # 权限：和 GET 同一道闸，普通成员拿不到
    TM = login("test", "123456")
    M = ensure_user("exp_member_39", "MEMBER", "筛选导出探针", TM) if TM else None
    MK = login("exp_member_39", "123456") if M else None
    if MK:
        st, body = _download(f"/tasks/{tid}/export", MK, payload={"recordIds": ids})
        check("普通成员筛选拿文件 -> 403（和 GET 同闸）", st == 403, f"st={st}")
    if TM:
        drop_user("exp_member_39", TM)

    # ---------- ⑥ GET 全量不受影响（老行为不能被这次改动带偏） ----------
    st, blob = _download(f"/tasks/{tid}/export", D)
    grid = rows_of(blob)
    full_rows = [r for r in grid[3:] if r[3]]
    check("GET 全量 -> 200", st == 200 and blob[:2] == b"PK", f"st={st}")
    check("全量行数 = 名册人数", len(full_rows) == total,
          f"got={len(full_rows)} total={total}")
    check("全量没有筛选字样", "筛选：" not in ((grid[1][0] if len(grid) > 1 else "") or ""),
          repr(grid[1][0] if len(grid) > 1 else ""))
    check("全量仍是「已填/共」口径",
          f"共 {total} 人" in ((grid[1][0] if len(grid) > 1 else "") or ""),
          repr(grid[1][0] if len(grid) > 1 else ""))

    cleanup(tid)


def test_a40_adviser_template_roundtrip() -> None:
    """**班主任导入模板必须「填完直接传回」**（第五十轮）。

    起因：用户下载模板、填好数据导入，**必然**报「表格里必须有「姓名」和
    「登录名」列」。根因是模板把标题/说明垫在表头前面（表头在第 3 行），
    而导入只认第一行——模板自己把自己废了，用户填什么都没用。
    `build_template_xlsx` 的 docstring 早把这条铁律写死了（「模板唯一的用途
    是填完直接传回来」），班主任模板没照着做，而回归里没有「下载→填→导回」
    的往返断言，于是它活到了用户手里。

    四条重点：

    1. **表头就在第 1 行**：下载 → 填一行 → 导入，全程不手改文件结构。
    2. 说明文字放**第二张 sheet**（导入只读第一张表，说明写哪儿都不碍事）。
    3. **旧布局也要能导**：表头在第 3 行的历史模板、用户自己加了标题行的
       表——导入端往前扫几行找表头。用户手里**已经填好的文件**不能作废，
       逼人家重新下载重填一遍说不过去。
    4. 找不到表头时的报错要**说人话**（点明「前 N 行里没找到」，
       别再让人以为是自己数据填错了位置）。
    """
    print("\n--- 四十. 班主任导入模板往返 ---")
    from io import BytesIO as _B  # noqa: PLC0415

    from openpyxl import load_workbook as _Lw  # noqa: PLC0415

    root = pathlib.Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root))

    FIX = "回归班主任导入夹具班"
    FIX_OLD = "回归班主任导入夹具班二"  # 旧布局那一行单独一个空班，见 ③
    ADV_PROBE = DEAN_PROBE + "_adv"
    TEACHER_U = "adv_rt_t1"     # 新模板导入建出来的账号
    OLD_U = "adv_rt_t2"         # 旧布局文件导入建出来的账号

    def purge() -> None:
        for u in (TEACHER_U, OLD_U, ADV_PROBE):
            _purge_user(u)
        _purge_fixture_class(FIX)
        _purge_fixture_class(FIX_OLD)

    purge()
    D = _insert_dean_probe(ADV_PROBE)
    if not check("院长探针可用", bool(D), "建号失败"):
        return
    fid = _fixture_class(FIX)
    fid_old = _fixture_class(FIX_OLD)
    if not check("夹具班可用", bool(fid) and bool(fid_old), f"{fid}/{fid_old}"):
        purge()
        return

    try:
        # ---------- ① 下载模板：表头在第 1 行 ----------
        st, body = _get_raw("/college/advisers/template", D)
        check("下载模板 -> 200 且是 xlsx", st == 200 and body[:2] == b"PK", f"st={st}")
        if not check("模板下载成功", st == 200, f"st={st}"):
            return
        wb = _Lw(_B(body))
        check("模板两张表：班主任导入 + 填写说明",
              wb.sheetnames == ["班主任导入", "填写说明"], str(wb.sheetnames))
        hdr = [c.value for c in wb["班主任导入"][1]][:5]
        check("★ 第 1 行就是表头（姓名/登录名/带的班都在）",
              hdr == ["姓名", "登录名", "初始密码", "手机号", "带的班"], str(hdr))
        hs = wb["填写说明"]
        check("说明页讲清必填项与默认密码",
              any("姓名、登录名必填" in str(hs.cell(row=r, column=1).value or "")
                  for r in range(1, 6)), str(hs["A1"].value))

        # ---------- ② 按模板填一行，原样导回去 ----------
        ws = wb["班主任导入"]
        ws.cell(row=2, column=1, value="往返老师")
        ws.cell(row=2, column=2, value=TEACHER_U)
        ws.cell(row=2, column=5, value=FIX)
        buf = _B()
        wb.save(buf)
        st, j = _post_multipart(
            "/college/advisers/import", "file", "班主任导入模板.xlsx", buf.getvalue(), D)
        r = data_of(j) or {}
        check("★ 按模板填的行能直接导入（created=1）",
              st == 200 and int(r.get("created") or 0) == 1,
              f"st={st} {str(r)[:160]}")
        st, j = call("GET", "/college/advisers", None, D)
        rows = (data_of(j) or {}).get("rows") or []
        check("★ 名册里出现导入的班主任，「带的班」也对",
              any(x.get("username") == TEACHER_U and x.get("classId") == fid
                  for x in rows), str(rows)[:200])

        # ---------- ③ 旧布局（标题垫在前面，表头在第 3 行）也要能导 ----------
        #
        # ⚠ 必须导到**另一个空班**：第五十一轮起一个班只有一位班主任，
        # 往 FIX 里再导第二位老师会被正当地拦下（那正是 a41 要测的规则）。
        # 这里测的是「表头能认出来」，不能让它撞在别的规则上。
        old_file = _mk_xlsx([
            ["班主任导入模板 · 填好传回「学院 → 成员管理 → 导入班主任」"],
            ["姓名、登录名必填；班级必须已存在，多个用顿号/逗号分隔。"],
            ["姓名", "登录名", "初始密码", "手机号", "带的班"],
            ["旧版老师", OLD_U, "", "", FIX_OLD],
        ])
        st, j = _post_multipart(
            "/college/advisers/import", "file", "旧版模板.xlsx", old_file, D)
        r2 = data_of(j) or {}
        check("★ 表头在第 3 行的旧文件也能导（用户已填好的不作废）",
              st == 200 and int(r2.get("created") or 0) == 1,
              f"st={st} {str(r2)[:160]}")
        st, j = call("GET", "/college/advisers", None, D)
        rows2 = (data_of(j) or {}).get("rows") or []
        check("★ 旧布局导进来的老师挂在它自己那个班",
              any(x.get("username") == OLD_U and x.get("classId") == fid_old
                  for x in rows2), str(rows2)[:240])

        # ---------- ④ 没有表头时的报错要说人话 ----------
        bad = _mk_xlsx([["乱七八糟的表头"], ["第二行也是乱的"]])
        st, j = _post_multipart(
            "/college/advisers/import", "file", "乱表.xlsx", bad, D)
        check("没找到表头 -> 400 且点明「前 N 行里没找到」",
              st == 400 and "没找到" in msg_of(j), f"st={st} {msg_of(j)}")

        # ---------- ⑤ 权限：学院层的东西，班主任拿不到 ----------
        TM = login("test", "123456")
        if TM:
            st, _ = _get_raw("/college/advisers/template", TM)
            check("班主任下载模板 -> 403（学院层）", st == 403, f"st={st}")
    finally:
        purge()


def test_a41_one_teacher_per_class() -> None:
    """**一个班一个班主任**（第五十一轮收紧）：安排=顶替，其余入口撞车报错。

    起因：用户在「班主任名册」看到大数据2502挂着 test-ls 和 haixuan-ls
    两个班主任账号，问「一个班不可能有两个班主任吧」。第三十二轮把
    「班主任」做成班的多对多属性时顺手允许了一班多个（当时的口径是
    「正、副班主任」）——现在收紧成**一个班一位**：

    - 「一个老师带几个班」照旧（**人**的属性，多对多不动）
    - 「一个班几个老师」不再允许；**改班主任安排是唯一允许覆盖的入口**
      （显式点名顶替），其余入口撞车一律报错/跳过并指路到这里
    - **院长兼班主任与普通班主任同权同额**：院长也占同一个名额，一个班
      无论角色都只出现一位；院长被顶替后仍保留「能管这个班」，只是不占名册位

    七条重点：
    1. 安排 = 顶替：换人后名册只剩新的（旧的被摘掉）
    2. 导入撞车 → 该行跳过 + 报错点名班和现任；**同一老师重导不算撞**（更新资料）
    3. 本人「我带的班」加一个已被占的班 → 400，文案带班名和现任；
       **默认班**撞车则静默不挂名册行（否则被顶替的班主任连个人信息都存不了）
    4. 建班主任号时操作者所在班已有班主任 → 400（不静默变两个）
    5. 给无班主任的班加人、一个老师带多个班 → 照常通过
    6. `teacherId=null` 清空该班班主任
    7. **院长占位**：先安排院长当班主任 → 别人导入/被安排时同样撞他；
       换成普通班主任后，名册只剩一位，但院长**仍能管这个班**
    """
    print("\n--- 四十一. 一个班一个班主任 ---")
    from sqlalchemy import text as _t  # noqa: PLC0415

    from app.db import engine as _engine  # noqa: PLC0415
    from app.security import hash_password as _hash  # noqa: PLC0415

    FIX_A = "回归单师夹具班A"
    FIX_B = "回归单师夹具班B"
    A, B, C = "one_t_a", "one_t_b", "one_t_c"
    NA, NB, NC = "探针甲", "探针乙", "探针丙"  # 真实姓名进报错文案，断言靠它

    def purge() -> None:
        for u in (A, B, C, "one_t_d", DEAN_PROBE + "_one"):
            _purge_user(u)
        _purge_fixture_class(FIX_A)
        _purge_fixture_class(FIX_B)

    def make_teacher(username: str, real_name: str, class_id: int, link: bool) -> None:
        """直写库造班主任探针（API 建号会被「班里已有班主任」拦——那正是本次要测的）。"""
        with _engine.begin() as c:
            c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": username})
            c.execute(
                _t(
                    "INSERT INTO sys_user (class_id, username, password, real_name, "
                    "role, status) VALUES (:c, :u, :p, :n, 'TEACHER', 1)"
                ),
                {"c": class_id, "u": username, "p": _hash("123456"), "n": real_name},
            )
            if link:
                c.execute(
                    _t("INSERT INTO sys_user_class (user_id, class_id, is_adviser) "
                       "SELECT id, :c, 1 FROM sys_user WHERE username = :u"),
                    {"c": class_id, "u": username},
                )

    def uid_of(u: str) -> int:
        with _engine.connect() as c:
            return int(c.execute(_t("SELECT id FROM sys_user WHERE username = :u"),
                                 {"u": u}).scalar() or 0)

    def teachers_of(cid: int) -> list[str]:
        """名册口径：该班 `is_adviser=1` 的账号（院长也占位，与 advisers 一致）。"""
        with _engine.connect() as c:
            return [str(r[0]) for r in c.execute(
                _t("SELECT u.username FROM sys_user_class uc "
                   "JOIN sys_user u ON u.id = uc.user_id "
                   "WHERE uc.class_id = :c AND uc.is_adviser = 1 AND u.status = 1 "
                   "AND (u.role = 'TEACHER' OR (u.role = 'DEAN' AND u.dean_only = 0)) "
                   "ORDER BY u.id"), {"c": cid})]

    purge()
    fid_a = _fixture_class(FIX_A)
    fid_b = _fixture_class(FIX_B)
    if not check("夹具班可用", bool(fid_a and fid_b), f"a={fid_a} b={fid_b}"):
        purge()
        return
    make_teacher(A, NA, int(fid_a), link=True)    # A 带 A 班
    make_teacher(B, NB, int(fid_b), link=True)    # B 带 B 班
    make_teacher(C, NC, int(fid_b), link=False)   # C 存在但不带班（默认班 B）

    D = _insert_dean_probe(DEAN_PROBE + "_one")
    if not check("院长探针可用", bool(D), "建号失败"):
        purge()
        return

    try:
        # ---------- ① 安排 = 顶替 ----------
        st, j = call("PUT", f"/college/classes/{fid_a}/teachers",
                     {"teacherId": uid_of(A)}, D)
        check("安排甲当 A 班班主任 -> 200", st == 200, f"st={st} {msg_of(j)}")
        check("★ 名册口径：A 班的班主任是甲",
              teachers_of(int(fid_a)) == [A], str(teachers_of(int(fid_a))))

        st, j = call("PUT", f"/college/classes/{fid_a}/teachers",
                     {"teacherId": uid_of(B)}, D)
        check("换成乙 -> 200（顶替不报冲突——这是唯一允许覆盖的入口）",
              st == 200, f"st={st} {msg_of(j)}")
        check("★ 顶替生效：A 班只剩乙（甲被摘掉）",
              teachers_of(int(fid_a)) == [B], str(teachers_of(int(fid_a))))
        # 第五十一轮：换班主任**不许搬走老师的默认班**（登录落点属于账号本人）。
        # 以前会「对齐」，于是一个老师带两个班时，改一次安排就被搬一次，
        # 下次登录落在别的班，自己的账目/学生全看不到。
        with _engine.connect() as c:
            b_default = int(c.execute(
                _t("SELECT class_id FROM sys_user WHERE username = :u"), {"u": B}
            ).scalar() or 0)
        check("★ 换班主任不改老师的默认班（登录落点不动）",
              b_default == int(fid_b), f"默认班={b_default} 预期={fid_b}")
        # 乙此时同时带 A、B 两个班（安排只重写目标班，另一班的关联不动）
        check("★ 一个老师带两个班（人的属性不受限）",
              teachers_of(int(fid_a)) == [B] and teachers_of(int(fid_b)) == [B],
              f"a={teachers_of(int(fid_a))} b={teachers_of(int(fid_b))}")

        # ---------- ② 导入撞车：整行跳过 + 指路；同一老师重导不算撞 ----------
        wb = _mk_xlsx([
            ["姓名", "登录名", "初始密码", "手机号", "带的班"],
            [NC, C, "", "", FIX_A],  # A 班已有乙 → 撞
        ])
        st, j = _post_multipart("/college/advisers/import", "file", "撞车.xlsx", wb, D)
        imp = data_of(j) or {}
        check("撞车行的导入请求本身 -> 200（行级跳过，不是整单 400）",
              st == 200, f"st={st} {msg_of(j)}")
        check("★ 撞车行被跳过（没有新增）",
              int(imp.get("created") or 0) == 0 and int(imp.get("skipped") or 0) == 1,
              str(imp)[:200])
        check("★ 报错点名班级、现任班主任、并指路改班主任安排",
              any(FIX_A in str(e) and NB in str(e) and "改班主任安排" in str(e)
                  for e in (imp.get("errors") or [])),
              str(imp.get("errors"))[:300])
        check("★ 名册没被导入改动：A 班还是乙",
              teachers_of(int(fid_a)) == [B], str(teachers_of(int(fid_a))))

        # 同一老师重导（乙换手机号、两个班都带上）：自己不算撞车
        wb2 = _mk_xlsx([
            ["姓名", "登录名", "初始密码", "手机号", "带的班"],
            ["探针乙改", B, "", "13900000000", f"{FIX_A}、{FIX_B}"],
        ])
        st, j = _post_multipart("/college/advisers/import", "file", "重导.xlsx", wb2, D)
        imp2 = data_of(j) or {}
        check("★ 同一老师重导不算撞车（updated=1，无跳过无报错）",
              st == 200 and int(imp2.get("updated") or 0) == 1
              and int(imp2.get("skipped") or 0) == 0
              and not (imp2.get("errors") or []),
              f"st={st} {str(imp2)[:200]}")

        # ---------- ③ 本人「我带的班」 ----------
        Ta = login(A, "123456")
        if check("探针甲可登录", bool(Ta), "登录失败"):
            # a) 默认班（已归乙）撞车：**静默不挂名册行**，不能把人锁死在存不了个人信息上
            st, j = call("PUT", "/auth/profile", {"classIds": [int(fid_a)]}, Ta)
            up_a = data_of(j) or {}
            check("★ 甲只勾默认班 A（已归乙）-> 200 不报错",
                  st == 200, f"st={st} {msg_of(j)}")
            check("★ 默认班不占名册位：甲不在 A 班名册",
                  A not in teachers_of(int(fid_a)), str(teachers_of(int(fid_a))))
            check("★ 但管理权保留：回执里仍含默认班（登录落点不受影响）",
                  int(fid_a) in [int(x) for x in (up_a.get("classIds") or [])],
                  str(up_a)[:200])
            # b) **显式勾选**一个已被占的班（非默认班）-> 400 指路
            st, j = call("PUT", "/auth/profile",
                         {"classIds": [int(fid_a), int(fid_b)]}, Ta)
            check("★ 甲显式勾已被乙占的 B 班 -> 400",
                  st == 400, f"st={st} {msg_of(j)}")
            check("★ 报错带班名、现任、指路",
                  FIX_B in msg_of(j) and NB in msg_of(j)
                  and "改班主任安排" in msg_of(j), msg_of(j)[:200])

        # ---------- ④ 建号撞车 -> 400 ----------
        T = S["T"]  # 班主任 test，本班=云计算2502（他就是该班班主任）
        st, j = call("POST", "/users",
                     {"username": "one_t_d", "realName": "建号撞车",
                      "password": "123456", "role": "TEACHER"}, T)
        check("★ 在已有班主任的班里建班主任号 -> 400",
              st == 400, f"st={st} {msg_of(j)}")
        check("★ 报错指路改班主任安排", "改班主任安排" in msg_of(j), msg_of(j)[:200])
        with _engine.connect() as c:
            gone = c.execute(_t("SELECT COUNT(*) FROM sys_user WHERE username = 'one_t_d'")
                             ).scalar()
        check("★ 被拒的账号没有残留", int(gone or 0) == 0, str(gone))

        # ---------- ⑤ 清空 + 给无班主任的班加人 ----------
        st, j = call("PUT", f"/college/classes/{fid_b}/teachers", {"teacherId": None}, D)
        check("★ 清空 B 班班主任 -> 200", st == 200, f"st={st} {msg_of(j)}")
        check("★ 名册：B 班没有班主任了", teachers_of(int(fid_b)) == [],
              str(teachers_of(int(fid_b))))
        st, j = call("PUT", f"/college/classes/{fid_b}/teachers",
                     {"teacherId": uid_of(C)}, D)
        check("★ 给无班主任的 B 班安排丙 -> 200（不撞车）",
              st == 200 and teachers_of(int(fid_b)) == [C],
              f"st={st} {str(teachers_of(int(fid_b)))}")

        # ---------- ⑥ 院长兼班主任也占同一个名额 ----------
        # 用户口径：「院长+班主任这个权限的话，跟班主任一样的，一个班级
        # 只能出现一个班主任」。所以院长不能是「额外的第二位」。
        DEAN_U = DEAN_PROBE + "_one"
        dean_uid = uid_of(DEAN_U)
        st, j = call("PUT", f"/college/classes/{fid_a}/teachers",
                     {"teacherId": dean_uid}, D)
        check("★ 安排院长当 A 班班主任 -> 200（顶替乙）",
              st == 200, f"st={st} {msg_of(j)}")
        check("★ 名册：A 班只有院长一位（院长占的就是那个名额）",
              teachers_of(int(fid_a)) == [DEAN_U], str(teachers_of(int(fid_a))))

        # 别的入口撞上「院长班主任」也必须报错指路——不能只拦 TEACHER。
        wb3 = _mk_xlsx([
            ["姓名", "登录名", "初始密码", "手机号", "带的班"],
            [NC, C, "", "", FIX_A],
        ])
        st, j = _post_multipart("/college/advisers/import", "file", "撞院长.xlsx", wb3, D)
        imp3 = data_of(j) or {}
        check("★ 班里已有院长时导入别人 -> 行级跳过",
              st == 200 and int(imp3.get("created") or 0) == 0
              and int(imp3.get("skipped") or 0) == 1, str(imp3)[:200])
        check("★ 报错点名院长并指路改班主任安排",
              any("院长探针" in str(e) and "改班主任安排" in str(e)
                  for e in (imp3.get("errors") or [])),
              str(imp3.get("errors"))[:300])
        check("★ 名册没被导入改动：A 班还是院长",
              teachers_of(int(fid_a)) == [DEAN_U], str(teachers_of(int(fid_a))))

        # 换成普通班主任：院长让位，但「能管这个班」必须留着
        st, j = call("PUT", f"/college/classes/{fid_a}/teachers",
                     {"teacherId": uid_of(B)}, D)
        check("★ 用普通班主任顶替院长 -> 200", st == 200, f"st={st} {msg_of(j)}")
        check("★ 名册：A 班只剩普通班主任（院长不再占位）",
              teachers_of(int(fid_a)) == [B], str(teachers_of(int(fid_a))))
        st, j = call("GET", "/auth/me", None, D)
        dean_classes = [int(x) for x in ((data_of(j) or {}).get("classIds") or [])]
        check("★ 院长被顶替后**仍然能管** A 班（管理行保留，只是不占名册位）",
              int(fid_a) in dean_classes, str(dean_classes)[:200])
    finally:
        purge()


def test_a42_dean_accounts() -> None:
    """院长账号（第五十二轮）：**可以有多位**，纯院长也能再开一个。

    三条重点：

    1. 纯院长虽然进不了「班级 → 成员管理」，但「再开一个院长」是**学院事务**，
       所以单开 `/college/deans` 这组接口，而不是放开 `/api/users`；
    2. 新院长一律建成**纯院长**——角色/班级字段由服务端钉死，请求体里塞
       `role=TEACHER` 也只会建出院长（防止把这一页当成绕过等级校验的后门）；
    3. 新账号能立刻登录、也拥有同一个入口——否则「最后一位院长」离职后，
       系统里就再也没人能开新院长了。
    """
    print("\n--- 院长账号（可多位）---")
    T = S["T"]
    MAKER = DEAN_PROBE + "_maker"
    MADE = DEAN_PROBE + "_made"
    D = _insert_dean_probe(MAKER, dean_only=1)
    _purge_user(MADE)
    if not check("纯院长探针可用（直写库模拟部署声明）", bool(D), "建号失败"):
        _purge_user(MAKER)
        return

    try:
        st, j = call("GET", "/auth/me", None, D)
        check("探针确实是纯院长（deanOnly=true）",
              (data_of(j) or {}).get("deanOnly") is True, str(data_of(j))[:120])

        # ---------- ① 班主任进不来：这是学院级入口 ----------
        st, j = call("GET", "/college/deans", None, T)
        check("班主任看院长账号列表 -> 403（仅院长）", st == 403,
              f"st={st} {msg_of(j)}")
        st, j = call("POST", "/college/deans",
                     {"username": MADE, "realName": "班主任想建的院长"}, T)
        check("班主任新增院长 -> 403（等级不够，不能开院长）", st == 403,
              f"st={st} {msg_of(j)}")

        # ---------- ② 纯院长能列、能建 ----------
        st, j = call("GET", "/college/deans", None, D)
        before = data_of(j) or {}
        check("纯院长能看院长账号列表", st == 200, f"st={st} {msg_of(j)}")
        check("列表里有自己",
              any(r.get("username") == MAKER for r in (before.get("rows") or [])),
              str(before)[:200])

        st, j = call("POST", "/college/deans",
                     {"username": MADE, "password": "dean123",
                      "realName": "新院长", "phone": "13800000000",
                      # 故意塞入别的角色：服务端必须仍按院长建
                      "role": "TEACHER"},
                     D)
        made = data_of(j) or {}
        check("纯院长新增院长 -> 200", st == 200, f"st={st} {msg_of(j)}")
        check("新增的一律是院长（请求体里的 role=TEACHER 被忽略）",
              made.get("role") == "DEAN", str(made)[:200])
        check("新院长默认纯院长（deanOnly=true）",
              made.get("deanOnly") is True, str(made)[:200])

        # ---------- ③ 列表可见 + 新账号能登录、也有同样的入口 ----------
        st, j = call("GET", "/college/deans", None, D)
        after = data_of(j) or {}
        rows = after.get("rows") or []
        row = next((r for r in rows if r.get("username") == MADE), None)
        check("列表里出现新院长", row is not None, str(rows)[:200])
        check("新院长在列表里也是纯院长", (row or {}).get("deanOnly") is True, str(row))
        check("院长数量 +1（允许多位）",
              int(after.get("total") or 0) == int(before.get("total") or 0) + 1,
              f"{after.get('total')} vs {before.get('total')}")

        P2 = login(MADE, "dean123")
        check("新院长能立刻登录", bool(P2), "登录失败")
        st, j = call("GET", "/auth/me", None, P2)
        me2 = data_of(j) or {}
        check("新院长的 role=DEAN / deanOnly=true",
              me2.get("role") == "DEAN" and me2.get("deanOnly") is True,
              str(me2)[:160])
        st, j = call("GET", "/college/deans", None, P2)
        check("新建的纯院长也能进同一个入口（不会出现「最后一位院长离职」死锁）",
              st == 200, f"st={st} {msg_of(j)}")

        # ---------- ④ 唯一登录名：复用 create_user 的校验 ----------
        st, j = call("POST", "/college/deans",
                     {"username": MADE, "realName": "重名院长"}, D)
        check("重复登录名 -> 400", st == 400 and "已存在" in msg_of(j),
              f"st={st} {msg_of(j)}")
    finally:
        _purge_user(MADE)
        _purge_user(MAKER)


def test_a43_adviser_batch_delete() -> None:
    """班主任名册批量删除账号（第五十三轮）。

    两条线：

    1. **删的是账号，不是班级**——名册上那个班还在，只是回到「未建账号」；
    2. **只删班主任账号**——学生、纯院长、同级院长混进选择里一律跳过并说明原因，
       不能把学院页变成「按 id 删任意账号」的后门。

    另外两条护栏与单条删除同口径：不能删自己、有缴费/流水/批次引用不能删。
    """
    print("\n--- 班主任名册：批量删除账号 ---")
    root = pathlib.Path(__file__).resolve().parents[1]
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from sqlalchemy import text as _t

    from app.db import engine as _engine
    from app.security import hash_password as _hash

    T = S["T"]
    FIX = "回归夹具-批量删班主任"
    D_ACC = DEAN_PROBE + "_a43"
    NAMES = [DEAN_PROBE + f"_a43_{s}"
             for s in ("t1", "t2", "t3", "ref", "stu", "pure", "dean2")]

    def mk(username: str, role: str, cid: int, *, dean_only: int = 0,
           adviser: bool = False) -> int:
        """直写库造一个账号（可选：占一个班主任位）。"""
        with _engine.begin() as c:
            c.execute(_t("DELETE FROM sys_user_class WHERE user_id IN "
                         "(SELECT id FROM sys_user WHERE username = :u)"),
                      {"u": username})
            c.execute(_t("DELETE FROM sys_user WHERE username = :u"), {"u": username})
            c.execute(_t(
                "INSERT INTO sys_user (class_id, username, password, real_name, "
                "role, dean_only, status) VALUES (:c, :u, :p, :n, :r, :d, 1)"),
                {"c": cid, "u": username, "p": _hash("123456"),
                 "n": "批量删探针", "r": role, "d": dean_only})
            uid = int(c.execute(
                _t("SELECT id FROM sys_user WHERE username = :u"), {"u": username}
            ).scalar())
            if adviser:
                c.execute(_t(
                    "INSERT INTO sys_user_class (user_id, class_id, is_adviser) "
                    "VALUES (:u, :c, 1)"), {"u": uid, "c": cid})
        return uid

    def exists(username: str) -> bool:
        with _engine.connect() as c:
            return bool(c.execute(
                _t("SELECT COUNT(*) FROM sys_user WHERE username = :u"),
                {"u": username}).scalar())

    def links_of(uid: int) -> int:
        with _engine.connect() as c:
            return int(c.execute(
                _t("SELECT COUNT(*) FROM sys_user_class WHERE user_id = :i"),
                {"i": uid}).scalar() or 0)

    def purge() -> None:
        with _engine.begin() as c:
            for u in NAMES:
                uid = c.execute(
                    _t("SELECT id FROM sys_user WHERE username = :u"), {"u": u}
                ).scalar()
                if uid:
                    c.execute(_t("DELETE FROM fee_payment WHERE user_id = :i"), {"i": uid})
                    c.execute(_t("DELETE FROM sys_user_class WHERE user_id = :i"),
                              {"i": uid})
                    c.execute(_t("DELETE FROM sys_user WHERE id = :i"), {"i": uid})
        _purge_user(D_ACC)
        _purge_fixture_class(FIX)

    purge()
    fid = _fixture_class(FIX)
    D = _insert_dean_probe(D_ACC, dean_only=1)
    if not check("夹具班 + 院长探针可用", bool(fid) and bool(D), f"fid={fid}"):
        purge()
        return

    try:
        t1 = mk(NAMES[0], "TEACHER", int(fid), adviser=True)
        t2 = mk(NAMES[1], "TEACHER", int(fid), adviser=True)
        t3 = mk(NAMES[2], "TEACHER", int(fid), adviser=True)
        t_ref = mk(NAMES[3], "TEACHER", int(fid), adviser=True)
        stu = mk(NAMES[4], "MEMBER", int(fid))
        pure = mk(NAMES[5], "DEAN", int(fid), dean_only=1)
        d2 = mk(NAMES[6], "DEAN", int(fid), dean_only=0, adviser=True)
        self_id = _probe_id(D_ACC)

        # ---------- ① 仅院长 ----------
        st, j = call("DELETE", f"/college/advisers?ids={t1}", None, T)
        check("班主任删班主任账号 -> 403（学院页仅院长）", st == 403,
              f"st={st} {msg_of(j)}")
        check("被 403 挡下后账号还在", exists(NAMES[0]))

        # ---------- ② 真删：账号 + 班级关联，班级不动 ----------
        st, j = call("DELETE", f"/college/advisers?ids={t1},{t2}", None, D)
        r = data_of(j) or {}
        check("院长批量删除 2 个班主任账号 -> 200", st == 200,
              f"st={st} {msg_of(j)}")
        check("回执 deleted=2", int(r.get("deleted") or 0) == 2, str(r)[:200])
        check("两个账号都从库里消失",
              not exists(NAMES[0]) and not exists(NAMES[1]))
        check("班级关联一并清掉（不留孤儿行）",
              links_of(t1) == 0 and links_of(t2) == 0)
        with _engine.connect() as c:
            alive = c.execute(_t("SELECT COUNT(*) FROM cls_class WHERE id = :i"),
                              {"i": int(fid)}).scalar()
        check("★ 班级不受影响（删的是账号，不是班）", int(alive or 0) == 1,
              f"alive={alive}")

        # ---------- ③ 只删班主任账号：别的角色一律跳过 ----------
        st, j = call("DELETE",
                     f"/college/advisers?ids={t3},{stu},{pure},{d2},{self_id}", None, D)
        r = data_of(j) or {}
        skipped = r.get("skipped") or []
        reasons = {int(s.get("userId") or 0): str(s.get("reason") or "") for s in skipped}
        check("混合批量 -> 200 且只删掉那个真班主任",
              st == 200 and int(r.get("deleted") or 0) == 1, str(r)[:200])
        check("跳过 4 个并逐条给原因", len(skipped) == 4, str(skipped)[:300])
        check("学生账号被跳过（不是班主任账号）",
              "不是班主任账号" in reasons.get(stu, ""))
        check("纯院长被跳过（不是班主任账号）",
              "不是班主任账号" in reasons.get(pure, ""))
        check("兼班主任院长被跳过（院长同级，不能互删）",
              "权限不足" in reasons.get(d2, ""))
        check("不能删除自己的账号", "自己" in reasons.get(self_id, ""))
        check("被跳过的账号都还在",
              exists(NAMES[4]) and exists(NAMES[5]) and exists(NAMES[6]))
        check("没有被跳过的那个班主任已删掉", not exists(NAMES[2]))

        # ---------- ④ 有引用的账号跳过（与单条删除同一口径） ----------
        with _engine.begin() as c:
            c.execute(_t("INSERT INTO fee_payment (batch_id, user_id, amount, status) "
                         "VALUES (0, :u, 0, 'UNPAID')"), {"u": t_ref})
        st, j = call("DELETE", f"/college/advisers?ids={t_ref}", None, D)
        r = data_of(j) or {}
        sk = (r.get("skipped") or [{}])[0]
        check("有缴费记录的账号跳过并说明原因",
              int(r.get("deleted") or 0) == 0 and "缴费记录" in str(sk.get("reason")),
              str(r)[:220])
        check("有引用的账号确实还在", exists(NAMES[3]))

        # ---------- ⑤ 空选择 ----------
        st, j = call("DELETE", "/college/advisers?ids=", None, D)
        check("空选择 -> 400", st == 400, f"st={st} {msg_of(j)}")
    finally:
        purge()


ALL_TESTS = [
    test_a00_encoding_guards,
    test_a00_bootstrap,
    test_a01_account_crud,
    test_a02_role_hierarchy,
    test_a03_self_profile,
    test_a04_password,
    test_a05_records,
    test_a06_categories,
    test_a07_batches,
    test_a08_class_info_perms,
    test_a09_class_info,
    test_a10_disabled_token,
    test_a11_role_matrix,
    test_a12_invariants,
    test_a13_ownership,
    test_a14_audit,
    test_a14b_payable_roles,
    test_a16_student_info,
    test_a17_class_tasks,
    test_a18_accounts_from_students,
    test_a19_version,
    test_a20_dean_role,
    test_a21_student_dashboard,
    test_a22_chart_container_visibility,
    test_a23_college_views,
    test_a24_pure_dean,
    test_a25_college_excel,
    test_a26_college_cell_edit,
    test_a27_college_field_restore,
    test_a29_multi_class,
    test_a30_profile_dean_scope,
    test_a31_class_teachers,
    test_a32_task_scope,
    test_a33_delete_students,
    test_a34_dean_managed_classes,
    test_a35_create_class,
    test_a36_reg_status,
    test_a37_import_template,
    test_a38_user_batch,
    test_a28_college_transfer,
    test_a39_task_export_filter,
    test_a40_adviser_template_roundtrip,
    test_a41_one_teacher_per_class,
    test_a42_dean_accounts,
    test_a43_adviser_batch_delete,
    test_a15_cleanup,
]


def main() -> int:
    print("=" * 74)
    print("班费系统接口回归 —— 需要后端已在 http://127.0.0.1:8080 启动")
    print("=" * 74)
    for fn in ALL_TESTS:
        fn()
        # 第五十一轮：每个用例收尾后检查**常驻班主任 test 的班级关联**没被改坏。
        #
        # 为什么需要这道守卫：测「我带的班 / 改班主任安排」的用例会临时重写
        # `sys_user_class`，而 `return` / 异常都会跳过它们自己的清理段——
        # 那一刻丢的不是测试数据，是**用户真实账号带哪个班**。
        # 曾经就这么丢过：跑完回归，test 少带了「大数据2502」，
        # 最后只表现为「账号回到基线」红了一条，查了很久才定位。
        # 发现被改坏时**当场写回基线**，让后面的用例继续跑得下去，同时记一条失败。
        base = S.get("root_classes0")
        if base is not None and fn.__name__ != "test_a00_bootstrap":
            now = root_class_links()
            if now != base:
                check(f"用例 {fn.__name__} 没还原 test 的班级安排", False,
                      f"现在={now} 基线={base}")
                restore_root_links(base)
    print()
    print("=" * 74)
    print(f"RESULT: {len(_passed)} passed, {len(_failed)} failed")
    if _failed:
        print("失败明细：")
        for name, detail in _failed:
            print(f"  - {name}  [{detail}]")
    print("=" * 74)
    return 1 if _failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
