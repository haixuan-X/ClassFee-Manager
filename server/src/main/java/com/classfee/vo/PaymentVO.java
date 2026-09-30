package com.classfee.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 批次明细行：某成员在某批次的缴费状态
 */
@Data
public class PaymentVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** fee_payment.id */
    private Long id;

    private Long userId;

    private String realName;

    private String studentNo;

    /** 角色名，区分班长/班主任 */
    private String role;

    /** UNPAID 未缴 / PAID 已缴 / REFUNDED 已退款 */
    private String status;

    /** 实收金额 */
    private BigDecimal amount;

    private String channel;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date paidAt;

    /** 自动生成的收款流水 id */
    private Long recordId;

    private String remark;
}
