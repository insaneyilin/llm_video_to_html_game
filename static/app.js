const state = {
  projectId: null,
  project: null,
  projects: [],
  htmlAbortController: null,
  htmlChatAbortController: null,
};

const views = {
  upload: document.querySelector("#uploadView"),
  frames: document.querySelector("#framesView"),
  spec: document.querySelector("#specView"),
  html: document.querySelector("#htmlView"),
};

const titles = {
  upload: ["上传视频", "上传新视频会创建一个 Project；也可以从左侧恢复已有 Project。"],
  frames: ["抽帧检查", "检查抽帧结果，并查看步骤 1 / 步骤 2 的模型输入 prompt。"],
  spec: ["GameSpec", "先从抽帧生成玩法提示，再基于提示生成结构化 GameSpec JSON。"],
  html: ["生成游戏", "确认规格后生成 HTML；试玩后可用聊天让模型修复 bug。"],
};

const $ = (selector) => document.querySelector(selector);

function formatDuration(ms) {
  const totalSeconds = Math.floor(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return minutes > 0 ? `${minutes}:${String(seconds).padStart(2, "0")}` : `${seconds}s`;
}

function beginStreamProgress({ outputEl, statusBase, initialMessage }) {
  const startedAt = Date.now();
  const timer = setInterval(() => {
    setStatus(`${statusBase} · ${formatDuration(Date.now() - startedAt)}`);
  }, 500);

  function elapsed() {
    return formatDuration(Date.now() - startedAt);
  }

  function showStatus(message) {
    outputEl.textContent = `[${elapsed()}] ${message}`;
    outputEl.scrollTop = outputEl.scrollHeight;
  }

  function stop(finalStatus) {
    clearInterval(timer);
    if (finalStatus) setStatus(finalStatus);
  }

  showStatus(initialMessage);
  return { showStatus, stop, elapsed };
}

function appendStreamOutput(outputEl, raw) {
  outputEl.textContent = raw;
  outputEl.scrollTop = outputEl.scrollHeight;
}

function isAbortError(error) {
  return error?.name === "AbortError";
}

function streamStatusMessage(data) {
  if (data.message) {
    return data.message;
  }
  if (data.status === "preparing") {
    return "正在加载抽帧图片并组装 prompt...";
  }
  if (data.stage === "hint" && data.status === "calling_model") {
    return `步骤 1：正在从 ${data.frame_count || "?"} 张抽帧生成玩法提示（JSON，think 关闭）...`;
  }
  if (data.stage === "spec" && data.status === "calling_model") {
    return "步骤 2：正在生成精简 GameSpec draft（temperature=0）...";
  }
  if (data.stage === "html" && data.status === "calling_model") {
    return data.message || "正在调用模型生成玩法 JavaScript 模块...";
  }
  if (data.status === "calling_model") {
    const thinkNote =
      data.think === true
        ? "已开启思考模式，思考过程会流式显示"
        : data.think === false
          ? "已关闭思考模式"
          : "";
    const suffix = thinkNote ? `（${thinkNote}）` : "";
    return `正在调用 ${data.model || "模型"}，发送 ${data.frame_count || "?"} 张图片${suffix}。视觉推断可能需要 30–90 秒才开始输出 JSON...`;
  }
  if (data.status === "parsing") {
    return "模型输出完成，正在校验 GameSpec JSON...";
  }
  if (data.status === "repairing") {
    return "模型返回的 JSON 格式有误，正在自动修复（下方会出现 [修复] 流式输出）...";
  }
  if (data.stage === "html_edit" && data.status === "calling_model") {
    const ctx = data.num_ctx ? `，上下文 ${Math.round(data.num_ctx / 1024)}k` : "";
    const thinkNote = data.think === false ? "，已关闭思考模式" : "";
    return `正在调用 ${data.model || "模型"} 修复 HTML（输入约 ${data.input_chars?.toLocaleString() || "?"} 字符${ctx}${thinkNote}）。长 HTML 首 token 可能仍需 30–60 秒...`;
  }
  if (data.stage === "html_edit" && data.status === "parsing") {
    return "模型输出完成，正在校验修复后的 HTML...";
  }
  return "处理中...";
}

function setStatus(text) {
  $("#statusPill").textContent = text;
}

function toast(message) {
  const el = $("#toast");
  el.textContent = message;
  el.hidden = false;
  setTimeout(() => {
    el.hidden = true;
  }, 3800);
}

function setView(name) {
  Object.entries(views).forEach(([key, el]) => el.classList.toggle("active", key === name));
  document.querySelectorAll(".step").forEach((button) => {
    button.classList.toggle("active", button.dataset.step === name);
  });
  $("#viewTitle").textContent = titles[name][0];
  $("#viewDescription").textContent = titles[name][1];
}

function enableStep(name, enabled = true) {
  document.querySelector(`.step[data-step="${name}"]`).disabled = !enabled;
}

function setActionState() {
  const project = state.project;
  const status = project?.status || {};
  enableStep("frames", Boolean(project));
  enableStep("spec", Boolean(status.frames_extracted));
  enableStep("html", Boolean(status.spec_generated));

  $("#extractFramesBtn").disabled = !project;
  $("#generateHintBtn").disabled = !status.frames_extracted;
  $("#gameHintInput").disabled = !status.frames_extracted;
  $("#loadHintInputBtn").disabled = !status.frames_extracted;
  $("#loadSpecInputBtn").disabled = !status.frames_extracted;
  $("#generateSpecBtn").disabled = !status.frames_extracted;
  $("#validateSpecBtn").disabled = !status.spec_generated;
  $("#chatInput").disabled = !status.spec_generated;
  $("#chatEditBtn").disabled = !status.spec_generated;
  $("#loadHtmlInputBtn").disabled = !status.spec_generated;
  $("#generateHtmlBtn").disabled = !status.spec_generated;
  $("#htmlChatInput").disabled = !status.html_generated;
  $("#htmlChatEditBtn").disabled = !status.html_generated;
}

function renderMetadata(project) {
  const meta = project?.metadata || {};
  $("#videoMetadata").innerHTML = `
    <div><dt>名称</dt><dd>${project?.name || "-"}</dd></div>
    <div><dt>文件名</dt><dd>${project?.original_filename || "-"}</dd></div>
    <div><dt>分辨率</dt><dd>${meta.width || "-"} × ${meta.height || "-"}</dd></div>
    <div><dt>时长</dt><dd>${meta.duration_seconds || 0}s</dd></div>
    <div><dt>阶段</dt><dd>${statusText(project?.status || {})}</dd></div>
  `;
  $("#projectSummaryText").textContent = project
    ? `Project ID: ${project.id} · 更新于 ${project.updated_at || "-"}`
    : "上传新视频或从左侧选择已有项目。";
}

function statusText(status) {
  if (status.html_generated) return "HTML 已生成";
  if (status.spec_generated) return "GameSpec 已生成";
  if (status.frames_extracted) return "抽帧完成";
  if (status.video_uploaded) return "视频已上传";
  return "未开始";
}

function renderProjectList() {
  const list = $("#projectList");
  if (!state.projects.length) {
    list.innerHTML = `<p class="empty-text">暂无 Project，上传视频开始。</p>`;
    return;
  }

  list.innerHTML = state.projects
    .map(
      (project) => `
        <button class="project-item ${project.id === state.projectId ? "selected" : ""}" data-project-id="${project.id}">
          <strong>${project.name}</strong>
          <span>${statusText(project.status || {})}</span>
          <small>${project.updated_at || ""}</small>
        </button>
      `
    )
    .join("");

  document.querySelectorAll(".project-item").forEach((button) => {
    button.addEventListener("click", () => loadProject(button.dataset.projectId));
  });
}

function renderFrames(frames) {
  $("#frameGrid").innerHTML = (frames || [])
    .map(
      (frame, index) => `
        <article class="frame-card">
          <img src="${frame.url}" alt="Extracted frame ${index + 1}" />
          <div>Frame ${index + 1} · index ${frame.index} · ${frame.timestamp_seconds ?? "-"}s</div>
        </article>
      `
    )
    .join("");
}

function restoreProject(project) {
  state.project = project;
  state.projectId = project.id;
  renderProjectList();
  renderMetadata(project);
  renderFrames(project.frames || []);

  const video = $("#videoPreview");
  video.src = project.video_url;
  video.hidden = false;
  $("#gameHintInput").value = project.game_hint || project.inferred_game_hint || "";

  if (project.game_spec) {
    $("#specEditor").value = JSON.stringify(project.game_spec, null, 2);
    $("#specStreamOutput").textContent ||= "已从 Project 恢复当前 GameSpec。";
  } else {
    $("#specEditor").value = "";
    $("#specStreamOutput").textContent = "";
  }

  if (project.current_html) {
    $("#gamePreview").src = `/api/projects/${project.id}/html/preview`;
    $("#downloadLink").href = `/api/projects/${project.id}/html/download`;
    $("#downloadLink").classList.remove("disabled");
    loadCurrentHtmlIntoEditor(project.id);
  } else {
    $("#gamePreview").removeAttribute("src");
    $("#downloadLink").href = "#";
    $("#downloadLink").classList.add("disabled");
    $("#htmlStreamOutput").textContent = "";
  }

  setActionState();
  setStatus(statusText(project.status || {}));

  if (project.status?.html_generated) setView("html");
  else if (project.status?.spec_generated) setView("spec");
  else if (project.status?.frames_extracted) setView("frames");
  else setView("upload");
}

function getHintRequest() {
  return {
    model: $("#modelInput").value.trim(),
    max_frames: Number($("#frameCountInput").value),
    user_notes: $("#gameHintInput").value.trim(),
  };
}

function getSpecRequest() {
  return {
    model: $("#modelInput").value.trim(),
    game_hint: $("#gameHintInput").value.trim(),
    extra_constraints: $("#constraintsInput").value.trim(),
    max_frames: Number($("#frameCountInput").value),
  };
}

function getHtmlModel() {
  return ($("#htmlModelInput")?.value || "").trim() || $("#modelInput").value.trim();
}

function getHtmlProvider() {
  return ($("#htmlProviderInput")?.value || "ollama").trim();
}

function htmlProviderLabel() {
  return getHtmlProvider() === "deepseek" ? "DeepSeek" : "Ollama";
}

function parseSpecEditor() {
  try {
    return JSON.parse($("#specEditor").value);
  } catch (error) {
    throw new Error(`GameSpec JSON 格式错误：${error.message}`);
  }
}

async function loadCurrentHtmlIntoEditor(projectId) {
  try {
    const response = await fetch(`/api/projects/${projectId}/html/preview`);
    if (!response.ok) return;
    const html = await response.text();
    $("#htmlStreamOutput").textContent = html;
  } catch {
    $("#htmlStreamOutput").textContent ||= "已从 Project 恢复当前 HTML 游戏。";
  }
}

async function getCurrentHtml() {
  const fromEditor = $("#htmlStreamOutput").textContent.trim();
  if (fromEditor && fromEditor.toLowerCase().includes("<html")) {
    return fromEditor;
  }
  if (!state.project?.current_html) {
    throw new Error("请先生成 HTML 游戏。");
  }
  const response = await fetch(`/api/projects/${state.projectId}/html/preview`);
  if (!response.ok) {
    throw new Error("无法加载当前 HTML 游戏。");
  }
  return response.text();
}

function getGameplayHint() {
  const manual = $("#gameHintInput").value.trim();
  if (manual) return manual;

  try {
    const spec = parseSpecEditor();
    return [
      spec.title && `Title: ${spec.title}`,
      spec.genre && `Genre: ${spec.genre}`,
      spec.objective && `Objective: ${spec.objective}`,
      spec.player_controls?.length && `Controls: ${spec.player_controls.join(", ")}`,
      spec.win_condition && `Win: ${spec.win_condition}`,
      spec.lose_condition && `Lose: ${spec.lose_condition}`,
    ]
      .filter(Boolean)
      .join("\n");
  } catch {
    return state.project?.game_hint || state.project?.inferred_game_hint || "";
  }
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.detail || "请求失败");
  }
  return data;
}

async function consumeNdjson(response, handlers) {
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || "流式请求失败");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop();

    for (const line of lines) {
      if (!line.trim()) continue;
      const event = JSON.parse(line);
      if (event.event === "delta") handlers.onDelta?.(event.data);
      if (event.event === "full") handlers.onFull?.(event.data);
      if (event.event === "module_delta") handlers.onModuleDelta?.(event.data);
      if (event.event === "think_delta") handlers.onThinkDelta?.(event.data);
      if (event.event === "validation") handlers.onValidation?.(event.data);
      if (event.event === "final") handlers.onFinal?.(event.data);
      if (event.event === "meta") handlers.onMeta?.(event.data);
      if (event.event === "error") throw new Error(event.data);
    }
  }
}

async function loadProjects() {
  const response = await fetch("/api/projects");
  const data = await response.json();
  if (!response.ok) throw new Error(data.detail || "加载 Project 失败");
  state.projects = data.projects || [];
  renderProjectList();
  if (!state.projectId && state.projects.length) {
    await loadProject(state.projects[0].id);
  }
}

async function loadProject(projectId) {
  const response = await fetch(`/api/projects/${projectId}`);
  const project = await response.json();
  if (!response.ok) throw new Error(project.detail || "加载 Project 失败");
  restoreProject(project);
}

async function refreshCurrentProject() {
  if (!state.projectId) return;
  await loadProject(state.projectId);
  await loadProjects();
}

async function uploadVideo(file) {
  const formData = new FormData();
  formData.append("file", file);
  setStatus("上传中");
  $("#gameHintInput").value = "";

  const response = await fetch("/api/projects/upload", { method: "POST", body: formData });
  const project = await response.json();
  if (!response.ok) throw new Error(project.detail || "上传失败");

  await loadProjects();
  restoreProject(project);
  setView("frames");
  setStatus("Project 已创建");
}

async function extractFrames() {
  if (!state.projectId) return;
  setStatus("抽帧中");
  $("#extractFramesBtn").disabled = true;
  const data = await postJson(`/api/projects/${state.projectId}/extract`, {
    max_frames: Number($("#frameCountInput").value),
  });
  restoreProject(data.project);
  renderFrames(data.frames);
  setView("frames");
  $("#extractFramesBtn").disabled = false;
}

async function loadHintInput() {
  const data = await postJson(`/api/projects/${state.projectId}/hint/input`, getHintRequest());
  $("#hintSystemPrompt").textContent = data.system_prompt;
  $("#hintUserPrompt").textContent = data.user_prompt;
  toast(`步骤 1 将发送 ${data.frame_count} 张抽帧图片给模型`);
}

async function loadSpecInput() {
  const data = await postJson(`/api/projects/${state.projectId}/spec/input`, getSpecRequest());
  $("#specSystemPrompt").textContent = data.system_prompt;
  $("#specUserPrompt").textContent = data.user_prompt;
  toast("步骤 2 为纯文本 + JSON 模式，不再发送图片");
}

async function generateGameplayHint() {
  setView("spec");
  const outputEl = $("#hintStreamOutput");
  const progress = beginStreamProgress({
    outputEl,
    statusBase: "生成玩法提示",
    initialMessage: "正在发送请求...",
  });
  $("#generateHintBtn").disabled = true;

  try {
    const response = await fetch(`/api/projects/${state.projectId}/hint/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getHintRequest()),
    });

    progress.showStatus("已连接，等待模型分析抽帧...");

    let raw = "";
    let thinkingRaw = "";
    const renderHintStream = () => {
      appendStreamOutput(outputEl, raw ? `[JSON 输出]\n${raw}` : "");
    };

    await consumeNdjson(response, {
      onMeta(data) {
        progress.showStatus(streamStatusMessage(data));
      },
      onDelta(delta) {
        raw += delta;
        renderHintStream();
        setStatus(`生成玩法提示 · ${progress.elapsed()}`);
      },
      onFinal(data) {
        $("#gameHintInput").value = data.game_hint;
        appendStreamOutput(outputEl, `[玩法提示]\n${data.game_hint}`);
        restoreProject(data.project);
        setView("spec");
        progress.stop("玩法提示已生成");
      },
    });
  } catch (error) {
    progress.stop("玩法提示生成失败");
    throw error;
  } finally {
    $("#generateHintBtn").disabled = false;
  }
}

async function generateSpec() {
  const gameplayHint = $("#gameHintInput").value.trim();
  if (!gameplayHint) {
    toast("请先生成或手动填写玩法提示");
    return;
  }

  setView("spec");
  const outputEl = $("#specStreamOutput");
  const progress = beginStreamProgress({
    outputEl,
    statusBase: "生成 GameSpec",
    initialMessage: "正在发送请求...",
  });
  $("#generateSpecBtn").disabled = true;

  try {
    const response = await fetch(`/api/projects/${state.projectId}/spec/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(getSpecRequest()),
    });

    progress.showStatus("已连接，等待服务器准备模型输入...");

    let raw = "";
    const renderSpecStream = () => {
      if (raw) appendStreamOutput(outputEl, `[GameSpec JSON]\n${raw}`);
    };

    await consumeNdjson(response, {
      onMeta(data) {
        progress.showStatus(streamStatusMessage(data));
      },
      onDelta(delta) {
        raw += delta;
        renderSpecStream();
        setStatus(`生成 GameSpec · ${progress.elapsed()}`);
      },
      onFull(data) {
        raw = data;
        renderSpecStream();
      },
      onFinal(data) {
        $("#specEditor").value = JSON.stringify(data.game_spec, null, 2);
        restoreProject(data.project);
        setView("spec");
        progress.stop("GameSpec 已生成");
      },
    });
  } catch (error) {
    progress.stop("GameSpec 生成失败");
    throw error;
  } finally {
    $("#generateSpecBtn").disabled = false;
  }
}

async function editSpecWithChat() {
  const userMessage = $("#chatInput").value.trim();
  if (!userMessage) return;

  const currentSpec = parseSpecEditor();
  const outputEl = $("#chatStreamOutput");
  const progress = beginStreamProgress({
    outputEl,
    statusBase: "修改 GameSpec",
    initialMessage: "正在发送修改请求...",
  });
  $("#chatEditBtn").disabled = true;

  try {
    const response = await fetch(`/api/projects/${state.projectId}/spec/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        model: $("#modelInput").value.trim(),
        current_spec: currentSpec,
        user_message: userMessage,
      }),
    });

    let raw = "";
    await consumeNdjson(response, {
      onMeta(data) {
        progress.showStatus(streamStatusMessage(data));
      },
      onDelta(delta) {
        raw += delta;
        appendStreamOutput(outputEl, raw);
        setStatus(`修改 GameSpec · ${progress.elapsed()}`);
      },
      onFinal(data) {
        $("#specEditor").value = JSON.stringify(data.game_spec, null, 2);
        $("#chatInput").value = "";
        restoreProject(data.project);
        setView("spec");
        progress.stop("GameSpec 修改完成");
      },
    });
  } catch (error) {
    progress.stop("GameSpec 修改失败");
    throw error;
  } finally {
    $("#chatEditBtn").disabled = false;
  }
}

async function loadHtmlInput() {
  const gameSpec = parseSpecEditor();
  const data = await postJson(`/api/projects/${state.projectId}/html/input`, {
    provider: getHtmlProvider(),
    model: getHtmlModel(),
    game_spec: gameSpec,
  });
  $("#htmlSystemPrompt").textContent = data.system_prompt;
  $("#htmlUserPrompt").textContent = data.user_prompt;
}

async function generateHtml() {
  const gameSpec = parseSpecEditor();
  setView("html");
  const outputEl = $("#htmlStreamOutput");
  const progress = beginStreamProgress({
    outputEl,
    statusBase: "生成 HTML",
    initialMessage: `请求已发送，正在连接后端并准备调用 ${htmlProviderLabel()}...`,
  });
  const generateBtn = $("#generateHtmlBtn");
  const cancelBtn = $("#cancelHtmlBtn");
  const controller = new AbortController();
  state.htmlAbortController = controller;
  const originalButtonText = generateBtn.textContent;
  generateBtn.disabled = true;
  generateBtn.textContent = "生成中...";
  cancelBtn.hidden = false;
  cancelBtn.disabled = false;
  $("#gamePreview").removeAttribute("src");

  try {
    const response = await fetch(`/api/projects/${state.projectId}/html/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        provider: getHtmlProvider(),
        model: getHtmlModel(),
        game_spec: gameSpec,
      }),
    });

    progress.showStatus(`已连接后端，等待 ${htmlProviderLabel()} 返回 HTML token...`);
    let raw = "";
    let thinkingRaw = "";
    const modules = new Map();
    const moduleModes = new Map();
    const validations = new Map();
    const renderHtmlOutput = () => {
      const parts = [];
      if (thinkingRaw) parts.push(`[模型思考]\n${thinkingRaw}`);
      const attempts = new Set([...modules.keys(), ...validations.keys()]);
      [...attempts].sort((a, b) => a - b).forEach((attempt) => {
        if (modules.has(attempt)) {
          const mode = moduleModes.get(attempt);
          const label = mode === "full_html"
            ? "game_step_00.html"
            : `module_attempt_${String(attempt).padStart(2, "0")}.js`;
          parts.push(`[${label}]\n${modules.get(attempt)}`);
        }
        if (validations.has(attempt)) {
          parts.push(`[validation_${String(attempt).padStart(2, "0")}]\n${validations.get(attempt)}`);
        }
      });
      if (raw) parts.push(`[最终 HTML]\n${raw}`);
      appendStreamOutput(outputEl, parts.join("\n\n"));
    };
    await consumeNdjson(response, {
      onMeta(data) {
        progress.showStatus(streamStatusMessage(data));
      },
      onModuleDelta(data) {
        const attempt = typeof data === "object" ? data.attempt || 1 : 1;
        const delta = typeof data === "object" ? data.delta || "" : data;
        const mode = typeof data === "object" ? data.mode || "module" : "module";
        moduleModes.set(attempt, mode);
        modules.set(attempt, (modules.get(attempt) || "") + delta);
        renderHtmlOutput();
        setStatus(`生成 HTML · ${progress.elapsed()}`);
      },
      onThinkDelta(delta) {
        thinkingRaw += delta;
        renderHtmlOutput();
      },
      onValidation(data) {
        const attempt = data.attempt || 1;
        const status = data.ok ? "PASS" : `FAIL (${data.stage || "unknown"})`;
        validations.set(attempt, `${status}\n${data.message || ""}`);
        renderHtmlOutput();
        setStatus(`校验模块 · ${attempt} · ${progress.elapsed()}`);
      },
      onDelta(delta) {
        raw += delta;
        renderHtmlOutput();
        setStatus(`生成 HTML · ${progress.elapsed()}`);
      },
      onFull(data) {
        raw = data;
        renderHtmlOutput();
      },
      onFinal(data) {
        outputEl.textContent = data.html;
        restoreProject(data.project);
        $("#gamePreview").src = `${data.preview_url}?t=${Date.now()}`;
        $("#downloadLink").href = data.download_url;
        $("#downloadLink").classList.remove("disabled");
        setView("html");
        progress.stop("HTML 已生成");
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      progress.stop("HTML 生成已终止");
      appendStreamOutput(outputEl, `${outputEl.textContent}\n\n[已终止]\n用户终止了本次 HTML 生成。`);
      return;
    }
    progress.stop("HTML 生成失败");
    throw error;
  } finally {
    if (state.htmlAbortController === controller) {
      state.htmlAbortController = null;
    }
    cancelBtn.hidden = true;
    cancelBtn.disabled = true;
    generateBtn.disabled = false;
    generateBtn.textContent = originalButtonText;
  }
}

async function editHtmlWithChat() {
  const userMessage = $("#htmlChatInput").value.trim();
  if (!userMessage) return;

  let currentHtml;
  try {
    currentHtml = await getCurrentHtml();
  } catch (error) {
    toast(error.message);
    return;
  }

  const outputEl = $("#htmlChatStreamOutput");
  const progress = beginStreamProgress({
    outputEl,
    statusBase: "修复 HTML",
    initialMessage: "正在发送修复请求...",
  });
  const controller = new AbortController();
  state.htmlChatAbortController = controller;
  $("#htmlChatEditBtn").disabled = true;
  $("#cancelHtmlChatBtn").hidden = false;
  $("#cancelHtmlChatBtn").disabled = false;

  try {
    const response = await fetch(`/api/projects/${state.projectId}/html/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      signal: controller.signal,
      body: JSON.stringify({
        provider: getHtmlProvider(),
        model: getHtmlModel(),
        current_html: currentHtml,
        gameplay_hint: getGameplayHint(),
        user_message: userMessage,
      }),
    });

    progress.showStatus("已连接，正在准备修复 prompt...");

    let raw = "";
    let thinkingRaw = "";
    const renderFixOutput = () => {
      const parts = [];
      if (thinkingRaw) parts.push(`[模型思考]\n${thinkingRaw}`);
      if (raw) parts.push(`[修复后 HTML]\n${raw}`);
      appendStreamOutput(outputEl, parts.join("\n\n"));
    };
    await consumeNdjson(response, {
      onMeta(data) {
        progress.showStatus(streamStatusMessage(data));
      },
      onThinkDelta(delta) {
        thinkingRaw += delta;
        renderFixOutput();
      },
      onDelta(delta) {
        raw += delta;
        renderFixOutput();
        setStatus(`修复 HTML · ${progress.elapsed()}`);
      },
      onFull(data) {
        raw = data;
        renderFixOutput();
      },
      onFinal(data) {
        $("#htmlStreamOutput").textContent = data.html;
        $("#htmlChatInput").value = "";
        restoreProject(data.project);
        $("#gamePreview").src = `${data.preview_url}?t=${Date.now()}`;
        $("#downloadLink").href = data.download_url;
        $("#downloadLink").classList.remove("disabled");
        setView("html");
        progress.stop("HTML 修复完成");
      },
    });
  } catch (error) {
    if (isAbortError(error)) {
      progress.stop("HTML 修复已终止");
      appendStreamOutput(outputEl, `${outputEl.textContent}\n\n[已终止]\n用户终止了本次 HTML 修复。`);
      return;
    }
    progress.stop("HTML 修复失败");
    throw error;
  } finally {
    if (state.htmlChatAbortController === controller) {
      state.htmlChatAbortController = null;
    }
    $("#cancelHtmlChatBtn").hidden = true;
    $("#cancelHtmlChatBtn").disabled = true;
    $("#htmlChatEditBtn").disabled = false;
  }
}

document.querySelectorAll(".step").forEach((button) => {
  button.addEventListener("click", () => setView(button.dataset.step));
});

$("#refreshProjectsBtn").addEventListener("click", async () => {
  try {
    await loadProjects();
    toast("Project 列表已刷新");
  } catch (error) {
    toast(error.message);
  }
});

$("#videoInput").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  try {
    await uploadVideo(file);
  } catch (error) {
    setStatus("上传失败");
    toast(error.message);
  }
});

$("#extractFramesBtn").addEventListener("click", async () => {
  try {
    await extractFrames();
  } catch (error) {
    setStatus("抽帧失败");
    $("#extractFramesBtn").disabled = false;
    toast(error.message);
  }
});

$("#loadHintInputBtn").addEventListener("click", async () => {
  try {
    await loadHintInput();
  } catch (error) {
    toast(error.message);
  }
});

$("#generateHintBtn").addEventListener("click", async () => {
  try {
    await generateGameplayHint();
  } catch (error) {
    setStatus("玩法提示生成失败");
    $("#generateHintBtn").disabled = false;
    toast(error.message);
  }
});

$("#loadSpecInputBtn").addEventListener("click", async () => {
  try {
    await loadSpecInput();
  } catch (error) {
    toast(error.message);
  }
});

$("#generateSpecBtn").addEventListener("click", async () => {
  try {
    await generateSpec();
  } catch (error) {
    setStatus("GameSpec 生成失败");
    $("#generateSpecBtn").disabled = false;
    toast(error.message);
  }
});

$("#validateSpecBtn").addEventListener("click", () => {
  try {
    parseSpecEditor();
    toast("JSON 格式有效");
  } catch (error) {
    toast(error.message);
  }
});

$("#chatEditBtn").addEventListener("click", async () => {
  try {
    await editSpecWithChat();
  } catch (error) {
    setStatus("修改失败");
    $("#chatEditBtn").disabled = false;
    toast(error.message);
  }
});

$("#loadHtmlInputBtn").addEventListener("click", async () => {
  try {
    await loadHtmlInput();
  } catch (error) {
    toast(error.message);
  }
});

$("#htmlProviderInput").addEventListener("change", () => {
  const modelInput = $("#htmlModelInput");
  const current = modelInput.value.trim();
  if (getHtmlProvider() === "deepseek" && (!current || current === "gemma4:e4b")) {
    modelInput.value = "deepseek-v4-pro";
  }
  if (getHtmlProvider() === "ollama" && (!current || current === "deepseek-v4-pro")) {
    modelInput.value = "gemma4:e4b";
  }
});

$("#generateHtmlBtn").addEventListener("click", async () => {
  try {
    await generateHtml();
  } catch (error) {
    setStatus("HTML 生成失败");
    $("#generateHtmlBtn").disabled = false;
    toast(error.message);
  }
});

$("#cancelHtmlBtn").addEventListener("click", () => {
  state.htmlAbortController?.abort();
});

$("#htmlChatEditBtn").addEventListener("click", async () => {
  try {
    await editHtmlWithChat();
  } catch (error) {
    setStatus("HTML 修复失败");
    $("#htmlChatEditBtn").disabled = false;
    toast(error.message);
  }
});

$("#cancelHtmlChatBtn").addEventListener("click", () => {
  state.htmlChatAbortController?.abort();
});

loadProjects()
  .then(() => setActionState())
  .catch((error) => {
    setStatus("Project 加载失败");
    toast(error.message);
  });
