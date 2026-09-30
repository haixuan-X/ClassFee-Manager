package com.classfee.dto;

import jakarta.validation.constraints.Pattern;
import lombok.Data;

import java.io.Serializable;

/**
 * 成员缴费列表查询条件。所有条件可选，组合过滤。
 */
@Data
public class MemberQuery implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 姓名/学号/登录名模糊匹配 */
    private String keyword;

    /** UNPAID / PAID / REFUNDED，空=全部 */
    @Pattern(regexp = "UNPAID|PAID|REFUNDED", message = "缴费状态不合法")
    private String payStatus;

    /** 指定批次；空则取最新进行中（其次最新）批次 */
    private Long batchId;
}
