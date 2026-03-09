class EzvizHcnetPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._sessionId = null;
    this._hlsUrl = null;
    this._hls = null;
    this._boundHlsUrl = null;
    this._statusTimer = null;
    this._liveCard = null;
    this._liveCardEntityId = null;
    this._liveCardBuildTask = null;
    this._initialized = false;
    this._dragSeekValue = null;
    this._isPaused = false;
    this._endedSessionId = null;
    this._state = {
      loading: false,
      error: "",
      status: null,
      recordingsDate: "",
      recordings: [],
      selectedRecordingId: null,
      loadingRecordings: false,
    };
  }

  set hass(hass) {
    const firstUpdate = !this._initialized;
    this._hass = hass;

    if (!this._state.recordingsDate) {
      this._state.recordingsDate = this._todayDateString();
    }

    if (firstUpdate) {
      this._initialized = true;
      this._render();
      this._refreshStatus(false);
      return;
    }

    if (this._liveCard) {
      this._liveCard.hass = hass;
    }

    if (!this._liveCard && this._cameraEntityId()) {
      this._render();
    }

    this._syncPlaybackUi();
  }

  set panel(panel) {
    const prevEntryId = this._entryId;
    this._panel = panel;
    const nextEntryId = this._entryId;
    if (nextEntryId && nextEntryId !== prevEntryId) {
      this._state.recordings = [];
      this._state.selectedRecordingId = null;
      this._sessionId = null;
      this._hlsUrl = null;
      this._dragSeekValue = null;
      this._isPaused = false;
      this._liveCard = null;
      this._liveCardEntityId = null;
      this._liveCardBuildTask = null;
      this._refreshStatus(false);
    }
    this._render();
  }

  disconnectedCallback() {
    if (this._statusTimer) {
      clearInterval(this._statusTimer);
      this._statusTimer = null;
    }
    this._destroyHls();
    this._liveCard = null;
    this._liveCardEntityId = null;
    this._liveCardBuildTask = null;
  }

  get _entryId() {
    return this._panel?.config?.entry_id;
  }

  async _api(method, path, body = undefined) {
    if (!this._hass) return null;
    return this._hass.callApi(method, path, body);
  }

  _todayDateString() {
    const now = new Date();
    const y = now.getFullYear();
    const m = String(now.getMonth() + 1).padStart(2, "0");
    const d = String(now.getDate()).padStart(2, "0");
    return `${y}-${m}-${d}`;
  }

  _cameraEntityId() {
    if (!this._hass || !this._entryId) return null;
    const states = this._hass.states || {};
    for (const [entityId, state] of Object.entries(states)) {
      if (!entityId.startsWith("camera.")) continue;
      if (state?.attributes?.entry_id === this._entryId) {
        return entityId;
      }
    }
    return null;
  }

  async _buildLiveCard(entityId) {
    const cardConfig = {
      type: "picture-entity",
      entity: entityId,
      camera_view: "live",
      show_name: false,
      show_state: false,
    };

    if (typeof window.loadCardHelpers === "function") {
      const helpers = await window.loadCardHelpers();
      return helpers.createCardElement(cardConfig);
    }

    await customElements.whenDefined("hui-picture-entity-card");
    const pictureEntityCard = document.createElement("hui-picture-entity-card");
    if (typeof pictureEntityCard.setConfig !== "function") {
      throw new Error("hui-picture-entity-card is unavailable in current frontend");
    }
    pictureEntityCard.setConfig(cardConfig);
    return pictureEntityCard;
  }

  _mountLiveCard() {
    const container = this.shadowRoot?.getElementById("liveCardContainer");
    if (!container) return;

    const entityId = this._cameraEntityId();
    if (!entityId || !this._hass) {
      this._liveCard = null;
      this._liveCardEntityId = null;
      this._liveCardBuildTask = null;
      container.innerHTML = '<div style="padding:14px;" class="muted">未找到对应 camera 实体，无法显示实时画面</div>';
      return;
    }

    if (this._liveCard && this._liveCardEntityId === entityId) {
      container.innerHTML = "";
      container.appendChild(this._liveCard);
      this._liveCard.hass = this._hass;
      return;
    }

    if (this._liveCardBuildTask && this._liveCardEntityId === entityId) {
      return;
    }

    this._liveCard = null;
    this._liveCardEntityId = entityId;
    container.innerHTML = '<div style="padding:14px;" class="muted">正在加载实时视频...</div>';

    this._liveCardBuildTask = (async () => {
      try {
        const card = await this._buildLiveCard(entityId);
        if (this._liveCardEntityId !== entityId) {
          return;
        }
        this._liveCard = card;
        const latestContainer = this.shadowRoot?.getElementById("liveCardContainer");
        if (!latestContainer) return;
        latestContainer.innerHTML = "";
        latestContainer.appendChild(card);
        card.hass = this._hass;
      } catch (err) {
        if (this._liveCardEntityId !== entityId) return;
        this._liveCard = null;
        const latestContainer = this.shadowRoot?.getElementById("liveCardContainer");
        if (latestContainer) {
          latestContainer.innerHTML = `<div style="padding:14px;" class="error">加载实时卡片失败: ${String(err)}</div>`;
        }
      } finally {
        if (this._liveCardEntityId === entityId) {
          this._liveCardBuildTask = null;
        }
      }
    })();
  }

  async _refreshStatus(shouldRender = true) {
    if (!this._entryId || !this._hass) return;
    const prevSessionId = this._sessionId;
    const prevHlsUrl = this._hlsUrl;
    const prevError = this._state.error;
    try {
      const status = await this._api("get", `ezviz_hcnet/${this._entryId}/status`);
      this._state.status = status;
      if (status?.playback?.session_id) {
        this._sessionId = status.playback.session_id;
        this._hlsUrl = status.playback.hls_url;
        this._isPaused = Boolean(status.playback.paused);
        const progress = Number(status.playback.progress || 0);
        if (progress >= 100 && this._endedSessionId !== this._sessionId) {
          this._endedSessionId = this._sessionId;
          await this._closePlayback(true);
          return;
        }
      } else {
        this._sessionId = null;
        this._hlsUrl = null;
        this._isPaused = false;
        this._endedSessionId = null;
      }
      this._state.error = "";
    } catch (err) {
      this._state.error = String(err);
    }

    const playbackChanged = prevSessionId !== this._sessionId || prevHlsUrl !== this._hlsUrl;
    const errorChanged = prevError !== this._state.error;
    this._ensureStatusPolling();
    if (shouldRender || playbackChanged || errorChanged) {
      this._render();
      return;
    }
    this._syncPlaybackUi();
  }

  _ensureStatusPolling() {
    const shouldPoll = Boolean(this._entryId && this._sessionId);
    if (shouldPoll && !this._statusTimer) {
      this._statusTimer = setInterval(() => this._refreshStatus(false), 1000);
      return;
    }
    if (!shouldPoll && this._statusTimer) {
      clearInterval(this._statusTimer);
      this._statusTimer = null;
    }
  }

  _syncPlaybackUi() {
    const root = this.shadowRoot;
    if (!root) return;

    const hasSession = Boolean(this._sessionId);
    const sessionLabel = root.getElementById("sessionLabel");
    if (sessionLabel) sessionLabel.textContent = this._sessionId || "-";

    const closeBtn = root.getElementById("closePlaybackBtn");
    if (closeBtn) closeBtn.disabled = !hasSession;

    const pauseBtn = root.getElementById("pausePlayBtn");
    if (pauseBtn) {
      pauseBtn.disabled = !hasSession;
      pauseBtn.textContent = this._isPaused ? "播放" : "暂停";
    }

    const seekBtn = root.getElementById("seekBtn");
    if (seekBtn) seekBtn.disabled = !hasSession;

    const seekRange = root.getElementById("seekRange");
    if (seekRange) seekRange.disabled = !hasSession;

    const playback = this._state.status?.playback || null;
    const liveProgress = Number(playback?.progress || 0);
    const effectiveProgress = this._dragSeekValue !== null ? Number(this._dragSeekValue) : liveProgress;

    if (seekRange && this._dragSeekValue === null) {
      seekRange.value = String(Math.round(liveProgress));
    }

    const percentLabel = root.getElementById("seekPercentLabel");
    if (percentLabel) percentLabel.textContent = `${Math.round(effectiveProgress)}%`;

    const previewLabel = root.getElementById("seekPreviewLabel");
    if (previewLabel) previewLabel.textContent = `目标时间: ${this._recordingPreviewTime(effectiveProgress)}`;
  }

  async _callPtz(direction) {
    if (!this._hass || !this._entryId) return;
    try {
      await this._hass.callService("ezviz_hcnet", "ptz_move", {
        entry_id: this._entryId,
        direction,
        duration_ms: 400,
      });
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

  _selectedRecording() {
    const id = this._state.selectedRecordingId;
    if (!id) return null;
    return this._state.recordings.find((item) => item.id === id) || null;
  }

  _formatDateTime(text) {
    if (!text) return "-";
    try {
      const dt = new Date(text);
      if (Number.isNaN(dt.getTime())) return text;
      return dt.toLocaleString();
    } catch (_err) {
      return text;
    }
  }

  _formatDuration(seconds) {
    const s = Math.max(0, Number(seconds) || 0);
    const h = Math.floor(s / 3600);
    const m = Math.floor((s % 3600) / 60);
    const sec = s % 60;
    if (h > 0) return `${h}h ${m}m ${sec}s`;
    return `${m}m ${sec}s`;
  }

  async _loadRecordings() {
    if (!this._entryId || !this._hass) return;
    const day = this._state.recordingsDate || this._todayDateString();

    this._state.loadingRecordings = true;
    this._state.error = "";
    this._render();

    try {
      const data = await this._api(
        "get",
        `ezviz_hcnet/${this._entryId}/recordings?date=${encodeURIComponent(day)}&slot_minutes=60`
      );
      const items = Array.isArray(data?.recordings) ? data.recordings : [];
      this._state.recordings = items;
      if (!items.find((item) => item.id === this._state.selectedRecordingId)) {
        this._state.selectedRecordingId = items[0]?.id || null;
      }
      this._state.error = "";
    } catch (err) {
      this._state.error = String(err);
      this._state.recordings = [];
      this._state.selectedRecordingId = null;
    } finally {
      this._state.loadingRecordings = false;
      this._render();
    }
  }

  _recordingPreviewTime(percent) {
    const rec = this._selectedRecording();
    if (!rec?.start || !rec?.end) return "-";

    const start = new Date(rec.start);
    const end = new Date(rec.end);
    if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) return "-";

    const ratio = Math.max(0, Math.min(100, Number(percent) || 0)) / 100;
    const ts = start.getTime() + (end.getTime() - start.getTime()) * ratio;
    return new Date(ts).toLocaleString();
  }

  async _openSelectedPlayback() {
    const rec = this._selectedRecording();
    if (!rec) {
      this._state.error = "请先选择录像片段";
      this._render();
      return;
    }

    this._state.loading = true;
    this._state.error = "";
    this._render();

    try {
      const resp = await this._api("post", `ezviz_hcnet/${this._entryId}/playback/session`, {
        start: rec.start,
        end: rec.end,
      });
      this._sessionId = resp.session_id;
      this._endedSessionId = null;
      this._hlsUrl = resp.hls_url;
      this._isPaused = false;
      this._dragSeekValue = null;
      await this._refreshStatus(false);
      this._render();
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
      const payload = await this._api("post", `ezviz_hcnet/${this._entryId}/playback/${this._sessionId}/control`, body);
      if (payload?.session_id) this._sessionId = payload.session_id;
      if (typeof payload?.paused === "boolean") {
        this._isPaused = payload.paused;
      } else if (action === "pause") {
        this._isPaused = true;
      } else if (action === "play") {
        this._isPaused = false;
      }
      if (this._state.status?.playback) {
        this._state.status.playback.progress = Number(payload?.progress || 0);
      }
      this._state.error = "";
      this._syncPlaybackUi();
      await this._refreshStatus(false);
    } catch (err) {
      this._state.error = String(err);
      this._render();
    }
  }

  async _togglePausePlay() {
    if (this._isPaused) {
      await this._control("play");
    } else {
      await this._control("pause");
    }
    this._syncPlaybackUi();
  }

  async _seekToCurrentDragValue() {
    if (this._dragSeekValue === null) return;
    const v = Number(this._dragSeekValue);
    this._dragSeekValue = null;
    await this._control("seek", v);
  }

  async _closePlayback(skipRefresh = false) {
    if (!this._sessionId) return;
    try {
      await this._api("delete", `ezviz_hcnet/${this._entryId}/playback/${this._sessionId}`);
    } catch (err) {
      this._state.error = String(err);
    }
    this._sessionId = null;
    this._hlsUrl = null;
    this._isPaused = false;
    this._dragSeekValue = null;
    this._destroyHls();
    this._ensureStatusPolling();
    if (!skipRefresh) {
      await this._refreshStatus(false);
    }
    this._render();
  }

  _destroyHls() {
    if (this._hls && typeof this._hls.destroy === "function") {
      this._hls.destroy();
    }
    this._hls = null;
    this._boundHlsUrl = null;
  }

  _bindPlayer() {
    const video = this.shadowRoot?.getElementById("player");
    if (!video || !this._hlsUrl) {
      this._destroyHls();
      return;
    }

    if (this._boundHlsUrl === this._hlsUrl && video.dataset.boundUrl === this._hlsUrl) {
      return;
    }

    this._destroyHls();
    const HlsCtor = window.Hls;
    if (HlsCtor && typeof HlsCtor.isSupported === "function" && HlsCtor.isSupported()) {
      this._hls = new HlsCtor();
      if (
        typeof this._hls.on === "function" &&
        HlsCtor.Events &&
        HlsCtor.ErrorTypes
      ) {
        this._hls.on(HlsCtor.Events.ERROR, (_event, data) => {
          if (!data?.fatal) return;
          if (data.type === HlsCtor.ErrorTypes.NETWORK_ERROR) {
            this._hls.startLoad();
            return;
          }
          if (data.type === HlsCtor.ErrorTypes.MEDIA_ERROR) {
            this._hls.recoverMediaError();
            return;
          }
          this._state.error = `播放流错误: ${String(data.details || "unknown")}`;
          this._destroyHls();
          this._render();
        });
      }
      this._hls.loadSource(this._hlsUrl);
      this._hls.attachMedia(video);
      this._boundHlsUrl = this._hlsUrl;
      video.dataset.boundUrl = this._hlsUrl;
      return;
    }

    video.src = this._hlsUrl;
    this._boundHlsUrl = this._hlsUrl;
    video.dataset.boundUrl = this._hlsUrl;
  }

  _renderRecordingsList() {
    const items = this._state.recordings;
    if (!items.length) {
      return '<div class="muted">当天未检测到录像片段</div>';
    }

    return `
      <div class="recordings-list">
        ${items
          .map((item) => {
            const selected = item.id === this._state.selectedRecordingId ? "selected" : "";
            return `
              <button class="recording-item ${selected}" data-recording-id="${item.id}">
                <div>${this._formatDateTime(item.start)} - ${this._formatDateTime(item.end)}</div>
                <div class="muted">时长: ${this._formatDuration(item.duration_seconds)}</div>
              </button>
            `;
          })
          .join("")}
      </div>
    `;
  }

  _render() {
    if (!this.shadowRoot) return;
    const status = this._state.status;
    const playback = status?.playback || null;
    const playbackPercent = this._dragSeekValue !== null ? Number(this._dragSeekValue) : Number(playback?.progress || 0);
    const previewTime = this._recordingPreviewTime(playbackPercent);
    const selectedRecording = this._selectedRecording();
    const cameraEntityId = this._cameraEntityId();

    this.shadowRoot.innerHTML = `
      <style>
        :host { display:block; padding:16px; box-sizing:border-box; }
        .card { background: var(--ha-card-background, #fff); border-radius:12px; padding:16px; box-shadow: var(--ha-card-box-shadow, 0 2px 8px rgba(0,0,0,.12)); }
        .section-title { margin: 0 0 8px 0; font-size: 18px; }
        .row { display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin-bottom:10px; }
        .grid-2 { display:grid; grid-template-columns: 1.2fr 1fr; gap:14px; }
        @media (max-width: 960px) { .grid-2 { grid-template-columns: 1fr; } }
        .live-wrap, .playback-wrap { background: #0f1720; border-radius: 12px; overflow: hidden; }
        .playback-wrap video { width: 100%; display:block; background:#000; min-height: 220px; object-fit: contain; }
        #liveCardContainer { min-height: 220px; }
        #liveCardContainer > * { display:block; }
        .ptz-grid { display:grid; grid-template-columns: 48px 48px 48px; grid-template-rows: 44px 44px 44px; gap:8px; align-items:center; justify-content:center; }
        button { padding:8px 10px; border-radius:8px; border:1px solid var(--divider-color); background:var(--card-background-color,#fff); cursor:pointer; }
        button.primary { background: var(--primary-color); color:#fff; border:none; }
        .muted { color: var(--secondary-text-color); font-size:13px; }
        .error { color: var(--error-color); font-size:13px; white-space: pre-wrap; }
        .recordings-list { max-height: 260px; overflow:auto; display:flex; flex-direction:column; gap:8px; }
        .recording-item { text-align:left; width:100%; }
        .recording-item.selected { outline: 2px solid var(--primary-color); }
        .slider { width: 340px; max-width: 100%; }
        input[type="date"] { padding: 6px 8px; }
      </style>
      <div class="card">
        <h2 class="section-title">EZVIZ HCNet 控制面板</h2>
        <div class="muted">Entry: ${this._entryId || "-"}</div>
        <div class="muted">设备: ${status?.host || "-"} / 通道: ${status?.channel ?? "-"} / 连接: ${status?.connected ? "在线" : "离线"}</div>

        <div class="grid-2" style="margin-top:12px;">
          <div>
            <h3 style="margin:0 0 8px 0;">实时画面</h3>
            <div class="live-wrap">
              <div id="liveCardContainer"></div>
            </div>
            <div class="muted" style="margin-top:6px;">Camera Entity: ${cameraEntityId || "-"}</div>
          </div>

          <div>
            <h3 style="margin:0 0 8px 0;">云台控制</h3>
            <div class="ptz-grid">
              <div></div>
              <button id="ptz-up" title="向上">↑</button>
              <div></div>
              <button id="ptz-left" title="向左">←</button>
              <div></div>
              <button id="ptz-right" title="向右">→</button>
              <div></div>
              <button id="ptz-down" title="向下">↓</button>
              <div></div>
            </div>
          </div>
        </div>

        <hr style="margin:16px 0; border:none; border-top:1px solid var(--divider-color);"/>

        <h3 style="margin:0 0 8px 0;">录像回放</h3>
        <div class="row">
          <label>日期</label>
          <input id="recordingDate" type="date" value="${this._state.recordingsDate}" />
          <button id="loadRecordingsBtn">查询录像</button>
          <span class="muted">当天录像片段数: ${this._state.recordings.length}</span>
          ${this._state.loadingRecordings ? '<span class="muted">加载中...</span>' : ""}
        </div>

        ${this._renderRecordingsList()}

        <div class="row" style="margin-top:10px;">
          <button class="primary" id="openSelectedBtn" ${selectedRecording ? "" : "disabled"}>播放选中片段</button>
          <button id="closePlaybackBtn" ${this._sessionId ? "" : "disabled"}>关闭会话</button>
          <span class="muted">当前会话: <span id="sessionLabel">${this._sessionId || "-"}</span></span>
        </div>

        <div class="playback-wrap" style="margin-top:10px;">
          ${this._hlsUrl ? `<video id="player" controls autoplay></video>` : '<div style="padding:14px;" class="muted">请先选择录像片段并点击播放</div>'}
        </div>

        <div class="row" style="margin-top:10px;">
          <button id="pausePlayBtn" ${this._sessionId ? "" : "disabled"}>${this._isPaused ? "播放" : "暂停"}</button>
          <input class="slider" id="seekRange" type="range" min="0" max="100" step="1" value="${playbackPercent}" ${this._sessionId ? "" : "disabled"} />
          <span id="seekPercentLabel">${Math.round(playbackPercent)}%</span>
          <button id="seekBtn" ${this._sessionId ? "" : "disabled"}>拖动后定位</button>
          <span class="muted" id="seekPreviewLabel">目标时间: ${previewTime}</span>
        </div>

        ${this._state.error ? `<div class="error">${this._state.error}</div>` : ""}
      </div>
    `;

    this.shadowRoot.getElementById("ptz-up")?.addEventListener("click", () => this._callPtz("up"));
    this.shadowRoot.getElementById("ptz-down")?.addEventListener("click", () => this._callPtz("down"));
    this.shadowRoot.getElementById("ptz-left")?.addEventListener("click", () => this._callPtz("left"));
    this.shadowRoot.getElementById("ptz-right")?.addEventListener("click", () => this._callPtz("right"));

    this.shadowRoot.getElementById("recordingDate")?.addEventListener("change", (ev) => {
      this._state.recordingsDate = ev.target.value || this._todayDateString();
      this._loadRecordings();
    });
    this.shadowRoot.getElementById("loadRecordingsBtn")?.addEventListener("click", () => {
      const val = this._readInput("recordingDate") || this._todayDateString();
      this._state.recordingsDate = val;
      this._loadRecordings();
    });

    this.shadowRoot.querySelectorAll(".recording-item").forEach((el) => {
      el.addEventListener("click", () => {
        this._state.selectedRecordingId = el.getAttribute("data-recording-id");
        this._render();
      });
    });

    this.shadowRoot.getElementById("openSelectedBtn")?.addEventListener("click", () => this._openSelectedPlayback());
    this.shadowRoot.getElementById("closePlaybackBtn")?.addEventListener("click", () => this._closePlayback());

    this.shadowRoot.getElementById("pausePlayBtn")?.addEventListener("click", () => this._togglePausePlay());
    this.shadowRoot.getElementById("seekRange")?.addEventListener("input", (ev) => {
      const v = Number(ev.target.value);
      this._dragSeekValue = v;
      const percentLabel = this.shadowRoot?.getElementById("seekPercentLabel");
      if (percentLabel) percentLabel.textContent = `${Math.round(v)}%`;
      const previewLabel = this.shadowRoot?.getElementById("seekPreviewLabel");
      if (previewLabel) previewLabel.textContent = `目标时间: ${this._recordingPreviewTime(v)}`;
    });
    this.shadowRoot.getElementById("seekRange")?.addEventListener("change", () => this._seekToCurrentDragValue());
    this.shadowRoot.getElementById("seekBtn")?.addEventListener("click", () => this._seekToCurrentDragValue());

    this._mountLiveCard();
    this._bindPlayer();
    this._ensureStatusPolling();
    this._syncPlaybackUi();
  }
}

customElements.define("ezviz-hcnet-panel", EzvizHcnetPanel);
