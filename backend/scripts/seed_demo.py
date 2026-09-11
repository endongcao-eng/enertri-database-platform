"""初始化分类、演示账号和两个示例术语。"""
from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import select

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.database import SessionLocal  # noqa: E402
from app.models import Category, Term  # noqa: E402
from app.migration_bootstrap import upgrade_database  # noqa: E402
from app.schemas import TermCreate  # noqa: E402
from app.security import hash_password  # noqa: E402
from app.utils import apply_term_payload, seed_defaults  # noqa: E402

upgrade_database("head")
with SessionLocal() as db:
    seed_defaults(db, hash_password)
    pv = db.scalar(select(Category).where(Category.code == "PV"))
    examples = [
        TermCreate(
            category_id=pv.id,
            zh="光伏组件",
            en="photovoltaic module",
            ru="фотоэлектрический модуль",
            definition_zh_academic="由多个太阳能电池片经串并联和封装形成的光伏发电单元。",
            definition_zh_popular="可以把阳光转换成电能的一块板，是光伏电站最常见的核心设备。",
            definition_en="A packaged PV unit composed of multiple solar cells that converts sunlight into electricity.",
            application_scenario="户用屋顶光伏、工商业屋顶光伏和集中式光伏电站。",
            keywords=["光伏", "组件", "太阳能电池"],
            references=["IEC 61215: Terrestrial photovoltaic modules - Design qualification and type approval."],
            video_path="videos/光伏组件.mp4",
            thumbnail_label="组件",
            thumbnail_hint="组件结构与封装示意",
            featured=True,
            review_status="approved",
        ),
        TermCreate(
            category_id=pv.id,
            zh="逆变器",
            en="inverter",
            ru="инвертор",
            definition_zh_academic="将直流电转换为交流电的电力电子变换装置。",
            definition_zh_popular="光伏板发出的电是直流电，逆变器负责把它变成家庭和电网可用的交流电。",
            definition_en="A power electronic device that converts direct current into alternating current.",
            application_scenario="光伏并网、储能系统、电机驱动和不间断电源。",
            keywords=["逆变", "电力电子", "并网"],
            references=["IEEE Std 1547: Standard for Interconnection and Interoperability of Distributed Energy Resources."],
            video_path="videos/逆变器.mp4",
            thumbnail_label="INV",
            thumbnail_hint="直流到交流的变换",
            featured=True,
            review_status="approved",
        ),
    ]
    for payload in examples:
        exists = db.scalar(select(Term).where(Term.zh == payload.zh, Term.en == payload.en))
        if not exists:
            db.add(apply_term_payload(db, Term(), payload))
    db.commit()
print("seeded")
