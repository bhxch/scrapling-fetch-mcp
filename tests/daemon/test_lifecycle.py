"""daemon/lifecycle 生命周期测试（Task 6）。

覆盖：socket 命名、daemon_dir 解析、is_alive 三态（无 lock/pid 死/身份
不符）、ping 往返、ensure_daemon 拉起+复用+spawn 仲裁+陈旧防御+启动即崩
检测、win32 拒绝、daemon_sockets 清点。

spawn 类测试经 ``spawn_fake_daemon`` fixture 把 ``lifecycle._DAEMON_MODULE``
注入为 ``tests.daemon.fake_worker``（假 worker 与真 worker 同 lock/ping
契约）；假 worker 需要知道期望 hash，由测试经 spawn_env 传
``SCRAPLING_DAEMON_CONFIG_HASH``（ensure_daemon 原样并入子进程 env）。
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from scrapling_fetch_mcp.daemon import lifecycle
from scrapling_fetch_mcp.daemon.lifecycle import (
    daemon_sockets,
    ensure_daemon,
    is_alive,
    ping,
    socket_name,
)
from scrapling_fetch_mcp.daemon.paths import daemon_dir, pkg_version

from . import fake_worker

REPO_ROOT = Path(__file__).resolve().parents[2]

# 假 worker 从该 spawn_env 键读取期望 hash（真 worker 不消费此键,自算 hash）。
CONFIG_HASH_KEY = "SCRAPLING_DAEMON_CONFIG_HASH"


def _reset_daemon_config() -> None:
    """重置配置单例的 daemon 字段后从 env 重新加载（沿用 tests/test_config.py 手法）。"""
    from scrapling_fetch_mcp._config import Config, init_config_from_env

    cfg = Config()  # Config.__new__ 返回单例,改它即改全局
    cfg._daemon_dir = None
    cfg._daemon_idle_timeout = 600.0
    init_config_from_env()


@pytest.fixture
def daemon_env(monkeypatch, tmp_path):
    """daemon 目录钉到 tmp_path：setenv + 单例重置（前后各一次防泄漏）。

    teardown 必须先撤 env 再重置单例——重置会执行 init_config_from_env，
    若 env 未撤会把 tmp 路径重新写进单例，泄漏给后续测试。
    """
    monkeypatch.setenv("SCRAPLING_DAEMON_DIR", str(tmp_path))
    _reset_daemon_config()
    yield tmp_path
    monkeypatch.delenv("SCRAPLING_DAEMON_DIR", raising=False)
    _reset_daemon_config()


@pytest.fixture
def spawn_fake_daemon(monkeypatch, daemon_env):
    """在 daemon_env 之上把 spawn 目标换成假 worker,并在用例结束后收尸。"""
    monkeypatch.setattr(lifecycle, "_DAEMON_MODULE", "tests.daemon.fake_worker")
    # spawn 的 cwd="/" 且假 worker 属 tests 包(不在 site-packages),须显式给 PYTHONPATH
    monkeypatch.setenv("PYTHONPATH", str(REPO_ROOT))
    yield daemon_env
    for lock in daemon_env.glob("daemon-*.lock"):
        try:
            pid = json.loads(lock.read_text(encoding="utf-8"))["pid"]
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            continue
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                break
            # 退出的子进程若未被收尸是僵尸态,kill(pid,0) 仍成功;以 waitpid 为准
            try:
                if os.waitpid(pid, os.WNOHANG)[0] == pid:
                    break
            except ChildProcessError:
                break  # 非本进程子进程:SIGTERM 已发,由其自行退出
            time.sleep(0.05)


class Responder:
    """进程内最小 ping 应答器（复用 fake_worker.handle_frame,应答同构）。

    自写 lock（pid 指向本进程=活着的）供 is_alive 读 token。
    """

    def __init__(self, sock: Path, config_hash: str, token: str = "tok"):
        self.sock = sock
        self.config_hash = config_hash
        self.token = token
        self._stop = threading.Event()
        if sock.exists():
            sock.unlink()
        self._srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._srv.bind(str(sock))
        self._srv.listen(5)
        self._srv.settimeout(0.05)
        sock.with_suffix(".lock").write_text(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "token": token,
                    "pkg": pkg_version(),
                    "config_hash": config_hash,
                    "sock": str(sock),
                }
            ),
            encoding="utf-8",
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                conn, _ = self._srv.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                conn.settimeout(1.0)
                buf = b""
                while True:
                    try:
                        chunk = conn.recv(65536)
                    except (socket.timeout, OSError):
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\n" in buf:
                        line, buf = buf.split(b"\n", 1)
                        conn.sendall(fake_worker.handle_frame(line, self.config_hash))

    def __enter__(self) -> "Responder":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def close(self) -> None:
        self._stop.set()
        self._thread.join(timeout=2)
        self._srv.close()
        for path in (self.sock, self.sock.with_suffix(".lock")):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


# ---------- 命名与目录 ----------

def test_socket_name_embeds_version_and_hash():
    name = socket_name("ab12cd34")
    assert name.startswith("daemon-") and name.endswith("-ab12cd34") and ".sock" not in name


def test_daemon_dir_env_override_and_mkdir(daemon_env):
    d = daemon_dir()
    assert d == Path(os.environ["SCRAPLING_DAEMON_DIR"]) and d.is_dir()


def test_daemon_dir_defaults_to_platformdirs(monkeypatch, tmp_path):
    monkeypatch.delenv("SCRAPLING_DAEMON_DIR", raising=False)
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))  # linux 下钉住 platformdirs 落点
    _reset_daemon_config()
    from platformdirs import user_data_dir

    d = daemon_dir()
    assert d == Path(user_data_dir("scrapling-fetch-mcp")) and d.is_dir()


def test_daemon_sockets_lists_named_sockets(daemon_env):
    d = daemon_dir()
    (d / "daemon-0.2.0-aaaa.sock").touch()
    (d / "daemon-0.2.0-bbbb.sock").touch()
    (d / "daemon-0.2.0-aaaa.lock").touch()  # 非 .sock 后缀不收
    (d / "other.sock").touch()  # 非 daemon- 前缀不收
    assert daemon_sockets() == sorted([d / "daemon-0.2.0-aaaa.sock", d / "daemon-0.2.0-bbbb.sock"])


# ---------- is_alive / ping ----------

def test_is_alive_false_on_missing_lock(tmp_path):
    assert is_alive(tmp_path / "nope.sock", "0.3.0", "ab12cd34") is False


def test_is_alive_false_on_dead_pid(tmp_path):
    gone = subprocess.Popen([sys.executable, "-c", "import sys; sys.exit(0)"])
    gone.wait()  # pid 已死
    with Responder(tmp_path / "r.sock", "ab12cd34") as r:
        lock = r.sock.with_suffix(".lock")
        lock.write_text(lock.read_text(encoding="utf-8").replace(f'"pid": {os.getpid()}', f'"pid": {gone.pid}'), encoding="utf-8")
        assert is_alive(r.sock, pkg_version(), "ab12cd34") is False


def test_is_alive_false_on_identity_mismatch(tmp_path):
    with Responder(tmp_path / "r.sock", "deadbeef") as r:
        assert is_alive(r.sock, pkg_version(), "ab12cd34") is False  # 自报 hash 不符


def test_is_alive_true_on_matching_identity(tmp_path):
    with Responder(tmp_path / "r.sock", "ab12cd34") as r:
        assert is_alive(r.sock, pkg_version(), "ab12cd34") is True


def test_ping_roundtrip_and_missing_sock(tmp_path):
    with Responder(tmp_path / "r.sock", "cafe1234", token="tok") as r:
        resp = ping(r.sock, "tok")
        assert resp is not None and resp["ok"] is True
        assert resp["result"]["config_hash"] == "cafe1234"
    assert ping(tmp_path / "ghost.sock", "tok") is None  # 不存在的 socket → None


# ---------- ensure_daemon ----------

def test_ensure_daemon_rejects_windows(monkeypatch, daemon_env):
    monkeypatch.setattr(lifecycle.sys, "platform", "win32")
    with pytest.raises(RuntimeError):
        ensure_daemon({}, "ab12cd34")


def test_ensure_daemon_spawns_and_reuses(spawn_fake_daemon):
    d = spawn_fake_daemon
    env, h = {CONFIG_HASH_KEY: "ab12cd34", "SCRAPLING_DAEMON_IDLE_TIMEOUT": "60"}, "ab12cd34"
    sock1 = ensure_daemon(env, h, timeout=30)
    assert sock1.exists()
    assert sock1.name == f"{socket_name(h)}.sock"
    pid1 = json.loads(sock1.with_suffix(".lock").read_text(encoding="utf-8"))["pid"]
    sock2 = ensure_daemon(env, h, timeout=30)  # 第二次复用,不新起
    assert sock2 == sock1
    assert json.loads(sock2.with_suffix(".lock").read_text(encoding="utf-8"))["pid"] == pid1
    # 只拉起过一个实例(journal 单行),仲裁锁用后即清
    assert (d / f"{socket_name(h)}.journal").read_text(encoding="utf-8").split() == [str(pid1)]
    assert not (d / f"{socket_name(h)}.spawn.lock").exists()


def test_ensure_daemon_concurrent_spawn_arbitration(spawn_fake_daemon):
    d = spawn_fake_daemon
    env, h = {CONFIG_HASH_KEY: "ab12cd34"}, "ab12cd34"
    barrier = threading.Barrier(2)
    results: list = []
    errors: list = []

    def run():
        barrier.wait()
        try:
            results.append(ensure_daemon(env, h, timeout=30))
        except Exception as exc:  # noqa: BLE001  收集到断言里
            errors.append(exc)

    threads = [threading.Thread(target=run) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=40)
    assert errors == []
    assert results[0] == results[1]
    # O_EXCL 仲裁:并发双方只应有一个真正 spawn
    journal = (d / f"{socket_name(h)}.journal").read_text(encoding="utf-8").split()
    assert len(journal) == 1
    assert not (d / f"{socket_name(h)}.spawn.lock").exists()


def test_stale_socket_with_wrong_hash_is_respawned(spawn_fake_daemon):
    d = spawn_fake_daemon
    h = "ffffff11"
    name = socket_name(h)
    stale_sock = d / f"{name}.sock"
    stale_sock.write_text("not a socket")  # 伪造 sock:连接必失败 → is_alive False
    (d / f"{name}.lock").write_text(
        json.dumps(
            {
                "pid": os.getpid(),  # 活着的 pid,但 ping 失败 → 陈旧
                "token": "stale",
                "pkg": pkg_version(),
                "config_hash": "deadbeef",  # 自报 hash 与期望不符
                "sock": str(stale_sock),
            }
        ),
        encoding="utf-8",
    )
    sock = ensure_daemon({CONFIG_HASH_KEY: h}, h, timeout=30)
    assert json.loads(sock.with_suffix(".lock").read_text(encoding="utf-8"))["config_hash"] == h


def test_ensure_daemon_raises_when_worker_dies_at_boot(spawn_fake_daemon):
    d = spawn_fake_daemon
    env = {CONFIG_HASH_KEY: "ab12cd34", "SCRAPLING_FAKE_WORKER_FAIL": "1"}
    with pytest.raises(TimeoutError):
        ensure_daemon(env, "ab12cd34", timeout=10)
    # 进程的 stdout/stderr 落在 <name>.log,仲裁锁在 finally 中释放
    assert "模拟启动失败" in (d / f"{socket_name('ab12cd34')}.log").read_text(encoding="utf-8")
    assert not (d / f"{socket_name('ab12cd34')}.spawn.lock").exists()
