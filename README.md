# SlidePilot for PowerPoint

SlidePilot turns workspace files into editable PowerPoint slides. The assistant uses a source-built Chatbox CE desktop client and a local MCP server. Each classic chart in a generated deck has its own embedded Excel workbook.

## 在 PowerPoint 中使用

1. 将完整便携包解压到固定目录，保存并关闭 PowerPoint。双击 `Enable.cmd` 或 `SlidePilot.Setup.exe` 打开安装器，选择“仅当前用户”或“整台电脑（管理员）”，点击启用。整机安装的目录须让所有使用者都能读取。已有用户注册时，可以选择备份并替换旧注册。
2. 在安装器中点击“启动并验证 PowerPoint”，然后打开一份演示文稿。安装器会等待该版本的功能区加载回执。SlidePilot 选项卡提供 **AI 助手** 和 **设置**。
3. 在 **AI 助手 → Chatbox 设置 → 模型提供商 → OpenAI** 中填写密钥。在原生连接设置中使用 `https://token-plan.maas.qianwenaiapi.com/compatible-mode/v1` 和 `qwen3.8-flash`。模型列表旁的连接测试可以检查供应商响应。
4. 在对话输入栏打开 **工作区**，加入包内示例目录 `examples/workspace`，或将自己的文件拖入浮层。独立文件、真实文件夹及虚拟文件夹可以混用。新聊天首次发送后保留本次添加的资料。移除资料引用会保留原文件。
5. 可以输入“读取工作区里的简报和存款表，做三页季度回顾。按季度画出两类存款的可编辑图表，把来源写入每页备注，并说明试点的下一步。”批准写入后，在工作区中找到生成的演示文稿。右键图表选择 **编辑数据 → 在 Excel 中编辑数据** 可修改内嵌工作簿。
6. 助手默认逐项请求写入批准。点击输入栏盾牌并完成两次确认，即可为当前演示文稿开启自动批准。红色盾牌表示已开启，再点一次恢复手动。切换演示文稿或重启 PowerPoint 后恢复手动。
7. Ribbon **设置** 管理插件外观与工作区偏好。部署、停用、切换版本和回滚由安装器管理。个人资料与会话位于 `%APPDATA%\SlidePilot`，文稿恢复副本位于 `%LOCALAPPDATA%\SlidePilot\backups`。保留旧版本目录，方便回滚。
8. 聊天窗口右上角、最小化按钮旁的 **收起为 PowerPoint 侧边栏** 会将当前对话停靠到演示文稿右侧。要恢复原窗口，点击同一位置的 **弹出为独立窗口**。两种显示方式共用当前会话和参考工作区。安装旧版后升级到本版时，请在新目录中打开安装器并启用，让 PowerPoint 注册侧栏控件。

## 图表与资料支持

| 项目 | 支持情况 |
| --- | --- |
| 经典图和组合图 | 草稿生成器提供 78 个类型入口，包含有序股票数据、独立 XY 坐标、气泡大小和双轴组合。通用组合入口按各系列类型和轴生成。 |
| 现代 Excel 图表 | 24 个扩展类型通过当前 PowerPoint 的原生接口尝试创建，再读回类型。适用性取决于 Office 版本、数据形状和具体构建。PowerPoint 2010 使用经典图。 |
| 样式和细粒度修改 | 可指定图例、轴范围与刻度、标签、配色、点、线、三维角度等。通过 `guide(formatting)` 查询原生属性和方法，或在草稿副本中按路径修改。 |
| 资料读取 | TXT、Markdown、CSV、TSV、XLSX、DOCX、PPTX 和带文本层的 PDF，可按行、段落、页或工作表定位。 |
| 图表绑定 | CSV、TSV、XLSX 均按列名取数。XLSX 可指定 `sheet`、`headerRow` 和 `lastRow`。公式使用已保存的计算结果。 |
| 编辑范围 | 新建多页演示、原生表格、PNG/JPEG 图片、演讲者备注。对当前文稿支持增删移动幻灯片、改文字、形状、表格单元格、几何位置和图表。 |

## Compatibility and transport

The distribution targets 64-bit Windows 10 21H1 or later, with desktop PowerPoint 2010 or later and .NET Framework 4.8. The AnyCPU add-in supports current-user and machine registration in the applicable registry views, for 32- or 64-bit Office on x64 Windows. Chatbox invokes the bundled Python MCP server over stdio. The server communicates with the active PowerPoint process over a user-scoped Windows named pipe. Model calls use the configured provider endpoint.

SlidePilot has its own COM class, PowerPoint ribbon, profile, process binding and recovery directory. Local checks and their host coverage are described in `TESTING.md`.

## Build from source on Windows

Use 64-bit Python 3.12, Node and pnpm for the build, .NET Framework with its C# compiler, Office primary interop build references and the .NET Framework edition of Open XML SDK 2.8.1. The target machine uses the bundled runtimes.

```bat
python scripts\prepare_chatbox.py
python scripts\build_portable.py --openxml "C:\build-deps\DocumentFormat.OpenXml.dll"
```

The source ZIP includes the pinned Chatbox source. To build from it, pass `--archive vendor\chatbox-upstream.zip` to the first command. `build_portable.py --help` describes the optional offline dependency caches. Each build uses a fresh staging directory and produces a ZIP with its file-level SHA-256 manifest under `dist`.

## MCP entry points

Use the conversation workspace ID attached to the latest user message to discover and read references. Use `capabilities` to check the PowerPoint host. Resolve source units, cite short exact quotes, call `deck_compose` once for the complete deck, and use `deck_inspect` to check the result. The `guide` tool documents the composition schema, host limits and editing examples. Numeric matrix values and native chart data remain editable in PowerPoint.
