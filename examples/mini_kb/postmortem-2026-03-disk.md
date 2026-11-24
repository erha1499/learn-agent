# 复盘：2026-03-08 user-mysql-04 binlog 撑满数据盘
现象：用户库写入全部失败，读请求正常。错误日志里大量 errno 28（No space left on device）。原因：binlog 保留 30 天，登录日志写入量翻倍后撑满了 1TB 数据盘。处置：PURGE BINARY LOGS 清理 7 天前的 binlog，数据盘扩容到 2TB。后续改进：binlog 保留改为 7 天，增加磁盘 80% 告警。
