package com.classfee.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonFormat;
import com.fasterxml.jackson.annotation.JsonIgnore;
import lombok.Data;

import java.util.Date;

/**
 * 系统用户 / 班级成员
 */
@Data
@TableName("sys_user")
public class SysUser {

    @TableId(type = IdType.AUTO)
    private Long id;

    private Long classId;

    /** 登录名，默认与学号一致 */
    private String username;

    /** BCrypt 密文，任何情况下都不允许返回给前端 */
    @JsonIgnore
    private String password;

    private String realName;

    private String studentNo;

    /** {@link com.classfee.security.Role} */
    private String role;

    private String phone;

    /** 1 启用 0 停用 */
    private Integer status;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date lastLoginAt;

    @JsonFormat(pattern = "yyyy-MM-dd HH:mm:ss")
    private Date createdAt;
}
