# SlidePilot for PowerPoint

SlidePilot turns workspace files into editable PowerPoint slides. The assistant uses a source-built Chatbox CE desktop client and a local MCP server. Each classic chart in a generated deck has its own embedded Excel workbook.

## 在 PowerPoint 中使用

1. 完整解压 Windows x64 便携包到固定目录，关闭 PowerPoint 后运行 `Enable.cmd`。重新打开 PowerPoint，新建或打开一个演示文稿。
2. 在 **SlidePilot → 选择工作区** 选取资料文件夹。包内的 `examples/workspace` 提供一份季度简报和一张 CSV，可直接试用。
3. 点击 **AI 助手**。在 Chatbox 设置中配置模型及 API 密钥。预设使用千问 AI 平台 Token Plan 的 OpenAI 兼容端点和 `qwen3.8-flash`。密钥由用户在自己的电脑上配置。
4. 例如，输入“读完工作区内的简报和存款表，做三页季度回顾。按季度画出两类存款，图表可编辑，每页把来源写入备注。说明试点的下一步。”
5. 助手默认逐项请求写入批准。草稿保存在工作区的 `_SlidePilot/drafts`。如需加入当前文稿，可要求助手插入草稿。切换文稿或工作区会恢复逐次审批。直接修改当前文稿前会保存恢复副本。
6. 在图表上点击右键，选择 **编辑数据 → 在 Excel 中编辑数据**，即可修改内嵌工作表。Excel 需安装在本机。原始资料后续更新时可重新生成草稿。

`Status.cmd` 显示注册位置。移动安装目录前从原目录运行 `Disable.cmd`，移动后再启用。三个入口均使用随包的 .NET 管理器。部署无需管理员权限、PowerShell、Node 或另外安装 Python。设置位于 `%APPDATA%\SlidePilot`，恢复副本位于 `%LOCALAPPDATA%\SlidePilot\backups`。工作区草稿由用户保管。

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

The distribution targets 64-bit Windows 10 21H1 or later, with desktop PowerPoint 2010 or later and .NET Framework 4.8. The AnyCPU add-in registers per user in the applicable registry views, for 32- or 64-bit Office on x64 Windows. Chatbox invokes the bundled Python MCP server over stdio. The server communicates with the active PowerPoint process over a user-scoped Windows named pipe. Model calls use the configured provider endpoint.

SlidePilot has its own COM class, PowerPoint ribbon, profile, process binding and recovery directory. Local checks and their host coverage are described in `TESTING.md`.

## Build from source on Windows

Use 64-bit Python 3.12, Node and pnpm for the build, .NET Framework with its C# compiler, Office primary interop build references and the .NET Framework edition of Open XML SDK 2.8.1. The target machine uses the bundled runtimes.

```bat
python scripts\prepare_chatbox.py
python scripts\build_portable.py --openxml "C:\build-deps\DocumentFormat.OpenXml.dll"
```

The source ZIP includes the pinned Chatbox source. To build from it, pass `--archive vendor\chatbox-upstream.zip` to the first command. `build_portable.py --help` describes the optional offline dependency caches. Each build uses a fresh staging directory and produces a ZIP with its file-level SHA-256 manifest under `dist`.

## MCP entry points

Start with `capabilities`, `workspace_list` and `workspace_read`. Resolve source units, cite short exact quotes, call `deck_compose` once for the complete deck, and use `deck_inspect` to check the result. The `guide` tool documents the composition schema, host limits and editing examples. Numeric matrix values and native chart data remain editable in PowerPoint.
