# Verifying SlidePilot

Generate the three-slide quarterly brief and the full chart matrix in a disposable test directory.

```bat
python tests\fixtures.py
python -m unittest discover -s tests -p "test_*.py" -v
SlidePilot.Validate.exe .build\qa\Harbour.pptx .build\qa\ChartMatrix.pptx
tests\native_regression.cmd
node tests\bootstrap_regression.cjs
```

The native regression runner compiles small fake-object chart tests with the developer machine's .NET Framework compiler; Office and PowerShell are not required. The Node bootstrap tests simulate named-pipe responses, busy retries, disconnection and timeout without opening Electron or modifying user settings. Neither compiler nor Node is required on the target machine.

The validator checks both the presentation parts and embedded XLSX workbooks against the Office 2010 file format. The workspace tests additionally check the relationship between a chart's formulas, cached points and worksheet cells. The Office desktop test opens a generated presentation and selects **Edit Data in Excel** on the chart. A separate theme for the notes master is necessary for PowerPoint to open the sample without a repair prompt.

For a provider benchmark, run the following from the source directory. Use the validator executable from the extracted portable package.

```bat
python tests\qwen_live.py --key-file "C:\private\provider-key.txt" --validator "C:\SlidePilot\SlidePilot.Validate.exe"
```

The benchmark gives the real model an isolated copy of the sample workspace. It records tool calls, model time and composition time, checks the two numerical series and validates the slides and citations. A fixture substitutes for the interactive PowerPoint approval dialog. A connectivity probe alone does not measure deck generation.

## Results on 24 November 2026

| Check | Result |
| --- | --- |
| Native desktop chart | The initial sample prompted for repair in PowerPoint. Giving the notes master its own theme let the regenerated three-slide sample open normally, with its notes and clustered columns. **Edit Data in Excel** opened the embedded workbook. The interactive edit/save step in Excel is still unverified. |
| Chart data | All 78 classic/combination fixtures had a distinct embedded workbook. Every chart formula, cached point and series header matched its referenced worksheet cell. The 24 newer types are runtime probes. |
| Source and edit tests | The Python regression suite passed. They cover XLSX row selection and sparse columns, stale source detection, malformed citations, the formatting inventory, stdio, edits and copy preservation. A test changed Q4 retail from 142 to 155, cleared another point, renamed a series and checked the saved cache and cells. |
| Portable runtime | An extracted package read a three-page PDF, composed an image and a native table, and passed the Office 2010 validator on those slides and the 78-chart matrix. The packaged Python server completed the MCP workflow over stdio and a Windows named pipe with a test approval host. Duplicate or denied drafts left the staging directory empty. |
| Speed on this machine | Three-slide composition median 16.6 ms over 15 runs. The 78-slide matrix took 190.8 ms over five runs. Changing one worksheet cell and its chart cache took 7.1 ms over 12 runs. A separate schema validation of the three-slide package took 703.5 ms over five runs. These are local timings. |
| Qwen Token Plan | Both the direct probe and the real tool-calling benchmark timed out at the configured provider endpoint (Windows 10060). Model latency and end-to-end output quality are unmeasured. |
| Target environment | Desktop file checks used Office 16 on Windows 11. PowerPoint 2010 on Windows 10 21H1 has not been exercised. Writes to a disposable HKCU registry key were denied in the build environment. Packaged Electron 44.7.0 ran in Node mode, while its GUI startup, including the unmodified runtime's version probe, exited with 0x80000003 in that environment. |

To repeat the packaged MCP checks, run `node tests/portable_smoke.cjs "C:\SlidePilot"` from the source checkout. To exercise the real renderer, launch the bundled Electron with `tests/chatbox_smoke.cjs` and the extracted package path as arguments. `tests/deployment.cs` exercises registration twice in each direction against a volatile test hive on a Windows desktop.

## RC2 local verification

PowerPoint 16 on the Windows desktop opened Harbour.pptx and returned the add-in Ribbon callback. Its SlidePilot tab showed AI 助手 and 设置. Selecting 设置 opened the dedicated Electron product preferences with the workspace, appearance and maintenance pages. The host recorded the PowerPoint process start time and add-in directory so Setup can distinguish registration from an actual Ribbon load.

The reference-workspace test used the two sample files to create a three-slide presentation through the same compose and validation path, with a test approval callback. Both embedded series matched all four quarters, the notes retained source citations, and the Office 2010 schema validator reported zero errors. These are local composition results. The live Qwen attempt on 24 November 2026 used the supplied OpenAI-compatible endpoint and qwen3.8-flash. Its first request timed out at 10 seconds on the execution environment's configured proxy, before any tool call or generated slide. Native model response time and provider-generated slide quality remain unverified.

From the extracted package, run:
```bat
Test-Qwen.cmd "C:\private\provider-key.txt"
```
This uses the bundled Python, sends the included example only, and writes latest-result.json and a per-run directory under %LOCALAPPDATA%\SlidePilot\benchmarks. The report checks the legacy host-tool workflow with a fixture approval host. It does not exercise the interactive chat window or grant automatic approval.

## RC3 window modes

On Windows 11 with PowerPoint 16, the portable installer upgraded the current user's registration from the previous directory. Both registry views pointed to the RC3 add-in. The reopened presentation showed the two SlidePilot commands. The all-users option was visible in Setup; this run used the current-user option.

With Harbour.pptx open, the assistant's title-bar button docked its existing window in a real PowerPoint task pane. The reverse trip through **Settings → AI assistant → Detached window** restored the original desktop window handle. The unsent draft, one reference to `brief.md`, and the selected `qwen3.8-flash` model remained present on both sides of the transition. The title-bar control displayed the matching pop-out action while docked. Automated tests exercise both directions of the title-bar control, concurrent requests, rejected switches, and late replies.

After closing the presentation and restarting PowerPoint, opening **AI assistant** restored sidebar mode. The test draft and workspace reference were still present. On the first desktop pass, a 1069-pixel-wide PowerPoint window opened a roughly 240-pixel pane. A second pass reproduced an empty geometry report during the synchronous first show. In the compact renderer the workspace button and model selector remained visible below the draft even when the pane was only about 180 pixels wide.

The final build waited for two nonzero layout observations from the task pane itself. On the same desktop at 192 DPI (200% scaling), the PowerPoint client measured 2134 physical pixels across. After Office applied the requested width, the add-in read back a pane client width of 960 physical pixels (480 logical pixels). The sidebar screenshot showed the draft, workspace count, approval shield, settings and selected model together. The task pane is sized once so users can resize it afterwards.

In the final desktop test the user clicked the sidebar's own pop-out arrow. We observed the detached Chatbox window with the original unsent text, one reference source, the selected model and manual approval mode. Its title bar again offered the action to dock in PowerPoint.
