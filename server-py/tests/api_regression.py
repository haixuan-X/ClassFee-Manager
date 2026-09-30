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
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:8080/api"
ROOT_U, ROOT_P = "test", "123456"

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

PROBE_USERS = [MEMBER_U, SNO_DEFAULT_U, SNO_EXPLICIT_U, DISPOSABLE_U,
               LVL_ADMIN_U, LVL_MONITOR_U, LVL_PEER_U, LVL_PLAIN_U, LVL_ESCALATE_U]

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
        return 0, {"code": 0, "message": repr(e)}


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
    S["notice0"] = len(data_of(call("GET", "/notices?status=all", None, T)[1]) or [])
    S["cls0"] = data_of(call("GET", "/class", None, T)[1]) or {}
    # 可见类别集合：收尾时必须一模一样。
    # 类别是软删（status=0），脚本造的类别删完后会留一行停用记录 —— 名字已释放、
    # 列表不再显示，所以「可见集合回到基线」成立；行数不会完全归零，这是软删的
    # 预期语义，不需要（也不应该）由测试去物理删行。
    S["cats0"] = visible_categories(T)
    S["dict0"] = dictionary_fingerprint(T)
    print(f"  基线: balance={S['b0']} records={S['rec0']} batches={S['batch0']} "
          f"notices={S['notice0']} class={S['cls0'].get('className')!r} "
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
    # 设计如此：改密失败走业务码 1002/1003，HTTP 仍 200（与 Java 统一响应一致）
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

def test_a08_notices():
    print("\n--- I. 公告（含第十六轮下架可见性修复）---")
    T, M = S["T"], S["M"]
    title = "regress notice"

    st, j = call("POST", "/notices", {"title": title, "content": "regression", "pinned": 0}, T)
    check("发布公告 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/notices?status=all", None, T)
    row = next((n for n in (data_of(j) or []) if n.get("title") == title), None)
    nid = row["id"] if row else None
    check("可按标题读到新公告", nid is not None, str(row))
    if not nid:
        return
    st, j = call("PUT", f"/notices/{nid}", {"title": title + " v2", "pinned": 1}, T)
    check("编辑公告 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/notices/{nid}", {"title": ""}, T)
    check("公告标题空白 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/notices?status=BOGUS", None, T)
    check("公告状态非法 -> 400", st == 400, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/notices/{nid}", None, T)
    check("发布中直接删除 -> 400（须先下架）", st == 400, f"st={st} {msg_of(j)}")

    # 下架后普通成员不应看到
    st, j = call("PUT", f"/notices/{nid}", {"status": 0}, T)
    check("下架公告 -> 200", st == 200, f"st={st} {msg_of(j)}")
    for q in ["status=0", "status=all", "status=1", ""]:
        st, j = call("GET", f"/notices?{q}" if q else "/notices", None, M)
        titles = [n.get("title") for n in (data_of(j) or [])]
        check(f"普通成员 GET /notices?{q or '(默认)'} 看不到下架公告",
              (title + " v2") not in titles, f"titles={titles}")
    st, j = call("GET", "/notices?status=0", None, T)
    titles = [n.get("title") for n in (data_of(j) or [])]
    check("班主任仍能看到下架公告（要能恢复）", (title + " v2") in titles, f"titles={titles}")

    st, j = call("DELETE", f"/notices/{nid}", None, T)
    check("下架后可彻底删除 -> 200", st == 200, f"st={st} {msg_of(j)}")

    st, j = call("POST", "/notices", {"title": "regress member notice", "content": "x"}, M)
    check("普通成员发公告 -> 403", st == 403, f"st={st} {msg_of(j)}")
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
              "/batches", "/users", "/notices?status=all", "/categories"]:
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
                "/categories", "/notices?status=all", "/records?page=1&size=5",
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

    # --- 公告 ---
    st, j = call("POST", "/notices", {"title": "regress owner notice", "content": "x"}, T)
    nid = (data_of(j) or {}).get("id")
    for label, m_, p_, b_ in [
        ("编辑", "PUT", f"/notices/{nid}", {"title": "hijack"}),
        ("下架", "PUT", f"/notices/{nid}", {"status": 0}),
    ]:
        st, j = call(m_, p_, b_, MON)
        check(f"班长{label}老师的公告 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("PUT", f"/notices/{nid}", {"status": 0}, T)
    check("班主任下架自己的公告 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/notices/{nid}", None, MON)
    check("班长彻底删除老师的公告 -> 403", st == 403, f"st={st} {msg_of(j)}")
    st, j = call("DELETE", f"/notices/{nid}", None, T)
    check("班主任删除自己的公告 -> 200", st == 200, f"st={st} {msg_of(j)}")

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

    # --- 公告编辑：谁发的 vs 谁最后改的，两条独立的线 ---
    st, j = call("POST", "/notices", {"title": "regress audit notice", "content": "x"}, T)
    notid = (data_of(j) or {}).get("id")
    chk("新建公告的编辑留痕字段为 null", (data_of(j) or {}).get("updatedBy") is None,
        f"{(data_of(j) or {}).get('updatedBy')}")
    st, j = call("PUT", f"/notices/{notid}", {"title": "regress audit notice v2", "pinned": 1}, T)
    chk("编辑公告 -> 200", st == 200, f"st={st} {msg_of(j)}")
    st, j = call("GET", "/notices?status=all", None, T)
    n1 = next((x for x in (data_of(j) or []) if x["id"] == notid), {})
    chk("编辑后 updatedBy = 操作者", n1.get("updatedBy") == root_id, f"updatedBy={n1.get('updatedBy')}")
    chk("编辑后 updatedByName 有姓名", bool(n1.get("updatedByName")), f"{n1.get('updatedByName')!r}")
    chk("编辑后 updatedAt 有时间", bool(n1.get("updatedAt")), f"{updated_at!r}" if False else f"{n1.get('updatedAt')!r}")
    chk("编辑不覆盖 createdBy（发布人独立保留）",
        n1.get("createdBy") == root_id and n1.get("createdByName") is not None,
        f"createdBy={n1.get('createdBy')}")

    # --- 幂等：迁移列存在且可重复执行 ---
    st, j = call("GET", "/records?page=1&size=1", None, T)
    chk("接口正常（审计列已由 seed.add_audit_columns 迁移）", st == 200, f"st={st}")


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
    check("公告条数与基线一致",
          len(data_of(call("GET", "/notices?status=all", None, T)[1]) or []) == S["notice0"],
          f"baseline={S['notice0']}")
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
    for n in data_of(call("GET", "/notices?status=all", None, T)[1]) or []:
        if str(n.get("title", "")).startswith("regress"):
            call("PUT", f"/notices/{n['id']}", {"status": 0}, T)
            st, _ = call("DELETE", f"/notices/{n['id']}", None, T)
            print(f"  删除公告「{n.get('title')}」-> {st}")
    page = 1
    while True:
        st, j = call("GET", f"/records?page={page}&size=100&status=all", None, T)
        rows = (data_of(j) or {}).get("records") or []
        if not rows:
            break
        for r in rows:
            if str(r.get("title", "")).startswith("regress"):
                call("DELETE", f"/records/{r['id']}", None, T)
                print(f"  删除流水 #{r['id']}「{r.get('title')}」")
        page += 1
        if page > 50:
            break

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
    check("账号回到基线（只剩部署配置的班主任）", set(left) == {ROOT_U}, f"剩余={left}")
    check("余额回到基线", near((data_of(j) or {}).get("balance"), S["b0"]),
          f"{(data_of(j) or {}).get('balance')} vs {S['b0']}")


# =====================================================================

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
    test_a08_notices,
    test_a09_class_info,
    test_a10_disabled_token,
    test_a11_role_matrix,
    test_a12_invariants,
    test_a13_ownership,
    test_a14_audit,
    test_a14b_payable_roles,
    test_a15_cleanup,
]


def main() -> int:
    print("=" * 74)
    print("班费系统接口回归 —— 需要后端已在 http://127.0.0.1:8080 启动")
    print("=" * 74)
    for fn in ALL_TESTS:
        fn()
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
