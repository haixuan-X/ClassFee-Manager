package com.classfee.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.baomidou.mybatisplus.core.metadata.IPage;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.classfee.common.BizException;
import com.classfee.common.PageResult;
import com.classfee.dto.RecordQuery;
import com.classfee.dto.RecordRequest;
import com.classfee.entity.FeeCategory;
import com.classfee.entity.FeePayment;
import com.classfee.entity.FeeRecord;
import com.classfee.entity.SysUser;
import com.classfee.mapper.ClsClassMapper;
import com.classfee.mapper.FeeCategoryMapper;
import com.classfee.mapper.FeePaymentMapper;
import com.classfee.mapper.FeeRecordMapper;
import com.classfee.mapper.SysUserMapper;
import com.classfee.security.LoginUser;
import com.classfee.security.UserContext;
import com.classfee.vo.RecordVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.format.DateTimeParseException;
import java.util.Date;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;
import java.util.stream.Collectors;

/**
 * 收支流水服务：记账、查询、作废（红冲）、删除。
 * <p>
 * 三条铁律：
 * <ol>
 *   <li>记错优先走 {@link #voidRecord}（红冲留痕，历史可追溯）；管理员可
 *       {@link #deleteRecord} 物理删除，但必须同样在事务内回滚余额并联动批次缴费状态</li>
 *   <li>金额恒为正数，方向由 {@code type} 决定</li>
 *   <li>流水与 {@code cls_class.balance} 必须在同一事务内一并变更</li>
 * </ol>
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class RecordService {

    private final FeeRecordMapper recordMapper;
    private final FeeCategoryMapper categoryMapper;
    private final SysUserMapper userMapper;
    private final ClsClassMapper classMapper;
    private final FeePaymentMapper paymentMapper;

    /** 分页查询（当前班级） */
    public PageResult<RecordVO> list(RecordQuery query) {
        LoginUser user = UserContext.require();

        boolean hasType = query.getType() != null && !query.getType().isBlank();
        boolean hasStatus = query.getStatus() != null && !query.getStatus().isBlank();
        String keyword = query.getKeyword() == null ? null : query.getKeyword().trim();
        boolean hasKeyword = keyword != null && !keyword.isEmpty();

        Date start = parseDate(query.getStart(), false);
        Date end = parseDate(query.getEnd(), true);

        LambdaQueryWrapper<FeeRecord> wrapper = new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getClassId, user.getClassId())
                .eq(query.getId() != null, FeeRecord::getId, query.getId())
                .eq(hasType, FeeRecord::getType, query.getType())
                .eq(query.getCategoryId() != null, FeeRecord::getCategoryId, query.getCategoryId())
                .eq(hasStatus, FeeRecord::getStatus, query.getStatus())
                .ge(start != null, FeeRecord::getOccurredAt, start)
                .lt(end != null, FeeRecord::getOccurredAt, end)
                .orderByDesc(FeeRecord::getOccurredAt)
                .orderByDesc(FeeRecord::getId);
        if (hasKeyword) {
            String kw = escapeLike(keyword);
            wrapper.and(w -> w.like(FeeRecord::getTitle, kw).or().like(FeeRecord::getRemark, kw));
        }

        IPage<FeeRecord> page = recordMapper.selectPage(
                new Page<>(query.getPage(), query.getSize()), wrapper);

        return PageResult.of(toVOList(page.getRecords()), page.getTotal(),
                page.getCurrent(), page.getSize());
    }

    /** 记一笔（ADMIN）：插流水 + 同事务原子更新余额 */
    @Transactional(rollbackFor = Exception.class)
    public RecordVO create(RecordRequest request) {
        LoginUser user = UserContext.require();

        FeeCategory category = categoryMapper.selectById(request.getCategoryId());
        if (category == null || !user.getClassId().equals(category.getClassId())
                || category.getStatus() == null || category.getStatus() != 1) {
            throw BizException.badRequest("所选类别不存在或已停用");
        }
        if (!category.getKind().equals(request.getType())) {
            throw BizException.badRequest("类别与收支类型不匹配，请重新选择");
        }

        FeeRecord record = new FeeRecord();
        record.setClassId(user.getClassId());
        record.setType(request.getType());
        record.setCategoryId(category.getId());
        record.setAmount(request.getAmount());
        record.setTitle(request.getTitle().trim());
        record.setOccurredAt(request.getOccurredAt());
        record.setChannel(request.getChannel() == null || request.getChannel().isBlank()
                ? FeeRecord.CHANNEL_CASH : request.getChannel());
        record.setRemark(request.getRemark());
        record.setStatus(FeeRecord.STATUS_NORMAL);
        record.setCreatedBy(user.getId());
        recordMapper.insert(record);

        // 收入加、支出减；余额列靠数据库行锁原子更新
        if (classMapper.addBalance(user.getClassId(), deltaOf(record)) != 1) {
            throw BizException.badRequest("班级余额更新失败，请重试");
        }

        // 录入人姓名从库里取：JWT 只带 id/username/role/classId，不带 realName
        SysUser creator = userMapper.selectById(user.getId());
        String creatorName = creator != null ? creator.getRealName() : user.getUsername();

        log.info("记账：{} {} 元（类别={}，操作人={}）",
                record.getType(), record.getAmount(), category.getName(), user.getUsername());
        return toVO(record, category.getName(), creatorName);
    }

    /**
     * 作废（红冲）：状态置 VOID 并反向回滚余额。
     * 用 {@code status=NORMAL} 作为更新条件，重复作废/并发作废只会命中 0 行。
     */
    @Transactional(rollbackFor = Exception.class)
    public void voidRecord(Long id) {
        LoginUser user = UserContext.require();
        FeeRecord record = recordMapper.selectById(id);
        if (record == null || !user.getClassId().equals(record.getClassId())) {
            throw BizException.badRequest("流水不存在或无权操作");
        }
        if (FeeRecord.STATUS_VOID.equals(record.getStatus())) {
            throw BizException.badRequest("该流水已作废，无需重复操作");
        }

        int rows = recordMapper.update(null, new LambdaUpdateWrapper<FeeRecord>()
                .eq(FeeRecord::getId, id)
                .eq(FeeRecord::getStatus, FeeRecord.STATUS_NORMAL)
                .set(FeeRecord::getStatus, FeeRecord.STATUS_VOID));
        if (rows == 0) {
            throw BizException.badRequest("该流水状态已变化，请刷新后重试");
        }

        if (classMapper.addBalance(record.getClassId(), deltaOf(record).negate()) != 1) {
            throw BizException.badRequest("班级余额更新失败，请重试");
        }

        // 批次自动流水被作废 → 同事务把缴费状态退回未缴，
        // 维持不变式「已缴 ⟺ 存在 NORMAL 流水」，避免钱没了人还算已交
        if (record.getBatchId() != null) {
            paymentMapper.update(null, new LambdaUpdateWrapper<FeePayment>()
                    .eq(FeePayment::getRecordId, record.getId())
                    .eq(FeePayment::getStatus, FeePayment.STATUS_PAID)
                    .set(FeePayment::getStatus, FeePayment.STATUS_UNPAID));
        }

        log.info("作废流水 id={}：{} {} 元，余额已回滚", id, record.getType(), record.getAmount());
    }

    /**
     * 物理删除（管理员）：条件删除 + 余额回滚 + 批次缴费联动，同一事务。
     * <p>
     * 删除条件带上「读到的状态」：与作废/标记缴费并发时只会命中 0 行并整体回滚，
     * 不会出现“作废回滚一次、删除再回滚一次”的双扣。
     */
    @Transactional(rollbackFor = Exception.class)
    public void deleteRecord(Long id) {
        LoginUser user = UserContext.require();
        FeeRecord record = recordMapper.selectById(id);
        if (record == null || !user.getClassId().equals(record.getClassId())) {
            throw BizException.badRequest("流水不存在或无权操作");
        }

        int rows = recordMapper.delete(new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getId, id)
                .eq(FeeRecord::getStatus, record.getStatus()));
        if (rows == 0) {
            throw BizException.badRequest("该流水状态已变化，请刷新后重试");
        }

        // NORMAL 仍在对账求和里，删除要反向回滚余额；VOID 在作废时已回滚过，这里不动
        if (FeeRecord.STATUS_NORMAL.equals(record.getStatus())) {
            if (classMapper.addBalance(record.getClassId(), deltaOf(record).negate()) != 1) {
                throw BizException.badRequest("班级余额更新失败，请重试");
            }
        }

        // 批次流水被删 → 缴费行退回未缴并解除关联（含作废后留痕的 recordId），
        // 维持不变式「已缴 ⟺ 存在 NORMAL 流水」，且不留下悬挂的 record_id
        if (record.getBatchId() != null) {
            paymentMapper.update(null, new LambdaUpdateWrapper<FeePayment>()
                    .eq(FeePayment::getRecordId, record.getId())
                    .set(FeePayment::getStatus, FeePayment.STATUS_UNPAID)
                    .set(FeePayment::getRecordId, null));
        }

        log.info("删除流水 id={}：{} {} 元（原状态={}），余额已同步",
                id, record.getType(), record.getAmount(), record.getStatus());
    }

    /** 流水金额 → 余额增量（收入为正、支出为负） */
    private BigDecimal deltaOf(FeeRecord record) {
        return FeeRecord.TYPE_INCOME.equals(record.getType())
                ? record.getAmount()
                : record.getAmount().negate();
    }

    /** LIKE 通配符转义（参数化绑定已无注入风险，但 %/_ 会破坏匹配语义） */
    private String escapeLike(String raw) {
        return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_");
    }

    /** yyyy-MM-dd → Date；end 为“含当天”，转成次日零点做左闭右开 */
    private Date parseDate(String text, boolean isEnd) {
        if (text == null || text.isBlank()) {
            return null;
        }
        try {
            LocalDate date = LocalDate.parse(text.trim());
            LocalDate boundary = isEnd ? date.plusDays(1) : date;
            return Date.from(boundary.atStartOfDay(java.time.ZoneId.systemDefault()).toInstant());
        } catch (DateTimeParseException e) {
            throw BizException.badRequest("日期格式应为 yyyy-MM-dd");
        }
    }

    /** 批量补齐类别名与录入人姓名，避免逐条查询（N+1）；仪表盘复用 */
    public List<RecordVO> toVOList(List<FeeRecord> records) {
        if (records == null || records.isEmpty()) {
            return List.of();
        }
        Set<Long> categoryIds = records.stream()
                .map(FeeRecord::getCategoryId).filter(Objects::nonNull).collect(Collectors.toSet());
        Set<Long> userIds = records.stream()
                .map(FeeRecord::getCreatedBy).filter(Objects::nonNull).collect(Collectors.toSet());

        Map<Long, String> categoryName = categoryIds.isEmpty() ? Map.of()
                : categoryMapper.selectBatchIds(categoryIds).stream()
                        .collect(Collectors.toMap(FeeCategory::getId, FeeCategory::getName, (a, b) -> a));
        Map<Long, String> userName = userIds.isEmpty() ? Map.of()
                : userMapper.selectBatchIds(userIds).stream()
                        .collect(Collectors.toMap(SysUser::getId, SysUser::getRealName, (a, b) -> a));

        return records.stream()
                .map(r -> toVO(r, categoryName.get(r.getCategoryId()), userName.get(r.getCreatedBy())))
                .collect(Collectors.toList());
    }

    private RecordVO toVO(FeeRecord record, FeeCategory category, SysUser creator) {
        return toVO(record, category == null ? null : category.getName(),
                creator == null ? null : creator.getRealName());
    }

    private RecordVO toVO(FeeRecord record, String categoryName, String creatorName) {
        RecordVO vo = new RecordVO();
        vo.setId(record.getId());
        vo.setType(record.getType());
        vo.setCategoryId(record.getCategoryId());
        vo.setCategoryName(categoryName);
        vo.setAmount(record.getAmount());
        vo.setTitle(record.getTitle());
        vo.setOccurredAt(record.getOccurredAt());
        vo.setChannel(record.getChannel());
        vo.setRemark(record.getRemark());
        vo.setStatus(record.getStatus());
        vo.setCreatedBy(record.getCreatedBy());
        vo.setCreatedByName(creatorName);
        vo.setCreatedAt(record.getCreatedAt());
        return vo;
    }
}
