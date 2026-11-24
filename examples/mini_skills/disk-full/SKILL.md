---
name: disk-full
description: 磁盘写满怎么查：写入失败但读正常，错误日志里的 errno 28
---
# 磁盘写满

## 症状
写入全部失败，读还正常；监控里连接数、CPU 往往都不高，容易被误判成锁或网络问题。

## 必查
1. query_error_log：找 "No space left on device"、"errno 28"、"Write to file ... failed"。这是唯一能定案的证据，监控指标里看不出来。
2. get_metrics：确认不是连接数或锁的问题（这些指标正常，反而支持磁盘问题）。
3. query_slow_log：写入语句可能因为写盘失败而变慢，不要因此判成慢 SQL 或锁等待。

## 容易混淆
- 锁等待：写入慢，但错误日志里是 Lock wait timeout，不是 errno 28。
- 慢 SQL：慢日志里的 INSERT 很慢，是写盘失败的结果，不是原因。

## 止血
清理 binlog 和临时文件、扩容磁盘；恢复后检查有没有写了一半的数据。

## 结论
根因 DISK_FULL。证据必须包括错误日志里的 No space left on device。
