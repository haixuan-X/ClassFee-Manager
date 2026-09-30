package com.classfee.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 标记某成员已缴费入参（默认值全部来自批次：金额=每人应收、时间=现在、方式=现金）。
 */
@Data
public class BatchPayRequest implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 缴费成员 id */
    @NotNull(message = "请选择缴费成员")
    private Long userId;

    /** 实收金额；空则取批次的每人应收 */
    @DecimalMin(value = "0.01", message = "金额必须大于 0")
    @Digits(integer = 8, fraction = 2, message = "金额最多两位小数")
    private BigDecimal amount;

    /** 空则默认现金 */
    @Pattern(regexp = "CASH|WECHAT|ALIPAY|BANK|OTHER", message = "支付方式不合法")
    private String channel;

    /** 业务发生时间；空则取现在 */
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date occurredAt;

    @Size(max = 255, message = "备注最多 255 字")
    private String remark;
}
