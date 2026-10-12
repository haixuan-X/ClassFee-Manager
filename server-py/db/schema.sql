-- ============================================================
-- 班费收支系统 · 数据库结构（MySQL 8 / MariaDB 10.6+ 兼容）
-- 幂等：可重复执行；应用启动时也会自动执行（spring.sql.init.mode=always）
-- ============================================================
CREATE TABLE IF NOT EXISTS cls_class (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  class_name   VARCHAR(50)  NOT NULL                COMMENT '班级名称，如 计科2201',
  grade        VARCHAR(20)  NULL                    COMMENT '年级/届别',
  head_teacher VARCHAR(50)  NULL                    COMMENT '班主任',
  balance      DECIMAL(12,2) NOT NULL DEFAULT 0.00  COMMENT '冗余余额，由流水事务同步、用流水对账',
  status       TINYINT      NOT NULL DEFAULT 1      COMMENT '1启用 0停用',
  created_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级';

CREATE TABLE IF NOT EXISTS sys_user (
  id            BIGINT      NOT NULL AUTO_INCREMENT,
  class_id      BIGINT      NOT NULL,
  username      VARCHAR(32) NOT NULL                COMMENT '登录名=学号',
  password      VARCHAR(100) NOT NULL               COMMENT 'BCrypt 密文',
  real_name     VARCHAR(32) NOT NULL,
  student_no    VARCHAR(20) NULL,
  role          ENUM('ADMIN','MEMBER','GUEST','MONITOR','TEACHER') NOT NULL DEFAULT 'MEMBER',
  phone         VARCHAR(20) NULL,
  status        TINYINT     NOT NULL DEFAULT 1      COMMENT '1启用 0停用',
  last_login_at DATETIME    NULL,
  created_at    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_username (username),
  KEY idx_class (class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='系统用户/班级成员';

CREATE TABLE IF NOT EXISTS fee_category (
  id       BIGINT       NOT NULL AUTO_INCREMENT,
  class_id BIGINT       NOT NULL,
  name     VARCHAR(30)  NOT NULL                COMMENT '如 班费收取/活动物资',
  kind     ENUM('INCOME','EXPENSE') NOT NULL,
  icon     VARCHAR(50)  NULL                    COMMENT 'Element Plus 图标名',
  sort     INT          NOT NULL DEFAULT 0,
  status   TINYINT      NOT NULL DEFAULT 1,
  PRIMARY KEY (id),
  KEY idx_class_kind (class_id, kind)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='收支类别字典';

-- 核心流水表：记错优先作废（红冲留痕），管理员可物理删除（同事务回滚余额并联动批次缴费）
CREATE TABLE IF NOT EXISTS fee_record (
  id            BIGINT        NOT NULL AUTO_INCREMENT,
  class_id      BIGINT        NOT NULL,
  type          ENUM('INCOME','EXPENSE') NOT NULL,
  category_id   BIGINT        NOT NULL,
  amount        DECIMAL(10,2) NOT NULL              COMMENT '恒为正数，方向由 type 决定',
  title         VARCHAR(60)   NOT NULL              COMMENT '摘要',
  occurred_at   DATETIME      NOT NULL              COMMENT '业务发生时间',
  channel       ENUM('CASH','WECHAT','ALIPAY','BANK','OTHER') NOT NULL DEFAULT 'CASH',
  payer_user_id BIGINT        NULL                  COMMENT '收入：缴费人',
  batch_id      BIGINT        NULL                  COMMENT '来自收费批次',
  remark        VARCHAR(255)  NULL,
  receipt_url   VARCHAR(255)  NULL                  COMMENT '票据图片路径',
  status        ENUM('NORMAL','VOID') NOT NULL DEFAULT 'NORMAL' COMMENT '作废=红冲',
  created_by    BIGINT        NOT NULL,
  created_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  -- 第十九轮审计：作废是「留痕」操作，必须能回答「谁在什么时候把这笔账作废了」
  voided_by     BIGINT        NULL                  COMMENT '作废人',
  voided_at     DATETIME      NULL                  COMMENT '作废时间',
  PRIMARY KEY (id),
  KEY idx_class_time (class_id, occurred_at),
  KEY idx_type (class_id, type, status),
  KEY idx_payer (payer_user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班费收支流水';

CREATE TABLE IF NOT EXISTS fee_batch (
  id         BIGINT        NOT NULL AUTO_INCREMENT,
  class_id   BIGINT        NOT NULL,
  name       VARCHAR(60)   NOT NULL                COMMENT '如 2026秋季班费',
  amount     DECIMAL(10,2) NOT NULL                COMMENT '每人应收',
  deadline   DATE          NULL,
  remark     VARCHAR(255)  NULL,
  status     ENUM('OPEN','CLOSED') NOT NULL DEFAULT 'OPEN',
  created_by BIGINT        NOT NULL,
  created_at DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  -- 第十九轮审计：关闭后不能再收款，是实质动作，记录操作人与时间
  closed_by  BIGINT        NULL                    COMMENT '关闭人',
  closed_at  DATETIME      NULL                    COMMENT '关闭时间',
  PRIMARY KEY (id),
  KEY idx_class (class_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='收费批次';

CREATE TABLE IF NOT EXISTS fee_payment (
  id        BIGINT        NOT NULL AUTO_INCREMENT,
  batch_id  BIGINT        NOT NULL,
  user_id   BIGINT        NOT NULL,
  amount    DECIMAL(10,2) NOT NULL DEFAULT 0.00  COMMENT '实收',
  status    ENUM('UNPAID','PAID','REFUNDED') NOT NULL DEFAULT 'UNPAID',
  channel   ENUM('CASH','WECHAT','ALIPAY','BANK','OTHER') NULL,
  paid_at   DATETIME      NULL,
  record_id BIGINT        NULL                   COMMENT '关联 fee_record.id',
  remark    VARCHAR(255)  NULL,
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_batch_user (batch_id, user_id),
  KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='成员缴费状态';

-- 第二十四轮：班级公告已整体移除（页面 / 路由 / 接口 / 本表一并删除）。
-- 已建好的库不会因为改了 DDL 文本而自动删表，`sys_notice` 会留在那里但**没有任何代码再用它**；
-- 确认不再需要历史公告后可手工 `DROP TABLE sys_notice;`。

-- ============ 第二十三轮：学生信息登记（动态字段 + 申请授权） ============
-- 字段定义与字段值**全部落库**：班主任/班长可以随时加字段，不需要改代码、不需要改表。
-- 之所以拆成「定义 / 记录 / 值」三张表：字段是**数据**（可增删改），值是**数据**，
-- 两者都不是代码里的常量。

-- 1) 字段定义：一列 = 一行
CREATE TABLE IF NOT EXISTS student_field (
  id          BIGINT       NOT NULL AUTO_INCREMENT,
  class_id    BIGINT       NOT NULL,
  field_key   VARCHAR(64)  NOT NULL                COMMENT '机器名，同班内唯一',
  field_label VARCHAR(64)  NOT NULL                COMMENT '表头显示名，可改名不影响数据',
  field_type  ENUM('TEXT','NUMBER','DATE','BOOL') NOT NULL DEFAULT 'TEXT',
  is_system   TINYINT      NOT NULL DEFAULT 0      COMMENT '1=随模板下发，不可删除',
  sort        INT          NOT NULL DEFAULT 0,
  status      TINYINT      NOT NULL DEFAULT 1      COMMENT '1启用 0停用（停用=软删，历史值保留）',
  created_by  BIGINT       NOT NULL,
  created_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_field_key (class_id, field_key),
  KEY idx_class (class_id, status, sort)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息字段定义（可动态扩展）';

-- 2) 学生记录：一行一人，**学号是锚点**
--    学号/姓名不放在字段值表里：它们要承担「这是谁的行」的定位职责，
--    放进 EAV 会让「我那一行是哪一行」变成一次联表比对。
CREATE TABLE IF NOT EXISTS student_record (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  class_id   BIGINT       NOT NULL,
  student_no VARCHAR(32)  NOT NULL                COMMENT '锚点，Excel 导入的 upsert 键',
  name       VARCHAR(32)  NOT NULL,
  user_id    BIGINT       NULL                    COMMENT '可关联登录账号，导入时按学号自动挂接',
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_student_no (class_id, student_no),
  KEY idx_class (class_id),
  KEY idx_user (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息记录（学号锚点）';

-- 3) 字段值：EAV。值统一按文本存，读写时按 field_type 解析/格式化。
--    选 EAV 而不是 JSON 列：字段集合会变（加字段是常态），JSON 改一次结构就要迁移全表；
--    且 EAV 能对单字段建索引，将来「按身份证号去重」这类需求不必回表全扫。
CREATE TABLE IF NOT EXISTS student_record_value (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  record_id  BIGINT       NOT NULL,
  field_id   BIGINT       NOT NULL,
  value_text VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uk_cell (record_id, field_id),
  KEY idx_field (field_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息字段值（EAV）';

-- 4) 访问申请：班长/同学默认只看得到自己那一行，要看全部/要改必须申请，班主任审批
CREATE TABLE IF NOT EXISTS student_access_request (
  id         BIGINT       NOT NULL AUTO_INCREMENT,
  class_id   BIGINT       NOT NULL,
  user_id    BIGINT       NOT NULL,
  scope      ENUM('EDIT_OWN','VIEW_ALL','EDIT_ALL') NOT NULL
                                      COMMENT 'EDIT_OWN=改自己那行 VIEW_ALL=看全部 EDIT_ALL=改全部',
  reason     VARCHAR(255) NULL,
  status     ENUM('PENDING','APPROVED','REJECTED') NOT NULL DEFAULT 'PENDING',
  created_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  handled_by BIGINT       NULL,
  handled_at DATETIME     NULL,
  reply      VARCHAR(255) NULL,
  PRIMARY KEY (id),
  KEY idx_inbox (class_id, status, created_at),
  KEY idx_user (user_id, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息访问申请与审批';

-- 5) 已授权：审批通过的结果落在这里（与「申请」分开：申请是流水，授权是当前状态）
CREATE TABLE IF NOT EXISTS student_grant (
  id         BIGINT   NOT NULL AUTO_INCREMENT,
  class_id   BIGINT   NOT NULL,
  user_id    BIGINT   NOT NULL,
  scope      ENUM('EDIT_OWN','VIEW_ALL','EDIT_ALL') NOT NULL,
  granted_by BIGINT   NOT NULL,
  granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_grant (class_id, user_id, scope)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='学生信息访问授权（审批通过后的当前状态）';

-- ============ 第二十五轮：班级任务（发出去 + 回收答案） ============
-- 和第二十四轮删掉的班级公告的**唯一区别**就在第二张表：公告是只读的，
-- 任务是发出去之后还要有人回来填。题型四种（BOOLEAN/SINGLE/MULTI/DATE），
-- 一个任务一个问题，细则见 app/models.py 的 ClsTask 注释。

-- 1) 任务：发布人拟题，可设截止时间和是否允许补充文字说明
CREATE TABLE IF NOT EXISTS cls_task (
  id            BIGINT       NOT NULL AUTO_INCREMENT,
  class_id      BIGINT       NOT NULL,
  title         VARCHAR(60)  NOT NULL COMMENT '任务标题，如「返校统计」',
  question      VARCHAR(255) NOT NULL COMMENT '题目正文，如「你已经返校了吗？」',
  qtype         ENUM('BOOLEAN','SINGLE','MULTI','DATE') NOT NULL DEFAULT 'BOOLEAN',
  options_json  TEXT         NULL COMMENT 'SINGLE/MULTI 的候选项，JSON 数组；其余类型为空',
  allow_text    TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '是否允许答完再补一段文字说明',
  deadline      DATETIME     NULL COMMENT '截止时间，NULL=不限；过了就不再收答案',
  status        TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=开放 0=已关闭（发布人手动关）',
    pinned        TINYINT(1)   NOT NULL DEFAULT 0 COMMENT '置顶：会出现在所有人仪表盘的「置顶任务」里',
  created_by    BIGINT       NOT NULL,
  created_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_task_class (class_id, status, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级任务（第二十五轮）：向班级成员收集一个问题的回答';

-- 2) 回答：一账号一任务一条（uk 保证重复提交是"改"而不是"多一行"）
--    value_json 按题型存：BOOLEAN 存 "true"/"false"，SINGLE 存选项**原文**，
--    MULTI 存 JSON 数组，DATE 存 YYYY-MM-DD。
--    存原文不存下标：发布人可能事后加一个"其他"选项，按下标回读会把老答案指到别的项上。
--
--    ⚠ 本库**不建外键**（沿用 Java 版做法：只建索引，由 service 负责级联删除），
--      所以这里没有 ON DELETE CASCADE。删任务必须由 `task_service.delete_task`
--      显式先删回答，否则会攒下一批没人会发现、也没法清理的孤儿数据。
CREATE TABLE IF NOT EXISTS cls_task_answer (
  id           BIGINT       NOT NULL AUTO_INCREMENT,
  task_id      BIGINT       NOT NULL,
  user_id      BIGINT       NOT NULL,
  value_json   TEXT         NULL,
  note         VARCHAR(255) NULL COMMENT '补充说明（allow_text=1 时可填）',
  submitted_at DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  UNIQUE KEY uk_task_user (task_id, user_id),
  KEY idx_answer_task (task_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级任务回答';
