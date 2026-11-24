---
name: slow-sql
description: 慢 SQL 怎么查：慢日志看什么、怎么判断是全表扫描还是锁等待造成的慢
---
# 慢 SQL

## 症状
接口变慢、超时；CPU 高；监控里 slow_queries_per_min 明显升高。

## 必查
1. get_metrics：CPU 和每分钟慢查询数。
2. query_slow_log：看 Query_time、Lock_time、Rows_examined。
   - Query_time 高、Lock_time 低、Rows_examined 很大：全表扫描或索引失效，是真正的慢 SQL。
   - Query_time 高、Lock_time 几乎等于 Query_time：时间都花在等锁上，根因应记 LOCK_WAIT。
3. 看 SQL 本身：WHERE 里对列用了函数（如 DATE(created_at)）、隐式类型转换、LIKE '%x'，都会让索引失效。

## 容易混淆
- 锁等待：慢日志里 Lock_time 很高。
- 连接数打满：慢 SQL 占住连接后，连接数也会上去，但先有慢 SQL。

## 止血
找到 SQL 的来源接口限流或降级；必要时 kill 掉正在跑的大查询；再补索引或改写 SQL。

## 结论
根因 SLOW_SQL。证据至少包括慢日志里的具体 SQL 和 Rows_examined。
