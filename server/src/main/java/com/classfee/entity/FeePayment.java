package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;

/**
 * 成员缴费状态（每批次 × 每人一行）。
 * <p>
 * {@code status=PAID} 与其 {@code record_id} 指向的流水必须同生共死：
 * 标记缴费时同事务插流水，作废该流水时同事务回退为 UNPAID。
 */
@Data
@TableName("fee_payment")
public class FeePayment {

    public static final String STATUS_UNPAID = "UNPAID";
    public static final String STATUS_PAID = "PAID";
    public static final String STATUS_REFUNDED = "REFUNDED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long batchId;

    private Long userId;

    /** 实收，可大于应收；未缴费为 0.00 */
    private BigDecimal amount;

    /** UNPAID 未缴 / PAID 已缴 / REFUNDED 已退款 */
    private String status;

    /** CASH / WECHAT / ALIPAY / BANK / OTHER */
    private String channel;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date paidAt;

    /** 关联 fee_record.id（自动收款流水） */
    private Long recordId;

    private String remark;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;
}
