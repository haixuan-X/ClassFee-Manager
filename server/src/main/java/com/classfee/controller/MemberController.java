package com.classfee.controller;

import com.classfee.common.R;
import com.classfee.dto.MemberQuery;
import com.classfee.security.RequireRole;
import com.classfee.security.Role;
import com.classfee.service.BatchService;
import com.classfee.vo.MemberVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 成员缴费接口（M6）：成员列表 + 指定批次的缴费状态，仅管理员。
 */
@RestController
@RequestMapping("/api/members")
@RequiredArgsConstructor
public class MemberController {

    private final BatchService batchService;

    /** keyword / payStatus / batchId 均可选；batchId 为空取最新进行中批次 */
    @GetMapping
    @RequireRole(Role.ADMIN)
    public R<List<MemberVO>> list(@Valid MemberQuery query) {
        return R.ok(batchService.members(query));
    }
}
