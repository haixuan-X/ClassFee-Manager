package com.classfee.dto;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import lombok.Data;

import java.io.Serializable;

/**
 * 流水分页查询条件。所有条件可选，组合过滤。
 */
@Data
public class RecordQuery implements Serializable {

    private static final long serialVersionUID = 1L;

    @Min(value = 1, message = "页码从 1 开始")
    private long page = 1;

    @Min(value = 1, message = "每页至少 1 条")
    @Max(value = 100, message = "每页最多 100 条")
    private long size = 20;

    /** INCOME / EXPENSE，空=全部 */
    private String type;

    private Long categoryId;

    /** 摘要/备注模糊匹配 */
    private String keyword;

    /** NORMAL / VOID，空=全部 */
    private String status;

    /** 精确查某条流水（如批次明细「查看流水」跳转）；与其余条件同时生效（AND） */
    private Long id;

    /** 起始日期 yyyy-MM-dd（含当天） */
    private String start;

    /** 结束日期 yyyy-MM-dd（含当天） */
    private String end;
}
