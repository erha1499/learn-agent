---
name: max-connections
description: 连接数打满（Too many connections）怎么查、怎么和慢 SQL、客户端连接池耗尽区分
---
# 连接数打满

## 症状
应用报 Too many connections、拿连接超时；监控里 connections 接近或等于 max_connections。

## 必查
1. get_metrics：connections / max_connections 是否到了 95% 以上。
2. query_error_log：有没有成片的 "Too many connections"，以及大量 "Aborted connection"。
3. query_slow_log：慢查询多不多。连接数高、慢查询也多，往往是慢 SQL 占住了连接，根因应记 SLOW_SQL。

## 容易混淆
- 慢 SQL：连接是被慢查询拖住的。先看慢日志里的 Query_time，再看连接数。
- 客户端连接池耗尽：数据库这边连接数不高，是应用自己的池子不够用。
- 网络问题：Aborted connection 多不代表网络坏了，连接被拒绝时也会大量出现。

## 止血
临时调大 max_connections，或重启连接泄漏的应用实例。不要一次 kill 掉所有连接。

## 结论
根因 MAX_CONNECTIONS。证据至少包括连接数指标和错误日志里的 Too many connections。
