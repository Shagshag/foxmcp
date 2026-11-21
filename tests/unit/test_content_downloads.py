"""Tests for content_list_downloads and content_watch_download"""

import json
from pathlib import Path

import pytest

import test_imports  # Automatic path setup
from server.mcp_tools import FoxMCPTools


class StubWebSocketServer:
    """Records the request and replays a canned response"""

    def __init__(self):
        self.sent_request = None
        self.timeout = None
        self.response = {"type": "response", "data": {}}

    async def send_request_and_wait(self, request, timeout=30.0):
        self.sent_request = request
        self.timeout = timeout
        return self.response


@pytest.fixture
def stub_server():
    return StubWebSocketServer()


@pytest.fixture
def call_tool(stub_server):
    tools = FoxMCPTools(stub_server)

    async def call(name, **kwargs):
        tool = await tools.mcp.get_tool(name)
        return await tool.fn(**kwargs)

    return call


EXPORT = {"id": 7, "filename": "/home/u/Downloads/export.csv", "state": "complete",
          "bytes": 120, "url": "https://example.org/export.csv", "error": None}


class TestListDownloads:

    @pytest.mark.asyncio
    async def test_lists_the_saved_files(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"downloads": [EXPORT]}}

        result = await call_tool("content_list_downloads", profile_id=1, limit=3)

        assert stub_server.sent_request["action"] == "content.list_downloads"
        assert stub_server.sent_request["data"] == {"limit": 3}
        assert result == ("- [7] /home/u/Downloads/export.csv (complete, 120 bytes) "
                          "from https://example.org/export.csv")

    @pytest.mark.asyncio
    async def test_says_when_there_are_none(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"downloads": []}}

        assert await call_tool("content_list_downloads", profile_id=1) == "No downloads"

    @pytest.mark.asyncio
    async def test_failed_downloads_show_their_error(self, call_tool, stub_server):
        failed = {**EXPORT, "state": "interrupted", "error": "NETWORK_FAILED"}
        stub_server.response = {"type": "response", "data": {"downloads": [failed]}}

        result = await call_tool("content_list_downloads", profile_id=1)

        assert result.endswith(" - error: NETWORK_FAILED")


class TestWatchDownload:

    @pytest.mark.asyncio
    async def test_registers_the_watch_and_says_where_the_outcome_goes(
            self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "watchId": "watch-1", "callbackUrl": "http://127.0.0.1:8099/", "timeoutMs": 60000}}

        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/")

        assert stub_server.sent_request["action"] == "content.watch_download"
        assert stub_server.sent_request["data"] == {
            "callbackUrl": "http://127.0.0.1:8099/", "timeoutMs": 60000}
        assert "watch-1" in result
        assert "http://127.0.0.1:8099/" in result

    @pytest.mark.asyncio
    async def test_returns_without_waiting_for_the_download(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "watchId": "watch-1", "callbackUrl": "http://127.0.0.1:8099/", "timeoutMs": 5000}}

        await call_tool("content_watch_download", profile_id=1,
                        callback_url="http://127.0.0.1:8099/", timeout=5)

        # The request is answered when the watch is registered, so no long wait is needed.
        assert stub_server.timeout <= 30.0
        assert stub_server.sent_request["data"]["timeoutMs"] == 5000

    @pytest.mark.asyncio
    async def test_passes_a_download_id(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "watchId": "watch-1", "callbackUrl": "http://127.0.0.1:8099/", "timeoutMs": 60000}}

        await call_tool("content_watch_download", profile_id=1,
                        callback_url="http://127.0.0.1:8099/", download_id=7)

        assert stub_server.sent_request["data"]["downloadId"] == 7
        assert "urlContains" not in stub_server.sent_request["data"]

    @pytest.mark.asyncio
    async def test_passes_a_url_filter(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "watchId": "watch-1", "callbackUrl": "http://127.0.0.1:8099/", "timeoutMs": 60000}}

        await call_tool("content_watch_download", profile_id=1,
                        callback_url="http://127.0.0.1:8099/", url_contains="export.csv")

        assert stub_server.sent_request["data"]["urlContains"] == "export.csv"
        assert "downloadId" not in stub_server.sent_request["data"]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("callback_url", [
        "http://localhost:8099/done", "https://127.0.0.1/", "http://[::1]:8099/"])
    async def test_accepts_a_receiver_on_this_machine(self, call_tool, stub_server, callback_url):
        stub_server.response = {"type": "response", "data": {
            "watchId": "watch-1", "callbackUrl": callback_url, "timeoutMs": 60000}}

        result = await call_tool("content_watch_download", profile_id=1, callback_url=callback_url)

        assert result.startswith("Watching for a download")
        assert stub_server.sent_request["data"]["callbackUrl"] == callback_url

    @pytest.mark.asyncio
    async def test_extension_rejection_is_reported(self, call_tool, stub_server):
        stub_server.response = {"type": "error", "data": {
            "code": "INVALID_PARAMETER", "message": "No download with downloadId 9"}}

        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/", download_id=9)

        assert result == "Failed to watch for a download: No download with downloadId 9"


class TestArguments:

    @pytest.mark.asyncio
    @pytest.mark.parametrize("limit", [0, -1, 101, True, 2.5, "3"])
    async def test_limit_must_be_an_integer_from_1_to_100(self, call_tool, stub_server, limit):
        result = await call_tool("content_list_downloads", profile_id=1, limit=limit)

        assert result == "Failed to list downloads: limit must be an integer from 1 to 100"
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("callback_url", [
        "https://example.org/done", "http://192.168.1.5:8099/", "ftp://127.0.0.1/",
        "http://user:secret@127.0.0.1:8099/", "http://127.0.0.1:port/", "not a url", "", 5, None])
    async def test_callback_must_be_a_local_web_address(self, call_tool, stub_server, callback_url):
        result = await call_tool("content_watch_download", profile_id=1, callback_url=callback_url)

        assert result.startswith("Failed to watch for a download: callback_url ")
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("timeout", [0, -5, 3601, True, "5", float("nan"), float("inf")])
    async def test_timeout_must_be_above_zero_and_at_most_3600(
            self, call_tool, stub_server, timeout):
        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/", timeout=timeout)

        assert result == ("Failed to watch for a download: "
                          "timeout must be a number above 0 and at most 3600")
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("download_id", [-1, True, 2.5, "7"])
    async def test_download_id_must_be_a_non_negative_integer(
            self, call_tool, stub_server, download_id):
        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/", download_id=download_id)

        assert result == "Failed to watch for a download: download_id must be a non-negative integer"
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("url_contains", ["", 5, "x" * 2049])
    async def test_url_filter_must_be_a_short_text(self, call_tool, stub_server, url_contains):
        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/", url_contains=url_contains)

        assert result == ("Failed to watch for a download: "
                          "url_contains must be a string of 1 to 2048 characters")
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    async def test_the_two_filters_are_exclusive(self, call_tool, stub_server):
        result = await call_tool("content_watch_download", profile_id=1,
                                 callback_url="http://127.0.0.1:8099/",
                                 download_id=1, url_contains="export")

        assert result == ("Failed to watch for a download: "
                          "download_id and url_contains cannot be used together")
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    async def test_extension_rejection_is_reported(self, call_tool, stub_server):
        stub_server.response = {"type": "error", "data": {
            "code": "INVALID_PARAMETER", "message": "limit must be an integer from 1 to 100"}}

        result = await call_tool("content_list_downloads", profile_id=1)

        assert result == "Failed to list downloads: limit must be an integer from 1 to 100"


def test_manifest_asks_for_the_downloads_permission():
    manifest = json.loads(
        (Path(__file__).resolve().parents[2] / "extension/manifest.json").read_text())

    assert "downloads" in manifest["permissions"]