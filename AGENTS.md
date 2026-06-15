# 运行环境
1. 默认使用venv虚拟环境，没有则询问是否创建
2. 命令用python3而不是python

# 文件结构
1. 数据抓取的核心脚本放在academic/src
2. log内存放的是数据抓取的过程日志，用于记录数据抓取进度
3. 所有的test或开发过程中的临时测试文件放在temp下

# 数据存储
1. 抓取数据存储在本机的clickhouse数据库内

# 开发规范
开发工作遵循team-collab这个skill，没有则询问