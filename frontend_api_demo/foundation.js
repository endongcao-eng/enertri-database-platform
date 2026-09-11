const Foundation = { poller: null };

function taskStatusLabel(status) {
  return ({queued:'排队中',running:'运行中',succeeded:'已完成',failed:'失败',cancelled:'已取消'})[status] || status;
}
function taskStatusClass(status) {
  return ({queued:'warning',running:'primary',succeeded:'success',failed:'danger',cancelled:'muted'})[status] || '';
}
function formatBytes(bytes) {
  const n = Number(bytes || 0); if (n < 1024) return `${n} B`; if (n < 1024*1024) return `${(n/1024).toFixed(1)} KB`; return `${(n/1024/1024).toFixed(1)} MB`;
}
function formatTime(value) { if (!value) return '—'; try { return new Date(value).toLocaleString('zh-CN', {hour12:false}); } catch { return value; } }

async function openTaskCenter(taskId = null) {
  State.route = 'task-center';
  State.foundationBusy = true; render();
  try {
    State.tasks = await api('/tasks?limit=200');
    if (taskId) State.selectedTaskId = Number(taskId);
    State.selectedTaskId ||= State.tasks[0]?.id || null;
    if (State.selectedTaskId) State.taskDetail = await api(`/tasks/${State.selectedTaskId}`);
    State.foundationError = '';
  } catch (e) { State.foundationError = e.message; }
  State.foundationBusy = false; render(); startTaskPolling();
}
function startTaskPolling() {
  clearInterval(Foundation.poller);
  if (State.route !== 'task-center') return;
  Foundation.poller = setInterval(async () => {
    if (State.route !== 'task-center') return clearInterval(Foundation.poller);
    if (!(State.tasks || []).some(t => ['queued','running'].includes(t.status))) return;
    try {
      State.tasks = await api('/tasks?limit=200');
      if (State.selectedTaskId) State.taskDetail = await api(`/tasks/${State.selectedTaskId}`);
      render();
    } catch {}
  }, 700);
}
async function openFileCenter() {
  clearInterval(Foundation.poller); State.route = 'file-center'; State.foundationBusy = true; render();
  try { State.files = await api('/files?limit=500'); State.foundationError = ''; } catch (e) { State.foundationError = e.message; }
  State.foundationBusy = false; render();
}
async function openAuditCenter() {
  clearInterval(Foundation.poller); State.route = 'audit-center'; State.foundationBusy = true; render();
  try {
    [State.auditLogs, State.migrationStatus, State.adminUsers] = await Promise.all([api('/admin/audit-logs?limit=300'), api('/admin/migrations'), api('/admin/users')]);
    State.foundationError = '';
  } catch (e) { State.foundationError = e.message; }
  State.foundationBusy = false; render();
}

function renderTaskCenter() {
  const tasks = State.tasks || [];
  const selected = State.taskDetail;
  const counts = {
    running: tasks.filter(t => ['queued','running'].includes(t.status)).length,
    succeeded: tasks.filter(t => t.status === 'succeeded').length,
    failed: tasks.filter(t => ['failed','cancelled'].includes(t.status)).length,
  };
  const rows = tasks.map(t => `<tr class="${Number(State.selectedTaskId)===t.id?'row-selected':''}">
    <td><button class="link-btn js-task-open" data-id="${t.id}">#${t.id} ${escapeHtml(t.title)}</button><small>${escapeHtml(t.task_type)}</small></td>
    <td><span class="badge ${taskStatusClass(t.status)}">${taskStatusLabel(t.status)}</span></td>
    <td><div class="task-progress"><span style="width:${Number(t.progress||0)}%"></span></div><small>${t.progress||0}% · ${escapeHtml(t.current_step||'')}</small></td>
    <td>${formatTime(t.created_at)}</td>
    <td class="actions">${['succeeded','failed','cancelled'].includes(t.status)?`<button class="btn small secondary js-task-retry" data-id="${t.id}">重新执行</button>`:''}${t.result?.download_url?`<button class="btn small primary js-task-download" data-url="${escapeHtml(t.result.download_url)}">下载成果</button>`:''}</td>
  </tr>`).join('');
  const eventRows = (selected?.events || []).slice().reverse().map(e => `<tr><td>${formatTime(e.created_at)}</td><td>${e.progress ?? '—'}%</td><td>${escapeHtml(e.step||'')}</td><td><span class="event-${escapeHtml(e.level)}">${escapeHtml(e.message)}</span></td></tr>`).join('');
  const result = selected?.result?.analysis_markdown ? `<pre class="result-pre compact-pre">${escapeHtml(selected.result.analysis_markdown)}</pre>` : selected?.result ? `<pre class="result-pre compact-pre">${escapeHtml(JSON.stringify(selected.result,null,2))}</pre>` : '<div class="empty-box compact-empty">任务尚未产生结果。</div>';
  app.innerHTML = `<div class="page-shell">${topbar('EnerTri 任务中心','统一管理论文解析、PPT、视频分析与仿真任务')}
    <section class="hero-grid task-kpis"><div class="stat-card"><strong>${counts.running}</strong><span>正在运行</span></div><div class="stat-card"><strong>${counts.succeeded}</strong><span>已完成</span></div><div class="stat-card"><strong>${counts.failed}</strong><span>失败/取消</span></div><div class="stat-card"><strong>${tasks.length}</strong><span>全部任务</span></div></section>
    ${State.foundationError?`<div class="notice error">${escapeHtml(State.foundationError)}</div>`:''}
    <div class="foundation-grid"><section class="card panel"><div class="section-head"><h2>任务列表</h2><button class="btn small secondary" id="taskRefreshBtn">刷新</button></div><div class="table-wrap"><table class="table task-table"><thead><tr><th>任务</th><th>状态</th><th>进度</th><th>创建时间</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="5" class="muted">暂无任务</td></tr>'}</tbody></table></div></section>
    <aside class="card panel task-detail"><div class="section-head"><h2>日志与成果</h2>${selected?`<span class="badge ${taskStatusClass(selected.status)}">${taskStatusLabel(selected.status)}</span>`:''}</div>${selected?`<h3>#${selected.id} ${escapeHtml(selected.title)}</h3><p class="muted">${escapeHtml(selected.current_step||'')} · ${selected.progress||0}%</p><div class="support-tags"><span class="chip">Worker ${escapeHtml(selected.worker_id||'待抢占')}</span><span class="chip">尝试 ${selected.attempt_count||0}</span><span class="chip">超时 ${selected.timeout_seconds||'—'}s</span></div>${result}<h3>执行日志</h3><div class="table-wrap"><table class="table log-table"><thead><tr><th>时间</th><th>进度</th><th>步骤</th><th>信息</th></tr></thead><tbody>${eventRows||'<tr><td colspan="4" class="muted">暂无日志</td></tr>'}</tbody></table></div>`:'<div class="empty-box">选择任务查看日志。</div>'}</aside></div></div>`;
  bindCommon(); bindTaskCenter();
}
function bindTaskCenter() {
  document.getElementById('taskRefreshBtn')?.addEventListener('click', () => openTaskCenter(State.selectedTaskId));
  document.querySelectorAll('.js-task-open').forEach(b => b.onclick = async () => { State.selectedTaskId=Number(b.dataset.id); State.taskDetail=await api(`/tasks/${b.dataset.id}`); renderTaskCenter(); });
  document.querySelectorAll('.js-task-retry').forEach(b => b.onclick = async () => { const t=await api(`/tasks/${b.dataset.id}/retry`,{method:'POST'}); await openTaskCenter(t.id); });
  document.querySelectorAll('.js-task-download').forEach(b => b.onclick = () => apiDownload(b.dataset.url,'task-output.bin'));
}

function renderFileCenter() {
  const files = State.files || [];
  const rows = files.map(f => `<tr><td>${f.id}</td><td><strong>${escapeHtml(f.original_name)}</strong><small>声明 ${escapeHtml(f.mime_type||f.file_type)}<br>检测 ${escapeHtml(f.detected_mime_type||'—')}</small></td><td>${formatBytes(f.size_bytes)}</td><td><code>${escapeHtml(f.sha256.slice(0,12))}…</code></td><td><span class="badge">${escapeHtml(f.confidentiality)}</span></td><td><span class="badge ${f.parse_status==='failed'?'danger':f.parse_status==='parsed'?'success':''}">${escapeHtml(f.parse_status)}</span></td><td>${f.external_ai_allowed?'允许':'禁止'}</td><td class="actions">${f.can_download?`<button class="btn small primary js-file-download" data-url="${escapeHtml(f.download_url)}" data-name="${escapeHtml(f.original_name)}">下载</button>`:'<span class="badge muted">无下载权限</span>'}${f.can_delete?`<button class="btn small danger js-file-delete" data-id="${f.id}">删除</button>`:''}</td></tr>`).join('');
  app.innerHTML = `<div class="page-shell">${topbar('EnerTri 文件管理','哈希去重、保密策略、权限校验与统一成果存储')}
    ${State.foundationError?`<div class="notice error">${escapeHtml(State.foundationError)}</div>`:''}
    <section class="card panel"><div class="section-head"><h2>上传文件</h2><span class="muted"></span></div><div class="upload-row"><input class="input" type="file" id="managedFile"><select class="select" id="fileConf"><option value="internal">内部</option><option value="public">公开</option><option value="confidential">保密</option><option value="restricted">严格保密</option></select><label class="check-row"><input type="checkbox" id="fileExternal">允许发送到外部 AI</label><label class="check-row"><input type="checkbox" id="fileTemporary">临时文件（自动清理）</label><button class="btn primary" id="managedUploadBtn">上传</button></div><div id="fileUploadNotice"></div></section>
    <section class="card panel"><div class="section-head"><h2>文件库</h2><button class="btn small secondary" id="fileRefreshBtn">刷新</button></div><div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>文件</th><th>大小</th><th>SHA-256</th><th>保密等级</th><th>解析状态</th><th>外部AI</th><th>操作</th></tr></thead><tbody>${rows||'<tr><td colspan="8" class="muted">暂无文件</td></tr>'}</tbody></table></div></section></div>`;
  bindCommon(); bindFileCenter();
}
function bindFileCenter() {
  document.getElementById('fileRefreshBtn')?.addEventListener('click', openFileCenter);
  document.querySelectorAll('.js-file-download').forEach(b => b.onclick=()=>apiDownload(b.dataset.url,b.dataset.name));
  document.querySelectorAll('.js-file-delete').forEach(b => b.onclick=async()=>{if(!confirm('确定删除该文件吗？'))return;await api(`/files/${b.dataset.id}`,{method:'DELETE'});await openFileCenter();});
  document.getElementById('managedUploadBtn')?.addEventListener('click', async()=>{
    const file=document.getElementById('managedFile').files[0]; if(!file)return alert('请选择文件');
    const fd=new FormData();fd.append('file',file);fd.append('confidentiality',document.getElementById('fileConf').value);fd.append('allow_external_ai',document.getElementById('fileExternal').checked);fd.append('temporary',document.getElementById('fileTemporary').checked);
    try{const r=await api('/files/upload',{method:'POST',body:fd});document.getElementById('fileUploadNotice').innerHTML=`<div class="notice success">${r.duplicate_detected?'检测到重复文件，已复用原记录':'上传成功'}：文件 #${r.id}</div>`;State.files=await api('/files?limit=500');setTimeout(renderFileCenter,500);}catch(e){document.getElementById('fileUploadNotice').innerHTML=`<div class="notice error">${escapeHtml(e.message)}</div>`;}
  });
}

function renderAuditCenter() {
  const migration = State.migrationStatus || {};
  const rows = (State.auditLogs || []).map(l => `<tr><td>${l.id}</td><td>${formatTime(l.created_at)}</td><td>${l.actor_user_id??'系统'}</td><td><code>${escapeHtml(l.action)}</code></td><td>${escapeHtml(l.resource_type)} #${escapeHtml(l.resource_id||'')}</td><td><span class="badge ${l.outcome==='success'?'success':'danger'}">${escapeHtml(l.outcome)}</span></td><td><small>${escapeHtml(l.ip_address||'—')}</small></td></tr>`).join('');
  const roleOptions = [
    ['learning_user','普通学习用户'],['researcher','科研用户'],['production_engineer','生产工程师'],
    ['review_expert','审核专家'],['admin','管理员'],['system_admin','系统管理员']
  ];
  const userRows = (State.adminUsers || []).map(u => {
    const systemLocked = u.role === 'system_admin' && State.user?.role !== 'system_admin';
    const options = roleOptions.map(([value,label]) => `<option value="${value}" ${u.role===value?'selected':''} ${value==='system_admin'&&State.user?.role!=='system_admin'?'disabled':''}>${label}</option>`).join('');
    return `<tr><td>${u.id}</td><td><strong>${escapeHtml(u.display_name)}</strong><small>${escapeHtml(u.username)}</small></td><td><select class="select compact-select js-user-role" data-id="${u.id}" ${systemLocked?'disabled':''}>${options}</select></td><td><label class="check-row"><input type="checkbox" class="js-user-active" data-id="${u.id}" ${u.is_active?'checked':''} ${u.id===State.user?.id?'disabled':''}>启用</label></td><td><button class="btn small primary js-user-save" data-id="${u.id}" ${systemLocked?'disabled':''}>保存</button></td></tr>`;
  }).join('');
  app.innerHTML = `<div class="page-shell">${topbar('EnerTri 管理审计','操作留痕、迁移状态、角色权限与系统治理')}
    <section class="card migration-card"><div><span class="badge success">数据库迁移</span><h2>${escapeHtml(migration.current_revision||'未知')}</h2><p>期望版本：${escapeHtml(migration.expected_revision||'v4_7_dynamic_development_loop')}</p></div><div class="migration-ok">${migration.status==='succeeded'?'✓ 迁移成功':'! 需要检查'}</div></section>
    <section class="card panel"><div class="section-head"><h2>用户角色与状态</h2><span class="muted">六级角色权限；系统管理员账户受保护，高权限变更需要目标用户名二次确认</span></div><div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>用户</th><th>角色</th><th>状态</th><th>操作</th></tr></thead><tbody>${userRows||'<tr><td colspan="5" class="muted">暂无用户</td></tr>'}</tbody></table></div><div id="roleUpdateNotice"></div></section>
    <section class="card panel"><div class="section-head"><h2>管理员审计日志</h2><button class="btn small secondary" id="auditRefreshBtn">刷新</button></div><div class="table-wrap"><table class="table"><thead><tr><th>ID</th><th>时间</th><th>操作者</th><th>动作</th><th>资源</th><th>结果</th><th>IP</th></tr></thead><tbody>${rows||'<tr><td colspan="7" class="muted">暂无审计日志</td></tr>'}</tbody></table></div></section></div>`;
  bindCommon();
  document.getElementById('auditRefreshBtn')?.addEventListener('click',openAuditCenter);
  document.querySelectorAll('.js-user-save').forEach(button => button.addEventListener('click', async () => {
    const id = Number(button.dataset.id);
    const role = document.querySelector(`.js-user-role[data-id="${id}"]`)?.value;
    const active = document.querySelector(`.js-user-active[data-id="${id}"]`)?.checked;
    try {
      const target = (State.adminUsers || []).find(u => Number(u.id) === id);
      const privileged = target && (['admin','system_admin'].includes(target.role) || ['admin','system_admin'].includes(role) || active === false);
      let confirmation = null;
      if (privileged) {
        confirmation = prompt(`高权限账户修改需要二次确认。请输入目标用户名：${target.username}`);
        if (confirmation === null) return;
      }
      await api(`/admin/users/${id}/role`, {method:'PATCH', body:JSON.stringify({role, is_active:active, confirmation})});
      document.getElementById('roleUpdateNotice').innerHTML = '<div class="notice success">角色与账户状态已更新并写入审计日志。</div>';
      [State.adminUsers, State.auditLogs] = await Promise.all([api('/admin/users'), api('/admin/audit-logs?limit=300')]);
      setTimeout(renderAuditCenter, 450);
    } catch (e) {
      document.getElementById('roleUpdateNotice').innerHTML = `<div class="notice error">${escapeHtml(e.message)}</div>`;
    }
  }));
}
