package com.classfee.security;

import com.classfee.common.BizException;
import io.jsonwebtoken.Claims;
import io.jsonwebtoken.JwtException;
import io.jsonwebtoken.Jwts;
import io.jsonwebtoken.security.Keys;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.SecretKey;
import java.nio.charset.StandardCharsets;
import java.util.Date;

/**
 * JWT 生成与解析（HS256）。
 * <p>
 * 选择 JWT 而非 Session：前后端分离、免状态、便于以后接小程序；
 * 代价是无法主动踢人，所以配了较短有效期（默认 2 小时）。
 */
@Component
public class JwtUtil {

    private static final String CLAIM_USERNAME = "username";
    private static final String CLAIM_ROLE = "role";
    private static final String CLAIM_CLASS_ID = "classId";

    @Value("${classfee.jwt.secret}")
    private String secret;

    @Value("${classfee.jwt.expire-hours}")
    private long expireHours;

    private SecretKey key() {
        // HS256 要求密钥 ≥ 256 bit
        return Keys.hmacShaKeyFor(secret.getBytes(StandardCharsets.UTF_8));
    }

    /** 签发令牌 */
    public String create(LoginUser user) {
        long now = System.currentTimeMillis();
        return Jwts.builder()
                .subject(String.valueOf(user.getId()))
                .claim(CLAIM_USERNAME, user.getUsername())
                .claim(CLAIM_ROLE, user.getRole())
                .claim(CLAIM_CLASS_ID, user.getClassId())
                .issuedAt(new Date(now))
                .expiration(new Date(now + expireHours * 3600_000L))
                .signWith(key())
                .compact();
    }

    /** 解析令牌，失败统一抛 401 */
    public LoginUser parse(String token) {
        try {
            Claims claims = Jwts.parser().verifyWith(key()).build()
                    .parseSignedClaims(token).getPayload();
            LoginUser user = new LoginUser();
            user.setId(Long.valueOf(claims.getSubject()));
            user.setUsername(claims.get(CLAIM_USERNAME, String.class));
            user.setRole(claims.get(CLAIM_ROLE, String.class));
            user.setClassId(claims.get(CLAIM_CLASS_ID, Number.class).longValue());
            return user;
        } catch (JwtException | IllegalArgumentException e) {
            throw BizException.unauthorized("登录已过期，请重新登录");
        }
    }
}
