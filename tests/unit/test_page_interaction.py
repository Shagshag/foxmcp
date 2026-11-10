"""
Tests for the page interaction tools: content_snapshot, content_click,
content_type and content_press_key

These stub the WebSocket server, so they check the request each tool builds and
how it renders the extension's answer. The events the content script dispatches
are exercised against real Firefox, where a stub could not tell a click that
opens a mousedown menu from one that does not.
"""

import base64

import pytest

import test_imports  # Automatic path setup
from server.mcp_tools import FoxMCPTools, UPLOAD_CHUNK_BYTES


class StubWebSocketServer:
    """Records the request and replays a canned response"""

    def __init__(self):
        self.sent_request = None
        self.response = {"type": "response", "data": {}}

    async def send_request_and_wait(self, request, timeout=30.0):
        self.sent_request = request
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


class TestSnapshot:

    @pytest.mark.asyncio
    async def test_lists_elements_under_the_page_title(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "title": "Form", "url": "https://example.org/form",
            "snapshot": '[r1] input "Name" (type=text)\n[r2] button "Save"'}}

        result = await call_tool("content_snapshot", profile_id=1, tab_id=4)

        assert stub_server.sent_request["profile_id"] == 1
        assert stub_server.sent_request["action"] == "content.snapshot"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "maxElements": 300, "viewportOnly": False}
        assert result.startswith("Snapshot of Form (https://example.org/form):")
        assert '[r2] button "Save"' in result


class TestWait:

    @pytest.mark.asyncio
    async def test_sends_what_to_wait_for(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "waitedMs": 420, "url": "https://example.org/done", "title": "Done"}}

        result = await call_tool("content_wait", profile_id=1, tab_id=4,
                                 selector="#ok", text="Saved", timeout=5, gone=True)

        assert stub_server.sent_request["action"] == "content.wait"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "selector": "#ok", "text": "Saved", "url": None,
            "state": "absent", "timeoutMs": 5000}
        assert result == "Ready after 420 ms: Done (https://example.org/done)"

    @pytest.mark.asyncio
    async def test_reports_a_timeout(self, call_tool, stub_server):
        stub_server.response = {"type": "error", "data": {
            "message": "Timed out after 1000 ms: it did not appear"}}

        result = await call_tool("content_wait", profile_id=1, tab_id=4, selector="#ok", timeout=1)

        assert result == "Failed to wait: Timed out after 1000 ms: it did not appear"


class TestClick:

    @pytest.mark.asyncio
    async def test_sends_the_ref(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"clicked": '[r2] button "Save"'}}

        result = await call_tool("content_click", profile_id=1, tab_id=4, ref="r2")

        assert stub_server.sent_request["action"] == "content.click"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "ref": "r2", "selector": None, "doubleClick": False}
        assert result == 'Clicked [r2] button "Save"'

    @pytest.mark.asyncio
    async def test_warns_when_the_page_did_not_react(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "clicked": '[r2] button "Save"', "reaction": "no visible reaction"}}

        result = await call_tool("content_click", profile_id=1, tab_id=4, ref="r2")

        assert result.startswith('Clicked [r2] button "Save" - the page showed no reaction')
        assert "not trusted" in result

    @pytest.mark.asyncio
    async def test_says_when_the_page_is_navigating(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "clicked": '[r2] a "Next"', "reaction": "page navigating"}}

        result = await call_tool("content_click", profile_id=1, tab_id=4, ref="r2")

        assert result == 'Clicked [r2] a "Next" - the page is navigating (content_wait for it)'

    @pytest.mark.asyncio
    async def test_double_click(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"clicked": '[r9] row "Characters"'}}

        result = await call_tool("content_click", profile_id=1, tab_id=4, ref="r9", double_click=True)

        assert stub_server.sent_request["data"]["doubleClick"] is True
        assert result == 'Double-clicked [r9] row "Characters"'

    @pytest.mark.asyncio
    async def test_requires_a_target(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="ref"):
            await call_tool("content_click", profile_id=1, tab_id=4)
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    async def test_reports_a_stale_ref(self, call_tool, stub_server):
        stub_server.response = {"type": "error", "data": {
            "message": "No element with ref r9; take a new snapshot"}}

        result = await call_tool("content_click", profile_id=1, tab_id=4, ref="r9")

        assert result == "Failed to click: No element with ref r9; take a new snapshot"


class TestType:

    @pytest.mark.asyncio
    async def test_replaces_by_default_and_can_submit(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"typed": '[r1] input "Dor"'}}

        await call_tool("content_type", profile_id=1, tab_id=4, selector="#name", text="Dor", submit=True)

        assert stub_server.sent_request["action"] == "content.type"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "ref": None, "selector": "#name",
            "text": "Dor", "clear": True, "submit": True}


class TestPressKey:

    @pytest.mark.asyncio
    async def test_targets_the_focused_element_when_none_given(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"pressed": "Escape"}}

        result = await call_tool("content_press_key", profile_id=1, tab_id=4, key="Escape")

        assert stub_server.sent_request["action"] == "content.press_key"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "key": "Escape", "ref": None, "selector": None}
        assert result == "Pressed Escape"


class TestScreenshotRegion:

    @pytest.mark.asyncio
    async def test_sends_rect_and_scale(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "dataUrl": "data:image/png;base64,AAAA", "format": "png", "quality": 90, "tabId": 4}}

        await call_tool("tabs_capture_screenshot", profile_id=1, tab_id=4,
                        x=10, y=20, width=300, height=100, scale=0.5)

        data = stub_server.sent_request["data"]
        assert data["rect"] == {"x": 10, "y": 20, "width": 300, "height": 100}
        assert data["scale"] == 0.5

    @pytest.mark.asyncio
    async def test_element_capture_sends_the_ref(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "dataUrl": "data:image/png;base64,AAAA", "format": "png", "quality": 90, "tabId": 4}}

        await call_tool("tabs_capture_screenshot", profile_id=1, tab_id=4, ref="r3", padding=2)

        data = stub_server.sent_request["data"]
        assert (data["ref"], data["selector"], data["padding"]) == ("r3", None, 2)
        assert "rect" not in data

    @pytest.mark.asyncio
    async def test_element_and_region_together_send_nothing(self, call_tool, stub_server):
        result = await call_tool("tabs_capture_screenshot", profile_id=1, ref="r3",
                                 x=0, y=0, width=10, height=10)

        assert "not both" in result
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    async def test_incomplete_region_sends_nothing(self, call_tool, stub_server):
        result = await call_tool("tabs_capture_screenshot", profile_id=1, x=10, y=20)

        assert "together" in result
        assert stub_server.sent_request is None


class TestMoreInteractions:

    @pytest.mark.asyncio
    async def test_hover(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"hovered": '[r4] a "Menu"'}}

        result = await call_tool("content_hover", profile_id=1, tab_id=4, ref="r4")

        assert stub_server.sent_request["action"] == "content.hover"
        assert stub_server.sent_request["data"] == {"tabId": 4, "ref": "r4", "selector": None}
        assert result == 'Hovered [r4] a "Menu"'

    @pytest.mark.asyncio
    async def test_drag_needs_a_drop_target(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="to_ref"):
            await call_tool("content_drag", profile_id=1, tab_id=4, ref="r1")
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    async def test_drag(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "dragged": '[r1] div "Card"', "to": '[r2] div "Done"'}}

        result = await call_tool("content_drag", profile_id=1, tab_id=4, ref="r1", to_ref="r2")

        assert stub_server.sent_request["data"] == {
            "tabId": 4, "ref": "r1", "selector": None, "toRef": "r2", "toSelector": None}
        assert result == 'Dragged [r1] div "Card" onto [r2] div "Done"'

    @pytest.mark.asyncio
    async def test_scroll_the_page(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"x": 0, "y": 640, "maxY": 2000}}

        result = await call_tool("content_scroll", profile_id=1, tab_id=4)

        assert stub_server.sent_request["data"]["direction"] == "down"
        assert result == "Scrolled to x=0, y=640 (bottom is y=2000)"

    @pytest.mark.asyncio
    async def test_scroll_rejects_an_unknown_direction(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="direction"):
            await call_tool("content_scroll", profile_id=1, tab_id=4, direction="sideways")

    @pytest.mark.asyncio
    async def test_select_option(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"selected": '[r6] select "Country"'}}

        result = await call_tool("content_select_option", profile_id=1, tab_id=4,
                                 values=["France"], selector="#country")

        assert stub_server.sent_request["data"] == {
            "tabId": 4, "ref": None, "selector": "#country", "values": ["France"]}
        assert result == 'Selected in [r6] select "Country"'

    @pytest.mark.asyncio
    async def test_fill_form_sends_every_field(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {
            "filled": ['[r1] input "Name"', '[r2] input "Agree"']}}

        result = await call_tool("content_fill_form", profile_id=1, tab_id=4, fields=[
            {"ref": "r1", "value": "Dor"}, {"selector": "#agree", "value": True}])

        assert stub_server.sent_request["data"]["fields"] == [
            {"ref": "r1", "selector": None, "value": "Dor"},
            {"ref": None, "selector": "#agree", "value": True}]
        assert result == 'Filled:\n[r1] input "Name"\n[r2] input "Agree"'

    @pytest.mark.asyncio
    async def test_fill_form_rejects_a_field_without_value(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="value"):
            await call_tool("content_fill_form", profile_id=1, tab_id=4, fields=[{"ref": "r1"}])
        assert stub_server.sent_request is None


class TestRequestFilters:

    CAPTURED = {"type": "response", "data": {"monitor_id": "m", "total_requests": 4, "requests": [
        {"url": "https://example.org/a.js", "method": "GET", "status_code": 200, "type": "script"},
        {"url": "https://example.org/api/save", "method": "POST", "status_code": 500, "type": "xmlhttprequest"},
        {"url": "https://example.org/api/list", "method": "GET", "status_code": 200, "type": "xmlhttprequest"},
        {"url": "https://example.org/b.png", "method": "GET", "status_code": 0, "type": "image",
         "error": "NS_ERROR"}]}}

    async def listed(self, call_tool, stub_server, **filters):
        stub_server.response = self.CAPTURED
        import json
        return json.loads(await call_tool(
            "requests_list_captured", profile_id=1, monitor_id="m", **filters))

    @pytest.mark.asyncio
    async def test_without_filters_nothing_is_dropped(self, call_tool, stub_server):
        data = await self.listed(call_tool, stub_server)

        assert len(data["requests"]) == 4
        assert "matched_requests" not in data

    @pytest.mark.asyncio
    async def test_filters_combine(self, call_tool, stub_server):
        data = await self.listed(call_tool, stub_server, url_contains="/api/", method="get")

        assert [r["url"] for r in data["requests"]] == ["https://example.org/api/list"]
        assert data["matched_requests"] == 1
        assert data["total_requests"] == 4

    @pytest.mark.asyncio
    async def test_failed_only_includes_errors_and_bad_statuses(self, call_tool, stub_server):
        data = await self.listed(call_tool, stub_server, failed_only=True)

        assert [r["type"] for r in data["requests"]] == ["xmlhttprequest", "image"]

    @pytest.mark.asyncio
    async def test_limit_keeps_the_newest(self, call_tool, stub_server):
        data = await self.listed(call_tool, stub_server, limit=1)

        assert [r["type"] for r in data["requests"]] == ["image"]


def jpeg(color):
    """A tiny real JPEG, for recording tests"""
    from PIL import Image
    import io
    out = io.BytesIO()
    Image.new("RGB", (8, 6), color).save(out, "JPEG")
    return out.getvalue()


class FrameServer:
    """Plays the extension's recording requests with canned frames"""

    def __init__(self, frames):
        self.frames = frames
        self.actions = []

    async def send_request_and_wait(self, request, timeout=30.0):
        self.actions.append(request["action"])
        action = request["action"]
        if action == "tabs.record_start":
            return {"type": "response", "data": {"recordingId": "rec-4", "intervalMs": 500, "maxFrames": 60}}
        if action == "tabs.record_stop":
            return {"type": "response", "data": {"frames": len(self.frames), "error": None}}
        if action == "tabs.record_frame":
            data = self.frames[request["data"]["index"]]
            url = "data:image/jpeg;base64," + base64.b64encode(data).decode("ascii")
            return {"type": "response", "data": {"dataUrl": url, "delayMs": 500}}
        return {"type": "response", "data": {"discarded": True}}


class TestRecording:

    @pytest.fixture
    def record(self):
        pytest.importorskip("PIL")

        def make(frames):
            server = FrameServer(frames)
            tools = FoxMCPTools(server)

            async def call(name, **kwargs):
                tool = await tools.mcp.get_tool(name)
                return await tool.fn(**kwargs)
            return server, call
        return make

    @pytest.mark.asyncio
    async def test_start_sends_the_settings(self, record):
        server, call = record([])
        stub = StubWebSocketServer()
        stub.response = {"type": "response", "data": {"recordingId": "rec-4", "intervalMs": 250, "maxFrames": 10}}
        tools = FoxMCPTools(stub)
        tool = await tools.mcp.get_tool("tabs_record_start")

        result = await tool.fn(profile_id=1, tab_id=4, interval_ms=250, max_frames=10)

        assert stub.sent_request["action"] == "tabs.record_start"
        assert stub.sent_request["data"] == {
            "tabId": 4, "intervalMs": 250, "maxFrames": 10, "scale": 0.5, "quality": 50}
        assert result == "Recording tab 4 as rec-4: a frame every 250 ms, up to 10 frames"

    @pytest.mark.asyncio
    async def test_stop_builds_a_gif_and_merges_repeats(self, record, tmp_path):
        from PIL import Image
        red, blue = jpeg("red"), jpeg("blue")
        server, call = record([red, red, blue])
        target = tmp_path / "out" / "demo"

        result = await call("tabs_record_stop", profile_id=1, recording_id="rec-4", filename=str(target))

        gif = tmp_path / "out" / "demo.gif"
        assert gif.exists()
        assert "3 frame(s) (2 distinct)" in result
        with Image.open(gif) as image:
            assert image.n_frames == 2
        assert server.actions == ["tabs.record_stop", "tabs.record_frame", "tabs.record_frame",
                                  "tabs.record_frame", "tabs.record_discard"]

    @pytest.mark.asyncio
    async def test_without_pillow_frames_are_saved_as_files(self, record, tmp_path, monkeypatch):
        import sys
        server, call = record([jpeg("red"), jpeg("blue")])
        monkeypatch.setitem(sys.modules, "PIL", None)

        result = await call("tabs_record_stop", profile_id=1, recording_id="rec-4",
                            filename=str(tmp_path / "demo.gif"))

        assert "Pillow is not installed" in result
        assert sorted(p.name for p in (tmp_path / "demo").iterdir()) == ["frame-000.jpg", "frame-001.jpg"]


class TestConsole:

    @pytest.mark.asyncio
    async def test_first_call_only_starts_recording(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"started": True, "entries": []}}

        result = await call_tool("content_read_console", profile_id=1, tab_id=4)

        assert stub_server.sent_request["action"] == "content.console"
        assert stub_server.sent_request["data"] == {
            "tabId": 4, "level": None, "pattern": None, "limit": 50, "clear": False}
        assert result.startswith("Console recording started")

    @pytest.mark.asyncio
    async def test_lists_entries_with_their_level(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"started": False, "entries": [
            {"level": "error", "message": "boom"}, {"level": "uncaught", "message": "x is not defined"}]}}

        result = await call_tool("content_read_console", profile_id=1, tab_id=4, level="error")

        assert result == "[error] boom\n[uncaught] x is not defined"

    @pytest.mark.asyncio
    async def test_level_is_checked(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="level"):
            await call_tool("content_read_console", profile_id=1, tab_id=4, level="loud")


class TestDialogsAndDownloads:

    @pytest.mark.asyncio
    async def test_dialog_handling_lists_what_was_answered(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"mode": "accept", "dialogs": [
            {"type": "confirm", "message": "Delete?", "accepted": True}]}}

        result = await call_tool("content_handle_dialogs", profile_id=1, tab_id=4, mode="accept")

        assert stub_server.sent_request["data"] == {
            "tabId": 4, "mode": "accept", "promptText": None}
        assert result == "Dialog handling: accept\n- confirm (accepted): Delete?"

    @pytest.mark.asyncio
    async def test_dialog_mode_is_checked(self, call_tool, stub_server):
        with pytest.raises(ValueError, match="mode"):
            await call_tool("content_handle_dialogs", profile_id=1, tab_id=4, mode="maybe")

    @pytest.mark.asyncio
    async def test_list_downloads(self, call_tool, stub_server):
        stub_server.response = {"type": "response", "data": {"downloads": [{
            "id": 7, "filename": "C:\\Users\\x\\Downloads\\export.csv", "state": "complete",
            "bytes": 120, "url": "https://example.org/export.csv", "error": None}]}}

        result = await call_tool("content_list_downloads", profile_id=1, limit=3)

        assert stub_server.sent_request["action"] == "content.list_downloads"
        assert stub_server.sent_request["data"] == {"limit": 3}
        assert result == ("- [7] C:\\Users\\x\\Downloads\\export.csv (complete, 120 bytes) "
                          "from https://example.org/export.csv")

    @pytest.mark.asyncio
    async def test_wait_for_a_download_that_never_comes(self, call_tool, stub_server):
        stub_server.response = {"type": "error", "data": {
            "message": "No download finished within 1000 ms"}}

        result = await call_tool("content_wait_download", profile_id=1, timeout=1)

        assert stub_server.sent_request["data"] == {"timeoutMs": 1000}
        assert result == "Failed to wait for a download: No download finished within 1000 ms"


class RecordingWebSocketServer:
    """Records every request; answers capture and finish the way the extension does"""

    def __init__(self):
        self.requests = []

    async def send_request_and_wait(self, request, timeout=30.0):
        self.requests.append(request)
        if request["action"] == "content.capture_file_input":
            return {"type": "response", "data": {"ref": "r7", "multiple": False, "directory": True}}
        if request["action"] == "content.upload_finish":
            return {"type": "response", "data": {
                "count": 2, "paths": ["Assets/a.txt", "Assets/sub/b.bin"], "target": "[r7] input"}}
        return {"type": "response", "data": {"ok": True}}

    def actions(self):
        return [r["action"] for r in self.requests]


class TestUploadFiles:

    @pytest.fixture
    def recorder(self):
        return RecordingWebSocketServer()

    @pytest.fixture
    def upload(self, recorder):
        tools = FoxMCPTools(recorder)

        async def call(**kwargs):
            tool = await tools.mcp.get_tool("content_upload_files")
            return await tool.fn(**kwargs)

        return call

    @pytest.fixture
    def folder(self, tmp_path):
        root = tmp_path / "Assets"
        (root / "sub").mkdir(parents=True)
        (root / "a.txt").write_text("alpha")
        (root / "sub" / "b.bin").write_bytes(b"\x00" * (UPLOAD_CHUNK_BYTES + 10))
        return root

    @pytest.mark.asyncio
    async def test_folder_files_keep_paths_under_the_folder_name(self, upload, recorder, folder):
        await upload(profile_id=1, tab_id=4, path=str(folder), ref="r2")

        begin = recorder.requests[0]
        assert begin["action"] == "content.upload_begin"
        assert begin["data"]["files"] == [
            {"name": "a.txt", "relativePath": "Assets/a.txt"},
            {"name": "b.bin", "relativePath": "Assets/sub/b.bin"}]

    @pytest.mark.asyncio
    async def test_large_files_are_split_into_chunks(self, upload, recorder, folder):
        await upload(profile_id=1, tab_id=4, path=str(folder), ref="r2")

        chunks = [r["data"] for r in recorder.requests if r["action"] == "content.upload_chunk"]
        assert [c["fileIndex"] for c in chunks] == [0, 1, 1]
        sizes = [len(base64.b64decode(c["data"])) for c in chunks]
        assert sizes == [5, UPLOAD_CHUNK_BYTES, 10]
        finish = recorder.requests[-1]
        assert finish["action"] == "content.upload_finish"
        assert finish["data"]["ref"] == "r2"

    @pytest.mark.asyncio
    async def test_trigger_fills_the_input_it_opens(self, upload, recorder, folder):
        result = await upload(profile_id=1, tab_id=4, path=str(folder), trigger_ref="r5")

        assert recorder.actions()[0] == "content.capture_file_input"
        assert recorder.requests[0]["data"]["triggerRef"] == "r5"
        assert recorder.requests[-1]["data"]["ref"] == "r7"
        assert result.startswith("Set 2 file(s) on [r7] input")

    @pytest.mark.asyncio
    async def test_single_file_has_no_relative_path(self, upload, recorder, folder):
        await upload(profile_id=1, tab_id=4, path=str(folder / "a.txt"), selector="#plain")

        assert recorder.requests[0]["data"]["files"] == [{"name": "a.txt", "relativePath": ""}]

    @pytest.mark.asyncio
    async def test_missing_path_sends_nothing(self, upload, recorder, tmp_path):
        result = await upload(profile_id=1, tab_id=4, path=str(tmp_path / "nope"), ref="r2")

        assert result.endswith("does not exist")
        assert recorder.requests == []
