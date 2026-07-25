# SRunPy 校园网登录器

适用于深澜（SRun）网关的第三方 Windows 客户端，同时保留可在 Windows/Linux 使用的命令行工具。

> 本项目不是学校或深澜官方客户端。使用前请确认符合所在学校的网络管理规定。

## 功能

- 登录、注销和在线状态查询
- 记住账号，并使用 Windows DPAPI 保护密码
- 掉线自动重连，支持可配置检查间隔和有界退避
- 多 IPv4 地址选择与源地址绑定
- Windows 开机自启动和系统托盘
- 网关与自服务地址配置
- 默认使用经过证书验证的 HTTPS
- 明确提示超时、TLS、网关协议和认证错误
- Windows 浅色/深色主题和高 DPI 响应式界面
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

旧版本的 `%APPDATA%\SRunPy\config.json` 会在首次运行时迁移。旧 AES 密码成功解密后，将改用当前 Windows 用户的 DPAPI 保护；单独复制配置文件到其他用户或电脑不能直接解密密码。

## 从 Python 安装

开发和 Python 安装方式统一使用 Python 3.12 x64：

```powershell
py -3.12 -m pip install .
srunpy
```

也可以使用 uv 工具模式：

```powershell
uv tool install . --python 3.12
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

操作完全成功时退出码为 `0`；查询不可达或登录/注销失败时退出码为非零值。

## 连接安全

默认连接策略是“验证证书的 HTTPS，失败即停止”，不会再因任意网络异常静默使用 `verify=False` 或明文 HTTP。

如果学校网关确实使用自签名证书或仅支持 HTTP，可在客户端设置中显式开启兼容选项：

- **允许未经验证的 HTTPS 证书**：存在中间人攻击风险；
- **允许明文 HTTP 兼容模式**：认证数据可能被监听或篡改，风险更高。

这些选项默认关闭，并且只应在确认学校网关要求时使用。网关请求默认不继承环境代理和 `.netrc`，避免校园认证流量被意外发送到代理。

## 开发

创建开发环境：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev,build]"
```

运行质量检查：

```powershell
.\.venv\Scripts\python -m pytest
.\.venv\Scripts\python -m ruff check srunpy tests
.\.venv\Scripts\python -m build
node --check srunpy\html\script.js
```

测试覆盖协议固定向量、JSON/JSONP 解析、TLS 失败策略、请求超时、配置迁移、原子写入、CLI 退出码、自动重连和前端资源完整性。

## 构建 Windows 发布包

构建要求：

- Python 3.12 x64；
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

项目不使用 UPX，也不优先提供 one-file 自解压版本，以减少启动延迟和杀毒软件启发式误报。

## 发布验收

发布前至少验证：

- Windows 10/11 普通用户安装、升级、卸载；
- WebView2 存在与缺失场景；
- 单实例、托盘恢复和开机启动；
- 正确密码、错误密码、登录、注销和网关不可达；
- 睡眠恢复、断网重连、DHCP 或多网卡切换；
- 125%、150% 和 200% DPI；
- 浅色/深色模式；
- 安装版和便携版的 SHA-256 校验；
- Defender/SmartScreen 扫描。

## 已测试院校

- 北京航空航天大学沙河校区

其他学校可能使用不同的深澜版本、证书或网关参数，请通过 Issue 提供脱敏后的错误代码和诊断信息。

## 致谢与许可

- 深澜协议实现基于 [iskoldt-X/SRUN-authenticator](https://github.com/iskoldt-X/SRUN-authenticator) 修改；
- 桌面容器使用 [pywebview](https://github.com/r0x0r/pywebview)；
- 界面字体为 MiSans Medium。

项目使用 [GPL-3.0](LICENSE) 许可证。
