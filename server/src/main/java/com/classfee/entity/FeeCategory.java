package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.Data;

/**
 * 收支类别字典
 */
@Data
@TableName("fee_category")
public class FeeCategory {

    public static final String KIND_INCOME = "INCOME";
    public static final String KIND_EXPENSE = "EXPENSE";

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long classId;

    private String name;

    /** INCOME / EXPENSE */
    private String kind;

    /** Element Plus 图标名 */
    private String icon;

    private Integer sort;

    private Integer status;
}
