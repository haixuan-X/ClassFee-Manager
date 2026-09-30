package com.classfee.controller;

import com.classfee.common.R;
import com.classfee.service.DashboardService;
import com.classfee.vo.PieItemVO;
import com.classfee.vo.SummaryVO;
import com.classfee.vo.TrendPointVO;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 仪表盘统计接口
 */
@RestController
@RequestMapping("/api/dashboard")
@RequiredArgsConstructor
public class DashboardController {

    private final DashboardService dashboardService;

    /** 余额 / 本月收支 / 最新 5 笔 */
    @GetMapping("/summary")
    public R<SummaryVO> summary() {
        return R.ok(dashboardService.summary());
    }

    /** 近 N 月收支趋势，months 默认 6 */
    @GetMapping("/trend")
    public R<List<TrendPointVO>> trend(@RequestParam(defaultValue = "6") int months) {
        return R.ok(dashboardService.trend(months));
    }

    /** 近 N 月支出分类占比 */
    @GetMapping("/category-pie")
    public R<List<PieItemVO>> categoryPie(@RequestParam(defaultValue = "6") int months) {
        return R.ok(dashboardService.categoryPie(months));
    }
}
