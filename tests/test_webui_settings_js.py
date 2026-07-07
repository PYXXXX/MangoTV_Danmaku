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
        self.assertIn("parseMgtvLiveUrl", source)

    def test_app_js_prefills_start_activity_from_runtime_defaults(self):
        source = (ROOT / "server" / "webui" / "app.js").read_text(encoding="utf-8")
        self.assertIn("function defaultActivityName()", source)
        self.assertIn("state.defaults", source)
        self.assertIn("el.activityName.value = defaultActivityName()", source)
        self.assertIn("const activity = el.activityName.value.trim() || defaultActivityName()", source)
        self.assertIn("downloadPng", source)
        self.assertIn("/result.png?result=", source)
        self.assertIn("downloadRaw", source)
        self.assertIn("/raw.jsonl", source)
        self.assertIn("recordingPlayer", source)
        self.assertIn("/recording/markers", source)
        self.assertIn("/recording/clips", source)
        self.assertIn("postRecordForm", source)
        self.assertIn("defaultFullRecordingName", source)
        self.assertIn("生成分析场次", source)
        self.assertIn("/analysis-round", source)
        self.assertIn("/raw.jsonl", source)
        self.assertIn("deleteRound", source)
        self.assertIn("/api/rounds/", source)
        self.assertIn("deleteActivity", source)
        self.assertIn("/api/activities/", source)
        self.assertIn("confirmPublishAfterDelete", source)
        self.assertIn("?publish=", source)
        self.assertIn("是否立即同步远端公开发布页", source)

    def test_public_page_can_export_png_with_source_credit(self):
        html = (ROOT / "site" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "site" / "app.js").read_text(encoding="utf-8")
        self.assertIn("exportPng", html)
        self.assertIn("renderCurrentPng", source)
        self.assertIn("canvas.toDataURL(\"image/png\")", source)
        self.assertIn("https://pyxxxx.github.io/MangoTV_Danmaku/", source)

    def test_settings_js_keeps_recording_config_fields(self):
        html = (ROOT / "server" / "webui" / "index.html").read_text(encoding="utf-8")
        source = (ROOT / "server" / "webui" / "settings.js").read_text(encoding="utf-8")
        self.assertIn("cfgRecordingEnabled", html)
        self.assertIn("cfgRecordingQuality", html)
        self.assertIn("cfgRecordingStreamUrl", html)
        self.assertIn("startMgtvAuth", html)
        self.assertIn("checkMgtvSource", html)
        self.assertIn("mgtvAuthProtocol", html)
        self.assertIn("录制后处理", html)
        self.assertIn("开始全程录制与弹幕", html)
        self.assertIn("SQLite 去重路径（空闲时热切换）", html)
        self.assertIn("录制目录（空闲时热切换）", html)
        self.assertNotIn("SQLite 去重路径（修改后需重启）", html)
        self.assertNotIn("录制目录（修改后需重启）", html)
        self.assertIn("postLiveUrl", html)
        self.assertIn("cfgRecordingFfmpeg", source)
        self.assertIn("recording:", source)
        self.assertIn("stream_url", source)
        self.assertIn("preferred_quality", source)
        self.assertIn("/api/mgtv/auth/start", source)
        self.assertIn("/api/mgtv/source/check", source)
        self.assertIn("芒果扫码接口", source)
        self.assertNotIn("mgtvAuthPlaywright", source)
        self.assertNotIn("playwrightAvailable", source)

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

    def test_mgtv_url_input_autofills_camera_and_room_id(self):
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
              dispatch(type) {
                const event = { target: this, preventDefault() {} };
                for (const handler of this.listeners[type] || []) handler(event);
              }
              closest(selector) {
                return selector === "#" + this.id ? this : null;
              }
              scrollIntoView() {}
            }

            const elements = new Map();
            function elementFor(id) {
              if (!elements.has(id)) elements.set(id, new Element(id));
              return elements.get(id);
            }
            const document = {
              getElementById: elementFor,
              addEventListener() {},
            };
            async function fetch(url) {
              if (url.startsWith("/api/settings")) {
                return { ok: true, status: 200, json: async () => ({
                  config: {
                    listen: {}, storage: {}, mgtv: {}, vote: {}, github: {},
                    feishu: {}, operator_auth: {}
                  },
                  runtime: {}
                }) };
              }
              if (url.startsWith("/api/feishu/binding")) {
                return { ok: true, status: 200, json: async () => ({ status: "idle" }) };
              }
              return { ok: true, status: 200, json: async () => ({ ok: true }) };
            }
            function requireLogin(response) { return response; }
            function addLog() {}
            const window = {
              console: { debug() {} },
              location: { pathname: "/", search: "", assign() {} },
              confirm() { return true; },
              open() {},
            };

            const code = fs.readFileSync("server/webui/settings.js", "utf8");
            vm.runInNewContext(code, {
              document, window, fetch, requireLogin, addLog,
              AbortController, Error, Date, Math, Number, String, Boolean, Array, Object, Set,
              setTimeout, clearTimeout, setInterval, clearInterval,
            });

            elementFor("cfgFlag").value = "liveshow";
            elementFor("cfgLiveUrl").value = "https://www.mgtv.com/z/1001668/5366.html?fpa=12437";
            elementFor("cfgLiveUrl").dispatch("input");

            if (elementFor("cfgCameraId").value !== "5366") {
              throw new Error("camera_id not autofilled: " + elementFor("cfgCameraId").value);
            }
            if (elementFor("cfgRoomId").value !== "liveshow-5366") {
              throw new Error("room_id not autofilled: " + elementFor("cfgRoomId").value);
            }
            if (!elementFor("mgtvUrlHint").textContent.includes("已自动识别")) {
              throw new Error("hint did not report success: " + elementFor("mgtvUrlHint").textContent);
            }

            elementFor("cfgLiveUrl").value = "https://www.mgtv.com/z/1001668.html?fpa=12437&fpos&lastp=ch_home&_source_=B";
            elementFor("cfgLiveUrl").dispatch("input");
            if (!elementFor("mgtvUrlHint").textContent.includes("activity_id=1001668")) {
              throw new Error("activity page hint did not report activity id: " + elementFor("mgtvUrlHint").textContent);
            }
            if (!elementFor("mgtvUrlHint").textContent.includes("自动解析 camera_id")) {
              throw new Error("activity page hint did not explain deferred camera parsing: " + elementFor("mgtvUrlHint").textContent);
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
