"""Browser regression tests; install Chromium with `python -m playwright install chromium`."""

import json
from urllib.parse import urlsplit

import pytest
from playwright.sync_api import expect, sync_playwright


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        yield browser
        browser.close()


@pytest.fixture
def page(browser, client, auth):
    context = browser.new_context()
    page = context.new_page()
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    def serve(route):
        request = route.request
        response = client.open(
            urlsplit(request.url).path,
            method=request.method,
            headers={**request.headers, **auth},
            data=request.post_data_buffer,
        )
        route.fulfill(
            status=response.status_code, headers=dict(response.headers), body=response.data
        )

    page.route("**/*", serve)
    yield page
    context.close()
    assert errors == []


def set_macros(app, counts):
    tabs = [
        {
            "id": f"tab-{i}",
            "label": f"グループ {i}",
            "macros": [
                {
                    "id": f"macro-{i}-{j}",
                    "label": f"ボタン {i}-{j}",
                    "steps": [{"type": "key", "value": "A"}],
                }
                for j in range(count)
            ],
        }
        for i, count in enumerate(counts)
    ]
    app.extensions["config_manager"].import_bytes(json.dumps({"version": 1, "tabs": tabs}).encode())
    return tabs


def test_home_flattens_tabs_caps_at_twelve_and_reloads_import(page, app, keyboard):
    tabs = set_macros(app, [2, 0, 4, 2, 2, 2, 2, 2, 2, 2])
    page.goto("http://keybridge.test/")
    buttons = page.locator("#macros button")
    expect(buttons).to_have_count(12)
    expect(page.locator("#tabs")).to_have_count(0)
    expect(page.locator("#macros strong")).to_have_text(
        [macro["label"] for tab in tabs for macro in tab["macros"]][:12]
    )
    expect(buttons.last).to_be_enabled()
    buttons.last.click()
    expect(page.locator("#message")).to_contain_text("送信が完了")
    assert len(keyboard.reports) == 1
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator("#file").set_input_files(
        {"name": "empty.json", "mimeType": "application/json", "buffer": b'{"version":1,"tabs":[]}'}
    )
    expect(page.locator("#message")).to_have_text("設定をインポートしました。")
    expect(buttons).to_have_count(0)
    expect(page.locator("#empty")).to_contain_text("マクロがありません")
    expect(page.locator("#macro-count")).to_have_text("0 件")


@pytest.mark.parametrize("size", [(320, 480), (390, 844), (844, 390), (480, 320)])
def test_input_tabs_fit_stay_fixed_and_follow_orientation(page, app, keyboard, size):
    set_macros(app, [100] + [2] * 9)
    width, height = size
    page.set_viewport_size({"width": width, "height": height})
    page.goto("http://keybridge.test/input")
    tabs = page.get_by_role("tab")
    expect(tabs).to_have_text(list("あかさたなはまやらわ"))
    expect(page.locator("#macros button")).to_have_count(100)
    panel = page.locator("#macro-panel")
    bar = page.get_by_role("tablist")
    expect(bar).to_have_attribute(
        "aria-orientation", "vertical" if height > width else "horizontal"
    )
    bounds = [tab.bounding_box() for tab in tabs.all()]
    panel_bounds = panel.bounding_box()
    for bounds_item in bounds:
        assert bounds_item["x"] >= 0 and bounds_item["y"] >= 0
        assert bounds_item["x"] + bounds_item["width"] <= width
        assert bounds_item["y"] + bounds_item["height"] <= height
        if height > width:
            assert bounds_item["x"] + bounds_item["width"] <= panel_bounds["x"]
        else:
            assert bounds_item["y"] + bounds_item["height"] <= panel_bounds["y"]
    assert bar.evaluate(
        "el => el.scrollWidth === el.clientWidth && el.scrollHeight === el.clientHeight"
    )
    assert page.evaluate("document.documentElement.scrollHeight <= innerHeight")
    panel.evaluate("el => { el.scrollTop = 200; }")
    assert panel.evaluate("el => el.scrollTop") == 200
    assert [tab.bounding_box() for tab in tabs.all()] == bounds
    tabs.last.click()
    expect(page.locator("#macros strong")).to_have_text(["ボタン 9-0", "ボタン 9-1"])
    page.locator("#macros button").last.click()
    expect(page.locator("#message")).to_contain_text("送信が完了")
    assert len(keyboard.reports) == 1
    tabs.first.click()
    assert panel.evaluate("el => el.scrollTop") == 200
    tabs.first.press("ArrowDown" if height > width else "ArrowRight")
    expect(tabs.nth(1)).to_have_attribute("aria-selected", "true")
    tabs.nth(1).press("End")
    expect(tabs.last).to_be_focused()
    page.set_viewport_size({"width": height, "height": width})
    expect(bar).to_have_attribute(
        "aria-orientation", "horizontal" if height > width else "vertical"
    )
    expect(tabs.last).to_have_attribute("aria-selected", "true")
    tabs.last.press("ArrowRight" if height > width else "ArrowDown")
    expect(tabs.first).to_have_attribute("aria-selected", "true")


@pytest.mark.parametrize("counts", [[], [0], [1, 0]])
def test_input_handles_fewer_or_empty_tabs(page, app, counts):
    set_macros(app, counts)
    page.goto("http://keybridge.test/input")
    expect(page.get_by_role("tab")).to_have_count(len(counts))
    if counts:
        page.get_by_role("tab").last.click()
        expect(page.locator("#empty")).to_have_text("このタブにマクロはありません。")
    else:
        expect(page.get_by_role("tablist")).to_be_hidden()
        expect(page.locator("#empty")).to_have_text("登録されているタブがありません。")
