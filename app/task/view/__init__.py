"""`app.task.view` — 任务视图映射层（任务 PR-5）。

暴露 `ProviderTaskView` dataclass 与 7 个 Provider map 函数，把
异构 Provider 响应折成统一 view。字段严格对齐：

- [[30 治理方案/任务模型与后台任务治理方案]] §"目标对象 · ProviderTask"
- [[30 治理方案/Provider 适配体系治理方案]] §"ProviderTaskRequest /
  ProviderTaskHandle / ProviderTaskView"

**本 PR 只提供映射函数，不接入调用点**（前端读端点响应 shape 保持不变）。
error 字段允许暂缺 `TaskErrorCategory` 枚举，任务 PR-6 承接 category 抽取。
"""

from app.task.view.error_category import ErrorCategoryMapper, TaskErrorCategory
from app.task.view.provider_view import (
    KNOWN_VIEW_STATUSES,
    ProviderTaskView,
    ViewError,
    map_apimart_task,
    map_chat_task,
    map_comfy_task,
    map_generic_image_task,
    map_jimeng_task,
    map_runninghub_task,
    map_video_task,
    sanitize_raw_excerpt,
)

__all__ = [
    "ProviderTaskView",
    "ViewError",
    "KNOWN_VIEW_STATUSES",
    "TaskErrorCategory",
    "ErrorCategoryMapper",
    "sanitize_raw_excerpt",
    "map_runninghub_task",
    "map_apimart_task",
    "map_generic_image_task",
    "map_video_task",
    "map_jimeng_task",
    "map_comfy_task",
    "map_chat_task",
]
