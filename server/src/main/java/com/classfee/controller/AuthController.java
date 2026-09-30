package com.classfee.controller;

import com.classfee.common.R;
import com.classfee.dto.LoginRequest;
import com.classfee.dto.PasswordRequest;
import com.classfee.service.AuthService;
import com.classfee.vo.LoginVO;
import com.classfee.vo.UserVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 认证接口
 */
@RestController
@RequestMapping("/api/auth")
@RequiredArgsConstructor
public class AuthController {

    private final AuthService authService;

    /** 登录（免鉴权，由拦截器排除） */
    @PostMapping("/login")
    public R<LoginVO> login(@Valid @RequestBody LoginRequest request) {
        return R.ok(authService.login(request));
    }

    /** 当前登录用户 */
    @GetMapping("/me")
    public R<UserVO> me() {
        return R.ok(authService.me());
    }

    /** 修改密码 */
    @PutMapping("/password")
    public R<Void> changePassword(@Valid @RequestBody PasswordRequest request) {
        authService.changePassword(request);
        return R.ok();
    }
}
