"""
Srun Authentication Module / Srun 认证模块

This module provides functionality to interact with the Srun authentication system.
本模块提供与深澜认证系统交互的功能。

Modified from: https://github.com/iskoldt-X/SRUN-authenticator
"""

import hashlib
import hmac
import json
import math
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple
from urllib.parse import parse_qs, urlparse

import requests
from requests.adapters import HTTPAdapter
from requests.exceptions import RequestException, SSLError, Timeout
from urllib3.poolmanager import PoolManager

from srunpy.errors import (
    AlreadyOnlineError,
    AuthenticationRejectedError,
    GatewayProtocolError,
    GatewayUnavailableError,
    NotOnlineError,
    RequestTimeoutError,
    SrunError,
    TLSVerificationError,
)


def get_md5(password: str, token: str) -> str:
    """
    Generate MD5 hash with HMAC for password.
    使用 HMAC 为密码生成 MD5 哈希。

    Args / 参数:
        password: User password / 用户密码
        token: Authentication token / 认证令牌

    Returns / 返回:
        MD5 hash string / MD5 哈希字符串
    """
    return hmac.new(token.encode(), password.encode(), hashlib.md5).hexdigest()


def get_sha1(value: str) -> str:
    """
    Generate SHA1 hash for a string value.
    为字符串值生成 SHA1 哈希。

    Args / 参数:
        value: Input string / 输入字符串

    Returns / 返回:
        SHA1 hash string / SHA1 哈希字符串
    """
    return hashlib.sha1(value.encode()).hexdigest()


def force(msg: str) -> bytes:
    """
    Convert string to bytes array (unused utility function).
    将字符串转换为字节数组（未使用的工具函数）。

    Args / 参数:
        msg: Input string / 输入字符串

    Returns / 返回:
        Bytes representation / 字节表示
    """
    ret = []
    for w in msg:
        ret.append(ord(w))
    return bytes(ret)


def ordat(msg: str, idx: int) -> int:
    """
    Get character code at index, return 0 if out of bounds.
    获取索引处的字符代码，如果越界则返回 0。

    Args / 参数:
        msg: Input string / 输入字符串
        idx: Index position / 索引位置

    Returns / 返回:
        Character code or 0 / 字符代码或 0
    """
    if len(msg) > idx:
        return ord(msg[idx])
    return 0


def sencode(msg: str, key: bool) -> List[int]:
    """
    Encode string to integer array (Srun encoding algorithm).
    将字符串编码为整数数组（深澜编码算法）。

    Args / 参数:
        msg: Message to encode / 要编码的消息
        key: Whether to append length / 是否追加长度

    Returns / 返回:
        List of encoded integers / 编码整数列表
    """
    message_length = len(msg)
    encoded_words = []
    for character_index in range(0, message_length, 4):
        encoded_words.append(
            ordat(msg, character_index)
            | ordat(msg, character_index + 1) << 8
            | ordat(msg, character_index + 2) << 16
            | ordat(msg, character_index + 3) << 24
        )
    if key:
        encoded_words.append(message_length)
    return encoded_words


def lencode(msg: List[int], key: bool) -> Optional[str]:
    """
    Convert integer array back to string (Srun decoding algorithm).
    将整数数组转换回字符串（深澜解码算法）。

    Args / 参数:
        msg: List of integers to decode / 要解码的整数列表
        key: Whether length was appended / 是否追加了长度

    Returns / 返回:
        Decoded string or None / 解码的字符串或 None
    """
    word_count = len(msg)
    decoded_length = (word_count - 1) << 2
    if key:
        message_length = msg[word_count - 1]
        if message_length < decoded_length - 3 or message_length > decoded_length:
            return None
        decoded_length = message_length
    for word_index in range(word_count):
        encoded_word = msg[word_index]
        msg[word_index] = (
            chr(encoded_word & 0xff)
            + chr(encoded_word >> 8 & 0xff)
            + chr(encoded_word >> 16 & 0xff)
            + chr(encoded_word >> 24 & 0xff)
        )
    if key:
        return "".join(msg)[:decoded_length]
    return "".join(msg)


def get_xencode(msg: str, key: str) -> str:
    """
    Apply Srun XEncode encryption algorithm.
    应用深澜 XEncode 加密算法。

    Args / 参数:
        msg: Message to encode / 要编码的消息
        key: Encryption key / 加密密钥

    Returns / 返回:
        Encoded string / 编码后的字符串
    """
    if msg == "":
        return ""
    pwd = sencode(msg, True)
    pwdk = sencode(key, False)
    if len(pwdk) < 4:
        pwdk = pwdk + [0] * (4 - len(pwdk))
    n = len(pwd) - 1
    z = pwd[n]
    y = pwd[0]
    c = 0x86014019 | 0x183639A0
    m = 0
    e = 0
    p = 0
    q = math.floor(6 + 52 / (n + 1))
    d = 0
    while 0 < q:
        d = d + c & (0x8CE0D9BF | 0x731F2640)
        e = d >> 2 & 3
        p = 0
        while p < n:
            y = pwd[p + 1]
            m = z >> 5 ^ y << 2
            m = m + ((y >> 3 ^ z << 4) ^ (d ^ y))
            m = m + (pwdk[(p & 3) ^ e] ^ z)
            pwd[p] = pwd[p] + m & (0xEFB8D130 | 0x10472ECF)
            z = pwd[p]
            p = p + 1
        y = pwd[0]
        m = z >> 5 ^ y << 2
        m = m + ((y >> 3 ^ z << 4) ^ (d ^ y))
        m = m + (pwdk[(p & 3) ^ e] ^ z)
        pwd[n] = pwd[n] + m & (0xBB390742 | 0x44C6F8BD)
        z = pwd[n]
        q = q - 1
    return lencode(pwd, False)


def parse_json_or_jsonp(raw_response: str) -> Dict[str, Any]:
    """Parse a JSON or JSONP object returned by a Srun gateway.

    A malformed payload is a protocol error rather than an offline result. This
    distinction allows the desktop UI to give a useful diagnostic instead of
    suggesting that the computer is simply outside the campus network.
    """
    response_text = (raw_response or "").strip()
    if not response_text:
        raise GatewayProtocolError("网关返回了空响应")

    json_text = response_text
    callback_start = response_text.find("(")
    callback_end = response_text.rfind(")")
    if callback_start >= 0 and callback_end > callback_start:
        json_text = response_text[callback_start + 1:callback_end].strip()

    try:
        payload = json.loads(json_text)
    except (TypeError, ValueError) as error:
        raise GatewayProtocolError("网关返回了无法解析的 JSON/JSONP 响应") from error

    if not isinstance(payload, dict):
        raise GatewayProtocolError("网关响应必须是 JSON 对象")
    return payload


@dataclass(frozen=True)
class _RequestCandidate:
    """One explicitly allowed transport candidate for a gateway request."""

    base_url: str
    verify_tls: bool
    use_host_header: bool = False


class SourceIPAdapter(HTTPAdapter):
    """
    HTTP Adapter for binding requests to a specific source IP address.
    用于将请求绑定到特定源 IP 地址的 HTTP 适配器。
    """

    def __init__(self, source_ip: str, **kwargs):
        """
        Initialize the adapter with source IP.
        使用源 IP 初始化适配器。

        Args / 参数:
            source_ip: Source IP address to bind / 要绑定的源 IP 地址
            **kwargs: Additional arguments for HTTPAdapter / HTTPAdapter 的额外参数
        """
        self.source_address = (source_ip, 0)
        super().__init__(**kwargs)

    def init_poolmanager(self, connections: int, maxsize: int,
                         block: bool = False, **pool_kwargs) -> None:
        """
        Initialize pool manager with source address.
        使用源地址初始化池管理器。
        """
        pool_kwargs["source_address"] = self.source_address
        self.poolmanager = PoolManager(
            num_pools=connections, maxsize=maxsize, block=block, **pool_kwargs
        )

    def proxy_manager_for(self, proxy: str, **proxy_kwargs):
        """
        Initialize proxy manager with source address.
        使用源地址初始化代理管理器。
        """
        proxy_kwargs["source_address"] = self.source_address
        return super().proxy_manager_for(proxy, **proxy_kwargs)


class Srun_Py:
    """
    Srun Gateway Authentication Client.
    深澜网关认证客户端。

    This class handles authentication with Srun gateway systems.
    该类处理与深澜网关系统的认证。
    """

    def __init__(
        self,
        srun_host: str = "gw.buaa.edu.cn",
        host_ip: str = "10.200.21.4",
        client_ip: Optional[str] = None,
        *,
        request_timeout: Tuple[float, float] = (3.0, 5.0),
        allow_unverified_tls: bool = False,
        allow_insecure_http: bool = False,
        trust_environment: bool = False,
    ) -> None:
        """
        Initialize Srun client.
        初始化深澜客户端。

        Args / 参数:
            srun_host: Gateway hostname / 网关主机名
            host_ip: Gateway IP address / 网关 IP 地址
            client_ip: Client IP address to bind (optional) / 要绑定的客户端 IP（可选）
        """
        self.srun_host = self._normalize_host(srun_host or host_ip)
        self.host_ip = self._normalize_host(host_ip or self.srun_host)
        self.init_url = f"https://{self.srun_host}"
        self.get_ip_api = f"{self.init_url}/cgi-bin/rad_user_info?callback=JQuery"
        self.get_ip_api_ip = f"https://{self.host_ip}/cgi-bin/rad_user_info?callback=JQuery"
        self.get_challenge_api = f"{self.init_url}/cgi-bin/get_challenge"
        self.get_challenge_api_ip = f"https://{self.host_ip}/cgi-bin/get_challenge"
        self.srun_portal_api = f"{self.init_url}/cgi-bin/srun_portal"
        self.srun_portal_api_ip = f"https://{self.host_ip}/cgi-bin/srun_portal"
        self.rad_user_dm_api = f"{self.init_url}/cgi-bin/rad_user_dm"
        self.rad_user_dm_api_ip = f"https://{self.host_ip}/cgi-bin/rad_user_dm"
        self.header = {
            "Host": self.srun_host,
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 "
                "Safari/537.36 Edg/122.0.0.0"
            ),
        }
        self.n = "200"
        self.type = "1"
        self.ac_id = "1"
        self.enc = "srun_bx1"
        self._ALPHA = "LVoJPiCN2R8G90yg+hmFHuacZ1OWMnrsSTXkYpUq/3dlbfKwv6xztjI7DeBE45QA"
        self.client_ip = client_ip
        self.request_timeout = request_timeout
        self.allow_unverified_tls = allow_unverified_tls
        self.allow_insecure_http = allow_insecure_http
        self.last_error: Optional[SrunError] = None
        self.session = requests.Session()
        self.session.trust_env = trust_environment
        if self.client_ip:
            adapter = SourceIPAdapter(self.client_ip)
            self.session.mount("http://", adapter)
            self.session.mount("https://", adapter)

    @staticmethod
    def _normalize_host(host: str) -> str:
        """Return a host name without a URL scheme, path, or trailing slash."""
        normalized_host = (host or "").strip()
        if "://" in normalized_host:
            parsed_host = urlparse(normalized_host).hostname
            normalized_host = parsed_host or ""
        else:
            normalized_host = normalized_host.split("/", 1)[0]
        if not normalized_host:
            raise ValueError("网关地址不能为空")
        return normalized_host

    def _build_request_candidates(self) -> List[_RequestCandidate]:
        """Build the ordered transports explicitly enabled for this client."""
        candidates = [_RequestCandidate(f"https://{self.srun_host}", verify_tls=True)]

        if self.allow_unverified_tls:
            unverified_host = self.host_ip or self.srun_host
            candidates.append(
                _RequestCandidate(
                    f"https://{unverified_host}",
                    verify_tls=False,
                    use_host_header=unverified_host != self.srun_host,
                )
            )

        if self.allow_insecure_http:
            candidates.append(_RequestCandidate(f"http://{self.srun_host}", verify_tls=True))
            if self.host_ip != self.srun_host:
                candidates.append(
                    _RequestCandidate(
                        f"http://{self.host_ip}",
                        verify_tls=True,
                        use_host_header=True,
                    )
                )

        unique_candidates: List[_RequestCandidate] = []
        for candidate in candidates:
            if candidate not in unique_candidates:
                unique_candidates.append(candidate)
        return unique_candidates

    def _request(
        self,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        allow_redirects: bool = True,
    ) -> requests.Response:
        """Send a GET request using only explicitly enabled transport fallbacks."""
        last_error: Optional[SrunError] = None
        normalized_path = path if path.startswith("/") else f"/{path}"

        for candidate in self._build_request_candidates():
            request_headers = {"User-Agent": self.header["User-Agent"]}
            if candidate.use_host_header:
                request_headers["Host"] = self.srun_host

            try:
                response = self.session.get(
                    f"{candidate.base_url}{normalized_path}",
                    params=params,
                    headers=request_headers,
                    timeout=self.request_timeout,
                    verify=candidate.verify_tls,
                    allow_redirects=allow_redirects,
                )
                response.raise_for_status()
                self.last_error = None
                return response
            except Timeout as error:
                last_error = RequestTimeoutError(
                    f"连接网关 {self.srun_host} 超时，请检查网络或网关设置"
                )
                last_error.__cause__ = error
            except SSLError as error:
                last_error = TLSVerificationError(
                    f"无法验证网关 {self.srun_host} 的 HTTPS 证书"
                )
                last_error.__cause__ = error
            except RequestException as error:
                last_error = GatewayUnavailableError(
                    f"无法连接网关 {self.srun_host}"
                )
                last_error.__cause__ = error

        self.last_error = last_error
        if last_error is not None:
            raise last_error
        raise GatewayUnavailableError(f"没有可用于访问 {self.srun_host} 的连接方式")

    def close(self) -> None:
        """Close pooled network connections owned by this client."""
        self.session.close()

    def __enter__(self) -> "Srun_Py":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def get_base64(self, s: str) -> str:
        """
        Custom base64 encoding using Srun's alphabet.
        使用深澜的字母表进行自定义 base64 编码。

        Args / 参数:
            s: String to encode / 要编码的字符串

        Returns / 返回:
            Encoded string / 编码后的字符串
        """
        r = []
        x = len(s) % 3
        if x:
            s = s + '\0' * (3 - x)
        for i in range(0, len(s), 3):
            d = s[i:i + 3]
            a = ord(d[0]) << 16 | ord(d[1]) << 8 | ord(d[2])
            r.append(self._ALPHA[a >> 18])
            r.append(self._ALPHA[a >> 12 & 63])
            r.append(self._ALPHA[a >> 6 & 63])
            r.append(self._ALPHA[a & 63])
        if x == 1:
            r[-1] = '='
            r[-2] = '='
        if x == 2:
            r[-1] = '='
        return ''.join(r)

    def get_chksum(self, username: str, token: str, hmd5: str,
                   ip: str, i: str) -> str:
        """
        Generate checksum for authentication.
        生成认证校验和。

        Args / 参数:
            username: Username / 用户名
            token: Authentication token / 认证令牌
            hmd5: MD5 hash / MD5 哈希
            ip: IP address / IP 地址
            i: Info string / 信息字符串

        Returns / 返回:
            SHA1 checksum / SHA1 校验和
        """
        chkstr = token + username
        chkstr += token + hmd5
        chkstr += token + self.ac_id
        chkstr += token + ip
        chkstr += token + self.n
        chkstr += token + self.type
        chkstr += token + i
        return chkstr

    def get_info(self, username: str, password: str, ip: str) -> str:
        """
        Build info string for authentication.
        构建认证信息字符串。

        Args / 参数:
            username: Username / 用户名
            password: Password / 密码
            ip: IP address / IP 地址

        Returns / 返回:
            JSON info string / JSON 信息字符串
        """
        info_payload = {
            "username": username,
            "password": password,
            "ip": ip,
            "acid": self.ac_id,
            "enc_ver": self.enc,
        }
        return json.dumps(info_payload, ensure_ascii=False, separators=(",", ":"))

    def init_getip(self) -> Tuple[str, Optional[str]]:
        """
        Get current IP and username from gateway.
        从网关获取当前 IP 和用户名。

        Returns / 返回:
            Tuple of (IP address, username) / (IP 地址, 用户名) 的元组
        """
        response = self._request(
            "/cgi-bin/rad_user_info",
            params={"callback": "JQuery"},
        )
        payload = parse_json_or_jsonp(response.text)
        client_address = payload.get("client_ip") or payload.get("online_ip")
        if not client_address:
            raise GatewayProtocolError("网关状态响应中缺少客户端 IP")
        username = payload.get("user_name")
        return str(client_address), str(username) if username is not None else None

    def get_token(self, username: str, ip: str) -> str:
        """
        Get authentication token from gateway.
        从网关获取认证令牌。

        Args / 参数:
            username: Username / 用户名
            ip: IP address / IP 地址

        Returns / 返回:
            Authentication token / 认证令牌
        """
        get_challenge_params = {
            "callback": (
                "jQuery112404953340710317169_" +
                str(int(time.time() * 1000))
            ),
            "username": username,
            "ip": ip,
            "_": int(time.time() * 1000),
        }
        response = self._request(
            "/cgi-bin/get_challenge",
            params=get_challenge_params,
        )
        payload = parse_json_or_jsonp(response.text)
        challenge = payload.get("challenge")
        if not challenge:
            raise GatewayProtocolError("网关 challenge 响应中缺少 challenge 字段")
        return str(challenge)

    def is_connected(self) -> Tuple[bool, bool, Optional[Dict]]:
        """
        Check if the client is connected to the gateway.
        检查客户端是否连接到网关。

        Returns / 返回:
            Tuple of (is_available, is_online, data) /
            (是否可用, 是否在线, 数据) 的元组
        """
        try:
            response = self._request(
                "/cgi-bin/rad_user_info",
                params={"callback": "JQuery"},
            )
            payload = parse_json_or_jsonp(response.text)
        except SrunError as error:
            self.last_error = error
            return False, False, None

        self.last_error = None
        error_code = str(payload.get("error", "")).lower()
        if error_code == "not_online_error":
            return True, False, payload
        if error_code and error_code not in {"ok", "online"}:
            self.last_error = GatewayProtocolError(
                f"网关返回了未知状态：{error_code}"
            )
            return True, False, payload
        return True, True, payload

    def do_complex_work(self, username: str, password: str,
                        ip: str, token: str) -> Tuple[str, str, str]:
        """
        Perform complex authentication work (encoding and hashing).
        执行复杂的认证工作（编码和哈希）。

        Args / 参数:
            username: Username / 用户名
            password: Password / 密码
            ip: IP address / IP 地址
            token: Authentication token / 认证令牌

        Returns / 返回:
            Tuple of (info, hmd5, chksum) / (信息, MD5哈希, 校验和) 的元组
        """
        i = self.get_info(username, password, ip)
        i = "{SRBX1}" + self.get_base64(get_xencode(i, token))
        hmd5 = get_md5(password, token)
        chksum = get_sha1(self.get_chksum(username, token, hmd5, ip, i))
        return i, hmd5, chksum

    def _parse_portal_payload(self, raw: str) -> Dict[str, Any]:
        """
        Parse raw portal response (JSON or JSONP) into a dictionary.
        将门户原始响应（JSON 或 JSONP）解析为字典。

        Args / 参数:
            raw: Raw response text / 原始响应文本

        Returns / 返回:
            Parsed payload dictionary / 解析后的载荷字典
        """
        try:
            return parse_json_or_jsonp(raw)
        except GatewayProtocolError:
            return {}

    def update_acid(self) -> None:
        """
        Update AC ID from gateway redirect URL.
        从网关重定向 URL 更新 AC ID。
        """
        response = self._request("/", allow_redirects=True)
        parsed_url = urlparse(response.url)
        query_params = parse_qs(parsed_url.query)
        acid_values = query_params.get("ac_id", [])
        if acid_values:
            self.ac_id = acid_values[0]

    def login(self, username: str, password: str) -> bool:
        """
        Login to the gateway.
        登录到网关。

        Args / 参数:
            username: Username / 用户名
            password: Password / 密码

        Returns / 返回:
            True if login successful / 登录成功返回 True

        Raises / 抛出:
            SrunError: If the gateway cannot be reached or the response is invalid /
                      如果网关不可达或响应无效
        """
        is_available, is_online, _ = self.is_connected()
        if not is_available:
            if self.last_error is not None:
                raise self.last_error
            raise GatewayUnavailableError("网关当前不可用")
        if is_online:
            raise AlreadyOnlineError("当前线路已经登录")

        self.update_acid()
        client_address, _ = self.init_getip()
        token = self.get_token(username, client_address)
        info, password_digest, checksum = self.do_complex_work(
            username,
            password,
            client_address,
            token,
        )
        srun_portal_params = {
            "callback": "jQuery11240645308969735664_" + str(int(time.time() * 1000)),
            "action": "login",
            "username": username,
            "password": "{MD5}" + password_digest,
            "ac_id": self.ac_id,
            "ip": client_address,
            "chksum": checksum,
            "info": info,
            "n": self.n,
            "type": self.type,
            "os": "windows+10",
            "name": "windows",
            "double_stack": "0",
            "_": int(time.time() * 1000),
        }

        response = self._request(
            "/cgi-bin/srun_portal",
            params=srun_portal_params,
        )
        payload = parse_json_or_jsonp(response.text)
        if str(payload.get("error", "")).lower() == "ok":
            self.last_error = None
            return True

        gateway_message = payload.get("error_msg") or payload.get("error")
        self.last_error = AuthenticationRejectedError(
            f"网关拒绝登录：{gateway_message or '请检查用户名和密码'}"
        )
        return False

    def logout(self) -> bool:
        is_available, is_online, _ = self.is_connected()
        if not is_available:
            if self.last_error is not None:
                raise self.last_error
            raise GatewayUnavailableError("网关当前不可用")
        if not is_online:
            raise NotOnlineError("当前线路尚未登录")

        try:
            self.update_acid()
        except SrunError:
            pass

        client_address, username = self.init_getip()
        params = {
            "action": "logout",
            "username": username,
            "ip": client_address,
            "ac_id": self.ac_id,
        }

        raw_response = ""
        try:
            raw_response = self._request(
                "/cgi-bin/srun_portal",
                params=params,
            ).text
        except GatewayUnavailableError:
            pass

        payload = self._parse_portal_payload(raw_response)
        success_codes = {
            str(payload.get("error", "")).lower(),
            str(payload.get("res", "")).lower(),
            str(payload.get("error_msg", "")).lower(),
            raw_response.strip().lower(),
        }

        if success_codes & {"ok", "logout_ok"}:
            self.last_error = None
            return True

        classic_response = self.logout_classic().strip().lower()
        logout_succeeded = classic_response in {"ok", "logout_ok", "success", "1", "true"}
        if logout_succeeded:
            self.last_error = None
        else:
            self.last_error = GatewayProtocolError("网关未确认注销成功")
        return logout_succeeded

    def logout_classic(self) -> str:
        """
        Logout from the gateway.
        从网关注销。

        Returns / 返回:
            True if logout successful / 注销成功返回 True

        Raises / 抛出:
            Exception: If not online or network not available /
                      如果未在线或网络不可用
        """
        client_address, username = self.init_getip()
        if not username:
            raise GatewayProtocolError("网关状态响应中缺少用户名，无法执行传统注销")

        timestamp = int(time.time() * 1000)
        sign = get_sha1(
            str(timestamp) + username + client_address + "0" + str(timestamp)
        )
        user_dm_params = {
            "ip": client_address,
            "username": username,
            "time": timestamp,
            "unbind": 0,
            "sign": sign,
        }
        response = self._request(
            "/cgi-bin/rad_user_dm",
            params=user_dm_params,
        )
        return response.text
