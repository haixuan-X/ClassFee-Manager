package com.classfee.common;

import lombok.extern.slf4j.Slf4j;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.validation.FieldError;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.MissingServletRequestParameterException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

import jakarta.validation.ConstraintViolationException;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;

/**
 * 全局异常处理：所有异常统一转成 R 结构，HTTP 状态码与业务 code 保持一致。
 */
@Slf4j
@RestControllerAdvice
public class GlobalExceptionHandler {

    /** 业务异常：由业务代码显式抛出 */
    @ExceptionHandler(BizException.class)
    public ResponseEntity<R<Object>> handleBiz(BizException e) {
        if (e.getStatus() >= 500) {
            log.error("业务异常 code={}", e.getCode(), e);
        }
        return ResponseEntity.status(e.getStatus()).body(R.fail(e.getCode(), e.getMessage()));
    }

    /** @Valid 参数校验失败：逐字段返回，供前端定位到具体输入框 */
    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<R<Object>> handleValid(MethodArgumentNotValidException e) {
        List<Map<String, String>> errors = e.getBindingResult().getFieldErrors().stream()
                .map(this::toItem)
                .collect(Collectors.toList());
        return ResponseEntity.badRequest()
                .body(R.fail(HttpStatus.BAD_REQUEST.value(), "参数校验失败", errors));
    }

    /** 请求体不是合法 JSON / 缺少必填参数 / 参数类型不匹配 */
    @ExceptionHandler({HttpMessageNotReadableException.class,
            MissingServletRequestParameterException.class,
            MethodArgumentTypeMismatchException.class,
            ConstraintViolationException.class})
    public ResponseEntity<R<Object>> handleParam(Exception e) {
        if (e instanceof ConstraintViolationException cve && !cve.getConstraintViolations().isEmpty()) {
            String first = cve.getConstraintViolations().iterator().next().getMessage();
            return ResponseEntity.badRequest().body(R.fail(HttpStatus.BAD_REQUEST.value(), first));
        }
        String message = e instanceof HttpMessageNotReadableException ? "请求体格式不正确" : "请求参数不合法";
        return ResponseEntity.badRequest().body(R.fail(HttpStatus.BAD_REQUEST.value(), message));
    }

    /** 不存在的接口路径：返回 404，而不是当成系统异常返回 500 */
    @ExceptionHandler(NoResourceFoundException.class)
    public ResponseEntity<R<Object>> handleNoResource(NoResourceFoundException e) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(R.fail(HttpStatus.NOT_FOUND.value(), "接口不存在"));
    }

    /** 兜底：未预期异常，不向前端泄露堆栈 */
    @ExceptionHandler(Exception.class)
    public ResponseEntity<R<Object>> handleOther(Exception e) {
        log.error("系统异常", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(R.fail(HttpStatus.INTERNAL_SERVER_ERROR.value(), "系统繁忙，请稍后重试"));
    }

    private Map<String, String> toItem(FieldError e) {
        Map<String, String> item = new LinkedHashMap<>(4);
        item.put("field", e.getField());
        item.put("message", e.getDefaultMessage());
        return item;
    }
}
