const ProjectMatchingUI = { busy:false, draftBusy:false, saveBusy:false, teamSize:3 };

function pmScoreBar(score, extra='') {
  const safe = Math.max(0, Math.min(100, Number(score)||0));
  return `<div class="pm-score ${extra}"><div class="pm-score-track"><span style="width:${safe}%"></span></div><strong>${safe.toFixed(1)}</strong></div>`;
}
function pmMatchClass(score) {
  const n=Number(score)||0; return n>=80?'excellent':n>=65?'good':n>=50?'medium':'weak';
}
function pmReqHtml(req) {
  return `<div class="pm-requirement ${req.is_critical?'critical':''}"><div><span>${req.is_critical?'关键':''}</span><strong>${escapeHtml(req.name_zh)}</strong><small>L${Number(req.required_level).toFixed(1)} · 权重 ${Number(req.weight).toFixed(2)}</small></div>${req.note?`<p>${escapeHtml(req.note)}</p>`:''}</div>`;
}

async function openProjectMatching(projectId=null) {
  const navigationId = beginNavigation('project-matching');
  ProjectMatchingUI.busy=true;
  render();
  try {
    const projects=await api('/project-matching/projects');
    State.matchingProjects=projects;
    let selected=Number(projectId||State.selectedMatchingProjectId||projects.find(p=>p.status==='active')?.id||projects[0]?.id||0);
    State.selectedMatchingProjectId=selected;
    if (selected && ['admin','system_admin'].includes(State.user?.role)) {
      const [matches,teams]=await Promise.all([
        api(`/project-matching/projects/${selected}/matches`),
        api(`/project-matching/projects/${selected}/teams?team_size=${ProjectMatchingUI.teamSize}`),
      ]);
      State.projectMatches=matches;
      State.projectTeams=teams;
      State.projectMatchingError='';
    }
  } catch(e) { if (isCurrentNavigation(navigationId, 'project-matching')) State.projectMatchingError=e.message; }
  if (!isCurrentNavigation(navigationId, 'project-matching')) return;
  ProjectMatchingUI.busy=false;
  render();
}

async function refreshProjectTeams(size) {
  ProjectMatchingUI.teamSize=Number(size)||3;
  if (!State.selectedMatchingProjectId) return;
  try {
    State.projectTeams=await api(`/project-matching/projects/${State.selectedMatchingProjectId}/teams?team_size=${ProjectMatchingUI.teamSize}`);
    State.projectMatchingError='';
  } catch(e){ State.projectMatchingError=e.message; }
  renderProjectMatching();
}

async function inferProjectDraft(e) {
  e.preventDefault();
  const title=document.getElementById('pmDraftTitle')?.value?.trim();
  const description=document.getElementById('pmDraftDescription')?.value?.trim();
  if (!title) return;
  ProjectMatchingUI.draftBusy=true; renderProjectMatching();
  try {
    State.projectRequirementDraft=await api('/project-matching/draft-requirements',{method:'POST',body:JSON.stringify({title,description})});
    State.projectDraftInput={title,description};
    State.projectMatchingError='';
  } catch(e){ State.projectMatchingError=e.message; }
  ProjectMatchingUI.draftBusy=false; renderProjectMatching();
}

async function saveProjectDraft() {
  const draft=State.projectRequirementDraft; const input=State.projectDraftInput;
  if (!draft||!input) return;
  ProjectMatchingUI.saveBusy=true; renderProjectMatching();
  try {
    const payload={
      title:input.title, description:input.description||null, research_direction:'教师新建科研方向', status:'active',
      capability_requirements:(draft.capability_requirements||[]).map(r=>({capability_id:r.capability_id,required_level:r.required_level,weight:r.weight,is_critical:r.is_critical,note:`草案关键词：${(r.matched_keywords||[]).join('、')}`})),
      knowledge_requirements:(draft.knowledge_requirements||[]).map(r=>({knowledge_node_id:r.knowledge_node_id,required_level:r.required_level,weight:r.weight,is_critical:r.is_critical,note:`草案关键词：${(r.matched_keywords||[]).join('、')}`})),
      metadata:{created_from:'v4.5-explainable-draft'}
    };
    const created=await api('/project-matching/projects',{method:'POST',body:JSON.stringify(payload)});
    State.projectRequirementDraft=null; State.projectDraftInput=null;
    await openProjectMatching(created.id);
  } catch(e){ State.projectMatchingError=e.message; ProjectMatchingUI.saveBusy=false; renderProjectMatching(); return; }
  ProjectMatchingUI.saveBusy=false;
}

function renderProjectMatching() {
  const isAdmin=['admin','system_admin'].includes(State.user?.role);
  if (ProjectMatchingUI.busy && !State.projectMatches) {
    app.innerHTML=`<div class="page-shell">${topbar('EnerTri 项目人才匹配','V4.5 Stage 3 · 项目能力模型 → 学生匹配 → 团队组建')}<div class="card panel">正在计算项目需求与学生能力画像匹配...</div></div>`;
    bindCommon(); return;
  }
  if (!isAdmin) {
    app.innerHTML=`<div class="page-shell">${topbar('EnerTri 项目人才匹配','V4.5 Stage 3')}<div class="card panel"><h2>教师侧科研人才匹配</h2><p>该页面会比较多名学生的个人科研画像，因此当前仅开放给教师/管理员角色。学生仍可在“个人科研画像”中查看自己的证据、能力和知识缺口。</p></div></div>`;
    bindCommon(); return;
  }
  const data=State.projectMatches||{};
  const project=data.project||(State.matchingProjects||[]).find(p=>Number(p.id)===Number(State.selectedMatchingProjectId))||{};
  const candidates=data.candidates||[];
  const teams=State.projectTeams?.teams||[];
  const top=candidates[0]; const topTeam=teams[0];
  const projectOptions=(State.matchingProjects||[]).map(p=>`<option value="${p.id}" ${Number(p.id)===Number(State.selectedMatchingProjectId)?'selected':''}>${escapeHtml(p.title)} · ${escapeHtml(p.status)}</option>`).join('');
  const capReq=(project.capability_requirements||[]).map(pmReqHtml).join('');
  const knowledgeReq=(project.knowledge_requirements||[]).map(req=>`<div class="pm-knowledge-req ${req.is_critical?'critical':''}"><strong>${escapeHtml(req.name_zh)}</strong><span>L${Number(req.required_level).toFixed(1)}</span><small>${escapeHtml(req.domain)}</small></div>`).join('');

  const candidateHtml=candidates.slice(0,6).map((c,i)=>{
    const details=(c.capability_details||[]).map(r=>`<div class="pm-fit-row"><div><strong>${escapeHtml(r.name_zh)}</strong><small>当前 L${Number(r.current_level).toFixed(1)} / 要求 L${Number(r.required_level).toFixed(1)} ${r.is_critical?'· 关键':''}</small></div>${pmScoreBar(r.satisfaction,'compact')}</div>`).join('');
    const gaps=(c.gaps||[]).slice(0,3).map(g=>`<span>${escapeHtml(g.name_zh)} ${Number(g.satisfaction).toFixed(0)}%</span>`).join('');
    const advantages=(c.advantages||[]).slice(0,3).map(g=>`<span>${escapeHtml(g.name_zh)}</span>`).join('');
    return `<article class="pm-candidate-card ${i===0?'top-candidate':''}"><div class="pm-candidate-rank"><span>#${i+1}</span><div><strong>${escapeHtml(c.display_name)}</strong><small>${escapeHtml(c.research_direction||'未设置方向')}</small></div><b class="${pmMatchClass(c.match_score)}">${Number(c.match_score).toFixed(1)}%</b></div><div class="pm-candidate-kpis"><span>能力匹配 <b>${Number(c.capability_fit).toFixed(1)}</b></span><span>知识匹配 <b>${Number(c.knowledge_fit).toFixed(1)}</b></span><span>证据可信 <b>${Number(c.evidence_confidence).toFixed(1)}%</b></span></div><div class="pm-candidate-summary"><div><small>推荐理由</small><p>${escapeHtml(c.summary?.strength||'')}</p><div class="pm-advantage-tags">${advantages||'<span>暂无显著优势项</span>'}</div></div><div><small>主要缺口</small><p>${escapeHtml(c.summary?.gap||'')}</p><div class="pm-gap-tags">${gaps||'<span>无明显缺口</span>'}</div></div></div><details ${i===0?'open':''}><summary>逐项查看项目要求满足度</summary><div class="pm-fit-list">${details}</div></details></article>`;
  }).join('');

  const teamHtml=teams.slice(0,4).map((team,i)=>`<article class="pm-team-card ${i===0?'best-team':''}"><div class="pm-team-head"><div><span>${i===0?'推荐团队':'备选团队'} #${i+1}</span><strong>${Number(team.team_score).toFixed(1)}%</strong><small>需求覆盖 ${Number(team.coverage_score).toFixed(1)} · 互补增益 +${Number(team.complementarity_gain).toFixed(1)}</small></div><div class="pm-team-ring">${Number(team.team_score).toFixed(0)}</div></div><div class="pm-team-members">${team.members.map(m=>`<div><span>${escapeHtml(m.display_name.slice(0,1))}</span><strong>${escapeHtml(m.display_name)}</strong><small>个人匹配 ${Number(m.individual_match).toFixed(1)}%</small><p>${m.suggested_responsibilities.map(escapeHtml).join(' / ')}</p></div>`).join('')}</div><div class="pm-team-gaps"><strong>团队剩余缺口</strong>${team.remaining_gaps.length?team.remaining_gaps.map(g=>`<span>${escapeHtml(g.name_zh)} ${Number(g.satisfaction).toFixed(0)}%</span>`).join(''):'<span class="success-gap">主要要求均达到 85% 以上</span>'}</div></article>`).join('');

  const draft=State.projectRequirementDraft;
  const draftHtml=draft?`<div class="pm-draft-result"><div class="section-head"><div><span class="eyebrow">Requirement Draft</span><h3>可解释需求草案</h3><p class="muted">${escapeHtml(draft.note||'')}</p></div><button class="btn primary" id="pmSaveDraftBtn" ${ProjectMatchingUI.saveBusy?'disabled':''}>${ProjectMatchingUI.saveBusy?'保存中…':'确认并保存为项目'}</button></div><div class="pm-draft-grid"><div><strong>能力要求</strong>${(draft.capability_requirements||[]).map(r=>`<div class="pm-draft-item"><span>${r.is_critical?'关键':'一般'}</span><b>${escapeHtml(r.name_zh)}</b><small>L${Number(r.required_level).toFixed(1)} · ${(r.matched_keywords||[]).map(escapeHtml).join(' / ')}</small></div>`).join('')}</div><div><strong>知识要求</strong>${(draft.knowledge_requirements||[]).map(r=>`<div class="pm-draft-item knowledge"><span>${r.is_critical?'关键':'知识'}</span><b>${escapeHtml(r.name_zh)}</b><small>L${Number(r.required_level).toFixed(1)} · ${(r.matched_keywords||[]).map(escapeHtml).join(' / ')}</small></div>`).join('')||'<p class="muted">未识别到必须单列的知识节点。</p>'}</div></div></div>`:'';

  app.innerHTML=`<div class="page-shell project-matching-shell">${topbar('EnerTri 项目人才智能匹配','V4.5 Stage 3 · 项目需求 → 个体匹配 → 能力缺口 → 互补组队')}
    <section class="pm-hero"><div><span class="eyebrow">Project × Research Digital Twin</span><h2>科研项目人才匹配</h2><p></p></div><div class="stage-badge"><span>03</span><strong>项目人才匹配</strong><small>可解释 · 可组队</small></div></section>
    ${State.projectMatchingError?`<div class="notice error">${escapeHtml(State.projectMatchingError)}</div>`:''}
    <section class="hero-grid pm-kpis"><div class="stat-card"><strong>${(project.capability_requirements||[]).length}</strong><span>能力要求</span><small>${(project.capability_requirements||[]).filter(x=>x.is_critical).length} 项关键</small></div><div class="stat-card"><strong>${data.candidate_count||0}</strong><span>候选学生</span><small>仅使用已有证据画像</small></div><div class="stat-card"><strong>${top?Number(top.match_score).toFixed(1)+'%':'—'}</strong><span>最高个人匹配</span><small>${escapeHtml(top?.display_name||'暂无')}</small></div><div class="stat-card"><strong>${topTeam?Number(topTeam.team_score).toFixed(1)+'%':'—'}</strong><span>推荐团队覆盖</span><small>${ProjectMatchingUI.teamSize} 人互补组队</small></div></section>

    <section class="pm-main-grid"><div class="card panel pm-project-panel"><div class="section-head"><div><span class="eyebrow">01 · Project Requirement Model</span><h2>项目需求能力模型</h2></div><select id="pmProjectSelect">${projectOptions}</select></div><div class="pm-project-title"><span>${escapeHtml(project.research_direction||'科研项目')}</span><h3>${escapeHtml(project.title||'尚无项目')}</h3><p>${escapeHtml(project.description||'')}</p></div><div class="pm-requirement-grid">${capReq}</div><div class="pm-knowledge-box"><strong>明确知识要求</strong><div>${knowledgeReq||'<span class="muted">该项目没有单列知识要求。</span>'}</div></div></div>
    <div class="card panel pm-scoring"><span class="eyebrow">Explainable Score</span><h2>匹配分怎么来</h2><p><strong>能力：</strong>${escapeHtml(data.scoring_model?.fit||'')}</p><p><strong>可信度：</strong>${escapeHtml(data.scoring_model?.confidence||'')}</p><p><strong>关键项：</strong>${escapeHtml(data.scoring_model?.critical||'')}</p><div class="pm-score-principle">不是“AI觉得像”，而是<strong>项目要求节点 × 学生证据画像</strong>逐项计算。</div></div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">02 · Student Matching</span><h2>学生智能匹配与缺口解释</h2><p class="muted">学生匹配</p></div></div><div class="pm-candidate-list">${candidateHtml||'<div class="empty-box">还没有拥有个人科研证据的候选学生。</div>'}</div></section>

    <section class="card panel"><div class="section-head"><div><span class="eyebrow">03 · Complementary Team</span><h2>科研团队智能组队</h2><p class="muted"></p></div><div class="pm-team-size"><span>团队人数</span>${[2,3,4].map(n=>`<button class="btn small ${ProjectMatchingUI.teamSize===n?'primary':'secondary'} js-pm-team-size" data-size="${n}">${n} 人</button>`).join('')}</div></div><div class="pm-team-grid">${teamHtml||'<div class="empty-box">候选人数不足，暂时无法组成团队。</div>'}</div></section>

    <section class="card panel pm-project-builder"><div class="section-head"><div><span class="eyebrow">04 · New Direction</span><h2>新建项目需求</h2><p class="muted"></p></div></div><form id="pmDraftForm"><label>课题 / 项目名称<input id="pmDraftTitle" required value="${escapeHtml(State.projectDraftInput?.title||'微纳热输运机器学习建模')}" placeholder="例如：基于机器学习的材料热物性预测"></label><label>项目说明<textarea id="pmDraftDescription" rows="4" placeholder="描述研究对象、方法、数据和预期任务">${escapeHtml(State.projectDraftInput?.description||'使用 Python 对材料热物性数据进行预测和误差分析，并结合微纳热输运机理解释结果。')}</textarea></label><button class="btn primary" type="submit">${ProjectMatchingUI.draftBusy?'解析中…':'生成需求草案'}</button></form>${draftHtml}</section>
  </div>`;
  bindCommon(); bindProjectMatching();
}

function bindProjectMatching() {
  document.getElementById('pmProjectSelect')?.addEventListener('change',e=>openProjectMatching(Number(e.target.value)));
  document.querySelectorAll('.js-pm-team-size').forEach(btn=>btn.addEventListener('click',()=>refreshProjectTeams(Number(btn.dataset.size))));
  document.getElementById('pmDraftForm')?.addEventListener('submit',inferProjectDraft);
  document.getElementById('pmSaveDraftBtn')?.addEventListener('click',saveProjectDraft);
}
