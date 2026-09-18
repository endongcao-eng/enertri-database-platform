const KnowledgeUI = { pdfObjectUrl: null, poller: null };

async function knowledgePdfBlobUrl(fileId) {
  if (!fileId) return null;
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const res = await fetch(`${API_BASE}/files/${fileId}/download`, { headers });
  if (!res.ok) throw new Error('无法加载论文原文');
  const blob = await res.blob();
  if (KnowledgeUI.pdfObjectUrl) URL.revokeObjectURL(KnowledgeUI.pdfObjectUrl);
  KnowledgeUI.pdfObjectUrl = URL.createObjectURL(blob);
  return KnowledgeUI.pdfObjectUrl;
}

async function openKnowledgeSystem(documentId = null) {
  const navigationId = beginNavigation('knowledge');
  State.knowledgeBusy = true;
  render();
  try {
    const [bases, publications, documents] = await Promise.all([
      api('/knowledge/bases'), api('/literature/publications?limit=100'), api('/knowledge/documents')
    ]);
    State.knowledgeBases = bases;
    State.publications = publications;
    State.knowledgeDocuments = documents;
    State.selectedKnowledgeBaseId ||= bases[0]?.id || null;
    if (documentId) State.selectedKnowledgeDocumentId = Number(documentId);
    State.selectedKnowledgeDocumentId ||= documents.find(d => d.status === 'ready')?.id || documents[0]?.id || null;
    if (State.selectedKnowledgeDocumentId) await loadKnowledgeDocument(State.selectedKnowledgeDocumentId, false);
    State.knowledgeError = '';
  } catch (e) { if (isCurrentNavigation(navigationId, 'knowledge')) State.knowledgeError = e.message; }
  if (!isCurrentNavigation(navigationId, 'knowledge')) return;
  State.knowledgeBusy = false;
  render();
}

async function loadKnowledgeDocument(documentId, rerender = true) {
  const navigationId = State.navigationId;
  State.selectedKnowledgeDocumentId = Number(documentId);
  State.knowledgeDocument = await api(`/knowledge/documents/${documentId}`);
  State.focusPage = 1;
  try { State.knowledgePdfUrl = await knowledgePdfBlobUrl(State.knowledgeDocument.file_id); }
  catch (e) { State.knowledgePdfUrl = null; }
  if (rerender && isCurrentNavigation(navigationId, 'knowledge')) renderKnowledgeSystem();
}

function knowledgeScopeLabel(scope) {
  return ({personal:'个人知识库', group:'课题组知识库', project:'项目知识库', enterprise:'企业知识库', public_terms:'公共术语知识库'})[scope] || scope;
}

function renderExtractedTable(table) {
  const rows = Array.isArray(table.data) ? table.data : [];
  if (!rows.length) return `<pre class="result-pre compact-pre">${escapeHtml(table.markdown || '')}</pre>`;
  const head = rows[0] || [];
  return `<div class="extracted-table-wrap"><table class="table extracted-table"><thead><tr>${head.map(c=>`<th>${escapeHtml(c ?? '')}</th>`).join('')}</tr></thead><tbody>${rows.slice(1).map(row=>`<tr>${row.map(c=>`<td>${escapeHtml(c ?? '')}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
}

function renderKnowledgeSystem() {
  const bases = State.knowledgeBases || [];
  const pubs = State.publications || [];
  const docs = State.knowledgeDocuments || [];
  const doc = State.knowledgeDocument;
  const sourceCount = new Set(pubs.flatMap(p => p.sources || [])).size;
  const mergedCount = pubs.filter(p => (p.sources || []).length > 1).length;
  const readyDocs = docs.filter(d => d.status === 'ready').length;
  const evidenceCount = (doc?.pages || []).length + (doc?.tables || []).length + (doc?.figures || []).length;
  const search = State.literatureSearchResult;
  const selectedKb = bases.find(k => Number(k.id) === Number(State.selectedKnowledgeBaseId)) || bases[0];
  const publicationCards = pubs.slice(0, 8).map(p => `<article class="publication-card">
    <div class="pub-top"><div>${(p.sources||[]).map(s=>`<span class="badge primary">${escapeHtml(s)}</span>`).join(' ')}</div><span class="badge ${p.open_access?'success':''}">${p.open_access?'OA':'Metadata'}</span></div>
    <h3>${escapeHtml(p.title)}</h3><p class="muted">${escapeHtml((p.authors||[]).slice(0,4).join(', ') || '作者信息待补充')} · ${escapeHtml(p.journal||'期刊待补充')} · ${escapeHtml(p.year||'—')}</p>
    <div class="pub-meta"><span>DOI ${escapeHtml(p.doi||'—')}</span><span>引用 ${p.citation_count||0}</span>${(p.sources||[]).length>1?'<strong class="dedup-pill">跨源已合并</strong>':''}</div>
  </article>`).join('');
  const docRows = docs.map(d => `<button class="doc-row ${Number(d.id)===Number(State.selectedKnowledgeDocumentId)?'active':''} js-knowledge-doc" data-id="${d.id}"><span><strong>${escapeHtml(d.title)}</strong><small>${d.page_count||0} 页 · ${escapeHtml(d.status)}</small></span><span class="badge ${d.status==='ready'?'success':d.status==='failed'?'danger':'warning'}">${escapeHtml(d.status)}</span></button>`).join('');
  const facts = (doc?.structure?.key_facts || []).map(f => `<button class="fact-card js-focus-page" data-page="${f.page}"><span>${escapeHtml(f.type.replaceAll('_',' '))}</span><strong>${escapeHtml(f.value)} ${escapeHtml(f.unit||'')}</strong><small>第 ${f.page} 页 · ${escapeHtml(f.evidence||'')}</small></button>`).join('');
  const sections = (doc?.structure?.sections || []).map(s=>`<button class="section-chip js-focus-page" data-page="${s.page_start}">${escapeHtml(s.title)} <span>P${s.page_start}${s.page_end!==s.page_start?`–${s.page_end}`:''}</span></button>`).join('');
  const tables = (doc?.tables || []).map(t => `<div class="table-result"><div class="section-head"><div><h3>${escapeHtml(t.table_number)} ${escapeHtml(t.title||'')}</h3><p class="muted">原文第 ${t.page_number} 页</p></div><button class="btn small secondary js-focus-page" data-page="${t.page_number}">定位原文</button></div>${renderExtractedTable(t)}</div>`).join('');
  const pageEvidence = (doc?.pages || []).map(p => `<button class="page-evidence js-focus-page" data-page="${p.page_number}"><strong>P${p.page_number}</strong><span>${escapeHtml((p.text||'').replace(/\s+/g,' ').slice(0,160))}</span><small>${p.ocr_used?'OCR':'文本层'} · ${escapeHtml(p.extraction_method||'')}</small></button>`).join('');
  const qa = State.paperQaResult;
  const qaEvidence = (qa?.evidence || []).map(e => `<button class="evidence-card js-focus-page" data-page="${e.page}"><span class="badge primary">第 ${e.page} 页</span><strong>${escapeHtml(e.section||'原文证据')}</strong><p>${escapeHtml(e.excerpt||'')}</p><small>相关度 ${escapeHtml(e.score)}</small></button>`).join('');
  const pdfSrc = State.knowledgePdfUrl ? `${State.knowledgePdfUrl}#page=${State.focusPage||1}&view=FitH` : '';
  const qaBlock = qa
    ? `<div class="qa-answer"><div><span class="badge ${qa.confidence==='high'?'success':'warning'}">${escapeHtml(qa.confidence)} confidence</span><h3>答案</h3><p>${escapeHtml(qa.answer)}</p></div><div class="qa-evidence-grid">${qaEvidence}</div></div>`
    : '<div class="empty-box compact-empty">输入问题后，系统会返回答案、页码、章节与原文片段。</div>';
  const documentMain = doc ? `<section class="card panel document-overview"><div class="section-head"><div><span class="eyebrow">03 · Evidence-first Paper Reading</span><h2>${escapeHtml(doc.title)}</h2><p class="muted">${doc.page_count} 页 · ${escapeHtml(doc.status)}</p></div><span class="badge success">${doc.status==='ready'?'结构化完成':escapeHtml(doc.status)}</span></div><div class="section-strip">${sections}</div>${facts?`<div class="facts-grid">${facts}</div>`:''}</section>
      <section class="paper-split"><div class="card pdf-panel"><div class="section-head"><div><h2>PDF 原文</h2><p class="muted">当前定位：第 ${State.focusPage||1} 页</p></div><div class="page-nav"><button class="btn small secondary" id="prevPdfPage">上一页</button><span>P${State.focusPage||1} / ${doc.page_count}</span><button class="btn small secondary" id="nextPdfPage">下一页</button></div></div>${pdfSrc?`<iframe id="paperPdfFrame" class="paper-pdf-frame" src="${escapeHtml(pdfSrc)}"></iframe>`:'<div class="empty-box">无法加载 PDF 原文预览</div>'}</div>
      <div class="card panel evidence-panel"><div class="section-head"><div><h2>结构化结果</h2><p class="muted">点击任意证据直接定位左侧原文页</p></div></div><div class="page-evidence-list">${pageEvidence}</div></div></section>
      <section class="card panel"><div class="section-head"><div><span class="eyebrow">04 · Table Extraction</span><h2>表格数据提取</h2></div><span class="badge primary">${doc.tables?.length||0} 个表格</span></div>${tables || '<div class="empty-box">当前论文未检测到可结构化表格。</div>'}</section>
      <section class="card panel paper-qa"><div class="section-head"><div><span class="eyebrow">05 · Paper QA</span><h2>基于论文的原文问答</h2><p class="muted">答案仅来自已解析证据；每条证据可点击回到原文页。</p></div></div><div class="qa-row"><input class="input" id="paperQaQuestion" value="${escapeHtml(State.paperQaQuestion||'激光功率是多少？')}" placeholder="例如：最高抗拉强度对应哪组参数？"><button class="btn primary" id="paperQaBtn">基于原文回答</button></div>${qaBlock}</section>`
    : '<section class="card panel"><div class="empty-box">上传或选择一篇论文，开始证据化结构化阅读。</div></section>';

  app.innerHTML = `<div class="page-shell knowledge-shell">${topbar('EnerTri 文献与论文知识系统','V4.2 · 多来源检索、证据化论文解析、知识库与原文问答')}
    <section class="hero-grid knowledge-kpis"><div class="stat-card"><strong>${sourceCount || 2}</strong><span>文献来源适配器</span></div><div class="stat-card"><strong>${mergedCount}</strong><span>跨源去重合并</span></div><div class="stat-card"><strong>${readyDocs}</strong><span>已结构化论文</span></div><div class="stat-card"><strong>${evidenceCount}</strong><span>当前证据对象</span></div></section>
    ${State.knowledgeError?`<div class="notice error">${escapeHtml(State.knowledgeError)}</div>`:''}

    <section class="card panel literature-panel"><div class="section-head"><div><span class="eyebrow">01 · Literature Retrieval</span><h2>多来源文献检索与去重</h2><p class="muted"></p></div>${mergedCount?`<span class="dedup-summary">已识别 ${mergedCount} 篇跨源合并记录</span>`:''}</div>
      <div class="literature-search-row"><input class="input" id="literatureQuery" value="${escapeHtml(State.literatureQuery||'laser welding porosity')}" placeholder="输入 DOI、题名或研究主题"><label class="check-row"><input type="checkbox" id="sourceOpenAlex" checked>OpenAlex</label><label class="check-row"><input type="checkbox" id="sourceCrossref" checked>Crossref</label><button class="btn primary" id="literatureSearchBtn">跨源检索</button></div>
      ${search?`<div class="dedup-flow"><span>原始结果 <strong>${search.raw_count}</strong></span><span>→</span><span>自动合并 <strong>${search.duplicate_count}</strong></span><span>→</span><span>唯一文献 <strong>${search.deduplicated_count}</strong></span>${(search.source_status||[]).map(s=>`<span class="badge ${s.ok?'success':'danger'}">${escapeHtml(s.source)} ${s.ok?s.count:'不可用'}</span>`).join('')}</div>`:''}
      <div class="publication-grid">${publicationCards || '<div class="empty-box">尚无已入库文献。</div>'}</div>
    </section>

    <section class="knowledge-layout"><aside class="card panel knowledge-sidebar"><div class="section-head"><div><span class="eyebrow">02 · Knowledge Base</span><h2>知识库</h2></div></div>
      <label class="label">当前知识库</label><select class="select" id="knowledgeBaseSelect">${bases.map(k=>`<option value="${k.id}" ${Number(k.id)===Number(selectedKb?.id)?'selected':''}>${escapeHtml(k.name)} · ${knowledgeScopeLabel(k.scope_type)}</option>`).join('')}</select>
      ${selectedKb?`<div class="kb-policy"><span>${knowledgeScopeLabel(selectedKb.scope_type)}</span><span>团队检索 ${selectedKb.allow_team_search?'✓':'—'}</span><span>AI 使用 ${selectedKb.allow_ai?'✓':'—'}</span><span>导出 ${selectedKb.allow_export?'✓':'—'}</span><span>保留原文 ${selectedKb.retain_original?'✓':'—'}</span></div>`:''}
      <details class="kb-create"><summary>＋ 新建知识库</summary><div class="form-grid"><input class="input" id="newKbName" placeholder="例如：激光焊接项目"><select class="select" id="newKbScope"><option value="personal">个人</option><option value="group">课题组</option><option value="project" selected>项目</option><option value="enterprise">企业</option><option value="public_terms">公共术语</option></select><label class="check-row"><input type="checkbox" id="newKbTeam">允许团队检索</label><label class="check-row"><input type="checkbox" id="newKbAi" checked>允许 AI 使用</label><label class="check-row"><input type="checkbox" id="newKbExport" checked>允许导出</label><label class="check-row"><input type="checkbox" id="newKbRetain" checked>保留原文</label><button class="btn secondary" id="createKbBtn">创建</button></div></details>
      <div class="upload-paper-box"><label class="label">上传 PDF 到当前知识库</label><input type="file" class="input" id="paperKnowledgeFile" accept=".pdf,application/pdf"><div class="form-row-2"><select class="select" id="paperConf"><option value="internal">内部</option><option value="confidential">保密</option><option value="restricted">严格保密</option><option value="public">公开</option></select><label class="check-row"><input type="checkbox" id="paperExternal">允许外部 AI</label></div><button class="btn primary" id="paperKnowledgeUploadBtn">上传并结构化</button><div id="paperUploadNotice"></div></div>
      <div class="document-list">${docRows || '<div class="empty-box compact-empty">当前知识库暂无论文</div>'}</div>
    </aside>
    <main class="knowledge-main">${documentMain}</main></section>
  </div>`;
  bindCommon(); bindKnowledgeSystem();
}

function focusKnowledgePage(page) {
  const doc = State.knowledgeDocument;
  if (!doc) return;
  State.focusPage = Math.min(Math.max(1, Number(page)||1), doc.page_count||1);
  const frame = document.getElementById('paperPdfFrame');
  if (frame && State.knowledgePdfUrl) frame.src = `${State.knowledgePdfUrl}#page=${State.focusPage}&view=FitH`;
  document.querySelector('.pdf-panel .muted')?.replaceChildren(document.createTextNode(`当前定位：第 ${State.focusPage} 页`));
  const nav = document.querySelector('.page-nav span'); if (nav) nav.textContent = `P${State.focusPage} / ${doc.page_count}`;
  document.querySelector('.pdf-panel')?.scrollIntoView({behavior:'smooth', block:'start'});
}

function bindKnowledgeSystem() {
  document.getElementById('knowledgeBaseSelect')?.addEventListener('change', async e => {
    State.selectedKnowledgeBaseId = Number(e.target.value);
    State.knowledgeDocuments = await api(`/knowledge/documents?knowledge_base_id=${State.selectedKnowledgeBaseId}`);
    State.selectedKnowledgeDocumentId = State.knowledgeDocuments[0]?.id || null;
    State.knowledgeDocument = null; State.paperQaResult = null;
    if (State.selectedKnowledgeDocumentId) await loadKnowledgeDocument(State.selectedKnowledgeDocumentId, false);
    renderKnowledgeSystem();
  });
  document.querySelectorAll('.js-knowledge-doc').forEach(b => b.onclick = async () => { State.paperQaResult=null; await loadKnowledgeDocument(b.dataset.id); });
  document.querySelectorAll('.js-focus-page').forEach(b => b.onclick = () => focusKnowledgePage(b.dataset.page));
  document.getElementById('prevPdfPage')?.addEventListener('click',()=>focusKnowledgePage((State.focusPage||1)-1));
  document.getElementById('nextPdfPage')?.addEventListener('click',()=>focusKnowledgePage((State.focusPage||1)+1));
  document.getElementById('literatureSearchBtn')?.addEventListener('click', async () => {
    const button=document.getElementById('literatureSearchBtn'); button.disabled=true; button.textContent='检索中…';
    try {
      State.literatureQuery=document.getElementById('literatureQuery').value.trim();
      const sources=[]; if(document.getElementById('sourceOpenAlex').checked)sources.push('openalex'); if(document.getElementById('sourceCrossref').checked)sources.push('crossref');
      State.literatureSearchResult=await api('/literature/search',{method:'POST',body:JSON.stringify({query:State.literatureQuery,sources,limit:12})});
      State.publications=await api('/literature/publications?limit=100'); renderKnowledgeSystem();
    } catch(e) { State.knowledgeError=e.message; renderKnowledgeSystem(); }
  });
  document.getElementById('createKbBtn')?.addEventListener('click', async()=>{
    try {
      const payload={name:document.getElementById('newKbName').value.trim(),scope_type:document.getElementById('newKbScope').value,description:'',allow_team_search:document.getElementById('newKbTeam').checked,allow_ai:document.getElementById('newKbAi').checked,allow_export:document.getElementById('newKbExport').checked,retain_original:document.getElementById('newKbRetain').checked};
      const kb=await api('/knowledge/bases',{method:'POST',body:JSON.stringify(payload)}); State.selectedKnowledgeBaseId=kb.id; await openKnowledgeSystem();
    } catch(e){State.knowledgeError=e.message;renderKnowledgeSystem();}
  });
  document.getElementById('paperKnowledgeUploadBtn')?.addEventListener('click', async()=>{
    const file=document.getElementById('paperKnowledgeFile').files[0]; if(!file)return alert('请选择 PDF 论文');
    const notice=document.getElementById('paperUploadNotice'); notice.innerHTML='<div class="notice">已提交，等待独立 Worker 处理…</div>';
    const fd=new FormData();fd.append('file',file);fd.append('knowledge_base_id',String(State.selectedKnowledgeBaseId));fd.append('confidentiality',document.getElementById('paperConf').value);fd.append('allow_external_ai',document.getElementById('paperExternal').checked);
    try {
      const task=await api('/knowledge/documents/upload',{method:'POST',body:fd}); State.selectedKnowledgeDocumentId=task.document_id;
      if(['failed','cancelled','succeeded'].includes(task.status)){await openKnowledgeSystem(task.document_id);return;}
      const navigationId=State.navigationId;
      clearInterval(KnowledgeUI.poller); KnowledgeUI.poller=setInterval(async()=>{if(!isCurrentNavigation(navigationId,'knowledge'))return clearInterval(KnowledgeUI.poller);try{const t=await api(`/tasks/${task.id}`);if(!isCurrentNavigation(navigationId,'knowledge'))return clearInterval(KnowledgeUI.poller);notice.innerHTML=`<div class="notice">${escapeHtml(t.current_step||t.status)} · ${t.progress||0}%</div>`;if(['failed','cancelled','succeeded'].includes(t.status)){clearInterval(KnowledgeUI.poller);await openKnowledgeSystem(task.document_id);}}catch{}},850);
    } catch(e){notice.innerHTML=`<div class="notice error">${escapeHtml(e.message)}</div>`;}
  });
  document.getElementById('paperQaBtn')?.addEventListener('click', async()=>{
    if(!State.selectedKnowledgeDocumentId)return;
    const button=document.getElementById('paperQaBtn'); button.disabled=true; button.textContent='检索证据…';
    try{State.paperQaQuestion=document.getElementById('paperQaQuestion').value.trim();State.paperQaResult=await api(`/knowledge/documents/${State.selectedKnowledgeDocumentId}/qa`,{method:'POST',body:JSON.stringify({question:State.paperQaQuestion})});renderKnowledgeSystem();}catch(e){State.knowledgeError=e.message;renderKnowledgeSystem();}
  });
}
