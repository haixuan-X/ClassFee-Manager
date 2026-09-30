package com.classfee.common;

import lombok.Getter;

/**
 * 业务异常：携带 HTTP 状态码 + 响应体 code，由 {@link GlobalExceptionHandler} 统一转换。
 */
@Getter
public class BizException extends RuntimeException {

    private static final long serialVersionUID = 1L;

    /** HTTP 状态码 */
    private final int status;
    /** 响应体中的业务 code */
    private final int code;

    public BizException(int status, int code, String message) {
        super(message);
        this.status = status;
        this.code = code;
    }

    /** code 与 HTTP 状态一致，如 400 / 401 / 403 */
    public static BizException of(int status, String message) {
        return new BizException(status, status, message);
    }

    /** 业务级错误（HTTP 200，前端按 code 展示提示），如 1001 */
    public static BizException biz(int code, String message) {
        return new BizException(200, code, message);
    }

    public static BizException badRequest(String message) {
        return of(400, message);
    }

    public static BizException unauthorized(String message) {
        return of(401, message);
    }

    public static BizException forbidden(String message) {
        return of(403, message);
    }
}
