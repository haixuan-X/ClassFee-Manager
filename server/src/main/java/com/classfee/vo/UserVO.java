package com.classfee.vo;

import lombok.Data;

import java.io.Serializable;

/**
 * 对外暴露的用户信息（绝不出参 password）
 */
@Data
public class UserVO implements Serializable {

    private static final long serialVersionUID = 1L;

    private Long id;
    private String username;
    private String realName;
    /** ADMIN / MEMBER / TEACHER */
    private String role;
    private Long classId;
    private String className;
}
