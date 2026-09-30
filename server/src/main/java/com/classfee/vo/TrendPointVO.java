package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;

/**
 * 月度收支趋势点
 */
@Data
public class TrendPointVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** yyyy-MM */
    private String ym;

    private BigDecimal income = BigDecimal.ZERO;

    private BigDecimal expense = BigDecimal.ZERO;
}
