function renderLineChart(values, config = {}) {
  const width = 600;
  const height = 180;
  const padding = 18;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || 1;

  const points = values
    .map((value, index) => {
      const x = padding + (index / Math.max(values.length - 1, 1)) * (width - padding * 2);
      const y = height - padding - ((value - min) / range) * (height - padding * 2);
      return `${x},${y}`;
    })
    .join(' ');

  const baseline = height - padding;
  const areaPoints = `0,${baseline} ${points} ${width},${baseline}`;

  return `
    <svg viewBox="0 0 ${width} ${height}" class="chart-svg" preserveAspectRatio="none" aria-label="chart">
      <defs>
        <linearGradient id="${config.gradientId || 'lineGradient'}" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="${config.color}" stop-opacity="0.35"></stop>
          <stop offset="100%" stop-color="${config.color}" stop-opacity="0.02"></stop>
        </linearGradient>
      </defs>
      <polyline points="${areaPoints}" fill="url(#${config.gradientId || 'lineGradient'})" opacity="0.9"></polyline>
      <polyline points="${points}" fill="none" stroke="${config.color}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"></polyline>
    </svg>
  `;
}

async function loadDashboard() {
  const [mockResponse, datasetResponse] = await Promise.all([
    fetch('mock_data.json').catch(() => null),
    fetch('data/tunnel_day_dataset.json')
  ]);

  const mock = mockResponse ? await mockResponse.json() : null;
  const data = await datasetResponse.json();

  const keyPoint = data.sensor_series.filter((item) => item.point_id === 'K922+065');
  const temperatures = keyPoint.map((item) => item.temperature_c);
  const coSeries = keyPoint.map((item) => item.co_ppm);
  const latestTemp = temperatures[temperatures.length - 1] ?? 0;
  const latestCo = coSeries[coSeries.length - 1] ?? 0;
  const avgTemp = (temperatures.reduce((sum, value) => sum + value, 0) / temperatures.length).toFixed(1);
  const peakCo = Math.max(...coSeries).toFixed(1);

  const timestamp = document.getElementById('timestamp');
  timestamp.textContent = `更新时间：${new Date().toLocaleString('zh-CN', { hour12: false })}`;

  const metrics = [
    { label: '当前风险等级', value: data.risk_summary.current_risk_level, trend: '+0.4 等级', type: 'warning' },
    { label: '设备在线率', value: '98.7%', trend: '+1.8%', type: 'success' },
    { label: '平均温度', value: `${avgTemp}℃`, trend: `${latestTemp.toFixed(1)}℃ 当前`, type: 'info' },
    { label: 'CO峰值', value: `${peakCo} ppm`, trend: `${latestCo.toFixed(1)}ppm 当前`, type: 'danger' }
  ];

  const metricContainer = document.getElementById('metrics');
  metricContainer.innerHTML = metrics
    .map(
      (metric) => `
        <article class="metric-card ${metric.type}">
          <div class="metric-header">
            <span>${metric.label}</span>
            <span class="dot online"></span>
          </div>
          <div class="metric-value">${metric.value}</div>
          <span class="metric-trend">${metric.trend}</span>
        </article>
      `
    )
    .join('');

  document.getElementById('current-risk').textContent = data.risk_summary.current_risk_level;
  document.getElementById('co-value').textContent = `${latestCo.toFixed(1)} ppm`;
  document.getElementById('fan-status').textContent = '正常';
  document.getElementById('coverage').textContent = '96.4%';

  const riskBars = document.getElementById('risk-bars');
  const riskCounts = data.risk_summary.risk_counts || { L0: 18, L1: 9, L2: 3, L3: 1 };
  const total = Object.values(riskCounts).reduce((sum, value) => sum + value, 0) || 1;
  riskBars.innerHTML = Object.entries(riskCounts)
    .map(([level, count]) => {
      const width = (count / total) * 100;
      return `
        <div class="risk-row">
          <span class="risk-label">${level}</span>
          <div class="bar-track">
            <div class="bar-fill ${level.toLowerCase()}" style="width:${width}%"></div>
          </div>
          <strong>${count}</strong>
        </div>
      `;
    })
    .join('');

  const routing = document.getElementById('routing');
  const routeConfig = mock?.routing || [];
  routing.innerHTML = routeConfig
    .map(
      (item) => `
        <div class="route-item">
          <div class="route-meta">
            <div class="workflow-index">${item.id}</div>
            <div>
              <span class="route-name">${item.name}</span>
              <span class="route-desc">${item.description}</span>
            </div>
          </div>
          <span class="route-pill ${item.priorityClass}">${item.priority}</span>
        </div>
      `
    )
    .join('');

  const workflow = document.getElementById('workflow');
  const workflowConfig = mock?.workflow || [];
  workflow.innerHTML = workflowConfig
    .map(
      (item) => `
        <div class="workflow-item">
          <div class="workflow-index">${item.step}</div>
          <div>
            <strong>${item.title}</strong>
            <span>${item.detail}</span>
          </div>
        </div>
      `
    )
    .join('');

  const eventTable = document.getElementById('event-table');
  eventTable.innerHTML = data.events
    .map(
      (event) => `
        <tr>
          <td>${event.event_id}</td>
          <td>${event.point_id}</td>
          <td>${event.event_type}</td>
          <td><span class="badge ${event.risk_level.toLowerCase()}">${event.risk_level}</span></td>
          <td class="status-text">${event.status}</td>
          <td>${event.evidence_chain.length ? event.evidence_chain.map((item) => item.type).join(' + ') : '无'}</td>
        </tr>
      `
    )
    .join('');

  const modelTable = document.getElementById('model-table');
  const modelMatrix = mock?.modelMatrix || [];
  modelTable.innerHTML = modelMatrix
    .map(
      (row) => `
        <tr>
          <td>${row.task}</td>
          <td>${row.model}</td>
          <td>${row.strategy}</td>
          <td>${row.reason}</td>
        </tr>
      `
    )
    .join('');

  const tempChart = document.getElementById('temperature-chart');
  tempChart.innerHTML = renderLineChart(temperatures.slice(-60), { color: '#5bb2ff', gradientId: 'tempGradient' });

  const coChart = document.getElementById('co-chart');
  coChart.innerHTML = renderLineChart(coSeries.slice(-60), { color: '#ffb25e', gradientId: 'coGradient' });
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, (character) => ({
    '&': '&amp;',
    '<': '&lt;',
    '>': '&gt;',
    '"': '&quot;',
    "'": '&#39;'
  })[character]);
}

async function fetchJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`请求失败 (${response.status})`);
  return response.json();
}

function formatNumber(value) {
  return Number.isFinite(value)
    ? value.toLocaleString('zh-CN', { maximumFractionDigits: 3 })
    : '--';
}

function formatFileSize(bytes) {
  if (bytes >= 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${bytes} B`;
}

function renderRealMetrics(overview) {
  const metricCards = ['CO', 'VI', 'WS', 'LA'].map((code) => {
    const metric = overview.metrics[code];
    return {
      label: metric.label,
      value: formatNumber(metric.latest_value),
      detail: metric.latest_timestamp
        ? `${metric.latest_timestamp} · ${metric.latest_station_count} 个测点`
        : '暂无实测记录',
      tone: code.toLowerCase()
    };
  });
  const faults = overview.fault_summary;
  metricCards.push({
    label: '设备故障记录',
    value: formatNumber(faults.total),
    detail: `${faults.recovered} 条已恢复 · ${faults.unresolved} 条未恢复`,
    tone: 'fault'
  });

  document.getElementById('real-metrics').innerHTML = metricCards.map((metric) => `
    <article class="real-metric ${metric.tone}">
      <span>${escapeHtml(metric.label)}</span>
      <strong>${escapeHtml(metric.value)}</strong>
      <small>${escapeHtml(metric.detail)}</small>
    </article>
  `).join('');

  const latestTimes = Object.values(overview.metrics)
    .map((metric) => metric.latest_timestamp)
    .filter(Boolean)
    .sort();
  document.getElementById('real-data-status').textContent = latestTimes.length
    ? `实测资料截至 ${latestTimes[latestTimes.length - 1]}`
    : '未找到可读取的实测记录';
}

function renderSourceFiles(files) {
  const list = document.getElementById('source-files');
  document.getElementById('source-count').textContent = `${files.length} 个文件`;
  list.innerHTML = files.map((file) => `
    <li>
      <span class="source-file-meta">
        <strong>${escapeHtml(file.name)}</strong>
        <small>${escapeHtml(file.category)} · ${formatFileSize(file.size_bytes)}</small>
      </span>
      <a href="${escapeHtml(file.url)}" download="${escapeHtml(file.name)}" aria-label="下载 ${escapeHtml(file.name)}">下载</a>
    </li>
  `).join('');
}

function renderFaults(data) {
  document.getElementById('fault-total').textContent = `${data.total} 条 · ${data.unresolved} 条未恢复`;
  document.getElementById('real-fault-table').innerHTML = data.events.map((event) => `
    <tr>
      <td>${escapeHtml(event.time.replace('T', ' '))}</td>
      <td>${escapeHtml(event.device)}<small class="table-subtext">${escapeHtml(event.category)} · ${escapeHtml(event.code)}</small></td>
      <td>${escapeHtml(event.station)}</td>
      <td>${escapeHtml(event.description)}</td>
      <td><span class="badge ${event.recovered ? 'l1' : 'l3'}">${event.recovered ? '已恢复' : '未恢复'}</span></td>
    </tr>
  `).join('') || '<tr><td colspan="5" class="empty-cell">暂无该隧道的设备故障记录</td></tr>';
}

async function loadEnvironment(overview) {
  const metricSelect = document.getElementById('metric-select');
  const stationSelect = document.getElementById('station-select');
  const metricCode = metricSelect.value;
  const metric = overview.metrics[metricCode];
  const previousStation = stationSelect.value;
  const preferredStation = metric.stations.find((station) => station.startsWith('YK')) || metric.stations[0];
  const selectedStation = metric.stations.includes(previousStation) ? previousStation : preferredStation;

  stationSelect.replaceChildren(...metric.stations.map((station) => {
    const option = document.createElement('option');
    option.value = station;
    option.textContent = station;
    return option;
  }));
  stationSelect.value = selectedStation || '';

  const query = new URLSearchParams({ metric: metricCode, limit: '1000' });
  if (selectedStation) query.set('station', selectedStation);
  const data = await fetchJson(`/api/v1/real-data/environment?${query}`);
  const records = data.records;
  const values = records.map((record) => record.value);
  const chart = document.getElementById('real-environment-chart');
  chart.innerHTML = values.length
    ? renderLineChart(values, { color: '#52d1bd', gradientId: 'realDataGradient' })
    : '<div class="empty-chart">该测点暂无对应指标记录</div>';

  document.getElementById('environment-source').textContent = `${data.source_file} · ${data.label} · 原表记录值`;
  document.getElementById('environment-count').textContent = `${data.count} 条原始记录`;
  document.getElementById('environment-latest').textContent = records.length
    ? `最近采样 ${records[records.length - 1].timestamp}`
    : '采样时间 --';
}

function videoContentRect(video) {
  const elementWidth = video.clientWidth;
  const elementHeight = video.clientHeight;
  const videoRatio = video.videoWidth / video.videoHeight;
  const elementRatio = elementWidth / elementHeight;
  if (!video.videoWidth || !video.videoHeight || !elementWidth || !elementHeight) {
    return { x: 0, y: 0, width: elementWidth, height: elementHeight };
  }
  if (elementRatio > videoRatio) {
    const height = elementHeight;
    const width = height * videoRatio;
    return { x: (elementWidth - width) / 2, y: 0, width, height };
  }
  const width = elementWidth;
  const height = width / videoRatio;
  return { x: 0, y: (elementHeight - height) / 2, width, height };
}

function drawDetectionBoxes(video, canvas, data) {
  const context = canvas.getContext('2d');
  const width = video.clientWidth;
  const height = video.clientHeight;
  if (canvas.width !== width || canvas.height !== height) {
    canvas.width = width;
    canvas.height = height;
  }
  context.clearRect(0, 0, width, height);
  if (!data?.samples?.length || video.readyState < 1) return;

  const hold = data.hold_seconds || 0.1;
  let sample = null;
  for (const item of data.samples) {
    if (item.time <= video.currentTime + 0.001) sample = item;
    else break;
  }
  if (!sample || video.currentTime - sample.time > hold) return;

  const rect = videoContentRect(video);
  context.lineWidth = 2;
  context.font = '12px sans-serif';
  for (const box of sample.boxes) {
    const x = rect.x + box.x1 * rect.width;
    const y = rect.y + box.y1 * rect.height;
    const boxWidth = (box.x2 - box.x1) * rect.width;
    const boxHeight = (box.y2 - box.y1) * rect.height;
    const color = box.class_name === 'person' ? '#ffb25e' : '#5ce3d5';
    context.strokeStyle = color;
    context.strokeRect(x, y, boxWidth, boxHeight);
    const caption = `${box.label} ${Math.round(box.confidence * 100)}%`;
    const textWidth = context.measureText(caption).width;
    const labelY = Math.max(rect.y, y - 16);
    context.fillStyle = 'rgba(2, 7, 10, 0.75)';
    context.fillRect(x, labelY, textWidth + 8, 16);
    context.fillStyle = color;
    context.fillText(caption, x + 4, labelY + 12);
  }
}

let detectionRequest = 0;

function detachDetections(video) {
  if (!video._detectionDraw) return;
  video.removeEventListener('timeupdate', video._detectionDraw);
  video.removeEventListener('seeked', video._detectionDraw);
  video.removeEventListener('loadeddata', video._detectionDraw);
  window.removeEventListener('resize', video._detectionDraw);
  video._detectionDraw = null;
}

async function attachDetections(video, fileName) {
  const details = document.getElementById('video-details');
  const sizeText = details.textContent.split(' · YOLO')[0].split(' · 检测框')[0].split(' · 正在用')[0];
  const requestId = ++detectionRequest;
  details.textContent = `${sizeText} · 正在用 YOLO 标注检测框`;
  detachDetections(video);
  const canvas = document.getElementById('video-overlay');
  canvas.getContext('2d').clearRect(0, 0, canvas.width, canvas.height);
  try {
    const data = await fetchJson(`/api/v1/videos/detections?video=${encodeURIComponent(fileName)}`);
    if (requestId !== detectionRequest) return;
    if (data.status !== 'ok') throw new Error(data.detail || '检测结果不可用');
    const draw = () => drawDetectionBoxes(video, canvas, data);
    video._detectionDraw = draw;
    video.addEventListener('timeupdate', draw);
    video.addEventListener('seeked', draw);
    video.addEventListener('loadeddata', draw);
    window.addEventListener('resize', draw);
    draw();
    const boxCount = data.samples.reduce((sum, sample) => sum + sample.boxes.length, 0);
    details.textContent = `${sizeText} · YOLO 检测框 ${boxCount} 个`;
  } catch (error) {
    if (requestId !== detectionRequest) return;
    details.textContent = `${sizeText} · 检测框未能生成`;
    console.error(error);
  }
}

let currentVideoName = '';
let reviewState = { findings: [], source: '', offline: '', routingPlan: [] };
let routingInFlight = false;

function playVideoFile(videoFile) {
  currentVideoName = videoFile.name;
  const video = document.getElementById('video-player');
  const empty = document.getElementById('video-empty');
  video.classList.remove('hidden');
  empty.classList.add('hidden');
  document.getElementById('video-name').textContent = videoFile.name.includes('演示')
    ? `${videoFile.name}（模拟）`
    : videoFile.name;
  const describe = () => `${formatFileSize(videoFile.size_bytes)} · ${video.videoWidth || 1280} × ${video.videoHeight || 720}${video.duration ? ` · ${Math.round(video.duration)} 秒` : ''}`;
  document.getElementById('video-details').textContent = describe();
  video.addEventListener('loadedmetadata', () => {
    document.getElementById('video-details').textContent = describe();
    attachDetections(video, videoFile.name);
  }, { once: true });
  video.src = videoFile.url;
  video.load();
}

function renderVideo(files) {
  const videos = files.filter((file) => file.category === '视频' && file.name.toLowerCase().endsWith('.mp4') && !file.name.includes('.detections'));
  const video = document.getElementById('video-player');
  const empty = document.getElementById('video-empty');
  const select = document.getElementById('video-select');
  const preferred = videos.find((file) => file.name.includes('演示')) || videos[0];
  if (!preferred) {
    video.classList.add('hidden');
    empty.classList.remove('hidden');
    select.classList.add('hidden');
    document.getElementById('video-name').textContent = '暂无可播放视频';
    return;
  }
  if (videos.length > 1) {
    select.classList.remove('hidden');
    select.innerHTML = videos.map((file) => `<option value="${escapeHtml(file.name)}">${escapeHtml(file.name)}</option>`).join('');
    select.value = preferred.name;
    select.onchange = () => {
      const next = videos.find((file) => file.name === select.value);
      if (next) playVideoFile(next);
    };
  } else {
    select.classList.add('hidden');
  }
  playVideoFile(preferred);
}

async function loadRealData() {
  const status = document.getElementById('real-data-status');
  try {
    const [overview, faults] = await Promise.all([
      fetchJson('/api/v1/real-data/overview'),
      fetchJson('/api/v1/real-data/faults?limit=12')
    ]);
    renderRealMetrics(overview);
    renderSourceFiles(overview.files);
    renderFaults(faults);
    renderVideo(overview.files);
    await loadEnvironment(overview);

    document.getElementById('metric-select').addEventListener('change', () => {
      resetMomaSession('测点范围已变化，请重新提交。');
      loadEnvironment(overview);
    });
    document.getElementById('station-select').addEventListener('change', () => {
      resetMomaSession('测点范围已变化，请重新提交。');
      loadEnvironment(overview);
    });
  } catch (error) {
    status.textContent = '真实资料加载失败，请确认使用项目服务启动';
    document.getElementById('real-environment-chart').innerHTML = '<div class="empty-chart">无法连接真实数据接口</div>';
    document.getElementById('video-empty').classList.remove('hidden');
    document.getElementById('video-player').classList.add('hidden');
    console.error(error);
  }
}

const momaSession = { id: null, turns: [] };
const momaTaskStrategy = { patrol: 'cost', review: 'quality', fusion: 'balanced' };

function resetMomaSession(notice) {
  const hadSession = Boolean(momaSession.id);
  momaSession.id = null;
  momaSession.turns = [];
  document.getElementById('moma-run').textContent = '提交至 MoMA';
  document.getElementById('moma-output').textContent = '分析结果将在此显示。';
  document.getElementById('moma-usage').textContent = '';
  if (notice && hadSession) {
    const status = document.getElementById('moma-status');
    status.classList.remove('error');
    status.textContent = notice;
  }
}

function renderMomaTranscript(pendingQuestion, pendingReply) {
  const turns = momaSession.turns.map((turn, index) => `第 ${index + 1} 轮\n问：${turn.question}\n答：${turn.reply}`);
  if (pendingQuestion) {
    turns.push(`第 ${momaSession.turns.length + 1} 轮\n问：${pendingQuestion}\n答：${pendingReply || ''}`);
  }
  document.getElementById('moma-output').textContent = turns.join('\n\n');
}

async function readMomaStream(response, onDelta) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  let result = null;
  const takeEvents = (chunk, flush) => {
    buffer += chunk;
    const blocks = buffer.split('\n\n');
    buffer = flush ? '' : (blocks.pop() || '');
    blocks.forEach((block) => {
      const data = block
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('\n');
      if (!data || data === '[DONE]') return;
      const event = JSON.parse(data);
      if (event.type === 'delta') onDelta(event.text || '');
      else if (event.type === 'done') result = event;
      else if (event.type === 'error') throw new Error(event.detail || 'MoMA 调用失败');
    });
  };
  let live = '';
  const originalOnDelta = onDelta;
  onDelta = (text) => {
    live += text;
    originalOnDelta(live);
  };
  while (true) {
    const { done, value } = await reader.read();
    takeEvents(decoder.decode(value || new Uint8Array(), { stream: !done }), done);
    if (done) break;
  }
  if (!result) throw new Error('MoMA 没有返回完整结论');
  return result;
}

async function loadMomaStatus() {
  const status = document.getElementById('moma-status');
  try {
    const data = await fetchJson('/api/v1/moma/status');
    if (!data.configured) {
      status.classList.add('error');
      status.textContent = `MoMA 尚未配置：${data.missing.join('、')}`;
      return;
    }
    status.classList.remove('error');
    status.textContent = `MoMA 已配置 · 模型 ${data.model} · 单次等待上限 ${data.timeout_seconds} 秒。选择任务后可提交历史数据。`;
  } catch (error) {
    status.classList.add('error');
    status.textContent = '无法读取 MoMA 配置状态，请确认页面由项目服务打开。';
  }
}

async function runMomaAnalysis() {
  const button = document.getElementById('moma-run');
  const status = document.getElementById('moma-status');
  const usage = document.getElementById('moma-usage');
  const question = document.getElementById('moma-question').value.trim();
  if (momaSession.id && !question) {
    status.classList.add('error');
    status.textContent = '继续追问前请先填写问题。';
    return;
  }

  button.disabled = true;
  status.classList.remove('error');
  status.textContent = momaSession.id
    ? '正在沿用本次会话的历史快照，向 MoMA 提交追问…'
    : '正在按所选路由策略向 MoMA 提交历史数据…';
  const asked = question || '请概括当前选择测点的历史数据特征，并给出需要人工复核的事项。';

  try {
    const response = await fetch('/api/v1/moma/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        metric: document.getElementById('metric-select').value,
        station: document.getElementById('station-select').value || null,
        question: question || null,
        strategy: document.getElementById('moma-strategy').value,
        task: document.getElementById('moma-task').value,
        session_id: momaSession.id
      })
    });
    const contentType = response.headers.get('content-type') || '';
    if (!response.ok || !contentType.includes('text/event-stream')) {
      const result = await response.json();
      if (response.status === 409) resetMomaSession();
      throw new Error(result.detail || `请求失败 (${response.status})`);
    }

    const result = await readMomaStream(response, (partial) => {
      status.textContent = '正在接收 MoMA 回复…';
      renderMomaTranscript(asked, partial);
    });
    momaSession.id = result.session_id;
    momaSession.turns.push({
      question: asked,
      reply: result.reply || 'MoMA 未返回文本内容。'
    });
    renderMomaTranscript();
    document.getElementById('moma-question').value = '';
    document.getElementById('moma-run').textContent = '继续追问';
    status.textContent = result.context.reused
      ? '追问完成。本次没有重复发送传感器快照，结果仍需人工复核。'
      : '分析完成。结果基于历史参考数据，需由值守人员复核。可在同一会话里继续追问。';
    const totalTokens = result.usage?.total_tokens;
    usage.textContent = [
      `任务：${result.task.label}`,
      `策略：${result.strategy.label}`,
      `模型：${result.model || 'MoMA 智能路由'}`,
      `第 ${result.turn} 轮`,
      result.context.reused ? '已复用上下文' : `上下文：${result.context.sensor_records} 条传感器记录、${result.context.fault_records} 条故障记录`,
      Number.isFinite(totalTokens) ? `Token：${totalTokens}` : '',
      Number.isFinite(result.elapsed_ms) ? `耗时：${(result.elapsed_ms / 1000).toFixed(1)} 秒` : ''
    ].filter(Boolean).join(' · ');
  } catch (error) {
    status.classList.add('error');
    const timedOut = /timed out|timeout/i.test(error.message);
    status.textContent = timedOut
      ? 'MoMA 模型响应超时，尚未收到分析结果。'
      : `MoMA 调用失败：${error.message}`;
    if (!momaSession.turns.length) {
      const needsConfig = /not configured|MOMA_/.test(error.message);
      document.getElementById('moma-output').textContent = timedOut
        ? '请稍后查看平台状态后再试；不要连续提交，以免重复消耗调用额度。可通过 MOMA_TIMEOUT_SECONDS 调整等待时间。'
        : (needsConfig ? '请检查本机 .env 中的 MoMA 地址、模型 ID 和已轮换的 API Key。' : error.message);
    }
  } finally {
    button.disabled = false;
  }
}

document.querySelectorAll('.nav-item').forEach((link) => {
  link.addEventListener('click', () => {
    document.querySelectorAll('.nav-item').forEach((item) => item.classList.remove('active'));
    link.classList.add('active');
  });
});

document.getElementById('moma-task').addEventListener('change', (event) => {
  document.getElementById('moma-strategy').value = momaTaskStrategy[event.target.value];
  resetMomaSession('分析任务已切换，请重新提交。');
});
document.getElementById('moma-strategy').addEventListener('change', () => {
  resetMomaSession('路由策略已切换，请重新提交。');
});
function renderFieldCheck(report) {
  const field = report.field_check;
  if (!field) return;
  const co = field.co || {};
  const light = field.light || {};
  document.getElementById('field-check').textContent = [
    field.conclusion,
    `一氧化碳 ${co.records ?? 0} 条，最高 ${co.max ?? '--'}。`,
    `光照 ${light.records ?? 0} 条，最高 ${light.max ?? '--'}。`,
    field.temperature
  ].filter(Boolean).join(' ');
}

function renderRouteBoard(routes, fusion) {
  const board = document.getElementById('route-board');
  const rows = [...(routes || [])];
  if (fusion) rows.push(fusion);
  else if ((routes || []).length >= 2) {
    rows.push({
      category: '多源关联',
      strategy_label: '成本优先',
      task_label: '异常复核',
      reason: '各类结论返回后在这里汇总',
      status: 'pending'
    });
  }
  if (!rows.length) {
    board.innerHTML = '';
    return;
  }
  board.innerHTML = `
    <table>
      <thead>
        <tr><th>类型</th><th>路由</th><th>原因</th><th>平台模型</th><th>结论</th></tr>
      </thead>
      <tbody>
        ${rows.map((route) => {
          const pending = !route.status || route.status === 'pending';
          const grouped = route.status === 'grouped';
          const model = route.status === 'ok'
            ? (route.model || '智能路由')
            : (grouped ? '同一次短调用' : (pending ? '待提交' : '未形成可见结论'));
          const reply = route.reply || (route.status === 'error' ? (route.detail || '未形成可见结论') : (pending ? '尚未调用' : ''));
          return `<tr>
            <td>${escapeHtml(route.category)}</td>
            <td>${escapeHtml(route.strategy_label)} · ${escapeHtml(route.task_label)}${route.max_tokens ? ` · ${route.max_tokens} tokens` : ''}</td>
            <td>${escapeHtml(route.reason || '')}</td>
            <td>${escapeHtml(model)}</td>
            <td>${escapeHtml(reply)}</td>
          </tr>`;
        }).join('')}
      </tbody>
    </table>
  `;
}

function armReview(findings, source, offline, routingPlan) {
  reviewState = {
    findings,
    source,
    offline: offline || reviewState.offline,
    routingPlan: routingPlan || []
  };
  document.getElementById('anomaly-verify').disabled = findings.length === 0;
  document.getElementById('offline-review').disabled = !reviewState.offline;
  renderRouteBoard(reviewState.routingPlan);
}

function renderFindings(findings) {
  const list = document.getElementById('anomaly-findings');
  if (!findings.length) {
    list.innerHTML = '<li><strong>当前列表没有待上报条目</strong><small>现场核对不产生异常。模拟事件或视频停驶判断会显示在这里。</small></li>';
    return;
  }
  list.innerHTML = findings.map((finding) => {
    const reading = finding.unit ? `${finding.value} ${finding.unit}` : finding.value;
    const tag = finding.simulated ? '<em class="demo-tag">模拟</em>' : '';
    return `
    <li class="${finding.simulated ? 'simulated' : ''}">
      <strong>${escapeHtml(finding.label)} · ${escapeHtml(finding.station)}${tag}</strong>
      <small>${escapeHtml(finding.timestamp)} · 读数 ${escapeHtml(reading)} · ${escapeHtml(finding.baseline)}</small>
      <small>${escapeHtml(finding.detail)}</small>
    </li>
  `;
  }).join('');
}

async function scanSensorAnomalies() {
  const button = document.getElementById('anomaly-scan');
  const status = document.getElementById('anomaly-status');
  const output = document.getElementById('anomaly-output');
  button.disabled = true;
  status.classList.remove('error');
  status.textContent = '正在核对现场历史表，并加载单独的模拟事件…';
  output.textContent = '';
  try {
    const report = await fetchJson('/api/v1/anomalies');
    renderFieldCheck(report);
    document.getElementById('finding-caption').textContent = report.findings.length ? '模拟事件' : '';
    renderFindings(report.findings);
    armReview(report.findings, '模拟事件', report.offline_review, report.routing_plan);
    if (!report.findings.length) {
      status.textContent = '现场核对完成，没有异常。未调用 MoMA。';
      return;
    }
    status.textContent = `现场核对完成。发现 ${report.findings.length} 条模拟异常，正在自动提交 MoMA。`;
    await submitReview();
  } catch (error) {
    status.classList.add('error');
    status.textContent = `现场核对失败：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function scanLocalVideo() {
  const button = document.getElementById('video-scan');
  const status = document.getElementById('anomaly-status');
  const output = document.getElementById('anomaly-output');
  button.disabled = true;
  status.classList.remove('error');
  status.textContent = '正在读取与播放器相同的检测结果…';
  output.textContent = '';
  try {
    const query = currentVideoName ? `?video=${encodeURIComponent(currentVideoName)}` : '';
    const response = await fetch(`/api/v1/anomalies/video${query}`, { method: 'POST' });
    const result = await response.json();
    if (!response.ok) throw new Error(result.detail || `请求失败 (${response.status})`);
    if (result.status === 'unavailable' || result.ready === false) {
      status.textContent = result.detail || '视频检测暂不可用。';
      document.getElementById('finding-caption').textContent = '';
      renderFindings([]);
      armReview([], '画面判断', result.offline_review, []);
      return;
    }
    const findings = result.findings || [];
    document.getElementById('finding-caption').textContent = findings.length ? `画面判断 · ${result.video || currentVideoName}` : '';
    renderFindings(findings);
    armReview(findings, '画面判断', result.offline_review, result.routing_plan);
    if (!findings.length) {
      status.textContent = result.reply || '检测结果里没有需要上报的停驶目标。未调用 MoMA。';
      return;
    }
    status.textContent = `发现 ${findings.length} 条画面异常，正在自动提交 MoMA。`;
    await submitReview();
  } catch (error) {
    status.classList.add('error');
    status.textContent = `视频判断失败：${error.message}`;
  } finally {
    button.disabled = false;
  }
}

async function submitReview(refresh) {
  const button = document.getElementById('anomaly-verify');
  const status = document.getElementById('anomaly-status');
  const output = document.getElementById('anomaly-output');
  if (!reviewState.findings.length || routingInFlight) return;
  routingInFlight = true;
  button.disabled = true;
  document.getElementById('anomaly-scan').disabled = true;
  document.getElementById('video-scan').disabled = true;
  status.classList.remove('error');
  status.textContent = '正在提交复核。';
  let waited = false;
  try {
    for (let attempt = 0; attempt < 55; attempt += 1) {
      const response = await fetch('/api/v1/anomalies/route', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          findings: reviewState.findings,
          source: reviewState.source,
          refresh: attempt === 0 && refresh === true
        })
      });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || `请求失败 (${response.status})`);
      renderRouteBoard(result.routes, result.fusion);
      if (result.pending) {
        waited = true;
        if (!output.textContent && reviewState.offline) output.textContent = reviewState.offline;
        status.textContent = '云端复核已发出。先显示备用结论，返回后自动替换。';
        await new Promise((resolve) => setTimeout(resolve, 2000));
        continue;
      }
      if (result.cached && !waited) {
        output.textContent = result.reply || '';
        status.textContent = '已复用云端复核，没有再次调用 MoMA。';
      } else if ((result.fusion && result.fusion.status === 'ok') || (result.cached && result.reply)) {
        output.textContent = result.reply || '';
        status.textContent = '云端复核已返回。类型策略标在表中。结论需要人工确认后再上报。';
      } else if (reviewState.offline) {
        output.textContent = reviewState.offline;
        status.textContent = '云端还没有可见结论。当前显示的是备用结论，不是本次云端返回。';
      } else {
        status.classList.add('error');
        status.textContent = '云端没有可见结论。';
      }
      return;
    }
    if (reviewState.offline && !output.textContent) output.textContent = reviewState.offline;
    status.textContent = '云端仍在处理。当前显示备用结论，不是本次云端返回。';
  } catch (error) {
    status.classList.add('error');
    status.textContent = `MoMA 复核失败：${error.message} 可改用离线结论继续演示。`;
    if (reviewState.offline) output.textContent = reviewState.offline;
  } finally {
    routingInFlight = false;
    button.disabled = reviewState.findings.length === 0;
    document.getElementById('anomaly-scan').disabled = false;
    document.getElementById('video-scan').disabled = false;
  }
}

function showOfflineReview() {
  const status = document.getElementById('anomaly-status');
  const output = document.getElementById('anomaly-output');
  if (!reviewState.offline) return;
  status.classList.remove('error');
  status.textContent = '正在显示演示备用结论，不是本次云端返回。';
  output.textContent = reviewState.offline;
}

document.getElementById('anomaly-scan').addEventListener('click', scanSensorAnomalies);
document.getElementById('video-scan').addEventListener('click', scanLocalVideo);
document.getElementById('anomaly-verify').addEventListener('click', () => submitReview(true));
document.getElementById('offline-review').addEventListener('click', showOfflineReview);
document.getElementById('moma-run').addEventListener('click', runMomaAnalysis);
document.getElementById('moma-reset').addEventListener('click', () => {
  resetMomaSession('已开始新会话。');
  document.getElementById('moma-status').textContent = '已开始新会话。选择测点后可重新提交。';
});
loadMomaStatus();

loadDashboard().catch((error) => {
  document.getElementById('timestamp').textContent = '方案演示样例暂不可用';
  console.error(error);
});
loadRealData();
