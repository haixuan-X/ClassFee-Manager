package com.classfee.controller;

import com.classfee.common.R;
import com.classfee.dto.BatchPayRequest;
import com.classfee.dto.BatchRequest;
import com.classfee.security.RequireRole;
import com.classfee.security.Role;
import com.classfee.service.BatchService;
import com.classfee.vo.BatchDetailVO;
import com.classfee.vo.BatchVO;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 收费批次接口：全部仅管理员（建批次/标记缴费都直接动钱）。
 * <p>
 * 仪表盘的完成率不走这里，由 DashboardService 内部调 {@link BatchService}，
 * 保证 MEMBER 不需要批次读权限也能看到完成率。
 */
@RestController
@RequestMapping("/api/batches")
@RequiredArgsConstructor
public class BatchController {

    private final BatchService batchService;

    /** 批次列表（含人数与完成率） */
    @GetMapping
    @RequireRole(Role.ADMIN)
    public R<List<BatchVO>> list() {
        return R.ok(batchService.list());
    }

    /** 新建批次：为全班成员生成未缴记录 */
    @PostMapping
    @RequireRole(Role.ADMIN)
    public R<BatchVO> create(@Valid @RequestBody BatchRequest request) {
        return R.ok(batchService.create(request));
    }

    /** 批次详情（谁交了谁没交） */
    @GetMapping("/{id}/payments")
    @RequireRole(Role.ADMIN)
    public R<BatchDetailVO> detail(@PathVariable Long id) {
        return R.ok(batchService.detail(id));
    }

    /** 标记某人已交 → 同事务生成收款流水并更新余额 */
    @PostMapping("/{id}/pay")
    @RequireRole(Role.ADMIN)
    public R<Void> pay(@PathVariable Long id, @Valid @RequestBody BatchPayRequest request) {
        batchService.pay(id, request);
        return R.ok();
    }

    /** 关闭批次：关闭后不能再标记缴费 */
    @PostMapping("/{id}/close")
    @RequireRole(Role.ADMIN)
    public R<Void> close(@PathVariable Long id) {
        batchService.close(id);
        return R.ok();
    }

    /** 删除批次：级联清理其缴费状态与全部流水（正常流水余额同事务回滚） */
    @DeleteMapping("/{id}")
    @RequireRole(Role.ADMIN)
    public R<Void> delete(@PathVariable Long id) {
        batchService.deleteBatch(id);
        return R.ok();
    }
}
