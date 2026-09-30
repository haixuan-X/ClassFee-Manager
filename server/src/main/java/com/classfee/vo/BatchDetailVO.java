package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;
import java.util.List;

/**
 * 批次详情：批次本身 + 逐人缴费明细
 */
@Data
public class BatchDetailVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private BatchVO batch;

    private List<PaymentVO> payments;
}
