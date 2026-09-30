package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;
import java.math.BigDecimal;

/**
 * 环形图数据项
 */
@Data
public class PieItemVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private String name;

    private BigDecimal value;
}
