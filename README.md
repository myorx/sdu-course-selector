# 山东大学选课请求重试脚本

基于原有的 `CourseChoose.py` 整理。脚本使用当前登录会话，对配置的课程发送选课请求；一次请求间隔由全局限速器控制，每门课程在成功或达到最大尝试次数后停止。**仅适用于你本人有权限使用的选课账号和课程**，使用前请确认符合学校的相关规定。

仓库不包含真实 Cookie、账号密码或课程 ID。实际配置保存在本机的 `config.json`，该文件和运行日志已被 `.gitignore` 排除。

## 环境准备

- Python 3.10 或更新版本
- 可访问山东大学选课系统的网络与已登录的本人账号

```bash
python -m pip install -r requirements.txt
```

## 配置

1. 复制 `config.example.json` 为同目录下的 `config.json`。
2. 在浏览器中登录自己的选课系统，通过开发者工具的 **Network/网络** 面板查看目标课程的选课请求。仅在自己的电脑上检查请求信息；不要把带 Cookie 的请求复制到第三方转换网站。
3. 将请求中的 `kcid` 和 `jx0404id` 填入 `courses`。多门课程可添加多个对象。把选课请求的完整 URL 填入 `operation_url`，对应页面地址填入 `referer_url`。示例使用原脚本的限选课接口；公共选修课等类型的请求路径可能不同，应以浏览器中实际看到的请求为准。
4. 从浏览器开发者工具的 Cookie 存储中，填写当前会话需要的 Cookie 名称和值；如请求还依赖其他 Cookie，可继续加到 `cookies` 对象。可将浏览器请求中的 User-Agent 填入 `user_agent`。

Windows PowerShell 中可以这样复制示例配置：

```powershell
Copy-Item config.example.json config.json
```

编辑完成后，先运行只检查配置、不发送选课请求的命令：

```bash
python CourseChoose.py --check
```

检查通过后运行：

```bash
python CourseChoose.py
```

在 macOS/Linux 上，若 `python` 指向旧版 Python，请使用 `python3`。

## 运行行为

- 默认全局最小请求间隔为 4 秒；每次未成功后，每门课程再等待随机 4–6 秒。
- 默认每门课程最多尝试 100 次，可在 `config.json` 中调整 `max_attempts`。请避免长时间高频请求。
- 服务器返回认证失败时，该课程任务停止；Cookie 过期后需重新登录并更新本地配置。
- 终端与 `logfile.txt` 会记录尝试状态。**最终选课结果请以教务系统页面为准。**
- 按 `Ctrl+C` 可停止脚本。停止可能需要等待当前请求超时，默认超时为 10 秒。

## 安全提示

`config.json` 中的 Cookie 相当于临时登录凭据，不能发给他人或提交到 GitHub。不要将 `logfile.txt`、开发者工具导出的请求、截图中的 Cookie 一起上传。更换网络、退出登录或会话过期都可能使 Cookie 失效。

此脚本只针对原文件中的请求格式整理，并未在真实选课时段或学校服务器上做自动化测试。接口和响应格式若有变化，应先在浏览器中核对。

