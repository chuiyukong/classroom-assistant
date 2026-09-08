# 维护、数据库与跨账号交接


## 1.4.0 当前规则（覆盖下方历史时限说明）

schema 5：保留迁移 1—4，新增 classes.year/semester，唯一约束为 name/year/semester。迁移通过新表复制全部班级、保留 id 后替换原表；迁移专用连接外键关闭，正常业务连接始终开启，测试以 foreign_key_check 核对关联。旧班 year=0、semester='' 表示未设置，不推断学期，不改名；暂无旧班补录界面。新建 API POST /teacher/classes 接受 year 整数 2000—2100、semester 上学期/下学期，旧客户端同时省略时兼容。

签到截止不再关闭课堂：删除 expire_due/_expire 自动写关闭时间。checkin 在事务中比较服务端当前时间与 attendance_deadline，恰好截止也计 late（秒数可为 0），其后记实际迟到秒数。关闭行为只由 close/end/切换课堂/回收班级等教师操作触发；到期未到保持 pending，关闭时才转 absent。已发布旧课堂的 attendance_closed_at 不自动清除，历史签到状态不重算。旧无 deadline 的课堂沿用已保存 late_after 作为兼容阈值；新 open 都有 deadline，页面不显示宽限输入。v1 late_after 参数暂留兼容，不影响新签到。

前端依据服务器时间偏移显示倒计时/已超时，不能凭浏览器计时决定服务端资格。轮询不重建学生输入控件。点名候选仍通过 attendance.candidates，未签到视觉状态不改变抽样规则。班级年份学期仅在选座与数据管理显示；日志用稳定 class_id 隔离。

维护者每次发布同步 docs/全部功能与流程.md、docs/功能测试指南.md、docs/images/function-flow.svg 和 README 全功能表；未实现功能保留在路线图。测试用合成数据；新模块浏览器测试真实等待一分钟。数据库升级自动备份，回退先恢复备份，不能直接用旧 EXE 打开 schema 5。


## 1.3.0 维护更新

当前 schema 4，自动升级备份。新增签到截止时间、课堂布局快照和长期换座申请。旧版开放签到不追设截止时间，新发起时默认 10 分钟。课堂结束前完成审批和纠错，历史只读。

1.2.0 原装模板升级的 JSON hash 检查有换行误判，1.3.0 已改为解析内容比较；xlsx 仍使用原文件核验。确认只运行新版 EXE，启动后原装 v1 当前座位自动用 v2，不要求删库。真正自定义配置不覆盖。不得通过读取真实学生表来验证模板问题；只检查配置内容/文件识别，并用临时安装重现。

scripts/check_package.py 会在临时目录预置 Windows CRLF 原装 v1 配置，再验证 EXE 自动升级到 v2 与原模板导出。新增测试 tests/test_v130.py；学生输入保留、审批、无签到控件的点名页面和高亮在 check_modules_browser.py 验证。

本节是当前维护规则，下面历史版本策略仅用于理解迁移背景。

## 1.2.0 维护更新

- 当前 schema 3，升级前自动 SQLite backup。旧 schema 2 跳过备份例外不适用于这次升级。
- 新增 lessons（课堂与名单来源）、attendance_entries（状态/临时座位/签到）、attendance_leave（长期请假）、rollcall_draws（点名结果）；classes.deleted_at 为回收站标记。名单快照里的 student_id 保留原记录身份，历史只读。
- 使用 docs/1.2.0使用指南.md；新模块浏览器验证命令为 `.venv\Scripts\python.exe scripts\check_modules_browser.py`，与原 check_browser.py 一起执行。
- 原装配置自动升级到新版 16 小组模板；原三份配置备份在 config/templates/classroom-64-v1，用户自行修改的配置不覆盖。此情况需要维护者检查三份配置、备份并选择匹配布局版本后升级；不要只覆盖 xlsx 留下旧映射。
- 仅当前安排切换 v2，旧存档继续使用旧模板；同一机房的 v1/v2 设备设置统一读取当前 v2。模板升级与数据库升级是两个独立步骤，失败时保留目录用于排查，不删除用户资料。
- 回收站不是永久删除；恢复保留身份与历史，不自动重开登记/课堂。同名班级含回收站都保持唯一，可使用学期前缀。
- AI 模块尚未实现，密钥不应写入 settings.json 或仓库，后续按独立方案实现本机安全存储。

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
