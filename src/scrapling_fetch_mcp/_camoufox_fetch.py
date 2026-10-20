"""Resumable downloader for the camoufox stealth browser.

camoufox 自带的 ``python -m camoufox fetch`` 把 1.2 GB 压缩包下到一次性
tempfile:请求不带读超时,连接停滞会永久挂起;失败/重启后无断点续传,
只能从头重下。本模块复用 camoufox.pkgman 的发布解析与安装原语
(:class:`camoufox.pkgman.CamoufoxFetcher`),仅替换下载环节:

- 压缩包落在 INSTALL_DIR 旁的稳定 ``.part`` 文件(按发布 URL 命名),
  重试、重启进程都从已下字节处 HTTP Range 续传;
- urlopen 的 socket 超时即停滞检测:速度归零超过 ``stall_timeout`` 秒
  判定本次尝试失败,立即从断点续传,至多 ``max_attempts`` 次;
- 服务端不支持 Range(返回 200)时自动清空 .part 从头重下;
- 下载完成后先校验 zip 中央目录再安装,校验失败丢弃 .part,留给下次
  启动从零重下,避免坏缓存永久卡死。
"""

import http.client
import io
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from zipfile import BadZipFile, ZipFile

logger = logging.getLogger("scrapling_fetch_mcp")

# 单次 socket 读(含连接建立)的停滞上限:速度归零超过该时长即重试续传
STALL_TIMEOUT = 60.0
MAX_ATTEMPTS = 10
_CHUNK = 64 * 1024
_PROGRESS_STEP = 200 * 1024 * 1024  # 下载中的日志步长


def _part_dir(install_dir: Path) -> Path:
    return install_dir.parent / f"{install_dir.name}-fetch"


def _part_path(install_dir: Path, url: str) -> Path:
    name = Path(urllib.parse.urlparse(url).path).name or "camoufox.zip"
    return _part_dir(install_dir) / f"{name}.part"


def _prune_stale_parts(part_file: Path) -> None:
    """清理其它发布遗留的 .part,防止磁盘被过期断点吃满。"""
    parent = part_file.parent
    if not parent.exists():
        return
    for stale in parent.glob("*.part"):
        if stale != part_file:
            try:
                stale.unlink()
            except OSError:
                pass


def _stream_body(resp, part: Path, have: int, progress=None) -> int:
    """把响应体追加到 part,返回新增字节数;停滞/断连在此抛异常。"""
    appended = 0
    with open(part, "ab" if have else "wb") as fh:
        while True:
            chunk = resp.read(_CHUNK)
            if not chunk:
                break
            fh.write(chunk)
            appended += len(chunk)
            if progress is not None:
                progress(have + appended)
    return appended


def _content_total(resp) -> int | None:
    """从 206/200 响应头解析总大小,拿不到返回 None。"""
    if resp.status == 206:
        content_range = resp.headers.get("Content-Range", "")
        if "/" in content_range:
            try:
                return int(content_range.rsplit("/", 1)[1])
            except ValueError:
                pass
        return None
    length = resp.headers.get("Content-Length")
    return int(length) if length else None


def download_release_zip(
    url: str,
    install_dir: Path,
    *,
    stall_timeout: float = STALL_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
) -> Path:
    """带断点续传地把 url 下到稳定 .part 文件,完成后校验 zip 完整性。"""
    part = _part_path(install_dir, url)
    part.parent.mkdir(parents=True, exist_ok=True)
    _prune_stale_parts(part)

    total: int | None = None
    last_error: Exception | None = None
    next_mark = 0

    def progress(done: int) -> None:
        nonlocal next_mark
        if done < next_mark:
            return
        if total:
            logger.info(
                "camoufox browser downloading: %.0f/%.0f MB (%d%%)",
                done / 1048576, total / 1048576, done * 100 // total,
            )
        else:
            logger.info("camoufox browser downloading: %.0f MB", done / 1048576)
        next_mark = done + _PROGRESS_STEP

    for attempt in range(1, max_attempts + 1):
        have = part.stat().st_size if part.exists() else 0
        if total is not None and have == total:
            break
        try:
            headers = {"Range": f"bytes={have}-"} if have else {}
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=stall_timeout) as resp:
                # total 必须在进入函数体读取前解析:停滞异常抛出后,
                # 已获得的 Content-Length 仍要留在本函数作用域内
                seen_total = _content_total(resp)
                if seen_total is not None:
                    total = seen_total
                if resp.status == 200 and have:
                    # 服务端不支持 Range,清空断点从头收
                    have = 0
                    open(part, "wb").close()
                appended = _stream_body(resp, part, have, progress=progress)
            logger.debug("camoufox download attempt %d: +%d bytes", attempt, appended)
        except urllib.error.HTTPError as exc:
            if exc.code == 416 and part.exists():
                # Range Not Satisfiable:断点已是完整文件,交给 zip 校验
                break
            raise
        except (OSError, http.client.HTTPException) as exc:
            last_error = exc
            have = part.stat().st_size if part.exists() else 0
            logger.warning(
                "camoufox download stalled or interrupted (%s); %.1f MB kept,"
                " retrying from resume point (%d/%d)",
                exc, have / 1048576, attempt, max_attempts,
            )
            continue
        if seen_total is None:
            # 服务端未给出总大小:干净的流结束即视为下完,完整性由 zip 校验兜底
            break

    have = part.stat().st_size if part.exists() else 0
    if total is not None and have != total:
        raise RuntimeError(
            f"camoufox download incomplete after {max_attempts} attempts:"
            f" {have}/{total} bytes ({last_error})"
        )
    try:
        with ZipFile(part) as zf:
            if not zf.infolist():
                raise BadZipFile(f"{part} has no entries")
    except BadZipFile:
        # 尺寸够但内容坏(服务端异常等):丢弃断点,下次从零重下
        part.unlink(missing_ok=True)
        raise RuntimeError(f"camoufox download is not a valid zip: {part}") from None
    return part


def install_release_zip(fetcher, install_dir: Path, zip_path: Path) -> None:
    """复用 camoufox 的清理/解压/版本标记原语落盘,成功后移除断点文件。

    仅在 zip 校验通过后调用:clean 发生在下载之后,失败的重试不会再
    破坏一个尚可使用的旧安装。
    """
    sink = io.StringIO()
    with redirect_stdout(sink), redirect_stderr(sink):
        fetcher.cleanup()
        install_dir.mkdir(parents=True, exist_ok=True)
        with open(zip_path, "rb") as fh:
            fetcher.extract_zip(fh)
        fetcher.set_version()
    # 与 camoufox 官方 install 一致的权限;zipfile 不恢复 Unix 权限位
    for member in install_dir.rglob("*"):
        if not member.is_symlink():
            os.chmod(member, 0o755)
    os.chmod(install_dir, 0o755)
    zip_path.unlink(missing_ok=True)


def fetch_camoufox_browser(
    *,
    stall_timeout: float = STALL_TIMEOUT,
    max_attempts: int = MAX_ATTEMPTS,
) -> None:
    """解析最新受支持发布 → 断点续传下载 → 安装;失败抛异常。"""
    # 延迟导入:与 _browser_check 的探测逻辑一致,camoufox 未安装时调用方
    # 根本不会走到这里
    from camoufox.pkgman import INSTALL_DIR, CamoufoxFetcher

    fetcher = CamoufoxFetcher()  # GitHub API 解析当前平台受支持的最新发布
    zip_path = download_release_zip(
        fetcher.url,
        INSTALL_DIR,
        stall_timeout=stall_timeout,
        max_attempts=max_attempts,
    )
    logger.info("camoufox browser zip complete (%s), installing...", zip_path.name)
    install_release_zip(fetcher, INSTALL_DIR, zip_path)
