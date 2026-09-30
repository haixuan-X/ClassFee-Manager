package com.classfee.mapper;

import com.classfee.vo.MonthSumVO;
import com.classfee.vo.PieItemVO;
import com.classfee.vo.TrendPointVO;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.util.Date;
import java.util.List;

/**
 * 报表聚合查询（仪表盘）。
 * <p>
 * 统计口径统一：只算 {@code status='NORMAL'} 的流水，作废（红冲）不参与。
 */
public interface ReportMapper {

    /** 某时间区间的收入/支出合计（左闭右开） */
    @Select("""
            SELECT COALESCE(SUM(CASE WHEN type = 'INCOME'  THEN amount END), 0) AS income,
                   COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount END), 0) AS expense,
                   COUNT(*) AS cnt
              FROM fee_record
             WHERE class_id = #{classId}
               AND status = 'NORMAL'
               AND occurred_at >= #{start}
               AND occurred_at < #{end}
            """)
    MonthSumVO sumRange(@Param("classId") Long classId,
                        @Param("start") Date start,
                        @Param("end") Date end);

    /** 自 from 起的月度收支（缺月由 Service 补零） */
    @Select("""
            SELECT DATE_FORMAT(occurred_at, '%Y-%m') AS ym,
                   COALESCE(SUM(CASE WHEN type = 'INCOME'  THEN amount END), 0) AS income,
                   COALESCE(SUM(CASE WHEN type = 'EXPENSE' THEN amount END), 0) AS expense
              FROM fee_record
             WHERE class_id = #{classId}
               AND status = 'NORMAL'
               AND occurred_at >= #{from}
             GROUP BY ym
             ORDER BY ym
            """)
    List<TrendPointVO> trend(@Param("classId") Long classId, @Param("from") Date from);

    /** 近 N 月支出按类别占比（前端画环形图） */
    @Select("""
            SELECT c.name AS name, COALESCE(SUM(f.amount), 0) AS value
              FROM fee_record f
              JOIN fee_category c ON c.id = f.category_id
             WHERE f.class_id = #{classId}
               AND f.type = 'EXPENSE'
               AND f.status = 'NORMAL'
               AND f.occurred_at >= #{from}
             GROUP BY c.id, c.name
             ORDER BY value DESC
            """)
    List<PieItemVO> expenseByCategory(@Param("classId") Long classId, @Param("from") Date from);
}
