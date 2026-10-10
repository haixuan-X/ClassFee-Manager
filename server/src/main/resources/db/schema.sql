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
  role          ENUM('ADMIN','MEMBER','TEACHER') NOT NULL DEFAULT 'MEMBER',
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

CREATE TABLE IF NOT EXISTS sys_notice (
  id           BIGINT      NOT NULL AUTO_INCREMENT,
  class_id     BIGINT      NOT NULL,
  title        VARCHAR(80) NOT NULL,
  content      TEXT        NOT NULL,
  pinned       TINYINT     NOT NULL DEFAULT 0,
  status       TINYINT     NOT NULL DEFAULT 1      COMMENT '1发布 0下架',
  published_at DATETIME    NULL,
  created_by   BIGINT      NOT NULL,
  created_at   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (id),
  KEY idx_class (class_id, pinned, published_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='班级公告';
