import subprocess
import textwrap
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class WebuiSettingsJsTest(unittest.TestCase):
    def test_settings_js_keeps_feishu_binding_entrypoints(self):
        source = (ROOT / "server" / "webui" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("startFeishuBinding", source)
        self.assertIn("/api/feishu/binding/start", source)
        self.assertIn("AbortController", source)

    def test_feishu_binding_button_click_posts_start_endpoint(self):
        script = textwrap.dedent(
            r"""
            const fs = require("fs");
            const vm = require("vm");

            class Element {
              constructor(id) {
                this.id = id;
                this.value = "";
                this.checked = false;
                this.disabled = false;
                this.hidden = false;
                this.href = "";
                this.textContent = "";
                this.className = "";
                this.placeholder = "";
                this.style = {};
                this.listeners = {};
                this.classList = { add: (name) => { this.className += " " + name; } };
              }
              addEventListener(type, handler) {
                this.listeners[type] = this.listeners[type] || [];
                this.listeners[type].push(handler);
              }
              closest(selector) {
                return selector === "#" + this.id ? this : null;
              }
              click() {
                const event = { target: this, preventDefault() { this.defaultPrevented = true; } };
                for (const handler of this.listeners.click || []) handler(event);
                document.dispatchEvent("click", event);
              }
              scrollIntoView() {}
            }

            const elements = new Map();
            function elementFor(id) {
              if (!elements.has(id)) elements.set(id, new Element(id));
              return elements.get(id);
            }
            const documentListeners = {};
            const document = {
              getElementById: elementFor,
              addEventListener(type, handler) {
                documentListeners[type] = documentListeners[type] || [];
                documentListeners[type].push(handler);
              },
              dispatchEvent(type, event) {
                for (const handler of documentListeners[type] || []) handler(event);
              },
            };
            const calls = [];
            const opened = [];
            const window = {
              console: { debug() {} },
              open(url) { opened.push(url); },
              location: { pathname: "/", search: "", assign() {} },
              confirm() { return true; },
            };
            async function fetch(url, options = {}) {
              calls.push({ url, method: options.method || "GET" });
              if (url.startsWith("/api/settings")) {
                return { ok: true, status: 200, json: async () => ({
                  config: {
                    listen: {}, storage: {}, mgtv: {}, vote: {}, github: {},
                    feishu: {}, operator_auth: {}
                  },
                  runtime: {}
                }) };
              }
              if (url.startsWith("/api/feishu/binding/start")) {
                return { ok: true, status: 200, json: async () => ({
                  status: "pending",
                  verificationUrl: "https://open.feishu.cn/page/cli?user_code=TEST",
                  userCode: "TEST",
                  expiresAt: Math.floor(Date.now() / 1000) + 300,
                }) };
              }
              if (url.startsWith("/api/feishu/binding")) {
                return { ok: true, status: 200, json: async () => ({ status: "idle" }) };
              }
              if (url.startsWith("/api/update/status")) {
                return { ok: true, status: 200, json: async () => ({ ok: true, updateAvailable: false, blockers: [] }) };
              }
              return { ok: true, status: 200, json: async () => ({ ok: true }) };
            }
            function requireLogin(response) { return response; }
            function addLog() {}

            const code = fs.readFileSync("server/webui/settings.js", "utf8");
            vm.runInNewContext(code, {
              document, window, fetch, requireLogin, addLog,
              AbortController, Error, Date, Math, Number, String, Boolean, Array, Object, Set,
              setTimeout, clearTimeout, setInterval, clearInterval,
            });

            calls.length = 0;
            elementFor("startFeishuBinding").click();
            const posted = calls.some((call) => call.url === "/api/feishu/binding/start" && call.method === "POST");
            if (!posted) {
              throw new Error("clicking #startFeishuBinding did not POST /api/feishu/binding/start; calls=" + JSON.stringify(calls));
            }
            """
        )
        result = subprocess.run(
            ["node", "-e", script],
            cwd=ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            self.fail(result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
