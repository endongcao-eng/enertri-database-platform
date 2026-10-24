from __future__ import annotations

import re
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Article, Category, Contributor, Keyword, MediaAsset, Term, TermReference, TermRelation, UserTermProgress
from .schemas import ArticleOut, ProgressOut, TermCreate, TermOut




VIDEO_PLACEHOLDER_VALUES = {"待上传", "待补充", "暂无", "无", "none", "null", "n/a"}


def normalize_video_path(value: object) -> str | None:
    text = str(value or "").strip()
    if not text or text.casefold() in {item.casefold() for item in VIDEO_PLACEHOLDER_VALUES}:
        return None
    return text


def normalize_term_name(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def build_term_name_lookup(terms: Iterable[Term]) -> dict[str, list[Term]]:
    lookup: dict[str, list[Term]] = {}
    for term in terms:
        for raw_name in (term.zh, term.en, term.ru):
            key = normalize_term_name(raw_name)
            if key:
                lookup.setdefault(key, []).append(term)
        lookup.setdefault(str(term.id), []).append(term)
    return lookup


def resolve_related_term_name(raw_name: str, lookup: dict[str, list[Term]]) -> tuple[Term | None, str | None]:
    raw_name = str(raw_name or "").strip()
    candidates = [raw_name, *re.split(r"\s*[/|]\s*", raw_name)]
    matches: dict[int, Term] = {}
    for candidate in candidates:
        key = normalize_term_name(candidate)
        for term in lookup.get(key, []):
            matches[term.id] = term
    if len(matches) == 1:
        return next(iter(matches.values())), None
    if len(matches) > 1:
        return None, f"相关术语“{raw_name}”匹配到多个词条"
    return None, f"未找到相关术语“{raw_name}”"


def apply_related_term_names(
    source_term: Term,
    related_names: Iterable[str],
    lookup: dict[str, list[Term]],
) -> list[str]:
    warnings: list[str] = []
    source_term.outgoing_relations.clear()
    seen_ids: set[int] = set()
    for raw_name in related_names:
        target, warning = resolve_related_term_name(raw_name, lookup)
        if warning:
            warnings.append(warning)
            continue
        if not target or target.id == source_term.id or target.id in seen_ids:
            continue
        source_term.outgoing_relations.append(TermRelation(related_term_id=target.id, relation_type="related"))
        seen_ids.add(target.id)
    return warnings


def split_list(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value).replace("；", ",").replace(";", ",").replace("，", ",").replace("、", ",")
    return [x.strip() for x in text.split(",") if x.strip()]


def split_refs(value: object) -> list[str]:
    if value is None:
        return []
    text = str(value).replace("；", "\n").replace(";", "\n")
    parts = [x.strip() for x in re.split(r"\n+|(?<=\.)\s+(?=\[?\d|[A-Z][a-z]+,)", text) if x.strip()]
    return parts or [str(value).strip()]



def join_keywords(words: Iterable[str]) -> str | None:
    values = [str(w).strip() for w in words if str(w).strip()]
    return ",".join(values) if values else None


def article_to_out(article: Article) -> ArticleOut:
    return ArticleOut(
        id=article.id,
        title=article.title,
        summary=article.summary,
        content=article.content,
        difficulty=article.difficulty,
        status=article.status,
        cover_label=article.cover_label,
        related_keywords=split_list(article.related_keywords),
        created_at=article.created_at,
        updated_at=article.updated_at,
    )


def progress_to_out(progress: UserTermProgress) -> ProgressOut:
    return ProgressOut(
        term_id=progress.term_id,
        is_favorite=progress.is_favorite,
        learned_at=progress.learned_at,
        quiz_best_score=progress.quiz_best_score,
        note=progress.note,
        last_viewed_at=progress.last_viewed_at,
    )

def bool_video(value: object) -> bool:
    return str(value or "").strip().lower() in {"有", "yes", "true", "1", "y"}


def get_or_create_keyword(db: Session, word: str) -> Keyword:
    word = word.strip()
    item = db.scalar(select(Keyword).where(Keyword.keyword == word))
    if item:
        return item
    item = Keyword(keyword=word)
    db.add(item)
    db.flush()
    return item


def get_or_create_contributor(db: Session, name: str | None, research_direction: str | None) -> Contributor | None:
    if not name:
        return None
    name = name.strip()
    research_direction = (research_direction or "").strip() or None
    item = db.scalar(select(Contributor).where(Contributor.name == name, Contributor.research_direction == research_direction))
    if item:
        return item
    item = Contributor(name=name, research_direction=research_direction)
    db.add(item)
    db.flush()
    return item


def apply_term_payload(db: Session, term: Term, payload: TermCreate, user_id: int | None = None) -> Term:
    contributor = get_or_create_contributor(db, payload.contributor_name, payload.contributor_research_direction)
    for field in [
        "category_id", "zh", "en", "ru", "definition_zh_academic", "definition_zh_popular",
        "definition_en", "application_scenario", "formula_model", "has_video", "featured",
        "review_status", "review_comment"
    ]:
        setattr(term, field, getattr(payload, field))
    if contributor:
        term.contributor_id = contributor.id
    if user_id:
        if not term.created_by:
            term.created_by = user_id
        term.updated_by = user_id

    term.keywords.clear()
    for word in payload.keywords:
        if word.strip():
            term.keywords.append(get_or_create_keyword(db, word))

    term.references.clear()
    for i, citation in enumerate(payload.references):
        if citation.strip():
            term.references.append(TermReference(citation=citation.strip(), sort_order=i))

    term.media_assets.clear()
    video_path = normalize_video_path(payload.video_path)
    if video_path:
        term.media_assets.append(MediaAsset(
            path=video_path,
            media_type="video",
            thumbnail_label=payload.thumbnail_label,
            thumbnail_hint=payload.thumbnail_hint,
            thumbnail_style=payload.thumbnail_style,
        ))
        term.has_video = True
    else:
        term.has_video = bool(payload.has_video)

    term.outgoing_relations.clear()
    for related_id in payload.related_term_ids:
        if related_id and related_id != term.id:
            term.outgoing_relations.append(TermRelation(related_term_id=related_id, relation_type="related"))
    return term


def term_to_out(term: Term) -> TermOut:
    media = next((item for item in term.media_assets if normalize_video_path(item.path)), None)
    return TermOut(
        id=term.id,
        category_id=term.category_id,
        category=term.category,
        zh=term.zh,
        en=term.en,
        ru=term.ru,
        definition_zh_academic=term.definition_zh_academic,
        definition_zh_popular=term.definition_zh_popular,
        definition_en=term.definition_en,
        application_scenario=term.application_scenario,
        formula_model=term.formula_model,
        has_video=bool(term.has_video or media),
        featured=term.featured,
        review_status=term.review_status,
        review_comment=term.review_comment,
        contributor_id=term.contributor_id,
        contributor_name=term.contributor.name if term.contributor else None,
        contributor_research_direction=term.contributor.research_direction if term.contributor else None,
        keywords=[k.keyword for k in term.keywords],
        related_term_ids=[r.related_term_id for r in term.outgoing_relations],
        references=[r.citation for r in sorted(term.references, key=lambda x: x.sort_order)],
        video_path=normalize_video_path(media.path) if media else None,
        thumbnail_label=media.thumbnail_label if media else None,
        thumbnail_hint=media.thumbnail_hint if media else None,
        thumbnail_style=media.thumbnail_style if media else None,
        created_at=term.created_at,
        updated_at=term.updated_at,
    )


def seed_defaults(db: Session, hash_password_func) -> None:
    if not db.scalar(select(Category).where(Category.code == "PV")):
        db.add_all([
            Category(code="PV", name_zh="光伏", name_en="Photovoltaics", name_ru="Фотовольтаика", description_zh="光伏设备、材料、参数和系统术语。", sort_order=10),
            Category(code="CN", name_zh="碳中和", name_en="Carbon Neutrality", name_ru="Углеродная нейтральность", description_zh="碳中和政策、管理与工程应用术语。", sort_order=20),
            Category(code="GRID", name_zh="电力系统", name_en="Power System", name_ru="Энергосистема", description_zh="电网、储能、调度与并网术语。", sort_order=30),
        ])
    from .models import User
    if not db.scalar(select(User).where(User.username == "admin")):
        db.add(User(username="admin", password_hash=hash_password_func("admin123"), role="admin", display_name="术语管理员"))
    if not db.scalar(select(User).where(User.username == "student")):
        db.add(User(username="student", password_hash=hash_password_func("123456"), role="learning_user", display_name="演示学生"))
    demo_articles = [
        Article(
            title="为什么光伏板能把阳光变成电？",
            summary="用大众语言解释光伏效应、组件、逆变器和并网发电的基本链路。",
            content="太阳光照射到太阳能电池片时，半导体材料会产生电荷分离，形成直流电。多个电池片封装成光伏组件后，输出的直流电通常要经过逆变器转换成交流电，再供家庭、工商业或电网使用。理解这条路径，可以把光伏系统看成‘收集阳光—产生直流电—转换交流电—接入用电场景’的过程。",
            difficulty="入门",
            status="approved",
            cover_label="PV",
            related_keywords="光伏,光伏组件,逆变器,并网",
        ),
        Article(
            title="碳中和离普通人有多远？",
            summary="从能源消费、建筑用能、交通出行和电力结构解释碳中和的生活关联。",
            content="碳中和不是只属于大型企业和政策文件的词。家庭用电、建筑供暖、交通出行和产品消费都会影响碳排放。对普通人来说，理解能效、可再生能源、储能和电力系统，有助于判断哪些技术真正能降低排放，哪些只是概念宣传。",
            difficulty="入门",
            status="approved",
            cover_label="CO₂",
            related_keywords="碳中和,能效,可再生能源,储能",
        ),
    ]
    for article in demo_articles:
        if not db.scalar(select(Article).where(Article.title == article.title)):
            db.add(article)
    db.commit()
