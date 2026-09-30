package com.classfee.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 新增收支流水入参
 */
@Data
public class RecordRequest implements Serializable {

    private static final long serialVersionUID = 1L;

    @NotBlank(message = "请选择收支类型")
    @Pattern(regexp = "INCOME|EXPENSE", message = "收支类型不合法")
    private String type;

    @NotNull(message = "请选择收支类别")
    private Long categoryId;

    @NotNull(message = "请输入金额")
    @DecimalMin(value = "0.01", message = "金额必须大于 0")
    @Digits(integer = 8, fraction = 2, message = "金额最多两位小数")
    private BigDecimal amount;

    @NotBlank(message = "请填写摘要")
    @Size(max = 60, message = "摘要最多 60 字")
    private String title;

    @NotNull(message = "请选择发生时间")
    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date occurredAt;

    /** 空则默认现金 */
    @Pattern(regexp = "CASH|WECHAT|ALIPAY|BANK|OTHER", message = "支付方式不合法")
    private String channel;

    @Size(max = 255, message = "备注最多 255 字")
    private String remark;
}
