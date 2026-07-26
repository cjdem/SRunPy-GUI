import re
from pathlib import Path

WEB_ROOT = Path(__file__).parents[1] / "srunpy" / "html"


def test_required_desktop_resources_exist() -> None:
    required_resources = [
        WEB_ROOT / "index.html",
        WEB_ROOT / "script.js",
        WEB_ROOT / "style.css",
        WEB_ROOT / "MiSans-Medium.ttf",
        WEB_ROOT / "favicon.png",
        WEB_ROOT / "icons" / "logo.ico",
        WEB_ROOT / "icons" / "logo.png",
        WEB_ROOT / "icons" / "journey.png",
        WEB_ROOT / "icons" / "journey_white.png",
    ]

    missing_resources = [str(resource) for resource in required_resources if not resource.is_file()]

    assert missing_resources == []


def test_local_html_and_css_references_resolve() -> None:
    html_text = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    css_text = (WEB_ROOT / "style.css").read_text(encoding="utf-8")
    referenced_paths = re.findall(
        r"(?:src|href)=[\"']\.\/([^\"']+)[\"']|url\([\"']?\.\/([^\"')]+)",
        html_text + css_text,
    )

    flattened_references = [first or second for first, second in referenced_paths]
    missing_references = [
        reference
        for reference in flattened_references
        if not (WEB_ROOT / reference).is_file()
    ]

    assert missing_references == []


def test_desktop_frontend_does_not_load_remote_resources() -> None:
    frontend_text = "\n".join(
        (WEB_ROOT / filename).read_text(encoding="utf-8")
        for filename in ("index.html", "style.css", "script.js")
    )

    assert "http://" not in frontend_text
    assert "https://" not in frontend_text


def test_javascript_cached_elements_exist_in_html() -> None:
    html_text = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script_text = (WEB_ROOT / "script.js").read_text(encoding="utf-8")
    element_array_match = re.search(
        r"const elementIds = \[(.*?)\];",
        script_text,
        flags=re.DOTALL,
    )

    assert element_array_match is not None
    cached_element_ids = re.findall(r'"([a-z0-9-]+)"', element_array_match.group(1))
    html_element_ids = set(re.findall(r'id="([a-z0-9-]+)"', html_text))

    assert set(cached_element_ids) <= html_element_ids


def test_frontend_avoids_inline_event_handlers() -> None:
    html_text = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert re.search(r"\son[a-z]+=", html_text, flags=re.IGNORECASE) is None


def test_traffic_dashboard_has_local_canvas_and_visibility_aware_polling() -> None:
    html_text = (WEB_ROOT / "index.html").read_text(encoding="utf-8")
    script_text = (WEB_ROOT / "script.js").read_text(encoding="utf-8")

    assert '<canvas id="traffic-chart">' in html_text
    assert 'data-range="recent"' in html_text
    assert 'data-range="1h"' in html_text
    assert 'data-range="5h"' in html_text
    assert 'data-range="12h"' in html_text
    assert 'data-range="24h"' in html_text
    assert 'data-range="7d"' in html_text
    assert 'document.addEventListener("visibilitychange"' in script_text
    assert "window.setTimeout(pollTrafficSnapshot" in script_text
    assert "window.devicePixelRatio" in script_text
    assert "formatAxisTime" in script_text
    assert "quadraticCurveTo" in script_text
    assert 'querySelectorAll("button[data-range]")' in script_text


def test_utility_rail_actions_have_visible_labels() -> None:
    html_text = (WEB_ROOT / "index.html").read_text(encoding="utf-8")

    assert '<span class="rail-label">仪表盘</span>' in html_text
    assert '<span class="rail-label">刷新</span>' in html_text
    assert '<span class="rail-label">自服务</span>' in html_text
    assert '<span class="rail-label">设置</span>' in html_text


def test_settings_dialog_uses_permanent_dark_green_theme() -> None:
    css_text = (WEB_ROOT / "style.css").read_text(encoding="utf-8")

    assert ".settings-dialog input[type=\"checkbox\"]" in css_text
    assert "accent-color: var(--accent);" in css_text
    assert "background: rgb(12 17 13 / 68%);" in css_text
    assert "background: rgb(41 54 46 / 92%);" in css_text
    assert ".settings-dialog .risk-critical" in css_text
