package com.classfee.mapper;

import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.classfee.entity.ClsClass;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Update;

import java.math.BigDecimal;

/**
 * 班级表 Mapper
 */
public interface ClsClassMapper extends BaseMapper<ClsClass> {

    /**
     * 余额原子增减：靠数据库行锁串行化并发记账，避免“读-改-写”丢更新。
     * 收入传正数、支出传负数、作废传反向数。
     */
    @Update("UPDATE cls_class SET balance = balance + #{delta} WHERE id = #{id}")
    int addBalance(@Param("id") Long id, @Param("delta") BigDecimal delta);
}
