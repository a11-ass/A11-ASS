"""端到端测试：/compact → 归档 → recallContext 能搜到。"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from main import build_agent

agent = build_agent()
print(f"✅ 启动成功，工具 {len(agent._tools.names)} 个\n")

# Step 1: 先跟 agent 聊几句，让上下文有东西
print("=" * 50)
print("Step 1: 模拟 3 轮对话")
print("=" * 50)

turns = [
    "你好，我想做一个 PPT，主题是 AI 和教育的关系。",
    "帮我在当前目录创建一个叫 ai-edu.pptx 的文件，内容要有标题页和目录页。",
    "再帮我生成一份 Word 文档叫 plan.docx，内容是这个项目的计划。",
]

for t in turns:
    print(f"\n用户: {t}")
    events = list(agent.run_turn(t))
    for e in events:
        etype = type(e).__name__
        if etype == "TurnStarted":
            continue
        elif etype == "TurnCompleted":
            print(f"  → AI 回复长度: {len(e.text)} 字符")
        elif etype == "ToolStarted":
            print(f"  🔧 调工具: {e.name}")
        elif etype == "ToolFinished":
            print(f"     {'✓' if e.ok else '✗'} {e.name}")
        elif etype == "TurnFailed":
            print(f"  💥 失败: {e.message}")

print(f"\n当前 token 估算: {agent.current_tokens()}")
print(f"当前消息数: {len(agent.messages)}")

# Step 2: 触发 /compact
print("\n" + "=" * 50)
print("Step 2: 执行 /compact")
print("=" * 50)

compact_events = list(agent.run_turn("/compact"))
for e in compact_events:
    print(f"  {type(e).__name__}: {e}")

print(f"\n压缩后 token 估算: {agent.current_tokens()}")
print(f"压缩后消息数: {len(agent.messages)}")

# Step 3: 验证归档文件存在
print("\n" + "=" * 50)
print("Step 3: 验证归档 + recallContext")
print("=" * 50)

from pathlib import Path
archive_dir = Path(r"D:\学校用的\大模型\trae 项目\xiangmu\Agent\prist\.agents\context")
files = sorted(archive_dir.glob("*.jsonl"))
print(f"归档文件: {[f.stem for f in files]}")

# 用 recallContext 搜 "PPT"
r = agent._tools.invoke("recallContext", {"text": "PPT"})
print(f"\nrecallContext 搜 'PPT':\n{r.output[:500]}")

# 搜 "docx"
r2 = agent._tools.invoke("recallContext", {"text": "docx"})
print(f"\nrecallContext 搜 'docx':\n{r2.output[:500]}")

# 结束
print("\n" + "=" * 50)
print("全部测试完成！")
print("=" * 50)
