const app = document.getElementById('app');
const State = {
  loading: true,
  error: '',
  route: 'home',
  user: getSavedUser(),
  categories: [],
  terms: [],
  articles: [],
  progressMap: {},
  selectedCategoryId: null,
  selectedTermId: null,
  selectedArticleId: null,
  searchText: '',
  adminFilter: '',
  adminStatus: 'all',
  importBusy: false,
  importResult: null,
  importError: '',
  editingId: null,
  quiz: null,
  quizAnswers: {},
  quizChecked: false,
  quizResult: null,
};

boot();
async function boot() {
  try {
    if (getToken()) {
      try { State.user = await api('/auth/me'); saveAuth(getToken(), State.user); }
      catch (e) { if(e.status !== 401) throw e; State.user = null; }
    }
    if (State.user?.must_change_password) { State.loading=false; return renderPasswordChange(); }
    await refreshData();
  }
  catch (e) { State.error = e.message; }
  State.loading = false;
  render();
}
async function refreshData() {
  const { categories, terms, articles, progress } = await loadDbFromApi(['admin','system_admin'].includes(State.user?.role) ? 'all' : 'approved');
  State.categories = categories.map(c => ({ ...c, id: String(c.id) }));
  State.terms = terms.map(termToDemo);
  State.articles = articles.map(articleToDemo);
  State.progressMap = Object.fromEntries((progress || []).map(p => [Number(p.term_id), p]));
  State.selectedCategoryId ||= State.categories[0]?.id || null;
  State.selectedTermId ||= featuredTerms()[0]?.id || State.terms[0]?.id || null;
  State.selectedArticleId ||= State.articles[0]?.id || null;
}
function escapeHtml(v) { return String(v ?? '').replace(/[&<>"']/g, s => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[s])); }
function normalize(v) { return String(v || '').toLowerCase().trim(); }
function splitCsv(v) { return String(v || '').replace(/；/g, ',').replace(/，/g, ',').split(',').map(s => s.trim()).filter(Boolean); }
function categories() { return State.categories; }
function terms() { return State.terms; }
function articles() { return State.articles; }
function getCategory(id) { return categories().find(c => c.id === String(id)); }
function getTerm(id) { return terms().find(t => t.id === Number(id)); }
function getArticle(id) { return articles().find(a => a.id === Number(id)); }
function currentTerm() { return getTerm(State.selectedTermId) || terms()[0]; }
function featuredTerms() { return terms().filter(t => t.featured); }
function termsByCategory(id) { return terms().filter(t => t.categoryId === String(id)); }
function hasVideo(t) {
  const path = String(t?.media?.videoPath || '').trim();
  return !!path && !['待上传', '待补充', '暂无', '无', 'none', 'null', 'n/a'].includes(path.toLowerCase());
}
function relatedTerms(t) { return (t?.relatedIds || []).map(getTerm).filter(Boolean); }
function progressFor(termId) { return State.progressMap[Number(termId)] || { term_id: Number(termId), is_favorite: false, learned_at: null, quiz_best_score: 0 }; }
function favoriteTerms() { return terms().filter(t => progressFor(t.id).is_favorite); }
function learnedTerms() { return terms().filter(t => progressFor(t.id).learned_at); }
function searchTerms(q) {
  const n = normalize(q);
  if (!n) return [];
  return terms().filter(t => [t.term.zh, t.term.en, t.term.ru, t.meaning.zh, t.meaning.popular, t.meaning.en, ...(t.keywords || [])].map(normalize).some(x => x.includes(n)));
}
function relatedArticles(term) {
  if (!term) return articles();
  const signals = [term.term.zh, term.term.en, ...(term.keywords || [])].map(normalize).filter(Boolean);
  const matched = articles().filter(a => [a.title, a.summary, a.content, ...(a.relatedKeywords || [])].map(normalize).some(x => signals.some(s => x.includes(s) || s.includes(x))));
  return matched.length ? matched : articles();
}
function statusBadge(s) {
  const map = { draft: '草稿', submitted: '待审核', approved: '已通过' };
  return map[s] || s;
}
function importResultHtml() {
  if (State.importBusy) return '<div class="notice import-result">正在导入 Excel，请稍候...</div>';
  if (State.importError) return `<div class="notice import-result error">导入失败：${escapeHtml(State.importError)}</div>`;
  if (!State.importResult) return '';
  const errors = State.importResult.errors || [];
  return `<div class="notice import-result success"><strong>导入完成：</strong>成功 ${State.importResult.imported || 0} 条，跳过 ${State.importResult.skipped || 0} 条。${errors.length ? `<details><summary>查看 ${errors.length} 条错误/警告</summary><ul>${errors.map(err => `<li>${escapeHtml(err)}</li>`).join('')}</ul></details>` : ''}</div>`;
}
function render() {
  if (State.loading) { app.innerHTML = '<div class="page-shell"><div class="card panel">正在连接数据库 API...</div></div>'; return; }
  if (State.error) { app.innerHTML = `<div class="page-shell"><div class="card panel"><h2>无法连接 API</h2><p>${escapeHtml(State.error)}</p><p class="muted">服务暂时不可用，请稍后刷新；持续失败时请联系试用管理员。</p></div></div>`; return; }
  if (State.user?.must_change_password || State.route === 'password') return renderPasswordChange();
  if (State.route === 'login') return renderLogin();
  if (State.route === 'admin') return renderAdmin();
  if (State.route === 'workspace') return renderWorkspace();
  if (State.route === 'task-center') return renderTaskCenter();
  if (State.route === 'file-center') return renderFileCenter();
  if (State.route === 'audit-center') return renderAuditCenter();
  if (State.route === 'knowledge') return renderKnowledgeSystem();
  if (State.route === 'capability-standards') return renderCapabilityStandards();
  if (State.route === 'research-profile') return renderResearchProfile();
  if (State.route === 'project-matching') return renderProjectMatching();
  if (State.route === 'development-planning') return renderDevelopmentPlanning();
  if (State.route === 'development-execution') return renderDevelopmentExecution();
  return renderHome();
}
function topbar(title = 'EnerTri', subtitle = '能源专业三语术语学习平台') {
  const isAdmin = ['admin','system_admin'].includes(State.user?.role);
  const adminNav = isAdmin
    ? `${State.route === 'admin' ? '<button class="btn secondary" id="toHomeBtn">返回前台</button>' : '<button class="btn secondary" id="toAdminBtn">术语后台</button>'}<button class="btn secondary" id="toAuditBtn">审计日志</button>`
    : '';
  const workspaceNav = State.user
    ? `${State.route === 'workspace' ? '<button class="btn secondary" id="toHomeBtn">返回前台</button>' : '<button class="btn primary" id="toWorkspaceBtn">智能工作台</button>'}<button class="btn ${State.route === 'knowledge' ? 'primary' : 'secondary'}" id="toKnowledgeBtn">论文知识库</button><button class="btn ${State.route === 'capability-standards' ? 'primary' : 'secondary'}" id="toCapabilityStandardsBtn">能力标准库</button><button class="btn ${State.route === 'research-profile' ? 'primary' : 'secondary'}" id="toResearchProfileBtn">个人科研画像</button>${isAdmin?`<button class="btn ${State.route === 'project-matching' ? 'primary' : 'secondary'}" id="toProjectMatchingBtn">项目人才匹配</button>`:''}<button class="btn ${State.route === 'development-planning' ? 'primary' : 'secondary'}" id="toDevelopmentPlanningBtn">成长与方向规划</button><button class="btn ${State.route === 'development-execution' ? 'primary' : 'secondary'}" id="toDevelopmentExecutionBtn">成长执行闭环</button><button class="btn secondary" id="toTasksBtn">任务中心</button><button class="btn secondary" id="toFilesBtn">文件管理</button>`
    : '';
  return `<header class="topbar"><div class="brand"><div class="brand-mark">ET</div><div><h1>${escapeHtml(title)}</h1><p>${escapeHtml(subtitle)}</p></div></div><div class="topbar-actions">${State.user ? `<span class="badge">${escapeHtml(State.user.display_name)} · ${escapeHtml(State.user.role)}</span>${workspaceNav}${adminNav}<button class="btn secondary" id="changePasswordBtn">修改密码</button><button class="btn ghost" id="logoutBtn">退出</button>` : '<button class="btn primary" id="toLoginBtn">登录学习</button>'}</div></header>`;
}
function termCardHtml(term) {
  const p = progressFor(term.id);
  const favText = p.is_favorite ? '★ 已收藏' : '☆ 收藏';
  const learnedText = p.learned_at ? '✓ 已学' : '标记已学';
  const quizScore = p.quiz_best_score ? `<span class="badge success">测验最高 ${p.quiz_best_score} 分</span>` : '';
  const related = relatedTerms(term);
  return `<article class="card term-card"><div class="term-head"><div><span class="badge primary">${escapeHtml(getCategory(term.categoryId)?.name_zh || '未分类')}</span><span class="badge ${term.reviewStatus === 'approved' ? 'success' : 'warning'}">${statusBadge(term.reviewStatus)}</span>${quizScore}<h2>${escapeHtml(term.term.zh)}</h2><p class="muted">${escapeHtml(term.term.en)} ${term.term.ru ? ' · ' + escapeHtml(term.term.ru) : ''}</p></div><div class="inline-actions">${State.user ? `<button class="btn small secondary js-favorite" data-id="${term.id}">${favText}</button><button class="btn small secondary js-learned" data-id="${term.id}">${learnedText}</button>` : '<span class="muted">登录后可收藏、记录进度</span>'}</div></div><div class="definition-grid"><div><h3>学术解释</h3><p>${escapeHtml(term.meaning.zh)}</p></div><div><h3>通俗解释</h3><p>${escapeHtml(term.meaning.popular || '暂无')}</p></div><div><h3>English</h3><p>${escapeHtml(term.meaning.en || 'N/A')}</p></div></div><div class="info-box"><h4>应用场景</h4><p>${escapeHtml(term.examples.zh || '暂无')}</p></div>${term.formulaModel ? `<div class="info-box formula-box"><h4>公式 / 模型</h4><p>${escapeHtml(term.formulaModel)}</p><small class="muted">已预留公式模块，可后续接入 KaTeX/MathJax 渲染。</small></div>` : ''}<div class="support-tags">${(term.keywords || []).map(k => `<span class="chip">${escapeHtml(k)}</span>`).join('')}</div>${related.length ? `<div class="info-box"><h4>相关术语</h4><div class="support-tags">${related.map(t => `<button class="quick-tag" data-term="${t.id}">${escapeHtml(t.term.zh)}</button>`).join('')}</div></div>` : ''}${term.references?.length ? `<div class="info-box"><h4>参考文献</h4><ol>${term.references.map(r => `<li>${escapeHtml(r)}</li>`).join('')}</ol></div>` : ''}</article>`;
}
function videoPanelHtml(term) {
  if (!hasVideo(term)) {
    return term?.media?.videoPlanned
      ? '<div class="empty-box">该术语已标记为有视频，视频文件待管理员上传。</div>'
      : '<div class="empty-box">该术语暂未关联视频。</div>';
  }
  const raw = term.media.videoPath;
  const path = raw.startsWith('/media') ? raw : raw.startsWith('videos/') ? `/media/${raw}` : raw;
  return `<div class="video-box"><video controls preload="metadata"><source src="${escapeHtml(path)}" type="video/mp4" />当前浏览器无法直接播放该视频文件。</video></div><div class="thumb-grid"><div class="thumb-card"><div class="thumb-preview" style="background:${escapeHtml(term.media.thumbnailStyle)}">${escapeHtml(term.media.thumbnailLabel)}</div><div class="thumb-meta"><strong>${escapeHtml(term.term.zh)}</strong><span>${escapeHtml(term.media.thumbnailHint)}</span></div></div></div>`;
}
function articlesPanelHtml(term) {
  const list = relatedArticles(term).slice(0, 4);
  const selected = getArticle(State.selectedArticleId) || list[0];
  return `<div class="card panel"><div class="section-head"><h3>专题科普</h3><span class="muted">${articles().length} 篇</span></div><div class="article-list">${list.map(a => `<button class="article-item ${selected?.id === a.id ? 'active' : ''}" data-article="${a.id}"><span class="article-cover">${escapeHtml(a.coverLabel)}</span><strong>${escapeHtml(a.title)}</strong><small>${escapeHtml(a.difficulty)} · ${(a.relatedKeywords || []).slice(0,3).map(escapeHtml).join(' / ')}</small></button>`).join('') || '<span class="muted">暂无专题文章</span>'}</div>${selected ? `<div class="article-detail"><h4>${escapeHtml(selected.title)}</h4><p class="muted">${escapeHtml(selected.summary)}</p><p>${escapeHtml(selected.content)}</p><div class="support-tags">${(selected.relatedKeywords || []).map(k => `<button class="quick-tag js-article-keyword" data-keyword="${escapeHtml(k)}">${escapeHtml(k)}</button>`).join('')}</div></div>` : ''}</div>`;
}
function learningPanelHtml(term) {
  if (!State.user) return `<div class="card panel"><div class="section-head"><h3>我的学习</h3></div><div class="empty-box">登录后可以收藏术语、标记已学并保存测验最高分。</div></div>`;
  const favs = favoriteTerms();
  const learned = learnedTerms();
  const p = term ? progressFor(term.id) : null;
  return `<div class="card panel"><div class="section-head"><h3>我的学习</h3><span class="badge primary">${learned.length}/${terms().length}</span></div><div class="progress-line"><span style="width:${terms().length ? Math.round(learned.length / terms().length * 100) : 0}%"></span></div><div class="mini-stats"><div><strong>${favs.length}</strong><small>收藏</small></div><div><strong>${learned.length}</strong><small>已学</small></div><div><strong>${p?.quiz_best_score || 0}</strong><small>当前测验分</small></div></div><h4>收藏夹</h4><div class="term-list compact">${favs.slice(0,6).map(t => `<button class="term-item" data-term="${t.id}">${escapeHtml(t.term.zh)}</button>`).join('') || '<span class="muted">暂无收藏</span>'}</div></div>`;
}
function quizPanelHtml(term) {
  const isCurrentQuiz = State.quiz && term && State.quiz.term_id === term.id;
  if (!term) return '';
  if (!isCurrentQuiz) return `<div class="card panel"><div class="section-head"><h3>随堂测验</h3></div><p class="muted">自动基于词条生成 3 道入门题，由服务端判题。</p><button class="btn primary" id="loadQuizBtn">开始测验</button></div>`;
  const resultMap = Object.fromEntries((State.quizResult?.results || []).map(item => [item.id, item]));
  return `<div class="card panel"><div class="section-head"><h3>${escapeHtml(State.quiz.title)}</h3><span class="muted">${State.quizResult ? `得分 ${State.quizResult.score}` : `${State.quiz.questions.length} 题`}</span></div><div class="quiz-list">${State.quiz.questions.map(q => { const result = resultMap[q.id]; return `<div class="quiz-question"><strong>${escapeHtml(q.question)}</strong>${q.options.map(o => { const checked = State.quizAnswers[q.id] === o.id ? 'checked' : ''; const stateClass = result ? (o.id === result.correct_answer ? 'correct' : (checked ? 'wrong' : '')) : ''; return `<label class="quiz-option ${stateClass}"><input type="radio" name="${q.id}" value="${o.id}" ${checked}>${escapeHtml(o.id)}. ${escapeHtml(o.text)}</label>`; }).join('')}${result ? `<p class="notice">正确答案：${escapeHtml(result.correct_answer)}。解析：${escapeHtml(result.explanation)}</p>` : ''}</div>`; }).join('')}</div><div class="inline-actions">${State.quizChecked ? '' : '<button class="btn primary" id="submitQuizBtn">提交测验</button>'}<button class="btn secondary" id="reloadQuizBtn">${State.quizChecked ? '再测一组' : '换一组题'}</button></div>${!State.user ? '<p class="muted">当前为游客自测；判题由服务端完成，登录后可保存最高分。</p>' : ''}</div>`;
}
function renderHome() {
  const term = currentTerm();
  const results = State.searchText ? searchTerms(State.searchText) : [];
  app.innerHTML = `<div class="page-shell">${topbar()}<section class="hero"><div class="card hero-panel"><h2>能源术语、科研与焊接智能平台</h2><p></p><div class="hero-grid"><div class="stat-card"><strong>${terms().length}</strong><span>术语</span></div><div class="stat-card"><strong>${articles().length}</strong><span>专题文章</span></div><div class="stat-card"><strong>${learnedTerms().length}</strong><span>已学记录</span></div><div class="stat-card"><strong>${terms().filter(hasVideo).length}</strong><span>视频</span></div></div></div><div class="card hero-side"><h3>推荐学习路径</h3><ul class="feature-list"><li>先读专题文章，建立背景知识</li><li>再查三语术语，理解专业表达</li><li>收藏重点词条，标记学习进度</li><li>最后用随堂测验自查掌握程度</li></ul></div></section><div class="layout"><aside class="card panel"><div class="section-head"><h3>分类导航</h3></div><div class="category-list">${categories().map(c => `<button class="category-item ${c.id === State.selectedCategoryId ? 'active' : ''}" data-category="${c.id}"><strong>${escapeHtml(c.name_zh)}</strong><br><span class="muted">${escapeHtml(c.name_en || '')}</span></button>`).join('')}</div><div class="section-head"><h3>当前分类术语</h3></div><div class="term-list">${termsByCategory(State.selectedCategoryId).map(t => `<button class="term-item ${t.id === term?.id ? 'active' : ''}" data-term="${t.id}">${progressFor(t.id).learned_at ? '✓ ' : ''}${escapeHtml(t.term.zh)}</button>`).join('') || '<span class="muted">暂无术语</span>'}</div></aside><section class="main-stack"><div class="card search-box"><div class="section-head"><h2>术语检索</h2><span class="muted">${State.searchText ? `检索到 ${results.length} 条` : '输入术语开始检索'}</span></div><div class="search-row"><input class="input" id="searchInput" value="${escapeHtml(State.searchText)}" placeholder="逆变器 / inverter / инвертор"><button class="btn primary" id="searchBtn">查询术语</button></div>${State.searchText ? `<div class="info-box"><h4>检索结果</h4>${results.map(t => `<button class="quick-tag" data-term="${t.id}">${escapeHtml(t.term.zh)} · ${escapeHtml(t.term.en)}</button>`).join('') || '<span class="muted">无结果</span>'}</div>` : ''}</div>${term ? termCardHtml(term) : '<div class="card panel">暂无术语数据</div>'}${quizPanelHtml(term)}</section><aside class="side-stack"><div class="card panel"><div class="section-head"><h3>视频学习</h3></div>${term ? videoPanelHtml(term) : ''}</div>${learningPanelHtml(term)}${articlesPanelHtml(term)}</aside></div></div>`;
  bindCommon();
}
function renderLogin(message = '') {
  app.innerHTML = `<div class="login-wrap"><section class="login-showcase"><div>${topbar('EnerTri 登录','数据库平台')}</div></section><section class="login-card-wrap"><div class="card login-card"><h2>账户登录</h2><p>请使用管理员分配的个人试用账号登录。</p>${message ? `<div class="notice">${escapeHtml(message)}</div>` : ''}<div class="form-grid"><div><label class="label">用户名</label><input class="input" id="loginUser" autocomplete="username"></div><div><label class="label">密码</label><input class="input" id="loginPass" type="password" autocomplete="current-password"></div><div class="inline-actions"><button class="btn primary" id="loginSubmit">登录</button><button class="btn secondary" id="backHomeBtn">返回首页</button></div></div></div></section></div>`;
  document.getElementById('loginSubmit').onclick = doLogin;
  document.getElementById('backHomeBtn').onclick = () => { State.route = 'home'; render(); };
}
function renderAdmin() {
  if (!['admin','system_admin'].includes(State.user?.role)) { State.route = 'login'; return renderLogin('请先以管理员身份登录。'); }
  const q = normalize(State.adminFilter);
  const filtered = terms().filter(t => (State.adminStatus === 'all' || t.reviewStatus === State.adminStatus) && (!q || [t.term.zh,t.term.en,t.term.ru,...t.keywords].map(normalize).some(x => x.includes(q))));
  const editing = getTerm(State.editingId);
  const importStatus = importResultHtml();
  app.innerHTML = `<div class="page-shell">${topbar('EnerTri 管理后台','词条录入、审核、数据维护与智能能力配置')}<section class="split"><div class="main-stack"><div class="card panel"><div class="section-head"><h2>术语库管理</h2><span class="muted">当前 ${filtered.length} 条</span></div><div class="toolbar"><input class="input" id="adminSearch" placeholder="筛选术语" value="${escapeHtml(State.adminFilter)}"><select class="select" id="adminStatus"><option value="all">全部状态</option><option value="draft">草稿</option><option value="submitted">待审核</option><option value="approved">已通过</option></select><button class="btn primary" id="newTermBtn">新增术语</button><button class="btn secondary" id="refreshBtn">刷新</button></div><div class="table-wrap" style="margin-top:16px"><table class="table"><thead><tr><th>ID</th><th>状态</th><th>分类</th><th>中文</th><th>English</th><th>贡献者</th><th>操作</th></tr></thead><tbody>${filtered.map(t => `<tr><td>${t.id}</td><td>${statusBadge(t.reviewStatus)}</td><td>${escapeHtml(getCategory(t.categoryId)?.name_zh || '')}</td><td>${escapeHtml(t.term.zh)}</td><td>${escapeHtml(t.term.en)}</td><td>${escapeHtml(t.contributorName || '')}</td><td class="actions"><button class="btn small js-edit" data-id="${t.id}">编辑</button><button class="btn small js-approve" data-id="${t.id}">通过</button><button class="btn small danger js-delete" data-id="${t.id}">删除</button></td></tr>`).join('')}</tbody></table></div></div><div class="card panel excel-import-panel"><div class="section-head"><div><h2>Excel 批量导入</h2><p class="muted">选择符合模板表头的 .xlsx 文件，系统会调用 <code>POST /api/import/excel</code> 写入术语库。</p></div></div><div class="import-row"><input class="input" id="excelFileInput" type="file" accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"><button class="btn primary" id="importExcelBtn" ${State.importBusy ? 'disabled' : ''}>${State.importBusy ? '导入中...' : '导入 Excel'}</button></div><p class="muted">必需列：中文术语、英文术语。其他列如关键词、解释、参考文献、审核状态会自动映射。</p>${importStatus}</div><div class="card panel"><div class="section-head"><h2>新增能力</h2></div><div class="support-tags"><span class="chip primary">专题文章 ${articles().length}</span><span class="chip primary">学习进度</span><span class="chip primary">随堂测验</span><span class="chip primary">收藏夹</span></div><p class="muted">专题文章接口已加入后端：GET/POST/PUT/DELETE /api/articles，可在后续单独扩展后台编辑页面。</p></div></div><aside class="card panel admin-form"><div class="section-head"><h2>${editing ? '编辑词条' : '新增词条'}</h2></div><form id="termForm" class="form-grid"><div class="form-row-2"><div><label class="label">分类</label><select class="select" name="categoryId">${categories().map(c => `<option value="${c.id}" ${editing?.categoryId === c.id ? 'selected' : ''}>${escapeHtml(c.name_zh)}</option>`).join('')}</select></div><div><label class="label">状态</label><select class="select" name="reviewStatus"><option value="draft">draft</option><option value="submitted">submitted</option><option value="approved">approved</option></select></div></div><div class="form-row-2"><div><label class="label">中文术语</label><input class="input" name="termZh" required value="${escapeHtml(editing?.term.zh || '')}"></div><div><label class="label">英文术语</label><input class="input" name="termEn" required value="${escapeHtml(editing?.term.en || '')}"></div></div><div><label class="label">俄文术语（可选）</label><input class="input" name="termRu" value="${escapeHtml(editing?.term.ru || '')}"></div><div><label class="label">中文解释（学术版）</label><textarea class="textarea" name="meaningZh">${escapeHtml(editing?.meaning.zh || '')}</textarea></div><div><label class="label">中文解释（通俗版）</label><textarea class="textarea" name="meaningPopular">${escapeHtml(editing?.meaning.popular || '')}</textarea></div><div><label class="label">英文解释（简要）</label><textarea class="textarea" name="meaningEn">${escapeHtml(editing?.meaning.en || '')}</textarea></div><div><label class="label">应用场景</label><textarea class="textarea" name="application">${escapeHtml(editing?.examples.zh || '')}</textarea></div><div><label class="label">公式 / 模型</label><input class="input" name="formulaModel" value="${escapeHtml(editing?.formulaModel || '')}"></div><div class="form-row-2"><div><label class="label">关键词（逗号分隔）</label><input class="input" name="keywords" value="${escapeHtml((editing?.keywords || []).join(', '))}"></div><div><label class="label">相关术语 ID</label><input class="input" name="relatedIds" value="${escapeHtml((editing?.relatedIds || []).join(', '))}"></div></div><div><label class="label">参考文献（用分号或逗号分隔）</label><textarea class="textarea" name="references">${escapeHtml((editing?.references || []).join('；'))}</textarea></div><div class="form-row-2"><div><label class="label">贡献者姓名</label><input class="input" name="contributorName" value="${escapeHtml(editing?.contributorName || '')}"></div><div><label class="label">研究方向</label><input class="input" name="contributorDirection" value="${escapeHtml(editing?.contributorResearchDirection || '')}"></div></div><div><label class="label">视频路径</label><input class="input" name="videoPath" value="${escapeHtml(editing?.media.videoPath || '')}" placeholder="/media/videos/xxx.mp4 或 videos/xxx.mp4"></div><div class="inline-actions"><button class="btn primary" type="submit">保存到数据库</button><button class="btn secondary" type="button" id="clearFormBtn">清空</button></div></form></aside></section></div>`;
  document.querySelector('select[name="reviewStatus"]').value = editing?.reviewStatus || 'draft';
  document.getElementById('adminStatus').value = State.adminStatus;
  bindCommon(); bindAdmin();
}
function bindCommon() {
  document.querySelectorAll('[data-category]').forEach(btn => btn.onclick = () => { State.selectedCategoryId = btn.dataset.category; State.selectedTermId = termsByCategory(State.selectedCategoryId)[0]?.id || null; clearQuiz(); render(); });
  document.querySelectorAll('[data-term]').forEach(btn => btn.onclick = () => { State.selectedTermId = Number(btn.dataset.term); State.selectedCategoryId = getTerm(State.selectedTermId)?.categoryId || State.selectedCategoryId; clearQuiz(); render(); });
  document.querySelectorAll('[data-article]').forEach(btn => btn.onclick = () => { State.selectedArticleId = Number(btn.dataset.article); render(); });
  document.querySelectorAll('.js-article-keyword').forEach(btn => btn.onclick = () => { State.searchText = btn.dataset.keyword; const r = searchTerms(State.searchText)[0]; if (r) { State.selectedTermId = r.id; State.selectedCategoryId = r.categoryId; } clearQuiz(); render(); });
  document.getElementById('searchBtn')?.addEventListener('click', () => { State.searchText = document.getElementById('searchInput').value.trim(); const r = searchTerms(State.searchText)[0]; if (r) { State.selectedTermId = r.id; State.selectedCategoryId = r.categoryId; } clearQuiz(); render(); });
  document.getElementById('searchInput')?.addEventListener('keydown', e => { if (e.key === 'Enter') document.getElementById('searchBtn').click(); });
  document.getElementById('toLoginBtn')?.addEventListener('click', () => { State.route = 'login'; render(); });
  document.getElementById('toAdminBtn')?.addEventListener('click', () => { State.route = 'admin'; render(); });
  document.getElementById('toWorkspaceBtn')?.addEventListener('click', () => { clearInterval(Foundation.poller); State.route = 'workspace'; render(); });
  document.getElementById('toKnowledgeBtn')?.addEventListener('click', () => openKnowledgeSystem());
  document.getElementById('toCapabilityStandardsBtn')?.addEventListener('click', () => openCapabilityStandards());
  document.getElementById('toResearchProfileBtn')?.addEventListener('click', () => openResearchProfile());
  document.getElementById('toProjectMatchingBtn')?.addEventListener('click', () => openProjectMatching());
  document.getElementById('toDevelopmentPlanningBtn')?.addEventListener('click', () => openDevelopmentPlanning());
  document.getElementById('toDevelopmentExecutionBtn')?.addEventListener('click', () => openDevelopmentExecution());
  document.getElementById('toTasksBtn')?.addEventListener('click', () => openTaskCenter());
  document.getElementById('toFilesBtn')?.addEventListener('click', () => openFileCenter());
  document.getElementById('toAuditBtn')?.addEventListener('click', () => openAuditCenter());
  document.getElementById('toHomeBtn')?.addEventListener('click', async () => { clearInterval(Foundation.poller); State.route = 'home'; clearQuiz(); await refreshData(); render(); });
  document.getElementById('changePasswordBtn')?.addEventListener('click', () => { State.route='password'; render(); });
  document.getElementById('logoutBtn')?.addEventListener('click', async () => { try { await api('/auth/logout',{method:'POST'}); } catch(e) { if(e.status!==401) { alert('退出失败，请重试'); return; } } saveAuth(null, null); State.user=null; State.progressMap={}; State.route='home'; await refreshData(); render(); });
  document.querySelectorAll('.js-favorite').forEach(btn => btn.onclick = () => toggleFavorite(Number(btn.dataset.id)));
  document.querySelectorAll('.js-learned').forEach(btn => btn.onclick = () => toggleLearned(Number(btn.dataset.id)));
  document.getElementById('loadQuizBtn')?.addEventListener('click', loadCurrentQuiz);
  document.getElementById('reloadQuizBtn')?.addEventListener('click', loadCurrentQuiz);
  document.querySelectorAll('.quiz-option input').forEach(input => input.onchange = e => { State.quizAnswers[e.target.name] = e.target.value; });
  document.getElementById('submitQuizBtn')?.addEventListener('click', submitCurrentQuiz);
}
function bindAdmin() {
  document.getElementById('adminSearch').oninput = e => { State.adminFilter = e.target.value; renderAdmin(); };
  document.getElementById('adminStatus').onchange = e => { State.adminStatus = e.target.value; renderAdmin(); };
  document.getElementById('newTermBtn').onclick = () => { State.editingId = null; renderAdmin(); };
  document.getElementById('refreshBtn').onclick = async () => { await refreshData(); renderAdmin(); };
  document.getElementById('importExcelBtn').onclick = importExcelFromAdmin;
  document.getElementById('clearFormBtn').onclick = () => { State.editingId = null; renderAdmin(); };
  document.querySelectorAll('.js-edit').forEach(b => b.onclick = () => { State.editingId = Number(b.dataset.id); renderAdmin(); });
  document.querySelectorAll('.js-approve').forEach(b => b.onclick = async () => { await api(`/terms/${b.dataset.id}/review`, {method:'POST', body: JSON.stringify({review_status:'approved', review_comment:'审核通过'})}); await refreshData(); renderAdmin(); });
  document.querySelectorAll('.js-delete').forEach(b => b.onclick = async () => { if (!confirm('确定删除该词条吗？')) return; await api(`/terms/${b.dataset.id}`, {method:'DELETE'}); await refreshData(); renderAdmin(); });
  document.getElementById('termForm').onsubmit = saveTerm;
}
async function importExcelFromAdmin() {
  const input = document.getElementById('excelFileInput');
  const file = input?.files?.[0];
  if (!file) {
    State.importResult = null;
    State.importError = '请先选择一个 .xlsx 文件。';
    return renderAdmin();
  }
  if (!file.name.toLowerCase().endsWith('.xlsx')) {
    State.importResult = null;
    State.importError = '目前仅支持 .xlsx 格式，请使用 Excel 工作簿文件。';
    return renderAdmin();
  }
  State.importBusy = true;
  State.importResult = null;
  State.importError = '';
  renderAdmin();
  try {
    State.importResult = await importExcelApi(file);
    await refreshData();
  } catch (e) {
    State.importError = e.message || '导入失败';
  } finally {
    State.importBusy = false;
    renderAdmin();
  }
}
function clearQuiz() { State.quiz = null; State.quizAnswers = {}; State.quizChecked = false; State.quizResult = null; }
async function loadCurrentQuiz() {
  const term = currentTerm();
  if (!term) return;
  State.quiz = await loadTermQuiz(term.id);
  State.quizAnswers = {};
  State.quizChecked = false;
  State.quizResult = null;
  render();
}
async function submitCurrentQuiz() {
  if (!State.quiz) return;
  try {
    State.quizResult = await submitTermQuiz(State.quiz.term_id, State.quiz.quiz_token, State.quizAnswers);
    State.quizChecked = true;
    if (State.user) await refreshData();
  } catch (e) {
    alert(e.message);
  }
  render();
}
async function toggleFavorite(termId) {
  if (!State.user) { State.route = 'login'; return renderLogin('请先登录再收藏术语。'); }
  const now = progressFor(termId);
  const updated = await updateTermProgress(termId, { is_favorite: !now.is_favorite });
  State.progressMap[termId] = updated;
  render();
}
async function toggleLearned(termId) {
  if (!State.user) { State.route = 'login'; return renderLogin('请先登录再记录学习进度。'); }
  const now = progressFor(termId);
  const updated = await updateTermProgress(termId, { learned: !now.learned_at });
  State.progressMap[termId] = updated;
  render();
}
async function doLogin() {
  try { State.user = await loginApi(document.getElementById('loginUser').value.trim(), document.getElementById('loginPass').value); if(State.user.must_change_password) {State.route='password';return render();} await refreshData(); State.route = ['admin','system_admin'].includes(State.user.role) ? 'admin' : 'home'; render(); }
  catch(e) { renderLogin(e.message); }
}
async function saveTerm(e) {
  e.preventDefault();
  const fd = new FormData(e.target);
  const item = { categoryId: fd.get('categoryId'), featured: false, reviewStatus: fd.get('reviewStatus'), reviewComment: '', term: { zh: fd.get('termZh').trim(), en: fd.get('termEn').trim(), ru: fd.get('termRu').trim() }, meaning: { zh: fd.get('meaningZh').trim(), popular: fd.get('meaningPopular').trim(), en: fd.get('meaningEn').trim() }, examples: { zh: fd.get('application').trim() }, formulaModel: fd.get('formulaModel').trim(), keywords: splitCsv(fd.get('keywords')), relatedIds: splitCsv(fd.get('relatedIds')).map(Number).filter(Boolean), references: splitCsv(fd.get('references')), contributorName: fd.get('contributorName').trim(), contributorResearchDirection: fd.get('contributorDirection').trim(), media: { videoPath: fd.get('videoPath').trim(), thumbnailLabel: '', thumbnailHint: '', thumbnailStyle: 'linear-gradient(135deg,#2563eb 0%,#0891b2 100%)' } };
  const method = State.editingId ? 'PUT' : 'POST';
  const path = State.editingId ? `/terms/${State.editingId}` : '/terms';
  await api(path, { method, body: JSON.stringify(demoToPayload(item)) });
  await refreshData(); State.editingId = null; renderAdmin();
}
