package com.classfee.common;

import lombok.Getter;

import java.io.Serializable;

/**
 * 统一响应体：{ code, message, data }
 *
 * @param <data> 数据类型
 */
@Getter
public class R<T> implements Serializable {

    private static final long serialVersionUID = 1L;

    public static final int OK = 200;

    private final int code;
    private final String message;
    private final T data;

    private R(int code, String message, T data) {
        this.code = code;
        this.message = message;
        this.data = data;
    }

    public static <T> R<T> ok(T data) {
        return new R<>(OK, "ok", data);
    }

    public static <T> R<T> ok() {
        return new R<>(OK, "ok", null);
    }

    public static <T> R<T> fail(int code, String message) {
        return new R<>(code, message, null);
    }

    public static <T> R<T> fail(int code, String message, T data) {
        return new R<>(code, message, data);
    }
}
