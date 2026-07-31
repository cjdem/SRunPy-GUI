"""
Windows GUI Interface Module / Windows GUI 界面模块

This module provides the Windows graphical interface for SRunPy.
本模块为 SRunPy 提供 Windows 图形界面。
"""

import base64
import ctypes
import os
import platform
import socket
import sys
import threading
import time
import uuid
import webbrowser
from binascii import a2b_hex, b2a_hex
from typing import Any, Dict, List, Optional, Tuple

import pystray
import requests
import webview
import win32api
import win32com.client as client
import win32con
import win32gui
from Crypto.Cipher import AES
from PIL import Image

try:
    from win10toast import ToastNotifier
except ImportError:
    class ToastNotifier:
        """Compatibility fallback when the legacy toast package is unavailable."""

        def show_toast(self, *_: object, **__: object) -> bool:
            return False

from srunpy import SrunClient, WebRoot, __version__
from srunpy.account_metrics import normalize_account_metrics
from srunpy.config import (
    ConfigStore,
    WindowsDPAPICredentialProtector,
    get_default_config_path,
    get_legacy_config_path,
)
from srunpy.ip_utils import get_local_ipv4_addresses
from srunpy.reconnect import ReconnectService
from srunpy.traffic import TrafficCounterProvider, TrafficMonitorService
from srunpy.traffic_store import TrafficHistoryStore, get_default_traffic_database_path
from srunpy.update import is_newer_release


def is_ip_address(address: str) -> bool:
    """
    Check if address is a valid IP address.
    检查地址是否为有效的 IP 地址。

    Args / 参数:
        address: Address string to check / 要检查的地址字符串

    Returns / 返回:
        True if valid IP address / 如果是有效 IP 地址返回 True
    """
    try:
        socket.inet_aton(address)
        return True
    except socket.error:
        return False


def is_domain(address: str) -> Tuple[bool, str]:
    """
    Check if address is a valid domain and resolve it.
    检查地址是否为有效域名并解析它。

    Args / 参数:
        address: Address string to check / 要检查的地址字符串

    Returns / 返回:
        Tuple of (is_valid, resolved_ip) / (是否有效, 解析的IP) 的元组
    """
    if not is_ip_address(address):
        try:
            ip = socket.gethostbyname(address)
            return True, ip
        except socket.error:
            return False, ""
    return False, ""


# Global instances / 全局实例
sysToaster = ToastNotifier()
application_path = os.path.abspath(sys.argv[0])
python_path = os.path.abspath(sys.executable)
start_lnk_path = os.path.join(
    os.path.expandvars(r'%APPDATA%'),
    r'Microsoft\Windows\Start Menu\Programs\Startup',
    '校园网登陆器.lnk'
)
config_path = str(get_default_config_path())


def get_Color_Mode() -> int:
    """
    Get Windows theme color mode (light/dark).
    获取 Windows 主题颜色模式（亮色/暗色）。

    Returns / 返回:
        0 for dark mode, 1 for light mode / 暗色模式返回 0，亮色模式返回 1
    """
    reg_root = win32con.HKEY_CURRENT_USER
    reg_path = r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize'
    reg_flags = win32con.KEY_READ | win32con.KEY_WOW64_64KEY
    key = win32api.RegOpenKey(reg_root, reg_path, 0, reg_flags)
    value, _ = win32api.RegQueryValueEx(key, "SystemUsesLightTheme")
    win32api.RegCloseKey(key)
    return value


def get_Update() -> bool:
    """
    Check if there is a newer version available on GitHub.
    检查 GitHub 上是否有可用的新版本。

    Returns / 返回:
        True if update available / 如果有更新可用返回 True
    """
    try:
        response = requests.get(
            "https://api.github.com/repos/cjdem/SRunPy-GUI/releases/latest",
            timeout=(3, 5),
        )
        if response.status_code == 200:
            data = response.json()
            tag_name = data['tag_name']
            if is_newer_release(tag_name, __version__):
                return True
        return False
    except Exception:
        return False


def load_config(aes_key: str) -> Dict[str, Any]:
    """
    Load configuration from file with AES decryption.
    使用 AES 解密从文件加载配置。

    Args / 参数:
        aes_key: AES encryption key / AES 加密密钥

    Returns / 返回:
        Configuration dictionary / 配置字典
    """
    legacy_cipher = MyAES(key=aes_key)
    store = ConfigStore(
        get_default_config_path(),
        WindowsDPAPICredentialProtector(),
        legacy_config_path=get_legacy_config_path(),
        legacy_password_decryptor=lambda ciphertext: legacy_cipher.decode_aes(
            ciphertext.encode("ascii")
        ),
    )
    return store.load()


def reset_config() -> None:
    """
    Reset configuration by removing config file.
    通过删除配置文件重置配置。
    """
    if os.path.exists(config_path):
        os.remove(config_path)


def save_config(config: Dict[str, Any], aes_key: str) -> None:
    """
    Save configuration to file with AES encryption.
    使用 AES 加密将配置保存到文件。

    Args / 参数:
        config: Configuration dictionary / 配置字典
        aes_key: AES encryption key / AES 加密密钥
    """
    legacy_cipher = MyAES(key=aes_key)
    store = ConfigStore(
        get_default_config_path(),
        WindowsDPAPICredentialProtector(),
        legacy_config_path=get_legacy_config_path(),
        legacy_password_decryptor=lambda ciphertext: legacy_cipher.decode_aes(
            ciphertext.encode("ascii")
        ),
    )
    store.save(config)


def check_lnk() -> bool:
    """
    Check if startup link exists.
    检查启动链接是否存在。

    Returns / 返回:
        True if exists / 如果存在返回 True
    """
    return os.path.exists(start_lnk_path)


def delete_lnk() -> None:
    """
    Delete startup link if it exists.
    如果存在则删除启动链接。
    """
    if check_lnk():
        os.remove(start_lnk_path)


def create_desktop_lnk(qt_backend: bool = False) -> None:
    """
    Create desktop shortcut.
    创建桌面快捷方式。

    Args / 参数:
        qt_backend: Whether using Qt backend / 是否使用 Qt 后端
    """
    no_cmd_path = os.path.join(
        os.path.dirname(application_path), 'srunpy-gui.exe'
    )
    if (python_path != application_path and os.path.exists(python_path) and
            os.path.basename(application_path).endswith(".exe") and
            os.path.exists(no_cmd_path)):
        desktop_lnk = os.path.join(
            os.path.expandvars(r'%USERPROFILE%'),
            'Desktop', '校园网登陆器.lnk'
        )
        if os.path.exists(desktop_lnk):
            os.remove(desktop_lnk)
        shell = client.Dispatch('Wscript.Shell')
        link = shell.CreateShortCut(desktop_lnk)
        link.TargetPath = no_cmd_path
        if qt_backend:
            link.Arguments += ' --qt'
        link.IconLocation = os.path.join(WebRoot, 'icons/logo.ico') + ',0'
        link.save()
    else:
        print("非EntryPoint启动，无法创建桌面快捷方式")


def create_lnk(qt_backend: bool = False) -> None:
    """
    Create startup link.
    创建启动链接。

    Args / 参数:
        qt_backend: Whether using Qt backend / 是否使用 Qt 后端
    """
    delete_lnk()
    startup_directory = os.path.dirname(start_lnk_path)
    os.makedirs(startup_directory, exist_ok=True)
    shell = client.Dispatch('Wscript.Shell')
    link = shell.CreateShortCut(start_lnk_path)
    no_cmd_path = os.path.join(
        os.path.dirname(application_path), 'srunpy-gui.exe'
    )
    if python_path == application_path or not os.path.exists(python_path):
        link.TargetPath = application_path
        link.Arguments = ' --no-auto-open'
        link.IconLocation = application_path + ',0'
    elif (os.path.exists(python_path) and
          os.path.basename(application_path).endswith(".exe") and
          os.path.exists(no_cmd_path)):
        link.TargetPath = no_cmd_path
        link.Arguments = ' --no-auto-open'
        link.IconLocation = os.path.join(WebRoot, 'icons/logo.ico') + ',0'
    else:
        link.TargetPath = python_path
        link.Arguments = '"' + application_path + '" --no-auto-open'
        link.IconLocation = os.path.join(WebRoot, 'icons/logo.ico') + ',0'
    if qt_backend:
        link.Arguments += ' --qt'
    link.save()



class MyAES:
    """
    AES encryption/decryption utility.
    AES 加密/解密工具。
    """

    def __init__(self, key: str) -> None:
        """
        Initialize AES cipher.
        初始化 AES 密码。

        Args / 参数:
            key: Encryption key (will be encoded to bytes) / 加密密钥（将编码为字节）
        """
        self.key = key.encode()

    def __add_to_16(self, text: str) -> bytes:
        """
        Pad text to 16-byte blocks.
        将文本填充到 16 字节块。

        Args / 参数:
            text: Text to pad / 要填充的文本

        Returns / 返回:
            Padded bytes / 填充后的字节
        """
        if len(text.encode()) % 16:
            add = 16 - (len(text.encode()) % 16)
        else:
            add = 0
        text += ("\0" * add)
        return text.encode()

    def encode_aes(self, text: str) -> bytes:
        """
        Encrypt text using AES.
        使用 AES 加密文本。

        Args / 参数:
            text: Text to encrypt / 要加密的文本

        Returns / 返回:
            Encrypted hex bytes / 加密的十六进制字节
        """
        cryptos = AES.new(key=self.key, mode=AES.MODE_ECB)
        cipher_text = cryptos.encrypt(self.__add_to_16(text))
        return b2a_hex(cipher_text)

    def decode_aes(self, text: bytes) -> str:
        """
        Decrypt text using AES.
        使用 AES 解密文本。

        Args / 参数:
            text: Encrypted hex bytes / 加密的十六进制字节

        Returns / 返回:
            Decrypted text / 解密的文本
        """
        cryptos = AES.new(key=self.key, mode=AES.MODE_ECB)
        plain_text = cryptos.decrypt(a2b_hex(text))
        return bytes.decode(plain_text).rstrip("\0")


class TaskbarIcon:
    """
    System tray icon for the application.
    应用程序的系统托盘图标。
    """

    def __init__(self) -> None:
        """Initialize taskbar icon / 初始化托盘图标"""
        self.should_exit = False
        self.menu = pystray.Menu(
            pystray.MenuItem("打开主界面", self.stop, default=True),
            pystray.MenuItem("退出登陆器", self.exit)
        )
        try:
            if get_Color_Mode() == 0:
                icon_path = r'icons\journey_white.png'
            else:
                icon_path = r'icons\journey.png'
        except Exception:
            icon_path = r'icons\logo.png'
        self.icon = pystray.Icon(
            "SRunPy",
            Image.open(os.path.join(WebRoot, icon_path)),
            "校园网登陆器",
            self.menu
        )
        self.icon.run()

    def stop(self, *_: object) -> None:
        """Stop the icon / 停止图标"""
        self.icon.stop()

    def exit(self, *_: object) -> None:
        """Exit the application / 退出应用程序"""
        self.should_exit = True
        self.icon.stop()


class GUIBackend:
    """
    Backend logic for the GUI application.
    GUI 应用程序的后端逻辑。
    """

    def __init__(self, use_qt: bool = False,
                 aes_key: str = "dj26Dh47useoUI28") -> None:
        """
        Initialize GUI backend.
        初始化 GUI 后端。

        Args / 参数:
            use_qt: Whether to use Qt backend for webview / 是否使用 Qt 后端
            aes_key: AES encryption key for config / 配置的 AES 加密密钥
        """
        if use_qt:
            try:
                import webview.platforms.qt  # noqa: F401
            except ImportError:
                print("无法导入Qt库，请使用pip install srumpy[qt]安装")
                print("Failed to import Qt library, please use pip install srumpy[qt] to install")
                use_qt = False

        self.aes_key = aes_key
        self.qt_backend = use_qt
        self.reconnect_service: Optional[ReconnectService] = None
        self.traffic_monitor: Optional[TrafficMonitorService] = None
        self.srun_clients: Dict[Optional[str], SrunClient] = {}
        self.active_ip: Optional[str] = None
        self.isUptoDate = False
        self.hasDoneUpdate = False

        def check_update():
            self.isUptoDate = get_Update()

        threading.Thread(
            target=check_update,
            name="SRunPy-UpdateCheck",
            daemon=True,
        ).start()
        self.refresh_config()

    def refresh_config(self) -> None:
        """
        Reload configuration from file.
        从文件重新加载配置。
        """
        try:
            self.config = load_config(self.aes_key)
            self.username = self.config['username']
            self.password = self.config['password']
            self.pass_correct = self.config['pass_correct']
            self.srun_host = self.config['srun_host']
            self.host_ip = self.config['host_ip']
            self.self_service = self.config['self_service']
            self.sleeptime = self.config['sleeptime']
            self.auto_login = self.config['auto_login']
            self.start_with_windows = self.config['start_with_windows']
            self.local_ips = self.config.get('local_ips', [])
            self.active_ip = self.config.get('active_ip')
            self.allow_unverified_tls = self.config.get('allow_unverified_tls', False)
            self.allow_insecure_http = self.config.get('allow_insecure_http', False)
            self.traffic_sampling_enabled = self.config.get('traffic_sampling_enabled', True)
            self.traffic_sample_interval = self.config.get('traffic_sample_interval', 1.0)
            self.traffic_history_enabled = self.config.get('traffic_history_enabled', True)
            self.traffic_retention_days = self.config.get('traffic_retention_days', 7)
        except Exception as error:
            raise RuntimeError(
                "无法读取应用配置；原配置已保留，请检查 Windows 凭据或配置文件权限"
            ) from error

        self._rebuild_clients()
        self._ensure_active_ip()
        self.srun = self.get_client()

        if self.start_with_windows:
            create_lnk(qt_backend=self.qt_backend)
        else:
            delete_lnk()

        self._sync_reconnect_service()
        self._sync_traffic_monitor()

    def shutdown(self) -> None:
        """Stop background work and close all pooled network connections."""
        if self.traffic_monitor is not None:
            self.traffic_monitor.stop()
        if self.reconnect_service is not None:
            self.reconnect_service.stop()
        for srun_client in self.srun_clients.values():
            try:
                srun_client.close()
            except Exception:
                pass

    def _sync_traffic_monitor(self) -> None:
        """Apply traffic preferences without coupling sampling to gateway polling."""
        desired_configuration = (
            float(self.traffic_sample_interval),
            bool(self.traffic_history_enabled),
            int(self.traffic_retention_days),
        )
        current_configuration = None
        if self.traffic_monitor is not None:
            current_configuration = (
                self.traffic_monitor.sample_interval,
                self.traffic_monitor.history_enabled,
                self.traffic_monitor.retention_days,
            )

        if self.traffic_monitor is not None and current_configuration != desired_configuration:
            self.traffic_monitor.stop()
            self.traffic_monitor = None

        if self.traffic_monitor is None:
            history_store = TrafficHistoryStore(get_default_traffic_database_path())
            self.traffic_monitor = TrafficMonitorService(
                TrafficCounterProvider(),
                history_store,
                preferred_ip=self.active_ip,
                gateway_ip=self.host_ip,
                sample_interval=self.traffic_sample_interval,
                history_enabled=self.traffic_history_enabled,
                retention_days=self.traffic_retention_days,
            )
        else:
            self.traffic_monitor.update_selection(self.active_ip, self.host_ip)

        if self.traffic_sampling_enabled:
            self.traffic_monitor.start()
        else:
            self.traffic_monitor.stop()

    def _sync_reconnect_service(self) -> None:
        """Start or stop automatic reconnection to match current configuration."""
        service_needs_rebuild = (
            self.reconnect_service is None
            or self.reconnect_service.check_interval != max(1.0, float(self.sleeptime))
        )
        if service_needs_rebuild:
            if self.reconnect_service is not None:
                self.reconnect_service.stop()
            self.reconnect_service = ReconnectService(
                clients_provider=lambda: dict(self.srun_clients),
                login_callback=self.login,
                check_interval=float(self.sleeptime),
                notification_callback=self._notify_reconnect_result,
            )

        if self.auto_login:
            self.reconnect_service.start()
        else:
            self.reconnect_service.stop()

    def _notify_reconnect_result(
        self,
        interface_ip: Optional[str],
        login_succeeded: bool,
        failure_count: int,
    ) -> None:
        """Show rate-limited reconnect feedback for one network interface."""
        interface_label = f"IP {interface_ip} " if interface_ip is not None else ""
        if login_succeeded:
            message = interface_label + "自动登录成功"
        elif failure_count in {1, 3}:
            message = interface_label + "自动登录失败，请检查账号或网络"
        else:
            return
        sysToaster.show_toast(
            "校园网登录器",
            message,
            duration=5,
            threaded=True,
        )

    def _create_client(self, client_ip: Optional[str]) -> SrunClient:
        """
        Create a SrunClient instance.
        创建 SrunClient 实例。

        Args / 参数:
            client_ip: IP to bind to / 要绑定的 IP

        Returns / 返回:
            SrunClient instance / SrunClient 实例
        """
        if self.srun_host == "":
            gateway_host = self.host_ip
        else:
            gateway_host = self.srun_host
        return SrunClient(
            gateway_host,
            self.host_ip,
            client_ip=client_ip,
            allow_unverified_tls=self.allow_unverified_tls,
            allow_insecure_http=self.allow_insecure_http,
        )

    def _rebuild_clients(self) -> None:
        """
        Rebuild all client instances based on configuration.
        根据配置重建所有客户端实例。
        """
        previous_clients = self.srun_clients
        self.srun_clients = {}
        for previous_client in previous_clients.values():
            try:
                previous_client.close()
            except Exception:
                pass
        ip_list: List[Optional[str]] = []
        seen = set()

        def append_ip(value: Optional[str]) -> None:
            if value not in seen:
                ip_list.append(value)
                seen.add(value)

        if self.local_ips:
            for ip in self.local_ips:
                append_ip(ip)
        if not ip_list:
            ip_list = [None]

        for ip in ip_list:
            try:
                self.srun_clients[ip] = self._create_client(ip)
            except Exception as exc:
                print(f"初始化IP {ip or '默认'} 失败: {exc}")

        if not self.srun_clients:
            self.srun_clients[None] = self._create_client(None)

    def _ensure_active_ip(self) -> None:
        """
        Ensure active_ip is valid and in srun_clients.
        确保 active_ip 有效且在 srun_clients 中。
        """
        if not self.srun_clients:
            self.active_ip = None
            return
        if self.active_ip not in self.srun_clients:
            self.active_ip = next(iter(self.srun_clients.keys()))
            self.config['active_ip'] = self.active_ip
            save_config(self.config, self.aes_key)

    def get_client(self, ip: Optional[str] = None) -> Optional[SrunClient]:
        """
        Get SrunClient for specified IP.
        获取指定 IP 的 SrunClient。

        Args / 参数:
            ip: IP address (None for default) / IP 地址（None 表示默认）

        Returns / 返回:
            SrunClient instance or None / SrunClient 实例或 None
        """
        if not self.srun_clients:
            return None
        if ip in self.srun_clients:
            return self.srun_clients[ip]
        if ip is None and None in self.srun_clients:
            return self.srun_clients[None]
        if self.active_ip in self.srun_clients:
            return self.srun_clients[self.active_ip]
        return next(iter(self.srun_clients.values()))

    def _parse_gateway(self, gateway: str) -> Tuple[str, str]:
        """
        Parse gateway address (IP or domain).
        解析网关地址（IP 或域名）。

        Args / 参数:
            gateway: Gateway address / 网关地址

        Returns / 返回:
            Tuple of (hostname, ip) / (主机名, IP) 的元组

        Raises / 抛出:
            ValueError: If gateway cannot be resolved / 如果无法解析网关
        """
        target = gateway.strip() if gateway else ""
        if not target:
            return self.srun_host, self.host_ip
        if is_ip_address(target):
            return "", target
        is_dom, resolved_ip = is_domain(target)
        if is_dom and resolved_ip:
            return target, resolved_ip
        raise ValueError("无法解析网关地址，请检查输入")

    def _update_gateway_only(self, srun_host: str, self_service: str) -> bool:
        """
        Update gateway configuration only.
        仅更新网关配置。

        Args / 参数:
            srun_host: Gateway host / 网关主机
            self_service: Self-service URL / 自助服务 URL

        Returns / 返回:
            True if successful / 成功返回 True
        """
        try:
            resolved_host, resolved_ip = self._parse_gateway(srun_host)
        except ValueError:
            return False
        self.config['srun_host'] = resolved_host
        self.config['host_ip'] = resolved_ip
        self.config['self_service'] = self_service
        return True

    def _update_local_ip_selection(
            self, selected_ips: Optional[List[Optional[str]]],
            active_ip: Optional[str]) -> None:
        """
        Update local IP selection in configuration.
        更新配置中的本地 IP 选择。

        Args / 参数:
            selected_ips: List of selected IPs / 选定的 IP 列表
            active_ip: Active IP / 活动 IP
        """
        if selected_ips is None:
            return

        normalized: List[Optional[str]] = []
        available = set(get_local_ipv4_addresses())
        for ip in selected_ips:
            if ip in (None, "", "null"):
                normalized.append(None)
            elif ip in available:
                normalized.append(ip)

        if normalized:
            # Remove duplicates while preserving order
            # 去除重复项同时保留顺序
            ordered: List[Optional[str]] = []
            for ip in normalized:
                if ip not in ordered:
                    ordered.append(ip)
            normalized = ordered
        else:
            normalized = []

        self.config['local_ips'] = normalized
        if normalized:
            if active_ip in normalized:
                self.config['active_ip'] = active_ip
            else:
                self.config['active_ip'] = normalized[0]
        else:
            self.config['active_ip'] = None

    def probe_gateway_ips(self, gateway: str,
                          self_service: Optional[str] = None) -> Dict[str, Any]:
        """
        Probe gateway connectivity for all local IPs.
        探测所有本地 IP 与网关的连接性。

        Args / 参数:
            gateway: Gateway address / 网关地址
            self_service: Self-service URL / 自助服务 URL

        Returns / 返回:
            Result dictionary with probe results / 包含探测结果的结果字典
        """
        try:
            resolved_host, resolved_ip = self._parse_gateway(gateway)
        except ValueError as exc:
            return {
                "ok": False,
                "error": str(exc),
                "results": [],
            }

        if not resolved_ip:
            return {
                "ok": False,
                "error": "无法解析网关地址，请检查输入",
                "results": [],
            }

        candidates = [None] + get_local_ipv4_addresses()
        results = []
        reachable_count = 0

        for ip in candidates:
            token = None if ip is None else ip
            try:
                client = SrunClient(
                    resolved_host if resolved_host != "" else resolved_ip,
                    resolved_ip,
                    client_ip=ip,
                    allow_unverified_tls=self.allow_unverified_tls,
                    allow_insecure_http=self.allow_insecure_http,
                )
                connectivity = client.is_connected()
                if isinstance(connectivity, tuple):
                    is_available = bool(connectivity[0])
                    detail_payload = connectivity[2] if len(connectivity) >= 3 else None
                else:
                    is_available = bool(connectivity)
                    detail_payload = None

                reachable = bool(is_available)
                if reachable:
                    message = "可访问"
                    reachable_count += 1
                else:
                    extra = None
                    if isinstance(detail_payload, dict):
                        extra = detail_payload.get('error') or detail_payload.get('error_msg')
                    elif isinstance(detail_payload, str):
                        extra = detail_payload
                    if extra:
                        extra = str(extra)
                    message = "不可访问" if not extra else f"不可访问：{extra}"
            except Exception as exc:
                reachable = False
                message = f"不可访问：{exc}"

            if isinstance(message, str) and len(message) > 120:
                message = message[:117] + "..."

            results.append({
                "ip": token,
                "label": "默认路由" if token is None else str(token),
                "reachable": reachable,
                "message": message,
            })

        return {
            "ok": True,
            "gateway": gateway,
            "resolved_host": resolved_host,
            "host_ip": resolved_ip,
            "self_service": self_service or self.self_service,
            "reachable_count": reachable_count,
            "results": results,
        }

    def set_config(self, username: str, password: str) -> None:
        """
        Update username and password configuration.
        更新用户名和密码配置。

        Args / 参数:
            username: New username / 新用户名
            password: New password / 新密码
        """
        if username != "" and username != self.config['username']:
            if self.srun_host == "gw.buaa.edu.cn":
                self.config['username'] = username.lower()
            else:
                self.config['username'] = username
            self.config['pass_correct'] = False
            self.config['auto_login'] = False
        if password != "" and password != self.config['password']:
            self.config['password'] = password
            self.config['pass_correct'] = False
            self.config['auto_login'] = False
        save_config(self.config, self.aes_key)
        self.refresh_config()

    def set_start_with_windows(self, start_with_windows: bool) -> None:
        """
        Set whether to start with Windows.
        设置是否随 Windows 启动。

        Args / 参数:
            start_with_windows: Enable/disable startup / 启用/禁用启动
        """
        self.config['start_with_windows'] = start_with_windows
        save_config(self.config, self.aes_key)
        self.refresh_config()

    def set_auto_login(self, auto_login: bool) -> bool:
        """
        Set auto-login configuration.
        设置自动登录配置。

        Args / 参数:
            auto_login: Enable/disable auto-login / 启用/禁用自动登录

        Returns / 返回:
            True if successful / 成功返回 True
        """
        if auto_login and not self.auto_login and not self.pass_correct:
            return False
        else:
            self.config['auto_login'] = auto_login
            save_config(self.config, self.aes_key)
            self.refresh_config()
            return True

    def set_active_client_ip(self, ip: Optional[str]) -> bool:
        """
        Set the active client IP.
        设置活动客户端 IP。

        Args / 参数:
            ip: IP address to set as active / 要设置为活动的 IP 地址

        Returns / 返回:
            True if successful / 成功返回 True
        """
        target = ip if ip not in (None, "", "null") else None
        if target not in self.srun_clients:
            return False
        self.active_ip = target
        self.config['active_ip'] = target
        save_config(self.config, self.aes_key)
        self.srun = self.get_client()
        if self.traffic_monitor is not None:
            self.traffic_monitor.update_selection(self.active_ip, self.host_ip)
        return True

    def get_config(self) -> Tuple:
        """
        Get current configuration.
        获取当前配置。

        Returns / 返回:
            Configuration tuple / 配置元组
        """
        return (
            self.username,
            self.password != "",
            self.auto_login,
            self.start_with_windows,
            self.isUptoDate,
            self.hasDoneUpdate,
            self.srun_host if self.srun_host != "" else self.host_ip,
            self.self_service,
            self.active_ip,
            self.local_ips,
        )

    def get_app_state(self) -> Dict[str, Any]:
        """Return named UI state without exposing the stored plaintext password."""
        return {
            "version": __version__,
            "username": self.username,
            "has_password": bool(self.password),
            "auto_login": self.auto_login,
            "start_with_windows": self.start_with_windows,
            "update_available": self.isUptoDate,
            "gateway": self.srun_host if self.srun_host else self.host_ip,
            "self_service": self.self_service,
            "active_ip": self.active_ip,
            "selected_ips": list(self.local_ips),
            "available_ips": get_local_ipv4_addresses(),
            "reconnect_interval": self.sleeptime,
            "allow_unverified_tls": self.allow_unverified_tls,
            "allow_insecure_http": self.allow_insecure_http,
            "traffic_sampling_enabled": self.traffic_sampling_enabled,
            "traffic_sample_interval": self.traffic_sample_interval,
            "traffic_history_enabled": self.traffic_history_enabled,
            "traffic_retention_days": self.traffic_retention_days,
        }

    def get_connection_status(self, ip: Optional[str] = None) -> Dict[str, Any]:
        """Return a structured connection state and safe diagnostic message."""
        client = self.get_client(ip)
        if client is None:
            return {
                "available": False,
                "online": False,
                "data": {},
                "error_code": "interface_unavailable",
                "message": "所选网络接口不可用",
            }

        is_available, is_online, data = client.is_connected()
        last_error = getattr(client, "last_error", None)
        return {
            "available": is_available,
            "online": is_online,
            "data": normalize_account_metrics(data, is_online=is_online).to_dict(),
            "error_code": getattr(last_error, "code", None),
            "message": getattr(last_error, "message", None),
        }

    def get_traffic_capabilities(self) -> Dict[str, Any]:
        """Return the fixed traffic feature contract exposed to the dashboard."""
        if self.traffic_monitor is None:
            return {"supported": False, "ranges": []}
        return self.traffic_monitor.get_capabilities()

    def get_traffic_snapshot(self) -> Dict[str, Any]:
        """Read the in-memory sample without contacting the SRun gateway."""
        if self.traffic_monitor is None or not self.traffic_sampling_enabled:
            return {
                "available": False,
                "gap": True,
                "message": "实时流量采样已关闭",
            }
        return self.traffic_monitor.get_snapshot()

    def get_traffic_history(self, history_range: str) -> Dict[str, Any]:
        """Return one allow-listed range with a bounded number of points."""
        supported_ranges = {"recent", "1h", "5h", "12h", "24h", "7d"}
        if history_range not in supported_ranges:
            return {"ok": False, "range": history_range, "points": [], "message": "不支持的历史范围"}
        if self.traffic_monitor is None:
            return {"ok": False, "range": history_range, "points": [], "message": "流量监控不可用"}
        return {
            "ok": True,
            "range": history_range,
            "points": self.traffic_monitor.get_history(history_range),
        }

    def update_traffic_preferences(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and persist only traffic-monitor preferences."""
        try:
            sample_interval = float(settings.get("sample_interval", self.traffic_sample_interval))
            retention_days = int(settings.get("retention_days", self.traffic_retention_days))
        except (TypeError, ValueError):
            return {"ok": False, "message": "采样间隔或保留天数无效"}
        if not 0.5 <= sample_interval <= 5.0:
            return {"ok": False, "message": "采样间隔必须在 0.5 到 5 秒之间"}
        if not 1 <= retention_days <= 30:
            return {"ok": False, "message": "历史保留天数必须在 1 到 30 天之间"}

        self.config["traffic_sampling_enabled"] = bool(settings.get("enabled", True))
        self.config["traffic_sample_interval"] = sample_interval
        self.config["traffic_history_enabled"] = bool(settings.get("history_enabled", True))
        self.config["traffic_retention_days"] = retention_days
        save_config(self.config, self.aes_key)
        self.refresh_config()
        return {"ok": True, "message": "流量监控设置已保存"}

    def clear_traffic_history(self) -> Dict[str, Any]:
        """Delete persisted and in-memory traffic history."""
        if self.traffic_monitor is None:
            return {"ok": False, "message": "流量监控不可用"}
        self.traffic_monitor.clear_history()
        return {"ok": True, "message": "流量历史已清空"}

    def perform_login(
        self,
        username: str,
        password: str,
        ip: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Save changed credentials and execute login as one UI operation."""
        if not username.strip():
            return {"ok": False, "message": "请输入用户名"}
        if not password and not self.password:
            return {"ok": False, "message": "请输入密码"}

        self.set_config(username.strip(), password)
        client = self.get_client(ip)
        if client is None:
            return {"ok": False, "message": "所选网络接口不可用"}
        try:
            login_succeeded = client.login(self.username, self.password)
        except Exception as error:
            return {"ok": False, "message": str(error)}

        if not login_succeeded:
            last_error = getattr(client, "last_error", None)
            return {
                "ok": False,
                "message": getattr(last_error, "message", "登录失败，请检查账号和网络"),
            }

        if not self.pass_correct:
            self.config["pass_correct"] = True
            save_config(self.config, self.aes_key)
            self.refresh_config()
        return {"ok": True, "message": "登录成功"}

    def perform_logout(self, ip: Optional[str] = None) -> Dict[str, Any]:
        """Execute logout and preserve a user-readable failure reason."""
        client = self.get_client(ip)
        if client is None:
            return {"ok": False, "message": "所选网络接口不可用"}
        try:
            logout_succeeded = client.logout()
        except Exception as error:
            return {"ok": False, "message": str(error)}
        return {
            "ok": logout_succeeded,
            "message": "已注销" if logout_succeeded else "注销失败，请稍后重试",
        }

    def update_preferences(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Validate and atomically apply desktop settings from the new UI."""
        gateway = str(settings.get("gateway", "")).strip()
        self_service = str(settings.get("self_service", "")).strip()
        if not self._update_gateway_only(gateway, self_service):
            return {"ok": False, "message": "无法解析网关地址，请检查输入"}

        try:
            reconnect_interval = int(settings.get("reconnect_interval", self.sleeptime))
        except (TypeError, ValueError):
            return {"ok": False, "message": "重连间隔必须是整数"}
        if not 3 <= reconnect_interval <= 300:
            return {"ok": False, "message": "重连间隔必须在 3 到 300 秒之间"}

        selected_ips = settings.get("selected_ips")
        active_ip = settings.get("active_ip")
        self._update_local_ip_selection(selected_ips, active_ip)
        self.config["sleeptime"] = reconnect_interval
        self.config["allow_unverified_tls"] = bool(settings.get("allow_unverified_tls"))
        self.config["allow_insecure_http"] = bool(settings.get("allow_insecure_http"))
        save_config(self.config, self.aes_key)
        self.refresh_config()
        return {"ok": True, "message": "设置已保存"}

    def get_ip_settings(self) -> Dict[str, Any]:
        """
        Get IP settings.
        获取 IP 设置。

        Returns / 返回:
            IP settings dictionary / IP 设置字典
        """
        return {
            "available": get_local_ipv4_addresses(),
            "selected": self.local_ips,
            "active": self.active_ip,
            "gateway": self.srun_host if self.srun_host != "" else self.host_ip,
            "self_service": self.self_service,
        }

    def update_ip_settings(self, settings: Dict[str, Any]) -> bool:
        """
        Update IP settings.
        更新 IP 设置。

        Args / 参数:
            settings: Settings dictionary / 设置字典

        Returns / 返回:
            True if successful / 成功返回 True
        """
        gateway = settings.get(
            'gateway',
            self.srun_host if self.srun_host != "" else self.host_ip
        )
        self_service = settings.get('self_service', self.self_service)
        selected = settings.get('selected')
        active = settings.get('active')
        return self.set_srun_host(gateway, self_service, selected, active)


    def do_update(self, start: bool = False) -> bool:
        """
        Perform software update.
        执行软件更新。

        Args / 参数:
            start: Whether to restart after update / 是否在更新后重启

        Returns / 返回:
            True if successful / 成功返回 True
        """
        if start:
            webbrowser.open("https://github.com/cjdem/SRunPy-GUI/releases/latest")
            return True
        self.hasDoneUpdate = True
        return True

    def start_self_service(self, ip: Optional[str] = None) -> None:
        """
        Open self-service portal in browser.
        在浏览器中打开自助服务门户。

        Args / 参数:
            ip: Client IP (None for default) / 客户端 IP（None 表示默认）
        """
        client = self.get_client(ip)
        configured_service = self.self_service.strip().rstrip("/")
        if configured_service.startswith(("http://", "https://")):
            self_service_url = configured_service
        else:
            self_service_url = f"https://{configured_service}"
        if client is None:
            webbrowser.open(self_service_url)
            return

        is_available, is_online, data = client.is_connected()
        if is_online:
            if "user_name" in data:
                username = data["user_name"]
            else:
                username = self.username
            data_str = base64.standard_b64encode(
                f"zh-CN:{username}".encode()
            ).decode()
            webbrowser.open(
                f"{self_service_url}/site/sso?data={data_str}"
            )
        else:
            webbrowser.open(self_service_url)

    def set_srun_host(self, srun_host: str, self_service: str,
                      selected_ips: Optional[List[Optional[str]]] = None,
                      active_ip: Optional[str] = None) -> bool:
        """
        Set gateway host and update configuration.
        设置网关主机并更新配置。

        Args / 参数:
            srun_host: Gateway host / 网关主机
            self_service: Self-service URL / 自助服务 URL
            selected_ips: List of selected IPs / 选定的 IP 列表
            active_ip: Active IP / 活动 IP

        Returns / 返回:
            True if successful / 成功返回 True
        """
        if not self._update_gateway_only(srun_host, self_service):
            return False
        self._update_local_ip_selection(selected_ips, active_ip)
        save_config(self.config, self.aes_key)
        self.refresh_config()
        return True

    def login(self, ip: Optional[str] = None) -> bool:
        """
        Login to gateway.
        登录到网关。

        Args / 参数:
            ip: Client IP (None for default) / 客户端 IP（None 表示默认）

        Returns / 返回:
            True if successful / 成功返回 True
        """
        client = self.get_client(ip)
        if client is None:
            return False
        try:
            success = client.login(self.username, self.password)
        except Exception:
            success = False

        if success and not self.pass_correct:
            self.config['pass_correct'] = True
            save_config(self.config, self.aes_key)
            self.refresh_config()
        return success

    def logout(self, ip: Optional[str] = None) -> str:
        """
        Logout from gateway.
        从网关注销。

        Args / 参数:
            ip: Client IP (None for default) / 客户端 IP（None 表示默认）

        Returns / 返回:
            True if successful / 成功返回 True
        """
        client = self.get_client(ip)
        if client is None:
            return False
        try:
            if client.logout():
                return "success"
                # for _ in range(20):
                #     _, is_online, _ = client.is_connected()
                #     if not is_online:
                #         return "success"
                #     time.sleep(0.25)
                # return "timeout"
            else:
                return "failed"
        except Exception as e:
            return str(e)

    def get_online_data(self, ip: Optional[str] = None,
                        hope: Optional[bool] = None) -> Tuple[bool, bool, Dict]:
        """
        Get online status and data.
        获取在线状态和数据。

        Args / 参数:
            ip: Client IP (None for default) / 客户端 IP（None 表示默认）
            hope: Expected online status / 期望的在线状态

        Returns / 返回:
            Tuple of (is_available, is_online, data) /
            (是否可用, 是否在线, 数据) 的元组
        """
        client = self.get_client(ip)
        if client is None:
            return False, False, {}
        try:
            is_available = False
            is_online = False
            data = {}
            if hope is not None:
                time.sleep(0.25)
            for _ in range(5):
                is_available, is_online, data = client.is_connected()
                if hope is None or is_online == hope:
                    break
                time.sleep(0.6)
            return is_available, is_online, data
        except Exception:
            return False, False, {}


class MainWindow:
    """
    Main window for the GUI application.
    GUI 应用程序的主窗口。
    """

    def __init__(self, srunpy: GUIBackend, open_window: bool = True) -> None:
        """
        Initialize main window.
        初始化主窗口。

        Args / 参数:
            srunpy: Backend instance / 后端实例
            open_window: Whether to open window immediately / 是否立即打开窗口
        """
        self.srunpy = srunpy
        self.window: Optional[Any] = None
        if self.srunpy.qt_backend:
            self.icon_path = os.path.join(WebRoot, r'icons\logo.png')
        if open_window:
            self.start_webview()

    def start_webview(self) -> None:
        """
        Start the webview window.
        启动 webview 窗口。
        """
        if len(webview.windows) > 0:
            print('window exists')
            return

        localization = {
            'global.quitConfirmation': '确定关闭?',
        }

        self.window = webview.create_window(
            "校园网登录器",
            os.path.join(WebRoot, "index.html"),
            width=1120,
            height=800,
            min_size=(720, 640),
            resizable=True,
            frameless=False,
        )
        
        self.hwnd = None

        def _animate_and_action(action: str) -> None:
            """
            Animate the frameless window using AnimateWindow if hwnd is available,
            then perform the requested action ('close' or 'minimize').
            """
            hwnd = getattr(self, 'hwnd', None)
            # Fallback to original behavior if no hwnd
            if not hwnd:
                if action == 'close':
                    try:
                        self.window.destroy()
                    except Exception:
                        pass
                else:
                    try:
                        self.window.minimize()
                    except Exception:
                        pass
                return

            try:
                # AnimateWindow flags
                AW_HIDE = 0x00010000
                AW_CENTER = 0x00000010
                AW_BLEND = 0x00080000

                

                animate = getattr(ctypes.windll.user32, "AnimateWindow", None)
                if animate is not None:
                    if action == 'close':
                        flags = AW_HIDE | AW_CENTER | AW_BLEND
                        # Slide down when closing (works well for frameless)
                        animate(hwnd, 300, flags)  # AW_VER_POSITIVE   
                    else:
                        # Use a short fade-out/slide when hiding (works well for frameless)
                        flags = AW_HIDE | AW_BLEND
                        # 200 ms feels natural (Windows typical animation length)
                        animate(hwnd, 200, flags)
            except Exception:
                # If animation fails, ignore and continue to the action
                pass

            # Perform the actual action
            try:
                if action == 'close':
                    self.window.destroy()
                else:
                    self.window.minimize()
            except Exception:
                pass    

        def close_window() -> None:
            _animate_and_action('close')

        def minimize_window() -> None:
            _animate_and_action('minimize')

        # Expose backend methods to JavaScript
        # 向 JavaScript 暴露后端方法
        self.window.expose(
            self.srunpy.get_online_data,
            self.srunpy.get_app_state,
            self.srunpy.get_connection_status,
            self.srunpy.get_traffic_capabilities,
            self.srunpy.get_traffic_snapshot,
            self.srunpy.get_traffic_history,
            self.srunpy.update_traffic_preferences,
            self.srunpy.clear_traffic_history,
            self.srunpy.perform_login,
            self.srunpy.perform_logout,
            self.srunpy.update_preferences,
            self.srunpy.login,
            self.srunpy.logout,
            self.srunpy.set_config,
            self.srunpy.get_config,
            self.srunpy.set_start_with_windows,
            self.srunpy.set_auto_login,
            self.srunpy.do_update,
            self.srunpy.start_self_service,
            self.srunpy.set_srun_host,
            self.srunpy.get_ip_settings,
            self.srunpy.update_ip_settings,
            self.srunpy.probe_gateway_ips,
            self.srunpy.set_active_client_ip,
            close_window,
            minimize_window
        )

        def after_window_created() -> None:
            """
            Callback after window is created for DPI scaling.
            窗口创建后的回调，用于 DPI 缩放。
            """
            if platform.system() == "Windows":
                # Ensure process is DPI aware
                # 确保进程支持 DPI
                try:
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

                # Get window handle and apply DPI scaling
                # 获取窗口句柄并应用 DPI 缩放
                hwnd = None
                random_title = uuid.uuid4().hex
                self.window.set_title(random_title)
                for _ in range(20):
                    hwnd = win32gui.FindWindow(None, random_title)
                    if hwnd:
                        break
                    time.sleep(0.05)
                self.window.set_title("校园网登陆器")

                if hwnd:
                    self.hwnd = hwnd
                    try:
                        icon_file = os.path.join(WebRoot, 'icons', 'logo.ico')
                        if os.path.exists(icon_file):
                            # Try to load icon sizes for big and small icons
                            large = win32gui.LoadImage(0, icon_file, win32con.IMAGE_ICON, 32, 32, win32con.LR_LOADFROMFILE)
                            small = win32gui.LoadImage(0, icon_file, win32con.IMAGE_ICON, 16, 16, win32con.LR_LOADFROMFILE)
                            if large:
                                win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_BIG, large)
                            if small:
                                win32gui.SendMessage(hwnd, win32con.WM_SETICON, win32con.ICON_SMALL, small)
                    except Exception:
                        pass

                    # try:
                    #     class MARGINS(ctypes.Structure):
                    #         _fields_ = [
                    #             ("cxLeftWidth", ctypes.c_int),
                    #             ("cxRightWidth", ctypes.c_int),
                    #             ("cyTopHeight", ctypes.c_int),
                    #             ("cyBottomHeight", ctypes.c_int),
                    #         ]

                    #     # 尝试通过 DWM 将窗口框架延伸到客户区顶部，模拟标题栏高度
                    #     try:
                    #         sys_cycaption = win32api.GetSystemMetrics(win32con.SM_CYCAPTION)
                    #         margins = MARGINS(0, 0, int(sys_cycaption), 0)
                    #         dwm = getattr(ctypes.windll, "dwmapi", None)
                    #         if dwm is not None:
                    #             dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
                    #     except Exception:
                    #         # 若不支持 DWM 或调用失败，静默忽略
                    #         pass
                    # except Exception as e:
                    #     pass

        if self.srunpy.qt_backend:
            webview.start(
                after_window_created,
                localization=localization,
                debug=False,
                gui='qt',
                icon=self.icon_path
            )
        else:
            webview.start(
                after_window_created,
                localization=localization,
                debug=False
            )
