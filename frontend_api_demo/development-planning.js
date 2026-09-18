const DevelopmentPlanningUI = { busy:false, previewBusy:false };

function planningScoreBar(score) {
  const safe=Math.max(0,Math.min(100,Number(score)||0));
  return `<div class="dp-score"><div><span style="width:${safe}%"></span></div><strong>${safe.toFixed(1)}%</strong></div>`;
}
function planningTypeLabel(type){return ({course:'课程',book:'专业书',project_task:'科研实践'})[type]||type;}
function planningGapLabel(type){return type==='capability'?'能力缺口':'知识缺口';}

async function openDevelopmentPlanning(mode=null, targetUserId=null, goalId=null) {
  const navigationId = beginNavigation('development-planning');
  const isAdmin=['admin','system_admin'].includes(State.user?.role);
  const previousMode=State.developmentPlanningMode;
  const nextMode=mode || previousMode || (isAdmin?'teacher':'student');
  if(mode && previousMode && mode!==previousMode && targetUserId==null){
    State.dpSelectedUserId=null; State.dpSelectedGoalId=null;
  }
  State.developmentPlanningMode = nextMode;
  DevelopmentPlanningUI.busy=true; render();
  try {
    let users=[];
    if(isAdmin){ users=await api('/research-profile/users'); State.dpUsers=users; }
    let selectedUserId=targetUserId || State.dpSelectedUserId;
    if(!selectedUserId){
      if(State.developmentPlanningMode==='teacher') selectedUserId=State.user?.id;
      else selectedUserId=isAdmin?(users.find(u=>u.username==='student')?.id||State.user?.id):State.user?.id;
    }
    State.dpSelectedUserId=Number(selectedUserId);
    const goals=await api(`/development-planning/goals?user_id=${encodeURIComponent(State.dpSelectedUserId)}`);
    State.dpGoals=goals;
    const expectedType=State.developmentPlanningMode==='teacher'?'teacher_research_direction':'student_growth';
    let selectedGoal=goals.find(g=>Number(g.id)===Number(goalId||State.dpSelectedGoalId) && g.goal_type===expectedType)
      || goals.find(g=>g.goal_type===expectedType) || goals[0];
    State.dpSelectedGoalId=selectedGoal?.id||null;
    State.developmentPlan = selectedGoal ? await api(`/development-planning/goals/${selectedGoal.id}/analysis`) : null;
    State.developmentPlanningError='';
  } catch(e){ if (isCurrentNavigation(navigationId, 'development-planning')) State.developmentPlanningError=e.message; }
  if (!isCurrentNavigation(navigationId, 'development-planning')) return;
  DevelopmentPlanningUI.busy=false; render();
}

async function previewDevelopmentGoal(e){
  e.preventDefault();
  const title=document.getElementById('dpGoalTitle')?.value?.trim();
  const description=document.getElementById('dpGoalDescription')?.value?.trim();
  if(!title)return;
  const goalType=State.developmentPlanningMode==='teacher'?'teacher_research_direction':'student_growth';
  DevelopmentPlanningUI.previewBusy=true; renderDevelopmentPlanning();
  try{
    const data=await api('/development-planning/preview',{method:'POST',body:JSON.stringify({goal_type:goalType,title,description,user_id:Number(State.dpSelectedUserId)})});
    State.developmentPlan=data; State.dpSelectedGoalId=null; State.developmentPlanningError='';
  }catch(err){State.developmentPlanningError=err.message;}
  DevelopmentPlanningUI.previewBusy=false; renderDevelopmentPlanning();
}

async function saveDevelopmentGoal(){
  const title=document.getElementById('dpGoalTitle')?.value?.trim();
  const description=document.getElementById('dpGoalDescription')?.value?.trim();
  if(!title)return;
  const goalType=State.developmentPlanningMode==='teacher'?'teacher_research_direction':'student_growth';
  try{
    const row=await api('/development-planning/goals',{method:'POST',body:JSON.stringify({goal_type:goalType,title,description,user_id:Number(State.dpSelectedUserId)})});
    await openDevelopmentPlanning(State.developmentPlanningMode,State.dpSelectedUserId,row.id);
  }catch(err){State.developmentPlanningError=err.message;renderDevelopmentPlanning();}
}

function renderDevelopmentPlanning(){
  const data=State.developmentPlan;
  const isAdmin=['admin','system_admin'].includes(State.user?.role);
  if(DevelopmentPlanningUI.busy && !data){
    app.innerHTML=`<div class="page-shell">${topbar('EnerTri 科研成长与方向规划','V4.6 Stage 4 · Goal-to-Gap Development Planning')}<div class="card panel">正在把目标方向与当前知识能力画像进行差距计算…</div></div>`;bindCommon();return;
  }
  const mode=State.developmentPlanningMode||'student';
  const teacher=mode==='teacher';
  const goal=data?.goal||{};
  const fit=data?.target_fit||{};
  const capGaps=data?.capability_gaps||[];
  const knowledgeGaps=data?.knowledge_gaps||[];
  const recs=data?.recommendations||[];
  const path=data?.learning_path||[];
  const collaborators=data?.collaborator_recommendations||[];
  const literature=data?.literature_queries||[];
  const users=State.dpUsers||[];
  const goals=State.dpGoals||[];
  const targetUser=users.find(u=>Number(u.id)===Number(State.dpSelectedUserId));
  const expectedType=teacher?'teacher_research_direction':'student_growth';
  const compatibleGoals=goals.filter(g=>g.goal_type===expectedType);

  const modeSwitch=isAdmin?`<div class="dp-mode-switch"><button class="btn ${teacher?'primary':'secondary'}" data-dp-mode="teacher">教师新方向规划</button><button class="btn ${!teacher?'primary':'secondary'}" data-dp-mode="student">学生选课 / 成长路径</button></div>`:'';
  const userPicker=isAdmin&&!teacher?`<label class="dp-picker"><span>规划学生</span><select id="dpUserSelect">${users.filter(u=>!['admin','system_admin'].includes(u.role)).map(u=>`<option value="${u.id}" ${Number(u.id)===Number(State.dpSelectedUserId)?'selected':''}>${escapeHtml(u.display_name)} · ${escapeHtml(u.research_direction||u.role)}</option>`).join('')}</select></label>`:'';
  const goalPicker=compatibleGoals.length?`<label class="dp-picker"><span>已保存目标</span><select id="dpGoalSelect">${compatibleGoals.map(g=>`<option value="${g.id}" ${Number(g.id)===Number(State.dpSelectedGoalId)?'selected':''}>${escapeHtml(g.title)}</option>`).join('')}</select></label>`:'';

  const gapsHtml=[...capGaps.map(x=>({...x,_type:'capability'})),...knowledgeGaps.map(x=>({...x,_type:'knowledge'}))]
    .sort((a,b)=>Number(b.severity)-Number(a.severity)).slice(0,8).map(g=>`<article class="dp-gap ${g.is_critical?'critical':''}"><div><span>${planningGapLabel(g._type)}</span>${g.is_critical?'<b>关键</b>':''}</div><h3>${escapeHtml(g.name_zh)}</h3><p>当前 L${Number(g.current_level||0).toFixed(1)} / 目标 L${Number(g.required_level||0).toFixed(1)}</p>${planningScoreBar(g.satisfaction)}<small>缺口严重度 ${Number(g.severity||0).toFixed(1)} · 权重 ${Number(g.weight||0).toFixed(2)}</small></article>`).join('')||'<div class="empty-box">当前目标没有明显缺口。</div>';

  const recHtml=recs.slice(0,8).map((r,i)=>`<article class="dp-rec ${i<2?'top':''}"><div class="dp-rec-head"><span>${String(i+1).padStart(2,'0')}</span><div><b>${escapeHtml(planningTypeLabel(r.resource_type))}</b><strong>${escapeHtml(r.title)}</strong><small>${escapeHtml(r.discipline||'标准资源')} · ${escapeHtml(r.phase)}</small></div><em>${Number(r.priority_score).toFixed(1)}</em></div><p>${escapeHtml(r.why||r.description||'')}</p><div class="dp-close-tags">${(r.gap_closure||[]).slice(0,4).map(x=>`<span>${escapeHtml(x.name_zh)} +${Number(x.potential_gap_closure).toFixed(0)}</span>`).join('')}</div>${r.unmet_prerequisites?.length?`<div class="dp-prereq"><strong>先修提醒：</strong>${r.unmet_prerequisites.map(x=>`${escapeHtml(x.name_zh)}（当前 ${Number(x.current_score).toFixed(0)}）`).join('、')}</div>`:''}</article>`).join('')||'<div class="empty-box">当前标准库暂无可补齐这一目标的学习资源。</div>';

  const pathHtml=path.map(step=>`<article class="dp-path-step"><div class="dp-path-index">${step.phase}</div><div><span>${escapeHtml(step.name)}</span><h3>${escapeHtml(step.goal)}</h3><div class="dp-path-resources">${step.resources.map(r=>`<div><b>${escapeHtml(planningTypeLabel(r.resource_type))}</b><strong>${escapeHtml(r.title)}</strong><small>优先级 ${Number(r.priority_score).toFixed(1)} · ${escapeHtml((r.gap_closure||[]).slice(0,2).map(x=>x.name_zh).join(' / '))}</small></div>`).join('')}</div></div></article>`).join('')||'<div class="empty-box">暂未生成学习路径。</div>';

  const collaboratorHtml=teacher?`<section class="card panel"><div class="section-head"><div><span class="eyebrow">05 · Complementary People</span><h2>Useful</h2><p class="muted">互补学生推荐</p></div></div><div class="dp-collab-grid">${collaborators.map((c,i)=>`<article><div><span>${i+1}</span><strong>${escapeHtml(c.display_name)}</strong><b>${Number(c.complementarity_score).toFixed(1)}</b></div><p>${escapeHtml(c.research_direction||'')}</p><small>目标整体匹配 ${Number(c.target_match_score).toFixed(1)} · 证据可信度 ${Number(c.evidence_confidence).toFixed(1)}%</small><div>${(c.covers_my_gaps||[]).map(x=>`<em>${escapeHtml(x.name_zh)} ${Number(x.satisfaction).toFixed(0)}%</em>`).join('')}</div></article>`).join('')||'<div class="empty-box">暂无有证据画像的候选学生。</div>'}</div></section>`:'';

  const literatureHtml=`<section class="card panel dp-literature"><div class="section-head"><div><span class="eyebrow">${teacher?'06':'05'} · Literature Bridge</span><h2>建议优先检索的论文主题</h2><p class="muted"></p></div></div><div class="dp-query-grid">${literature.map((q,i)=>`<article><span>Q${i+1}</span><strong>${escapeHtml(q.query)}</strong><p>${escapeHtml(q.purpose)}</p></article>`).join('')}</div></section>`;

  app.innerHTML=`<div class="page-shell development-planning-shell">${topbar('EnerTri 科研成长与方向规划','V4.6 Stage 4 · 目标方向 → 知识能力差距 → 课程/书籍/科研实践 → 合作匹配')}
    <section class="dp-hero"><div><span class="eyebrow">Goal-to-Gap Development Engine</span><h2>${teacher?'教师新科研方向差距分析':'学生选课与科研成长路径'}</h2><p>${teacher?'':''}</p></div><div>${modeSwitch}<span class="stage-badge"><span>04</span><strong>发展路径规划</strong><small>Gap-driven · Explainable</small></span></div></section>
    ${State.developmentPlanningError?`<div class="notice error">${escapeHtml(State.developmentPlanningError)}</div>`:''}
    <section class="dp-control card panel"><div>${userPicker}${goalPicker}</div><div class="dp-current-goal"><span>${escapeHtml(goal.goal_type==='teacher_research_direction'?'教师方向':'成长目标')}</span><h3>${escapeHtml(goal.title||'尚未选择目标')}</h3><p>${escapeHtml(goal.description||'可在页面底部输入一个新的科研方向进行即时差距分析。')}</p>${goal.id?'<button class="btn small danger" id="dpArchiveGoalBtn">归档当前目标</button>':''}</div></section>
    <section class="hero-grid dp-kpis"><div class="stat-card"><strong>${Number(fit.match_score||0).toFixed(1)}%</strong><span>当前目标匹配</span><small>考虑证据可信度与关键缺口</small></div><div class="stat-card"><strong>${Number(fit.capability_fit||0).toFixed(1)}%</strong><span>能力准备度</span><small>目标能力逐项比较</small></div><div class="stat-card"><strong>${Number(fit.knowledge_fit||0).toFixed(1)}%</strong><span>知识准备度</span><small>当前知识体系 vs 目标知识</small></div><div class="stat-card"><strong>${Number(fit.critical_gap_count||0)}</strong><span>关键缺口</span><small>优先进入成长路径</small></div></section>
    <section class="card panel"><div class="section-head"><div><span class="eyebrow">01 · Gap Diagnosis</span><h2>从目标方向反推当前缺什么</h2><p class="muted"></p></div></div><div class="dp-gap-grid">${gapsHtml}</div></section>
    <section class="card panel"><div class="section-head"><div><span class="eyebrow">02 · Course & Resource Matching</span><h2>${teacher?'补知识资源优先级':'选课 / 读书 / 实践推荐'}</h2><p class="muted"></p></div></div><div class="dp-rec-grid">${recHtml}</div></section>
    <section class="card panel"><div class="section-head"><div><span class="eyebrow">03 · Learning Sequence</span><h2>建议成长路径</h2><p class="muted">基础补齐 → 系统深化 → 科研实践</p></div></div><div class="dp-path">${pathHtml}</div></section>
    <section class="card panel dp-loop"><div><span class="eyebrow">04 · Closed Loop</span><h2>能力更新流程</h2></div><div class="dp-loop-flow"><span>目标方向</span><b>→</b><span>知识/能力缺口</span><b>→</b><span>课程 / 专业书</span><b>→</b><span>科研任务</span><b>→</b><span>导师核验</span><b>→</b><span>画像升级</span></div></section>
    ${collaboratorHtml}${literatureHtml}
    <section class="card panel dp-builder"><div class="section-head"><div><span class="eyebrow">Try another direction</span><h2>输入一个新的目标方向即时试算</h2><p class="muted"></p></div></div><form id="dpGoalForm"><label>目标名称<input id="dpGoalTitle" value="${escapeHtml(teacher?'AI + 微纳热输运新课题':'芯片热管理科研方向')}" required></label><label>方向说明<textarea id="dpGoalDescription" rows="3">${escapeHtml(teacher?'希望将图神经网络、深度学习与材料热物性、微纳尺度传热结合，建立 Python 可解释预测模型。':'希望参与芯片热管理、微纳尺度传热和数值模拟项目，明确下一步优先选哪些课程。')}</textarea></label><div><button class="btn primary" type="submit">${DevelopmentPlanningUI.previewBusy?'分析中…':'即时差距分析'}</button><button class="btn secondary" type="button" id="dpSaveGoalBtn">保存为目标</button></div></form></section>
    <section class="card panel scoring-model"><div><span class="eyebrow">Scoring Transparency</span><h2>规划逻辑透明说明</h2></div><div><p><strong>缺口：</strong>${escapeHtml(data?.scoring_model?.gap||'')}</p><p><strong>资源排序：</strong>${escapeHtml(data?.scoring_model?.resource_priority||'')}</p><p><strong>路径：</strong>${escapeHtml(data?.scoring_model?.sequence||'')}</p></div></section>
  </div>`;
  bindCommon(); bindDevelopmentPlanning();
}

function bindDevelopmentPlanning(){
  document.querySelectorAll('[data-dp-mode]').forEach(btn=>btn.addEventListener('click',()=>openDevelopmentPlanning(btn.dataset.dpMode)));
  document.getElementById('dpUserSelect')?.addEventListener('change',e=>openDevelopmentPlanning('student',Number(e.target.value)));
  document.getElementById('dpGoalSelect')?.addEventListener('change',e=>openDevelopmentPlanning(State.developmentPlanningMode,State.dpSelectedUserId,Number(e.target.value)));
  document.getElementById('dpGoalForm')?.addEventListener('submit',previewDevelopmentGoal);
  document.getElementById('dpSaveGoalBtn')?.addEventListener('click',saveDevelopmentGoal);
  document.getElementById('dpArchiveGoalBtn')?.addEventListener('click',async()=>{
    if(!confirm('归档当前目标？归档后不再出现在目标列表中。'))return;
    try{await api(`/development-planning/goals/${State.dpSelectedGoalId}`,{method:'DELETE'});State.dpSelectedGoalId=null;await openDevelopmentPlanning(State.developmentPlanningMode,State.dpSelectedUserId);}catch(e){State.developmentPlanningError=e.message;renderDevelopmentPlanning();}
  });
}
