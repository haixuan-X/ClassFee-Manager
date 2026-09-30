package com.classfee;

import org.mybatis.spring.annotation.MapperScan;
import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * 班费收支系统后端入口
 *
 * @author classfee
 */
@SpringBootApplication
@MapperScan("com.classfee.mapper")
public class ClassfeeApplication {

    public static void main(String[] args) {
        SpringApplication.run(ClassfeeApplication.class, args);
    }
}
