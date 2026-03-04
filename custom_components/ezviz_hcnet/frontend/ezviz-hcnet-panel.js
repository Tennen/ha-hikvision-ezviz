class EzvizHcnetPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sessionId = null;
    this._hlsUrl = null;
    this._hls = null;
    this._statusTimer = null;
    this._state = { loading: false, error: "", status: null };
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
    if (!this._statusTimer) {
      this._refreshStatus();
      this._statusTimer = setInterval(() => this._refreshStatus(), 3000);
    }
  }

  set panel(panel) {
    this._panel = panel;
    this._render();
  }

  disconnectedCallback() {
    if (this._statusTimer) {
      clearInterval(this._statusTimer);
      this._statusTimer = null;
    }
    this._destroyHls();
  }

  get _entryId() {
    return this._panel?.config?.entry_id;
  }

  async _api(method, path, body = undefined) {
    if (!this._hass) return null;
    return this._hass.callApi(method, path, body);
  }

  async _refreshStatus() {
    if (!this._entryId || !this._hass) return;
    try {
      const status = await this._api("get", `ezviz_hcnet/${this._entryId}/status`);
      this._state.status = status;
      if (status?.playback?.session_id) {
        this._sessionId = status.playback.session_id;
        this._hlsUrl = status.playback.hls_url;
      }
      this._state.error = "";
    } catch (err) {
      this._state.error = String(err);
    }
    this._render();
  }

  _readInput(id) {
    const el = this.shadowRoot?.getElementById(id);
    return el ? el.value : "";
  }

  async _openPlayback() {
    const start = this._readInput("startTime");
    const end = this._readInput("endTime");
    if (!start || !end) {
      this._state.error = "请先填写开始和结束时间";
      this._render();
      return;
    }

    this._state.loading = true;
    this._state.error = "";
    this._render();

    try {
      const resp = await this._api("post", `ezviz_hcnet/${this._entryId}/playback/session`, {
        start,
        end,
      });
      this._sessionId = resp.session_id;
      this._hlsUrl = resp.hls_url;
      await this._refreshStatus();
    } catch (err) {
      this._state.error = String(err);
      this._render();
    } finally {
      this._state.loading = false;
      this._render();
    }
  }

  async _control(action, seekPercent = null) {
    if (!this._sessionId) {
      this._state.error = "暂无播放会话";
      this._render();
      return;
    }
    try {
      const body = { action };
      if (seekPercent !== null) body.seek_percent = Number(seekPercent);
      await this._api("post", `ezviz_hcnet/${this._entryId}/playback/${this._sessionId}/control`, body);
      await this._refreshStatus();
    } catch (err) {
      this._state.error = String(err);
      this._render();
    }
  }

  async _closePlayback() {
    if (!this._sessionId) return;
    try {
      await this._api("delete", `ezviz_hcnet/${this._entryId}/playback/${this._sessionId}`);
    } catch (err) {
      this._state.error = String(err);
    }
    this._sessionId = null;
    this._hlsUrl = null;
    this._destroyHls();
    await this._refreshStatus();
  }

  _destroyHls() {
    if (this._hls && typeof this._hls.destroy === "function") {
      this._hls.destroy();
    }
    this._hls = null;
  }

  _bindPlayer() {
    const video = this.shadowRoot?.getElementById("player");
    if (!video || !this._hlsUrl) {
      this._destroyHls();
      return;
    }

    this._destroyHls();
    const HlsCtor = window.Hls;
    if (HlsCtor && typeof HlsCtor.isSupported === "function" && HlsCtor.isSupported()) {
      this._hls = new HlsCtor();
      this._hls.loadSource(this._hlsUrl);
      this._hls.attachMedia(video);
      return;
    }

    video.src = this._hlsUrl;
  }

  _render() {
    if (!this.shadowRoot) return;
    const status = this._state.status;
    const playback = status?.playback || null;
    const progress = playback?.progress ?? 0;

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; padding:16px; box-sizing:border-box; }
        .card { background: var(--ha-card-background, #fff); border-radius:12px; padding:16px; box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.12)); }
        .row { display:flex; gap:12px; align-items:center; flex-wrap:wrap; margin-bottom:12px; }
        label { min-width:88px; color:var(--primary-text-color); }
        input, button { font-size:14px; }
        input[type="datetime-local"] { padding:6px 8px; }
        button { padding:8px 12px; border-radius:8px; border:1px solid var(--divider-color); background:var(--card-background-color,#fff); cursor:pointer; }
        button.primary { background: var(--primary-color); color:#fff; border:none; }
        .muted { color: var(--secondary-text-color); font-size:13px; }
        .error { color: var(--error-color); font-size:13px; white-space: pre-wrap; }
        video { width:100%; max-height:60vh; background:#000; border-radius:10px; }
        .slider { width:320px; max-width:100%; }
      </style>
      <div class="card">
        <h2>EZVIZ HCNet 回放面板</h2>
        <div class="muted">Entry: ${this._entryId || "-"}</div>
        <div class="muted">设备: ${status?.host || "-"} / 通道: ${status?.channel ?? "-"} / 连接: ${status?.connected ? "在线" : "离线"}</div>
        <div class="row">
          <label>开始时间</label>
          <input id="startTime" type="datetime-local" />
          <label>结束时间</label>
          <input id="endTime" type="datetime-local" />
          <button class="primary" id="openBtn">打开回放</button>
          <button id="closeBtn">关闭会话</button>
        </div>
        <div class="row">
          <button id="playBtn">播放</button>
          <button id="pauseBtn">暂停</button>
          <label>定位</label>
          <input class="slider" id="seekRange" type="range" min="0" max="100" step="1" value="${progress}" />
          <span>${progress}%</span>
          <button id="seekBtn">跳转</button>
        </div>
        <div class="muted">会话: ${playback?.session_id || "-"} / 状态: ${playback?.status || "-"}</div>
        ${this._state.error ? `<div class="error">${this._state.error}</div>` : ""}
        <div style="margin-top:12px;">
          ${this._hlsUrl ? `<video id="player" controls autoplay src="${this._hlsUrl}"></video>` : '<div class="muted">请先打开回放会话</div>'}
        </div>
      </div>
    `;

    this.shadowRoot.getElementById("openBtn")?.addEventListener("click", () => this._openPlayback());
    this.shadowRoot.getElementById("closeBtn")?.addEventListener("click", () => this._closePlayback());
    this.shadowRoot.getElementById("playBtn")?.addEventListener("click", () => this._control("play"));
    this.shadowRoot.getElementById("pauseBtn")?.addEventListener("click", () => this._control("pause"));
    this.shadowRoot.getElementById("seekBtn")?.addEventListener("click", () => {
      const val = this._readInput("seekRange");
      this._control("seek", val);
    });
    this._bindPlayer();
  }
}

customElements.define("ezviz-hcnet-panel", EzvizHcnetPanel);
