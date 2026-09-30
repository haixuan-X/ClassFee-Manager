package com.classfee.controller;

import com.classfee.common.PageResult;
import com.classfee.common.R;
import com.classfee.dto.RecordQuery;
import com.classfee.dto.RecordRequest;
import com.classfee.security.RequireRole;
import com.classfee.security.Role;
import com.classfee.service.RecordService;
import com.classfee.vo.RecordVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 收支流水接口：查询全员可读，记账/作废仅管理员
 */
@RestController
@RequestMapping("/api/records")
@RequiredArgsConstructor
public class RecordController {

    private final RecordService recordService;

    /** 分页流水：page,size,type,categoryId,keyword,status,start,end */
    @GetMapping
    public R<PageResult<RecordVO>> list(@Valid RecordQuery query) {
        return R.ok(recordService.list(query));
    }

    /** 记一笔 */
    @PostMapping
    @RequireRole(Role.ADMIN)
    public R<RecordVO> create(@Valid @RequestBody RecordRequest request) {
        return R.ok(recordService.create(request));
    }

    /** 作废（红冲）：状态置 VOID 并回滚余额，历史保留 */
    @PostMapping("/{id}/void")
    @RequireRole(Role.ADMIN)
    public R<Void> voidRecord(@PathVariable Long id) {
        recordService.voidRecord(id);
        return R.ok();
    }

    /** 物理删除（ADMIN）：正常流水回滚余额并联动批次缴费状态，作废流水直接清除 */
    @DeleteMapping("/{id}")
    @RequireRole(Role.ADMIN)
    public R<Void> delete(@PathVariable Long id) {
        recordService.deleteRecord(id);
        return R.ok();
    }
}
