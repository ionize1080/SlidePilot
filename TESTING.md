# Verifying SlidePilot

Generate the three-slide quarterly brief and the full chart matrix in a disposable test directory.

```bat
python tests\fixtures.py
python -m unittest discover -s tests -p "test_*.py" -v
SlidePilot.Validate.exe .build\qa\Harbour.pptx .build\qa\ChartMatrix.pptx
```

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
| Source and edit tests | Nine regression tests passed. They cover XLSX row selection and sparse columns, stale source detection, malformed citations, the formatting inventory, stdio, edits and copy preservation. A test changed Q4 retail from 142 to 155, cleared another point, renamed a series and checked the saved cache and cells. |
| Portable runtime | An extracted package read a three-page PDF, composed an image and a native table, and passed the Office 2010 validator on those slides and the 78-chart matrix. The packaged Python server completed the MCP workflow over stdio and a Windows named pipe with a test approval host. Duplicate or denied drafts left the staging directory empty. |
| Speed on this machine | Three-slide composition median 16.6 ms over 15 runs. The 78-slide matrix took 190.8 ms over five runs. Changing one worksheet cell and its chart cache took 7.1 ms over 12 runs. A separate schema validation of the three-slide package took 703.5 ms over five runs. These are local timings. |
| Qwen Token Plan | Both the direct probe and the real tool-calling benchmark timed out at the configured provider endpoint (Windows 10060). Model latency and end-to-end output quality are unmeasured. |
| Target environment | Desktop file checks used Office 16 on Windows 11. PowerPoint 2010 on Windows 10 21H1 has not been exercised. Writes to a disposable HKCU registry key were denied in the build environment. Packaged Electron 44.7.0 ran in Node mode, while its GUI startup, including the unmodified runtime's version probe, exited with 0x80000003 in that environment. |

To repeat the packaged MCP checks, run `node tests/portable_smoke.cjs "C:\SlidePilot"` from the source checkout. To exercise the real renderer, launch the bundled Electron with `tests/chatbox_smoke.cjs` and the extracted package path as arguments. `tests/deployment.cs` exercises registration twice in each direction against a volatile test hive on a Windows desktop.
