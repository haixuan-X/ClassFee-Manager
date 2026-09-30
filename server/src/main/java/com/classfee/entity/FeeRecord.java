package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;

/**
 * 班费收支流水（核心表，只增不改）。
 * <p>
 * 记错不修改也不删除，只把 {@code status} 置为 VOID（红冲），同时回滚余额，
 * 保证账目全程可追溯。
 */
@Data
@TableName("fee_record")
public class FeeRecord {

    public static final String TYPE_INCOME = "INCOME";
    public static final String TYPE_EXPENSE = "EXPENSE";

    public static final String STATUS_NORMAL = "NORMAL";
    public static final String STATUS_VOID = "VOID";

    public static final String CHANNEL_CASH = "CASH";
    public static final String CHANNEL_WECHAT = "WECHAT";
    public static final String CHANNEL_ALIPAY = "ALIPAY";
    public static final String CHANNEL_BANK = "BANK";
    public static final String CHANNEL_OTHER = "OTHER";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long classId;

    /** INCOME / EXPENSE，金额恒为正数，方向由本字段决定 */
    private String type;

    private Long categoryId;

    private BigDecimal amount;

    /** 摘要，如「收取XX班费」「购买班级活动矿泉水」 */
    private String title;

    /** 业务发生时间（非录入时间） */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date occurredAt;

    /** CASH / WECHAT / ALIPAY / BANK / OTHER */
    private String channel;

    /** 收入：缴费人；支出留空 */
    private Long payerUserId;

    /** 来收费批次（M3） */
    private Long batchId;

    private String remark;

    private String receiptUrl;

    /** NORMAL 正常 / VOID 已作废（红冲） */
    private String status;

    private Long createdBy;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date updatedAt;
}
