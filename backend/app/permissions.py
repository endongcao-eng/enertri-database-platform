from __future__ import annotations

# V4.2: permissions are deliberately action-specific. View access never implies manage/download access.
ROLE_PERMISSIONS: dict[str, set[str]] = {
    "learning_user": {
        "paper.upload", "task.own.view", "task.own.retry", "task.own.cancel",
        "file.own.view", "file.own.download", "file.own.delete", "knowledge.own.manage",
        "template.view", "template.download",
    },
    "researcher": {
        "paper.upload", "ai.external", "task.own.view", "task.own.retry", "task.own.cancel",
        "file.own.view", "file.own.download", "file.own.delete", "data.export", "knowledge.own.manage",
        "template.view", "template.download", "template.manage",
    },
    "production_engineer": {
        "paper.upload", "ai.external", "simulation.commercial", "task.own.view", "task.own.retry", "task.own.cancel",
        "file.own.view", "file.own.download", "file.own.delete", "data.export", "knowledge.own.manage",
        "template.view", "template.download",
    },
    "review_expert": {
        "paper.upload", "ai.external", "task.own.view", "task.other.view", "task.own.retry", "task.own.cancel",
        "file.own.view", "file.other.view", "file.own.download", "file.own.delete", "data.export",
        "process.approve", "knowledge.own.manage", "knowledge.shared.search",
        "template.view", "template.download",
    },
    "admin": {
        "paper.upload", "ai.external", "simulation.commercial",
        "task.own.view", "task.other.view", "task.own.retry", "task.own.cancel", "task.other.manage",
        "file.own.view", "file.other.view", "file.own.download", "file.other.download", "file.own.delete", "file.other.manage",
        "data.export", "user.role.manage", "rules.maintain", "process.approve", "audit.view",
        "knowledge.own.manage", "knowledge.shared.search", "knowledge.enterprise.manage",
        "template.view", "template.download", "template.manage",
    },
    "system_admin": {"*"},
}

ROLE_LABELS = {
    "learning_user": "普通学习用户",
    "researcher": "科研用户",
    "production_engineer": "生产工程师",
    "review_expert": "审核专家",
    "admin": "管理员",
    "system_admin": "系统管理员",
}


def has_permission(role: str, permission: str) -> bool:
    granted = ROLE_PERMISSIONS.get(role, set())
    return "*" in granted or permission in granted
