const API_BASE = window.API_BASE || '/api';
const TOKEN_KEY = 'enertri_api_token_v1';
const USER_KEY = 'enertri_api_user_v1';

function getToken() { return localStorage.getItem(TOKEN_KEY); }
function getSavedUser() { try { return JSON.parse(localStorage.getItem(USER_KEY)); } catch { return null; } }
function saveAuth(token, user) {
  if (token) localStorage.setItem(TOKEN_KEY, token); else localStorage.removeItem(TOKEN_KEY);
  if (user) localStorage.setItem(USER_KEY, JSON.stringify(user)); else localStorage.removeItem(USER_KEY);
}
async function api(path, options = {}) {
  const headers = { ...(options.headers || {}) };
  if (!(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
  const token = getToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    if (res.status === 401) saveAuth(null,null);
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail)); error.status=res.status; throw error;
  }
  return res.status === 204 ? null : res.json();
}
async function apiDownload(path, fallbackName = 'download.bin') {
  const token = getToken();
  const headers = token ? { Authorization: `Bearer ${token}` } : {};
  const url = /^https?:\/\//i.test(path) || path.startsWith('/api/') ? path : `${API_BASE}${path}`;
  const res = await fetch(url, { headers });
  if (!res.ok) {
    let detail = await res.text();
    try { detail = JSON.parse(detail).detail || detail; } catch {}
    if (res.status === 401) saveAuth(null,null);
    const error = new Error(typeof detail === "string" ? detail : JSON.stringify(detail)); error.status=res.status; throw error;
  }
  const disposition = res.headers.get('Content-Disposition') || '';
  const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i);
  const asciiName = disposition.match(/filename=\"?([^\";]+)\"?/i);
  let filename = fallbackName;
  try {
    filename = decodeURIComponent(utf8Name?.[1] || asciiName?.[1] || fallbackName);
  } catch { filename = asciiName?.[1] || fallbackName; }
  const blob = await res.blob();
  const objectUrl = URL.createObjectURL(blob);
  const anchor = document.createElement('a');
  anchor.href = objectUrl;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(objectUrl);
}
async function loginApi(username, password) {
  const data = await api('/auth/login', { method: 'POST', body: JSON.stringify({ username, password }) });
  saveAuth(data.access_token, data.user);
  return data.user;
}
async function loadDbFromApi(status = 'all') {
  const articleStatus = status === 'all' ? 'all' : 'approved';
  const [categories, terms, articles] = await Promise.all([
    api('/categories'),
    api(`/terms?status=${encodeURIComponent(status)}`),
    api(`/articles?status=${articleStatus}`),
  ]);
  let progress = [];
  if (getToken()) {
    try { progress = await api('/me/progress'); } catch { progress = []; }
  }
  return { categories, terms, articles, progress };
}
async function updateTermProgress(termId, payload) {
  return api(`/me/progress/${termId}`, { method: 'POST', body: JSON.stringify(payload) });
}
async function loadTermQuiz(termId) {
  return api(`/terms/${termId}/quiz`);
}
async function submitTermQuiz(termId, quizToken, answers) {
  return api(`/terms/${termId}/quiz/submit`, { method: 'POST', body: JSON.stringify({ quiz_token: quizToken, answers }) });
}
async function importExcelApi(file) {
  const formData = new FormData();
  formData.append('file', file);
  return api('/import/excel', { method: 'POST', body: formData });
}
function termToDemo(t) {
  return {
    id: t.id,
    categoryId: String(t.category_id || ''),
    featured: !!t.featured,
    reviewStatus: t.review_status,
    reviewComment: t.review_comment || '',
    term: { zh: t.zh || '', en: t.en || '', ru: t.ru || '' },
    meaning: { zh: t.definition_zh_academic || '', popular: t.definition_zh_popular || '', en: t.definition_en || '', ru: '' },
    examples: { zh: t.application_scenario || '', en: '', ru: '' },
    formulaModel: t.formula_model || '',
    relatedIds: t.related_term_ids || [],
    references: t.references || [],
    keywords: t.keywords || [],
    contributorName: t.contributor_name || '',
    contributorResearchDirection: t.contributor_research_direction || '',
    media: {
      videoPath: t.video_path || '',
      videoPlanned: !!t.has_video,
      thumbnailLabel: t.thumbnail_label || (t.zh || '').slice(0, 2),
      thumbnailHint: t.thumbnail_hint || t.application_scenario || '术语示意',
      thumbnailStyle: t.thumbnail_style || 'linear-gradient(135deg,#2563eb 0%,#0891b2 100%)',
    },
    updatedAt: t.updated_at || new Date().toISOString(),
  };
}
function articleToDemo(a) {
  return {
    id: a.id,
    title: a.title || '',
    summary: a.summary || '',
    content: a.content || '',
    difficulty: a.difficulty || '入门',
    status: a.status || 'approved',
    coverLabel: a.cover_label || '科普',
    relatedKeywords: a.related_keywords || [],
    updatedAt: a.updated_at || new Date().toISOString(),
  };
}
function demoToPayload(item) {
  return {
    category_id: Number(item.categoryId) || null,
    zh: item.term.zh,
    en: item.term.en,
    ru: item.term.ru || null,
    definition_zh_academic: item.meaning.zh || '待补充',
    definition_zh_popular: item.meaning.popular || null,
    definition_en: item.meaning.en || null,
    application_scenario: item.examples.zh || null,
    formula_model: item.formulaModel || null,
    has_video: !!item.media.videoPath || !!item.media.videoPlanned,
    featured: !!item.featured,
    review_status: item.reviewStatus || 'draft',
    review_comment: item.reviewComment || null,
    contributor_name: item.contributorName || null,
    contributor_research_direction: item.contributorResearchDirection || null,
    keywords: item.keywords || [],
    related_term_ids: item.relatedIds || [],
    references: item.references || [],
    video_path: item.media.videoPath || null,
    thumbnail_label: item.media.thumbnailLabel || null,
    thumbnail_hint: item.media.thumbnailHint || null,
    thumbnail_style: item.media.thumbnailStyle || null,
  };
}
