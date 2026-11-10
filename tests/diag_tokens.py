"""诊断为什么上下文一直显示 1k。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))
os.chdir(r"D:\学校用的\大模型\trae 项目\xiangmu\Agent\prist")

from main import build_agent
agent = build_agent()

# 模拟几轮对话看看 token 怎么涨
from prist.core.domain.models import ChatMessage

print(f"初始状态:")
print(f"  消息数: {len(agent.messages)}")
print(f"  total_tokens: {agent.current_tokens()}")
print(f"  显示: {agent.current_tokens() // 1024}k\n")

# 看看每条消息的贡献
total = 0
for i, m in enumerate(agent.messages):
    from prist.core.application.context_manager import estimate_tokens
    c_tokens = estimate_tokens(m.content or "")
    overhead = 50
    total += c_tokens + overhead
    preview = (m.content or "")[:60].replace("\n", " ")
    print(f"  [{i}] role={m.role:9s} content_tokens={c_tokens:5d} +{overhead}  '{preview}'")
print(f"  → 合计: {total} tokens = {total/1024:.1f}k  (显示 {total // 1024}k)")
print()

# 加一轮对话看看涨多少
print("加一轮 user + assistant 后:")
agent._messages.append(ChatMessage(role="user", content="帮我生成一个 officecli 的 SKILL"))
agent._messages.append(ChatMessage(role="assistant", content="好的，我来帮你生成。首先...（很长的回复）..."))
new_total = agent.current_tokens()
print(f"  新 total: {new_total} tokens = {new_total/1024:.1f}k  (显示 {new_total // 1024}k)")
print()

# 加 5 轮
for i in range(5):
    agent._messages.append(ChatMessage(role="user", content=f"第{i}轮问题：你好{'啊' * 20}"))
    agent._messages.append(ChatMessage(role="assistant", content=f"第{i}轮回复：好的，这是答案{'测试' * 30}"))

print(f"加 5 轮后: {agent.current_tokens()} tokens = {agent.current_tokens()/1024:.1f}k  (显示 {agent.current_tokens() // 1024}k)")
