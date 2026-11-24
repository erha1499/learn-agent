---
name: lock-wait
description: 锁等待和死锁怎么查：行锁等待指标、Lock wait timeout、慢日志里的 Lock_time
---
# 锁等待

## 症状
写接口超时、偶发失败；同一行数据被频繁更新（扣余额、扣库存）时最常见。

## 必查
1. get_metrics：row_lock_waits_per_min 是否明显高于平时。
2. query_error_log：有没有 "Lock wait timeout exceeded" 或 "Deadlock found"。
3. query_slow_log：慢 SQL 的 Lock_time 是否接近 Query_time，Rows_examined 很小（只改一行却等很久）。

## 容易混淆
- 慢 SQL：慢日志里 Lock_time 低、Rows_examined 大，是扫描慢，不是等锁。
- 网络问题：错误日志里的 Aborted connection 是噪音，不要被刷屏的告警带偏。

## 止血
找到长事务（持锁不放的会话）并结束它；热点行拆分、减少事务里的无关操作。

## 结论
根因 LOCK_WAIT。证据至少包括行锁等待指标，以及错误日志或慢日志里的锁等待记录。
