package com.classfee.dto;

import com.fasterxml.jackson.annotation.JsonFormat;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Digits;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 新建收费批次入参
 */
@Data
public class BatchRequest implements Serializable {

    private static final long serialVersionUID = 1L;

    @NotBlank(message = "请填写批次名称")
    @Size(max = 60, message = "批次名称最多 60 字")
    private String name;

    @NotNull(message = "请填写每人应收金额")
    @DecimalMin(value = "0.01", message = "金额必须大于 0")
    @Digits(integer = 8, fraction = 2, message = "金额最多两位小数")
    private BigDecimal amount;

    /** 截止日，可空；yyyy-MM-dd */
    @JsonFormat(pattern = "yyyy-MM-dd")
    private Date deadline;

    @Size(max = 255, message = "备注最多 255 字")
    private String remark;
}
