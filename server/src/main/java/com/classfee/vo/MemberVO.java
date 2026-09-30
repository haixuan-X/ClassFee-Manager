package com.classfee.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 成员缴费列表行：成员信息 + 指定批次下的缴费状态。
 * <p>
 * 班级还没有任何批次时 {@code batchId/payStatus} 为 null（前端引导先建批次）。
 */
@Data
public class MemberVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long userId;

    private String username;

    private String realName;

    private String studentNo;

    private String role;

    /** 1 启用 0 停用 */
    private Integer status;

    /** 当前查看的批次 id；无批次时为 null */
    private Long batchId;

    /** UNPAID / PAID / REFUNDED；无批次时为 null */
    private String payStatus;

    /** 实收金额；未缴或无批次时为 null */
    private BigDecimal amount;

    private String channel;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date paidAt;

    private Long recordId;
}
