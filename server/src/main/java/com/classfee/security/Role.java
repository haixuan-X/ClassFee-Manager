package com.classfee.security;

/**
 * 系统角色，与 sys_user.role 一一对应。
 */
public enum Role {

    /** 班级管理员（班长/生活委员）：记账、成员、批次、公告 */
    ADMIN,
    /** 普通成员（同学）：只读 */
    MEMBER,
    /** 班主任：只读监督 */
    TEACHER;

    public boolean sameAs(String name) {
        return this.name().equals(name);
    }
}
