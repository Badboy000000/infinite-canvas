"""API 层包骨架。

后续 `app.api.routers.*` 将承接根 `main.py` 中 162 个 `@app.*` 装饰器；
`app.api.dto.legacy` 冻结现有 Pydantic 模型，`app.api.dto.internal` 定
义命令 / 内部响应对象。PR-BE-01 只建立目录树，不做任何抽取。
"""
