package com.classfee.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Data;

import java.io.Serializable;

/**
 * 类别维护入参（新建时 id 为空，更新时必填）
 */
@Data
public class CategoryRequest implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;

    @NotBlank(message = "请输入类别名称")
    @Size(max = 30, message = "类别名称最多 30 字")
    private String name;

    @NotBlank(message = "请选择类别方向")
    @Pattern(regexp = "INCOME|EXPENSE", message = "类别方向不合法")
    private String kind;

    /** Element Plus 图标名，可空 */
    @Size(max = 50, message = "图标名最多 50 字")
    private String icon;

    /** 排序，越小越靠前 */
    private Integer sort;
}
