package com.classfee.security;

import com.classfee.common.BizException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Component;
import org.springframework.web.method.HandlerMethod;
import org.springframework.web.servlet.HandlerInterceptor;

import java.util.Arrays;

/**
 * 认证 + 鉴权拦截器。
 * <ul>
 *   <li>校验 {@code Authorization: Bearer &lt;token&gt;}，解析出登录用户放入 {@link UserContext}</li>
 *   <li>若方法标注了 {@link RequireRole}，校验角色，不符抛 403</li>
 * </ul>
 * 真正的权限边界在这里，前端隐藏入口只是体验优化。
 */
@Component
@RequiredArgsConstructor
public class AuthInterceptor implements HandlerInterceptor {

    private static final String BEARER_PREFIX = "Bearer ";

    private final JwtUtil jwtUtil;

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String header = request.getHeader("Authorization");
        if (header == null || !header.startsWith(BEARER_PREFIX)) {
            throw BizException.unauthorized("未登录或登录已过期");
        }

        LoginUser user = jwtUtil.parse(header.substring(BEARER_PREFIX.length()));
        UserContext.set(user);

        try {
            if (handler instanceof HandlerMethod method) {
                RequireRole requireRole = method.getMethodAnnotation(RequireRole.class);
                if (requireRole != null && Arrays.stream(requireRole.value())
                        .noneMatch(role -> role.sameAs(user.getRole()))) {
                    throw BizException.forbidden("当前角色无权执行该操作");
                }
            }
            return true;
        } catch (BizException e) {
            // preHandle 抛异常时 afterCompletion 不会执行，需自行清理 ThreadLocal
            UserContext.clear();
            throw e;
        }
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response,
                                Object handler, Exception ex) {
        UserContext.clear();
    }
}
