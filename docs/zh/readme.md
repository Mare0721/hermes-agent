# Vertex 稳定性更新总结（2026-04-15）

## 范围
本文档汇总了本轮 Vertex 稳定性修复中新增与修改的内容，以及已执行的标准发布流程。

## 目标
- 在首次 429 时立即轮换凭证。
- 避免全部凭证临时 exhausted 时导致运行时启动失败。
- 在会话级模型覆盖后继续保持 credential pool 生效。
- 确保日用运行环境与测试通过代码保持同步。

## 代码变更

### 1）首次 429 立即轮换
- 文件：run_agent.py
- 变更：
  - 在 _recover_with_credential_pool 中，首次 429 改为立即轮换。
  - 移除了“首次 429 仅重试当前凭证”的旧行为。
- 结果：
  - 限流场景下故障切换更快。

### 2）全 exhausted 场景运行时兜底
- 文件：agent/credential_pool.py
- 新增：
  - select_with_exhausted_fallback()
  - _select_exhausted_fallback_unlocked(...)
- 行为更新：
  - 当全部凭证处于 exhausted 冷却时，不再直接返回无 key，而是继续选择一个凭证用于应急。
  - 应急选择遵循配置策略（random、round_robin、least_used、fill_first）。
  - 轮换路径在有候选时会尽量避开当前刚 exhausted 的同一凭证。

### 3）运行时 Provider 解析防护
- 文件：hermes_cli/runtime_provider.py
- 变更：
  - 当 pool.select() 返回 None 时，运行时会尝试 exhausted fallback 选择。
- 结果：
  - 避免全部凭证冷却时出现 no API key found 启动报错。

### 4）会话覆盖仍保留凭证池路由
- 文件：gateway/run.py
- 新增：
  - _load_provider_credential_pool(provider) 辅助函数。
- 更新：
  - 会话覆盖状态现在会保存并传递 credential_pool。
  - fast-path 与后台路径在缺失时会补齐对应 provider 的 pool。
- 结果：
  - 会话模型覆盖后不再丢失轮换能力。

### 5）测试更新
- 涉及文件：
  - tests/run_agent/test_run_agent.py
  - tests/agent/test_credential_pool_routing.py
  - tests/hermes_cli/test_runtime_provider_resolution.py
  - tests/agent/test_credential_pool.py
  - tests/gateway/test_session_model_override_routing.py
- 覆盖内容：
  - 首次 429 立即轮换。
  - 运行时 exhausted fallback。
  - exhausted fallback 的策略一致性。
  - 会话覆盖路径的 credential-pool 补齐。
  - codex reset timestamp 场景用例稳定性修正。

## 日用运行环境已执行修复
- 同步缺失模块 agent/models/vertex_ai.py。
- 修复 /root/.hermes/auth.json 中 Vertex 占位 key（k1/k2），恢复为真实 key。
- 将测试通过版 run_agent.py 同步到日用仓。
- 同步后重启 gateway 服务。

## 已执行的标准发布流程
1. 在测试仓验证代码变更。
2. 运行针对性回归测试。
3. 提交并推送到远端分支。
4. 将测试通过的关键运行文件回灌到日用仓。
5. 重启 gateway 并确认服务在线。

## 验证结果
- 针对性回归测试：354 passed。
- key 修复后运行时检查：
  - Vertex 凭证池可解析到真实长度 key（非占位值）。
- 网关状态：
  - 最终重启后服务处于 active running。

## 本轮关键提交
- cf4b8b5e - fix(gateway): keep credential pool on session overrides
- ffae63c2 - docs: add vertex stability rollout summary readme

## 说明
- 根目录 README.md 未被修改。
- 英文总结位于 docs/readme.md。
- 中文版本位于 docs/zh/readme.md。
