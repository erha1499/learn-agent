# 慢 SQL 排查手册
先看慢日志的 Query_time、Lock_time、Rows_examined。Rows_examined 很大说明扫描多，检查 WHERE 条件是否对列用了函数、是否走了索引。Lock_time 接近 Query_time 说明在等锁，按锁等待处理。
