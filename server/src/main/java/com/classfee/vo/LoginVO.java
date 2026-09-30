package com.classfee.vo;

import lombok.AllArgsConstructor;
import lombok.Data;

import java.io.Serializable;

/**
 * 登录成功返回
 */
@Data
@AllArgsConstructor
public class LoginVO implements Serializable {

    private static final long serialVersionUID = 1L;

    /** 后续请求放 Header：Authorization: Bearer &lt;token&gt; */
    private String token;

    private UserVO user;
}
