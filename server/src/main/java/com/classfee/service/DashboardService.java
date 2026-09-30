package com.classfee.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.classfee.entity.ClsClass;
import com.classfee.entity.FeeRecord;
import com.classfee.mapper.ClsClassMapper;
import com.classfee.mapper.FeeRecordMapper;
import com.classfee.mapper.ReportMapper;
import com.classfee.security.LoginUser;
import com.classfee.security.UserContext;
import com.classfee.vo.MonthSumVO;
import com.classfee.vo.PieItemVO;
import com.classfee.vo.SummaryVO;
import com.classfee.vo.TrendPointVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.ZoneId;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.Date;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 仪表盘统计：余额、本月收支、近 N 月趋势、支出分类占比、最新流水。
 * <p>
 * 统一口径：只统计 {@code status='NORMAL'} 的流水，作废（红冲）不参与。
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class DashboardService {

    private static final DateTimeFormatter YM = DateTimeFormatter.ofPattern("yyyy-MM");
    private static final Date EPOCH = Date.from(LocalDate.of(1970, 1, 1)
            .atStartOfDay(ZoneId.systemDefault()).toInstant());
    private static final Date FAR_FUTURE = Date.from(LocalDate.of(2999, 1, 1)
            .atStartOfDay(ZoneId.systemDefault()).toInstant());

    private final ClsClassMapper classMapper;
    private final FeeRecordMapper recordMapper;
    private final ReportMapper reportMapper;
    private final RecordService recordService;
    private final BatchService batchService;

    public SummaryVO summary() {
        LoginUser user = UserContext.require();
        Long classId = user.getClassId();

        SummaryVO vo = new SummaryVO();

        // 冗余余额（记账时原子更新）
        ClsClass clazz = classMapper.selectById(classId);
        vo.setBalance(clazz == null || clazz.getBalance() == null ? BigDecimal.ZERO : clazz.getBalance());

        // 本月收支
        LocalDate today = LocalDate.now();
        Date monthStart = toDate(today.withDayOfMonth(1));
        Date monthEnd = toDate(today.plusMonths(1).withDayOfMonth(1));
        MonthSumVO month = reportMapper.sumRange(classId, monthStart, monthEnd);
        vo.setMonthIncome(month.getIncome());
        vo.setMonthExpense(month.getExpense());
        vo.setMonthCount(month.getCnt());

        // 全量流水对账：与冗余余额应当一致，不一致说明有并发或数据问题
        MonthSumVO all = reportMapper.sumRange(classId, EPOCH, FAR_FUTURE);
        vo.setRealBalance(all.getIncome().subtract(all.getExpense()));

        // 最新 5 笔（含作废，前端按状态标注）
        List<FeeRecord> latest = recordMapper.selectList(new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getClassId, classId)
                .orderByDesc(FeeRecord::getOccurredAt)
                .orderByDesc(FeeRecord::getId)
                .last("limit 5"));
        vo.setLatestRecords(recordService.toVOList(latest));

        // 最新收费批次的完成率（0-100）；班级还没有批次时为 null
        vo.setCompletionRate(batchService.completionRate(classId));
        // M4 接公告后才有值
        vo.setPinnedNotices(List.of());
        return vo;
    }

    /** 近 N 月收支趋势，缺月补零，保证横轴连续 */
    public List<TrendPointVO> trend(int months) {
        LoginUser user = UserContext.require();
        int n = normalizeMonths(months);

        LocalDate from = LocalDate.now().withDayOfMonth(1).minusMonths(n - 1L);
        List<TrendPointVO> rows = reportMapper.trend(user.getClassId(), toDate(from));
        Map<String, TrendPointVO> byYm = rows.stream()
                .collect(Collectors.toMap(TrendPointVO::getYm, Function.identity(), (a, b) -> a));

        List<TrendPointVO> result = new ArrayList<>(n);
        for (int i = 0; i < n; i++) {
            String ym = from.plusMonths(i).format(YM);
            TrendPointVO point = byYm.get(ym);
            if (point == null) {
                point = new TrendPointVO();
                point.setYm(ym);
            }
            result.add(point);
        }
        return result;
    }

    /** 近 N 月支出分类占比（环形图） */
    public List<PieItemVO> categoryPie(int months) {
        LoginUser user = UserContext.require();
        LocalDate from = LocalDate.now().withDayOfMonth(1).minusMonths(normalizeMonths(months) - 1L);
        return reportMapper.expenseByCategory(user.getClassId(), toDate(from));
    }

    private int normalizeMonths(int months) {
        if (months < 1 || months > 24) {
            throw com.classfee.common.BizException.badRequest("months 需在 1-24 之间");
        }
        return months;
    }

    private Date toDate(LocalDate day) {
        return Date.from(day.atStartOfDay(ZoneId.systemDefault()).toInstant());
    }
}
