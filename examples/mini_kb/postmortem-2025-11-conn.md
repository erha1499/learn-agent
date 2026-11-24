# 复盘：2025-11-12 order-mysql-01 连接数打满
大促前把 order-service 扩容到 36 个实例，每个实例连接池上限 30，总共可能占用 1080 个连接，超过了 max_connections 1000，下单接口大量报 Too many connections。处置：临时把 max_connections 调到 1500。后续改进：制定《应用连接池规范》，扩容前先核对数据库容量。
