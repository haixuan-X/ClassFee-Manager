package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;

/**
 * 收费批次：建批次（金额/截止日）→ 逐人标记缴费 → 自动生成流水 → 关闭批次。
 * <p>
 * 创建时会为全班成员各建一条 {@code fee_payment}（UNPAID），
 * 靠 {@code uk_batch_user} 唯一键防止重复建行。
 */
@Data
@TableName("fee_batch")
public class FeeBatch {

    public static final String STATUS_OPEN = "OPEN";
    public static final String STATUS_CLOSED = "CLOSED";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long classId;

    /** 如 2026 春季班费 */
    private String name;

    /** 每人应收 */
    private BigDecimal amount;

    /** 截止日（可空） */
    @JsonFormat(pattern = "yyyy-MM-dd")
    private Date deadline;

    private String remark;

    /** OPEN 进行中 / CLOSED 已关闭 */
    private String status;

    private Long createdBy;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;
}
