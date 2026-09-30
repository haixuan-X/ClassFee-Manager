package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;

/**
 * 时间区间收支合计
 */
@Data
public class MonthSumVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private BigDecimal income = BigDecimal.ZERO;

    private BigDecimal expense = BigDecimal.ZERO;

    /** 区间内正常流水条数 */
    private Long cnt;
}
