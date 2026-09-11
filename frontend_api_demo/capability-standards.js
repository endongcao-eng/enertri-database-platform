const CapabilityStandardsUI = { simulationBusy: false };

function standardResourceTypeLabel(type) {
  return ({course:'课程', book:'专业书', project_task:'项目任务'})[type] || type;
}
function standardCapabilityCategoryLabel(type) {
  return ({theory:'理论', methodology:'方法', computation:'计算', experiment:'实验', research:'科研', communication:'表达', project:'项目'})[type] || type;
}
function standardKnowledgeTypeLabel(type) {
  return ({concept:'概念', theory:'理论', method:'方法', tool:'工具', practice:'科研实践'})[type] || type;
}

async function openCapabilityStandards() {
  clearInterval(Foundation?.poller);
  clearInterval(KnowledgeUI?.poller);
  State.route = 'capability-standards';
  State.capabilityStandardsBusy = true;
  render();
  try {
    const [overview, knowledgeNodes, capabilities, resources, graph] = await Promise.all([
      api('/capability-standards/overview'),
      api('/capability-standards/knowledge-nodes'),
      api('/capability-standards/capabilities'),
      api('/capability-standards/resources'),
      api('/capability-standards/graph'),
    ]);
    State.capabilityStandardsOverview = overview;
    State.standardKnowledgeNodes = knowledgeNodes;
    State.standardCapabilities = capabilities;
    State.standardResources = resources;
    State.standardGraph = graph;
    if (!Array.isArray(State.selectedStandardResourceIds) || !State.selectedStandardResourceIds.length) {
      const preferred = [
        resources.find(r => r.code === 'R-COURSE-HEAT'),
        resources.find(r => r.code === 'R-BOOK-MICRO'),
        resources.find(r => r.code === 'R-TASK-MICRO'),
      ].filter(Boolean);
      State.selectedStandardResourceIds = preferred.map(r => r.id);
    }
    await runStandardSimulation(false);
    State.capabilityStandardsError = '';
  } catch (e) {
    State.capabilityStandardsError = e.message;
  }
  State.capabilityStandardsBusy = false;
  render();
}

async function runStandardSimulation(rerender = true) {
  const ids = (State.selectedStandardResourceIds || []).map(Number).filter(Boolean);
  if (!ids.length) {
    State.standardSimulation = null;
    if (rerender) renderCapabilityStandards();
    return;
  }
  CapabilityStandardsUI.simulationBusy = true;
  if (rerender) renderCapabilityStandards();
  try {
    State.standardSimulation = await api('/capability-standards/simulate', {
      method: 'POST', body: JSON.stringify({ resource_ids: ids })
    });
    State.capabilityStandardsError = '';
  } catch (e) {
    State.capabilityStandardsError = e.message;
  }
  CapabilityStandardsUI.simulationBusy = false;
  if (rerender) renderCapabilityStandards();
}

function standardScoreBar(score, compact=false) {
  const safe = Math.max(0, Math.min(100, Number(score)||0));
  return `<div class="standard-score ${compact?'compact':''}"><div class="standard-score-track"><span style="width:${safe}%"></span></div><strong>${safe.toFixed(1)}</strong></div>`;
}

function resourceImpactMini(resource) {
  const k = (resource.knowledge_links || []).slice(0, 4);
  const c = (resource.capability_links || []).slice(0, 3);
  return `<div class="resource-impact-mini">
    <div><small>→ 知识</small>${k.map(x=>`<span>${escapeHtml(x.name_zh)} L${Number(x.coverage_level).toFixed(1)}</span>`).join('') || '<span>待映射</span>'}</div>
    <div><small>→ 能力</small>${c.map(x=>`<span>${escapeHtml(x.name_zh)} L${Number(x.contribution_level).toFixed(1)}</span>`).join('') || '<span>待映射</span>'}</div>
  </div>`;
}

function renderCapabilityStandards() {
  const overview = State.capabilityStandardsOverview || {};
  const resources = State.standardResources || [];
  const knowledgeNodes = State.standardKnowledgeNodes || [];
  const capabilities = State.standardCapabilities || [];
  const graph = State.standardGraph || {capability_knowledge_links:[], knowledge_relations:[]};
  const sim = State.standardSimulation;
  const selected = new Set((State.selectedStandardResourceIds || []).map(Number));
  const resourceGroups = ['course','book','project_task'].map(type => {
    const rows = resources.filter(r => r.resource_type === type);
    return `<div class="standard-resource-group"><div class="standard-resource-group-head"><span class="resource-type-dot ${type}"></span><strong>${standardResourceTypeLabel(type)}</strong><span>${rows.length}</span></div>${rows.map(r=>`<label class="standard-resource-card ${selected.has(Number(r.id))?'selected':''}"><input type="checkbox" class="js-standard-resource" data-id="${r.id}" ${selected.has(Number(r.id))?'checked':''}><div class="standard-resource-main"><div class="resource-title-row"><strong>${escapeHtml(r.title)}</strong><span class="badge">${escapeHtml(r.discipline||'通用')}</span></div><p>${escapeHtml(r.description||'')}</p>${resourceImpactMini(r)}</div></label>`).join('')}</div>`;
  }).join('');

  const knowledgeById = Object.fromEntries(knowledgeNodes.map(x => [Number(x.id), x]));
  const capKnowledge = {};
  (graph.capability_knowledge_links || []).forEach(link => {
    (capKnowledge[Number(link.capability_id)] ||= []).push({...link, node: knowledgeById[Number(link.knowledge_node_id)]});
  });
  const capabilityCards = capabilities.map(cap => {
    const links = (capKnowledge[Number(cap.id)] || []).filter(x=>x.node);
    return `<article class="standard-capability-card"><div class="capability-card-top"><span class="badge primary">${standardCapabilityCategoryLabel(cap.category)}</span><code>${escapeHtml(cap.code)}</code></div><h3>${escapeHtml(cap.name_zh)}</h3><p>${escapeHtml(cap.description||'')}</p><div class="capability-requires"><small>知识基础</small>${links.map(x=>`<span class="knowledge-pill ${x.relation_type}">${escapeHtml(x.node.name_zh)} · L${Number(x.required_level).toFixed(0)}</span>`).join('') || '<span class="muted">待建立</span>'}</div></article>`;
  }).join('');

  const domains = [...new Set(knowledgeNodes.map(n => n.domain))];
  const relationLookup = {};
  (graph.knowledge_relations || []).forEach(r => { (relationLookup[Number(r.target_node_id)] ||= []).push(r); });
  const knowledgeMapHtml = domains.map(domain => `<div class="knowledge-domain-column"><div class="knowledge-domain-head"><strong>${escapeHtml(domain)}</strong><span>${knowledgeNodes.filter(n=>n.domain===domain).length} 节点</span></div>${knowledgeNodes.filter(n=>n.domain===domain).map(n=>{
    const prereq = (relationLookup[Number(n.id)]||[]).filter(r=>r.relation_type==='prerequisite').map(r=>knowledgeById[Number(r.source_node_id)]?.name_zh).filter(Boolean);
    return `<div class="knowledge-node-card"><div><span class="knowledge-node-type">${standardKnowledgeTypeLabel(n.node_type)}</span>${n.linked_term_id?'<span class="term-link-dot">术语已链接</span>':''}</div><strong>${escapeHtml(n.name_zh)}</strong><small>${escapeHtml(n.code)}</small>${prereq.length?`<p>先修：${prereq.map(escapeHtml).join(' → ')}</p>`:''}</div>`;
  }).join('')}</div>`).join('');

  const simKnowledge = (sim?.knowledge || []).slice(0, 10).map(item => `<div class="simulation-row"><div class="simulation-label"><strong>${escapeHtml(item.name_zh)}</strong><small>${escapeHtml(item.domain)}</small></div>${standardScoreBar(item.mapping_score)}<details><summary>证据路径 ${item.trace.length}</summary>${item.trace.map(t=>`<p>${escapeHtml(standardResourceTypeLabel(t.resource_type))} · ${escapeHtml(t.title)} → ${t.mapping_contribution}%</p>`).join('')}</details></div>`).join('');
  const simCapabilities = (sim?.capabilities || []).slice(0, 8).map(item => `<div class="simulation-row capability"><div class="simulation-label"><strong>${escapeHtml(item.name_zh)}</strong><small>${standardCapabilityCategoryLabel(item.category)}</small></div>${standardScoreBar(item.mapping_score)}<details><summary>来源 ${item.trace.length}</summary>${item.trace.map(t=>`<p>${escapeHtml(standardResourceTypeLabel(t.resource_type))} · ${escapeHtml(t.title)} → ${t.mapping_contribution}%</p>`).join('')}</details></div>`).join('');

  const isAdmin = ['admin','system_admin'].includes(State.user?.role);
  const adminHint = isAdmin ? `<div class="standard-admin-hint"><span class="badge success">管理员维护已开放</span><p></p></div>` : '';

  app.innerHTML = `<div class="page-shell standards-shell">${topbar('EnerTri 科研知识与能力标准库','V4.4 · Stage 1 标准底座持续服务个人科研画像')}
    <section class="standards-hero"><div><span class="eyebrow">Research Capability Standard Library</span><h2>科研知识与能力标准库</h2><p></p></div><div class="stage-badge"><span>01</span><strong>底层标准库</strong><small>已接入数据库</small></div></section>
    <section class="hero-grid standards-kpis"><div class="stat-card"><strong>${overview.knowledge_nodes||0}</strong><span>标准知识节点</span></div><div class="stat-card"><strong>${overview.capabilities||0}</strong><span>科研能力节点</span></div><div class="stat-card"><strong>${overview.resources||0}</strong><span>课程 / 书 / 项目任务</span></div><div class="stat-card"><strong>${overview.mapping_links||0}</strong><span>可追溯映射关系</span></div></section>
    ${State.capabilityStandardsError?`<div class="notice error">${escapeHtml(State.capabilityStandardsError)}</div>`:''}

    <section class="card panel standard-pipeline"><div class="section-head"><div><span class="eyebrow">01 · Canonical Mapping</span><h2></h2><p class="muted"></p></div></div><div class="pipeline-flow"><div><span class="pipeline-icon">A</span><strong>学习 / 科研来源</strong><small>课程 · 专业书 · 项目任务</small></div><b>→</b><div><span class="pipeline-icon">K</span><strong>标准知识节点</strong><small>概念 · 理论 · 方法 · 工具</small></div><b>→</b><div><span class="pipeline-icon">C</span><strong>科研能力节点</strong><small>理论 · 计算 · 实验 · 科研</small></div><b>→</b><div><span class="pipeline-icon">P</span><strong>个人证据画像</strong><small>第二阶段已接入：成绩 / 项目 / 导师评价</small></div></div></section>

    <section class="standards-main-grid"><div class="card panel"><div class="section-head"><div><span class="eyebrow">02 · Source Standardization</span><h2>课程、专业书与项目任务标准</h2><p class="muted">勾选任意组合，右侧立即演算它们能映射出哪些知识和能力。</p></div><button class="btn primary" id="runStandardSimulationBtn">${CapabilityStandardsUI.simulationBusy?'演算中…':'重新演算'}</button></div><div class="standard-resource-list">${resourceGroups}</div></div>
    <div class="card panel simulation-panel"><div class="section-head"><div><span class="eyebrow">03 · Mapping Sandbox</span><h2>标准映射演算</h2><p class="muted">当前选中 ${(State.selectedStandardResourceIds||[]).length} 项。这里展示的是“映射强度”，不是学生能力分。</p></div></div>${sim?`<div class="simulation-section"><h3>形成的知识覆盖</h3>${simKnowledge||'<div class="empty-box compact-empty">暂无知识映射</div>'}</div><div class="simulation-section"><h3>可贡献的能力</h3>${simCapabilities||'<div class="empty-box compact-empty">暂无能力映射</div>'}</div><div class="notice standard-note">${escapeHtml(sim.note||'')}</div>`:'<div class="empty-box">选择左侧资源后开始演算。</div>'}</div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">04 · Knowledge System</span><h2>标准知识体系</h2><p class="muted">与术语库关联</p></div><span class="badge primary">${overview.linked_terms||0} 个节点已直接链接现有术语</span></div><div class="knowledge-domain-grid">${knowledgeMapHtml}</div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">05 · Capability Ontology</span><h2>科研能力标准</h2><p class="muted">每个能力都明确依赖哪些知识、最低需要到什么等级；后续所有匹配都使用同一套能力定义。</p></div></div><div class="standard-capability-grid">${capabilityCards}</div>${adminHint}</section>
  </div>`;
  bindCommon();
  bindCapabilityStandards();
}

function bindCapabilityStandards() {
  document.querySelectorAll('.js-standard-resource').forEach(input => input.onchange = e => {
    const id = Number(e.target.dataset.id);
    const set = new Set((State.selectedStandardResourceIds || []).map(Number));
    if (e.target.checked) set.add(id); else set.delete(id);
    State.selectedStandardResourceIds = [...set];
    renderCapabilityStandards();
  });
  document.getElementById('runStandardSimulationBtn')?.addEventListener('click', () => runStandardSimulation(true));
}
