"""daemon/protocol 的 NDJSON 帧编解码测试（Task 5）"""

import pytest

from scrapling_fetch_mcp.daemon.protocol import (
    E_BAD_FRAME,
    E_CANCELLED,
    E_INTERNAL,
    E_UNAUTHORIZED,
    E_UNKNOWN_OP,
    OP_CANCEL,
    OP_FETCH_PAGE,
    OP_FETCH_PATTERN,
    OP_PING,
    OP_SHUTDOWN,
    OP_STATUS,
    ProtocolError,
    make_error,
    make_progress,
    make_request,
    make_response,
    parse_frame,
)


def test_request_roundtrip():
    line = make_request(OP_PING, {}, "tok", 7, "0.3.0")
    assert line.endswith(b"\n") and b"\n" not in line[:-1]   # 单行
    frame = parse_frame(line)
    assert frame["v"] == 2 and frame["op"] == "ping" and frame["token"] == "tok" and frame["id"] == 7

def test_parse_rejects_wrong_version():
    with pytest.raises(ProtocolError): parse_frame(b'{"v":1,"id":1,"op":"ping","token":"t"}')

def test_progress_and_error_frames():
    assert parse_frame(make_progress(3, 1, 2, "x"))["progress"]["total"] == 2
    err = parse_frame(make_error(3, E_CANCELLED, "bye"))
    assert err["ok"] is False and err["error"]["code"] == "cancelled"

def test_payload_with_newlines_stays_single_line():
    line = make_request(OP_FETCH_PAGE, {"url": "http://x", "mode": "basic", "content": "a\nb"}, "t", 1, "0.3.0")
    assert line.count(b"\n") == 1

def test_response_roundtrip():
    line = make_response(9, {"pong": True})
    assert line.endswith(b"\n") and b"\n" not in line[:-1]
    frame = parse_frame(line)
    assert frame["v"] == 2 and frame["id"] == 9 and frame["ok"] is True and frame["result"] == {"pong": True}

def test_request_requires_id_op_token():
    with pytest.raises(ProtocolError):
        parse_frame(b'{"v":2,"id":1,"op":"ping"}')            # 缺 token
    with pytest.raises(ProtocolError):
        parse_frame(b'{"v":2,"op":"ping","token":"t"}')       # 缺 id
    with pytest.raises(ProtocolError):
        parse_frame(b'{"v":2,"id":1,"token":"t"}')            # 缺 op
    with pytest.raises(ProtocolError):                        # 非 JSON 也归一为 ProtocolError
        parse_frame(b"not-json")

def test_request_field_types_enforced():
    """字段族命中后按类型校验：presence 检查挡不住的同值异型必须拒绝。"""
    bad_frames = [
        b'{"v":2.0,"id":1,"op":"ping","token":"t"}',   # v 浮点:JSON 侧 == 2 但类型不对
        b'{"v":true,"id":1,"op":"ping","token":"t"}',  # v 布尔是 int 子类,一并拒绝
        b'{"id":1,"op":"ping","token":"t"}',           # 无 v 键
        b'{"v":2,"id":"x","op":"ping","token":"t"}',   # id 非 int
        b'{"v":2,"id":true,"op":"ping","token":"t"}',  # id 布尔
        b'{"v":2,"id":1,"op":7,"token":"t"}',          # op 非 str
        b'{"v":2,"id":1,"op":"ping","token":9}',       # token 非 str
        b'{"v":2,"id":1,"op":"ping","token":"t","payload":"nope"}',  # payload 非 dict
        b'{"v":2,"id":1,"op":"ping","token":"t","payload":[1]}',     # payload 数组
        b'{"v":2,"payload":{}}',                       # 仅 payload 键也触发请求校验:缺 id/op/token
        b'{"v":2,"pkg":"0.3.0"}',                      # 仅 pkg 键同理
    ]
    for raw in bad_frames:
        with pytest.raises(ProtocolError, match=r""):
            parse_frame(raw)
    # 合法请求帧照常通过
    frame = parse_frame(b'{"v":2,"id":1,"op":"ping","token":"t","payload":{}}')
    assert frame["id"] == 1 and frame["payload"] == {}

def test_constants():
    assert (OP_FETCH_PAGE, OP_FETCH_PATTERN, OP_CANCEL, OP_PING, OP_STATUS, OP_SHUTDOWN) == (
        "fetch_page", "fetch_pattern", "cancel", "ping", "status", "shutdown",
    )
    assert (E_BAD_FRAME, E_UNAUTHORIZED, E_UNKNOWN_OP, E_CANCELLED, E_INTERNAL) == (
        "bad_frame", "unauthorized", "unknown_op", "cancelled", "internal",
    )
    assert issubclass(ProtocolError, ValueError)
