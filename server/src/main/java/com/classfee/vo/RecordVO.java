package com.classfee.vo;

import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;
import java.util.Date;

/**
 * 流水出参（含类别名与录入人，前端免二次查询）
 */
@Data
public class RecordVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;

    /** INCOME / EXPENSE */
    private String type;

    private Long categoryId;

    private String categoryName;

    private BigDecimal amount;

    private String title;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date occurredAt;

    private String channel;

    private String remark;

    /** NORMAL / VOID */
    private String status;

    private Long createdBy;

    private String createdByName;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;
}
