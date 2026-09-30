package com.classfee.security;

import lombok.Getter;
import lombok.Setter;

import java.io.Serializable;

/**
 * 当前登录用户（从 JWT 解析得到），存放于 {@link UserContext} 的 ThreadLocal 中。
 */
@Getter
@Setter
public class LoginUser implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;
    private String username;
    private String realName;
    /** {@link Role} 名称 */
    private String role;
    private Long classId;
}
