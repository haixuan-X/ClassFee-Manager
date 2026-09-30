package com.classfee.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.classfee.common.BizException;
import com.classfee.dto.CategoryRequest;
import com.classfee.entity.FeeCategory;
import com.classfee.entity.FeeRecord;
import com.classfee.mapper.FeeCategoryMapper;
import com.classfee.mapper.FeeRecordMapper;
import com.classfee.security.LoginUser;
import com.classfee.security.UserContext;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/**
 * 收支类别字典服务
 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CategoryService {

    private final FeeCategoryMapper categoryMapper;
    private final FeeRecordMapper recordMapper;

    /** 本班已启用类别，按 sort 排序 */
    public List<FeeCategory> list(String kind) {
        LoginUser user = UserContext.require();
        boolean hasKind = kind != null && !kind.isBlank();
        return categoryMapper.selectList(new LambdaQueryWrapper<FeeCategory>()
                .eq(FeeCategory::getClassId, user.getClassId())
                .eq(FeeCategory::getStatus, 1)
                .eq(hasKind, FeeCategory::getKind, kind)
                .orderByAsc(FeeCategory::getSort)
                .orderByAsc(FeeCategory::getId));
    }

    @Transactional(rollbackFor = Exception.class)
    public void create(CategoryRequest request) {
        LoginUser user = UserContext.require();
        ensureNameUnique(user.getClassId(), request.getKind(), request.getName(), null);

        FeeCategory entity = new FeeCategory();
        entity.setClassId(user.getClassId());
        apply(entity, request);
        entity.setStatus(1);
        categoryMapper.insert(entity);
        log.info("新增类别：{}（{}）", request.getName(), request.getKind());
    }

    @Transactional(rollbackFor = Exception.class)
    public void update(CategoryRequest request) {
        if (request.getId() == null) {
            throw BizException.badRequest("缺少类别 id");
        }
        LoginUser user = UserContext.require();
        FeeCategory existing = requireOwned(request.getId(), user.getClassId());
        ensureNameUnique(existing.getClassId(), request.getKind(), request.getName(), existing.getId());

        FeeCategory patch = new FeeCategory();
        patch.setId(existing.getId());
        apply(patch, request);
        categoryMapper.updateById(patch);
        log.info("更新类别 id={}：{}", existing.getId(), request.getName());
    }

    /**
     * 删除（ADMIN）：未被任何流水引用的类别直接移除（腾出同名位），
     * 被流水引用过的一律拒绝——历史账目要能还原类别名。
     */
    @Transactional(rollbackFor = Exception.class)
    public void delete(Long id) {
        LoginUser user = UserContext.require();
        requireOwned(id, user.getClassId());

        Long used = recordMapper.selectCount(new LambdaQueryWrapper<FeeRecord>()
                .eq(FeeRecord::getCategoryId, id));
        if (used != null && used > 0) {
            throw BizException.badRequest("该类别已有 " + used + " 笔流水，不能删除；可改名继续使用");
        }

        categoryMapper.deleteById(id);
        log.info("删除类别 id={}", id);
    }

    private FeeCategory requireOwned(Long id, Long classId) {
        FeeCategory existing = categoryMapper.selectById(id);
        // 他班类别一律当不存在，避免暴露存在性
        if (existing == null || !classId.equals(existing.getClassId())) {
            throw BizException.badRequest("类别不存在或已停用");
        }
        return existing;
    }

    private void ensureNameUnique(Long classId, String kind, String name, Long excludeId) {
        Long dup = categoryMapper.selectCount(new LambdaQueryWrapper<FeeCategory>()
                .eq(FeeCategory::getClassId, classId)
                .eq(FeeCategory::getKind, kind)
                .eq(FeeCategory::getName, name)
                // 只查启用中的：历史遗留的软删行（status=0）不该永久占住名字
                .eq(FeeCategory::getStatus, 1)
                .ne(excludeId != null, FeeCategory::getId, excludeId));
        if (dup != null && dup > 0) {
            throw BizException.badRequest("同类下已存在同名类别");
        }
    }

    private void apply(FeeCategory entity, CategoryRequest request) {
        entity.setName(request.getName());
        entity.setKind(request.getKind());
        entity.setIcon(request.getIcon());
        entity.setSort(request.getSort() == null ? 0 : request.getSort());
    }
}
