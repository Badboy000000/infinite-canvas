"""任务 PR-5 · ProviderTaskView 映射层测试包。

fixture 位于 `fixtures/provider_samples/{provider}/{status}.json`；
标准化预期位于 `fixtures/provider_samples/{provider}/expected_normalized.json`。

7 Provider × 6 状态 = 42 fixture 对；对应 7 aggregation test + 独立
error / sentinel branch test。
"""
