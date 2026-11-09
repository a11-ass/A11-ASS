---
name: office-cli
description: 调用 officecli-win-x64.exe 读写 Office 文档
---
# office-cli 使用说明
---

本 Skill 可以调用 officecli-win-x64.exe 读写 .docx / .xlsx / .pptx 文档。

## 使用方法

1. 在 office-test/ 目录下找到 officecli-win-x64.exe。
2. 使用 RunCli 工具调用它，并传入相应的命令和参数。
3. 详细的命令参考请查看 office-test/OfficeCli操作说明.md。

## 示例

```python
# 读取 .docx 文档
readFile('path/to/document.docx')

# 写入 .xlsx 文档
writeFile('path/to/document.xlsx', '内容')

# 转换 .pptx 文档
convert('path/to/document.pptx', 'path/to/output.pptx')