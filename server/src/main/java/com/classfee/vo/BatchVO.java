package com.classfee.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 收费批次（含缴费统计）
 */
@Data
public class BatchVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;

    private String name;

    /** 每人应收 */
    private BigDecimal amount;

    @JsonFormat(pattern = "yyyy-MM-dd")
    private Date deadline;

    private String remark;

    /** OPEN 进行中 / CLOSED 已关闭 */
    private String status;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;

    /** 应缴人数（= fee_payment 行数） */
    private Long total;

    private Long paidCount;

    private Long unpaidCount;

    /** 完成率百分比 0-100，保留 1 位小数 */
    private BigDecimal rate;
}
