package com.classfee.security;

import java.lang.annotation.ElementType;
import java.lang.annotation.Retention;
import java.lang.annotation.RetentionPolicy;
import java.lang.annotation.Target;

/**
 * 接口角色校验：标注在 Controller 方法上，由 {@link AuthInterceptor} 强制校验。
 * <p>
 * 注意：前端隐藏入口只是体验优化，权限的真正边界在这里。
 */
@Target(ElementType.METHOD)
@Retention(RetentionPolicy.RUNTIME)
public @interface RequireRole {

    /** 允许访问的角色列表 */
    Role[] value();
}
