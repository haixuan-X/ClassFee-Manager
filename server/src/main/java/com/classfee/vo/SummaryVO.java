package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.List;

/**
 * 仪表盘汇总
 */
@Data
public class SummaryVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** cls_class.balance 冗余余额 */
    private BigDecimal balance;

    /** 由全部正常流水实时求和，用于与冗余余额对账 */
    private BigDecimal realBalance;

    private BigDecimal monthIncome;

    private BigDecimal monthExpense;

    /** 本月正常流水条数 */
    private Long monthCount;

    /** 缴费完成率百分比 0-100（1 位小数）；班级还没有收费批次时为 null */
    private BigDecimal completionRate;

    /** 最新 5 笔流水（含作废，标注状态） */
    private List<RecordVO> latestRecords;

    /** 置顶公告（M4 公告接入后才有值，当前为空） */
    private List<NoticeVO> pinnedNotices;
}
