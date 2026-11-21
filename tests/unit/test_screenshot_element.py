"""Tests for capturing one element of a tab by ref or selector"""

import pytest

import test_imports  # Automatic path setup
from server.mcp_tools import FoxMCPTools


from test_screenshot_filename import StubScreenshotServer


@pytest.fixture
def stub_server():
    server = StubScreenshotServer()
    yield server
    server.file_transfers.close()


@pytest.fixture
def capture(stub_server):
    tools = FoxMCPTools(stub_server, file_transfers=stub_server.file_transfers)

    async def call(**kwargs):
        tool = await tools.mcp.get_tool("tabs_capture_screenshot")
        return await tool.fn(**kwargs)

    return call


class TestElementCapture:

    @pytest.mark.asyncio
    async def test_the_ref_and_padding_reach_the_extension(self, capture, stub_server):
        await capture(profile_id=1, tab_id=4, ref="r3", padding=2)

        data = stub_server.sent_request["data"]
        assert (data["ref"], data["selector"], data["padding"]) == ("r3", None, 2)
        assert "rect" not in data

    @pytest.mark.asyncio
    async def test_a_selector_is_sent_without_a_ref(self, capture, stub_server):
        await capture(profile_id=1, selector="#chart")

        data = stub_server.sent_request["data"]
        assert (data["ref"], data["selector"]) == (None, "#chart")
        assert "padding" not in data

    @pytest.mark.asyncio
    async def test_an_element_and_a_region_together_send_nothing(self, capture, stub_server):
        result = await capture(profile_id=1, ref="r3", x=0, y=0, width=10, height=10)

        assert "not both" in result
        assert stub_server.sent_request is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("padding", [-1, True, "2", float("nan"), float("inf")])
    async def test_padding_must_be_a_number_of_zero_or_more(self, capture, stub_server, padding):
        result = await capture(profile_id=1, ref="r3", padding=padding)

        assert "padding must be a number of 0 or more" in result
        assert stub_server.sent_request is None
