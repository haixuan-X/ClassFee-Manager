package com.classfee.controller;

import com.classfee.common.R;
import com.classfee.dto.CategoryRequest;
import com.classfee.entity.FeeCategory;
import com.classfee.security.RequireRole;
import com.classfee.security.Role;
import com.classfee.service.CategoryService;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

/**
 * 收支类别字典：读全员，写仅管理员
 */
@RestController
@RequestMapping("/api/categories")
@RequiredArgsConstructor
public class CategoryController {

    private final CategoryService categoryService;

    /** 类别列表，kind=INCOME|EXPENSE 可选 */
    @GetMapping
    public R<List<FeeCategory>> list(@RequestParam(required = false) String kind) {
        return R.ok(categoryService.list(kind));
    }

    @PostMapping
    @RequireRole(Role.ADMIN)
    public R<Void> create(@Valid @RequestBody CategoryRequest request) {
        categoryService.create(request);
        return R.ok();
    }

    @PutMapping("/{id}")
    @RequireRole(Role.ADMIN)
    public R<Void> update(@PathVariable Long id, @Valid @RequestBody CategoryRequest request) {
        request.setId(id);
        categoryService.update(request);
        return R.ok();
    }

    @DeleteMapping("/{id}")
    @RequireRole(Role.ADMIN)
    public R<Void> delete(@PathVariable Long id) {
        categoryService.delete(id);
        return R.ok();
    }
}
