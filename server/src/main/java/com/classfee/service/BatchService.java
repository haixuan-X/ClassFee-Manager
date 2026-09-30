package com.classfee.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.classfee.common.BizException;
import com.classfee.dto.BatchPayRequest;
import com.classfee.dto.BatchRequest;
import com.classfee.dto.MemberQuery;
import com.classfee.entity.ClsClass;
import com.classfee.entity.FeeBatch;
import com.classfee.entity.FeeCategory;
import com.classfee.entity.FeePayment;
import com.classfee.entity.FeeRecord;
import com.classfee.entity.SysUser;
import com.classfee.mapper.ClsClassMapper;
import com.classfee.mapper.FeeBatchMapper;
import com.classfee.mapper.FeeCategoryMapper;
import com.classfee.mapper.FeePaymentMapper;
import com.classfee.mapper.FeeRecordMapper;
import com.classfee.mapper.SysUserMapper;
import com.classfee.security.LoginUser;
import com.classfee.security.UserContext;
import com.classfee.vo.BatchDetailVO;
import com.classfee.vo.BatchVO;
import com.classfee.vo.MemberVO;
import com.classfee.vo.PaymentVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 收费批次服务：建批次 → 逐人标记缴费（同事务生成流水）→ 关闭批次。
 * <p>
 * 两条不变式（全部在同一事务里维护）：
 * <ol>
 *   <li>{@code fee_payment.status=PAID} ⟺ 其 {@code record_id} 指向一条 NORMAL 流水</li>
 *   <li>自动流水与 {@code cls_class.balance} 同事务原子变更（复用记账铁律）</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class BatchService {

    /** 自动流水的类别名优先级：找不到就退回第一个收入类别 */
    private static final String PREFERRED_INCOME_CATEGORY = "班费收取";

    private final FeeBatchMapper batchMapper;
    private final FeePaymentMapper paymentMapper;
    private final FeeRecordMapper recordMapper;
    private final FeeCategoryMapper categoryMapper;
    private final SysUserMapper userMapper;
    private final ClsClassMapper classMapper;

    /* ============================ 批次 ============================ */

    /** 批次列表（本班，新→旧），带人数与完成率 */
    public List<BatchVO> list() {
        LoginUser user = UserContext.require();
        List<FeeBatch> batches = batchMapper.selectList(new LambdaQueryWrapper<FeeBatch>()
                .eq(FeeBatch::getClassId, user.getClassId())
                .orderByDesc(FeeBatch::getId));
        return toVOList(batches);
    }

    /** 新建批次：为当前全班成员各建一条未缴记录（uk_batch_user 防重复） */
    @Transactional(rollbackFor = Exception.class)
    public BatchVO create(BatchRequest request) {
        LoginUser user = UserContext.require();

        // 行锁班级：同班并发创建串行化，补上“先查后插”之间的防重缺口
        classMapper.selectOne(new LambdaQueryWrapper<ClsClass>()
                .eq(ClsClass::getId, user.getClassId())
                .last("for update"));

        String name = request.getName().trim();
        Long duplicated = batchMapper.selectCount(new LambdaQueryWrapper<FeeBatch>()
                .eq(FeeBatch::getClassId, user.getClassId())
                .eq(FeeBatch::getStatus, FeeBatch.STATUS_OPEN)
                .eq(FeeBatch::getName, name));
        if (duplicated != null && duplicated > 0) {
            throw BizException.badRequest("已存在同名的进行中批次，请勿重复创建");
        }

        FeeBatch batch = new FeeBatch();
        batch.setClassId(user.getClassId());
        batch.setName(name);
        batch.setAmount(request.getAmount().setScale(2, RoundingMode.HALF_UP));
        batch.setDeadline(request.getDeadline());
        batch.setRemark(request.getRemark());
        batch.setStatus(FeeBatch.STATUS_OPEN);
        batch.setCreatedBy(user.getId());
        batchMapper.insert(batch);

        List<SysUser> members = classMembers(user.getClassId());
        if (members.isEmpty()) {
            throw BizException.badRequest("班级暂无成员，无法创建批次");
        }
        for (SysUser member : members) {
            FeePayment payment = new FeePayment();
            payment.setBatchId(batch.getId());
            payment.setUserId(member.getId());
            payment.setAmount(BigDecimal.ZERO.setScale(2, RoundingMode.HALF_UP));
            payment.setStatus(FeePayment.STATUS_UNPAID);
            paymentMapper.insert(payment);
        }

        log.info("创建收费批次：{}，每人 {} 元，成员 {} 人（操作人={}）",
                name, batch.getAmount(), members.size(), user.getUsername());
        return toVOList(List.of(batch)).get(0);
    }

    /** 批次详情：批次 + 逐人缴费明细（按学号排序） */
    public BatchDetailVO detail(Long batchId) {
        FeeBatch batch = requireBatch(batchId);
        List<FeePayment> payments = paymentMapper.selectList(new LambdaQueryWrapper<FeePayment>()
                .eq(FeePayment::getBatchId, batchId));
        Map<Long, SysUser> users = usersById(payments.stream()
                .map(FeePayment::getUserId).collect(Collectors.toSet()));

        List<PaymentVO> rows = payments.stream()
                .map(p -> toPaymentVO(p, users.get(p.getUserId())))
                .sorted(Comparator
                        .comparing((PaymentVO v) -> v.getStudentNo() == null ? "" : v.getStudentNo())
                        .thenComparing(v -> v.getRealName() == null ? "" : v.getRealName()))
                .collect(Collectors.toList());

        BatchDetailVO detail = new BatchDetailVO();
        detail.setBatch(toVOList(List.of(batch)).get(0));
        detail.setPayments(rows);
        return detail;
    }

    /**
     * 标记某人已交 → 同事务生成收入流水 + 原子更新余额 + 回填缴费行。
     * <p>
     * 缴费行用 {@code status != PAID} 做条件更新：双击/并发只会命中一行，另一路拿到 0 行后回滚，
     * 不会出现“收了两次钱”。
     */
    @Transactional(rollbackFor = Exception.class)
    public void pay(Long batchId, BatchPayRequest request) {
        LoginUser user = UserContext.require();
        // 行锁读取批次：与 close 的条件更新串行，堵住“关闭后仍入账”的并发窗口
        FeeBatch batch = requireBatchForUpdate(batchId);

        SysUser payer = userMapper.selectById(request.getUserId());
        if (payer == null || !batch.getClassId().equals(payer.getClassId())) {
            throw BizException.badRequest("缴费成员不存在或不属于本班");
        }
        if (payer.getStatus() == null || payer.getStatus() != 1) {
            throw BizException.badRequest("该成员账号已停用");
        }

        FeePayment payment = paymentMapper.selectOne(new LambdaQueryWrapper<FeePayment>()
                .eq(FeePayment::getBatchId, batchId)
                .eq(FeePayment::getUserId, payer.getId())
                .last("limit 1"));
        if (payment != null && FeePayment.STATUS_PAID.equals(payment.getStatus())) {
            throw BizException.badRequest(payer.getRealName() + " 已缴费，无需重复标记");
        }
        // 关闭后仅放行“作废后重新标记”（缴费行 UNPAID 且 recordId 指向 VOID 流水），
        // 否则作废一笔已关批次的流水会让该成员永远补不回来
        if (FeeBatch.STATUS_CLOSED.equals(batch.getStatus()) && !remarkableAfterVoid(payment)) {
            throw BizException.badRequest("批次已关闭，不能继续标记缴费");
        }

        BigDecimal amount = request.getAmount() == null
                ? batch.getAmount() : request.getAmount().setScale(2, RoundingMode.HALF_UP);
        String channel = request.getChannel() == null || request.getChannel().isBlank()
                ? FeeRecord.CHANNEL_CASH : request.getChannel();
        Date occurredAt = request.getOccurredAt() == null ? new Date() : request.getOccurredAt();

        // 自动收款流水（收入，优先班费收取类别）
        FeeCategory category = incomeCategory(batch.getClassId());
        FeeRecord record = new FeeRecord();
        record.setClassId(batch.getClassId());
        record.setType(FeeRecord.TYPE_INCOME);
        record.setCategoryId(category.getId());
        record.setAmount(amount);
        record.setTitle(truncate("收取" + batch.getName() + "·" + payer.getRealName(), 60));
        record.setOccurredAt(occurredAt);
        record.setChannel(channel);
        record.setPayerUserId(payer.getId());
        record.setBatchId(batch.getId());
        record.setRemark(request.getRemark());
        record.setStatus(FeeRecord.STATUS_NORMAL);
        record.setCreatedBy(user.getId());
        recordMapper.insert(record);

        if (classMapper.addBalance(batch.getClassId(), amount) != 1) {
            throw BizException.badRequest("班级余额更新失败，请重试");
        }

        int rows;
        if (payment == null) {
            // 罕见路径：批次行缺失时补建（并发撞 uk_batch_user 由事务回滚兜底）
            FeePayment created = new FeePayment();
            created.setBatchId(batchId);
            created.setUserId(payer.getId());
            created.setAmount(amount);
            created.setStatus(FeePayment.STATUS_PAID);
            created.setChannel(channel);
            created.setPaidAt(occurredAt);
            created.setRecordId(record.getId());
            created.setRemark(request.getRemark());
            try {
                rows = paymentMapper.insert(created);
            } catch (DuplicateKeyException e) {
                throw BizException.badRequest("该成员缴费状态已变化，请刷新后重试");
            }
        } else {
            rows = paymentMapper.update(null, new LambdaUpdateWrapper<FeePayment>()
                    .eq(FeePayment::getId, payment.getId())
                    .ne(FeePayment::getStatus, FeePayment.STATUS_PAID)
                    .set(FeePayment::getStatus, FeePayment.STATUS_PAID)
                    .set(FeePayment::getAmount, amount)
                    .set(FeePayment::getChannel, channel)
                    .set(FeePayment::getPaidAt, occurredAt)
                    .set(FeePayment::getRecordId, record.getId())
                    .set(FeePayment::getRemark, request.getRemark()));
        }
        if (rows == 0) {
            throw BizException.badRequest("该成员缴费状态已变化，请刷新后重试");
        }

        log.info("标记缴费：批次={}（{}），成员={}，{} 元，流水 id={}",
                batch.getId(), batch.getName(), payer.getUsername(), amount, record.getId());
    }

    /** 关闭批次：条件更新，并发/重复关闭只会命中一行 */
    @Transactional(rollbackFor = Exception.class)
    public void close(Long batchId) {
        requireBatch(batchId);
        int rows = batchMapper.update(null, new LambdaUpdateWrapper<FeeBatch>()
                .eq(FeeBatch::getId, batchId)
                .eq(FeeBatch::getStatus, FeeBatch.STATUS_OPEN)
                .set(FeeBatch::getStatus, FeeBatch.STATUS_CLOSED));
        if (rows == 0) {
            FeeBatch now = batchMapper.selectById(batchId);
            if (now != null && FeeBatch.STATUS_CLOSED.equals(now.getStatus())) {
                throw BizException.badRequest("批次已关闭，无需重复操作");
            }
            throw BizException.badRequest("批次状态已变化，请刷新后重试");
        }
        log.info("关闭收费批次 id={}", batchId);
    }

    /**
     * 删除批次（管理员）：同事务级联清理整批数据 —— 全部流水（NORMAL 反向回滚余额）、
     * 全部缴费状态、批次本身。行锁批次，与标记缴费/关闭完全串行。
     * <p>
     * 级联顺序刻意为「流水 → 缴费状态 → 余额 → 批次行」：班级行锁最后才拿，
     * 与单笔作废/删除（流水行 → 班级行）方向一致，避免互持等待。
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteBatch(Long batchId) {
        FeeBatch batch = requireBatchForUpdate(batchId);

        List<FeeRecord> records = recordMapper.selectList(new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getBatchId, batchId));
        // 回滚量 = 各笔正常流水的增量取反：收入减掉、支出加回来
        BigDecimal rollback = records.stream()
                .filter(r -> FeeRecord.STATUS_NORMAL.equals(r.getStatus()))
                .map(r -> FeeRecord.TYPE_INCOME.equals(r.getType())
                        ? r.getAmount().negate() : r.getAmount())
                .reduce(BigDecimal.ZERO, BigDecimal::add);

        int removedRecords = recordMapper.delete(new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getBatchId, batchId));
        int removedPayments = paymentMapper.delete(new LambdaQueryWrapper<FeePayment>()
                .eq(FeePayment::getBatchId, batchId));
        batchMapper.deleteById(batch.getId());

        if (rollback.signum() != 0 && classMapper.addBalance(batch.getClassId(), rollback) != 1) {
            throw BizException.badRequest("班级余额更新失败，请重试");
        }

        log.info("删除收费批次 id={}（{}）：级联删除流水 {} 笔、缴费状态 {} 条，余额回滚 {}",
                batch.getId(), batch.getName(), removedRecords, removedPayments, rollback);
    }

    /* ============================ 成员缴费 ============================ */

    /** 成员列表 + 指定批次下的缴费状态 */
    public List<MemberVO> members(MemberQuery query) {
        LoginUser user = UserContext.require();
        FeeBatch batch = resolveBatch(query.getBatchId(), user.getClassId());

        String keyword = query.getKeyword() == null ? null : query.getKeyword().trim();
        boolean hasKeyword = keyword != null && !keyword.isEmpty();

        LambdaQueryWrapper<SysUser> wrapper = new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getClassId, user.getClassId())
                .eq(SysUser::getStatus, 1)
                .orderByAsc(SysUser::getUsername);
        if (hasKeyword) {
            String kw = escapeLike(keyword);
            wrapper.and(w -> w.like(SysUser::getRealName, kw)
                    .or().like(SysUser::getStudentNo, kw)
                    .or().like(SysUser::getUsername, kw));
        }
        List<SysUser> users = userMapper.selectList(wrapper);

        Map<Long, FeePayment> payMap = batch == null ? Map.of()
                : paymentMapper.selectList(new LambdaQueryWrapper<FeePayment>()
                        .eq(FeePayment::getBatchId, batch.getId()))
                        .stream()
                        .collect(Collectors.toMap(FeePayment::getUserId, Function.identity(), (a, b) -> a));

        List<MemberVO> result = new ArrayList<>(users.size());
        for (SysUser u : users) {
            result.add(toMemberVO(u, batch, payMap.get(u.getId())));
        }

        String payStatus = query.getPayStatus();
        if (payStatus != null && !payStatus.isBlank()) {
            final String wanted = payStatus;
            result = result.stream()
                    .filter(m -> wanted.equals(m.getPayStatus()))
                    .collect(Collectors.toList());
        }
        return result;
    }

    /** 仪表盘完成率：0-100（1 位小数），班级还没有批次时返回 null */
    public BigDecimal completionRate(Long classId) {
        FeeBatch batch = resolveBatch(null, classId);
        if (batch == null) {
            return null;
        }
        return toVOList(List.of(batch)).get(0).getRate();
    }

    /* ============================ 内部工具 ============================ */

    /** 批次解析：指定 id > 最新进行中 > 最新 */
    private FeeBatch resolveBatch(Long batchId, Long classId) {
        if (batchId != null) {
            return requireBatch(batchId);
        }
        FeeBatch open = batchMapper.selectOne(new LambdaQueryWrapper<FeeBatch>()
                .eq(FeeBatch::getClassId, classId)
                .eq(FeeBatch::getStatus, FeeBatch.STATUS_OPEN)
                .orderByDesc(FeeBatch::getId)
                .last("limit 1"));
        if (open != null) {
            return open;
        }
        return batchMapper.selectOne(new LambdaQueryWrapper<FeeBatch>()
                .eq(FeeBatch::getClassId, classId)
                .orderByDesc(FeeBatch::getId)
                .last("limit 1"));
    }

    private FeeBatch requireBatch(Long batchId) {
        LoginUser user = UserContext.require();
        FeeBatch batch = batchMapper.selectById(batchId);
        if (batch == null || !user.getClassId().equals(batch.getClassId())) {
            throw BizException.badRequest("批次不存在或无权操作");
        }
        return batch;
    }

    /** 行锁读取批次（pay 用）：与 close 的条件更新互斥，事务结束前一直持有 */
    private FeeBatch requireBatchForUpdate(Long batchId) {
        LoginUser user = UserContext.require();
        FeeBatch batch = batchMapper.selectOne(new LambdaQueryWrapper<FeeBatch>()
                .eq(FeeBatch::getId, batchId)
                .last("for update"));
        if (batch == null || !user.getClassId().equals(batch.getClassId())) {
            throw BizException.badRequest("批次不存在或无权操作");
        }
        return batch;
    }

    /** 缴费行是否处于“流水作废、等待重新标记”状态（recordId 指向 VOID 流水） */
    private boolean remarkableAfterVoid(FeePayment payment) {
        if (payment == null || payment.getRecordId() == null
                || !FeePayment.STATUS_UNPAID.equals(payment.getStatus())) {
            return false;
        }
        FeeRecord old = recordMapper.selectById(payment.getRecordId());
        return old != null && FeeRecord.STATUS_VOID.equals(old.getStatus());
    }

    /** LIKE 通配符转义（参数化绑定已无注入风险，但 %/_ 会破坏匹配语义） */
    private String escapeLike(String raw) {
        return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    /** 班级成员（含管理员/班主任：班长也要交班费） */
    private List<SysUser> classMembers(Long classId) {
        return userMapper.selectList(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getClassId, classId)
                .eq(SysUser::getStatus, 1)
                .orderByAsc(SysUser::getUsername));
    }

    private Map<Long, SysUser> usersById(Set<Long> ids) {
        if (ids == null || ids.isEmpty()) {
            return Map.of();
        }
        return userMapper.selectBatchIds(ids).stream()
                .collect(Collectors.toMap(SysUser::getId, Function.identity(), (a, b) -> a));
    }

    /** 收入类别：优先「班费收取」，否则第一个可用收入类别 */
    private FeeCategory incomeCategory(Long classId) {
        List<FeeCategory> categories = categoryMapper.selectList(new LambdaQueryWrapper<FeeCategory>()
                .eq(FeeCategory::getClassId, classId)
                .eq(FeeCategory::getKind, FeeRecord.TYPE_INCOME)
                .eq(FeeCategory::getStatus, 1)
                .orderByAsc(FeeCategory::getSort));
        if (categories.isEmpty()) {
            throw BizException.badRequest("缺少可用的收入类别，请先在类别字典中配置");
        }
        return categories.stream()
                .filter(c -> PREFERRED_INCOME_CATEGORY.equals(c.getName()))
                .findFirst()
                .orElse(categories.get(0));
    }

    /** 批次统计（一次聚合查询，避免 N+1） */
    private Map<Long, long[]> statMap(List<FeeBatch> batches) {
        if (batches.isEmpty()) {
            return Map.of();
        }
        List<Long> ids = batches.stream().map(FeeBatch::getId).collect(Collectors.toList());
        List<Map<String, Object>> rows = paymentMapper.selectMaps(new QueryWrapper<FeePayment>()
                .select("batch_id", "COUNT(*) AS total", "SUM(status = 'PAID') AS paid")
                .in("batch_id", ids)
                .groupBy("batch_id"));
        return rows.stream().collect(Collectors.toMap(
                r -> ((Number) r.get("batch_id")).longValue(),
                r -> new long[]{
                        ((Number) r.get("total")).longValue(),
                        r.get("paid") == null ? 0L : ((Number) r.get("paid")).longValue()
                }));
    }

    private List<BatchVO> toVOList(List<FeeBatch> batches) {
        Map<Long, long[]> stats = statMap(batches);
        List<BatchVO> result = new ArrayList<>(batches.size());
        for (FeeBatch batch : batches) {
            long[] stat = stats.getOrDefault(batch.getId(), new long[]{0L, 0L});
            long total = stat[0];
            long paid = stat[1];

            BatchVO vo = new BatchVO();
            vo.setId(batch.getId());
            vo.setName(batch.getName());
            vo.setAmount(batch.getAmount());
            vo.setDeadline(batch.getDeadline());
            vo.setRemark(batch.getRemark());
            vo.setStatus(batch.getStatus());
            vo.setCreatedAt(batch.getCreatedAt());
            vo.setTotal(total);
            vo.setPaidCount(paid);
            vo.setUnpaidCount(total - paid);
            vo.setRate(total == 0 ? BigDecimal.ZERO.setScale(1, RoundingMode.HALF_UP)
                    : BigDecimal.valueOf(paid)
                            .multiply(BigDecimal.valueOf(100))
                            .divide(BigDecimal.valueOf(total), 1, RoundingMode.HALF_UP));
            result.add(vo);
        }
        return result;
    }

    private PaymentVO toPaymentVO(FeePayment payment, SysUser member) {
        PaymentVO vo = new PaymentVO();
        vo.setId(payment.getId());
        vo.setUserId(payment.getUserId());
        vo.setRealName(member == null ? null : member.getRealName());
        vo.setStudentNo(member == null ? null : member.getStudentNo());
        vo.setRole(member == null ? null : member.getRole());
        vo.setStatus(payment.getStatus());
        vo.setAmount(payment.getAmount());
        vo.setChannel(payment.getChannel());
        vo.setPaidAt(payment.getPaidAt());
        vo.setRecordId(payment.getRecordId());
        vo.setRemark(payment.getRemark());
        return vo;
    }

    private MemberVO toMemberVO(SysUser member, FeeBatch batch, FeePayment payment) {
        MemberVO vo = new MemberVO();
        vo.setUserId(member.getId());
        vo.setUsername(member.getUsername());
        vo.setRealName(member.getRealName());
        vo.setStudentNo(member.getStudentNo());
        vo.setRole(member.getRole());
        vo.setStatus(member.getStatus());
        if (batch != null) {
            vo.setBatchId(batch.getId());
            vo.setPayStatus(payment == null ? FeePayment.STATUS_UNPAID : payment.getStatus());
            if (payment != null) {
                vo.setAmount(payment.getAmount());
                vo.setChannel(payment.getChannel());
                vo.setPaidAt(payment.getPaidAt());
                vo.setRecordId(payment.getRecordId());
            }
        }
        return vo;
    }

    /** 标题超长截断（fee_record.title 上限 60） */
    private String truncate(String text, int max) {
        if (text == null || text.length() <= max) {
            return text;
        }
        return text.substring(0, max);
    }

    /** 供其他服务判断“流水是不是批次自动入账”（避免空指针） */
    public static boolean isBatchRecord(FeeRecord record) {
        return record != null && Objects.nonNull(record.getBatchId());
    }
}
