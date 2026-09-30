package com.classfee.config;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.classfee.entity.ClsClass;
import com.classfee.entity.FeeCategory;
import com.classfee.entity.SysUser;
import com.classfee.mapper.ClsClassMapper;
import com.classfee.mapper.FeeCategoryMapper;
import com.classfee.mapper.SysUserMapper;
import com.classfee.security.Role;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 首次启动初始化种子数据：班级 + 管理员账号 + 默认收支类别。
 * <p>
 * 幂等：已存在则跳过。上线前把 {@code classfee.init.enabled} 设为 false。
 */
@Slf4j
@Component
@RequiredArgsConstructor
@ConditionalOnProperty(prefix = "classfee.init", name = "enabled", havingValue = "true", matchIfMissing = true)
public class DataInitializer implements ApplicationRunner {

    private static final String[][] INCOME_CATEGORIES = {
            {"班费收取", "Money"}, {"义卖收入", "Sell"}, {"捐款", "Present"},
            {"退款", "RefreshLeft"}, {"其他", "MoreFilled"}
    };
    private static final String[][] EXPENSE_CATEGORIES = {
            {"活动物资", "Goods"}, {"打印资料", "Document"}, {"饮用水", "Cup"},
            {"班会布置", "House"}, {"交通", "Bus"}, {"其他", "MoreFilled"}
    };

    /** 演示成员（登录名/姓名/角色）：M3 收费批次需要真实成员才能跑通 */
    private static final String[][] DEMO_MEMBERS = {
            {"20220102", "生活委员-李娜", Role.ADMIN.name()},
            {"teacher", "班主任-李老师", Role.TEACHER.name()},
            {"20220103", "王小明", Role.MEMBER.name()},
            {"20220104", "赵晓慧", Role.MEMBER.name()},
            {"20220105", "陈志强", Role.MEMBER.name()},
            {"20220106", "刘思彤", Role.MEMBER.name()},
            {"20220107", "孙浩然", Role.MEMBER.name()},
            {"20220108", "周雨欣", Role.MEMBER.name()},
            {"20220109", "吴嘉豪", Role.MEMBER.name()},
            {"20220110", "郑雅文", Role.MEMBER.name()},
            {"20220111", "冯天翊", Role.MEMBER.name()},
            {"20220112", "蒋若曦", Role.MEMBER.name()},
    };

    /** 演示成员统一初始密码（与管理员演示密码区分，README 有说明） */
    private static final String DEMO_MEMBER_PASSWORD = "123456";

    private final ClsClassMapper classMapper;
    private final SysUserMapper userMapper;
    private final FeeCategoryMapper categoryMapper;
    private final BCryptPasswordEncoder encoder = new BCryptPasswordEncoder();

    @Value("${classfee.init.username}")
    private String username;
    @Value("${classfee.init.password}")
    private String password;
    @Value("${classfee.init.real-name}")
    private String realName;
    @Value("${classfee.init.class-name}")
    private String className;
    @Value("${classfee.init.grade}")
    private String grade;
    @Value("${classfee.init.head-teacher}")
    private String headTeacher;

    @Override
    public void run(ApplicationArguments args) {
        Long classId = initClass();
        initAdmin(classId);
        initMembers(classId);
        initCategories(classId);
    }

    private Long initClass() {
        ClsClass existing = classMapper.selectOne(new LambdaQueryWrapper<ClsClass>()
                .eq(ClsClass::getClassName, className).last("limit 1"));
        if (existing != null) {
            return existing.getId();
        }
        ClsClass clazz = new ClsClass();
        clazz.setClassName(className);
        clazz.setGrade(grade);
        clazz.setHeadTeacher(headTeacher);
        clazz.setBalance(BigDecimal.ZERO);
        clazz.setStatus(1);
        classMapper.insert(clazz);
        log.info("已初始化班级：{}（id={}）", className, clazz.getId());
        return clazz.getId();
    }

    private void initAdmin(Long classId) {
        Long count = userMapper.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getUsername, username));
        if (count > 0) {
            return;
        }
        SysUser admin = new SysUser();
        admin.setClassId(classId);
        admin.setUsername(username);
        admin.setPassword(encoder.encode(password));
        admin.setRealName(realName);
        admin.setStudentNo(username);
        admin.setRole(Role.ADMIN.name());
        admin.setStatus(1);
        userMapper.insert(admin);
        log.warn("已创建初始管理员：{} / {}（首次登录后请立即修改密码）", username, password);
    }

    /**
     * 演示成员：班长之外的生活委员（ADMIN）、班主任（TEACHER）与 10 名普通成员。
     * 幂等：本班除初始管理员外已有任意账号则跳过（避免重复灌数据）。
     */
    private void initMembers(Long classId) {
        Long others = userMapper.selectCount(new LambdaQueryWrapper<SysUser>()
                .eq(SysUser::getClassId, classId)
                .ne(SysUser::getUsername, username));
        if (others != null && others > 0) {
            return;
        }
        String encoded = encoder.encode(DEMO_MEMBER_PASSWORD);
        for (String[] item : DEMO_MEMBERS) {
            SysUser member = new SysUser();
            member.setClassId(classId);
            member.setUsername(item[0]);
            member.setPassword(encoded);
            member.setRealName(item[1]);
            member.setStudentNo(item[0].startsWith("20") ? item[0] : null);
            member.setRole(item[2]);
            member.setStatus(1);
            userMapper.insert(member);
        }
        log.info("已初始化演示成员 {} 人（统一初始密码 {}，请提醒修改）",
                DEMO_MEMBERS.length, DEMO_MEMBER_PASSWORD);
    }

    private void initCategories(Long classId) {
        Long count = categoryMapper.selectCount(new LambdaQueryWrapper<FeeCategory>()
                .eq(FeeCategory::getClassId, classId));
        if (count > 0) {
            return;
        }
        List<FeeCategory> all = new ArrayList<>();
        int sort = 10;
        for (String[] item : INCOME_CATEGORIES) {
            all.add(build(classId, item, FeeCategory.KIND_INCOME, sort));
            sort += 10;
        }
        sort = 10;
        for (String[] item : EXPENSE_CATEGORIES) {
            all.add(build(classId, item, FeeCategory.KIND_EXPENSE, sort));
            sort += 10;
        }
        all.forEach(categoryMapper::insert);
        log.info("已初始化默认收支类别：收入 {} 个，支出 {} 个",
                INCOME_CATEGORIES.length, EXPENSE_CATEGORIES.length);
    }

    private FeeCategory build(Long classId, String[] item, String kind, int sort) {
        FeeCategory category = new FeeCategory();
        category.setClassId(classId);
        category.setName(item[0]);
        category.setKind(kind);
        category.setIcon(item[1]);
        category.setSort(sort);
        category.setStatus(1);
        return category;
    }
}
