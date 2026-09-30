package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import lombok.Data;

import java.math.BigDecimal;
import java.util.Date;

/**
 * 班级
 */
@Data
@TableName("cls_class")
public class ClsClass {

    @TableId(type = IdType.AUTO)
    private Long id;

    private String className;

    private String grade;

    private String headTeacher;

    /**
     * 冗余余额：记账/作废时在事务内原子更新，
     * 真值仍以 fee_record 的 SUM 为准，可定期对账。
     */
    private BigDecimal balance;

    private Integer status;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date updatedAt;
}
