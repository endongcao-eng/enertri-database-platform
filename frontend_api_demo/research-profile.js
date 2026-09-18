const ResearchProfileUI = { busy: false, evidenceBusy: false, verifyBusyId: null };

function profileVerificationLabel(status) {
  return ({self_reported:'学生自报', pending:'待导师核验', verified:'导师已核验', rejected:'已退回'})[status] || status;
}
function profileVerificationClass(status) {
  return ({verified:'success', pending:'warning', self_reported:'', rejected:'error'})[status] || '';
}
function profileEvidenceTypeLabel(type) {
  return ({course_grade:'课程成绩', book_reading:'专业书阅读', project_participation:'科研项目'})[type] || type;
}
function researchScoreBar(score, extra='') {
  const safe = Math.max(0, Math.min(100, Number(score)||0));
  return `<div class="profile-score ${extra}"><div class="profile-score-track"><span style="width:${safe}%"></span></div><strong>${safe.toFixed(1)}</strong></div>`;
}
function profileResourceTypeToEvidence(type) {
  return ({course:'course_grade', book:'book_reading', project_task:'project_participation'})[type] || 'course_grade';
}

async function openResearchProfile(targetUserId = null) {
  const navigationId = beginNavigation('research-profile');
  ResearchProfileUI.busy = true;
  render();
  try {
    const isAdmin = ['admin','system_admin'].includes(State.user?.role);
    let users = [];
    if (isAdmin) {
      users = await api('/research-profile/users');
      State.profileUsers = users;
    }
    let selectedId = targetUserId || State.selectedProfileUserId;
    if (!selectedId) {
      selectedId = isAdmin ? (users.find(u=>u.username==='student')?.id || State.user?.id) : State.user?.id;
    }
    State.selectedProfileUserId = Number(selectedId);
    const [profile, resources] = await Promise.all([
      api(`/research-profile/profile?user_id=${encodeURIComponent(State.selectedProfileUserId)}`),
      api('/capability-standards/resources'),
    ]);
    State.researchProfile = profile;
    State.profileResources = resources;
    State.researchProfileError = '';
  } catch (e) {
    if (isCurrentNavigation(navigationId, 'research-profile')) State.researchProfileError = e.message;
  }
  if (!isCurrentNavigation(navigationId, 'research-profile')) return;
  ResearchProfileUI.busy = false;
  render();
}

async function submitProfileEvidence(e) {
  e.preventDefault();
  const resourceId = Number(document.getElementById('profileEvidenceResource')?.value);
  const resource = (State.profileResources || []).find(r=>Number(r.id)===resourceId);
  if (!resource) return;
  const evidenceType = profileResourceTypeToEvidence(resource.resource_type);
  const num = id => {
    const raw = document.getElementById(id)?.value;
    return raw === '' || raw == null ? null : Number(raw);
  };
  const payload = {
    user_id: Number(State.selectedProfileUserId),
    resource_id: resourceId,
    evidence_type: evidenceType,
    title: document.getElementById('profileEvidenceTitle')?.value?.trim() || `${resource.title} · 个人证据`,
    completion_ratio: Math.max(0, Math.min(1, (num('profileEvidenceCompletion') ?? 100) / 100)),
    verification_status: 'pending',
    occurred_on: document.getElementById('profileEvidenceDate')?.value || null,
    notes: document.getElementById('profileEvidenceNotes')?.value?.trim() || null,
  };
  if (evidenceType === 'course_grade') payload.grade_percent = num('profileEvidenceGrade');
  if (evidenceType === 'book_reading') payload.quality_rating = num('profileEvidenceQuality');
  if (evidenceType === 'project_participation') {
    payload.independence_ratio = (num('profileEvidenceIndependence') ?? 50) / 100;
    payload.quality_rating = num('profileEvidenceQuality');
    payload.mentor_rating = num('profileEvidenceMentor');
  }
  ResearchProfileUI.evidenceBusy = true;
  renderResearchProfile();
  try {
    await api('/research-profile/evidence', {method:'POST', body:JSON.stringify(payload)});
    await openResearchProfile(State.selectedProfileUserId);
  } catch (err) {
    State.researchProfileError = err.message;
    ResearchProfileUI.evidenceBusy = false;
    renderResearchProfile();
  }
}

async function verifyProfileEvidence(evidenceId, status) {
  const mentor = document.querySelector(`[data-mentor-for="${evidenceId}"]`)?.value;
  const quality = document.querySelector(`[data-quality-for="${evidenceId}"]`)?.value;
  const note = document.querySelector(`[data-note-for="${evidenceId}"]`)?.value?.trim();
  const payload = {
    verification_status: status,
    mentor_rating: mentor === '' || mentor == null ? null : Number(mentor),
    quality_rating: quality === '' || quality == null ? null : Number(quality),
    verification_note: note || (status === 'verified' ? '导师已核验证据。' : '请补充或修正证据。'),
  };
  ResearchProfileUI.verifyBusyId = Number(evidenceId);
  renderResearchProfile();
  try {
    await api(`/research-profile/evidence/${evidenceId}/verify`, {method:'PATCH', body:JSON.stringify(payload)});
    await openResearchProfile(State.selectedProfileUserId);
  } catch (err) {
    State.researchProfileError = err.message;
    ResearchProfileUI.verifyBusyId = null;
    renderResearchProfile();
  }
}

function refreshProfileEvidenceFields() {
  const id = Number(document.getElementById('profileEvidenceResource')?.value);
  const resource = (State.profileResources || []).find(r=>Number(r.id)===id);
  const type = resource?.resource_type;
  document.querySelectorAll('[data-profile-field]').forEach(el => {
    const allowed = String(el.dataset.profileField || '').split(',');
    el.style.display = allowed.includes(type) ? '' : 'none';
  });
}

function evidenceMetricsHtml(ev) {
  const metrics = [];
  if (ev.grade_percent != null) metrics.push(`成绩 ${Number(ev.grade_percent).toFixed(0)}`);
  if (ev.completion_ratio != null) metrics.push(`完成 ${Math.round(Number(ev.completion_ratio)*100)}%`);
  if (ev.independence_ratio != null) metrics.push(`独立度 ${Math.round(Number(ev.independence_ratio)*100)}%`);
  if (ev.quality_rating != null) metrics.push(`质量 ${Number(ev.quality_rating).toFixed(1)}/5`);
  if (ev.mentor_rating != null) metrics.push(`导师 ${Number(ev.mentor_rating).toFixed(1)}/5`);
  return metrics.map(x=>`<span>${escapeHtml(x)}</span>`).join('');
}

function renderResearchProfile() {
  const data = State.researchProfile;
  const isAdmin = ['admin','system_admin'].includes(State.user?.role);
  if (ResearchProfileUI.busy && !data) {
    app.innerHTML = `<div class="page-shell">${topbar('EnerTri 学生科研能力画像','V4.4 Stage 2 · Evidence-backed Research Profile')}<div class="card panel">正在计算个人知识体系与科研能力…</div></div>`;
    bindCommon(); return;
  }
  const profile = data?.profile || {};
  const summary = data?.summary || {};
  const users = State.profileUsers || [];
  const resources = State.profileResources || [];
  const strengths = data?.top_strengths || [];
  const evidence = data?.evidence || [];
  const gaps = data?.gaps || [];
  const domains = data?.knowledge_domains || [];
  const capabilities = data?.capabilities || [];

  const userPicker = isAdmin ? `<label class="profile-user-picker"><span>老师查看学生</span><select id="profileUserSelect">${users.map(u=>`<option value="${u.id}" ${Number(u.id)===Number(State.selectedProfileUserId)?'selected':''}>${escapeHtml(u.display_name)} · ${escapeHtml(u.role)}</option>`).join('')}</select></label>` : '';
  const strengthHtml = strengths.length ? strengths.map((item,i)=>`<article class="profile-strength-card rank-${i+1}"><div class="profile-strength-head"><span>${String(i+1).padStart(2,'0')}</span><div><strong>${escapeHtml(item.name_zh)}</strong><small>${escapeHtml(standardCapabilityCategoryLabel(item.category))}</small></div><b>${Number(item.score).toFixed(1)}</b></div>${researchScoreBar(item.score)}<p>${escapeHtml(item.maturity)} · 证据 ${item.evidence_count} 条</p></article>`).join('') : '<div class="empty-box">还没有足够证据形成能力优势。</div>';

  const evidenceHtml = evidence.map(ev=>`<article class="profile-evidence-card"><div class="profile-evidence-top"><div><span class="badge ${profileVerificationClass(ev.verification_status)}">${escapeHtml(profileVerificationLabel(ev.verification_status))}</span><span class="badge">${escapeHtml(profileEvidenceTypeLabel(ev.evidence_type))}</span></div><strong>${Math.round(Number(ev.personal_evidence_strength||0)*100)}%</strong></div><h3>${escapeHtml(ev.title)}</h3><p class="muted">${escapeHtml(ev.resource_title||'标准资源')} ${ev.occurred_on?'· '+escapeHtml(ev.occurred_on):''}</p><div class="evidence-metrics">${evidenceMetricsHtml(ev)}</div><p>${escapeHtml(ev.notes||'暂无说明')}</p><div class="evidence-trust-line"><span>个人证据有效度</span>${researchScoreBar(Number(ev.personal_evidence_strength||0)*100,'compact')}</div>${ev.verification_note?`<div class="mentor-note"><strong>核验说明</strong><span>${escapeHtml(ev.verification_note)}</span>${ev.verifier_name?`<small>${escapeHtml(ev.verifier_name)}</small>`:''}</div>`:''}${isAdmin && ev.verification_status!=='verified'?`<div class="teacher-verify-box"><div><label>导师评分<input type="number" min="0" max="5" step="0.1" value="${ev.mentor_rating??''}" data-mentor-for="${ev.id}"></label><label>成果质量<input type="number" min="0" max="5" step="0.1" value="${ev.quality_rating??''}" data-quality-for="${ev.id}"></label></div><input type="text" placeholder="核验说明" data-note-for="${ev.id}"><div class="inline-actions"><button class="btn small primary js-profile-verify" data-id="${ev.id}" data-status="verified">${ResearchProfileUI.verifyBusyId===Number(ev.id)?'处理中…':'核验通过'}</button><button class="btn small secondary js-profile-verify" data-id="${ev.id}" data-status="rejected">退回</button></div></div>`:''}</article>`).join('');

  const gapHtml = gaps.length ? gaps.map(g=>`<article class="profile-gap-card"><div><span class="gap-severity">缺口 ${Number(g.severity).toFixed(0)}</span><strong>${escapeHtml(g.name_zh)}</strong><small>${escapeHtml(g.domain)} · 当前 ${Number(g.current_score).toFixed(1)}</small></div><p>影响：${g.blocking_capabilities.map(escapeHtml).join('、')}</p><div class="gap-resources">${(g.recommended_resources||[]).map(r=>`<span>${escapeHtml(standardResourceTypeLabel(r.resource_type))} · ${escapeHtml(r.title)}</span>`).join('') || '<span>标准库中暂无直接补齐资源</span>'}</div></article>`).join('') : '<div class="empty-box compact-empty">当前主要能力链路没有明显的必备知识缺口。</div>';

  const domainHtml = domains.map(domain=>`<section class="profile-domain-card"><div class="profile-domain-head"><div><strong>${escapeHtml(domain.domain)}</strong><small>${domain.evidenced_nodes}/${domain.node_count} 节点已有证据</small></div><b>${Number(domain.average_score).toFixed(1)}</b></div><div class="profile-domain-nodes">${domain.nodes.map(node=>`<div class="profile-node-row ${Number(node.score)<20?'weak':''}"><div><strong>${escapeHtml(node.name_zh)}</strong><small>L${Number(node.estimated_level).toFixed(1)} · ${node.evidence_count} 条证据</small></div>${researchScoreBar(node.score,'compact')}<details><summary>证据链</summary>${node.trace.length?node.trace.map(t=>`<p>${escapeHtml(t.resource_title)} · ${profileVerificationLabel(t.verification_status)} → ${t.contribution}%</p>`).join(''):'<p>尚无个人证据。</p>'}</details></div>`).join('')}</div></section>`).join('');

  const capabilityHtml = capabilities.map(cap=>`<article class="profile-capability-row"><div class="profile-capability-name"><span class="badge primary">${escapeHtml(standardCapabilityCategoryLabel(cap.category))}</span><strong>${escapeHtml(cap.name_zh)}</strong><small>${escapeHtml(cap.maturity)} · L${Number(cap.estimated_level).toFixed(1)}</small></div><div class="capability-score-block"><span>综合能力</span>${researchScoreBar(cap.score)}</div><div class="capability-score-block"><span>直接证据</span>${researchScoreBar(cap.direct_evidence_score)}</div><div class="capability-score-block"><span>知识准备</span>${researchScoreBar(cap.knowledge_readiness_score)}</div><details><summary>查看证据与知识要求</summary><div class="capability-detail-grid"><div><strong>直接证据链</strong>${cap.trace.length?cap.trace.map(t=>`<p>${escapeHtml(t.resource_title)} → ${t.contribution}%</p>`).join(''):'<p class="muted">暂无直接任务证据，当前分数主要来自知识准备度折算。</p>'}</div><div><strong>知识要求</strong>${cap.requirements.map(r=>`<p>${escapeHtml(r.name_zh)} · 当前 L${Number(r.current_level).toFixed(1)} / 要求 L${Number(r.required_level).toFixed(1)} · ${Number(r.readiness).toFixed(0)}%</p>`).join('')||'<p>暂无要求</p>'}</div></div></details></article>`).join('');

  const resourceOptions = resources.map(r=>`<option value="${r.id}">${escapeHtml(standardResourceTypeLabel(r.resource_type))} · ${escapeHtml(r.title)}</option>`).join('');

  app.innerHTML = `<div class="page-shell research-profile-shell">${topbar('EnerTri 学生科研能力画像','V4.4 Stage 2 · 课程 / 读书 / 项目证据 → 个人知识体系 → 科研能力')}
    <section class="profile-hero"><div><span class="eyebrow">Evidence-backed Research Digital Twin</span><h2>${escapeHtml(profile.display_name||'学生')} · 个人科研知识与能力画像</h2><p>${escapeHtml(profile.research_direction||'尚未设置研究方向')}</p></div><div class="profile-hero-side">${userPicker}<span class="stage-badge"><span>02</span><strong>个人证据画像</strong><small>可追溯 · 可核验</small></span></div></section>
    ${State.researchProfileError?`<div class="notice error">${escapeHtml(State.researchProfileError)}</div>`:''}
    <section class="hero-grid profile-kpis"><div class="stat-card"><strong>${summary.evidence_count||0}</strong><span>个人证据</span><small>${summary.verified_evidence_count||0} 条已核验</small></div><div class="stat-card"><strong>${Number(summary.evidence_confidence||0).toFixed(0)}%</strong><span>证据可信度</span><small>考虑自报 / 待核验 / 已核验</small></div><div class="stat-card"><strong>${summary.covered_knowledge_nodes||0}/${summary.total_knowledge_nodes||0}</strong><span>知识节点覆盖</span><small>${Number(summary.knowledge_coverage_percent||0).toFixed(1)}%</small></div><div class="stat-card"><strong>${Number(summary.top_capability_score||0).toFixed(1)}</strong><span>最高科研能力分</span><small>不是自报分</small></div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">01 · Capability Snapshot</span><h2>当前科研能力优势</h2><p class="muted">综合能力 = 直接科研/课程能力证据 + 知识准备度/p></div></div><div class="profile-strength-grid">${strengthHtml}</div></section>

    <section class="profile-two-col"><div class="card panel"><div class="section-head"><div><span class="eyebrow">02 · Evidence Ledger</span><h2>个人科研证据账本</h2><p class="muted"></p></div></div><div class="profile-evidence-list">${evidenceHtml||'<div class="empty-box">尚无个人证据。</div>'}</div></div><div class="card panel"><div class="section-head"><div><span class="eyebrow">03 · Knowledge Gaps</span><h2>当前知识缺口</h2><p class="muted">只列出已经影响当前能力链路的必备知识，并优先推荐标准库中尚未学习的资源。</p></div></div><div class="profile-gap-list">${gapHtml}</div><div class="profile-add-evidence"><div class="section-head"><div><span class="eyebrow">Add Evidence</span><h3>录入新的学习 / 科研证据</h3></div></div><form id="profileEvidenceForm"><label>标准来源<select id="profileEvidenceResource" required>${resourceOptions}</select></label><label>证据标题<input id="profileEvidenceTitle" placeholder="例如：传热学期末成绩 / 项目阶段任务"></label><div class="profile-form-grid"><label data-profile-field="course">成绩<input id="profileEvidenceGrade" type="number" min="0" max="100" step="0.1" value="85"></label><label>完成度 %<input id="profileEvidenceCompletion" type="number" min="0" max="100" step="1" value="100"></label><label data-profile-field="project_task">独立度 %<input id="profileEvidenceIndependence" type="number" min="0" max="100" step="1" value="70"></label><label data-profile-field="book,project_task">学习/成果质量 0-5<input id="profileEvidenceQuality" type="number" min="0" max="5" step="0.1" value="4"></label>${isAdmin?'<label data-profile-field="project_task">导师评分 0-5<input id="profileEvidenceMentor" type="number" min="0" max="5" step="0.1" value="4"></label>':''}<label>日期<input id="profileEvidenceDate" type="date"></label></div><label>说明<textarea id="profileEvidenceNotes" rows="3" placeholder="完成了哪些章节、任务、成果或考核"></textarea></label><button class="btn primary" type="submit">${ResearchProfileUI.evidenceBusy?'提交中…':'提交并进入待核验'}</button></form></div></div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">04 · Personal Knowledge System</span><h2>当前形成的知识体系</h2><p class="muted"></p></div></div><div class="profile-domain-grid">${domainHtml}</div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">05 · Evidence-backed Capability</span><h2>完整科研能力矩阵</h2><p class="muted"></p></div></div><div class="profile-capability-list">${capabilityHtml}</div></section>

    <section class="card panel scoring-model"><div><span class="eyebrow">Scoring Transparency</span><h2>评分模型透明说明</h2></div><div><p><strong>原则：</strong>${escapeHtml(data?.scoring_model?.principle||'')}</p><p><strong>知识：</strong>${escapeHtml(data?.scoring_model?.knowledge||'')}</p><p><strong>能力：</strong>${escapeHtml(data?.scoring_model?.capability||'')}</p></div></section>
  </div>`;
  bindCommon();
  bindResearchProfile();
  refreshProfileEvidenceFields();
}

function bindResearchProfile() {
  document.getElementById('profileUserSelect')?.addEventListener('change', e => openResearchProfile(Number(e.target.value)));
  document.getElementById('profileEvidenceResource')?.addEventListener('change', refreshProfileEvidenceFields);
  document.getElementById('profileEvidenceForm')?.addEventListener('submit', submitProfileEvidence);
  document.querySelectorAll('.js-profile-verify').forEach(btn => btn.addEventListener('click', () => verifyProfileEvidence(Number(btn.dataset.id), btn.dataset.status)));
}
