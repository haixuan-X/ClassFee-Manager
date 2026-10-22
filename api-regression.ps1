# API regression (accounts / records / batches / categories / receipts).
# Account model (round 9): no account is hard-coded and there is no sign-up page.
# The teacher (ops) account is declared in deployment config via
# CLASSFEE_TEACHER_USERNAME / CLASSFEE_TEACHER_PASSWORD and created at startup
# only when absent (existing accounts are never overwritten); student accounts
# are created by the teacher via POST /api/users. The script below logs in with
# an existing ops account and self-bootstraps its own member account. Money data
# is net-zero inside the script. Test member accounts persist after the run by
# design (no physical delete API).
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$base = 'http://localhost:8080/api'
$RootU = 'test'       # ops account (TEACHER; ADMIN also accepted)
$RootP = '123456'
$MemberU = '20220103'  # test member (MEMBER = read-only)
$MemberP = '123456'
$MemberName = 'Wang Xiaoming'
$script:pass = 0
$script:fail = 0

function Invoke-Api($method, $path, $body, $token) {
    $h = @{}
    if ($token) { $h['Authorization'] = "Bearer $token" }
    $p = @{ Uri = "$base$path"; Method = $method; Headers = $h; UseBasicParsing = $true }
    if ($null -ne $body) {
        $p['ContentType'] = 'application/json; charset=utf-8'
        $p['Body'] = [System.Text.Encoding]::UTF8.GetBytes(($body | ConvertTo-Json -Depth 6 -Compress))
    }
    try {
        $r = Invoke-WebRequest @p
        $sr = New-Object System.IO.StreamReader($r.RawContentStream, [System.Text.Encoding]::UTF8)
        $text = $sr.ReadToEnd(); $sr.Dispose()
        $j = $null
        if ($text) { try { $j = $text | ConvertFrom-Json } catch {} }
        return @{ status = [int]$r.StatusCode; j = $j }
    } catch {
        $resp = $_.Exception.Response
        $status = 0
        $j = $null
        if ($resp) {
            $status = [int]$resp.StatusCode
            try {
                $sr = New-Object System.IO.StreamReader($resp.GetResponseStream(), [System.Text.Encoding]::UTF8)
                $text = $sr.ReadToEnd(); $sr.Dispose()
                if ($text) { try { $j = $text | ConvertFrom-Json } catch {} }
            } catch {}
        }
        return @{ status = $status; j = $j }
    }
}

function OK($name, $cond, $detail) {
    if ($cond) { $script:pass++; Write-Host "  [PASS] $name" }
    else { $script:fail++; Write-Host "  [FAIL] $name :: $detail" -ForegroundColor Red }
}
function Near($a, $b) { [math]::Abs([double]$a - [double]$b) -lt 0.005 }

# ---------- A: bootstrap ops/member account + account management ----------
$ra = Invoke-Api POST '/auth/login' @{ username = $RootU; password = $RootP }
$A = $ra.j.data.token
OK 'login ops account (TEACHER/ADMIN)' ($A -and ($ra.j.data.user.role -in @('ADMIN', 'TEACHER'))) "st=$($ra.status) role=$($ra.j.data.user.role)"
if (-not $A) { exit 1 }

# member account: reuse when loginable, otherwise create (or repair) via /api/users
$created = $false
$rm = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = $MemberP }
if ($rm.status -ne 200) {
    $cr = Invoke-Api POST '/users' @{ username = $MemberU; realName = $MemberName; password = $MemberP } $A
    $created = ($cr.status -eq 200)
    if (-not $created -and $cr.status -ne 400) {
        OK 'TEACHER create member -> 200' $false "st=$($cr.status) msg=$($cr.j.message)"
    }
    if (-not $created) {
        # exists but unusable (wrong password / disabled): repair via reset+enable
        $userRows = @((Invoke-Api GET '/users' $null $A).j.data)
        $mid0 = @($userRows | Where-Object { $_.username -eq $MemberU })[0].id
        $null = Invoke-Api PUT "/users/$mid0" @{ password = $MemberP; status = 1 } $A
    }
    $rm = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = $MemberP }
    if ($created) {
        OK 'TEACHER create member -> 200 + auto login' ($rm.status -eq 200) "login=$($rm.status) msg=$($rm.j.message)"
    } else {
        OK 'existing member repaired (reset+enable) and loginable' ($rm.status -eq 200) "login=$($rm.status)"
    }
} else {
    OK 'existing member account reused' $true $MemberU
}
$M = $rm.j.data.token
OK 'login member' ($null -ne $M) "st=$($rm.status)"
if (-not $M) { exit 1 }
$mId = $rm.j.data.user.id
$rId = $ra.j.data.user.id

# duplicate username -> 400
$dup = Invoke-Api POST '/users' @{ username = $MemberU; realName = 'Duplicate' } $A
OK 'duplicate account -> 400' ($dup.status -eq 400) "st=$($dup.status)"

# list contains ops + member
$ulist = @((Invoke-Api GET '/users' $null $A).j.data)
$hasOps = @($ulist | Where-Object { $_.username -eq $RootU }).Count -gt 0
$hasMember = @($ulist | Where-Object { $_.username -eq $MemberU }).Count -gt 0
OK 'GET /users lists ops+member' ($hasOps -and $hasMember) "count=$($ulist.Count) ops=$hasOps member=$hasMember"

# MEMBER forbidden on /users (read / create / update)
$u403a = Invoke-Api GET '/users' $null $M
$u403b = Invoke-Api POST '/users' @{ username = 'nope1'; realName = 'Nope' } $M
$u403c = Invoke-Api PUT "/users/$mId" @{ realName = 'Nope' } $M
OK 'MEMBER list accounts -> 403' ($u403a.status -eq 403) "st=$($u403a.status)"
OK 'MEMBER create account -> 403' ($u403b.status -eq 403) "st=$($u403b.status)"
OK 'MEMBER update account -> 403' ($u403c.status -eq 403) "st=$($u403c.status)"

# edit name + phone
$ed = Invoke-Api PUT "/users/$mId" @{ realName = 'Li Xiaoming'; phone = '13800001111' } $A
OK 'edit name+phone -> 200' ($ed.status -eq 200 -and $ed.j.data.phone -eq '13800001111') "st=$($ed.status) phone=$($ed.j.data.phone)"

# phone must be kept when omitted (regression for the None-vs-empty validator bug)
$ed2 = Invoke-Api PUT "/users/$mId" @{ realName = $MemberName } $A
OK 'phone kept when omitted' ($ed2.status -eq 200 -and $ed2.j.data.phone -eq '13800001111') "st=$($ed2.status) phone=$($ed2.j.data.phone)"

# empty phone string clears it; name restored by the same call
$ed3 = Invoke-Api PUT "/users/$mId" @{ phone = '' } $A
OK 'empty phone clears field' ($ed3.status -eq 200 -and $null -eq $ed3.j.data.phone) "st=$($ed3.status) phone=$($ed3.j.data.phone)"

# studentNo: defaults to the username for MEMBER, can be set explicitly, edited and cleared
# 专用测试账号跨轮复用（无删除接口）：不存在才创建，存在则复用——保证脚本可重复执行
$snoU = '20220997'
$snoList = @((Invoke-Api GET "/users?keyword=$snoU" $null $A).j.data)
$snoRow = @($snoList | Where-Object { $_.username -eq $snoU })[0]
$snDefaultId = $snoRow.id
if ($snDefaultId) {
    OK 'studentNo test account reused' $true $snoU
} else {
    $snNew = Invoke-Api POST '/users' @{ username = $snoU; realName = 'Sn Default' } $A
    $snDefaultId = $snNew.j.data.id
    OK 'studentNo defaults to username (MEMBER)' (($snNew.status -eq 200) -and ($snNew.j.data.studentNo -eq $snoU)) "st=$($snNew.status) studentNo=$($snNew.j.data.studentNo)"
}
# 创建时显式指定学号（与登录名不同）：同样跨轮复用
$sneU = '20220995'
$sneList = @((Invoke-Api GET "/users?keyword=$sneU" $null $A).j.data)
$sneRow = @($sneList | Where-Object { $_.username -eq $sneU })[0]
if ($sneRow) {
    OK 'explicit studentNo kept on reuse' ($sneRow.studentNo -eq 'S-20220995') "studentNo=$($sneRow.studentNo)"
} else {
    $snExp = Invoke-Api POST '/users' @{ username = $sneU; realName = 'Sn Explicit'; studentNo = 'S-20220995' } $A
    OK 'create with explicit studentNo -> 200' (($snExp.status -eq 200) -and ($snExp.j.data.studentNo -eq 'S-20220995')) "st=$($snExp.status) studentNo=$($snExp.j.data.studentNo)"
}
# 校验与唯一性都放在更新路径上断言（跨轮幂等，不依赖「账号不存在」）
$snLong = Invoke-Api PUT "/users/$snDefaultId" @{ studentNo = ('9' * 21) } $A
OK 'studentNo >20 -> 400' ($snLong.status -eq 400) "st=$($snLong.status)"
$snSet = Invoke-Api PUT "/users/$mId" @{ studentNo = 'S-2022-0103' } $A
OK 'edit studentNo -> 200' (($snSet.status -eq 200) -and ($snSet.j.data.studentNo -eq 'S-2022-0103')) "st=$($snSet.status) sn=$($snSet.j.data.studentNo)"
$snDupUpd = Invoke-Api PUT "/users/$snDefaultId" @{ studentNo = 'S-2022-0103' } $A
OK 'studentNo collides within class -> 400' ($snDupUpd.status -eq 400) "st=$($snDupUpd.status)"
$snKeep = Invoke-Api PUT "/users/$mId" @{ realName = $MemberName } $A
OK 'studentNo kept when omitted' (($snKeep.status -eq 200) -and ($snKeep.j.data.studentNo -eq 'S-2022-0103')) "sn=$($snKeep.j.data.studentNo)"
$snClear = Invoke-Api PUT "/users/$mId" @{ studentNo = '' } $A
OK 'empty studentNo clears field' (($snClear.status -eq 200) -and ($null -eq $snClear.j.data.studentNo)) "sn=$($snClear.j.data.studentNo)"
# studentNo restored
$snRestore = Invoke-Api PUT "/users/$mId" @{ studentNo = $MemberU } $A
OK 'studentNo restored' (($snRestore.status -eq 200) -and ($snRestore.j.data.studentNo -eq $MemberU)) "sn=$($snRestore.j.data.studentNo)"

# delete: only accounts with zero history may be removed (self / referenced / role are rejected)
$delSelf = Invoke-Api DELETE "/users/$rId" $null $A
OK 'delete self -> 400' ($delSelf.status -eq 400) "st=$($delSelf.status)"
# ops account has created records/notices -> must be rejected with a reason
$delReferenced = Invoke-Api DELETE "/users/$rId" $null $A
OK 'delete account with history -> 400' ($delReferenced.status -eq 400) "st=$($delReferenced.status) msg=$($delReferenced.j.message)"
# disposable account: created then deleted, so the script stays net-zero and repeatable
$delU = '20220993'
$delRows = @((Invoke-Api GET "/users?keyword=$delU" $null $A).j.data)
$delRow = @($delRows | Where-Object { $_.username -eq $delU })[0]
if ($delRow) { $null = Invoke-Api DELETE "/users/$($delRow.id)" $null $A }   # leftover from an interrupted run
$mkDel = Invoke-Api POST '/users' @{ username = $delU; realName = 'Del Probe' } $A
$delId = $mkDel.j.data.id
OK 'disposable account created' (($mkDel.status -eq 200) -and ($null -ne $delId)) "st=$($mkDel.status) id=$delId"
$delMem = Invoke-Api DELETE "/users/$mId" $null $M
OK 'MEMBER delete account -> 403' ($delMem.status -eq 403) "st=$($delMem.status)"
$delClean = Invoke-Api DELETE "/users/$delId" $null $A
$afterDel = @((Invoke-Api GET "/users?keyword=$delU" $null $A).j.data)
OK 'delete zero-history account -> 200' ($delClean.status -eq 200) "st=$($delClean.status) msg=$($delClean.j.message)"
OK 'deleted account is gone' ($afterDel.Count -eq 0) "count=$($afterDel.Count)"
$delMissing = Invoke-Api DELETE '/users/99999999' $null $A
OK 'delete missing account -> 400' ($delMissing.status -eq 400) "st=$($delMissing.status)"

# no-op body -> 400
$eb = Invoke-Api PUT "/users/$mId" @{} $A
OK 'empty update body -> 400' ($eb.status -eq 400) "st=$($eb.status)"

# missing account -> 400
$mi = Invoke-Api PUT '/users/99999999' @{ realName = 'Nobody' } $A
OK 'update missing account -> 400' ($mi.status -eq 400) "st=$($mi.status)"

# self lockout guard
$sd = Invoke-Api PUT "/users/$rId" @{ status = 0 } $A
OK 'self disable -> 400' ($sd.status -eq 400) "st=$($sd.status)"

# password reset cycle: old rejected (401), new accepted (200)
$rp = Invoke-Api PUT "/users/$mId" @{ password = '654321' } $A
$oldRej = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = $MemberP }
$newOk = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = '654321' }
OK 'reset password: old pw rejected' ($rp.status -eq 200 -and $oldRej.status -eq 401) "reset=$($rp.status) old=$($oldRej.status)"
OK 'reset password: new pw logs in' ($newOk.status -eq 200) "st=$($newOk.status)"
$null = Invoke-Api PUT "/users/$mId" @{ password = $MemberP } $A   # restore

# disable / enable cycle
$null = Invoke-Api PUT "/users/$mId" @{ status = 0 } $A
$dl = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = $MemberP }
OK 'disabled account cannot login (403)' ($dl.status -eq 403) "st=$($dl.status)"
$en = Invoke-Api PUT "/users/$mId" @{ status = 1 } $A
$rl = Invoke-Api POST '/auth/login' @{ username = $MemberU; password = $MemberP }
OK 'enabled account logs in again' ($en.status -eq 200 -and $rl.status -eq 200) "en=$($en.status) login=$($rl.status)"
$M = $rl.j.data.token

# ---------- T: self-service profile (GET/PUT /auth/profile, every role) ----------
# 设计要点：读写都只认登录令牌里的 id（请求体没有 id），角色/状态/登录名不在可改范围。
# 因此断言重点是：普通成员能用、能读到自己学号、能改自己三字段、越权字段无效、
# 值语义与运营编辑一致。
$pReadAnon = Invoke-Api GET '/auth/profile' $null $null
OK 'profile read without token -> 401' ($pReadAnon.status -eq 401) "st=$($pReadAnon.status)"
# 普通成员必须能读到自己的学号/手机号（早期版本靠 /api/users 取，普通成员 403 会导致读不到）
$pReadMe = Invoke-Api GET '/auth/profile' $null $M
OK 'MEMBER reads own profile (studentNo included)' (($pReadMe.status -eq 200) -and ($pReadMe.j.data.username -eq $MemberU) -and ($null -ne $pReadMe.j.data.studentNo)) "st=$($pReadMe.status) sn=$($pReadMe.j.data.studentNo)"
# 读到的必须是自己：role/status 与自己一致
OK 'profile read returns own row only' (($pReadMe.j.data.role -eq 'MEMBER') -and ($pReadMe.j.data.id -gt 0)) "id=$($pReadMe.j.data.id) role=$($pReadMe.j.data.role)"

$pAnon = Invoke-Api PUT '/auth/profile' @{ realName = 'No Token' } $null
OK 'profile without token -> 401' ($pAnon.status -eq 401) "st=$($pAnon.status)"

# 普通成员改自己的姓名（这是本轮的核心诉求：学生也能自助修改）
# 字面量保持纯 ASCII：PS 5.1 按 ANSI 读本文件，含中文会被解成乱码
$selfName = 'ProfileSelf'
$pSelf = Invoke-Api PUT '/auth/profile' @{ realName = $selfName } $M
OK 'MEMBER updates own realName -> 200' (($pSelf.status -eq 200) -and ($pSelf.j.data.realName -eq $selfName)) "st=$($pSelf.status) name=$($pSelf.j.data.realName)"
# 姓名立即生效：/auth/me 与登录都应看到新名字
$pMe = Invoke-Api GET '/auth/me' $null $M
OK 'profile change visible on /auth/me' (($pMe.status -eq 200) -and ($pMe.j.data.realName -eq $selfName)) "me=$($pMe.j.data.realName)"

# 空体 / 姓名空白 -> 400
$pEmpty = Invoke-Api PUT '/auth/profile' @{} $M
OK 'profile empty body -> 400' ($pEmpty.status -eq 400) "st=$($pEmpty.status)"
$pBlank = Invoke-Api PUT '/auth/profile' @{ realName = '   ' } $M
OK 'profile blank realName -> 400' ($pBlank.status -eq 400) "st=$($pBlank.status)"

# 越权字段一律无效：id 指向别人、role/status/username 想改自己，全部不生效
$pPriv = Invoke-Api PUT '/auth/profile' @{ realName = $selfName; id = 99999; role = 'ADMIN'; status = 0; username = 'hijack'; classId = 2 } $M
$privRow = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $MemberU })[0]
OK 'profile ignores id/role/status/username' (($pPriv.status -eq 200) -and ($privRow.role -eq 'MEMBER') -and ($privRow.username -eq $MemberU) -and ($privRow.status -eq 1)) "st=$($pPriv.status) role=$($privRow.role) user=$($privRow.username) status=$($privRow.status)"

# 长度上限与学号唯一（与运营编辑同口径）
$pSnLong = Invoke-Api PUT '/auth/profile' @{ studentNo = ('9' * 21) } $M
OK 'profile studentNo >20 -> 400' ($pSnLong.status -eq 400) "st=$($pSnLong.status)"
$pPhLong = Invoke-Api PUT '/auth/profile' @{ phone = ('1' * 21) } $M
OK 'profile phone >20 -> 400' ($pPhLong.status -eq 400) "st=$($pPhLong.status)"

# 学号同班唯一：先给另一个号占一个学号，再让本人抢同一个 -> 400
$pSnTake = Invoke-Api PUT '/auth/profile' @{ studentNo = 'P-2022-9001' } $M
OK 'profile studentNo set -> 200' ($pSnTake.status -eq 200) "st=$($pSnTake.status)"
$pSnDup = Invoke-Api PUT "/users/$rId" @{ studentNo = 'P-2022-9001' } $A
OK 'profile studentNo blocks duplicate in class -> 400' ($pSnDup.status -eq 400) "st=$($pSnDup.status)"
# 自己重设成同一个学号必须放行（唯一性校验要排除自己）
$pSnSelf = Invoke-Api PUT '/auth/profile' @{ studentNo = 'P-2022-9001' } $M
OK 'profile studentNo same value allowed (excludes self)' ($pSnSelf.status -eq 200) "st=$($pSnSelf.status)"

# 空串清空 + 复原（保持脚本跨轮幂等）
$pPhSet = Invoke-Api PUT '/auth/profile' @{ phone = '13900001234' } $M
OK 'profile phone set -> 200' ($pPhSet.status -eq 200) "st=$($pPhSet.status)"
$pPhClear = Invoke-Api PUT '/auth/profile' @{ phone = '' } $M
$phRow = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $MemberU })[0]
OK 'profile empty phone clears field' (($pPhClear.status -eq 200) -and ($null -eq $phRow.phone)) "st=$($pPhClear.status) phone=$($phRow.phone)"
# studentNo omitted -> kept
$pKeep = Invoke-Api PUT '/auth/profile' @{ realName = $selfName } $M
$snRow = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $MemberU })[0]
OK 'profile studentNo kept when omitted' (($pKeep.status -eq 200) -and ($snRow.studentNo -eq 'P-2022-9001')) "sn=$($snRow.studentNo)"

# 复原姓名与学号到脚本基线
$null = Invoke-Api PUT '/auth/profile' @{ realName = $MemberName; studentNo = $MemberU } $M
$restored = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $MemberU })[0]
OK 'profile restored to baseline' (($restored.realName -eq $MemberName) -and ($restored.studentNo -eq $MemberU)) "name=$($restored.realName) sn=$($restored.studentNo)"
# GET /auth/profile 读回的必须是复原后的值（前端刷新页面靠它）
$pReadBack = Invoke-Api GET '/auth/profile' $null $M
OK 'profile read reflects saved values' (($pReadBack.j.data.realName -eq $MemberName) -and ($pReadBack.j.data.studentNo -eq $MemberU)) "name=$($pReadBack.j.data.realName) sn=$($pReadBack.j.data.studentNo)"

# 运营角色同样能用本接口（改自己，不是改别人）
# 注意顺序：**先**读原值再改，否则复原时读到的是刚改过的值，会把真实姓名覆盖掉
$rootRow = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $RootU })[0]
$rootNameBefore = $rootRow.realName
$pOps = Invoke-Api PUT '/auth/profile' @{ realName = 'Root Self' } $A
OK 'TEACHER updates own profile -> 200' (($pOps.status -eq 200) -and ($pOps.j.data.realName -eq 'Root Self')) "st=$($pOps.status)"
$null = Invoke-Api PUT '/auth/profile' @{ realName = $rootNameBefore } $A
$rootAfter = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $RootU })[0]
OK 'ops profile restored to original name' ($rootAfter.realName -eq $rootNameBefore) "before=[$rootNameBefore] after=[$($rootAfter.realName)]"

# ---------- T2: account-management role hierarchy (TEACHER > MONITOR > ADMIN > MEMBER) ----------
# 背景：第十四轮加「班长」时让三个运营角色同权，结果班长/生活委员能停用、删除班主任账号。
# 第十五轮引入等级 LEVEL：编辑资料 / 重置密码 / 停用 / 删除 都要求操作者**严格高于**目标
# （同级也不能互管）；新建账号时角色不得高于自己——那是唯一的提权入口
# （「建一个班主任账号再登进去」能绕开所有护栏）。
# 探针账号用固定学号跨轮复用，结尾随 Q 段一起删除，脚本保持净零。
# 字面量保持纯 ASCII：PS 5.1 按 ANSI 读本文件，含中文会被解成乱码。
$LV = @{ MEMBER = 0; ADMIN = 1; MONITOR = 2; TEACHER = 3 }
$rootRole2 = $ra.j.data.user.role
$rootLv = $LV[$rootRole2]
$hAdm = '20220991'    # life committee member, level 1
$hMon = '20220992'    # class monitor, level 2
$hMem = '20220994'    # plain member, level 0
$hMon2 = '20220989'   # second monitor, for the same-level case
$hEsc = '20220988'    # ADMIN created by MONITOR (positive control, deleted inline)

function Get-ProbeId($u) {
    return @((Invoke-Api GET "/users?keyword=$u" $null $A).j.data | Where-Object { $_.username -eq $u })[0].id
}
function Ensure-Probe($u, $role) {
    $id = Get-ProbeId $u
    if ($id) { return $id }
    $r = Invoke-Api POST '/users' @{ username = $u; realName = 'Probe'; password = '123456'; role = $role } $A
    if ($r.status -eq 200) { return $r.j.data.id }
    $script:fail++
    Write-Host "  [FAIL] probe account $u ($role) not created :: st=$($r.status) msg=$($r.j.message)" -ForegroundColor Red
    return $null
}

if ($rootLv -ge 3) {
    $hAdmId = Ensure-Probe $hAdm 'ADMIN'
    $hMonId = Ensure-Probe $hMon 'MONITOR'
    $hMemId = Ensure-Probe $hMem 'MEMBER'
    $hMon2Id = Ensure-Probe $hMon2 'MONITOR'
    OK 'hierarchy probe accounts ready' ($hAdmId -and $hMonId -and $hMemId -and $hMon2Id) "adm=$hAdmId mon=$hMonId mem=$hMemId mon2=$hMon2Id"

    $lgAdm = Invoke-Api POST '/auth/login' @{ username = $hAdm; password = '123456' }
    $lgMon = Invoke-Api POST '/auth/login' @{ username = $hMon; password = '123456' }
    $tAdm = $lgAdm.j.data.token
    $tMon = $lgMon.j.data.token
    OK 'hierarchy probe accounts log in' (($tAdm -and $tMon)) "adm=$($lgAdm.status) mon=$($lgMon.status)"

    # 越级：班长对班主任的四类账号管理动作全被拒（班主任就是本脚本的 ops 账号）
    $rootNameBefore = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $RootU })[0].realName
    $e1 = Invoke-Api PUT "/users/$rId" @{ realName = 'Hijacked' } $tMon
    $e2 = Invoke-Api PUT "/users/$rId" @{ status = 0 } $tMon
    $e3 = Invoke-Api DELETE "/users/$rId" $null $tMon
    $e4 = Invoke-Api PUT "/users/$rId" @{ password = 'hijack999' } $tMon
    OK 'MONITOR edit TEACHER -> 400' ($e1.status -eq 400) "st=$($e1.status) msg=$($e1.j.message)"
    OK 'MONITOR disable TEACHER -> 400' ($e2.status -eq 400) "st=$($e2.status) msg=$($e2.j.message)"
    OK 'MONITOR delete TEACHER -> 400' ($e3.status -eq 400) "st=$($e3.status) msg=$($e3.j.message)"
    OK 'MONITOR reset TEACHER password -> 400' ($e4.status -eq 400) "st=$($e4.status) msg=$($e4.j.message)"
    # 被拒的请求必须「什么都没改」：姓名没变、没被停用、旧密码仍有效
    $rootAfter = @((Invoke-Api GET '/users' $null $A).j.data | Where-Object { $_.username -eq $RootU })[0]
    $rootRelogin = Invoke-Api POST '/auth/login' @{ username = $RootU; password = $RootP }
    OK 'rejected MONITOR actions left TEACHER untouched' (($rootAfter.realName -eq $rootNameBefore) -and ($rootAfter.status -eq 1) -and ($rootRelogin.status -eq 200)) "name=[$($rootAfter.realName)] status=$($rootAfter.status) relogin=$($rootRelogin.status)"

    # 越级：生活委员动班长（低等级不能改高等级）
    $e5 = Invoke-Api PUT "/users/$hMonId" @{ realName = 'Hijacked' } $tAdm
    $e6 = Invoke-Api DELETE "/users/$hMonId" $null $tAdm
    OK 'ADMIN edit MONITOR -> 400' ($e5.status -eq 400) "st=$($e5.status) msg=$($e5.j.message)"
    OK 'ADMIN delete MONITOR -> 400' ($e6.status -eq 400) "st=$($e6.status) msg=$($e6.j.message)"

    # 同级：班长不能管理另一个班长（避免同等级互踢）
    $e7 = Invoke-Api PUT "/users/$hMon2Id" @{ realName = 'Hijacked' } $tMon
    $e8 = Invoke-Api DELETE "/users/$hMon2Id" $null $tMon
    $e9 = Invoke-Api PUT "/users/$hMon2Id" @{ password = 'hijack999' } $tMon
    OK 'MONITOR edit peer MONITOR -> 400' ($e7.status -eq 400) "st=$($e7.status) msg=$($e7.j.message)"
    OK 'MONITOR delete peer MONITOR -> 400' ($e8.status -eq 400) "st=$($e8.status) msg=$($e8.j.message)"
    OK 'MONITOR reset peer MONITOR password -> 400' ($e9.status -eq 400) "st=$($e9.status) msg=$($e9.j.message)"

    # 新建账号不得高于自己（唯一提权入口）
    $n1 = Invoke-Api POST '/users' @{ username = '20220987'; realName = 'Esc'; password = '123456'; role = 'TEACHER' } $tAdm
    $n2 = Invoke-Api POST '/users' @{ username = '20220986'; realName = 'Esc'; password = '123456'; role = 'TEACHER' } $tMon
    $n3 = Invoke-Api POST '/users' @{ username = '20220985'; realName = 'Esc'; password = '123456'; role = 'MONITOR' } $tAdm
    OK 'ADMIN create TEACHER -> 400' ($n1.status -eq 400) "st=$($n1.status) msg=$($n1.j.message)"
    OK 'MONITOR create TEACHER -> 400' ($n2.status -eq 400) "st=$($n2.status) msg=$($n2.j.message)"
    OK 'ADMIN create MONITOR -> 400' ($n3.status -eq 400) "st=$($n3.status) msg=$($n3.j.message)"

    # 正向对照：只能建**不高于**自己的角色（班长建生活委员放行）
    $n4 = Invoke-Api POST '/users' @{ username = $hEsc; realName = 'Life'; password = '123456'; role = 'ADMIN' } $tMon
    OK 'MONITOR create ADMIN -> 200 (lower role allowed)' ($n4.status -eq 200) "st=$($n4.status) msg=$($n4.j.message)"
    if ($n4.status -eq 200) { $null = Invoke-Api DELETE "/users/$($n4.j.data.id)" $null $A }

    # 正向对照：管理低等级放行（每一级都能管比自己低的）
    $a1 = Invoke-Api PUT "/users/$hAdmId" @{ realName = 'Managed' } $tMon
    OK 'MONITOR edit ADMIN -> 200' ($a1.status -eq 200) "st=$($a1.status) msg=$($a1.j.message)"
    $a2 = Invoke-Api PUT "/users/$hMemId" @{ realName = 'Managed' } $tAdm
    OK 'ADMIN edit MEMBER -> 200' ($a2.status -eq 200) "st=$($a2.status) msg=$($a2.j.message)"
    $a3 = Invoke-Api PUT "/users/$hMonId" @{ realName = 'Managed' } $A
    OK 'TEACHER edit MONITOR -> 200' ($a3.status -eq 200) "st=$($a3.status) msg=$($a3.j.message)"
    # 复原探针姓名（用刚才成功的那个操作者复原，符合同一套护栏）
    $null = Invoke-Api PUT "/users/$hAdmId" @{ realName = 'Probe' } $tMon
    $null = Invoke-Api PUT "/users/$hMemId" @{ realName = 'Probe' } $tAdm
    $null = Invoke-Api PUT "/users/$hMonId" @{ realName = 'Probe' } $A
} else {
    Write-Host "HIER: skipped (ops account role=$rootRole2 is not the top of the hierarchy)"
}

# ---------- baseline (money) ----------
$sum = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
$b0 = [double]$sum.balance; $rb0 = [double]$sum.realBalance; $r0 = [double]$sum.completionRate
$total0 = (Invoke-Api GET '/records?page=1&size=1' $null $A).j.data.total
$batches0 = @((Invoke-Api GET '/batches' $null $A).j.data).Count
$notices0 = @((Invoke-Api GET '/notices?status=all' $null $A).j.data).Count
Write-Host "BASE balance=$b0 real=$rb0 rate=$r0 records=$total0 batches=$batches0 notices=$notices0"

# ---------- D/E: delete NORMAL record (balance rollback) ----------
$cats = @((Invoke-Api GET '/categories?kind=EXPENSE' $null $A).j.data)
$expCat = $cats[0].id
$rec = (Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 10; title = 'E2E delete probe'; occurredAt = '2026-09-26 10:00:00'; channel = 'CASH' } $A).j
$rid1 = $rec.data.id
OK 'create expense probe record' ($null -ne $rid1) "resp=$($rec.code)"
$s1 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance -10 after expense create' (Near $s1.balance ($b0 - 10)) "got=$($s1.balance)"
$d1 = Invoke-Api DELETE "/records/$rid1" $null $A
OK 'DELETE normal record 200' ($d1.status -eq 200) "status=$($d1.status) msg=$($d1.j.message)"
$s2 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance restored after delete' (Near $s2.balance $b0) "got=$($s2.balance)"
OK 'realBalance == balance' (Near $s2.realBalance $s2.balance) "real=$($s2.realBalance)"

# ---------- F: delete VOID record (no balance move) ----------
$rid2 = (Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 7.5; title = 'E2E void probe'; occurredAt = '2026-09-26 10:05:00'; channel = 'CASH' } $A).j.data.id
$vd = Invoke-Api POST "/records/$rid2/void" $null $A
$vf = Invoke-Api GET "/records?id=$rid2&size=5" $null $A
$vstatus = @($vf.j.data.records)[0].status
OK 'void probe -> VOID' ($vd.status -eq 200 -and $vstatus -eq 'VOID') "st=$($vd.status) status=$vstatus"
$sv = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance kept after void' (Near $sv.balance $b0) "got=$($sv.balance)"
$d2 = Invoke-Api DELETE "/records/$rid2" $null $A
$vf2 = Invoke-Api GET "/records?id=$rid2&size=5" $null $A
OK 'DELETE void record' ($d2.status -eq 200 -and $vf2.j.data.total -eq 0) "st=$($d2.status) total=$($vf2.j.data.total)"
$sv2 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance unchanged deleting VOID' (Near $sv2.balance $b0) "got=$($sv2.balance)"

# ---------- G-K: batch cascade delete ----------
$batchName = 'E2E delete cascade batch'
$bid1 = (Invoke-Api POST '/batches' @{ name = $batchName; amount = 5.55; deadline = '2026-12-31'; remark = 'created by delete test' } $A).j.data.id
OK 'create test batch' ($null -ne $bid1) 'batch id'
$members = @((Invoke-Api GET "/members?batchId=$bid1" $null $A).j.data)
$memberId = ($members | Where-Object { $_.username -eq $MemberU } | Select-Object -First 1).userId
OK 'member userId found' ($null -ne $memberId) "member lookup count=$($members.Count)"

$pay1 = Invoke-Api POST "/batches/$bid1/pay" @{ userId = $memberId; amount = 5.55; channel = 'WECHAT' } $A
OK 'pay member' ($pay1.status -eq 200) "st=$($pay1.status) msg=$($pay1.j.message)"
$sp = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance +5.55 after pay' (Near $sp.balance ($b0 + 5.55)) "got=$($sp.balance)"
$mrow = @((Invoke-Api GET "/members?batchId=$bid1&keyword=$MemberU" $null $A).j.data)[0]
OK 'member PAID with recordId' ($mrow.payStatus -eq 'PAID' -and $null -ne $mrow.recordId) "status=$($mrow.payStatus) rid=$($mrow.recordId)"
$rid3 = $mrow.recordId

# delete the batch-generated record -> payment must fall back to UNPAID, no dangling recordId
$d3 = Invoke-Api DELETE "/records/$rid3" $null $A
OK 'DELETE batch record 200' ($d3.status -eq 200) "st=$($d3.status) msg=$($d3.j.message)"
$s3 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance back after record delete' (Near $s3.balance $b0) "got=$($s3.balance)"
$mrow2 = @((Invoke-Api GET "/members?batchId=$bid1&keyword=$MemberU" $null $A).j.data)[0]
OK 'payment reset to UNPAID, recordId cleared' ($mrow2.payStatus -eq 'UNPAID' -and $null -eq $mrow2.recordId) "status=$($mrow2.payStatus) rid=$($mrow2.recordId)"

# re-pay after deletion still works, then cascade-delete the whole batch
$pay2 = Invoke-Api POST "/batches/$bid1/pay" @{ userId = $memberId; amount = 5.55; channel = 'WECHAT' } $A
$sp2 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 're-pay after delete works' ($pay2.status -eq 200 -and (Near $sp2.balance ($b0 + 5.55))) "st=$($pay2.status) bal=$($sp2.balance)"
$rid4 = @((Invoke-Api GET "/members?batchId=$bid1&keyword=$MemberU" $null $A).j.data)[0].recordId

$db = Invoke-Api DELETE "/batches/$bid1" $null $A
OK 'DELETE batch 200' ($db.status -eq 200) "st=$($db.status) msg=$($db.j.message)"
$afterBatches = @((Invoke-Api GET '/batches' $null $A).j.data)
OK 'batch removed from list' (-not ($afterBatches | Where-Object { $_.id -eq $bid1 })) 'list still contains batch'
$rbRec = Invoke-Api GET "/records?id=$rid4&size=5" $null $A
OK 'cascade removed generated record' ($rbRec.j.data.total -eq 0) "total=$($rbRec.j.data.total)"
$s4 = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'balance restored after batch delete' (Near $s4.balance $b0) "got=$($s4.balance)"
OK 'realBalance == balance after cascade' (Near $s4.realBalance $s4.balance) "real=$($s4.realBalance)"
OK 'completionRate back to baseline' (Near $s4.completionRate $r0) "r0=$r0 got=$($s4.completionRate)"

# ---------- L: close then delete ----------
$bid2 = (Invoke-Api POST '/batches' @{ name = 'E2E close-then-delete'; amount = 1; deadline = '2026-12-31' } $A).j.data.id
$cl = Invoke-Api POST "/batches/$bid2/close" $null $A
$null = Invoke-Api GET '/dashboard/summary' $null $A
$dc = Invoke-Api DELETE "/batches/$bid2" $null $A
$fc = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
OK 'close + delete batch' ($cl.status -eq 200 -and $dc.status -eq 200) "cl=$($cl.status) dc=$($dc.status)"
OK 'balance untouched by close/delete empty batch' ((Near $fc.balance $b0) -and (Near $fc.completionRate $r0)) "bal=$($fc.balance) rate=$($fc.completionRate) r0=$r0"

# ---------- M: role enforcement ----------
$ridDemo = (Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 1; title = 'E2E role probe'; occurredAt = '2026-09-26 10:10:00'; channel = 'CASH' } $A).j.data.id
OK 'create role-probe record' ($null -ne $ridDemo) "id=$ridDemo"
$r403a = Invoke-Api DELETE "/records/$ridDemo" $null $M
$r403b = Invoke-Api DELETE "/batches/1" $null $M
$r403c = Invoke-Api POST '/categories' @{ name = 'member should not'; kind = 'EXPENSE' } $M
$rRead = Invoke-Api GET '/records?page=1&size=1' $null $M
OK 'MEMBER delete record -> 403' ($r403a.status -eq 403) "st=$($r403a.status)"
OK 'MEMBER delete batch -> 403' ($r403b.status -eq 403) "st=$($r403b.status)"
OK 'MEMBER create category -> 403' ($r403c.status -eq 403) "st=$($r403c.status)"
OK 'MEMBER read records still 200' ($rRead.status -eq 200) "st=$($rRead.status)"
$null = Invoke-Api DELETE "/records/$ridDemo" $null $A   # net-zero restore

# ---------- N: category CRUD (create returns Void -> re-read id from list) ----------
$cnew = Invoke-Api POST '/categories' @{ name = 'E2E temp category'; kind = 'EXPENSE'; sort = 99 } $A
$cnewRow = (Invoke-Api GET '/categories?kind=EXPENSE' $null $A).j.data | Where-Object { $_.name -eq 'E2E temp category' } | Select-Object -First 1
$cnewId = $cnewRow.id
OK 'create category' ($cnew.status -eq 200 -and $null -ne $cnewId) "st=$($cnew.status) msg=$($cnew.j.message)"
$cdup = Invoke-Api POST '/categories' @{ name = 'E2E temp category'; kind = 'EXPENSE' } $A
OK 'duplicate category -> 400' ($cdup.status -eq 400) "st=$($cdup.status)"
# referenced category (has a real record) must be rejected: guarantee a reference with a probe record
$refProbe = (Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 2; title = 'E2E ref probe'; occurredAt = '2026-09-26 10:15:00'; channel = 'CASH' } $A).j.data.id
$expAll = @((Invoke-Api GET '/categories?kind=EXPENSE' $null $A).j.data)
$refCat = $null
foreach ($c in $expAll) {
    $t = (Invoke-Api GET "/records?categoryId=$($c.id)&size=1" $null $A).j.data.total
    if ($t -gt 0) { $refCat = $c.id; break }
}
if ($refCat) {
    $cref = Invoke-Api DELETE "/categories/$refCat" $null $A
    OK 'referenced category -> 400 rejected' ($cref.status -eq 400) "st=$($cref.status) msg=$($cref.j.message)"
} else { OK 'referenced category -> 400 rejected' $false 'no referenced category found' }
$null = Invoke-Api DELETE "/records/$refProbe" $null $A   # net-zero restore
$cde = Invoke-Api DELETE "/categories/$cnewId" $null $A
$cList = @((Invoke-Api GET '/categories?kind=EXPENSE' $null $A).j.data)
OK 'delete unused category' ($cde.status -eq 200 -and -not ($cList | Where-Object { $_.id -eq $cnewId })) "st=$($cde.status)"
# deleted name must be reusable (hard delete frees the name)
$crecreate = Invoke-Api POST '/categories' @{ name = 'E2E temp category'; kind = 'EXPENSE'; sort = 99 } $A
OK 'recreate same name after delete' ($crecreate.status -eq 200) "st=$($crecreate.status) msg=$($crecreate.j.message)"
$cagainId = ((Invoke-Api GET '/categories?kind=EXPENSE' $null $A).j.data | Where-Object { $_.name -eq 'E2E temp category' } | Select-Object -First 1).id
$cdel2 = Invoke-Api DELETE "/categories/$cagainId" $null $A
OK 'cleanup recreated category' ($cdel2.status -eq 200) "st=$($cdel2.status)"

# ---------- O: not found ----------
$o1 = Invoke-Api DELETE '/records/99999999' $null $A
$o2 = Invoke-Api DELETE '/batches/99999999' $null $A
OK 'delete missing record -> 400' ($o1.status -eq 400) "st=$($o1.status)"
OK 'delete missing batch -> 400' ($o2.status -eq 400) "st=$($o2.status)"

# ---------- Q: receipt upload / view / recycle (/api/files) ----------
# Helpers write curl body to a temp file: PNG bytes contain 0x0A, so splitting
# stdout would corrupt them. Temp fixtures are removed at the end of the section.
$upOut = Join-Path $env:TEMP 'classfee_regr_upload_out.json'
$binOut = Join-Path $env:TEMP 'classfee_regr_get_out.bin'
$tmpPng = Join-Path $env:TEMP 'classfee_regr_receipt.png'
$tmpTxt = Join-Path $env:TEMP 'classfee_regr_receipt.txt'
$tmpEmpty = Join-Path $env:TEMP 'classfee_regr_receipt_empty.png'
$tmpBig = Join-Path $env:TEMP 'classfee_regr_receipt_big.png'

function Upload-Receipt($path, $token) {
    if (Test-Path $script:upOut) { Remove-Item $script:upOut -Force }
    if ($token) {
        $code = & curl.exe -s -S -o $script:upOut -w '%{http_code}' -H "Authorization: Bearer $token" -F "file=@$path" "$base/files"
    } else {
        $code = & curl.exe -s -S -o $script:upOut -w '%{http_code}' -F "file=@$path" "$base/files"
    }
    $status = 0
    [int]::TryParse("$code".Trim(), [ref]$status) | Out-Null
    $j = $null
    if ((Test-Path $script:upOut) -and (Get-Item $script:upOut).Length -gt 0) {
        try { $j = [IO.File]::ReadAllText($script:upOut, [System.Text.Encoding]::UTF8) | ConvertFrom-Json } catch {}
    }
    return @{ status = $status; j = $j }
}

function Get-Receipt($path, $token) {
    if (Test-Path $script:binOut) { Remove-Item $script:binOut -Force }
    if ($token) {
        $code = & curl.exe -s -S -o $script:binOut -w '%{http_code}' -H "Authorization: Bearer $token" "$base/files/$path"
    } else {
        $code = & curl.exe -s -S -o $script:binOut -w '%{http_code}' "$base/files/$path"
    }
    $status = 0
    [int]::TryParse("$code".Trim(), [ref]$status) | Out-Null
    $bytes = @()
    if (Test-Path $script:binOut) { $bytes = [IO.File]::ReadAllBytes($script:binOut) }
    return @{ status = $status; bytes = $bytes }
}

# 1x1 PNG (base64) + non-image + empty + oversize fixtures
[IO.File]::WriteAllBytes($tmpPng, [Convert]::FromBase64String('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=='))
[IO.File]::WriteAllText($tmpTxt, 'not an image')
[IO.File]::WriteAllBytes($tmpEmpty, @())
$bigBytes = New-Object byte[] (5 * 1024 * 1024 + 128 * 1024)
$bigBytes[0] = 0x89; $bigBytes[1] = 0x50; $bigBytes[2] = 0x4E; $bigBytes[3] = 0x47   # png magic prefix
[IO.File]::WriteAllBytes($tmpBig, $bigBytes)

$up = Upload-Receipt $tmpPng $A
OK 'receipt upload -> 200 receipts/*' (($up.status -eq 200) -and ("$($up.j.data.path)" -like 'receipts/*')) "st=$($up.status) path=$($up.j.data.path)"
$rpath = "$($up.j.data.path)"

$upTxt = Upload-Receipt $tmpTxt $A
OK 'non-image upload -> 400' ($upTxt.status -eq 400) "st=$($upTxt.status) msg=$($upTxt.j.message)"

$upEmpty = Upload-Receipt $tmpEmpty $A
OK 'empty file -> 400' ($upEmpty.status -eq 400) "st=$($upEmpty.status)"

$upBig = Upload-Receipt $tmpBig $A
OK 'oversize file -> 400' ($upBig.status -eq 400) "st=$($upBig.status)"

$upAnon = Upload-Receipt $tmpPng $null
OK 'upload without token -> 401' ($upAnon.status -eq 401) "st=$($upAnon.status)"

$upMem = Upload-Receipt $tmpPng $M
OK 'MEMBER upload -> 403' ($upMem.status -eq 403) "st=$($upMem.status)"

# uploaded but not attached to any record yet -> invisible (no dangling reads)
$gOrphan = Get-Receipt $rpath $A
OK 'orphan path -> 404' ($gOrphan.status -eq 404) "st=$($gOrphan.status)"

# attach to an expense record
$recR = Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 1.5; title = 'E2E receipt probe'; occurredAt = '2026-09-28 10:00:00'; channel = 'CASH'; receiptUrl = $rpath } $A
$ridR = $recR.j.data.id
OK 'expense with receipt -> 200 + receiptUrl' (($recR.status -eq 200) -and ("$($recR.j.data.receiptUrl)" -eq $rpath)) "st=$($recR.status) ru=$($recR.j.data.receiptUrl)"

$lstR = @((Invoke-Api GET "/records?id=$ridR&size=5" $null $A).j.data.records)[0]
OK 'list row carries receiptUrl' ("$($lstR.receiptUrl)" -eq $rpath) "ru=$($lstR.receiptUrl)"

$gStaff = Get-Receipt $rpath $A
$pngMagic = ($gStaff.bytes.Length -ge 4) -and ($gStaff.bytes[0] -eq 0x89) -and ($gStaff.bytes[1] -eq 0x50) -and ($gStaff.bytes[2] -eq 0x4E) -and ($gStaff.bytes[3] -eq 0x47)
OK 'staff view receipt -> 200 + png magic' (($gStaff.status -eq 200) -and $pngMagic) "st=$($gStaff.status) len=$($gStaff.bytes.Length)"

$gMember = Get-Receipt $rpath $M
OK 'class member view receipt -> 200' ($gMember.status -eq 200) "st=$($gMember.status)"

$trav = Get-Receipt 'receipts/%2e%2e%2f%2e%2e%2fapp%2fconfig.py' $A
OK 'path traversal -> 404' ($trav.status -eq 404) "st=$($trav.status)"

$incCat = @((Invoke-Api GET '/categories?kind=INCOME' $null $A).j.data)[0].id
$incR = Invoke-Api POST '/records' @{ type = 'INCOME'; categoryId = $incCat; amount = 1; title = 'E2E income receipt'; occurredAt = '2026-09-28 10:05:00'; channel = 'CASH'; receiptUrl = $rpath } $A
OK 'income with receipt -> 400' ($incR.status -eq 400) "st=$($incR.status)"

$bogusR = Invoke-Api POST '/records' @{ type = 'EXPENSE'; categoryId = $expCat; amount = 1; title = 'E2E bogus receipt'; occurredAt = '2026-09-28 10:10:00'; channel = 'CASH'; receiptUrl = 'receipts/nonexistent9f.png' } $A
OK 'unknown receipt path -> 400' ($bogusR.status -eq 400) "st=$($bogusR.status)"

# physical delete recycles the image (money net-zero via delete rollback)
$delR = Invoke-Api DELETE "/records/$ridR" $null $A
OK 'delete receipt record -> 200' ($delR.status -eq 200) "st=$($delR.status)"
$gGone = Get-Receipt $rpath $A
OK 'file unviewable after delete -> 404' ($gGone.status -eq 404) "st=$($gGone.status)"
$rfileName = Split-Path $rpath -Leaf
OK 'file removed from disk' (-not (Test-Path "$PSScriptRoot\server-py\uploads\receipts\$rfileName")) "file=$rfileName"

Remove-Item $tmpPng, $tmpTxt, $tmpEmpty, $tmpBig, $upOut, $binOut -Force -ErrorAction SilentlyContinue

# ---------- S: ledger export to Excel (M4) ----------
$xlsxOut = Join-Path $env:TEMP 'classfee_regr_export.xlsx'
function Export-Csv($path, $token) {
    if (Test-Path $script:xlsxOut) { Remove-Item $script:xlsxOut -Force }
    if ($token) {
        $code = & curl.exe -s -S -o $script:xlsxOut -w '%{http_code}' -H "Authorization: Bearer $token" "$base$path"
    } else {
        $code = & curl.exe -s -S -o $script:xlsxOut -w '%{http_code}' "$base$path"
    }
    $status = 0
    [int]::TryParse("$code".Trim(), [ref]$status) | Out-Null
    $bytes = @()
    if (Test-Path $script:xlsxOut) { $bytes = [IO.File]::ReadAllBytes($script:xlsxOut) }
    return @{ status = $status; bytes = $bytes }
}
function Export-Head($token) {
    # 用 GET 只收响应头（-D - 打印头、-o NUL 丢弃正文）：该路由只注册 GET，HEAD 会 405
    if ($token) {
        return (& curl.exe -s -S -D - -o NUL -H "Authorization: Bearer $token" "$base/records/export") -join "`n"
    }
    return (& curl.exe -s -S -D - -o NUL "$base/records/export") -join "`n"
}

$expAll = Export-Csv '/records/export' $A
$isZip = ($expAll.bytes.Length -ge 2) -and ($expAll.bytes[0] -eq 0x50) -and ($expAll.bytes[1] -eq 0x4B)   # PK = xlsx
OK 'export xlsx -> 200' ($expAll.status -eq 200) "st=$($expAll.status) bytes=$($expAll.bytes.Length)"
OK 'export body is a real xlsx (PK zip)' $isZip "head=$($expAll.bytes[0])"
$expHeaders = Export-Head $A
OK 'export content-type is xlsx' ($expHeaders -match 'spreadsheetml\.sheet') "headers len=$($expHeaders.Length)"
OK 'export sets attachment filename' ($expHeaders -match 'filename\*=UTF-8') 'no filename* in Content-Disposition'
$expFiltered = Export-Csv '/records/export?type=EXPENSE&status=NORMAL' $A
OK 'export honours filters -> 200 xlsx' (($expFiltered.status -eq 200) -and ($expFiltered.bytes.Length -gt 0)) "st=$($expFiltered.status) bytes=$($expFiltered.bytes.Length)"
$expAnon = Export-Csv '/records/export' $null
OK 'export without token -> 401' ($expAnon.status -eq 401) "st=$($expAnon.status)"
$expMember = Export-Csv '/records/export' $M
OK 'MEMBER export -> 403' ($expMember.status -eq 403) "st=$($expMember.status)"
Remove-Item $xlsxOut -Force -ErrorAction SilentlyContinue

# ---------- R: class info + notices (M4) ----------
# Class info: everyone reads, only ops edit (balance stays read-only).
$cls0 = (Invoke-Api GET '/class' $null $M).j.data
$grade0 = $cls0.grade
OK 'MEMBER read class info' ($null -ne $cls0.id -and "$($cls0.className)" -ne '') "class=$($cls0.className)"
$c403 = Invoke-Api PUT '/class' @{ grade = 'hack' } $M
OK 'MEMBER edit class -> 403' ($c403.status -eq 403) "st=$($c403.status)"
$cEmpty = Invoke-Api PUT '/class' @{} $A
$cBlank = Invoke-Api PUT '/class' @{ className = '   ' } $A
$cLong = Invoke-Api PUT '/class' @{ className = ('x' * 51) } $A
OK 'empty class body -> 400' ($cEmpty.status -eq 400) "st=$($cEmpty.status)"
OK 'blank className -> 400' ($cBlank.status -eq 400) "st=$($cBlank.status)"
OK 'className >50 -> 400' ($cLong.status -eq 400) "st=$($cLong.status)"
$cUpd = Invoke-Api PUT '/class' @{ grade = '2022-PROBE' } $A
$cRead = (Invoke-Api GET '/class' $null $M).j.data
OK 'TEACHER edit grade -> 200' (($cUpd.status -eq 200) -and ($cRead.grade -eq '2022-PROBE')) "st=$($cUpd.status) grade=$($cRead.grade)"
$cBack = Invoke-Api PUT '/class' @{ grade = $grade0 } $A
OK 'class grade restored' (($cBack.status -eq 200) -and ($cBack.j.data.grade -eq $grade0)) "st=$($cBack.status) grade=$($cBack.j.data.grade)"

# Notices: publish (pinned), visibility rules, unpublish -> hard delete.
$nPub = Invoke-Api POST '/notices' @{ title = 'E2E notice probe'; content = 'probe body'; pinned = 1 } $A
$nid = $nPub.j.data.id
OK 'publish notice -> 200' (($nPub.status -eq 200) -and ($null -ne $nid)) "st=$($nPub.status) msg=$($nPub.j.message)"
if (-not $nid) { OK 'notice flow (aborted: no id)' $false 'publish failed, remaining notice checks skipped' }
else {
    OK 'notice VO carries pinned/status/author' (($nPub.j.data.pinned -eq 1) -and ($nPub.j.data.status -eq 1) -and "$($nPub.j.data.createdByName)" -ne '') "pinned=$($nPub.j.data.pinned) status=$($nPub.j.data.status) by=$($nPub.j.data.createdByName)"
    $nList = @((Invoke-Api GET '/notices' $null $M).j.data)
    OK 'MEMBER read notices' (@($nList | Where-Object { $_.id -eq $nid }).Count -eq 1) "count=$($nList.Count)"
    $nPins = @((Invoke-Api GET '/dashboard/summary' $null $M).j.data.pinnedNotices)
    OK 'dashboard shows pinned notice' (@($nPins | Where-Object { $_.id -eq $nid }).Count -eq 1) "pins=$($nPins.Count)"
    $nKw = @((Invoke-Api GET '/notices?keyword=E2E%20notice' $null $M).j.data)
    OK 'notice keyword search' ($nKw.Count -eq 1) "count=$($nKw.Count)"
    $nBadStatus = Invoke-Api GET '/notices?status=xyz' $null $A
    OK 'bad notice status -> 400' ($nBadStatus.status -eq 400) "st=$($nBadStatus.status)"
    $n403a = Invoke-Api POST '/notices' @{ title = 'x'; content = 'y' } $M
    $n403b = Invoke-Api PUT "/notices/$nid" @{ title = 'x' } $M
    $n403c = Invoke-Api DELETE "/notices/$nid" $null $M
    OK 'MEMBER publish notice -> 403' ($n403a.status -eq 403) "st=$($n403a.status)"
    OK 'MEMBER edit notice -> 403' ($n403b.status -eq 403) "st=$($n403b.status)"
    OK 'MEMBER delete notice -> 403' ($n403c.status -eq 403) "st=$($n403c.status)"
    $nNoTitle = Invoke-Api POST '/notices' @{ content = 'x' } $A
    $nBlankTitle = Invoke-Api POST '/notices' @{ title = '  '; content = 'x' } $A
    $nLongTitle = Invoke-Api POST '/notices' @{ title = ('t' * 81); content = 'x' } $A
    $nLongBody = Invoke-Api POST '/notices' @{ title = 'ok'; content = ('c' * 2001) } $A
    OK 'notice missing title -> 400' ($nNoTitle.status -eq 400) "st=$($nNoTitle.status)"
    OK 'notice blank title -> 400' ($nBlankTitle.status -eq 400) "st=$($nBlankTitle.status)"
    OK 'notice title >80 -> 400' ($nLongTitle.status -eq 400) "st=$($nLongTitle.status)"
    OK 'notice content >2000 -> 400' ($nLongBody.status -eq 400) "st=$($nLongBody.status)"
    $nEmptyUpd = Invoke-Api PUT "/notices/$nid" @{} $A
    OK 'notice empty update body -> 400' ($nEmptyUpd.status -eq 400) "st=$($nEmptyUpd.status)"
    $nEdit = Invoke-Api PUT "/notices/$nid" @{ title = 'E2E notice probe v2' } $A
    OK 'edit notice title -> 200' (($nEdit.status -eq 200) -and ($nEdit.j.data.title -eq 'E2E notice probe v2')) "st=$($nEdit.status)"
    $nUnpub = Invoke-Api PUT "/notices/$nid" @{ status = 0 } $A
    OK 'unpublish notice -> status 0' (($nUnpub.status -eq 200) -and ($nUnpub.j.data.status -eq 0)) "st=$($nUnpub.status)"
    $nMemberAll = @((Invoke-Api GET '/notices?status=all' $null $M).j.data)
    $nStaffOff = @((Invoke-Api GET '/notices?status=0' $null $A).j.data)
    OK 'MEMBER cannot list unlisted' ($nMemberAll.Count -eq 0) "count=$($nMemberAll.Count)"
    OK 'staff can list unlisted' ($nStaffOff.Count -eq 1) "count=$($nStaffOff.Count)"
    $nPins2 = @((Invoke-Api GET '/dashboard/summary' $null $A).j.data.pinnedNotices)
    OK 'dashboard drops unlisted notice' ($nPins2.Count -eq 0) "pins=$($nPins2.Count)"
    $nRepub = Invoke-Api PUT "/notices/$nid" @{ status = 1 } $A
    OK 'republish notice -> 200' (($nRepub.status -eq 200) -and ($nRepub.j.data.status -eq 1)) "st=$($nRepub.status)"
    $nDelPub = Invoke-Api DELETE "/notices/$nid" $null $A
    OK 'hard delete while published -> 400' ($nDelPub.status -eq 400) "st=$($nDelPub.status)"
    $null = Invoke-Api PUT "/notices/$nid" @{ status = 0 } $A
    $nHard = Invoke-Api DELETE "/notices/$nid" $null $A
    $nAfter = @((Invoke-Api GET '/notices?status=all' $null $A).j.data)
    OK 'hard delete after unpublish -> 200' ($nHard.status -eq 200) "st=$($nHard.status)"
    OK 'notice removed for good' ($nAfter.Count -eq 0) "count=$($nAfter.Count)"
    $nUpdMissing = Invoke-Api PUT '/notices/99999999' @{ title = 'x' } $A
    $nDelMissing = Invoke-Api DELETE '/notices/99999999' $null $A
    OK 'edit missing notice -> 400' ($nUpdMissing.status -eq 400) "st=$($nUpdMissing.status)"
    OK 'delete missing notice -> 400' ($nDelMissing.status -eq 400) "st=$($nDelMissing.status)"
}

# ---------- P: final state matches baseline ----------
$fin = (Invoke-Api GET '/dashboard/summary' $null $A).j.data
$total1 = (Invoke-Api GET '/records?page=1&size=1' $null $A).j.data.total
$batches1 = @((Invoke-Api GET '/batches' $null $A).j.data).Count
$notices1 = @((Invoke-Api GET '/notices?status=all' $null $A).j.data).Count
OK 'final balance == baseline' (Near $fin.balance $b0) "b0=$b0 got=$($fin.balance)"
OK 'final realBalance == balance' (Near $fin.realBalance $fin.balance) "real=$($fin.realBalance)"
OK 'final completionRate == baseline' (Near $fin.completionRate $r0) "r0=$r0 got=$($fin.completionRate)"
OK 'final record count == baseline' ($total1 -eq $total0) "t0=$total0 t1=$total1"
OK 'final batch count == baseline' ($batches1 -eq $batches0) "b0=$batches0 b1=$batches1"
OK 'final notice count == baseline' ($notices1 -eq $notices0) "n0=$notices0 n1=$notices1"

# ---------- Q: cleanup: remove the accounts this script created ----------
# 为什么需要：这些固定学号（20220103/20220995/20220997/test）是断言载体，
# 复用它们是为了让脚本可重复执行，但如果**留在库里**，班费系统的「成员管理」里
# 就会留下一堆英文占位姓名（Wang Xiaoming / Sn Explicit / test-tx…），
# 看起来像真人数据，是噪音。
# 收尾时按「零引用可删」规则清掉自己造的账号，只留真人账号（班主任本人等）。
# 已在断言里被引用过流水/缴费/批次的账号会自动被后端拒绝（400），跳过即可。
$cleanupUsers = @($MemberU, $snoU, $sneU, $delU, 'nope1', $hAdm, $hMon, $hMem, $hMon2, $hEsc)
$left = @()
foreach ($cu in $cleanupUsers) {
    $row = @((Invoke-Api GET "/users?keyword=$cu" $null $A).j.data | Where-Object { $_.username -eq $cu })[0]
    if (-not $row) { continue }
    $du = Invoke-Api DELETE "/users/$($row.id)" $null $A
    if ($du.status -ne 200) { $left += "$cu(st=$($du.status))" }
}
OK 'regression-created accounts cleaned up' ($left.Count -eq 0) "not removed: $(if ($left.Count) { $left -join ',' } else { 'none' })"

Write-Host ""
Write-Host "RESULT: $script:pass passed, $script:fail failed"
if ($script:fail -gt 0) { exit 1 } else { exit 0 }
