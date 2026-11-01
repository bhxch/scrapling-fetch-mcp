"""daemon NDJSON 线路协议：帧构造与解析。

daemon worker（Task 7）与前端 client（Task 8）之间通过 unix socket
交换 NDJSON 帧：每帧一行 UTF-8 JSON，以 ``\\n`` 结尾。四类帧：

- 请求   ``{"v":2,"id":int,"op":str,"token":str,"pkg":str,"payload":{}}``
- 响应   ``{"v":2,"id":int,"ok":true,"result":...}``
- 错误   ``{"v":2,"id":int,"ok":false,"error":{"code":str,"message":str}}``
- 进度   ``{"v":2,"id":int,"progress":{"progress":float,"total":float,"message":str}}``

NDJSON 分帧依赖 ``json.dumps(..., ensure_ascii=True)``：所有非 ASCII
字符被转义，payload 内的换行也变成 ``\\n`` 转义序列，帧因此必然单行
——这是协议正确性的承重约束，勿改为 ``ensure_ascii=False``。

Import 边界约束：本模块在前端 import 白名单上，只允许 stdlib 与
``daemon.config_env``（取 ``PROTOCOL_VERSION``），禁止引入重依赖。
"""

from __future__ import annotations

import json

from scrapling_fetch_mcp.daemon.config_env import PROTOCOL_VERSION

__all__ = [
    "E_BAD_FRAME",
    "E_INTERNAL",
    "E_CANCELLED",
    "E_UNAUTHORIZED",
    "E_UNKNOWN_OP",
    "OP_CANCEL",
    "OP_FETCH_PAGE",
    "OP_FETCH_PATTERN",
    "OP_PING",
    "OP_SHUTDOWN",
    "OP_STATUS",
    "PROTOCOL_VERSION",
    "ProtocolError",
    "make_error",
    "make_progress",
    "make_request",
    "make_response",
    "parse_frame",
]

# op 名常量（请求帧的 "op" 字段取值）。
OP_FETCH_PAGE: str = "fetch_page"
OP_FETCH_PATTERN: str = "fetch_pattern"
OP_CANCEL: str = "cancel"
OP_PING: str = "ping"
OP_STATUS: str = "status"
OP_SHUTDOWN: str = "shutdown"

# 错误码常量（错误帧 error.code 取值）。
E_BAD_FRAME: str = "bad_frame"
E_UNAUTHORIZED: str = "unauthorized"
E_UNKNOWN_OP: str = "unknown_op"
E_CANCELLED: str = "cancelled"
E_INTERNAL: str = "internal"


class ProtocolError(ValueError):
    """帧不合法：JSON 解码失败、协议版本不匹配或信封字段缺失。"""


def _encode(frame: dict) -> bytes:
    """单行序列化一帧：ensure_ascii=True 保证 payload 内换行不破帧，尾部补 \\n。"""
    return json.dumps(frame, ensure_ascii=True).encode("utf-8") + b"\n"


def make_request(op: str, payload: dict, token: str, req_id: int, pkg: str) -> bytes:
    """构造请求帧（含尾部 \\n）。"""
    return _encode(
        {"v": PROTOCOL_VERSION, "id": req_id, "op": op, "token": token, "pkg": pkg, "payload": payload}
    )


def make_response(req_id: int, result: object) -> bytes:
    """构造成功响应帧（含尾部 \\n）。"""
    return _encode({"v": PROTOCOL_VERSION, "id": req_id, "ok": True, "result": result})


def make_error(req_id: int, code: str, message: str) -> bytes:
    """构造错误响应帧（含尾部 \\n）。"""
    return _encode(
        {"v": PROTOCOL_VERSION, "id": req_id, "ok": False, "error": {"code": code, "message": message}}
    )


def make_progress(req_id: int, progress: float, total: float, message: str) -> bytes:
    """构造 progress 中间帧（含尾部 \\n）。"""
    return _encode(
        {
            "v": PROTOCOL_VERSION,
            "id": req_id,
            "progress": {"progress": progress, "total": total, "message": message},
        }
    )


def parse_frame(line: bytes) -> dict:
    """解析并校验一帧（不含尾部 \\n 亦可），返回解码后的 dict。

    - 非 JSON 输入 → ``ProtocolError``
    - ``v`` 必须是 int 且等于 ``PROTOCOL_VERSION``（bool 是 int 子类，一并
      拒绝；``2.0`` 这类 float 在 JSON 侧 ``==`` 相等，必须按类型挡掉）
    - 请求帧（含任一请求专属字段 ``op``/``token``/``pkg``/``payload``）
      必须有类型正确的 ``id``(int)/``op``(str)/``token``(str)；``payload``
      存在时必须是 dict——按字段族识别而非仅看 ``op``，否则缺 ``op`` 的
      残缺请求会漏检
    """
    try:
        frame = json.loads(line)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"帧不是合法 JSON: {exc}") from exc
    if not isinstance(frame, dict):
        raise ProtocolError(f"帧必须是 JSON object, 得到 {type(frame).__name__}")
    version = frame.get("v")
    if isinstance(version, bool) or not isinstance(version, int) or version != PROTOCOL_VERSION:
        raise ProtocolError(f"协议版本不匹配: 期望 v={PROTOCOL_VERSION}, 得到 {version!r}")
    if {"op", "token", "pkg", "payload"} & frame.keys():
        req_id = frame.get("id")
        if isinstance(req_id, bool) or not isinstance(req_id, int):
            raise ProtocolError(f"请求帧 id 必须是整数, 得到 {req_id!r}")
        for key in ("op", "token"):
            if not isinstance(frame.get(key), str):
                raise ProtocolError(f"请求帧 {key} 必须是字符串, 得到 {frame.get(key)!r}")
        if "payload" in frame and not isinstance(frame["payload"], dict):
            raise ProtocolError(
                f"payload 必须是 JSON object, 得到 {type(frame['payload']).__name__}"
            )
    return frame
