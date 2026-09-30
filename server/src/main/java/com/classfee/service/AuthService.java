package com.classfee.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.classfee.common.BizException;
import com.classfee.dto.LoginRequest;
import com.classfee.dto.PasswordRequest;
import com.classfee.entity.ClsClass;
import com.classfee.entity.SysUser;
import com.classfee.mapper.ClsClassMapper;
import com.classfee.mapper.SysUserMapper;
import com.classfee.security.JwtUtil;
import com.classfee.security.LoginUser;
import com.classfee.security.Role;
import com.classfee.security.UserContext;
import com.classfee.vo.LoginVO;
import com.classfee.vo.UserVO;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Service;

import java.util.Date;

/**
 * 认证与账号服务
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class AuthService {

    /** 固定 strength=10，与 BCrypt 密文格式兼容 */
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    private final SysUserMapper userMapper;
    private final ClsClassMapper classMapper;
    private final JwtUtil jwtUtil;

    /** 登录：校验账号密码 → 签发 JWT */
    public LoginVO login(LoginRequest request) {
        SysUser user = userMapper.selectOne(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, request.getUsername())
                .last("limit 1"));

        // 用户名不存在与密码错误返回同一提示，避免账号枚举
        if (user == null || !encoder.matches(request.getPassword(), user.getPassword())) {
            throw new BizException(401, 40101, "账号或密码错误");
        }
        if (user.getStatus() == null || user.getStatus() != 1) {
            throw BizException.forbidden("账号已被停用，请联系班长");
        }

        SysUser patch = new SysUser();
        patch.setId(user.getId());
        patch.setLastLoginAt(new Date());
        userMapper.updateById(patch);

        LoginUser loginUser = toLoginUser(user);
        log.info("用户登录：{} ({})", user.getUsername(), user.getRole());
        return new LoginVO(jwtUtil.create(loginUser), toUserVO(user));
    }

    /** 当前登录用户信息 */
    public UserVO me() {
        LoginUser current = UserContext.require();
        SysUser user = userMapper.selectById(current.getId());
        if (user == null) {
            throw BizException.unauthorized("账号不存在或已被删除");
        }
        return toUserVO(user);
    }

    /** 修改密码：校验原密码 → 更新为 BCrypt 新密文 */
    public void changePassword(PasswordRequest request) {
        LoginUser current = UserContext.require();
        SysUser user = userMapper.selectById(current.getId());
        if (user == null) {
            throw BizException.unauthorized("账号不存在或已被删除");
        }
        if (!encoder.matches(request.getOldPassword(), user.getPassword())) {
            throw BizException.biz(1002, "原密码错误");
        }
        if (request.getOldPassword().equals(request.getNewPassword())) {
            throw BizException.biz(1003, "新密码不能与原密码相同");
        }

        SysUser patch = new SysUser();
        patch.setId(user.getId());
        patch.setPassword(encoder.encode(request.getNewPassword()));
        userMapper.updateById(patch);
        log.info("用户修改密码：{}", user.getUsername());
    }

    private LoginUser toLoginUser(SysUser user) {
        LoginUser loginUser = new LoginUser();
        loginUser.setId(user.getId());
        loginUser.setUsername(user.getUsername());
        loginUser.setRealName(user.getRealName());
        loginUser.setRole(user.getRole());
        loginUser.setClassId(user.getClassId());
        return loginUser;
    }

    private UserVO toUserVO(SysUser user) {
        UserVO vo = new UserVO();
        vo.setId(user.getId());
        vo.setUsername(user.getUsername());
        vo.setRealName(user.getRealName());
        vo.setRole(user.getRole() == null ? Role.MEMBER.name() : user.getRole());
        vo.setClassId(user.getClassId());
        if (user.getClassId() != null) {
            ClsClass clazz = classMapper.selectById(user.getClassId());
            vo.setClassName(clazz == null ? null : clazz.getClassName());
        }
        return vo;
    }
}
