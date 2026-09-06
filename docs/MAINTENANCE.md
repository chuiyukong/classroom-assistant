# 维护、数据库与跨账号交接

## 数据在哪里

默认目录 `%LOCALAPPDATA%\ClassroomAssistant`，启动窗口“打开数据目录”可直接查看。`classroom.sqlite3` 确实是主数据库；`--data-dir` 或 `CLASSROOM_DATA_DIR` 会改变位置。程序目录内的 resources 是初始模板，日常配置在数据目录的 config 下。

| 表 / 文件 | 内容 |
|---|---|
| classes | 班级编号与名称 |
| layouts | 不可变布局定义 |
| rounds | 当前登记与存档，archived_at 非空表示存档 |
| registrations | 座位姓名、学生关联、来源 IP、备注快照 |
| submissions | 幂等提交收据，防止重试覆盖或复活旧记录 |
| students | 班级内学生稳定编号、规范化姓名、私密备注 |
| seat_configs | 布局/座位维度的设备停用与私密设备备注 |
| classroom_state | 全局当前上课班级，服务重启仍保留 |
| settings.json | 端口、按 IP 限制设置 |
| session.key | 本机管理会话密钥，不公开分享 |
| application.log | 异常日志（轮转）；故障反馈前检查是否含本地信息 |

## 轻量查看程序

推荐 **DB Browser for SQLite**，开源图形界面，Windows 提供安装包及 PortableApp。从[官方页面](https://sqlitebrowser.org/dl/)获取。在“打开数据库”选择 classroom.sqlite3，然后在“浏览数据”切换表，不需要编写 SQL。

优先关闭课堂助手后，以只读方式打开或查看副本。程序运行时可能同时有 `classroom.sqlite3-wal`、`classroom.sqlite3-shm`，最新数据可能仍在 WAL；不要运行时仅复制主文件，也不要删这两个文件。正式运行备份使用 SQLite backup API，或关闭程序后复制整个数据目录。[SQLite WAL](https://www.sqlite.org/wal.html)、[SQLite Backup API](https://www.sqlite.org/backup.html)

查看可以用外部程序，日常修改应使用教师管理端，以维护登记唯一性、身份关联、存档快照及提交收据。直接改数据库会绕过业务规则。

只读 SQL 示例：

```sql
PRAGMA user_version;
SELECT c.name AS class_name, r.number AS sequence, r.is_open, r.archived_at,
       g.seat_no, g.name AS student_name
FROM rounds r JOIN classes c ON c.id=r.class_id
LEFT JOIN registrations g ON g.round_id=r.id
ORDER BY c.name, r.number DESC, g.seat_no;
SELECT * FROM seat_configs ORDER BY layout_id, seat_no;
```

## 本次升级与数据策略

用户明确旧库仅为测试数据、不需要备份。1.1.0 调用迁移时只对目标 schema 2 跳过自动备份；不会主动删除旧库。后续目标版本不为 2 时恢复升级前 backup API 备份。不要移除通用备份机制。

迁移保留已有登记，不伪造旧来源 IP。仅为各班当前安排中的旧记录生成独立学生身份；既有同名不会自动合并；更早存档保留原姓名但可能没有 student_id。新登记只在姓名唯一时复用学生记录，重名由教师明确选择。

## IP 限制的边界

- 默认 `limit_one_registration_per_ip: true`，按 socket 来源 IP 校验，不信任 X-Forwarded-For、客户端填写的 IP 或浏览器指纹。
- IP 唯一约束范围是登记 id。同班发起新登记、另一个班发起登记后，同机可立即提交；没有十分钟有效期。
- 清除登记释放该条 IP 占用；旧请求收据仍保留，不会因为网络重试复活错误记录。
- 直接局域网通常每台学生机有独立 IP。DHCP 更换地址、换网卡、代理/NAT 都影响此假设；需要更强限制时采用受控机号/设备令牌及教师核验，不能宣称 IP 等于身份。
- 如确实经共享出口，关闭程序，在 settings.json 添加/修改 `"limit_one_registration_per_ip": false`，重启。浏览器会话限制、座位唯一、同名拦截仍生效；关闭后换浏览器可能重复使用不同姓名。恢复 true 后按已有 source_ip 再次拦截新提交。

## 开发与发布

仓库为 `chuiyukong/classroom-assistant`，必须保持私有。上传前用 `git status` / `git diff --cached` 确认不包含数据库、会话密钥、真实学生数据与本地日志。公开图片服务和 GitHub Pages 不用于本项目。

版本标签对应已验证的源码提交；Release 附便携包和源码包，说明文件保存在 docs/releases。不要为无法还原的旧版本制造标签或伪造历史提交日期。

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe scripts\check_browser.py
powershell -ExecutionPolicy Bypass -File scripts\build.ps1
.\.venv\Scripts\python.exe scripts\check_package.py
```

测试用临时数据，不连接默认用户库。浏览器并发脚本仅在测试 WSGI 包装中模拟独立 IP，生产代码不包含或信任该测试头；防伪造转发 IP 另由 API 测试覆盖。

修改版本在 classroom/version.py，构建按版本输出便携包和源码包，避免覆盖正在运行的旧 EXE。发布前同步更新 CHANGELOG、PROJECT_STATUS、验收记录；增加表时追加迁移，不能修改已发布迁移。若未来 schema 升级后回退程序，应恢复升级前备份，不能直接让旧程序打开新版数据库。

## 新 AI / 新账号接手

将整个源代码压缩包解压，打开项目根目录，先读 AGENTS.md。它明确入口文档、用户决定和测试方式。无需导入原聊天，也不需要当前账号的记忆目录。给接手者说明此次目标，未实现功能均在 ROADMAP，不得把路线图当作已授权开发任务。

## 现场验收记录应填写

教师机系统、学生 Chrome/Firefox 具体版本、网络拓扑（是否代理/共享出口）、同 IP 换浏览器、不同 IP 同名、停用设备、备注跨班级/存档、下节课新登记、极域全班打开、导出与程序重启。记录真实结果，不使用模拟测试替代实机确认。
