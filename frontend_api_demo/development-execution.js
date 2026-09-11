const DevelopmentExecutionUI={busy:false,updating:null};
function dxTypeLabel(type){return ({course:'课程',book:'专业书',project_task:'科研实践',publication:'论文知识库',research_project:'可参与项目'})[type]||type;}
function dxStatusLabel(s){return ({planned:'计划中',in_progress:'进行中',completed:'已完成',skipped:'已跳过'})[s]||s;}
function dxPhaseOrder(p){return ({'基础补齐':1,'系统深化':2,'文献桥接':3,'科研实践':4,'科研转化':5})[p]||9;}
async function openDevelopmentExecution(goalId=null){
  clearInterval(Foundation?.poller); clearInterval(KnowledgeUI?.poller);
  State.route='development-execution'; DevelopmentExecutionUI.busy=true; render();
  try{
    const goals=await api('/development-planning/goals');
    State.dxGoals=goals;
    const selected=goals.find(g=>Number(g.id)===Number(goalId||State.dxSelectedGoalId))||goals[0];
    State.dxSelectedGoalId=selected?.id||null;
    if(selected){
      let roadmap=await api(`/development-execution/goals/${selected.id}/roadmap`);
      if(!roadmap.items?.length) roadmap=await api(`/development-execution/goals/${selected.id}/roadmap/generate`,{method:'POST'});
      State.dxRoadmap=roadmap; State.dxError='';
    }else State.dxRoadmap=null;
  }catch(e){State.dxError=e.message;}
  DevelopmentExecutionUI.busy=false; render();
}
async function updateDevelopmentItem(itemId,status,progress=null){
  DevelopmentExecutionUI.updating=itemId; renderDevelopmentExecution();
  try{
    await api(`/development-execution/items/${itemId}`,{method:'PATCH',body:JSON.stringify({status,progress_percent:progress,completion_note:status==='completed'?'已按路线完成，提交系统生成待核验证据。':null})});
    State.dxRoadmap=await api(`/development-execution/goals/${State.dxSelectedGoalId}/roadmap`); State.dxError='';
  }catch(e){State.dxError=e.message;}
  DevelopmentExecutionUI.updating=null; renderDevelopmentExecution();
}
function renderDevelopmentExecution(){
  const data=State.dxRoadmap;
  if(DevelopmentExecutionUI.busy&&!data){app.innerHTML=`<div class="page-shell">${topbar('EnerTri 科研成长执行闭环','V4.7 Stage 5 · Dynamic Development Loop')}<div class="card panel">正在把发展目标转换为可执行科研成长路线…</div></div>`;bindCommon();return;}
  const goal=data?.goal||{}; const summary=data?.summary||{}; const fit=data?.current_fit||{}; const items=[...(data?.items||[])].sort((a,b)=>dxPhaseOrder(a.phase)-dxPhaseOrder(b.phase)||Number(b.priority_score)-Number(a.priority_score));
  const snapshots=data?.snapshots||[]; const baseline=Number(summary.baseline_match_score||fit.match_score||0); const latest=Number(summary.latest_snapshot_score||fit.match_score||0);
  const grouped={}; items.forEach(x=>(grouped[x.phase]||(grouped[x.phase]=[])).push(x));
  const phaseHtml=Object.entries(grouped).sort((a,b)=>dxPhaseOrder(a[0])-dxPhaseOrder(b[0])).map(([phase,rows],pi)=>`<section class="dx-phase"><div class="dx-phase-title"><span>0${pi+1}</span><div><b>${escapeHtml(phase)}</b><small>${rows.length} 个执行项</small></div></div><div class="dx-items">${rows.map(r=>`<article class="dx-item ${r.status}"><div class="dx-item-head"><span>${escapeHtml(dxTypeLabel(r.item_type))}</span><em>${Number(r.priority_score||0).toFixed(1)}</em></div><h3>${escapeHtml(r.title)}</h3><p>${escapeHtml(r.rationale||'')}</p><div class="dx-targets">${(r.gap_targets||[]).slice(0,3).map(t=>`<span>${escapeHtml(t.name_zh||t.type||'目标')} ${t.potential_gap_closure!=null?`+${Number(t.potential_gap_closure).toFixed(0)}`:''}</span>`).join('')}</div><div class="dx-progress"><div><span style="width:${Number(r.progress_percent||0)}%"></span></div><b>${Number(r.progress_percent||0)}%</b><strong>${escapeHtml(dxStatusLabel(r.status))}</strong></div><div class="dx-actions">${r.status==='planned'?`<button class="btn small secondary" data-dx-start="${r.id}">开始</button>`:''}${r.status==='in_progress'?`<button class="btn small primary" data-dx-complete="${r.id}">完成并提交证据</button>`:''}${r.status==='planned'?`<button class="btn small primary" data-dx-complete="${r.id}">直接完成</button>`:''}${r.status==='completed'?'<span class="dx-verified-note">已生成待核验证据/完成记录</span>':''}</div></article>`).join('')}</div></section>`).join('')||'<div class="empty-box">当前还没有路线项。</div>';
  const timeline=snapshots.map((s,i)=>`<div class="dx-snap"><span>${i+1}</span><div><b>${escapeHtml(s.snapshot_type==='baseline'?'基线':s.snapshot_type==='completion'?'完成项后重算':'重新计算')}</b><small>${escapeHtml((s.created_at||'').replace('T',' ').slice(0,16))}</small></div><strong>${Number(s.match_score||0).toFixed(1)}%</strong><em>能力 ${Number(s.capability_fit||0).toFixed(1)} · 知识 ${Number(s.knowledge_fit||0).toFixed(1)}</em></div>`).join('');
  app.innerHTML=`<div class="page-shell dx-shell">${topbar('EnerTri 科研成长执行闭环','V4.7 Stage 5 · 课程 / 书籍 / 论文 / 项目一体化路线 + 证据回流')}
    <section class="dx-hero"><div><span class="eyebrow">Dynamic Research Development Loop</span><h2>科研成长路线</h2><p>路线中的课程、专业书、论文知识库、科研实践和可参与项目来自同一个目标差距模型。完成标准资源后只生成低可信待核验证据，可形成临时画像变化；经教师核验后才升级为高可信科研证据。</p></div><span class="stage-badge"><span>05</span><strong>动态成长闭环</strong><small>Plan · Execute · Verify · Recalculate</small></span></section>
    ${State.dxError?`<div class="notice error">${escapeHtml(State.dxError)}</div>`:''}
    <section class="card panel dx-goal"><label><span>当前发展目标</span><select id="dxGoalSelect">${(State.dxGoals||[]).map(g=>`<option value="${g.id}" ${Number(g.id)===Number(State.dxSelectedGoalId)?'selected':''}>${escapeHtml(g.title)}</option>`).join('')}</select></label><div><span>${escapeHtml(goal.goal_type==='teacher_research_direction'?'教师科研方向':'学生成长目标')}</span><h3>${escapeHtml(goal.title||'暂无目标')}</h3><p>${escapeHtml(goal.description||'')}</p></div></section>
    <section class="hero-grid dx-kpis"><div class="stat-card"><strong>${Number(summary.progress_percent||0).toFixed(1)}%</strong><span>路线执行进度</span><small>${summary.completed||0}/${summary.total||0} 已完成</small></div><div class="stat-card"><strong>${Number(fit.match_score||0).toFixed(1)}%</strong><span>当前目标匹配</span><small>能力 ${Number(fit.capability_fit||0).toFixed(1)} · 知识 ${Number(fit.knowledge_fit||0).toFixed(1)}</small></div><div class="stat-card"><strong>${Number(summary.pending_evidence_count||0)}</strong><span>待核验证据</span><small>待核验仅按低可信权重参与</small></div><div class="stat-card"><strong>${(latest-baseline)>=0?'+':''}${(latest-baseline).toFixed(1)}</strong><span>目标匹配变化</span><small>基线 ${baseline.toFixed(1)} → 最新 ${latest.toFixed(1)}</small></div></section>
    <section class="card panel"><div class="section-head"><div><span class="eyebrow">01 · Integrated Roadmap</span><h2>课程 + 专业书 + 论文 + 科研实践 + 项目</h2><p class="muted"></p></div></div><div class="dx-roadmap">${phaseHtml}</div></section>
    <section class="card panel dx-loop"><div><span class="eyebrow">02 · Evidence Return</span><h2>证据更新流程</h2><p>${escapeHtml(data?.closed_loop||'')}</p></div><div class="dx-loop-flow"><span>完成路线项</span><b>→</b><span>生成待核验证据</span><b>→</b><span>导师核验</span><b>→</b><span>画像重算</span><b>→</b><span>目标匹配重算</span><b>→</b><span>下一轮路线</span></div></section>
    <section class="card panel"><div class="section-head"><div><span class="eyebrow">03 · Progress Snapshots</span><h2>动态成长轨迹</h2><p class="muted">动态成长轨迹</p></div></div><div class="dx-timeline">${timeline||'<div class="empty-box">还没有成长快照。</div>'}</div></section>
  </div>`;
  bindCommon(); bindDevelopmentExecution();
}
function bindDevelopmentExecution(){
  document.getElementById('dxGoalSelect')?.addEventListener('change',e=>openDevelopmentExecution(Number(e.target.value)));
  document.querySelectorAll('[data-dx-start]').forEach(b=>b.addEventListener('click',()=>updateDevelopmentItem(Number(b.dataset.dxStart),'in_progress',30)));
  document.querySelectorAll('[data-dx-complete]').forEach(b=>b.addEventListener('click',()=>updateDevelopmentItem(Number(b.dataset.dxComplete),'completed',100)));
}
