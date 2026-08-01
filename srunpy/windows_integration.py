"""Windows-specific desktop integration: shortcuts, tray icon, theme and legacy AES.

This layer owns everything that only makes sense on an interactive Windows
desktop: the Start Menu startup shortcut, the system tray icon, the light/dark
theme probe, the legacy fixed-key AES decryptor, and the GitHub update check.
It has no dependency on the GUI backend orchestration.
"""

import os
import sys
from binascii import a2b_hex, b2a_hex
from typing import Final

import pystray
import requests
import win32api
import win32com.client as client
import win32con
from Crypto.Cipher import AES
from PIL import Image

from srunpy import WebRoot, __version__
from srunpy.update import is_newer_release

application_path = os.path.abspath(sys.argv[0])
python_path = os.path.abspath(sys.executable)
start_lnk_path = os.path.join(
    os.path.expandvars(r'%APPDATA%'),
    r'Microsoft\Windows\Start Menu\Programs\Startup',
    '校园网登录器.lnk'
)
legacy_start_lnk_path = os.path.join(
    os.path.expandvars(r'%APPDATA%'),
    r'Microsoft\Windows\Start Menu\Programs\Startup',
    '校园网登陆器.lnk'
)
LEGACY_AES_KEY: Final[str] = "dj26Dh47useoUI28"


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


def check_lnk() -> bool:
    """
    Check if startup link exists.
    检查启动链接是否存在。

    Returns / 返回:
        True if exists / 如果存在返回 True
    """
    return os.path.exists(start_lnk_path) or os.path.exists(legacy_start_lnk_path)


def delete_lnk() -> None:
    """
    Delete current and legacy startup links if they exist.
    如果存在则删除当前及旧版启动链接。
    """
    for shortcut_path in (start_lnk_path, legacy_start_lnk_path):
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)


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

    仅用于解密旧版本使用固定密钥写入的配置文件；新配置使用 DPAPI 保护。
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
            pystray.MenuItem("退出登录器", self.exit)
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
            "校园网登录器",
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
