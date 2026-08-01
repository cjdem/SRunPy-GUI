# SRunPy 校园网登录器

适用于深澜（SRun）网关的第三方 Windows 客户端，同时保留可在 Windows/Linux 使用的命令行工具。

> 本项目不是学校或深澜官方客户端。使用前请确认符合所在学校的网络管理规定。

## 项目来源与修改说明

当前修改版由 [cjdem/SRunPy-GUI](https://github.com/cjdem/SRunPy-GUI) 维护，基于上游 [HofNature/SRunPy-GUI](https://github.com/HofNature/SRunPy-GUI) 持续开发，属于 GPL-3.0-only 许可下的二次开发/派生版本，并非与上游无关的独立实现。原项目及其他贡献者对既有代码的版权不因本修改版而改变。

2026-07-26 起，本修改版主要增加或重构了：

- Windows 活动网卡每秒上传、下载速度采样和 3 秒 EMA 平滑；
- 独立 SQLite 分钟聚合、7 天保留以及 1/5/12/24 小时和 7 天趋势；
- 深澜账户字段归一化，区分网关账户累计流量与本机实时流量；
- 桌面仪表盘、设置页面、暗绿色主题和本地 Canvas 趋势图；
- TLS/HTTP 显式兼容开关、配置校验和相应自动化测试。

修改版应在发布说明中继续标明修改事实、日期和所基于的上游版本或提交。

## 功能

- 登录、注销和在线状态查询
- 记住账号，并使用 Windows DPAPI 保护密码
- 掉线自动重连，支持可配置检查间隔和有界退避
- 多 IPv4 地址选择与源地址绑定
- Windows 开机自启动和系统托盘
- 网关与自服务地址配置
- 默认使用经过证书验证的 HTTPS
- 明确提示超时、TLS、网关协议和认证错误
- Windows 活动网卡实时上传/下载速度和 60 秒平滑趋势图
- SQLite 分钟聚合，以及 1 小时、5 小时、12 小时、24 小时和 7 天趋势
- 深澜账户累计流量、余额、在线账号和在线 IP 状态卡
- 暗绿色主题和高 DPI 响应式界面
- 命令行批量操作

## Windows 客户端

正式发布提供两种产物：

1. `SRunPy-<version>-win-x64-setup.exe`：每用户安装包，不需要管理员权限；
2. `SRunPy-<version>-win-x64-portable.zip`：解压即用的便携版。

客户端要求：

- Windows 10 或 Windows 11 x64；
- Microsoft Edge WebView2 Runtime（多数 Windows 10/11 已安装）；
- 校园网使用深澜网页认证协议。

安装版默认安装到：

```text
%LOCALAPPDATA%\Programs\SRunPy
```

用户配置保存到：

```text
%LOCALAPPDATA%\SRunPy\config.json
```

本机流量分钟历史单独保存到：

```text
%LOCALAPPDATA%\SRunPy\traffic.db
```

流量数据库不保存 URL、进程、SSID、MAC 或数据包内容。删除该数据库只会清除本机流量趋势，不会影响深澜账户数据。

旧版本的 `%APPDATA%\SRunPy\config.json` 会在首次运行时迁移。旧 AES 密码成功解密后，将改用当前 Windows 用户的 DPAPI 保护；单独复制配置文件到其他用户或电脑不能直接解密密码。

## 从 Python 安装

开发和 Python 安装支持 Python 3.12 至 3.14 x64。以下示例使用 Python 3.14：

```powershell
py -3.14 -m pip install .
srunpy
```

也可以使用 uv 工具模式：

```powershell
uv tool install . --python 3.14
srunpy
```

Windows 上 `srunpy` 启动桌面客户端；Linux 上启动命令行界面。也可以显式运行：

```powershell
srunpy-gui
srunpy-cli --info
```

## 命令行用法

查询状态：

```powershell
srunpy-cli --info
```

登录：

```powershell
srunpy-cli --login --username <用户名>
```

未传入密码时会使用安全的交互式密码输入。虽然仍保留 `--passwd` 兼容参数，但密码可能出现在 shell 历史、进程列表或运维采集工具中，不建议使用。

注销：

```powershell
srunpy-cli --logout
```

列出本机 IPv4 地址：

```powershell
srunpy-cli --list-ips
```

指定网关和多个本地 IP：

```powershell
srunpy-cli --info `
  --gateway gw.example.edu.cn `
  --local-ip 10.1.1.7 `
  --local-ip 10.1.1.8
```

如果网关使用自签名证书或仅支持明文 HTTP，可传入与客户端设置一致的兼容选项（默认关闭）：

```powershell
srunpy-cli --login --username <用户名> --allow-unverified-tls
srunpy-cli --login --username <用户名> --allow-insecure-http
```

操作完全成功时退出码为 `0`；查询不可达或登录/注销失败时退出码为非零值。
底层错误以 `[错误码] 消息` 形式输出（例如 `[request_timeout] 网关请求超时`），便于脚本按错误码区分故障类型。

## 连接安全

默认连接策略是“验证证书的 HTTPS，失败即停止”，不会再因任意网络异常静默使用 `verify=False` 或明文 HTTP。

如果学校网关确实使用自签名证书或仅支持 HTTP，可在客户端设置中显式开启兼容选项：

- **允许未经验证的 HTTPS 证书**：存在中间人攻击风险；
- **允许明文 HTTP 兼容模式**：认证数据可能被监听或篡改，风险更高。

这些选项默认关闭，并且只应在确认学校网关要求时使用。网关请求默认不继承环境代理和 `.netrc`，避免校园认证流量被意外发送到代理。

## 开发

创建开发环境：

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,build]"
```

运行质量检查：

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check srunpy tests
.\.venv\Scripts\python -m build
node --test "tests\js\*.test.js"
node --check srunpy\html\script.js
```

本地覆盖率检查（与 CI 门禁一致）：

```powershell
.\.venv\Scripts\python -m pytest --cov --cov-report=term-missing --cov-fail-under=65
```

测试覆盖协议固定向量与完整登录/注销流程、JSON/JSONP 解析、TLS 失败策略、请求超时、配置迁移、原子写入、CLI 退出码、自动重连、账户字段归一化、流量计数差分、分钟历史、前端资源完整性和 JavaScript 纯函数。

## 构建 Windows 发布包

构建要求：

- Python 3.12 至 3.14 x64；
- `pip install -e ".[dev,build]"`；
- Inno Setup 6（只构建便携版时可省略）；
- Visual Studio C++ Build Tools，或允许 Nuitka 下载 MinGW64。

运行：

```powershell
.\scripts\build_windows.ps1
```

只构建便携版：

```powershell
.\scripts\build_windows.ps1 -SkipInstaller
```

脚本执行测试和 Ruff，使用 Nuitka `standalone` 生成同一份目录产物，再创建：

- 便携 ZIP；
- Inno Setup 每用户安装包；
- `SHA256SUMS.txt` 校验清单。

发布目录会同时携带 GPL 许可证、第三方组件声明和源码获取说明。二进制发布必须对应一个可复现的源码提交或版本标签。

项目不使用 UPX，也不优先提供 one-file 自解压版本，以减少启动延迟和杀毒软件启发式误报。

## 发布验收

发布前至少验证：

- Windows 10/11 普通用户安装、升级、卸载；
- WebView2 存在与缺失场景；
- 单实例、托盘恢复和开机启动；
- 正确密码、错误密码、登录、注销和网关不可达；
- 睡眠恢复、断网重连、DHCP 或多网卡切换；
- 125%、150% 和 200% DPI；
- 暗绿色主题、设置弹窗和图表对比度；
- 60 秒、1/5/12/24 小时和 7 天趋势切换；
- 安装版和便携版的 SHA-256 校验；
- Defender/SmartScreen 扫描。

## 已测试院校

- 北京航空航天大学沙河校区

其他学校可能使用不同的深澜版本、证书或网关参数，请通过 Issue 提供脱敏后的错误代码和诊断信息。

## 致谢与许可

- 深澜协议实现基于 [iskoldt-X/SRUN-authenticator](https://github.com/iskoldt-X/SRUN-authenticator) 修改；
- 桌面容器使用 [pywebview](https://github.com/r0x0r/pywebview)；
- 界面字体为 MiSans Medium。

项目使用 [GNU GPL v3.0 only](LICENSE) 许可证。第三方依赖和资源仍适用各自的许可证，详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。

你可以运行、研究、修改、复制和收费分发本项目。若向他人分发源码、安装包或便携版，必须同时遵守 GPL-3.0-only，主要包括：

- 保留现有版权、许可和无担保声明；
- 显著说明你修改过项目并给出相关日期；
- 整个派生作品继续以 GPL-3.0-only 提供，不附加与 GPL 冲突的限制；
- 向接收者提供与该二进制版本对应的完整机器可读源码和构建脚本；
- 允许接收者继续运行、修改和再分发。

仅在私人环境中运行或修改而不向他人分发时，通常不要求公开修改。GPL 允许收费，但不允许在分发 GPL 派生版本时仅提供闭源二进制。源码交付说明见 [SOURCE_CODE.md](SOURCE_CODE.md)。

`参考ui/` 是本地设计参考目录，不属于本项目发布内容，并已通过 `.gitignore` 排除。不得未经许可将其中 Octopus 项目的 AGPL-3.0 代码、图标、Logo 或其他资源打包进本项目。

以上内容是项目维护和发布指引，不构成法律意见。商业闭源集成或大规模分发前，应由熟悉开源许可证的专业人士审查最终发布物。
