const TemplateLibraryUI = { busy: false, error: '', query: '', category: 'all' };
const TEMPLATE_CATEGORIES = [['all', '全部'], ['pdf', 'PDF'], ['ppt', 'PPT'], ['excel', 'EXCEL'], ['word', 'WORD']];
let templatePreviewObjectUrl = null;

async function openTemplateLibrary() {
  if (!State.user) { beginNavigation('login'); return renderLogin('请先登录后使用模板库。'); }
  const navigationId = beginNavigation('template-library');
  TemplateLibraryUI.busy = true; TemplateLibraryUI.error = ''; render();
  try {
    const params = new URLSearchParams();
    if (TemplateLibraryUI.category !== 'all') params.set('category', TemplateLibraryUI.category);
    if (TemplateLibraryUI.query.trim()) params.set('q', TemplateLibraryUI.query.trim());
    State.templates = await api(`/templates${params.toString() ? `?${params}` : ''}`);
  } catch (e) { if (isCurrentNavigation(navigationId, 'template-library')) TemplateLibraryUI.error = e.message; }
  if (!isCurrentNavigation(navigationId, 'template-library')) return;
  TemplateLibraryUI.busy = false; render();
}

function templateCategoryIcon(category) { return ({pdf:'PDF', ppt:'PPT', excel:'XLS', word:'DOC'})[category] || 'FILE'; }

function closeTemplatePreview() {
  if (templatePreviewObjectUrl) URL.revokeObjectURL(templatePreviewObjectUrl);
  templatePreviewObjectUrl = null;
  document.getElementById('templatePreviewModal')?.remove();
}

function templatePreviewBody(data) {
  if (data.kind === 'pdf') return `<div class="template-preview-pages">${(data.sections || []).map(section => `<section><h4>${escapeHtml(section.title)}</h4><pre>${escapeHtml(section.text || '本页未提取到文本，可使用上方 PDF 视图浏览。')}</pre></section>`).join('')}</div>`;
  if (data.kind === 'docx') return `<div class="template-preview-text"><pre>${escapeHtml(data.sections?.[0]?.text || '文档没有可提取的正文文本。')}</pre>${(data.tables || []).map((table, index) => `<h4>表格 ${index + 1}</h4><div class="table-wrap"><table class="table">${table.map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</table></div>`).join('')}</div>`;
  if (data.kind === 'pptx') return `<div class="template-preview-pages">${(data.sections || []).map(section => `<section><h4>${escapeHtml(section.title)}</h4><pre>${escapeHtml(section.text || '本页没有可提取的文字。')}</pre></section>`).join('')}</div>`;
  if (data.kind === 'xlsx') return `<div class="template-preview-text">${(data.sheets || []).map(sheet => `<h4>${escapeHtml(sheet.title)}</h4><div class="table-wrap"><table class="table">${(sheet.rows || []).map(row => `<tr>${row.map(cell => `<td>${escapeHtml(cell)}</td>`).join('')}</tr>`).join('')}</table></div>`).join('') || '<div class="empty-box">工作簿没有可展示的数据。</div>'}</div>`;
  return `<div class="empty-box">${escapeHtml(data.message || '该文件暂不支持网页预览，请下载后查看。')}</div>`;
}

async function previewTemplate(templateId) {
  closeTemplatePreview();
  document.body.insertAdjacentHTML('beforeend', `<div class="template-preview-modal" id="templatePreviewModal"><div class="template-preview-dialog"><div class="section-head"><h2>正在生成预览…</h2><button class="btn ghost" id="closeTemplatePreviewBtn">关闭</button></div><div class="empty-box">请稍候</div></div></div>`);
  document.getElementById('closeTemplatePreviewBtn').onclick = closeTemplatePreview;
  try {
    const data = await api(`/templates/${templateId}/preview`);
    const dialog = document.querySelector('#templatePreviewModal .template-preview-dialog');
    if (!dialog) return;
    let visual = '';
    if (data.kind === 'pdf') {
      const previewUrl = data.pdf_url.startsWith('/api/') ? data.pdf_url : `${API_BASE}${data.pdf_url}`;
      const response = await fetch(previewUrl, {headers: {Authorization: `Bearer ${getToken()}`} });
      if (response.ok) { templatePreviewObjectUrl = URL.createObjectURL(await response.blob()); visual = `<iframe class="template-pdf-frame" src="${templatePreviewObjectUrl}#page=1&view=FitH"></iframe>`; }
    }
    dialog.innerHTML = `<div class="section-head"><div><span class="badge primary">${escapeHtml(data.category?.toUpperCase() || '模板')}</span><h2>${escapeHtml(data.title)}</h2></div><div class="inline-actions"><button class="btn primary small js-preview-download">下载原文件</button><button class="btn ghost" id="closeTemplatePreviewBtn">关闭</button></div></div>${visual}${templatePreviewBody(data)}`;
    document.getElementById('closeTemplatePreviewBtn').onclick = closeTemplatePreview;
    dialog.querySelector('.js-preview-download').onclick = () => apiDownload(`/api/templates/${templateId}/download`, data.original_name);
  } catch (e) {
    const dialog = document.querySelector('#templatePreviewModal .template-preview-dialog');
    if (dialog) dialog.innerHTML = `<div class="section-head"><h2>预览失败</h2><button class="btn ghost" id="closeTemplatePreviewBtn">关闭</button></div><div class="notice error">${escapeHtml(e.message)}</div>`;
    document.getElementById('closeTemplatePreviewBtn')?.addEventListener('click', closeTemplatePreview);
  }
}

function renderTemplateLibrary() {
  const isManager = ['admin', 'system_admin', 'researcher'].includes(State.user?.role);
  const templates = State.templates || [];
  const rows = templates.map(item => `<article class="template-card js-template-preview" data-id="${item.id}"><div class="template-icon template-${escapeHtml(item.category)}">${templateCategoryIcon(item.category)}</div><div class="template-card-main"><div class="template-card-head"><div><span class="badge primary">${escapeHtml(item.category_label)}</span><h3>${escapeHtml(item.title)}</h3></div><div class="inline-actions"><button class="btn secondary small js-template-preview-btn" data-id="${item.id}">预览</button><button class="btn primary small js-template-download" data-url="${escapeHtml(item.download_url)}" data-name="${escapeHtml(item.original_name)}">下载</button></div></div><p class="muted">${formatBytes(item.size_bytes)} · ${formatTime(item.created_at)}${item.uploader_name ? ` · ${escapeHtml(item.uploader_name)}` : ''}</p></div></article>`).join('');
  const categoryButtons = TEMPLATE_CATEGORIES.map(([value, label]) => `<button class="template-category-btn ${TemplateLibraryUI.category === value ? 'active' : ''}" data-template-category="${value}"><span>${value === 'all' ? 'ALL' : templateCategoryIcon(value)}</span>${label}</button>`).join('');
  app.innerHTML = `<div class="page-shell template-shell">${topbar('EnerTri 模板库', '教学与科研模板集中管理、分类检索与下载')}
    <section class="template-hero"><div><span class="eyebrow">Template Library</span><h2>把常用模板放在一个地方</h2><p>按文件类型分类浏览，输入文件名即可快速检索。模板文件由教师或管理员统一维护，学生仅可下载使用。</p></div><div class="template-count"><strong>${templates.length}</strong><span>当前结果</span></div></section>
    ${TemplateLibraryUI.error ? `<div class="notice error">${escapeHtml(TemplateLibraryUI.error)}</div>` : ''}
    <section class="template-toolbar card panel"><div class="template-categories">${categoryButtons}</div><div class="template-search"><input class="input" id="templateSearchInput" placeholder="按文件名搜索模板" value="${escapeHtml(TemplateLibraryUI.query)}"><button class="btn primary" id="templateSearchBtn">搜索</button></div></section>
    ${isManager ? `<section class="card panel template-upload-panel"><div class="section-head"><div><h2>上传模板</h2><p class="muted">支持 PDF/PPT、Excel、Word 文件；文件上传后所有登录用户均可下载。</p></div></div><div class="template-upload-row"><input class="input" id="templateFileInput" type="file" accept=".pdf,.ppt,.pptx,.xls,.xlsx,.doc,.docx"><select class="select" id="templateCategorySelect"><option value="pdf">PDF</option><option value="ppt">PPT</option><option value="excel">EXCEL</option><option value="word">WORD</option></select><button class="btn primary" id="templateUploadBtn">上传模板</button></div><div id="templateUploadNotice"></div></section>` : ''}
    <section class="template-results"><div class="section-head"><div><span class="eyebrow">Files</span><h2>${TemplateLibraryUI.category === 'all' ? '全部模板' : TEMPLATE_CATEGORIES.find(x => x[0] === TemplateLibraryUI.category)?.[1] + '模板'}</h2></div><span class="muted">${TemplateLibraryUI.busy ? '加载中…' : `${templates.length} 个文件`}</span></div><div class="template-grid">${rows || '<div class="empty-box">当前分类没有模板文件。</div>'}</div></section>
  </div>`;
  bindCommon();
  document.querySelectorAll('[data-template-category]').forEach(btn => btn.onclick = () => { TemplateLibraryUI.category = btn.dataset.templateCategory; openTemplateLibrary(); });
  document.getElementById('templateSearchBtn')?.addEventListener('click', () => { TemplateLibraryUI.query = document.getElementById('templateSearchInput').value; openTemplateLibrary(); });
  document.getElementById('templateSearchInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('templateSearchBtn').click(); });
  document.querySelectorAll('.js-template-download').forEach(btn => btn.onclick = () => apiDownload(btn.dataset.url, btn.dataset.name));
  document.querySelectorAll('.js-template-preview, .js-template-preview-btn').forEach(btn => btn.onclick = event => { if (event.target.closest('.js-template-download')) return; event.stopPropagation(); previewTemplate(Number(btn.dataset.id || btn.closest('.js-template-preview')?.dataset.id)); });
  document.getElementById('templateUploadBtn')?.addEventListener('click', async () => {
    const file = document.getElementById('templateFileInput').files[0];
    if (!file) return alert('请选择模板文件');
    const fd = new FormData(); fd.append('file', file); fd.append('category', document.getElementById('templateCategorySelect').value);
    const notice = document.getElementById('templateUploadNotice');
    try { const result = await api('/templates', {method:'POST', body:fd}); notice.innerHTML = `<div class="notice success">${result.duplicate_detected ? '模板已存在，已复用原文件' : '模板上传成功'}。</div>`; setTimeout(openTemplateLibrary, 450); }
    catch (e) { notice.innerHTML = `<div class="notice error">${escapeHtml(e.message)}</div>`; }
  });
}
