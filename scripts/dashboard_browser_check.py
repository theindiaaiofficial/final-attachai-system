"""Real Chromium/API E2E on an isolated database; only external model adapters are faked.

Run: python scripts/dashboard_browser_check.py
Requires requirements-dev.txt and `python -m playwright install chromium`.
"""
from __future__ import annotations

import json
import secrets
import socket
import sys
import tempfile
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

import httpx
import uvicorn
from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import main  # noqa: E402
from app.config import Settings  # noqa: E402


class OfflineEmbeddings:
    async def embed_documents(self, texts):
        return [[1.0] + [0.0] * 767 for _ in texts]


async def offline_completion(*args, **kwargs):
    return 'Hello from Orbit. <img src=x onerror="window.__injected=true">'


def run():
    shots = ROOT / "docs" / "screenshots"
    shots.mkdir(parents=True, exist_ok=True)
    outcomes = []
    with tempfile.TemporaryDirectory(prefix="orbit-dashboard-e2e-") as temporary:
        admin_key = secrets.token_urlsafe(32)
        settings = Settings(_env_file=None, APP_ENV="test", ADMIN_API_KEY=admin_key,
                            DATABASE_PROVIDER="sqlite", STORAGE_PROVIDER="local", VECTOR_PROVIDER="sqlite",
                            SQLITE_PATH=Path(temporary) / "browser.db", LOCAL_STORAGE_PATH=Path(temporary) / "storage",
                            ROUTER_PROVIDER="openai", ROUTER_MODEL="test-router", ANSWER_PROVIDER="openai", ANSWER_MODEL="test-answer")
        main.get_settings = lambda: settings
        original_lifespan = main.app.router.lifespan_context

        @asynccontextmanager
        async def lifespan(app):
            async with original_lifespan(app):
                app.state.state.knowledge.embeddings = OfflineEmbeddings()
                app.state.state.llm.complete = offline_completion
                yield

        main.app.router.lifespan_context = lifespan
        with socket.socket() as reserved:
            reserved.bind(("127.0.0.1", 0))
            port = reserved.getsockname()[1]
        url = f"http://127.0.0.1:{port}"
        server = uvicorn.Server(uvicorn.Config(main.app, host="127.0.0.1", port=port, log_level="error", access_log=False))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        for _ in range(100):
            try:
                if httpx.get(url + "/health").status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(.1)
        else:
            raise RuntimeError("Browser check server did not start")
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch()
                context = browser.new_context(viewport={"width": 1440, "height": 1050})
                page = context.new_page()
                errors = []
                page.on("pageerror", lambda error: errors.append(error.stack))

                def check(label):
                    if errors:
                        raise AssertionError(f"JavaScript errors: {errors}")
                    outcomes.append({"check": label, "result": "PASS"})

                def screenshot(name):
                    page.evaluate("document.getElementById('toasts')?.replaceChildren()")
                    page.screenshot(path=str(shots / name), full_page=True)

                def go(key, title):
                    page.goto(url + "/admin#" + key)
                    expect(page.locator("#content h1")).to_have_text(title)
                    expect(page.get_by_text("We couldn’t load this page")).to_have_count(0)

                page.goto(url + "/admin")
                expect(page).to_have_url(url + "/admin/login")
                screenshot("login.png")
                page.get_by_label("Admin API key").fill("wrong")
                page.get_by_role("button", name="Sign in to Orbit").click()
                expect(page.get_by_role("alert")).to_contain_text("Invalid")
                page.get_by_label("Admin API key").fill(admin_key)
                page.get_by_role("button", name="Sign in to Orbit").click()
                page.wait_for_url(url + "/admin#overview")
                page.wait_for_timeout(400)
                if errors:
                    raise AssertionError(f"Dashboard JavaScript failed to initialize: {errors}")
                expect(page.locator("#content h1")).to_have_text("Overview")
                check("Login rejection, session creation, protected shell")
                screenshot("overview-empty.png")

                go("clients", "Clients")
                page.get_by_role("button", name="Create client", exact=True).first.click()
                form = page.get_by_role("dialog", name="Create a client")
                form.get_by_label("Client name").fill("Dashboard verification")
                form.get_by_label("URL slug").fill("dashboard-verification")
                form.get_by_label("Allowed website origins").fill(url)
                form.get_by_label("Assistant name", exact=True).fill("Orbit QA")
                form.get_by_role("button", name="Create client", exact=True).click()
                key_box = page.get_by_role("dialog", name="Save your client API key")
                expect(key_box).to_be_visible()
                public_key = key_box.get_by_label("One-time API key").input_value()
                assert public_key.startswith("orb_")
                key_box.get_by_role("button", name="Close", exact=True).click()
                expect(page.get_by_text("Dashboard verification", exact=True)).to_be_visible()
                check("Create client with one-time API key and persisted list")

                page.get_by_role("button", name="Manage", exact=True).click()
                page.get_by_role("dialog").get_by_role("button", name="Edit", exact=True).click()
                edit = page.get_by_role("dialog", name="Edit client")
                edit.get_by_label("Assistant system prompt").fill("Use only tenant knowledge. Be clear and helpful.")
                edit.get_by_role("button", name="Save client", exact=True).click()
                expect(edit).not_to_be_visible()
                page.get_by_role("button", name="Manage", exact=True).click()
                page.get_by_role("dialog").get_by_role("button", name="Prompt versions", exact=True).click()
                expect(page.get_by_role("dialog", name="Prompt version history")).to_be_visible()
                page.get_by_role("dialog", name="Prompt version history").get_by_role("button", name="Close", exact=True).click()
                page.get_by_role("dialog").get_by_role("button", name="Disable key", exact=True).click()
                page.get_by_role("dialog", name="Change API key access?").get_by_role("button", name="Confirm", exact=True).click()
                expect(page.get_by_role("dialog")).to_have_count(0)
                page.get_by_role("button", name="Manage", exact=True).click()
                page.get_by_role("dialog").get_by_role("button", name="Enable key", exact=True).click()
                page.get_by_role("dialog", name="Change API key access?").get_by_role("button", name="Confirm", exact=True).click()
                expect(page.get_by_role("dialog")).to_have_count(0)
                check("Edit client, prompt version history, disable/enable key confirmations")

                go("knowledge", "Knowledge base")
                page.get_by_label("Knowledge files").set_input_files({"name": "verification.md", "mimeType": "text/markdown", "buffer": b"Verification tenant: support hours are Monday to Friday."})
                page.get_by_role("button", name="Upload & index", exact=True).click()
                expect(page.get_by_role("heading", name="Latest processing results")).to_be_visible()
                expect(page.get_by_role("cell", name="ready", exact=True).first).to_be_visible()
                page.get_by_role("button", name="Rebuild index", exact=True).click()
                page.get_by_role("dialog").get_by_role("button", name="Rebuild index", exact=True).click()
                expect(page.get_by_role("dialog")).to_have_count(0)
                check("Multi-format upload UI, persisted metadata, real rebuild completion")
                screenshot("knowledge-desktop.png")

                headers = {"X-API-Key": public_key, "Origin": url}
                chat = httpx.post(url + "/v1/chat", headers=headers, json={"message": "hello"})
                chat.raise_for_status()
                session = chat.json()["session_id"]
                lead = httpx.post(url + "/v1/leads", headers={**headers, "Idempotency-Key": "browser-lead"}, json={"name": "Verification contact", "email": "qa@example.test", "requirement": "Test follow-up", "conversation_id": session})
                lead.raise_for_status()
                go("conversations", "Conversations")
                page.get_by_role("button", name="View", exact=True).click()
                expect(page.get_by_text(chat.json()["answer"], exact=True)).to_be_visible()
                assert not page.evaluate("Boolean(window.__injected)")
                page.get_by_role("dialog").get_by_role("button", name="Close", exact=True).click()
                check("Conversation history rendering and adversarial model-text escaping")
                screenshot("conversations-desktop.png")

                go("leads", "Leads")
                page.get_by_role("button", name="View lead", exact=True).click()
                page.get_by_role("dialog").get_by_label("Status", exact=True).select_option("qualified")
                page.get_by_role("dialog").get_by_label("Internal notes").fill("Browser verified note")
                page.get_by_role("dialog").get_by_role("button", name="Update lead", exact=True).click()
                expect(page.get_by_role("cell", name="qualified", exact=True)).to_be_visible()
                with page.expect_download() as download:
                    page.get_by_role("button", name="Export CSV", exact=True).click()
                assert download.value.suggested_filename == "orbit-leads.csv"
                check("Lead workflow, contact details, persisted notes, authenticated CSV download")
                screenshot("leads-desktop.png")

                go("analytics", "Analytics")
                expect(page.get_by_role("img", name="conversations and leads by UTC day")).to_be_visible()
                page.get_by_label("Activity period").select_option("90")
                expect(page.get_by_text("Daily records for the last 90 days · UTC")).to_be_visible()
                check("Actual analytics chart, period filter, usage table")
                screenshot("analytics-desktop.png")

                go("providers", "AI providers")
                page.get_by_role("button", name="Test completion", exact=True).first.click()
                expect(page.get_by_text("completion_succeeded", exact=True)).to_be_visible()
                page.get_by_role("button", name="Configure roles", exact=True).click()
                expect(page.get_by_role("dialog", name="Configure provider roles")).to_be_visible()
                page.get_by_role("dialog").get_by_role("button", name="Cancel", exact=True).click()
                check("Provider role display and completion test with isolated model adapter")
                screenshot("providers-desktop.png")

                for key, title in (("settings", "System settings"), ("activity", "Activity log"), ("docs", "Documentation")):
                    go(key, title)
                    check(title + " page and API integration")
                go("overview", "Overview")
                screenshot("overview-desktop.png")
                page.get_by_role("button", name="Switch color theme").click()
                screenshot("overview-dark.png")
                page.get_by_role("button", name="Switch color theme").click()
                page.get_by_role("button", name="Collapse navigation").click()
                assert "collapsed" in page.locator("body").get_attribute("class")
                page.get_by_role("button", name="Expand navigation").click()
                check("Theme toggle and collapsible desktop navigation")

                page.set_viewport_size({"width": 390, "height": 844})
                overflow = page.evaluate("""() => ({width:innerWidth,scroll:document.documentElement.scrollWidth,nodes:[...document.querySelectorAll('body *')].filter(n=>n.getBoundingClientRect().right>innerWidth+1).slice(0,12).map(n=>({tag:n.tagName,cls:n.className,right:n.getBoundingClientRect().right}))})""")
                assert overflow["scroll"] <= overflow["width"], overflow
                page.get_by_role("button", name="Open navigation").click()
                expect(page.get_by_role("navigation", name="")).to_be_visible()
                page.locator("#navigation").get_by_role("link", name="Clients", exact=True).click()
                expect(page.locator("#content h1")).to_have_text("Clients")
                assert "mobile-open" not in page.locator("body").get_attribute("class")
                screenshot("clients-mobile.png")
                check("390px responsive layout, mobile drawer, tenant table")

                # Exercise widget against the same public API with its actual browser asset.
                page.set_viewport_size({"width": 1440, "height": 1050})
                page.evaluate("""key => { const s=document.createElement('script');s.src='/widget.js';s.dataset.apiKey=key;s.dataset.baseUrl=location.origin;document.body.append(s); }""", public_key)
                page.wait_for_timeout(500)
                if errors:
                    raise AssertionError(f"Widget JavaScript failed to initialize: {errors}")
                widget_debug = page.evaluate("""() => { const node=document.querySelector('[data-orbit-widget]'); const scope=node?.shadowRoot || node; const button=scope?.querySelector('.orbit-launcher'); const rect=button?.getBoundingClientRect(); const point=rect ? document.elementFromPoint(rect.left+rect.width/2,rect.top+rect.height/2)?.tagName : null; return {count:node?1:0, shadow:scope?.innerHTML?.slice(0,120) || '', host:node ? {z:getComputedStyle(node).zIndex,position:getComputedStyle(node).position,pointer:getComputedStyle(node).pointerEvents} : null, button:rect ? {left:rect.left,top:rect.top,right:rect.right,bottom:rect.bottom,z:getComputedStyle(button).zIndex,pointer:getComputedStyle(button).pointerEvents,position:getComputedStyle(button).position} : null, point}; }""")
                if not widget_debug["count"]:
                    raise AssertionError(f"Widget root was not created: {widget_debug}")
                # Keep the diagnostic available only for the local widget smoke while debugging stacking contexts.
                if widget_debug.get("point") not in {"BUTTON", "DIV"}:
                    raise AssertionError(f"Widget click target is obscured: {widget_debug}")
                widget = page.locator("[data-orbit-widget]")
                widget.locator(".orbit-launcher").click()
                page.get_by_placeholder("Ask a question").fill("hello")
                page.get_by_role("button", name="Send", exact=True).click()
                expect(page.get_by_text(chat.json()["answer"], exact=True)).to_be_visible()
                assert not page.evaluate("Boolean(window.__injected)")
                check("Existing widget/public key/chat integration and safe DOM output")
                page.get_by_role("button", name="Log out", exact=True).click()
                expect(page).to_have_url(url + "/admin/login")
                assert page.evaluate("Object.keys(localStorage)") == ["orbit-theme"]
                check("Logout invalidates server session; browser storage has theme only")
                browser.close()
        finally:
            server.should_exit = True
            thread.join(timeout=10)
    result = {"executed_at": datetime.now(UTC).isoformat(), "mode": "Real local FastAPI + SQLite + Chromium; external LLM/embedding adapters faked only", "checks": outcomes, "screenshots": [str(path.relative_to(ROOT)) for path in sorted(shots.glob("*.png"))]}
    (ROOT / "docs" / "DASHBOARD_BROWSER_RESULTS.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"PASS: {len(outcomes)} browser checks; {len(result['screenshots'])} screenshots")


if __name__ == "__main__":
    run()
